# Experimental stationary benchmark in v0.2.13

**Experimental hardware above four requests/second remains LOCKED.** Normal
sessions and Normal Benchmark retain their independent maximum of four total
requests/second. No physical higher-rate test is authorized or performed during
development. Passing a normal benchmark does not establish ECU headroom.

The new `research/experimental_benchmark.py` implements a separate, bounded
request engine for the first candidate experiment: **five requests/second for
sixty seconds**. Its development backend is an in-memory fake COM byte stream.
The engine writes carriage-return-terminated commands, reads fragmented replies,
uses the existing Mode 01 command policy and ISO-TP parser, checks positive
support/response evidence, and records every attempted request and actual fake
write. It exercises protocol and lifecycle code beyond the older scalar timing
model. The virtual clock and constructed replies still provide **no hardware,
Bluetooth, CAN utilization, wall-clock timing or physical sensor validation**.

## Fixed, globally accounted operation

One serialized owner controls the endpoint. There is no second diagnostic writer,
background polling, automatic retry, rate ramp or hidden initialization command.
All fake writes use the same ledger and previous-send timestamp across phases.

| Phase | Commands and bounds | Minimum send gap |
| --- | --- | --- |
| Fresh preparation | Twelve requests: `0100`, then the fixed speed/RPM/MAP/MAF sequence truncated to eleven additional requests | 250 ms, at most 4/s |
| Transition | Same ledger and timestamp; no limiter reset | 250 ms after the last preparation write |
| Measurement | `010D`, `010C`, `010B`, `0110` repeated; at most 300 requests in one 60-second half-open send window | 200 ms, at most 5/s |
| Stop/finalization | Close the experimental fake endpoint; retain partial ledger | Zero requests |

The operation is bounded by **312 total requests**, including preparation.
Only the four already allowed read-only dynamic Mode 01 PIDs and their base
support bitmap are used. The base bitmap and actual positive responses must be
fresh. This is support verification for the fixed mix, not a full ECU inventory.
The ordinary transport and its hard four-request/second guard are unchanged.

Preparation requires stationary speed replies and constructed application/adapter
p95 latency no greater than **150 ms**. Every measured speed reply must be zero.
Before every subsequent send, the age of the latest speed observation must be at
most **1,200 ms**. Speed is requested once per four measured requests, nominally
every **800 ms**. These are reviewable engineering candidates, not demonstrated
safety thresholds. Speed zero does not prove safe parking, brake engagement,
ventilation, transmission position or absence of another diagnostic client.

## Fail-closed behavior

Stop, suspend, shutdown, connection/port/baud/context or ECU change, missing or
stale speed, moving speed, lost port, unread/unsynchronized prompt, competing
writer, NRC, wrong PID, ambiguous/multiple ECU response, invalid frame, adapter
error, partial response, timeout, or excessive latency terminates the operation.
A request/response must fit within its **250 ms** limit and the remaining fixed
measurement window. There is no retry or attempted automatic recovery at a
higher rate. The fake port closes, and completed samples plus the final partial
request remain available in the result ledger. Finalization sends nothing.

The minimum-gap schedule also respects response completion. Slow replies cannot
overlap the next request; fewer requests or an aborted final receive are valid
outcomes. Requested rate and achieved fake throughput are reported separately.
No benchmark success is a vehicle health or safety result.

## Hardware lock and the future authorization step

The release contains **no physical backend for this pathway**. The constructor
accepts only the concrete built-in `FakeScenario`; it constructs its own private
memory endpoint and virtual clock. It accepts no port, transport, callable,
arbitrary response bytes, external clock, subclass or configuration dictionary.
There is no serial/socket/process import or route to an existing live worker.
`request_hardware_experiment(...)` always raises `HardwareLocked`, including when
passed affirmative consent/review booleans. A JSON file, environment variable,
feature flag or checkbox cannot authorize a physical send.

Before a hardware-enabled implementation or any actual five-request/second run:

1. Obtain independent technical safety review, preferably from an automotive
   professional. Review ECU/adapter timing, every send path, global accounting,
   Stop/suspend/loss behavior, deadline handling and private evidence retention.
   State any unavailable expertise or vehicle information explicitly.
2. Produce a separately reviewed hardware-enabled build with an exact immutable
   five-request/second, sixty-second policy. Keep the ordinary four-request/second
   transport policy independent. Review current 4/s reference results from the
   same adapter/ECU and fixed mix; success is admission evidence, not proof of
   capacity at five.
3. Present the operator with the build identity and exact request plan: preparation
   at most 4/s, the four PIDs above, at most 300 measured and 312 total requests,
   no retry/ramp, all abort rules, and the proposed physical procedure. Obtain
   separate explicit approval for this precise experiment.
4. Validate physical port ownership, healthy prompt/context reuse, freshness,
   immediate Stop, actual OS suspend and port loss, private partial export and
   shutdown closure. No initialization, discovery, keepalive or fallback send may
   escape the common accountant. Preparation needing extra setup must end and
   return to the ordinary <=4/s path.
5. Run only while safely stationary in appropriate outdoor conditions, with
   operator control of Stop and no competing OBD client. Preserve a matched 4/s
   reference and review the single 5/s result before considering anything else.

Six requests/second is not implemented by this engine and receives no inherited
approval. No development test, consent to software work or old release approval
satisfies the separate hardware gate.

## Synthetic acceptance and integration API

`ExperimentalFakeCOMBenchmark()` starts in `PREFLIGHT`. Each `advance()` processes
at most one complete command/reply, and `active` becomes false on completion or
abort. `stop()`, `suspend()` and `shutdown()` stop without a write. `snapshot()`
returns detached data with `mode=FAKE_COM_BYTES`, state, virtual countdown,
phase counters, fake write counts, exact byte ledger, send gaps, overlaps,
latencies and categories. `actual_hardware_transmissions` is always zero;
`hardware_state=LOCKED` and `live_enabled=false` are explicit on every result.
`implementation_brief()` exports the fixed scope without granting authority.

New public tests construct all bytes independently. They run the full twelve
preparation and 300 measurement requests, verify **250 ms preparation/transition
and 200 ms measured gaps**, exercise fragmented reception through the actual
parser, and check support, speed, lifecycle, framing, ownership and lock failures.
They also verify the existing ordinary transport rejects a five-request/second
write after a successful fake run. No original vehicle file, route or timestamp
is used in these tests.

For collecting useful driving evidence now, first improve allocation within the
normal <=4/s budget: fast time-related dynamic signals, periodic slower status
signals, and explicit per-PID age/cadence. A larger nominal aggregate count does
not add supported PIDs, resolve undocumented layouts or verify DPF units.
