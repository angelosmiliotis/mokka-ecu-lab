# PID research scope for v0.2.12

This note contains no vehicle packets, capture identifiers, private measurements, original hashes or driving chronology. The private evidence register is stored outside the repository. Reproducing recorded CSV from packet bytes checks software consistency; it does not independently calibrate a sensor or establish component health.

## Evidence gates

Evaluate each PID and each field separately:

1. **ADVERTISED** — affirmative, ordered current bitmap evidence.
2. **RECORDED POSITIVE** — a real positive reply in the selected recording. A snapshot outside its journal is not proof of recording or polling.
3. **FRAMED** — correct service/PID, ECU source and complete transport framing.
4. **LAYOUT VERIFIED** — the applicable documented length, flags, reserved bits and encodings pass.
5. **NUMERIC** — a supported field can be decoded using valid current configuration.
6. **PHYSICAL UNVERIFIED** — generic arithmetic still lacks independent vehicle calibration.

A bitmap bit does not establish a decoder. A positive reply does not establish its physical meaning. Unsupported, missing, stale and layout-unverified fields remain distinct from a numeric zero. Numeric field counts include configuration, status and historical counters; they are not counts of independent physical sensors. Benchmark discovery is intentionally partial and must not be compared with a complete drive inventory as if missing pages meant lost support.

## Decoder review register

| PID or group | Existing interpretation | Required next evidence / limitation |
|---|---|---|
| `017A` | Exact reviewed historical layout, or preserved RAW when that layout fails | An applicable primary definition for any alternative length, field flags, signedness, scaling and units. No pressure, soot, ash or regeneration formula is selected from RAW patterns. |
| `018C` | Numeric output only for the exact reviewed layout | An applicable primary definition for any different layout. No padding, truncation or invented oxygen/lambda values. |
| `0101` | LIVE blocked | Complete ignition-specific readiness semantics and tests distinguishing monitor support from completion; current bitmap support alone is insufficient. |
| `019D` | LIVE blocked | Exact authoritative definition, edition, length, masks, scaling, applicability and tests. A guessed label cannot authorize a request. |
| `010B` / `0110` | MAP / MAF with current same-ECU range configuration | Validate `014F` / `0150` selectors. A maximum encoded byte can censor a value; it cannot reconstruct higher physical pressure. MAP is absolute pressure. |
| `0171` | VGT command, reported position and status | Same-frame differences are descriptive. Sparse sampling cannot establish turbo lag, fault or Sport-mode causation. |
| Pedal, throttle, EGR, rail and fuel-rate fields | Separate standard measurements or commands | Preserve units, field semantics, source, sample age and actual cadence. Commands are not independent position measurements. |
| `0183` / `0185` | Supported NOx and reagent fields | Respect per-field availability. Quantized tank level is not measured consumption; a lone NOx channel cannot establish SCR conversion efficiency. |
| `0188` | Current SCR inducement and historical blocks | Separate current activation/reasons from historical latches and distance/time counters. Neither is an overall health verdict. |
| `018F` | PM-sensor status and normalized signal | PM-sensor regeneration is distinct from DPF regeneration. Normalized signal is not DPF soot mass. |

No new decoder or LIVE command is admitted by this research review. Existing exact-layout decoders and the separate allowlist remain in place. Unsupported identifiers must not be probed. OEM/UDS requests, writes, actuation, DTC clearing and forced regeneration remain outside the application policy.

## Primary-source review

SAE lists **J1979DA_202607**, revised 16 July 2026, as the current Digital Annex. Its public publisher page describes a registry and version history; it does not expose an applicable alternative field table. [SAE current Digital Annex](https://saemobilus.sae.org/standards/j1979da_202607-j1979-da-digital-annex-e-e-diagnostic-test-modes).

The existing implementation records the historical OCT2011 table references. The publisher confirms that edition's identity; the public metadata does not independently certify every implemented field or its applicability to a particular ECU. [SAE OCT2011 edition](https://saemobilus.sae.org/standards/j1979da_201110-j1979-da-digital-annex-e-e-diagnostic-test-modes).

The publisher also records later revisions, including [March 2022](https://saemobilus.sae.org/standards/j1979da_202203-j1979-da-digital-annex-e-e-diagnostic-test-modes) and [October 2025](https://saemobilus.sae.org/standards/j1979da_202510-j1979-da-digital-annex-e-e-diagnostic-test-modes). Lawful access to exact applicable tables and independent review remain necessary before accepting an alternative layout. Public mirrors, forum formulas and catalog descriptions were not accepted as new decoder authority.

Each future candidate register must retain edition/table reference, expected length, availability/reserved-bit rules, endian/signedness, scaling, units, unavailable encodings, current range selectors, private sample references, cadence, acceptance reason and unresolved questions. Do not redistribute copyrighted annex tables.

## Temporal analysis and next work

Offline RAW analysis uses preceding asynchronous samples with explicit age and sensitivity gates; it does not interpolate future observations. Warm/cold and stopped/moving groups are descriptive. Serial dependence, flow, temperature, load and sampling schedules confound correlations. An apparent association with airflow cannot supply a missing unit or diagnose a DPF.

Compare Comprehensive and Critical profiles using matched new captures and actual per-field cadence while preserving the normal aggregate **4 requests/s** ceiling. Retain slow counters/configuration where appropriate; make every loss of coverage explicit. Sport annotations require a human-reported uncertainty interval. A faster stationary experimental benchmark requires its own reviewed operation and explicit approval; clean lower-rate results or adapter latency alone do not establish ECU capacity.
