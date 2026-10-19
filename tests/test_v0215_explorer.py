"""Independently constructed evidence combinations; no real vehicle fixtures."""
import base64,hashlib,json
from zipfile import ZipFile
from datetime import datetime,timedelta,timezone
import pytest
from mokka_ecu_lab.analysis.explorer import analyze_explorer,export_explorer,select_rows
from mokka_ecu_lab.transport.simulator import can_reply


def bundle(path,*,conflict=False,split_context=False):
    records=[]
    def add(pid,data,seconds,context='synthetic-one',**extra):
        i=len(records);raw=(can_reply('7E9',pid,data)+'\r>').encode()
        records.append(dict(id=f'constructed-{i}',record_type='transaction',command=f'01{pid:02X}',pid=f'{pid:02X}',
            timestamp=(datetime(2001,1,1,tzinfo=timezone.utc)+timedelta(seconds=seconds)).isoformat(),monotonic_ns=int((seconds+1)*1e9),
            sent=True,status='OK',context_id=context,mode='SIMULATED',source_kind='SIMULATED',raw_b64=base64.b64encode(raw).decode(),**extra))
    ids={1,12,32,64,96,122,128,131,157}
    for base in (0,32,64,96,128):add(base,sum(1<<(32-(p-base)) for p in ids if base<p<=base+32).to_bytes(4,'big'),len(records)*.25)
    add(12,b'\x08\x00',2,discovery_samples=True)
    add(12,b'\x0c\x00',3,pacing_mode='ADAPTIVE');add(12,b'\x10\x00',5,pacing_mode='ADAPTIVE')
    add(122,b'\x01\x03\x02\x04\x05\x06',6,pacing_mode='ADAPTIVE')
    add(131,b'\x01\x00\x0c\x00\x00\x00\x00\x00\x00',7,pacing_mode='ADAPTIVE')
    if split_context:add(12,b'\x14\x00',8,context='synthetic-other',pacing_mode='ADAPTIVE')
    if conflict:add(0,bytes(4),9)
    add(157,b'\x00',20)
    payload=('\n'.join(json.dumps(r) for r in records)+'\n').encode()
    receipt=dict(ecu='7E9',mode='SIMULATED',source_kind='SIMULATED',context_id='synthetic-one',preset='CONSTRUCTED',effective_schedule={'0C':dict(nominal_interval_seconds=1),'83':dict(nominal_interval_seconds=4)})
    members={'raw-redacted.jsonl':payload,'session-summary.json':json.dumps(dict(session_id='CONSTRUCTED')).encode(),'acquisition-receipt.json':json.dumps(receipt).encode()}
    members['SHA256SUMS.txt']=''.join(hashlib.sha256(v).hexdigest()+'  '+k+'\n' for k,v in members.items()).encode()
    with ZipFile(path,'w') as z:
        for k,v in members.items():z.writestr(k,v)
    return path


def test_separate_gates_field_multiplicity_and_age(tmp_path):
    path=bundle(tmp_path/'constructed.zip');g=analyze_explorer([path])['sessions'][0]['groups'][0];rows={r['pid']:r for r in g['rows']}
    assert g['declared_count']==5 and g['positive_pid_count']==4 and g['numeric_pid_count']==2 and g['valid_field_ids']==2
    assert rows['01']['advertised_support']=='SUPPORTED' and rows['01']['representation']=='NOT_READ'
    assert rows['0C']['repeated_polling'] and rows['0C']['role_counts']=={'DISCOVERY':1,'POLLING':2}
    assert rows['0C']['polling_timing']['gap_seconds']['p50']==2
    f=rows['0C']['fields'][0];assert f['last_valid_value']==1024 and f['age_at_recording_end_seconds']==15 and f['staleness']=='STALE'
    assert rows['7A']['representation']=='RAW_ONLY' and rows['7A']['bounded_raw_examples'][0]['payload_hex']=='01 03 02 04 05 06'
    assert rows['83']['field_count']==4 and rows['83']['valid_field_count']==1
    assert rows['83']['fields'][1]['observed_states']=={'UNSUPPORTED_FIELD':1}
    assert rows['9D']['definition']['implementation']=='UNVERIFIED' and rows['9D']['representation']=='RAW_ONLY'
    assert g['physical_sensor_count'] is None
    assert {r['pid'] for r in select_rows(g,state='RAW only')}=={'7A','9D'}
    assert [r['pid'] for r in select_rows(g,'rpm','Repeated polling')]==['0C']
    assert [r['pid'] for r in select_rows(g,state='Advertised without response')]==['01']
    assert [r['pid'] for r in select_rows(g,state='Unavailable subfields')]==['83']
    assert len(select_rows(g,state='All non-bitmap IDs'))==len(g['rows'])==248


def test_context_and_conflicting_bitmap_do_not_promote_support(tmp_path):
    report=analyze_explorer([bundle(tmp_path/'context.zip',split_context=True,conflict=True)])
    groups=report['sessions'][0]['groups'];assert len(groups)==2
    assert all(g['declared_count']==0 for g in groups)
    other=next(g for g in groups if g['context_id']=='synthetic-other')
    rpm=next(r for r in other['rows'] if r['pid']=='0C')
    assert rpm['advertised_support']=='UNKNOWN' and rpm['same_ecu_positive']==1 and not rpm['repeated_polling']
    assert rpm['profile_evidence']=='NO_UNAMBIGUOUS_RECEIPT'


def test_private_export_preserves_original_and_rejects_duplicates_git_and_overwrite(tmp_path):
    path=bundle(tmp_path/'original.zip');before=path.read_bytes();report=analyze_explorer([path])
    session=report['sessions'][0]
    assert session['input_container_sha256']==hashlib.sha256(before).hexdigest()
    assert session['verified_member_manifest_sha256']==session['evidence_id']!=session['input_container_sha256']
    with pytest.raises(ValueError,match='Duplicate'):analyze_explorer([path,path])
    targets=export_explorer(report,tmp_path/'ιδιωτικό.json',[path]);assert all(p.exists() for p in targets) and path.read_bytes()==before
    assert 'physical_calibration' in targets[1].read_text(encoding='utf-8') and json.loads(targets[0].read_text(encoding='utf-8'))==json.loads(json.dumps(report))
    with pytest.raises(ValueError):export_explorer(report,targets[0],[path])
    git=tmp_path/'repo';git.mkdir();(git/'.git').mkdir()
    with pytest.raises(ValueError,match='Git'):export_explorer(report,git/'evidence.json',[path])


def write_members(path,members):
    members={k:v for k,v in members.items() if k!='SHA256SUMS.txt'}
    members['SHA256SUMS.txt']=''.join(hashlib.sha256(v).hexdigest()+'  '+k+'\n' for k,v in members.items()).encode()
    with ZipFile(path,'w') as z:
        for k,v in members.items():z.writestr(k,v)
    return path


def test_distinct_zero_request_failures_do_not_disappear_as_duplicate_empty_journals(tmp_path):
    paths=[write_members(tmp_path/f'empty-{n}.zip',{'raw-redacted.jsonl':b'','session-summary.json':json.dumps(dict(session_id=f'CONSTRUCTED{n}')).encode()}) for n in (1,2)]
    report=analyze_explorer(paths)
    assert len(report['sessions'])==2 and all(not s['groups'] for s in report['sessions'])
    with pytest.raises(ValueError):analyze_explorer([paths[0],paths[0]])


def test_alternate_layout_and_reserved_bits_keep_all_bytes_without_numeric_promotion(tmp_path):
    original=bundle(tmp_path/'base.zip')
    with ZipFile(original) as z:members={k:z.read(k) for k in z.namelist()}
    records=[json.loads(line) for line in members['raw-redacted.jsonl'].splitlines()]
    reserved=next(r for r in records if r['command']=='0183');reserved['raw_b64']=base64.b64encode((can_reply('7E9',131,b'\xf0'+bytes(8))+'\r>').encode()).decode()
    alternate=dict(records[-1],id='constructed-alternate',command='018C',pid='8C',raw_b64=base64.b64encode((can_reply('7E9',140,bytes(range(15)))+'\r>').encode()).decode())
    records.append(alternate);members['raw-redacted.jsonl']='\n'.join(json.dumps(r) for r in records).encode()
    path=write_members(tmp_path/'alternate.zip',members);g=analyze_explorer([path])['sessions'][0]['groups'][0];rows={r['pid']:r for r in g['rows']}
    assert rows['83']['representation']=='RAW_ONLY' and rows['83']['valid_field_count']==0
    assert rows['8C']['representation']=='RAW_ONLY' and rows['8C']['bounded_raw_examples'][0]['payload_hex']==bytes(range(15)).hex(' ').upper()
    assert rows['8C']['evidence_progression']['length_verified']['samples']==0 and rows['8C']['definition']['expected_bytes']==17


def test_csv_does_not_execute_untrusted_source_context_as_a_formula(tmp_path):
    path=bundle(tmp_path/'source.zip')
    with ZipFile(path) as z:members={k:z.read(k) for k in z.namelist()}
    records=[json.loads(line) for line in members['raw-redacted.jsonl'].splitlines()]
    for r in records:r['context_id']='=CONSTRUCTED()'
    members['raw-redacted.jsonl']='\n'.join(json.dumps(r) for r in records).encode()
    changed=write_members(tmp_path/'formula.zip',members);report=analyze_explorer([changed]);targets=export_explorer(report,tmp_path/'safe.json')
    import csv
    with targets[1].open(encoding='utf-8',newline='') as stream:rows=list(csv.DictReader(stream))
    assert rows and all(r['context_id']=="'=CONSTRUCTED()" for r in rows)


def test_duplicate_send_timestamp_is_not_repeated_polling(tmp_path):
    original=bundle(tmp_path/'base.zip')
    with ZipFile(original) as z:members={k:z.read(k) for k in z.namelist()}
    records=[json.loads(line) for line in members['raw-redacted.jsonl'].splitlines()]
    records=[r for r in records if r['command']!='010C' or r['monotonic_ns']==4_000_000_000]
    record=next(r for r in records if r['command']=='010C')
    records.append(dict(record,id='constructed-duplicate-send-stamp'))
    members['raw-redacted.jsonl']='\n'.join(json.dumps(r) for r in records).encode()
    path=write_members(tmp_path/'duplicate-replies.zip',members);g=analyze_explorer([path])['sessions'][0]['groups'][0]
    row=next(r for r in g['rows'] if r['pid']=='0C')
    assert row['same_ecu_positive']==2 and row['polling_replies']==2
    assert row['distinct_polling_send_timestamps']==1 and not row['repeated_polling']
    assert not select_rows(g,state='Repeated polling')


def test_extended_decode_annotations_are_not_a_discovery_phase(tmp_path):
    original=bundle(tmp_path/'base.zip')
    with ZipFile(original) as z:members={k:z.read(k) for k in z.namelist()}
    records=[json.loads(line) for line in members['raw-redacted.jsonl'].splitlines()]
    for record in records:
        if record.get('pacing_mode')=='ADAPTIVE':record['discovery_samples']=[dict(constructed_decode_annotation=True)]
    records.append(dict(next(r for r in records if r['command']=='017A'),id='constructed-next-raw',monotonic_ns=9_000_000_000))
    members['raw-redacted.jsonl']='\n'.join(json.dumps(r) for r in records).encode()
    path=write_members(tmp_path/'annotated-polling.zip',members);g=analyze_explorer([path])['sessions'][0]['groups'][0];rows={r['pid']:r for r in g['rows']}
    assert rows['7A']['repeated_polling'] and rows['7A']['polling_replies']==2 and rows['7A']['role_counts']=={'POLLING':2}
    assert rows['83']['polling_replies']==1 and rows['83']['role_counts']=={'POLLING':1}
    assert rows['0C']['role_counts']=={'DISCOVERY':1,'POLLING':2}


def test_raw_research_annotation_cites_the_registered_definition(tmp_path):
    """Research prose must not contradict the separately registered definition."""
    from mokka_ecu_lab.sensors.diesel import STANDARD_DIESEL
    group=analyze_explorer([bundle(tmp_path/'constructed.zip')])['sessions'][0]['groups'][0]
    row=next(r for r in group['rows'] if r['pid']=='7A')
    from mokka_ecu_lab.research.definition_status import research_status
    note=research_status(0x7A)['interpretation']
    assert STANDARD_DIESEL[0x7A].metadata()['source_table'] in note
    assert row['representation']=='RAW_ONLY' and row['valid_field_count']==0
