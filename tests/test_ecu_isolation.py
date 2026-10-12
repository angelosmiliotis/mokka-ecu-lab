import time
from mokka_ecu_lab.adapter import AcquisitionWorker
from mokka_ecu_lab.transport.simulator import Simulator
from mokka_ecu_lab.protocols import parse_obd

def test_decoding_does_not_inherit_another_ecus_support(tmp_path, monkeypatch):
    original = Simulator._exchange
    def two_sources(self, command, stop, timeout):
        raw = original(self, command, stop, timeout)
        if command == '0100':
            # 7E9 supports coolant only, with no continuation page; 7E8 supports all fixtures.
            return raw.replace(b'>', b'7E9 06 41 00 08 00 00 00\r>')
        if command == '010C':
            return raw.replace(b'>', b'7E9 04 41 0C 0C 30\r>')
        return raw
    monkeypatch.setattr(Simulator, '_exchange', two_sources)
    worker = AcquisitionWorker(tmp_path)
    try:
        worker.submit('connect', simulation=True, port='COM4')
        deadline = time.monotonic() + 7
        rpm_readings = None
        while time.monotonic() < deadline:
            try: kind, value = worker.events.get(timeout=.1)
            except __import__('queue').Empty: continue
            if kind == 'transaction' and value[0]['command']=='010C':
                record, rpm_readings = value
                assert len(record['parsed']) == 2
                break
        assert rpm_readings and [r['ecu'] for r in rpm_readings] == ['7E8']
        assert worker.support['7E9'] == {5}
    finally:
        worker.submit('shutdown'); worker.join(5)
