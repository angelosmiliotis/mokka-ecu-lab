# Architecture

## v0.2.1 capture and bundles

`capture.py` builds a pure filtered plan; preparing a preset does not touch the worker or transport. Explicit activation revalidates support/fields and feeds the existing PollScheduler. The original basic selection/priorities remain independent. Advanced requests retain their existing scoped transport permissions. Session metadata stores evidence snapshots; advanced raw transactions also retain observed bitmap support for initialization-free replay. `logging/bundle.py` exports a closed selected session locally with atomic ZIP replacement and checksums, independently of current UI state. Marker records extend the journal with a separate record_type, do not increment request/error counts, and are replayed without a transport. A bounded command queue and session-bound pending marker map prevent duplication or attachment to another session during Stop/finalization. Export runs after recording stops; large exports may briefly occupy the UI thread.

## v0.2 Discovery extension

`protocols/isotp.py` returns independently validated responses plus per-source errors; state is local to one reply. `sensors/diesel.py` owns strict historical standard layouts and offline candidates. `discovery.py` builds evidence reports without a transmit API. The worker follows ECU-specific continuation and temporarily enables fixed standard Discovery scope on SafeTransport; monitoring shares PollScheduler with basic sensors. Original bytes and advanced fields use the existing recorder, without journal migration. Replay recomputes fields using recorded support and never creates a transport. The sixth tab shows metadata/export while the dashboard remains ten sensors. See [research](research/v0.2-discovery.md) for revision and vehicle boundaries.

The Qt main thread owns display widgets and bounded previews. One `AcquisitionWorker` thread owns serial/simulator transport, support discovery, polling, SQLite/JSONL recording and streaming replay. A bounded 64-entry command queue and 512-entry UI event queue connect them. Critical state messages replace an old preview when the event queue is full. The GUI drains at most 100 events per 100 ms. The worker records before publishing previews; preview drops never remove on-disk records.

## Modules

| Package | Responsibility |
|---|---|
| `transport` | Port enumeration, 8N1 serial framing, strict pre-write safety validation, rate cap, cancellation, synthetic fixtures |
| `adapter` | Single-worker lifetime, identity/configuration, per-ECU PID discovery, optional smooth weighted round-robin, capture orchestration |
| `protocols` | Fixed/scoped command allowlists, Mode 01 matching, classic CAN ISO-TP and legacy parsing, bitmap semantics |
| `sensors` | Validated JSON registry, standard numeric decoders, units, provenance and verification |
| `logging` | Per-session append-only raw JSONL; SQLite session metadata and separate decoded readings; exports |
| `replay` | Streaming journal reader, truncated final-line recovery |
| `analysis` | Offline candidate integers/scaling, physical-reference metrics, future verified regeneration-history foundation |
| `ui` | Dashboard, Sessions, Raw Data, Sensor Explorer and Research |

## Acquisition flow

User Connect → queued worker operation → open COM port or explicitly synthetic simulator → ATI/STI → fixed benign runtime settings → 0100 / advertised 0120 / advertised 0140 → per-ECU support map → protocol description → supported selected PID round-robin.

All writes, including initialization, pass `SafeTransport.exchange`. It verifies exact syntax and code-owned allowlists and caps total send starts at four per second. Ownership checks prevent concurrent calls from another thread. The cancellation Event interrupts rate waits and serial receive loops. Queued Connect is also canceled by a subsequent Stop; cancellation is cleared when the user submits a fresh Connect or Resume, never later in initialization.

Each transaction receives a unique ID, UTC microsecond timestamp, monotonic nanoseconds, original outbound command/bytes, original inbound bytes as base64, loss-tolerant text preview, adapter/port/protocol/settings, parsed source/payloads, latency, decoder IDs, verification and errors. A `sent` flag distinguishes commands canceled before transmission. Acquisition timestamps are taken at send; clocks serve separate purposes: UTC for review and monotonic for ordering/pacing.

Decode only if the response matches service/PID, the ECU independently advertises support and the standard layout/value validation passes. Never splice responses from separate ECUs. Headerless replies are labeled explicitly; they cannot establish physical ECU identity. A selected ECU drives the dashboard; raw logs retain every reply.

Mode 01 `7F 01 NRC` replies are represented separately from positive sensor payloads. Transactions add `negative_responses` (ECU, service, NRC, reason code/text); `ECU_NEGATIVE_RESPONSE` can coexist with a valid reading from a different responding ECU. NRC 22 is Conditions Not Correct; other codes retain their numeric identity without guessing their meaning. A negative response identifies service 01, not a PID; the requested PID comes from the retained command. No negative payload enters a numeric decoder or support bitmap. These are additive journal fields; original raw bytes and schema-1 replay remain compatible. Legacy INVALID negative records are reclassified for display during replay only, with `original_status` retained.

Each acquisition/replay context has an ID. Changing context clears GUI caches and rejects delayed preview events from the old context. Stop immediately suspends current coverage; worker acquisition events communicate paused/halted states separately from adapter connection. Freshness uses acquisition monotonic timestamps, not delayed GUI arrival. Replay intervals use recorded monotonic gaps, and replay is always displayed as offline evidence. NRC 22 stales all cached readings from the rejecting ECU; a subsequent success refreshes only that sensor. Nominal intervals reflect supported selected weights, while actual mean interval and maximum recent gap use up to 20 recorded success times per ECU/sensor.

Priorities default off, with weights bounded to 1–4 and only code-allowlisted, selected, advertised-supported PIDs eligible. Smooth weighted round-robin prevents starvation; priority changes never alter the transport limiter or live policy. Three consecutive rejected/invalid transactions latch a polling halt; Resume cannot bypass it. Only explicit reconnect resets this halt.

## Storage and failure behavior

The raw JSONL journal is appended, flushed and fsynced before decoded SQLite insertion. SQLite uses WAL and FULL synchronization with a commit per transaction. Raw journal schema version 1 is portable; decoded data reference session/transaction IDs. Power failure between journal and DB commit can lose a decoded row, which remains reproducible from raw bytes. The journal and SQLite are not one atomic transaction; this limitation is documented rather than hidden.

Receive framing reads through the adapter prompt with a six-second outer deadline, short 50 ms reads and a 64 KiB raw cap. Incomplete reply/timeouts close the transport; no new request is sent into an unsynchronized byte stream. Invalid/NO DATA replies do not trigger an immediate retry. Three consecutive invalid ECU transactions stop polling. Reconnect is explicit. Storage errors surface through the event queue and close the transport rather than silently discarding capture.

The recorder uses no unbounded queue. Disk work introduces backpressure directly in the serialized worker. Each receive buffer and UI preview is bounded; research preview is capped at 1,000 samples. Export streams CSV rows and JSONL lines. Long export/import scans currently run on the GUI thread, a known responsiveness limitation for future improvement.

Stop polling and Stop Recording are independent serialized operations and may be submitted in either order. Disconnect/shutdown closes the recorder after the final in-flight transaction has been handled; raw journal counts and SQLite session end are finalized. An empty pre-connect recording is assigned the selected source on initialization. Reconnect closes a nonempty recording rather than relabeling captured simulation as live ECU data. CSV provenance comes from each stored reading's source mode, with explicit source kind. Replay cannot start a new acquisition recording.

## Replay and future clients

Loading replay closes serial, stops recording and resets support state. Play streams one record at a time with monotonic gaps at chosen speed; Step consumes exactly one transaction. Decoders run on original bytes. Replay timestamps remain original UTC; UI arrival/rate is playback rate. No replay code obtains a serial transport. A future iOS client can share registry/journal concepts; Bluetooth/platform restrictions require separate acquisition code. No iOS functionality exists in this release.
