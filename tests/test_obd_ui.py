"""Private offline view is isolated from acquisition; synthetic input only."""
import time
from mokka_ecu_lab.ui.obd import ObdDialog
from test_obd_performance import synthetic_bundle
from test_ui_freshness import window


def test_offline_inventory_and_performance_do_not_submit_to_worker(window,tmp_path,monkeypatch,qt_app):
    calls=[]
    with monkeypatch.context() as patch:
        patch.setattr(window.worker,'submit',lambda *a,**k:calls.append(a))
        dialog=ObdDialog([synthetic_bundle(tmp_path/'constructed.zip')],window)
        deadline=time.monotonic()+5
        while not dialog.future.done() and time.monotonic()<deadline:qt_app.processEvents();time.sleep(.01)
        dialog.poll()
        assert dialog.report and dialog.groups.count()==1 and 'Declared 38' in dialog.inventory_view.toPlainText()
        assert '38' in dialog.inventory_view.toPlainText() and 'latency_ms' in dialog.performance_view.toPlainText()
        assert calls==[] and window.worker.transport is None
        dialog.close();dialog.deleteLater();qt_app.processEvents()


def test_benchmark_controls_hidden_in_normal_three_action_ui(window):
    window.session_panel.advanced.setChecked(False);window.session_panel.update()
    assert window.session_panel.benchmark_group.isHidden()
    assert window.session_panel.connect.text()=='Connect' and window.session_panel.start.text()=='Start Session' and window.session_panel.finish.text()=='Finish Session'
