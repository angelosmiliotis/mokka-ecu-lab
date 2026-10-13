# Full Auto Research Drive · v0.2.7

Start from a parked vehicle with the laptop secured. Close other OBD clients. The app opens disconnected with Simulation selected; opening a page never connects or probes an ECU.

## Recommended button sequence

1. **Connection settings → Bluetooth / Serial LIVE → outgoing COM port → 115200**. Use COM4 only when Windows identifies it as the outgoing adapter port. Keep **4 total req/s** or a lower selected aggregate rate.
2. **Drive Capture → Comprehensive / All supported sensors**. Optional **DPF Research Priority** keeps all eligible PIDs and changes only weights.
3. Check **I am parked: allow all eligible standard sensors + RAW-only evidence for this preset** once. Press **Start Full Auto Research Drive** once. No individual PID or RAW checkboxes are needed.
4. Wait for acknowledged stages: **RECORDING → CONNECTING → DISCOVERING → CONFIGURED → WAITING_RAW**. The worker records initialization before a new connection, observes the responding ECU, follows advertised standard bitmaps, obtains strict positive samples and revalidates eligibility before activating its schedule. An existing healthy selected connection can be reused explicitly. Multiple ECU responses require choosing the ECU explicitly; identity is never assumed from the vehicle model.
5. Before departure inspect **017A RAW: READY**, **worker scheduled YES** and **stored six-byte positives ≥ 2**. The fixed row shows current ECU bitmap provenance, prior response length/decoder, consent acknowledgment, last stored timestamp/length/bytes. **Auto preflight & coverage** lists every known allowlisted PID, support, positive sample, units, representation, inclusion/omission reason, actual schedule/weight, counts, intervals, ages and gaps.
6. If **PARTIAL** appears, inspect its reason while parked. Other valid sensors can continue. The explicit **Retry Capture Setup** button performs one bounded setup pass only on the same healthy open connection and active recording. It inherits that run's preset consent. It never reconnects automatically or bypasses the existing failure latch. Unsupported/unknown/malformed evidence does not qualify for RAW proof. Stop or abandon the research session while parked if its target cannot be captured.
7. During the journey leave the laptop untouched. A passenger may add a private USER_REPORTED phase note. No modal prompt or repeated consent is required by the automatic monitor.
8. Once parked, **Finish session → wait for recording closed → Disconnect → Export Research Bundle**. Finish normally keeps the adapter open; the existing receive-cancel safety can disconnect if a reply is in flight. Export is explicitly local. The app shows the exact ZIP destination only after success. Keep every actual bundle, journal, route timeline, annotation and report private.

READY certifies stored research evidence only. It does not establish hardware compatibility, safe departure, DPF pressure, soot, component health or a regeneration event. Simulation always says **SIMULATION — synthetic data**. Live readings remain hardware unverified.

## Fixed existing sensor scope

| Scope | Existing allowlisted measurement PIDs |
|---|---|
| Basic | 0104 load, 0105 coolant, 010B absolute MAP, 010C RPM, 010D speed, 010F intake temperature, 0110 MAF, 0142 control-module voltage, 0146 ambient temperature, 015C oil temperature |
| Advanced standard | 0173 exhaust pressure, 0178/0179 exhaust temperatures, 017A/017B DPF pressure definitions, 017C DPF temperatures, 017F engine run time, 0183 NOx, 0185 reagent, 0186 particulate sensor, 0188 SCR inducement/history, 018B DPF regeneration indicator |

All eligible fields from each selected PID are recorded. Advertised support alone does not guarantee a positive sample or valid decoder. Unknown/unsupported bitmaps, incomplete framing, invalid layouts outside the two RAW candidates and fields with no supported values are omitted with reasons. 018B is rechecked in the current ECU context. Bitmap pages are metadata, never sensor polling targets.

The only RAW candidates are existing **017A/0188**. A strictly valid documented layout uses one numeric request representation and preserves its original bytes in the journal. A complete eligible unverified layout uses RAW-only after preset consent; no numeric readings are fabricated. Six-byte 017A stays numerically unverified. Documented seven-byte 017A is a different numeric case; the six-byte RAW research target is then marked not applicable, never invented.

## Scheduling and proof

Comprehensive uses weight 1 for every eligible PID. DPF Priority uses 017A=4, RPM=3, speed/MAP/MAF/coolant=2, all others=1. Existing smooth weighted round-robin and the transport's shared send-start limiter remain unchanged. All application commands, including initialization and Discovery, share that limiter. No extra readiness probes are sent; proof counts ordinary scheduled RAW transactions after successful recorder append, excluding Discovery, another ECU/context/source, replay, canceled/unrecorded frames and duplicate first-proof IDs.

The nominal interval is `sum(weights) / (PID weight × selected aggregate rate)`. It is an estimate. The adapter, storage and serialized worker can lower observed frequency. With many PIDs, individual refresh is several seconds even at 4 total req/s. The coverage matrix reports actual mean/max gap, age, samples and gaps over twice the estimate. Priority tests check minimum sampling and exact long-run weight ratios, not a promised per-PID Hz.

Preflight waits `min(120 s, max(30 s, 3 × largest nominal interval))`. Incomplete proof becomes PARTIAL; ordinary monitoring can continue and later genuinely stored samples can establish READY. A subsequent failed 017A query downgrades readiness. Repeated failures retain the existing transport/failure behavior. No hidden immediate retry, reconnect, OEM query or faster polling is added.

Private session metadata and **acquisition-receipt.json** separate the requested plan, proposed schedule, acknowledged effective worker schedule, RAW consent, raw bitmap bytes/provenance, omitted reasons, stages and post-activation observed outcomes. Counters use constant memory per PID; only the first two proof receipts and last response metadata are retained. Recent state transitions are capped at 64, with an older-transition counter. The UI still previews at most 500 raw records. Receipt snapshots are checkpointed periodically and closed with session metadata; original raw journals are never rewritten. Up to sixteen prior explicit retry attempts are retained in the receipt, with truncation indicated; the original journal remains complete. Power loss can leave a recent metadata checkpoint behind the fsynced journal.

## Private phases and Sport comparison

**Drive Capture → Journey markers → phase → uncertainty → Add USER_REPORTED phase** records a local annotation only. Normal, Sport on/off, City and Open road are user notes, not ECU states. Operate only while stationary or as a passenger. Default exports redact free-text notes and phase labels. **Sessions → Include private phase labels in Research Bundle** explicitly includes labels/uncertainty/provenance for local analysis; notes remain redacted. A redacted bundle still contains private telemetry and timestamps and is never a public-safe driving trace.

Use **Sessions → Offline Sport / Normal comparison…**, select one private bundle, choose its exact ECU/mode/source group, enter or edit a USER_REPORTED Sport on timestamp and uncertainty, confirm provenance and **Compare before / after**. Loading and comparison run in a background analysis thread with no acquisition worker. Editing an anchor invalidates its prior result. Save edits to a fresh private JSON sidecar; original bundles/journals remain unchanged. Comparison exports fresh self-contained HTML with measured-point SVG plots and full private JSON.

Plots use actual UTC instants, independent asynchronous samples and a user uncertainty band. No interpolation is presented as measurement. Statistics include count, maximum, median, p95, descriptive quartiles, observed gaps and MAP saturation at 255 kPa. The uncertainty band is excluded from phase summaries. MAP/MAF comparisons use overlapping 500-rpm, 20%-load and 10-km/h bins with at least five actual observations per phase; cached RPM/load/speed context must be no older than five seconds and its ages remain explicit. Insufficient overlap suppresses comparison. Serially dependent samples and missing pedal/gear/commanded boost prevent causal confidence or a turbo-lag conclusion. All results say **OBSERVATIONAL — NOT CAUSAL**. No new throttle, accelerator or OEM PID is added.

Optional headless private comparison:

```powershell
MokkaECULab.exe --compare-phases private-bundle.zip --phase-annotations private-annotation.json --phase-output private-comparison.html
```

The sidecar must contain exactly one matching Sport on anchor for the checksum-verified bundle and selected ECU/source. Existing files are preserved. Reports compare observations, never establish a Sport toggle or turbo calibration change.

## Validation and limits

See [software checks](../TESTING.md) and [portable synthetic validation summary](../samples/v0.2.7-validation.json). Public tests and screenshots use constructed data and the existing simulator only. Actual vehicle evidence is independently analyzed outside Git, with initial raw bitmap gaps kept separate from recorded support snapshots. No private trace, annotation, derived analysis or SAE document is distributed.

Actual synthetic native screenshots: [before consent](screenshots/v0.2.7/full-auto-before-consent.png), [worker READY and stored RAW proof](screenshots/v0.2.7/full-auto-ready.png), [automatic coverage](screenshots/v0.2.7/full-auto-coverage.png), [recording closed](screenshots/v0.2.7/full-auto-finished.png), [phase statistics](screenshots/v0.2.7/offline-phase-statistics.png) and [UTC measured points](screenshots/v0.2.7/offline-phase-utc-plot.png). These contain no vehicle observations.

Manual capture, replay, offline research and the read-only allowlist remain available. Strict framing, numeric definitions, transport limiter and scheduler are unchanged. Hardware validation of the new automatic preset awaits a real parked-vehicle/drive test. At small resolutions/high DPI, vertical scrolling is expected; tables retain their own horizontal scroll.
