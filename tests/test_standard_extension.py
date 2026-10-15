"""Independent constructed endpoints and strict framing; no vehicle fixtures."""
import threading
import pytest
from mokka_ecu_lab.protocols import EXTENSION_PIDS,validate_command,UnsafeRequest
from mokka_ecu_lab.protocols.isotp import parse_reply
from mokka_ecu_lab.sensors.extended import EXTENDED_STANDARD,basic_range
from mokka_ecu_lab.sensors import load_registry
from mokka_ecu_lab.transport.simulator import can_reply


CASES=[(0x11,b'\xff',100,'%',),(0x1F,b'\x02\x01',513,'s'),(0x21,b'\x02\x03',515,'km'),
    (0x23,b'\x01\x02',2580,'kPa gauge'),(0x2C,b'\x00',0,'%'),(0x2D,b'\x00',-100,'%'),
    (0x30,b'\x13',19,'count'),(0x31,b'\x01\x03',259,'km'),(0x33,b'\x4b',75,'kPa abs'),
    (0x3C,b'\x00\x00',-40,'°C'),(0x49,b'\xff',100,'%'),(0x4A,b'\x00',0,'%'),
    (0x4C,b'\xff',100,'%'),(0x4D,b'\x02\x02',514,'min'),(0x4E,b'\x03\x01',769,'min'),(0x5E,b'\x00\x19',1.25,'L/h')]


@pytest.mark.parametrize('pid,payload,value,unit',CASES)
@pytest.mark.parametrize('header',['7E9','18DAF111'])
def test_independent_scalar_formulas_and_both_can_headers(pid,payload,value,unit,header):
    result=parse_reply((can_reply(header,pid,payload)+'\r>').encode(),pid,f'01{pid:02X}')
    assert not result.errors and result.responses[0].header==header
    field=EXTENDED_STANDARD[pid].decode(result.responses[0].data)[0]
    assert field['value']==pytest.approx(value) and field['unit']==unit and field['state']=='AVAILABLE'


@pytest.mark.parametrize('pid',sorted(EXTENSION_PIDS))
def test_exact_layout_scope_negative_and_malformed(pid):
    d=EXTENDED_STANDARD[pid]
    for payload in (bytes(d.length-1),bytes(d.length+1)):
        with pytest.raises(ValueError):d.decode(payload)
    assert validate_command(f'01{pid:02X}',set(),discovery_enabled=True,discovery_supported={pid})==f'01{pid:02X}'
    with pytest.raises(UnsafeRequest):validate_command(f'01{pid:02X}',set(),discovery_enabled=True,discovery_supported=set())
    negative=parse_reply(b'18DAF111 03 7F 01 22\r>',pid,f'01{pid:02X}')
    assert negative.responses[0].negative_code==0x22
    assert parse_reply(b'7E9 04 41 ZZ\r>',pid,f'01{pid:02X}').errors


def test_flags_signed_pm_status_and_no_false_dpf_regeneration():
    fields=EXTENDED_STANDARD[0x8F].decode(bytes.fromhex('03 02 FE 0C 00 00 00'))
    values={f['id']:f for f in fields}
    assert values['bank_1_normalized']['value']==-5
    assert values['bank_1_sensor_regenerating']['value']==1
    assert values['bank_2_normalized']['value'] is None
    assert 'not DPF regeneration' in values['bank_1_sensor_regenerating']['name']
    with pytest.raises(ValueError):EXTENDED_STANDARD[0x8F].decode(bytes.fromhex('03 04 00 01 00 00 00'))
    oxygen=EXTENDED_STANDARD[0x8C].decode(bytes([0x81])+bytes.fromhex('00 64')+bytes(12)+bytes.fromhex('01 00'))
    assert sum(f['state']=='AVAILABLE' for f in oxygen)==2
    assert oxygen[0]['value']==pytest.approx(.1526) and oxygen[7]['value']==pytest.approx(.031232)
    vgt=EXTENDED_STANDARD[0x71].decode(bytes.fromhex('07 20 40 00 00 03'))
    assert vgt[0]['state']=='UNRELIABLE_REPORTED_FAULT' and vgt[0]['value'] is None
    assert next(f for f in vgt if f['id']=='vgt_a_status')['value']==3
    with pytest.raises(ValueError):EXTENDED_STANDARD[0x71].decode(bytes.fromhex('C7 20 40 00 00 01'))


def test_enum_unavailable_and_current_same_ecu_range_configuration():
    assert EXTENDED_STANDARD[0x51].decode(b'\x04')[0]['display']=='Diesel'
    for pid in (0x51,0x1C):
        assert EXTENDED_STANDARD[pid].decode(b'\xff')[0]['value'] is None
    registry=load_registry();ranges={0x4F:bytes([0,0,0,17]),0x50:bytes([32,0,0,0])}
    assert basic_range(registry[0x0B],b'\x40',ranges)==pytest.approx(64*170/255)
    assert basic_range(registry[0x10],bytes.fromhex('1F 40'),ranges)==pytest.approx(8000*320/65535)
    assert basic_range(registry[0x0B],b'\x40',{})==64
    with pytest.raises(ValueError):basic_range(registry[0x0B],b'\x40',{},advertised={0x4F})
    with pytest.raises(ValueError):EXTENDED_STANDARD[0x50].decode(bytes([32,1,0,0]))
    assert set(EXTENDED_STANDARD)==EXTENSION_PIDS and len(EXTENSION_PIDS)==23
    for command in ('0101','019D','0159','015A','22D525','22D526','22D52F','22D532'):
        with pytest.raises(UnsafeRequest):validate_command(command,{1,0x9D,0x59,0x5A},discovery_enabled=True,discovery_supported=set(range(256)))
