"""Checksum-verified private RAW evolution; representations are hypotheses, never decoders."""
import base64,json
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
CONTEXT=('rpm','maf','map','speed','coolant')


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
                        unit={'rpm':'rpm','maf':'g/s','map':'kPa','speed':'km/h','coolant':'°C'}[name],
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
                statistics=statistics,points=values,rejected_raw_records=rejected))
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
    html='<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'"><title>Private DPF RAW evolution</title><style>body{font:16px system-ui;margin:2em;max-width:1100px}svg{width:100%;max-width:900px}pre{white-space:pre-wrap;overflow-wrap:anywhere}</style></head><body><h1>Private DPF RAW evolution</h1><p>'+escape(LIMITATIONS)+'</p>'+''.join(blocks)+'</body></html>'
    _write_atomic([(target.with_suffix('.json'),json.dumps(report,ensure_ascii=False,indent=2)+'\n'),(target.with_suffix('.html'),html)])
    return target.with_suffix('.html')
