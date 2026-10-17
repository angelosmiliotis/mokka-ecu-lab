"""Newly constructed virtual schedules; no private capture or hardware input."""
import ast
import inspect
import json
import math
import threading
import pytest
from mokka_ecu_lab.research import future_benchmark as research
from mokka_ecu_lab.research.future_benchmark import (
    SyntheticBenchmark,SyntheticFault,FAULTS,BEFORE_SEND_FAULTS,FIXED_PIDS,
    engineering_brief)


def finish(model):
    for _ in range(500):
        model.advance()
        if not model.active:return model.snapshot()
    raise AssertionError('Constructed model must be bounded')


@pytest.mark.parametrize('rate',range(1,7))
def test_all_rates_share_preflight_measurement_accounting_without_any_wire(rate):
    result=finish(SyntheticBenchmark(rate))
    assert result['state']=='COMPLETED'
    assert result['actual_transmissions']==0 and not result['live_enabled']
    assert not result['hardware_capacity_verified']
    assert result['modeled_preflight_requests']==12
    assert result['modeled_measurement_requests']==60*rate
    assert result['modeled_total_requests']==12+60*rate
    assert result['virtual_elapsed_seconds']==60
    assert result['virtual_remaining_seconds']==0
    events=result['events'];gap=math.ceil(1_000_000_000/rate)
    assert result['minimum_required_gap_ns']==gap
    assert result['modeled_spacing_violations']==result['modeled_response_overlap']==0
    assert all(b['send_ns']-a['send_ns']>=gap and b['send_ns']>=a['response_end_ns'] for a,b in zip(events,events[1:]))
    assert events[12]['send_ns']-events[11]['send_ns']>=gap
    assert [e['command'] for e in events]==[FIXED_PIDS[i%4] for i in range(len(events))]
    assert events[-1]['response_end_ns']<=result['phase_boundaries']['measurement_end_ns']


@pytest.mark.parametrize('kind',FAULTS)
@pytest.mark.parametrize('fault_at',[0,7,12,33])
def test_every_abort_retains_partial_constructed_evidence_and_never_retries(kind,fault_at):
    model=SyntheticBenchmark(5,fault=SyntheticFault(fault_at,kind))
    result=finish(model)
    assert result['state']=='ABORTED' and kind in result['reason']
    assert result['modeled_total_requests']==fault_at+(kind not in BEFORE_SEND_FAULTS)
    assert result['actual_transmissions']==0
    previous=model.snapshot()
    for _ in range(3):model.advance();model.stop()
    assert model.snapshot()==previous
    assert result['modeled_spacing_violations']==result['modeled_response_overlap']==0


def test_immediate_stop_and_slow_response_are_explicit_partial_outcomes():
    model=SyntheticBenchmark(6);model.stop()
    assert model.snapshot()['modeled_total_requests']==0 and model.state=='ABORTED'
    slow=SyntheticBenchmark(6,response_ms=250);result=finish(slow)
    assert result['state']=='ABORTED' and result['categories']=={'EXCESSIVE_LATENCY':1}
    assert result['modeled_measurement_requests']==0
    model=SyntheticBenchmark(6,response_ms=210)
    result=finish(model)
    assert result['modeled_measurement_requests']<360
    assert result['modeled_response_overlap']==0 and result['virtual_elapsed_seconds']==60
    assert result['state']=='ABORTED' and result['categories']['TIMEOUT']==1


@pytest.mark.parametrize('kwargs',[
    {'rate':0},{'rate':7},{'rate':True},{'rate':4.5},
    {'response_ms':0},{'response_ms':float('inf')},{'response_ms':float('nan')},
    {'response_ms':True},{'response_ms':1001},
    {'duration_seconds':0},{'duration_seconds':61},{'duration_seconds':1.5},
    {'duration_seconds':True},{'fault':{'kind':'STOP'}},
])
def test_model_rejects_unbounded_or_ambiguous_assumptions(kwargs):
    with pytest.raises(ValueError):SyntheticBenchmark(**kwargs)


def test_fault_input_bounds():
    for index in (-1,401,1.2,True):
        with pytest.raises(ValueError):SyntheticFault(index,'STOP')
    with pytest.raises(ValueError):SyntheticFault(1,'RETRY')


def test_short_measurements_and_returned_snapshots_cannot_mutate_the_model():
    model=SyntheticBenchmark(5,duration_seconds=2);first=model.advance()
    first['events'][0]['category']='NRC';first['events'].clear()
    assert model.snapshot()['events'][0]['category']=='OK'
    result=finish(model)
    assert result['modeled_measurement_requests']==10 and result['modeled_total_requests']==22


def test_no_transport_import_or_policy_unlock_and_normal_guard_still_denies_higher_rates():
    assert research.LIVE_HIGH_RATE_ENABLED is False
    tree=ast.parse(inspect.getsource(research))
    imports=[node.module for node in ast.walk(tree) if isinstance(node,ast.ImportFrom)]
    imports += [alias.name for node in ast.walk(tree) if isinstance(node,ast.Import) for alias in node.names]
    assert imports==['dataclasses','math']
    from mokka_ecu_lab.transport import SafeTransport
    class NoWire(SafeTransport):
        def _exchange(self,*args):raise AssertionError('No higher-rate write may occur')
    for rate in (5,6):
        transport=NoWire();transport.supported={12};transport.rate=rate
        with pytest.raises(ValueError,match='4 Hz'):transport.exchange('010C',threading.Event())


def test_proposal_is_specific_locked_and_not_a_hardware_result():
    brief=engineering_brief();step=brief['proposed_first_step']
    assert brief['live_state']=='LOCKED' and not brief['live_enabled']
    assert step['rate_req_s']==5 and step['measurement_seconds']==60
    assert step['minimum_all_send_gap_ms']==200
    assert step['maximum_total_requests']==312
    assert step['fixed_mode01_pids']==list(FIXED_PIDS)
    assert brief['normal_live_ceiling_req_s']==4
    assert not step['automatic_ramp'] and not step['automatic_retry']
    brief['proposed_first_step']['rate_req_s']=99
    assert engineering_brief()['proposed_first_step']['rate_req_s']==5


def test_research_ui_visits_and_exports_never_obtain_worker_or_replace_files(qt_app,tmp_path):
    from mokka_ecu_lab.ui.higher_rate import HigherRatePanel
    page=HigherRatePanel();page.show();qt_app.processEvents()
    assert not page.live_start.isEnabled() and page.model is None
    assert 'LOCKED' in page.lock_state.text()
    assert [page.rate.itemText(i) for i in range(page.rate.count())]==list('123456')
    page.start.click();page.advance_model();page.stop.click()
    assert page.snapshot['state']=='ABORTED' and page.snapshot['actual_transmissions']==0
    assert not page.timer.isActive() and page.start.isEnabled()
    destination=tmp_path/'new-proposal.json';page.export_brief(destination)
    data=json.loads(destination.read_text('utf-8'))
    assert data['live_state']=='LOCKED' and data['last_constructed_model']['state']=='ABORTED'
    before=destination.read_bytes()
    with pytest.raises(FileExistsError):page.export_brief(destination)
    assert destination.read_bytes()==before
    assert not page.live_start.isEnabled()
    page.start.click();page.close();assert not page.timer.isActive() and page.model.state=='ABORTED'
