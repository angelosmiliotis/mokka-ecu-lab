"""Private offline support inventory and passive performance. No transport API."""
import base64,json,math,statistics
from collections import Counter,defaultdict
from html import escape
from pathlib import Path
from mokka_ecu_lab.protocols import BITMAP_PIDS,LIVE_PIDS,DISCOVERY_PIDS,EXTENSION_PIDS,supported_pids
from mokka_ecu_lab.protocols.isotp import parse_reply
from mokka_ecu_lab.research.evidence import read_bundle,BitmapEvidence,MAX_RECORDS,MAX_SESSIONS
from mokka_ecu_lab.sensors import load_registry
from mokka_ecu_lab.sensors.diesel import STANDARD_DIESEL
from mokka_ecu_lab.sensors.extended import UNIMPLEMENTED_STANDARD,basic_range
from .phases import _write_atomic

LEGACY_PIDS=LIVE_PIDS | (DISCOVERY_PIDS-EXTENSION_PIDS)
LIMITATIONS=('PRIVATE. Bitmap support, documented definition, response observation and valid decoding are separate facts. '
    'Performance is application/adapter end-to-end timing, not ECU service time or maximum ECU capacity. '
    'Functional requests share one wire budget; per-ECU replies do not multiply transmitted requests. '
    'No extra queries, inferred retries, automatic confidence promotion or higher-rate validation.')


def finite(value):return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) and value>=0
def percentile(values,q):
    if not values:return None
    values=sorted(values);pos=(len(values)-1)*q;lo=int(pos);hi=min(lo+1,len(values)-1)
    return values[lo]+(values[hi]-values[lo])*(pos-lo)
def distribution(values):
    return dict(n=len(values),**{f'p{int(q*100)}':percentile(values,q) for q in (.5,.9,.95,.99)},maximum=max(values) if values else None,
        minimum=min(values) if values else None,mean=statistics.mean(values) if values else None)


def symptom(record,parsed=None):
    """Disjoint feedback categories; decoder mismatch never implies overload."""
    if record.get('status')=='CANCELLED':return 'INTENTIONAL_CANCELLATION'
    if record.get('status')=='TRANSPORT_ERROR':return 'TRANSPORT_FAILURE'
    if record.get('status')=='INVALID' and record.get('raw_text','').strip().upper() in {'NO DATA\r>','NO DATA\n>','NO DATA >'}:return 'ECU_NO_DATA'
    if record.get('negative_responses') or parsed and any(r.negative_code is not None for r in parsed.responses):return 'ECU_NRC'
    errors=record.get('protocol_errors',[])
    if parsed and parsed.errors:return 'FRAMING_OR_PROTOCOL'
    if errors and all(e.get('category')=='DECODER_LAYOUT' for e in errors):return 'DECODER_LAYOUT'
    if record.get('status')!='OK':return 'FRAMING_OR_PROTOCOL'
    return 'OK'


def strict_records(members):
    records=[]
    for i,line in enumerate(members['raw-redacted.jsonl'].splitlines()):
        if i>=MAX_RECORDS:raise ValueError('Offline transaction limit exceeded')
        r=json.loads(line)
        if not isinstance(r,dict):raise ValueError('Invalid journal record')
        if r.get('record_type')!='transaction':continue
        if not isinstance(r.get('command'),str):raise ValueError('Missing command')
        ns=r.get('monotonic_ns')
        if not isinstance(ns,int) or isinstance(ns,bool) or ns<0:raise ValueError('Valid monotonic send timestamp required')
        raw=base64.b64decode(r['raw_b64'],validate=True)
        if len(raw)>65536:raise ValueError('Oversized reply')
        command=r['command'];parsed=None
        if len(command)==4 and command.startswith('01'):
            pid=int(command[2:],16)
            if r.get('pid') and int(r['pid'],16)!=pid:raise ValueError('Command/PID disagreement')
            parsed=parse_reply(raw,pid,command)
        records.append((r,parsed))
    return sorted(records,key=lambda pair:pair[0]['monotonic_ns'])


def source_key(r):
    mode=r.get('mode','UNKNOWN');source=r.get('source_kind','UNKNOWN')
    if not isinstance(mode,str) or not isinstance(source,str):raise ValueError('Invalid source')
    if mode.startswith('LIVE') and source!='ECU_READING' or mode=='SIMULATED' and source!='SIMULATED':source='UNKNOWN_SOURCE_CONFLICT'
    context=r.get('context_id','LEGACY_CONTEXT_UNAVAILABLE')
    if not isinstance(context,str) or len(context)>256:raise ValueError('Invalid source context')
    return mode,source,context


def inventory(records,identity):
    groups={};registry=load_registry();definitions={**registry,**STANDARD_DIESEL}
    for r,parsed in records:
        if parsed is None:continue
        pid=int(r['command'][2:],16)
        for response in parsed.responses:
            if response.header is None:continue
            key=(response.header,)+source_key(r)
            if key not in groups and len(groups)>=128:raise ValueError('Too many ECU/source inventory groups')
            g=groups.setdefault(key,dict(bitmap=BitmapEvidence(),ledger=[],positive=Counter(),decoded=Counter(),lengths=defaultdict(Counter),ranges={},
                length_verified=Counter(),layout_verified=Counter(),numeric_verified=Counter(),roles=defaultdict(Counter),refs=defaultdict(lambda:defaultdict(list))))
            if response.negative_code is not None:continue
            if parsed.errors:continue
            if pid in BITMAP_PIDS:
                state=g['bitmap'].observe(pid,response.data)
                if state=='BITMAP_INVALID_LENGTH':g['bitmap'].invalidate(pid)
                g['ledger'].append(dict(request=r['command'],raw_bytes=response.data.hex(' ').upper(),ecu=key[0],mode=key[1],source_kind=key[2],timestamp=r.get('timestamp'),
                    transaction_id=r.get('id'),state=state,origin='RECORDED_ORIGINAL_RESPONSE'))
            else:
                g['positive'][pid]+=1
                g['lengths'][pid][len(response.data)]+=1
                role=('ADAPTIVE_POLLING' if r.get('pacing_mode')=='ADAPTIVE' else 'BENCHMARK_MEASUREMENT' if r.get('benchmark_phase')=='MEASUREMENT'
                    else 'RECORDED_DISCOVERY' if r.get('discovery_samples') else 'FIXED_PREPARATION' if r.get('pacing_mode')=='FIXED_POLICY' else 'UNCLASSIFIED_RECORDED')
                g['roles'][pid][role]+=1
                ref=dict(evidence_id=identity,transaction_id=r.get('id'),timestamp=r.get('timestamp'),origin='RECORDED_ORIGINAL_RESPONSE')
                def remember(stage):
                    if len(g['refs'][pid][stage])<3:g['refs'][pid][stage].append(ref)
                remember('framed')
                definition=definitions.get(pid);expected=definition.length if definition else UNIMPLEMENTED_STANDARD.get(pid,{}).get('length')
                exact=expected is not None and len(response.data)==expected
                if exact:g['length_verified'][pid]+=1;remember('length_verified')
                try:
                    if pid in STANDARD_DIESEL:
                        valid=any(f['state']=='AVAILABLE' for f in STANDARD_DIESEL[pid].decode(response.data))
                        if pid in {0x4F,0x50}:g['ranges'][pid]=response.data
                    elif pid in registry:
                        advertised={p for p in (0x4F,0x50) if g['bitmap'].support(p)=='SUPPORTED'}
                        basic_range(registry[pid],response.data,g['ranges'],advertised);valid=True
                    else:valid=False
                    g['decoded'][pid]+=valid
                    if definition is not None:
                        if exact:g['layout_verified'][pid]+=1;remember('layout_verified')
                        if exact and valid:g['numeric_verified'][pid]+=1;remember('numeric')
                except ValueError:pass
    output=[]
    for key,g in sorted(groups.items()):
        bitmap=g['bitmap'];declared=sorted(set().union(*(supported_pids(v,p) for p,v in bitmap.accepted.items()))-BITMAP_PIDS)
        pending=[p+32 for p,v in bitmap.accepted.items() if p<224 and p+32 in supported_pids(v,p) and p+32 not in bitmap.accepted]
        coverage='CONFLICTED' if bitmap.conflicts else 'UNKNOWN' if not bitmap.accepted else 'PARTIAL' if pending else 'COMPLETE_ADVERTISED_CHAIN'
        rows=[]
        for pid in range(1,256):
            if pid in BITMAP_PIDS:continue
            definition=definitions.get(pid);support=bitmap.support(pid)
            name=definition.name if definition else UNIMPLEMENTED_STANDARD.get(pid,{}).get('name',f'PID 01{pid:02X} — definition not verified')
            implemented=definition is not None;count=g['positive'][pid]
            facts=[f'ADVERTISED {support}' if support=='SUPPORTED' else support]
            if implemented:facts.append('DEFINITION IMPLEMENTED / synthetic tests; observed layout and vehicle accuracy separate')
            elif pid in UNIMPLEMENTED_STANDARD and UNIMPLEMENTED_STANDARD[pid]['edition']:facts.append('DOCUMENTED BUT UNIMPLEMENTED')
            else:facts.append('DEFINITION UNVERIFIED')
            if count:facts.append('RESPONSE OBSERVED')
            if count and not g['decoded'][pid]:facts.append('RAW ONLY / LAYOUT UNVERIFIED')
            expected=definition.length if definition else UNIMPLEMENTED_STANDARD.get(pid,{}).get('length')
            base=((pid-1)//32)*32
            bitmap_refs=[dict(evidence_id=identity,transaction_id=e['transaction_id'],timestamp=e['timestamp'],request=e['request'],state=e['state']) for e in g['ledger'] if e['request']==f'01{base:02X}'][:3]
            progression=dict(advertised=dict(state=support,evidence=bitmap_refs),
                recorded_positive=dict(samples=count,evidence=g['refs'][pid]['framed']),
                framed=dict(samples=count,evidence=g['refs'][pid]['framed']),
                length_verified=dict(expected_data_bytes=expected,samples=g['length_verified'][pid],evidence=g['refs'][pid]['length_verified']),
                layout_verified=dict(samples=g['layout_verified'][pid],evidence=g['refs'][pid]['layout_verified'],basis='Existing exact definition, flags and reserved/encoding rules; no new layout inferred'),
                numeric=dict(samples=g['numeric_verified'][pid],evidence=g['refs'][pid]['numeric'],basis='Offline exact-layout replay; field availability and current range configuration apply'),
                sampling=dict(role_counts=dict(g['roles'][pid]),pattern='REPEATED_ADAPTIVE_POLLING' if g['roles'][pid]['ADAPTIVE_POLLING']>1 else 'SINGLE_ADAPTIVE_POLLING_REPLY' if g['roles'][pid]['ADAPTIVE_POLLING'] else 'REPEATED_BENCHMARK_SUBSET' if g['roles'][pid]['BENCHMARK_MEASUREMENT']>1 else 'NO_RECORDED_ONGOING_POLLING_PROOF',
                    interpretation='Discovery/preparation-only values do not establish continuous monitoring or stable behavior. Repeated polling is recorded coverage, not uninterrupted physical sensing.'),
                physical=dict(state='UNVERIFIED',basis='No independent vehicle calibration supplied by software decoding'),
                evidence_limit='At most three original references per gate; samples count the full selected recording. Gates are separate facts, not health ratings.')
            rows.append(dict(pid=f'{pid:02X}',request=f'01{pid:02X}',name=name,advertised_support=support,
                decoder_implemented=implemented,live_allowlisted=pid in LIVE_PIDS|DISCOVERY_PIDS,legacy_scope=pid in LEGACY_PIDS,
                response_observed=count,valid_numeric_responses=g['decoded'][pid],positive_payload_lengths=dict(g['lengths'][pid]),facts=facts,
                confidence='Independent vehicle accuracy UNVERIFIED',evidence_progression=progression,priority='CURRENT DOCUMENTED MEASUREMENT' if implemented else 'OFFLINE RESEARCH ONLY',
                reason=UNIMPLEMENTED_STANDARD.get(pid,{}).get('reason','A support bit is not a valid positive reply; current same-ECU gates apply')))
        output.append(dict(evidence_id=identity,ecu=key[0],mode=key[1],source_kind=key[2],context_id=key[3],
            declared_measurement_status_ids=[f'{p:02X}' for p in declared],declared_count=len(declared),
            outside_legacy_scope_count=sum(p not in LEGACY_PIDS for p in declared),
            implemented_declared_count=sum(p in definitions for p in declared),
            bitmap_pages=[f'{p:02X}' for p in sorted(bitmap.accepted)],bitmap_ledger=g['ledger'],
            bitmap_coverage=coverage,unread_advertised_pages=[f'{p:02X}' for p in pending],inventory_scope_note='Declared count covers recorded anchored pages only. Partial Benchmark discovery is not evidence that Comprehensive ECU support disappeared.',
            contradictions=bitmap.problems,rows=rows,opening_sends_requests=False))
    return output


def performance(records,identity):
    scopes=defaultdict(list)
    for r,p in records:
        key=source_key(r)
        if key not in scopes and len(scopes)>=128:raise ValueError('Too many performance source scopes')
        scopes[key].append((r,p))
    output=[]
    for key,pairs in sorted(scopes.items()):
        sent=[r for r,_ in pairs if r.get('sent') is True];stamps=[r['monotonic_ns'] for r in sent]
        gaps=[(b-a)/1e6 for a,b in zip(stamps,stamps[1:])];duration=(stamps[-1]-stamps[0])/1e9 if len(stamps)>1 else None
        categories=Counter(symptom(r,p) for r,p in pairs);lat=[r['latency_ms'] for r,_ in pairs if r.get('sent') and symptom(r)=='OK' and finite(r.get('latency_ms'))]
        per=defaultdict(list)
        for r,p in pairs:
            ecus=sorted({reply.header or 'HEADERLESS' for reply in p.responses}) if p and p.responses else ['UNASSIGNED_WIRE_ATTEMPT']
            for ecu in ecus:per[(ecu,r['command'])].append((r,p))
        pid_rows=[]
        for (ecu,command),part in sorted(per.items()):
            times=[r['monotonic_ns'] for r,_ in part if r.get('sent')];cadence=[(b-a)/1e9 for a,b in zip(times,times[1:])]
            usable=sum(bool(p and not p.errors and any((reply.header or 'HEADERLESS')==ecu and reply.negative_code is None for reply in p.responses)) for r,p in part)
            pid_rows.append(dict(ecu=ecu,command=command,sent_attempts=sum(bool(r.get('sent')) for r,_ in part),
                usable_framed_positive_replies=usable,positive_replies_per_second=usable/duration if duration else None,
                recorded_numeric_decoding_replies=sum(bool(r.get('decoder')) and symptom(r,p)=='OK' for r,p in part),
                complete_017a_raw_polling_replies=sum(bool(command=='017A' and r.get('raw_only') and p and not p.errors and any((reply.header or 'HEADERLESS')==ecu and reply.negative_code is None and len(reply.data)==6 for reply in p.responses)) for r,p in part),
                sampling_gap_seconds=distribution(cadence),latency_ms=distribution([r['latency_ms'] for r,_ in part if r.get('sent') and finite(r.get('latency_ms')) and symptom(r,p)=='OK']),
                categories=dict(Counter(symptom(r,p) for r,p in part)),explicit_retry_records=sum(r.get('retry') is True for r,_ in part)))
        rolling=[statistics.pstdev(gaps[i:i+32]) for i in range(0,max(1,len(gaps)-31),8) if len(gaps[i:i+32])>=2]
        output.append(dict(evidence_id=identity,mode=key[0],source_kind=key[1],context_id=key[2],
            transmitted_requests=len(sent),send_span_seconds=duration,actual_transmitted_rate_hz=len(sent)/duration if duration else None,
            interval_rate_hz=(len(sent)-1)/duration if duration else None,rate_denominator='First to last send; count/span and interval/span are both reported',
            throughput_definitions=dict(actual_transmitted_rate_hz='COUNT_OVER_SEND_SPAN: N transmitted requests / (last send - first send); endpoint count convention',
                interval_rate_hz='INTERVALS_OVER_SEND_SPAN: (N - 1) intervals / (last send - first send); unavailable without a positive send span',
                sustained_window_rate='COUNT_OVER_MEASUREMENT_WINDOW: N measurement sends / full measured window; separate benchmark field, not send-span throughput'),
            wire_send_gap_ms=distribution(gaps),hard_four_hz_spacing_violations=sum(g<250-1e-6 for g in gaps),latency_ms=distribution(lat),categories=dict(categories),
            rolling_gap_jitter_ms=distribution(rolling),rolling_window_gaps=32,rolling_stride_gaps=8,explicit_retry_records=sum(r.get('retry') is True for r,_ in pairs),
            retries_note='Only explicit retry metadata counted; repeated ordinary polling is not inferred to be retry',
            application_latency_occupancy_proxy=sum(lat)/(duration*1000) if duration else None,
            observed_budget_slack_ms=250-percentile(lat,.95) if lat else None,
            headroom_note='Difference from the 250 ms policy interval; not bus utilization, ECU capacity or permission to increase rate',
            per_ecu_pid=pid_rows))
    return output


def analyze_obd(paths):
    if not 1<=len(paths)<=MAX_SESSIONS:raise ValueError('Choose one to sixteen private bundles')
    sessions=[];seen=set()
    for path in paths:
        identity,members=read_bundle(path)
        if identity in seen:raise ValueError('Duplicate original evidence selected, possibly through a run wrapper')
        seen.add(identity);records=strict_records(members)
        from .benchmark import benchmark_summary
        from .quality import field_quality
        benchmark=benchmark_summary(records,members,identity)
        if benchmark:
            benchmark['throughput_definitions']=dict(actual_sustained_rate='COUNT_OVER_MEASUREMENT_WINDOW: measurement sent_requests / measurement_duration_seconds; preflight excluded',
                actual_transmitted_rate_hz='COUNT_OVER_SEND_SPAN: each performance source group N / (last send - first send)',
                interval_rate_hz='INTERVALS_OVER_SEND_SPAN: each performance source group (N - 1) / (last send - first send)')
        sessions.append(dict(evidence_id=identity,checksum_verified=True,inventory=inventory(records,identity),performance=performance(records,identity),benchmark=benchmark,field_quality=field_quality(members,records)))
    histories=defaultdict(list);comparisons=[]
    for s in sessions:
        for g in s['inventory']:histories[(g['ecu'],g['mode'],g['source_kind'])].append(g)
    for key,groups in sorted(histories.items()):
        for before,after in zip(groups,groups[1:]):
            if before['evidence_id']==after['evidence_id']:continue
            if len(comparisons)>=256:break
            old=set(before['declared_measurement_status_ids']);new=set(after['declared_measurement_status_ids'])
            states={r['pid']:r['advertised_support'] for r in after['rows']}
            comparisons.append(dict(ecu=key[0],mode=key[1],source_kind=key[2],before_evidence_id=before['evidence_id'],after_evidence_id=after['evidence_id'],
                newly_advertised_ids=sorted(new-old),no_longer_advertised=[dict(pid=p,new_state=states[p]) for p in sorted(old-new)],
                unchanged_advertised_ids=sorted(old&new),order='Caller-selected bundle order, not inferred chronology',
                bitmap_coverage_pair=[before['bitmap_coverage'],after['bitmap_coverage']],complete_coverage_pair=before['bitmap_coverage']==after['bitmap_coverage']=='COMPLETE_ADVERTISED_CHAIN',
                identity_limit='CAN response address comparison only; exact ECU/calibration identity not established',
                inference_limit='Missing/conflicting bitmap evidence is UNKNOWN, not evidence of lost support; traces never joined'))
    from .benchmark import compare_benchmarks
    return dict(schema_version=1,private=True,passive=True,sends_requests=False,cloud_upload=False,sessions=sessions,inventory_comparisons=comparisons,benchmark_comparisons=compare_benchmarks(sessions),limitations=LIMITATIONS)


def export_obd_report(report,path,inputs=()):
    target=Path(path).resolve()
    if {target.with_suffix('.html'),target.with_suffix('.json')} & {Path(p).resolve() for p in inputs}:raise ValueError('Output cannot overwrite input')
    blocks=[]
    if report.get('benchmark_comparisons'):blocks.append('<h2>Separate benchmark comparisons</h2><pre>'+escape(json.dumps(report['benchmark_comparisons'],indent=2))+'</pre>')
    if report.get('inventory_comparisons'):blocks.append('<h2>Address/source inventory comparisons · no joined trace</h2><pre>'+escape(json.dumps(report['inventory_comparisons'],indent=2))+'</pre>')
    for session in report['sessions']:
        if session.get('benchmark'):
            b=session['benchmark'];blocks.append('<h2>Fixed 60-second benchmark</h2><p>'+escape(f"Run {b['run_id']} | {b['mode']} | ECU {b['ecu']} | requested {b['requested_rate']} req/s | sustained N/full measured window {b['actual_sustained_rate']} req/s | measured {b['measurement_duration_seconds']} s | sent {b['sent_requests']} | completed {b['completed']}")+'</p><p>'+escape(b['interpretation'])+'</p><details><summary>Preflight, phase and outcome provenance</summary><pre>'+escape(json.dumps(b,indent=2))+'</pre></details>')
        for g in session['inventory']:
            blocks.append('<h2>'+escape(g['ecu']+' / '+g['mode']+' / '+g['source_kind'])+'</h2><p>'+escape(f"Declared {g['declared_count']} non-bitmap identifiers; {g['outside_legacy_scope_count']} outside legacy scope. Bitmap coverage {g['bitmap_coverage']}. Support is not observation. "+g['inventory_scope_note'])+'</p>')
            blocks.append('<table><tr><th>Request</th><th>Definition</th><th>Support</th><th>Observed</th><th>Facts / provenance</th></tr>')
            for r in g['rows']:
                if r['advertised_support']!='SUPPORTED' and not r['response_observed']:continue
                blocks.append('<tr>'+''.join('<td>'+escape(str(v))+'</td>' for v in (r['request'],r['name'],r['advertised_support'],r['response_observed'],'; '.join(r['facts'])))+'</tr>')
            blocks.append('</table><details><summary>Original bitmap ledger</summary><pre>'+escape(json.dumps(g['bitmap_ledger'],indent=2))+'</pre></details>')
            blocks.append('<h3>Offline PID Explorer · separate evidence gates</h3><p>ADVERTISED → RECORDED POSITIVE → FRAMED → LENGTH VERIFIED → LAYOUT VERIFIED → NUMERIC. Physical calibration remains UNVERIFIED. No unknown values are rated healthy.</p>')
            for r in g['rows']:
                if r['advertised_support']!='SUPPORTED' and not r['response_observed']:continue
                blocks.append('<details><summary>'+escape(r['request']+' · '+r['name'])+'</summary><pre>'+escape(json.dumps(r['evidence_progression'],indent=2))+'</pre></details>')
        for q in session.get('field_quality',[]):
            blocks.append('<h2>Recorded field cadence / quality · '+escape(q['ecu'])+'</h2><p>'+escape(q['field_basis'])+'</p><p>'+escape(f"MAP byte ceiling samples {q['map_byte_ceiling_samples']} / numeric samples {q['map_numeric_samples']}; current encoding maximum {q['map_encoding_max_kpa']} kPa. "+q['map_limit'])+'</p><p>'+escape(q['vgt_limit']+' '+q['interpretation'])+'</p><table><tr><th>Field</th><th>Samples</th><th>Min / median / max</th><th>Cadence mean / max s</th></tr>')
            for f in q['fields']:blocks.append('<tr>'+''.join('<td>'+escape(str(v))+'</td>' for v in (f['sensor_id']+' / '+f['unit'],f['samples'],f"{f['minimum']} / {f['median']} / {f['maximum']}",f"{f['sampling_gap_seconds']['mean']} / {f['sampling_gap_seconds']['maximum']}"))+'</tr>')
            blocks.append('</table>')
        for g in session['performance']:
            d=g['latency_ms'];blocks.append('<h2>Communication summary · '+escape(g['mode'])+'</h2><p>'+escape(f"Sent {g['transmitted_requests']} | COUNT_OVER_SEND_SPAN N/span {g['actual_transmitted_rate_hz']} req/s | INTERVALS_OVER_SEND_SPAN (N−1)/span {g['interval_rate_hz']} req/s | latency p50 {d['p50']} / p95 {d['p95']} / p99 {d['p99']} ms | spacing violations {g['hard_four_hz_spacing_violations']}")+'</p><p>'+escape(str(g['categories']))+'</p><table><tr><th>ECU/request</th><th>Sent</th><th>Latency p50 / p95 / p99 ms</th><th>Sampling mean / max s</th></tr>')
            for r in g['per_ecu_pid']:
                d=r['latency_ms'];gap=r['sampling_gap_seconds'];blocks.append('<tr>'+''.join('<td>'+escape(str(v))+'</td>' for v in (r['ecu']+' / '+r['command'],r['sent_attempts'],f"{d['p50']} / {d['p95']} / {d['p99']}",f"{gap['mean']} mean / {gap['maximum']} max"))+'</tr>')
            blocks.append('</table>')
            blocks.append('<h2>Passive OBD performance · '+escape(g['mode'])+'</h2><pre>'+escape(json.dumps(g,indent=2))+'</pre>')
    html='<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'"><title>Private OBD inventory and performance</title><style>body{font:16px system-ui;margin:2em;max-width:1200px}table{border-collapse:collapse;width:100%}td,th{padding:.5em;border:1px solid #bbb;text-align:left}pre{white-space:pre-wrap;overflow-wrap:anywhere}</style></head><body><h1>Private OBD inventory and passive performance</h1><p>'+escape(LIMITATIONS)+'</p>'+''.join(blocks)+'</body></html>'
    _write_atomic([(target.with_suffix('.json'),json.dumps(report,ensure_ascii=False,indent=2)+'\n'),(target.with_suffix('.html'),html)])
    return target.with_suffix('.html')
