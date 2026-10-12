# Mokka ECU Lab

A locally runnable Windows 11 desktop application for read-only OBD-II acquisition, recording, replay and offline decoder research. Python 3.12+ / PySide6 / pyserial. No account, telemetry or automatic connection. The first delivery includes ten generic Mode 01 sensors. Manufacturer-specific live requests are intentionally absent.

## Run on this computer

The project environment is already installed. The packaged executable was also built and tested: double-click **release\validated\MokkaECULab\MokkaECULab.exe**. Keep its `_internal` folder beside it. Use this validated folder; earlier build/debug folders are superseded.

For source execution, double-click **launch.cmd**, or from this directory:

```powershell
.\.venv\Scripts\python.exe -m mokka_ecu_lab
```

The application starts disconnected with Simulation selected. Data defaults to `%LOCALAPPDATA%\MokkaECULab\data`, outside this OneDrive workspace. Data is local from the application's perspective; Windows backup/sync policies are under your control.

## Install on another Windows 11 computer

Install Python 3.12 or newer from [python.org](https://www.python.org/downloads/windows/) with the Python launcher. In PowerShell:

```powershell
Set-Location -LiteralPath 'C:\Users\angel\OneDrive\Υπολογιστής\MOKKA ECU LAB'
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[dev]'
.\.venv\Scripts\python.exe -m mokka_ecu_lab
```

Use your copied project path on another machine. The current computer uses a bundled Python 3.12 runtime because its `python` command points to the Windows Store placeholder. If rebuilding the environment here without installing another Python:

```powershell
& 'C:\Users\angel\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[dev]'
```

No activation or PowerShell execution-policy changes are required. `launch.ps1` is also available if your policy allows scripts.

## Offline workflow

1. Leave **Simulation** selected. Choose Normal idle, Warming up or another scenario. Press **Connect**. Allow around four seconds for rate-limited initialization and support discovery.
2. The banner says **SIMULATED**. Initial idle values are approximately 780 RPM, 54 °C and 30% load; these are synthetic fixtures, never vehicle observations.
3. Check sensors in the left panel; drag them to reorder. Select an ECU explicitly when multiple responses are present. Alternate display units do not change stored base units.
4. Press **Start Recording**. You can start recording before Connect to retain initialization and support bitmaps as well. Stop Recording closes the journal and marks the session ended.
5. In **Sessions**, Refresh, select a session, then Export CSV or Export JSONL. Default JSONL exports redact adapter/port identification; diagnostic support export includes originals.
6. **Replay selected** or **Open JSONL replay** disconnects the transport. Use Play at 1×, 2×, 5× or 10×, Pause, or Step one transaction. Decoder outputs are recomputed from original bytes. Replay never creates a live connection.
7. **Raw Data** retains the latest 500 preview rows; select one to see the exact original response in text/hex and transaction metadata. All recorded rows remain on disk regardless of UI preview limits.
8. **Sensor Explorer** shows formulas, evidence and verification. STANDARD_VERIFIED means the generic formula was cross-checked; vehicle support/accuracy is still unverified.
9. **Research** accepts offline payloads or recorded JSONL. Select PID and ECU, byte slice, scale and offset. Compare big/little endian and signed/unsigned hypotheses; optionally supply paired measured values. Plot integer/candidate/reference series and save a reproducible EXPERIMENTAL JSON report. Compare recordings includes per-file transaction/error counts and preview boundaries; it does not time-align separate drives automatically.

The ECU timeout and malformed-response simulations periodically fail. Adapter timeout, incomplete reply and disconnection scenarios stop the transport; press Connect to explicitly reconnect. Unsupported PID omits oil temperature. Stop interrupts waits and prevents new requests; Disconnect also closes the serial port. Recording controls are independent of polling controls.

## Connect the vehicle later — hardware unverified

Park safely, set the parking brake and follow the adapter/vehicle instructions. Close OBDwiz, Car Scanner and any other client first; one client can own COM4 at a time. Plug in/power the MX+, enable Bluetooth and ignition, choose **Bluetooth serial**, **COM4**, **115200**, then Connect. COM3 is the incoming port and is never preferred. COM4 remains manually selectable even when unavailable. Port descriptions may not identify a Bluetooth adapter reliably.

Baud choices 115200/38400/9600 are host settings; no automatic baud scan or persistent adapter change is made. Identity, support discovery and protocol are logged. Adapter connection and ECU communication have separate statuses. If COM4 fails to open, the app reports the error and stays usable offline. No hardware test has been performed in this delivery.

## Samples, tests and executable

`samples/simulated-idle.jsonl` and `.csv` are included and clearly marked synthetic; they were generated by the actual acquisition/recorder path. Run `scripts/generate_demo.py` to recreate the corresponding local `samples/sessions/` SQLite session and original journal (excluded from Git). Import the portable JSONL through Sessions. A truncated final JSONL line can be replayed with a warning; earlier malformed records are reported as errors.

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts\generate_demo.py
.\.venv\Scripts\python.exe scripts\verify_ui.py
.\.venv\Scripts\python.exe -m mokka_ecu_lab --smoke-test --data-dir samples\ui-smoke
```

Optional executable build, using the supplied build script:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\build.ps1
```

The script prints the executable path under `release\<build timestamp>\MokkaECULab\MokkaECULab.exe`. Each build uses a fresh folder to avoid overwriting a running binary or locked OneDrive placeholders. Distribute the entire `MokkaECULab` folder, including `_internal`, rather than just the executable. Source is the authoritative project; binaries do not eliminate the hardware validation boundary.

The checked-in PyInstaller spec excludes foreign ICU DLLs from the builder's PATH. In this environment Poppler's versioned ICU was otherwise collected and caused Qt startup to fail; Qt 6.12 uses the unversioned Windows 11 ICU API. The build deliberately uses the target OS library. It is a Windows 11 build, not a compatibility claim for older Windows versions.

## Limitations

- No manufacturer DPF/AdBlue/SCR PID is verified, queried or fabricated. No regeneration detector is enabled.
- Only the fixed Mode 01 allowlist can transmit live. Editing a JSON definition cannot authorize a new request or diagnostic service.
- Parser handles the single-frame generic replies needed here, including CAN 11/29-bit and common legacy header forms. ISO-TP multiframe reassembly is not implemented. Raw replies are retained for future parser extensions.
- Only aggregate rate is configurable; round-robin polling divides it among selected supported sensors. Adapter commands and support discovery also obey the four-request-per-second cap.
- Recording is synchronous and durable in the worker. Slow storage reduces acquisition rate rather than consuming unbounded memory. UI table history is bounded, and dropped previews are counted.
- Unexpected process termination can leave a session marked Open/interrupted. Complete journal records remain recoverable; an interrupted raw/SQLite pair may lack the last decoded row. Replay reprocesses raw bytes; SQLite reconciliation is not automatic.
- Exports and research imports run in the UI thread and may pause the interface for very large files. Acquisition stays in the separate worker. Do not benchmark long drives with the car until the validation checklist is complete.
- Greek navigation/control labels are optional; full translation is future work. No iOS/CarPlay app is included.

See [SAFETY.md](SAFETY.md), [ARCHITECTURE.md](ARCHITECTURE.md), [SENSOR_REGISTRY.md](SENSOR_REGISTRY.md), [TESTING.md](TESTING.md) and [RESEARCH_NOTES.md](RESEARCH_NOTES.md).
