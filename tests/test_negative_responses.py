"""Minimal response fixtures from chapter 6; no full vehicle journal is included."""
import base64
import csv
import json
import queue
import time

import pytest

from mokka_ecu_lab.adapter import AcquisitionWorker
from mokka_ecu_lab.logging import list_sessions, export_csv, utc_now
from mokka_ecu_lab.protocols import parse_obd
from mokka_ecu_lab.sensors import load_registry
from mokka_ecu_lab.transport.simulator import Simulator


@pytest.mark.parametrize("pid,command", [(0x0D, "010D"), (0x04, "0104"), (0x0B, "010B")])
def test_exact_negative_session_replies(pid, command):
    reply, = parse_obd(b"7E8 03 7F 01 22\r>", pid, command)
    assert reply.header == "7E8" and reply.data == bytes.fromhex("7F 01 22")
    assert reply.rejection() == {"ecu": "7E8", "service": "01", "nrc": "22",
                                 "reason_code": "CONDITIONS_NOT_CORRECT", "reason": "Conditions Not Correct"}


@pytest.mark.parametrize("text,pid,value", [
    ("7E8 04 41 0C 0C 52", 0x0C, 788.5),
    ("7E8 03 41 05 54", 0x05, 44),
    ("7E8 04 41 10 02 41", 0x10, 5.77),
    ("7E8 04 41 0C 17 80", 0x0C, 1504),
    ("7E8 03 41 04 00", 0x04, 0),
])
def test_exact_positive_session_replies(text, pid, value):
    reply, = parse_obd((text + "\r>").encode(), pid, f"01{pid:02X}")
    assert reply.negative_code is None
    assert load_registry()[pid].decode(reply.data) == pytest.approx(value)


@pytest.mark.parametrize("raw,header", [
    (b"7E8037F0122\r>", "7E8"),
    (b"18DAF110 03 7F 01 22\r>", "18DAF110"),
    (b"18DAF110037F0122\r>", "18DAF110"),
    (b"010D\rSEARCHING...\r7E8 8 03 7F 01 22 00 00 00 00\r>", "7E8"),
    (b"7E8 7F 01 22\r>", "7E8"),
    (b"7F 01 22\r>", None),
    (b"03 7F 01 22\r>", None),
    (b"48 6B 10 7F 01 22 65\r>", "48 6B 10"),
])
def test_negative_frame_formats(raw, header):
    reply, = parse_obd(raw, 0x0D, "010D")
    assert reply.header == header and reply.negative_code == 0x22


@pytest.mark.parametrize("raw", [
    b"7E8 03 7F 01\r>", b"7E8 02 7F 01 22\r>", b"7E8 04 7F 01 22\r>",
    b"7E8 03 7F 09 22\r>", b"7E8 10 03 7F 01 22\r>",
    b"7E8 03 7F 01 22", b"7E8 03 7F 01 ZZ\r>", b"7F 01\r>",
])
def test_malformed_or_other_service_is_not_a_mode01_rejection(raw):
    with pytest.raises(ValueError): parse_obd(raw, 0x0D)


def test_other_nrc_is_retained_without_guessing_ignition():
    reply, = parse_obd(b"7E8 03 7F 01 78\r>", 12)
    assert reply.rejection()["nrc"] == "78"
    assert reply.rejection()["reason_code"] == "ECU_REJECTION"


def wait_event(worker, kind, predicate=lambda value: True, timeout=9):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try: event, value = worker.events.get(timeout=.1)
        except queue.Empty: continue
        if event == kind and predicate(value): return value
    raise AssertionError(f"Missing {kind} event")


def shutdown(worker):
    worker.submit("shutdown")
    worker.join(8)
    assert not worker.is_alive()


def test_conditions_loss_stops_without_retry_and_retains_final_raw(tmp_path):
    worker = AcquisitionWorker(tmp_path)
    try:
        worker.submit("select", pids=[0x0D, 0x04, 0x0B])
        worker.submit("record")
        worker.submit("connect", simulation=True, port="COM4", scenario="Conditions Not Correct")
        state = wait_event(worker, "acquisition", lambda state: state["requires_reconnect"])
        assert not state["polling"] and "Conditions Not Correct" in state["reason"]
        last_send = worker.transport.last_send
        worker.submit("start")
        wait_event(worker, "notice", lambda message: "remains stopped" in message)
        time.sleep(.3)
        assert not worker.polling and worker.transport.last_send == last_send
        worker.submit("disconnect")
        wait_event(worker, "connection", lambda state: state["adapter"] == "Disconnected")
        session, = list_sessions(tmp_path)
        assert session["ended"] and session["errors"] == 3
        records = [json.loads(line) for line in (tmp_path/session["raw_path"]).read_text().splitlines()]
        negatives = [r for r in records if r["status"] == "ECU_NEGATIVE_RESPONSE"]
        assert [r["command"] for r in negatives] == ["010D", "0104", "010B"]
        for record in negatives:
            assert record["request_id"] == record["command"]
            assert base64.b64decode(record["raw_b64"]) == b"7E8 03 7F 01 22\r>"
            assert record["negative_responses"][0]["reason_code"] == "CONDITIONS_NOT_CORRECT"
            assert not record["parsed"] and not record["decoder"]
        assert session["requests"] == len(records)
        export_csv(tmp_path, session["id"], tmp_path/"decoded.csv")
        with (tmp_path/"decoded.csv").open(encoding="utf-8-sig") as file:
            readings = list(csv.DictReader(file))
        assert len(readings) == 3
        assert {r["source_kind"] for r in readings} == {"SIMULATED"}
    finally: shutdown(worker)


def test_mixed_ecus_preserve_valid_measurement_and_separate_rejection(tmp_path, monkeypatch):
    monkeypatch.setattr(AcquisitionWorker, "start", lambda self: None)
    worker = AcquisitionWorker(tmp_path)
    sim = Simulator(); sim.supported = {12}
    monkeypatch.setattr(sim, "_exchange", lambda *args: b"7E8 04 41 0C 0C 52\r7E9 03 7F 01 22\r>")
    worker.transport, worker.mode = sim, "SIMULATED"
    worker.support = {"7E8": {12}, "7E9": {12}}
    record = worker.transaction("010C")
    _, (_, readings) = worker.events.get_nowait()
    assert record["status"] == "ECU_NEGATIVE_RESPONSE"
    assert record["parsed"] == [{"ecu": "7E8", "data_hex": "0C 52"}]
    assert record["negative_responses"][0]["ecu"] == "7E9"
    assert [(r["ecu"], r["value"]) for r in readings] == [("7E8", 788.5)]


def test_legacy_negative_replay_is_reclassified_without_live_io(tmp_path, monkeypatch):
    monkeypatch.setattr(AcquisitionWorker, "start", lambda self: None)
    def forbidden_serial(*args): raise AssertionError("Replay opened serial")
    monkeypatch.setattr("mokka_ecu_lab.adapter.SerialTransport", forbidden_serial)
    original = {"record_type": "transaction", "id": "minimal-fixture", "timestamp": utc_now(),
                "monotonic_ns": 1, "pid": "0D", "command": "010D", "mode": "LIVE · hardware unverified",
                "raw_b64": base64.b64encode(b"7E8 03 7F 01 22\r>").decode(), "status": "INVALID"}
    path = tmp_path/"minimal-negative.jsonl"
    content = json.dumps(original) + "\n"; path.write_text(content)
    worker = AcquisitionWorker(tmp_path)
    try:
        worker.handle("replay", {"path": str(path)})
        worker.handle("record", {})
        assert worker.recorder is None
        worker.handle("step", {})
        transactions = []
        while not worker.events.empty():
            kind, value = worker.events.get_nowait()
            if kind == "transaction": transactions.append(value)
        (record, readings), = transactions
        assert not readings and worker.transport is None
        assert record["replay"] and record["original_status"] == "INVALID"
        assert record["status"] == "ECU_NEGATIVE_RESPONSE"
        assert path.read_text() == content
    finally: worker.replay.close()
