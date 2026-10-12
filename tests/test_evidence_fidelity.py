"""Small constructed wire journals, never private drive data."""
import json
import pytest
from test_research import bundle,transaction
from mokka_ecu_lab.research.evidence import analyze_bundles


def snapshots(*rows):
    return {'pid-support.json':json.dumps([dict(ecu=ecu,pid=pid,support=state) for ecu,pid,state in rows]).encode()}


def chain(targets=(),ecu='7E8',mode='SIMULATED'):
    records=[]
    for base in range(0,129,32):
        pids={p for p in targets if base<p<=base+32}
        if base<128: pids.add(base+32)
        bits=sum(1<<(32-(p-base)) for p in pids)
        records.append(transaction(base,bits.to_bytes(4,'big'),base+1,ecu=ecu,mode=mode))
    return records


def entry(report,pid,ecu='7E8',mode='SIMULATED'):
    g=next(g for g in report['sessions'][0]['groups'] if g['ecu']==ecu and g['mode']==mode)
    return next(r for r in g['matrix'] if r['pid']==pid)


def test_recorded_snapshot_is_supported_without_raw_verification(tmp_path):
    p=bundle(tmp_path/'a.zip',[transaction(0x85,bytes(10),1)],snapshots(('7E8','85','SUPPORTED')))
    report=analyze_bundles([p]); r=entry(report,'85')
    assert r['support']==r['raw_bitmap_support']=='UNKNOWN'
    assert r['recorded_discovery_support']=='SUPPORTED' and r['recorded_support']==['SUPPORTED']
    assert r['recorded_support_provenance']==['pid-support.json'] and not r['recorded_support_raw_verified']
    assert r['positive_response_count']==1 and r['observation_state']=='SIMULATED_OBSERVED'
    assert not r['contradictions'] and not report['sessions'][0]['contradictions']


def test_complete_chain_agrees_but_never_crosses_ecu(tmp_path):
    p=bundle(tmp_path/'a.zip',chain({0x85})+[transaction(0x85,bytes(10),200,ecu='7E9')],
        snapshots(('7E8','85','SUPPORTED'),('7E9','85','SUPPORTED')))
    report=analyze_bundles([p])
    assert entry(report,'85')['raw_bitmap_support']==entry(report,'85')['recorded_discovery_support']=='SUPPORTED'
    assert entry(report,'85','7E9')['raw_bitmap_support']=='UNKNOWN'
    assert entry(report,'85','7E9')['recorded_discovery_support']=='SUPPORTED'


def test_snapshot_and_raw_disagreement_never_promotes(tmp_path):
    r=entry(analyze_bundles([bundle(tmp_path/'a.zip',chain(),snapshots(('7E8','85','SUPPORTED')))]),'85')
    assert r['raw_bitmap_support']=='UNSUPPORTED' and r['recorded_discovery_support']=='SUPPORTED'
    assert r['contradictions'] and r['observation_state']=='NOT_OBSERVED'


def test_unanchored_bitmap_is_valid_length_and_not_decoder_error(tmp_path):
    records=[transaction(0x60,b'\0\0\0\1',1),transaction(0x80,b'\x08\0\0\0',2)]
    report=analyze_bundles([bundle(tmp_path/'a.zip',records)])
    for pid in ('60','80'):
        r=entry(report,pid)
        assert r['layout_state']=='BITMAP_VALID_UNANCHORED' and r['layout_mismatches']==0
        assert r['valid_framing']==1 and r['invalid_framing']==0
        assert 'MISSING_PREDECESSOR_EVIDENCE' in r['evidence_explanation']
    assert entry(report,'85')['raw_bitmap_support']=='UNKNOWN'


def test_wrong_length_negative_and_broken_transport_are_separate(tmp_path):
    records=[transaction(0x60,bytes(3),1),transaction(0x60,b'',2,raw=b'7E8 03 7F 01 22\r>'),
        transaction(0x60,b'',3,raw=b'7E8 10 06 41 60 00 00\r>')]
    r=entry(analyze_bundles([bundle(tmp_path/'a.zip',records)]),'60')
    assert r['positive_response_count']==1 and r['layout_mismatches']==1
    assert r['layout_state']=='BITMAP_INVALID_LENGTH'
    assert r['valid_framing']==2 and r['negative_responses']==1 and r['invalid_framing']==1
    assert r['frame_validity']=='MIXED_FRAMING'


def test_unobserved_definition_never_inherits_live_observation(tmp_path):
    p=bundle(tmp_path/'a.zip',[transaction(0x85,bytes(10),1,mode='LIVE CAN')],snapshots(('7E8','8B','UNSUPPORTED')))
    r=entry(analyze_bundles([p]),'8B',mode='LIVE CAN')
    assert r['positive_response_count']==0 and r['observation_state']==r['vehicle_evidence']=='NOT_OBSERVED'
    assert r['definition_state']=='STANDARD_DOCUMENTED' and r['layout_state']=='NO_POSITIVE_RESPONSE'
    assert r['recorded_discovery_support']=='UNSUPPORTED' and r['raw_bitmap_support']=='UNKNOWN'
    assert 'OEM equivalent' in r['evidence_explanation']


def test_conflicting_snapshots_and_ambiguous_source_scope(tmp_path):
    extra=snapshots(('7E8','85','SUPPORTED'),('7E8','85','UNSUPPORTED'))
    r=entry(analyze_bundles([bundle(tmp_path/'a.zip',[transaction(0x85,bytes(10),1)],extra)]),'85')
    assert r['recorded_discovery_support']=='CONFLICT' and r['contradictions']
    records=[transaction(0x85,bytes(10),1),transaction(0x85,bytes(10),2,mode='LIVE CAN')]
    report=analyze_bundles([bundle(tmp_path/'b.zip',records,extra)])
    for g in report['sessions'][0]['groups']:
        r=next(e for e in g['matrix'] if e['pid']=='85')
        assert r['recorded_discovery_support']=='UNKNOWN' and 'ambiguous' in r['evidence_explanation']


def test_bitmap_conflicts_quarantine_descendants_and_keep_order(tmp_path):
    records=chain({0x85})+[transaction(0,b'\0\0\0\0',200)]
    report=analyze_bundles([bundle(tmp_path/'a.zip',records)])
    assert entry(report,'85')['raw_bitmap_support']=='UNKNOWN'
    assert entry(report,'80')['layout_state']=='BITMAP_CHAIN_CONFLICT'
    assert report['sessions'][0]['contradictions']
    # Later predecessors do not retroactively certify the earlier page.
    early=[transaction(0x80,b'\x08\0\0\0',0)]+chain()[:-1]
    report=analyze_bundles([bundle(tmp_path/'b.zip',early)])
    assert entry(report,'85')['raw_bitmap_support']=='UNKNOWN'
    assert entry(report,'80')['layout_state']=='BITMAP_VALID_UNANCHORED'


def test_bitmap_parent_continuation_conflict_is_not_length_error(tmp_path):
    p=bundle(tmp_path/'a.zip',[transaction(0,bytes(4),1),transaction(32,bytes(4),2)])
    report=analyze_bundles([p]); r=entry(report,'20')
    assert r['layout_state']=='BITMAP_CHAIN_CONFLICT' and r['layout_mismatches']==0
    assert report['sessions'][0]['contradictions'] and entry(report,'85')['raw_bitmap_support']=='UNKNOWN'
