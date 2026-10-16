"""Offline separate-run benchmarks; no hardware-capacity or exact ECU identity claim."""
import json
from collections import Counter
from .obd import performance,distribution,symptom


def benchmark_summary(records,members,identity):
    summary=json.loads(members.get('session-summary.json',b'{}'));checkpoint=summary.get('stationary_benchmark')
    measured=[(r,p) for r,p in records if r.get('benchmark_phase')=='MEASUREMENT']
    if not measured and not (checkpoint and checkpoint.get('kind')=='AUTO_60S_V1'):return None
    sent=[r for r,p in measured if r.get('sent')]
    first=sent[0] if sent else measured[0][0] if measured else dict(benchmark_run_id=checkpoint.get('session_id'),benchmark_ecu=checkpoint.get('ecu'),mode=checkpoint.get('mode'),source_kind=checkpoint.get('source_kind'),benchmark_requested_rate=checkpoint.get('rate'))
    metadata=checkpoint or {}
    from mokka_ecu_lab.library import run_facts
    elapsed=metadata.get('measurement_duration_seconds')
    perf=performance(measured,identity)
    return dict(evidence_id=identity,run_id=first.get('benchmark_run_id'),ecu=first.get('benchmark_ecu'),
        mode=first.get('mode'),source_kind=first.get('source_kind'),requested_rate=first.get('benchmark_requested_rate'),
        measurement_duration_seconds=elapsed,actual_sustained_rate=len(sent)/elapsed if elapsed and elapsed>0 else None,
        sent_requests=len(sent),completed=metadata.get('completed',False),reason=metadata.get('reason','Legacy checkpoint unavailable'),outcome=run_facts(summary)['outcome'],
        pids=sorted({r['command'] for r,p in measured if r.get('sent')}),
        expected_pids=['010B','010C','010D','0110'],fixed_speed_cadence='One per four measurement sends',
        preflight_sent_requests=sum(r.get('sent') is True and r.get('benchmark_phase')=='PREFLIGHT' for r,p in records),
        categories=dict(Counter(symptom(r,p) for r,p in measured)),performance=perf,
        thermal_context='UNKNOWN: coolant is outside this fixed subset; compare warm-up conditions separately',
        identity_limit='Response address/source only; same exact ECU/calibration not independently established',
        interpretation='Fixed communication test within <=4 req/s; neither a drive-equivalent experiment nor maximum ECU capacity',
        original_journal_sha256=summary.get('original_journal_sha256'),application_versions=summary.get('application_versions',[]),
        journal_close_checkpoint=metadata)


def compare_benchmarks(sessions):
    runs=[s['benchmark'] for s in sessions if s.get('benchmark')];result=[]
    for before,after in zip(runs,runs[1:]):
        if before['evidence_id']==after['evidence_id']:continue
        same_source=all(before.get(k)==after.get(k) for k in ('ecu','mode','source_kind'))
        same_mix=before['pids']==after['pids']==before['expected_pids']
        categories=after['categories'];ok=before['completed'] and after['completed'] and same_source and same_mix and not any(v for k,v in categories.items() if k!='OK') and not any(v for k,v in before['categories'].items() if k!='OK')
        rate=after['requested_rate']
        result.append(dict(before_run=before['run_id'],after_run=after['run_id'],same_address_source=same_source,
            same_pid_mix=same_mix,same_requested_rate=before['requested_rate']==rate,complete_pair=before['completed'] and after['completed'],
            before=before,after=after,thermal_match='UNKNOWN; not a controlled causal comparison',
            next_user_choice=min(4,int(rate)+1) if ok and rate in (1,2,3) else None,
            suggestion_limit='Optional explicit separate run only, after operator review; never automatically launched; <=4 req/s'))
    return result
