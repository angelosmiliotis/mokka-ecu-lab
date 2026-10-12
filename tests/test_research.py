"""Offline research fixtures constructed in memory, without identifying metadata."""
import base64
import hashlib
import json
import zipfile
import pytest
from mokka_ecu_lab.research.evidence import analyze_bundles,read_bundle
from mokka_ecu_lab.research.catalog import KnowledgeBase,new_catalog,validate_contribution
from mokka_ecu_lab.transport.simulator import can_reply


def transaction(pid,payload,ns,ecu='7E8',mode='SIMULATED',raw=None):
    return dict(record_type='transaction',command=f'01{pid:02X}',pid=f'{pid:02X}',
        monotonic_ns=ns,timestamp='constructed timestamp',mode=mode,
        raw_b64=base64.b64encode(raw or (can_reply(ecu,pid,payload)+'\r>').encode()).decode())


def bundle(path,records,extra=None):
    members={'raw-redacted.jsonl':('\n'.join(json.dumps(r) for r in records)+'\n').encode(),
        'session-summary.json':b'{"decoder_versions":["constructed-legacy"]}',
        'pid-support.json':b'[]'}
    members.update(extra or {})
    sums='\n'.join(hashlib.sha256(data).hexdigest()+'  '+name for name,data in members.items())
    with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as z:
        for name,data in members.items(): z.writestr(name,data)
        z.writestr('SHA256SUMS.txt',sums+'\n')
    return path


def test_raw_redecode_layout_changes_context_age_and_no_source_mixing(tmp_path):
    records=[transaction(12,b'\x0C\x80',10**9),transaction(16,b'\x01\xF4',2*10**9),
        transaction(13,b'\x14',3*10**9),transaction(0x7A,bytes.fromhex('00 C8 00 00 00 00'),4*10**9),
        transaction(0x7A,bytes.fromhex('00 C9 00 00 00 00'),5*10**9),
        transaction(0x88,bytes.fromhex('00 01 00 00 02 00 04 00 00 00 00 00 00'),6*10**9),
        transaction(0x88,bytes(3),7*10**9),transaction(0x7A,bytes(6),8*10**9,mode='LIVE CAN'),
        transaction(0x7A,bytes(6),9*10**9,ecu='7E9')]
    path=bundle(tmp_path/'a.zip',records); original=path.read_bytes()
    report=analyze_bundles([path]); groups=report['sessions'][0]['groups']
    assert len(groups)==3 and path.read_bytes()==original
    simulated=next(g for g in groups if g['ecu']=='7E8' and g['mode']=='SIMULATED')
    sample=simulated['samples'][0]
    assert sample['fields']==[] and sample['layout_status']=='UNVERIFIED_LAYOUT'
    assert sample['context']['rpm']['age_seconds']==3 and sample['context']['maf']['age_seconds']==2
    assert sample['context']['speed']['age_seconds']==1
    raw=next(e for e in simulated['matrix'] if e['pid']=='7A')
    assert raw['lengths']=={6:2} and raw['byte_changes']=={1:1} and raw['layout_mismatches']==2
    scr=next(e for e in simulated['matrix'] if e['pid']=='88')
    assert scr['lengths']=={13:1,3:1} and scr['layout_mismatches']==1
    assert next(s for s in simulated['samples'] if s['pid']=='88')['fields'][0]['value']==0
    for g in groups:
        if g is not simulated: assert g['samples'][0]['context']['rpm']['state']=='UNAVAILABLE'
    assert not list(tmp_path.glob('*.jsonl'))


def test_invalid_and_negative_framing_do_not_generate_payloads(tmp_path):
    records=[transaction(0x88,b'',1,raw=b'7E8 03 7F 01 22\r>'),
        transaction(0x88,b'',2,raw=b'7E8 10 0F 41 88 00 00 00 00\r>')]
    g=analyze_bundles([bundle(tmp_path/'a.zip',records)])['sessions'][0]['groups'][0]
    row=next(e for e in g['matrix'] if e['pid']=='88')
    assert row['negative_responses']==1 and row['invalid_framing']==1 and row['lengths']=={}
    assert g['samples']==[]


def test_multiple_sessions_stay_separate_and_duplicates_rejected(tmp_path):
    a=bundle(tmp_path/'a.zip',[transaction(0x7A,bytes(6),1,mode='LIVE CAN')])
    b=bundle(tmp_path/'b.zip',[transaction(0x7A,bytes(6),2)])
    r=analyze_bundles([a,b])
    assert len(r['sessions'])==2 and r['sessions'][0]['groups'][0]['source_kind']=='ECU_READING'
    with pytest.raises(ValueError,match='same evidence'): analyze_bundles([a,a])


def test_checksum_coverage_and_paths_fail_closed(tmp_path):
    path=bundle(tmp_path/'a.zip',[])
    with pytest.warns(UserWarning,match='Duplicate name'):
        with zipfile.ZipFile(path,'a') as z: z.writestr('raw-redacted.jsonl','modified')
    with pytest.raises(ValueError,match='Duplicate'): read_bundle(path)
    path=bundle(tmp_path/'b.zip',[],{'../secret.txt':b'no extraction'})
    with pytest.raises(ValueError,match='unrecognized'): read_bundle(path)
    path=bundle(tmp_path/'c.zip',[])
    with zipfile.ZipFile(path,'a') as z: z.writestr('markers.json',b'[]')
    with pytest.raises(ValueError,match='Checksum'): read_bundle(path)


def test_bounds_and_unknown_source_contradiction(tmp_path,monkeypatch):
    from mokka_ecu_lab.research import evidence
    record=transaction(0x7A,bytes(6),1); record['source_kind']='ECU_READING'
    path=bundle(tmp_path/'a.zip',[record])
    r=analyze_bundles([path])['sessions'][0]
    assert r['contradictions'] and r['groups'][0]['source_kind']=='UNKNOWN'
    monkeypatch.setattr(evidence,'MAX_MEMBER',10)
    with pytest.raises(ValueError,match='limits'): read_bundle(path)


def test_catalog_roundtrip_keeps_identity_unknown_and_never_promotes(tmp_path):
    catalog=KnowledgeBase(tmp_path/'catalog.json')
    r=analyze_bundles([bundle(tmp_path/'a.zip',[transaction(0x88,bytes(13),1,mode='LIVE CAN')])])
    catalog.record_evidence(r)
    data=KnowledgeBase(catalog.path).data
    assert data['profile']['hardware_identification']=='UNKNOWN'
    assert data['evidence'][0]['evidence_state']=='VEHICLE_OBSERVED'
    assert data['evidence'][0]['independent_verification']=='UNVERIFIED'
    assert all(d['evidence_state']=='STANDARD_DOCUMENTED' and d['vehicle_verification']=='UNVERIFIED' for d in data['standard_definitions'])
    hypothesis=dict(verification='EXPERIMENTAL',scale=.01,offset=0,request='017A')
    catalog.add_hypothesis(hypothesis);catalog.reject_hypothesis(0,'Constructed reference disagrees')
    assert KnowledgeBase(catalog.path).data['hypotheses'][0]['evidence_state']=='REJECTED'
    with pytest.raises(ValueError): catalog.add_hypothesis(dict(hypothesis,verification='INDEPENDENTLY_VERIFIED'))
    assert all(not c['live_enabled'] for c in new_catalog()['manufacturer_candidates'])


def test_future_definition_schema_excludes_observations_and_identity():
    d=dict(schema_version=1,definition_id='constructed',service='01',pid='88',length=13,
        formula='unsigned big-endian',units='km',signed=False,flags={},sentinel=None,
        references=['constructed independent source'],revision='example',evidence_state='INDEPENDENTLY_VERIFIED',
        verification_method='constructed reference comparison',test_provenance='synthetic')
    assert validate_contribution(d)==d
    for extra in ('vin','journey','raw_b64','ecu_identifier','cloud_upload'):
        with pytest.raises(ValueError): validate_contribution(dict(d,**{extra:'excluded'}))
    with pytest.raises(ValueError): validate_contribution(dict(d,evidence_state='EXPERIMENTAL'))


def test_raw_bitmap_snapshot_contradiction_and_independent_identity(tmp_path):
    records=[transaction(0, (1<<(31-31)).to_bytes(4,'big'),1),
        transaction(32,(1<<(31-31)).to_bytes(4,'big'),2),
        transaction(64,(1<<(31-31)).to_bytes(4,'big'),3),
        transaction(96,((1<<(31-31))|(1<<(31-25))).to_bytes(4,'big'),4),
        transaction(0x7A,bytes(6),5)]
    p=bundle(tmp_path/'a.zip',records,{'pid-support.json':b'[{"pid":"7A","ecu":"7E8","support":"UNSUPPORTED"}]'})
    r=analyze_bundles([p])['sessions'][0]
    assert r['contradictions']
    row=next(e for e in r['groups'][0]['matrix'] if e['pid']=='7A')
    assert row['support']=='SUPPORTED'
    catalog=KnowledgeBase(tmp_path/'catalog.json')
    catalog.set_known_identity({'hardware_identification':'constructed HW'},'constructed independent source','reference record')
    assert catalog.data['profile']['hardware_identification']=='constructed HW'
    assert all(c['live_enabled'] is False for c in catalog.data['manufacturer_candidates'])
    with pytest.raises(ValueError): catalog.set_known_identity({'vin':'excluded'},'source','method')
