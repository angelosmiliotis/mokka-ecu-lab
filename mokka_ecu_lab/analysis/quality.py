"""Offline recorded-field cadence and censoring facts; no physical diagnosis."""
import csv,io,math,statistics
from collections import defaultdict

def field_quality(members,records):
    from .obd import distribution
    from mokka_ecu_lab.research.evidence import MAX_RECORDS
    tx={r['id']:r for r,p in records if isinstance(r.get('id'),str)};groups={}
    for i,row in enumerate(csv.DictReader(io.StringIO(members.get('measurements.csv',b'').decode('utf-8-sig')))):
        if i>=MAX_RECORDS:raise ValueError('Recorded field quality limit exceeded')
        r=tx.get(row.get('transaction_id'))
        if r is None:continue
        value=float(row['value']);ns=int(row['monotonic_ns'])
        if not math.isfinite(value) or ns<0:continue
        key=(row['ecu'],row.get('source_mode',r.get('mode','UNKNOWN')),row.get('source_kind',r.get('source_kind','UNKNOWN')),r.get('context_id','UNKNOWN'))
        g=groups.setdefault(key,dict(fields=defaultdict(list),pairs=defaultdict(dict),map_ceiling=0,range_selectors={}))
        g['fields'][row['sensor_id']].append((value,ns,row['unit']))
        if row['sensor_id'] in {'sae_71_vgt_a_command','sae_71_vgt_a_position'}:g['pairs'][row['transaction_id']][row['sensor_id']]=value
    for r,parsed in records:
        if not parsed or parsed.errors:continue
        for reply in parsed.responses:
            if reply.negative_code is not None:continue
            key=(reply.header,r.get('mode'),r.get('source_kind'),r.get('context_id','UNKNOWN'));g=groups.get(key)
            if g is None:continue
            if r['command']=='014F' and len(reply.data)==4:g['range_selectors']['014F_MAP']=reply.data[3]
            if r['command']=='0150' and len(reply.data)==4:g['range_selectors']['0150_MAF']=reply.data[0]
            if r['command']=='010B' and len(reply.data)==1 and reply.data[0]==255:g['map_ceiling']+=1
    result=[]
    for key,g in sorted(groups.items()):
        fields=[]
        for name,points in sorted(g['fields'].items()):
            values=[p[0] for p in points];times=sorted({p[1] for p in points});gaps=[(b-a)/1e9 for a,b in zip(times,times[1:])]
            fields.append(dict(sensor_id=name,unit=points[0][2],samples=len(points),minimum=min(values),median=statistics.median(values),maximum=max(values),distinct_values=len(set(values)),sampling_gap_seconds=distribution(gaps),physical_accuracy='UNVERIFIED'))
        differences=[p['sae_71_vgt_a_position']-p['sae_71_vgt_a_command'] for p in g['pairs'].values() if {'sae_71_vgt_a_command','sae_71_vgt_a_position'}<=p.keys()]
        selector=g['range_selectors'].get('014F_MAP');encoding_max=255 if selector==0 else selector*10 if selector else None
        result.append(dict(ecu=key[0],mode=key[1],source_kind=key[2],context_id=key[3],fields=fields,
            map_byte_ceiling_samples=g['map_ceiling'],map_numeric_samples=len(g['fields'].get('map',[])),current_range_selectors=g['range_selectors'],map_encoding_max_kpa=encoding_max,
            map_limit='Byte 255 can censor higher MAP. Current range configuration is required; do not extrapolate clipped boost or substitute exhaust pressure. No verified currently advertised alternative is inferred.',
            vgt_position_minus_command_percent=distribution(differences),vgt_limit='Same-frame descriptive differences; sparse cadence and control dynamics do not establish lag or a fault.',
            field_basis='Checksum-covered recorded numeric CSV, linked to original transaction/source context; not independent physical calibration',
            interpretation='Pedal D/E, throttle and EGR command/error have distinct meanings. Quantized reagent is not consumption; current/historical SCR and PM-sensor/DPF regeneration are separate. Sport timing requires an explicit uncertain user annotation.'))
    return result
