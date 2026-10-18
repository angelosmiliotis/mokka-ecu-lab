import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication
from mokka_ecu_lab.ui.window import MainWindow
from PySide6.QtGui import QCloseEvent

def test_ui_offline_and_shutdown(tmp_path,qt_app):
    app = qt_app
    window = MainWindow(tmp_path,validation=True)
    try:
        app.processEvents(); window.drain()
        assert window.tabs.count() == 14 and window.tabs.currentIndex()==7
        assert window.tabs.tabText(11)=='Higher-rate research'
        assert window.tabs.tabText(12)=='Workspace / Storage'
        assert window.workspace_panel.jobs.future is None
        assert window.higher_rate_panel.model is None and not window.higher_rate_panel.live_start.isEnabled()
        assert not window.windowIcon().isNull()
        for index in (11,12):
            window.sidebar.activate(index)
            assert window.tabs.currentIndex()==index
        assert window.worker.transport is None
        assert window.source.currentText() == 'Simulation'
        assert window.port.findData('COM4') >= 0
        window.port.setEditText('COM19')
        captured = []
        original_send = window.send
        window.send = lambda action, **kwargs: captured.append((action,kwargs))
        window.connect_adapter()
        assert captured[-1][1]['port'] == 'COM19'
        window.send = original_send
        assert window.worker.transport is None
        assert window.dashboard.rowCount() == 10
        window.payloads.setPlainText('04 80\n04 90')
        window.measured.setPlainText('1152\n1168')
        window.evaluate(); assert window.analysis_report['metrics'][0]['mae'] == 0
        assert window.chart.series()
    finally:
        window.close(); app.processEvents()
        assert not window.worker.is_alive()


def test_shutdown_waits_for_workspace_job_and_stops_offline_model(tmp_path,qt_app,monkeypatch):
    window=MainWindow(tmp_path,validation=True)
    try:
        window.higher_rate_panel.start_model()
        assert window.higher_rate_panel.model.active
        with monkeypatch.context() as patch:
            patch.setattr(window.workspace_panel.jobs,'busy',lambda:True)
            event=QCloseEvent();window.closeEvent(event)
            assert not event.isAccepted() and window.worker.is_alive()
            assert not window.higher_rate_panel.model.active and not window.higher_rate_panel.timer.isActive()
        assert window.worker.transport is None
    finally:
        window.close();qt_app.processEvents()
        assert not window.worker.is_alive()


def test_long_windows_data_paths_do_not_force_horizontal_page_overflow(tmp_path,qt_app):
    window=MainWindow(tmp_path,validation=True)
    try:
        original='C:\\'+('constructed-long-Windows-package-directory\\'*16)+'session-data'
        window.session_info.setText('Selected synthetic session · Stored in '+original)
        window.versions_panel.launcher_identity.setText('Stable target: '+original+'\\MokkaECULabLauncher.exe')
        window.resize(853,480);window.show()
        for index in (1,10):
            window.tabs.setCurrentIndex(index);qt_app.processEvents()
            area=window.tabs.widget(index)
            assert area.widget().width()<=area.viewport().width()+1
        assert original in window.session_info.toolTip()
        assert window.root==tmp_path and window.worker.transport is None
    finally:
        window.close();qt_app.processEvents()
        assert not window.worker.is_alive()
