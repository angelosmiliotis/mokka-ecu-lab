"""Constructed fake Windows COM lifecycle; no physical serial port or vehicle data."""
import base64
import hashlib
import json
import threading
import time
from types import SimpleNamespace

import pytest

from mokka_ecu_lab.adapter import AcquisitionWorker
from mokka_ecu_lab.logging import list_sessions
from mokka_ecu_lab.transport import SerialTransport
from mokka_ecu_lab.transport.simulator import Simulator
from test_discovery import fast_clock
from test_negative_responses import shutdown, wait_event
from test_session import wait_state
from test_v029_worker import until


@pytest.fixture
def com(tmp_path, monkeypatch):
    import mokka_ecu_lab.transport as transport_module
    h=SimpleNamespace(handles=[],wire=[],events=[],arm=False,partial=False,blocked=threading.Event(),release=threading.Event())

    class FakeSerial:
        def __init__(self,port,**_):
            assert port=='SYNTHETIC-COM'
            self.is_open=True;self.buffer=bytearray();self.pending=False;self.lost=False
            self.engine=Simulator('Diesel thirteen sensors');h.handles.append(self)
        @property
        def in_waiting(self):return len(self.buffer)
        def write(self,data):
            if self.lost:raise transport_module.serial.SerialException('Constructed removed port')
            command=data.decode().strip();h.wire.append((self,command,threading.get_ident(),time.monotonic_ns()))
            response=self.engine._exchange(command,threading.Event(),1)
            if command=='ATDPN' and getattr(h,'protocol_changed',False):response=b'A3\r>'
            if command=='0100' and getattr(h,'ecu_changed',False):response=response.replace(b'7E8',b'7E9')
            self.buffer=bytearray(response)
            if h.arm and h.worker.capture_mode and command.startswith('01'):
                h.arm=False;self.pending=True;h.blocked.set()
                if h.partial:self.buffer=self.buffer.rstrip(b'>')
            return len(data)
        def read(self,_):
            if self.lost:raise transport_module.serial.SerialException('Constructed removed port')
            if self.pending and not h.release.wait(.01):return b''
            self.pending=False
            if self.buffer:return bytes([self.buffer.pop(0)])
            time.sleep(.002);return b''
        def close(self):
            if getattr(h,'close_error',False):raise OSError('Constructed close failure')
            self.is_open=False

    monkeypatch.setattr(transport_module.serial,'Serial',FakeSerial)
    monkeypatch.setattr('serial.tools.list_ports.comports',lambda:[SimpleNamespace(device='SYNTHETIC-COM',description='Synthetic outgoing test port')])
    # Keep missing-prompt fault tests bounded; normal fake replies remain complete.
    original=SerialTransport._exchange
    monkeypatch.setattr(SerialTransport,'_exchange',lambda self,c,stop,timeout:original(self,c,stop,min(timeout,.4)))
    h.worker=AcquisitionWorker(tmp_path)
    original_emit=h.worker.emit
    def emit(kind,value):
        h.events.append((kind,value,h.worker.context_id));original_emit(kind,value)
    h.worker.emit=emit
    try:yield h
    finally:h.release.set();shutdown(h.worker)


def connect(h):
    h.worker.submit('session_connect',simulation=False,port='SYNTHETIC-COM',baud=115200)
    assert wait_state(h.worker,lambda d:d['state'] in {'CONNECTED','FAILED'})['state']=='CONNECTED'


def start(h):
    h.worker.submit('session_start',simulation=False,port='SYNTHETIC-COM',baud=115200)
    result=wait_state(h.worker,lambda d:d['state'] in {'CAPTURING','PARTIAL','FAILED'})
    assert result['state']=='CAPTURING'
    return result


def finish(h):
    h.worker.submit('session_finish')
    return wait_state(h.worker,lambda d:d['state']=='EXPORTED')


def bench(h):
    h.worker.submit('bench_auto_start',simulation=False,port='SYNTHETIC-COM',baud=115200,rate=4,parked_consent=True)
    until(lambda:h.worker.benchmark and h.worker.benchmark.requests>=4)
    h.worker.benchmark.started=time.monotonic()-60
    return wait_event(h.worker,'benchmark',lambda d:d.get('exported'))


@pytest.mark.parametrize('sequence',[('session','session'),('session','bench'),('bench','session')])
def test_one_handle_fresh_context_and_recorded_preflight_each_explicit_start(com,fast_clock,sequence):
    h=com;w=h.worker;contexts=[];session_ids=[]
    if sequence[0]=='session':connect(h)
    for action in sequence:
        if action=='session':
            first=start(h);session_ids.append(first['session_id']);state=finish(h)
            assert state['checksums_verified'] and state['connection_state']=='CONNECTED_IDLE'
        else:
            state=bench(h);session_ids.append(state['session_id']);assert state['state']=='CONNECTED_IDLE'
        assert w.transport and w.transport.idle_status()==dict(open=True,prompt_synchronized=True)
        assert not w.polling and not w.recorder and not state['disconnected']
        assert w.transport.operation_deadline_ns is None
        contexts.append(w.context_id)
        before=len(h.wire);time.sleep(.18);assert len(h.wire)==before
    assert len(h.handles)==1 and len(set(contexts))==2 and len(set(session_ids))==2
    assert len({thread for _,_,thread,_ in h.wire})==1
    for context in contexts:
        assert any(k=='connection' and d['ecu']=='Connected' and c==context for k,d,c in h.events)
    for session in list_sessions(w.root):
        records=[json.loads(line) for line in (w.root/session['raw_path']).read_text().splitlines()]
        transactions=[r for r in records if r.get('record_type')=='transaction']
        assert len({r['context_id'] for r in transactions})==1
        assert any(r['command']=='0100' for r in transactions)
        assert any(r['command']=='ATDPN' for r in transactions)
        assert all(r['context_id'] in contexts for r in transactions)


def test_finish_waits_for_clean_pending_reply_and_keeps_last_proved_sample(com,fast_clock):
    h=com;connect(h);start(h);w=h.worker
    h.arm=True;assert h.blocked.wait(3)
    current=h.wire[-1][1];before=len(h.wire)
    w.submit('session_finish');time.sleep(.04)
    assert not w.stop_io.is_set() and w.recorder and w.transport
    h.release.set();state=wait_state(w,lambda d:d['state']=='EXPORTED')
    assert state['connection_state']=='CONNECTED_IDLE' and len(h.wire)==before
    session=list_sessions(w.root)[0]
    rows=[json.loads(line) for line in (w.root/session['raw_path']).read_text().splitlines()]
    last=[r for r in rows if r.get('record_type')=='transaction'][-1]
    assert last['command']==current and last['status']=='OK' and base64.b64decode(last['raw_b64']).endswith(b'>')
    assert not any(r.get('status')=='CANCELLED' for r in rows)


def test_finish_partial_body_without_prompt_is_not_a_completed_numeric_sample(com,fast_clock):
    h=com;connect(h);start(h);w=h.worker
    h.arm=h.partial=True;assert h.blocked.wait(3);h.release.set()
    state=finish(h)
    assert state['disconnected'] and not w.transport and w.requires_reconnect
    session=list_sessions(w.root)[0]
    rows=[json.loads(line) for line in (w.root/session['raw_path']).read_text().splitlines()]
    last=[r for r in rows if r.get('record_type')=='transaction'][-1]
    assert last['status']=='TRANSPORT_ERROR' and last['parsed']==[] and last['decoder']==[]
    assert not base64.b64decode(last['raw_b64']).endswith(b'>')
    from mokka_ecu_lab.logging import connect_database
    db=connect_database(w.root)
    try:assert db.execute('SELECT COUNT(*) FROM readings WHERE transaction_id=?',(last['id'],)).fetchone()[0]==0
    finally:db.close()


@pytest.mark.parametrize('action',['stop','disconnect','system_suspend','shutdown'])
def test_explicit_close_or_suspend_during_receive_exports_saved_evidence_and_closes(com,fast_clock,action):
    h=com;connect(h);start(h);w=h.worker
    h.arm=True;assert h.blocked.wait(3)
    w.submit(action)
    if action=='shutdown':w.join(5);assert not w.is_alive()
    else:until(lambda:w.transport is None and not w.session.active and w.recorder is None)
    assert not h.handles[0].is_open and not w.polling
    sessions=list_sessions(w.root);assert len(sessions)==1 and sessions[0]['ended']
    assert len(list((w.root/'Reports').rglob('original-research.zip')))==1
    rows=[json.loads(line) for line in (w.root/sessions[0]['raw_path']).read_text().splitlines()]
    assert any(r.get('status')=='CANCELLED' for r in rows)
    before=len(h.wire);time.sleep(.12);assert len(h.wire)==before


def test_export_failure_closes_then_offline_retry_has_zero_live_sends(com,fast_clock,monkeypatch):
    import mokka_ecu_lab.adapter as adapter_module
    h=com;connect(h);start(h);w=h.worker
    original=adapter_module.export_closed_session
    monkeypatch.setattr(adapter_module,'export_closed_session',lambda *_:(_ for _ in ()).throw(OSError('Constructed disk failure')))
    w.submit('session_finish');failed=wait_state(w,lambda d:d['state']=='FAILED' and d.get('retry_export'))
    assert not failed['active'] and failed['disconnected'] and not w.transport
    journal=w.root/list_sessions(w.root)[0]['raw_path'];digest=hashlib.sha256(journal.read_bytes()).hexdigest();before=len(h.wire)
    monkeypatch.setattr(adapter_module,'export_closed_session',original)
    w.submit('session_export_retry');out=wait_state(w,lambda d:d['state']=='EXPORTED')
    assert out['checksums_verified'] and len(h.wire)==before and not w.transport
    assert hashlib.sha256(journal.read_bytes()).hexdigest()==digest


@pytest.mark.parametrize('change',[dict(simulation=True),dict(port='OTHER-SYNTHETIC'),dict(baud=9600)])
def test_idle_source_port_baud_mismatch_cannot_send_or_reopen(com,fast_clock,change):
    h=com;connect(h);start(h);finish(h);w=h.worker;before=len(h.wire);handle=w.transport
    options=dict(simulation=False,port='SYNTHETIC-COM',baud=115200);options.update(change)
    w.submit('session_start',**options);wait_event(w,'session_rejected')
    assert len(h.wire)==before and len(h.handles)==1 and w.transport is handle


@pytest.mark.parametrize('cause',['port_loss','broken_prompt','protocol_changed'])
def test_retained_invalid_handle_or_changed_protocol_fails_closed(com,fast_clock,cause):
    h=com;connect(h);start(h);finish(h);w=h.worker;before=len(h.wire)
    if cause=='port_loss':h.handles[0].is_open=False
    elif cause=='broken_prompt':w.transport.prompt_synchronized=False
    else:h.protocol_changed=True
    w.submit('session_start',simulation=False,port='SYNTHETIC-COM',baud=115200)
    if cause=='protocol_changed':
        wait_state(w,lambda d:d['state']=='FAILED');w.submit('session_finish')
        wait_state(w,lambda d:d['state']=='EXPORTED')
        assert len(h.wire)==before+1 and h.wire[-1][1]=='ATDPN'
    else:until(lambda:w.transport is None);assert len(h.wire)==before
    assert not w.transport and w.requires_reconnect


def test_manual_disconnect_after_finish_has_no_diagnostic_send(com,fast_clock):
    h=com;connect(h);start(h);finish(h);w=h.worker;before=len(h.wire)
    w.submit('disconnect');until(lambda:w.transport is None and w.session.data['state']=='DISCONNECTED')
    assert len(h.wire)==before and not h.handles[0].is_open


def test_actual_port_loss_during_collection_closes_without_reconnect_and_finish_exports(com,fast_clock):
    h=com;connect(h);start(h);w=h.worker
    h.handles[0].lost=True
    until(lambda:w.transport is None)
    before=len(h.wire);state=finish(h)
    assert state['disconnected'] and w.requires_reconnect and len(h.handles)==1
    time.sleep(.15);assert len(h.wire)==before


def test_failed_recorder_close_is_recoverable_offline_without_more_wire_traffic(com,fast_clock,monkeypatch):
    h=com;connect(h);start(h);w=h.worker
    recorder=w.recorder
    monkeypatch.setattr(recorder,'close',lambda **_:(_ for _ in ()).throw(OSError('Constructed close failure')))
    w.submit('session_finish');state=wait_state(w,lambda d:d['state']=='FAILED' and d.get('retry_export'))
    assert not w.transport and not w.recorder and not state['active']
    session=list_sessions(w.root)[0];assert not session['ended']
    journal=w.root/session['raw_path'];digest=hashlib.sha256(journal.read_bytes()).hexdigest();before=len(h.wire)
    w.submit('session_export_retry');out=wait_state(w,lambda d:d['state']=='EXPORTED')
    assert out['checksums_verified'] and not w.transport and len(h.wire)==before
    assert hashlib.sha256(journal.read_bytes()).hexdigest()==digest


def test_explicit_source_switch_and_offline_replay_close_retained_handle(com,fast_clock):
    h=com;connect(h);start(h);finish(h);w=h.worker
    first=list_sessions(w.root)[0];journal=w.root/first['raw_path'];original=journal.read_bytes()
    w.submit('replay',path=str(journal))
    wait_event(w,'connection',lambda d:d['ecu']=='Replay paused')
    assert not w.transport and not h.handles[0].is_open and w.mode=='REPLAY'
    before=len(h.wire);w.submit('step')
    first_record=json.loads(original.splitlines()[0])
    wait_event(w,'marker' if first_record.get('record_type')=='marker' else 'transaction')
    assert len(h.wire)==before and journal.read_bytes()==original
    # Explicit source selection starts a new context; replay never becomes LIVE.
    w.submit('connect',simulation=True,scenario='Diesel thirteen sensors')
    wait_event(w,'connection',lambda d:d['ecu']=='Connected')
    assert w.mode=='SIMULATED' and len(h.handles)==1
    assert list_sessions(w.root)[0]['mode'].startswith('LIVE')


def test_reused_benchmark_cannot_silently_change_the_reserved_ecu(com,fast_clock):
    h=com;connect(h);start(h);finish(h);w=h.worker;h.ecu_changed=True
    w.submit('bench_auto_start',simulation=False,port='SYNTHETIC-COM',baud=115200,rate=4,parked_consent=True)
    out=wait_event(w,'benchmark',lambda d:d.get('exported'))
    assert out['state']=='ABORTED' and out['disconnected'] and 'ECU_MISMATCH' in out['reason']
    assert not w.transport and len(h.handles)==1
    assert not any(k=='connection' and d['ecu']=='Connected' and c==w.context_id for k,d,c in h.events)


def test_close_error_isolates_handle_preserves_offline_retry_and_worker_can_terminate(com,fast_clock,monkeypatch):
    import mokka_ecu_lab.adapter as adapter_module
    h=com;connect(h);start(h);w=h.worker;h.close_error=True
    original=adapter_module.export_closed_session
    monkeypatch.setattr(adapter_module,'export_closed_session',lambda *_:(_ for _ in ()).throw(OSError('Constructed export failure')))
    w.submit('session_finish');state=wait_state(w,lambda d:d['state']=='FAILED' and d.get('retry_export'))
    assert not w.transport and w.unclosed_transport and w.requires_reconnect
    assert state['isolated_handle'] and not state['handle_close_confirmed'] and state['connection_state']=='RECONNECT_REQUIRED'
    before=len(h.wire);w.submit('session_connect',simulation=False,port='SYNTHETIC-COM',baud=115200)
    assert 'close' in wait_event(w,'session_rejected')
    assert w.session.data['session_id']==state['session_id']
    assert len(h.handles)==1 and len(h.wire)==before
    monkeypatch.setattr(adapter_module,'export_closed_session',original)
    w.submit('session_export_retry');out=wait_state(w,lambda d:d['state']=='EXPORTED')
    assert out['checksums_verified'] and out['isolated_handle'] and len(h.wire)==before
    w.submit('shutdown');w.join(5)
    assert not w.is_alive() and len(h.wire)==before
    # Explicit fixture cleanup mirrors the user's later Disconnect retry.
    h.close_error=False;w.disconnect()
    assert not w.unclosed_transport and not h.handles[0].is_open


def test_new_session_resets_prior_adaptive_backoff_and_reports_actual_new_rate(com,fast_clock):
    h=com;connect(h);start(h);w=h.worker
    w.pacing.rate=2.;w.transport.rate=2.
    finish(h);start(h)
    assert w.pacing.rate==w.transport.rate==w.rate==4.
    until(lambda:w.auto_receipt.data.get('adaptive_pacing'))
    receipt=w.auto_receipt.snapshot()
    assert receipt['adaptive_pacing']['rate']==4.
    finish(h)


@pytest.mark.parametrize('method',['marker','evidence'])
def test_initial_finish_marker_or_evidence_failure_preserves_offline_recovery(com,fast_clock,monkeypatch,method):
    h=com;connect(h);start(h);w=h.worker
    h.arm=True;assert h.blocked.wait(3)
    recorder=w.recorder
    monkeypatch.setattr(recorder,method,lambda *a,**kw:(_ for _ in ()).throw(OSError('Constructed finalization storage failure')))
    w.submit('session_finish');h.release.set()
    failed=wait_state(w,lambda d:d['state']=='FAILED' and d.get('retry_export'))
    assert not failed['active'] and not w.transport and not w.recorder and w.is_alive()
    journal=w.root/list_sessions(w.root)[0]['raw_path'];digest=hashlib.sha256(journal.read_bytes()).hexdigest();before=len(h.wire)
    w.submit('session_export_retry');out=wait_state(w,lambda d:d['state']=='EXPORTED')
    assert out['checksums_verified'] and out['export_outcome']=='VERIFIED' and len(h.wire)==before
    assert hashlib.sha256(journal.read_bytes()).hexdigest()==digest


def test_disconnect_cleanup_refreshes_failed_state_without_losing_export_retry(com,fast_clock,monkeypatch):
    import mokka_ecu_lab.adapter as adapter_module
    h=com;connect(h);start(h);w=h.worker;h.close_error=True
    monkeypatch.setattr(adapter_module,'export_closed_session',lambda *_:(_ for _ in ()).throw(OSError('Constructed export failure')))
    w.submit('session_finish');failed=wait_state(w,lambda d:d['state']=='FAILED' and d.get('isolated_handle'))
    before=len(h.wire);h.close_error=False;w.submit('disconnect')
    cleaned=wait_state(w,lambda d:d['state']=='FAILED' and d.get('handle_close_confirmed'))
    assert not cleaned['isolated_handle'] and cleaned['retry_export']
    assert cleaned['session_id']==failed['session_id'] and len(h.wire)==before
    assert not h.handles[0].is_open


def test_finish_during_actual_rate_wait_does_not_send_the_unsent_request(com,monkeypatch):
    # Real pacing here (no fast_clock) protects the boundary before the wire send.
    h=com;connect(h);start(h);w=h.worker;waiting=threading.Event();original=w.transport.exchange
    def rate_wait(command,stop,timeout=6):
        if not waiting.is_set():
            w.transport._last_send_ns=time.monotonic_ns()
            w.transport.last_send=w.transport._last_send_ns/1e9
            waiting.set()
        return original(command,stop,timeout)
    monkeypatch.setattr(w.transport,'exchange',rate_wait)
    assert waiting.wait(3);before=len(h.wire)
    out=finish(h)
    assert len(h.wire)==before and out['connection_state']=='CONNECTED_IDLE'
    session=list_sessions(w.root)[0]
    rows=[json.loads(line) for line in (w.root/session['raw_path']).read_text().splitlines()]
    assert not any(r.get('status')=='CANCELLED' for r in rows)
