"""Qt interaction with invented offline evidence only; no hardware requests."""
from mokka_ecu_lab.analysis.explorer import analyze_explorer
from test_v0215_explorer import bundle
from test_ui_freshness import window


def test_explorer_navigation_filter_fields_and_details_never_submit(window,tmp_path,monkeypatch):
    panel=window.evidence_panel;calls=[]
    monkeypatch.setattr(window.worker,'submit',lambda *a,**k:calls.append((a,k)))
    path=bundle(tmp_path/'constructed.zip');panel.loaded(analyze_explorer([path]),[path])
    window.sidebar.activate(13)
    assert window.tabs.currentIndex()==13 and 'physical sensor count UNKNOWN' in panel.counts.text()
    panel.search.setText('nox');panel.filter.setCurrentText('Unavailable subfields')
    assert panel.tree.topLevelItemCount()==1 and panel.tree.topLevelItem(0).childCount()==4
    panel.tree.setCurrentItem(panel.tree.topLevelItem(0).child(1))
    assert 'UNSUPPORTED_FIELD' in panel.detail.toPlainText() and 'UNVERIFIED' in panel.detail.toPlainText()
    assert not calls and window.worker.transport is None
    monkeypatch.undo()


def test_passed_result_displays_separate_disconnected_connection(window):
    panel=window.session_panel
    window.connection_detail=dict(stage='DISCONNECTED',reason='Explicit Disconnect')
    panel.acknowledge(dict(state='EXPORTED',adapter_open=False,mode='SIMULATED',idle_validation=dict(state='VERIFIED',verification_elapsed_seconds=60.42,start_send_count=3,current_send_count=3,idle_requests=0,reason='Bounded passive observation',receipt_path='C:/synthetic/nonexistent.json')))
    assert 'PASSED · 60.42s' in panel.idle_status.text() and '/60' not in panel.idle_status.text()
    assert 'DISCONNECTED' in panel.idle_connection.text() and 'Explicit Disconnect' in panel.idle_connection.text()
    assert panel.idle_open.isEnabled() and panel.idle_folder.isEnabled() and panel.idle_path.isReadOnly()
    assert not panel.idle_verify.isEnabled() and window.worker.transport is None


def test_receipt_buttons_validate_checksum_before_opening(window,tmp_path,monkeypatch):
    from pathlib import Path
    from test_v0215_idle_receipt import completed
    idle=completed(tmp_path);path=Path(idle.save(tmp_path/'ιδιωτικά'));panel=window.session_panel;calls=[]
    monkeypatch.setattr('mokka_ecu_lab.ui.session.QDesktopServices.openUrl',lambda url:calls.append(url.toLocalFile()))
    panel.idle_path.setText(str(path));panel.open_idle_report(False);panel.open_idle_report(True)
    assert calls==[str(path).replace('\\','/'),str(path.parent).replace('\\','/')]
    idle.bundle.write_bytes(b'synthetic changed source');panel.open_idle_report(False)
    assert len(calls)==2 and 'verification failed' in panel.idle_status.text()


def test_history_opens_only_validated_selected_session_receipt(window,tmp_path,monkeypatch,qt_app):
    import time
    from test_v0215_idle_receipt import completed
    panel=window.history_panel;idle=completed(tmp_path);path=idle.save(window.root/'PostExportEvidence'/'SYNTHETIC');calls=[]
    monkeypatch.setattr(panel,'one',lambda:dict(session_id='SYNTHETIC'))
    monkeypatch.setattr('mokka_ecu_lab.ui.library.QInputDialog.getItem',lambda *a,**k:(a[3][0],True))
    monkeypatch.setattr('mokka_ecu_lab.ui.library.QDesktopServices.openUrl',lambda url:calls.append(url.toLocalFile()))
    deadline=time.monotonic()+5
    while panel.jobs.future is not None and time.monotonic()<deadline:qt_app.processEvents();time.sleep(.01)
    panel.idle_reports()
    while panel.jobs.future is not None and time.monotonic()<deadline:qt_app.processEvents();time.sleep(.01)
    assert calls==[path.replace('\\','/')] and window.worker.transport is None
