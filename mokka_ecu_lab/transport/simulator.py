import math
import time
from . import SafeTransport, TransportError, Cancelled

SCENARIOS = ["Normal idle", "Warming up", "RPM variation", "Adapter timeout", "ECU timeout", "Malformed response", "Unsupported PID", "Disconnection", "Multiple ECUs", "Whitespace and echo", "Incomplete reply", "Conditions Not Correct"]
SCENARIOS += ['Diesel discovery', 'Diesel discovery 29-bit', 'Diesel multi-ECU', 'Diesel truncated', 'Diesel unknown page']
SCENARIOS += ['Diesel alternative layouts']

# Constructed, non-identifying payloads. Shape and framing tests, not live logs.
ALTERNATIVE_PAYLOADS = {0x7A: bytes.fromhex('00 C8 00 00 00 00'),
                        0x88: bytes.fromhex('00 22 33 00 64 00 C8 01 2C 01 90 01 F4')}

DIESEL_PAYLOADS = {
    0x73: bytes.fromhex('03 27 10 27 74'),
    0x78: bytes.fromhex('0F 0D 48 10 68 11 30 0E 10'),
    0x79: bytes.fromhex('01 0D 48 00 00 00 00 00 00'),
    0x7A: bytes.fromhex('07 00 FA 27 74 26 7A'),
    0x7B: bytes.fromhex('00 00 00 00 00 00 00'),
    0x7C: bytes.fromhex('03 0D 48 0C E4 00 00 00 00'),
    0x7F: bytes.fromhex('03 00 01 51 80 00 00 0E 10 00 00 00 00'),
    0x83: bytes.fromhex('03 00 96 00 14 00 00 00 00'),
    0x85: bytes.fromhex('0F 00 28 00 32 CC 00 00 00 00'),
    0x86: bytes.fromhex('01 00 50 00 00'),
    0x88: bytes.fromhex('00 00 00 00 00 01 00 00 00 00 00 00 00'),
    0x8B: bytes.fromhex('73 03 80 01 2C 01 5E'),
}

def can_reply(header, pid, payload):
    data = bytes([0x41,pid])+payload
    if len(data) <= 7:
        return header+' '+(bytes([len(data)])+data).hex(' ').upper()
    frames = [bytes([0x10 | (len(data)>>8),len(data)&255])+data[:6]]
    for index,start in enumerate(range(6,len(data),7),1):
        frames.append((bytes([0x20|(index&15)])+data[start:start+7]).ljust(8,b'\x00'))
    return '\r'.join(header+' '+frame.hex(' ').upper() for frame in frames)

class Simulator(SafeTransport):
    def __init__(self, scenario="Normal idle"):
        super().__init__()
        self.scenario, self.n, self.started = scenario, 0, time.monotonic()
        self.supported_fixture = {4, 5, 11, 12, 13, 15, 16, 66, 70, 92}
        if scenario.startswith('Diesel'):
            self.supported_fixture.update(DIESEL_PAYLOADS)
            self.supported_fixture.update({0x60,0x80,0xA0,0xA1})
        if scenario == "Unsupported PID": self.supported_fixture.remove(92)

    def _exchange(self, command, stop, timeout):
        if stop.wait(0.015): raise Cancelled("Simulation stopped")
        if command.startswith("AT") or command == "STI":
            return {"ATI": b"ELM327 v1.4b (SIMULATED)\r>", "STI": b"STN SIMULATOR\r>",
                    "ATDP": b"ISO 15765-4 CAN (11 bit, 500 kbaud) SIMULATED\r>", "ATDPN": b"A6\r>"}.get(command, b"OK\r>")
        pid = int(command[2:], 16)
        if pid in range(0,256,32):
            if self.scenario == 'Diesel unknown page' and pid == 0x80: return b'NO DATA\r>'
            supported = set(self.supported_fixture) | {32, 64}
            bits = sum(1 << (31 - (x - pid - 1)) for x in supported if pid < x <= pid + 32)
            payload = bits.to_bytes(4, "big")
        else:
            self.n += 1
            if self.scenario == "Conditions Not Correct" and self.n >= 4:
                return b"7E8 03 7F 01 22\r>"
            if self.scenario == "Adapter timeout" and self.n % 5 == 0:
                raise TransportError("SIMULATED adapter timeout")
            if self.scenario == "Disconnection" and self.n >= 6:
                raise TransportError("SIMULATED disconnected adapter")
            if self.scenario == "ECU timeout" and self.n % 4 == 0: return b"NO DATA\r>"
            if self.scenario == "Malformed response" and self.n % 4 == 0: return b"7E8 04 41 ZZ\r>"
            if self.scenario == "Incomplete reply" and self.n % 4 == 0:
                raise TransportError("SIMULATED incomplete reply", b"7E8 04 41")
            if pid in DIESEL_PAYLOADS and self.scenario.startswith('Diesel'):
                header = '18DAF110' if '29-bit' in self.scenario else '7E8'
                payload=ALTERNATIVE_PAYLOADS.get(pid,DIESEL_PAYLOADS[pid]) if self.scenario=='Diesel alternative layouts' else DIESEL_PAYLOADS[pid]
                line = can_reply(header,pid,payload)
                if self.scenario == 'Diesel truncated' and len(DIESEL_PAYLOADS[pid]) > 5:
                    line = line.split('\r')[0]
                if self.scenario == 'Diesel multi-ECU':
                    line += '\r'+can_reply('7E9',pid,DIESEL_PAYLOADS[pid])
                return (line+'\r>').encode()
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
        if self.scenario == 'Diesel discovery 29-bit': line = line.replace('7E8','18DAF110')
        if self.scenario == 'Diesel multi-ECU' and pid in range(0,256,32):
            other = {5,32,64,96,120,128,133}
            bits = sum(1 << (31-(x-pid-1)) for x in other if pid < x <= pid+32)
            line += '\r'+can_reply('7E9',pid,bits.to_bytes(4,'big'))
        if self.scenario == "Multiple ECUs": line += "\r7E9 " + data.hex(' ').upper()
        if self.scenario == "Whitespace and echo": line = command + "\r\n  " + line.replace(' ', '   ') + "\r\n"
        return (line + "\r>").encode("ascii")
