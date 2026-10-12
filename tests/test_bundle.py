import base64
import csv
import hashlib
import io
import json
import zipfile
from pathlib import Path
import pytest
from mokka_ecu_lab.logging import Recorder, list_sessions, utc_now
from mokka_ecu_lab.logging.bundle import export_research_bundle
from mokka_ecu_lab.discovery import discovery_report
from mokka_ecu_lab.sensors.diesel import STANDARD_DIESEL
from mokka_ecu_lab.transport.simulator import DIESEL_PAYLOADS
from mokka_ecu_lab.adapter import AcquisitionWorker
from test_negative_responses import wait_event, shutdown
from test_discovery import fast_clock


def test_bundle_closed_session_integrity_privacy_intervals_and_original_unchanged(tmp_path):
    recorder=Recorder(tmp_path,'SIMULATED',{'VIN':'SECRET-VIN','owner':'SECRET-OWNER','adapter':'SECRET-ADAPTER'})
    for index,(cmd,raw) in enumerate([('ATI',b'SECRET-ADAPTER SECRET-VIN\r>'),('010C',b'7E8 04 41 0C 0C 52\r>'),('010C',b'7E8 04 41 0C 0C 52\r>')]):
        record=dict(id=str(index),timestamp=utc_now(),monotonic_ns=index*10**9,command=cmd,pid=cmd[2:] if cmd.startswith('01') else None,
                    raw_b64=base64.b64encode(raw).decode(),raw_text=raw.decode(),status='OK',mode='SIMULATED',
                    adapter='SECRET-ADAPTER',port='SECRET-PORT',VIN='SECRET-VIN',owner='SECRET-OWNER',parsed=[{'ecu':'7E8','data_hex':'0C 52'}] if index else [])
        readings=[dict(sensor_id='rpm',ecu='7E8',value=788.5,unit='rpm',timestamp=record['timestamp'],monotonic_ns=record['monotonic_ns'],verification='STANDARD_VERIFIED')] if index else []
        recorder.append(record,readings)
    with pytest.raises(ValueError,match='Stop Recording'): export_research_bundle(tmp_path,recorder.id,tmp_path/'open.zip')
    recorder.close(); original=recorder.path.read_bytes()
    manifest=export_research_bundle(tmp_path,recorder.id,tmp_path/'bundle.zip')
    assert recorder.path.read_bytes()==original and manifest['redacted']
    with zipfile.ZipFile(tmp_path/'bundle.zip') as z:
        assert {'raw-redacted.jsonl','measurements.csv','discovery-report.json','session-summary.json','pid-support.json',
                'ecu-identifiers.json','polling-statistics.json','errors.json','markers.json','manifest.json','SHA256SUMS.txt'}==set(z.namelist())
        for line in z.read('SHA256SUMS.txt').decode().splitlines():
            expected,name=line.split('  '); assert hashlib.sha256(z.read(name)).hexdigest()==expected
        for name in z.namelist():
            assert not any(secret in z.read(name) for secret in [b'SECRET-ADAPTER',b'SECRET-PORT',b'SECRET-VIN',b'SECRET-OWNER'])
        raw=[json.loads(line) for line in z.read('raw-redacted.jsonl').decode().splitlines()]
        assert raw[0]['raw_text']=='REDACTED\r>' and raw[1]['raw_b64']==base64.b64encode(b'7E8 04 41 0C 0C 52\r>').decode()
        stats=json.loads(z.read('polling-statistics.json'))
        assert stats['7E8:0C']['decoded_samples']==2 and stats['7E8:0C']['observed_mean_seconds']==1
        assert stats['request:0C']['requests']==2 and json.loads(z.read('ecu-identifiers.json'))==['7E8']
        summary=json.loads(z.read('session-summary.json')); assert summary['duration_seconds']>=0 and summary['ended']
        assert any('version unavailable' in w for w in manifest['unavailable'])


def test_bundle_uses_stored_session_discovery_not_current_connection(tmp_path,fast_clock):
    w=AcquisitionWorker(tmp_path)
    try:
        w.submit('connect',simulation=True,port='COM4',scenario='Diesel discovery')
        wait_event(w,'connection',lambda s:s['ecu']=='Connected')
        w.submit('record'); session_id=wait_event(w,'recording',bool)
        w.submit('discover',ecu='7E8'); wait_event(w,'discovery',lambda s:'Discovery ended' in s['reason'])
        w.submit('drive_capture',ecu='7E8',pids=[0x8B,0x7A,0x85])
        wait_event(w,'capture',lambda s:s['active'])
        for _ in range(3): wait_event(w,'transaction',lambda s:s[0]['command']=='0185')
        w.submit('disconnect'); wait_event(w,'connection',lambda s:s['adapter']=='Disconnected')
        session=list_sessions(tmp_path)[0]; original=(tmp_path/session['raw_path']).read_bytes()
        w.submit('connect',simulation=True,port='COM4',scenario='Normal idle')
        wait_event(w,'connection',lambda s:s['ecu']=='Connected')
        assert not any(pid in STANDARD_DIESEL for ecu,pid in w.discovery_observations)
        manifest=export_research_bundle(tmp_path,session_id,tmp_path/'bundle.zip')
        assert (tmp_path/session['raw_path']).read_bytes()==original
        assert not any('No completed explicit discovery' in m for m in manifest['unavailable'])
        with zipfile.ZipFile(tmp_path/'bundle.zip') as z:
            report=json.loads(z.read('discovery-report.json'))
            row=next(e for e in report['standard'] if e.get('pid')=='85' and e['ecu']=='7E8')
            assert row['sample']['fields'][2]['value']==80 and row['support']=='SUPPORTED'
            summary=json.loads(z.read('session-summary.json'))
            assert summary['capture_weights']=={'139':4,'122':3,'133':1}
            assert summary['application_versions']==['0.2.1']
            assert json.loads(z.read('polling-statistics.json'))['7E8:85']['decoded_samples']>=4
    finally: shutdown(w)


def test_bundle_rejects_unknown_session_and_nonzip_target(tmp_path):
    with pytest.raises(ValueError,match='Unknown session'): export_research_bundle(tmp_path,'missing',tmp_path/'x.zip')
    recorder=Recorder(tmp_path,'SIMULATED',{}); recorder.close()
    with pytest.raises(ValueError,match='ZIP'): export_research_bundle(tmp_path,recorder.id,recorder.path)
