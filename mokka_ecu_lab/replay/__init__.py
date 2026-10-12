import base64
import json
from pathlib import Path

class Replay:
    """Streaming, bounded memory. A final truncated journal line is recoverable."""
    def __init__(self, path: Path):
        self.file = path.open(encoding="utf-8")
        self.warnings = []

    def next(self):
        while line := self.file.readline(1024 * 1024 + 1):
            if len(line) > 1024 * 1024:
                raise ValueError("Replay record exceeds 1 MiB limit")
            try:
                record = json.loads(line)
                if record.get("record_type") not in {'transaction','marker'}: continue
                if not isinstance(record.get("monotonic_ns"), int): raise ValueError("Invalid time")
                if record['record_type']=='transaction': base64.b64decode(record["raw_b64"], validate=True)
                else:
                    if record.get('event') not in {'Journey Start','Journey End','Note'}: raise ValueError('Invalid marker')
                    if not isinstance(record.get('timestamp'),str) or not isinstance(record.get('note',''),str):
                        raise ValueError('Invalid marker timestamp/note')
                return record
            except (json.JSONDecodeError, KeyError, ValueError) as exc:
                if not line.endswith("\n"):
                    self.warnings.append("Ignored truncated final journal line")
                    return None
                raise ValueError(f"Invalid replay record: {exc}") from exc
        return None

    def close(self):
        self.file.close()
