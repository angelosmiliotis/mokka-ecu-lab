"""Constructed standard-session lifecycle, persistence and recovery fixtures only."""
import hashlib
import json
import time
import pytest
from mokka_ecu_lab.adapter import AcquisitionWorker
from mokka_ecu_lab.logging import list_sessions, Recorder, connect_database
from mokka_ecu_lab.research.evidence import read_bundle
from mokka_ecu_lab.session import CONFLICTS, recover_interrupted_session
from test_discovery import fast_clock
from test_negative_responses import shutdown

EXPECTED={4,5,11,12,13,15,16,66,70,0x7A,0x83,0x85,0x88}


def wait_state(worker,predicate,timeout=15):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        try: kind,data=worker.events.get(timeout=.1)
        except Exception: continue
        if kind=='session_state' and predicate(data): return data
    raise AssertionError(worker.session.snapshot())


def connect(worker,scenario='Diesel thirteen sensors'):
    worker.submit('session_connect',simulation=True,scenario=scenario,port='',baud=115200)
    return wait_state(worker,lambda d:d['state'] in {'CONNECTED','FAILED'})


def start(worker):
    worker.submit('session_start',simulation=True)
    return wait_state(worker,lambda d:d['state'] in {'CAPTURING','PARTIAL','FAILED'})


def test_three_actions_one_journal_all_thirteen_fields_and_automatic_export(tmp_path,fast_clock):
    worker=AcquisitionWorker(tmp_path)
    try:
        assert connect(worker)['state']=='CONNECTED'
        assert not list_sessions(tmp_path) and not worker.polling
        initial=start(worker); sid=initial['session_id']; assert sid
        # The worker also rejects directly queued manual actions, not just disabled UI.
        before=dict(worker.capture_weights)
        for action in CONFLICTS-{'disconnect','stop'}: assert worker.submit(action) is False
        worker.submit('session_start',simulation=True)
        ready=wait_state(worker,lambda d: d.get('receipt') and d['receipt']['dpf']['state']=='READY' and
            all(s.get('positive_samples',0)>=2 for s in d['receipt']['observed'].values()) and len(d['receipt']['observed'])==13)
        assert set(worker.capture_weights)==EXPECTED and worker.capture_weights==before
        assert worker.capture_weights[0x7A]==4 and worker.capture_weights[0x0C]==3
        assert worker.capture_raw_pids=={0x7A}
        assert ready['session_id']==sid and len(list_sessions(tmp_path))==1
        receipt=ready['receipt']; assert receipt['dpf']['recorded_positive_six_byte_frames']>=2
        assert receipt['pre_connect_initialization_recorded'] is False
        assert all(v['recorded'] for v in receipt['bitmap_evidence'].values())
        assert all(not s.get('fields') for p,s in receipt['observed'].items() if p=='7A')
        assert len(receipt['observed']['85']['fields'])==4
        assert len(receipt['observed']['88']['fields'])>5
        assert len(receipt['observed']['83']['fields'])==2  # Other NOx slots absent, never fabricated zero.
        worker.submit('session_finish'); worker.submit('session_finish')
        final=wait_state(worker,lambda d:d['state']=='EXPORTED')
        assert worker.transport and not worker.recorder and not worker.polling
        assert final['connection_state']=='CONNECTED_IDLE' and not final['disconnected']
        assert final['checksums_verified'] and final['session_id']==sid
        _,members=read_bundle(final['bundle_path']); stored=json.loads(members['acquisition-receipt.json'])
        assert stored['closed_at'] and stored['dpf_proof_met_before_close']
        records=[json.loads(l) for l in members['raw-redacted.jsonl'].splitlines()]
        commands=[r['command'] for r in records if r.get('record_type')=='transaction']
        assert commands[:2]==['ATDPN','0100'] and 'ATI' not in commands
        assert not any(c in commands for c in ('015C','018B','0178','0179','0173'))
        assert len(list_sessions(tmp_path))==1 and list_sessions(tmp_path)[0]['ended']
        assert len(list((tmp_path/'Reports').rglob('original-research.zip')))==1
        journal=tmp_path/list_sessions(tmp_path)[0]['raw_path']
        assert hashlib.sha256(journal.read_bytes()).hexdigest()==final['original_journal_sha256']
        assert any(e['state']=='DISCOVERING' for e in final['transitions'])
        assert all(state in [e['state'] for e in final['transitions']] for state in ('RECORDING_SETUP','CONFIGURING','CAPTURING','FINALIZING','EXPORTED'))
    finally: shutdown(worker)


def test_export_failure_preserves_journal_and_explicit_offline_retry(tmp_path,fast_clock,monkeypatch):
    import mokka_ecu_lab.adapter as module
    worker=AcquisitionWorker(tmp_path)
    try:
        connect(worker); initial=start(worker); sid=initial['session_id']
        original=module.export_closed_session
        monkeypatch.setattr(module,'export_closed_session',lambda *_:(_ for _ in ()).throw(OSError('Synthetic unwritable destination')))
        worker.submit('session_finish'); failed=wait_state(worker,lambda d:d['state']=='FAILED' and d.get('retry_export'))
        assert not worker.transport and not worker.recorder and not failed['active']
        session=list_sessions(tmp_path)[0]; journal=tmp_path/session['raw_path']; digest=hashlib.sha256(journal.read_bytes()).hexdigest()
        assert session['ended'] and session['id']==sid
        monkeypatch.setattr(module,'export_closed_session',original)
        worker.submit('session_export_retry',session_id=sid)
        exported=wait_state(worker,lambda d:d['state']=='EXPORTED')
        assert exported['checksums_verified'] and hashlib.sha256(journal.read_bytes()).hexdigest()==digest
        assert not worker.transport and len(list_sessions(tmp_path))==1
    finally: shutdown(worker)


@pytest.mark.parametrize('scenario',['Normal idle','Diesel truncated'])
def test_partial_dpf_keeps_other_eligible_sensors_and_can_finish(tmp_path,fast_clock,scenario):
    worker=AcquisitionWorker(tmp_path)
    try:
        connect(worker,scenario); state=start(worker)
        assert state['state'] in {'PARTIAL','FAILED'} and state['receipt']['dpf']['recorded_positive_six_byte_frames']==0
        worker.submit('session_finish'); final=wait_state(worker,lambda d:d['state']=='EXPORTED')
        assert not final['receipt']['dpf_proof_met_before_close'] and final['checksums_verified']
    finally: shutdown(worker)


def test_multiple_ecus_never_auto_select_and_connect_starts_no_journal(tmp_path,fast_clock):
    worker=AcquisitionWorker(tmp_path)
    try:
        result=connect(worker,'Multiple ECUs')
        assert result['state']=='FAILED' and not worker.transport and not list_sessions(tmp_path)
        worker.submit('session_start',simulation=True)
        time.sleep(.1)
        assert not worker.recorder
    finally: shutdown(worker)


def test_missing_windows_port_connect_failure_has_no_pairing_or_recording(tmp_path,monkeypatch):
    monkeypatch.setattr('serial.tools.list_ports.comports',lambda:[])
    worker=AcquisitionWorker(tmp_path)
    try:
        worker.submit('session_connect',simulation=False,port='COM99',baud=115200)
        result=wait_state(worker,lambda d:d['state']=='FAILED')
        assert 'enumerated by Windows' in result['reason'] and not worker.transport and not list_sessions(tmp_path)
    finally: shutdown(worker)


def test_shutdown_finalizes_and_exports_active_standard_session(tmp_path,fast_clock):
    worker=AcquisitionWorker(tmp_path)
    connect(worker); start(worker); shutdown(worker)
    assert list_sessions(tmp_path)[0]['ended'] and len(list((tmp_path/'Reports').rglob('original-research.zip')))==1


def test_offline_interrupted_recovery_preserves_tail_and_repairs_missing_rows(tmp_path):
    import base64
    recorder=Recorder(tmp_path,'SIMULATED',{})
    sid=recorder.id
    r=dict(id='constructed-row',record_type='transaction',session_id=sid,pid='05',command='0105',
        timestamp='2000-01-01T00:00:01+00:00',monotonic_ns=1000000000,mode='SIMULATED',status='OK',raw_b64=base64.b64encode(b'7E8 03 41 05 60\r>').decode())
    recorder.file.write(json.dumps(r)+'\n{"truncated":'); recorder.file.close(); recorder.db.close()
    digest=hashlib.sha256(recorder.path.read_bytes()).hexdigest()
    recover_interrupted_session(tmp_path,sid)
    session=list_sessions(tmp_path)[0]; assert session['ended']
    metadata=json.loads(session['metadata']); assert metadata['recovery']['truncated_tail_preserved'] and metadata['recovery']['repaired_missing_rows']==1
    db=connect_database(tmp_path); assert db.execute('SELECT value FROM readings').fetchone()[0]==56; db.close()
    assert hashlib.sha256(recorder.path.read_bytes()).hexdigest()==digest
