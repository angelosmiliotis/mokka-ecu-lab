import csv
import hashlib
import io
import zipfile
import pytest
from mokka_ecu_lab.analysis.trends import recorded_trends,load_trends


def row(sensor='speed',value=20,ns=10**9,ecu='7E8',mode='SIMULATED',unit='km/h'):
    return dict(sensor_id=sensor,value=str(value),monotonic_ns=str(ns),ecu=ecu,
                source_mode=mode,source_kind='SIMULATED' if mode=='SIMULATED' else 'ECU_READING',unit=unit)


def test_groups_never_mix_ecu_or_source_and_no_simultaneous_pairs_are_invented():
    report=recorded_trends([row(),row(ns=3*10**9,value=30),row(ecu='7E9',value=90),
                           row(mode='LIVE · hardware unverified',value=40),
                           row('rpm',800,2*10**9,unit='rpm')])
    assert len(report['groups'])==3
    group=next(g for g in report['groups'] if g['ecu']=='7E8' and g['mode']=='SIMULATED')
    assert group['series']['speed']==[(0,20),(2,30)]
    assert group['series']['rpm']==[(1,800)]
    assert 'Independent sampling' in report['limitations']
    assert next(s for s in group['summary'] if s['sensor_id']=='rpm')['note']=='One sample; no trend'


def test_static_warning_counter_and_quantized_tank_are_not_fault_or_consumption():
    rows=[row('sae_85_warning_time',100,n*10**9,unit='s') for n in (1,2,3)]
    rows += [row('sae_85_tank_level',v,n*10**9,unit='%') for n,v in ((1,80),(2,80),(3,79))]
    rows += [row('sae_83_bank_1_sensor_1',50,2*10**9,unit='ppm')]
    group=recorded_trends(rows)['groups'][0]
    counter=next(s for s in group['summary'] if s['sensor_id']=='sae_85_warning_time')
    assert counter['static'] and 'cannot establish a current SCR' in counter['note']
    tank=next(s for s in group['summary'] if s['sensor_id']=='sae_85_tank_level')
    assert tank['distinct_values']==2 and 'not measured fluid consumption' in tank['note']


def test_invalid_values_units_and_missing_sources_stay_explicit():
    report=recorded_trends([row(value='NaN'),row(unit='mph'),row(ns=-1),
                           dict(sensor_id='speed',value='1',monotonic_ns='1',unit='km/h')])
    assert report['ignored_invalid_rows']==3
    group=report['groups'][0]
    assert group['ecu']=='UNKNOWN ECU' and group['mode']=='UNKNOWN MODE'


def test_local_bundle_csv_checksum_and_original_preservation(tmp_path):
    buf=io.StringIO(); writer=csv.DictWriter(buf,fieldnames=list(row())); writer.writeheader(); writer.writerow(row())
    payload=buf.getvalue().encode(); path=tmp_path/'synthetic.zip'
    with zipfile.ZipFile(path,'w') as z:
        z.writestr('measurements.csv',payload)
        z.writestr('SHA256SUMS.txt',hashlib.sha256(payload).hexdigest()+'  measurements.csv\n')
        z.writestr('../ignored.txt','No extraction')
    original=path.read_bytes()
    assert load_trends(path)['groups'][0]['summary'][0]['samples']==1
    assert path.read_bytes()==original and not (tmp_path.parent/'ignored.txt').exists()
    with zipfile.ZipFile(tmp_path/'bad.zip','w') as z:
        z.writestr('measurements.csv',payload); z.writestr('SHA256SUMS.txt','0'*64+'  measurements.csv\n')
    with pytest.raises(ValueError,match='checksum'): load_trends(tmp_path/'bad.zip')


def test_preview_bounds_and_empty_data(monkeypatch):
    monkeypatch.setattr('mokka_ecu_lab.analysis.trends.MAX_ROWS',2)
    with pytest.raises(ValueError,match='rows'): recorded_trends([row(),row(),row()])
    assert recorded_trends([])['groups']==[]
