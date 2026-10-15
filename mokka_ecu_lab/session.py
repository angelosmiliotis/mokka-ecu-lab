"""Worker-owned session lifecycle and offline closure; no transport implementation."""
from copy import deepcopy
from pathlib import Path
import hashlib
import json
import uuid
from .logging import utc_now, list_sessions, connect_database
from .logging.bundle import export_research_bundle
from .research.evidence import read_bundle

CONFLICTS = frozenset({'connect','disconnect','start','stop','record','record_stop','discover',
    'monitor_discovery','drive_capture','full_auto','retry_auto','select','priorities','rate','replay','session_connect','benchmark_start','benchmark_stop','bench_auto_start','bench_auto_stop'})


class SessionCoordinator:
    """One canonical lifecycle, mutated only by the serialized acquisition worker."""
    def __init__(self):
        self.data = dict(state='DISCONNECTED', reason='Connect explicitly; no recording is open',
            active=False, session_id=None, bundle_path=None, export_error=None, transitions=[])
        self.finish_requested = False

    @property
    def active(self): return self.data['active']

    def transition(self, state, reason, **values):
        self.data.update(values, state=state, reason=reason, acknowledged_at=utc_now())
        self.data['transitions'].append(dict(state=state, reason=reason, timestamp=self.data['acknowledged_at']))
        self.data['transitions'] = self.data['transitions'][-64:]

    def begin(self):
        self.data.update(active=True, session_id=None, bundle_path=None, export_error=None,
            checksums_verified=False,retry_export=False,recorded_mode=None,recorded_ecus=[],exported_acquisition_receipt=None,
            recorded_transactions=0,transaction_errors=0,journal_closed=False,journal_path=None,duration_seconds=0,
            started_at=utc_now(), pre_connect_initialization_recorded=False,
            profile='DPF Research Priority; all eligible fixed standard PIDs + eligible RAW', transitions=[])
        self.finish_requested=False
        self.transition('RECORDING_SETUP','Starting one journal before fresh session Discovery')

    def snapshot(self): return deepcopy(self.data)


def export_closed_session(root, session_id):
    """Fresh destination, independent checksum validation, original journal immutable."""
    root=Path(root)
    session=next((s for s in list_sessions(root) if s['id']==session_id),None)
    if not session or not session['ended']: raise ValueError('A confirmed closed session is required')
    source=(root/session['raw_path']).resolve()
    if not source.is_relative_to(root.resolve()): raise ValueError('Invalid journal location')
    original=hashlib.sha256(source.read_bytes()).hexdigest()
    target=root/'bundles'/f'{session_id}-research-{uuid.uuid4().hex[:12]}.zip'
    export_research_bundle(root,session_id,target)
    identity,members=read_bundle(target)
    summary=json.loads(members['session-summary.json'])
    if summary['session_id']!=session_id or not summary['ended']: raise ValueError('Exported session identity/closure mismatch')
    metadata=json.loads(session['metadata'] or '{}').get('capture_evidence',{})
    if metadata.get('session_coordinator') and not summary.get('acquisition_receipt'):
        raise ValueError('Automatic session acquisition receipt missing')
    if hashlib.sha256(source.read_bytes()).hexdigest()!=original: raise ValueError('Original journal changed during export')
    from .analysis.obd import analyze_obd,export_obd_report
    report_path=export_obd_report(analyze_obd([target]),target.with_suffix('.html'),[target])
    return dict(obd_report_path=str(report_path),bundle_path=str(target.resolve()), bundle_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
        verified_evidence_id=identity, original_journal_sha256=original, checksums_verified=True,
        recorded_mode=summary['mode'],recorded_ecus=json.loads(members.get('ecu-identifiers.json',b'[]')),
        exported_acquisition_receipt=summary.get('acquisition_receipt'))


def recover_interrupted_session(root, session_id):
    """Explicit offline recovery; preserve original bytes, including any truncated tail.

    Reconstruct only missing numeric rows from complete, strict positive records.
    Existing historical decoded rows are never overwritten with a new decoder.
    """
    import base64
    from .protocols.isotp import parse_reply
    from .sensors import load_registry
    from .sensors.extended import basic_range
    from .sensors.diesel import STANDARD_DIESEL
    from .research.evidence import MAX_RECORDS, MAX_MEMBER
    root=Path(root); session=next((s for s in list_sessions(root) if s['id']==session_id),None)
    if not session: raise ValueError('Unknown session')
    if session['ended']: return
    source=(root/session['raw_path']).resolve()
    if not source.is_relative_to(root.resolve()) or source.stat().st_size>MAX_MEMBER: raise ValueError('Invalid/oversized recovery journal')
    original=hashlib.sha256(source.read_bytes()).hexdigest(); records=[]; truncated=False
    with source.open(encoding='utf-8') as stream:
        for index,line in enumerate(stream):
            if index>=MAX_RECORDS: raise ValueError('Recovery record limit exceeded')
            try: record=json.loads(line)
            except json.JSONDecodeError:
                if not line.endswith('\n'): truncated=True; break
                raise ValueError('Malformed complete journal line; original preserved')
            if record.get('session_id')!=session_id: raise ValueError('Recovery journal session mismatch')
            if record.get('record_type')=='transaction': records.append(record)
    db=connect_database(root); registry=load_registry(); repaired=0;ranges={}
    try:
        for r in records:
            if not r.get('pid') or r.get('raw_only'): continue
            pid=int(r['pid'],16)
            if pid not in registry and pid not in STANDARD_DIESEL: continue
            for reply in parse_reply(base64.b64decode(r['raw_b64'],validate=True),pid,r['command']).responses:
                if reply.negative_code is not None: continue
                try:
                    if pid in STANDARD_DIESEL:
                        fields=STANDARD_DIESEL[pid].decode(reply.data)
                        if pid in {0x4F,0x50}:ranges.setdefault(reply.header,{})[pid]=reply.data
                    else:fields=[dict(sensor_id=registry[pid].id,value=basic_range(registry[pid],reply.data,ranges.get(reply.header,{})),unit=registry[pid].unit,state='AVAILABLE',verification='STANDARD_VERIFIED')]
                except ValueError: continue
                for f in fields:
                    if f['state']!='AVAILABLE': continue
                    cursor=db.execute('INSERT OR IGNORE INTO readings (session_id,transaction_id,timestamp,monotonic_ns,sensor_id,ecu,value,unit,verification,mode) VALUES (?,?,?,?,?,?,?,?,?,?)',
                        (session_id,r['id'],r['timestamp'],r['monotonic_ns'],f['sensor_id'],reply.header or 'headerless',f['value'],f['unit'],f.get('verification','STANDARD_VERIFIED'),r['mode']))
                    repaired+=cursor.rowcount
        metadata=json.loads(session['metadata'] or '{}')
        metadata['recovery']=dict(provenance='EXPLICIT_OFFLINE_RECOVERY',recovered_at=utc_now(),
            complete_transactions=len(records),truncated_tail_preserved=truncated,repaired_missing_rows=repaired,
            original_sha256=original,hardware_verified=False)
        evidence=metadata.setdefault('capture_evidence',{})
        receipt=evidence.get('acquisition_receipt')
        if receipt:
            receipt.update(recording_active=False,closed_at=utc_now(),capture_outcome=dict(state='INTERRUPTED',reason='Recovered without transport; recent checkpoint may lag journal'))
        db.execute('UPDATE sessions SET ended=?,metadata=?,requests=?,errors=? WHERE id=?',
            (utc_now(),json.dumps(metadata),len(records),sum(r['status']!='OK' for r in records),session_id))
        db.commit()
    finally: db.close()
    assert hashlib.sha256(source.read_bytes()).hexdigest()==original
