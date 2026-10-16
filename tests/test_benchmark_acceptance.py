"""Synthetic acceptance for visible action, unknown layouts and source boundaries."""
import json,time
import pytest
from test_ui_freshness import window
from test_discovery import fast_clock
from test_negative_responses import shutdown,wait_event
from test_v029_worker import until
from mokka_ecu_lab.adapter import AcquisitionWorker
from mokka_ecu_lab.transport.simulator import Simulator
from mokka_ecu_lab.sensors.extended import EXTENDED_STANDARD


def test_visible_sidebar_visit_never_submits_and_start_is_complete(window,monkeypatch):
    calls=[];window.session_panel.advanced.setChecked(False)
    with monkeypatch.context() as patch:
        patch.setattr(window.worker,'submit',lambda *a,**k:calls.append((a,k)))
        window.sidebar.buttons[8].click();window.drain()
        assert calls==[] and window.tabs.currentIndex()==8 and not window.session_panel.advanced.isChecked()
        p=window.benchmark_panel;assert [p.rate.itemText(i) for i in range(p.rate.count())]==['1','2','3','4']
        window.source.setCurrentIndex(1);window.port.setCurrentText('SYNTHETIC-COM')
        p.start.click();assert calls[-1][0]==('bench_auto_start',)
        assert calls[-1][1]['simulation'] is False and calls[-1][1]['port']=='SYNTHETIC-COM' and calls[-1][1]['parked_consent']
        assert not p.start.isEnabled() and p.stop.isEnabled()
        p.reject('Synthetic conflict');window.drain();assert 'Synthetic conflict' in p.state.text()


@pytest.mark.parametrize('length',[0,14,15,16,18])
def test_018c_alternate_length_stays_numeric_unverified(length):
    payload=bytes((i*17+3)%256 for i in range(length)) # fabricated; never a private captured frame
    with pytest.raises(ValueError,match='exactly 17'):EXTENDED_STANDARD[0x8C].decode(payload)


def test_live_source_with_explicit_synthetic_transport_does_not_switch_source(tmp_path,fast_clock,monkeypatch):
    import mokka_ecu_lab.adapter as module
    monkeypatch.setattr(module,'SerialTransport',lambda *a,**k:Simulator('Diesel thirteen sensors'))
    w=AcquisitionWorker(tmp_path)
    try:
        w.submit('bench_auto_start',simulation=False,port='CONSTRUCTED-NO-COM',rate=3,parked_consent=True)
        until(lambda:w.benchmark is not None and w.benchmark.requests>=4)
        assert w.benchmark.mode.startswith('LIVE') and w.port=='CONSTRUCTED-NO-COM'
        w.submit('bench_auto_stop');result=wait_event(w,'benchmark',lambda d:d.get('exported'))
        assert result['mode'].startswith('LIVE') and result['source_kind']=='ECU_READING' and not result['completed']
        assert result['requests']<240 and result['disconnected']
    finally:shutdown(w)


@pytest.mark.parametrize('stage',['CONNECTING','DISCOVERY','VERIFYING_PRETEST'])
def test_stop_at_preflight_stage_preserves_available_originals(tmp_path,fast_clock,monkeypatch,stage):
    import mokka_ecu_lab.adapter.benchmark as module
    original=module.BenchmarkWorkflow.bench_emit
    def emit(self,phase=None,reason=None):
        original(self,phase,reason)
        if self.benchmark.phase==stage:self.stop_io.set()
    monkeypatch.setattr(module.BenchmarkWorkflow,'bench_emit',emit)
    w=AcquisitionWorker(tmp_path)
    try:
        w.submit('bench_auto_start',simulation=True,scenario='Diesel thirteen sensors',port='',rate=2,parked_consent=True)
        result=wait_event(w,'benchmark',lambda d:d.get('state')=='ABORTED',timeout=12)
        assert result['disconnected'] and not result['completed'] and result['requests']==0
        assert result.get('bundle_path') or result.get('retry_export')
    finally:shutdown(w)


def test_failed_export_has_explicit_offline_retry_and_preserves_journal(tmp_path,fast_clock,monkeypatch):
    import hashlib
    import mokka_ecu_lab.adapter.benchmark as module
    original=module.export_closed_session
    def fail(*a,**k):raise OSError('Constructed export failure')
    monkeypatch.setattr(module,'export_closed_session',fail)
    w=AcquisitionWorker(tmp_path)
    try:
        w.submit('bench_auto_start',simulation=True,scenario='Diesel thirteen sensors',port='',rate=2,parked_consent=True)
        until(lambda:w.benchmark is not None and w.benchmark.requests>=4)
        w.submit('bench_auto_stop');state=wait_event(w,'benchmark',lambda d:d.get('retry_export'))
        sid=state['session_id'];path=tmp_path/(sid+'.jsonl');sha=hashlib.sha256(path.read_bytes()).hexdigest()
        assert state['disconnected'] and not w.transport and not w.recorder
        monkeypatch.setattr(module,'export_closed_session',original)
        w.submit('bench_export_retry',session_id=sid);out=wait_event(w,'benchmark',lambda d:d.get('exported'))
        assert out['session_id']==sid and not out['completed'] and hashlib.sha256(path.read_bytes()).hexdigest()==sha
    finally:shutdown(w)


def test_two_explicit_rates_compare_separately_without_auto_launch(tmp_path,fast_clock):
    from mokka_ecu_lab.analysis.obd import analyze_obd
    w=AcquisitionWorker(tmp_path);bundles=[]
    try:
        for rate in (1,3):
            w.submit('bench_auto_start',simulation=True,scenario='Diesel thirteen sensors',port='',rate=rate,parked_consent=True)
            until(lambda:w.benchmark is not None and w.benchmark.requests>=8)
            w.benchmark.started=time.monotonic()-60
            out=wait_event(w,'benchmark',lambda d:d.get('exported'));bundles.append(out['bundle_path'])
        assert bundles[0]!=bundles[1]
        c=analyze_obd(bundles)['benchmark_comparisons'][0]
        assert c['same_pid_mix'] and c['same_address_source'] and not c['same_requested_rate']
        assert c['next_user_choice']==4 and c['thermal_match'].startswith('UNKNOWN') and w.benchmark is None and w.transport
    finally:shutdown(w)


def test_bad_com_preserves_failed_run_without_source_fallback(tmp_path,monkeypatch):
    import mokka_ecu_lab.adapter as module
    def bad(*a,**k):raise OSError('Constructed port unavailable')
    monkeypatch.setattr(module,'SerialTransport',bad)
    w=AcquisitionWorker(tmp_path)
    try:
        w.submit('bench_auto_start',simulation=False,port='CONSTRUCTED-NO-COM',rate=2,parked_consent=True)
        result=wait_event(w,'benchmark',lambda d:d.get('state')=='ABORTED')
        assert result['mode'].startswith('LIVE') and result['disconnected'] and result['requests']==0
        assert 'port unavailable' in result['reason'] and result.get('bundle_path')
        from mokka_ecu_lab.analysis.obd import analyze_obd
        b=analyze_obd([result['bundle_path']])['sessions'][0]['benchmark']
        assert b and not b['completed'] and b['sent_requests']==0 and 'port unavailable' in b['reason']
    finally:shutdown(w)


def test_preflight_monotonic_deadline_never_starts_measurement(tmp_path,fast_clock,monkeypatch):
    from mokka_ecu_lab.adapter.benchmark import AutoBenchmark
    monkeypatch.setattr(AutoBenchmark,'preflight_seconds',0)
    w=AcquisitionWorker(tmp_path)
    try:
        w.submit('bench_auto_start',simulation=True,port='',rate=2,parked_consent=True)
        result=wait_event(w,'benchmark',lambda d:d.get('state')=='ABORTED')
        assert 'PREFLIGHT_TIMEOUT' in result['reason'] and result['measurement_started_monotonic'] is None
        assert result['requests']==0 and result['disconnected']
    finally:shutdown(w)
