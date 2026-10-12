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
from mokka_ecu_lab.sensors.diesel import STANDARD_DIESEL
from mokka_ecu_lab.capture import DECODER_VERSION

MAX_MEMBER = 64 * 1024 * 1024
MAX_TOTAL = 128 * 1024 * 1024
MAX_RECORDS = 250000
MAX_SESSIONS = 16
MAX_PREVIEW = 2000
MAX_GROUPS = 128
MEMBERS = frozenset({'raw-redacted.jsonl','measurements.csv','discovery-report.json',
    'session-summary.json','pid-support.json','ecu-identifiers.json','polling-statistics.json',
    'errors.json','markers.json','manifest.json','SHA256SUMS.txt','raw-observations.json'})
REQUIREMENTS = [
    '017A six-byte layout: obtain an authoritative byte definition and identified calibration applicability; retain bytes without padding or shifting.',
    'Pair any proposed pressure formula with independent diagnostic or physical reference measurements, units, timestamps and uncertainty.',
    '0188 documented decoding is not independent vehicle verification; compare current state and all block counters with an independent diagnostic source.',
    'Identify hardware/software/calibration only from independently known records; no new identification request or VIN lookup is authorized.',
    'Correlation, matching length and shared ECU/manufacturer names do not prove a decoder or proprietary DID compatibility.']


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
        if 'discovery-report.json' not in members: missing.append('No recorded discovery snapshot')
        if 'raw-observations.json' not in members: missing.append('Legacy bundle: no recorded raw/context component')
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
                    groups[key] = dict(ecu=key[0],mode=mode,source_kind=source,support=set(),pages=set(),
                        matrix={},samples=[],cache={},last={},missing=[])
                return groups[key]
            def entry(g):
                return g['matrix'].setdefault(pid,dict(pid=f'{pid:02X}',request=command,
                    valid_framing=0,invalid_framing=0,negative_responses=0,layout_mismatches=0,
                    lengths=Counter(),field_states={},support_flags=Counter(),byte_changes=Counter(),
                    semantic_warnings=[],status='UNVERIFIED_LAYOUT'))
            for error in result.errors:
                e = entry(group(error.get('ecu'))); e['invalid_framing'] += 1
            if not result.responses and not result.errors:
                e = entry(group(None)); e['invalid_framing'] += 1
            for reply in result.responses:
                g = group(reply.header); e = entry(g)
                e['valid_framing'] += 1
                if reply.negative_code is not None:
                    e['negative_responses'] += 1; continue
                payload = reply.data; e['lengths'][len(payload)] += 1
                prior = g['last'].get(pid)
                if prior is not None:
                    for i in range(max(len(prior),len(payload))):
                        if prior[i:i+1] != payload[i:i+1]: e['byte_changes'][i] += 1
                g['last'][pid] = payload
                if pid in BITMAP_PIDS:
                    if len(payload)==4 and (pid==0 or (pid in g['support'] and pid-32 in g['pages'])):
                        g['support'].update(supported_pids(payload,pid)); g['pages'].add(pid)
                    else: e['layout_mismatches'] += 1
                    continue
                fields = []; decode_error = None
                try:
                    if pid in STANDARD_DIESEL:
                        fields = STANDARD_DIESEL[pid].decode(payload)
                        if any(f.support_bit is not None for f in STANDARD_DIESEL[pid].fields): e['support_flags'][payload[0]] += 1
                    elif pid in registry:
                        sensor = registry[pid]
                        value = sensor.decode(payload)
                        fields = [dict(sensor_id=sensor.id,value=value,unit=sensor.unit,state='AVAILABLE')]
                    else: decode_error = 'No code-owned decoder'
                except ValueError as exc: decode_error = str(exc)
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
        snapshots = json.loads(members.get('pid-support.json',b'[]'))
        if not isinstance(snapshots,list): raise ValueError('Invalid support snapshot')
        snapshot_support={}
        for row in snapshots:
            if not isinstance(row,dict): raise ValueError('Invalid support snapshot row')
            ecu,pid,state=(row.get(k) for k in ('ecu','pid','support'))
            if not all(isinstance(v,str) for v in (ecu,pid,state)): continue
            snapshot_support.setdefault((ecu,pid),set()).add(state)
        output = []
        for key,g in sorted(groups.items()):
            for pid in set(g['support']) | set(STANDARD_DIESEL):
                g['matrix'].setdefault(pid,dict(pid=f'{pid:02X}',request=f'01{pid:02X}',valid_framing=0,invalid_framing=0,
                    negative_responses=0,layout_mismatches=0,lengths=Counter(),field_states={},support_flags=Counter(),
                    byte_changes=Counter(),semantic_warnings=[],status='UNVERIFIED_LAYOUT'))
            matrix = []
            for pid,e in sorted(g['matrix'].items()):
                state = support_state(g['support'],g['pages'],pid).upper()
                recorded = snapshot_support.get((g['ecu'],f'{pid:02X}'),set())
                if recorded and state != 'UNKNOWN' and recorded != {state}:
                    contradictions.append(f'{g["ecu"]} 01{pid:02X}: raw bitmap and recorded support disagree')
                if state == 'UNSUPPORTED' and e['lengths']:
                    contradictions.append(f'{g["ecu"]} 01{pid:02X}: positive response despite unsupported bitmap')
                if e['layout_mismatches']: e['status']='UNVERIFIED_LAYOUT'
                matrix.append(dict(e,support=state,recorded_support=sorted(s for s in recorded if s),
                    lengths=dict(e['lengths']),support_flags=dict(e['support_flags']),byte_changes=dict(e['byte_changes']),
                    field_states={f:dict(c) for f,c in e['field_states'].items()},
                    vehicle_evidence='VEHICLE_OBSERVED' if g['source_kind']=='ECU_READING' and e['lengths'] else g['source_kind'],
                    independent_verification='UNVERIFIED'))
            if not g['pages']: g['missing'].append('No original bitmap evidence in this source group; snapshot support is not inferred')
            output.append(dict(ecu=g['ecu'],mode=g['mode'],source_kind=g['source_kind'],matrix=matrix,
                samples=g['samples'],preview_limit=MAX_PREVIEW,preview_truncated=sum(sum(e['lengths'].values()) for p,e in g['matrix'].items() if p in {0x7A,0x88})>MAX_PREVIEW,
                missing_evidence=sorted(set(g['missing']))))
        sessions.append(dict(evidence_id=identity,checksum_verified=True,recorded_decoder_versions=summary.get('decoder_versions',[]),
            groups=output,transactions=len(records),missing_evidence=missing,
            contradictions=sorted(set(contradictions)),transaction_errors=transaction_errors,
            note='Offline re-decoding uses current definitions; original CSV/journal and historical decoder versions are unchanged.'))
    return dict(schema_version=1,decoder_version=DECODER_VERSION,sessions=sessions,cloud_upload=False,
        verification_requirements=REQUIREMENTS,
        limitations='Private local evidence. Separate session/ECU/mode/source groups; cached context is asynchronous with age. Correlation never establishes a decoder. No automatic confidence promotion.')


def save_analysis(report,path,inputs=()):
    target=Path(path).resolve()
    if target.suffix.lower()!='.json' or target in {Path(p).resolve() for p in inputs}:
        raise ValueError('Choose a separate JSON analysis output; original input cannot be overwritten')
    target.parent.mkdir(parents=True,exist_ok=True)
    fd,temporary=tempfile.mkstemp(prefix='analysis-',suffix='.json',dir=target.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as stream:
            json.dump(report,stream,ensure_ascii=False,indent=2);stream.write('\n')
        os.replace(temporary,target)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)
