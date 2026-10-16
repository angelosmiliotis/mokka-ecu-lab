"""Entirely constructed benchmark clocks, source boundaries and failure evidence."""
import json,time
import pytest
from mokka_ecu_lab.adapter import AcquisitionWorker
from mokka_ecu_lab.adapter.benchmark import AutoBenchmark,BENCH_PIDS
from mokka_ecu_lab.transport.simulator import Simulator,can_reply
from mokka_ecu_lab.analysis.obd import analyze_obd
from mokka_ecu_lab.research.evidence import read_bundle
from test_discovery import fast_clock
from test_negative_responses import shutdown,wait_event
from test_v029_worker import until


@pytest.mark.parametrize('rate',[1,2,3,4])
def test_virtual_sixty_second_window_counts_all_rates(rate):
    run=AutoBenchmark(rate,100,'SIMULATED');run.begin(110)
    for n in range(60*rate):
        now=110+n/rate
        assert run.due_pid(now)==BENCH_PIDS[n%4]
        run.requests+=1
    assert run.due_pid(170) is None
    assert run.snapshot(170)['elapsed_seconds']==60 and run.maximum_requests==240
    assert run.requests==rate*60 and not run.snapshot(170)['adaptive']


@pytest.mark.parametrize('rate',[0,5,8,float('nan'),float('inf'),True,'4'])
def test_unknown_rates_cannot_create_benchmark(rate):
    with pytest.raises(ValueError):AutoBenchmark(rate,0,'LIVE')


@pytest.mark.parametrize('rate',[1,2,3,4])
def test_last_second_reserves_receive_allowance_without_shortening_timer(rate):
    from types import SimpleNamespace
    from mokka_ecu_lab.adapter.benchmark import BenchmarkWorkflow
    now=time.monotonic();run=AutoBenchmark(rate,now-70,'SIMULATED');run.begin(now-59.5);waits=[]
    stop=SimpleNamespace(is_set=lambda:False,wait=lambda seconds:waits.append(seconds))
    def forbidden(*_):raise AssertionError('No new request can fit receive allowance')
    worker=SimpleNamespace(benchmark=run,stop_io=stop,transport=SimpleNamespace(last_send=now-.1),transaction=forbidden)
    BenchmarkWorkflow.auto_benchmark_tick(worker)
    assert waits and 0<waits[0]<=.05 and run.active and run.requests==0


@pytest.mark.parametrize('rate',[1,2,3,4])
def test_one_click_worker_records_pretest_and_measurement_then_exports(tmp_path,fast_clock,rate):
    w=AcquisitionWorker(tmp_path)
    try:
        assert w.submit('bench_auto_start',simulation=True,scenario='Diesel thirteen sensors',port='',baud=115200,rate=rate,parked_consent=True)
        until(lambda:w.benchmark is not None and w.benchmark.requests>=8,10)
        b=w.benchmark;assert b.started is not None and b.session_id and b.ecu=='7E8'
        assert set(b.pretest)=={'0D','0C','0B','10'} and w.recorder.id==b.session_id
        assert w.submit('session_start',simulation=True) is False
        assert w.submit('bench_auto_start',simulation=True,rate=4,parked_consent=True) is False
        b.started=time.monotonic()-60 # integration cleanup; full real timer checked by native/EXE validation
        out=wait_event(w,'benchmark',lambda v:v.get('exported'),timeout=10)
        assert out['completed'] and not out['disconnected'] and w.transport and out['state']=='CONNECTED_IDLE'
        report=analyze_obd([out['bundle_path']]);b=report['sessions'][0]['benchmark']
        assert b['requested_rate']==rate and b['completed'] and b['sent_requests']>=8 and b['preflight_sent_requests']>0
        assert b['pids']==['010B','010C','010D','0110']
        _,members=read_bundle(out['bundle_path']);assert json.loads(members['session-summary.json'])['stationary_benchmark']['completed']
    finally:shutdown(w)


@pytest.mark.parametrize('problem',['moving','missing','nrc','layout','mismatch','latency','stop','transport'])
def test_measurement_failure_closes_partial_evidence_without_retry(tmp_path,fast_clock,monkeypatch,problem):
    exchange=Simulator._exchange;injected=[]
    w=AcquisitionWorker(tmp_path)
    def fault(self,command,stop,timeout):
        if w.benchmark and w.benchmark.started is not None:
            injected.append(command)
            if problem=='stop':stop.set();return exchange(self,command,stop,timeout)
            if problem=='transport':
                from mokka_ecu_lab.transport import TransportError
                raise TransportError('Constructed lost transport')
            if problem=='moving':return (can_reply('7E8',0x0D,b'\x05')+'\r>').encode()
            if problem=='missing':return b'NO DATA\r>'
            if problem=='nrc':return b'7E8 03 7F 01 22\r>'
            if problem=='layout':return b'7E8 02 41\r>'
            if problem=='mismatch':return (can_reply('7E9',0x0D,b'\x00')+'\r>').encode()
            if problem=='latency':time.sleep(1.01)
        return exchange(self,command,stop,timeout)
    monkeypatch.setattr(Simulator,'_exchange',fault)
    try:
        w.submit('bench_auto_start',simulation=True,scenario='Diesel thirteen sensors',port='',rate=2,parked_consent=True)
        out=wait_event(w,'benchmark',lambda v:v.get('exported'),timeout=15)
        assert not out['completed'] and out['state']=='ABORTED' and out['disconnected']
        assert len(injected)==1 and out['requests']==1 # Injection occurs after the serialized send.
        assert 'capacity' not in out['reason'] or 'not a capacity' in out['reason']
    finally:shutdown(w)


def test_reject_does_not_hijack_existing_session(tmp_path,fast_clock):
    from test_session import connect,start
    w=AcquisitionWorker(tmp_path)
    try:
        connect(w);start(w);sid=w.recorder.id
        assert w.submit('bench_auto_start',simulation=True,rate=2,parked_consent=True) is False
        assert w.recorder.id==sid and w.session.active
        w.submit('session_finish');wait_event(w,'session_state',lambda d:d['state']=='EXPORTED')
    finally:shutdown(w)


@pytest.mark.parametrize('scenario',['Multiple ECUs','Unknown support page'])
def test_preflight_bad_scope_is_bounded_and_private(tmp_path,fast_clock,scenario):
    w=AcquisitionWorker(tmp_path)
    try:
        w.submit('bench_auto_start',simulation=True,scenario=scenario,port='',rate=2,parked_consent=True)
        # Some constructed scenarios are valid; explicitly stop if pretest reaches RUNNING.
        state=wait_event(w,'benchmark',lambda d:d.get('state') in {'RUNNING_60S','ABORTED'},timeout=10)
        if state.get('active'):w.submit('bench_auto_stop');state=wait_event(w,'benchmark',lambda d:d.get('exported'))
        assert state['disconnected'] and not w.transport
    finally:shutdown(w)
