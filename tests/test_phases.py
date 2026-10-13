"""Synthetic phase data only; no real dates, driving history or bundle bytes."""
import json
from copy import deepcopy
from datetime import datetime,timezone
import pytest
from mokka_ecu_lab.analysis.phases import (annotation,compare_phases,save_annotations,load_annotations,
    export_phase_report,utc_epoch)
from mokka_ecu_lab.logging import Recorder,export_jsonl
from mokka_ecu_lab.replay import Replay


def synthetic():
    base=946684800.; fields={}
    for i,(sensor,value) in enumerate([('rpm',2100),('load',45),('speed',35),('map',115),('maf',22),('coolant',70),('sae_83_bank_1_sensor_1',30)]):
        rows=[]
        for j in range(24):
            epoch=base+j*2+i*.1
            measured=255 if sensor=='map' and j==20 else value+(10 if sensor in {'map','maf'} and j>11 else 0)
            rows.append(dict(epoch=epoch,monotonic_ns=int((epoch-base)*1e9),value=measured,
                timestamp=datetime.fromtimestamp(epoch,timezone.utc).isoformat()))
        fields[sensor]=rows
    data=dict(evidence_id='synthetic-evidence',groups=[dict(ecu='7E8',mode='SIMULATED',source_kind='SIMULATED',fields=fields)])
    a=annotation('Sport on','2000-01-01T00:00:24+00:00',2,ecu='7E8',mode='SIMULATED',source_kind='SIMULATED',evidence_id=data['evidence_id'],note='<script>private</script>')
    return data,a


def test_uncertain_anchor_capped_map_and_asynchronous_overlap_are_noncausal():
    data,a=synthetic(); report=compare_phases(data,0,a)
    map_row=next(r for r in report['summary'] if r['sensor_id']=='map')
    assert map_row['after']['maximum']==255 and map_row['after']['saturation_count']==1
    assert map_row['uncertain_samples']>=1
    assert report['causal_conclusion'] is None and not report['interpolation']
    assert 'OBSERVATIONAL — NOT CAUSAL' in report['limitations']
    assert all(m['valid_overlap_bins']>=1 for m in report['matched'])
    assert all(c['context_simultaneous'] is False and c['maximum_context_age_seconds']<=5
               for m in report['matched'] for c in m['comparisons'])
    assert all('INSUFFICIENT' in r['after']['transient_quality'] for r in report['summary'])


def test_absent_matching_context_suppresses_comparison():
    data,a=synthetic(); data['groups'][0]['fields'].pop('load')
    report=compare_phases(data,0,a)
    assert all(m['state']=='INSUFFICIENT_OVERLAP' and not m['comparisons'] for m in report['matched'])
    assert report['causal_conclusion'] is None


@pytest.mark.parametrize('key,value',[('evidence_id','different'),('ecu','7E9'),('mode','LIVE'),('source_kind','ECU_READING')])
def test_annotation_never_crosses_session_ecu_or_source(key,value):
    data,a=synthetic(); a[key]=value
    with pytest.raises(ValueError,match='match'): compare_phases(data,0,a)


def test_annotation_validation_provenance_uncertainty_and_time_zone():
    data,a=synthetic()
    for invalid in [dict(a,provenance='ECU_READING'),dict(a,ecu_confirmed=True),dict(a,uncertainty_seconds=-1),
                    dict(a,timestamp='2000-01-01T00:00:24')]:
        with pytest.raises(ValueError): compare_phases(data,0,invalid)
    edited=annotation('Sport on','2000-01-01T00:00:28+00:00',5,ecu='7E8',mode='SIMULATED',source_kind='SIMULATED',evidence_id=data['evidence_id'],previous=a)
    assert edited['previous_timestamp']==a['timestamp'] and edited['provenance']=='USER_REPORTED'


def test_private_sidecar_html_exports_preserve_original_and_escape_notes(tmp_path):
    data,a=synthetic(); source=tmp_path/'original.json'; source.write_text('original')
    with pytest.raises(ValueError): save_annotations([a],source,[source])
    sidecar=tmp_path/'phase.json'; save_annotations([a],sidecar,[source]); loaded=load_annotations(sidecar)
    assert loaded[0]['timestamp']==a['timestamp']
    report=compare_phases(data,0,loaded[0]); targets=export_phase_report(report,tmp_path/'report.html',[source,sidecar])
    assert all(p.exists() for p in targets) and source.read_text()=='original'
    html=targets[1].read_text(encoding='utf-8'); assert '<script>' not in html and 'default-src' in html
    assert json.loads(targets[0].read_text(encoding='utf-8'))['anchor']['note']=='<script>private</script>'
    with pytest.raises(ValueError): export_phase_report(report,tmp_path/'report.html',[source])


def test_phase_marker_redaction_replay_and_no_requests(tmp_path):
    recorder=Recorder(tmp_path,'SIMULATED',{})
    record=recorder.marker('Phase','private','SIMULATED','2000-01-01T00:00:01+00:00',1000000000,
                           'Sport on',30,'7E8')
    assert recorder.count==0 and recorder.errors==0 and record['provenance']=='USER_REPORTED'
    assert record['uncertainty_seconds']==30 and not record['ecu_confirmed']
    recorder.close(); before=recorder.path.read_bytes()
    target=tmp_path/'redacted.jsonl'; export_jsonl(recorder.path,target)
    redacted=json.loads(target.read_text()); assert redacted['phase']=='REDACTED_USER_PHASE'
    assert redacted['note']=='REDACTED_USER_NOTE'
    private=tmp_path/'private.jsonl'; export_jsonl(recorder.path,private,include_private_phases=True)
    assert json.loads(private.read_text())['phase']=='Sport on'
    assert json.loads(private.read_text())['note']=='REDACTED_USER_NOTE'
    replay=Replay(target)
    try: assert replay.next()['event']=='Phase'
    finally: replay.close()
    assert recorder.path.read_bytes()==before
