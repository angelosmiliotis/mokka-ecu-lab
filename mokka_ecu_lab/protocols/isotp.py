"""Bounded classic-CAN ISO-TP reception; never emits CAN frames or flow control.

ELM327DSJ pp.13-15,42-44; STN11xx FRPM CAN automatic formatting.
State belongs to exactly one adapter reply and one ECU. Failed ECU streams
cannot contribute decoded bytes; healthy ECU streams remain independent.
"""
from dataclasses import dataclass
import re
from . import Response, _legacy_parse_obd


@dataclass
class ParsedReply:
    responses: list[Response]
    errors: list[dict]


def parse_reply(raw: bytes, pid: int, command: str = '') -> ParsedReply:
    errors, payloads, streams, poisoned = [], [], {}, set()

    def fail(ecu, reason):
        errors.append({'ecu': ecu, 'reason': reason, 'state': 'INVALID'})
        poisoned.add(ecu)
        streams.pop(ecu, None)

    if len(raw) > 65536 or not raw.rstrip().endswith(b'>'):
        return ParsedReply([], [{'ecu': None, 'state': 'INVALID', 'reason': 'Incomplete or oversized adapter reply'}])
    lines = [x.strip() for x in re.split(r'[\r\n>]', raw.decode('ascii', 'replace')) if x.strip()]
    segmented = any(re.match(r'^[0-9A-Fa-f]:', x) for x in lines)
    if segmented:
        # Headerless CAF1 output has no ECU attribution. Reject ambiguous mixed
        # streams instead of inventing a source or associating them by PID.
        lengths = [x for x in lines if re.fullmatch(r'[0-9A-Fa-f]{3}', x)]
        if len(lengths) != 1:
            return ParsedReply([], [{'ecu': None, 'state': 'INVALID', 'reason': 'Ambiguous segmented length/source'}])
        total, buffer, expected = int(lengths[0], 16), bytearray(), 0
        if not 8 <= total <= 4095:
            fail(None, 'Invalid segmented payload length')
        for line in lines:
            if line.upper() == command.upper() or line in lengths or line.upper() in {'SEARCHING...', 'OK'}:
                continue
            match = re.fullmatch(r'([0-9A-Fa-f]):\s*([0-9A-Fa-f\s]+)', line)
            if not match:
                fail(None, 'Mixed or malformed headerless segmented output'); continue
            compact = re.sub(r'\s', '', match[2])
            if len(compact) % 2 or int(match[1], 16) != expected:
                fail(None, 'Segment sequence or hex data invalid'); continue
            data = bytes.fromhex(compact)
            if len(buffer) >= total or not 1 <= len(data) <= (6 if expected == 0 and not buffer else 7):
                fail(None, 'Segment size or duplicate completion invalid'); continue
            needed = total - len(buffer)
            if len(data) < min(needed, 6 if not buffer else 7):
                fail(None, 'Truncated segment'); continue
            buffer.extend(data[:needed]); expected = (expected + 1) & 15
        if len(buffer) != total:
            fail(None, 'Truncated segmented message')
        payloads.append((None, bytes(buffer)))
    else:
        for line in lines:
            compact = re.sub(r'\s', '', line).upper()
            if compact == command.upper() or compact in {'SEARCHING...', 'BUSINIT:OK', 'OK'}:
                continue
            tokens = line.upper().split()
            ecu, body, dlc = None, None, None
            if len(tokens) > 1 and len(tokens[0]) in {3, 8} and re.fullmatch(r'[0-9A-F]+', tokens[0]):
                ecu = tokens[0]
                if len(tokens[1]) == 1:
                    dlc = int(tokens[1], 16) if re.fullmatch(r'[0-9A-F]', tokens[1]) else -1
                    body = ''.join(tokens[2:])
                else: body = ''.join(tokens[1:])
            elif re.fullmatch(r'[0-9A-F]+', compact) and len(compact) % 2 and len(compact) > 3:
                ecu, body = compact[:3], compact[3:]
            elif compact.startswith('18DA') and len(compact) >= 14:
                ecu, body = compact[:8], compact[8:]
            if ecu is None:
                try:
                    for response in _legacy_parse_obd((line+'\r>').encode(), pid, command):
                        payloads.append((response.header, response.data if response.negative_code is not None else bytes([0x41, pid])+response.data))
                except ValueError:
                    if compact.startswith(('41', '7F', '0')):
                        fail(None, 'Malformed headerless response')
                continue
            if not body or len(body) % 2 or not re.fullmatch(r'[0-9A-F]+', body):
                fail(ecu, 'Malformed CAN hex data'); continue
            data = bytes.fromhex(body)
            if dlc is not None and (not 1 <= dlc <= 8 or len(data) != dlc):
                fail(ecu, 'CAN DLC mismatch'); continue
            if ecu in poisoned: continue
            if data[0] in {0x41, 0x7F}:
                if ecu in streams: fail(ecu, 'Unexpected payload inside multi-frame stream')
                else: payloads.append((ecu, data))
                continue
            frame = data[0] >> 4
            if not 1 <= len(data) <= 8:
                fail(ecu, 'Invalid classic CAN frame size'); continue
            if frame == 0:
                length = data[0] & 15
                if ecu in streams or not 2 <= length <= 7 or len(data) < length+1:
                    fail(ecu, 'Invalid or truncated single frame'); continue
                payloads.append((ecu, data[1:1+length]))
            elif frame == 1:
                length = ((data[0] & 15) << 8) | data[1] if len(data) > 1 else 0
                if ecu in streams or len(data) != 8 or not 8 <= length <= 4095:
                    fail(ecu, 'Invalid first frame or duplicate stream'); continue
                streams[ecu] = [length, bytearray(data[2:]), 1]
            elif frame == 2:
                if ecu not in streams:
                    fail(ecu, 'Orphan or duplicate consecutive frame'); continue
                total, buffer, expected = streams[ecu]
                if data[0] & 15 != expected or len(data) < 2:
                    fail(ecu, 'Multi-frame sequence mismatch'); continue
                needed = total-len(buffer)
                if len(data)-1 < min(7, needed):
                    fail(ecu, 'Truncated consecutive frame'); continue
                buffer.extend(data[1:1+needed])
                streams[ecu][2] = (expected+1) & 15
                if len(buffer) == total:
                    payloads.append((ecu, bytes(buffer))); streams.pop(ecu)
            elif frame != 3:
                fail(ecu, 'Unknown ISO-TP frame type')
        for ecu in list(streams): fail(ecu, 'Truncated multi-frame message')
    responses = []
    seen_sources = set()
    for ecu, data in payloads:
        if ecu in poisoned: continue
        if ecu in seen_sources:
            fail(ecu, 'Duplicate or ambiguous response from the same source'); continue
        seen_sources.add(ecu)
        if data[:2] == bytes([0x41, pid]): responses.append(Response(ecu, data[2:]))
        elif data[:2] == b'\x7f\x01' and len(data) == 3: responses.append(Response(ecu, data, data[2]))
        else: fail(ecu, 'No matching Mode 01 service/PID or malformed negative response')
    responses = [r for r in responses if r.header not in poisoned]
    if not responses and not errors:
        fail(None, 'No matching Mode 01 response')
    return ParsedReply(responses, errors)
