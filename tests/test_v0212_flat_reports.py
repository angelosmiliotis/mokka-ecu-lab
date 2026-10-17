"""Fresh fabricated reports: flat output, approved copy migration and index rollback."""
from datetime import datetime,timedelta
from pathlib import Path
import json
import time
import pytest
from test_library import legacy
from test_ui_freshness import window
from mokka_ecu_lab.library import ReportLibrary,MigrationCancelled,digest,recent_title,write_json
from mokka_ecu_lab.logging import Recorder,connect_database
from mokka_ecu_lab.logging.bundle import export_research_bundle


def snapshot(folder):return {str(p.relative_to(folder)):digest(p) for p in folder.rglob('*') if p.is_file()}


@pytest.fixture
def deep(tmp_path,legacy):
    library=ReportLibrary(tmp_path/'OneDrive-like Ω data root')
    for bundle in legacy.glob('*.zip'):library.publish_bundle(bundle)
    # Only these newly constructed tmp_path copies are rearranged to emulate v0.2.11.
    for row in library.rows():
        current=Path(row['folder']);stamp=datetime.fromisoformat(row['started_local'])
        previous=current.parent/stamp.strftime('%Y/%m/%d')/current.name;previous.parent.mkdir(parents=True,exist_ok=True);current.rename(previous)
        metadata=json.loads((previous/'run-metadata.json').read_text(encoding='utf-8'));metadata['schema_version']=1;metadata.pop('duration_seconds',None);write_json(previous/'run-metadata.json',metadata)
        with library.db() as db:db.execute('UPDATE runs SET path=?,metadata=? WHERE id=?',(previous.relative_to(library.reports).as_posix(),json.dumps(metadata),row['library_id']))
    return library


def test_new_outputs_are_flat_exactly_four_and_reimport_does_not_copy_again(tmp_path,legacy):
    library=ReportLibrary(tmp_path/'flat')
    for bundle in legacy.glob('*.zip'):library.publish_bundle(bundle)
    before=snapshot(library.reports)
    for row in library.rows():
        folder=Path(row['folder']);assert len(folder.relative_to(library.reports).parts)==2
        assert {p.name for p in folder.iterdir()}=={'original-research.zip','report.json','report.html','run-metadata.json'}
        assert recent_title(row).startswith(datetime.fromisoformat(row['started_local']).strftime('%d '))
        assert 'PASS' in recent_title(row) if row['status']=='COMPLETED' else row['status'] in recent_title(row)
        wrapper=library.export_run(row['library_id'],tmp_path/(row['library_id']+'-share.zip'))
        library.publish_bundle(wrapper)
    assert snapshot(library.reports)==before


def test_deep_preview_copy_rebase_dedup_labels_notes_and_pointer_rollback(deep):
    rows=deep.rows();first=rows[0];deep.label(first['library_id'],'Constructed Ω test')
    note=deep.annotate(first['library_id'],'Note','2002-03-04T05:06:07+00:00',15,'Synthetic only')
    original=snapshot(deep.reports);plan=deep.preview_flatten()
    assert snapshot(deep.reports)==original and len(plan['groups'])==6
    assert plan['copy_bytes']==sum(g['bytes'] for g in plan['groups'])
    for group in plan['groups']:
        assert len(Path(group['source_folder']).relative_to(deep.reports).parts)==5
        assert len(Path(group['destination_folder']).relative_to(deep.reports).parts)==2
        assert len(group['sources'])==4 and all(f['bytes'] and len(f['sha256'])==64 for f in group['sources'])
    with pytest.raises(ValueError,match='approval'):deep.migrate(plan,'unapproved')
    outputs=deep.migrate(plan,plan['approval_token']);assert deep.migrate(plan,plan['approval_token'])==outputs
    assert len(deep.rows())==6 and all(len(Path(r['folder']).relative_to(deep.reports).parts)==2 for r in deep.rows())
    assert deep.get(first['library_id'])['display_label']=='Constructed Ω test' and deep.annotations(first['library_id'])==[note]
    assert all(digest(deep.reports/path)==sha for path,sha in original.items())
    rollback=deep.preview_migration_rollback(plan['approval_token'])
    with pytest.raises(ValueError):deep.rollback_migration(rollback,'unapproved')
    assert deep.rollback_migration(rollback,rollback['approval_token'])==dict(restored=6,files_deleted=0,files_moved=0)
    assert all(len(Path(r['folder']).relative_to(deep.reports).parts)==5 for r in deep.rows())
    deep.recover_index();assert all(len(Path(r['folder']).relative_to(deep.reports).parts)==5 for r in deep.rows())
    assert deep.get(first['library_id'])['display_label']=='Constructed Ω test' and deep.annotations(first['library_id'])==[note]
    again=deep.preview_flatten();deep.migrate(again,again['approval_token']);assert len(deep.rows())==6


def test_cancelled_copy_resumes_without_extra_report_storage(deep):
    plan=deep.preview_flatten();original=snapshot(deep.reports);calls=0
    def cancel():
        nonlocal calls
        calls+=1;return calls>=4
    with pytest.raises(MigrationCancelled):deep.migrate(plan,plan['approval_token'],cancelled=cancel)
    assert all(digest(deep.reports/path)==sha for path,sha in original.items())
    assert deep.migrations()[0]['state']=='CANCELLED'
    deep.migrate(plan,plan['approval_token']);after=snapshot(deep.reports)
    assert len(deep.rows())==6 and not list((deep.reports/'.staging').rglob('*.zip'))
    deep.migrate(plan,plan['approval_token']);assert snapshot(deep.reports)==after


def test_interruption_after_verified_copy_can_resume_index_registration(deep,monkeypatch):
    plan=deep.preview_flatten();original=deep.db;calls=0
    from contextlib import contextmanager
    @contextmanager
    def fail_once():
        nonlocal calls
        calls+=1
        if calls==1:raise OSError('Constructed interruption after verified directory rename')
        with original() as db:yield db
    with monkeypatch.context() as patch:
        patch.setattr(deep,'db',fail_once)
        with pytest.raises(OSError):deep.migrate(plan,plan['approval_token'])
    assert Path(plan['groups'][0]['destination_folder']).is_dir()
    deep.migrate(plan,plan['approval_token']);assert len(deep.rows())==6


def test_missing_or_changed_source_and_destination_collision_are_blocked(deep):
    plan=deep.preview_flatten();source=Path(plan['groups'][0]['sources'][0]['path']);source.write_bytes(b'new synthetic corruption')
    with pytest.raises(ValueError):deep.migrate(plan,plan['approval_token'])
    blocked=deep.preview_flatten();assert any(g.get('action')=='NO ACTION' for g in blocked['groups'])


def test_copy_target_collision_is_not_overwritten_and_preview_stays_read_only(deep):
    plan=deep.preview_flatten();target=Path(plan['groups'][0]['destination_folder']);target.mkdir(parents=True)
    sentinel=target/'operator-note.txt';sentinel.write_text('Constructed unknown data; keep me',encoding='utf-8');before=snapshot(deep.reports)
    checked=deep.preview_flatten();assert any(g.get('blocked') for g in checked['groups'])
    assert snapshot(deep.reports)==before
    with pytest.raises((ValueError,OSError)):deep.migrate(plan,plan['approval_token'])
    assert sentinel.read_text(encoding='utf-8')=='Constructed unknown data; keep me'


def test_partial_legacy_companion_backup_survives_copy_and_offline_repair(tmp_path,legacy):
    library=ReportLibrary(tmp_path/'partial');bundle=next(legacy.glob('*.zip'))
    out=library.publish_bundle(bundle,{'.json':bundle.with_suffix('.json')});row=library.get(out['library_id']);current=Path(row['folder'])
    stamp=datetime.fromisoformat(row['started_local']);old=current.parent/stamp.strftime('%Y/%m/%d')/current.name;old.parent.mkdir(parents=True);current.rename(old)
    with library.db() as db:db.execute('UPDATE runs SET path=? WHERE id=?',(old.relative_to(library.reports).as_posix(),row['library_id']))
    source_hash=digest(old/'source-report.json');plan=library.preview_flatten()
    assert plan['groups'][0]['preserved_legacy_companions']==['source-report.json']
    library.migrate(plan,plan['approval_token']);library.retry(row['library_id']);new=Path(library.get(row['library_id'])['folder'])
    assert digest(old/'source-report.json')==source_hash==digest(new/'source-report.json')
    assert library.verify(row['library_id'])['status']==row['outcome']


def test_rollback_refuses_changed_canonical_pointer_without_changing_files(deep):
    plan=deep.preview_flatten();deep.migrate(plan,plan['approval_token']);rollback=deep.preview_migration_rollback(plan['approval_token'])
    group=plan['groups'][0]
    with deep.db() as db:db.execute('UPDATE runs SET path=? WHERE id=?',(Path(group['source_folder']).relative_to(deep.reports).as_posix(),group['library_id']))
    before=snapshot(deep.reports)
    with pytest.raises(ValueError,match='pointer'):deep.rollback_migration(rollback,rollback['approval_token'])
    assert snapshot(deep.reports)==before


def test_unindexed_flat_and_deep_recovery_prefers_one_flat_identity(deep):
    plan=deep.preview_flatten();deep.migrate(plan,plan['approval_token'])
    with deep.db() as db:db.execute('DELETE FROM runs')
    deep.recover_index();assert len(deep.rows())==6
    assert all(len(Path(r['folder']).relative_to(deep.reports).parts)==2 for r in deep.rows())


def test_existing_verified_canonical_with_distinct_derived_html_is_reused(deep):
    plan=deep.preview_flatten();deep.migrate(plan,plan['approval_token']);rollback=deep.preview_migration_rollback(plan['approval_token']);deep.rollback_migration(rollback,rollback['approval_token'])
    group=plan['groups'][0];target=Path(group['destination_folder']);html=target/'report.html';html.write_text(html.read_text(encoding='utf-8')+'\n<!-- constructed newer derived view -->',encoding='utf-8')
    metadata=json.loads((target/'run-metadata.json').read_text(encoding='utf-8'));metadata['hashes']['report.html']=digest(html);write_json(target/'run-metadata.json',metadata)
    before=snapshot(deep.reports);preview=deep.preview_flatten()
    assert preview['copy_bytes']==0 and all(g['copy_mode']=='REUSE_VERIFIED_CANONICAL' for g in preview['groups'])
    deep.migrate(preview,preview['approval_token']);assert snapshot(deep.reports)==before and len(deep.rows())==6
    assert deep.verify(group['library_id'])['hashes']['report.html']==digest(html)


def test_athens_dst_same_wall_second_has_distinct_identity_and_exact_utc(tmp_path):
    data=tmp_path/'journals';library=ReportLibrary(tmp_path/'reports')
    for index,start in enumerate(('2030-10-27T00:30:00+00:00','2030-10-27T01:30:00+00:00')):
        recorder=Recorder(data,'SIMULATED',{});recorder.close()
        with connect_database(data) as db:db.execute('UPDATE sessions SET started=?,ended=? WHERE id=?',(start,(datetime.fromisoformat(start)+timedelta(seconds=12)).isoformat(),recorder.id))
        bundle=tmp_path/f'constructed-{index}.zip';export_research_bundle(data,recorder.id,bundle);library.publish_bundle(bundle)
    rows=library.rows();assert len({r['folder'] for r in rows})==2
    assert {r['started_local'] for r in rows}=={'2030-10-27T03:30:00+03:00','2030-10-27T03:30:00+02:00'}
    assert all(len(Path(r['folder']).relative_to(library.reports).parts)==2 for r in rows)


def test_history_titles_sort_and_organize_menu_never_request_obd(window,legacy,qt_app,monkeypatch):
    panel=window.history_panel;deadline=time.monotonic()+5
    while panel.jobs.future is not None and time.monotonic()<deadline:qt_app.processEvents();time.sleep(.01)
    plan=panel.library.preview_migration(legacy);panel.library.migrate(plan,plan['approval_token']);panel.loaded(panel.library.rows());calls=[]
    with monkeypatch.context() as patch:
        patch.setattr(window.worker,'submit',lambda *args,**kwargs:calls.append(args))
        assert panel.table.rowCount()==6 and ' · ' in panel.table.item(0,0).text()
        newest=[r['library_id'] for r in panel.visible];panel.sort.setCurrentText('Oldest first')
        assert [r['library_id'] for r in panel.visible]==list(reversed(newest))
        assert {'Flatten existing Reports…','Rollback report migration…','Cancel copy migration'}<=set(a.text() for a in panel.storage_menu.actions())
        assert calls==[]


def test_history_resumes_preserved_checkpoint_after_restart_only_after_new_approval(deep,window,qt_app,monkeypatch):
    import mokka_ecu_lab.ui.library as ui_module
    plan=deep.preview_flatten();calls=0
    def cancel():
        nonlocal calls
        calls+=1;return calls>=4
    with pytest.raises(MigrationCancelled):deep.migrate(plan,plan['approval_token'],cancelled=cancel)
    stages=list((deep.reports/'.staging').iterdir());assert len(stages)==1
    copied_before=snapshot(deep.reports);audit_before=deep._audit_path(plan['approval_token']).read_bytes()
    panel=window.history_panel
    def wait_jobs():
        deadline=time.monotonic()+15
        while panel.jobs.future is not None and time.monotonic()<deadline:qt_app.processEvents();time.sleep(.005)
        assert panel.jobs.future is None
    wait_jobs()
    # Reopen the same library without retaining the in-memory preview from the interrupted run.
    panel.library=ReportLibrary(deep.root)
    previews=[];obd=[]
    with monkeypatch.context() as patch:
        patch.setattr(window.worker,'submit',lambda *a,**kw:obd.append(a))
        patch.setattr(ui_module.QInputDialog,'getItem',lambda parent,title,prompt,items,**kw:(items[0],True))
        patch.setattr(ui_module,'preview_dialog',lambda parent,title,p,approve=None,**kw:previews.append((title,p,approve)))
        assert 'Resume report migration…' in {a.text() for a in panel.storage_menu.actions()}
        panel.resume_migration();wait_jobs()
        title,reviewed,approve=previews[-1]
        assert 'RESUME' in title and reviewed==plan
        assert snapshot(deep.reports)==copied_before and deep._audit_path(plan['approval_token']).read_bytes()==audit_before
        assert len(list(deep.index.glob('migration-*.json')))==1 and not obd
        approve();wait_jobs()
        assert len(deep.rows())==6 and all(len(Path(r['folder']).relative_to(deep.reports).parts)==2 for r in deep.rows())
        assert len(list(deep.index.glob('migration-*.json')))==1
        assert not list((deep.reports/'.staging').iterdir()) and deep.migrations()[0]['state']=='COMPLETED'
        assert not obd


def test_history_checkpoint_selection_cancel_and_changed_plan_do_not_resume(deep,window,qt_app,monkeypatch):
    import mokka_ecu_lab.ui.library as ui_module
    plan=deep.preview_flatten()
    with pytest.raises(MigrationCancelled):deep.migrate(plan,plan['approval_token'],cancelled=lambda:True)
    panel=window.history_panel;deadline=time.monotonic()+5
    while panel.jobs.future is not None and time.monotonic()<deadline:qt_app.processEvents();time.sleep(.005)
    panel.library=ReportLibrary(deep.root);before=snapshot(deep.reports);previews=[]
    monkeypatch.setattr(ui_module.QInputDialog,'getItem',lambda parent,title,prompt,items,**kw:(items[0],False))
    monkeypatch.setattr(ui_module,'preview_dialog',lambda *a,**kw:previews.append(a))
    panel.choose_resume(deep.migrations())
    assert previews==[] and snapshot(deep.reports)==before
    path=deep._audit_path(plan['approval_token']);record=json.loads(path.read_text(encoding='utf-8'))
    record['plan']['groups'][0]['destination_folder']=str(deep.reports/'unapproved destination');write_json(path,record)
    with pytest.raises(ValueError,match='approval'):panel.saved_migration_plan(plan['approval_token'])
    assert previews==[] and snapshot(deep.reports)==before
