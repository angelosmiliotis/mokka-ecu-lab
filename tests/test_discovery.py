import base64
import json
import threading
import time
import pytest
from mokka_ecu_lab.adapter import AcquisitionWorker
from mokka_ecu_lab.discovery import discovery_report
from mokka_ecu_lab.protocols import DISCOVERY_PIDS, validate_command, UnsafeRequest, support_state
from mokka_ecu_lab.logging import list_sessions, export_csv
from mokka_ecu_lab.transport import SafeTransport
from mokka_ecu_lab.transport.simulator import Simulator
from test_negative_responses import wait_event, shutdown


@pytest.fixture
def fast_clock(monkeypatch):
    original=SafeTransport.exchange
    def exchange(self,*args,**kwargs):
        self.last_send=0  # Fixture-only clock; separate integration asserts wire rate.
        return original(self,*args,**kwargs)
    monkeypatch.setattr(SafeTransport,'exchange',exchange)


@pytest.mark.parametrize('pid',sorted(DISCOVERY_PIDS|{0x60,0x80,0xA0,0xC0,0xE0}))
def test_new_requests_require_explicit_scope_and_ecu_support(pid):
    command=f'01{pid:02X}'
    with pytest.raises(UnsafeRequest): validate_command(command,{pid})
    with pytest.raises(UnsafeRequest): validate_command(command,{pid},discovery_enabled=True,discovery_supported=set())
    assert validate_command(command,{pid},discovery_enabled=True,discovery_supported={pid})==command


@pytest.mark.parametrize('command',['22D525','22D526','22D52F','22D532','1003','2701','ATSH6A8','ATFCSD300000','ATCAF0','ATCFC0','2E123400','3101FF00','04','0190','010100'])
def test_offline_candidates_and_arbitrary_commands_stay_blocked(command):
    with pytest.raises(UnsafeRequest):
        validate_command(command,set(range(256)),discovery_enabled=True,discovery_supported=set(range(256)))


def test_future_page_unknown_and_closed_chain_unsupported_are_distinct():
    assert support_state({32,64,96,128},{0,32,64,96},0x85)=='unknown'
    assert support_state({32,64,96},{0,32,64,96},0x85)=='unsupported'
    assert support_state({32,64,96,128,0x85},{0,32,64,96,128},0x85)=='supported'


def test_default_connection_never_enables_or_sends_advanced_requests(tmp_path,fast_clock,monkeypatch):
    calls=[]; original=Simulator._exchange
    def spy(self,command,*args): calls.append(command); return original(self,command,*args)
    monkeypatch.setattr(Simulator,'_exchange',spy)
    w=AcquisitionWorker(tmp_path)
    try:
        w.submit('connect',simulation=True,port='COM4',scenario='Diesel discovery')
        wait_event(w,'transaction',lambda x: bool(x[1]))
        assert not w.transport.discovery_enabled
        assert not set(calls)&{'0160','0180','01A0','0178','0185','018B','ATCAF1','ATCFC1','ATAL'}
        w.submit('stop'); wait_event(w,'acquisition',lambda x:not x['polling'])
    finally: shutdown(w)


@pytest.mark.parametrize('scenario,ecu',[('Diesel discovery','7E8'),('Diesel discovery 29-bit','18DAF110'),('Diesel multi-ECU','7E8')])
def test_bitmap_chain_decodes_supported_fields_without_cross_ecu_inheritance(tmp_path,fast_clock,scenario,ecu):
    w=AcquisitionWorker(tmp_path)
    try:
        w.submit('record'); w.submit('connect',simulation=True,port='COM4',scenario=scenario)
        wait_event(w,'connection',lambda x:x['ecu']=='Connected')
        w.submit('discover',ecu=ecu)
        report=wait_event(w,'discovery',lambda x:'Discovery ended' in x['reason'])
        assert w.support_pages[ecu]=={0,32,64,96,128,160}
        assert not w.transport.discovery_enabled and not w.polling
        rows={int(e['pid'],16):e for e in report['standard'] if e['ecu']==ecu and 'pid' in e}
        assert rows[0x85]['support']=='SUPPORTED' and rows[0x85]['availability']=='AVAILABLE'
        assert rows[0x7B]['sample']['fields'][0]['value'] is None
        assert all(x['vehicle_verification']=='UNVERIFIED' for x in report['standard'])
        if scenario=='Diesel multi-ECU':
            assert 0x83 not in w.support['7E9']
            other=next(e for e in report['standard'] if e['ecu']=='7E9' and e.get('pid')=='83')
            assert other['availability']=='UNSUPPORTED' and other['sample']['fields']==[] and other['sample']['not_decoded']
        w.submit('record_stop'); wait_event(w,'recording',lambda x:x is None)
        session,=list_sessions(tmp_path)
        records=[json.loads(x) for x in (tmp_path/session['raw_path']).read_text().splitlines()]
        assert any(r['command']=='01A0' for r in records)
        assert not any(r['command']=='01C0' for r in records)
        assert all(r['command'].startswith(('01','AT','STI')) for r in records)
        original=next(r for r in records if r['command']=='0185')
        assert base64.b64decode(original['raw_b64']).decode()==original['raw_text']
        export_csv(tmp_path,session['id'],tmp_path/'decoded.csv')
        assert 'sae_85_tank_level' in (tmp_path/'decoded.csv').read_text(encoding='utf-8-sig')
        w.submit('replay',path=str(tmp_path/session['raw_path']))
        wait_event(w,'connection',lambda x:x['ecu']=='Replay paused')
        for _ in records:
            w.submit('step'); wait_event(w,'transaction',lambda x:x[0].get('replay'))
        assert w.transport is None
        assert w.discovery_observations[ecu,0x85]['fields'][2]['value']==80
        assert w.discovery_observations[ecu,0x85]['replay']
    finally: shutdown(w)


def test_missing_advertised_bitmap_remains_unknown_and_is_not_probed(tmp_path,fast_clock):
    w=AcquisitionWorker(tmp_path)
    try:
        w.submit('connect',simulation=True,port='COM4',scenario='Diesel unknown page')
        wait_event(w,'connection',lambda x:x['ecu']=='Connected')
        w.submit('discover',ecu='7E8')
        report=wait_event(w,'discovery',lambda x:'Discovery ended' in x['reason'])
        assert w.support_pages['7E8']=={0,32,64,96}
        assert not any(pid in w.discovery_observations for pid in [('7E8',0x83),('7E8',0x85),('7E8',0x8B)])
        assert next(e for e in report['standard'] if e.get('pid')=='85')['support']=='UNKNOWN'
    finally: shutdown(w)


def test_stop_during_discovery_closes_recording_without_new_requests(tmp_path,fast_clock):
    w=AcquisitionWorker(tmp_path)
    try:
        w.submit('record'); w.submit('connect',simulation=True,port='COM4',scenario='Diesel discovery')
        wait_event(w,'connection',lambda x:x['ecu']=='Connected')
        w.submit('discover',ecu='7E8')
        wait_event(w,'transaction',lambda x:x[0]['command']=='ATCAF1')
        w.submit('stop'); w.submit('disconnect')
        wait_event(w,'connection',lambda x:x['adapter']=='Disconnected')
        assert w.transport is None and not w.polling and w.recorder is None
        session,=list_sessions(tmp_path); assert session['ended']
        size=(tmp_path/session['raw_path']).stat().st_size
        time.sleep(.08); assert (tmp_path/session['raw_path']).stat().st_size==size
    finally: shutdown(w)


def test_discovery_recording_and_monitoring_keep_aggregate_wire_cap(tmp_path,monkeypatch):
    calls=[]; original=Simulator._exchange
    def spy(self,command,*args): calls.append((time.monotonic(),command)); return original(self,command,*args)
    monkeypatch.setattr(Simulator,'_exchange',spy)
    w=AcquisitionWorker(tmp_path)
    try:
        w.submit('connect',simulation=True,port='COM4',scenario='Diesel discovery')
        wait_event(w,'connection',lambda x:x['ecu']=='Connected')
        w.submit('discover',ecu='7E8')
        wait_event(w,'discovery',lambda x:'Discovery ended' in x['reason'],timeout=15)
        w.submit('monitor_discovery',ecu='7E8')
        wait_event(w,'transaction',lambda x:x[0]['command']=='018B',timeout=12)
        w.submit('stop'); wait_event(w,'acquisition',lambda x:not x['polling'])
        assert all(b[0]-a[0]>=.245 for a,b in zip(calls,calls[1:]))
        assert not w.transport.discovery_enabled and not w.discovery_active
        count=len(calls); time.sleep(.3); assert len(calls)==count
        assert len([c for _,c in calls if c=='018B'])>=2
    finally: shutdown(w)


def test_legacy_v011_fixture_replays_without_modification(tmp_path):
    from pathlib import Path
    path=Path(__file__).resolve().parents[1]/'samples/simulated-idle.jsonl'
    raw=path.read_bytes(); w=AcquisitionWorker(tmp_path)
    try:
        w.submit('replay',path=str(path)); wait_event(w,'connection',lambda x:x['ecu']=='Replay paused')
        decoded=[]
        for _ in range(len(raw.splitlines())):
            w.submit('step'); event=wait_event(w,'transaction',lambda x:x[0].get('replay'))
            decoded.extend(event[1])
        assert decoded and all(r['mode'].startswith('REPLAY') for r in decoded)
        assert w.transport is None and path.read_bytes()==raw
        report=discovery_report(w.support,w.support_pages,w.discovery_observations,mode=w.mode)
        assert next(e for e in report['standard'] if e.get('pid')=='85')['support']=='UNSUPPORTED'
    finally: shutdown(w)
