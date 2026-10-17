# Higher-rate research in v0.2.12

**Experimental LIVE above 4 req/s is LOCKED.** Normal sessions and benchmarks
retain the independent hard ceiling of four total requests per second. This
release provides a visible research page, a tested offline timing model and an
exportable engineering proposal. It does not implement a higher-rate hardware
transport or an authorization bypass.

Open **Higher-rate research** in the left menu. The disabled **Experimental LIVE ·
LOCKED** control states the boundary. **Run OFFLINE model** models constructed
responses at a chosen rate from 1 to 6. Its countdown advances in virtual time,
faster than wall time. The ordinary Benchmark rate selector remains 1–4.

The model uses only the fixed standard Mode 01 sequence `010D`, `010C`, `010B`,
`0110`. Twelve modeled preparation requests and a bounded measurement share one
serialized all-request schedule. The minimum modeled send spacing is rounded
up to integer nanoseconds: 200 ms at five and 166,666,667 ns at six. No response
overlaps the next request. Phase counters and timing are reported separately;
actual diagnostic transmissions always equal zero.

**Stop model** retains its constructed partial events. Fault injection covers
Stop, suspend, connection-context/ECU changes, prompt desynchronization, missing
or nonzero speed, NRC, invalid framing, NO DATA, timeout and excessive latency.
Any modeled failure terminates the run without retries or automatic rate changes.
The model does not emulate Bluetooth, CAN arbitration or actual ECU behavior.

## Precise proposed first hardware experiment — still inactive

The proposal is **one stationary five-request/second, 60-second measurement**,
with the same four known PIDs, twelve preparation requests and at most 300
measurement requests. A future separately reviewed global limiter must enforce
at least 200 ms between **all** sends, including preparation and any initialization
or discovery. No unaccounted wakeup or retry is permitted. Six requests/second
requires later independent result review and a new explicit authorization.

Before implementing or running this experiment:

1. Review the exported engineering brief and obtain separate explicit human
   authorization of the exact five-request/second experiment and bound.
   Independent automotive professional review is preferred.
2. Compare a fresh matched normal four-request/second reference. Proposed
   admission criteria are no diagnostic errors, a synchronized prompt and
   application/adapter p95 latency no greater than 150 ms. These are proposed
   admission thresholds, not proven safety or capacity limits. Reuse its verified
   healthy connection and already-confirmed support. The experimental fixed mix
   has no hidden initialization/discovery/wakeup requests: if these are needed,
   abandon preparation and return to ordinary acquisition at no more than four.
3. Audit a separate experimental operation with one serialized writer and one
   global send accountant. The normal transport ceiling must remain unchanged.
4. Require new per-run operator confirmation of safe stationary operation,
   brake, transmission, outdoor ventilation and no competing diagnostic app.
   Verify current speed zero, ECU, context and prompt; speed zero alone does not
   verify parking brake or safe surroundings. Final speed freshness thresholds
   require review in the actual LIVE design.
5. Validate immediate Stop, shutdown/suspend/port-loss closure and immutable
   partial evidence. Abort on any missing/nonzero speed, NRC, invalid frame,
   NO DATA, timeout, context/ECU change or prompt loss. The proposed single
   application latency abort threshold is **250 ms**, also requiring review.
   Preserve evidence, close the experimental operation, and do not retry.

**Export engineering brief** writes a new local JSON file only when requested.
It contains this generic proposal and optional constructed model results, with
no vehicle logs, personal paths, real timestamps or private analyses. Existing
files are never replaced. No imported file, setting or checkbox unlocks LIVE.

End-to-end application/adapter latency is not ECU service time, CAN utilization
or free capacity. A successful four-request/second hardware benchmark does not
establish a safe five- or six-request/second rate. Synthetic passing results do
not satisfy any hardware acceptance gate.
