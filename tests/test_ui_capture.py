from PySide6.QtCore import Qt
from test_ui_freshness import window, connected, transaction
from test_capture import evidence


def prepared(ui):
    connected(ui,mode='SIMULATED')
    ui.support,ui.support_pages,ui.discovery_observations=evidence()
    ui.discovery_prepared=True; ui.discovery_target='7E8'
    ui.update_capture()


def test_preset_is_no_send_and_manual_choices_are_explicit(window,monkeypatch):
    prepared(window); calls=[]
    with monkeypatch.context() as patch:
        patch.setattr(window,'send',lambda action,**kwargs:calls.append((action,kwargs)))
        window.prepare_capture()
        assert calls==[] and len(window.capture_selected())==9
        for i in range(window.capture_list.count()):
            item=window.capture_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole)==0x8B: item.setCheckState(Qt.CheckState.Unchecked)
            if item.data(Qt.ItemDataRole.UserRole)==0x83: item.setCheckState(Qt.CheckState.Checked)
        assert not calls and 0x8B not in window.capture_selected() and 0x83 in window.capture_selected()
        window.start_capture()
        assert calls[-1][0]=='drive_capture' and calls[-1][1]['ecu']=='7E8'
        assert 0x8B not in calls[-1][1]['pids']
    assert '017B' in window.capture_omissions.toPlainText()


def test_focused_dashboard_missing_is_not_zero_and_stop_is_stale(window):
    prepared(window); window.capture_focus.setChecked(True); window.update_capture()
    assert window.capture_table.rowCount()==7
    window.discovery_observations.pop(('7E8',0x7A)); window.update_capture()
    row=1
    assert window.capture_table.item(row,1).text()=='—'
    assert 'unavailable' in window.capture_table.item(row,3).text()
    transaction(window,mode='SIMULATED')
    window.capture_weights={12:2}; window.capture_ecu='7E8'; window.capture_active=True
    window.update_capture()
    assert 'Current sample' in window.capture_table.item(3,3).text()
    window.send('stop'); window.update_capture()
    assert 'Stale' in window.capture_table.item(3,3).text()


def test_capture_new_context_clears_selection_and_requires_rediscovery(window):
    prepared(window); window.prepare_capture()
    connected(window,context='new')
    assert not window.capture_list.count() and not window.capture_start.isEnabled()
    assert not window.capture_preset.isEnabled()
