import time
import threading
from mokka_ecu_lab.adapter import AcquisitionWorker
from mokka_ecu_lab.transport.simulator import Simulator
from mokka_ecu_lab.transport import Cancelled

def test_receive_cancel_requires_reconnect(tmp_path, monkeypatch):
    original = Simulator._exchange
    receiving = threading.Event()
    def delayed_reply(self, command, stop, timeout):
        if command == '010C':
            receiving.set()
            if stop.wait(2): raise Cancelled('Receive canceled', b'7E8 04 41')
        return original(self,command,stop,timeout)
    monkeypatch.setattr(Simulator,'_exchange',delayed_reply)
    worker = AcquisitionWorker(tmp_path)
    try:
        worker.submit('connect',simulation=True,port='COM4')
        assert receiving.wait(6)
        worker.submit('stop')
        deadline = time.monotonic() + 2
        while worker.transport is not None and time.monotonic() < deadline: time.sleep(.01)
        assert worker.transport is None
        worker.submit('start'); time.sleep(.1)
        assert worker.transport is None and not worker.polling
    finally:
        worker.submit('shutdown'); worker.join(5)
