"""Synthetic UI regression coverage; no COM connections or private fixtures."""
import base64
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from test_ui_freshness import window,connected,transaction
from test_ui_raw_capture import prepared
from test_research import bundle,transaction as research_transaction


def test_sidebar_keyboard_and_step_navigation_never_acquire(window,monkeypatch):
    window.show(); QApplication.processEvents(); calls=[]
    with monkeypatch.context() as patch:
        patch.setattr(window.worker,'submit',lambda *a,**k:calls.append((a,k)))
        for index,button in window.sidebar.buttons.items():
            button.setFocus(); QTest.keyClick(button,Qt.Key.Key_Space)
            assert window.tabs.currentIndex()==index and button.isChecked()
            assert button.accessibleName()
        QTest.keyClick(window,Qt.Key.Key_1,Qt.KeyboardModifier.AltModifier); QApplication.processEvents()
        assert window.tabs.currentIndex()==0
        for stage in range(7): window.show_capture_step(stage)
        assert not calls and window.worker.transport is None


def test_source_configuration_and_connecting_states(window,monkeypatch):
    window.show(); QApplication.processEvents()
    assert window.sim_config.isVisible() and not window.live_config.isVisible()
    assert not window.disconnect_button.isEnabled() and not window.stop_button.isEnabled()
    window.source.setCurrentIndex(1)
    assert window.live_config.isVisible() and not window.sim_config.isVisible()
    assert window.rate.maximum()==4 and window.connect_button.text()=='Connect'
    calls=[]
    with monkeypatch.context() as patch:
        patch.setattr(window.worker,'submit',lambda *a,**k:calls.append((a,k)))
        window.connect_button.click()
        assert window.mode=='Connecting' and not window.connect_button.isEnabled()
        assert not window.source.isEnabled() and window.disconnect_button.isEnabled()
        assert calls[0][0]==('connect',) and calls[0][1]['simulation'] is False
    connected(window)
    assert window.status_indicators['Connection'].text()=='Connection: Connected'
    window.requires_reconnect=True; window.polling_active=False; window.refresh_presentation()
    assert not window.start_button.isEnabled() and 'Reconnect' in window.start_button.toolTip()


def test_recording_and_polling_have_independent_states(window):
    connected(window,mode='SIMULATED')
    window.worker.events.put(('recording','constructed-session')); window.drain()
    assert not window.record_button.isEnabled() and window.record_stop_button.isEnabled()
    assert not window.session_record_button.isEnabled() and window.session_finish_button.isEnabled()
    window.send('stop'); window.drain()
    assert window.status_indicators['Polling'].text()=='Polling: Stopped'
    assert window.status_indicators['Recording'].text()=='Recording: Active'
    for index in range(7): window.tabs.setCurrentIndex(index)
    assert window.recording_id=='constructed-session'
    window.worker.events.put(('recording',None)); window.drain()
    assert window.record_button.isEnabled() and not window.record_stop_button.isEnabled()


def test_existing_greek_labels_survive_status_refresh(window):
    window.greek.setChecked(True); window.drain()
    assert window.sidebar.buttons[0].text()=='Πίνακας'
    assert window.connect_button.text()=='Σύνδεση'
    assert window.stop_button.text()=='Διακοπή'


def test_cards_preserve_missing_stale_raw_evidence_and_chart_source(window):
    window.update_measurements(); window.refresh_cards()
    assert window.sensor_cards[0].value.text()=='—'
    connected(window,mode='SIMULATED'); transaction(window,mode='SIMULATED')
    assert 'Current sample' in window.sensor_cards[0].state.text()
    assert not window.signal_chart.series()  # One observation is not a trend.
    transaction(window,mode='SIMULATED',when=107.)
    assert window.signal_chart.series()[0].count()==2
    window.send('stop'); window.drain()
    assert 'Stale' in window.sensor_cards[0].state.text()
    connected(window,context='another'); assert not window.signal_chart.series()
    prepared(window); window.support['7E8'].discard(0x8B); window.discovery_observations.pop(('7E8',0x8B),None)
    window.prepare_capture(); window.focus_dashboard.setChecked(True); window.update_capture(); window.refresh_cards()
    assert sum(not card.isHidden() for card in window.sensor_cards)<=7
    assert all('regeneration' not in card.name.text().lower() for card in window.sensor_cards if not card.isHidden())


def test_raw_filter_and_copy_preserve_original_bytes(window):
    raw=b'7E8 04 41 0C 00 04\r>'
    window.raw_records.append(dict(raw_b64=base64.b64encode(raw).decode()))
    from mokka_ecu_lab.ui.window import add_row
    add_row(window.raw_table,['synthetic','010C','OK','1','7E8','00 04','rpm',''])
    window.raw_table.selectRow(0); window.copy_raw_response()
    assert QApplication.clipboard().text()==raw.decode('ascii')
    assert raw.hex(' ') in window.raw_detail.toPlainText()
    assert window.raw_detail.font().family()=='Consolas'
    assert window.raw_table.item(0,5).font().family()=='Consolas'
    window.raw_search.setText('0183'); assert window.raw_table.isRowHidden(0)
    window.raw_search.setText('7E8'); assert not window.raw_table.isRowHidden(0)
    window.raw_status_filter.setCurrentIndex(2); assert window.raw_table.isRowHidden(0)


def test_research_search_sort_keeps_selected_evidence_and_no_requests(window,tmp_path,monkeypatch):
    path=bundle(tmp_path/'synthetic.zip',[research_transaction(0x7A,bytes(6),1),research_transaction(0x85,bytes(10),2)])
    view=window.research_view; view.load_paths([path]); calls=[]
    with monkeypatch.context() as patch:
        patch.setattr(window.worker,'submit',lambda *a,**k:calls.append((a,k)))
        view.matrix.sortItems(3,Qt.SortOrder.DescendingOrder)
        view.matrix_search.setText('0185')
        visible=[r for r in range(view.matrix.rowCount()) if not view.matrix.isRowHidden(r)]
        assert len(visible)==1
        view.matrix.selectRow(visible[0]); assert '"pid": "85"' in view.matrix_detail.toPlainText()
        assert isinstance(view.matrix.item(visible[0],3).data(Qt.ItemDataRole.DisplayRole),int)
        view.matrix_search.setText('DPF pressures'); assert any(not view.matrix.isRowHidden(r) for r in range(view.matrix.rowCount()))
        view.matrix_filter.setCurrentIndex(3)
        assert all(view.matrix.item(r,0).data(Qt.ItemDataRole.UserRole)['positive_response_count']>0 for r in range(view.matrix.rowCount()) if not view.matrix.isRowHidden(r))
        assert not calls


@pytest.mark.parametrize('physical',[(1280,720),(1366,768),(1536,864),(1920,1080)])
@pytest.mark.parametrize('scale',[1,1.25,1.5])
def test_every_page_fits_scaled_desktop_and_has_scroll_access(window,physical,scale):
    logical=(round(physical[0]/scale),round(physical[1]/scale))
    window.resize(*logical); window.show(); QApplication.processEvents()
    assert (window.width(),window.height())==logical
    for index in range(7):
        window.tabs.setCurrentIndex(index); QApplication.processEvents()
        area=window.tabs.widget(index)
        assert area.widget().width()<=area.viewport().width()+1, (index,area.widget().width(),area.viewport().width())
        assert area.verticalScrollBar().isEnabled()
    assert window.sidebar.compact==(logical[0]<1120)
