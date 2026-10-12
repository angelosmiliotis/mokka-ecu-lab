import threading
import time
import serial
from serial.tools import list_ports
from mokka_ecu_lab.protocols import validate_command

class TransportError(Exception):
    def __init__(self, message: str, raw: bytes = b""):
        super().__init__(message)
        self.raw = raw

class Cancelled(TransportError):
    pass

def discover_ports() -> list[tuple[str, str]]:
    ports = [(p.device, p.description) for p in list_ports.comports()]
    if not any(p[0] == "COM4" for p in ports):
        ports.append(("COM4", "Confirmed outgoing port (currently unavailable)"))
    return sorted(ports, key=lambda p: (p[0] != "COM4", "OBD" not in p[1].upper(), p[0]))

class SafeTransport:
    """All live writes pass policy here, even if the caller is faulty."""
    def __init__(self):
        self.supported: set[int] = set()
        self.discovery_enabled = False
        self.discovery_supported: set[int] = set()
        self.owner = threading.get_ident()
        self.last_send = 0.0
        self.rate = 4.0
        self.last_wire_ns = None

    def exchange(self, command: str, stop: threading.Event, timeout: float = 6.0) -> bytes:
        if threading.get_ident() != self.owner:
            raise RuntimeError("Transport belongs to one serialized worker")
        command = validate_command(command, self.supported,
                                   discovery_enabled=self.discovery_enabled,
                                   discovery_supported=self.discovery_supported)
        self.last_wire_ns = None
        if not 0.25 <= self.rate <= 4:
            raise ValueError("Total request rate must be between 0.25 and 4 Hz")
        if stop.wait(max(0, 1 / self.rate - (time.monotonic() - self.last_send))) or stop.is_set():
            raise Cancelled("Stopped before send")
        self.last_send = time.monotonic()
        self.last_wire_ns = time.monotonic_ns()
        return self._exchange(command, stop, timeout)

    def close(self):
        pass

class SerialTransport(SafeTransport):
    def __init__(self, port: str, baud: int = 115200):
        super().__init__()
        self.baud = baud
        self.port = serial.Serial(port, baudrate=baud, bytesize=8, parity="N", stopbits=1,
                                  timeout=0.05, write_timeout=0.3)

    def _exchange(self, command, stop, timeout):
        raw = bytearray()
        try:
            # No retry after a missing prompt: resynchronization requires reconnect.
            self.port.write(command.encode("ascii") + b"\r")
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if stop.is_set():
                    raise Cancelled("Stopped during receive", bytes(raw))
                chunk = self.port.read(1)
                raw.extend(chunk)
                if chunk == b">":
                    return bytes(raw)
                if len(raw) >= 65536:
                    raise TransportError("Reply exceeds 64 KiB limit", bytes(raw))
            raise TransportError("Adapter timeout / incomplete response", bytes(raw))
        except serial.SerialException as exc:
            raise TransportError(str(exc), bytes(raw)) from exc

    def close(self):
        self.port.close()
