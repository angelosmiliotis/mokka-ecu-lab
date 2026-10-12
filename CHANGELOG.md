# Changes

## 0.2.3

- Corrected OCT2011 B115 PID 88 to exactly 13 data bytes: current activation/reasons, four latched history blocks and five unsigned kilometre counters. Three-byte layouts are unverified; RAW-only remains an optional numeric bypass. Counter anomalies are surfaced without clipping or inventing sentinels. Vehicle verification stays UNVERIFIED.
- Six-byte 017A remains complete framing with unverified numeric layout. No added/dropped byte, pressure formula or DPF health inference.
- Local versioned JSON knowledge base records provisional identity, code-owned layouts/provenance and per-ECU evidence separately. Hypotheses stay EXPERIMENTAL or explicitly REJECTED.
- Bounded offline bundle analyzer validates checksums, reparses original wire bytes, compares layout/support/framing and byte changes, and shows cached RPM/MAF/speed with timestamps/age. Multiple sessions, ECUs and LIVE/SIMULATED sources stay separate. Original CSV/raw data is unchanged.
- Research view adds catalog, compatibility matrix, byte/context tables, 017A scatter charts, findings and local hypothesis persistence. A definition-only schema provides a future contribution foundation; no remote backend or uploader exists.
- All read-only allowlists and the aggregate 4 req/s ceiling are unchanged. No VIN/identity queries or OEM candidates are enabled. Private data and copyrighted source pages are excluded.


## 0.2.2 — 2026-10-12

- Separate unchecked RAW-only 017A/0188 opt-ins require completed per-ECU discovery, advertised support and a complete prior positive response. Weight 1 shares the unchanged global scheduler/rate cap. Unknown layouts produce no measurements; no request service or allowlist is added.
- Record raw responses, layout/framing evidence and independently timestamped cached RPM/speed without extra queries. Replay stays offline; bundles add raw-observations.json and checksums while preserving originals.
- Expose unchecked NOx selection for documented supported 0183 fields. Preserve all 0185/numeric decoders; explain static warning counters without current SCR-fault inference.
- Add local CSV/Research Bundle trends with separate ECU/mode/source, recorded-point plots and summaries without interpolation or simultaneous-peak assumptions.
- Fixtures are constructed and non-identifying. Private reports, logs, bundles, route timelines and derived private analysis remain outside the public repository and releases. Alternative layouts remain unverified; see research/v0.2.2-layout-verification.md.

## 0.2.1 — 2026-10-12

- Drive Capture preset prepares preferred supported choices without transmitting; explicit Start uses the existing weighted scheduler and unchanged 4 application requests/s cap. Manual advanced PID choices require ECU-specific discovery and valid fields.
- Recording stays open across discovery/monitoring. Stored session evidence and recorded support make exports/replay independent of later connections.
- Export Research Bundle creates a local redacted ZIP with raw, CSV, discovery/support/ECU reports, observed counts/intervals, errors, session/version metadata, markers, manifest and SHA-256 checksums.
- Optional focused dashboard shows seven readings with current/stale/unavailable evidence. Journey Start/End/Note markers are local only; default note text is redacted and queued markers survive canceled receive finalization.
- Original read-only allowlists, OEM exclusions and failure/reconnect rules remain. No physical vehicle validation. See DRIVE_CAPTURE.md for the operator workflow.

## 0.2.0 — 2026-10-12

- Explicit ECU-specific standard diesel discovery and advertised bitmap continuation through E0; separate optional monitoring shares the 4 application requests/s cap.
- Classic CAN ISO-TP reception with sequence/length/source isolation, raw error retention and legacy replay compatibility.
- Twelve documented diesel PID layouts and a sixth Discovery tab with fields, sources, confidence and JSON evidence export. Original dashboard and v0.1.1 fixes remain.
- MD1CS003 D525/D526/D52F/D532 research entries without live reads or numeric guesses. No UDS sessions, security, arbitrary headers, writes or routines.
- 240 passing tests and native Windows synthetic verification. No vehicle connection; modern PID 88 extensions and OEM compatibility remain unverified. Consolidated future steps: research/v0.2-discovery.md.

## 0.1.1

- Parse Mode 01 negative replies, including CAN length/DLC, headerless and legacy frames. Retain NRC/ECU/reason alongside original command and raw reply. Keep positive measurements from other responding ECUs separate.
- Explain NRC 22 as Conditions Not Correct without asserting ignition state or a vehicle fault. Three consecutive ECU failures halt polling; explicit reconnect is required and automatic retries remain absent.
- Show per-ECU stale values, source evidence, actual intervals, recent gaps and current/support coverage. Stop invalidates current coverage immediately. Replay stays offline and cannot create a new live recording; v0.1.0 negative journals are classified during replay without modification.
- Finalize recording on Disconnect/shutdown and support either Stop order. Close previous nonempty sessions on reconnect/source change instead of relabeling simulation as live data. Add Finish session and ignition-off instructions.
- Add optional priorities 1–4 using smooth weighted round-robin; preserve the existing total 4 req/s ceiling, transport ownership, cancellation and exact code-owned read-only allowlists.
- Add regression tests from minimal response strings, loss-of-conditions simulation, session lifecycle, rate cap, source separation and GUI freshness. Full user vehicle logs are excluded.

Vehicle revalidation of this patch is pending. Do not treat software or fixture tests as actual hardware validation.
