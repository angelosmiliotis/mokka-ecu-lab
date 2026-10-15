"""Bounded, checksum-checked offline bundle analysis from original wire bytes.

Session, ECU, mode and source boundaries are never joined. Reports contain
private operating evidence and stay local. No archive member is extracted.
"""
import base64
import hashlib
import json
import os
import tempfile
import zipfile
from collections import Counter
from pathlib import Path

from mokka_ecu_lab.protocols import BITMAP_PIDS, supported_pids, support_state
from mokka_ecu_lab.protocols.isotp import parse_reply
from mokka_ecu_lab.sensors import load_registry
from mokka_ecu_lab.sensors.extended import basic_range
from mokka_ecu_lab.sensors.diesel import STANDARD_DIESEL
from mokka_ecu_lab.capture import DECODER_VERSION
from mokka_ecu_lab import __version__
from .summary import observe_summary,scr_summary

MAX_MEMBER = 64 * 1024 * 1024
MAX_TOTAL = 128 * 1024 * 1024
MAX_RECORDS = 250000
MAX_SESSIONS = 16
MAX_PREVIEW = 2000
MAX_GROUPS = 128
MEMBERS = frozenset({'raw-redacted.jsonl','measurements.csv','discovery-report.json',
    'session-summary.json','pid-support.json','ecu-identifiers.json','polling-statistics.json',
    'errors.json','markers.json','manifest.json','SHA256SUMS.txt','raw-observations.json','acquisition-receipt.json'})
REQUIREMENTS = [
    '017A six-byte layout: obtain an authoritative byte definition and identified calibration applicability; retain bytes without padding or shifting.',
    'Pair any proposed pressure formula with independent diagnostic or physical reference measurements, units, timestamps and uncertainty.',
    '0188 documented decoding is not independent vehicle verification; compare current state and all block counters with an independent diagnostic source.',
    'Identify hardware/software/calibration only from independently known records; no new identification request or VIN lookup is authorized.',
    'Correlation, matching length and shared ECU/manufacturer names do not prove a decoder or proprietary DID compatibility.']


def observation_state(source, count):
    if not count: return 'NOT_OBSERVED'
    return {'ECU_READING':'VEHICLE_OBSERVED','SIMULATED':'SIMULATED_OBSERVED'}.get(source,'UNKNOWN_SOURCE_OBSERVED')


def matrix_entry(pid):
    return dict(pid=f'{pid:02X}',request=f'01{pid:02X}',valid_framing=0,invalid_framing=0,
        negative_responses=0,positive_response_count=0,recorded_raw_only_positive_count=0,layout_mismatches=0,
        lengths=Counter(),field_states={},support_flags=Counter(),byte_changes=Counter(),
        semantic_warnings=[],bitmap_evidence_states=Counter(),status='UNVERIFIED_LAYOUT')


class BitmapEvidence:
    """Ordered wire evidence only. Conflicting pages quarantine their descendants."""
    def __init__(self):
        self.seen={}; self.accepted={}; self.conflicts=set(); self.problems=[]

    def invalidate(self, base):
        self.conflicts.add(base)
        self.accepted={p:v for p,v in self.accepted.items() if p<base}

    def observe(self, pid, payload):
        if len(payload)!=4:
            self.invalidate(pid);return 'BITMAP_INVALID_LENGTH'
        try:supported_pids(payload,pid)
        except ValueError:
            self.invalidate(pid);self.problems.append(f'01{pid:02X}: reserved or invalid bitmap bits');return 'BITMAP_INVALID_RESERVED_BITS'
        prior=self.seen.setdefault(pid,set()); prior.add(payload)
        if len(prior)>1:
            self.invalidate(pid); self.problems.append(f'01{pid:02X}: conflicting original bitmap values')
        if any(p<=pid for p in self.conflicts): return 'BITMAP_CHAIN_CONFLICT'
        if pid:
            parent=pid-32
            if parent not in self.accepted: return 'BITMAP_VALID_UNANCHORED'
            if pid not in supported_pids(self.accepted[parent],parent):
                self.invalidate(parent)
                self.problems.append(f'01{pid:02X}: positive page conflicts with parent continuation bit')
                return 'BITMAP_CHAIN_CONFLICT'
        self.accepted[pid]=payload
        return 'BITMAP_VALID_ANCHORED'

    def support(self, pid):
        pages=set(self.accepted)
        bits=set().union(*(supported_pids(v,p) for p,v in self.accepted.items()))
        return support_state(bits,pages,pid).upper()


def recorded_snapshots(members, summary):
    """Checksum-verified stored snapshots; never original bitmap authority."""
    snapshots=[]
    for filename in ('pid-support.json','discovery-report.json'):
        content=json.loads(members.get(filename,b'[]' if filename=='pid-support.json' else b'{}'))
        if filename=='discovery-report.json':
            if not isinstance(content,dict): raise ValueError('Invalid Discovery snapshot')
            rows=content.get('standard',[]); mode=content.get('mode') or summary.get('mode')
        else: rows=content; mode=summary.get('mode')
        if not isinstance(rows,list): raise ValueError('Invalid support snapshot')
        for row in rows:
            if not isinstance(row,dict): raise ValueError('Invalid support snapshot row')
            ecu,pid,state=(row.get(k) for k in ('ecu','pid','support'))
            if not all(isinstance(v,str) for v in (ecu,pid,state)): continue
            try: number=int(pid[2:] if len(pid)==4 and pid.startswith('01') else pid,16)
            except ValueError: continue
            if not 0<=number<=255: continue
            snapshots.append(dict(ecu=ecu,pid=number,state=state.upper() if state.upper() in
                {'SUPPORTED','UNSUPPORTED','UNKNOWN'} else 'UNKNOWN',origin=filename,
                mode=row.get('mode') or mode,source_kind=row.get('source_kind')))
    return snapshots


def complete_row(e, g, bitmap, snapshots, ambiguous=False):
    """Additive schema v1 fields; the legacy support key remains raw-only."""
    pid=int(e['pid'],16); state=bitmap.support(pid)
    recorded={r['state'] for r in snapshots}; known=recorded-{'UNKNOWN'}
    snapshot_state='CONFLICT' if len(known)>1 else next(iter(known),'UNKNOWN')
    notes=[]; disagreements=[]
    if ambiguous: notes.append('Recorded snapshot source scope is ambiguous; it cannot be assigned to this source group.')
    if state=='UNKNOWN': notes.append('Raw bitmap support UNKNOWN: the ordered predecessor/continuation chain is missing or conflicting.')
    if recorded: notes.append(f'Recorded Discovery snapshot: {snapshot_state}; checksum-verified stored evidence, not independently raw-verified.')
    else: notes.append('No applicable recorded Discovery support snapshot.')
    if snapshot_state=='CONFLICT': disagreements.append('Conflicting recorded Discovery snapshots')
    if state!='UNKNOWN' and known and known!={state}: disagreements.append('Raw bitmap and recorded support disagree')
    if state=='UNSUPPORTED' and e['positive_response_count']: disagreements.append('Positive response despite unsupported raw bitmap')
    notes.extend(disagreements)
    count=e['positive_response_count']; observed=observation_state(g['source_kind'],count)
    if not count: notes.append('No complete positive response for this PID; the session source does not establish PID observation.')
    if snapshot_state=='UNSUPPORTED': notes.append('Snapshot UNSUPPORTED refers to this standard PID; an OEM equivalent is not ruled out.')
    bitmap_states=e['bitmap_evidence_states']
    if pid in BITMAP_PIDS:
        if set(bitmap_states) in ({'BITMAP_INVALID_LENGTH'},{'BITMAP_INVALID_RESERVED_BITS'}):layout=next(iter(bitmap_states))
        elif 'BITMAP_CHAIN_CONFLICT' in bitmap_states or any(p<=pid for p in bitmap.conflicts): layout='BITMAP_CHAIN_CONFLICT'
        elif len(bitmap_states)>1: layout='BITMAP_MIXED_EVIDENCE'
        else: layout=next(iter(bitmap_states),'NO_POSITIVE_RESPONSE')
        if 'BITMAP_VALID_UNANCHORED' in bitmap_states: notes.append('MISSING_PREDECESSOR_EVIDENCE: four-byte bitmap is valid; its bits cannot infer support.')
        e['status']='BITMAP_EVIDENCE'
    else:
        layout='UNVERIFIED_LAYOUT' if e['layout_mismatches'] else 'DOCUMENTED_LAYOUT' if count else 'NO_POSITIVE_RESPONSE'
        if e['layout_mismatches']: e['status']='UNVERIFIED_LAYOUT'
    framing='MIXED_FRAMING' if e['invalid_framing'] and e['valid_framing'] else 'INVALID_FRAMING' if e['invalid_framing'] else 'VALID_FRAMING' if e['valid_framing'] else 'NO_RESPONSE'
    return dict(e,support=state,raw_bitmap_support=state,recorded_support=sorted(recorded),
        recorded_discovery_support=snapshot_state,recorded_support_provenance=sorted({r['origin'] for r in snapshots}),
        recorded_support_kind='RECORDED_SNAPSHOT',recorded_support_raw_verified=False,
        observation_state=observed,vehicle_evidence=observed,layout_state=layout,frame_validity=framing,
        definition_state='STANDARD_DOCUMENTED' if pid in STANDARD_DIESEL or pid in load_registry() else 'BITMAP_DEFINITION' if pid in BITMAP_PIDS else 'UNAVAILABLE',
        evidence_explanation=' '.join(notes),contradictions=disagreements,
        lengths=dict(e['lengths']),support_flags=dict(e['support_flags']),byte_changes=dict(e['byte_changes']),
        bitmap_evidence_states=dict(bitmap_states),field_states={f:dict(c) for f,c in e['field_states'].items()},
        independent_verification='UNVERIFIED')


def read_bundle(path):
    path = Path(path)
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        names = [i.filename for i in infos]
        if len(names) != len(set(names)) or set(names) - MEMBERS:
            raise ValueError('Duplicate or unrecognized bundle members; root-level Research Bundle expected')
        if any(i.file_size > MAX_MEMBER or i.flag_bits & 1 for i in infos) or sum(i.file_size for i in infos) > MAX_TOTAL:
            raise ValueError('Bundle exceeds offline limits or is encrypted')
        if not {'raw-redacted.jsonl','SHA256SUMS.txt'} <= set(names):
            raise ValueError('Original redacted raw journal and checksum list are required')
        if archive.getinfo('SHA256SUMS.txt').file_size > 65536:
            raise ValueError('Oversized checksum list')
        checks = {}
        for line in archive.read('SHA256SUMS.txt').decode('utf-8-sig').splitlines():
            try: digest, name = line.split('  ', 1)
            except ValueError as exc: raise ValueError('Invalid checksum list') from exc
            if name not in MEMBERS or name in checks or len(digest) != 64:
                raise ValueError('Invalid checksum entry')
            checks[name] = digest.lower()
        data = {}
        for name in names:
            content = archive.read(name)
            if name != 'SHA256SUMS.txt' and checks.get(name) != hashlib.sha256(content).hexdigest():
                raise ValueError(f'Checksum missing or mismatch: {name}')
            data[name] = content
        if set(checks) != set(names) - {'SHA256SUMS.txt'}:
            raise ValueError('Checksum coverage does not match bundle contents')
    # Hash of verified member identities: independent of ZIP compression/order.
    identity = hashlib.sha256(json.dumps(checks,sort_keys=True).encode()).hexdigest()
    return identity, data


def analyze_bundles(paths):
    if not 1 <= len(paths) <= MAX_SESSIONS:
        raise ValueError('Select 1–16 local Research Bundles')
    sessions = []; seen = set()
    registry = load_registry()
    for path in paths:
        identity, members = read_bundle(path)
        if identity in seen: raise ValueError('The same evidence bundle was selected twice')
        seen.add(identity)
        groups = {}; missing = []; contradictions = []; transaction_errors = []
        summary = json.loads(members.get('session-summary.json',b'{}'))
        if not isinstance(summary,dict): raise ValueError('Invalid session summary')
        snapshots=recorded_snapshots(members,summary)
        if 'discovery-report.json' not in members: missing.append('No recorded discovery snapshot')
        if 'raw-observations.json' not in members: missing.append('Legacy bundle: no raw-observations.json sidecar; the complete original raw journal is still analyzed.')
        records = []
        for index, line in enumerate(members['raw-redacted.jsonl'].decode('utf-8-sig').splitlines()):
            if index >= MAX_RECORDS: raise ValueError('Journal exceeds offline record limit')
            if len(line) > 262144: raise ValueError('Oversized journal record')
            record = json.loads(line)
            if not isinstance(record,dict): raise ValueError('Invalid journal record')
            if record.get('record_type') == 'transaction': records.append(record)
        # Stable journal order breaks timestamp ties; never align different sessions.
        def timestamp(record):
            n = record.get('monotonic_ns')
            return n if isinstance(n,int) and not isinstance(n,bool) and n >= 0 else 0
        records.sort(key=timestamp)
        for record in records:
            command = record.get('command','')
            if not isinstance(command,str) or len(command)!=4 or not command.startswith('01'): continue
            try:
                pid = int(command[2:],16)
                if record.get('pid') and int(record['pid'],16) != pid: raise ValueError('PID/command disagreement')
                raw = base64.b64decode(record['raw_b64'],validate=True)
                if len(raw)>65536: raise ValueError('Oversized wire reply')
            except (KeyError,TypeError,ValueError) as exc:
                transaction_errors.append(str(exc)); continue
            mode = record.get('mode') or summary.get('mode') or 'UNKNOWN'
            if not isinstance(mode,str): raise ValueError('Invalid source mode')
            source = record.get('source_kind') or ('SIMULATED' if mode=='SIMULATED' else 'ECU_READING' if mode.startswith('LIVE') else 'UNKNOWN')
            if not isinstance(mode,str) or not isinstance(source,str): raise ValueError('Invalid source metadata')
            if (mode=='SIMULATED' and source!='SIMULATED') or (mode.startswith('LIVE') and source!='ECU_READING'):
                contradictions.append('Mode/source disagreement; evidence kept in a separate UNKNOWN source group')
                source = 'UNKNOWN'
            result = parse_reply(raw,pid,command)
            def group(ecu):
                key = (ecu or 'UNKNOWN ECU',mode,source)
                if key not in groups:
                    if len(groups)>=MAX_GROUPS: raise ValueError('Too many source groups in one bundle (128 maximum)')
                    groups[key] = dict(ecu=key[0],mode=mode,source_kind=source,bitmap=BitmapEvidence(),
                        matrix={},samples=[],cache={},last={},missing=[],ranges={})
                return groups[key]
            def entry(g):
                return g['matrix'].setdefault(pid,matrix_entry(pid))
            for error in result.errors:
                e = entry(group(error.get('ecu'))); e['invalid_framing'] += 1
            if not result.responses and not result.errors:
                e = entry(group(None)); e['invalid_framing'] += 1
            for reply in result.responses:
                g = group(reply.header); e = entry(g)
                e['valid_framing'] += 1
                if reply.negative_code is not None:
                    e['negative_responses'] += 1; continue
                payload = reply.data; e['lengths'][len(payload)] += 1; e['positive_response_count'] += 1
                e['recorded_raw_only_positive_count'] += bool(record.get('raw_only'))
                prior = g['last'].get(pid)
                if prior is not None:
                    for i in range(max(len(prior),len(payload))):
                        if prior[i:i+1] != payload[i:i+1]: e['byte_changes'][i] += 1
                g['last'][pid] = payload
                if pid in BITMAP_PIDS:
                    bitmap_state=g['bitmap'].observe(pid,payload); e['bitmap_evidence_states'][bitmap_state]+=1
                    if bitmap_state=='BITMAP_INVALID_LENGTH': e['layout_mismatches'] += 1
                    continue
                fields = []; decode_error = None
                try:
                    if pid in STANDARD_DIESEL:
                        fields = STANDARD_DIESEL[pid].decode(payload)
                        if pid in {0x4F,0x50}:g['ranges'][pid]=payload
                        if any(f.support_bit is not None for f in STANDARD_DIESEL[pid].fields): e['support_flags'][payload[0]] += 1
                    elif pid in registry:
                        sensor = registry[pid]
                        value = basic_range(sensor,payload,g['ranges'])
                        fields = [dict(sensor_id=sensor.id,value=value,unit=sensor.unit,state='AVAILABLE')]
                    else: decode_error = 'No code-owned decoder'
                except ValueError as exc: decode_error = str(exc)
                observe_summary(g,pid,record,fields,decode_error)
                if decode_error: e['layout_mismatches'] += 1
                else: e['status'] = 'STANDARD_DOCUMENTED'
                ns = timestamp(record)
                if type(record.get('monotonic_ns')) is not int or record['monotonic_ns'] < 0:
                    g['missing'].append('Acquisition monotonic timestamp unavailable'); ns = None
                warnings = list(dict.fromkeys(w for f in fields for w in f.get('semantic_warnings',[])))
                e['semantic_warnings'] = sorted(set(e['semantic_warnings']+warnings))
                for f in fields:
                    states = e['field_states'].setdefault(f['sensor_id'],Counter()); states[f['state']] += 1
                    if f['sensor_id'] in {'rpm','maf','speed'} and f['state']=='AVAILABLE' and ns is not None:
                        g['cache'][f['sensor_id']] = dict(value=f['value'],unit=f['unit'],monotonic_ns=ns,timestamp=record.get('timestamp'))
                if pid in {0x7A,0x88} and len(g['samples']) < MAX_PREVIEW:
                    context = {}
                    for name in ('rpm','maf','speed'):
                        cached = g['cache'].get(name)
                        if cached and ns is not None and cached['monotonic_ns'] <= ns:
                            context[name] = dict(cached,age_seconds=(ns-cached['monotonic_ns'])/1e9,
                                simultaneous=False,state='RECORDED_NON_SIMULTANEOUS')
                        else: context[name] = dict(state='UNAVAILABLE',age_seconds=None,simultaneous=False)
                    g['samples'].append(dict(pid=f'{pid:02X}',timestamp=record.get('timestamp'),monotonic_ns=ns,
                        payload_hex=payload.hex(' ').upper(),bytes=list(payload),framing_valid=True,
                        layout_status='UNVERIFIED_LAYOUT' if decode_error else 'STANDARD_DOCUMENTED',
                        decoder_error=decode_error,fields=fields,context=context,
                        vehicle_evidence='VEHICLE_OBSERVED' if source=='ECU_READING' else source,
                        independent_verification='UNVERIFIED',recorded_raw_only=bool(record.get('raw_only'))))
        output = []
        for key,g in sorted(groups.items()):
            bitmap=g['bitmap']; raw_pids=set().union(*(supported_pids(v,p) for p,v in bitmap.accepted.items()))
            applicable=[]; ambiguous=set()
            for row in snapshots:
                if row['ecu']!=g['ecu']: continue
                if row['mode'] and row['mode']!=g['mode'] or row['source_kind'] and row['source_kind']!=g['source_kind']: continue
                if not row['mode'] and not row['source_kind'] and sum(k[0]==g['ecu'] for k in groups)>1:
                    ambiguous.add(row['pid']); continue
                applicable.append(row)
            for pid in raw_pids | set(STANDARD_DIESEL) | set(registry) | {r['pid'] for r in applicable} | ambiguous:
                g['matrix'].setdefault(pid,matrix_entry(pid))
            matrix = []
            for pid,e in sorted(g['matrix'].items()):
                row=complete_row(e,g,bitmap,[r for r in applicable if r['pid']==pid],pid in ambiguous)
                contradictions.extend(f'{g["ecu"]} · {g["mode"]} · {g["source_kind"]} {row["request"]}: {c}' for c in row['contradictions'])
                matrix.append(row)
            contradictions.extend(f'{g["ecu"]} · {g["mode"]} · {g["source_kind"]}: {p}' for p in bitmap.problems)
            if not bitmap.accepted: g['missing'].append('No anchored original bitmap chain in this source group; recorded snapshot remains separate.')
            result_group=dict(ecu=g['ecu'],mode=g['mode'],source_kind=g['source_kind'],matrix=matrix,
                samples=g['samples'],preview_limit=MAX_PREVIEW,preview_truncated=sum(sum(e['lengths'].values()) for p,e in g['matrix'].items() if p in {0x7A,0x88})>MAX_PREVIEW,
                missing_evidence=sorted(set(g['missing'])))
            result_group['scr_summary']=scr_summary(dict(g,matrix=matrix))
            output.append(result_group)
        receipt=json.loads(members['acquisition-receipt.json']) if 'acquisition-receipt.json' in members else summary.get('acquisition_receipt')
        for g in output:
            scoped=receipt if isinstance(receipt,dict) and all(receipt.get(k)==g[k] for k in ('ecu','mode','source_kind')) else {}
            g['capture_coverage']=[dict(pid=row['pid'],positive_responses=row['positive_response_count'],
                recorded_raw_only_positive_count=row.get('recorded_raw_only_positive_count',0),
                requested_weight=scoped.get('effective_schedule',{}).get(row['pid'],{}).get('weight'),
                actual_auto_capture_samples=scoped.get('observed',{}).get(row['pid'],{}).get('positive_samples'),
                observed_auto_capture_interval=scoped.get('observed',{}).get(row['pid'],{}).get('mean_interval_seconds'),
                plan_evidence='WORKER_RECEIPT' if scoped else 'LEGACY_NO_SELECTION_RECEIPT')
                for row in g['matrix'] if int(row['pid'],16) not in BITMAP_PIDS]
        sessions.append(dict(evidence_id=identity,checksum_verified=True,recorded_decoder_versions=summary.get('decoder_versions',[]),
            acquisition_receipt=receipt,
            acquisition_quality=dict(recorded_status_counts=dict(Counter(r.get('status','UNKNOWN') for r in records)),
                transport_failures=sum(r.get('status')=='TRANSPORT_ERROR' for r in records),
                intentional_cancellations=sum(r.get('status')=='CANCELLED' for r in records),
                current_decoder_layout_mismatches=sum(r['layout_mismatches'] for g in output for r in g['matrix'])),
            groups=output,transactions=len(records),missing_evidence=missing,
            contradictions=sorted(set(contradictions)),transaction_errors=transaction_errors,
            note='Offline re-decoding uses current definitions; original CSV/journal and historical decoder versions are unchanged.'))
    return dict(schema_version=1,analysis_revision=2,analyzer_version=__version__,decoder_version=DECODER_VERSION,sessions=sessions,cloud_upload=False,
        verification_requirements=REQUIREMENTS,
        limitations='Private local evidence. Separate session/ECU/mode/source groups; cached context is asynchronous with age. Correlation never establishes a decoder. No automatic confidence promotion.')


def save_analysis(report,path,inputs=()):
    target=Path(path).resolve()
    if target.suffix.lower()!='.json' or target in {Path(p).resolve() for p in inputs}:
        raise ValueError('Choose a separate JSON analysis output; original input cannot be overwritten')
    if target.exists(): raise ValueError('Choose a fresh JSON filename; saved analyses are never overwritten by default')
    target.parent.mkdir(parents=True,exist_ok=True)
    fd,temporary=tempfile.mkstemp(prefix='analysis-',suffix='.json',dir=target.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as stream:
            json.dump(report,stream,ensure_ascii=False,indent=2);stream.write('\n')
        os.rename(temporary,target)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)
