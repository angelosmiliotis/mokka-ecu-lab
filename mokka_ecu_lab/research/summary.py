"""Source-specific human summaries of fields from the code-owned decoder.

No formulas, transport access, diagnostic thresholds or confidence promotion.
"""
from collections import Counter

REASONS=('low reagent','incorrect reagent','consumption deviation','high NOx')


def observe_summary(group,pid,record,fields,error):
    if pid not in {0x83,0x85,0x88}: return
    aggregate=group.setdefault('summary_evidence',dict(decoded_counts=Counter(),ranges={},latest={},last_valid_scr=None))
    sample=dict(timestamp=record.get('timestamp'),layout_valid=not bool(error),fields=fields)
    aggregate['latest'][f'{pid:02X}']=sample
    if error: return
    aggregate['decoded_counts'][f'{pid:02X}']+=1
    if pid==0x88: aggregate['last_valid_scr']=sample
    for f in fields:
        if f['state']!='AVAILABLE' or f['value'] is None: continue
        key=f['sensor_id']; value=f['value']
        stats=aggregate['ranges'].setdefault(key,dict(count=0,minimum=value,maximum=value,latest=value,unit=f['unit']))
        stats.update(count=stats['count']+1,minimum=min(stats['minimum'],value),maximum=max(stats['maximum'],value),latest=value)


def scr_summary(group):
    evidence=group.get('summary_evidence',{})
    counts=evidence.get('decoded_counts',{}); latest=evidence.get('latest',{}).get('88')
    rows={r['pid']:r for r in group['matrix']}
    current=dict(availability='UNAVAILABLE',state='UNAVAILABLE',timestamp=None,reasons=[],historical=[],counters=[],semantic_warnings=[])
    if latest and latest['layout_valid']:
        fields={f['sensor_id']:f for f in latest['fields']}
        active=fields['sae_88_active']['value']==1
        current.update(availability='AVAILABLE',state='Active at recorded time' if active else 'Inactive at recorded time',timestamp=latest['timestamp'],
            reasons=[dict(reason=name,set=bool(fields['sae_88_'+key]['value'])) for key,name in
                zip(('low_reagent','incorrect_reagent','consumption_deviation','high_nox'),REASONS)],
            historical=[dict(block=j+1,meaning=fields[f'sae_88_history_{j}_0']['temporal_semantics'],
                reasons=[dict(reason=name,set=bool(fields[f'sae_88_history_{j}_{i}']['value'])) for i,name in enumerate(REASONS)]) for j in range(4)],
            counters=[dict(name=f['name'],value=f['value'],unit=f['unit'],meaning=f['temporal_semantics']) for f in latest['fields'] if f['unit']=='km'],
            semantic_warnings=sorted({w for f in latest['fields'] for w in f.get('semantic_warnings',[])}))
    elif latest:
        current['unavailable_reason']='Latest complete 0188 reply has an unverified layout; no inactive/active value can be assigned.'
    else: current['unavailable_reason']='No complete positive 0188 sample. Absence never means inactive or healthy.'
    ranges=evidence.get('ranges',{})
    tank=ranges.get('sae_85_tank_level')
    warning=ranges.get('sae_85_warning_time')
    return dict(independent_verification='UNVERIFIED',current=current,
        positive_samples={pid:rows.get(pid,{}).get('positive_response_count',0) for pid in ('83','85','88')},
        documented_samples={pid:counts.get(pid,0) for pid in ('83','85','88')},
        adblue=dict(tank_level=tank,warning_time=warning,decoded_observations=counts.get('85',0),
            availability='AVAILABLE' if tank or warning else 'UNAVAILABLE',
            warning_time_static=bool(warning and warning['count']>1 and warning['minimum']==warning['maximum']),
            interpretation='Tank level is quantized (100/255 percent per encoded step); its observed range does not measure consumed volume. A static or nonzero warning-time counter alone does not establish a current SCR fault.'),
        nox=dict(decoded_observations=counts.get('83',0),
            fields={k:v for k,v in ranges.items() if k.startswith('sae_83_')},
            availability='AVAILABLE' if any(k.startswith('sae_83_') for k in ranges) else 'UNAVAILABLE',
            interpretation='One sample is not a trend. Concentration observations alone do not establish SCR health, emissions compliance or conversion efficiency.'),
        limitations='Recorded-time evidence only. Historical evidence — not current fault. Counters describe SAE rolling blocks, not odometer, lifetime fault distance or distance since DPF regeneration. No physical diagnosis is established.')


def summary_lines(summary, detailed=True):
    """Plain text for GUI; HTML export escapes every line independently."""
    current=summary['current']
    lines=['SCR / AdBlue · independent verification: UNVERIFIED',
        f"0188: {summary['positive_samples']['88']} complete positive replies; {summary['documented_samples']['88']} documented samples.",
        'Current inducement evidence: '+current['state']]
    if current['availability']=='AVAILABLE':
        lines.append('Acquisition timestamp: '+str(current['timestamp']) if detailed else 'Acquisition timestamp omitted in compact report; retained in private JSON.')
        lines.extend('Current reason '+r['reason']+': '+('set at recorded time' if r['set'] else 'not set at recorded time') for r in current['reasons'])
        lines.append('Historical evidence — not current fault')
        for block in current['historical']:
            names=', '.join(r['reason'] for r in block['reasons'] if r['set']) or 'no reason flags set'
            lines.append(f"Block {block['block']}: {names}. {block['meaning']}")
        lines.append('Five unsigned kilometre counters at the same recorded acquisition')
        lines.extend(f"{c['name']}: {c['value']:g} {c['unit']}. {c['meaning']}" for c in current['counters'])
        lines.extend('Semantic warning: '+w for w in current['semantic_warnings'])
    else: lines.append(current.get('unavailable_reason','Re-import the original ZIP to recover documented sample evidence.'))
    adblue=summary['adblue']; tank=adblue['tank_level']; warning=adblue['warning_time']
    lines.append(f"0185 AdBlue: {adblue['decoded_observations']} documented observations; {adblue['availability']}.")
    if tank: lines.append(f"Tank level: {tank['count']} decoded observations; quantized range {tank['minimum']:.3f}–{tank['maximum']:.3f} %.")
    if warning: lines.append(f"Warning engine-time counter: {warning['minimum']:g}–{warning['maximum']:g} s; "+('static in these observations.' if adblue['warning_time_static'] else 'recorded counter evidence.'))
    lines.append(adblue['interpretation'])
    nox=summary['nox']; lines.append(f"0183 NOx: {nox['decoded_observations']} documented samples; {nox['availability']}.")
    lines.append(nox['interpretation']); lines.append(summary['limitations'])
    return lines
