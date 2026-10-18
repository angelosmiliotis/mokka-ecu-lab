"""Bounded offline PID/field evidence replay. Imports no acquisition controller."""
from collections import Counter,defaultdict
from pathlib import Path
import csv,io,json,math,hashlib
from .obd import inventory,strict_records,source_key,distribution
from .phases import _write_atomic
from mokka_ecu_lab.local_paths import linked
from mokka_ecu_lab.protocols import BITMAP_PIDS
from mokka_ecu_lab.research.evidence import read_bundle,MAX_SESSIONS,BitmapEvidence
from mokka_ecu_lab.sensors import load_registry
from mokka_ecu_lab.sensors.diesel import STANDARD_DIESEL
from mokka_ecu_lab.sensors.extended import basic_range,UNIMPLEMENTED_STANDARD

LIMITS=('OFFLINE PRIVATE evidence, scoped to original bundle / responder address / source / context. '
    'A responder header is not authenticated ECU hardware, VIN or calibration identity. '
    'PID count, field count and physical sensor count are different; physical sensor identity and calibration remain UNVERIFIED. '
    'Availability, framing, definition, numeric replay and repeated polling are independent facts. '
    'A status bit is not a diagnosis; asynchronous samples do not establish causality or regeneration.')


def role(record):
    # Extended decode annotations also occur during polling; they are not a phase.
    if record.get('pacing_mode')=='ADAPTIVE':return 'POLLING'
    if record.get('benchmark_phase')=='MEASUREMENT':return 'BENCHMARK'
    if record.get('discovery_samples'):return 'DISCOVERY'
    if record.get('pacing_mode')=='FIXED_POLICY':return 'PREPARATION'
    return 'UNCLASSIFIED'


def definition(pid,registry):
    if pid==1:
        from .readiness import DEFINITION
        return dict(implementation='OFFLINE_PURE_DEFINITION; NOT_LIVE_ADMITTED',source=DEFINITION['source'],revision=DEFINITION['revision'],table='B2/B3 + EPA Table2',expected_bytes=4,fields=[])
    if pid in STANDARD_DIESEL:
        d=STANDARD_DIESEL[pid];meta=d.metadata()
        fields=[dict(f.metadata(),sensor_id=f'sae_{pid:02x}_{f.id}') for f in d.fields]
        return dict(implementation='IMPLEMENTED',source=meta['source'],revision=meta['edition'],table=meta['source_table'],expected_bytes=d.length,fields=fields)
    if pid in registry:
        d=registry[pid]
        return dict(implementation='IMPLEMENTED',source=d.metadata['evidence'],revision='LOCAL_LEGACY_DEFINITION; revision not recorded',table=None,expected_bytes=d.length,
            fields=[dict(sensor_id=d.id,name=d.name,unit=d.unit,formula=d.metadata['formula'],validity=d.metadata['validity'])])
    candidate=UNIMPLEMENTED_STANDARD.get(pid,{})
    return dict(implementation='OFFLINE_RESEARCH_ONLY' if candidate.get('edition') else 'UNVERIFIED',source=candidate.get('source'),revision=candidate.get('edition'),table=candidate.get('table'),expected_bytes=candidate.get('length'),fields=[])


def timing(points,end,expected=None):
    stamps=sorted({p['monotonic_ns'] for p in points})
    gaps=[(b-a)/1e9 for a,b in zip(stamps,stamps[1:])]
    age=(end-stamps[-1])/1e9 if stamps else None
    expected=expected if isinstance(expected,(int,float)) and not isinstance(expected,bool) and math.isfinite(expected) and expected>0 else None
    return dict(samples=len(points),last_timestamp=points[-1].get('timestamp') if points else None,last_monotonic_ns=stamps[-1] if stamps else None,
        age_at_recording_end_seconds=age,staleness='NO_SAMPLE' if age is None else 'UNKNOWN_NO_PROFILE' if expected is None else 'STALE' if age>2*expected else 'WITHIN_RECORDED_PROFILE',
        gap_seconds=distribution(gaps),expected_interval_seconds=expected,severe_gaps_over_twice_profile=sum(g>2*expected for g in gaps) if expected else None,
        age_basis='Selected source-context recording end, never wall-clock LIVE freshness; no interpolation')


def analyze_explorer(paths):
    if not 1<=len(paths)<=MAX_SESSIONS:raise ValueError('Choose one to sixteen original bundles')
    sessions=[];seen=set();journals=set();registry=load_registry()
    for path in paths:
        def container_digest():
            digest=hashlib.sha256()
            with Path(path).open('rb') as stream:
                while block:=stream.read(1024*1024):digest.update(block)
            return digest.hexdigest()
        container_sha=container_digest()
        identity,members=read_bundle(path)
        if container_digest()!=container_sha:raise ValueError('Selected input container changed during offline verification')
        journal=hashlib.sha256(members['raw-redacted.jsonl']).hexdigest()
        records=strict_records(members)
        if identity in seen or records and journal in journals:raise ValueError('Duplicate original journal selected; histories are never double-counted')
        seen.add(identity)
        if records:journals.add(journal)
        groups=inventory(records,identity)
        summary=json.loads(members.get('session-summary.json',b'{}'))
        receipt=json.loads(members['acquisition-receipt.json']) if 'acquisition-receipt.json' in members else summary.get('acquisition_receipt')
        scoped=defaultdict(list)
        for r,p in records:scoped[source_key(r)].append((r,p))
        replay_fields=0
        for g in groups:
            key=(g['mode'],g['source_kind'],g['context_id']);pairs=scoped[key];end=max(r['monotonic_ns'] for r,p in pairs)
            state=defaultdict(lambda:dict(attempts=[],positive=[],polling=[],roles=Counter(),fields=defaultdict(list),field_states=defaultdict(Counter),examples=[],errors=Counter()))
            ranges={};profile={};bitmap=BitmapEvidence()
            # A legacy receipt without context can only describe a unique matching source scope.
            matching=[k for k in scoped if isinstance(receipt,dict) and k[:2]==(receipt.get('mode'),receipt.get('source_kind'))]
            if isinstance(receipt,dict) and receipt.get('ecu')==g['ecu'] and key in matching and (receipt.get('context_id')==key[2] or not receipt.get('context_id') and len(matching)==1):profile=receipt
            for r,parsed in pairs:
                command=r['command']
                if len(command)!=4 or not command.startswith('01'):continue
                pid=int(command[2:],16)
                if pid in BITMAP_PIDS:
                    if parsed and not parsed.errors:
                        for response in parsed.responses:
                            if response.header==g['ecu'] and response.negative_code is None:
                                observed=bitmap.observe(pid,response.data)
                                if observed=='BITMAP_INVALID_LENGTH':bitmap.invalidate(pid)
                    continue
                item=state[pid];ref=dict(evidence_id=identity,transaction_id=r.get('id'),timestamp=r.get('timestamp'),monotonic_ns=r['monotonic_ns'],role=role(r),
                    role_basis=dict(pacing_mode=r.get('pacing_mode'),benchmark_phase=r.get('benchmark_phase'),extended_decode_annotation_present=bool(r.get('discovery_samples'))))
                if r.get('sent') is True:item['attempts'].append(ref)
                replies=[v for v in parsed.responses if v.header==g['ecu']] if parsed else []
                if not parsed or parsed.errors:item['errors']['FRAMING_OR_PROTOCOL']+=1;continue
                for response in replies:
                    if response.negative_code is not None:item['errors']['ECU_NEGATIVE']+=1;continue
                    item['positive'].append(ref);item['roles'][role(r)]+=1
                    if role(r) in {'POLLING','BENCHMARK'} and r.get('sent') is True:item['polling'].append(ref)
                    if len(item['examples'])<3:item['examples'].append(dict(ref,payload_hex=response.data.hex(' ').upper(),data_bytes=len(response.data)))
                    try:
                        if pid in STANDARD_DIESEL:
                            fields=STANDARD_DIESEL[pid].decode(response.data)
                            if pid in {0x4F,0x50} and bitmap.support(pid)=='SUPPORTED':ranges[pid]=response.data
                        elif pid in registry:
                            if len(response.data)!=registry[pid].length:raise ValueError('Exact length required')
                            # Range configuration is accepted only with the same anchored source evidence.
                            advertised={p for p in (0x4F,0x50) if bitmap.support(p)=='SUPPORTED'}
                            config={p:v for p,v in ranges.items() if bitmap.support(p)=='SUPPORTED'}
                            value=basic_range(registry[pid],response.data,config,advertised)
                            fields=[dict(sensor_id=registry[pid].id,name=registry[pid].name,value=value,unit=registry[pid].unit,state='AVAILABLE')]
                        else:continue
                    except ValueError:item['errors']['LAYOUT_OR_VALUE_UNVERIFIED']+=1;continue
                    for f in fields:
                        replay_fields+=1
                        if replay_fields>500000:raise ValueError('Explorer replay exceeds 500000 fields per bundle; select a smaller recording')
                        name=f['sensor_id'];item['field_states'][name][f['state']]+=1
                        value=f.get('value')
                        if f['state']=='AVAILABLE' and isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value):item['fields'][name].append(dict(ref,value=value,unit=f['unit']))
            for row in g['rows']:
                pid=int(row['pid'],16);item=state[pid];meta=definition(pid,registry);schedule=profile.get('effective_schedule',{}).get(row['pid'],{})
                expected=schedule.get('nominal_interval_seconds');fields=[]
                for field in meta['fields']:
                    name=field['sensor_id'];points=item['fields'][name];states=dict(item['field_states'][name])
                    kind='CONFIGURATION' if pid in {0x4F,0x50} else 'STATUS_OR_HISTORY' if pid in {0x1C,0x51,0x88} or field.get('value_bit') is not None or field.get('labels') or field.get('temporal_semantics') else 'NUMERIC_CHANNEL'
                    fields.append(dict(field,kind=kind,observed_states=states,last_valid_value=points[-1]['value'] if points else None,
                        last_valid_unit=points[-1]['unit'] if points else None,numeric_validity='REPLAY_VALID' if points else 'NO_VALID_SAMPLE',physical_calibration='UNVERIFIED',physical_sensor_identity='UNVERIFIED',**timing(points,end,expected)))
                count=len(item['positive']);numeric=any(f['samples'] for f in fields)
                row.update(definition=meta,fields=fields,field_count=len(fields),valid_field_count=sum(bool(f['samples']) for f in fields),
                    representation='NUMERIC_REPLAY' if numeric else 'RAW_ONLY' if count else 'NOT_READ',
                    physical_sensor_identity='UNVERIFIED',physical_sensor_count=None,
                    last_attempt=item['attempts'][-1] if item['attempts'] else None,attempted_requests=len(item['attempts']),
                    same_ecu_positive=count,repeated_polling=len({p['monotonic_ns'] for p in item['polling']})>=2,polling_replies=len(item['polling']),
                    distinct_polling_send_timestamps=len({p['monotonic_ns'] for p in item['polling']}),role_counts=dict(item['roles']),
                    positive_timing=timing(item['positive'],end),polling_timing=timing(item['polling'],end,expected),
                    profile=profile.get('preset') or profile.get('requested_plan',{}).get('preset'),profile_evidence='RECORDED_RECEIPT' if profile else 'NO_UNAMBIGUOUS_RECEIPT',
                    bounded_raw_examples=item['examples'],error_counts=dict(item['errors']),
                    unknowns=['Physical calibration and hardware identity unverified']+(['No positive same-responder response'] if not count else [])+(['No valid numeric replay; no physical unit inferred'] if not numeric else []))
                from mokka_ecu_lab.research.definition_status import research_status
                row['research']=research_status(pid)
            g.update(positive_pid_count=sum(r['same_ecu_positive']>0 for r in g['rows']),numeric_pid_count=sum(r['representation']=='NUMERIC_REPLAY' for r in g['rows']),
                valid_field_ids=sum(r['valid_field_count'] for r in g['rows']),physical_sensor_count=None,recording_end_monotonic_ns=end)
        sessions.append(dict(evidence_id=identity,verified_member_manifest_sha256=identity,input_container_sha256=container_sha,
            container_scope='Exact selected ZIP file; a run-wrapper digest is not the inner original ZIP digest',
            journal_sha256=journal,checksum_verified=True,session_id=summary.get('session_id'),groups=groups))
    return dict(schema='mokka-sensor-pid-explorer-1',private=True,offline=True,sends_requests=False,cloud_upload=False,limitations=LIMITS,sessions=sessions)


FILTERS=('Relevant evidence','All non-bitmap IDs','Advertised','Observed positive','Repeated polling','RAW only','Numeric replay','Advertised without response','Not read','Unknown definition','Status / history','Configuration','Unavailable subfields','Stale at recording end')


def select_rows(group,query='',state='Relevant evidence'):
    if state not in FILTERS:raise ValueError('Unknown evidence filter')
    selected=[]
    for row in group['rows']:
        relevant=row['advertised_support']=='SUPPORTED' or row['same_ecu_positive'] or row['attempted_requests']
        checks={'Relevant evidence':relevant,'All non-bitmap IDs':True,'Advertised':row['advertised_support']=='SUPPORTED',
            'Observed positive':row['same_ecu_positive']>0,'Repeated polling':row['repeated_polling'],'RAW only':row['representation']=='RAW_ONLY',
            'Numeric replay':row['representation']=='NUMERIC_REPLAY','Advertised without response':row['advertised_support']=='SUPPORTED' and not row['same_ecu_positive'],
            'Not read':not row['same_ecu_positive'],'Unknown definition':row['definition']['implementation']=='UNVERIFIED',
            'Status / history':any(f['kind']=='STATUS_OR_HISTORY' for f in row['fields']),'Configuration':any(f['kind']=='CONFIGURATION' for f in row['fields']),
            'Unavailable subfields':any(any(k!='AVAILABLE' and n for k,n in f['observed_states'].items()) for f in row['fields']),
            'Stale at recording end':any(f['staleness']=='STALE' for f in row['fields'])}
        if checks[state] and query.casefold() in json.dumps(row,ensure_ascii=False).casefold():selected.append(row)
    return selected


def export_explorer(report,path,inputs=()):
    target=Path(path).absolute();targets=[target.with_suffix('.json'),target.with_suffix('.csv')]
    for p in targets:
        if any(linked(v) or (v/'.git').exists() for v in [p,*p.parents]):raise ValueError('Explorer exports must stay outside links and Git trees')
    if set(p.resolve() for p in targets)&{Path(p).resolve() for p in inputs}:raise ValueError('Output overlaps an original input')
    stream=io.StringIO(newline='');columns=['input_container_sha256','verified_member_manifest_sha256','journal_sha256','ecu','mode','source_kind','context_id','request','name','advertised','same_ecu_positive','polling_replies','representation','definition_revision','definition_source','field_id','field_kind','definition_unit','last_valid_replay_unit','valid_samples','last_value','age_seconds','gap_median_s','gap_p95_s','gap_max_s','physical_calibration','unknowns']
    writer=csv.DictWriter(stream,fieldnames=columns,lineterminator='\n');writer.writeheader()
    def safe(value):
        value=str(value) if value is not None else ''
        return "'"+value if value[:1] in {'=','+','-','@','\t','\r','\n'} else value
    for session in report['sessions']:
        for group in session['groups']:
            for row in select_rows(group):
                for f in row['fields'] or [{}]:
                    values=[session['input_container_sha256'],session['verified_member_manifest_sha256'],session['journal_sha256'],group['ecu'],group['mode'],group['source_kind'],group['context_id'],row['request'],row['name'],row['advertised_support'],row['same_ecu_positive'],row['polling_replies'],row['representation'],row['definition']['revision'],json.dumps(row['definition']['source']),f.get('sensor_id'),f.get('kind'),f.get('unit'),f.get('last_valid_unit'),f.get('samples'),f.get('last_valid_value'),f.get('age_at_recording_end_seconds'),f.get('gap_seconds',{}).get('p50'),f.get('gap_seconds',{}).get('p95'),f.get('gap_seconds',{}).get('maximum'),'UNVERIFIED','; '.join(row['unknowns'])]
                    writer.writerow(dict(zip(columns,map(safe,values))))
    _write_atomic([(targets[0],json.dumps(report,ensure_ascii=False,indent=2)+'\n'),(targets[1],stream.getvalue())])
    return targets
