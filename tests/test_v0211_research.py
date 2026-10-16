"""Constructed coverage, censoring and purely offline future-rate arithmetic."""
import base64,csv,io,json,threading
import pytest
from mokka_ecu_lab.analysis.obd import analyze_obd
from mokka_ecu_lab.analysis.quality import field_quality
from mokka_ecu_lab.protocols.isotp import parse_reply
from mokka_ecu_lab.transport.simulator import can_reply
from mokka_ecu_lab.transport import SafeTransport
from mokka_ecu_lab.research.future_benchmark import illustrative_feasibility,LIVE_HIGH_RATE_ENABLED
from test_obd_performance import synthetic_bundle

def test_partial_bitmap_count_is_not_a_feature_disappearance(tmp_path):
    from zipfile import ZipFile
    import hashlib
    source=synthetic_bundle(tmp_path/'whole.zip')
    with ZipFile(source) as z:records=[json.loads(x) for x in z.read('raw-redacted.jsonl').splitlines()]
    records=[r for r in records if r['command'] not in {'0160','0180','01A0'}]
    raw=('\n'.join(json.dumps(r) for r in records)+'\n').encode();partial=tmp_path/'partial.zip'
    with ZipFile(partial,'w') as z:z.writestr('raw-redacted.jsonl',raw);z.writestr('SHA256SUMS.txt',hashlib.sha256(raw).hexdigest()+'  raw-redacted.jsonl\n')
    report=analyze_obd([source,partial]);a,b=[s['inventory'][0] for s in report['sessions']]
    assert b['bitmap_coverage']=='PARTIAL' and b['unread_advertised_pages']==['60']
    assert a['declared_count']>b['declared_count'] and not report['inventory_comparisons'][0]['complete_coverage_pair']
    assert 'not evidence' in b['inventory_scope_note']

def test_map_byte_ceiling_and_recorded_field_quality_are_separate_from_health():
    rows=[];records=[]
    for i,(command,data) in enumerate([('014F',bytes(4)),('010B',b'\xff'),('010B',b'\xfd')]):
        record=dict(id=f'constructed-{i}',command=command,mode='SIMULATED',source_kind='SIMULATED',context_id='scope')
        parsed=parse_reply((can_reply('7E8',int(command[2:],16),data)+'\r>').encode(),int(command[2:],16),command);records.append((record,parsed))
        if i:rows.append(dict(transaction_id=record['id'],sensor_id='map',monotonic_ns=i*1000000000,value=data[0],unit='kPa',ecu='7E8',source_mode='SIMULATED',source_kind='SIMULATED'))
    buf=io.StringIO();writer=csv.DictWriter(buf,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    q=field_quality({'measurements.csv':buf.getvalue().encode()},records)[0]
    assert q['map_byte_ceiling_samples']==1 and q['map_numeric_samples']==2 and q['map_encoding_max_kpa']==255
    assert q['fields'][0]['samples']==2 and q['fields'][0]['physical_accuracy']=='UNVERIFIED'

def test_future_arithmetic_never_enables_live_above_four():
    model=illustrative_feasibility(110)
    assert not LIVE_HIGH_RATE_ENABLED and not model['live_enabled'] and model['transmissions']==0
    assert [r['illustrative_requested_rate'] for r in model['rows']]==[4,5,6]
    class Guard(SafeTransport):
        def _exchange(self,*args):raise AssertionError('No higher-rate wire call permitted')
    for rate in (5,6,20):
        t=Guard();t.supported={12};t.rate=rate
        with pytest.raises(ValueError,match='4 Hz'):t.exchange('010C',threading.Event())

@pytest.mark.parametrize('response',[0,-1,float('nan'),float('inf'),True])
def test_synthetic_feasibility_rejects_unbounded_assumptions(response):
    with pytest.raises(ValueError):illustrative_feasibility(response)
