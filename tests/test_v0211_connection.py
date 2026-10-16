"""Constructed serial lifecycle cases; no real COM or captured bytes."""
import time
import pytest
from mokka_ecu_lab.adapter import AcquisitionWorker
from mokka_ecu_lab.transport import SerialTransport,SerialOpenError
from mokka_ecu_lab.transport.simulator import Simulator
from test_discovery import fast_clock
from test_negative_responses import shutdown,wait_event
from test_v029_worker import until

def finish(w):
    until(lambda:w.benchmark and w.benchmark.requests>=4)
    w.benchmark.started=time.monotonic()-60
    return wait_event(w,'benchmark',lambda d:d.get('exported'))

def test_consecutive_234_reuses_handle_context_no_idle_requests_then_normal(tmp_path,fast_clock,monkeypatch):
    import mokka_ecu_lab.adapter as module
    handles=[];wire=[]
    class Serial(Simulator):
        def __init__(self,*_):super().__init__('Diesel thirteen sensors');self.baud=115200;self.closed=False;handles.append(self)
        def _exchange(self,c,*args):wire.append((self,c));return super()._exchange(c,*args)
        def close(self):self.closed=True
    monkeypatch.setattr(module,'SerialTransport',Serial)
    w=AcquisitionWorker(tmp_path);ids=[]
    try:
        context=None
        for rate in (2,3,4):
            w.submit('bench_auto_start',simulation=False,port='CONSTRUCTED-COM',rate=rate,parked_consent=True)
            state=finish(w);ids.append(state['session_id'])
            assert state['state']=='CONNECTED_IDLE' and not state['disconnected'] and not w.polling and not w.recorder
            assert w.transport.operation_deadline_ns is None and w.session.data['state']=='CONNECTED'
            assert context is None or context==w.context_id
            context=w.context_id;n=len(wire);time.sleep(.22);assert len(wire)==n
        assert len(handles)==1 and len(set(ids))==3 and not handles[0].closed
        # Normal Start reuses the positively confirmed adapter without reopening COM.
        w.submit('session_start',simulation=False)
        wait_event(w,'session_state',lambda d:d.get('state')=='CAPTURING')
        assert len(handles)==1
        w.submit('session_finish');wait_event(w,'session_state',lambda d:d.get('state')=='EXPORTED')
        assert handles[0].closed and not w.transport
    finally:shutdown(w)

def test_success_disconnect_option_and_explicit_disconnect(tmp_path,fast_clock):
    w=AcquisitionWorker(tmp_path)
    try:
        for keep in (False,True):
            w.submit('bench_auto_start',simulation=True,scenario='Diesel thirteen sensors',rate=2,parked_consent=True,keep_connected=keep)
            state=finish(w);assert state['disconnected'] is not keep
            if keep:
                w.submit('disconnect');wait_event(w,'connection',lambda d:d['adapter']=='Disconnected');until(lambda:w.transport is None)
                assert w.session.data['state']=='DISCONNECTED'
    finally:shutdown(w)

def test_serial_open_121_classification_before_any_send(monkeypatch):
    import mokka_ecu_lab.transport as module
    def fail(*a,**k):raise OSError(22,'The semaphore timeout period has expired.',None,121)
    monkeypatch.setattr(module.serial,'Serial',fail)
    with pytest.raises(SerialOpenError,match='FAILED_COM_OPEN.*121'):SerialTransport('CONSTRUCTED-COM')

@pytest.mark.parametrize('cause',['remove','suspend','stale_prompt'])
def test_idle_invalidation_closes_without_diagnostic_retries(tmp_path,fast_clock,cause):
    w=AcquisitionWorker(tmp_path)
    try:
        w.submit('bench_auto_start',simulation=True,scenario='Diesel thirteen sensors',rate=2,parked_consent=True)
        state=finish(w);transport=w.transport;last=transport.last_wire_ns
        if cause=='suspend':w.submit('system_suspend')
        else:
            transport.idle_status=lambda:dict(open=cause!='remove',prompt_synchronized=False)
            w.idle_health_checked=time.monotonic()-2
        until(lambda:w.transport is None)
        assert transport.last_wire_ns==last and not w.recorder and not w.polling
    finally:shutdown(w)

def test_long_active_collection_is_not_misclassified_as_idle_suspend(tmp_path,fast_clock):
    w=AcquisitionWorker(tmp_path)
    try:
        w.submit('connect',simulation=True,scenario='Normal idle')
        wait_event(w,'connection',lambda d:d['adapter']!='Disconnected')
        until(lambda:w.polling)
        handle=w.transport
        w.idle_health_checked=time.monotonic()-100
        w.check_idle_connection()
        assert w.transport is handle and time.monotonic()-w.idle_health_checked<1
        w.set_polling(False,'Constructed normal stop')
        w.check_idle_connection()
        assert w.transport is handle
        w.idle_health_checked=time.monotonic()-100
        w.check_idle_connection()
        assert w.transport is None and w.requires_reconnect
    finally:shutdown(w)
