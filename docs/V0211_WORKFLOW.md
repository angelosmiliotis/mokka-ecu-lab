# v0.2.11 operator workflow

Start the extracted `MokkaECULab/MokkaECULab.exe` with its `_internal` directory beside it. The app opens disconnected. The header identifies Simulation or LIVE; choose deliberately in Connection settings. Default private data remains `%LOCALAPPDATA%/MokkaECULab/data`; an explicit `--data-dir` changes it independently of installation. Existing journals and SQLite stay in their original location for compatibility.

## Next parked benchmark

1. Park, apply the brake, select a safe transmission state, ensure ventilation and follow vehicle/adapter instructions. Close other OBD clients. Pairing in Windows alone does not confirm an open COM handle or ECU communication.
2. Connection settings → Bluetooth serial → select the outgoing port and baud → Benchmark. For an existing installation, confirm its selected port rather than relying on a remembered pairing. No automatic retry or OS settings change is performed.
3. Select **2 requests/second**, leave **Keep connected after success** ON, press **Start BENCH**. This explicit click confirms parked conditions. Connection, current bitmap/configuration/positive checks and stationary speed verification happen before the sixty-second measured window.
4. Wait for **COMPLETED / CONNECTED IDLE · zero polling · private export verified**. Inspect **Open report**, **Open folder** and History. The same handle remains open with no idle requests. There is no automatic next experiment.
5. Select **4**, press **Start BENCH** once. Fresh recorded preflight precedes the same fixed speed/RPM/MAP/MAF mix and another sixty seconds. Compare the two runs in History, including achieved rate, spacing, latency and errors. A COM-open error before sending is a preflight failure, not an ECU capacity result.
6. Press **Disconnect** when finished. Unchecking Keep connected closes automatically after the next successful run. Stop/error/suspension/removal also closes and requires explicit reconnection; there are no hidden wire retries.

For a normal drive, use **Session Dashboard → Connect → Start Session → Finish Session**. Comprehensive is the default; optionally select **DPF + Turbo / Critical subset** before Start to trade broad coverage for cadence within the same budget. Start and Finish while parked. Confirm scheduled `017A RAW` and at least two stored positive frames when supported; no manual PID/RAW selection is required. Physical accuracy and decoder applicability still need independent evidence.

## Reports and old exports

```text
data/
  <existing immutable journals and session database>
  Reports/
    Drives|Benchmarks|FailedTests/YYYY/MM/DD/<Athens-time_type_stable-key>/
      original-research.zip
      report.json
      report.html
      run-metadata.json
  Index/reports.sqlite3
```

Original UTC remains verbatim in metadata; local folder dates use Europe/Athens including daylight saving. Failed COM-open tests have a separate outcome and folder. A ZIP, JSON and HTML are companions of one logical run. History filters date/ECU/app/label text, type, outcome and selected rate. Display labels do not rename immutable IDs. Optional offline annotations record uncertain human Stop/Sport/acceleration markers; they are not ECU-confirmed events.

**Preview legacy COPY migration…** selects one exact old flat export folder and displays every source path/hash/size and destination before approval. The operation copies and verifies, leaves all originals, records checkpoints and safely resumes when repeated. Cancel leaves sources unchanged. No move/delete or destructive rollback is implemented; copied results can remain without changing the old workflow. **Recover verified index** handles an interrupted rename/index checkpoint. **Retry report offline** repairs derived companions without opening a transport. Preserved invalid/incomplete imported companions remain separately named. Disk usage is informational; no automatic purge.

**Export this run as one ZIP…** writes a fresh self-contained private wrapper (optional annotations). Import and offline comparison accept both that wrapper and older Research Bundles. They use the original evidence identity, reject duplicate selections and never upload files. Inspect exports before sharing.

## App Versions

Download an exact published Windows ZIP from the repository Releases page. In **App Versions**, enter its exact tag → **Install official release ZIP…** → inspect the precise COPY preview → explicitly approve. Official GitHub release SHA, ZIP content/runtime and a fresh simulation startup are checked before a new build is accepted. This copies into the managed versions root; it does not overwrite or move the application you are running.

**Inventory / dry-run preview** shows actual launch target, verified CURRENT/ROLLBACK, files/provenance and managed running processes. **Set as CURRENT…** and **Rollback preview…** require their own exact pointer previews. Launch CURRENT uses the separate existing data root. A detected immediate startup failure restores the previous verified pointer; launch that rollback explicitly. This is a managed launcher, not a replacement of arbitrary desktop shortcuts. Close an existing managed application before launching another.

**Inspect exact standalone folder…** is read-only. Unknown files and developer repository output are protected. Old unmanaged builds remain untouched. Operation-lock/interrupted-stage problems stop for inspection rather than deleting evidence. No existing user files have to be moved or deleted to adopt this workflow. Release availability depends on upstream retention; keep a verified rollback locally.

Physical v0.2.11 Bluetooth/vehicle validation awaits a new field bundle. Keep the absolute **4 aggregate req/s**, one worker and read-only allowlist. Rates above four and OEM/UDS remain unavailable.
