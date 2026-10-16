"""Constructed portable ZIPs only; no real executable launch or maintenance."""
from pathlib import Path
import json,zipfile
import pytest
from mokka_ecu_lab.versions import ManagedVersions,REPOSITORY
from mokka_ecu_lab.library import digest

def artifact(tmp_path,tag='v1.0.0',extra=None):
    path=tmp_path/(tag+'.zip')
    with zipfile.ZipFile(path,'w') as z:
        z.writestr('MokkaECULab/MokkaECULab.exe',b'MZ_CONSTRUCTED_NOT_EXECUTABLE_'+tag.encode())
        z.writestr('MokkaECULab/_internal/PySide6/Qt6Core.dll',b'constructed Qt placeholder')
        z.writestr('MokkaECULab/_internal/python312.dll',b'constructed Python placeholder')
        if extra:z.writestr(extra,b'constructed unsafe member')
    return path,dict(tag=tag,repository=REPOSITORY,sha256=digest(path),bytes=path.stat().st_size,asset=f'MokkaECULab-{tag}-Windows11-x64.zip',url=f'https://github.com/{REPOSITORY}/releases/download/{tag}/MokkaECULab-{tag}-Windows11-x64.zip',trust='OFFICIAL_GITHUB_RELEASE_DIGEST')

def install(manager,path,release):
    plan=manager.preview_install(path,release)
    return manager.install(plan,plan['approval_token'],smoke=lambda exe:dict(exit_code=0,constructed=True))

def activate(manager,key):
    plan=manager.preview_activation(key);return manager.activate(plan,plan['approval_token'])

def test_current_previous_rollback_and_no_user_data_change(tmp_path):
    data=tmp_path/'personal Ω data';data.mkdir();journal=data/'untouchable.jsonl';journal.write_bytes(b'constructed original evidence');sha=digest(journal)
    manager=ManagedVersions(tmp_path/'managed builds Ω',data)
    a,ra=artifact(tmp_path);b,rb=artifact(tmp_path,'v1.0.1')
    one=install(manager,a,ra);assert manager.state()['current'] is None
    assert activate(manager,one['key'])==dict(current=one['key'],previous=None)
    two=install(manager,b,rb);state=activate(manager,two['key']);assert state==dict(current=two['key'],previous=one['key'])
    plan=manager.preview_activation(one['key']);manager.rollback(plan['approval_token'])
    assert manager.state()==dict(current=one['key'],previous=two['key']) and digest(journal)==sha
    assert len(list(manager.builds.iterdir()))==2

def test_hash_approval_corrupt_build_and_extra_user_file_guards(tmp_path):
    manager=ManagedVersions(tmp_path/'builds',tmp_path/'data');path,release=artifact(tmp_path)
    plan=manager.preview_install(path,release)
    with pytest.raises(ValueError,match='Approve'):manager.install(plan,'unapproved')
    row=install(manager,path,release);folder=Path(row['folder']);(folder/'user-added.txt').write_text('preserve me')
    with pytest.raises(ValueError,match='Unknown'):manager.preview_activation(row['key'])
    assert (folder/'user-added.txt').read_text()=='preserve me' and manager.state()['current'] is None
    changed=dict(release,sha256='0'*64)
    with pytest.raises(ValueError,match='mismatch'):manager.preview_install(path,changed)

def test_interrupted_or_failed_upgrade_does_not_switch_or_remove_rollback(tmp_path):
    manager=ManagedVersions(tmp_path/'builds',tmp_path/'data');a,ra=artifact(tmp_path);one=install(manager,a,ra);activate(manager,one['key'])
    b,rb=artifact(tmp_path,'v1.0.1');plan=manager.preview_install(b,rb)
    def fail(exe):raise OSError('Constructed smoke/startup failure')
    with pytest.raises(OSError):manager.install(plan,plan['approval_token'],smoke=fail)
    assert manager.state()['current']==one['key'] and manager.verify(one['key'])['verified']
    assert list((manager.root/'Staging').iterdir()) # partial staging preserved for inspection
    (manager.root/'operation.lock').write_text('{"pid":99999999}')
    with pytest.raises(ValueError,match='lock'):manager.install(plan,plan['approval_token'],smoke=fail)
    assert (manager.root/'operation.lock').is_file()

@pytest.mark.parametrize('member',['../escape.exe','MokkaECULab/CON.txt','MokkaECULab/_internal/a.','MokkaECULab/data/private.jsonl','MokkaECULab/_internal/../../escape','MokkaECULab/_internal/C:bad'])
def test_unsafe_zip_never_installed(tmp_path,member):
    path,release=artifact(tmp_path,extra=member);manager=ManagedVersions(tmp_path/'managed',tmp_path/'data')
    with pytest.raises(ValueError):manager.preview_install(path,release)
    assert not manager.root.exists()

def test_protected_roots_and_pointer_tampering(tmp_path):
    with pytest.raises(ValueError,match='separate'):ManagedVersions(tmp_path/'data/versions',tmp_path/'data')
    repo=tmp_path/'repo';(repo/'.git').mkdir(parents=True)
    with pytest.raises(ValueError,match='Git'):ManagedVersions(repo/'builds',tmp_path/'data')
    manager=ManagedVersions(tmp_path/'managed',tmp_path/'data');manager.root.mkdir();manager.pointer.write_text('{"current":"../../escape","previous":null}')
    with pytest.raises(ValueError,match='identity'):manager.state()

def test_launch_failure_rolls_pointer_back_without_touching_builds(tmp_path,monkeypatch):
    import mokka_ecu_lab.versions as module
    manager=ManagedVersions(tmp_path/'builds',tmp_path/'data');a,ra=artifact(tmp_path);b,rb=artifact(tmp_path,'v1.0.1');one=install(manager,a,ra);activate(manager,one['key']);two=install(manager,b,rb);activate(manager,two['key'])
    monkeypatch.setattr(module,'running_executables',lambda:dict(processes=[],inaccessible_processes=0))
    class Failed:
        def wait(self,timeout):return 5
    monkeypatch.setattr(module.subprocess,'Popen',lambda *a,**k:Failed())
    with pytest.raises(ValueError,match='rolled back'):manager.launch_current()
    assert manager.state()['current']==one['key'] and manager.verify(two['key'])['verified']
