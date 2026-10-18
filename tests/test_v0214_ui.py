"""Constructed Qt projections; no actual owner upgrade or network request."""
from mokka_ecu_lab.ui.window import MainWindow
from mokka_ecu_lab import __version__

def test_versions_always_names_running_version_current_and_stable_target(tmp_path,qt_app):
    ui=MainWindow(tmp_path,validation=True);ui.timer.stop()
    try:
        text=ui.versions_panel.identity.text()
        assert __version__ in text and 'CURRENT' in text and 'Rollback' in text and 'GitHub latest known' in text and 'Shortcut target' in text
        assert ui.worker.transport is None
    finally:ui.close();qt_app.processEvents()

def test_upgrade_approval_cannot_close_or_start_helper_during_acquisition(tmp_path,qt_app,monkeypatch):
    ui=MainWindow(tmp_path,validation=True);ui.timer.stop();calls=[]
    try:
        monkeypatch.setattr('mokka_ecu_lab.ui.versions.subprocess.Popen',lambda *a,**k:calls.append((a,k)))
        ui.adapter_open=True;ui.versions_panel.begin_approved_upgrade({'CONSTRUCTED':'not-used'})
        assert not calls and 'Finish' in ui.versions_panel.status.text()
    finally:ui.adapter_open=False;monkeypatch.undo();ui.close();qt_app.processEvents()

def test_post_export_idle_projection_has_no_implicit_verification(tmp_path,qt_app):
    ui=MainWindow(tmp_path,validation=True);ui.timer.stop()
    try:
        ui.adapter_open=True
        ui.session_panel.acknowledge(dict(state='EXPORTED',mode='SIMULATED',active=False,adapter_open=True,connection_state='CONNECTED_IDLE',idle_validation=dict(state='NOT_REQUESTED',start_send_count=7,current_send_count=7,idle_requests=0)))
        assert ui.session_panel.idle_verify.isEnabled() and '7 → 7' in ui.session_panel.idle_status.text()
        assert ui.worker.transport is None and not ui.worker.commands.qsize()
    finally:ui.adapter_open=False;ui.close();qt_app.processEvents()
