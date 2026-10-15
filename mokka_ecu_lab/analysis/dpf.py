"""Checksum-verified private RAW evolution; representations are hypotheses, never decoders."""
import base64,json,math,statistics
from bisect import bisect_right
from collections import defaultdict
from datetime import datetime,timezone
from html import escape
from pathlib import Path
from .phases import load_phase_data,utc_epoch,_write_atomic
from mokka_ecu_lab.research.evidence import read_bundle,MAX_RECORDS,MAX_SESSIONS
from mokka_ecu_lab.protocols.isotp import parse_reply

LIMITATIONS=('HYPOTHESIS ONLY: byte A and unsigned AB big/little endian are raw integer representations, '
    'not pressure units or a selected formula. No DPF health, regeneration, soot or ash inference. '
    'RPM/MAF/MAP/speed/coolant are asynchronous prior samples with explicit age; no interpolation. '
    'Flow, temperature, load, sensor zero/signedness and exact ECU calibration remain confounders. '
    'Separate bundles/ECUs/source modes are never joined into one time series. Small sample counts cannot establish dynamics.')
CONTEXT=('rpm','maf','map','load','speed','coolant')


def ranks(values):
    ordered=sorted(enumerate(values),key=lambda p:p[1]);result=[0.]*len(values);i=0
    while i<len(ordered):
        j=i+1
        while j<len(ordered) and ordered[j][1]==ordered[i][1]:j+=1
        for index,_ in ordered[i:j]:result[index]=(i+j-1)/2+1
        i=j
    return result


def pearson(x,y):
    if len(x)<3:return None
    mx,my=statistics.mean(x),statistics.mean(y);vx=sum((v-mx)**2 for v in x);vy=sum((v-my)**2 for v in y)
    return sum((a-mx)*(b-my) for a,b in zip(x,y))/math.sqrt(vx*vy) if vx and vy else None


def dynamic_statistics(points):
    polling=[p for p in points if p['raw_only_polling']]
    population='RECORDED_RAW_ONLY_POLLING' if polling else 'COMPLETE_POSITIVE_FRAMES; no polling proof'
    points=polling or points
    values=sorted({p['AB_big_endian_HYPOTHESIS'] for p in points});differences=[b-a for a,b in zip(values,values[1:])]
    correlations={}
    for name in CONTEXT:
        selected=[p for p in points if p['context'][name]['value'] is not None]
        x=[p['AB_big_endian_HYPOTHESIS'] for p in selected];y=[p['context'][name]['value'] for p in selected]
        ages=[p['context'][name]['age_seconds'] for p in selected]
        correlations[name]=dict(n=len(x),coverage_fraction=len(x)/len(points) if points else 0,pearson=pearson(x,y),spearman=pearson(ranks(x),ranks(y)),
            maximum_context_age_seconds=max(ages) if ages else None,median_context_age_seconds=statistics.median(ages) if ages else None,
            interpretation='DESCRIPTIVE / NON-CAUSAL; serial samples dependent; prior asynchronous context; no pressure formula')
    groups={}
    for label in ('STATIONARY','MOVING','UNKNOWN'):
        subset=[p for p in points if p['motion_group']==label]
        groups[label]=dict(n=len(subset),correlations={name:pearson([p['AB_big_endian_HYPOTHESIS'] for p in subset if p['context'][name]['value'] is not None],[p['context'][name]['value'] for p in subset if p['context'][name]['value'] is not None]) for name in CONTEXT})
    thermal={}
    for label,lo,hi in (('COOLANT_BELOW_60',-100,60),('COOLANT_60_TO_80',60,80),('COOLANT_80_AND_ABOVE',80,1000)):
        subset=[p for p in points if p['context']['coolant']['value'] is not None and lo<=p['context']['coolant']['value']<hi]
        thermal[label]=dict(n=len(subset),raw_first_word_range=[min(p['AB_big_endian_HYPOTHESIS'] for p in subset),max(p['AB_big_endian_HYPOTHESIS'] for p in subset)] if subset else None)
    return dict(population=population,population_samples=len(points),unique_payloads=len({p['payload_hex'] for p in points}),observed_first_word_increment_gcd=math.gcd(*differences) if differences else None,
        motion_group_descriptive=groups,coolant_context_bins=thermal,group_limit='Descriptive age-gated groups; thresholds are labels, not validated operating/health criteria. No causal model selected.',
        quantization='Observed raw-integer spacing only; no physical unit or universal resolution',
        payload_byte_ranges=[dict(byte=i,minimum=min(bytes.fromhex(p['payload_hex'])[i] for p in points),maximum=max(bytes.fromhex(p['payload_hex'])[i] for p in points),
            always_zero=all(bytes.fromhex(p['payload_hex'])[i]==0 for p in points)) for i in range(6)],correlations=correlations)


def analyze_dpf(paths):
    if not paths or len(paths)>MAX_SESSIONS: raise ValueError('Choose one to sixteen private bundles')
    groups=[]
    for path in paths:
        identity,members=read_bundle(path); data=load_phase_data(path)
        sources={(g['ecu'],g['mode'],g['source_kind']):g['fields'] for g in data['groups']}
        indices={key:{name:([p['monotonic_ns'] for p in fields.get(name,[])],fields.get(name,[])) for name in CONTEXT} for key,fields in sources.items()}
        rows=defaultdict(list); rejected=0; candidates=[]
        for index,line in enumerate(members['raw-redacted.jsonl'].splitlines()):
            if index>=MAX_RECORDS: raise ValueError('Raw record limit exceeded')
            r=json.loads(line)
            if r.get('record_type')!='transaction' or r.get('command')!='017A': continue
            candidates.append(dict(r,sample_provenance='RECORDED_JOURNAL'))
        snapshot=json.loads(members.get('discovery-report.json',b'{}'))
        for e in snapshot.get('standard',[]):
            sample=e.get('sample',{})
            if e.get('request')!='017A' or e.get('support')!='SUPPORTED' or not sample.get('raw_b64'): continue
            candidates.append(dict(command='017A',raw_b64=sample['raw_b64'],timestamp=sample['timestamp'],
                monotonic_ns=sample['monotonic_ns'],mode=snapshot.get('mode','UNKNOWN'),source_kind=sample.get('source_kind','UNKNOWN'),
                raw_only=False,id=None,sample_provenance='UNRECORDED_DISCOVERY_SNAPSHOT'))
        seen=set()
        for r in candidates:
            parsed=parse_reply(base64.b64decode(r['raw_b64'],validate=True),0x7A,'017A')
            if parsed.errors: rejected+=1; continue
            epoch=utc_epoch(r['timestamp']); ns=int(r['monotonic_ns'])
            if ns<0: raise ValueError('Invalid RAW monotonic timestamp')
            for reply in parsed.responses:
                if reply.negative_code is not None or len(reply.data)!=6: rejected+=1; continue
                identity_key=(reply.header,ns,reply.data)
                if r['sample_provenance']=='UNRECORDED_DISCOVERY_SNAPSHOT' and identity_key in seen: continue
                seen.add(identity_key)
                source_key=(reply.header or 'headerless',r.get('mode','UNKNOWN'),r.get('source_kind','UNKNOWN'))
                key=source_key+(r['sample_provenance'],)
                context={}
                for name in CONTEXT:
                    stamps,values=indices.get(source_key,{}).get(name,([],[])); pos=bisect_right(stamps,ns)-1
                    prior=values[pos] if pos>=0 else None
                    age=(ns-prior['monotonic_ns'])/1e9 if prior else None
                    context[name]=dict(value=prior['value'] if prior and age<=5 else None,
                        unit={'rpm':'rpm','maf':'g/s','map':'kPa','load':'%','speed':'km/h','coolant':'°C'}[name],
                        timestamp=prior['timestamp'] if prior else None,age_seconds=age,
                        state='PRIOR_ASYNCHRONOUS' if prior and age<=5 else 'MISSING_OR_STALE',simultaneous=False)
                speed=context['speed']['value']; group='UNKNOWN' if speed is None else 'STATIONARY' if speed==0 else 'MOVING'
                rows[key].append(dict(timestamp=r['timestamp'],epoch=epoch,monotonic_ns=ns,transaction_id=r['id'],sample_provenance=r['sample_provenance'],
                    payload_hex=reply.data.hex(' ').upper(),raw_only_polling=bool(r.get('raw_only')),
                    byte_A_HYPOTHESIS=reply.data[0],AB_big_endian_HYPOTHESIS=int.from_bytes(reply.data[:2],'big'),
                    AB_little_endian_HYPOTHESIS=int.from_bytes(reply.data[:2],'little'),context=context,motion_group=group))
        for key,values in sorted(rows.items()):
            values.sort(key=lambda r:r['monotonic_ns']); statistics={}
            for representation in ('byte_A_HYPOTHESIS','AB_big_endian_HYPOTHESIS','AB_little_endian_HYPOTHESIS'):
                statistics[representation]={}
                for motion in ('ALL','STATIONARY','MOVING','UNKNOWN'):
                    selected=[r[representation] for r in values if motion=='ALL' or r['motion_group']==motion]
                    statistics[representation][motion]=dict(samples=len(selected),minimum=min(selected) if selected else None,maximum=max(selected) if selected else None,unit='raw integer / HYPOTHESIS')
            groups.append(dict(evidence_id=identity,ecu=key[0],mode=key[1],source_kind=key[2],sample_provenance=key[3],samples=len(values),
                raw_only_polling_samples=sum(r['raw_only_polling'] for r in values),
                dynamic_evidence='INSUFFICIENT_SINGLE_SAMPLE' if len(values)<2 else 'OBSERVED_RAW_EVOLUTION_ONLY',
                statistics=statistics,dynamic_statistics=dynamic_statistics(values),points=values,rejected_raw_records=rejected,
                range_configuration_warning='Historical MAP/MAF CSV uses its recorded decoder; missing 014F/0150 observations cannot certify physical scaling. Originals are never rewritten.'))
    return dict(schema_version=1,private=True,groups=groups,limitations=LIMITATIONS,selected_formula=None,
        pressure=None,regeneration=None,soot=None,ash=None,hardware_verified=False,cloud_upload=False,plot_limit=2000)


def export_dpf_report(report,path,inputs=()):
    target=Path(path).resolve(); destinations={target.with_suffix('.json'),target.with_suffix('.html')}
    if destinations & {Path(p).resolve() for p in inputs}: raise ValueError('Output must differ from inputs')
    blocks=[]
    for group in report['groups']:
        points=group['points']; blocks.append('<h2>'+escape(group['ecu']+' / '+group['mode']+' / '+group['source_kind'])+'</h2>')
        blocks.append('<p>'+escape(f'{group["samples"]} complete six-byte samples; {group["raw_only_polling_samples"]} RAW-only polling; {group["dynamic_evidence"]}; {group["sample_provenance"]}. Snapshots outside the journal never count as recording or polling proof.')+'</p>')
        for field in ('byte_A_HYPOTHESIS','AB_big_endian_HYPOTHESIS','AB_little_endian_HYPOTHESIS')+CONTEXT:
            series=[dict(epoch=p['epoch'],value=p[field]) if field not in CONTEXT else dict(epoch=utc_epoch(p['context'][field]['timestamp']),value=p['context'][field]['value']) for p in points if field not in CONTEXT or p['context'][field]['value'] is not None]
            if field in CONTEXT: series=list({p['epoch']:p for p in series}.values())
            if not series: continue
            preview=series[::max(1,(len(series)+1999)//2000)][:2000]
            low=min(p['epoch'] for p in preview); high=max(p['epoch'] for p in preview); bottom=min(p['value'] for p in preview)-1; top=max(p['value'] for p in preview)+1
            x=lambda t:40+700*(t-low)/max(1,high-low)
            y=lambda v:190-160*(v-bottom)/max(1,top-bottom)
            svg='<svg viewBox="0 0 800 240" role="img" aria-label="Actual UTC points">'
            svg+=''.join(f'<circle cx="{x(p["epoch"]):.2f}" cy="{y(p["value"]):.2f}" r="3" fill="#176c85"/>' for p in preview)
            svg+='<text x="40" y="215">'+escape(datetime.fromtimestamp(low,timezone.utc).isoformat())+'</text><text x="350" y="235">'+escape(datetime.fromtimestamp(high,timezone.utc).isoformat())+'</text></svg>'
            unit='raw integer' if field not in CONTEXT else points[0]['context'][field]['unit']
            blocks.append('<h3>'+escape(field+' / '+unit)+'</h3><p>'+escape(f'Actual timestamps; no interpolated curve. Vertical range {bottom:g}–{top:g}. Context uses prior samples, not simultaneous values.')+'</p>'+svg)
        blocks.append('<pre>'+escape(json.dumps(group['statistics'],indent=2))+'</pre>')
        blocks.append('<h3>Dynamic descriptive evidence · no causality</h3><pre>'+escape(json.dumps(group['dynamic_statistics'],indent=2))+'</pre><p>'+escape(group['range_configuration_warning'])+'</p>')
        for name in CONTEXT:
            pairs=[p for p in points if p['raw_only_polling'] and p['context'][name]['value'] is not None][:2000]
            if not pairs:continue
            xs=[p['context'][name]['value'] for p in pairs];ys=[p['AB_big_endian_HYPOTHESIS'] for p in pairs]
            xmin,xmax=min(xs),max(xs);ymin,ymax=min(ys),max(ys)
            scatter='<svg viewBox="0 0 800 250" role="img" aria-label="RAW hypothesis versus asynchronous context">'
            for p in pairs:
                cx=50+690*(p['context'][name]['value']-xmin)/max(1,xmax-xmin);cy=185-155*(p['AB_big_endian_HYPOTHESIS']-ymin)/max(1,ymax-ymin)
                tooltip=p['timestamp']+' / '+p['payload_hex']+' / context age '+str(p['context'][name]['age_seconds'])+' s'
                scatter+=f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="3" fill="#176c85"><title>'+escape(tooltip)+'</title></circle>'
            scatter+='<text x="50" y="220">'+escape(f'{name} {xmin:g}–{xmax:g} {pairs[0]["context"][name]["unit"]}; prior samples, not simultaneous')+'</text><text x="50" y="240">'+escape(f'RAW first-word HYPOTHESIS {ymin:g}–{ymax:g}; no physical unit or causal inference')+'</text></svg>'
            blocks.append('<h3>'+escape('RAW first-word HYPOTHESIS vs '+name)+'</h3>'+scatter)
        blocks.append('<details><summary>All six bytes and prior context / ages · preview ≤2000 points</summary><pre>'+escape('\n'.join(p['timestamp']+' / '+p['payload_hex']+' / '+json.dumps(p['context']) for p in points[:2000]))+'</pre></details>')
    html='<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'"><title>Private DPF RAW evolution</title><style>body{font:16px system-ui;margin:2em;max-width:1100px}svg{width:100%;max-width:900px}pre{white-space:pre-wrap;overflow-wrap:anywhere}</style></head><body><h1>Private DPF RAW evolution</h1><p>'+escape(LIMITATIONS)+'</p>'+''.join(blocks)+'</body></html>'
    _write_atomic([(target.with_suffix('.json'),json.dumps(report,ensure_ascii=False,indent=2)+'\n'),(target.with_suffix('.html'),html)])
    return target.with_suffix('.html')
