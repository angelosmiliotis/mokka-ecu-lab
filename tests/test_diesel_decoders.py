import pytest
from mokka_ecu_lab.sensors.diesel import STANDARD_DIESEL, RESEARCH_CANDIDATES
from mokka_ecu_lab.transport.simulator import DIESEL_PAYLOADS


def decoded(pid,hex_payload):
    return {f['id']:f for f in STANDARD_DIESEL[pid].decode(bytes.fromhex(hex_payload))}


@pytest.mark.parametrize('pid',STANDARD_DIESEL)
def test_complete_documented_layout_with_evidence_and_unique_fields(pid):
    definition=STANDARD_DIESEL[pid]
    fields=definition.decode(DIESEL_PAYLOADS[pid])
    assert len({f['sensor_id'] for f in fields})==len(fields)
    assert definition.metadata()['vehicle_verification']=='UNVERIFIED'
    assert definition.metadata()['source_table'].startswith('B')
    assert all(f['verification']=='STANDARD_DOCUMENTED' and f['formula'] and f['validity'] for f in fields)


@pytest.mark.parametrize('pid',STANDARD_DIESEL)
@pytest.mark.parametrize('delta',[-1,1])
def test_incomplete_or_different_revision_never_fabricates_fields(pid,delta):
    p=DIESEL_PAYLOADS[pid]
    with pytest.raises(ValueError,match='layout.*unverified'):
        STANDARD_DIESEL[pid].decode(p[:-1] if delta==-1 else p+b'\x00')


def test_regeneration_supported_is_not_regeneration_active():
    f=decoded(0x8B,'01 00 00 00 00 00 00')
    assert f['regeneration']['value']==0 and f['regeneration']['display']=='Not in progress'
    assert f['regeneration_type']['value'] is None
    f=decoded(0x8B,'00 03 FF FF FF FF FF')
    assert all(x['value'] is None and x['state']=='UNSUPPORTED_FIELD' for x in f.values())
    f=decoded(0x8B,'73 03 80 01 2C 01 5E')
    assert f['regeneration']['value']==1 and f['regeneration_type']['display']=='Active'
    assert f['normalized_trigger']['value']==pytest.approx(128*100/255)
    assert f['average_time']['value']==300 and f['average_time']['unit']=='min'
    assert f['average_distance']['value']==350 and f['average_distance']['unit']=='km'


def test_adblue_requires_specific_support_bit_and_f_byte():
    f=decoded(0x85,'04 FF FF FF FF CC FF FF FF FF')
    assert f['tank_level']['value']==80
    assert f['warning_time']['value'] is None and f['consumption']['value'] is None
    f=decoded(0x85,'03 00 C8 01 90 FF 00 00 00 00')
    assert f['tank_level']['value'] is None
    assert f['consumption']['value']==1 and f['demand']['value']==2
    assert decoded(0x85,'08 00 00 00 00 00 FF FF FF FF')['warning_time']['value']==4294967295


@pytest.mark.parametrize('pid',[0x7A,0x7B])
def test_dpf_pressure_signed_delta_unsigned_absolute_and_no_blockage_percentage(pid):
    f=decoded(pid,'07 FF 9C 27 10 FF FF')
    assert [x['value'] for x in f.values()]==[-1,100,655.35]
    assert all(x['unit']=='kPa' for x in f.values())
    assert decoded(pid,'00 FF FF FF FF FF FF')['delta_pressure']['value'] is None


@pytest.mark.parametrize('pid',[0x78,0x79,0x7C])
def test_temperature_channels_and_support_mask(pid):
    f=list(decoded(pid,'05 00 00 FF FF 17 70 00 00').values())
    assert f[0]['value']==-40 and f[2]['value']==560
    assert f[1]['value'] is None and f[3]['value'] is None


def test_nox_pm_units_and_cumulative_time_are_not_soot_mass_or_time_since_regen():
    assert list(decoded(0x83,'01 00 96 00 00 00 00 00 00').values())[0]['value']==150
    pm=list(decoded(0x86,'01 00 50 00 00').values())[0]
    assert pm['value']==1 and pm['unit']=='mg/m³'
    f=decoded(0x7F,'07 00 01 51 80 00 00 0E 10 00 00 00 0A')
    assert [x['value'] for x in f.values()]==[86400,3600,10]


def test_scr_inducement_current_and_history_are_separate():
    f=decoded(0x88,'81 12 48 00 01 00 02 00 03 00 04 00 05')
    assert f['active']['value']==1 and f['low_reagent']['value']==1
    values=list(f.values())[5:]
    assert [x['value'] for x in values[:8]]==[0,1,0,0,1,0,0,0]
    with pytest.raises(ValueError): decoded(0x88,'01 00 00')
    with pytest.raises(ValueError): decoded(0x88,'10 00 00')


def test_oem_candidates_have_no_decoder_or_vehicle_claim():
    assert {x['request'] for x in RESEARCH_CANDIDATES}=={'22D525','22D526','22D52F','22D532'}
    assert all(not x['live_enabled'] and x['verification']=='RESEARCH_ONLY' for x in RESEARCH_CANDIDATES)
