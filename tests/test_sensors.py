import json
import pytest
from dataclasses import replace
from mokka_ecu_lab.sensors import load_registry, convert
from mokka_ecu_lab.analysis import interpretations, compare, RegenerationHistory

@pytest.mark.parametrize('pid,payload,value', [(12,'0C30',780), (5,'5E',54), (13,'32',50), (4,'FF',100), (11,'65',101), (15,'43',27), (16,'01E0',4.8), (66,'3714',14.1), (70,'3F',23), (92,'6E',70)])
def test_formulas(pid, payload, value): assert load_registry()[pid].decode(bytes.fromhex(payload)) == pytest.approx(value)

def test_validity_schema_and_conversions(tmp_path):
    rpm = load_registry()[12]
    with pytest.raises(ValueError): rpm.decode(b'\x01')
    with pytest.raises(ValueError): replace(rpm, scale=float('nan')).decode(b'\x01\x00')
    with pytest.raises(ValueError): replace(rpm, maximum=1).decode(b'\x01\x00')
    assert convert(0,'°C',True) == (32,'°F')
    assert convert(100,'kPa',True) == (1,'bar abs')
    assert convert(10,'g/s',True) == (36,'kg/h')
    assert convert(100,'km/h',True)[0] == pytest.approx(62.1371192)
    d = rpm.metadata.copy(); d['verification'] = 'GUESS_VERIFIED'
    path = tmp_path / 'invalid.json'; path.write_text(json.dumps([d]))
    with pytest.raises(ValueError): load_registry(path)

def test_offline_analysis_and_regen():
    variants = interpretations(b'\x04\x80', .01)
    assert variants[0]['candidate'] == pytest.approx(11.52)
    assert variants[2]['integer'] == 32772
    assert variants[3]['integer'] == -32764
    assert compare([1.,2.],[1.,3.])['mae'] == .5
    with pytest.raises(ValueError): compare([float('inf')],[1.])
    history = RegenerationHistory()
    with pytest.raises(ValueError): history.observe('now', True, 100, 'EXPERIMENTAL')
    history.observe('t1',True,100,'VEHICLE_VERIFIED'); history.gap('t1','t2')
    history.observe('t2',False,200,'VEHICLE_VERIFIED'); assert not history.events
    history.observe('t3',True,201,'VEHICLE_VERIFIED'); history.observe('t4',False,202,'VEHICLE_VERIFIED')
    assert len(history.events) == 1
