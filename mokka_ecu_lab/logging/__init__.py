"""Crash-tolerant transaction journal and separate decoded SQLite readings."""
import base64
import csv
import json
import os
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")

def connect_database(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(root / "sessions.sqlite3", timeout=5)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=FULL")
    db.executescript('''
    CREATE TABLE IF NOT EXISTS sessions (
      id TEXT PRIMARY KEY, started TEXT, ended TEXT, mode TEXT, metadata TEXT,
      raw_path TEXT, requests INTEGER DEFAULT 0, errors INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS readings (
      session_id TEXT, transaction_id TEXT, timestamp TEXT, monotonic_ns INTEGER,
      sensor_id TEXT, ecu TEXT, value REAL, unit TEXT, verification TEXT,
      PRIMARY KEY(session_id,transaction_id,sensor_id,ecu));
    ''')
    if "mode" not in {row[1] for row in db.execute("PRAGMA table_info(readings)")}:
        db.execute("ALTER TABLE readings ADD COLUMN mode TEXT")
    db.commit()
    return db

class Recorder:
    def __init__(self, root: Path, mode: str, metadata: dict):
        self.db = connect_database(root)
        self.id = uuid.uuid4().hex
        self.path = root / (self.id + ".jsonl")
        self.file = self.path.open("a", encoding="utf-8", newline="\n")
        self.count = self.errors = 0
        self.db.execute("INSERT INTO sessions (id,started,mode,metadata,raw_path) VALUES (?,?,?,?,?)",
                        (self.id, utc_now(), mode, json.dumps(metadata), self.path.name))
        self.db.commit()

    def append(self, raw: dict, readings: list[dict]):
        # Raw journal first; replay can recover even if SQLite insertion is interrupted.
        journal = dict(raw, session_id=self.id, schema_version=1, record_type="transaction")
        self.file.write(json.dumps(journal, ensure_ascii=False) + "\n")
        self.file.flush()
        os.fsync(self.file.fileno())
        for r in readings:
            self.db.execute("INSERT INTO readings (session_id,transaction_id,timestamp,monotonic_ns,sensor_id,ecu,value,unit,verification,mode) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (self.id, raw["id"], raw["timestamp"], raw["monotonic_ns"], r["sensor_id"],
                 r["ecu"] or "headerless", r["value"], r["unit"], r["verification"], raw.get("mode", "Unknown")))
        self.count += 1
        self.errors += raw["status"] != "OK"
        self.db.execute("UPDATE sessions SET requests=?,errors=? WHERE id=?", (self.count, self.errors, self.id))
        self.db.commit()

    def close(self, evidence=None):
        if not self.file.closed:
            self.file.close()
            ended=utc_now()
            if evidence is not None:
                evidence['acquisition_receipt']['closed_at']=ended
                metadata=json.loads(self.db.execute('SELECT metadata FROM sessions WHERE id=?',(self.id,)).fetchone()[0])
                metadata['capture_evidence']=evidence
                self.db.execute('UPDATE sessions SET metadata=? WHERE id=?',(json.dumps(metadata),self.id))
            self.db.execute("UPDATE sessions SET ended=? WHERE id=?", (ended, self.id))
            self.db.commit()
            self.db.close()
            return ended

    def evidence(self, data):
        """Local session metadata; no request and no change to original journal."""
        metadata = json.loads(self.db.execute('SELECT metadata FROM sessions WHERE id=?',(self.id,)).fetchone()[0])
        metadata['capture_evidence'] = data
        self.db.execute('UPDATE sessions SET metadata=? WHERE id=?',(json.dumps(metadata),self.id))
        self.db.commit()

    def marker(self, event, note='', mode='Unknown', timestamp=None, monotonic_ns=None, phase=None, uncertainty_seconds=0, ecu=None):
        if event not in {'Journey Start','Journey End','Note','Phase'}: raise ValueError('Unknown marker')
        record=dict(schema_version=2,record_type='marker',id=uuid.uuid4().hex,session_id=self.id,
                    timestamp=timestamp or utc_now(),monotonic_ns=monotonic_ns or time.monotonic_ns(),event=event,
                    note=str(note)[:512] if event in {'Note','Phase'} else '',mode=mode)
        if event=='Phase':
            from mokka_ecu_lab.analysis.phases import annotation
            record.update(annotation(phase,record['timestamp'],uncertainty_seconds,ecu=ecu,mode=mode,
                source_kind='SIMULATED' if mode=='SIMULATED' else 'ECU_READING' if mode.startswith('LIVE') else 'UNKNOWN',
                origin='STATIONARY_OR_PASSENGER_MARKER',note=note))
        self.file.write(json.dumps(record,ensure_ascii=False)+'\n')
        self.file.flush(); os.fsync(self.file.fileno())
        return record

def list_sessions(root: Path) -> list[dict]:
    db = connect_database(root)
    db.row_factory = sqlite3.Row
    rows = [dict(r) for r in db.execute("SELECT * FROM sessions ORDER BY started DESC")]
    db.close()
    return rows

def export_csv(root: Path, session_id: str, target: Path):
    db = connect_database(root)
    cursor = db.execute("""SELECT r.timestamp,r.monotonic_ns,r.sensor_id,r.ecu,r.value,r.unit,r.verification,r.transaction_id,
        COALESCE(r.mode,s.mode) AS source_mode,
        CASE WHEN COALESCE(r.mode,s.mode)='SIMULATED' THEN 'SIMULATED'
             WHEN COALESCE(r.mode,s.mode) LIKE 'LIVE%' THEN 'ECU_READING'
             ELSE 'UNKNOWN' END AS source_kind
        FROM readings r JOIN sessions s ON r.session_id=s.id WHERE r.session_id=? ORDER BY r.monotonic_ns""", (session_id,))
    with target.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([x[0] for x in cursor.description])
        writer.writerows(cursor)
    db.close()

def export_jsonl(source: Path, target: Path, diagnostic_support=False, include_private_phases=False):
    if source.resolve() == target.resolve():
        raise ValueError("Export target must differ from source recording")
    with source.open(encoding="utf-8") as src, target.open("w", encoding="utf-8", newline="\n") as out:
        for line in src:
            try: record = json.loads(line)
            except json.JSONDecodeError as exc:
                if not line.endswith('\n'): continue
                raise ValueError("Malformed complete journal line; export stopped") from exc
            if not diagnostic_support:
                if record.get('record_type')=='marker' and record.get('event') in {'Note','Phase'}:
                    record['note']='REDACTED_USER_NOTE'; record['note_redacted']=True
                    if record.get('event')=='Phase' and not include_private_phases:
                        record['phase']='REDACTED_USER_PHASE'; record['phase_redacted']=True
                        record.pop('edited_at',None); record.pop('previous_timestamp',None)
                for key in ('VIN','vin','vehicle_identification_number','owner','personal_identifiers','metadata'):
                    record.pop(key,None)
                record["adapter"] = "REDACTED"
                record["port"] = "REDACTED"
                # Identification replies themselves may contain a device serial/name.
                if record.get("command") in {"ATI", "STI"}:
                    record["raw_b64"] = base64.b64encode(b"REDACTED\r>").decode()
                    record["raw_text"] = "REDACTED\r>"
                    record["redacted"] = True
            out.write(json.dumps(record, ensure_ascii=False) + "\n")
