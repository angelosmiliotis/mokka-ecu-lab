"""Opt-in managed portable builds. Copy/install/pointers only; no cleanup/delete API."""
from contextlib import contextmanager
from pathlib import Path,PurePosixPath
from urllib.request import Request,urlopen
import hashlib,json,os,re,subprocess,sys,tempfile,uuid,zipfile
from .library import digest,write_json
from .local_paths import inside,regular_files,linked

REPOSITORY='angelosmiliotis/mokka-ecu-lab'

def release_info(tag):
    if not re.fullmatch(r'v\d+\.\d+\.\d+',tag):raise ValueError('Select an exact version tag')
    url='https://api.github.com/repos/'+REPOSITORY+'/releases/tags/'+tag
    req=Request(url,headers={'User-Agent':'MokkaECULab-version-check','Accept':'application/vnd.github+json'})
    with urlopen(req,timeout=20) as response:
        payload=response.read(2_000_001)
    if len(payload)>2_000_000:raise ValueError('Release metadata too large')
    data=json.loads(payload)
    if data.get('draft') or data.get('tag_name')!=tag:raise ValueError('Published exact tag required')
    name=f'MokkaECULab-{tag}-Windows11-x64.zip';assets=[a for a in data['assets'] if a['name']==name]
    if len(assets)!=1:raise ValueError('One official Windows asset required')
    a=assets[0];sha=a.get('digest','')
    if not re.fullmatch(r'sha256:[0-9a-f]{64}',sha or ''):raise ValueError('Official GitHub SHA-256 unavailable; installation blocked')
    expected='https://github.com/'+REPOSITORY+'/releases/download/'+tag+'/'+name
    if a['browser_download_url']!=expected:raise ValueError('Unexpected release asset origin')
    return dict(tag=tag,repository=REPOSITORY,asset=name,sha256=sha[7:],bytes=a['size'],url=expected,release_url=data['html_url'],trust='OFFICIAL_GITHUB_RELEASE_DIGEST')

def running_executables():
    import psutil
    rows=[];inaccessible=0
    for p in psutil.process_iter(['pid','exe']):
        try:
            if p.info['exe']:rows.append(dict(pid=p.info['pid'],path=str(Path(p.info['exe']).resolve())))
        except (psutil.AccessDenied,psutil.NoSuchProcess):inaccessible+=1
    return dict(processes=rows,inaccessible_processes=inaccessible)

class ManagedVersions:
    def __init__(self,root,data_root):
        self.root=Path(root).resolve();self.data_root=Path(data_root).resolve()
        if self.root.is_relative_to(self.data_root) or self.data_root.is_relative_to(self.root):raise ValueError('Installations and personal data must be separate')
        if any((p/'.git').exists() for p in [self.root,*self.root.parents]):raise ValueError('A Git working tree cannot be a managed install root')
        if any(linked(p) for p in [self.root,*self.root.parents]):raise ValueError('Managed installations cannot traverse symbolic links/junctions')
        self.builds=self.root/'Builds';self.pointer=self.root/'current.json'

    @contextmanager
    def lock(self):
        self.root.mkdir(parents=True,exist_ok=True);path=self.root/'operation.lock'
        try:fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
        except FileExistsError:raise ValueError('Another managed update, or an interrupted operation lock, needs review. No files changed.')
        try:
            os.write(fd,json.dumps(dict(pid=os.getpid())).encode());os.fsync(fd);os.close(fd);yield
        finally:path.unlink() # only the lock created by this operation

    def state(self):
        if not self.pointer.exists():return dict(current=None,previous=None)
        value=json.loads(self.pointer.read_text(encoding='utf-8'))
        if set(value)!={'current','previous'}:raise ValueError('Invalid managed current/rollback pointer')
        for k in value.values():
            if k is not None and not re.fullmatch(r'v\d+\.\d+\.\d+-[0-9a-f]{12}',k):raise ValueError('Unsafe managed build identity')
        return value

    def folder(self,key):
        if not re.fullmatch(r'v\d+\.\d+\.\d+-[0-9a-f]{12}',key):raise ValueError('Unsafe build identity')
        return inside(self.root,self.builds/key)

    @staticmethod
    def zip_members(path):
        with zipfile.ZipFile(path) as z:
            infos=z.infolist();seen=set();files=[]
            if len(infos)>6000 or sum(i.file_size for i in infos)>800_000_000:raise ValueError('Portable archive limits exceeded')
            for i in infos:
                name=i.filename;p=PurePosixPath(name)
                invalid=any(c.endswith((' ','.')) or c.split('.')[0].upper() in {'CON','PRN','AUX','NUL',*(f'COM{k}' for k in range(1,10)),*(f'LPT{k}' for k in range(1,10))} for c in p.parts)
                if p.is_absolute() or '..' in p.parts or invalid or '\\' in name or ':' in name or name.casefold() in seen or i.flag_bits&1 or (i.external_attr>>16)&0o170000==0o120000:raise ValueError('Unsafe/duplicate portable archive member')
                seen.add(name.casefold())
                if i.is_dir():continue
                if len(p.parts)<2 or p.parts[0]!='MokkaECULab' or not (p.parts[1]=='MokkaECULab.exe' and len(p.parts)==2 or p.parts[1]=='_internal'):raise ValueError('Archive contains unmanaged/user data')
                files.append(dict(name='/'.join(p.parts[1:]),bytes=i.file_size))
            names={f['name'] for f in files}
            if not {'MokkaECULab.exe','_internal/PySide6/Qt6Core.dll'}<=names or not any(n.startswith('_internal/python3') and n.endswith('.dll') for n in names):raise ValueError('Incomplete executable / _internal runtime')
            if z.read('MokkaECULab/MokkaECULab.exe')[:2]!=b'MZ':raise ValueError('Expected a Windows executable')
            if z.testzip() is not None:raise ValueError('Portable ZIP CRC failure')
            return files

    def preview_install(self,path,release):
        path=Path(path).resolve()
        if release.get('repository')!=REPOSITORY or release.get('trust')!='OFFICIAL_GITHUB_RELEASE_DIGEST' or digest(path)!=release['sha256'] or path.stat().st_size!=release['bytes']:raise ValueError('Release asset identity/SHA-256 mismatch')
        if not re.fullmatch(r'v\d+\.\d+\.\d+',release.get('tag','')):raise ValueError('Invalid release tag')
        files=self.zip_members(path);key=release['tag']+'-'+release['sha256'][:12];destination=self.folder(key)
        existing=next(p for p in [self.root,*self.root.parents] if p.exists());processes=running_executables()
        plan=dict(action='COPY_TO_NEW_MANAGED_BUILD; preserve current, rollback and personal data',source=str(path),destination=str(destination),key=key,files=files,bytes=sum(f['bytes'] for f in files),release=release,state=self.state(),
            managed_running_pids=[p['pid'] for p in processes['processes'] if Path(p['path']).is_relative_to(self.root)],write_permission=os.access(existing,os.W_OK),dependency_complete=True,no_deletions=True)
        plan['approval_token']=hashlib.sha256(json.dumps(plan,sort_keys=True).encode()).hexdigest();return plan

    @staticmethod
    def approve(plan,token):
        c=dict(plan);found=c.pop('approval_token',None)
        if not token or token!=found or token!=hashlib.sha256(json.dumps(c,sort_keys=True).encode()).hexdigest():raise ValueError('Approve the exact unchanged preview first')

    def smoke(self,exe):
        with tempfile.TemporaryDirectory(prefix='mokka-managed-smoke-') as temp:
            # Fresh child directory: the app's synthetic smoke mode rejects existing data.
            run=subprocess.run([str(exe),'--smoke-test','--data-dir',str(Path(temp)/'synthetic-data')],timeout=45,capture_output=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            if run.returncode:raise ValueError('New build startup validation failed; current/rollback pointers untouched')
        return dict(exit_code=0,mode='EXPLICIT_SYNTHETIC_SMOKE',hardware_connected=False)

    def install(self,plan,approval_token,*,smoke=None):
        self.approve(plan,approval_token)
        if plan!=self.preview_install(plan['source'],plan['release']):raise ValueError('Install preview changed; review again')
        with self.lock():
            destination=self.folder(plan['key'])
            if destination.exists():return self.verify(plan['key'])
            stage=inside(self.root,self.root/'Staging'/uuid.uuid4().hex);stage.mkdir(parents=True)
            with zipfile.ZipFile(plan['source']) as z:
                for row in plan['files']:
                    out=stage/row['name'];out.parent.mkdir(parents=True,exist_ok=True)
                    with out.open('xb') as f:f.write(z.read('MokkaECULab/'+row['name']));f.flush();os.fsync(f.fileno())
            hashes={p.relative_to(stage).as_posix():digest(p) for p in regular_files(stage)}
            if digest(plan['source'])!=plan['release']['sha256']:raise ValueError('Source archive changed during extraction; no smoke or activation')
            validation=(smoke or self.smoke)(stage/'MokkaECULab.exe')
            if validation.get('exit_code')!=0:raise ValueError('Managed smoke must succeed before activation')
            # Validate that smoke did not create personal data inside the installation.
            if set(hashes)!={p.relative_to(stage).as_posix() for p in regular_files(stage)} or any(digest(stage/n)!=sha for n,sha in hashes.items()):raise ValueError('Build changed during smoke validation')
            metadata=dict(key=plan['key'],release=plan['release'],files=hashes,smoke=validation,source_sha256=plan['release']['sha256'],personal_data_root=str(self.data_root),no_deletions=True)
            write_json(stage/'install-metadata.json',metadata);self.builds.mkdir(parents=True,exist_ok=True);stage.rename(destination)
            return self.verify(plan['key'])

    def verify(self,key):
        folder=self.folder(key);metadata=json.loads((folder/'install-metadata.json').read_text(encoding='utf-8'))
        if metadata.get('key')!=key or metadata['release'].get('trust')!='OFFICIAL_GITHUB_RELEASE_DIGEST':raise ValueError('Unverified managed build provenance')
        files=metadata['files'];actual={p.relative_to(folder).as_posix() for p in regular_files(folder)}
        if actual!=set(files)|{'install-metadata.json'}:raise ValueError('Unknown added files or links; no mutation permitted')
        for name,sha in files.items():
            p=(folder/name).resolve()
            if not p.is_relative_to(folder) or digest(p)!=sha:raise ValueError('Managed build file/hash mismatch')
        return dict(key=key,folder=str(folder),file_count=len(files),bytes=sum((folder/n).stat().st_size for n in files),release=metadata['release'],verified=True,smoke=metadata['smoke'])

    def preview_activation(self,key):
        build=self.verify(key);plan=dict(action='SET_CURRENT_POINTER_ONLY',build=build,state=self.state(),personal_data_untouched=True,no_deletions=True)
        plan['approval_token']=hashlib.sha256(json.dumps(plan,sort_keys=True).encode()).hexdigest();return plan

    def activate(self,plan,approval_token):
        self.approve(plan,approval_token)
        if plan!=self.preview_activation(plan['build']['key']):raise ValueError('Current/rollback state changed; preview again')
        with self.lock():
            old=self.state();key=plan['build']['key']
            if old['current']==key:return old
            if old['current']:self.verify(old['current'])
            value=dict(current=key,previous=old['current']);write_json(self.pointer,value);return value

    def rollback(self,approval_token):
        previous=self.state()['previous']
        if not previous:raise ValueError('No verified local rollback is selected')
        return self.activate(self.preview_activation(previous),approval_token)

    def launch_current(self):
        state=self.state()
        if not state['current']:raise ValueError('Select a verified current build first')
        row=self.verify(state['current']);exe=Path(row['folder'])/'MokkaECULab.exe'
        if any(Path(p['path']).is_relative_to(self.builds.resolve()) for p in running_executables()['processes']):raise ValueError('A managed executable is already running; close it before launching another')
        process=subprocess.Popen([str(exe),'--data-dir',str(self.data_root)],creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        try:code=process.wait(timeout=2)
        except subprocess.TimeoutExpired:return dict(pid=process.pid,current=state['current'])
        if code and state['previous']:
            self.verify(state['previous'])
            with self.lock():
                if self.state()==state:write_json(self.pointer,dict(current=state['previous'],previous=state['current']))
            raise ValueError('Startup failed; current pointer rolled back. Personal data untouched. Launch rollback explicitly.')
        return dict(exit_code=code,current=state['current'])

    def inventory(self):
        state=self.state();processes=running_executables();rows=[]
        inside(self.root,self.builds)
        if self.builds.exists():
            for p in sorted(self.builds.iterdir()):
                if not p.is_dir() or linked(p):continue
                try:row=self.verify(p.name)
                except Exception as exc:row=dict(folder=str(p),verified=False,reason=str(exc))
                row['role']='CURRENT' if p.name==state['current'] else 'ROLLBACK' if p.name==state['previous'] else 'RETAINED / NO CLEANUP'
                row['running_pids']=[x['pid'] for x in processes['processes'] if Path(x['path']).is_relative_to(p.resolve())];rows.append(row)
        launch=str(Path(sys.executable).resolve());return dict(managed_root=str(self.root),data_root=str(self.data_root),actual_launch_target=launch,source_mode=not getattr(sys,'frozen',False),state=state,builds=rows,inaccessible_processes=processes['inaccessible_processes'],cleanup_actions=[],no_deletions=True)

    def preview_external(self,folder):
        if linked(folder):raise ValueError('Select the actual standalone folder, not a link/junction')
        folder=Path(folder).resolve()
        if not (folder/'MokkaECULab.exe').is_file() or not (folder/'_internal').is_dir():raise ValueError('Select one exact standalone executable folder, not Downloads or a parent directory')
        if any((p/'.git').exists() for p in [folder,*folder.parents]):return dict(path=str(folder),classification='DEVELOPER_REPOSITORY_OUTPUT',action='NO ACTION; repository and release outputs protected',no_deletions=True)
        files=[]
        for p in regular_files(folder):files.append(dict(path=str(p),bytes=p.stat().st_size,sha256=digest(p)))
        processes=running_executables()
        return dict(path=str(folder),classification='UNMANAGED; exact version/provenance unverified',file_count=len(files),bytes=sum(f['bytes'] for f in files),files=files,
            extra_contents=[f['path'] for f in files if Path(f['path']).relative_to(folder).parts[0] not in {'MokkaECULab.exe','_internal'}],
            dependency_complete=(folder/'_internal/PySide6/Qt6Core.dll').is_file(),running_pids=[p['pid'] for p in processes['processes'] if Path(p['path']).is_relative_to(folder)],
            write_permission=os.access(folder,os.W_OK),action='PREVIEW ONLY; no move/delete/activation authorized',no_deletions=True)
