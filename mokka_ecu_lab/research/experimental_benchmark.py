"""Bounded five-request/second experimental engine, restricted to fake COM.

This is a byte-stream request engine, not the scalar timing model. The shipped
factory constructs its own in-memory COM endpoint and virtual clock. There is no
serial import, port name input, arbitrary transport/callback injection or hardware
backend. Hardware admission always raises, regardless of configuration values.
The normal SafeTransport policy is separate and remains at four total req/s.
"""
from copy import deepcopy
from dataclasses import dataclass
import math
import re
import threading

from mokka_ecu_lab.protocols import validate_command
from mokka_ecu_lab.protocols.isotp import parse_reply


FIXED_COMMANDS = ('010D', '010C', '010B', '0110')
PREFLIGHT_COMMANDS = ('0100',) + (FIXED_COMMANDS * 3)[:11]
PREFLIGHT_GAP_NS = 250_000_000
MEASUREMENT_GAP_NS = 200_000_000
MEASUREMENT_NS = 60_000_000_000
MAX_MEASUREMENT_REQUESTS = 300
MAX_TOTAL_REQUESTS = len(PREFLIGHT_COMMANDS) + MAX_MEASUREMENT_REQUESTS
MAX_REPLY_NS = 250_000_000
MAX_SPEED_AGE_NS = 1_200_000_000
PREFLIGHT_P95_MS = 150
SUPPORTED_PIDS = frozenset(int(command[2:], 16) for command in FIXED_COMMANDS)
LIVE_LOCK_REASON = (
    'Experimental hardware is LOCKED. Separate exact operator authorization and '
    'independent technical safety review, preferably by an automotive professional, '
    'are required before a separately reviewed hardware-enabled release. '
    'This release has no physical higher-rate backend.'
)

BEFORE_SEND_FAULTS = frozenset({
    'STOP', 'SUSPEND', 'SHUTDOWN', 'CONTEXT_CHANGE', 'PORT_CHANGE',
    'ECU_CHANGE', 'PROMPT_DESYNC', 'SPEED_MISSING', 'SPEED_STALE',
    'PORT_LOSS', 'COMPETING_WRITER',
})
REPLY_FAULTS = frozenset({
    'SPEED_NONZERO', 'NRC', 'INVALID_FRAME', 'PARTIAL_RESPONSE', 'NO_DATA',
    'TIMEOUT', 'EXCESSIVE_LATENCY', 'REPLY_ECU_CHANGE', 'WRONG_PID',
    'MULTIPLE_ECUS', 'UNSUPPORTED_BITMAP', 'STOP_DURING_RECEIVE',
    'SUSPEND_DURING_RECEIVE', 'PORT_LOSS_DURING_RECEIVE', 'ADAPTER_ERROR',
})
FAULTS = BEFORE_SEND_FAULTS | REPLY_FAULTS


class HardwareLocked(RuntimeError):
    """An explanation, never a flag/token that can enable hardware."""


def request_hardware_experiment(*args, **kwargs):
    """Deliberately unconditional: JSON, settings and consent booleans cannot unlock."""
    raise HardwareLocked(LIVE_LOCK_REASON)


@dataclass(frozen=True)
class FakeFault:
    request_index: int
    kind: str

    def __post_init__(self):
        if type(self.request_index) is not int or not 0 <= self.request_index < MAX_TOTAL_REQUESTS:
            raise ValueError('Fake fault index must be within the bounded all-phase request ledger')
        if self.kind not in FAULTS:
            raise ValueError('Unknown fake COM fault')


@dataclass(frozen=True)
class FakeScenario:
    """Constructed inputs only; no bytes, callable, file, port or transport input."""
    fault: FakeFault | None = None
    preflight_response_ms: float = 80
    measurement_response_ms: float = 80
    fragment_bytes: int = 3

    def __post_init__(self):
        if self.fault is not None and type(self.fault) is not FakeFault:
            raise ValueError('Only a concrete FakeFault is accepted')
        if self.fault is not None:
            index = self.fault.request_index
            command = (PREFLIGHT_COMMANDS[index] if index < len(PREFLIGHT_COMMANDS)
                       else FIXED_COMMANDS[(index - len(PREFLIGHT_COMMANDS)) % len(FIXED_COMMANDS)])
            if self.fault.kind == 'SPEED_NONZERO' and command != '010D':
                raise ValueError('Moving-speed fault must target an actual speed response')
            if self.fault.kind == 'UNSUPPORTED_BITMAP' and command != '0100':
                raise ValueError('Bitmap fault must target the actual bitmap response')
        for value in (self.preflight_response_ms, self.measurement_response_ms):
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= 1000:
                raise ValueError('Constructed response latency must be finite and within 0–1000 ms')
        if type(self.fragment_bytes) is not int or not 1 <= self.fragment_bytes <= 64:
            raise ValueError('Fake reply fragments must contain 1–64 bytes')


class _VirtualClock:
    def __init__(self):
        self.ns = 0

    def advance_to(self, deadline_ns):
        if deadline_ns < self.ns:
            raise RuntimeError('Virtual monotonic clock cannot reverse')
        self.ns = deadline_ns


class _Abort(Exception):
    def __init__(self, reason, raw=b''):
        super().__init__(reason)
        self.reason = reason
        self.raw = raw


class _FakeCOM:
    """Actual memory-backed write/read endpoint. It cannot delegate to hardware."""
    def __init__(self, clock, scenario, writer_key):
        self.clock = clock
        self.scenario = scenario
        self._writer_key = writer_key
        self.open = True
        self.prompt_synchronized = True
        self.context = ('FAKE_COM_ONLY', 115200, 'CONSTRUCTED_CONTEXT', '7E8')
        self.writes = []
        self._buffer = b''
        self._ready_ns = 0
        self._read_fault = None

    def write(self, wire_bytes, writer_key, phase, fault):
        if writer_key is not self._writer_key:
            raise _Abort('COMPETING_WRITER')
        if not self.open:
            raise _Abort('PORT_LOSS')
        if not self.prompt_synchronized or self._buffer:
            raise _Abort('PROMPT_DESYNC')
        command = wire_bytes.decode('ascii').removesuffix('\r')
        self.writes.append((self.clock.ns, wire_bytes))
        self.prompt_synchronized = False
        pid = int(command[2:], 16)
        data = {0x00: self._bitmap(), 0x0D: b'\x00', 0x0C: b'\x10\x00',
                0x0B: b'\x64', 0x10: b'\x0b\xb8'}[pid]
        ecu = '7E8'
        if fault == 'SPEED_NONZERO' and pid == 0x0D:
            data = b'\x05'
        if fault == 'UNSUPPORTED_BITMAP' and pid == 0:
            data = b'\x00' * 4
        if fault == 'REPLY_ECU_CHANGE':
            ecu = '7E9'
        reply_pid = 0x0E if fault == 'WRONG_PID' else pid
        frame = bytes((2 + len(data), 0x41, reply_pid)) + data
        raw = (ecu + ' ' + frame.hex(' ').upper() + '\r>').encode('ascii')
        if fault == 'NRC':
            raw = b'7E8 03 7F 01 22\r>'
        elif fault == 'INVALID_FRAME':
            raw = b'7E8 06 41 0D 00\r>'
        elif fault == 'PARTIAL_RESPONSE':
            raw = raw.removesuffix(b'>')
        elif fault == 'NO_DATA':
            raw = b'NO DATA\r>'
        elif fault == 'ADAPTER_ERROR':
            raw = b'CAN ERROR\r>' + raw
        elif fault == 'MULTIPLE_ECUS':
            raw = raw.removesuffix(b'>') + raw.replace(b'7E8', b'7E9')
        elif fault == 'TIMEOUT':
            raw = b''
        latency = (self.scenario.preflight_response_ms if phase == 'PREFLIGHT'
                   else self.scenario.measurement_response_ms)
        if fault == 'EXCESSIVE_LATENCY':
            latency = 250
        self._ready_ns = self.clock.ns + math.ceil(latency * 1_000_000)
        self._buffer = raw
        self._read_fault = fault
        return len(wire_bytes)

    @staticmethod
    def _bitmap():
        return sum(1 << (32 - pid) for pid in SUPPORTED_PIDS).to_bytes(4, 'big')

    def read(self, deadline_ns):
        if not self.open:
            raise _Abort('PORT_LOSS')
        if self._read_fault in {'STOP_DURING_RECEIVE', 'SUSPEND_DURING_RECEIVE', 'PORT_LOSS_DURING_RECEIVE'}:
            self.clock.advance_to(min(self._ready_ns, deadline_ns))
            raise _Abort(self._read_fault, self._buffer[:2])
        if self._ready_ns >= deadline_ns or not self._buffer:
            self.clock.advance_to(deadline_ns)
            return b''
        self.clock.advance_to(max(self.clock.ns, self._ready_ns))
        chunk, self._buffer = self._buffer[:self.scenario.fragment_bytes], self._buffer[self.scenario.fragment_bytes:]
        if b'>' in chunk and not self._buffer:
            self.prompt_synchronized = True
        return chunk

    def close(self):
        self.open = False
        self.prompt_synchronized = False


class ExperimentalFakeCOMBenchmark:
    """One serialized writer exercising real bytes, policy, framing and aborts.

    advance() processes at most one request/response. The virtual clock makes a
    full sixty-second acceptance run practical without pretending that wall-clock
    or vehicle behavior was measured. stop()/suspend()/shutdown() send nothing.
    Neither endpoint nor clock can be supplied by the caller.
    """
    def __init__(self, scenario=None):
        if scenario is None:
            scenario = FakeScenario()
        if type(scenario) is not FakeScenario:
            raise ValueError('Use a concrete memory-only FakeScenario; hardware and dictionaries are rejected')
        self._owner = threading.get_ident()
        self._advance_lock = threading.Lock()
        self._writer_key = object()
        self._clock = _VirtualClock()
        self._port = _FakeCOM(self._clock, scenario, self._writer_key)
        self._initial_context = self._port.context
        self._scenario = scenario
        self._ledger = []
        self._last_send_ns = None
        self._speed_ns = None
        self._bitmap_verified = False
        self._positives = set()
        self._stop_reason = None
        self._measurement_start_ns = None
        self._measurement_end_ns = None
        self.state = 'PREFLIGHT'
        self.reason = 'Fake COM preparation; every byte write is globally accounted at <=4/s'

    @property
    def active(self):
        return self.state in {'PREFLIGHT', 'MEASUREMENT'}

    def stop(self):
        self._stop_reason = 'STOP'
        self._abort('STOP')

    def suspend(self):
        self._stop_reason = 'SUSPEND'
        self._abort('SUSPEND')

    def shutdown(self):
        self._stop_reason = 'SHUTDOWN'
        self._abort('SHUTDOWN')

    def _abort(self, reason):
        if self.active:
            self.state = 'ABORTED'
            self.reason = reason
            self._port.close()

    def _check(self, *, bootstrap=False):
        if self._stop_reason:
            raise _Abort(self._stop_reason)
        if not self._port.open:
            raise _Abort('PORT_LOSS')
        if self._port.context != self._initial_context:
            raise _Abort('CONTEXT_CHANGE')
        if not self._port.prompt_synchronized:
            raise _Abort('PROMPT_DESYNC')
        if self._port._buffer:
            raise _Abort('PROMPT_DESYNC')
        if self._speed_ns is None:
            if not bootstrap:
                raise _Abort('SPEED_MISSING')
        elif self._clock.ns - self._speed_ns > MAX_SPEED_AGE_NS:
            raise _Abort('SPEED_STALE')

    def _validate(self, raw, command):
        if len(raw) > 65536 or not raw.endswith(b'>') or raw.count(b'>') != 1:
            raise _Abort('PARTIAL_RESPONSE', raw)
        try:
            lines = [line.strip() for line in re.split(r'[\r\n>]', raw.decode('ascii')) if line.strip()]
        except UnicodeDecodeError:
            raise _Abort('INVALID_FRAME', raw)
        for line in lines:
            if line != command and not re.fullmatch(r'[0-9A-Fa-f\s]+', line):
                raise _Abort('NO_DATA' if line == 'NO DATA' else 'ADAPTER_ERROR', raw)
        pid = int(command[2:], 16)
        parsed = parse_reply(raw, pid, command)
        if parsed.errors or len(parsed.responses) != 1:
            raise _Abort('INVALID_FRAME', raw)
        reply = parsed.responses[0]
        if reply.header != self._initial_context[-1]:
            raise _Abort('ECU_CHANGE', raw)
        if reply.negative_code is not None:
            raise _Abort('NRC', raw)
        expected_length = {0: 4, 0x0D: 1, 0x0C: 2, 0x0B: 1, 0x10: 2}[pid]
        if len(reply.data) != expected_length:
            raise _Abort('INVALID_FRAME', raw)
        if pid == 0:
            bits = int.from_bytes(reply.data, 'big')
            if any(not bits & (1 << (32 - value)) for value in SUPPORTED_PIDS):
                raise _Abort('UNSUPPORTED_BITMAP', raw)
            self._bitmap_verified = True
        elif pid == 0x0D:
            if reply.data != b'\x00':
                raise _Abort('SPEED_NONZERO', raw)
            self._speed_ns = self._clock.ns
        self._positives.add(command)

    def _exchange(self, command, phase):
        command = validate_command(command, SUPPORTED_PIDS if self._bitmap_verified else set())
        if command not in (('0100',) + FIXED_COMMANDS):
            raise _Abort('COMMAND_POLICY')
        if len(self._ledger) >= MAX_TOTAL_REQUESTS:
            raise _Abort('REQUEST_BOUND')
        gap = PREFLIGHT_GAP_NS if phase == 'PREFLIGHT' else MEASUREMENT_GAP_NS
        # The transition preserves the previous <=4/s reservation. There is no
        # phase-local limiter reset or unaccounted initialization path.
        if phase == 'MEASUREMENT' and len(self._ledger) == len(PREFLIGHT_COMMANDS):
            gap = PREFLIGHT_GAP_NS
        if self._last_send_ns is not None:
            self._clock.advance_to(max(self._clock.ns, self._last_send_ns + gap))
        bootstrap = phase == 'PREFLIGHT' and len(self._ledger) <= 1
        self._check(bootstrap=bootstrap)
        send_ns = self._clock.ns
        if self._measurement_end_ns is not None and send_ns >= self._measurement_end_ns:
            return False
        if self._last_send_ns is not None and send_ns - self._last_send_ns < gap:
            raise _Abort('GLOBAL_RATE_ACCOUNTING')
        event = dict(index=len(self._ledger), phase=phase, command=command,
                     send_ns=send_ns, response_end_ns=None, sent=False,
                     raw_hex='', category='PENDING', source='FAKE_COM_BYTES')
        self._ledger.append(event)
        fault = self._scenario.fault
        kind = fault.kind if fault and fault.request_index == event['index'] else None
        deadline = send_ns + MAX_REPLY_NS
        if self._measurement_end_ns is not None:
            deadline = min(deadline, self._measurement_end_ns)
        raw = bytearray()
        try:
            wire = command.encode('ascii') + b'\r'
            count = self._port.write(wire, self._writer_key, phase, kind)
            event['sent'] = True
            self._last_send_ns = send_ns
            if count != len(wire):
                raise _Abort('PARTIAL_WRITE')
            while self._clock.ns < deadline:
                if self._stop_reason:
                    raise _Abort(self._stop_reason, bytes(raw))
                chunk = self._port.read(deadline)
                raw.extend(chunk)
                if len(raw) > 65536:
                    raise _Abort('INVALID_FRAME', bytes(raw))
                if b'>' in chunk:
                    break
            if not raw.endswith(b'>'):
                raise _Abort('PARTIAL_RESPONSE' if raw else 'TIMEOUT', bytes(raw))
            if self._clock.ns - send_ns >= MAX_REPLY_NS:
                raise _Abort('EXCESSIVE_LATENCY', bytes(raw))
            self._validate(bytes(raw), command)
            self._check(bootstrap=bootstrap)
            event['category'] = 'OK'
        except _Abort as exc:
            if exc.raw:
                raw = bytearray(exc.raw)
            event['category'] = exc.reason
            raise
        finally:
            event['raw_hex'] = bytes(raw).hex(' ').upper()
            event['response_end_ns'] = self._clock.ns
        return True

    def advance(self):
        if threading.get_ident() != self._owner:
            self._abort('COMPETING_WRITER')
            raise RuntimeError('Experimental engine belongs to one serialized owner')
        if not self._advance_lock.acquire(blocking=False):
            self._abort('COMPETING_WRITER')
            raise RuntimeError('Experimental engine is not reentrant')
        try:
            if not self.active:
                return self.snapshot()
            try:
                index = len(self._ledger)
                fault = self._scenario.fault
                if fault and fault.request_index == index and fault.kind in BEFORE_SEND_FAULTS:
                    raise _Abort(fault.kind)
                if self.state == 'PREFLIGHT' and index == len(PREFLIGHT_COMMANDS):
                    latencies = sorted((event['response_end_ns'] - event['send_ns']) / 1e6 for event in self._ledger)
                    p95 = latencies[math.ceil(.95 * len(latencies)) - 1]
                    if p95 > PREFLIGHT_P95_MS:
                        raise _Abort('PREFLIGHT_LATENCY')
                    if not self._bitmap_verified or not set(FIXED_COMMANDS) <= self._positives:
                        raise _Abort('PREFLIGHT_SUPPORT')
                    self._check()
                    self._measurement_start_ns = max(self._clock.ns, self._last_send_ns + PREFLIGHT_GAP_NS)
                    self._measurement_end_ns = self._measurement_start_ns + MEASUREMENT_NS
                    self.state = 'MEASUREMENT'
                    self.reason = 'Fake byte-stream measurement: fixed 5/s, at most 300 requests, no retry or ramp'
                measured = sum(event['phase'] == 'MEASUREMENT' for event in self._ledger)
                if self.state == 'MEASUREMENT' and (measured >= MAX_MEASUREMENT_REQUESTS or self._clock.ns >= self._measurement_end_ns):
                    self._check()
                    self._clock.advance_to(max(self._clock.ns, self._measurement_end_ns))
                    self.state = 'COMPLETED'
                    self.reason = 'FAKE COM ONLY: bounded byte exchange completed; no hardware safety/capacity result'
                    self._port.close()
                else:
                    command = (PREFLIGHT_COMMANDS[index] if self.state == 'PREFLIGHT'
                               else FIXED_COMMANDS[measured % len(FIXED_COMMANDS)])
                    if not self._exchange(command, self.state):
                        self.state = 'COMPLETED'
                        self.reason = 'FAKE COM ONLY: fixed measurement window elapsed'
                        self._port.close()
            except _Abort as exc:
                self._abort(exc.reason)
            return self.snapshot()
        finally:
            self._advance_lock.release()

    def snapshot(self):
        events = deepcopy(self._ledger)
        measured = [event for event in events if event['phase'] == 'MEASUREMENT']
        writes = list(self._port.writes)
        gaps = [b[0] - a[0] for a, b in zip(writes, writes[1:])]
        measurement_gaps = [b['send_ns'] - a['send_ns'] for a, b in zip(measured, measured[1:])]
        elapsed_ns = 0 if self._measurement_start_ns is None else min(MEASUREMENT_NS, max(0, self._clock.ns - self._measurement_start_ns))
        preflight = [event for event in events if event['phase'] == 'PREFLIGHT']
        preflight_gaps = [b['send_ns'] - a['send_ns'] for a, b in zip(preflight, preflight[1:])]
        latencies = sorted((event['response_end_ns'] - event['send_ns']) / 1e6
                           for event in events if event['sent'] and event['response_end_ns'] is not None)
        overlaps = sum(b['send_ns'] < a['response_end_ns'] for a, b in zip(events, events[1:]))
        spacing_violations = sum(gap < PREFLIGHT_GAP_NS for gap in preflight_gaps)
        spacing_violations += sum(gap < MEASUREMENT_GAP_NS for gap in measurement_gaps)
        if preflight and measured:
            spacing_violations += measured[0]['send_ns'] - preflight[-1]['send_ns'] < PREFLIGHT_GAP_NS
        return dict(schema='mokka-experimental-fake-com-1', mode='FAKE_COM_BYTES',
                    state=self.state, active=self.active, reason=self.reason,
                    live_enabled=False, hardware_state='LOCKED', hardware_lock_reason=LIVE_LOCK_REASON,
                    actual_hardware_transmissions=0, fake_com_writes=len(writes),
                    hardware_capacity_verified=False, rate_req_s=5, maximum_seconds=60,
                    elapsed_virtual_seconds=elapsed_ns / 1e9, remaining_virtual_seconds=(MEASUREMENT_NS - elapsed_ns) / 1e9,
                    preflight_requests=len(events) - len(measured), measurement_requests=len(measured),
                    maximum_measurement_requests=300, maximum_total_requests=MAX_TOTAL_REQUESTS,
                    minimum_all_phase_fake_send_gap_ns=min(gaps) if gaps else None,
                    minimum_preflight_fake_send_gap_ns=min(preflight_gaps) if preflight_gaps else None,
                    minimum_measured_fake_send_gap_ns=min(measurement_gaps) if measurement_gaps else None,
                    fake_send_spacing_violations=spacing_violations, fake_response_overlaps=overlaps,
                    all_phase_fake_latency_p95_ms=latencies[math.ceil(.95 * len(latencies)) - 1] if latencies else None,
                    speed_age_ms=(self._clock.ns - self._speed_ns) / 1e6 if self._speed_ns is not None else None,
                    categories={category: sum(event['category'] == category for event in events)
                                for category in sorted({event['category'] for event in events})},
                    measurement_start_ns=self._measurement_start_ns, measurement_end_ns=self._measurement_end_ns,
                    fake_port_open=self._port.open, context='CONSTRUCTED_CONTEXT',
                    fixed_commands=list(FIXED_COMMANDS), events=events,
                    evidence_note='Real request-engine execution over constructed in-memory serial bytes and a virtual clock; not a hardware or wall-time result.')


def implementation_brief():
    """Publicly exportable scope. No input can turn this description into authority."""
    return dict(schema='mokka-experimental-engine-1', hardware_state='LOCKED',
                live_enabled=False, reason=LIVE_LOCK_REASON, implemented='SERIALIZED_FAKE_COM_BYTE_ENGINE',
                ordinary_live_ceiling_req_s=4, proposed_rate_req_s=5,
                measurement_seconds=60, preflight_rate_ceiling_req_s=4,
                preflight_commands=list(PREFLIGHT_COMMANDS), measurement_commands=list(FIXED_COMMANDS),
                maximum_measurement_requests=300, maximum_total_requests=MAX_TOTAL_REQUESTS,
                speed_maximum_age_ms=MAX_SPEED_AGE_NS / 1e6,
                preflight_p95_admission_ms=PREFLIGHT_P95_MS, single_reply_abort_ms=MAX_REPLY_NS / 1e6,
                current_limitations=['No physical serial backend exists in this pathway.',
                    'No JSON/configuration/checkbox/environment unlock is accepted.',
                    'Thresholds are engineering candidates; fake-COM passes do not certify ECU safety.',
                    'No automatic retry, rate ramp, 6/s mode or return to higher rate after an error.'],
                before_hardware_enable=['Independent technical safety review of every writer and fail-closed path, preferably by an automotive professional.',
                    'A separate reviewed build with an exact 5/s, 60-second, fixed-command hardware policy; ordinary <=4 remains independent.',
                    'Explicit separate operator approval naming exact rate, duration, PIDs, request maximum, stop rules and stationary conditions.',
                    'Fresh healthy matched normal <=4/s reference, fresh support/positive/prompt/context checks, stationary operator acknowledgement.',
                    'Physical Bluetooth/OS suspend/port loss/Stop handling and immutable partial evidence validation before any authorized trial.'])
