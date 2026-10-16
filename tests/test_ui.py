import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication
from mokka_ecu_lab.ui.window import MainWindow

def test_ui_offline_and_shutdown(tmp_path,qt_app):
    app = qt_app
    window = MainWindow(tmp_path,validation=True)
    try:
        app.processEvents(); window.drain()
        assert window.tabs.count() == 11 and window.tabs.currentIndex()==7
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
