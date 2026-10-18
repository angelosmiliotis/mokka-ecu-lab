"""Verified persistent CURRENT dispatcher and exact, approved shortcut installation."""
from pathlib import Path
import ctypes,json,os,subprocess,sys,uuid
from .versions import ManagedVersions
from .library import digest,write_json
from .workspace import approve,seal
from .local_paths import inside,linked

SHORTCUT_SCRIPT=r'''
$ErrorActionPreference='Stop'
[Console]::InputEncoding=New-Object System.Text.UTF8Encoding($false)
$taskShortcut=[Console]::In.ReadToEnd() | ConvertFrom-Json
$taskShell=New-Object -ComObject WScript.Shell
$taskLink=$taskShell.CreateShortcut($taskShortcut.path)
$taskLink.TargetPath=$taskShortcut.target
$taskLink.WorkingDirectory=$taskShortcut.directory
$taskLink.IconLocation=$taskShortcut.icon
$taskLink.Description='Mokka ECU Lab - verified CURRENT; starts disconnected'
$taskLink.Save()
'''

def create_shortcut(path,target,directory,icon):
    path=Path(path)
    if path.exists() or path.suffix.lower()!='.lnk':raise ValueError('Fresh .lnk staging path required; existing shortcuts preserved')
    command=['powershell.exe','-NoProfile','-NonInteractive','-WindowStyle','Hidden','-Command',SHORTCUT_SCRIPT]
    row=dict(path=str(path),target=str(target),directory=str(directory),icon=str(icon)+',0')
    run=subprocess.run(command,input=json.dumps(row),text=True,encoding='utf-8',capture_output=True,timeout=20,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if run.returncode or not path.is_file():raise ValueError('Windows shortcut staging failed; no existing shortcut changed')

def shortcut_folders():
    script="[Console]::OutputEncoding=New-Object System.Text.UTF8Encoding($false); [ordered]@{desktop=[Environment]::GetFolderPath('Desktop');programs=[Environment]::GetFolderPath('Programs')} | ConvertTo-Json -Compress"
    run=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-WindowStyle','Hidden','-Command',script],text=True,encoding='utf-8',capture_output=True,timeout=15,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),check=True)
    return json.loads(run.stdout)

def inspect_shortcuts(paths):
    """Read actual Windows .lnk metadata; never save or rewrite a shortcut."""
    script=r'''
$ErrorActionPreference='Stop'
[Console]::InputEncoding=New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding=New-Object System.Text.UTF8Encoding($false)
$taskPaths=[Console]::In.ReadToEnd() | ConvertFrom-Json
$taskShell=New-Object -ComObject WScript.Shell
$taskRows=@(foreach($taskPath in $taskPaths) {
 $taskLink=$taskShell.CreateShortcut([string]$taskPath)
 [ordered]@{path=$taskPath;target=$taskLink.TargetPath;arguments=$taskLink.Arguments;directory=$taskLink.WorkingDirectory;icon=$taskLink.IconLocation}
})
ConvertTo-Json -InputObject $taskRows -Compress
'''
    paths=[str(Path(p).absolute()) for p in paths]
    if not paths:return []
    if any(not Path(p).is_file() or Path(p).suffix.lower()!='.lnk' for p in paths):raise ValueError('Existing exact Windows shortcuts required')
    result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-WindowStyle','Hidden','-Command',script],input=json.dumps(paths),text=True,encoding='utf-8',capture_output=True,timeout=20,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),check=True)
    rows=json.loads(result.stdout)
    return rows if isinstance(rows,list) else [rows]

class CurrentLauncher:
    def __init__(self,manager,root):
        self.manager=manager;raw=Path(root).absolute()
        if any(linked(p) for p in [raw,*raw.parents]):raise ValueError('Launcher cannot traverse links/junctions')
        self.root=raw.resolve();self.exe=self.root/'MokkaECULabLauncher.exe';self.config=self.root/'launcher.json';self.receipt=self.root/'installation.json'
        if self.root.is_relative_to(manager.data_root) or manager.data_root.is_relative_to(self.root) or any((p/'.git').exists() for p in [self.root,*self.root.parents]):raise ValueError('Stable launcher must be outside data and source checkout')

    def preview(self,key,desktop,programs,stage_root,*,shortcut_writer=create_shortcut,_release_install=None):
        build=self.manager.verify(key) if _release_install is None else dict(key=key,folder=_release_install['destination'],verified=False,basis='HASH_VERIFIED_RELEASE_PREVIEW; not installed')
        source=Path(build['folder'])/'_internal/launcher/MokkaECULabLauncher.exe'
        stage_base=Path(stage_root).absolute()
        if any(linked(p) for p in [stage_base,*stage_base.parents]):raise ValueError('Preview staging cannot traverse links')
        stage_base=stage_base.resolve()
        if stage_base.is_relative_to(self.manager.data_root) or any((p/'.git').exists() for p in [stage_base,*stage_base.parents]):raise ValueError('Preview staging cannot be in personal data or source checkout')
        if _release_install is not None:
            import zipfile
            self.manager.approve(_release_install,_release_install['approval_token'])
            if key!=_release_install['key'] or _release_install!=self.manager.preview_install(_release_install['source'],_release_install['release']):raise ValueError('Release installation preview changed')
            source=stage_base/uuid.uuid4().hex/'MokkaECULabLauncher.exe';source.parent.mkdir(parents=True)
            with zipfile.ZipFile(_release_install['source']) as archive:source.write_bytes(archive.read('MokkaECULab/_internal/launcher/MokkaECULabLauncher.exe'))
        if not source.is_file() or source.read_bytes()[:2]!=b'MZ':raise ValueError('Selected verified release has no stable launcher; choose v0.2.12+')
        sha=digest(source);stage=stage_base/uuid.uuid4().hex;stage.mkdir(parents=True)
        config=dict(schema_version=1,managed_root=str(self.manager.root),data_root=str(self.manager.data_root),launcher_sha256=sha,startup='DISCONNECTED; no automatic OBD acquisition')
        write_json(stage/'launcher.json',config)
        assets=[dict(source=str(source),destination=str(self.exe),sha256=sha,bytes=source.stat().st_size),dict(source=str(stage/'launcher.json'),destination=str(self.config),sha256=digest(stage/'launcher.json'),bytes=(stage/'launcher.json').stat().st_size)]
        shortcuts=[]
        for folder in (desktop,programs):
            if not folder:continue
            dest=Path(folder).absolute()/'Mokka ECU Lab.lnk'
            if any(linked(p) for p in [dest,*dest.parents]):raise ValueError('Shortcut destination cannot traverse links')
            dest=dest.resolve()
            if any(Path(s['destination'])==dest for s in shortcuts):raise ValueError('Choose distinct Desktop / Start Menu destinations')
            if dest.exists():raise ValueError('Existing shortcut preserved: '+str(dest)+'. Choose an empty shortcut destination or review it separately.')
            staged=stage/('shortcut-'+str(len(shortcuts))+'.lnk');shortcut_writer(staged,self.exe,self.root,self.exe)
            item=dict(source=str(staged),destination=str(dest),target=str(self.exe),working_directory=str(self.root),icon=str(self.exe)+',0',sha256=digest(staged),bytes=staged.stat().st_size)
            shortcuts.append(item);assets.append(item)
        if not shortcuts:raise ValueError('Select Desktop and/or Start Menu shortcut destination')
        if self.exe.exists() or self.config.exists() or self.receipt.exists():raise ValueError('Stable launcher already exists; it follows CURRENT automatically. No overwrite is proposed.')
        return seal(dict(kind='INSTALL_CURRENT_LAUNCHER',root=str(self.root),build_key=key,build=build,state=self.manager.state(),assets=assets,shortcuts=shortcuts,bytes=sum(a['bytes'] for a in assets),no_overwrites=True,no_deletions=True,personal_data_untouched=True,config=config))

    def install(self,plan,token,*,on_created=None):
        approve(plan,token)
        if plan['kind']!='INSTALL_CURRENT_LAUNCHER' or plan['root']!=str(self.root) or plan['state']!=self.manager.state() or self.manager.state()['current']!=plan['build_key']:raise ValueError('Select verified CURRENT and review unchanged installation state')
        self.manager.verify(plan['build_key'])
        if self.receipt.exists():raise ValueError('Installation receipt appeared after preview; existing files preserved')
        for a in plan['assets']:
            if any(linked(p) for p in [Path(a['destination']),*Path(a['destination']).parents]):raise ValueError('Installation destination became linked; no writes')
            if Path(a['destination']).exists() or digest(a['source'])!=a['sha256']:raise ValueError('Source/destination changed; no overwrite')
        self.root.mkdir(parents=True,exist_ok=True);created=[]
        for a in plan['assets']:
            target=Path(a['destination']);target.parent.mkdir(parents=True,exist_ok=True)
            if any(linked(p) for p in [target,*target.parents]):raise ValueError('Installation destination became linked; preserve created files for review')
            # Exclusive creation; no replacement of an existing user shortcut or launcher.
            temporary=target.with_name('.mokka-new-'+uuid.uuid4().hex+'.tmp')
            with temporary.open('xb') as f:f.write(Path(a['source']).read_bytes());f.flush();os.fsync(f.fileno())
            if digest(temporary)!=a['sha256']:raise ValueError('New staging copy mismatch; no partial shortcut published')
            if os.name=='nt':temporary.rename(target) # Windows rename fails if target appeared; never replace.
            else:os.link(temporary,target);temporary.unlink() # exclusive publish, own temporary only
            if on_created:on_created(a)
            if digest(target)!=a['sha256']:raise ValueError('Installed copy mismatch; preserve files for explicit recovery')
            created.append(a)
        with self.receipt.open('x',encoding='utf-8') as f:
            json.dump(dict(plan=plan,created=created,verified=True,config_sha256=digest(self.config)),f,indent=2);f.flush();os.fsync(f.fileno())
        return self.verify()

    def verify(self):
        if any(linked(p) for p in [self.root,*self.root.parents,self.exe,self.config,self.receipt]):raise ValueError('Stable dispatcher path became linked')
        data=json.loads(self.receipt.read_text(encoding='utf-8'));config=json.loads(self.config.read_text(encoding='utf-8'))
        if digest(self.config)!=data['config_sha256'] or digest(self.exe)!=config['launcher_sha256']:raise ValueError('Stable dispatcher/config changed; refuse launch')
        for a in data['created']:
            if digest(a['destination'])!=a['sha256']:raise ValueError('Installed shortcut/launcher changed')
        if config['managed_root']!=str(self.manager.root) or config['data_root']!=str(self.manager.data_root):raise ValueError('Launcher configuration mismatch')
        state=self.manager.state()
        if not state['current']:raise ValueError('No verified CURRENT selected')
        self.manager.verify(state['current'])
        return dict(verified=True,target=str(self.exe),shortcuts=data['plan']['shortcuts'],current=state,starts_disconnected=True)

def dispatch(root,*,verify_only=False):
    root=Path(root).resolve();config=json.loads((root/'launcher.json').read_text(encoding='utf-8'))
    manager=ManagedVersions(config['managed_root'],config['data_root']);launcher=CurrentLauncher(manager,root);identity=launcher.verify()
    if verify_only:return identity
    return manager.launch_current()

def main():
    import argparse
    parser=argparse.ArgumentParser(description='Verified Mokka CURRENT launcher; no automatic OBD connection')
    parser.add_argument('--verify-only',action='store_true');parser.add_argument('--receipt',type=Path)
    parser.add_argument('--apply-upgrade-plan',type=Path)
    parser.add_argument('--approval-token')
    parser.add_argument('--wait-parent',type=int)
    parser.add_argument('--show-upgrade-result',action='store_true')
    args=parser.parse_args()
    try:
        if args.apply_upgrade_plan:
            if not args.receipt or not args.approval_token or args.verify_only:raise ValueError('Exact approved upgrade plan and fresh receipt required')
            from .upgrade import execute_saved_plan
            result=execute_saved_plan(args.apply_upgrade_plan,args.approval_token,args.receipt,args.wait_parent)
            if args.show_upgrade_result and os.name=='nt':ctypes.windll.user32.MessageBoxW(None,'Installed and activated '+str(result['current']['current'])+'. Close this message, then open the same Mokka ECU Lab Desktop shortcut.','Mokka ECU Lab — upgrade verified',0x40)
            return 0
        if args.approval_token or args.wait_parent is not None or args.show_upgrade_result:raise ValueError('Upgrade-only arguments require explicit plan')
        result=dispatch(Path(sys.executable).parent,verify_only=args.verify_only)
        if args.receipt:
            with args.receipt.open('x',encoding='utf-8') as f:json.dump(result,f,indent=2)
        return 0
    except Exception as exc:
        if args.receipt:
            if not args.receipt.exists():
                with args.receipt.open('x',encoding='utf-8') as f:json.dump(dict(error=str(exc)),f)
        if os.name=='nt' and (not args.receipt or args.show_upgrade_result):ctypes.windll.user32.MessageBoxW(None,str(exc),'Mokka ECU Lab CURRENT — launch blocked',0x10)
        return 1
