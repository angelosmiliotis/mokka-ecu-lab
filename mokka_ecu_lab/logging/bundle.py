"""Offline evidence ZIPs for closed local sessions. Never modifies raw input."""
import base64
import hashlib
import json
import os
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from collections import defaultdict
from . import list_sessions, export_csv, export_jsonl, utc_now
from mokka_ecu_lab import __version__
from mokka_ecu_lab.capture import DECODER_VERSION
from mokka_ecu_lab.discovery import discovery_report
from mokka_ecu_lab.protocols import BITMAP_PIDS, supported_pids
from mokka_ecu_lab.protocols.isotp import parse_reply
from mokka_ecu_lab.sensors import load_registry
from mokka_ecu_lab.layouts import RAW_ONLY_PIDS, layout_evidence


def export_research_bundle(root: Path, session_id: str, target: Path, *, include_private_phases=False):
    root, target = Path(root), Path(target)
    session = next((s for s in list_sessions(root) if s['id']==session_id),None)
    if not session: raise ValueError('Unknown session')
    if not session['ended']: raise ValueError('Stop Recording / Finish session before exporting a research bundle')
    if target.suffix.lower() != '.zip': raise ValueError('Research bundle target must be a ZIP')
    source = root/session['raw_path']
    if not source.is_file(): raise ValueError('Original raw journal is unavailable')
    target.parent.mkdir(parents=True,exist_ok=True)
    evidence = json.loads(session.get('metadata') or '{}').get('capture_evidence',{})
    components, warnings = {}, []
    with tempfile.TemporaryDirectory(prefix='mokka-bundle-') as work:
        folder=Path(work)
        raw_path=folder/'raw-redacted.jsonl'; export_jsonl(source,raw_path,include_private_phases=include_private_phases)
        export_csv(root,session_id,folder/'measurements.csv')
        support, pages = {}, {}
        errors, versions, decoder_versions, identifiers, markers = [], set(), set(), set(), []
        raw_observations=[]
        stats = defaultdict(lambda:dict(requests=0,responses=0,decoded_samples=0,times=[],timestamps=[]))
        sent_requests=0; transaction_count=0
        for line in raw_path.open(encoding='utf-8'):
            record=json.loads(line)
            if record.get('record_type')=='marker':
                markers.append({k:record.get(k) for k in ('id','timestamp','monotonic_ns','event','note','note_redacted','mode',
                    'phase','phase_redacted','provenance','precision','uncertainty_seconds','ecu_confirmed','ecu','source_kind')})
                continue
            if record.get('record_type') != 'transaction': continue
            transaction_count+=1; sent_requests+=bool(record.get('sent',True))
            if record.get('application_version'): versions.add(record['application_version'])
            if record.get('decoder_version'): decoder_versions.add(record['decoder_version'])
            pid_text=record.get('pid')
            pid=int(pid_text,16) if pid_text else None
            if record.get('support_evidence'):
                support={e:set(p) for e,p in record['support_evidence'].items()}
                pages={e:set(p) for e,p in record.get('support_pages',{}).items()}
            if pid is not None:
                result=parse_reply(base64.b64decode(record['raw_b64']),pid,record.get('command',''))
                if pid in RAW_ONLY_PIDS:
                    for reply in result.responses:
                        if reply.negative_code is not None: continue
                        retained=next((s for s in record.get('raw_samples',[]) if s.get('ecu')==reply.header),{})
                        raw_observations.append(dict(request=record['command'],ecu=reply.header,
                            timestamp=record['timestamp'],monotonic_ns=record['monotonic_ns'],
                            source_kind=record.get('source_kind','UNKNOWN'),mode=record.get('mode','UNKNOWN'),
                            raw_only=bool(record.get('raw_only')),framing_valid=True,
                            payload_hex=reply.data.hex(' ').upper(),**layout_evidence(pid,reply.data),
                            context_readings=retained.get('context_readings',{}),
                            context_state='RECORDED_NON_SIMULTANEOUS' if retained.get('context_readings') else 'UNAVAILABLE'))
                if pid in BITMAP_PIDS:
                    for reply in result.responses:
                        ecu=reply.header or 'headerless'
                        if reply.negative_code is None and len(reply.data)==4 and (pid==0 or
                                (pid in support.get(ecu,set()) and pid-32 in pages.get(ecu,set()))):
                            support.setdefault(ecu,set()).update(supported_pids(reply.data,pid))
                            pages.setdefault(ecu,set()).add(pid)
                request=stats['request:'+pid_text]
                request['requests']+=bool(record.get('sent',True))
                if record.get('sent',True):
                    request['times'].append(record['monotonic_ns']); request['timestamps'].append(record['timestamp'])
            for reply in record.get('parsed',[]):
                ecu=reply.get('ecu') or 'headerless'; identifiers.add(ecu)
                if pid_text: stats[ecu+':'+pid_text]['responses']+=1
            for problem in record.get('protocol_errors',[])+record.get('negative_responses',[]):
                if problem.get('ecu'): identifiers.add(problem['ecu'])
            if record.get('status')!='OK':
                errors.append(dict(timestamp=record['timestamp'],request=record.get('command'),
                                   status=record.get('status'),error=record.get('error',''),
                                   protocol_errors=record.get('protocol_errors',[]),negative_responses=record.get('negative_responses',[])))
        if evidence.get('support'):
            support={e:set(p) for e,p in evidence['support'].items()}
            pages={e:set(p) for e,p in evidence.get('support_pages',{}).items()}
        # These are recorded session snapshots, including discovery made before
        # recording started. Never substitute the current GUI's connection.
        report=evidence.get('report')
        if not report:
            report=discovery_report(support,pages,{},mode=session['mode'])
            warnings.append('No recorded discovery field snapshot; support reconstructed from retained bitmaps when possible')
        report=dict(report,exported_at=utc_now(),evidence_state='RECORDED_SESSION',vehicle_verification='UNVERIFIED')
        summary_rows=[{k:e.get(k) for k in ('request','pid','ecu','support','availability','verification','vehicle_verification')}
                      for e in report['standard']]
        identifiers.update(support)
        # CSV is the recorded decoded database, not values invented by export.
        import csv
        basic_ids={s.id:f'{pid:02X}' for pid,s in load_registry().items()}
        seen_decoded=set()
        for row in csv.DictReader((folder/'measurements.csv').open(encoding='utf-8-sig')):
            key=row['ecu']+':'+row['sensor_id']; entry=stats[key]
            entry['decoded_samples']+=1
            entry['times'].append(int(row['monotonic_ns'])); entry['timestamps'].append(row['timestamp'])
            pid_text=basic_ids.get(row['sensor_id'])
            if row['sensor_id'].startswith('sae_'): pid_text=row['sensor_id'].split('_')[1].upper()
            frame=(row['ecu'],pid_text,row['transaction_id'])
            if pid_text and frame not in seen_decoded:
                seen_decoded.add(frame); entry=stats[row['ecu']+':'+pid_text]
                entry['decoded_samples']+=1; entry['times'].append(int(row['monotonic_ns'])); entry['timestamps'].append(row['timestamp'])
        intervals={}
        for key,entry in sorted(stats.items()):
            times=sorted(entry.pop('times')); stamps=entry.pop('timestamps')
            gaps=[(b-a)/1e9 for a,b in zip(times,times[1:]) if b>a]
            intervals[key]=dict(entry,first_sample_utc=min(stamps) if stamps else None,last_sample_utc=max(stamps) if stamps else None,
                observed_interval_count=len(gaps),observed_mean_seconds=sum(gaps)/len(gaps) if gaps else None,
                observed_min_seconds=min(gaps) if gaps else None,observed_max_seconds=max(gaps) if gaps else None,
                interval_basis='monotonic timestamps; no guaranteed rate')
        duration=(datetime.fromisoformat(session['ended'])-datetime.fromisoformat(session['started'])).total_seconds()
        summary=dict(session_id=session_id,started=session['started'],ended=session['ended'],duration_seconds=duration,
                     mode=session['mode'],requests=session['requests'],errors=session['errors'],
                     recorded_transactions=transaction_count,sent_requests=sent_requests,marker_count=len(markers),
                     application_versions=sorted(versions) or ([evidence['application_version']] if evidence.get('application_version') else []),
                     decoder_versions=sorted(decoder_versions) or ([evidence['decoder_version']] if evidence.get('decoder_version') else []),
                     export_application_version=__version__,export_decoder_version=DECODER_VERSION,
                     capture_weights=evidence.get('capture_weights',{}),vehicle_verified=False,
                     capture_raw_pids=evidence.get('capture_raw_pids',[]),
                     acquisition_receipt=evidence.get('acquisition_receipt'),
                     session_coordinator=evidence.get('session_coordinator'),
                     stationary_benchmark=evidence.get('stationary_benchmark'),
                     original_journal_sha256=hashlib.sha256((root/session['raw_path']).read_bytes()).hexdigest(),
                     coordinator_snapshot_scope='Journal-close checkpoint; final ZIP verification is stored separately in the local session database',
                     recovery=json.loads(session.get('metadata') or '{}').get('recovery'),
                     raw_only_samples=sum(r['raw_only'] for r in raw_observations),
                     redaction='Default application export; adapter/port/identity bytes and personal metadata excluded')
        for name,data in [('discovery-report.json',report),('session-summary.json',summary),
                          ('pid-support.json',summary_rows),('ecu-identifiers.json',sorted(identifiers)),
                          ('polling-statistics.json',intervals),('errors.json',errors),('markers.json',markers),
                          ('raw-observations.json',raw_observations)]:
            (folder/name).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        if evidence.get('acquisition_receipt'):
            (folder/'acquisition-receipt.json').write_text(json.dumps(evidence['acquisition_receipt'],ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        if not summary['application_versions']: warnings.append('Recording application version unavailable (legacy journal)')
        if not summary['decoder_versions']: warnings.append('Recording decoder version unavailable (legacy journal)')
        if not seen_decoded: warnings.append('No decoded measurements recorded; CSV contains its schema only')
        if not evidence.get('discovery_completed',evidence.get('discovery_prepared')): warnings.append('No completed explicit discovery stored for this session')
        if any(m.get('note_redacted') for m in markers): warnings.append('Free-text Note contents redacted by default; original local journal retains notes')
        for path in sorted(folder.iterdir()):
            components[path.name]=dict(state='AVAILABLE',bytes=path.stat().st_size,
                                      sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        manifest=dict(schema_version=1,created_at=utc_now(),session_id=session_id,components=components,
                      unavailable=warnings,local_original_unchanged=True,redacted=True,cloud_upload=False,
                      private_phase_annotations_included=include_private_phases,
                      checksum_scope='All content files plus manifest are covered by SHA256SUMS.txt; checksum file cannot hash itself')
        (folder/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
        lines=[hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name for p in sorted(folder.iterdir())]
        (folder/'SHA256SUMS.txt').write_text('\n'.join(lines)+'\n',encoding='utf-8')
        fd, temporary=tempfile.mkstemp(prefix=target.stem+'-',suffix='.zip',dir=target.parent); os.close(fd)
        try:
            with zipfile.ZipFile(temporary,'w',zipfile.ZIP_DEFLATED) as bundle:
                for path in sorted(folder.iterdir()): bundle.write(path,path.name)
            os.replace(temporary,target)
        finally:
            if os.path.exists(temporary): os.unlink(temporary)
    return manifest
