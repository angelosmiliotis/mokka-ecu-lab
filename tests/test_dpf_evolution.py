"""Small generated, non-identifying offline bundles; no vehicle payloads."""
import base64,csv,hashlib,io,json
from zipfile import ZipFile
import pytest
from mokka_ecu_lab.analysis.dpf import analyze_dpf,export_dpf_report
from mokka_ecu_lab.transport.simulator import can_reply
from mokka_ecu_lab.research.roadmap import research_roadmap
from mokka_ecu_lab.protocols import validate_command,UnsafeRequest


def fixture_bundle(path,*,csv_ecu='7E8',negative=False,snapshot=False,duplicate_snapshot=False):
    records=[]
    for i,(second,payload) in enumerate(((2,bytes([0xA5,0x10,3,4,5,6])),(20,bytes([0xA5,0x14,4,5,6,7])))):
        records.append(dict(id=f'generated-{i}',record_type='transaction',command='017A',pid='7A',
            timestamp=f'2000-01-01T00:00:{second:02d}+00:00',monotonic_ns=second*1000000000,mode='SIMULATED',source_kind='SIMULATED',
            raw_only=True,raw_b64=base64.b64encode((can_reply('7E8',0x7A,payload)+'\r>').encode()).decode()))
    if negative: records[0]['raw_b64']=base64.b64encode(b'7E8 03 7F 01 22\r>').decode()
    buf=io.StringIO(); writer=csv.writer(buf); writer.writerow(['timestamp','monotonic_ns','sensor_id','ecu','value','unit','source_mode','source_kind'])
    for second,speed in ((1,0),(19,10)):
        for sensor,value,unit in (('rpm',900,'rpm'),('speed',speed,'km/h'),('maf',4.2,'g/s'),('map',100,'kPa'),('coolant',60,'°C')):
            writer.writerow([f'2000-01-01T00:00:{second:02d}+00:00',second*1000000000,sensor,csv_ecu,value,unit,'SIMULATED','SIMULATED'])
    members={'raw-redacted.jsonl':('\n'.join(json.dumps(r) for r in records)+'\n').encode(),'measurements.csv':buf.getvalue().encode()}
    if snapshot:
        r=records[0]; sample=dict(raw_b64=r['raw_b64'],timestamp=r['timestamp'],monotonic_ns=r['monotonic_ns'],source_kind='SIMULATED')
        members['discovery-report.json']=json.dumps(dict(mode='SIMULATED',standard=[dict(request='017A',support='SUPPORTED',sample=sample)])).encode()
        if not duplicate_snapshot: members['raw-redacted.jsonl']=b''
    members['SHA256SUMS.txt']=''.join(hashlib.sha256(content).hexdigest()+'  '+name+'\n' for name,content in members.items()).encode()
    with ZipFile(path,'w') as z:
        for name,content in members.items(): z.writestr(name,content)
    return path


def test_raw_hypotheses_context_ages_motion_and_no_formula(tmp_path):
    bundle=fixture_bundle(tmp_path/'synthetic.zip'); digest=hashlib.sha256(bundle.read_bytes()).digest()
    report=analyze_dpf([bundle]); group=report['groups'][0]
    assert group['samples']==2 and group['raw_only_polling_samples']==2
    assert group['statistics']['AB_big_endian_HYPOTHESIS']['ALL']['minimum']==0xA510
    assert group['points'][0]['context']['rpm']['age_seconds']==1 and not group['points'][0]['context']['rpm']['simultaneous']
    assert [p['motion_group'] for p in group['points']]==['STATIONARY','MOVING']
    assert all(report[k] is None for k in ('selected_formula','pressure','regeneration','soot','ash'))
    export_dpf_report(report,tmp_path/'private-result.html',[bundle])
    html=(tmp_path/'private-result.html').read_text()
    assert 'HYPOTHESIS' in html and '<svg' in html and '2000-01-01' in html and 'default-src' in html
    assert '<script' not in html and 'src=' not in html
    assert hashlib.sha256(bundle.read_bytes()).digest()==digest
    with pytest.raises(ValueError): export_dpf_report(report,tmp_path/'private-result.html',[bundle])


def test_other_ecu_context_not_used_and_separate_bundles_never_merged(tmp_path):
    one=fixture_bundle(tmp_path/'one.zip',csv_ecu='7E9'); two=fixture_bundle(tmp_path/'two.zip')
    report=analyze_dpf([one,two]); assert len(report['groups'])==2
    assert all(p['context']['rpm']['value'] is None for p in report['groups'][0]['points'])
    assert all(p['motion_group']=='UNKNOWN' for p in report['groups'][0]['points'])


def test_negative_reply_not_evolution_or_proof(tmp_path):
    report=analyze_dpf([fixture_bundle(tmp_path/'negative.zip',negative=True)])
    assert report['groups'][0]['samples']==1 and report['groups'][0]['dynamic_evidence']=='INSUFFICIENT_SINGLE_SAMPLE'


@pytest.mark.parametrize('duplicate',[False,True])
def test_unrecorded_snapshot_is_explicit_and_never_double_counts_journal(tmp_path,duplicate):
    report=analyze_dpf([fixture_bundle(tmp_path/'snapshot.zip',snapshot=True,duplicate_snapshot=duplicate)])
    assert len(report['groups'])==1
    group=report['groups'][0]
    if duplicate: assert group['sample_provenance']=='RECORDED_JOURNAL' and group['samples']==2
    else: assert group['sample_provenance']=='UNRECORDED_DISCOVERY_SNAPSHOT' and group['raw_only_polling_samples']==0 and group['samples']==1


def test_bad_checksum_refused_without_any_output(tmp_path):
    path=fixture_bundle(tmp_path/'bad.zip')
    with ZipFile(path) as z: members={n:z.read(n) for n in z.namelist()}
    members['measurements.csv']=b'changed'
    with ZipFile(path,'w') as z:
        for name,content in members.items(): z.writestr(name,content)
    with pytest.raises(ValueError): analyze_dpf([path])


def test_research_records_have_required_evidence_and_cannot_expand_allowlist():
    records=research_roadmap()
    assert len(records)>=15
    for record in records:
        assert {'sources','ecu_applicability','units','decoding_formula','expected_data_bytes','version','validation_status','contradictions','risk'}<=record.keys()
        assert record['live_enabled'] is False and record['sources'] and record['contradictions']
    for command in ('0111','015A','0159','22D525','22D526','22D52F','22D532'):
        with pytest.raises(UnsafeRequest): validate_command(command,{0x11,0x5A,0x59},discovery_enabled=True,discovery_supported={0x11,0x5A,0x59})
