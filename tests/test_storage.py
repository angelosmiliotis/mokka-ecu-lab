import base64
import csv
import json
import time
from mokka_ecu_lab.logging import Recorder, list_sessions, export_csv, export_jsonl, utc_now
from mokka_ecu_lab.replay import Replay

def record(command='010C'):
    return dict(id='tx1',timestamp=utc_now(),monotonic_ns=time.monotonic_ns(),port='COM4',adapter='Private 36627',protocol='6',
        command=command,pid=command[2:] if command.startswith('01') else None,raw_b64=base64.b64encode(b'7E8 04 41 0C 0C 30\r>').decode(),
        raw_text='7E8 04 41 0C 0C 30\r>',status='OK',parsed=[dict(ecu='7E8',data_hex='0C 30')],decoder=['rpm'],verification=['STANDARD_VERIFIED'],latency_ms=10,error='',mode='SIMULATED')

def test_record_export_replay(tmp_path):
    recorder = Recorder(tmp_path,'SIMULATED',{'VIN':'not queried'})
    original = record()
    recorder.append(original,[dict(sensor_id='rpm',ecu='7E8',value=780,unit='rpm',verification='STANDARD_VERIFIED')])
    recorder.close()
    session = list_sessions(tmp_path)[0]; assert session['requests'] == 1 and session['ended']
    export_csv(tmp_path,session['id'],tmp_path/'out.csv')
    with (tmp_path/'out.csv').open(encoding='utf-8-sig') as f:
        reading = list(csv.DictReader(f))[0]
        assert reading['value'] == '780.0'
        assert reading['source_mode'] == 'SIMULATED'
    export_jsonl(recorder.path,tmp_path/'out.jsonl')
    exported = json.loads((tmp_path/'out.jsonl').read_text())
    assert exported['adapter'] == 'REDACTED' and exported['port'] == 'REDACTED'
    assert exported['raw_b64'] == original['raw_b64']
    replay = Replay(tmp_path/'out.jsonl'); assert replay.next()['id'] == 'tx1'; assert replay.next() is None; replay.close()

def test_interrupted_journal_and_identification_redaction(tmp_path):
    recorder = Recorder(tmp_path,'SIMULATED',{})
    recorder.append(record('STI'),[])
    # Mimic abrupt exit without the normal session end (already flushed transaction).
    recorder.file.close(); recorder.db.close()
    with recorder.path.open('a') as f: f.write('{"broken":')
    replay = Replay(recorder.path); assert replay.next(); assert replay.next() is None; assert replay.warnings; replay.close()
    assert list_sessions(tmp_path)[0]['ended'] is None
    export_jsonl(recorder.path,tmp_path/'redacted.jsonl')
    assert json.loads((tmp_path/'redacted.jsonl').read_text())['raw_text'] == 'REDACTED\r>'
    export_jsonl(recorder.path,tmp_path/'support.jsonl',True)
    assert json.loads((tmp_path/'support.jsonl').read_text())['adapter'] == 'Private 36627'
