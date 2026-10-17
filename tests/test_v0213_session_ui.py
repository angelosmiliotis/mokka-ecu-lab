"""Synthetic worker acknowledgements; no serial connection."""
from mokka_ecu_lab.ui.window import MainWindow


def test_exported_connected_idle_can_restart_or_disconnect_without_advanced(tmp_path,qt_app,monkeypatch):
    ui=MainWindow(tmp_path,validation=True);ui.timer.stop();calls=[]
    try:
        monkeypatch.setattr(ui.worker,'submit',lambda *a,**k:calls.append((a,k)))
        ui.adapter_open=True;ui.connected=True;ui.mode='SIMULATED'
        ui.session_panel.acknowledge(dict(state='EXPORTED',active=False,adapter_open=True,connection_state='CONNECTED_IDLE',
            recorded_mode='SIMULATED',mode='SIMULATED',port='SIMULATED',ecu='7E9',reason='Verified export; no polling'))
        assert ui.session_panel.start.isEnabled() and ui.session_panel.disconnect.isEnabled()
        assert not ui.session_panel.connect.isEnabled() and 'CONNECTED IDLE' in ui.session_panel.state.text()
        assert 'CLOSED' not in ui.session_panel.identity.text()
        ui.session_panel.disconnect.click();assert calls[-1][0]==('disconnect',)
        assert not ui.session_panel.advanced.isChecked()
        ui.user_paused=True
        ui.send('session_start',simulation=True,profile=ui.session_panel.profile.currentData())
        assert not ui.user_paused
    finally:monkeypatch.undo();ui.close();qt_app.processEvents()


def test_active_session_exposes_disconnect_and_reconnect_required_blocks_start(tmp_path,qt_app,monkeypatch):
    ui=MainWindow(tmp_path,validation=True);ui.timer.stop();calls=[]
    try:
        monkeypatch.setattr(ui.worker,'submit',lambda *a,**k:calls.append((a,k)))
        ui.adapter_open=True
        ui.session_panel.acknowledge(dict(state='CAPTURING',active=True,adapter_open=True,mode='SIMULATED'))
        assert ui.session_panel.disconnect.isEnabled() and not ui.session_panel.start.isEnabled()
        ui.session_panel.disconnect.click();assert calls[-1][0]==('disconnect',)
        ui.requires_reconnect=True
        ui.session_panel.acknowledge(dict(state='EXPORTED',active=False,adapter_open=False,mode='Disconnected'))
        assert not ui.session_panel.start.isEnabled() and 'CONNECTED IDLE' not in ui.session_panel.state.text()
    finally:monkeypatch.undo();ui.close();qt_app.processEvents()


def test_inflight_capture_ack_does_not_clear_finish_request(tmp_path,qt_app):
    ui=MainWindow(tmp_path,validation=True);ui.timer.stop()
    try:
        ui.pending_actions['session_finish']='constructed-context'
        ui.session_panel.acknowledge(dict(state='CAPTURING',active=True,adapter_open=True,mode='SIMULATED'))
        assert 'session_finish' in ui.pending_actions and 'FINISH REQUESTED' in ui.session_panel.state.text()
        assert not ui.session_panel.finish.isEnabled()
        ui.session_panel.acknowledge(dict(state='FAILED',active=True,adapter_open=True,mode='SIMULATED'))
        assert 'session_finish' in ui.pending_actions
        ui.session_panel.acknowledge(dict(state='FINALIZING',active=True,adapter_open=True,mode='SIMULATED'))
        assert 'session_finish' not in ui.pending_actions and not ui.session_panel.start.isEnabled()
    finally:ui.close();qt_app.processEvents()
