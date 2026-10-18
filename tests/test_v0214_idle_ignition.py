"""Constructed timing/error context only; no vehicle bytes or COM access."""
import json
import pytest
from mokka_ecu_lab.idle_evidence import SilentIdle
from mokka_ecu_lab.ignition import IgnitionContext
from mokka_ecu_lab.library import digest,run_facts

def test_explicit_sixty_second_idle_sidecar_preserves_original(tmp_path):
    original=tmp_path/'constructed.zip';original.write_bytes(b'constructed immutable bundle');before=digest(original)
    idle=SilentIdle('CONSTRUCTED',original,'SIMULATED',7,100.);idle.request(100.)
    for n in range(1,61):idle.observe(100.+n,7,True,True)
    assert idle.data['state']=='VERIFIED' and idle.data['idle_requests']==0
    receipt=idle.save(tmp_path/'sidecars');assert json.loads(open(receipt,encoding='utf-8').read())['verification_elapsed_seconds']==60
    assert idle.save(tmp_path/'sidecars')==receipt and digest(original)==before

@pytest.mark.parametrize('fault',['send','health','identity','suspend','clock'])
def test_silent_idle_fails_closed_without_changing_original(tmp_path,fault):
    p=tmp_path/'constructed.zip';p.write_bytes(b'constructed original');idle=SilentIdle('CONSTRUCTED',p,'SIMULATED',7,100.);idle.request(100.)
    idle.observe(99. if fault=='clock' else 116. if fault=='suspend' else 101.,8 if fault=='send' else 7,fault!='health',fault!='identity')
    assert idle.data['state']=='INTERRUPTED' and idle.save(tmp_path/'private')

def test_no_sidecar_without_explicit_request_and_modified_source_blocked(tmp_path):
    p=tmp_path/'constructed.zip';p.write_bytes(b'constructed original');idle=SilentIdle('CONSTRUCTED',p,'SIMULATED',7,100.)
    idle.end('manual Disconnect');assert idle.save(tmp_path/'unused') is None and not (tmp_path/'unused').exists()
    with pytest.raises(ValueError):idle.request(101.)
    idle=SilentIdle('CONSTRUCTED',p,'SIMULATED',7,100.);idle.request(100.);idle.end('Disconnect');p.write_bytes(b'changed')
    with pytest.raises(ValueError):idle.save(tmp_path/'private')

@pytest.mark.parametrize('context,ecu,age,positive,expected',[('ONE','SYNTHETIC',5,True,True),('OTHER','SYNTHETIC',5,True,False),('ONE','DIFFERENT',5,True,False),('ONE','SYNTHETIC',31,True,False),('ONE','SYNTHETIC',5,False,False)])
def test_ignition_hint_requires_recent_same_context_rpm_and_three_nrc(context,ecu,age,positive,expected):
    model=IgnitionContext();model.observe(dict(status='OK',context_id='ONE',monotonic_ns=1_000_000_000),[dict(sensor_id='rpm',ecu='SYNTHETIC',value=800 if positive else 0)])
    for _ in range(3):model.observe(dict(status='ECU_NEGATIVE_RESPONSE',context_id=context,monotonic_ns=(1+age)*1_000_000_000,negative_responses=[dict(ecu=ecu,nrc='22')]),[])
    assert ('Possible engine/ignition off' in model.explanation((1+age)*1_000_000_000))==expected
    assert 'Conditions Not Correct' in model.explanation((1+age)*1_000_000_000)
    model.observe(dict(status='OK',context_id=context,monotonic_ns=99_000_000_000),[]);assert not model.rejections

def test_capture_abort_and_export_completion_are_distinct():
    assert run_facts(dict(session_coordinator=dict(state='FINALIZING',capture_outcome='ABORTED')))['outcome']=='MEASUREMENT_FAILED'
