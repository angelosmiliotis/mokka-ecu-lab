# Session Dashboard · v0.2.8

**Current v0.2.9:** the same three actions now use the reviewed 45-identifier software scope, adaptive pacing at ≤4 total req/s, and automatic companion inventory/performance reports. See [current definitions and benchmark operation](V029_RESEARCH_PERFORMANCE.md). The 22-PID scope described below is the historical v0.2.8 baseline; the source tag for that release is preserved.

The standard workflow has three primary actions: **Connect → Start Session → Finish Session**. Manual Recording, Discovery, Drive Capture, individual PID/RAW selection and independent stop/resume belong to **Advanced / Developer** diagnostics. They cannot replace an active automatic session.

## Normal operation

Configure **Connection settings → Bluetooth / Serial LIVE → the Windows outgoing adapter COM port → 115200** once. A successfully confirmed LIVE connection saves that source and port for the next launch. The app always opens disconnected; a first launch uses Simulation. The standard Connect verifies current Windows port enumeration and then a positive responding CAN ECU. An idle Windows Bluetooth “Not connected” indication does not establish an application failure. No pairing, removal, reset or baud scan is performed.

1. **Connect**. Await **CONNECTED** and the actual responding ECU. This opens no journal. When several ECUs respond, choose one explicitly in Advanced / Developer; an address is not a verified hardware/software/calibration identity.
2. **Start Session**, while parked. This deliberate action authorizes the displayed fixed read-only profile, including eligible RAW evidence. One journal and stable session ID are created before fresh session Discovery. Previously unrecorded connection initialization is honestly labelled **not recorded**. Bitmap `0100` and every advertised continuation are reacquired inside this journal; earlier cached samples cannot substitute. All eligible known standard PIDs are selected with **DPF Research Priority**. No extra Recording, Discovery, consent, PID selection or Export action is required.
3. Await worker states **RECORDING_SETUP → DISCOVERING → CONFIGURING → CAPTURING**. For eligible six-byte `017A`, inspect **READY**, **worker scheduled YES** and **stored six-byte positives ≥2**. Only ordinary acknowledged polling replies successfully appended to this journal count. Discovery, snapshots, replay, another ECU/context and unrecorded replies do not count. Other valid sensors continue if DPF proof remains PARTIAL; the reason is visible. READY certifies stored research evidence, not health, pressure or safe departure.
4. Leave the laptop secured and untouched during the journey.
5. Once parked, **Finish Session**. Await **EXPORTED**. The worker stops acquisition, closes the original journal/database, builds and independently checksum-verifies one private ZIP, then disconnects. The page shows the exact path and **Open Folder**. No manual export is needed.

Default bundle directory: `%LOCALAPPDATA%\MokkaECULab\data\bundles\`. A custom `--data-dir` uses its own `bundles` subfolder. Unique session/attempt filenames prevent ordinary retry collisions. Every real bundle remains private even when notes/identification are redacted; it contains route timestamps and telemetry.

## Scope, fields and cadence

The immutable measurement scope remains **22 Mode 01 PIDs**: basic `0104 0105 010B 010C 010D 010F 0110 0142 0146 015C`; advanced `0173 0178 0179 017A 017B 017C 017F 0183 0185 0186 0188 018B`. “All” means every currently eligible PID within that scope, never arbitrary scanning. Unsupported/unknown bitmaps, incomplete frames, invalid numeric layouts outside the two RAW candidates, and absent fields receive explicit omissions. Every connection/session rechecks eligibility; past support does not authorize this ECU/session.

All validated individual fields are recorded with their original transaction, ECU/source, units and timestamps. NOx absent slots are unavailable, never fabricated zero. Reagent demand/average consumption fields are not proof of current flow; quantized tank-level changes are not measured fluid consumption. SCR current inducement, historical flags and counters have distinct semantics and do not establish component health or DTC presence.

The dashboard's **Sensor catalog** includes decoded/RAW/unavailable/stale states, last query outcome, last valid UTC, actual field counts, adaptive age, nominal cadence, observed mean/max gaps and omissions. Columns have independent scrolling and full tooltips; selecting a row shows its complete details. A failed/cancelled latest query remains visible separately from the last valid measurement. It does not turn that older reading into a new measurement or a Bluetooth diagnosis.

Default weights: `017A=4`, RPM `010C=3`, speed/MAP/MAF/coolant `=2`, all other eligible PIDs `=1`. The existing smooth weighted scheduler preserves low-priority sampling. Nominal interval is `sum(weights)/(weight*selected aggregate rate)`; observed timing can be slower. One serialized application budget covers all initialization, bitmap, Discovery and polling send-starts, including a later connection. The limiter rechecks a monotonic nanosecond deadline after early Windows wait timeouts. The ceiling is **4 total req/s**, not four per sensor.

## Failure, cancellation and recovery

Duplicate Start/Finish and conflicting manual actions cannot create another journal or silently replace the schedule. Communication failure never triggers automatic reconnect. After a failure, finish the existing session to preserve/export its evidence; **Connect** is a subsequent explicit operation.

An intentional receive cancellation is classified separately from transport failures and decoder/layout mismatches. Finish during setup or polling preserves whatever was actually stored. Original journals are retained on export failure. **Retry private export offline** runs with no open connection/recording and uses a fresh ZIP destination after independent checksum validation.

In **Sessions**, select a prior session and use **Recover / retry selected session export offline**. Explicit interrupted recovery preserves the journal bytes and any truncated tail, rejects malformed complete records, reconstructs only missing decoded rows from strict complete standard replies, preserves historical existing rows, and marks recovery provenance/checkpoint limitations. A recent acquisition checkpoint can lag the journal; offline analysis recomputes observations from original bytes. Replay and ordinary private exports remain available in Advanced / Developer.

The bundle includes a non-null acquisition receipt for an automatic run, requested/proposed/effective schedules, original recorded bitmap provenance, actual counts/cadence/errors and DPF proof. Its coordinator snapshot is the journal-close checkpoint; final verification of the ZIP is stored separately in the local database and shown only after success. A ZIP cannot contain its own final SHA-256 as a self-verifying receipt.

## Offline research

**Sessions → Offline DPF RAW evolution…** accepts checksum-verified private bundles and loads them in a background analysis thread. Export fresh private HTML plots and JSON. Recorded journal replies are separated from unrecorded Discovery snapshots; snapshots never count as capture/polling proof. Duplicate snapshots of journal samples are not counted again. Separate bundles, ECUs and LIVE/SIMULATION sources remain separate series.

Plots retain actual UTC points, six-byte payloads and HYPOTHESIS-only byte A / unsigned first-word big/little endian representations. Nearby RPM, MAF, MAP, speed and coolant retain actual prior sample ages, with stale/missing context explicit. Stationary/moving summaries use recent reported speed, not an independently observed motion state. Small isolated samples cannot establish a dynamic model. No pressure formula, regeneration classifier, soot mass, ash mass or DPF-health verdict is selected.

```powershell
MokkaECULab.exe --dpf-bundles private-one.zip private-two.zip --dpf-output fresh-private-dpf.html
```

**Sessions → Offline Sport / Normal comparison…** retains the existing USER_REPORTED anchor/uncertainty workflow and non-causal interpretation. **Session history → offline trends** browses recorded sensors without transmission. [Research roadmap](../research/v0.2.8-roadmap.md) and **Research → Research roadmap** document current evidence gaps and prohibited live candidates.

## Field validation

While parked, verify LIVE identity/current ECU, one session ID, recording before session Discovery, all currently eligible known PIDs, and two genuinely stored six-byte `017A` replies when eligible. Check individual NOx/reagent/SCR fields and observed cadence. After normal driving and parked Finish, verify EXPORTED, adapter disconnected, exact path and non-null receipt, all expected journal/CSV observations and checksums. Keep the real ZIP and any analysis local. Physical v0.2.8 ECU/adapter/drive validation remains pending until this field session.
# v0.2.10 note

The default Comprehensive session still uses **Connect → Start Session → Finish Session** and includes every eligible sensor. The optional pre-drive DPF + Turbo choice explicitly selects a critical subset; its omissions are recorded. The separate visible [Benchmark](V0210_BENCHMARK.md) owns automatic connection/preflight and a fixed sixty-second experiment. It cannot interrupt an existing session. Historical scope/count notes below describe earlier versions.
