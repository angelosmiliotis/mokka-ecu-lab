import threading
import time
import pytest
from mokka_ecu_lab.protocols import validate_command, UnsafeRequest, parse_obd, supported_pids, support_state
from mokka_ecu_lab.transport import SafeTransport, SerialTransport, TransportError, Cancelled

@pytest.mark.parametrize('command', ['04', '0902', '0100\r04', 'ATZ', 'ATSP0', 'ATSH7E0', 'ATPP00SVFF', '2701', '2E1234', '3101FF00', '1101', '', '\r', '010C00', '010c ', '0122'])
def test_unsafe_rejected(command):
    with pytest.raises(UnsafeRequest): validate_command(command, {12, 34})

def test_supported_gate_and_bitmap():
    assert validate_command('0100') == '0100'
    assert validate_command('010c', {12}) == '010C'
    with pytest.raises(UnsafeRequest): validate_command('010C', set())
    assert supported_pids(bytes.fromhex('80000001'), 32) == {33, 64}
    with pytest.raises(ValueError): supported_pids(b'\xff', 0)

def test_unknown_support_page_is_not_false_unsupported():
    assert support_state({5,32}, {0}, 66) == 'unknown'
    assert support_state({5}, {0}, 66) == 'unsupported'
    assert support_state({5,32}, {0,32}, 66) == 'unsupported'
    assert support_state({5,32,64}, {0,32}, 66) == 'unknown'
    assert support_state({5,32,64}, {0,32,64}, 66) == 'unsupported'

@pytest.mark.parametrize('raw,headers', [
    (b'010C\r41 0C 0C 30\r>', [None]),
    (b'7E8 04 41 0C 0C 30\r>', ['7E8']),
    (b'7E804410C0C30\r>', ['7E8']),
    (b'18DAF110 04 41 0C 0C 30\r>', ['18DAF110']),
    (b'18DAF11004410C0C30\r>', ['18DAF110']),
    (b'7E8 8 04 41 0C 0C 30 00 00 00\r>', ['7E8']),
    (b' 010C \r\nSEARCHING...\r\n7E8   04  41 0C 0C 30\r7E9 04 41 0C 0C 30\r>', ['7E8','7E9']),
    (b'48 6B 10 41 0C 0C 30 4C\r>', ['48 6B 10']),
])
def test_formats(raw, headers):
    responses = parse_obd(raw, 12, '010C')
    assert [r.header for r in responses] == headers
    assert all(r.data == b'\x0c\x30' for r in responses)

@pytest.mark.parametrize('raw', [b'NO DATA\r>', b'CAN ERROR\r>', b'7E8 04 41 ZZ\r>', b'7E8 04 41 05 20\r>', b'7E8 10 41 0C 00\r>', b'41 0C 00'])
def test_malformed(raw):
    with pytest.raises(ValueError): parse_obd(raw, 12)

class ProbeTransport(SafeTransport):
    def __init__(self): super().__init__(); self.writes = []
    def _exchange(self, command, stop, timeout): self.writes.append((time.monotonic(), command)); return b'OK\r>'

def test_transport_gate_stop_rate_owner():
    transport = ProbeTransport(); stop = threading.Event()
    with pytest.raises(UnsafeRequest): transport.exchange('04', stop)
    assert not transport.writes
    transport.exchange('ATI', stop); transport.exchange('STI', stop)
    assert transport.writes[1][0] - transport.writes[0][0] >= .245
    stop.set()
    with pytest.raises(Cancelled): transport.exchange('ATI', stop)
    assert len(transport.writes) == 2
    result = []
    def other_thread():
        try: transport.exchange('ATI', threading.Event())
        except RuntimeError: result.append(True)
    thread = threading.Thread(target=other_thread); thread.start(); thread.join(); assert result

class FakeSerial:
    def __init__(self, incoming=b'41 0C 0C 30\r>'):
        self.incoming = bytearray(incoming); self.writes = []; self.closed = False; self.received = bytearray()
    def write(self, data): self.writes.append(data)
    def read(self, n):
        if self.incoming:
            chunk = bytes([self.incoming.pop(0)]); self.received.extend(chunk); return chunk
        time.sleep(.001); return b''
    def close(self): self.closed = True

def test_serial_prompt_and_timeout(monkeypatch):
    fake = FakeSerial(); monkeypatch.setattr('mokka_ecu_lab.transport.serial.Serial', lambda *a, **k: fake)
    transport = SerialTransport('COM4'); transport.supported = {12}
    assert transport.exchange('010C', threading.Event()) == b'41 0C 0C 30\r>'
    assert fake.writes == [b'010C\r']
    transport.last_send = 0; fake.incoming.extend(b'41 0C'); fake.received.clear()
    with pytest.raises(TransportError) as error: transport.exchange('010C', threading.Event(), timeout=.05)
    assert error.value.raw == bytes(fake.received)
    assert error.value.raw + bytes(fake.incoming) == b'41 0C'
    assert len(fake.writes) == 2
    transport.close(); assert fake.closed
