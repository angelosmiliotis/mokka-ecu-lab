"""One explicitly approved official install/activate/shortcut verification transaction.

No downloads, automatic startup, diagnostic access or personal shortcut replacement.
The application must close before this separate helper may change CURRENT.
"""
from pathlib import Path
from contextlib import contextmanager,ExitStack
import json,os,subprocess,sys,time,uuid
from .library import digest,write_json
from .versions import running_executables
from .launcher import inspect_shortcuts
from .workspace import seal,approve
from .local_paths import linked,inside

def gui_processes():
    import psutil
    rows=[]
    for process in psutil.process_iter(['pid','name','exe'],ad_value=None):
        name=(process.info.get('name') or '').lower()
        if name=='mokkaeculab.exe':rows.append(dict(pid=process.info['pid'],path=process.info.get('exe') or 'UNRESOLVED_MOKKA_GUI; cannot assume closed'))
        elif name in {'python.exe','pythonw.exe','python','python3'}:
            try:
                args=process.cmdline()
                module=any(a=='-m' and i+1<len(args) and args[i+1]=='mokka_ecu_lab' for i,a in enumerate(args))
                source=any(Path(a).name=='run_app.py' and (Path(a).absolute().parent/'mokka_ecu_lab').is_dir() for a in args[1:] if not a.startswith('-'))
                if module or source:rows.append(dict(pid=process.info['pid'],path='MOKKA_SOURCE_PROCESS; close before upgrade'))
            except (psutil.AccessDenied,psutil.NoSuchProcess):pass
    return rows

def _same_path(a,b):return os.path.normcase(str(Path(a).resolve()))==os.path.normcase(str(Path(b).resolve()))

class ApprovedUpgrade:
    def __init__(self,manager,launcher):
        if launcher.manager.root!=manager.root:raise ValueError('Upgrade/launcher manager mismatch')
        self.manager=manager;self.launcher=launcher

    @contextmanager
    def current_start_guard(self,plan):
        """Windows denies new readers/startup of old CURRENT during the switch.

        Validate it first; this does not alter any executable. New candidate smoke
        remains possible. Other application processes are checked again at commit.
        """
        old=plan['pointer_before']['current']
        if os.name!='nt' or not old or old==plan['selected_key']:yield;return
        import ctypes
        from ctypes import wintypes
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.CreateFileW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
        kernel.CreateFileW.restype=wintypes.HANDLE;kernel.CloseHandle.argtypes=[wintypes.HANDLE]
        handle=kernel.CreateFileW(str(self.manager.folder(old)/'MokkaECULab.exe'),0x80000000,0,None,3,0x80,None)
        if handle==wintypes.HANDLE(-1).value:raise ValueError('Current executable is running/locked or unavailable; no activation')
        try:yield
        finally:kernel.CloseHandle(handle)

    def shortcut_snapshot(self,paths,*,reader=None,allow_missing=False):
        snapshots=[]
        for path in paths:
            path=Path(path).absolute()
            if any(linked(p) for p in [path,*path.parents]):raise ValueError('Linked shortcut path; preserve and review separately')
            if not path.exists():
                if not allow_missing:raise ValueError('Stable shortcut is missing; review verified shortcut setup before upgrading: '+str(path))
                snapshots.append(dict(path=str(path),exists=False));continue
            row=(reader or inspect_shortcuts)([path])[0]
            if not _same_path(row['path'],path) or not _same_path(row['target'],self.launcher.exe) or row.get('arguments','') or not _same_path(row['directory'],self.launcher.root):
                raise ValueError('Conflicting/legacy direct-EXE shortcut preserved. No overwrite: '+str(path))
            snapshots.append(dict(path=str(path),exists=True,sha256=digest(path),bytes=path.stat().st_size,resolution=row))
        return snapshots

    def preview(self,archive,release,desktop,programs=None,*,caller_pid=None,reader=None,shortcut_writer=None):
        if not desktop:raise ValueError('Exact actual Desktop folder is required')
        install=self.manager.preview_install(archive,release)
        current=install['state']['current']
        if current and tuple(map(int,release['tag'][1:].split('.')))<tuple(map(int,current.split('-')[0][1:].split('.'))):raise ValueError('An older install cannot replace newer CURRENT. Use the explicit verified rollback preview instead.')
        if install['state']['current']:self.manager.verify(install['state']['current'])
        paths=[str(Path(p).absolute()/'Mokka ECU Lab.lnk') for p in (desktop,programs) if p]
        if len({p.casefold() for p in paths})!=len(paths):raise ValueError('Distinct shortcut folders required')
        fresh=None;stable=None
        if any(p.exists() for p in (self.launcher.exe,self.launcher.config,self.launcher.receipt)):
            shortcuts=self.shortcut_snapshot(paths,reader=reader);stable=self.launcher.verify()
        else:
            shortcuts=self.shortcut_snapshot(paths,reader=reader,allow_missing=True)
            if any(row['exists'] for row in shortcuts):raise ValueError('Existing shortcut preserved; explicit conflict correction required')
            options={} if shortcut_writer is None else dict(shortcut_writer=shortcut_writer)
            fresh=self.launcher.preview(install['key'],desktop,programs,self.manager.root.parent/'Development/upgrade-previews',_release_install=install,**options)
        old=install['state'];key=install['key'];after=old if old['current']==key else dict(current=key,previous=old['current'])
        existing_build=self.manager.verify(key) if self.manager.folder(key).exists() else None
        plan=dict(kind='INSTALL_ACTIVATE_VERIFY_OFFICIAL_RELEASE',install=install,selected_key=key,managed_root=str(self.manager.root),data_root=str(self.manager.data_root),launcher_root=str(self.launcher.root),
            pointer_before=old,pointer_after=after,stable_launcher=stable,fresh_launcher=fresh,shortcuts=shortcuts,
            shortcut_paths=paths,caller_pid=caller_pid,running_gui=gui_processes(),new_build_already_installed=bool(existing_build),
            added_build_files=0 if existing_build else len(install['files'])+1,added_build_bytes=0 if existing_build else install['bytes'],
            existing_shortcuts_preserved=True,personal_data_untouched=True,no_old_build_deletions=True,
            rollback='Restore exact previous CURRENT/ROLLBACK on failed verification. Retain copied builds. Remove only newly created, hash-unchanged transaction shortcuts if fresh setup fails.',
            rollback_new_shortcut_cleanup=[] if fresh is None else [a['destination'] for a in fresh['shortcuts']],
            requires_all_gui_closed_before_activation=True,serial_ownership='NO COM ACCESS; caller must Finish and Disconnect; external COM ownership not probed',
            steps=['CLOSE_CALLER_SAFELY','COPY_VERIFIED_OFFICIAL_RELEASE','ISOLATED_DISCONNECTED_SMOKE','VERIFY_STABLE_SHORTCUTS','ATOMIC_CURRENT_ACTIVATION','VERIFY_PACKAGED_DISPATCH'])
        return seal(plan)

    def preview_installed(self,key,desktop,programs=None,*,caller_pid=None,reader=None):
        build=self.manager.verify(key);stable=self.launcher.verify();old=self.manager.state()
        paths=[str(Path(p).absolute()/'Mokka ECU Lab.lnk') for p in (desktop,programs) if p]
        if not desktop:raise ValueError('Exact Desktop folder required')
        return seal(dict(kind='INSTALL_ACTIVATE_VERIFY_OFFICIAL_RELEASE',install=None,selected_key=key,installed_build=build,
            managed_root=str(self.manager.root),data_root=str(self.manager.data_root),launcher_root=str(self.launcher.root),
            pointer_before=old,pointer_after=old if old['current']==key else dict(current=key,previous=old['current']),
            stable_launcher=stable,fresh_launcher=None,shortcuts=self.shortcut_snapshot(paths,reader=reader),shortcut_paths=paths,
            caller_pid=caller_pid,running_gui=gui_processes(),added_build_files=0,added_build_bytes=0,
            rollback_new_shortcut_cleanup=[],no_old_build_deletions=True,personal_data_untouched=True,
            requires_all_gui_closed_before_activation=True,action='APPROVED_INSTALLED_ACTIVATION_OR_ROLLBACK; stable shortcuts unchanged'))

    def _dispatch_proof(self):
        self.launcher.verify()
        result=subprocess.run([str(self.launcher.exe),'--verify-only'],capture_output=True,timeout=30,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if result.returncode:raise ValueError('Packaged stable dispatcher verification failed')
        return dict(exit_code=0,mode='VERIFY_ONLY; no GUI/COM started')

    def execute(self,plan,token,*,smoke=None,reader=None,dispatch_verifier=None):
        approve(plan,token)
        if plan['kind']!='INSTALL_ACTIVATE_VERIFY_OFFICIAL_RELEASE' or plan['managed_root']!=str(self.manager.root) or plan['data_root']!=str(self.manager.data_root) or plan['launcher_root']!=str(self.launcher.root):raise ValueError('Wrong upgrade roots')
        old=plan['pointer_before'];selected=plan['selected_key']
        expected=old if old['current']==selected else dict(current=selected,previous=old['current'])
        if plan['pointer_after']!=expected or plan['install'] and plan['install']['key']!=selected:raise ValueError('Inconsistent approved activation transition; no files changed')
        if plan['install'] and old['current'] and tuple(map(int,plan['install']['release']['tag'][1:].split('.')))<tuple(map(int,old['current'].split('-')[0][1:].split('.'))):raise ValueError('Older installation requires explicit installed rollback')
        if gui_processes():raise ValueError('Close every Mokka GUI, Finish and Disconnect before upgrade. Nothing activated.')
        if plan.get('caller_pid'):
            import psutil
            if psutil.pid_exists(plan['caller_pid']):raise ValueError('Approving application is still open; close it before upgrade')
        fresh_install=self.manager.preview_install(plan['install']['source'],plan['install']['release']) if plan['install'] else None
        def fixed(row):return {k:v for k,v in row.items() if k not in {'managed_running_pids','approval_token'}}
        if (fresh_install is not None and fixed(fresh_install)!=fixed(plan['install'])) or (fresh_install is None and self.manager.verify(plan['selected_key'])!=plan['installed_build']) or self.manager.state()!=plan['pointer_before']:raise ValueError('Archive, destination or CURRENT changed; exact preview required again')
        if fresh_install and not fresh_install['write_permission']:raise ValueError('Managed destination is not writable; no installation')
        stage=inside(self.manager.root,self.manager.root/'Upgrades'/uuid.uuid4().hex);stage.mkdir(parents=True)
        journal=stage/'transaction.json';old=plan['pointer_before'];activated=False;created=[]
        def record(state,**extra):write_json(journal,dict(state=state,plan=plan,**extra))
        with self.manager.lock(),ExitStack() as guards:
            if gui_processes() or self.manager.state()!=old:raise ValueError('Application/state changed before installation')
            if plan['fresh_launcher'] is None:
                if self.launcher.verify()!=plan['stable_launcher'] or self.shortcut_snapshot(plan['shortcut_paths'],reader=reader)!=plan['shortcuts']:raise ValueError('Stable launcher or shortcut changed; no mutation')
            else:
                if self.shortcut_snapshot(plan['shortcut_paths'],reader=reader,allow_missing=True)!=plan['shortcuts']:raise ValueError('Shortcut appeared after preview; preserved')
            guards.enter_context(self.current_start_guard(plan))
            record('INSTALLING')
            try:
                build=self.manager._install_locked(fresh_install,smoke=smoke) if fresh_install else self.manager.verify(plan['selected_key'])
                record('INSTALLED',build=build)
                if gui_processes():raise ValueError('Mokka opened during upgrade; activation blocked')
                if plan['fresh_launcher'] is None:
                    if self.shortcut_snapshot(plan['shortcut_paths'],reader=reader)!=plan['shortcuts']:raise ValueError('Shortcut changed during smoke; activation blocked')
                record('ACTIVATING')
                # Crash at atomic replacement leaves either old or a verified new build.
                if plan['pointer_after']!=old:activated=True;write_json(self.manager.pointer,plan['pointer_after'])
                if plan['fresh_launcher'] is not None:
                    internal=dict(plan['fresh_launcher']);internal.pop('approval_token');internal['state']=self.manager.state();internal=seal(internal)
                    self.launcher.install(internal,internal['approval_token'],on_created=created.append)
                resolved=self.shortcut_snapshot(plan['shortcut_paths'],reader=reader)
                if plan['fresh_launcher'] is None and resolved!=plan['shortcuts']:raise ValueError('Existing shortcuts changed; rollback required')
                dispatch=(dispatch_verifier or self._dispatch_proof)()
                if dispatch.get('exit_code')!=0:raise ValueError('Stable dispatcher rejected new CURRENT')
                result=dict(completed=True,installed=True,activated=True,verified_dispatch=True,current=self.manager.state(),build=build,shortcuts=resolved,dispatch=dispatch,
                    activation_changed=activated,
                    starts_disconnected=True,personal_data_untouched=True,old_builds_retained=True,ordinary_gui_launch_verified=False,
                    ordinary_gui_launch_note='Actual Desktop double-click/version observation is a separate owner acceptance step',journal=str(journal))
                record('COMPLETED',result=result);return result
            except Exception as exc:
                if activated:
                    if self.manager.state()!=plan['pointer_after']:raise ValueError('Concurrent pointer change; preserve for explicit recovery') from exc
                    if gui_processes():
                        record('RECOVERY_PENDING_GUI_CLOSE',error=str(exc),current=self.manager.state())
                        raise ValueError('An application opened after activation; close it before an explicitly reviewed rollback. Verified installed build retained.') from exc
                    write_json(self.manager.pointer,old)
                if plan['fresh_launcher'] is not None:
                    for row in created:
                        path=Path(row['destination'])
                        if path.suffix.lower()=='.lnk' and path.is_file() and not linked(path) and digest(path)==row['sha256']:path.unlink() # only approved, exclusively new transaction shortcut
                record('FAILED_ROLLED_BACK' if activated else 'FAILED_NO_ACTIVATION',error=str(exc),restored_state=self.manager.state())
                raise

def execute_saved_plan(path,token,receipt,wait_parent=None):
    """Separate packaged helper; approval is bound to the saved exact preview."""
    from .versions import ManagedVersions
    from .launcher import CurrentLauncher
    path=Path(path);receipt=Path(receipt)
    if receipt.exists():raise ValueError('Fresh helper receipt required')
    plan=json.loads(path.read_text(encoding='utf-8'));approve(plan,token)
    if wait_parent is not None:
        if plan.get('caller_pid')!=wait_parent:raise ValueError('Caller identity differs from approved preview')
        import psutil
        deadline=time.monotonic()+60
        while psutil.pid_exists(wait_parent):
            if time.monotonic()>deadline:raise ValueError('Application did not close; no upgrade performed')
            time.sleep(.1)
    manager=ManagedVersions(plan['managed_root'],plan['data_root']);launcher=CurrentLauncher(manager,plan['launcher_root'])
    try:
        if plan['install']:
            from .versions import release_info
            if release_info(plan['install']['release']['tag'])!=plan['install']['release']:raise ValueError('Published official release metadata changed or is unavailable; no upgrade')
        result=ApprovedUpgrade(manager,launcher).execute(plan,token)
    except Exception as exc:
        write_json(receipt,dict(completed=False,error=str(exc),current=manager.state()));raise
    write_json(receipt,result);return result
