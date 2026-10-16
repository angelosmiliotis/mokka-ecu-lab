"""Private user annotations and cautious offline comparisons; no acquisition imports."""
import csv
import io
import json
import math
import os
import tempfile
from bisect import bisect_right
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from mokka_ecu_lab.research.evidence import read_bundle, MAX_RECORDS

PHASES = ('Normal', 'Sport on', 'Sport off', 'City', 'Open road')
FIELDS = {'rpm':'rpm','speed':'km/h','load':'%','maf':'g/s','map':'kPa','coolant':'°C',
          'sae_83_bank_1_sensor_1':'ppm','sae_83_bank_1_sensor_2':'ppm',
          'sae_83_bank_2_sensor_1':'ppm','sae_83_bank_2_sensor_2':'ppm'}
LIMITS = ('OBSERVATIONAL — NOT CAUSAL. Sport state is USER_REPORTED, never ECU-confirmed. '
          'The selected uncertainty range is user-defined, not a validated bound on actual toggle timing. '
          'RPM, load, speed, temperature and driver inputs can differ. MAP is absolute manifold pressure; '
          'Byte 255 can be an encoding ceiling; its physical maximum depends on current range configuration and may be censored. Cached context is asynchronous, with age; '
          'no interpolation, gear/pedal/commanded boost or sub-second turbo-lag conclusion. '
          'Serial samples are dependent; descriptive ranges are not causal confidence intervals.')


def _write_atomic(outputs):
    targets=[Path(p) for p,_ in outputs]
    if len(set(targets))!=len(targets) or any(p.exists() for p in targets):
        raise ValueError('Choose fresh output filenames; existing files are preserved')
    staged=[]
    try:
        for target,text in outputs:
            target.parent.mkdir(parents=True,exist_ok=True)
            fd,name=tempfile.mkstemp(prefix='private-phase-',dir=target.parent)
            staged.append((name,target))
            with os.fdopen(fd,'w',encoding='utf-8') as stream: stream.write(text)
        for name,target in staged:
            # Exclusive atomic publication on NTFS; an existing destination is never replaced.
            os.link(name,target)
    finally:
        for name,_ in staged:
            if os.path.exists(name): os.unlink(name)


def utc_epoch(value):
    stamp=datetime.fromisoformat(value.replace('Z','+00:00'))
    if stamp.tzinfo is None: raise ValueError('Annotation and sample timestamps require an explicit UTC offset')
    return stamp.timestamp()


def annotation(phase, timestamp, uncertainty_seconds, *, ecu, mode, source_kind,
               evidence_id=None, note='', origin='OFFLINE_USER_EDIT', previous=None):
    if phase not in PHASES: raise ValueError('Unknown user phase')
    utc_epoch(timestamp)
    uncertainty=float(uncertainty_seconds)
    if not math.isfinite(uncertainty) or not 0<=uncertainty<=3600:
        raise ValueError('Uncertainty must be 0–3600 seconds')
    if origin not in {'OFFLINE_USER_EDIT','STATIONARY_OR_PASSENGER_MARKER'}:
        raise ValueError('Unknown annotation origin')
    return dict(phase=phase,timestamp=timestamp,uncertainty_seconds=uncertainty,
        precision='APPROXIMATE' if uncertainty else 'USER_ENTERED_TIMESTAMP',
        provenance='USER_REPORTED',ecu=ecu,mode=mode,source_kind=source_kind,
        evidence_id=evidence_id,note=str(note)[:512],origin=origin,ecu_confirmed=False,
        edited_at=datetime.now(timezone.utc).isoformat(),
        previous_timestamp=previous.get('timestamp') if previous else None)


def validate_annotation(item):
    if not isinstance(item,dict) or item.get('provenance')!='USER_REPORTED' or item.get('ecu_confirmed') is not False:
        raise ValueError('Only user-reported, non-ECU-confirmed annotations are accepted')
    checked=annotation(item['phase'],item['timestamp'],item['uncertainty_seconds'],
        ecu=item['ecu'],mode=item['mode'],source_kind=item['source_kind'],evidence_id=item.get('evidence_id'),
        origin=item.get('origin','OFFLINE_USER_EDIT'),note=item.get('note',''))
    checked.update({k:item[k] for k in ('edited_at','previous_timestamp') if k in item})
    return checked


def save_annotations(items, path, inputs=()):
    target=Path(path).resolve()
    if target.suffix.lower()!='.json' or target in {Path(p).resolve() for p in inputs}:
        raise ValueError('Choose a separate private JSON sidecar; original evidence cannot be overwritten')
    _write_atomic([(target,json.dumps(dict(schema_version=1,private=True,
        annotations=[validate_annotation(i) for i in items]),ensure_ascii=False,indent=2)+'\n')])


def load_annotations(path):
    path=Path(path)
    if path.stat().st_size>1048576: raise ValueError('Annotation sidecar exceeds 1 MiB')
    data=json.loads(path.read_text(encoding='utf-8-sig'))
    if data.get('schema_version')!=1 or not isinstance(data.get('annotations'),list) or len(data['annotations'])>1000:
        raise ValueError('Unsupported annotation sidecar')
    return [validate_annotation(i) for i in data['annotations']]


def load_phase_data(path):
    identity,members=read_bundle(path)
    groups=defaultdict(lambda:defaultdict(list)); ignored=0
    for index,row in enumerate(csv.DictReader(io.StringIO(members.get('measurements.csv',b'').decode('utf-8-sig')))):
        if index>=MAX_RECORDS: raise ValueError('Measurement row limit exceeded')
        sensor=row.get('sensor_id')
        if sensor not in FIELDS: continue
        try:
            epoch=utc_epoch(row['timestamp']); ns=int(row['monotonic_ns']); value=float(row['value'])
            if not math.isfinite(value) or ns<0 or row['unit']!=FIELDS[sensor]: raise ValueError()
        except (KeyError,TypeError,ValueError): ignored+=1; continue
        key=(row.get('ecu','UNKNOWN'),row.get('source_mode','UNKNOWN'),row.get('source_kind','UNKNOWN'))
        groups[key][sensor].append(dict(epoch=epoch,monotonic_ns=ns,value=value,timestamp=row['timestamp']))
    result=[]
    for key,fields in sorted(groups.items()):
        for values in fields.values(): values.sort(key=lambda r:r['monotonic_ns'])
        result.append(dict(ecu=key[0],mode=key[1],source_kind=key[2],fields=dict(fields)))
    markers=json.loads(members.get('markers.json',b'[]'))
    return dict(evidence_id=identity,groups=result,ignored_invalid_rows=ignored,markers=markers,
        acquisition_receipt=json.loads(members['acquisition-receipt.json']) if 'acquisition-receipt.json' in members else None,
        checksum_verified=True)


def percentile(values, q):
    values=sorted(values)
    if not values: return None
    position=(len(values)-1)*q; low=int(position); fraction=position-low
    return values[low]*(1-fraction)+values[min(low+1,len(values)-1)]*fraction


def statistics(samples, sensor):
    values=[r['value'] for r in samples]
    gaps=[(b['monotonic_ns']-a['monotonic_ns'])/1e9 for a,b in zip(samples,samples[1:]) if b['monotonic_ns']>a['monotonic_ns']]
    return dict(samples=len(values),maximum=max(values) if values else None,median=median(values) if values else None,
        p95=percentile(values,.95),p25=percentile(values,.25),p75=percentile(values,.75),
        saturation_count=sum(v==255 for v in values) if sensor=='map' else None,
        saturation_fraction=sum(v==255 for v in values)/len(values) if values and sensor=='map' else None,
        mean_interval_seconds=sum(gaps)/len(gaps) if gaps else None,maximum_gap_seconds=max(gaps) if gaps else None,
        transient_quality='INSUFFICIENT: no user-identified comparable transient events; no turbo-lag inference')


def compare_phases(data, group_index, anchor, *, max_context_age=5., minimum_per_phase=5):
    anchor=validate_annotation(anchor); group=data['groups'][group_index]
    if anchor.get('evidence_id')!=data['evidence_id'] or any(anchor[k]!=group[k] for k in ('ecu','mode','source_kind')):
        raise ValueError('Annotation must match this exact session, ECU, mode and source')
    if (group['source_kind'] not in {'ECU_READING','SIMULATED'} or
        (group['source_kind']=='SIMULATED' and group['mode']!='SIMULATED') or
        (group['source_kind']=='ECU_READING' and not group['mode'].startswith('LIVE'))):
        raise ValueError('Unknown or contradictory source provenance; comparisons suppressed')
    if anchor['phase']!='Sport on': raise ValueError('Choose a USER_REPORTED Sport on anchor for this comparison')
    if not math.isfinite(max_context_age) or not 0<max_context_age<=30 or not 2<=minimum_per_phase<=100:
        raise ValueError('Invalid matching bounds')
    cutoff=utc_epoch(anchor['timestamp']); uncertainty=anchor['uncertainty_seconds']
    all_epochs=[r['epoch'] for samples in group['fields'].values() for r in samples]
    if not all_epochs or not min(all_epochs)<=cutoff<=max(all_epochs):
        raise ValueError('Anchor lies outside the selected recorded source group')
    def phase(r): return 'before' if r['epoch']<cutoff-uncertainty else 'after' if r['epoch']>cutoff+uncertainty else 'uncertain'
    summary=[]; matched=[]; series={}; excluded=0
    fields=group['fields']; lookup={s:[r['monotonic_ns'] for r in rows] for s,rows in fields.items()}
    for sensor,samples in sorted(fields.items()):
        phases={name:[r for r in samples if phase(r)==name] for name in ('before','after','uncertain')}
        summary.append(dict(sensor_id=sensor,unit=FIELDS[sensor],before=statistics(phases['before'],sensor),
            after=statistics(phases['after'],sensor),uncertain_samples=len(phases['uncertain'])))
        step=max(1,(len(samples)+1999)//2000)
        series[sensor]=[dict(timestamp=r['timestamp'],epoch=r['epoch'],value=r['value'],phase=phase(r)) for r in samples[::step]]
        if sensor not in {'map','maf'}: continue
        bins=defaultdict(lambda:dict(before=[],after=[],context_ages=[])); missing=0
        for r in samples:
            p=phase(r)
            if p=='uncertain': continue
            context={}; ages=[]
            for signal in ('rpm','load','speed'):
                index=bisect_right(lookup.get(signal,[]),r['monotonic_ns'])-1
                if index<0: break
                prior=fields[signal][index]; age=(r['monotonic_ns']-prior['monotonic_ns'])/1e9
                if age>max_context_age: break
                context[signal]=prior['value']; ages.append(age)
            if len(context)!=3: missing+=1; continue
            key=(int(context['rpm']//500)*500,int(context['load']//20)*20,int(context['speed']//10)*10)
            bins[key][p].append(r); bins[key]['context_ages'].extend(ages)
        comparisons=[]
        for key,values in sorted(bins.items()):
            if min(len(values['before']),len(values['after']))<minimum_per_phase: continue
            before=statistics(values['before'],sensor); after=statistics(values['after'],sensor)
            comparisons.append(dict(rpm_range=[key[0],key[0]+500],load_range=[key[1],key[1]+20],speed_range=[key[2],key[2]+10],
                before=before,after=after,median_difference=after['median']-before['median'],
                maximum_context_age_seconds=max(values['context_ages']),context_simultaneous=False,
                interpretation='OBSERVATIONAL — NOT CAUSAL; residual confounding remains'))
        excluded+=missing
        matched.append(dict(sensor_id=sensor,valid_overlap_bins=len(comparisons),comparisons=comparisons,
            excluded_missing_or_old_context=missing,state='DESCRIPTIVE_OVERLAP' if comparisons else 'INSUFFICIENT_OVERLAP',
            conclusion='Causal Sport/turbo conclusions suppressed'))
    return dict(schema_version=1,private=True,evidence_id=data['evidence_id'],ecu=group['ecu'],mode=group['mode'],source_kind=group['source_kind'],
        anchor=anchor,uncertainty_band_seconds=[cutoff-uncertainty,cutoff+uncertainty],summary=summary,matched=matched,series=series,
        plot_limit_per_field=2000,interpolation=False,max_context_age_seconds=max_context_age,minimum_per_phase=minimum_per_phase,
        excluded_context_samples=excluded,limitations=LIMITS,causal_conclusion=None,hardware_verified=False,cloud_upload=False)


def export_phase_report(report, path, inputs=()):
    """Fresh private JSON plus escaped self-contained HTML; original inputs immutable."""
    from html import escape
    target=Path(path).resolve(); json_path=target.with_suffix('.json'); html_path=target.with_suffix('.html')
    if {json_path,html_path} & {Path(p).resolve() for p in inputs}: raise ValueError('Output must differ from inputs')
    cells=[]
    for row in report['summary']:
        cells.append('<tr>'+''.join('<td>'+escape(str(v))+'</td>' for v in [row['sensor_id'],row['unit'],
            row['before']['samples'],row['after']['samples'],row['before']['maximum'],row['after']['maximum'],
            row['before']['median'],row['after']['median'],row['before']['p95'],row['after']['p95'],
            row['before']['saturation_fraction'],row['after']['saturation_fraction']])+'</tr>')
    plots=[]
    for sensor,points in report['series'].items():
        if not points: continue
        low=min(p['epoch'] for p in points); high=max(p['epoch'] for p in points)
        ymin=min(p['value'] for p in points)-1; ymax=max(p['value'] for p in points)+1
        x=lambda t:40+720*(t-low)/max(1,high-low)
        y=lambda v:200-170*(v-ymin)/max(1,ymax-ymin)
        band=report['uncertainty_band_seconds']; left=max(40,min(760,x(band[0]))); right=max(40,min(760,x(band[1])))
        svg='<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 245" role="img" aria-label="UTC measured points">'
        svg+=f'<rect x="{left:.2f}" y="20" width="{max(0,right-left):.2f}" height="180" fill="#ffe7aa"/>'
        anchor_x=x(utc_epoch(report['anchor']['timestamp']))
        if 40<=anchor_x<=760: svg+=f'<path d="M{anchor_x:.2f} 20 V200" stroke="#aa6500" stroke-dasharray="4 4"/>'
        svg+=''.join(f'<circle cx="{x(p["epoch"]):.2f}" cy="{y(p["value"]):.2f}" r="2" fill="#176c85"/>' for p in points)
        svg+='<text x="40" y="225">'+escape(datetime.fromtimestamp(low,timezone.utc).isoformat())+'</text><text x="420" y="242">'+escape(datetime.fromtimestamp(high,timezone.utc).isoformat())+'</text></svg>'
        plots.append('<h3>'+escape(sensor)+'</h3><p>Measured points on UTC axis; shaded user uncertainty band. Vertical range '+escape(f'{ymin:g}–{ymax:g}')+'. Preview limited to 2000 points; statistics use all valid samples.</p>'+svg)
    html='<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'"><title>Private phase comparison</title><style>body{font:16px system-ui;padding:2em}table{border-collapse:collapse}td,th{border:1px solid #999;padding:.5em}pre{white-space:pre-wrap;overflow-wrap:anywhere}svg{width:100%;max-width:1000px}</style></head><body><h1>Private phase comparison</h1><p>'+escape(report['limitations'])+'</p><p>USER_REPORTED anchor: '+escape(report['anchor']['timestamp'])+' ± '+escape(str(report['anchor']['uncertainty_seconds']))+' seconds. User-selected uncertainty band excluded; the true timing error is not independently known.</p><p>Private anchor note: '+escape(report['anchor'].get('note',''))+'</p><table><tr>'+''.join('<th>'+s+'</th>' for s in ['Field','Unit','Before n','After n','Before max','After max','Before median','After median','Before p95','After p95','Before capped fraction','After capped fraction'])+'</tr>'+''.join(cells)+'</table><h2>Matched asynchronous operating ranges</h2><pre>'+escape(json.dumps(report['matched'],ensure_ascii=False,indent=2))+'</pre><h2>UTC measured-point plots</h2>'+''.join(plots)+'</body></html>'
    _write_atomic([(json_path,json.dumps(report,ensure_ascii=False,indent=2)+'\n'),(html_path,html)])
    return [json_path,html_path]
