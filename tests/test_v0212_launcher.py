"""Constructed releases and temporary shortcuts; never touches the real Desktop."""
from pathlib import Path
import json
import os
import subprocess
import zipfile

import pytest

from mokka_ecu_lab.launcher import CurrentLauncher, create_shortcut, dispatch
from mokka_ecu_lab.library import digest
from mokka_ecu_lab.versions import ManagedVersions, REPOSITORY


def release(tmp_path, tag, *, include_launcher=True):
    archive = tmp_path / (tag + '.zip')
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr('MokkaECULab/MokkaECULab.exe', b'MZ_CONSTRUCTED_GUI_' + tag.encode())
        z.writestr('MokkaECULab/_internal/python312.dll', b'constructed runtime')
        z.writestr('MokkaECULab/_internal/PySide6/Qt6Core.dll', b'constructed Qt')
        if include_launcher:
            z.writestr('MokkaECULab/_internal/launcher/MokkaECULabLauncher.exe', b'MZ_CONSTRUCTED_LAUNCHER_' + tag.encode())
    return archive, dict(tag=tag, repository=REPOSITORY, sha256=digest(archive),
        bytes=archive.stat().st_size, asset=f'MokkaECULab-{tag}-Windows11-x64.zip',
        url=f'https://github.com/{REPOSITORY}/releases/download/{tag}/MokkaECULab-{tag}-Windows11-x64.zip',
        trust='OFFICIAL_GITHUB_RELEASE_DIGEST')


def install_release(manager, tmp_path, tag):
    path, metadata = release(tmp_path, tag)
    plan = manager.preview_install(path, metadata)
    return manager.install(plan, plan['approval_token'], smoke=lambda exe: dict(exit_code=0, constructed=True))


def activate(manager, key):
    plan = manager.preview_activation(key)
    return manager.activate(plan, plan['approval_token'])


def constructed_shortcut(path, target, directory, icon):
    # Deterministic content permits cross-platform install/failure tests.
    Path(path).write_text(json.dumps(dict(target=str(target), directory=str(directory), icon=str(icon))), encoding='utf-8')


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    import mokka_ecu_lab.versions as versions
    monkeypatch.setattr(versions, 'running_executables', lambda: dict(processes=[], inaccessible_processes=0))
    data = tmp_path / 'προσωπικά δεδομένα'
    data.mkdir()
    original = data / 'preserve.jsonl'
    original.write_bytes(b'constructed original: unchanged throughout launcher installation')
    manager = ManagedVersions(tmp_path / 'managed εκδόσεις', data)
    row = install_release(manager, tmp_path, 'v0.2.12')
    activate(manager, row['key'])
    launcher = CurrentLauncher(manager, tmp_path / 'σταθερή εκκίνηση')
    return manager, row, launcher, original


def preview(prepared, tmp_path, **kwargs):
    manager, row, launcher, original = prepared
    defaults = dict(desktop=tmp_path / 'synthetic Desktop Ω', programs=tmp_path / 'synthetic Start Menu Ω',
                    stage_root=tmp_path / 'fresh private staging', shortcut_writer=constructed_shortcut)
    defaults.update(kwargs)
    return launcher.preview(row['key'], **defaults)


def install_launcher(prepared, tmp_path):
    plan = preview(prepared, tmp_path)
    launcher = prepared[2]
    launcher.install(plan, plan['approval_token'])
    return plan


def test_exact_preview_records_every_byte_without_changing_destinations(prepared, tmp_path):
    manager, row, launcher, original = prepared
    before = digest(original)
    plan = preview(prepared, tmp_path)
    assert plan['kind'] == 'INSTALL_CURRENT_LAUNCHER'
    assert plan['build_key'] == row['key'] and plan['state'] == manager.state()
    assert plan['no_overwrites'] and plan['no_deletions'] and plan['personal_data_untouched']
    assert len(plan['assets']) == 4 and len(plan['shortcuts']) == 2
    assert plan['bytes'] == sum(Path(a['source']).stat().st_size for a in plan['assets'])
    for asset in plan['assets']:
        assert digest(asset['source']) == asset['sha256']
        assert Path(asset['source']).stat().st_size == asset['bytes']
        assert not Path(asset['destination']).exists()
    for shortcut in plan['shortcuts']:
        assert shortcut['target'] == str(launcher.exe)
        assert shortcut['working_directory'] == str(launcher.root)
        assert shortcut['icon'] == str(launcher.exe) + ',0'
    assert not launcher.root.exists() and digest(original) == before


@pytest.mark.parametrize('name', ['MokkaECULabLauncher.exe', 'launcher.json', 'installation.json'])
def test_existing_stable_files_are_never_overwritten(prepared, tmp_path, name):
    launcher = prepared[2]
    launcher.root.mkdir()
    existing = launcher.root / name
    existing.write_bytes(b'preserve existing user file')
    before = digest(existing)
    with pytest.raises(ValueError, match='already exists'):
        preview(prepared, tmp_path)
    assert digest(existing) == before


def test_existing_shortcut_and_missing_selection_preserved(prepared, tmp_path):
    folder = tmp_path / 'existing synthetic Desktop'
    folder.mkdir()
    shortcut = folder / 'Mokka ECU Lab.lnk'
    shortcut.write_bytes(b'preserve existing shortcut')
    before = digest(shortcut)
    with pytest.raises(ValueError, match='Existing shortcut preserved'):
        preview(prepared, tmp_path, desktop=folder)
    assert digest(shortcut) == before
    with pytest.raises(ValueError, match='Select Desktop'):
        preview(prepared, tmp_path, desktop=None, programs=None)
    assert not prepared[2].root.exists()


def test_duplicate_desktop_and_start_menu_path_cannot_cause_partial_install(prepared, tmp_path):
    folder = tmp_path / 'one synthetic shortcut folder'
    launcher = prepared[2]
    try:
        plan = preview(prepared, tmp_path, desktop=folder, programs=folder)
    except ValueError:
        assert not launcher.root.exists() and not folder.exists()
    else:
        assert len(plan['shortcuts']) == 1
        assert len({a['destination'].casefold() for a in plan['assets']}) == len(plan['assets'])
        assert launcher.install(plan, plan['approval_token'])['verified']


def test_preview_cannot_create_staging_inside_personal_data_or_git(prepared, tmp_path):
    manager = prepared[0]
    before = {p.relative_to(manager.data_root): digest(p) for p in manager.data_root.rglob('*') if p.is_file()}
    forbidden = manager.data_root / 'must never be created'
    with pytest.raises(ValueError):
        preview(prepared, tmp_path, stage_root=forbidden)
    assert not forbidden.exists()
    assert {p.relative_to(manager.data_root): digest(p) for p in manager.data_root.rglob('*') if p.is_file()} == before
    checkout = tmp_path / 'synthetic checkout'
    (checkout / '.git').mkdir(parents=True)
    forbidden = checkout / 'must never be created'
    with pytest.raises(ValueError):
        preview(prepared, tmp_path, stage_root=forbidden)
    assert not forbidden.exists()


@pytest.mark.parametrize('root_kind', ['data', 'git'])
def test_stable_launcher_root_is_separate_from_data_and_checkout(prepared, tmp_path, root_kind):
    manager = prepared[0]
    root = manager.data_root / 'launcher'
    if root_kind == 'git':
        checkout = tmp_path / 'checkout'
        (checkout / '.git').mkdir(parents=True)
        root = checkout / 'launcher'
    with pytest.raises(ValueError):
        CurrentLauncher(manager, root)
    assert not root.exists()


def test_unapproved_or_changed_plan_cannot_install(prepared, tmp_path):
    launcher = prepared[2]
    plan = preview(prepared, tmp_path)
    with pytest.raises(ValueError, match='Approve'):
        launcher.install(plan, 'not-approved')
    changed = dict(plan, bytes=plan['bytes'] + 1)
    with pytest.raises(ValueError, match='Approve'):
        launcher.install(changed, plan['approval_token'])
    assert not launcher.root.exists()


def test_changed_current_or_source_invalidates_exact_installation(prepared, tmp_path):
    manager, row, launcher, original = prepared
    plan = preview(prepared, tmp_path)
    second = install_release(manager, tmp_path, 'v0.2.13')
    activate(manager, second['key'])
    with pytest.raises(ValueError, match='unchanged installation state'):
        launcher.install(plan, plan['approval_token'])
    assert not launcher.root.exists()
    activate(manager, row['key'])
    plan = preview(prepared, tmp_path)
    config_stage = next(Path(a['source']) for a in plan['assets'] if Path(a['destination']) == launcher.config)
    config_stage.write_text('changed staging configuration')
    with pytest.raises(ValueError, match='Source/destination changed'):
        launcher.install(plan, plan['approval_token'])
    assert not launcher.root.exists()


@pytest.mark.parametrize('appeared', ['receipt', 'shortcut'])
def test_destination_appearing_after_preview_is_preserved(prepared, tmp_path, appeared):
    launcher = prepared[2]
    plan = preview(prepared, tmp_path)
    target = launcher.receipt if appeared == 'receipt' else Path(plan['shortcuts'][0]['destination'])
    target.parent.mkdir(parents=True)
    target.write_bytes(b'new user content after preview')
    before = digest(target)
    with pytest.raises(ValueError):
        launcher.install(plan, plan['approval_token'])
    assert digest(target) == before and not launcher.exe.exists()


def test_install_verifies_dispatcher_shortcuts_and_preserves_personal_data(prepared, tmp_path):
    manager, row, launcher, original = prepared
    before = digest(original)
    plan = install_launcher(prepared, tmp_path)
    result = launcher.verify()
    assert result['verified'] and result['starts_disconnected']
    assert result['current'] == manager.state()
    assert json.loads(launcher.config.read_text(encoding='utf-8'))['managed_root'] == str(manager.root)
    assert json.loads(launcher.config.read_text(encoding='utf-8'))['data_root'] == str(manager.data_root)
    assert 'DISCONNECTED' in json.loads(launcher.config.read_text(encoding='utf-8'))['startup']
    for asset in plan['assets']:
        assert digest(asset['destination']) == asset['sha256']
    assert digest(original) == before and manager.verify(row['key'])['verified']


def test_old_release_without_embedded_dispatcher_requires_upgrade(prepared, tmp_path):
    manager, row, launcher, original = prepared
    path, metadata = release(tmp_path, 'v0.2.11', include_launcher=False)
    plan = manager.preview_install(path, metadata)
    old = manager.install(plan, plan['approval_token'], smoke=lambda exe: dict(exit_code=0, constructed=True))
    activate(manager, old['key'])
    with pytest.raises(ValueError, match='v0.2.12'):
        launcher.preview(old['key'], tmp_path / 'Desktop', None, tmp_path / 'staging', shortcut_writer=constructed_shortcut)
    assert not launcher.root.exists()


def test_copy_failure_preserves_partial_files_for_explicit_recovery(prepared, tmp_path, monkeypatch):
    launcher = prepared[2]
    original = prepared[3]
    before = digest(original)
    plan = preview(prepared, tmp_path)
    original_open = Path.open
    writes=[]
    def fail_second_copy(path, mode='r', *args, **kwargs):
        if path.parent == launcher.root and mode == 'xb':
            writes.append(path)
            if len(writes)==2:raise OSError('constructed interrupted copy')
        return original_open(path, mode, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', fail_second_copy)
    with pytest.raises(OSError, match='interrupted copy'):
        launcher.install(plan, plan['approval_token'])
    assert launcher.exe.exists() and not launcher.config.exists() and not launcher.receipt.exists()
    assert digest(launcher.exe) == plan['assets'][0]['sha256']
    assert all(not Path(a['destination']).exists() for a in plan['shortcuts'])
    assert digest(original) == before


def junction(link, target):
    target.mkdir(parents=True, exist_ok=True)
    if os.name != 'nt':
        link.symlink_to(target, target_is_directory=True)
        return
    script = r"""
$ErrorActionPreference='Stop'
[Console]::InputEncoding=New-Object System.Text.UTF8Encoding($false)
$taskPaths=[Console]::In.ReadToEnd() | ConvertFrom-Json
New-Item -ItemType Junction -Path $taskPaths.path -Target $taskPaths.target | Out-Null
"""
    run = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-WindowStyle', 'Hidden', '-Command', script],
        input=json.dumps(dict(path=str(link), target=str(target))), encoding='utf-8', text=True, capture_output=True,
        timeout=20, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if run.returncode:
        pytest.skip('Temporary junction creation unavailable on this host')
    assert link.is_junction()


def test_shortcut_preview_rejects_junction_before_resolving_it(prepared, tmp_path):
    actual = tmp_path / 'actual temporary target'
    alias = tmp_path / 'temporary junction'
    junction(alias, actual)
    with pytest.raises(ValueError, match='links'):
        preview(prepared, tmp_path, desktop=alias, programs=None)
    assert not list(actual.iterdir())


@pytest.mark.parametrize('redirected', ['launcher', 'shortcut'])
def test_junction_added_after_preview_cannot_redirect_approved_writes(prepared, tmp_path, redirected):
    launcher = prepared[2]
    plan = preview(prepared, tmp_path)
    alias = launcher.root if redirected == 'launcher' else Path(plan['shortcuts'][0]['destination']).parent
    actual = tmp_path / 'outside approved destination'
    junction(alias, actual)
    with pytest.raises(ValueError, match='link|junction|changed'):
        launcher.install(plan, plan['approval_token'])
    assert not list(actual.iterdir())
    if redirected == 'shortcut':
        assert not launcher.root.exists()


def test_one_shortcut_automatically_follows_verified_upgrade_and_rollback(prepared, tmp_path, monkeypatch):
    import mokka_ecu_lab.versions as versions
    manager, one, launcher, original = prepared
    plan = install_launcher(prepared, tmp_path)
    installed = {a['destination']: digest(a['destination']) for a in plan['assets']}
    two = install_release(manager, tmp_path, 'v0.2.13')
    activate(manager, two['key'])
    calls = []
    class Running:
        pid = 4242
        def wait(self, timeout):
            raise subprocess.TimeoutExpired('constructed process', timeout)
    def launch(args, **kwargs):
        calls.append(args)
        return Running()
    monkeypatch.setattr(versions.subprocess, 'Popen', launch)
    assert dispatch(launcher.root, verify_only=True)['current']['current'] == two['key']
    assert dispatch(launcher.root)['current'] == two['key']
    assert calls[-1] == [str(Path(two['folder']) / 'MokkaECULab.exe'), '--data-dir', str(manager.data_root)]
    rollback = manager.preview_activation(one['key'])
    manager.rollback(rollback['approval_token'])
    assert dispatch(launcher.root, verify_only=True)['current']['current'] == one['key']
    assert dispatch(launcher.root)['current'] == one['key']
    assert calls[-1][0] == str(Path(one['folder']) / 'MokkaECULab.exe')
    assert {a['destination']: digest(a['destination']) for a in plan['assets']} == installed


@pytest.mark.parametrize('damage', ['config', 'dispatcher', 'shortcut', 'unsafe_pointer', 'missing_current', 'current_build'])
def test_damaged_installation_or_current_build_refuses_verification_and_launch(prepared, tmp_path, monkeypatch, damage):
    import mokka_ecu_lab.versions as versions
    manager, row, launcher, original = prepared
    plan = install_launcher(prepared, tmp_path)
    if damage == 'config':
        launcher.config.write_text('{}')
    elif damage == 'dispatcher':
        launcher.exe.write_bytes(b'MZ altered dispatcher')
    elif damage == 'shortcut':
        Path(plan['shortcuts'][0]['destination']).write_bytes(b'altered shortcut')
    elif damage == 'unsafe_pointer':
        manager.pointer.write_text(json.dumps(dict(current='../../escape', previous=None)))
    elif damage == 'missing_current':
        manager.pointer.write_text(json.dumps(dict(current='v0.2.99-' + '0' * 12, previous=None)))
    else:
        (Path(row['folder']) / 'MokkaECULab.exe').write_bytes(b'MZ changed installed GUI')
    calls = []
    monkeypatch.setattr(versions.subprocess, 'Popen', lambda *a, **k: calls.append(a))
    for verify_only in (True, False):
        with pytest.raises((ValueError, OSError, KeyError)):
            dispatch(launcher.root, verify_only=verify_only)
    assert not calls


@pytest.mark.skipif(os.name != 'nt', reason='Native Windows shortcut semantics')
def test_real_windows_shortcuts_round_trip_greek_temporary_paths(prepared, tmp_path):
    manager, row, launcher, original = prepared
    original_sha = digest(original)
    plan = preview(prepared, tmp_path, shortcut_writer=create_shortcut)
    assert all(Path(a['source']).read_bytes()[:4] == b'L\x00\x00\x00' for a in plan['shortcuts'])
    launcher.install(plan, plan['approval_token'])
    script = r"""
[Console]::InputEncoding=New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding=New-Object System.Text.UTF8Encoding($false)
$taskPaths=[Console]::In.ReadToEnd() | ConvertFrom-Json
$taskShell=New-Object -ComObject WScript.Shell
@($taskPaths | ForEach-Object {
    $taskLink=$taskShell.CreateShortcut($_)
    [ordered]@{target=$taskLink.TargetPath;directory=$taskLink.WorkingDirectory;icon=$taskLink.IconLocation;arguments=$taskLink.Arguments}
}) | ConvertTo-Json -Compress
"""
    paths = [a['destination'] for a in plan['shortcuts']]
    run = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-WindowStyle', 'Hidden', '-Command', script],
        input=json.dumps(paths), encoding='utf-8', text=True, capture_output=True, timeout=20, check=True,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    links = json.loads(run.stdout)
    assert len(links) == 2
    for link in links:
        assert Path(link['target']) == launcher.exe
        assert Path(link['directory']) == launcher.root
        assert link['icon'].lower() == (str(launcher.exe) + ',0').lower()
        assert link['arguments'] == ''
    assert digest(original) == original_sha
