from copy import deepcopy
from test_ui_freshness import window,connected
from test_auto_capture import proof_receipt
from PySide6.QtCore import Qt


def test_one_deliberate_preset_consent_no_individual_pid_clicks(window,monkeypatch):
    calls=[]
    with monkeypatch.context() as patch:
        patch.setattr(window.worker,'submit',lambda *a,**k:calls.append((a,k)))
        window.tabs.setCurrentIndex(6); window.auto_preset.setCurrentIndex(1)
        assert not calls and not window.auto_start.isEnabled()
        window.auto_consent.setChecked(True); assert window.auto_start.isEnabled()
        window.auto_start.click()
        assert len(calls)==1 and calls[0][0]==('full_auto',)
        options=calls[0][1]; assert options['consent'] and options['simulation'] and options['preset']=='DPF Research Priority'
        assert 'pids' not in options and 'raw_pids' not in options
        assert not window.auto_start.isEnabled() and not window.capture_active
        assert 'Awaiting worker' in window.auto_status.text()


def test_preflight_does_not_claim_proof_from_pending_button(window):
    connected(window,mode='SIMULATED')
    receipt=proof_receipt(); receipt.data['context_id']=window.context_id
    receipt.data['state']='WAITING_RAW'
    window.worker.events.put(('auto_capture',receipt.snapshot())); window.drain()
    assert 'stored six-byte positives 0 / 2' in window.auto_dpf.text()
    assert 'worker scheduled NO' in window.auto_dpf.text()
    window.worker.events.put(('capture',dict(context_id=window.context_id,active=True,weights={0x7A:1},raw_pids=[0x7A],ecu='7E8',reason='test')))
    window.worker.events.put(('acquisition',dict(polling=True,reason='test',requires_reconnect=False)))
    receipt.data['dpf'].update(worker_scheduled=True,recorded_positive_six_byte_frames=2,state='READY')
    receipt.data['state']='READY'; window.worker.events.put(('auto_capture',receipt.snapshot())); window.drain()
    assert 'stored six-byte positives 2 / 2' in window.auto_dpf.text()
    assert 'worker scheduled YES' in window.auto_dpf.text()


def test_user_phase_sends_marker_only_and_navigation_sends_nothing(window,monkeypatch):
    connected(window,mode='SIMULATED'); window.recording_id='synthetic'; window.update_capture(); calls=[]
    with monkeypatch.context() as patch:
        patch.setattr(window.worker,'submit',lambda *a,**k:calls.append((a,k)))
        window.journey_phase.setCurrentText('Sport on'); window.journey_uncertainty.setValue(60)
        window.capture_sections.setCurrentIndex(2); assert not calls
        window.phase_note_button.click()
        assert calls==[(('marker',),dict(event='Phase',phase='Sport on',uncertainty_seconds=60))]


def test_rejected_auto_action_releases_pending_controls(window,monkeypatch):
    calls=[]
    with monkeypatch.context() as patch:
        patch.setattr(window.worker,'submit',lambda *a,**k:calls.append((a,k)))
        window.auto_consent.setChecked(True); window.auto_start.click()
        window.worker.events.put(('auto_rejected',dict(context_id=window.context_id,reason='Explicit reconnect required')))
        window.drain()
        assert 'full_auto' not in window.pending_actions and 'reconnect' in window.auto_status.text()


def test_offline_utc_labels_and_annotation_edit_invalidates_result(window,monkeypatch):
    import mokka_ecu_lab.ui.phases as module
    from test_phases import synthetic
    from mokka_ecu_lab.analysis.phases import compare_phases
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    data,anchor=synthetic()
    monkeypatch.setattr(module,'load_phase_data',lambda _:data)
    dialog=module.PhaseDialog(window.root/'constructed.zip',window)
    try:
        for _ in range(100):
            QTest.qWait(10)
            if dialog.data: break
        assert dialog.data and window.worker.transport is None
        dialog.report=compare_phases(data,0,anchor); dialog.show_report()
        chart=dialog.charts.widget(0).chart()
        axis=chart.axes(Qt.Orientation.Horizontal)[0]
        assert axis.categoriesLabels()[0]=='00:00:00.500 UTC'
        assert dialog.export_button.isEnabled()
        dialog.timestamp.setText('2000-01-01T00:00:25+00:00')
        assert dialog.report is None and not dialog.export_button.isEnabled()
    finally: dialog.close(); QApplication.processEvents()
