# v0.2.13 software engineering review

This document records source and synthetic test review. It is **not an automotive
safety assessment, physical ECU validation, hardware approval or operator consent**.
No vehicle data is included. A successful fake-COM test is insufficient authority
to transmit above the normal four-request/second ceiling.

## Review separation and scope

The developer of the new experimental byte engine independently reviewed the
normal Session lifecycle, scheduling and UI changes. A different reviewer reviewed
the experimental engine. Review covered the shared worker ownership, immutable
journal/export boundary, retained-handle reuse, cancellation, passive idle checks,
source/port/context freshness, UI state claims and the distinction between fake
byte execution and the legacy scalar timing model. Neither reviewer claims
independent automotive expertise or a physical higher-rate test.

## Session and ordinary scheduling review

The intended successful Finish path stops future polling, permits the current
bounded response to complete and be recorded, closes the recorder, verifies the
private bundle and retains only a healthy synchronized handle. Idle has no
diagnostic request, keepalive, reset or hidden reconnect. Each explicit new
Session/Benchmark clears old support/sample gates, refreshes adapter protocol and
positive ECU evidence, and preserves the same global transport send clock.

The review raised the following findings. The corresponding implementation fixes
and synthetic regression coverage are present; final full-suite and packaged
validation results are recorded separately before release:

- **Retained responder:** Benchmark reserves the existing confirmed ECU before
  clearing old support and rejects a changed fresh responder. Fresh support does
  not authorize a silent source/context change.
- **Close exception:** A failed OS/driver close isolates the resource from every
  acquisition path, reports that closure is unconfirmed, and blocks replacement
  COM handles. Explicit Disconnect can retry cleanup; offline export and worker
  shutdown remain possible without diagnostic sends.
- **Finish acknowledgement:** Acquisition snapshots no longer clear a pending
  Finish merely because a response completed. The UI waits for the corresponding
  worker finalization acknowledgement and describes pending work explicitly.
- **Retained pacing:** Fresh pacing and the transport rate are reset together for
  a new explicit acquisition. The shared last-send timestamp is retained and the
  ordinary hard four/s ceiling remains in force.
- **Early storage failure:** The first finalization marker/checkpoint write is
  inside the failure/recovery boundary. Marker, evidence, close and export faults
  preserve original journal bytes and permit explicit offline recovery.
- **Fake validation input:** Invalid fake-fault/request-index combinations produce
  a visible BLOCKED explanation. The UI distinguishes 250 ms preparation and
  transition timing from 200 ms measured timing.

Inactive failure-state cleanup now publishes a fresh Session acknowledgement too,
so a successful Disconnect retry clears an isolated-handle warning without losing
the failed export's recovery identity. Active partial/preflight failure snapshots
retain a pending Finish until finalization is acknowledged. These final review
fixes have dedicated synthetic coverage. The list is not a claim that all release
gates have passed: the final validation record reports full-suite, native Windows
and packaged results and remaining physical constraints.

The correlated sampling profile changes only already eligible PID weights under
the unchanged <=4/s boundary. The smooth weighted scheduler bounds weights 1–4
and gives slower eligible status/configuration PIDs recurring slots. All support,
strict positive/sample and exact-layout gates still apply. Requested nominal
intervals remain estimates; recorded intervals and sample ages are evidence.
Independent timestamps must never be presented as simultaneous measurements.

## Experimental engine review boundary

The shipped separate engine is fixed to five requests/second, sixty virtual
seconds and four already allowed standard PIDs, with twelve <=4/s preparation
requests and at most 300 measured requests. One accountant covers all fake writes,
including preparation and the transition; the ordinary transport's four/s guard
does not change. Fragmented fake serial bytes pass through the real command
validator and ISO-TP reply parser, positive support/layout/speed checks and bounded
receive handling. This is more implementation coverage than scalar arithmetic,
while still being entirely offline.

The engine constructs its own concrete in-memory endpoint. It accepts no physical
port, arbitrary backend, transport callback, imported vehicle bytes or caller clock.
Hardware admission always raises, regardless of configuration or consent booleans.
The UI names fake COM, virtual time, zero hardware transmissions and LOCKED LIVE
explicitly. Exporting a generic engineering brief does not change authorization.

The engine's partial ledger is detached in-memory evidence, not a hardware recorder
or OS timing proof. A future physical implementation requires a separately reviewed
hardware adapter path, real monotonic/suspend handling, immutable private recording,
actual Stop/port-loss validation and independent safety assessment, followed by
separate exact operator authorization. Six/s has no inherited permission.

The independent engine code review checked these concrete boundaries:

- Imports include the existing pure command/parser modules and standard-library
  helpers, with no serial, socket, native device, process or live-worker import.
- Exact concrete fake scenario types are required; subclasses, dictionaries,
  arbitrary endpoints, callables and external clocks cannot supply a backend.
- The single fake endpoint records each command write, and engine evidence is
  checked against that write history. The same all-phase accountant enforces
  preparation, transition and measurement gaps, response serialization and the
  maximum 312-request bound.
- The hardware admission function is unconditional. Consent/review booleans or a
  generic exported JSON brief never enable a physical request.
- All timing is virtual. Tests exercise the real byte/policy/parser state machine,
  but do not exercise physical OS suspend, Bluetooth scheduling, CAN arbitration,
  ECU loading, calibration or transport shutdown timing.
- Future hardware work remains contingent on a separately reviewed physical
  backend, real monotonic/suspend-generation handling, immutable private recording
  and physical failure validation, independent safety review and a new exact
  operator approval. This release supplies none of those permissions implicitly.

See [the experimental implementation scope](V0213_EXPERIMENTAL_BENCHMARK.md) for
the fixed request plan, candidate thresholds, abort list and future approval steps.

## Required release evidence

Use synthetic public fixtures only. Run the full regression suite, fragmented
fake-COM lifecycle transitions, export-failure recovery, unchanged normal rate
guards, the full 312-request experimental fake run and failure matrix, native
Windows GUI/scaling checks, packaged executable workflows, source/package parity,
rollback/launcher verification and a complete publication privacy audit. Physical
Bluetooth/ECU results require a later explicitly controlled field trial and cannot
be inferred from these checks.
