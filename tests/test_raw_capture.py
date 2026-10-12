"""Constructed payloads only; no private route, session or raw-log fixtures."""
import base64
import json
import time
import zipfile
import hashlib
import pytest
from mokka_ecu_lab.adapter import AcquisitionWorker
from mokka_ecu_lab.capture import capture_plan
from mokka_ecu_lab.layouts import layout_evidence
from mokka_ecu_lab.protocols.isotp import parse_reply
from mokka_ecu_lab.transport.simulator import Simulator,ALTERNATIVE_PAYLOADS,can_reply,DIESEL_PAYLOADS
from mokka_ecu_lab.logging import list_sessions
from mokka_ecu_lab.logging.bundle import export_research_bundle
from test_capture import evidence
from test_discovery import fast_clock
from test_negative_responses import wait_event,shutdown


def raw_evidence():
    support,pages,samples=evidence()
    for pid,payload in ALTERNATIVE_PAYLOADS.items():
        samples['7E8',pid]=dict(framing_valid=True,payload_hex=payload.hex(' '),fields=[],error='unverified layout',
                               **layout_evidence(pid,payload))
    return support,pages,samples


def test_raw_opt_in_requires_completed_discovery_own_support_and_complete_frame():
    support,pages,samples=raw_evidence()
    assert not capture_plan(support,pages,samples,'7E8',selected=[],raw_selected=[0x7A,0x88])['weights']
    numeric=capture_plan(support,pages,samples,'7E8',prepared=True)
    assert 0x7A not in numeric['weights']
    plan=capture_plan(support,pages,samples,'7E8',prepared=True,selected=[0x83],raw_selected=[0x7A,0x88])
    assert plan['weights']=={0x83:1,0x7A:1,0x88:1} and plan['raw_pids']==[0x7A,0x88]
    assert not capture_plan(support,pages,samples,'7E9',prepared=True,selected=[],raw_selected=[0x7A])['weights']
    support['7E9']={0x7A}; pages['7E9']=set(pages['7E8'])
    assert not capture_plan(support,pages,samples,'7E9',prepared=True,selected=[],raw_selected=[0x7A])['weights']
    samples['7E8',0x7A]['framing_valid']=False
    assert not capture_plan(support,pages,samples,'7E8',prepared=True,selected=[],raw_selected=[0x7A])['weights']
    assert not capture_plan(support,pages,samples,'7E8',prepared=True,selected=[],raw_selected=[0x83,0x60,0x22])['weights']
    pages['7E8'].remove(128)
    support['7E8'].remove(0x88)
    assert not capture_plan(support,pages,samples,'7E8',prepared=True,selected=[],raw_selected=[0x88])['weights']


@pytest.mark.parametrize('pid,length',[(0x7A,6),(0x88,13)])
def test_alternative_iso_tp_shapes_never_produce_numeric_values(tmp_path,monkeypatch,pid,length):
    monkeypatch.setattr(AcquisitionWorker,'start',lambda self:None)
    w=AcquisitionWorker(tmp_path); w.support,w.support_pages,_=raw_evidence()
    raw=(can_reply('7E8',pid,ALTERNATIVE_PAYLOADS[pid])+'\r>').encode()
    result=parse_reply(raw,pid,f'01{pid:02X}')
    assert not result.errors and len(result.responses[0].data)==length
    sample=w.diesel_sample(result.responses[0],pid,'2020-01-01T00:00:00+00:00',10)
    assert sample['fields']==[] and sample['error'] and sample['framing_valid']
    assert sample['isotp_payload_length']==length+2 and sample['alternative_format_source'] is None
    opted=w.diesel_sample(result.responses[0],pid,'2020-01-01T00:00:00+00:00',10,raw_only=True)
    assert opted['fields']==[] and opted['raw_only'] and 'error' not in opted
    # Padding is excluded from the reconstructed payload; a missing CF cannot qualify.
    truncated=(raw.decode().split('\r')[0]+'\r>').encode()
    assert parse_reply(truncated,pid).errors and not parse_reply(truncated,pid).responses


def test_documented_layout_still_decodes_but_explicit_raw_choice_disables_numbers(tmp_path,monkeypatch):
    monkeypatch.setattr(AcquisitionWorker,'start',lambda self:None)
    w=AcquisitionWorker(tmp_path); w.support,w.support_pages,_=evidence()
    from mokka_ecu_lab.protocols import Response
    reply=Response('7E8',DIESEL_PAYLOADS[0x7A])
    assert w.diesel_sample(reply,0x7A,'synthetic',1)['fields'][0]['value']==2.5
    assert w.diesel_sample(reply,0x7A,'synthetic',1,raw_only=True)['fields']==[]
    other=w.diesel_sample(Response('7E9',reply.data),0x7A,'synthetic',1,raw_only=True)
    assert not other.get('raw_only') and other['fields']==[]


def test_raw_monitoring_and_nox_keep_session_bundle_and_replay_separation(tmp_path,fast_clock):
    w=AcquisitionWorker(tmp_path)
    try:
        w.submit('connect',simulation=True,port='COM4',scenario='Diesel alternative layouts')
        wait_event(w,'connection',lambda s:s['ecu']=='Connected')
        w.submit('record'); session_id=wait_event(w,'recording',bool)
        w.submit('discover',ecu='7E8'); wait_event(w,'discovery',lambda s:'Discovery ended' in s['reason'])
        assert w.discovery_prepared and not w.transport.discovery_enabled
        w.submit('drive_capture',ecu='7E8',pids=[0x83,0x85,12,13],raw_pids=[0x7A,0x88])
        event=wait_event(w,'capture',lambda s:s['active']); assert event['raw_pids']==[0x7A,0x88]
        for _ in range(4):
            record,readings=wait_event(w,'transaction',lambda s:s[0]['command']=='017A' and s[0].get('raw_only'))
            assert not readings and record['status']=='OK' and record['raw_samples'][0]['fields']==[]
            assert record['raw_samples'][0]['source_kind']=='SIMULATED'
            assert record['raw_samples'][0]['context_readings']['rpm']['simultaneous'] is False
        _,nox=wait_event(w,'transaction',lambda s:s[0]['command']=='0183')
        assert nox and all(r['source_kind']=='SIMULATED' for r in nox)
        assert w.recorder.id==session_id and not w.requires_reconnect
        w.submit('stop'); w.submit('disconnect'); wait_event(w,'connection',lambda s:s['adapter']=='Disconnected')
        session=list_sessions(tmp_path)[0]; path=tmp_path/session['raw_path']; original=path.read_bytes()
        export_research_bundle(tmp_path,session_id,tmp_path/'export.zip')
        assert path.read_bytes()==original
        with zipfile.ZipFile(tmp_path/'export.zip') as z:
            for line in z.read('SHA256SUMS.txt').decode().splitlines():
                digest,name=line.split('  '); assert hashlib.sha256(z.read(name)).hexdigest()==digest
            observations=json.loads(z.read('raw-observations.json'))
            assert any(o['raw_only'] and o['data_length']==13 for o in observations)
            assert json.loads(z.read('session-summary.json'))['raw_only_samples']>=8
            csv=z.read('measurements.csv'); assert b'sae_83_bank_1_sensor_1' in csv and b'sae_85_tank_level' in csv
            assert b'sae_7a_' not in csv and b'sae_88_' not in csv
        records=[json.loads(line) for line in original.splitlines()]
        w.submit('replay',path=str(path)); wait_event(w,'connection',lambda s:s['ecu']=='Replay paused')
        for _ in records:
            w.submit('step'); r,rs=wait_event(w,'transaction',lambda s:s[0].get('replay'))
            if r.get('raw_only'): assert not rs and r['discovery_samples'][0]['replay']
        assert w.transport is None and path.read_bytes()==original
    finally: shutdown(w)


def test_raw_capture_real_wire_cap_and_clean_stop(tmp_path,monkeypatch):
    calls=[]; original=Simulator._exchange
    def spy(self,command,*args): calls.append((self.last_wire_ns,command)); return original(self,command,*args)
    monkeypatch.setattr(Simulator,'_exchange',spy)
    w=AcquisitionWorker(tmp_path)
    try:
        w.submit('record'); w.submit('connect',simulation=True,port='COM4',scenario='Diesel alternative layouts')
        wait_event(w,'connection',lambda s:s['ecu']=='Connected')
        w.submit('discover',ecu='7E8'); wait_event(w,'discovery',lambda s:'Discovery ended' in s['reason'],timeout=15)
        w.submit('drive_capture',ecu='7E8',pids=[0x83],raw_pids=[0x7A,0x88])
        wait_event(w,'capture',lambda s:s['active'])
        for _ in range(3): wait_event(w,'transaction',lambda s:s[0]['command']=='0188' and s[0].get('raw_only'))
        w.submit('stop'); w.submit('disconnect'); wait_event(w,'connection',lambda s:s['adapter']=='Disconnected')
        assert all(b[0]-a[0]>=250000000 for a,b in zip(calls,calls[1:]))
        count=len(calls); time.sleep(.3); assert len(calls)==count
        assert w.recorder is None and list_sessions(tmp_path)[0]['ended']
    finally: shutdown(w)


def test_three_malformed_raw_replies_require_explicit_reconnect(tmp_path,fast_clock,monkeypatch):
    original=Simulator._exchange
    def malformed(self,command,*args):
        if command=='017A' and getattr(self,'break_raw',False): return b'7E8 10 08 41 7A 00 C8 00 00\r>'
        return original(self,command,*args)
    monkeypatch.setattr(Simulator,'_exchange',malformed)
    w=AcquisitionWorker(tmp_path)
    try:
        w.submit('connect',simulation=True,port='COM4',scenario='Diesel alternative layouts')
        wait_event(w,'connection',lambda s:s['ecu']=='Connected')
        w.submit('discover',ecu='7E8'); wait_event(w,'discovery',lambda s:'Discovery ended' in s['reason'])
        w.transport.break_raw=True
        w.submit('drive_capture',ecu='7E8',pids=[],raw_pids=[0x7A]); wait_event(w,'capture',lambda s:s['active'])
        wait_event(w,'acquisition',lambda s:s['requires_reconnect'])
        assert not w.polling and not w.transport.discovery_enabled and not w.discovery_observations['7E8',0x7A]['framing_valid']
        count=w.transport.last_wire_ns
        w.submit('drive_capture',ecu='7E8',pids=[],raw_pids=[0x7A]); wait_event(w,'notice',lambda s:'no eligible' in s)
        assert w.transport.last_wire_ns==count
        w.submit('start'); wait_event(w,'notice',lambda s:'reconnect' in s)
        assert not w.polling
    finally: shutdown(w)
