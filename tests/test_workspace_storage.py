"""New constructed workspace trees only; no actual developer output is touched."""
import json,subprocess
from pathlib import Path
import pytest
from mokka_ecu_lab.workspace import WorkspaceStorage,tree_snapshot,fingerprint

@pytest.fixture
def storage(tmp_path):
    repo=tmp_path/'OneDrive-like Ελληνικό workspace';repo.mkdir();subprocess.run(['git','init',str(repo)],capture_output=True,check=True)
    root=repo/'release';root.mkdir();return WorkspaceStorage(root)

def folder(storage,name):
    p=storage.root/name;p.mkdir();(p/'generated.txt').write_text('NEW CONSTRUCTED fixture '+name);return p

def test_545_entry_inventory_is_read_only_and_processes_protected(storage,tmp_path):
    for i in range(545):folder(storage,'constructed-qa-'+str(i))
    selected=storage.root/'constructed-qa-3';before=tree_snapshot(selected)
    inv=storage.inventory(keep=[selected],processes=dict(processes=[dict(pid=77,path=str(storage.root/'constructed-qa-5/app.exe'))]))
    assert inv['entry_count']==545 and len(list(storage.root.iterdir()))==545
    assert sum(x['action']=='KEEP' for x in inv['entries'])==2
    assert tree_snapshot(selected)==before and not inv['automatic_cleanup']
    with pytest.raises(ValueError):storage.preview_quarantine(inv,tmp_path/'quarantine',[selected])

def test_approval_quarantine_cancel_resume_restore_all_bytes(storage,tmp_path):
    paths=[folder(storage,'new-'+str(i)) for i in range(3)];before={str(p):tree_snapshot(p) for p in paths}
    plan=storage.preview_quarantine(storage.inventory(processes=dict(processes=[])),tmp_path/'private quarantine',paths)
    assert plan['disk_bytes_freed']==0
    with pytest.raises(ValueError):storage.execute(plan,'not approved')
    calls=[]
    partial=storage.execute(plan,plan['approval_token'],cancel=lambda:len(calls)>0 or calls.append(1))
    assert partial['state']=='CANCELLED_PRESERVED' and len(partial['completed'])==1
    done=storage.execute(plan,plan['approval_token']);assert done['state']=='COMPLETE' and not list(storage.root.iterdir())
    restore=storage.preview_restore(Path(plan['destination'])/'operation.json');storage.restore(restore,restore['approval_token'])
    assert all(tree_snapshot(p)==before[str(p)] for p in paths)

def test_changed_source_or_destination_race_never_moves(storage,tmp_path):
    p=folder(storage,'new');plan=storage.preview_quarantine(storage.inventory(processes=dict(processes=[])),tmp_path/'private',[p])
    (p/'added-user-file.txt').write_text('keep')
    with pytest.raises(ValueError,match='changed'):storage.execute(plan,plan['approval_token'])
    assert p.exists() and (p/'added-user-file.txt').exists()

def test_rename_before_checkpoint_resume(storage,tmp_path):
    p=folder(storage,'new');plan=storage.preview_quarantine(storage.inventory(processes=dict(processes=[])),tmp_path/'private',[p]);dest=Path(plan['destination']);dest.mkdir()
    from mokka_ecu_lab.library import write_json
    write_json(dest/'operation.json',dict(plan=plan,completed=[],state='IN_PROGRESS'));p.rename(dest/p.name)
    result=storage.execute(plan,plan['approval_token']);assert result['state']=='COMPLETE' and len(result['completed'])==1

def test_tracked_and_wrong_root_are_protected(storage,tmp_path):
    p=folder(storage,'tracked');subprocess.run(['git','-C',str(storage.repo),'add','-f',str(p)],capture_output=True,check=True)
    inv=storage.inventory(processes=dict(processes=[]));assert inv['entries'][0]['git_tracked'] and inv['entries'][0]['action']=='KEEP'
    with pytest.raises(ValueError):WorkspaceStorage(tmp_path)

@pytest.mark.parametrize('record',['[]','null','42','"unknown journal record"','{"mode":"SIMULATED"}'])
def test_unknown_nontransaction_journal_is_kept_without_aborting_inventory(storage,tmp_path,record):
    journal=storage.root/'unknown-journal.jsonl';journal.write_text(record+'\n',encoding='utf-8')
    other=folder(storage,'constructed-generated-output');before=tree_snapshot(journal)
    inv=storage.inventory(processes=dict(processes=[]));rows={Path(r['path']).name:r for r in inv['entries']}
    assert rows[journal.name]['action']=='KEEP' and rows[journal.name]['protected_evidence']==['.']
    assert rows[other.name]['action']=='REVIEW' and tree_snapshot(journal)==before
    with pytest.raises(ValueError,match='Protected'):
        storage.preview_quarantine(inv,tmp_path/'quarantine',[journal])

def test_unknown_record_among_simulated_transactions_is_still_protected(storage):
    journal=storage.root/'mixed-journal.jsonl'
    journal.write_text('{"record_type":"transaction","mode":"SIMULATED"}\n[]\n',encoding='utf-8')
    inv=storage.inventory(processes=dict(processes=[]))
    assert inv['entries'][0]['action']=='KEEP'

def test_top_level_private_note_basename_is_protected(storage):
    note=storage.root/'PRIVATE-constructed-note.md';note.write_text('Synthetic note: no vehicle data')
    inv=storage.inventory(processes=dict(processes=[]))
    assert inv['entries'][0]['action']=='KEEP' and inv['entries'][0]['protected_evidence']==['.']

@pytest.mark.parametrize('attribute',[0x1000,0x40000,0x400000])
def test_cloud_placeholder_never_opens_or_hydrates_file(tmp_path,monkeypatch,attribute):
    from types import SimpleNamespace
    path=tmp_path/'constructed-cloud-file';path.write_bytes(b'constructed placeholder')
    real_stat=Path.stat;real_open=Path.open
    def marked_stat(p,*args,**kwargs):
        value=real_stat(p,*args,**kwargs)
        if p==path:return SimpleNamespace(st_size=value.st_size,st_mtime_ns=value.st_mtime_ns,st_file_attributes=attribute)
        return value
    def block_open(p,*args,**kwargs):
        if p==path:raise AssertionError('Placeholder must be rejected before content is read')
        return real_open(p,*args,**kwargs)
    monkeypatch.setattr(Path,'stat',marked_stat);monkeypatch.setattr(Path,'open',block_open)
    with pytest.raises(ValueError,match='no automatic hydration'):fingerprint(path)

def test_restore_rename_before_checkpoint_needs_exact_approval_and_resumes(storage,tmp_path):
    paths=[folder(storage,'restore-'+str(i)) for i in range(2)]
    before={str(p):tree_snapshot(p) for p in paths}
    plan=storage.preview_quarantine(storage.inventory(processes=dict(processes=[])),tmp_path/'private quarantine',paths)
    storage.execute(plan,plan['approval_token']);destination=Path(plan['destination']);receipt=destination/'operation.json'
    # Construct the interruption window: the atomic return succeeded, its receipt did not.
    (destination/paths[0].name).rename(paths[0]);receipt_before=receipt.read_bytes()
    restore=storage.preview_restore(receipt)
    assert restore['recovered_completed']==[str(paths[0])]
    assert [r['source'] for r in restore['entries']]==[str(paths[1])]
    assert receipt.read_bytes()==receipt_before and not paths[1].exists()
    with pytest.raises(ValueError,match='Approve'):storage.restore(restore,'not approved')
    assert receipt.read_bytes()==receipt_before and not paths[1].exists()
    result=storage.restore(restore,restore['approval_token'])
    assert result['state']=='RESTORED' and result['completed']==[]
    assert all(tree_snapshot(p)==before[str(p)] for p in paths)

def test_restore_collision_preserves_new_source_and_quarantined_original(storage,tmp_path):
    path=folder(storage,'restore-collision');before=tree_snapshot(path)
    plan=storage.preview_quarantine(storage.inventory(processes=dict(processes=[])),tmp_path/'private quarantine',[path])
    storage.execute(plan,plan['approval_token']);target=Path(plan['destination'])/path.name
    path.mkdir();(path/'new-personal-note.txt').write_text('Constructed newer file: preserve')
    with pytest.raises(ValueError,match='collision'):storage.preview_restore(Path(plan['destination'])/'operation.json')
    assert tree_snapshot(target)==before and (path/'new-personal-note.txt').read_text()=='Constructed newer file: preserve'

def test_cancelled_restore_preserves_both_locations_and_resumes_after_fresh_approval(storage,tmp_path):
    paths=[folder(storage,'cancel-restore-'+str(i)) for i in range(2)]
    before={str(p):tree_snapshot(p) for p in paths}
    quarantine=storage.preview_quarantine(storage.inventory(processes=dict(processes=[])),tmp_path/'quarantine',paths)
    storage.execute(quarantine,quarantine['approval_token']);dest=Path(quarantine['destination']);receipt=dest/'operation.json'
    plan=storage.preview_restore(receipt);checks=0
    def cancel_after_one():
        nonlocal checks
        checks+=1;return checks>1
    partial=storage.restore(plan,plan['approval_token'],cancel=cancel_after_one)
    assert partial['state']=='RESTORE_CANCELLED_PRESERVED' and len(partial['completed'])==1
    assert sum(p.exists() for p in paths)==1
    for p in paths:assert tree_snapshot(p if p.exists() else dest/p.name)==before[str(p)]
    resume=storage.preview_restore(receipt)
    assert len(resume['entries'])==1
    with pytest.raises(ValueError,match='Approve'):storage.restore(resume,plan['approval_token'])
    done=storage.restore(resume,resume['approval_token'])
    assert done['state']=='RESTORED' and done['completed']==[]
    assert all(tree_snapshot(p)==before[str(p)] for p in paths)

def test_executable_becoming_running_in_archive_blocks_remaining_restore_items(storage,tmp_path,monkeypatch):
    import mokka_ecu_lab.workspace as module
    paths=[folder(storage,'running-restore-'+str(i)) for i in range(2)]
    for p in paths:(p/'app.exe').write_bytes(b'MZ_CONSTRUCTED_NOT_EXECUTABLE')
    before={str(p):tree_snapshot(p) for p in paths}
    quarantine=storage.preview_quarantine(storage.inventory(processes=dict(processes=[])),tmp_path/'quarantine',paths)
    storage.execute(quarantine,quarantine['approval_token']);dest=Path(quarantine['destination']);receipt=dest/'operation.json'
    plan=storage.preview_restore(receipt);checks=0
    def running_after_first_item():
        nonlocal checks
        checks+=1
        return dict(processes=[] if checks==1 else [dict(pid=777,path=str(dest/paths[1].name/'app.exe'))])
    with monkeypatch.context() as patch:
        patch.setattr(module,'running_executables',running_after_first_item)
        with pytest.raises(ValueError,match='Archived executable is running'):storage.restore(plan,plan['approval_token'])
    assert paths[0].exists() and not paths[1].exists()
    assert tree_snapshot(paths[0])==before[str(paths[0])] and tree_snapshot(dest/paths[1].name)==before[str(paths[1])]
    assert json.loads(receipt.read_text(encoding='utf-8'))['completed']==[str(paths[1])]
    resume=storage.preview_restore(receipt);storage.restore(resume,resume['approval_token'])
    assert all(tree_snapshot(p)==before[str(p)] for p in paths)
