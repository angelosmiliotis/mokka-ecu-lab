"""Produce actual simulator→worker→recorder→export→replay demonstration artifacts."""
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mokka_ecu_lab.adapter import AcquisitionWorker
from mokka_ecu_lab.logging import list_sessions, export_csv, export_jsonl
from mokka_ecu_lab.replay import Replay

def main():
    root = Path(__file__).resolve().parents[1] / "samples" / "sessions"
    worker = AcquisitionWorker(root)
    worker.submit("record")
    worker.submit("connect", simulation=True, port="COM4", scenario="Normal idle")
    deadline = time.monotonic() + 9
    acquired = []
    while time.monotonic() < deadline:
        try:
            kind, value = worker.events.get(timeout=.2)
            if kind == 'transaction': acquired.extend(value[1])
        except __import__('queue').Empty: pass
    worker.submit("stop")
    worker.submit("record_stop")
    worker.submit("shutdown")
    worker.join(8)
    assert not worker.is_alive()
    assert len(acquired) >= 10, 'Expected a complete sensor cycle'
    session = list_sessions(root)[0]
    source = root / session['raw_path']
    export_csv(root, session['id'], root.parent / 'simulated-idle.csv')
    export_jsonl(source, root.parent / 'simulated-idle.jsonl')
    replay = Replay(root.parent / 'simulated-idle.jsonl')
    records = 0
    while replay.next() is not None: records += 1
    replay.close()
    assert records == session['requests']
    print(f"SIMULATED end-to-end demonstration: {records} raw transactions, {len(acquired)} decoded readings; CSV, JSONL and replay passed.")

if __name__ == '__main__': main()
