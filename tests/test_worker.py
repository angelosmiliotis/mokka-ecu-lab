import queue
import time
import threading
import pytest
from mokka_ecu_lab.adapter import AcquisitionWorker
from mokka_ecu_lab.logging import list_sessions
from mokka_ecu_lab.transport.simulator import Simulator, SCENARIOS
from mokka_ecu_lab.transport import TransportError
from mokka_ecu_lab.protocols import parse_obd

@pytest.mark.parametrize('scenario', SCENARIOS)
def test_simulator_scenarios(scenario):
    sim = Simulator(scenario); sim.supported = set(sim.supported_fixture)
    stop = threading.Event()
    assert b'SIMULAT' in sim.exchange('ATI', stop)
    if scenario == 'Unsupported PID': assert 92 not in sim.supported
    errors, multiple = 0, False
    for _ in range(6):
        sim.last_send = 0  # Fixture clock only; production transport remains capped.
        try:
            raw = sim.exchange('010C',stop)
            replies = parse_obd(raw,12)
            multiple |= len(replies) == 2
        except (TransportError, ValueError): errors += 1
    if scenario in {'Adapter timeout','ECU timeout','Malformed response','Disconnection','Incomplete reply'}: assert errors
    if scenario == 'Multiple ECUs': assert multiple

def await_event(worker, kind, predicate=lambda x: True, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try: k,v = worker.events.get(timeout=.1)
        except queue.Empty: continue
        if k == kind and predicate(v): return v
    raise AssertionError(f'Missing event {kind}')

def test_worker_record_stop_reconnect_replay(tmp_path):
    worker = AcquisitionWorker(tmp_path)
    try:
        time.sleep(.1); assert worker.transport is None
        worker.submit('record')
        worker.submit('connect',simulation=True,port='COM4',scenario='Unsupported PID')
        support = await_event(worker,'support'); assert 92 not in support['7E8']; assert 12 in support['7E8']
        await_event(worker,'transaction',lambda x: bool(x[1]))
        worker.submit('stop'); time.sleep(.2)
        last_send = worker.transport.last_send; time.sleep(.3); assert worker.transport.last_send == last_send
        worker.submit('record_stop'); await_event(worker,'recording',lambda x:x is None)
        session = list_sessions(tmp_path)[0]; assert session['requests'] >= 15 and session['mode']=='SIMULATED'
        worker.submit('replay',path=str(tmp_path/session['raw_path']))
        await_event(worker,'connection',lambda x:x['ecu']=='Replay paused')
        assert worker.transport is None
        worker.submit('step'); await_event(worker,'transaction',lambda x:x[0].get('replay'))
        worker.submit('connect',simulation=True,port='COM4',scenario='Normal idle')
        await_event(worker,'support'); assert 92 in worker.transport.supported
    finally:
        worker.submit('shutdown'); worker.join(8); assert not worker.is_alive()
