# Architecture

The Qt main thread owns display widgets and bounded previews. One `AcquisitionWorker` thread owns serial/simulator transport, support discovery, polling, SQLite/JSONL recording and streaming replay. A bounded 64-entry command queue and 512-entry UI event queue connect them. Critical state messages replace an old preview when the event queue is full. The GUI drains at most 100 events per 100 ms. The worker records before publishing previews; preview drops never remove on-disk records.

## Modules

| Package | Responsibility |
|---|---|
| `transport` | Port enumeration, 8N1 serial framing, strict pre-write safety validation, rate cap, cancellation, synthetic fixtures |
| `adapter` | Single-worker lifetime, identity/configuration, per-ECU PID discovery, round-robin polling, capture orchestration |
| `protocols` | Fixed command allowlist, positive Mode 01 matching, CAN/legacy single-frame parsing, bitmap semantics |
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

## Storage and failure behavior

The raw JSONL journal is appended, flushed and fsynced before decoded SQLite insertion. SQLite uses WAL and FULL synchronization with a commit per transaction. Raw journal schema version 1 is portable; decoded data reference session/transaction IDs. Power failure between journal and DB commit can lose a decoded row, which remains reproducible from raw bytes. The journal and SQLite are not one atomic transaction; this limitation is documented rather than hidden.

Receive framing reads through the adapter prompt with a six-second outer deadline, short 50 ms reads and a 64 KiB raw cap. Incomplete reply/timeouts close the transport; no new request is sent into an unsynchronized byte stream. Invalid/NO DATA replies do not trigger an immediate retry. Three consecutive invalid ECU transactions stop polling. Reconnect is explicit. Storage errors surface through the event queue and close the transport rather than silently discarding capture.

The recorder uses no unbounded queue. Disk work introduces backpressure directly in the serialized worker. Each receive buffer and UI preview is bounded; research preview is capped at 1,000 samples. Export streams CSV rows and JSONL lines. Long export/import scans currently run on the GUI thread, a known responsiveness limitation for future improvement.

## Replay and future clients

Loading replay closes serial, stops recording and resets support state. Play streams one record at a time with monotonic gaps at chosen speed; Step consumes exactly one transaction. Decoders run on original bytes. Replay timestamps remain original UTC; UI arrival/rate is playback rate. No replay code obtains a serial transport. A future iOS client can share registry/journal concepts; Bluetooth/platform restrictions require separate acquisition code. No iOS functionality exists in this release.
