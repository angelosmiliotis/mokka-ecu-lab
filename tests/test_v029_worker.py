"""Synthetic serialized workflow/benchmark integration; no physical adapter."""
import json,time
import pytest
from mokka_ecu_lab.adapter import AcquisitionWorker
from mokka_ecu_lab.protocols import EXTENSION_PIDS
from mokka_ecu_lab.analysis.obd import analyze_obd
from mokka_ecu_lab.logging import list_sessions
from mokka_ecu_lab.transport.simulator import Simulator
from test_session import connect,start,wait_state
from test_negative_responses import shutdown,wait_event
from test_discovery import fast_clock


def until(predicate,timeout=10):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        if predicate():return
        time.sleep(.02)
    raise AssertionError('Synthetic worker state deadline')


def test_expanded_single_session_36_gated_sensors_no_unknown_queries(tmp_path,fast_clock):
    worker=AcquisitionWorker(tmp_path)
    try:
        assert connect(worker,'Standard expanded research')['ecu']=='18DAF110'
        first=start(worker);sid=first['session_id']
        ready=wait_state(worker,lambda d:d.get('receipt',{}).get('dpf',{}).get('state')=='READY' and len(d['receipt']['observed'])==36 and all(v['positive_samples']>=2 for v in d['receipt']['observed'].values()),20)
        assert worker.capture_raw_pids=={0x7A} and EXTENSION_PIDS<=set(worker.capture_weights)
        assert all(worker.capture_weights[p]==4 for p in (0x7A,0x0B,0x10,0x0D)) and worker.capture_weights[0x0C]==3
        assert worker.submit('benchmark_start',parked_consent=True) is False
        worker.submit('session_finish');final=wait_state(worker,lambda d:d['state']=='EXPORTED')
        assert final['session_id']==sid and final['obd_report_path'] and not worker.transport
        report=analyze_obd([final['bundle_path']]);g=report['sessions'][0]['inventory'][0]
        assert g['declared_count']==38 and g['outside_legacy_scope_count']==25
        assert g['implemented_declared_count']==36
        assert all(r['response_observed']==0 for r in g['rows'] if r['pid'] in {'01','A1','9D'})
        assert ready['receipt']['adaptive_pacing']['maximum_live_rate']==4
        assert len(ready['receipt']['observed']['8C']['fields'])==8
        assert len(ready['receipt']['observed']['71']['fields'])==6
        assert len(ready['receipt']['observed']['8F']['fields'])==6
    finally:shutdown(worker)


@pytest.mark.parametrize('failure',[False,True])
def test_stationary_existing_positive_scope_owns_recording_and_aborts(tmp_path,fast_clock,monkeypatch,failure):
    import mokka_ecu_lab.adapter as module
    original=module.StationaryBenchmark
    def short(*a,**k):
        b=original(*a,**k);b.maximum_requests=3;return b
    monkeypatch.setattr(module,'StationaryBenchmark',short)
    worker=AcquisitionWorker(tmp_path)
    try:
        worker.submit('connect',simulation=True,scenario='Diesel thirteen sensors',port='',baud=115200)
        until(lambda:worker.can_protocol)
        worker.submit('discover',ecu='7E8');until(lambda:worker.discovery_completed)
        worker.submit('monitor_discovery',ecu='7E8')
        until(lambda:all(worker.discovery_observations.get(('7E8',p),{}).get('fields') for p in (12,11,16)))
        worker.submit('stop');until(lambda:not worker.polling)
        if failure:
            exchange=Simulator._exchange
            def injected(self,command,stop,timeout):
                if worker.benchmark and worker.benchmark.active:return b'7E8 03 7F 01 22\r>'
                return exchange(self,command,stop,timeout)
            monkeypatch.setattr(Simulator,'_exchange',injected)
        assert worker.submit('benchmark_start',parked_consent=True,rate=2)
        result=wait_event(worker,'benchmark',lambda v:not v.get('active') and v.get('bundle_path'),timeout=15)
        assert result['requests']==(1 if failure else 3) and result['disconnected'] and not worker.transport
        assert result['pids']==['0C','0B','10'] and result['rate']==2 and not result['higher_rate_authorized']
        assert len(list_sessions(tmp_path))==1 and list_sessions(tmp_path)[0]['ended']
        if failure:assert 'ECU_NRC' in result['reason']
        report=analyze_obd([result['bundle_path']]);p=report['sessions'][0]['performance'][0]
        assert p['transmitted_requests']==result['requests']
    finally:shutdown(worker)
