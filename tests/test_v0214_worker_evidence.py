"""Existing constructed fake COM fixture; no physical port or vehicle input."""
from pathlib import Path
import json,time
from test_v0213_session_keep import com,fast_clock,connect,start,finish
from test_session import wait_state
from test_v029_worker import until
from mokka_ecu_lab.library import digest

def test_explicit_passive_verification_disconnect_saves_separate_partial_receipt(com,fast_clock):
    h=com;connect(h);start(h);state=finish(h);w=h.worker;before=len(h.wire);original=Path(state['bundle_path']);sha=digest(original)
    assert state['idle_validation']['state']=='NOT_REQUESTED'
    w.submit('session_idle_verify');check=wait_state(w,lambda d:(d.get('idle_validation') or {}).get('state')=='VERIFYING')
    assert check['idle_validation']['current_send_count']==check['idle_validation']['start_send_count']
    time.sleep(.08);w.submit('disconnect');until(lambda:w.transport is None)
    receipt=next((w.root/'PostExportEvidence').rglob('*.json'));saved=json.loads(receipt.read_text(encoding='utf-8'))
    assert saved['state']=='INTERRUPTED' and saved['idle_requests']==0 and len(h.wire)==before
    assert saved['original_bundle_sha256']==sha and digest(original)==sha

def test_optional_idle_evidence_failure_does_not_undo_verified_export(com,fast_clock,monkeypatch):
    h=com;connect(h);start(h)
    def fail(*_):raise OSError('Constructed passive sidecar storage fault')
    monkeypatch.setattr('mokka_ecu_lab.idle_evidence.SilentIdle',fail)
    state=finish(h)
    assert state['checksums_verified'] and state['connection_state']=='CONNECTED_IDLE' and not state['idle_validation']
    assert h.worker.transport and not h.worker.recorder
