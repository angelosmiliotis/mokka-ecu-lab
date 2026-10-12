import json
import threading
import time
import pytest
from mokka_ecu_lab.capture import capture_plan, manual_options, DRIVE_WEIGHTS
from mokka_ecu_lab.protocols import DISCOVERY_PIDS, LIVE_PIDS
from mokka_ecu_lab.sensors.diesel import STANDARD_DIESEL
from mokka_ecu_lab.transport.simulator import DIESEL_PAYLOADS, Simulator
from mokka_ecu_lab.adapter import AcquisitionWorker
from mokka_ecu_lab.logging import list_sessions
from test_negative_responses import wait_event, shutdown
from test_discovery import fast_clock


def evidence(ecu='7E8'):
    support={ecu:set(DRIVE_WEIGHTS)|{32,64,96,128}|DISCOVERY_PIDS}
    pages={ecu:{0,32,64,96,128}}
    observations={(ecu,p):{'fields':STANDARD_DIESEL[p].decode(data)} for p,data in DIESEL_PAYLOADS.items()}
    return support,pages,observations


def test_preset_requires_discovery_and_cannot_inherit_another_ecu():
    support,pages,samples=evidence()
    assert not capture_plan(support,pages,samples,'7E8')['weights']
    plan=capture_plan(support,pages,samples,'7E8',prepared=True)
    assert plan['weights']==DRIVE_WEIGHTS and not plan['omitted']
    assert not capture_plan(support,pages,samples,'7E9',prepared=True)['weights']
    support['7E9']={5}; pages['7E9']={0}
    plan=capture_plan(support,pages,samples,'7E9',prepared=True)
    assert plan['weights']=={5:1}
    assert any('UNSUPPORTED' in r['reason'] for r in plan['omitted'])


def test_invalid_missing_unknown_and_no_supported_fields_are_omitted():
    support,pages,samples=evidence(); samples.pop(('7E8',0x78))
    samples['7E8',0x8B]['error']='wrong length'
    samples['7E8',0x7A]['fields']=[]
    pages['7E8'].remove(128); support['7E8'].remove(0x85)
    plan=capture_plan(support,pages,samples,'7E8',prepared=True)
    assert not {0x78,0x8B,0x7A,0x85}&plan['weights'].keys()
    assert any('UNKNOWN' in e['reason'] for e in plan['omitted'])
    options=manual_options(*evidence(),'7E8',prepared=True)
    assert 0x7B not in options['weights'] and 0x83 in options['weights']


def test_manual_selection_deduplicates_and_never_authorizes_oem_or_bitmap():
    plan=capture_plan(*evidence(),'7E8',prepared=True,selected=[0x83,0x0C,0x83,0x22,0x60])
    assert plan['weights']=={0x83:1,0x0C:2} and len(plan['omitted'])==2
    assert not capture_plan(*evidence(),'7E8',prepared=True,selected=[])['weights']


def test_drive_weights_share_existing_scheduler_without_starvation():
    from collections import Counter
    from mokka_ecu_lab.adapter.scheduling import PollScheduler
    scheduler=PollScheduler()
    counts=Counter(scheduler.next(list(DRIVE_WEIGHTS),DRIVE_WEIGHTS,allow_discovery=True) for _ in range(900))
    assert counts=={p:w*50 for p,w in DRIVE_WEIGHTS.items()}


def test_empty_manual_selection_stops_capture_without_any_send(tmp_path,monkeypatch):
    monkeypatch.setattr(AcquisitionWorker,'start',lambda self:None)
    w=AcquisitionWorker(tmp_path); w.transport=Simulator('Diesel discovery')
    w.support,w.support_pages,w.discovery_observations=evidence()
    w.discovery_prepared=True; w.discovery_target='7E8'; w.can_protocol=True
    w.handle('drive_capture',{'ecu':'7E8','pids':[0x8B]})
    assert w.capture_mode and w.polling
    w.handle('drive_capture',{'ecu':'7E8','pids':[]})
    assert not w.polling and not w.capture_mode and not w.transport.discovery_enabled
    assert w.transport.last_wire_ns is None
    w.disconnect()


def test_drive_transition_keeps_recording_and_only_chosen_requests(tmp_path,fast_clock,monkeypatch):
    calls=[]; original=Simulator._exchange
    def spy(self,command,*args): calls.append(command); return original(self,command,*args)
    monkeypatch.setattr(Simulator,'_exchange',spy)
    w=AcquisitionWorker(tmp_path)
    try:
        w.submit('connect',simulation=True,port='COM4',scenario='Diesel discovery')
        wait_event(w,'connection',lambda s:s['ecu']=='Connected')
        w.submit('record'); session_id=wait_event(w,'recording',bool)
        w.submit('discover',ecu='7E8'); wait_event(w,'discovery',lambda s:'Discovery ended' in s['reason'])
        boundary=len(calls)
        w.submit('drive_capture',ecu='7E8',pids=[0x8B,0x7A,0x0C,0x7B,0x22])
        event=wait_event(w,'capture',lambda s:s['active'])
        assert event['weights']=={0x8B:4,0x7A:3,0x0C:2}
        for _ in range(10): wait_event(w,'transaction',lambda s:s[0]['command']=='018B')
        assert w.recorder.id==session_id
        assert set(calls[boundary:])<={'018B','017A','010C'}
        w.submit('stop'); wait_event(w,'acquisition',lambda s:not s['polling'])
        n=len(calls); time.sleep(.08); assert len(calls)==n and not w.transport.discovery_enabled
        w.submit('record_stop'); wait_event(w,'recording',lambda s:s is None)
        session=list_sessions(tmp_path)[0]; assert session['id']==session_id and session['ended']
        records=[json.loads(line) for line in (tmp_path/session['raw_path']).read_text().splitlines()]
        assert any(r['command']=='0178' for r in records) and any(r['command']=='018B' for r in records)
        assert all(r['record_type']=='transaction' for r in records)
        metadata=json.loads(session['metadata'])['capture_evidence']
        assert metadata['discovery_completed'] and metadata['capture_weights']=={'139':4,'122':3,'12':2}
        # Replay without initialization bitmaps: advanced records retain earlier support evidence.
        w.submit('replay',path=str(tmp_path/session['raw_path'])); wait_event(w,'connection',lambda s:s['ecu']=='Replay paused')
        for _ in records:
            w.submit('step'); wait_event(w,'transaction',lambda s:s[0].get('replay'))
        assert w.transport is None and w.discovery_observations['7E8',0x8B]['fields'][0]['value']==1
    finally: shutdown(w)


def test_real_capture_wire_cap_and_stop_disconnect(tmp_path,monkeypatch):
    calls=[]; original=Simulator._exchange
    def spy(self,command,*args): calls.append((time.monotonic(),command)); return original(self,command,*args)
    monkeypatch.setattr(Simulator,'_exchange',spy)
    w=AcquisitionWorker(tmp_path)
    try:
        w.submit('record'); w.submit('connect',simulation=True,port='COM4',scenario='Diesel discovery')
        wait_event(w,'connection',lambda s:s['ecu']=='Connected')
        w.submit('discover',ecu='7E8'); wait_event(w,'discovery',lambda s:'Discovery ended' in s['reason'],timeout=15)
        w.submit('drive_capture',ecu='7E8',pids=[0x8B,0x7A,0x0C])
        wait_event(w,'capture',lambda s:s['active'])
        for _ in range(5): wait_event(w,'transaction',lambda s:s[0]['command']=='018B')
        w.submit('stop'); w.submit('disconnect'); wait_event(w,'connection',lambda s:s['adapter']=='Disconnected')
        assert all(b[0]-a[0]>=.245 for a,b in zip(calls,calls[1:]))
        assert w.transport is None and w.recorder is None and list_sessions(tmp_path)[0]['ended']
        count=len(calls); time.sleep(.3); assert len(calls)==count
    finally: shutdown(w)
