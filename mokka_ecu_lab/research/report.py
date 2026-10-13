"""Private, network-free HTML rendering and additive schema-v1 compatibility."""
import copy
import html
import json
import os
import tempfile
from pathlib import Path
from .evidence import MAX_TOTAL,MAX_SESSIONS,MAX_GROUPS,MAX_PREVIEW,observation_state,REQUIREMENTS
from .summary import scr_summary,observe_summary,summary_lines
from mokka_ecu_lab.protocols import BITMAP_PIDS
from mokka_ecu_lab.sensors.diesel import STANDARD_DIESEL

RECOMMENDATIONS=[
    'Start recording before Connect; complete Discovery while stationary and choose the ECU actually observed.',
    'While parked, choose Full Auto Research Drive and give one preset RAW consent. All eligible existing standard PIDs, including NOx and eligible RAW targets, are selected automatically. Manual choices remain available.',
    'Before departure inspect worker scheduling and at least two stored six-byte 017A RAW positives when eligible; PARTIAL is an evidence warning, not a health or safety certificate.',
    'Retain complete raw bytes and asynchronous context timestamps/age. Obtain independent reference readings, units and uncertainty before interpreting a pressure hypothesis.',
    'The driver must not interact with the laptop while driving. Finish/Disconnect after parking.',
    'Read-only preparation only: no additional requests, scans, unsupported PID selection, regeneration or rate change. Aggregate ceiling remains 4 application commands/s.']


def normalize_analysis(report):
    """Preserve old keys; do not pretend a saved JSON revalidates original wire bytes."""
    if not isinstance(report,dict) or report.get('schema_version')!=1 or not isinstance(report.get('sessions'),list):
        raise ValueError('Unsupported private analysis schema')
    result=copy.deepcopy(report)
    if len(result['sessions'])>MAX_SESSIONS: raise ValueError('Too many analysis sessions')
    result.setdefault('analysis_revision',1); result.setdefault('verification_requirements',REQUIREMENTS)
    result.setdefault('limitations','Saved analysis; re-import original ZIPs to verify current framing, bitmaps and decoder evidence.')
    for session in result['sessions']:
        if not isinstance(session,dict) or not isinstance(session.get('groups'),list) or len(session['groups'])>MAX_GROUPS:
            raise ValueError('Invalid saved analysis groups')
        for key,default in (('missing_evidence',[]),('contradictions',[]),('transaction_errors',[]),('recorded_decoder_versions',[]),('transactions',0)):
            session.setdefault(key,default)
        for g in session['groups']:
            if not isinstance(g,dict) or not isinstance(g.get('matrix'),list) or len(g['matrix'])>256:
                raise ValueError('Invalid saved compatibility matrix')
            g.setdefault('samples',[])
            if not isinstance(g['samples'],list) or len(g['samples'])>MAX_PREVIEW: raise ValueError('Oversized saved preview')
            g.setdefault('source_kind','UNKNOWN'); g.setdefault('mode','UNKNOWN'); g.setdefault('ecu','UNKNOWN ECU')
            g.setdefault('missing_evidence',[]); g.setdefault('preview_limit',MAX_PREVIEW); g.setdefault('preview_truncated',False)
            for r in g['matrix']:
                if not isinstance(r,dict): raise ValueError('Invalid saved matrix row')
                try: pid=int(r['pid'],16)
                except (KeyError,TypeError,ValueError) as exc: raise ValueError('Invalid saved PID') from exc
                if not 0<=pid<=255: raise ValueError('Invalid saved PID')
                count=sum(r.get('lengths',{}).values())
                r.setdefault('request',f'01{pid:02X}'); r.setdefault('positive_response_count',count)
                r.setdefault('raw_bitmap_support',r.get('support','UNKNOWN'))
                known=set(r.get('recorded_support',[]))-{'UNKNOWN'}
                r.setdefault('recorded_discovery_support','CONFLICT' if len(known)>1 else next(iter(known),'UNKNOWN'))
                r.setdefault('recorded_support_provenance',['LEGACY_SAVED_SNAPSHOT'] if known else [])
                r.setdefault('recorded_support_raw_verified',False)
                r.setdefault('observation_state',observation_state(g['source_kind'],count))
                r.setdefault('frame_validity','INVALID_FRAMING' if r.get('invalid_framing') else 'VALID_FRAMING' if r.get('valid_framing') else 'NO_RESPONSE')
                r.setdefault('layout_state','LEGACY_ANALYSIS_REQUIRES_REIMPORT' if pid in BITMAP_PIDS else r.get('status','UNVERIFIED_LAYOUT') if count else 'NO_POSITIVE_RESPONSE')
                r.setdefault('definition_state','STANDARD_DOCUMENTED' if pid in STANDARD_DIESEL else 'UNAVAILABLE')
                r.setdefault('evidence_explanation','Saved legacy analysis: original ZIP re-import required for current bitmap provenance. The original support/layout counters have not been rewritten.')
                r.setdefault('contradictions',[])
            if 'scr_summary' not in g:
                # Old previews may contain 0188 bytes. Decode with the single
                # code-owned definition, never trust stored formulas/fields.
                aggregate=dict(matrix=g['matrix'])
                for sample in g['samples']:
                    if sample.get('pid')!='88': continue
                    try: fields=STANDARD_DIESEL[0x88].decode(bytes(sample.get('bytes',[]))); error=None
                    except (ValueError,TypeError): fields=[]; error='Legacy sample layout unverified'
                    observe_summary(aggregate,0x88,sample,fields,error)
                g['scr_summary']=scr_summary(aggregate)
                g['missing_evidence'].append('Legacy saved analysis lacks full AdBlue/NOx aggregates; re-import original ZIP for a complete current report.')
    return result


def load_analysis(path):
    path=Path(path)
    if path.stat().st_size>MAX_TOTAL: raise ValueError('Saved analysis exceeds 128 MiB limit')
    result=normalize_analysis(json.loads(path.read_text(encoding='utf-8-sig')))
    result['analysis_origin']='SAVED_ANALYSIS_NOT_REVALIDATED'
    return result


def render_html(report,selection=None,detailed=False):
    report=normalize_analysis(report)
    escape=lambda v:html.escape(str(v),quote=True)
    parts=['<!doctype html><html lang="en"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'">',
        '<title>Private Mokka ECU Lab offline research report</title>',
        '<style>body{font:16px system-ui,sans-serif;max-width:1200px;margin:2em auto;padding:0 1em;line-height:1.5;color:#17222b;background:#fff}table{border-collapse:collapse;font-size:14px;width:100%}th,td{border:1px solid #aebac4;padding:.45em;text-align:left;vertical-align:top}.scroll{overflow-x:auto}h1,h2,h3{line-height:1.25}pre{white-space:pre-wrap;overflow-wrap:anywhere}.notice{border-left:4px solid #425b73;padding:1em;background:#eff3f6}</style></head><body>',
        '<h1>Private offline ECU research report</h1>',
        '<p class="notice">Private operational evidence. Review and remove sensitive information before sharing. No physical diagnosis or independently verified ECU/DPF health conclusion is established. No network resources are loaded.</p>',
        '<h2>Overview and limits</h2>', '<p>'+escape(report['limitations'])+'</p>',
        '<p>Offline analyzer: '+escape(report.get('analyzer_version','UNKNOWN (legacy saved analysis)'))+'. Current decoder: '+escape(report.get('decoder_version','UNKNOWN'))+'. Schema 1, additive analysis revision '+escape(report['analysis_revision'])+'.</p>',
        '<p>'+('Detailed private mode explicitly selected: raw preview bytes and acquisition timestamps follow.' if detailed else 'Compact HTML: no vehicle/owner/adapter identity fields or raw acquisition timeline. The accompanying JSON retains full private evidence and must also be reviewed before sharing.')+'</p>']
    if report.get('analysis_origin'): parts.append('<p>'+escape(report['analysis_origin'])+': saved results have not been revalidated against the original ZIP.</p>')
    emitted=False
    for si,session in enumerate(report['sessions']):
        for gi,g in enumerate(session['groups']):
            if selection is not None and (si,gi)!=tuple(selection): continue
            emitted=True; rows=g['matrix']; valid=sum(r.get('valid_framing',0) for r in rows); invalid=sum(r.get('invalid_framing',0) for r in rows)
            parts.extend(['<h2>Session '+str(si+1)+' · '+escape(g['ecu'])+'</h2>',
                '<p>Mode: '+escape(g['mode'])+' · source: '+escape(g['source_kind'])+'. Original checksum verification recorded: '+escape(session.get('checksum_verified',False))+'.</p>',
                f'<p>Total session transactions: {escape(session["transactions"])}. Selected source group: {valid} valid frames, {invalid} invalid frames. Valid negative replies are counted separately from positive observations.</p>',
                '<p>Original decoder versions: '+escape(session['recorded_decoder_versions'])+'. Original CSV and wire journal remain unchanged.</p>',
                '<h3>Three-way support evidence and observed/unobserved PIDs</h3>',
                '<p>Recorded support is a stored Discovery snapshot. Raw support requires an ordered original bitmap chain. Positive response counts show observed replies, not independent decoder certification. UNKNOWN means insufficient/conflicting provenance. Snapshot UNSUPPORTED does not rule out a proprietary equivalent signal.</p>',
                '<div class="scroll"><table><thead><tr>'+''.join('<th>'+c+'</th>' for c in ('PID','Recorded snapshot','Raw bitmap','Positive samples','Observation','Frames valid / invalid / negative','Layout','Notes'))+'</tr></thead><tbody>'])
            for r in rows:
                values=(r['request'],r['recorded_discovery_support'],r['raw_bitmap_support'],r['positive_response_count'],r['observation_state'],
                    f"{r.get('valid_framing',0)} / {r.get('invalid_framing',0)} / {r.get('negative_responses',0)}",r['layout_state'],r['evidence_explanation'])
                parts.append('<tr>'+''.join('<td>'+escape(v)+'</td>' for v in values)+'</tr>')
            parts.extend(['</tbody></table></div>', '<h3>DPF 017A limitation</h3>',
                '<p>The six-byte layout remains numerically UNVERIFIED. Preserve complete RAW evidence without inserting/removing bytes. No pressure, blockage percentage or filter condition is inferred.</p>',
                '<h3>SCR, AdBlue and NOx recorded evidence</h3>'])
            if g.get('capture_coverage'):
                parts.append('<h3>Planned and observed capture coverage</h3><p>All-session positive replies and recorded RAW-only frames are separate from post-activation automatic counts. Legacy sessions lack a selection receipt; no missing plan is invented.</p><div class="scroll"><table><tr>'+''.join('<th>'+v+'</th>' for v in ('PID','All positive replies','Recorded RAW-only','Worker weight','Actual automatic positives','Observed mean interval','Plan evidence'))+'</tr>')
                for row in g['capture_coverage']:
                    values=[row.get(k) for k in ('pid','positive_responses','recorded_raw_only_positive_count','requested_weight','actual_auto_capture_samples','observed_auto_capture_interval','plan_evidence')]
                    parts.append('<tr>'+''.join('<td>'+escape(v if v is not None else 'UNKNOWN')+'</td>' for v in values)+'</tr>')
                parts.append('</table></div><p>Acquisition quality: '+escape(session.get('acquisition_quality',{}))+'</p>')
            parts.extend('<p>'+escape(line)+'</p>' for line in summary_lines(g['scr_summary'],detailed))
            parts.append('<h3>Missing provenance and contradictions</h3>')
            messages=session['missing_evidence']+g['missing_evidence']+session['contradictions']+session['transaction_errors']
            parts.extend('<p>'+escape(m)+'</p>' for m in messages or ['No additional gap reported; independent verification remains UNVERIFIED.'])
            if detailed:
                parts.extend(['<h3>Private raw preview and asynchronous context</h3>',
                    '<p>Bounded preview; full aggregate counts remain separate. Preview truncated: '+escape(g['preview_truncated'])+'. Correlation does not establish a decoder.</p>'])
                # Whitelist fields: never serialize arbitrary import metadata.
                for s in g['samples']:
                    selected={k:s.get(k) for k in ('pid','timestamp','monotonic_ns','payload_hex','layout_status')}
                    selected['context']={sensor:{k:v for k,v in values.items() if k in
                        {'value','unit','timestamp','monotonic_ns','age_seconds','simultaneous','state'}}
                        for sensor,values in s.get('context',{}).items() if sensor in {'rpm','maf','speed'} and isinstance(values,dict)}
                    parts.append('<pre>'+escape(json.dumps(selected,ensure_ascii=False,indent=2))+'</pre>')
    if not emitted: raise ValueError('Choose an existing session/source group')
    parts.append('<h2>Recommendations for the next optional recording</h2>')
    parts.extend('<p>'+escape(r)+'</p>' for r in RECOMMENDATIONS)
    parts.append('<h2>Independent verification requirements</h2>')
    parts.extend('<p>'+escape(r)+'</p>' for r in report['verification_requirements'])
    parts.append('</body></html>')
    return '\n'.join(parts)


def export_private_report(report,path,inputs=(),selection=None,detailed=False,json_path=None):
    """Fresh atomic files only. JSON is full evidence; optional HTML is selected scope."""
    path=Path(path).resolve()
    if path.suffix.lower() not in {'.json','.html'}: raise ValueError('Choose a JSON or HTML destination')
    json_path=Path(json_path).resolve() if json_path else path.with_suffix('.json')
    if json_path.suffix.lower()!='.json': raise ValueError('JSON report destination must end in .json')
    targets=[json_path]+([path] if path.suffix.lower()=='.html' else [])
    protected={Path(p).resolve() for p in inputs}
    if any(p in protected or p.exists() for p in targets):
        raise ValueError('Choose fresh report filenames; imported evidence and saved reports are never overwritten.')
    contents=[json.dumps(report,ensure_ascii=False,indent=2)+'\n']
    if len(targets)>1: contents.append(render_html(report,selection,detailed))
    if any(len(c.encode('utf-8'))>MAX_TOTAL for c in contents): raise ValueError('Report exceeds 128 MiB export limit')
    staged=[]
    try:
        for target,content in zip(targets,contents):
            target.parent.mkdir(parents=True,exist_ok=True)
            fd,name=tempfile.mkstemp(prefix='private-report-',suffix=target.suffix,dir=target.parent)
            staged.append((name,target))
            with os.fdopen(fd,'w',encoding='utf-8') as stream: stream.write(content)
        for name,target in staged:
            # Windows rename refuses replacement, including a race with a new file.
            if target.exists(): raise ValueError('Report destination appeared; choose a fresh filename')
            os.rename(name,target)
    finally:
        for name,_ in staged:
            if os.path.exists(name): os.unlink(name)
    return targets
