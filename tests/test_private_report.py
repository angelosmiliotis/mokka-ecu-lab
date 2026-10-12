"""Constructed reports; no private recording values or identifying metadata."""
import copy
import json
from html.parser import HTMLParser
import pytest
from test_research import bundle,transaction
from mokka_ecu_lab.research.evidence import analyze_bundles
from mokka_ecu_lab.research.report import export_private_report,render_html,normalize_analysis,load_analysis
from mokka_ecu_lab.research.summary import summary_lines


def report(tmp_path,records):
    return analyze_bundles([bundle(tmp_path/'constructed.zip',records)])


def test_inactive_at_recorded_time_keeps_history_separate(tmp_path):
    payload=bytes.fromhex('00 42 81 00 05 00 14 00 03 00 02 00 01')
    r=report(tmp_path,[transaction(0x88,payload,1)])
    s=r['sessions'][0]['groups'][0]['scr_summary']; current=s['current']
    assert current['state']=='Inactive at recorded time' and current['availability']=='AVAILABLE'
    assert not any(v['set'] for v in current['reasons'])
    assert any(v['set'] for b in current['historical'] for v in b['reasons'])
    assert len(current['counters'])==5 and s['independent_verification']=='UNVERIFIED'
    text='\n'.join(summary_lines(s))
    assert 'Historical evidence — not current fault' in text and 'constructed timestamp' in text
    assert 'healthy' not in text.lower()


@pytest.mark.parametrize('payload',[None,bytes(3),b'\x01'+bytes(12),b'\x10'+bytes(12)])
def test_absent_or_unverified_scr_never_becomes_inactive(tmp_path,payload):
    records=[transaction(0x85,bytes(10),1)]
    if payload is not None: records.append(transaction(0x88,payload,2))
    s=report(tmp_path,records)['sessions'][0]['groups'][0]['scr_summary']
    assert s['current']['state']=='UNAVAILABLE' and s['current']['counters']==[]


def test_latest_invalid_scr_does_not_reuse_prior_inactive_value(tmp_path):
    s=report(tmp_path,[transaction(0x88,bytes(13),1),transaction(0x88,bytes(3),2)])['sessions'][0]['groups'][0]['scr_summary']
    assert s['current']['state']=='UNAVAILABLE' and s['documented_samples']['88']==1


def test_tank_quantization_static_warning_and_single_nox_have_no_diagnosis(tmp_path):
    # Supported tank and warning-time only; tiny synthetic observation count.
    tank=lambda step:bytes([12,0,0,0,0,step,0,0,0,17])
    nox=bytes([1,0,23,0,0,0,0,0,0])
    s=report(tmp_path,[transaction(0x85,tank(90),1),transaction(0x85,tank(91),2),transaction(0x83,nox,3)])['sessions'][0]['groups'][0]['scr_summary']
    assert s['adblue']['tank_level']['count']==2 and s['adblue']['warning_time_static']
    assert s['nox']['decoded_observations']==1
    text='\n'.join(summary_lines(s))
    assert 'quantized range' in text and 'does not measure consumed volume' in text
    assert 'One sample is not a trend' in text and 'does not establish a current SCR fault' in text


def test_summary_scope_does_not_mix_sessions_modes_or_ecus(tmp_path):
    a=bundle(tmp_path/'a.zip',[transaction(0x88,b'\x81'+bytes(12),1,mode='LIVE CAN'),
        transaction(0x88,bytes(13),2),transaction(0x85,bytes(10),3,ecu='7E9')])
    b=bundle(tmp_path/'b.zip',[transaction(0x88,bytes(3),4)])
    r=analyze_bundles([a,b])
    live=next(g for g in r['sessions'][0]['groups'] if g['mode']=='LIVE CAN')
    sim=next(g for g in r['sessions'][0]['groups'] if g['ecu']=='7E8' and g['mode']=='SIMULATED')
    other=next(g for g in r['sessions'][0]['groups'] if g['ecu']=='7E9')
    assert live['scr_summary']['current']['state']=='Active at recorded time'
    assert sim['scr_summary']['current']['state']=='Inactive at recorded time'
    assert other['scr_summary']['current']['state']=='UNAVAILABLE'
    assert r['sessions'][1]['groups'][0]['scr_summary']['current']['state']=='UNAVAILABLE'


class NetworkAudit(HTMLParser):
    def handle_starttag(self,tag,attrs):
        assert tag not in {'script','iframe','img','link','object','embed','form','a','base'}
        assert not any(k.lower().startswith('on') or k.lower() in {'src','href','srcset','action'} for k,v in attrs)
        assert not (tag=='meta' and any(k=='http-equiv' and v.lower()=='refresh' for k,v in attrs))


def test_html_escapes_untrusted_metadata_excludes_identity_and_default_timeline(tmp_path):
    r=report(tmp_path,[transaction(0x88,bytes(13),1),transaction(0x7A,bytes(6),2)])
    session=r['sessions'][0]; g=session['groups'][0]
    g['mode']='<script src="https://invalid.example/a">injection</script>'
    session.update(vin='IDENTITY_SENTINEL',owner='OWNER_SENTINEL',adapter='ADAPTER_SENTINEL')
    g['samples'][0]['context']['rpm'].update(vin='NESTED_IDENTITY_SENTINEL')
    compact=render_html(r)
    assert '&lt;script src=&quot;' in compact and '<script ' not in compact
    assert 'IDENTITY_SENTINEL' not in compact and 'OWNER_SENTINEL' not in compact and 'ADAPTER_SENTINEL' not in compact
    assert 'constructed timestamp' not in compact and 'payload_hex' not in compact
    NetworkAudit().feed(compact)
    detailed=render_html(r,detailed=True)
    assert 'constructed timestamp' in detailed and 'payload_hex' in detailed
    assert 'NESTED_IDENTITY_SENTINEL' not in detailed
    NetworkAudit().feed(detailed)


def test_fresh_atomic_exports_preserve_all_inputs_and_saved_reports(tmp_path):
    r=report(tmp_path,[transaction(0x88,bytes(13),1)])
    original=(tmp_path/'constructed.zip').read_bytes()
    target=tmp_path/'private.html'; outputs=export_private_report(r,target,[tmp_path/'constructed.zip'])
    assert len(outputs)==2 and json.loads(target.with_suffix('.json').read_text(encoding='utf-8'))==json.loads(json.dumps(r))
    assert '<!doctype html>' in target.read_text()
    with pytest.raises(ValueError,match='never overwritten'): export_private_report(r,target)
    with pytest.raises(ValueError): export_private_report(r,tmp_path/'constructed.zip')
    assert (tmp_path/'constructed.zip').read_bytes()==original
    assert not list(tmp_path.glob('private-report-*'))


def test_older_json_additive_migration_preserves_raw_support_and_layout_counts(tmp_path):
    current=report(tmp_path,[transaction(0x60,bytes(4),1),transaction(0x88,bytes(13),2)])
    old=copy.deepcopy(current); old.pop('analysis_revision')
    g=old['sessions'][0]['groups'][0]; g.pop('scr_summary')
    for r in g['matrix']:
        for key in ('raw_bitmap_support','recorded_discovery_support','positive_response_count','observation_state','layout_state','frame_validity','definition_state','evidence_explanation','recorded_support_provenance'):
            r.pop(key)
    bitmap=next(r for r in g['matrix'] if r['pid']=='60'); bitmap['layout_mismatches']=1
    frozen=copy.deepcopy(old); migrated=normalize_analysis(old)
    assert old==frozen and migrated['schema_version']==1
    row=next(r for r in migrated['sessions'][0]['groups'][0]['matrix'] if r['pid']=='60')
    assert row['support']==bitmap['support'] and row['layout_mismatches']==1
    assert row['layout_state']=='LEGACY_ANALYSIS_REQUIRES_REIMPORT'
    assert migrated['sessions'][0]['groups'][0]['scr_summary']['current']['state']=='Inactive at recorded time'
    p=tmp_path/'old.json';p.write_text(json.dumps(old))
    assert load_analysis(p)['analysis_origin']=='SAVED_ANALYSIS_NOT_REVALIDATED'


def test_eleven_file_legacy_bundle_retains_full_raw_journal(tmp_path):
    extras={name:b'{}' for name in ('discovery-report.json','ecu-identifiers.json','polling-statistics.json','errors.json','markers.json','manifest.json')}
    extras['measurements.csv']=b'sensor_id,value\n'
    r=analyze_bundles([bundle(tmp_path/'legacy.zip',[transaction(0x88,bytes(13),1)],extras)])
    assert r['sessions'][0]['groups'][0]['scr_summary']['documented_samples']['88']==1
    assert any('complete original raw journal is still analyzed' in s for s in r['sessions'][0]['missing_evidence'])
