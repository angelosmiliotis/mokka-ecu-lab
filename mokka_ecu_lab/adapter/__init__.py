"""Worker owns transport, recorder, discovery, polling and streaming replay."""
import base64
import queue
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from mokka_ecu_lab.transport import SerialTransport, TransportError, Cancelled
from mokka_ecu_lab.transport.simulator import Simulator
from mokka_ecu_lab.protocols import parse_obd, supported_pids, LIVE_PIDS
from mokka_ecu_lab.sensors import load_registry
from mokka_ecu_lab.logging import Recorder, utc_now
from mokka_ecu_lab.replay import Replay
from .scheduling import PollScheduler

class AcquisitionWorker(threading.Thread):
    def __init__(self, root: Path):
        super().__init__(name="serialized-obd-worker", daemon=False)
        self.root = root
        self.commands = queue.Queue(maxsize=64)
        self.events = queue.Queue(maxsize=512)
        self.stop_io = threading.Event()
        self.quit_event = threading.Event()
        self.transport = self.recorder = self.replay = None
        self.registry = load_registry()
        self.selected = list(self.registry)
        self.adapter, self.protocol, self.port, self.mode = "Unknown", "Unknown", "", "Disconnected"
        self.support = {}
        self.support_pages = {}
        self.polling = False
        self.priorities = {}
        self.scheduler = PollScheduler()
        self.failures = 0
        self.requires_reconnect = False
        self.context_id = uuid.uuid4().hex
        self.rate = 4.0
        self.dropped = 0
        self.replay_playing = False
        self.replay_speed = 1.0
        self.pending_record = None
        self.replay_previous = None
        self.replay_due = 0.0
        self.start()

    def emit(self, kind, value):
        try: self.events.put_nowait((kind, value))
        except queue.Full:
            self.dropped += 1  # Only UI preview is bounded/dropped, never recorded transactions.
            if kind != "transaction":
                try: self.events.get_nowait()
                except queue.Empty: pass
                try: self.events.put_nowait((kind, value))
                except queue.Full: pass

    def submit(self, action, **kwargs):
        if action in {"connect", "start"}:
            # Clear only at user submission, so a later Stop cancels queued Connect too.
            self.stop_io.clear()
        if action in {"disconnect", "stop", "shutdown", "replay"}:
            self.stop_io.set()
        self.commands.put_nowait((action, kwargs))

    def transaction(self, command):
        sent_ns, stamp = time.monotonic_ns(), utc_now()
        raw, error, status, readings, parsed, rejections = b"", "", "OK", [], [], []
        try:
            raw = self.transport.exchange(command, self.stop_io)
            if command.startswith("01"):
                pid = int(command[2:], 16)
                replies = parse_obd(raw, pid, command)
                for reply in replies:
                    if reply.negative_code is not None:
                        rejections.append(reply.rejection())
                        continue
                    source = reply.header or "headerless"
                    parsed.append({"ecu": reply.header, "data_hex": reply.data.hex(' ').upper()})
                    if pid in self.registry:
                        if pid not in self.support.get(source, set()):
                            continue
                        sensor = self.registry[pid]
                        readings.append({"sensor_id": sensor.id, "pid": pid, "ecu": reply.header,
                            "value": sensor.decode(reply.data), "unit": sensor.unit,
                            "verification": sensor.metadata["verification"], "timestamp": stamp,
                            "monotonic_ns": sent_ns, "decoder": sensor.id, "mode": self.mode,
                            "source_kind": "SIMULATED" if self.mode == "SIMULATED" else "ECU_READING"})
                if rejections:
                    status = "ECU_NEGATIVE_RESPONSE"
                    error = '; '.join(f'{r["ecu"] or "headerless"}: {r["reason"]} (7F 01 {r["nrc"]})' for r in rejections)
        except TransportError as exc:
            raw, error, status = exc.raw, str(exc), "CANCELLED" if isinstance(exc, Cancelled) else "TRANSPORT_ERROR"
        except ValueError as exc:
            error, status = str(exc), "INVALID"
        wire_ns = self.transport.last_wire_ns
        if wire_ns is not None:
            stamp = datetime.fromtimestamp(time.time() - (time.monotonic_ns() - wire_ns) / 1e9, timezone.utc).isoformat(timespec='microseconds')
            sent_ns = wire_ns
            for reading in readings:
                reading["timestamp"], reading["monotonic_ns"] = stamp, sent_ns
        record = {"id": uuid.uuid4().hex, "timestamp": stamp, "monotonic_ns": sent_ns,
            "port": self.port, "adapter": self.adapter, "protocol": self.protocol, "mode": self.mode,
            "context_id": self.context_id, "source_kind": "SIMULATED" if self.mode == "SIMULATED" else "ECU_READING",
            "serial_settings": {"baud": getattr(self.transport, "baud", None), "data_bits": 8, "parity": "N", "stop_bits": 1},
            "request_id": command, "pid": command[2:] if command.startswith("01") else None,
            "command": command, "outbound_b64": base64.b64encode((command + '\r').encode()).decode(),
            "sent": wire_ns is not None,
            "raw_b64": base64.b64encode(raw).decode(), "raw_text": raw.decode("ascii", "replace"),
            "latency_ms": (time.monotonic_ns() - sent_ns) / 1e6, "status": status,
            "parsed": parsed, "negative_responses": rejections, "decoder": [r["decoder"] for r in readings],
            "verification": [r["verification"] for r in readings], "error": error}
        if self.recorder: self.recorder.append(record, readings)
        self.emit("transaction", (record, readings))
        if status == "TRANSPORT_ERROR":
            raise TransportError(error, raw)
        if status == "CANCELLED": raise Cancelled(error, raw)
        return record

    def set_polling(self, active, reason, requires_reconnect=False):
        self.polling = active
        self.requires_reconnect = requires_reconnect
        self.emit("acquisition", {"polling": active, "reason": reason, "requires_reconnect": requires_reconnect})

    def close_recording(self):
        if self.recorder:
            self.recorder.close()
            self.recorder = None
        self.emit("recording", None)

    def disconnect(self, finish_recording=True):
        self.set_polling(False, "Disconnected")
        if self.transport: self.transport.close()
        self.transport = None
        if finish_recording: self.close_recording()
        self.emit("connection", {"adapter": "Disconnected", "ecu": "Unavailable", "protocol": self.protocol, "mode": self.mode})

    def initialize(self, options):
        # An empty pre-connect recorder is allowed; captured sources never share a session.
        if self.recorder and self.recorder.count:
            self.close_recording()
            self.emit("notice", "Previous session closed before reconnect/source change. Start Recording for the new session.")
        self.disconnect(finish_recording=False)
        if self.replay: self.replay.close(); self.replay = None
        self.replay_playing = False
        self.support = {}
        self.support_pages = {}
        self.mode = "SIMULATED" if options["simulation"] else "LIVE · hardware unverified"
        self.context_id = uuid.uuid4().hex
        self.failures = 0
        self.scheduler = PollScheduler()
        self.emit("context", {"id": self.context_id, "mode": self.mode})
        if self.recorder:
            self.recorder.db.execute("UPDATE sessions SET mode=? WHERE id=?", (self.mode, self.recorder.id))
            self.recorder.db.commit()
        self.port = "SIMULATED" if options["simulation"] else options["port"]
        self.adapter, self.protocol = "Unknown", "Unknown"
        self.transport = Simulator(options.get("scenario", "Normal idle")) if options["simulation"] else SerialTransport(self.port, options.get("baud", 115200))
        self.transport.rate = self.rate
        self.emit("notice", f"Opening {self.port} at {options.get('baud', 115200)} baud, 8N1; bounded prompt timeout 6 s. {self.mode}")
        self.emit("connection", {"adapter": "Initializing", "ecu": "Not yet verified", "protocol": "Unknown", "mode": self.mode})
        identity = self.transaction("ATI")
        if not any(x in identity["raw_text"].upper() for x in ("ELM", "STN", "OBDLINK")):
            raise TransportError("Adapter identity not recognized; no ECU requests sent")
        self.adapter = identity["raw_text"].replace('>', '').strip()
        stn = self.transaction("STI")
        if "STN" in stn["raw_text"]: self.adapter += " / " + stn["raw_text"].replace('>', '').strip()
        for cmd in ("ATE0", "ATL0", "ATS1", "ATH1", "ATM0", "ATTP0", "ATST64"):
            response = self.transaction(cmd)
            if "OK" not in response["raw_text"].upper():
                raise TransportError(f"Required adapter configuration rejected: {cmd}")
        self.emit("connection", {"adapter": self.adapter, "ecu": "Discovering support", "protocol": "Auto", "mode": self.mode})
        for base in (0, 32, 64):
            if base and not any(base in s for s in self.support.values()): break
            record = self.transaction(f"01{base:02X}")
            for item in record["parsed"]:
                source = item["ecu"] or "headerless"
                # Do not let a non-advertising ECU inherit another ECU's next bitmap.
                if base == 0 or base in self.support.get(source, set()):
                    self.support.setdefault(source, set()).update(supported_pids(bytes.fromhex(item["data_hex"]), base))
                    self.support_pages.setdefault(source, set()).add(base)
        self.transport.supported = set().union(*self.support.values()) if self.support else set()
        self.protocol = self.transaction("ATDP")["raw_text"].replace('>', '').strip()
        self.transaction("ATDPN")
        self.emit("support", self.support)
        self.emit("support_pages", self.support_pages)
        self.emit("connection", {"adapter": self.adapter, "ecu": "Connected" if self.support else "No verified ECU response", "protocol": self.protocol, "mode": self.mode})
        self.set_polling(bool(self.support), "Polling" if self.support else "No verified ECU response")

    def decode_replay(self, record):
        # Reclassify legacy v0.1.0 INVALID negative replies without rewriting the journal.
        record = dict(record, replay=True, context_id=self.context_id)
        readings = []
        if record.get("pid"):
            pid = int(record["pid"], 16)
            try:
                replies = parse_obd(base64.b64decode(record["raw_b64"]), pid, record["command"])
            except ValueError:
                replies = []
            rejections = [r.rejection() for r in replies if r.negative_code is not None]
            if rejections:
                record["original_status"] = record["status"]
                record["status"] = "ECU_NEGATIVE_RESPONSE"
                record["negative_responses"] = rejections
                record["error"] = '; '.join(f'{r["ecu"] or "headerless"}: {r["reason"]} (7F 01 {r["nrc"]})' for r in rejections)
            positive_replies = [r for r in replies if r.negative_code is None]
            if pid in {0, 32, 64} and record.get("status") == "OK":
                try:
                    for reply in positive_replies:
                        source = reply.header or "headerless"
                        if pid == 0 or pid in self.support.get(source, set()):
                            self.support.setdefault(source, set()).update(supported_pids(reply.data, pid))
                            self.support_pages.setdefault(source, set()).add(pid)
                    self.emit("support", dict(self.support))
                    self.emit("support_pages", dict(self.support_pages))
                except ValueError as exc: self.emit("notice", str(exc))
            if pid in self.registry and record.get("original_status", record.get("status")) in {"OK", "ECU_NEGATIVE_RESPONSE"}:
                sensor = self.registry[pid]
                try:
                    for reply in positive_replies:
                        readings.append({"sensor_id": sensor.id, "pid": pid, "ecu": reply.header,
                            "value": sensor.decode(reply.data), "unit": sensor.unit,
                            "verification": sensor.metadata["verification"], "timestamp": record["timestamp"],
                            "monotonic_ns": record["monotonic_ns"], "mode": "REPLAY · " + record.get("mode", "unknown"),
                            "source_kind": "SIMULATED" if record.get("mode") == "SIMULATED" else "ECU_READING" if record.get("mode", "").startswith("LIVE") else "UNKNOWN"})
                except ValueError as exc: self.emit("notice", str(exc))
        self.emit("transaction", (record, readings))

    def handle(self, action, options):
        if action == "connect": self.initialize(options)
        elif action == "disconnect": self.disconnect()
        elif action == "stop":
            self.set_polling(False, "Polling stopped by user", self.requires_reconnect)
            self.replay_playing = False
        elif action == "start" and self.transport:
            if self.requires_reconnect:
                self.emit("notice", "Polling remains stopped after ECU failures. Check ignition and explicitly reconnect.")
            else:
                self.failures = 0
                self.set_polling(bool(self.support), "Polling resumed")
        elif action == "select": self.selected = options["pids"]
        elif action == "priorities": self.priorities = options["weights"] if options.get("enabled") else {}
        elif action == "rate":
            self.rate = max(0.25, min(4., options["rate"]))
            if self.transport: self.transport.rate = self.rate
        elif action == "record":
            if self.replay:
                self.emit("notice", "Replay is recorded evidence, not a new ECU session. Recording replay is disabled.")
                return
            if not self.recorder:
                self.recorder = Recorder(self.root, self.mode if self.transport else "Pending connection", {"vehicle": "Opel Mokka B 2022 1.5 diesel", "adapter": "REDACTED", "VIN": "not queried"})
                self.emit("recording", self.recorder.id)
        elif action == "record_stop":
            self.close_recording()
        elif action == "replay":
            self.disconnect()
            if self.replay: self.replay.close()
            self.replay = Replay(Path(options["path"]))
            self.mode = "REPLAY"
            self.context_id = uuid.uuid4().hex
            self.emit("context", {"id": self.context_id, "mode": self.mode})
            self.support = {}
            self.support_pages = {}
            self.pending_record, self.replay_previous = None, None
            self.replay_playing = False
            self.emit("connection", {"adapter": "Offline", "ecu": "Replay paused", "protocol": "Recorded", "mode": "REPLAY"})
        elif action == "replay_play":
            self.replay_speed = options["speed"]; self.replay_playing = True
        elif action == "step" and self.replay:
            self.replay_playing = False
            record = self.pending_record or self.replay.next()
            self.pending_record = None
            if record: self.decode_replay(record); self.replay_previous = record["monotonic_ns"]
            else: self.emit("notice", "Replay complete. " + '; '.join(self.replay.warnings))
        elif action == "shutdown": self.quit_event.set()

    def run(self):
        try:
            while not self.quit_event.is_set():
                try:
                    action, options = self.commands.get(timeout=0.02 if self.polling or self.replay_playing else 0.1)
                    self.handle(action, options)
                except queue.Empty: pass
                except Cancelled:
                    self.set_polling(False, "Connection canceled")
                    if self.transport and self.transport.last_wire_ns is not None:
                        self.disconnect(); self.emit("notice", "Receive canceled after send; reconnect to restore prompt synchronization")
                except Exception as exc:
                    self.emit("notice", str(exc)); self.disconnect()
                if self.polling and self.transport and not self.stop_io.is_set():
                    pids = [p for p in self.selected if p in LIVE_PIDS and p in self.transport.supported]
                    pid = self.scheduler.next(pids, self.priorities)
                    if pid is None:
                        self.set_polling(False, "No selected supported sensors")
                        continue
                    try:
                        record = self.transaction(f"01{pid:02X}")
                        self.failures = self.failures + 1 if record["status"] != "OK" else 0
                        if self.failures >= 3:
                            reason = ("Conditions Not Correct (7F 01 22); ignition state is not confirmed"
                                      if any(r["nrc"] == "22" for r in record["negative_responses"])
                                      else record["error"] or "Invalid ECU reply")
                            self.set_polling(False, reason, requires_reconnect=True)
                            self.emit("notice", f"Polling stopped after three consecutive ECU failures: {reason}. Values are stale. Stop Recording, check ignition and reconnect explicitly.")
                    except Cancelled:
                        self.set_polling(False, "Polling canceled", self.requires_reconnect)
                        if self.transport and self.transport.last_wire_ns is not None:
                            self.disconnect(); self.emit("notice", "Receive canceled after send; reconnect to restore prompt synchronization")
                    except Exception as exc:
                        self.emit("notice", str(exc)); self.disconnect()
                if self.replay_playing and self.replay:
                    try:
                        if self.pending_record is None:
                            self.pending_record = self.replay.next()
                            if self.pending_record is None:
                                self.replay_playing = False
                                self.emit("notice", "Replay complete. " + '; '.join(self.replay.warnings)); continue
                            gap = 0 if self.replay_previous is None else max(0, (self.pending_record["monotonic_ns"] - self.replay_previous) / 1e9)
                            self.replay_due = time.monotonic() + gap / self.replay_speed
                        if time.monotonic() >= self.replay_due:
                            self.decode_replay(self.pending_record)
                            self.replay_previous = self.pending_record["monotonic_ns"]
                            self.pending_record = None
                    except Exception as exc:
                        self.replay_playing = False; self.emit("notice", str(exc))
        finally:
            self.disconnect()
            if self.replay: self.replay.close()
