"""Strict request policy and bounded Mode 01 parsing."""
from dataclasses import dataclass
import re

# This policy is code-owned, independent of editable sensor definitions.
LIVE_PIDS = frozenset({0x04, 0x05, 0x0B, 0x0C, 0x0D, 0x0F, 0x10, 0x42, 0x46, 0x5C})
BITMAP_PIDS = frozenset(range(0, 0x100, 0x20))
DISCOVERY_PIDS = frozenset({0x73, 0x78, 0x79, 0x7A, 0x7B, 0x7C, 0x7F, 0x83, 0x85, 0x86, 0x88, 0x8B})
DISCOVERY_SETUP = frozenset({'ATCAF1', 'ATCFC1', 'ATAL'})
ADAPTER_COMMANDS = frozenset({"ATI", "STI", "ATE0", "ATL0", "ATS1", "ATH1", "ATM0", "ATTP0", "ATST64", "ATDP", "ATDPN"})

class UnsafeRequest(ValueError):
    pass

def validate_command(command: str, supported: set[int] | None = None, *,
                     discovery_enabled=False, discovery_supported=None) -> str:
    # Reject injection, repeats, extra data, arbitrary AT/UDS and non-ASCII text.
    if not isinstance(command, str) or not re.fullmatch(r"[A-Za-z0-9]+", command):
        raise UnsafeRequest("Only exact allowlisted commands are permitted")
    command = command.upper()
    if command in ADAPTER_COMMANDS:
        return command
    if command in DISCOVERY_SETUP and discovery_enabled:
        return command
    if re.fullmatch(r"01[0-9A-F]{2}", command):
        pid = int(command[2:], 16)
        if pid == 0 or (pid in LIVE_PIDS and supported is not None and pid in supported):
            return command
        if pid in {0x20, 0x40} and supported is not None and pid in supported:
            return command
        if discovery_enabled and discovery_supported is not None and pid in discovery_supported and pid in (DISCOVERY_PIDS | BITMAP_PIDS):
            return command
    raise UnsafeRequest(f"Request rejected by read-only policy: {command}")

@dataclass(frozen=True)
class Response:
    header: str | None
    data: bytes
    negative_code: int | None = None

    def rejection(self) -> dict:
        if self.negative_code is None:
            raise ValueError("Positive response is not a rejection")
        return {"ecu": self.header, "service": "01", "nrc": f"{self.negative_code:02X}",
                "reason_code": "CONDITIONS_NOT_CORRECT" if self.negative_code == 0x22 else "ECU_REJECTION",
                "reason": "Conditions Not Correct" if self.negative_code == 0x22 else f"ECU rejection NRC 0x{self.negative_code:02X}"}

def parse_obd(raw: bytes, pid: int, command: str = "") -> list[Response]:
    """Strict compatibility wrapper; detailed parsing retains per-ECU errors."""
    from .isotp import parse_reply
    result = parse_reply(raw, pid, command)
    if result.errors:
        raise ValueError('; '.join(e['reason'] for e in result.errors))
    return result.responses


def _legacy_parse_obd(raw: bytes, pid: int, command: str = "") -> list[Response]:
    """Legacy single-frame fallback for ISO 9141/KWP and headerless data."""
    if b">" not in raw:
        raise ValueError("Incomplete adapter reply (missing prompt)")
    responses = []
    for line in re.split(r"[\r\n>]", raw.decode("ascii", "replace")):
        line = line.strip()
        compact = re.sub(r"\s", "", line).upper()
        if not compact or compact == command.upper() or compact in {"SEARCHING...", "BUSINIT:OK", "OK"}:
            continue
        if not re.fullmatch(r"[0-9A-F]+", compact):
            continue
        header = None
        tokens = line.upper().split()
        if len(tokens) > 1 and len(tokens[0]) in {3, 8}:
            header = tokens[0]
            body = ''.join(tokens[1:])
            # Optional one-nibble CAN DLC (AT D1 adapters).
            if len(tokens[1]) == 1:
                body = ''.join(tokens[2:])
        elif len(compact) % 2:
            header, body = compact[:3], compact[3:]
        else:
            body = compact
            if body.startswith("18DA") and len(body) >= 14:
                header, body = body[:8], body[8:]
        if len(body) % 2:
            continue
        data = bytes.fromhex(body)
        if header is not None:
            if not data:
                continue
            if data[0] not in {0x41, 0x7F}:
                if data[0] >> 4 != 0 or not 2 <= data[0] <= 7 or len(data) < data[0] + 1:
                    continue
                data = data[1:1 + data[0]]
        elif len(data) >= 6 and data[3:5] in {bytes([0x41, pid]), b"\x7f\x01"}:
            # ISO 9141/KWP three-byte header and trailing checksum.
            header, data = data[:3].hex(' ').upper(), data[3:-1]
        elif len(data) >= 4 and 2 <= data[0] <= 7 and len(data) >= data[0] + 1:
            # Headerless single-frame replies with a length byte.
            data = data[1:1 + data[0]]
        if data[:2] == bytes([0x41, pid]):
            responses.append(Response(header, data[2:]))
        elif len(data) == 3 and data[:2] == b"\x7f\x01":
            responses.append(Response(header, data, data[2]))
    if not responses:
        raise ValueError("No matching Mode 01 response")
    return responses

def supported_pids(payload: bytes, base: int) -> set[int]:
    if len(payload) != 4:
        raise ValueError("Support bitmap must contain exactly four bytes")
    bits = int.from_bytes(payload, "big")
    return {base + i + 1 for i in range(32) if bits & (1 << (31 - i))}

def support_state(supported: set[int], pages: set[int], pid: int) -> str:
    if pid in supported: return "supported"
    base = ((pid - 1) // 32) * 32
    if base in pages: return "unsupported"
    for earlier in range(0, base, 32):
        if earlier in pages and earlier + 32 not in supported: return "unsupported"
    return "unknown"
