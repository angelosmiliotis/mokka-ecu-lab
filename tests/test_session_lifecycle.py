import json
import time
from collections import Counter

import pytest

from mokka_ecu_lab.adapter import AcquisitionWorker
from mokka_ecu_lab.logging import list_sessions
from mokka_ecu_lab.transport.simulator import Simulator
from test_negative_responses import wait_event, shutdown


@pytest.mark.parametrize("order", [("stop", "record_stop"), ("record_stop", "stop")])
def test_final_session_is_closed_in_either_stop_order(tmp_path, order):
    worker = AcquisitionWorker(tmp_path)
    try:
        worker.submit("record")
        worker.submit("connect", simulation=True, port="COM4")
        wait_event(worker, "transaction", lambda value: bool(value[1]))
        for action in order: worker.submit(action)
        worker.submit("disconnect")
        wait_event(worker, "connection", lambda state: state["adapter"] == "Disconnected")
        session, = list_sessions(tmp_path)
        assert session["ended"] and worker.recorder is None and worker.transport is None
        path = tmp_path/session["raw_path"]
        records = [json.loads(line) for line in path.read_text().splitlines()]
        assert len(records) == session["requests"]
        assert records and all(r["session_id"] == session["id"] for r in records)
        size = path.stat().st_size
        time.sleep(.1)
        assert path.stat().st_size == size
    finally: shutdown(worker)


def test_weighted_acquisition_keeps_global_wire_rate_cap(tmp_path, monkeypatch):
    sends = []
    original = Simulator._exchange
    def spy(self, command, stop, timeout):
        sends.append((time.monotonic(), command))
        return original(self, command, stop, timeout)
    monkeypatch.setattr(Simulator, "_exchange", spy)
    worker = AcquisitionWorker(tmp_path)
    samples = []
    def enough(value):
        if value[1]: samples.append(value[0]["command"])
        return len(samples) >= 8
    try:
        worker.submit("select", pids=[12, 5, 0x22])
        worker.submit("priorities", enabled=True, weights={12: 3, 5: 1, 0x22: 999})
        worker.submit("rate", rate=100)  # The request cap still clamps at the worker boundary.
        worker.submit("connect", simulation=True, port="COM4")
        wait_event(worker, "transaction", enough)
        worker.submit("stop")
        wait_event(worker, "acquisition", lambda state: not state["polling"])
        assert Counter(samples[:8]) == {"010C": 6, "0105": 2}
        assert all(b[0]-a[0] >= .245 for a, b in zip(sends, sends[1:]))
        assert not any(command == "0122" for _, command in sends)
    finally: shutdown(worker)


def test_source_switch_closes_old_session_instead_of_relabeling_simulation(tmp_path, monkeypatch):
    # A simulated serial boundary exercises LIVE provenance without opening a real COM port.
    monkeypatch.setattr("mokka_ecu_lab.adapter.SerialTransport", lambda *args: Simulator())
    worker = AcquisitionWorker(tmp_path)
    try:
        worker.submit("record")
        worker.submit("connect", simulation=True, port="COM4")
        wait_event(worker, "transaction", lambda value: bool(value[1]))
        worker.submit("connect", simulation=False, port="COM4")
        wait_event(worker, "context", lambda context: context["mode"].startswith("LIVE"))
        old_session, = list_sessions(tmp_path)
        assert old_session["ended"] and old_session["mode"] == "SIMULATED"
        records = [json.loads(line) for line in (tmp_path/old_session["raw_path"]).read_text().splitlines()]
        assert all(record["mode"] == "SIMULATED" for record in records)
        wait_event(worker, "transaction", lambda value: bool(value[1]) and value[0]["mode"].startswith("LIVE"))
        assert worker.recorder is None
        worker.submit("record")
        wait_event(worker, "transaction", lambda value: bool(value[1]))
        worker.submit("disconnect")
        wait_event(worker, "connection", lambda state: state["adapter"] == "Disconnected")
        new_session = next(s for s in list_sessions(tmp_path) if s["id"] != old_session["id"])
        assert new_session["ended"] and new_session["mode"].startswith("LIVE")
        records = [json.loads(line) for line in (tmp_path/new_session["raw_path"]).read_text().splitlines()]
        assert records and all(record["source_kind"] == "ECU_READING" for record in records)
    finally: shutdown(worker)
