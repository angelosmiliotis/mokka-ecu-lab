import json
import math
from pathlib import Path
from dataclasses import dataclass

VERIFICATION_STATES = {"STANDARD_VERIFIED", "VEHICLE_VERIFIED", "EXPERIMENTAL", "UNSUPPORTED", "INVALID"}

@dataclass(frozen=True)
class Sensor:
    id: str
    name: str
    pid: int
    unit: str
    length: int
    scale: float
    offset: float
    minimum: float
    maximum: float
    metadata: dict

    def decode(self, payload: bytes) -> float:
        if len(payload) < self.length:
            raise ValueError("Truncated sensor payload")
        # Standard CAN padding beyond the documented bytes is allowed.
        value = int.from_bytes(payload[:self.length], "big", signed=False) * self.scale + self.offset
        if not math.isfinite(value) or not self.minimum <= value <= self.maximum:
            raise ValueError("Decoded value outside standardized range")
        return value

def load_registry(path: Path | None = None) -> dict[int, Sensor]:
    definitions = json.loads((path or Path(__file__).with_name("standard.json")).read_text(encoding="utf-8"))
    registry, ids = {}, set()
    required = {"id", "name", "pid", "unit", "length", "scale", "offset", "minimum", "maximum", "service", "positive_response", "layout", "byte_order", "signed", "source_ecu", "limitations", "evidence", "verification", "formula", "validity"}
    for d in definitions:
        if not required <= d.keys() or d["verification"] not in VERIFICATION_STATES:
            raise ValueError("Invalid sensor definition schema")
        pid = int(d["pid"], 16)
        if pid in registry or d["id"] in ids or d["service"] != "01" or d["positive_response"] != f"41{pid:02X}":
            raise ValueError("Duplicate or mismatched definition")
        if d["length"] not in (1, 2) or d["byte_order"] != "big" or d["signed"] is not False:
            raise ValueError("Unsupported standard payload layout")
        for key in ("scale", "offset", "minimum", "maximum"):
            if not isinstance(d[key], (float, int)) or not math.isfinite(d[key]):
                raise ValueError("Invalid numeric schema field")
        if d["minimum"] > d["maximum"]:
            raise ValueError("Invalid validity range")
        ids.add(d["id"])
        registry[pid] = Sensor(d["id"], d["name"], pid, d["unit"], d["length"], d["scale"], d["offset"], d["minimum"], d["maximum"], d)
    return registry

def convert(value: float, unit: str, alternate: bool) -> tuple[float, str]:
    if not alternate:
        return value, unit
    if unit == "°C": return value * 9 / 5 + 32, "°F"
    if unit == "km/h": return value * 0.621371192, "mph"
    if unit == "kPa": return value / 100, "bar abs"
    if unit == "g/s": return value * 3.6, "kg/h"
    return value, unit
