"""Newly constructed fake serial bytes; no vehicle captures or wall-time claims."""
import ast
import inspect
import json
import threading

import pytest

from mokka_ecu_lab.research import experimental_benchmark as engine


def complete(run):
    for _ in range(314):
        result = run.advance()
        if not run.active:
            return result
    raise AssertionError('Bounded fake COM run must terminate')


def test_byte_engine_runs_full_fixed_window_with_global_phase_boundary_accounting():
    run = engine.ExperimentalFakeCOMBenchmark()
    result = complete(run)
    assert result['state'] == 'COMPLETED'
    assert result['elapsed_virtual_seconds'] == 60
    assert result['remaining_virtual_seconds'] == 0
    assert result['preflight_requests'] == 12
    assert result['measurement_requests'] == 300
    assert result['fake_com_writes'] == 312
    assert result['actual_hardware_transmissions'] == 0
    assert result['hardware_state'] == 'LOCKED' and not result['live_enabled']
    assert result['fake_port_open'] is False
    events = result['events']
    assert [event['command'] for event in events[:12]] == list(engine.PREFLIGHT_COMMANDS)
    assert [event['command'] for event in events[12:]] == list(engine.FIXED_COMMANDS) * 75
    assert all(event['sent'] and event['category'] == 'OK' for event in events)
    assert all(bytes.fromhex(event['raw_hex']).endswith(b'>') for event in events)
    assert [event['send_ns'] for event in events] == [t for t, raw in run._port.writes]
    assert [raw for t, raw in run._port.writes] == [event['command'].encode() + b'\r' for event in events]
    assert all(b['send_ns'] - a['send_ns'] == 250_000_000 for a, b in zip(events[:12], events[1:13]))
    assert all(b['send_ns'] - a['send_ns'] == 200_000_000 for a, b in zip(events[12:], events[13:]))
    assert all(b['send_ns'] >= a['response_end_ns'] for a, b in zip(events, events[1:]))
    assert events[12]['send_ns'] == result['measurement_start_ns']
    assert events[-1]['response_end_ns'] <= result['measurement_end_ns']
    assert result['minimum_measured_fake_send_gap_ns'] == 200_000_000
    assert result['minimum_preflight_fake_send_gap_ns'] == 250_000_000
    assert result['fake_send_spacing_violations'] == result['fake_response_overlaps'] == 0
    assert result['all_phase_fake_latency_p95_ms'] == 80
    assert max(sum(e['command'] == pid and e['phase'] == 'MEASUREMENT' for e in events)
               for pid in engine.FIXED_COMMANDS) == 75


@pytest.mark.parametrize('fragment_bytes', [1, 2, 7, 64])
def test_actual_fragmented_byte_reception_and_existing_parser(fragment_bytes):
    result = complete(engine.ExperimentalFakeCOMBenchmark(engine.FakeScenario(fragment_bytes=fragment_bytes)))
    assert result['state'] == 'COMPLETED'
    assert result['fake_com_writes'] == 312


@pytest.mark.parametrize('kind', sorted(engine.BEFORE_SEND_FAULTS))
@pytest.mark.parametrize('index', [0, 8, 12, 71])
def test_stop_suspend_loss_context_prompt_stale_speed_close_before_next_write(kind, index):
    run = engine.ExperimentalFakeCOMBenchmark(engine.FakeScenario(fault=engine.FakeFault(index, kind)))
    result = complete(run)
    assert result['state'] == 'ABORTED' and result['reason'] == kind
    assert result['fake_com_writes'] == index
    assert not result['fake_port_open']
    before = run.snapshot()
    assert run.advance() == before
    run.stop()
    assert run.advance() == before


@pytest.mark.parametrize('kind', sorted(engine.REPLY_FAULTS - {'SPEED_NONZERO', 'UNSUPPORTED_BITMAP'}))
@pytest.mark.parametrize('index', [3, 12, 85])
def test_errors_after_write_retain_partial_bytes_and_never_retry(kind, index):
    run = engine.ExperimentalFakeCOMBenchmark(engine.FakeScenario(fault=engine.FakeFault(index, kind)))
    result = complete(run)
    assert result['state'] == 'ABORTED'
    assert result['events'][-1]['category'] != 'OK'
    assert result['fake_com_writes'] == index + 1
    assert len(result['events']) == index + 1
    assert not result['fake_port_open']
    if kind not in {'TIMEOUT', 'EXCESSIVE_LATENCY'}:
        assert result['events'][-1]['raw_hex']
    before = run.snapshot()
    for _ in range(3):
        assert run.advance() == before


def test_speed_and_support_are_verified_from_received_positive_bytes():
    for fault in [engine.FakeFault(1, 'SPEED_NONZERO'), engine.FakeFault(0, 'UNSUPPORTED_BITMAP')]:
        result = complete(engine.ExperimentalFakeCOMBenchmark(engine.FakeScenario(fault=fault)))
        assert result['state'] == 'ABORTED' and result['reason'] == fault.kind
        assert result['fake_com_writes'] == fault.request_index + 1
    run = engine.ExperimentalFakeCOMBenchmark()
    run.advance()
    assert run._bitmap_verified and run._speed_ns is None
    run.advance()
    assert run._speed_ns is not None


@pytest.mark.parametrize('action,reason', [('stop', 'STOP'), ('suspend', 'SUSPEND'), ('shutdown', 'SHUTDOWN')])
def test_external_lifecycle_actions_are_zero_send_and_close_fake_endpoint(action, reason):
    run = engine.ExperimentalFakeCOMBenchmark()
    for _ in range(25):
        run.advance()
    before = len(run._port.writes)
    getattr(run, action)()
    result = run.advance()
    assert result['state'] == 'ABORTED' and result['reason'] == reason
    assert result['fake_com_writes'] == before and not result['fake_port_open']


def test_stale_speed_and_mutated_context_are_detected_without_injected_fault_shortcut():
    run = engine.ExperimentalFakeCOMBenchmark()
    for _ in range(13):
        run.advance()
    before = len(run._port.writes)
    run._clock.advance_to(run._clock.ns + engine.MAX_SPEED_AGE_NS + 1)
    result = run.advance()
    assert result['state'] == 'ABORTED' and result['reason'] == 'SPEED_STALE'
    assert result['fake_com_writes'] == before
    for field, replacement in [(0, 'CHANGED_COM'), (1, 9600), (2, 'CHANGED_CONTEXT'), (3, '7E9')]:
        run = engine.ExperimentalFakeCOMBenchmark()
        run.advance()
        values = list(run._port.context)
        values[field] = replacement
        run._port.context = tuple(values)
        result = run.advance()
        assert result['reason'] == 'CONTEXT_CHANGE' and result['fake_com_writes'] == 1


def test_prompt_loss_and_unread_bytes_are_detected_without_new_transmission():
    run = engine.ExperimentalFakeCOMBenchmark()
    run.advance()
    run._port.prompt_synchronized = False
    assert run.advance()['reason'] == 'PROMPT_DESYNC'
    assert len(run._port.writes) == 1
    run = engine.ExperimentalFakeCOMBenchmark()
    run.advance()
    run._port._buffer = b'UNEXPECTED'
    result = run.advance()
    assert result['reason'] == 'PROMPT_DESYNC'
    assert result['fake_com_writes'] == 1


def test_reference_admission_is_stricter_than_reply_abort_and_rejects_before_five_rate():
    run = engine.ExperimentalFakeCOMBenchmark(engine.FakeScenario(preflight_response_ms=151))
    result = complete(run)
    assert result['state'] == 'ABORTED' and result['reason'] == 'PREFLIGHT_LATENCY'
    assert result['preflight_requests'] == 12 and result['measurement_requests'] == 0
    assert all(b[0] - a[0] >= 250_000_000 for a, b in zip(run._port.writes, run._port.writes[1:]))
    result = complete(engine.ExperimentalFakeCOMBenchmark(engine.FakeScenario(measurement_response_ms=210)))
    assert result['measurement_requests'] < 300
    assert all(b['send_ns'] >= a['response_end_ns'] for a, b in zip(result['events'], result['events'][1:]))
    assert result['measurement_end_ns'] >= result['events'][-1]['response_end_ns']


def test_owner_and_reentrant_guard_cannot_create_a_second_writer():
    run = engine.ExperimentalFakeCOMBenchmark()
    errors = []
    def attempt():
        try:
            run.advance()
        except RuntimeError as exc:
            errors.append(str(exc))
    thread = threading.Thread(target=attempt)
    thread.start()
    thread.join()
    assert errors and run.snapshot()['fake_com_writes'] == 0
    assert run.state == 'ABORTED'
    run = engine.ExperimentalFakeCOMBenchmark()
    with run._advance_lock:
        with pytest.raises(RuntimeError, match='not reentrant'):
            run.advance()
    assert run.snapshot()['fake_com_writes'] == 0 and run.state == 'ABORTED'
    run = engine.ExperimentalFakeCOMBenchmark()
    with pytest.raises(Exception, match='COMPETING_WRITER'):
        run._port.write(b'010D\r', object(), 'MEASUREMENT', None)
    assert not run._port.writes


def test_published_hardware_gate_is_unconditional_and_no_transport_can_be_injected():
    for options in [{}, {'authorized': True}, {'hardware_enabled': True, 'rate': 5, 'duration': 60},
                    json.loads('{"independent_review": true, "operator_consent": true}')]:
        with pytest.raises(engine.HardwareLocked, match='LOCKED'):
            engine.request_hardware_experiment(**options)
    class PretendPort:
        def write(self, *args):
            raise AssertionError('Must never touch a supplied hardware-like object')
    class PretendScenario(engine.FakeScenario):
        pass
    for supplied in [PretendPort(), {'port': 'COM99'}, {'rate': 5}, PretendScenario()]:
        with pytest.raises(ValueError, match='concrete memory-only'):
            engine.ExperimentalFakeCOMBenchmark(supplied)
    parsed = ast.parse(inspect.getsource(engine))
    imports = [node.module for node in ast.walk(parsed) if isinstance(node, ast.ImportFrom)]
    imports += [alias.name for node in ast.walk(parsed) if isinstance(node, ast.Import) for alias in node.names]
    assert set(imports) == {'copy', 'dataclasses', 'math', 're', 'threading',
                            'mokka_ecu_lab.protocols', 'mokka_ecu_lab.protocols.isotp'}
    assert not any(value.startswith(('serial', 'socket', 'ctypes', 'subprocess', 'os')) for value in imports)


def test_existing_ordinary_policy_still_rejects_five_even_after_successful_fake_run():
    from mokka_ecu_lab.transport import SafeTransport
    class NoHardware(SafeTransport):
        def _exchange(self, *args):
            raise AssertionError('Ordinary higher-rate wire send must never occur')
    complete(engine.ExperimentalFakeCOMBenchmark())
    port = NoHardware()
    port.rate = 5
    port.supported = {0x0D}
    with pytest.raises(ValueError, match='4 Hz'):
        port.exchange('010D', threading.Event())


def test_snapshots_and_briefs_are_detached_and_strictly_label_fake_evidence():
    run = engine.ExperimentalFakeCOMBenchmark()
    first = run.advance()
    first['events'][0]['category'] = 'FORGED'
    first['events'].clear()
    assert run.snapshot()['events'][0]['category'] == 'OK'
    brief = engine.implementation_brief()
    brief['measurement_commands'].append('22FFFF')
    assert engine.implementation_brief()['measurement_commands'] == list(engine.FIXED_COMMANDS)
    assert brief['hardware_state'] == 'LOCKED' and not brief['live_enabled']
    assert brief['maximum_total_requests'] == 312


@pytest.mark.parametrize('kwargs', [
    {'preflight_response_ms': True}, {'preflight_response_ms': float('nan')},
    {'measurement_response_ms': 0}, {'measurement_response_ms': float('inf')},
    {'fragment_bytes': 0}, {'fragment_bytes': 65}, {'fragment_bytes': True},
    {'fault': {'kind': 'STOP'}},
])
def test_unbounded_or_ambiguous_fake_inputs_rejected(kwargs):
    with pytest.raises(ValueError):
        engine.FakeScenario(**kwargs)


def test_fake_fault_bounds_and_names_are_not_open_commands():
    for index in [-1, 312, True, 1.5]:
        with pytest.raises(ValueError):
            engine.FakeFault(index, 'STOP')
    with pytest.raises(ValueError):
        engine.FakeFault(1, '22FFFF')
    for fault in [engine.FakeFault(0, 'SPEED_NONZERO'), engine.FakeFault(2, 'UNSUPPORTED_BITMAP')]:
        with pytest.raises(ValueError):
            engine.FakeScenario(fault=fault)
