# Mokka ECU Lab

Version **0.2.14** adds **Install & activate verified release**: one approved transaction copies an official SHA-verified build, checks disconnected startup, atomically selects CURRENT and verifies the stable Desktop/Start Menu dispatcher. The approving app closes first; the same shortcuts then follow the new CURRENT without a separate activation step. Previous CURRENT remains rollback. Running version, CURRENT, rollback, known GitHub version and shortcut target are shown separately. Changed/personal shortcuts are preserved and block unattended replacement. A published release is not an owner installation until local deployment and actual Desktop launch have been verified.

After Finish, optional **Verify 60s silent idle** observes only local handle state and the global admitted-send counter, then saves a separate private provenance receipt without modifying the original bundle. It sends no diagnostic query. Capture abort, successful export and connection state are distinct; repeated Conditions Not Correct can show an explicitly uncertain engine/ignition hint while preserving every ECU error. Normal read-only acquisition remains one serialized worker at **≤4 total req/s**. **5/s is fake COM only / physical LOCKED; 6/s is not authorized.** [v0.2.14 workflow](docs/V0214_WORKFLOW.md), [physical-backend readiness](docs/V0214_PHYSICAL_BENCHMARK_READINESS.md), [controlled PID source register](research/V0214_SOURCE_REGISTER.md).

The preceding v0.2.13 scope follows for context:

Version **0.2.13** keeps a healthy connection after **Finish Session**: close recording, verify the private export, then **EXPORTED · CONNECTED IDLE**, with zero idle diagnostic sends. Visible **Disconnect** closes it. Each explicit new Session or Benchmark refreshes the protocol/ECU/support evidence in a new run context over the retained handle. Unsafe replies, missing prompts, port loss, Stop, suspend, shutdown and storage failures fail closed with explicit recovery states.

The default **Comprehensive · correlated DPF / turbo / SCR** preserves all eligible PIDs and redistributes the same four-request budget between dynamics, context and slower status. The legacy and Critical presets remain available. **Higher-rate research** adds a separately implemented five-request byte engine with fragmented **fake COM** I/O, real policy/parser checks, global accounting and abort coverage. **Physical experimental LIVE remains LOCKED**: no serial backend or configuration unlock is shipped. The legacy scalar offline model remains distinct.

Stable **CURRENT/ROLLBACK**, Desktop/Start Menu launcher, flat **Reports/History**, reversible approved workspace quarantine and private data boundaries remain. Normal **Connect → Start Session → Finish Session**, fixed read-only allowlists, one diagnostic worker and **4 total LIVE req/s** are preserved. [v0.2.13 operation](docs/V0213_WORKFLOW.md), [experimental implementation](docs/V0213_EXPERIMENTAL_BENCHMARK.md), [engineering review](docs/V0213_ENGINEERING_REVIEW.md), [PID evidence](research/PUBLIC_PID_SCOPE.md), [validation](TESTING.md).

The historical v0.2.10 workflow disconnected after every benchmark. v0.2.11 supersedes that behavior for successful runs with **Keep connected after success** selected (default ON).

The following v0.2.9 description records the preceding scope; its Advanced-only benchmark UI and 48-send bound are superseded by the new visible sixty-second workflow.

Version 0.2.9 preserves **Connect → Start Session → Finish Session** on the default Session Dashboard, with 23 reviewed standard additions in a fixed 45-identifier scope, current ECU support/positive gates, RAW DPF proof and automatic verified private export/disconnect. Full bitmap inventory, passive OBD timing reports, age-labelled DPF research and adaptive pacing stay within **4 total req/s**. A separate fixed stationary benchmark is available only in Advanced / Developer with explicit consent. No individual PID/RAW checkbox or manual recording/export is needed in normal operation. Unknown identifiers and OEM/UDS requests remain blocked. See [v0.2.9 scope, operation and limits](docs/V029_RESEARCH_PERFORMANCE.md) and [definition review](research/v0.2.9-standard-review.md).

A locally runnable Windows 11 desktop application for read-only OBD-II acquisition, recording, replay and offline decoder research. Python 3.12+ / PySide6 / pyserial. No account, telemetry or automatic connection. The first delivery includes ten generic Mode 01 sensors. Manufacturer-specific live requests are intentionally absent.

## Run on this computer

The project environment is already installed. Download the versioned Windows package from [GitHub Releases](https://github.com/angelosmiliotis/mokka-ecu-lab/releases), extract it and double-click **MokkaECULab/MokkaECULab.exe**. Keep its `_internal` folder beside it. Older local release folders retain their original versions.

For an existing managed Desktop installation, use **App Versions → Install & activate verified release**, review the exact preview and approve closure/upgrade. Then open the same **Mokka ECU Lab** shortcut. Extracting or publishing a portable ZIP alone does not update CURRENT. Conflicting shortcuts require separate review and are never silently overwritten.

For source execution, double-click **launch.cmd**, or from this directory:

```powershell
.\.venv\Scripts\python.exe -m mokka_ecu_lab
```

The application always starts disconnected. A first launch selects Simulation; subsequent launches can reuse the last successfully confirmed source/outgoing port. Data defaults to `%LOCALAPPDATA%\MokkaECULab\data`, outside this OneDrive workspace. Data is local from the application's perspective; Windows backup/sync policies are under your control.

## Install on another Windows 11 computer

Install Python 3.12 or newer from [python.org](https://www.python.org/downloads/windows/) with the Python launcher. In PowerShell:

```powershell
Set-Location -LiteralPath 'C:\Projects\Mokka ECU Lab'
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[dev]'
.\.venv\Scripts\python.exe -m mokka_ecu_lab
```

Replace the example project path with your copied checkout. Use an installed Python 3.12+ runtime; if `python` opens the Windows Store placeholder, use the Python launcher or the explicit path of your installed runtime.

No activation or PowerShell execution-policy changes are required. `launch.ps1` is also available if your policy allows scripts.

## Offline workflow

1. Leave **Simulation** selected. Choose Normal idle, Warming up or another scenario. Press **Start Simulation**. Allow around four seconds for rate-limited initialization and support discovery.
2. The persistent source label says **SIMULATION — synthetic data** and identifies the scenario. Initial idle values are approximately 780 RPM, 54 °C and 30% load; these are synthetic fixtures, never vehicle observations.
3. Choose sensors under **Dashboard → Sensor selection**; drag them to reorder. Select an ECU explicitly when multiple responses are present. Alternate display units do not change stored base units.
4. Press **Start Recording**. You can start recording before Connect to retain initialization and support bitmaps as well. **Finish recording** closes the journal and marks the session ended.
5. In **Sessions**, Refresh, select a session, then Export CSV or Export JSONL. Default JSONL exports redact adapter/port identification; diagnostic support export includes originals.
6. **Replay selected** or **Open JSONL replay** disconnects the transport. Use Play at 1×, 2×, 5× or 10×, Pause, or Step one transaction. Decoder outputs are recomputed from original bytes. Replay never creates a live connection.
7. **Raw Data** retains the latest 500 preview rows; select one to see the exact original response in text/hex and transaction metadata. All recorded rows remain on disk regardless of UI preview limits.
8. **Sensor Explorer** shows formulas, evidence and verification. STANDARD_VERIFIED means the generic formula was cross-checked; vehicle support/accuracy is still unverified.
9. **Research** accepts offline payloads or recorded JSONL. Select PID and ECU, byte slice, scale and offset. Compare big/little endian and signed/unsigned hypotheses; optionally supply paired measured values. Plot integer/candidate/reference series and save a reproducible EXPERIMENTAL JSON report. Compare recordings includes per-file transaction/error counts and preview boundaries; it does not time-align separate drives automatically.
10. In **Research → Offline evidence analyzer**, import existing Research Bundle ZIPs (including legacy eleven-file bundles), choose a session/ECU/source, then inspect Compatibility and SCR / AdBlue summary. **Export private research report** writes full JSON and optional compact HTML; open the HTML locally in a browser. Explicit detailed mode includes raw preview bytes/timestamps. Review both files before sharing. Fresh filenames preserve saved reports. **Open saved analysis** also reads older schema-1 JSON but does not revalidate original ZIP checksums; re-import ZIPs for current bitmap analysis.

The ECU timeout and malformed-response simulations periodically fail. Adapter timeout, incomplete reply and disconnection scenarios stop the transport; press Connect to explicitly reconnect. Unsupported PID omits oil temperature. Stop interrupts waits and prevents new requests; Disconnect also closes the serial port. Recording controls are independent of polling controls.

## Standard diesel discovery

Choose **Diesel discovery** in Simulation, start recording before Connect, then open **Discovery** and select an ECU. **Scan standard PIDs for selected ECU** follows only advertised bitmap continuation and pauses basic polling. Inspect field support, values, raw bytes and documented metadata; export JSON evidence. Completion leaves samples only. **Monitor available standard PIDs** is a separate explicit action sharing the 4 req/s scheduler. Stop cancels it; Resume restores basic polling. OEM rows remain offline research entries. Additional synthetic scenarios cover 29-bit CAN, multiple ECUs, truncation and unknown support pages.

## Connect the vehicle later — hardware unverified

Park safely, set the parking brake and follow the adapter/vehicle instructions. Close OBDwiz, Car Scanner and any other client first; one client can own COM4 at a time. Plug in/power the MX+, enable Bluetooth and ignition, choose **Bluetooth serial**, **COM4**, **115200**, then Connect. COM3 is the incoming port and is never preferred. COM4 remains manually selectable even when unavailable. Port descriptions may not identify a Bluetooth adapter reliably.

Baud choices 115200/38400/9600 are host settings; no automatic baud scan or persistent adapter change is made. Identity, support discovery and protocol are logged. Adapter connection and ECU communication have separate statuses. If COM4 fails to open, the app reports the error and stays usable offline. No hardware test has been performed in this delivery.

## Samples, tests and executable

`samples/simulated-idle.jsonl` and `.csv` are included and clearly marked synthetic; they were generated by the actual acquisition/recorder path. Run `scripts/generate_demo.py` to recreate the corresponding local `samples/sessions/` SQLite session and original journal (excluded from Git). Import the portable JSONL through Sessions. A truncated final JSONL line can be replayed with a warning; earlier malformed records are reported as errors.

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts\generate_demo.py
.\.venv\Scripts\python.exe scripts\verify_ui.py
.\.venv\Scripts\python.exe scripts\verify_discovery.py
.\.venv\Scripts\python.exe scripts\verify_capture.py
.\.venv\Scripts\python.exe scripts\verify_raw_capture.py
.\.venv\Scripts\python.exe -m mokka_ecu_lab --smoke-test --data-dir samples\ui-smoke
```

Optional executable build, using the supplied build script:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\build.ps1
```

The script prints the executable path under `%LOCALAPPDATA%\MokkaECULab\Development\v0.2.14\Candidates\candidate-<timestamp>\MokkaECULab\MokkaECULab.exe`. It refuses a fourth default candidate until existing outputs have been explicitly reviewed or archived. An explicit `-OutputDirectory` must also be fresh. Temporary build work created by that invocation is removed after a strict boundary check; existing builds and personal data are never automatically removed. The GUI package includes its separately built stable dispatcher in `_internal/launcher`. Distribute the entire `MokkaECULab` folder, including `_internal`, rather than just the executable. Source is the authoritative project; binaries do not eliminate the hardware validation boundary.

The checked-in PyInstaller spec excludes foreign ICU DLLs from the builder's PATH. In this environment Poppler's versioned ICU was otherwise collected and caused Qt startup to fail; Qt 6.12 uses the unversioned Windows 11 ICU API. The build deliberately uses the target OS library. It is a Windows 11 build, not a compatibility claim for older Windows versions.

## Limitations

- No manufacturer DPF/AdBlue/SCR PID is verified, queried or fabricated. No regeneration detector is enabled.
- Only the fixed Mode 01 allowlist can transmit live. Editing a JSON definition cannot authorize a new request or diagnostic service.
- Parser handles classic CAN 11/29-bit ISO-TP single/multiple frames with source isolation and strict sequence/length checks, plus legacy generic replies and offline headerless ELM segmentation. Live advanced discovery requires identified CAN sources. CAN FD and extended addressing are absent.
- New standard PIDs are 73, 78, 79, 7A, 7B, 7C, 7F, 83, 85, 86, 88 and 8B. Decoders use documented OCT2011 layouts; PID 88 accepts exactly 13 data bytes (OCT2011 B115); three-byte responses retain raw evidence without numeric fields. OEM D525/D526/D52F/D532 remain research-only. No distance-since-last-regeneration estimate is inferred from standard averages.
- Round-robin is the default. Enable **Use sensor priorities** to assign weights 1–4 to selected supported sensors (initial suggestions: RPM 3, coolant 2, others 1). Weighted scheduling changes each sensor's share of the existing aggregate rate; all adapter commands and vehicle requests still pass the unchanged four-request-per-second cap. Dashboard shows actual mean interval, age, recent maximum gap and current/support coverage; Sensor Explorer shows nominal intervals. These are not guarantees under timeouts or slow storage.
- Before switching ignition off, **Stop Recording and Stop polling, then Disconnect**. Either Stop order is supported; Finish session submits Stop polling followed by Stop Recording. Disconnect and application shutdown also finalize any open recording. Reconnecting closes a nonempty previous session; start a new recording for the new connection/source.
- `7F 01 22` is shown as **ECU_NEGATIVE_RESPONSE / Conditions Not Correct**, separately from malformed data and transport errors. It does not prove an ignition event or a vehicle defect. Raw request/reply bytes remain intact. Three consecutive ECU failures stop polling and require explicit reconnect; there is no automatic retry. A rejected ECU's cached values become stale; another ECU's valid replies remain separate.
- Dashboard evidence distinguishes `ECU_READING`, `SIMULATED` and offline `REPLAY`; cached stale values carry `(last)` and never count as current coverage. CSV includes source mode and source kind. Replay cannot be recorded as a new live session, and source changes clear cached evidence.
- Recording is synchronous and durable in the worker. Slow storage reduces acquisition rate rather than consuming unbounded memory. UI table history is bounded, and dropped previews are counted.
- Unexpected process termination can leave a session marked Open/interrupted. Complete journal records remain recoverable; an interrupted raw/SQLite pair may lack the last decoded row. Replay reprocesses raw bytes; SQLite reconciliation is not automatic.
- Exports and research imports run in the UI thread and may pause the interface for very large files. Acquisition stays in the separate worker. Do not benchmark long drives with the car until the validation checklist is complete.
- Greek navigation/control labels are optional; full translation is future work. No iOS/CarPlay app is included.

See [SAFETY.md](SAFETY.md), [ARCHITECTURE.md](ARCHITECTURE.md), [SENSOR_REGISTRY.md](SENSOR_REGISTRY.md), [TESTING.md](TESTING.md) and [RESEARCH_NOTES.md](RESEARCH_NOTES.md).
