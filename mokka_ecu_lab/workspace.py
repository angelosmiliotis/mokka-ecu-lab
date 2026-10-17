"""Exact release-workspace inventory and approved reversible quarantine. No deletion API."""
from pathlib import Path
from datetime import datetime,timezone
from concurrent.futures import ThreadPoolExecutor
import hashlib,json,os,subprocess,uuid,csv,sqlite3,zipfile
from .local_paths import inside,linked,regular_files
from .library import write_json
from .versions import running_executables

def fingerprint(path):
    path=Path(path);before=path.stat()
    if getattr(before,'st_file_attributes',0)&(0x1000|0x40000|0x400000):raise ValueError('Offline/cloud placeholder; no automatic hydration')
    h=hashlib.sha256()
    with path.open('rb') as f:
        for part in iter(lambda:f.read(1024*1024),b''):h.update(part)
    after=path.stat()
    if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise ValueError('File changed during inventory')
    return dict(bytes=before.st_size,sha256=h.hexdigest(),modified_ns=before.st_mtime_ns)

def tree_snapshot(path):
    path=Path(path)
    if linked(path):raise ValueError('Linked entry is blocked')
    files=[path] if path.is_file() else sorted(regular_files(path,limit=100000))
    if any('.git' in p.relative_to(path).parts for p in files if p!=path):raise ValueError('Embedded Git repository is protected')
    with ThreadPoolExecutor(max_workers=4) as pool:values=list(pool.map(fingerprint,files))
    rows=[dict(relative='.' if p==path else p.relative_to(path).as_posix(),**v) for p,v in zip(files,values)]
    digest=hashlib.sha256(json.dumps(rows,sort_keys=True).encode()).hexdigest()
    return dict(kind='FILE' if path.is_file() else 'DIRECTORY',files=rows,file_count=len(rows),bytes=sum(r['bytes'] for r in rows),tree_sha256=digest)

def seal(plan):
    plan=dict(plan);plan['approval_token']=hashlib.sha256(json.dumps(plan,sort_keys=True).encode()).hexdigest();return plan

def protected_evidence(path,snapshot):
    """Unknown or real evidence never becomes a workspace-cleanup candidate."""
    protected=[];base=Path(path)
    def simulated_records(lines):
        found=False
        for line in lines:
            if not line.strip():continue
            r=json.loads(line)
            if not isinstance(r,dict):return False
            mode=r.get('mode',r.get('source_kind'))
            if mode is not None and mode!='SIMULATED':return False
            if r.get('record_type')=='transaction':
                if mode!='SIMULATED':return False
                found=True
        return found
    for row in snapshot['files']:
        p=base if row['relative']=='.' else base/row['relative'];suffix=p.suffix.lower()
        if 'private' in (base.name+'/'+row['relative']).casefold():protected.append(row['relative']);continue
        try:
            if suffix=='.jsonl' and not simulated_records(p.read_bytes().splitlines()):protected.append(row['relative'])
            elif suffix=='.csv':
                with p.open(encoding='utf-8-sig',newline='') as f:
                    records=csv.DictReader(f)
                    if 'source_kind' not in (records.fieldnames or []) or any(r['source_kind']!='SIMULATED' for r in records):protected.append(row['relative'])
            elif suffix in {'.db','.sqlite','.sqlite3'}:
                db=sqlite3.connect(p.resolve().as_uri()+'?mode=ro&immutable=1',uri=True)
                try:
                    modes=[r[0] for r in db.execute('SELECT DISTINCT mode FROM sessions')]
                    if not modes or any(x!='SIMULATED' for x in modes):protected.append(row['relative'])
                finally:db.close()
            elif suffix=='.zip':
                with zipfile.ZipFile(p) as z:
                    if 'raw-redacted.jsonl' in z.namelist() and not simulated_records(z.read('raw-redacted.jsonl').splitlines()):protected.append(row['relative'])
        except (OSError,ValueError,KeyError,sqlite3.Error,zipfile.BadZipFile):protected.append(row['relative'])
    return protected

def approve(plan,token):
    c=dict(plan);found=c.pop('approval_token',None)
    if not token or token!=found or token!=hashlib.sha256(json.dumps(c,sort_keys=True).encode()).hexdigest():raise ValueError('Approve the exact unchanged path-level preview first')

class WorkspaceStorage:
    def __init__(self,root):
        original=Path(root).absolute()
        if linked(original):raise ValueError('Select actual release folder, not a link/junction')
        self.root=original.resolve();self.repo=self.root.parent
        if self.root.name!='release' or not (self.repo/'.git').exists():raise ValueError('Select one exact Git workspace release folder')
        inside(self.repo,self.root)

    def tracked(self):
        run=subprocess.run(['git','-C',str(self.repo),'ls-files','-z'],capture_output=True,check=True)
        return [self.repo/p.decode('utf-8') for p in run.stdout.split(b'\0') if p]

    def inventory(self,*,keep=(),processes=None):
        tracked=self.tracked();processes=processes or running_executables();keep={Path(p).resolve() for p in keep};rows=[]
        process_paths=[(x['pid'],Path(x['path']).resolve()) for x in processes['processes']]
        for p in sorted(self.root.iterdir(),key=lambda p:p.name.casefold()):
            resolved=p.resolve()
            row=dict(path=str(p),action='REVIEW',provenance='UNMANAGED_GENERATED_OR_UNKNOWN; contents retained',running_pids=[pid for pid,path in process_paths if path.is_relative_to(resolved)],git_tracked=any(t==p or t.is_relative_to(p) for t in tracked),reason='')
            try:
                inside(self.root,p);row.update(tree_snapshot(p));row['protected_evidence']=protected_evidence(p,row)
                if row['protected_evidence']:row.update(action='KEEP',reason='Private/unknown research evidence or original database; excluded from workspace cleanup')
            except (OSError,ValueError) as exc:row.update(action='BLOCKED',reason=str(exc),bytes=0,file_count=0)
            if row['git_tracked'] or row['running_pids'] or resolved in keep:row.update(action='KEEP',reason='Tracked, running, or explicitly retained CURRENT / ROLLBACK / official artifact')
            rows.append(row)
        return dict(root=str(self.root),entries=rows,entry_count=len(rows),directories=sum(x.get('kind')=='DIRECTORY' for x in rows),bytes=sum(x['bytes'] for x in rows),inaccessible_processes=processes.get('inaccessible_processes',0),automatic_cleanup=False,network_upload=False)

    def preview_quarantine(self,inventory,destination,selected):
        if inventory['root']!=str(self.root):raise ValueError('Wrong selected root')
        dest=Path(destination).absolute()
        if linked(dest) or any(linked(p) for p in dest.parents):raise ValueError('Quarantine cannot follow links')
        dest=dest.resolve()
        if dest.is_relative_to(self.repo) or self.repo.is_relative_to(dest) or dest.exists():raise ValueError('Choose a fresh private quarantine folder outside the entire repository')
        if self.root.drive.casefold()!=dest.drive.casefold():raise ValueError('Quarantine requires same-volume atomic rename; no cross-volume source removal')
        selection=set(str(Path(p).resolve()) for p in selected);rows=[]
        for row in inventory['entries']:
            if row['path'] not in selection:continue
            if row['action'] in {'KEEP','BLOCKED'}:raise ValueError('Protected/blocked entry selected')
            p=Path(row['path']);inside(self.root,p)
            rows.append(dict(source=str(p),destination=str(dest/p.name),snapshot={k:row[k] for k in ('kind','files','file_count','bytes','tree_sha256')},action='MOVE_TO_PRIVATE_QUARANTINE; preserve every byte; reversible'))
        if not rows or len(rows)!=len(selection):raise ValueError('Select exact inventoried entries only')
        return seal(dict(schema_version=1,kind='WORKSPACE_QUARANTINE',root=str(self.root),destination=str(dest),entries=rows,kept=[dict(path=r['path'],reason=r['reason']) for r in inventory['entries'] if r['path'] not in selection],bytes=sum(r['snapshot']['bytes'] for r in rows),entry_count=len(rows),disk_bytes_freed=0,source_policy='No deletion; atomic moves only after exact approval; originals recoverable in quarantine',created_utc=datetime.now(timezone.utc).isoformat()))

    def execute(self,plan,token,*,cancel=None):
        approve(plan,token)
        if plan['root']!=str(self.root) or plan['kind']!='WORKSPACE_QUARANTINE':raise ValueError('Wrong workspace plan')
        dest=Path(plan['destination']);inside(dest,dest/'operation.json')
        if dest.is_relative_to(self.repo) or self.root.drive.casefold()!=dest.drive.casefold():raise ValueError('Invalid quarantine boundary')
        receipt=dest/'operation.json'
        if dest.exists() and not receipt.exists():raise ValueError('Quarantine destination appeared after preview')
        dest.mkdir(parents=True,exist_ok=True)
        previous=json.loads(receipt.read_text(encoding='utf-8')) if receipt.exists() else dict(plan=plan,completed=[],state='IN_PROGRESS')
        if previous['plan']!=plan:raise ValueError('Destination belongs to another exact plan')
        completed=previous['completed'];running=running_executables()['processes'];tracked=self.tracked()
        # Verify every source BEFORE the first move; resume checks completed destinations.
        for row in plan['entries']:
            src=Path(row['source']);target=Path(row['destination']);inside(self.root,src);inside(dest,target)
            if src.parent!=self.root or target.parent!=dest:raise ValueError('Only immediate inventoried children may move')
            if row['source'] in completed:
                if src.exists() or tree_snapshot(target)!=row['snapshot']:raise ValueError('Changed completed quarantine item')
                continue
            if not src.exists() and target.exists() and tree_snapshot(target)==row['snapshot']:
                completed.append(row['source']);continue # recover rename-before-checkpoint interruption
            if target.exists() or tree_snapshot(src)!=row['snapshot']:raise ValueError('Inventory changed; generate a new preview')
            if any(t==src or t.is_relative_to(src) for t in tracked) or any(Path(p['path']).is_relative_to(src) for p in running):raise ValueError('New tracked/running source; no move')
        write_json(receipt,previous)
        for row in plan['entries']:
            if row['source'] in completed:continue
            if cancel and cancel():previous['state']='CANCELLED_PRESERVED';write_json(receipt,previous);return previous
            src=Path(row['source']);target=Path(row['destination'])
            inside(self.root,src);inside(dest,target)
            running=running_executables()['processes'];tracked=self.tracked()
            if any(t==src or t.is_relative_to(src) for t in tracked) or any(Path(p['path']).resolve().is_relative_to(src) for p in running):raise ValueError('Source became tracked/running; remaining items preserved')
            if tree_snapshot(src)!=row['snapshot']:raise ValueError('Source changed before atomic move')
            os.rename(src,target)
            if tree_snapshot(target)!=row['snapshot']:raise ValueError('Quarantine verification failed; preserve target for review')
            completed.append(row['source']);write_json(receipt,previous)
        previous['state']='COMPLETE';write_json(receipt,previous);return previous

    def preview_restore(self,receipt):
        receipt=Path(receipt);record=json.loads(receipt.read_text(encoding='utf-8'));plan=record['plan'];approve(plan,plan['approval_token'])
        if plan['root']!=str(self.root):raise ValueError('Wrong workspace')
        candidates=[r for r in plan['entries'] if r['source'] in record['completed']];rows=[];recovered=[]
        for row in candidates:
            inside(self.root,Path(row['source']));inside(Path(plan['destination']),Path(row['destination']))
            if Path(row['source']).parent!=self.root or Path(row['destination']).parent!=Path(plan['destination']):raise ValueError('Invalid restore member boundary')
            if Path(row['source']).exists():
                if not Path(row['destination']).exists() and tree_snapshot(row['source'])==row['snapshot']:recovered.append(row['source']);continue
                raise ValueError('Restore collision/hash mismatch')
            if tree_snapshot(row['destination'])!=row['snapshot']:raise ValueError('Restore collision/hash mismatch')
            rows.append(row)
        return seal(dict(kind='RESTORE_QUARANTINE',receipt=str(receipt),entries=rows,recovered_completed=recovered,root=str(self.root),no_deletions=True))

    def restore(self,plan,token,*,cancel=None):
        approve(plan,token)
        if plan!=self.preview_restore(plan['receipt']):raise ValueError('Restore state changed')
        record=json.loads(Path(plan['receipt']).read_text(encoding='utf-8'))
        for source in plan['recovered_completed']:record['completed'].remove(source)
        write_json(plan['receipt'],record)
        for row in plan['entries']:
            if cancel and cancel():record['state']='RESTORE_CANCELLED_PRESERVED';write_json(plan['receipt'],record);return record
            inside(self.root,Path(row['source']));inside(Path(record['plan']['destination']),Path(row['destination']))
            if any(Path(p['path']).resolve().is_relative_to(Path(row['destination'])) for p in running_executables()['processes']):raise ValueError('Archived executable is running; remaining restore items preserved')
            if Path(row['source']).exists() or tree_snapshot(row['destination'])!=row['snapshot']:raise ValueError('Restore source/destination changed; remaining items preserved')
            os.rename(row['destination'],row['source']);record['completed'].remove(row['source']);record['state']='RESTORING';write_json(plan['receipt'],record)
        record['state']='RESTORED';write_json(plan['receipt'],record)
        return record
