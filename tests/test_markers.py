import json
import zipfile
import pytest
from mokka_ecu_lab.adapter import AcquisitionWorker
from mokka_ecu_lab.logging import list_sessions, export_jsonl
from mokka_ecu_lab.logging.bundle import export_research_bundle
from mokka_ecu_lab.replay import Replay
from test_negative_responses import wait_event, shutdown
from test_ui_freshness import window, connected
from test_discovery import fast_clock


def test_markers_are_local_durable_redacted_and_replayable_without_transport(tmp_path):
    w=AcquisitionWorker(tmp_path)
    try:
        w.submit('record'); session_id=wait_event(w,'recording',bool)
        for event,note in [('Journey Start',''),('Note','SECRET-VIN private note'),('Journey End','')]:
            w.submit('marker',event=event,note=note); result=wait_event(w,'marker')
            assert result['event']==event and w.transport is None
        w.submit('record_stop'); wait_event(w,'recording',lambda s:s is None)
        session=list_sessions(tmp_path)[0]; assert session['requests']==0 and session['errors']==0 and session['ended']
        path=tmp_path/session['raw_path']; original=path.read_bytes()
        records=[json.loads(line) for line in original.splitlines()]
        assert records[1]['note']=='SECRET-VIN private note'
        export_research_bundle(tmp_path,session_id,tmp_path/'bundle.zip')
        with zipfile.ZipFile(tmp_path/'bundle.zip') as z:
            assert all(b'SECRET-VIN' not in z.read(name) for name in z.namelist())
            assert json.loads(z.read('markers.json'))[1]['note_redacted']
        export_jsonl(path,tmp_path/'diagnostic.jsonl',diagnostic_support=True)
        assert b'SECRET-VIN' in (tmp_path/'diagnostic.jsonl').read_bytes()
        w.submit('replay',path=str(path)); wait_event(w,'connection',lambda s:s['ecu']=='Replay paused')
        for expected in records:
            w.submit('step'); marker=wait_event(w,'marker')
            assert marker['event']==expected['event'] and marker['replay'] and w.transport is None
        assert path.read_bytes()==original
    finally: shutdown(w)


def test_markers_require_recording_and_known_event(tmp_path,monkeypatch):
    monkeypatch.setattr(AcquisitionWorker,'start',lambda self:None)
    w=AcquisitionWorker(tmp_path); w.handle('marker',{'event':'Journey Start'})
    assert w.transport is None and not list_sessions(tmp_path)
    w.handle('record',{})
    with pytest.raises(ValueError,match='Unknown marker'): w.handle('marker',{'event':'ATSH6A8'})
    w.close_recording()


@pytest.mark.parametrize('change',[{'timestamp':None},{'note':None}])
def test_malformed_marker_is_rejected_on_replay(tmp_path,change):
    record=dict(record_type='marker',event='Note',timestamp='2026-10-12T00:00:00Z',note='',monotonic_ns=1)
    record.update(change); path=tmp_path/'marker.jsonl'; path.write_text(json.dumps(record)+'\n')
    replay=Replay(path)
    try:
        with pytest.raises(ValueError,match='Invalid marker'): replay.next()
    finally: replay.close()


def test_full_command_queue_does_not_leak_pending_markers(tmp_path,monkeypatch):
    import queue
    monkeypatch.setattr(AcquisitionWorker,'start',lambda self:None)
    w=AcquisitionWorker(tmp_path)
    for _ in range(64): w.submit('select',pids=[])
    with pytest.raises(queue.Full): w.submit('marker',event='Journey Start')
    assert not w.pending_markers


def test_marker_buttons_disabled_offline_and_replay_display(window):
    assert not window.journey_start.isEnabled() and not window.note_button.isEnabled()
    connected(window,mode='REPLAY')
    window.worker.events.put(('marker',dict(timestamp='2026-10-12T00:00:00Z',event='Journey Start',note='',replay=True,context_id='one')))
    window.drain()
    assert window.marker_table.rowCount()==1 and 'REPLAY' in window.marker_table.item(0,2).text()
    assert not window.journey_start.isEnabled()


def test_queued_marker_survives_stop_canceling_an_inflight_request(tmp_path,fast_clock,monkeypatch):
    import threading
    from mokka_ecu_lab.transport import Cancelled
    from mokka_ecu_lab.transport.simulator import Simulator
    receiving=threading.Event(); original=Simulator._exchange
    def exchange(self,command,stop,timeout):
        if command=='010C':
            receiving.set(); stop.wait(2)
            raise Cancelled('Fixture receive canceled',b'7E8 04 41')
        return original(self,command,stop,timeout)
    monkeypatch.setattr(Simulator,'_exchange',exchange)
    w=AcquisitionWorker(tmp_path)
    try:
        w.submit('select',pids=[12]); w.submit('record')
        w.submit('connect',simulation=True,port='COM4',scenario='Normal idle')
        assert receiving.wait(5)
        w.submit('marker',event='Journey End'); w.submit('stop'); w.submit('disconnect')
        wait_event(w,'connection',lambda s:s['adapter']=='Disconnected')
        session=list_sessions(tmp_path)[0]; assert session['ended']
        records=[json.loads(line) for line in (tmp_path/session['raw_path']).read_text().splitlines()]
        assert sum(r.get('event')=='Journey End' for r in records)==1
        assert any(r.get('status')=='CANCELLED' for r in records)
    finally: shutdown(w)
