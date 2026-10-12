"""Constructed B115 payloads; no vehicle recording fixtures."""
import pytest
from mokka_ecu_lab.sensors.diesel import STANDARD_DIESEL
from mokka_ecu_lab.layouts import layout_evidence
from mokka_ecu_lab.protocols import Response,validate_command,UnsafeRequest
from mokka_ecu_lab.protocols.isotp import parse_reply
from mokka_ecu_lab.transport.simulator import can_reply,DIESEL_PAYLOADS
from mokka_ecu_lab.adapter import AcquisitionWorker
from test_capture import evidence
from test_discovery import fast_clock
from test_negative_responses import wait_event,shutdown


def decode(payload): return {f['id']:f for f in STANDARD_DIESEL[0x88].decode(payload)}


def test_b115_all_counters_unsigned_big_endian_and_no_sentinel():
    f=decode(bytes.fromhex('00 00 00 01 02 03 04 05 06 07 08 09 0A'))
    assert len(f)==26
    assert [x['value'] for x in f.values() if x['unit']=='km']==[258,772,1286,1800,2314]
    assert all(x['temporal_semantics'] and x['sentinel'] is None for x in f.values())
    assert all(x['vehicle_verification']=='UNVERIFIED' for x in f.values())
    f=decode(bytes.fromhex('00 00 00 FF FF 00 01 00 00 00 00 00 00'))
    assert f['active_distance_current']['value']==65535
    assert len(f['active']['semantic_warnings'])==2


@pytest.mark.parametrize('block',range(4))
@pytest.mark.parametrize('reason',range(4))
def test_each_history_bit_is_latched_history_and_does_not_activate_current(block,reason):
    p=bytearray(13); p[1+block//2]=1<<((block%2)*4+reason)
    fields=decode(bytes(p))
    assert fields['active']['value']==0
    history=[f for key,f in fields.items() if key.startswith('history_')]
    assert sum(f['value'] for f in history)==1
    assert fields[f'history_{block}_{reason}']['value']==1
    assert 'not a current fault' in fields[f'history_{block}_{reason}']['temporal_semantics']


@pytest.mark.parametrize('reason',range(4))
def test_each_current_reason_and_active_bit(reason):
    p=bytearray(13); p[0]=0x80|(1<<reason)
    f=list(decode(bytes(p)).values())
    assert f[0]['value']==1 and [x['value'] for x in f[1:5]]==[int(i==reason) for i in range(4)]


@pytest.mark.parametrize('status',[0x10,0x20,0x40,0xF0,0x01,0x0F])
def test_reserved_bits_and_inactive_reasons_fail_closed(status):
    with pytest.raises(ValueError): decode(bytes([status])+bytes(12))


@pytest.mark.parametrize('length',[0,3,6,12,14,15])
def test_other_lengths_are_unverified_not_old_oct2011(length):
    p=bytes(length)
    with pytest.raises(ValueError,match='exactly 13'): decode(p)
    assert layout_evidence(0x88,p)['layout_status']=='DECODER_UNVERIFIED'


def test_cross_ecu_framing_negative_and_raw_choice(tmp_path,monkeypatch):
    monkeypatch.setattr(AcquisitionWorker,'start',lambda self:None)
    w=AcquisitionWorker(tmp_path); w.support,w.support_pages,_=evidence()
    p=DIESEL_PAYLOADS[0x88]
    raw=(can_reply('7E8',0x88,p)+'\r'+can_reply('7E9',0x88,bytes(3))+'\r>').encode()
    parsed=parse_reply(raw,0x88)
    samples=[w.diesel_sample(r,0x88,'synthetic',1) for r in parsed.responses]
    assert len(samples[0]['fields'])==26 and samples[1]['fields']==[]
    raw_sample=w.diesel_sample(Response('7E8',p),0x88,'synthetic',1,raw_only=True)
    assert raw_sample['fields']==[] and raw_sample['layout_status']=='STANDARD_DOCUMENTED'
    negative=parse_reply(b'7E8 03 7F 01 22\r>',0x88)
    assert negative.responses[0].negative_code==0x22
    broken=(can_reply('7E8',0x88,p).split('\r')[0]+'\r'+can_reply('7E9',0x88,p)+'\r>').encode()
    result=parse_reply(broken,0x88)
    assert result.errors and [r.header for r in result.responses]==['7E9']


def test_corrected_numeric_monitor_and_raw_override(tmp_path,fast_clock):
    w=AcquisitionWorker(tmp_path)
    try:
        w.submit('connect',simulation=True,port='COM4',scenario='Diesel discovery')
        wait_event(w,'connection',lambda s:s['ecu']=='Connected')
        w.submit('discover',ecu='7E8');wait_event(w,'discovery',lambda s:'Discovery ended' in s['reason'])
        w.submit('drive_capture',ecu='7E8',pids=[0x88]);wait_event(w,'capture',lambda s:s['active'])
        record,readings=wait_event(w,'transaction',lambda s:s[0]['command']=='0188')
        assert record['status']=='OK' and len(readings)==26
        assert {r['verification'] for r in readings}=={'STANDARD_DOCUMENTED'}
        w.submit('drive_capture',ecu='7E8',pids=[0x88],raw_pids=[0x88]);wait_event(w,'capture',lambda s:s['raw_pids']==[0x88])
        record,readings=wait_event(w,'transaction',lambda s:s[0]['command']=='0188' and s[0].get('raw_only'))
        assert readings==[] and record['raw_samples'][0]['layout_status']=='STANDARD_DOCUMENTED'
    finally: shutdown(w)


def test_six_byte_dpf_still_fail_closed_and_oem_stays_forbidden():
    p=bytes.fromhex('00 C8 00 00 00 00')
    with pytest.raises(ValueError,match='exactly 7'): STANDARD_DIESEL[0x7A].decode(p)
    for command in ('22D525','22D526','22D52F','22D532','1003','2701','04','ATSH7E0'):
        with pytest.raises(UnsafeRequest): validate_command(command,{0x88},discovery_enabled=True,discovery_supported={0x88})


def test_legacy_three_byte_replay_retains_raw_but_no_numeric_values(tmp_path,fast_clock):
    import json
    from test_research import transaction
    record=transaction(0x88,bytes(3),1);record.update(status='OK',support_evidence={'7E8':[0x88]},support_pages={'7E8':[0,32,64,96,128]})
    path=tmp_path/'constructed.jsonl';original=(json.dumps(record)+'\n').encode();path.write_bytes(original)
    w=AcquisitionWorker(tmp_path)
    try:
        w.submit('replay',path=str(path));wait_event(w,'connection',lambda s:s['ecu']=='Replay paused')
        w.submit('step'); r,readings=wait_event(w,'transaction',lambda s:s[0].get('replay'))
        assert readings==[] and r['raw_b64']==record['raw_b64']
        assert r['discovery_samples'][0]['layout_status']=='DECODER_UNVERIFIED'
        assert w.transport is None and path.read_bytes()==original
    finally: shutdown(w)
