"""Strict request policy and bounded Mode 01 parsing."""
from dataclasses import dataclass
import re

# This policy is code-owned, independent of editable sensor definitions.
LIVE_PIDS = frozenset({0x04, 0x05, 0x0B, 0x0C, 0x0D, 0x0F, 0x10, 0x42, 0x46, 0x5C})
BITMAP_PIDS = frozenset({0x00, 0x20, 0x40})
ADAPTER_COMMANDS = frozenset({"ATI", "STI", "ATE0", "ATL0", "ATS1", "ATH1", "ATM0", "ATTP0", "ATST64", "ATDP", "ATDPN"})

class UnsafeRequest(ValueError):
    pass

def validate_command(command: str, supported: set[int] | None = None) -> str:
    # Reject injection, repeats, extra data, arbitrary AT/UDS and non-ASCII text.
    if not isinstance(command, str) or not re.fullmatch(r"[A-Za-z0-9]+", command):
        raise UnsafeRequest("Only exact allowlisted commands are permitted")
    command = command.upper()
    if command in ADAPTER_COMMANDS:
        return command
    if re.fullmatch(r"01[0-9A-F]{2}", command):
        pid = int(command[2:], 16)
        if pid in BITMAP_PIDS or (pid in LIVE_PIDS and supported is not None and pid in supported):
            return command
    raise UnsafeRequest(f"Request rejected by read-only policy: {command}")

@dataclass(frozen=True)
class Response:
    header: str | None
    data: bytes

def parse_obd(raw: bytes, pid: int, command: str = "") -> list[Response]:
    """Single-frame J1979 replies: bare, CAN 11/29-bit (optional DLC), legacy headers.

    Multi-frame payloads are deliberately rejected; these PIDs never need them.
    Raw bytes are retained separately, including echo, padding and prompt.
    """
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
            if data[0] != 0x41:
                if data[0] >> 4 != 0 or not 2 <= data[0] <= 7 or len(data) < data[0] + 1:
                    continue
                data = data[1:1 + data[0]]
        elif len(data) >= 5 and data[3:5] == bytes([0x41, pid]):
            # ISO 9141/KWP three-byte header and trailing checksum.
            header, data = data[:3].hex(' ').upper(), data[3:-1]
        if data[:2] == bytes([0x41, pid]):
            responses.append(Response(header, data[2:]))
    if not responses:
        raise ValueError("No matching positive Mode 01 response")
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
