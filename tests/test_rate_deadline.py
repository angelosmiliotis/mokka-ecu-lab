"""Deterministic early Windows wake-up; no serial device or recorded trace."""
from mokka_ecu_lab.transport import SafeTransport


def test_early_timeout_is_rechecked_until_actual_monotonic_send_deadline(monkeypatch):
    clock=[1_000_000_000]; waits=[]
    class EarlyWait:
        def is_set(self): return False
        def wait(self,seconds):
            waits.append(seconds); clock[0]+=max(1,int(seconds*1e9/2)); return False
    class Probe(SafeTransport):
        def _exchange(self,*_): return b'OK\r>'
    monkeypatch.setattr('mokka_ecu_lab.transport.time.monotonic_ns',lambda:clock[0])
    transport=Probe(); starts=[]
    for _ in range(5):
        transport.exchange('ATE0',EarlyWait()); starts.append(transport.last_wire_ns)
    assert all(b-a>=250_000_000 for a,b in zip(starts,starts[1:]))
    assert len(waits)>4  # Every early wake-up is bounded by a fresh deadline check.


def test_new_transport_can_inherit_the_application_send_budget(monkeypatch):
    clock=[1_000_000_000]
    class Wait:
        def is_set(self): return False
        def wait(self,seconds): clock[0]+=max(1,int(seconds*1e9)); return False
    class Probe(SafeTransport):
        def _exchange(self,*_): return b'OK\r>'
    monkeypatch.setattr('mokka_ecu_lab.transport.time.monotonic_ns',lambda:clock[0])
    old=Probe(); old.exchange('ATE0',Wait())
    new=Probe(); new._last_send_ns=old.last_wire_ns; new.last_send=old.last_send
    new.exchange('ATE0',Wait())
    assert new.last_wire_ns-old.last_wire_ns>=250_000_000
