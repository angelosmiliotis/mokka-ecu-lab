# v0.2.13 operation and validation boundaries

The application starts disconnected. Normal Sessions and Benchmark still share
one serialized diagnostic worker, the fixed read-only command allowlist and the
hard **four total requests/second** ceiling. Navigation, idle and offline research
send no diagnostic queries. A later explicit start refreshes evidence rather than
trusting an earlier run's bitmap or samples.

## Normal Session and manual Disconnect

1. Confirm the intended Simulation or outgoing Bluetooth/Serial source in
   **Connection settings**. Press **Connect** on **Session Dashboard**.
2. Press **Start Session**. Recording starts before fresh adapter-protocol,
   supported-PID, configuration and positive-sample verification. Every eligible
   standard PID and eligible RAW-only representation is selected automatically;
   no individual PID checkbox is needed.
3. Before moving, inspect **017A RAW research evidence** where supported. READY
   requires worker-confirmed scheduling and two actually stored positive polling
   replies. Discovery and replay do not count. RAW is not a pressure/soot/ash or
   regeneration decoder.
4. When parked, press **Finish Session**. The worker refuses another polling send,
   allows an already transmitted bounded reply to complete through its prompt,
   closes the recorder and verifies the private export. Progress distinguishes
   Finish requested, finalization and verified export.
5. Successful healthy closure shows **EXPORTED · CONNECTED IDLE**. The same handle
   remains open, with no polling, keepalive, reset, retry or background query.
   Press **Start Session** or use **Benchmark → Start BENCH** for another explicit
   run. It receives a new acquisition context and fresh recorded verification
   over the retained handle; the shared last-send deadline is preserved.
6. Press the visible **Disconnect** when you want to close the connection.

Finish cannot keep an unsafe connection. A missing prompt, uncertain in-flight
Stop/cancellation, port loss, unrecoverable I/O, suspend or application shutdown
closes or isolates it and requires explicit reconnect. A complete CAN body without
the final adapter prompt is not a safely completed transaction. Valid completed
samples remain stored; incomplete bytes remain raw evidence without fabricated
numeric rows. Passive idle checks cannot prove an unplugged ECU is still present;
the next explicit Start performs real verification.

An unconfirmed driver close is isolated from all future acquisition. No replacement
handle is opened automatically. The UI names **RECONNECT REQUIRED** and offers
Disconnect to retry cleanup. Recording/export failure preserves the original
journal and offers explicit **Retry private export offline**. Retry makes no ECU
request and does not turn a failed export into a successful one without verification.

## Sampling goals within four requests/second

The default **Comprehensive · correlated DPF / turbo / SCR** keeps every already
eligible PID. Its bounded weights are:

- Four slots: 017A, VGT, MAP, RPM and MAF dynamic channels.
- Two slots: supported load/speed/coolant, exhaust-temperature, NOx, reagent,
  SCR and PM context channels.
- One recurring slot: other eligible measurements, status and configuration.

The existing smooth weighted scheduler cannot admit another PID or starve a
selected one. These are allocations of one shared budget, not independent per-PID
rates. Increasing VGT/NOx/SCR allocation can make RAW/MAP/MAF slightly slower than
the legacy DPF Priority preset and lengthens low-priority intervals. Receipts name
roles and nominal intervals; recorded per-PID counts/gaps and previous-sample ages
are the evidence. Samples are asynchronous, never simultaneous by assertion.

The optional **DPF + Turbo · critical subset only** favors a smaller subset.
**Comprehensive · legacy DPF priority** preserves the previous allocation for
comparison. Select a goal while parked before Start; do not compare different
profiles as if they collected identical coverage.

## Normal and experimental Benchmark

**Benchmark → 1/2/3/4 req/s → Start BENCH** remains the physical normal path.
Preparation, stationary checks, fixed sixty-second measurement and private export
are automatic. With Keep connected enabled, success retains CONNECTED IDLE.
Another explicit Benchmark or Session uses fresh evidence over the same handle.
Stop, errors or unsafe context fail closed. Speed zero alone does not prove parking
brake, safe transmission, ventilation or absence of another diagnostic client.

**Higher-rate research** now has two clearly different development tools:

- **Validate 5/s engine · FAKE COM** executes actual command writes, fragmented
  serial-byte reads, command policy, ISO-TP parsing, positive support, stationary
  speed/freshness, global accounting and fail-closed lifecycle code against an
  internally constructed memory COM endpoint. Twelve preparation writes remain
  at least 250 ms apart; the transition preserves that gap. Measurement permits
  at most 300 writes over sixty virtual seconds, at least 200 ms apart. Stop and
  injected failures preserve the partial synthetic ledger and never retry/ramp.
- **Run OFFLINE model** retains the older scalar timing/fault arithmetic. It is
  distinct from the byte engine, and neither tool is physical ECU evidence.

**Experimental LIVE remains LOCKED.** The shipped engine has no physical serial
backend, and hardware admission rejects all callers. No JSON, environment flag,
checkbox or imported brief unlocks it. Five/s has not been exercised on a vehicle.
A separate reviewed hardware-enabled build needs immutable private recording,
real clock/suspend/Stop/port-loss validation, independent technical safety review
and new explicit operator authorization for exact rate, duration, commands and
abort rules. Six/s has no inherited approval. See the
[implementation and future authorization plan](V0213_EXPERIMENTAL_BENCHMARK.md)
and [independent software engineering review](V0213_ENGINEERING_REVIEW.md).

## Reports, CURRENT and rollback

The stable Desktop/Start Menu dispatcher, managed CURRENT/ROLLBACK and flat
Reports remain as documented in the [v0.2.12 maintenance workflow](V0212_WORKFLOW.md).
New exports use **Reports/type/one-run-folder**, with original-research.zip,
report.json, report.html and run-metadata.json. History describes recorded run and
verified export outcomes; the current connection badge describes the current
handle. An archived FINALIZING phase or pre-close adapter snapshot alone cannot
prove a handle stayed open after export.

Installing or activating a newer official ZIP requires its exact preview and
approval. The existing shortcut then follows CURRENT without replacement. Source
builds use a bounded private development cache outside the checkout/OneDrive.
No old workspace, private recording, managed build or quarantine is deleted or
moved by this upgrade. Actual cleanup and restore require separate exact approval.

## Next physical trial

While parked, open the selected v0.2.13 build, Connect → Start Session, wait for
the required RAW proof and Finish. Confirm verified export and CONNECTED IDLE;
leave it idle for at least sixty seconds. Start another Session, or a normal 4/s
Benchmark, and verify fresh preflight plus distinct flat Reports. Finish and use
manual Disconnect. An ordinary comparable drive can then measure the correlated
profile's per-PID cadence and coverage. Do not interact with the computer while
driving. There is no physical >4/s test in this plan or authorization in this release.

Physical sensor calibration, undocumented RAW layouts, DPF soot/ash/regeneration,
turbo causality and catalyst efficiency remain unverified. No new numeric decoder
or unsupported/OEM/UDS probe is enabled.
