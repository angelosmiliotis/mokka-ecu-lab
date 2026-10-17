"""Private copy-only run library. Original journals and imported files are immutable."""
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import hashlib,json,os,shutil,sqlite3,uuid,zipfile
from .local_paths import inside,regular_files

ASSETS=('original-research.zip','report.json','report.html')
PRESERVED=('source-report.json','source-report.html')
COMPANIONS=ASSETS+('run-metadata.json',)
BUCKETS=('Drives','Benchmarks','FailedTests')


class MigrationCancelled(RuntimeError):
    """An explicit cancellation preserves sources and verified copied files."""


def _approved(plan,token):
    check=dict(plan);actual=check.pop('approval_token',None)
    if actual!=token or actual!=hashlib.sha256(json.dumps(check,sort_keys=True).encode()).hexdigest():
        raise ValueError('Explicit approval of this exact preview is required')


def _preview(plan):
    plan['approval_token']=hashlib.sha256(json.dumps(plan,sort_keys=True).encode()).hexdigest();return plan


def _run_identity(summary,members):
    journal=summary.get('original_journal_sha256') or hashlib.sha256(members['raw-redacted.jsonl']).hexdigest()
    return hashlib.sha256((str(summary['session_id'])+':'+journal).encode()).hexdigest(),journal


def _run_location(summary,key):
    started=datetime.fromisoformat(summary['started'])
    if started.tzinfo is None:raise ValueError('Original UTC start needs an explicit timezone')
    local=started.astimezone(ZoneInfo('Europe/Athens'));facts=run_facts(summary)
    bucket='FailedTests' if facts['outcome']!='COMPLETED' else 'Benchmarks' if facts['kind']=='BENCHMARK' else 'Drives'
    label='FAILED_BENCH_COM' if facts['outcome']=='FAILED_COM_OPEN' else 'BENCH_'+str(facts['rate']).replace('.0','')+'rps' if facts['kind']=='BENCHMARK' else 'DRIVE'
    return local,facts,Path(bucket)/(local.strftime('%Y-%m-%d_%H-%M-%S_')+label+'_'+key[:16])


def _duration(row):
    value=row.get('duration_seconds')
    if type(value) in (int,float) and __import__('math').isfinite(value) and value>=0:return value
    try:return max(0,(datetime.fromisoformat(row['ended_utc'])-datetime.fromisoformat(row['started_utc'])).total_seconds())
    except (ValueError,TypeError,KeyError):return None


def recent_title(row):
    """A human title is a projection; immutable identities and status stay intact."""
    local=datetime.fromisoformat(row['started_local']);stamp=f'{local.day:02d} {local.strftime("%b %H:%M")}'
    kind=('BENCH '+str(row['rate']).removesuffix('.0')+'/s') if row['kind']=='BENCHMARK' else 'DRIVE'
    duration=_duration(row);span='duration unavailable' if duration is None else f'{int(duration)//60}m{int(duration)%60:02d}s'
    outcome='PASS' if row['status']=='COMPLETED' else row['status']
    return ' · '.join((stamp,kind,span,outcome))

def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def write_json(path,value):
    path=Path(path);temp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    with temp.open('x',encoding='utf-8',newline='\n') as f:
        json.dump(value,f,ensure_ascii=False,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
    os.replace(temp,path)

def run_facts(summary):
    b=summary.get('stationary_benchmark');reason=(b or {}).get('reason','')
    if not b:kind,status,rate='DRIVE','COMPLETED',None
    else:
        rate=b.get('rate');rate=rate if type(rate) in (int,float) and rate in (1,2,3,4) else None;kind='BENCHMARK'
        status='COMPLETED' if b.get('completed') else 'STOPPED' if any(x in reason.lower() for x in ('intentional_stop','shutdown','explicit disconnect')) else 'FAILED_COM_OPEN' if b.get('failure_stage')=='FAILED_COM_OPEN' or 'open port' in reason.lower() or 'failed_com_open' in reason.lower() else 'PREFLIGHT_FAILED' if b.get('measurement_started_monotonic') is None else 'MEASUREMENT_FAILED'
    if not b:
        coordinator=summary.get('session_coordinator') or {}
        if coordinator.get('state') in {'FAILED','PARTIAL','INTERRUPTED'}:status='MEASUREMENT_FAILED'
    return dict(kind=kind,outcome=status,rate=rate,reason=reason,measured_requests=(b or {}).get('requests'),mode=summary.get('mode','UNKNOWN'))

class PartialExportError(OSError):
    def __init__(self,result):super().__init__('EXPORT_PARTIAL: original ZIP/journal preserved; retry derived report offline. '+result.get('report_error',''));self.result=result

class ReportLibrary:
    def __init__(self,root):
        self.root=Path(root).resolve();self.reports=self.root/'Reports';self.index=self.root/'Index'
        inside(self.root,self.reports);inside(self.root,self.index)
        self.reports.mkdir(parents=True,exist_ok=True);self.index.mkdir(parents=True,exist_ok=True)
        with self.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, path TEXT UNIQUE, metadata TEXT, label TEXT DEFAULT "")')
            db.execute('CREATE TABLE IF NOT EXISTS imports (source_sha TEXT PRIMARY KEY, run_id TEXT, source TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS annotations (id TEXT PRIMARY KEY,run_id TEXT,metadata TEXT)')

    @contextmanager
    def db(self):
        path=inside(self.root,self.index/'reports.sqlite3')
        if path.exists() and path.stat().st_nlink>1:raise ValueError('Linked report index cannot be modified')
        db=sqlite3.connect(path,timeout=10);db.row_factory=sqlite3.Row
        db.execute('PRAGMA journal_mode=WAL');db.execute('PRAGMA synchronous=FULL')
        try:yield db;db.commit()
        finally:db.close()

    def _path(self,relative):
        inside(self.root,self.reports)
        return inside(self.reports,self.reports/relative)

    def stage(self):
        p=self._path('.staging/'+uuid.uuid4().hex);p.mkdir(parents=True);return p

    def _discard_owned_scratch(self,stage):
        """Remove only this call's new transient copies, never a report or input."""
        stage=self._path(Path(stage).relative_to(self.reports))
        if stage.parent!=self.reports/'.staging' or len(stage.name)!=32 or any(c not in '0123456789abcdef' for c in stage.name):raise ValueError('Not owned scratch')
        files=list(regular_files(stage,limit=8))
        if any(p.parent!=stage or p.name not in COMPANIONS+PRESERVED for p in files):raise ValueError('Unknown scratch contents preserved')
        for p in files:p.unlink()
        stage.rmdir()

    def rows(self,query=''):
        with self.db() as db:rows=[dict(r) for r in db.execute('SELECT * FROM runs ORDER BY json_extract(metadata,"$.started_utc") DESC,id')]
        result=[]
        for r in rows:
            m=json.loads(r['metadata']);m.update(library_id=r['id'],folder=str(self._path(r['path'])),display_label=r['label'])
            if query.casefold() in json.dumps(m,ensure_ascii=False).casefold():result.append(m)
        return result

    def get(self,key):
        found=next((r for r in self.rows() if r['library_id']==key),None)
        if found is None:raise ValueError('Unknown library run')
        return found

    def _register(self,folder,metadata,source=None,*,rebase=False):
        relative=folder.relative_to(self.reports).as_posix()
        with self.db() as db:
            statement='INSERT INTO runs(id,path,metadata) VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET metadata=excluded.metadata'
            if rebase:statement+=',path=excluded.path'
            db.execute(statement,(metadata['library_id'],relative,json.dumps(metadata)))
            if source:db.execute('INSERT OR IGNORE INTO imports VALUES(?,?,?)',(source['sha256'],metadata['library_id'],source['path']))

    def _metadata_at(self,folder):
        """Verify an immutable managed leaf before trusting identity or rebasing."""
        from .research.evidence import read_bundle
        folder=self._path(Path(folder).relative_to(self.reports))
        paths=list(regular_files(folder,limit=8))
        if any(p.parent!=folder or p.name not in COMPANIONS+PRESERVED for p in paths):raise ValueError('Unknown files in report folder; no migration action')
        metadata=json.loads((folder/'run-metadata.json').read_text(encoding='utf-8'))
        if not isinstance(metadata,dict) or not isinstance(metadata.get('hashes'),dict) or ASSETS[0] not in metadata['hashes']:raise ValueError('Incomplete managed report metadata')
        for name,sha in metadata['hashes'].items():
            if name not in ASSETS+PRESERVED or digest(inside(folder,folder/name))!=sha:raise ValueError('Library asset changed: '+name)
        if {p.name for p in paths}!={*metadata['hashes'],'run-metadata.json'}:raise ValueError('Report metadata file coverage differs from folder')
        if metadata.get('status')!='EXPORT_PARTIAL' and not set(ASSETS)<=set(metadata['hashes']):raise ValueError('Completed report is missing a companion')
        identity,members=read_bundle(folder/ASSETS[0]);summary=json.loads(members['session-summary.json']);key,journal=_run_identity(summary,members)
        if (metadata.get('library_id'),metadata.get('session_id'),metadata.get('evidence_id'),metadata.get('original_journal_sha256'))!=(key,summary['session_id'],identity,journal):raise ValueError('Report identity differs from original evidence')
        if metadata.get('started_utc')!=summary['started']:raise ValueError('Report start differs from original evidence')
        return metadata,summary

    def verify(self,key):
        row=self.get(key);folder=Path(row['folder'])
        metadata,_=self._metadata_at(folder)
        if metadata['hashes']!=row['hashes'] or metadata['library_id']!=row['library_id']:raise ValueError('Report index differs from immutable metadata')
        return row

    def _publish(self,stage,source=None,companions=None):
        from .research.evidence import read_bundle
        identity,members=read_bundle(stage/ASSETS[0]);summary=json.loads(members['session-summary.json'])
        sid=summary['session_id']
        # A journal identifies a logical run; retries never create a second history row.
        key,journal=_run_identity(summary,members);local,facts,relative=_run_location(summary,key)
        with self.db() as db:old=db.execute('SELECT * FROM runs WHERE id=?',(key,)).fetchone()
        if old:
            row=self.verify(key)
            if source:
                with self.db() as db:db.execute('INSERT OR IGNORE INTO imports VALUES(?,?,?)',(source['sha256'],key,source['path']))
            self._discard_owned_scratch(stage);return self.result(row)
        error=None
        try:
            if companions:
                for ext,target in (('.json','report.json'),('.html','report.html')):
                    src=companions.get(ext)
                    if src and Path(src).is_file():shutil.copyfile(src,stage/target)
                if not all((stage/n).is_file() for n in ASSETS[1:]):raise ValueError('Missing legacy companion; original ZIP retained')
                report=json.loads((stage/'report.json').read_text(encoding='utf-8-sig'))
                if not any(s.get('evidence_id')==identity for s in report.get('sessions',[])):raise ValueError('JSON companion evidence identity mismatch')
                html=(stage/'report.html').read_text(encoding='utf-8-sig')
                has_data=any(s.get('inventory') or s.get('performance') or s.get('benchmark') for s in report.get('sessions',[]))
                if '<html' not in html.lower() or has_data and not (identity in html or str(sid) in html):raise ValueError('HTML companion evidence identity mismatch')
            else:
                from .analysis.obd import analyze_obd,export_obd_report
                export_obd_report(analyze_obd([stage/ASSETS[0]]),stage/'report.html')
        except Exception as exc:
            error=str(exc)
            for name in ASSETS[1:]:
                if (stage/name).is_file():(stage/name).rename(stage/('source-'+name))
        # The date belongs in one leaf, not three repeated intermediate directories.
        folder=self._path(relative)
        metadata=dict(schema_version=2,library_id=key,session_id=sid,started_utc=summary['started'],ended_utc=summary.get('ended'),duration_seconds=summary.get('duration_seconds'),timezone='Europe/Athens',started_local=local.isoformat(),
            **facts,status='EXPORT_PARTIAL' if error else facts['outcome'],report_error=error,evidence_id=identity,original_journal_sha256=journal,
            ecu=json.loads(members.get('ecu-identifiers.json',b'[]')),application_versions=summary.get('application_versions',[]),
            source=source,hashes={n:digest(stage/n) for n in ASSETS+PRESERVED if (stage/n).is_file()},originals_preserved=True,cloud_upload=False)
        write_json(stage/'run-metadata.json',metadata)
        for file in stage.iterdir():
            if file.is_file():
                with file.open('rb+') as f:os.fsync(f.fileno())
        folder.parent.mkdir(parents=True,exist_ok=True)
        try:stage.rename(folder) # same-volume, fresh directory; never replace a run
        except FileExistsError:
            existing,_=self._metadata_at(folder)
            if existing['library_id']!=key:raise ValueError('Report short-ID collision; destination was not overwritten')
            self.recover_index();self._discard_owned_scratch(stage);return self.result(self.verify(key))
        self._register(folder,metadata,source)
        return self.result(self.get(key))

    def publish_closed(self,session_id):
        from .logging.bundle import export_research_bundle
        old=next((r for r in self.rows() if r['session_id']==session_id),None)
        if old:return self.retry(old['library_id']) if old['status']=='EXPORT_PARTIAL' else self.result(self.verify(old['library_id']))
        stage=self.stage();export_research_bundle(self.root,session_id,stage/ASSETS[0])
        return self._publish(stage)

    def publish_bundle(self,bundle,companions=None):
        bundle=Path(bundle).resolve();sha=digest(bundle)
        from .research.evidence import read_bundle
        _,members=read_bundle(bundle);key,_=_run_identity(json.loads(members['session-summary.json']),members)
        with self.db() as db:old=db.execute('SELECT run_id FROM imports WHERE source_sha=?',(sha,)).fetchone()
        if old:return self.result(self.verify(old['run_id']))
        with self.db() as db:old=db.execute('SELECT id FROM runs WHERE id=?',(key,)).fetchone()
        if old:
            row=self.verify(key)
            with self.db() as db:db.execute('INSERT OR IGNORE INTO imports VALUES(?,?,?)',(sha,key,str(bundle)))
            if digest(bundle)!=sha:raise ValueError('Original input changed')
            return self.result(row)
        stage=self.stage()
        with zipfile.ZipFile(bundle) as z:
            wrapped='run-export.json' in z.namelist()
            if wrapped:
                (stage/ASSETS[0]).write_bytes(z.read(ASSETS[0]));companions=None
            else:shutil.copyfile(bundle,stage/ASSETS[0])
        if not wrapped and digest(stage/ASSETS[0])!=sha or digest(bundle)!=sha:raise ValueError('Input changed during copy')
        result=self._publish(stage,dict(path=str(bundle),sha256=sha),companions)
        if digest(bundle)!=sha:raise ValueError('Original input changed')
        return result

    @staticmethod
    def result(row):
        folder=Path(row['folder'])
        return dict(library_id=row['library_id'],report_status=row['status'],bundle_path=str(folder/ASSETS[0]),obd_report_path=str(folder/'report.html') if 'report.html' in row['hashes'] else None,
            bundle_sha256=row['hashes'][ASSETS[0]],checksums_verified=row['status']!='EXPORT_PARTIAL',original_journal_sha256=row['original_journal_sha256'],report_error=row.get('report_error'))

    def retry(self,key):
        row=self.verify(key)
        if row['status']!='EXPORT_PARTIAL':return self.result(row)
        from .analysis.obd import analyze_obd,export_obd_report
        folder=Path(row['folder']);stage=self.stage();shutil.copyfile(folder/ASSETS[0],stage/ASSETS[0])
        export_obd_report(analyze_obd([stage/ASSETS[0]]),stage/'report.html')
        for name in ASSETS[1:]:
            if (folder/name).exists() and name in row['hashes']:
                # A valid imported companion is preserved, even when another was missing.
                continue
            os.replace(stage/name,folder/name)
        row.update(status=row['outcome'],report_error=None,hashes={n:digest(folder/n) for n in ASSETS+PRESERVED if (folder/n).is_file()})
        for k in ('folder','display_label'):row.pop(k,None)
        write_json(folder/'run-metadata.json',row);self._register(folder,row)
        self._discard_owned_scratch(stage);return self.result(self.get(key))

    def recover_index(self):
        """After a rename/index interruption, register only hash-verified managed leaves."""
        candidates={}
        for folder in self._managed_leaves(self.reports):
            metadata,_=self._metadata_at(folder);key=metadata['library_id']
            candidates.setdefault(key,[]).append((folder,metadata))
        # Keep an already registered verified pointer, including an explicit rollback.
        with self.db() as db:known={r['id']:r['path'] for r in db.execute('SELECT id,path FROM runs')}
        for key,leaves in candidates.items():
            current=next(((p,m) for p,m in leaves if p.relative_to(self.reports).as_posix()==known.get(key)),None)
            folder,metadata=current or sorted(leaves,key=lambda item:(len(item[0].relative_to(self.reports).parts),str(item[0])))[0]
            self._register(folder,metadata,metadata.get('source'),rebase=current is None)
        return dict(recovered=len(candidates),originals_retained=True)

    def _managed_leaves(self,folder):
        folder=self._path(Path(folder).relative_to(self.reports));leaves=[]
        for path in regular_files(folder,limit=100000):
            if path.name!='run-metadata.json':continue
            parts=path.parent.relative_to(self.reports).parts
            if parts and parts[0] in BUCKETS and (len(parts)==2 or len(parts)==5 and all(p.isdigit() for p in parts[1:4])):leaves.append(path.parent)
        return sorted(leaves)

    def label(self,key,label):
        self.get(key)
        if len(label)>160:raise ValueError('Display label is limited to 160 characters')
        with self.db() as db:db.execute('UPDATE runs SET label=? WHERE id=?',(label,key))

    def annotate(self,key,event,timestamp,uncertainty,note=''):
        row=self.get(key);dt=datetime.fromisoformat(timestamp)
        if event not in {'Stop','Sport on','Sport off','Acceleration','Note'} or dt.tzinfo is None or not isinstance(uncertainty,(int,float)) or isinstance(uncertainty,bool) or not __import__('math').isfinite(uncertainty) or not 0<=uncertainty<=3600:raise ValueError('Explicit timezone and finite uncertainty 0..3600 seconds required')
        if len(note)>512:raise ValueError('Annotation note is limited to 512 characters')
        record=dict(event=event,timestamp=timestamp,uncertainty_seconds=uncertainty,note=note,provenance='USER_REPORTED_OFFLINE',ecu_confirmed=False,original_journal_modified=False)
        with self.db() as db:db.execute('INSERT INTO annotations VALUES(?,?,?)',(uuid.uuid4().hex,key,json.dumps(record)))
        return record

    def annotations(self,key):
        self.get(key)
        with self.db() as db:return [json.loads(r[0]) for r in db.execute('SELECT metadata FROM annotations WHERE run_id=? ORDER BY rowid',(key,))]

    def usage(self):
        rows=self.rows();sizes=[p.stat().st_size for p in regular_files(self.reports,limit=100000)]
        seen={};duplicates=0
        for row in rows:
            h=row['hashes'][ASSETS[0]];duplicates+=h in seen;seen[h]=True
        return dict(runs=len(rows),bytes=sum(sizes),oldest_utc=min((r['started_utc'] for r in rows),default=None),duplicate_bundle_checksums=duplicates,automatic_purge=False)

    def export_run(self,key,target,*,include_annotations=False):
        row=self.verify(key);folder=Path(row['folder']);target=Path(target).resolve()
        if target.exists() or target.is_relative_to(self.root):raise ValueError('Select a fresh ZIP destination outside the data root')
        names=[n for n in (*ASSETS,*PRESERVED,'run-metadata.json') if (folder/n).is_file()]
        temp=target.with_name(target.name+'.'+uuid.uuid4().hex+'.tmp')
        with zipfile.ZipFile(temp,'x',zipfile.ZIP_DEFLATED) as z:
            for name in names:z.write(folder/name,name)
            info=dict(schema_version=1,kind='MOKKA_PRIVATE_RUN',members={n:digest(folder/n) for n in names})
            if include_annotations:
                annotations=self.annotations(key)
                data=json.dumps(dict(provenance='USER_REPORTED_OFFLINE',annotations=annotations),ensure_ascii=False).encode('utf-8')
                z.writestr('annotations.json',data);info['members']['annotations.json']=hashlib.sha256(data).hexdigest()
                from html import escape
                html=('<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'"><title>Private user timeline annotations</title></head><body><h1>User-reported offline annotations</h1><p>Uncertain human timeline; ECU confirmation absent. Original journal unchanged. These markers do not establish causation.</p><pre>'+escape(json.dumps(annotations,ensure_ascii=False,indent=2))+'</pre></body></html>').encode('utf-8')
                z.writestr('annotations.html',html);info['members']['annotations.html']=hashlib.sha256(html).hexdigest()
            z.writestr('run-export.json',json.dumps(info))
        from .research.evidence import read_bundle
        read_bundle(temp)
        with temp.open('rb+') as f:os.fsync(f.fileno())
        # Exclusive link prevents a race from overwriting a destination selected by another process.
        os.link(temp,target);temp.unlink()
        return target

    def preview_migration(self,folder):
        folder=Path(folder).resolve();groups=[]
        if folder.is_relative_to(self.reports):return self.preview_flatten(folder)
        # This older import mode intentionally scans only a selected flat folder.
        list(regular_files(folder,limit=100000))
        for bundle in sorted(folder.glob('*.zip')):
            try:
                from .research.evidence import read_bundle
                _,members=read_bundle(bundle);summary=json.loads(members['session-summary.json'])
                sources=[bundle]+[bundle.with_suffix(ext) for ext in ('.json','.html') if bundle.with_suffix(ext).is_file()]
                groups.append(dict(session_id=summary['session_id'],sources=[dict(path=str(s),bytes=s.stat().st_size,sha256=digest(s)) for s in sources],action='COPY; retain all originals'))
            except (ValueError,KeyError,zipfile.BadZipFile) as exc:groups.append(dict(blocked=str(bundle),reason=str(exc),action='NO ACTION'))
        return _preview(dict(schema_version=2,operation='IMPORT_FLAT_EXPORTS',destination=str(self.reports),groups=groups,source_policy='COPY_ONLY; no move/delete; originals remain'))

    def migrate(self,plan,approval_token,*,cancelled=None):
        _approved(plan,approval_token)
        if plan['destination']!=str(self.reports):raise ValueError('Preview destination differs from this library')
        if plan.get('operation')=='FLATTEN_REPORTS_COPY':return self._flatten(plan,cancelled=cancelled)
        token=approval_token
        results=[];audit=self.index/('migration-'+token+'.json')
        for group in plan['groups']:
            if 'sources' not in group:continue
            if cancelled and cancelled():raise MigrationCancelled('Migration cancelled; completed copies and all originals retained. Reapprove the same preview to resume.')
            for source in group['sources']:
                if digest(source['path'])!=source['sha256']:raise ValueError('Migration input changed; generate a new preview')
            bundle=Path(group['sources'][0]['path']);companions={Path(s['path']).suffix:s['path'] for s in group['sources'][1:]}
            results.append(self.publish_bundle(bundle,companions));write_json(audit,dict(plan=plan,completed=results,originals_retained=True))
        return results

    def preview_flatten(self,folder=None):
        """Read-only exact deep-to-flat copy and index-rebase plan, never a purge."""
        folder=self.reports if folder is None else Path(folder)
        leaves=self._managed_leaves(folder);groups=[];retained=[];seen=set()
        with self.db() as db:registered={r['id']:dict(r) for r in db.execute('SELECT * FROM runs')}
        for source in leaves:
            try:
                metadata,summary=self._metadata_at(source);key=metadata['library_id']
                if len(source.relative_to(self.reports).parts)==2:
                    retained.append(dict(path=str(source),action='KEEP existing flat run'));continue
                if key in seen:
                    retained.append(dict(path=str(source),action='KEEP duplicate legacy evidence; one canonical History row'));continue
                seen.add(key);_,_,relative=_run_location(summary,key);target=self._path(relative)
                files=[dict(path=str(p),name=p.name,bytes=p.stat().st_size,sha256=digest(p)) for p in sorted(regular_files(source,limit=8))]
                current=registered.get(key);before=dict(path=current['path'],metadata=json.loads(current['metadata'])) if current else None
                canonical_files=[]
                if target.exists():
                    other,_=self._metadata_at(target)
                    if other['library_id']!=key:raise ValueError('Flat destination has a different full identity; no overwrite')
                    canonical_files=[dict(path=str(p),name=p.name,bytes=p.stat().st_size,sha256=digest(p)) for p in sorted(regular_files(target,limit=8))]
                groups.append(dict(library_id=key,session_id=summary['session_id'],source_folder=str(source),destination_folder=str(target),sources=files,bytes=sum(f['bytes'] for f in files),
                    destination_exists=target.exists(),canonical_files=canonical_files,copy_mode='REUSE_VERIFIED_CANONICAL' if target.exists() else 'COPY',index_before=before,
                    action='VERIFY_EXISTING_CANONICAL then REBASE_INDEX; retain every original' if target.exists() else 'COPY_AND_VERIFY then REBASE_INDEX; retain every original',preserved_legacy_companions=[f['name'] for f in files if f['name'] in PRESERVED]))
            except (ValueError,KeyError,OSError,zipfile.BadZipFile) as exc:groups.append(dict(blocked=str(source),reason=str(exc),action='NO ACTION'))
        return _preview(dict(schema_version=2,operation='FLATTEN_REPORTS_COPY',preview_nonce=uuid.uuid4().hex,destination=str(self.reports),selected_root=str(folder),groups=groups,retained=retained,
            copy_bytes=sum(g.get('bytes',0) for g in groups if not g.get('destination_exists')),source_policy='COPY_ONLY; originals, journals and databases stay in place; rollback changes index pointers only',automatic_cleanup=False))

    def _audit_path(self,token):
        if not isinstance(token,str) or len(token)!=64 or any(c not in '0123456789abcdef' for c in token):raise ValueError('Invalid migration identity')
        return inside(self.index,self.index/('migration-'+token+'.json'))

    def _check_sources(self,group):
        source=self._path(Path(group['source_folder']).relative_to(self.reports))
        metadata,summary=self._metadata_at(source)
        if metadata['library_id']!=group['library_id']:raise ValueError('Migration source identity changed')
        _,_,relative=_run_location(summary,metadata['library_id'])
        if len(source.relative_to(self.reports).parts)!=5 or group['destination_folder']!=str(self._path(relative)):raise ValueError('Migration paths differ from verified deep-to-flat layout')
        expected={f['name'] for f in group['sources']}
        if {p.name for p in regular_files(source,limit=8)}!=expected:raise ValueError('Migration input changed; generate a new preview')
        for item in group['sources']:
            path=inside(source,source/item['name'])
            if str(path)!=item['path'] or path.stat().st_size!=item['bytes'] or digest(path)!=item['sha256']:raise ValueError('Migration input changed; generate a new preview')
        return metadata

    def _flatten(self,plan,*,cancelled=None):
        token=plan['approval_token'];audit_path=self._audit_path(token)
        audit=json.loads(audit_path.read_text(encoding='utf-8')) if audit_path.exists() else dict(plan=plan,completed=[],stages={},originals_retained=True,state='COPYING')
        if audit.get('plan')!=plan:raise ValueError('Migration checkpoint differs from approved plan')
        if audit.get('state')=='ROLLED_BACK':raise ValueError('This migration was rolled back; create a new preview')
        def checkpoint():write_json(audit_path,audit)
        def check_cancel():
            if cancelled and cancelled():
                audit['state']='CANCELLED';checkpoint()
                raise MigrationCancelled('Migration cancelled; originals and copied bytes retained. Reapprove this exact preview to resume.')
        for group in plan['groups']:
            if 'sources' not in group:continue
            key=group['library_id'];check_cancel();metadata=self._check_sources(group)
            target=self._path(Path(group['destination_folder']).relative_to(self.reports))
            if group['copy_mode']=='REUSE_VERIFIED_CANONICAL' and not target.exists():raise ValueError('Approved canonical destination is missing; create a new preview')
            if not target.exists():
                saved=audit['stages'].get(key);stage=self._path(saved) if saved else self.stage()
                if not saved:audit['stages'][key]=stage.relative_to(self.reports).as_posix();checkpoint()
                if stage.parent!=self.reports/'.staging':raise ValueError('Invalid migration staging path')
                for item in group['sources']:
                    check_cancel();destination=inside(stage,stage/item['name'])
                    if destination.exists():
                        if digest(destination)!=item['sha256']:raise ValueError('Interrupted copy checksum differs; preserved for review')
                    else:
                        with Path(item['path']).open('rb') as src,destination.open('xb') as dst:
                            shutil.copyfileobj(src,dst);dst.flush();os.fsync(dst.fileno())
                    if digest(destination)!=item['sha256']:raise ValueError('Copied file failed SHA-256 verification')
                self._check_sources(group);check_cancel();target.parent.mkdir(parents=True,exist_ok=True)
                try:stage.rename(target)
                except FileExistsError:pass # Concurrent destinations are checked byte-for-byte below.
            copied,_=self._metadata_at(target)
            expected_files=group['canonical_files'] if group['copy_mode']=='REUSE_VERIFIED_CANONICAL' else group['sources']
            if copied['library_id']!=key or {p.name for p in regular_files(target,limit=8)}!={f['name'] for f in expected_files} or any(digest(target/f['name'])!=f['sha256'] for f in expected_files):raise ValueError('Copied destination differs; index was not rebased')
            self._check_sources(group);check_cancel()
            before=group['index_before'];expected=before['path'] if before else None;relative=target.relative_to(self.reports).as_posix()
            with self.db() as db:
                db.execute('BEGIN IMMEDIATE');current=db.execute('SELECT path FROM runs WHERE id=?',(key,)).fetchone();actual=current['path'] if current else None
                if actual not in (expected,relative):raise ValueError('Canonical index changed after preview; create a new preview')
                db.execute('INSERT INTO runs(id,path,metadata) VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET path=excluded.path,metadata=excluded.metadata',(key,relative,json.dumps(copied)))
            if key not in audit['completed']:audit['completed'].append(key)
            audit['state']='COPYING';checkpoint()
        audit['state']='COMPLETED';checkpoint()
        return [self.result(self.verify(g['library_id'])) for g in plan['groups'] if 'sources' in g]

    def migrations(self):
        result=[]
        for path in sorted(self.index.glob('migration-*.json')):
            inside(self.index,path);audit=json.loads(path.read_text(encoding='utf-8'));plan=audit.get('plan',{})
            if plan.get('operation')=='FLATTEN_REPORTS_COPY':result.append(dict(token=plan['approval_token'],state=audit['state'],completed=len(audit['completed']),path=str(path)))
        return result

    def preview_migration_rollback(self,token):
        audit=json.loads(self._audit_path(token).read_text(encoding='utf-8'));plan=audit['plan'];_approved(plan,token)
        if plan.get('operation')!='FLATTEN_REPORTS_COPY' or audit['state']=='ROLLED_BACK':raise ValueError('No reversible copy migration')
        groups=[]
        for group in plan['groups']:
            if group.get('library_id') not in audit['completed']:continue
            metadata=self._check_sources(group);current=self.verify(group['library_id']);source=Path(group['source_folder']);target=Path(group['destination_folder'])
            if current['folder']!=str(target):raise ValueError('Canonical pointer changed; rollback preview blocked')
            old=group['index_before'];restore=old['path'] if old else source.relative_to(self.reports).as_posix()
            groups.append(dict(library_id=group['library_id'],from_path=target.relative_to(self.reports).as_posix(),to_path=restore,metadata=old['metadata'] if old else metadata,action='RESTORE_INDEX_POINTER_ONLY; retain both folders'))
        return _preview(dict(schema_version=1,operation='ROLLBACK_REPORT_INDEX',destination=str(self.reports),migration_token=token,groups=groups,files_deleted=0,files_moved=0,labels_annotations_preserved=True))

    def rollback_migration(self,preview,approval_token):
        _approved(preview,approval_token)
        if preview!=self.preview_migration_rollback(preview['migration_token']):raise ValueError('Rollback state changed; approve a fresh preview')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            for group in preview['groups']:
                current=db.execute('SELECT path FROM runs WHERE id=?',(group['library_id'],)).fetchone()
                if current is None or current['path']!=group['from_path']:raise ValueError('Canonical index changed before rollback')
                db.execute('UPDATE runs SET path=?,metadata=? WHERE id=?',(group['to_path'],json.dumps(group['metadata']),group['library_id']))
        path=self._audit_path(preview['migration_token']);audit=json.loads(path.read_text(encoding='utf-8'));audit['state']='ROLLED_BACK';write_json(path,audit)
        return dict(restored=len(preview['groups']),files_deleted=0,files_moved=0)
