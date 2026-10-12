import math
import time
from . import SafeTransport, TransportError, Cancelled

SCENARIOS = ["Normal idle", "Warming up", "RPM variation", "Adapter timeout", "ECU timeout", "Malformed response", "Unsupported PID", "Disconnection", "Multiple ECUs", "Whitespace and echo", "Incomplete reply"]

class Simulator(SafeTransport):
    def __init__(self, scenario="Normal idle"):
        super().__init__()
        self.scenario, self.n, self.started = scenario, 0, time.monotonic()
        self.supported_fixture = {4, 5, 11, 12, 13, 15, 16, 66, 70, 92}
        if scenario == "Unsupported PID": self.supported_fixture.remove(92)

    def _exchange(self, command, stop, timeout):
        if stop.wait(0.015): raise Cancelled("Simulation stopped")
        if command.startswith("AT") or command == "STI":
            return {"ATI": b"ELM327 v1.4b (SIMULATED)\r>", "STI": b"STN SIMULATOR\r>",
                    "ATDP": b"ISO 15765-4 CAN (11 bit, 500 kbaud) SIMULATED\r>", "ATDPN": b"A6\r>"}.get(command, b"OK\r>")
        pid = int(command[2:], 16)
        if pid in {0, 32, 64}:
            supported = set(self.supported_fixture) | {32, 64}
            bits = sum(1 << (31 - (x - pid - 1)) for x in supported if pid < x <= pid + 32)
            payload = bits.to_bytes(4, "big")
        else:
            self.n += 1
            if self.scenario == "Adapter timeout" and self.n % 5 == 0:
                raise TransportError("SIMULATED adapter timeout")
            if self.scenario == "Disconnection" and self.n >= 6:
                raise TransportError("SIMULATED disconnected adapter")
            if self.scenario == "ECU timeout" and self.n % 4 == 0: return b"NO DATA\r>"
            if self.scenario == "Malformed response" and self.n % 4 == 0: return b"7E8 04 41 ZZ\r>"
            if self.scenario == "Incomplete reply" and self.n % 4 == 0:
                raise TransportError("SIMULATED incomplete reply", b"7E8 04 41")
            elapsed = time.monotonic() - self.started
            rpm = 780 + (300 * math.sin(elapsed / 3) if self.scenario == "RPM variation" else 8 * math.sin(elapsed))
            temp = min(90, 25 + elapsed / 3) if self.scenario == "Warming up" else 54
            values = {4: (77, 1), 5: (int(temp + 40), 1), 11: (101, 1), 12: (int(rpm * 4), 2),
                      13: (0, 1), 15: (67, 1), 16: (480, 2), 66: (14100, 2), 70: (63, 1), 92: (110, 1)}
            if pid not in self.supported_fixture: return b"NO DATA\r>"
            val, length = values[pid]
            payload = val.to_bytes(length, "big")
        data = bytes([2 + len(payload), 0x41, pid]) + payload
        line = "7E8 " + data.hex(' ').upper()
        if self.scenario == "Multiple ECUs": line += "\r7E9 " + data.hex(' ').upper()
        if self.scenario == "Whitespace and echo": line = command + "\r\n  " + line.replace(' ', '   ') + "\r\n"
        return (line + "\r>").encode("ascii")
