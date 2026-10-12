import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from types import SimpleNamespace
import pytest
from PySide6.QtWidgets import QApplication
from mokka_ecu_lab.ui.window import MainWindow


@pytest.fixture
def window(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    ui = MainWindow(tmp_path)
    ui.timer.stop()
    monkeypatch.setattr("mokka_ecu_lab.ui.window.time", SimpleNamespace(monotonic=lambda: 110.))
    yield ui
    ui.close(); app.processEvents()
    assert not ui.worker.is_alive()


def connected(ui, mode="LIVE · hardware unverified", context="one"):
    for kind, value in [
        ("context", {"id": context, "mode": mode}),
        ("support", {"7E8": {12, 5}, "7E9": {12, 5}}),
        ("support_pages", {"7E8": {0}, "7E9": {0}}),
        ("connection", {"adapter": "fixture", "ecu": "Connected", "mode": mode, "protocol": "6"}),
        ("acquisition", {"polling": True, "reason": "Polling", "requires_reconnect": False}),
    ]: ui.worker.events.put((kind, value))
    ui.drain()


def transaction(ui, pid=12, ecu="7E8", when=109., mode="LIVE · hardware unverified", replay=False, rejection=False, context="one"):
    reading = {"pid": pid, "ecu": ecu, "value": 788.5 if pid == 12 else 44, "timestamp": "2026-10-12T10:00:00+00:00",
               "monotonic_ns": int(when*1e9), "mode": "REPLAY · "+mode if replay else mode,
               "source_kind": "SIMULATED" if mode == "SIMULATED" else "ECU_READING"}
    record = {"context_id": context, "timestamp": reading["timestamp"], "command": f"01{pid:02X}", "pid": f"{pid:02X}",
              "status": "ECU_NEGATIVE_RESPONSE" if rejection else "OK", "latency_ms": 1,
              "parsed": [] if rejection else [{"ecu": ecu, "data_hex": "0C 52"}], "decoder": [] if rejection else ["rpm"],
              "error": "Conditions Not Correct (7F 01 22)" if rejection else "", "replay": replay,
              "negative_responses": [{"ecu": ecu, "nrc": "22", "reason": "Conditions Not Correct"}] if rejection else []}
    ui.worker.events.put(("transaction", (record, [] if rejection else [reading])))
    ui.drain()


def cell(ui, pid, col):
    name = ui.registry[pid].name
    row = next(row for row in range(ui.dashboard.rowCount()) if ui.dashboard.item(row, 0).text() == name)
    return ui.dashboard.item(row, col).text()


def test_actual_intervals_and_old_queued_reading_age(window):
    connected(window)
    transaction(window, when=106.)
    transaction(window, when=109.)
    assert cell(window, 12, 3) == "Valid"
    assert cell(window, 12, 7) == "ECU_READING"
    assert cell(window, 12, 8) == "3.00 s"
    assert cell(window, 12, 9) == "age 1.00 s / max 3.00 s"
    transaction(window, pid=5, when=95.)
    assert cell(window, 5, 3).startswith("Stale")
    assert "(last)" in cell(window, 5, 1)


def test_rejection_stales_only_responding_ecu_and_explains_reason(window):
    connected(window)
    for ecu in ("7E8", "7E9"):
        for pid in (12, 5): transaction(window, pid=pid, ecu=ecu)
    transaction(window, pid=13, ecu="7E9", rejection=True)
    assert cell(window, 12, 3) == "Valid"  # 7E8 never inherits 7E9's rejection.
    window.ecu.setCurrentIndex(window.ecu.findData("7E9")); window.update_measurements()
    assert "Conditions Not Correct" in cell(window, 12, 3)
    assert cell(window, 5, 3).startswith("Stale")
    assert "not a transport timeout" in window.rejection_reason.text()
    assert "current: 0/2" in window.coverage.text()
    transaction(window, ecu="7E9")
    assert cell(window, 12, 3) == "Valid" and cell(window, 5, 3).startswith("Stale")


def test_stop_marks_cached_values_stale_immediately_even_with_queued_polling_event(window):
    connected(window); transaction(window)
    window.send("stop")
    window.worker.events.put(("acquisition", {"polling": True, "reason": "Polling", "requires_reconnect": False}))
    window.drain()
    assert cell(window, 12, 3).startswith("Stale")
    assert "(last)" in cell(window, 12, 1)
    assert "current: 0/2" in window.coverage.text()
    assert not window.polling_active


def test_replay_is_offline_and_preserves_simulated_evidence(window):
    connected(window, mode="SIMULATED"); transaction(window, mode="SIMULATED")
    assert cell(window, 12, 7) == "SIMULATED"
    window.worker.events.put(("context", {"id": "replay", "mode": "REPLAY"}))
    window.worker.events.put(("connection", {"adapter": "Offline", "ecu": "Replay paused", "mode": "REPLAY", "protocol": "Recorded"}))
    window.drain()
    assert not window.readings
    transaction(window, mode="SIMULATED", replay=True, context="replay", when=1.)
    assert cell(window, 12, 3) == "Recorded (offline)"
    assert cell(window, 12, 7) == "REPLAY · SIMULATED"
    assert "current: 0/2" in window.coverage.text() or "current: 0/0" in window.coverage.text()
    assert not window.connected and not window.polling_active


def test_new_context_discards_previous_source_and_late_transactions(window):
    connected(window, mode="SIMULATED"); transaction(window, mode="SIMULATED")
    connected(window, context="new-live")
    assert not window.readings and cell(window, 12, 1) == "—"
    transaction(window, mode="SIMULATED", context="one")
    assert not window.readings
    transaction(window, context="new-live")
    assert cell(window, 12, 7) == "ECU_READING"


def test_session_finish_and_optional_priority_controls(window):
    sent = []
    window.send = lambda action, **options: sent.append((action, options))
    window.finish_session()
    assert [action for action, _ in sent] == ["stop", "record_stop"]
    window.use_priorities.setChecked(True)
    window.priority_sensor.setCurrentIndex(window.priority_sensor.findData(12))
    window.priority_weight.setValue(4)
    assert sent[-1] == ("priorities", {"enabled": True, "weights": window.priorities})
    # Restore shutdown dispatch for fixture cleanup.
    window.send = lambda action, **options: window.worker.submit(action, **options)
