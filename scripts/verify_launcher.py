"""Validate the packaged CURRENT dispatcher in a new synthetic Windows workspace.

The unpublished candidate is explicitly local validation evidence. Its metadata
uses the same constructed install fixture contract as unit tests, not a claim
that GitHub has authenticated an unpublished release. The previous ZIP must
match the exact published release digest obtained from GitHub. Neither real
Desktop/Start Menu folders nor existing installations are inspected or changed.
"""
import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from mokka_ecu_lab import __version__
from mokka_ecu_lab.launcher import CurrentLauncher
from mokka_ecu_lab.library import digest
from mokka_ecu_lab.local_paths import linked
from mokka_ecu_lab.versions import ManagedVersions,REPOSITORY,release_info


READ_SHORTCUTS=r'''
$ErrorActionPreference='Stop'
[Console]::InputEncoding=New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding=New-Object System.Text.UTF8Encoding($false)
$taskPayload=[Console]::In.ReadToEnd() | ConvertFrom-Json
$taskShell=New-Object -ComObject WScript.Shell
$taskRows=@(foreach($taskPath in $taskPayload.paths) {
    $taskLink=$taskShell.CreateShortcut([string]$taskPath)
    [ordered]@{path=$taskPath;target=$taskLink.TargetPath;directory=$taskLink.WorkingDirectory;icon=$taskLink.IconLocation;description=$taskLink.Description}
})
ConvertTo-Json -InputObject $taskRows -Compress
'''


def read_shortcuts(paths):
    result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-WindowStyle','Hidden','-Command',READ_SHORTCUTS],
        input=json.dumps(dict(paths=[str(path) for path in paths])),text=True,encoding='utf-8',capture_output=True,timeout=25,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),check=True)
    rows=json.loads(result.stdout)
    return rows if isinstance(rows,list) else [rows]


def activate(manager,key):
    plan=manager.preview_activation(key)
    return manager.activate(plan,plan['approval_token'])


def run_verified_helper(launcher,output,name,current):
    receipt=output/(name+'-helper-receipt.json')
    result=subprocess.run([str(launcher.exe),'--verify-only','--receipt',str(receipt)],capture_output=True,timeout=60,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    assert result.returncode==0,(name,result.returncode,result.stderr.decode('utf-8','replace'))
    payload=json.loads(receipt.read_text(encoding='utf-8'))
    assert payload['verified'] and payload['starts_disconnected'] and payload['current']['current']==current,payload
    return dict(stage=name,exit_code=result.returncode,current=current,receipt=str(receipt))


def own_gui_windows(pid):
    user32=ctypes.windll.user32;rows=[]
    callback=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
    @callback
    def collect(hwnd,lparam):
        owner=wintypes.DWORD();user32.GetWindowThreadProcessId(hwnd,ctypes.byref(owner))
        if owner.value==pid and user32.IsWindowVisible(hwnd):
            title=ctypes.create_unicode_buffer(1024);user32.GetWindowTextW(hwnd,title,len(title))
            rows.append((hwnd,title.value))
        return True
    user32.EnumWindows(collect,0)
    return rows


def launch_and_close_own_candidate(launcher,output,current):
    """Optional ordinary GUI launch; only this invocation's reported PID is closed."""
    import psutil
    receipt=output/'actual-candidate-gui-dispatch.json'
    run=subprocess.run([str(launcher.exe),'--receipt',str(receipt)],capture_output=True,timeout=60,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    assert run.returncode==0,run.stderr.decode('utf-8','replace')
    result=json.loads(receipt.read_text(encoding='utf-8'))
    assert result['current']==current and result.get('pid'),result
    process=psutil.Process(result['pid']);expected=launcher.manager.folder(current)/'MokkaECULab.exe'
    assert Path(process.exe()).resolve()==expected.resolve()
    deadline=time.monotonic()+20;windows=[]
    while time.monotonic()<deadline:
        windows=own_gui_windows(process.pid)
        if any('Mokka ECU Lab '+__version__ in title for _,title in windows):break
        time.sleep(.1)
    assert windows and any('Mokka ECU Lab '+__version__ in title for _,title in windows),windows
    observed=[title for _,title in windows]
    for hwnd,_ in windows:ctypes.windll.user32.PostMessageW(hwnd,0x0010,0,0) # WM_CLOSE, only the newly launched test PID.
    try:code=process.wait(timeout=20)
    except psutil.TimeoutExpired:
        raise AssertionError(f'Synthetic GUI PID {process.pid} remains open for review; it was not forcibly terminated')
    assert code==0,code
    return dict(launched=True,pid=process.pid,window_titles=observed,graceful_exit_code=code,
        start_mode='ordinary disconnected startup; no automatic connection requested',
        physical_transport_observation='not instrumented; synthetic smoke independently verifies disconnected state')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate-zip',type=Path,required=True)
    parser.add_argument('--previous-zip',type=Path,required=True)
    parser.add_argument('--previous-tag',default='v0.2.11')
    parser.add_argument('--synthetic-root',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--launch-gui',action='store_true',help='Launch and gracefully close only this isolated candidate GUI')
    args=parser.parse_args()
    if os.name!='nt':parser.error('Actual Windows executable and WScript.Shell verification requires Windows')
    synthetic=args.synthetic_root.absolute();output=args.output_dir.absolute()
    for root in (synthetic,output):
        if root.exists() or any(linked(p) for p in [root,*root.parents]):parser.error('Fresh unlinked synthetic/output paths required')
        if any((p/'.git').exists() for p in [root,*root.parents]):parser.error('Validation must stay outside repositories')
    if not synthetic.is_relative_to(Path(synthetic.anchor)/'MokkaECULabSynthetic'):parser.error('Use the dedicated drive-root MokkaECULabSynthetic workspace; no Desktop/Start Menu roots')
    if synthetic.is_relative_to(output) or output.is_relative_to(synthetic):parser.error('Separate output and synthetic roots required')
    candidate=args.candidate_zip.resolve();previous=args.previous_zip.resolve()
    originals={str(path):digest(path) for path in (candidate,previous)}
    # Authenticate only the already published reference, before creating test directories.
    reference=release_info(args.previous_tag)
    assert reference['sha256']==digest(previous) and reference['bytes']==previous.stat().st_size
    synthetic.mkdir(parents=True);output.mkdir(parents=True)
    space=synthetic/'Ελληνικός έλεγχος με κενά';space.mkdir()
    personal=space/'Ιδιωτικά συνθετικά δεδομένα';personal.mkdir()
    sentinel=personal/'constructed-sentinel.txt';sentinel.write_text('New synthetic personal-data preservation sentinel\n',encoding='utf-8');sentinel_sha=digest(sentinel)
    manager=ManagedVersions(space/'Versions',personal)
    old_plan=manager.preview_install(previous,reference);old=manager.install(old_plan,old_plan['approval_token']);activate(manager,old['key'])
    tag='v'+__version__
    local=dict(tag=tag,repository=REPOSITORY,asset=f'MokkaECULab-{tag}-Windows11-x64.zip',
        sha256=digest(candidate),bytes=candidate.stat().st_size,
        url=f'https://github.com/{REPOSITORY}/releases/download/{tag}/MokkaECULab-{tag}-Windows11-x64.zip',
        trust='OFFICIAL_GITHUB_RELEASE_DIGEST',validation_fixture=True,network_attested=False,
        provenance='LOCAL_UNPUBLISHED_CANDIDATE_FIXTURE_ONLY; not authenticated against a published release')
    plan=manager.preview_install(candidate,local);new=manager.install(plan,plan['approval_token']);activate(manager,new['key'])
    launcher=CurrentLauncher(manager,space/'Σταθερός Launcher')
    desktop=space/'Προσωρινή επιφάνεια εργασίας';programs=space/'Προσωρινό μενού Έναρξης'
    preview=launcher.preview(new['key'],desktop,programs,space/'Νέα staging previews')
    (output/'exact-synthetic-shortcut-preview.json').write_text(json.dumps(preview,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    assert not launcher.root.exists() and not desktop.exists() and not programs.exists()
    launcher.install(preview,preview['approval_token'])
    shortcuts=read_shortcuts([row['destination'] for row in preview['shortcuts']])
    assert len(shortcuts)==2
    for row in shortcuts:
        assert Path(row['target']).resolve()==launcher.exe.resolve()
        assert Path(row['directory']).resolve()==launcher.root.resolve()
        icon,index=row['icon'].rsplit(',',1)
        assert Path(icon).resolve()==launcher.exe.resolve() and index=='0'
    stable_hashes={str(path):digest(path) for path in (launcher.exe,launcher.config,launcher.receipt,*[Path(row['destination']) for row in preview['shortcuts']])}
    stages=[run_verified_helper(launcher,output,'candidate-current',new['key'])]
    activate(manager,old['key']);stages.append(run_verified_helper(launcher,output,'previous-current',old['key']))
    rollback=manager.preview_activation(manager.state()['previous']);manager.rollback(rollback['approval_token'])
    stages.append(run_verified_helper(launcher,output,'rollback-to-candidate',new['key']))
    gui=launch_and_close_own_candidate(launcher,output,new['key']) if args.launch_gui else dict(launched=False,reason='Optional ordinary GUI launch not requested; both installed GUI synthetic startup checks passed')
    assert all(digest(path)==sha for path,sha in stable_hashes.items())
    assert all(digest(path)==sha for path,sha in originals.items()) and digest(sentinel)==sentinel_sha
    result=dict(passed=True,candidate_provenance=local['provenance'],candidate_network_attested=False,
        previous_reference_verified_against_published_digest=True,all_personal_data_synthetic=True,
        real_desktop_or_startmenu_touched=False,existing_files_moved_or_deleted=0,
        windows_shortcuts_verified=shortcuts,packaged_helper_checks=stages,
        stable_helper_and_shortcuts_unchanged_across_current_rollback=True,
        installed_gui_smoke_exit_codes=[old['smoke']['exit_code'],new['smoke']['exit_code']],
        synthetic_personal_sentinel_unchanged=True,input_archives_unchanged=True,
        managed_state=manager.state(),ordinary_gui_dispatch=gui)
    (output/'packaged-launcher-validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(passed=True,helper_checks=len(stages),shortcuts=len(shortcuts),all_data_synthetic=True,gui_launched=gui['launched'])))


if __name__=='__main__':main()
