"""Fabricated six-run corpus, private wrapper and copy-only migration safety."""
from pathlib import Path
import hashlib,json,zipfile
import pytest
from mokka_ecu_lab.logging import Recorder
from mokka_ecu_lab.logging.bundle import export_research_bundle
from mokka_ecu_lab.library import ReportLibrary,digest
from mokka_ecu_lab.analysis.obd import analyze_obd,export_obd_report
from mokka_ecu_lab.research.evidence import read_bundle

@pytest.fixture
def legacy(tmp_path):
    root=tmp_path/'unmanaged fabricated sources';root.mkdir();data=tmp_path/'constructed journals'
    for i in range(6):
        rec=Recorder(data,'SIMULATED',{})
        if i<5:
            failed=i in (3,4)
            rec.evidence(dict(application_version='0.2.10',stationary_benchmark=dict(kind='AUTO_60S_V1',completed=not failed,rate=(2,3,4,3,4)[i],requests=0,
                reason='Preflight aborted: could not open port SYNTHETIC; semaphore timeout 121' if failed else 'Completed fixed window',measurement_started_monotonic=None if failed else 100,measurement_duration_seconds=0 if failed else 60,session_id=rec.id,mode='SIMULATED')))
        rec.close();bundle=root/(rec.id+'-research-constructed.zip');export_research_bundle(data,rec.id,bundle)
        export_obd_report(analyze_obd([bundle]),bundle.with_suffix('.html'))
    return root

def test_six_groups_eighteen_companions_approved_copy_idempotent_and_wrapper(tmp_path,legacy):
    hashes={p:digest(p) for p in legacy.iterdir()};assert len(hashes)==18
    lib=ReportLibrary(tmp_path/'data Ω with spaces');plan=lib.preview_migration(legacy)
    assert len(plan['groups'])==6 and all(g['action'].startswith('COPY') for g in plan['groups'])
    with pytest.raises(ValueError,match='approval'):lib.migrate(plan,'not-approved')
    outputs=lib.migrate(plan,plan['approval_token']);assert len(outputs)==6
    rows=lib.rows();assert len(rows)==6
    assert [r['status'] for r in rows].count('FAILED_COM_OPEN')==2
    assert all(r['timezone']=='Europe/Athens' and r['started_local'].endswith(('+03:00','+02:00')) for r in rows)
    for row in rows:
        folder=Path(row['folder']);assert folder.is_dir() and len(list(folder.iterdir()))==4
        assert len(folder.relative_to(lib.reports).parts)==2
        assert all(lib.verify(row['library_id'])['hashes'][n]==digest(folder/n) for n in ('original-research.zip','report.json','report.html'))
    assert lib.migrate(plan,plan['approval_token'])==outputs and len(lib.rows())==6
    assert all(digest(p)==h for p,h in hashes.items())
    row=rows[0];original_identity=read_bundle(Path(row['folder'])/'original-research.zip')[0]
    lib.label(row['library_id'],'Synthetic display label Ω');assert lib.rows('display label')[0]['library_id']==row['library_id']
    note=lib.annotate(row['library_id'],'Sport on','2001-02-03T04:05:06+00:00',45,'Approximate constructed note')
    assert not note['ecu_confirmed'] and note['provenance']=='USER_REPORTED_OFFLINE'
    target=lib.export_run(row['library_id'],tmp_path/'private-wrapper.zip',include_annotations=True)
    assert read_bundle(target)[0]==original_identity
    assert 'annotations.json' in zipfile.ZipFile(target).namelist()
    assert 'annotations.html' in zipfile.ZipFile(target).namelist()
    with pytest.raises(ValueError,match='Duplicate'):analyze_obd([target,Path(row['folder'])/'original-research.zip'])
    from mokka_ecu_lab.analysis.dpf import analyze_dpf
    with pytest.raises(ValueError,match='Duplicate'):analyze_dpf([target,Path(row['folder'])/'original-research.zip'])
    other=ReportLibrary(tmp_path/'other data');out=other.publish_bundle(target)
    assert read_bundle(out['bundle_path'])[0]==original_identity
    other.export_run(out['library_id'],tmp_path/'second-wrapper.zip') # no nested wrapper accumulation
    assert lib.usage()['runs']==6 and not lib.usage()['automatic_purge']

def test_missing_companion_preserved_partial_and_truly_offline_retry(tmp_path,legacy):
    bundle=next(legacy.glob('*.zip'));source=digest(bundle);lib=ReportLibrary(tmp_path/'library')
    out=lib.publish_bundle(bundle,{'.json':bundle.with_suffix('.json')})
    assert out['report_status']=='EXPORT_PARTIAL' and not out['checksums_verified'] and not out['obd_report_path']
    row=lib.get(out['library_id']);preserved=Path(row['folder'])/'source-report.json';saved=digest(preserved)
    retried=lib.retry(out['library_id']);assert retried['checksums_verified']
    assert digest(preserved)==saved and digest(bundle)==source and len(lib.rows())==1

def test_interrupted_index_registration_recovers_without_overwriting(tmp_path,legacy,monkeypatch):
    lib=ReportLibrary(tmp_path/'library');bundle=next(legacy.glob('*.zip'));original=lib._register
    def interrupt(*a,**k):raise OSError('Constructed interruption after atomic directory rename')
    monkeypatch.setattr(lib,'_register',interrupt)
    with pytest.raises(OSError):lib.publish_bundle(bundle)
    assert not lib.rows()
    monkeypatch.setattr(lib,'_register',original);lib.recover_index()
    assert len(lib.rows())==1
    out=lib.publish_bundle(bundle);assert len(lib.rows())==1 and out['checksums_verified']

def test_preview_changed_input_and_tampered_plan_are_rejected(tmp_path,legacy):
    lib=ReportLibrary(tmp_path/'library');plan=lib.preview_migration(legacy)
    plan['destination']=str(tmp_path/'escape')
    with pytest.raises(ValueError):lib.migrate(plan,plan['approval_token'])
    plan=lib.preview_migration(legacy);path=Path(plan['groups'][0]['sources'][0]['path']);path.write_bytes(b'constructed changed input')
    with pytest.raises(ValueError,match='changed'):lib.migrate(plan,plan['approval_token'])
    assert not lib.rows()

def test_wrapper_tampering_no_overwrite_or_hidden_extra_member(tmp_path,legacy):
    lib=ReportLibrary(tmp_path/'library');out=lib.publish_bundle(next(legacy.glob('*.zip')))
    target=lib.export_run(out['library_id'],tmp_path/'wrapper.zip')
    with pytest.raises(ValueError):lib.export_run(out['library_id'],target)
    with zipfile.ZipFile(target,'a') as z:z.writestr('../unexpected.txt','never extract')
    with pytest.raises(ValueError,match='wrapper'):read_bundle(target)
    folder=Path(lib.get(out['library_id'])['folder']);(folder/'report.html').write_text('constructed corruption')
    with pytest.raises(ValueError,match='changed'):lib.verify(out['library_id'])

def test_zero_send_preflight_research_html_preserves_absence_of_ecu(tmp_path,legacy):
    from mokka_ecu_lab.research.evidence import analyze_bundles
    from mokka_ecu_lab.research.report import render_html
    lib=ReportLibrary(tmp_path/'data')
    for b in legacy.glob('*.zip'):lib.publish_bundle(b)
    row=next(r for r in lib.rows() if r['status']=='FAILED_COM_OPEN')
    wrapper=lib.export_run(row['library_id'],tmp_path/'failed-private-run.zip')
    report=analyze_bundles([wrapper]);assert not report['sessions'][0]['groups']
    page=render_html(report)
    assert 'no observed ECU/source group' in page and 'not a measured ECU failure' in page
    with pytest.raises(ValueError,match='existing'):render_html(report,selection=(0,0))

@pytest.mark.parametrize('value',[float('nan'),float('inf'),-1,True,4000])
def test_annotation_uncertainty_is_explicit_finite_and_bounded(tmp_path,legacy,value):
    lib=ReportLibrary(tmp_path/'library');out=lib.publish_bundle(next(legacy.glob('*.zip')))
    with pytest.raises(ValueError):lib.annotate(out['library_id'],'Sport on','2001-02-03T00:00:00+00:00',value)
