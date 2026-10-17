"""Constructed journals, independent inventory/timing and bounded feedback."""
import base64,hashlib,json
from datetime import datetime,timedelta,timezone
from zipfile import ZipFile
import pytest
from mokka_ecu_lab.analysis.obd import analyze_obd,export_obd_report,symptom
from mokka_ecu_lab.adapter.pacing import AdaptivePacing,StationaryBenchmark
from mokka_ecu_lab.transport.simulator import Simulator,can_reply
from mokka_ecu_lab.protocols import BITMAP_PIDS


def synthetic_bundle(path,*,conflict=False,other_source=False):
    sim=Simulator('Standard expanded research');bits=sim.supported_fixture;records=[]
    def append(pid,payload,ecu='18DAF111',**extra):
        i=len(records);stamp=(datetime(2000,1,1,tzinfo=timezone.utc)+timedelta(seconds=i*.25)).isoformat()
        records.append(dict(id=f'synthetic-{i}',record_type='transaction',command=f'01{pid:02X}',pid=f'{pid:02X}',timestamp=stamp,
            monotonic_ns=1_000_000_000+i*250_000_000,mode='SIMULATED',source_kind='SIMULATED',context_id='constructed-context',
            sent=True,latency_ms=20+i%4,status='OK',raw_b64=base64.b64encode((can_reply(ecu,pid,payload)+'\r>').encode()).decode(),**extra))
    for base in (0,32,64,96,128,160):
        mask=sum(1<<(31-(p-base-1)) for p in bits if base<p<=base+32);append(base,mask.to_bytes(4,'big'))
    append(12,bytes.fromhex('10 00'))
    if conflict:append(0,bytes(4))
    if other_source:
        append(12,bytes.fromhex('12 00'),'7E9');records[-1].update(mode='LIVE · hardware unverified',source_kind='ECU_READING',context_id='other-source')
    data=('\n'.join(json.dumps(r) for r in records)+'\n').encode()
    members={'raw-redacted.jsonl':data};members['SHA256SUMS.txt']=(hashlib.sha256(data).hexdigest()+'  raw-redacted.jsonl\n').encode()
    with ZipFile(path,'w') as z:
        for n,v in members.items():z.writestr(n,v)
    return path


def test_synthetic_38_declared_25_outside_legacy_not_38_observed(tmp_path):
    path=synthetic_bundle(tmp_path/'constructed.zip');digest=hashlib.sha256(path.read_bytes()).digest();report=analyze_obd([path])
    g=report['sessions'][0]['inventory'][0]
    assert g['declared_count']==38 and g['outside_legacy_scope_count']==25 and len(g['bitmap_ledger'])==6
    rows={r['pid']:r for r in g['rows']}
    assert rows['11']['advertised_support']=='SUPPORTED' and rows['11']['response_observed']==0 and rows['11']['decoder_implemented']
    assert rows['01']['facts']==['ADVERTISED SUPPORTED','DOCUMENTED BUT UNIMPLEMENTED']
    assert not rows['A1']['live_allowlisted'] and rows['A1']['response_observed']==0
    assert 'RESPONSE OBSERVED' in rows['0C']['facts'] and rows['0C']['valid_numeric_responses']==1
    p=report['sessions'][0]['performance'][0]
    assert p['transmitted_requests']==7 and p['wire_send_gap_ms']['minimum']==250 and p['hard_four_hz_spacing_violations']==0
    assert p['actual_transmitted_rate_hz']==pytest.approx(7/1.5) # endpoint count bias reported separately
    assert p['interval_rate_hz']==4 and p['latency_ms']['p50']==21
    assert report['passive'] and not report['sends_requests']
    export_obd_report(report,tmp_path/'private.html',[path]);html=(tmp_path/'private.html').read_text(encoding='utf-8')
    assert '<script' not in html and 'not ECU service time' in html
    assert hashlib.sha256(path.read_bytes()).digest()==digest
    with pytest.raises(ValueError):export_obd_report(report,tmp_path/'private.html',[path])


def test_conflicting_chain_and_separate_sources_never_merge(tmp_path):
    report=analyze_obd([synthetic_bundle(tmp_path/'one.zip',conflict=True,other_source=True),synthetic_bundle(tmp_path/'two.zip')])
    assert len(report['sessions'])==2
    groups=report['sessions'][0]['inventory'];assert len(groups)==2
    first=next(g for g in groups if g['source_kind']=='SIMULATED');assert first['declared_count']==0 and first['contradictions']
    second=next(g for g in groups if g['source_kind']=='ECU_READING');assert all(r['advertised_support']=='UNKNOWN' for r in second['rows'])
    assert len(report['sessions'][0]['performance'])==2


def test_adaptation_uses_communication_not_values_decoder_or_cancellation():
    c=AdaptivePacing(4);r=dict(command='017A',status='INVALID',latency_ms=900,protocol_errors=[dict(category='DECODER_LAYOUT')])
    assert symptom(r)=='DECODER_LAYOUT' and not c.observe(r,1) and c.rate==4
    assert not c.observe(dict(r,status='CANCELLED'),2) and c.rate==4
    assert c.observe(dict(command='010C',status='TRANSPORT_ERROR',latency_ms=6000),3) and c.rate==2
    for i in range(120):c.observe(dict(command='010C',status='OK',latency_ms=30,value=999999),4+i*.1)
    assert c.rate==2 # cooldown plus prolonged stability, not sample-value spikes
    for i in range(300):c.observe(dict(command='010C',status='OK',latency_ms=30),40+i*.5)
    assert 2<c.rate<=4 and all(.25<=t['rate']<=4 for t in c.history)
    for i in range(50):c.observe(dict(command='0105',status='TRANSPORT_ERROR',latency_ms=6000),200+i)
    assert c.rate==.25 and len(c.history)<=64 and len(c.baselines['010C'])==32


def test_stationary_fixed_scope_immediate_abort_and_duration():
    b=StationaryBenchmark([12,11],2,0)
    assert b.next_pid(0)==12
    b.observe(dict(status='OK',sent=True));assert b.next_pid(1)==11
    b.observe(dict(status='ECU_NEGATIVE_RESPONSE',sent=True,negative_responses=[dict(nrc='22')]))
    assert not b.active and b.next_pid(2) is None and 'ECU_NRC' in b.reason
    assert StationaryBenchmark([12],1,0).next_pid(60) is None
    for rate in (0,4.01,10):
        with pytest.raises(ValueError):StationaryBenchmark([12],rate,0)


def test_invalid_reserved_final_bitmap_never_invents_pid_100():
    from mokka_ecu_lab.protocols import supported_pids
    from mokka_ecu_lab.research.evidence import BitmapEvidence
    with pytest.raises(ValueError):supported_pids(bytes.fromhex('00 00 00 01'),0xE0)
    with pytest.raises(ValueError):supported_pids(bytes(4),3)
    evidence=BitmapEvidence()
    assert evidence.observe(0,bytes.fromhex('00 00 00 01'))=='BITMAP_VALID_ANCHORED'
    assert evidence.observe(0,b'\x01')=='BITMAP_INVALID_LENGTH' and evidence.support(4)=='UNKNOWN'
    assert evidence.observe(0xE0,bytes.fromhex('00 00 00 01'))=='BITMAP_INVALID_RESERVED_BITS'


def test_sensor_unavailability_and_slow_benchmark_are_separate_from_capacity():
    c=AdaptivePacing(4)
    record=dict(command='019D',status='INVALID',raw_text='NO DATA\r>',latency_ms=1200)
    assert symptom(record)=='ECU_NO_DATA' and not c.observe(record,1) and c.rate==4
    b=StationaryBenchmark([12],2,0);b.observe(dict(status='OK',sent=True,latency_ms=1200))
    assert not b.active and 'no ECU capacity inference' in b.reason
