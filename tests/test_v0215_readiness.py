"""Invented bit patterns; offline readiness must not authorize LIVE traffic."""
import pytest
from mokka_ecu_lab.analysis.readiness import decode_readiness
from mokka_ecu_lab.protocols import validate_command,UnsafeRequest,LIVE_PIDS,DISCOVERY_PIDS


def test_mil_dtc_mask_and_compression_support_completion_are_independent():
    r=decode_readiness(bytes([0x85,0x19,0x43,0x02]));m={v['name']:v for v in r['monitors']}
    assert r['mil_commanded_on'] and r['emission_related_dtc_count']==5 and r['ignition']=='COMPRESSION'
    assert m['Misfire']['readiness']=='NOT_COMPLETE' and m['NMHC catalyst']['readiness']=='COMPLETE'
    assert m['NOx/SCR aftertreatment']['readiness']=='NOT_COMPLETE' and m['PM filter']['readiness']=='COMPLETE'
    assert m['Boost pressure']['readiness']=='NOT_SUPPORTED' and m['Boost pressure']['complete'] is None
    assert not r['live_admitted'] and r['physical_calibration']=='UNVERIFIED'


def test_ignition_changes_labels_and_unsupported_never_reports_complete():
    spark=decode_readiness(bytes([0,7,2,2]));diesel=decode_readiness(bytes([0,15,2,2]))
    assert any(m['name']=='Heated catalyst' for m in spark['monitors'])
    assert not any(m['name']=='Heated catalyst' for m in diesel['monitors'])
    assert next(m for m in spark['monitors'] if m['name']=='Catalyst')['complete'] is None
    assert decode_readiness(bytes(4))['emission_related_dtc_count']==0


@pytest.mark.parametrize('payload',[b'',bytes(3),bytes(5),bytes([0,128,0,0]),bytes([0,8,4,0]),bytes([0,8,0,16])])
def test_wrong_lengths_and_reserved_bits_are_rejected(payload):
    with pytest.raises(ValueError):decode_readiness(payload)


def test_definition_cannot_change_code_owned_live_policy():
    decode_readiness(bytes([0,8,0,0]))
    assert 1 not in LIVE_PIDS|DISCOVERY_PIDS
    with pytest.raises(UnsafeRequest):validate_command('0101',supported={1},discovery_enabled=True,discovery_supported={1})
