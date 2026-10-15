"""Deterministic early Windows wake-up; no serial device or recorded trace."""
from mokka_ecu_lab.transport import SafeTransport
import pytest


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


def test_reduced_adaptive_rate_changes_next_deadline_after_early_wait(monkeypatch):
    clock=[2_000_000_000]
    class Early:
        def is_set(self):return False
        def wait(self,seconds):clock[0]+=max(1,int(seconds*1e9*.4));return False
    class Probe(SafeTransport):
        def _exchange(self,*_):return b'OK\r>'
    monkeypatch.setattr('mokka_ecu_lab.transport.time.monotonic_ns',lambda:clock[0])
    transport=Probe();transport.exchange('ATE0',Early());first=transport.last_wire_ns
    transport.rate=2;transport.exchange('ATE0',Early());second=transport.last_wire_ns
    assert second-first>=500_000_000
    transport.rate=.25;transport.exchange('ATE0',Early())
    assert transport.last_wire_ns-second>=4_000_000_000


def test_operation_window_can_expire_during_early_rate_wait_without_send(monkeypatch):
    from mokka_ecu_lab.transport import Cancelled
    clock=[1_000_000_000];sent=[]
    class Early:
        def is_set(self):return False
        def wait(self,seconds):clock[0]+=max(1,int(seconds*1e9*.5));return False
    class Probe(SafeTransport):
        def _exchange(self,*_):sent.append(self.last_wire_ns);return b'OK\r>'
    monkeypatch.setattr('mokka_ecu_lab.transport.time.monotonic_ns',lambda:clock[0])
    t=Probe();t.exchange('ATE0',Early());t.operation_deadline_ns=clock[0]+200_000_000
    with pytest.raises(Cancelled,match='deadline'):t.exchange('ATE0',Early())
    assert len(sent)==1 and t.last_wire_ns is None
