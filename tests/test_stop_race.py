import time
from mokka_ecu_lab.adapter import AcquisitionWorker
from mokka_ecu_lab.transport.simulator import Simulator

def test_stop_cancels_queued_connection(tmp_path, monkeypatch):
    writes = []
    original = Simulator._exchange
    def spy(self, command, stop, timeout):
        writes.append(command)
        return original(self, command, stop, timeout)
    monkeypatch.setattr(Simulator, '_exchange', spy)
    worker = AcquisitionWorker(tmp_path)
    # Lock worker dispatch until both UI commands have been submitted.
    original_init = worker.initialize
    def delayed(options):
        time.sleep(.1)
        return original_init(options)
    worker.initialize = delayed
    try:
        worker.submit('connect', simulation=True, port='COM4')
        worker.submit('stop')
        time.sleep(.4)
        assert not writes
        assert not worker.polling
    finally:
        worker.submit('shutdown'); worker.join(5)
