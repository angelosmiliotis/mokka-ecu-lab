"""Private copy-only run library. Original journals and imported files are immutable."""
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import hashlib,json,os,shutil,sqlite3,uuid,zipfile
from .local_paths import inside,regular_files

ASSETS=('original-research.zip','report.json','report.html')
PRESERVED=('source-report.json','source-report.html')

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

    def _register(self,folder,metadata,source=None):
        relative=folder.relative_to(self.reports).as_posix()
        with self.db() as db:
            db.execute('INSERT INTO runs(id,path,metadata) VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET metadata=excluded.metadata',(metadata['library_id'],relative,json.dumps(metadata)))
            if source:db.execute('INSERT OR IGNORE INTO imports VALUES(?,?,?)',(source['sha256'],metadata['library_id'],source['path']))

    def verify(self,key):
        row=self.get(key);folder=Path(row['folder'])
        for name,sha in row['hashes'].items():
            if name not in ASSETS+PRESERVED or digest(folder/name)!=sha:raise ValueError('Library asset changed: '+name)
        from .research.evidence import read_bundle
        read_bundle(folder/ASSETS[0])
        return row

    def _publish(self,stage,source=None,companions=None):
        from .research.evidence import read_bundle
        identity,members=read_bundle(stage/ASSETS[0]);summary=json.loads(members['session-summary.json'])
        sid=summary['session_id'];started=datetime.fromisoformat(summary['started'])
        if started.tzinfo is None:raise ValueError('Original UTC start needs an explicit timezone')
        local=started.astimezone(ZoneInfo('Europe/Athens'));facts=run_facts(summary)
        # A journal identifies a logical run; retries never create a second history row.
        journal=summary.get('original_journal_sha256') or hashlib.sha256(members['raw-redacted.jsonl']).hexdigest()
        key=hashlib.sha256((str(sid)+':'+journal).encode()).hexdigest()
        with self.db() as db:old=db.execute('SELECT * FROM runs WHERE id=?',(key,)).fetchone()
        if old:
            row=self.verify(key)
            if source:
                with self.db() as db:db.execute('INSERT OR IGNORE INTO imports VALUES(?,?,?)',(source['sha256'],key,source['path']))
            return self.result(row)
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
        bucket='FailedTests' if facts['outcome']!='COMPLETED' else 'Benchmarks' if facts['kind']=='BENCHMARK' else 'Drives'
        label='FAILED_BENCH_COM' if facts['outcome']=='FAILED_COM_OPEN' else 'BENCH_'+str(facts['rate']).replace('.0','')+'rps' if facts['kind']=='BENCHMARK' else 'DRIVE'
        # Only derived numeric date, fixed labels and hex identities enter paths.
        leaf=local.strftime('%Y-%m-%d_%H-%M-%S_')+label+'_'+key[:16]
        folder=self._path((Path(bucket)/local.strftime('%Y/%m/%d')/leaf).as_posix())
        metadata=dict(schema_version=1,library_id=key,session_id=sid,started_utc=summary['started'],ended_utc=summary.get('ended'),timezone='Europe/Athens',started_local=local.isoformat(),
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
            self.recover_index();return self.result(self.verify(key))
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
        read_bundle(bundle)
        with self.db() as db:old=db.execute('SELECT run_id FROM imports WHERE source_sha=?',(sha,)).fetchone()
        if old:return self.result(self.verify(old['run_id']))
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
        return self.result(self.get(key))

    def recover_index(self):
        """After a rename/index interruption, register only hash-verified managed leaves."""
        for path in self.reports.glob('*/*/*/*/*/run-metadata.json'):
            folder=path.parent
            if not self._path(folder.relative_to(self.reports)).is_dir():raise ValueError('Invalid recovered folder')
            inside(self.root,path);metadata=json.loads(path.read_text(encoding='utf-8'))
            if all(name in ASSETS+PRESERVED and digest(folder/name)==sha for name,sha in metadata['hashes'].items()):self._register(folder,metadata,metadata.get('source'))

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
        if folder.is_relative_to(self.reports):raise ValueError('Select legacy exports, not the managed report tree')
        for bundle in sorted(folder.glob('*.zip')):
            try:
                from .research.evidence import read_bundle
                _,members=read_bundle(bundle);summary=json.loads(members['session-summary.json'])
                sources=[bundle]+[bundle.with_suffix(ext) for ext in ('.json','.html') if bundle.with_suffix(ext).is_file()]
                groups.append(dict(session_id=summary['session_id'],sources=[dict(path=str(s),bytes=s.stat().st_size,sha256=digest(s)) for s in sources],action='COPY; retain all originals'))
            except (ValueError,KeyError,zipfile.BadZipFile) as exc:groups.append(dict(blocked=str(bundle),reason=str(exc),action='NO ACTION'))
        plan=dict(schema_version=1,destination=str(self.reports),groups=groups,source_policy='COPY_ONLY; no move/delete; originals remain')
        plan['approval_token']=hashlib.sha256(json.dumps(plan,sort_keys=True).encode()).hexdigest()
        return plan

    def migrate(self,plan,approval_token):
        check=dict(plan);token=check.pop('approval_token',None)
        if token!=approval_token or token!=hashlib.sha256(json.dumps(check,sort_keys=True).encode()).hexdigest() or plan['destination']!=str(self.reports):raise ValueError('Explicit approval of this exact preview is required')
        results=[];audit=self.index/('migration-'+token+'.json')
        for group in plan['groups']:
            if 'sources' not in group:continue
            for source in group['sources']:
                if digest(source['path'])!=source['sha256']:raise ValueError('Migration input changed; generate a new preview')
            bundle=Path(group['sources'][0]['path']);companions={Path(s['path']).suffix:s['path'] for s in group['sources'][1:]}
            results.append(self.publish_bundle(bundle,companions));write_json(audit,dict(plan=plan,completed=results,originals_retained=True))
        return results
