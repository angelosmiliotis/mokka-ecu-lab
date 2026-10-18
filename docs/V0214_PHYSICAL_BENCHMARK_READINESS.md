# v0.2.14 potential physical five/s backend readiness review

Status: **NOT ADMITTED / NOT IMPLEMENTED FOR HARDWARE / NOT AUTHORIZED TO RUN**.
This software design review is not independent automotive safety approval.
The shipped byte engine remains in-memory fake COM with virtual time. Normal
Session/Benchmark transport still rejects rates above four. There is no hidden
configuration, environment setting or consent checkbox that changes this.

## Proposed separation and admission

A future reviewed build would expose one separate stationary experiment: fixed
`010D`, `010C`, `010B`, `0110`, at five aggregate sends/s, one sixty-second
measurement, at most 300 measurement requests. Preparation and transition stay at
or below four/s. Six/s needs another independent review and exact authorization.
It must reuse one serialized physical owner, never race the normal worker or
silently change SafeTransport's ordinary policy. An immutable admitted run object
would bind rate, duration, commands, protocol, ECU/context and exact build identity.
The operator must approve those parameters after independent technical/safety
assessment, preferably by an automotive professional.

Before admission, collect a matched four/s stationary reference with current
bitmap/positive/layout/configuration evidence. Operator-reported parking brake,
safe transmission, surroundings, ventilation and no competing client are distinct
from measured fresh zero speed. They cannot be proved by an offline model.

## Required physical architecture

- A separately reviewed physical transport path must enforce the admitted plan
  at its only write boundary. One monotonic accountant must include preparation,
  adapter operations, failed/uncertain writes, transition and measurement. No
  catch-up bursts, upward adaptation or second writer are permitted.
- The existing fake byte/parser state machine is reusable evidence, not a physical
  backend. Add real monotonic deadlines and suspend-generation tracking, Windows
  cancellation/port-close semantics and a durable private recorder before any send.
- A fresh speed response must remain within a reviewed age bound. Moving or stale
  speed, changed ECU/protocol/context/port, NRC, framing error, partial prompt,
  timeout, excessive latency, Stop, suspend or port loss aborts the run. Do not
  alternate rates or issue additional stress/recovery probes.
- Record every attempted command, wire-admission time, response boundary, category,
  sample age and terminal reason privately. Preserve partial data atomically on
  disk failure/cancel; block further sends if required provenance cannot persist.
- A sixty-second monotonic measurement deadline, maximum request count and bounded
  current receive are independent limits. After completion, no automatic repeat,
  reconnect, driving use or inherited permission for another rate is allowed.

## Gates still required

1. Independent review of the hardware design and explicit risk/stop procedure.
2. Reviewed real transport/clock/suspend implementation and command admission.
3. Fake serial plus physical failure-injection tests for partial writes/reads,
   prompt loss, port removal, Stop at every boundary, suspension and disk failure.
4. Verification that one global ledger counts every phase, including failed writes,
   with no overlap, overspeed or burst at transitions or deadline boundaries.
5. Matched four/s evidence, fresh support/configuration and operator conditions.
6. Fresh exact operator authorization for one five/s sixty-second fixed-subset run.
7. Private result review of per-PID cadence, usable samples, age, latency and errors;
   hardware capacity and diagnostic safety must remain separate conclusions.

Until these gates are satisfied in a separately reviewed release, **physical five/s
stays locked**. Stationary/low-latency data at four/s does not authorize five/s.
Prefer scientifically useful subsets and slow-status rotation within the existing
budget before increasing throughput. The [prior implementation review](V0213_ENGINEERING_REVIEW.md)
and [five/s fake byte scope](V0213_EXPERIMENTAL_BENCHMARK.md) remain software evidence only.
