"""Offline hypotheses. No transport imports or live request entry points."""
import math

def interpretations(payload: bytes, scale=1., offset=0.) -> list[dict]:
    if not 1 <= len(payload) <= 8: raise ValueError("Select 1–8 payload bytes")
    if not math.isfinite(scale) or not math.isfinite(offset): raise ValueError("Scale/offset must be finite")
    return [{"order": order, "signed": signed, "integer": int.from_bytes(payload, order, signed=signed),
             "candidate": int.from_bytes(payload, order, signed=signed) * scale + offset,
             "verification": "EXPERIMENTAL"} for order in ("big", "little") for signed in (False, True)]

def compare(candidate: list[float], measured: list[float]) -> dict:
    if not candidate or len(candidate) != len(measured): raise ValueError("Paired measured/candidate series required")
    if not all(math.isfinite(x) for x in candidate + measured): raise ValueError("Non-finite values")
    errors = [a - b for a, b in zip(candidate, measured)]
    return {"n": len(errors), "bias": sum(errors) / len(errors), "mae": sum(abs(e) for e in errors) / len(errors),
            "rmse": math.sqrt(sum(e * e for e in errors) / len(errors)), "verification": "EXPERIMENTAL"}

class RegenerationHistory:
    """Future foundation: requires explicitly vehicle-verified state and distance.

    No current sensor qualifies; uncertain observations are never events.
    """
    def __init__(self):
        self.previous = None
        self.events, self.gaps = [], []

    def gap(self, start, end):
        self.gaps.append({"start": start, "end": end})
        self.previous = None

    def observe(self, timestamp, active, distance, verification):
        if verification != "VEHICLE_VERIFIED" or not isinstance(active, bool) or not math.isfinite(distance):
            raise ValueError("Verified regeneration state and reliable distance required")
        current = {"timestamp": timestamp, "active": active, "distance": distance}
        if self.previous and self.previous["active"] and not active:
            self.events.append({"observed_end": timestamp, "distance": distance, "coverage": "observed transition only"})
        self.previous = current
