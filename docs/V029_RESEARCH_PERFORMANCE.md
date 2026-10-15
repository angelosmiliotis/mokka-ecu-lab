# v0.2.9 standard inventory, DPF research and performance

Normal operation remains **Connect → Start Session → Finish Session**. Start records fresh per-ECU bitmap Discovery, checks strict positive field layouts, then collects every eligible known PID with DPF Research Priority. No individual PID/RAW checkbox, separate recording or export is required. Finish closes the journal, verifies one private Research Bundle, creates a private companion OBD inventory/performance HTML+JSON report and disconnects. The app always launches disconnected.

## Fixed standard scope

The code-owned scope now contains **45 non-bitmap Mode 01 identifiers**, comprising the previous 22 and 23 reviewed additions. This is a maximum software scope, not a claim that a vehicle implements 45 sensors. Current affirmative ordered support bits and a complete valid positive field are required. Invalid/no-data candidate replies receive explicit omissions, and invalid candidates are removed from polling. A true transport failure stops acquisition; reconnect is always explicit. No arbitrary advertised identifier is probed.

| Added requests | Data / interpretation |
|---|---|
| 0111, 0149, 014A, 014C | Reported throttle/pedal positions and throttle command; no actuator command is transmitted |
| 011F, 0121, 0130, 0131, 014D, 014E | Run-time, MIL-related history, warm-up and DTC-clear counters; nonzero history is not a current fault |
| 0123, 012C, 012D, 0133, 013C, 015E | Gauge rail pressure, EGR command/error, absolute barometer, catalyst temperature and average fuel rate |
| 011C, 0151 | Encoded OBD compliance/fuel type; unknown/reserved values remain unavailable |
| 014F, 0150 | Decoder range configuration, not additional physical sensors; current same-ECU configuration changes MAP/MAF scaling when nonzero |
| 0171 | VGT positions/loop status; unsupported slots and reported unreliable data do not become measurements |
| 018C | Eight individually flagged oxygen concentration/lambda slots in the complete 17-byte historical layout |
| 018F | Signed normalized PM-sensor output and sensor status; PM-sensor regeneration is not DPF regeneration, and this is not soot mass |

Definitions were reviewed against **SAE J1979-DA OCT2011**, with edition/table references in [the decoder records](../mokka_ecu_lab/sensors/extended.py) and independent synthetic tests. Exact vehicle calibration and newer layouts remain unverified. `0101` is documented but its full readiness decoder is deferred; `019D` has no verified applicable definition. Both remain outside the live policy, together with all OEM/UDS candidates. [Review matrix](../research/v0.2.9-standard-review.md).

When advertised 014F/0150 configuration lacks a valid current response, new live MAP/MAF numeric interpretation fails closed. Historical CSV/journals are preserved, and offline analysis reports its historical/default-scaling limitation instead of silently rewriting old measurements.

## Inventory and passive benchmark

**Sessions → Offline ECU inventory / OBD performance…** opens one or more checksum-verified private bundles. It sends no commands. Inventory separates advertised support, unsupported/unknown evidence, documented-but-unimplemented definitions, tested decoder implementation, response observation and layout-unverified RAW facts. Exact bitmap bytes, source/ECU, timestamps and transaction references form a separate ledger. Unanchored, conflicting, malformed or reserved bitmap evidence cannot establish support. Bitmap page continuations are excluded from measurement/status counts.

Multiple bundles retain separate traces. Comparisons show address/source support-set changes in caller-selected order, with UNKNOWN distinguished from unsupported. A common CAN response address is not proof of identical hardware/calibration. The report remains private even with redacted port/identity fields.

Passive performance uses existing recorded send starts and replies: interval distributions, end-to-end latency p50/p90/p95/p99/max, overlapping jitter windows, observed PID gaps, framed positives, recorded numeric-decoding annotations and genuine six-byte RAW polling counts. Transport, framing/protocol, ECU NRC, complete NO DATA, decoder layout and intentional cancellation remain separate. Only explicit retry annotations are counted; ordinary repeated polling is not called a retry.

Count/span and interval/span rates are both shown; short endpoint spans can bias count/span upward. Latency/policy slack and the application occupancy proxy are **not ECU capacity, bus utilization or authorization for a higher rate**.

```powershell
MokkaECULab.exe --obd-bundles private-one.zip private-two.zip --obd-output fresh-private-obd.html
```

## Adaptive pacing and fixed stationary benchmark

One serialized worker controls pacing. Automatic standard sessions adapt within **0.25–4.0 total req/s**, starting at the selected ceiling. Per-request bounded latency baselines, a 30-second cooldown and prolonged stable reply counts permit cautious recovery; genuine communication deterioration reduces rate promptly. Numeric values, decoded-layout mismatch, absence of numeric fields, NO DATA and intentional cancellation never masquerade as overload feedback. The transport remains the hard boundary, including initialization, Discovery and later connections. No additional probes are used.

For a larger eligible set, DPF Priority protects MAP/MAF/speed context with bounded weights while retaining every eligible low-priority PID. Every retained PID has weight at least one. More identifiers share the same aggregate budget; actual per-field cadence and asynchronous age are displayed rather than promising a high refresh rate for every sensor.

The separate **Advanced / Developer → Stationary benchmark** is an explicit opt-in, fixed experiment. Confirm parked conditions, safe transmission, engaged brake, ventilation and no other OBD client. These are user-reported conditions. Prepare a connected idle adapter with completed current Discovery and recently verified positive RPM/MAP/MAF; no automatic session or recording may be open. One to three of those verified PIDs form the fixed repeated subset. Pretest original positive replies and bitmap provenance are saved separately as **unrecorded pretest evidence**, not benchmark polling proof.

Select 1, 2 or 4 total req/s within the configured ceiling; default is **2**. The hard bounds are **48 requests / 60 seconds**. NRC, transport/protocol failure, cancellation or excessive end-to-end latency aborts the experiment; there is no automatic reconnect or extension. Completion/abort closes its journal, exports private evidence and disconnects. The ordinary three-action workflow is unaffected. Higher-than-four LIVE tests are not implemented or authorized.

## DPF RAW research and next field check

Six-byte 017A remains RAW-only. Private reports retain all bytes and actual UTC points, label alternative integer/endian representations as hypotheses, add prior RPM/MAF/MAP/load/speed/coolant with actual ages, and show speed-derived stationary/moving/unknown groups. Descriptive Pearson/Spearman correlations use genuine recorded RAW-only polling when available, with age/coverage warnings and serial-dependence limits. Observed increment GCD and zero-byte ranges describe this dataset, not physical resolution or a pressure formula. Scatter plots do not establish causality, regeneration, soot, ash or health.

Next stationary LIVE validation: run the same three actions; inspect fresh declared inventory, each newly eligible PID's exact layout/field flags, 014F/0150 scaling provenance, preserved prior PID coverage and 017A scheduled/stored≥2 READY. Finish must produce a verified bundle, companion report and disconnected adapter. Review latency/error categories/cadence offline first. The optional fixed stationary benchmark should initially use 2 req/s after explicit preparation. **v0.2.9 hardware validation is pending**, and no higher rate or unknown OEM/UDS request is part of this plan. Real bundles/reports/charts remain local and private.
