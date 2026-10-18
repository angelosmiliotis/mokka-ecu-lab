"""Entirely constructed ZIP/shortcut fixtures; no owner paths or real executables."""
import json,zipfile
from pathlib import Path
import pytest
from mokka_ecu_lab.versions import ManagedVersions,REPOSITORY
from mokka_ecu_lab.launcher import CurrentLauncher
from mokka_ecu_lab.upgrade import ApprovedUpgrade
from mokka_ecu_lab.library import digest

def artifact(root,tag):
    p=root/(tag+'.zip')
    with zipfile.ZipFile(p,'w') as z:
        for name,data in {'MokkaECULab.exe':b'MZ_CONSTRUCTED_GUI_'+tag.encode(),'_internal/python312.dll':b'constructed runtime','_internal/PySide6/Qt6Core.dll':b'constructed Qt','_internal/launcher/MokkaECULabLauncher.exe':b'MZ_CONSTRUCTED_HELPER_'+tag.encode()}.items():z.writestr('MokkaECULab/'+name,data)
    return p,dict(tag=tag,repository=REPOSITORY,sha256=digest(p),bytes=p.stat().st_size,trust='OFFICIAL_GITHUB_RELEASE_DIGEST',asset=p.name,url='CONSTRUCTED_NO_NETWORK')

def writer(path,target,directory,icon):
    Path(path).write_text(json.dumps(dict(target=str(target),directory=str(directory),icon=str(icon)+',0',arguments='')),encoding='utf-8')

def reader(paths):return [dict(json.loads(Path(p).read_text(encoding='utf-8')),path=str(Path(p).absolute())) for p in paths]
def smoke(_):return dict(exit_code=0,constructed=True)

@pytest.fixture
def prepared(tmp_path,monkeypatch):
    import mokka_ecu_lab.versions as versions
    import mokka_ecu_lab.upgrade as upgrade
    monkeypatch.setattr(versions,'running_executables',lambda:dict(processes=[],inaccessible_processes=0))
    monkeypatch.setattr(upgrade,'gui_processes',lambda:[])
    data=tmp_path/'private synthetic Ω';data.mkdir();sentinel=data/'preserve.txt';sentinel.write_bytes(b'constructed personal sentinel')
    m=ManagedVersions(tmp_path/'Versions Ω',data);l=CurrentLauncher(m,tmp_path/'Stable Ω')
    old,release=artifact(tmp_path,'v1.0.0');p=m.preview_install(old,release);row=m.install(p,p['approval_token'],smoke=smoke);a=m.preview_activation(row['key']);m.activate(a,a['approval_token'])
    desktop=tmp_path/'OneDrive redirected Desktop Ω';programs=tmp_path/'Start Menu Ω'
    p=l.preview(row['key'],desktop,programs,tmp_path/'previews',shortcut_writer=writer);l.install(p,p['approval_token'])
    new,release=artifact(tmp_path,'v1.0.1');u=ApprovedUpgrade(m,l)
    return dict(m=m,l=l,u=u,archive=new,release=release,desktop=desktop,programs=programs,sentinel=sentinel)

def preview(h):return h['u'].preview(h['archive'],h['release'],h['desktop'],h['programs'],reader=reader)
def execute(h,p,**kw):return h['u'].execute(p,p['approval_token'],smoke=smoke,reader=reader,dispatch_verifier=lambda:dict(exit_code=0,constructed=True),**kw)

def test_one_approval_installs_activates_preserves_same_links_and_rollback(prepared):
    h=prepared;old=h['m'].state();links={p:digest(p) for p in [h['desktop']/'Mokka ECU Lab.lnk',h['programs']/'Mokka ECU Lab.lnk']};before=digest(h['sentinel'])
    plan=preview(h);assert h['m'].state()==old and not h['m'].folder(plan['selected_key']).exists()
    result=execute(h,plan)
    assert result['completed'] and result['activated'] and result['verified_dispatch'] and not result['ordinary_gui_launch_verified']
    assert h['m'].state()==dict(current=plan['selected_key'],previous=old['current'])
    assert all(digest(p)==sha for p,sha in links.items()) and digest(h['sentinel'])==before
    back=h['u'].preview_installed(old['current'],h['desktop'],h['programs'],reader=reader);execute(h,back)
    assert h['m'].state()==dict(current=old['current'],previous=plan['selected_key'])

def test_same_version_repeat_is_idempotent(prepared):
    h=prepared;execute(h,preview(h));before=h['m'].state();p=preview(h)
    assert p['added_build_files']==0 and p['added_build_bytes']==0 and p['pointer_after']==before
    stamp=h['m'].pointer.stat().st_mtime_ns
    result=execute(h,p);assert h['m'].state()==before and h['m'].pointer.stat().st_mtime_ns==stamp and not result['activation_changed']

@pytest.mark.parametrize('change',['archive','shortcut','pointer','running'])
def test_changed_preview_or_running_gui_never_activates(prepared,monkeypatch,change):
    import mokka_ecu_lab.upgrade as module
    h=prepared;p=preview(h);old=h['m'].state()
    if change=='archive':h['archive'].write_bytes(b'constructed corrupt ZIP')
    elif change=='shortcut':(h['desktop']/'Mokka ECU Lab.lnk').write_bytes(b'personal conflicting shortcut preserved')
    elif change=='pointer':h['m'].pointer.write_text(json.dumps(dict(current=old['current'],previous=old['current'])))
    else:monkeypatch.setattr(module,'gui_processes',lambda:[dict(pid=123,path='CONSTRUCTED_GUI')])
    expected=h['m'].state()
    with pytest.raises((ValueError,json.JSONDecodeError)):execute(h,p)
    assert h['m'].state()==expected and not h['m'].folder(p['selected_key']).exists()

def test_wrong_approval_and_wrong_digest(prepared):
    h=prepared;p=preview(h)
    with pytest.raises(ValueError):h['u'].execute(p,'not-approved')
    with pytest.raises(ValueError):h['u'].preview(h['archive'],dict(h['release'],sha256='0'*64),h['desktop'],reader=reader)

@pytest.mark.parametrize('part',['selected_key','pointer_after'])
def test_even_reapproved_inconsistent_plan_cannot_copy_or_select_wrong_build(prepared,part):
    from mokka_ecu_lab.workspace import seal
    h=prepared;p=preview(h);p.pop('approval_token')
    if part=='selected_key':p['selected_key']=p['pointer_before']['current']
    else:p['pointer_after']=p['pointer_before']
    p=seal(p)
    with pytest.raises(ValueError,match='Inconsistent'):execute(h,p)
    assert h['m'].state()==p['pointer_before'] and not h['m'].folder(p['install']['key']).exists()

@pytest.mark.parametrize('fault',['smoke','dispatch','pointer_after_replace'])
def test_failed_update_restores_exact_pointer_and_preserves_files(prepared,monkeypatch,fault):
    import mokka_ecu_lab.upgrade as module
    h=prepared;p=preview(h);old=h['m'].state();links={str(x):digest(x) for x in [h['desktop']/'Mokka ECU Lab.lnk',h['programs']/'Mokka ECU Lab.lnk']}
    def fail(*_):raise OSError('Constructed transaction failure')
    original=module.write_json
    def replace_then_fail(path,value):
        original(path,value)
        if Path(path)==h['m'].pointer and value==p['pointer_after']:raise OSError('Constructed interruption after atomic replace')
    if fault=='pointer_after_replace':monkeypatch.setattr(module,'write_json',replace_then_fail)
    with pytest.raises(OSError):h['u'].execute(p,p['approval_token'],smoke=fail if fault=='smoke' else smoke,reader=reader,dispatch_verifier=fail if fault=='dispatch' else lambda:dict(exit_code=0))
    assert h['m'].state()==old and all(digest(x)==sha for x,sha in links.items()) and h['sentinel'].is_file()
    if fault!='smoke':assert h['m'].verify(p['selected_key'])['verified']

def test_fresh_launcher_and_conflicting_personal_shortcut(tmp_path,monkeypatch):
    import mokka_ecu_lab.versions as versions
    import mokka_ecu_lab.upgrade as module
    monkeypatch.setattr(versions,'running_executables',lambda:dict(processes=[],inaccessible_processes=0));monkeypatch.setattr(module,'gui_processes',lambda:[])
    m=ManagedVersions(tmp_path/'versions',tmp_path/'data');l=CurrentLauncher(m,tmp_path/'stable');u=ApprovedUpgrade(m,l);path,release=artifact(tmp_path,'v1.0.0');desktop=tmp_path/'Desktop Ω'
    p=u.preview(path,release,desktop,shortcut_writer=writer,reader=reader);assert not desktop.exists()
    result=u.execute(p,p['approval_token'],smoke=smoke,reader=reader,dispatch_verifier=lambda:dict(exit_code=0));assert result['completed'] and l.verify()['verified']
    (desktop/'Mokka ECU Lab.lnk').write_text(json.dumps(dict(target=str(tmp_path/'personal.exe'),directory=str(tmp_path),arguments='',icon='personal')),encoding='utf-8');before=digest(desktop/'Mokka ECU Lab.lnk')
    with pytest.raises(ValueError):u.preview(path,release,desktop,reader=reader)
    assert digest(desktop/'Mokka ECU Lab.lnk')==before

def test_explicit_preview_cancel_has_no_install_or_pointer_effect(prepared):
    h=prepared;before=h['m'].state();p=preview(h)
    assert h['m'].state()==before and not h['m'].folder(p['selected_key']).exists()
    assert h['l'].verify()['verified'] and h['sentinel'].read_bytes()==b'constructed personal sentinel'

def test_older_install_requires_explicit_rollback_not_accidental_upgrade(prepared):
    h=prepared;execute(h,preview(h));old=h['archive'].parent/'v1.0.0.zip';metadata=json.loads((h['m'].folder(h['m'].state()['previous'])/'install-metadata.json').read_text(encoding='utf-8'))['release']
    with pytest.raises(ValueError,match='older install'):h['u'].preview(old,metadata,h['desktop'],h['programs'],reader=reader)

def test_offline_official_metadata_failure_never_copies_or_activates(prepared,monkeypatch):
    from mokka_ecu_lab.upgrade import execute_saved_plan
    h=prepared;p=preview(h);saved=h['archive'].parent/'approved.json';receipt=h['archive'].parent/'result.json';saved.write_text(json.dumps(p),encoding='utf-8')
    def offline(_):raise OSError('Constructed offline metadata service')
    monkeypatch.setattr('mokka_ecu_lab.versions.release_info',offline)
    with pytest.raises(OSError,match='offline'):execute_saved_plan(saved,p['approval_token'],receipt)
    assert h['m'].state()==p['pointer_before'] and not h['m'].folder(p['selected_key']).exists() and json.loads(receipt.read_text(encoding='utf-8'))['completed'] is False

def test_noninteractive_helper_preserves_existing_failure_receipt_without_popup(tmp_path,monkeypatch):
    import ctypes,sys
    import mokka_ecu_lab.launcher as module
    receipt=tmp_path/'receipt.json';calls=[]
    def fail(*_):receipt.write_text('{"completed":false}',encoding='utf-8');raise OSError('Constructed helper failure')
    monkeypatch.setattr('mokka_ecu_lab.upgrade.execute_saved_plan',fail)
    monkeypatch.setattr(sys,'argv',['launcher','--apply-upgrade-plan',str(tmp_path/'constructed-plan.json'),'--approval-token','CONSTRUCTED','--receipt',str(receipt)])
    if hasattr(ctypes,'windll'):monkeypatch.setattr(ctypes.windll.user32,'MessageBoxW',lambda *args:calls.append(args))
    assert module.main()==1 and not calls and json.loads(receipt.read_text(encoding='utf-8'))==dict(completed=False)

def test_only_explicit_user_upgrade_flow_requests_result_dialog(tmp_path,monkeypatch):
    import ctypes,sys,os
    import mokka_ecu_lab.launcher as module
    calls=[];monkeypatch.setattr('mokka_ecu_lab.upgrade.execute_saved_plan',lambda *args:dict(current=dict(current='CONSTRUCTED')))
    monkeypatch.setattr(sys,'argv',['launcher','--apply-upgrade-plan',str(tmp_path/'constructed-plan.json'),'--approval-token','CONSTRUCTED','--receipt',str(tmp_path/'result.json'),'--show-upgrade-result'])
    if hasattr(ctypes,'windll'):monkeypatch.setattr(ctypes.windll.user32,'MessageBoxW',lambda *args:calls.append(args))
    assert module.main()==0 and len(calls)==(1 if os.name=='nt' else 0)

def test_running_managed_gui_blocks_legacy_pointer_activation(prepared,monkeypatch):
    import mokka_ecu_lab.versions as module
    h=prepared;p=h['m'].preview_install(h['archive'],h['release']);row=h['m'].install(p,p['approval_token'],smoke=smoke);activation=h['m'].preview_activation(row['key']);before=h['m'].state()
    monkeypatch.setattr(module,'running_executables',lambda:dict(processes=[dict(pid=123,path=str(h['m'].folder(before['current'])/'MokkaECULab.exe'))],inaccessible_processes=0))
    with pytest.raises(ValueError,match='Close'):h['m'].activate(activation,activation['approval_token'])
    assert h['m'].state()==before

def test_windows_locked_current_prevents_update_before_copy(prepared):
    import os,ctypes
    from ctypes import wintypes
    if os.name!='nt':pytest.skip('Actual Windows file sharing guard')
    h=prepared;p=preview(h);exe=h['m'].folder(p['pointer_before']['current'])/'MokkaECULab.exe'
    with exe.open('rb'):
        with pytest.raises(ValueError,match='locked'):execute(h,p)
    assert h['m'].state()==p['pointer_before'] and not h['m'].folder(p['selected_key']).exists()

def test_corruption_after_copy_rolls_back_before_dispatch(prepared):
    h=prepared;p=preview(h);original=h['m']._install_locked
    def tamper(*args,**kwargs):
        row=original(*args,**kwargs);(Path(row['folder'])/'MokkaECULab.exe').write_bytes(b'corrupted constructed candidate');return row
    h['m']._install_locked=tamper
    with pytest.raises(ValueError,match='hash mismatch'):h['u'].execute(p,p['approval_token'],smoke=smoke,reader=reader)
    assert h['m'].state()==p['pointer_before'] and h['l'].verify()['verified']

def test_fresh_setup_failure_removes_only_this_transactions_new_shortcuts(tmp_path,monkeypatch):
    import mokka_ecu_lab.versions as versions
    import mokka_ecu_lab.upgrade as module
    monkeypatch.setattr(versions,'running_executables',lambda:dict(processes=[],inaccessible_processes=0));monkeypatch.setattr(module,'gui_processes',lambda:[])
    m=ManagedVersions(tmp_path/'versions',tmp_path/'data');l=CurrentLauncher(m,tmp_path/'stable');u=ApprovedUpgrade(m,l);path,release=artifact(tmp_path,'v1.0.0');desktop=tmp_path/'Desktop Ω'
    p=u.preview(path,release,desktop,shortcut_writer=writer,reader=reader)
    def fail():raise OSError('Constructed dispatch failure')
    with pytest.raises(OSError):u.execute(p,p['approval_token'],smoke=smoke,reader=reader,dispatch_verifier=fail)
    assert m.state()==p['pointer_before'] and not (desktop/'Mokka ECU Lab.lnk').exists() and m.verify(p['selected_key'])['verified']
