from mokka_ecu_lab.ui.window import MainWindow
from mokka_ecu_lab.session import CONFLICTS


def test_default_home_has_only_three_primary_actions_and_no_hidden_manual_start(tmp_path,qt_app,monkeypatch):
    ui=MainWindow(tmp_path,validation=True); ui.timer.stop(); calls=[]
    try:
        assert ui.tabs.currentIndex()==7 and not ui.session_panel.advanced.isChecked()
        assert ui.session_panel.connect.text()=='Connect' and not ui.session_panel.start.isEnabled()
        monkeypatch.setattr(ui.worker,'submit',lambda *a,**k:calls.append((a,k)))
        ui.send('record'); ui.send('full_auto',consent=True)
        assert not calls
        ui.session_panel.connect.click()
        assert calls[0][0]==('session_connect',) and calls[0][1]['simulation'] and calls[0][1]['baud']==115200
        assert not ui.session_panel.connect.isEnabled() and not ui.session_panel.start.isEnabled()
        ui.worker.events.put(('session_state',dict(state='CONNECTED',reason='Synthetic ECU acknowledged',active=False,mode='SIMULATED',port='SIMULATED',ecu='7E8',source_kind='SIMULATED')))
        ui.drain(); ui.session_panel.start.click()
        assert calls[-1]==(('session_start',),dict(simulation=True,profile='Correlated DPF / Turbo / SCR'))
        assert not ui.auto_consent.isChecked() and not ui.session_panel.start.isEnabled()
        ui.worker.events.put(('session_state',dict(state='CAPTURING',reason='Worker acknowledged',active=True,session_id='synthetic',mode='SIMULATED',ecu='7E8',recording_active=True)))
        ui.drain(); count=len(calls)
        for action in CONFLICTS-{'disconnect','stop'}: ui.send(action)
        assert len(calls)==count and not ui.session_panel.advanced.isEnabled()
        assert not ui.source.isEnabled() and not ui.port.isEnabled()
        ui.session_panel.finish.click(); assert calls[-1][0]==('session_finish',)
    finally:
        monkeypatch.undo(); ui.close(); qt_app.processEvents()


def test_offline_live_export_is_not_mislabeled_simulation(tmp_path,qt_app):
    ui=MainWindow(tmp_path,validation=True); ui.timer.stop()
    try:
        ui.session_panel.acknowledge(dict(state='EXPORTED',reason='Offline verified',active=False,recorded_mode='LIVE · hardware unverified',recorded_ecus=['7E8'],mode='Disconnected'))
        assert 'LIVE' in ui.session_panel.identity.text() and 'synthetic data' not in ui.session_panel.identity.text()
        assert ui.worker.transport is None
    finally: ui.close(); qt_app.processEvents()


def test_validation_refuses_existing_data_before_starting_gui_or_worker(tmp_path):
    import subprocess,sys
    sentinel=tmp_path/'existing-private-data.txt'; sentinel.write_text('constructed sentinel')
    result=subprocess.run([sys.executable,'-m','mokka_ecu_lab','--session-smoke-test','--data-dir',str(tmp_path)],capture_output=True,timeout=10)
    assert result.returncode==2 and b'fresh --data-dir' in result.stderr
    assert sentinel.read_text()=='constructed sentinel' and not (tmp_path/'sessions.sqlite3').exists()
