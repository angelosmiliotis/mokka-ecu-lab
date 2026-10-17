"""New history/navigation projections never submit OBD actions on page visit."""
import time
from test_ui_freshness import window
from test_library import legacy

def test_history_versions_visits_filter_and_label_without_transport(window,legacy,qt_app,monkeypatch):
    p=window.history_panel;plan=p.library.preview_migration(legacy);p.library.migrate(plan,plan['approval_token']);p.refresh();calls=[]
    deadline=time.monotonic()+5
    while (p.jobs.future is not None or p.refresh_pending) and time.monotonic()<deadline:qt_app.processEvents();time.sleep(.01)
    with monkeypatch.context() as patch:
        patch.setattr(window.worker,'submit',lambda *a,**k:calls.append(a))
        for index in (8,9,10):window.sidebar.buttons[index].click();qt_app.processEvents()
        assert calls==[] and window.tabs.count()==13
        p.outcome.setCurrentText('FAILED_COM_OPEN');assert p.table.rowCount()==2
        p.outcome.setCurrentIndex(0);p.kind.setCurrentText('DRIVE');assert p.table.rowCount()==1
        p.kind.setCurrentIndex(0);p.rate.setCurrentText('2');assert p.table.rowCount()==1
        assert window.benchmark_panel.keep.isChecked()
        assert window.sidebar.buttons[9].accessibleName()=='History / Reports' and window.sidebar.buttons[10].accessibleName()=='App Versions'
