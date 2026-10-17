"""v0.2.6 state accuracy: synthetic events and the existing simulator only."""
from PySide6.QtCore import Qt
from test_ui_freshness import window, connected, transaction, cell
from test_ui_raw_capture import prepared
from mokka_ecu_lab.ui.presentation import StepState
from mokka_ecu_lab.logging import Recorder


def capture_cell(ui, pid, column=3):
    row=next(r for r in range(ui.capture_table.rowCount()) if ui.capture_table.item(r,0).data(Qt.ItemDataRole.UserRole)==pid)
    return ui.capture_table.item(row,column).text()


def acknowledge(ui, kind, **value):
    ui.worker.events.put((kind,dict(context_id=ui.context_id,**value))); ui.drain()


def test_current_step_is_not_completion_and_navigation_emits_nothing(window,monkeypatch):
    calls=[]
    with monkeypatch.context() as patch:
        patch.setattr(window.worker,'submit',lambda *a,**k:calls.append((a,k)))
        assert window.capture_stepper.states[0]==StepState.CURRENT
        for step in range(7): window.capture_stepper.buttons[step].click()
        assert not calls and not window.recording_id
        assert window.capture_stepper.states[1]!=StepState.COMPLETED
        assert window.capture_stepper.buttons[0].property('workflowState')=='CURRENT'
        assert 'Navigation only' in window.capture_stepper.buttons[1].accessibleName()
        assert not window.capture_finish.isEnabled()


def test_record_before_connect_waits_for_worker_confirmation(window,monkeypatch):
    calls=[]
    with monkeypatch.context() as patch:
        patch.setattr(window.worker,'submit',lambda *a,**k:calls.append((a,k)))
        window.capture_record.click()
        assert calls==[(('record',),{})]
        assert window.recording_id is None and not window.record_button.isEnabled()
        assert 'awaiting worker start' in window.capture_recording_note.text()
        assert window.capture_stepper.states[1] not in (StepState.COMPLETED,StepState.IN_PROGRESS)
        window.worker.events.put(('recording','synthetic-session')); window.drain()
        assert not window.connected and window.recording_id=='synthetic-session'
        assert window.capture_stepper.states[1]==StepState.IN_PROGRESS
        assert window.connect_button.isEnabled() and window.capture_finish.isEnabled()
        assert 'SIMULATION — synthetic data' in window.capture_identity.text()
        assert window.next_capture_action=='connect'


def test_recording_off_cannot_complete_record_step_after_finish(window):
    connected(window,mode='SIMULATED')
    recorder=Recorder(window.root,'SIMULATED',{})
    window.worker.events.put(('recording',recorder.id)); window.drain()
    recorder.close()
    window.worker.events.put(('recording',None))
    acknowledge(window,'acquisition',polling=False,reason='Stopped',requires_reconnect=False)
    assert window.capture_stepper.states[1]!=StepState.COMPLETED
    assert window.capture_stepper.states[5]==StepState.COMPLETED
    assert window.capture_stepper.states[6]==StepState.CURRENT
    assert 'Adapter remains connected' in window.capture_next_help.text()
    assert window.capture_bundle.isEnabled() and not window.capture_finish.isEnabled()


def test_capture_start_waits_for_ack_and_configuration_only_sends_when_pressed(window,monkeypatch):
    prepared(window); calls=[]
    with monkeypatch.context() as patch:
        patch.setattr(window.worker,'submit',lambda *a,**k:calls.append((a,k)))
        window.prepare_capture()
        assert not calls and window.raw_selected()==[] and 0x83 not in window.capture_selected()
        window.capture_start.click()
        assert len(calls)==1 and calls[0][0]==('drive_capture',)
        assert not window.capture_active and window.capture_stepper.states[4]!=StepState.IN_PROGRESS
        assert not window.capture_start.isEnabled()
        acknowledge(window,'capture',active=True,weights={12:2},raw_pids=[],ecu='7E8',reason='Drive Capture active')
        assert window.capture_stepper.states[4]==StepState.IN_PROGRESS
        assert window.capture_finish.isEnabled() and 'not recording' in window.capture_finish.text()
        assert 'Monitoring only' in window.capture_next_help.text()


def test_fresh_basic_polling_is_current_in_both_views_and_recording_is_separate(window):
    connected(window,mode='SIMULATED'); transaction(window,mode='SIMULATED')
    assert cell(window,12,3)=='Valid'
    assert 'Current sample · Basic polling' in capture_cell(window,12)
    assert 'SIMULATED · synthetic' in capture_cell(window,12)
    assert 'Drive Capture' not in capture_cell(window,12)
    assert 'Current sample · Basic polling' in window.sensor_cards[0].state.text()
    assert 'Not recorded' in window.sensor_cards[0].evidence.text()
    assert 'Not recorded in current session' in window.sensor_cards[0].toolTip()
    window.worker.events.put(('recording','synthetic-session')); window.drain()
    assert 'Not recorded in current session' in window.sensor_cards[0].toolTip()
    transaction(window,mode='SIMULATED')
    assert 'Recorded in current session' in window.sensor_cards[0].toolTip()
    assert not window.capture_active


def test_stopped_disconnected_failed_and_deselected_values_are_stale(window,monkeypatch):
    connected(window); transaction(window)
    with monkeypatch.context() as patch:
        patch.setattr(window.worker,'submit',lambda *a,**k:None)
        window.send('stop'); window.drain()
        assert 'Stale' in capture_cell(window,12) and cell(window,12,3).startswith('Stale')
        connected(window,context='again'); transaction(window,context='again')
        acknowledge(window,'acquisition',polling=False,reason='Failed',requires_reconnect=True)
        assert 'Stale' in capture_cell(window,12) and not window.start_button.isEnabled()
        acknowledge(window,'connection',adapter='Disconnected',ecu='Unavailable',mode='LIVE · hardware unverified',protocol='6')
        assert 'Stale' in capture_cell(window,12) and not window.disconnect_button.isEnabled()
        connected(window,context='third'); transaction(window,context='third')
        item=next(window.sensor_list.item(i) for i in range(window.sensor_list.count()) if window.sensor_list.item(i).data(Qt.ItemDataRole.UserRole)==12)
        item.setCheckState(Qt.CheckState.Unchecked); window.drain()
        assert 'Stale' in capture_cell(window,12)


def test_discovery_freshness_and_ended_discovery_do_not_claim_capture(window):
    connected(window,mode='SIMULATED')
    acknowledge(window,'acquisition',polling=False,reason='Discovery',requires_reconnect=False)
    acknowledge(window,'discovery',active=True,prepared=False,target='7E8',reason='Discovering')
    window.support['7E8'].add(0x85); window.support_pages['7E8'].update({32,64,96,128})
    sample=dict(ecu='7E8',pid=0x85,fields=[dict(sensor_id='scr_tank_level',name='Tank level',state='AVAILABLE',value=50,unit='%')],
                timestamp='synthetic',monotonic_ns=109*10**9,source_kind='SIMULATED',context_id=window.context_id,acquisition_mode='Discovery')
    window.discovery_observations['7E8',0x85]=sample; window.update_capture()
    assert 'Current sample · Discovery' in capture_cell(window,0x85)
    acknowledge(window,'discovery',active=False,prepared=True,target='7E8',reason='Discovery ended')
    assert window.capture_stepper.states[2]==StepState.COMPLETED
    assert 'Stale' in capture_cell(window,0x85)
    assert not window.capture_active


def test_ecu_rejection_stales_both_views_for_only_that_ecu(window):
    connected(window)
    transaction(window); transaction(window,ecu='7E9')
    transaction(window,pid=13,ecu='7E9',rejection=True)
    assert 'Current sample' in capture_cell(window,12)
    window.ecu.setCurrentIndex(window.ecu.findData('7E9')); window.drain()
    assert 'Stale' in capture_cell(window,12) and cell(window,12,3).startswith('Stale')


def test_source_change_and_late_events_cannot_carry_simulation_to_live(window):
    connected(window,mode='SIMULATED'); transaction(window,mode='SIMULATED')
    acknowledge(window,'connection',adapter='Disconnected',ecu='Unavailable',mode='SIMULATED',protocol='6')
    window.source.setCurrentIndex(1)
    assert 'LIVE — Bluetooth / Serial ECU' in window.status_indicators['Source'].text()
    assert not window.readings and not window.support and not window.discovery_prepared
    transaction(window,mode='SIMULATED')
    assert not window.readings  # Discard queued old-context data before reconnect too.
    connected(window,context='live-new')
    transaction(window,mode='SIMULATED',context='one')
    assert not window.readings and capture_cell(window,12,1)=='—'
    transaction(window,context='live-new')
    assert 'LIVE' in capture_cell(window,12) and 'SIMULATED' not in capture_cell(window,12)


def test_serial_open_and_no_ecu_response_do_not_complete_connection(window,monkeypatch):
    window.source.setCurrentIndex(1)
    with monkeypatch.context() as patch:
        patch.setattr(window.worker,'submit',lambda *a,**k:None)
        window.connect_adapter()
        acknowledge(window,'context',id='new',mode='LIVE · hardware unverified')
        acknowledge(window,'connection',adapter='Initializing',ecu='Not yet verified',mode='LIVE · hardware unverified',protocol='Unknown')
        assert not window.connected and window.disconnect_button.isEnabled()
        assert not window.source.isEnabled() and not window.discovery_start.isEnabled()
        assert window.capture_stepper.states[0]!=StepState.COMPLETED
        acknowledge(window,'connection',adapter='fixture',ecu='No verified ECU response',mode='LIVE · hardware unverified',protocol='6')
        assert not window.connected and window.disconnect_button.isEnabled()
        assert 'No current ECU confirmed' in window.status_indicators['ECU'].text()
        assert 'Adapter connected / no ECU response' in window.status_indicators['Connection'].text()
        assert window.next_capture_action=='reconnect' and window.capture_next.isEnabled()


def test_replay_is_offline_in_both_views_and_record_controls_are_disabled(window):
    connected(window,mode='REPLAY',context='replay')
    acknowledge(window,'connection',adapter='Offline',ecu='Replay paused',mode='REPLAY',protocol='Recorded')
    transaction(window,mode='SIMULATED',replay=True,context='replay',when=1)
    assert cell(window,12,3)=='Recorded (offline)'
    assert 'Recorded (offline)' in capture_cell(window,12) and 'REPLAY · SIMULATED' in capture_cell(window,12)
    assert not window.record_button.isEnabled() and not window.capture_record.isEnabled()
    assert not window.capture_start.isEnabled() and not window.capture_finish.isEnabled()


def test_current_ecu_and_scenario_support_not_historical_claims(window):
    prepared(window); window.support['7E8'].discard(0x8B)
    window.update_capture()
    assert 'selected simulation scenario' in capture_cell(window,0x8B)
    assert capture_cell(window,0x8B,1)=='—'
    window.prepare_capture()
    assert 0x8B not in window.capture_selected() and not window.raw_selected()
    connected(window,context='new-live')
    assert not window.capture_preset.isEnabled() and window.capture_stepper.states[2]!=StepState.COMPLETED


def test_simple_and_technical_views_keep_details_without_requests(window,monkeypatch):
    prepared(window); window.prepare_capture(); calls=[]
    with monkeypatch.context() as patch:
        patch.setattr(window.worker,'submit',lambda *a,**k:calls.append((a,k)))
        assert all(window.capture_table.isColumnHidden(c) for c in (4,5,6))
        assert window.capture_evidence_tabs.isHidden()
        window.capture_technical.setChecked(True)
        assert all(not window.capture_table.isColumnHidden(c) for c in (4,5,6))
        assert not window.capture_evidence_tabs.isHidden()
        assert 'weight' in window.capture_list.item(0).text()
        for _ in range(5): window.update_capture(); window.refresh_presentation(); window.show_capture_step(4)
        assert not calls


def test_bundle_export_waits_for_closed_session_and_success_receipt(window,tmp_path,monkeypatch):
    connected(window,mode='SIMULATED')
    recorder=Recorder(window.root,'SIMULATED',{})
    window.worker.events.put(('recording',recorder.id)); window.drain()
    assert not window.capture_bundle.isEnabled() and window.capture_finish.isEnabled()
    recorder.close(); window.worker.events.put(('recording',None))
    acknowledge(window,'acquisition',polling=False,reason='Stopped',requires_reconnect=False)
    assert window.capture_stepper.states[6]==StepState.CURRENT
    destination=tmp_path/'synthetic-export.zip'
    with monkeypatch.context() as patch:
        patch.setattr('mokka_ecu_lab.ui.window.QFileDialog.getSaveFileName',lambda *a,**k:(str(destination),'ZIP'))
        window.bundle_export(latest=True)
    assert destination.exists() and window.capture_stepper.states[6]==StepState.COMPLETED
    assert window.bundle_destination==str(destination.resolve())
    assert str(destination.resolve()) in window.capture_next_help.text().replace('\u200b','')
    assert str(destination.resolve()) in window.capture_next_help.toolTip()
    assert window.connected and not window.polling_active


def test_failed_export_does_not_complete_export_step(window,tmp_path,monkeypatch):
    recorder=Recorder(window.root,'SIMULATED',{}); recorder.close()
    window.last_recording_id=recorder.id; window.refresh_sessions(); window.update_capture()
    with monkeypatch.context() as patch:
        patch.setattr('mokka_ecu_lab.ui.window.QFileDialog.getSaveFileName',lambda *a,**k:(str(tmp_path/'failed.zip'),'ZIP'))
        def fail(*args): raise OSError('Synthetic export failure')
        patch.setattr('mokka_ecu_lab.ui.window.export_research_bundle',fail)
        window.bundle_export(latest=True)
    assert window.exported_session_id is None and window.capture_stepper.states[6]!=StepState.COMPLETED


def test_replay_provenance_survives_preparing_a_different_connection_source(window):
    connected(window,mode='REPLAY',context='replay')
    acknowledge(window,'connection',adapter='Offline',ecu='Replay paused',mode='REPLAY',protocol='Recorded')
    transaction(window,mode='SIMULATED',replay=True,context='replay',when=1)
    window.source.setCurrentIndex(1)
    assert window.mode=='REPLAY' and 'REPLAY' in window.status_indicators['Source'].text()
    assert 'Recorded (offline)' in capture_cell(window,12)
    assert not window.record_button.isEnabled()


def test_future_timestamp_unknown_provenance_and_old_sample_are_not_current(window):
    connected(window); transaction(window,when=111.)
    assert 'Stale' in capture_cell(window,12) and cell(window,12,3).startswith('Stale')
    transaction(window,when=109.)
    window.readings['7E8',12]['source_kind']='UNKNOWN'
    window.discovery_observations['7E8',12]['source_kind']='UNKNOWN'; window.drain()
    assert 'Stale' in capture_cell(window,12) and cell(window,12,3).startswith('Stale')
    transaction(window,when=50.)
    assert 'Stale' in capture_cell(window,12)


def test_reconnect_prompt_is_explicit_and_stop_cancellation_is_not_a_monitoring_failure(window,monkeypatch):
    prepared(window); window.prepare_capture()
    acknowledge(window,'capture',active=True,weights={12:2},raw_pids=[],ecu='7E8',reason='Active')
    record=dict(context_id=window.context_id,timestamp='synthetic',command='010C',pid='0C',status='CANCELLED',latency_ms=1,
                parsed=[],decoder=[],error='Explicit stop cancellation')
    window.worker.events.put(('transaction',(record,[]))); window.drain()
    assert window.error_count==1 and window.capture_monitor_errors==0
    acknowledge(window,'capture',active=False,weights={},raw_pids=[],ecu='7E8',reason='Failed')
    acknowledge(window,'acquisition',polling=False,reason='Failed',requires_reconnect=True)
    assert window.next_capture_action=='reconnect' and not window.start_button.isEnabled()
    calls=[]
    with monkeypatch.context() as patch:
        patch.setattr(window.worker,'submit',lambda *a,**k:calls.append((a,k)))
        window.capture_next.click()
        assert calls==[(('disconnect',),{})]  # Never a hidden disconnect/connect chain.
