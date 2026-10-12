# Offline manufacturer-decoding hypotheses

Status: EXPERIMENTAL. Recorded 12 October 2026. All observations in this file came from the owner's previous Car Scanner session summary. No underlying requests or raw replies were supplied, and the physical vehicle is unavailable. There are no enabled manufacturer-specific live queries.

## H001 — distance increment is 256 times the reported trip distance

Owner observation: displayed distance since regeneration changed from 1152.63 to 1792.63 during approximately 2.5 km of driving. Arithmetic: `1792.63 - 1152.63 = 640`; `640 / 2.5 = 256`.

Candidate explanations: incorrect fixed-point scaling, byte position, endianness, field alignment, wrong source ECU, an unrelated counter, or mismatched vehicle profile. These are independent hypotheses; the factor does not select one. Dividing the whole displayed value by 256 would yield 4.5024609375 and 7.0024609375, but their absolute meaning is unknown. Do not apply this as a correction to live values.

Offline experiment when legitimate raw records are available:

1. Preserve exact request, ECU address, response bytes, timestamps and profile context. Identify candidate data fields without deleting the service/DID prefix from the archive.
2. Compare unsigned and signed 16/24/32-bit fields in both byte orders, at explicitly recorded offsets. Keep every transformation attached to its raw source.
3. Fit `distance_delta = scale * raw_delta` over several independently measured trips, including stationary intervals and byte carries. Do not fit only two samples.
4. Reserve a separate trip to test predictions. Record the uncertainty of the independent distance measurement, session gaps and any counter reset/wrap.
5. A successful increment fit does not identify the field as distance since regeneration. Verification also needs authoritative semantics and a verified regeneration boundary.

## H002 — 425% soot clogging

Owner observation: a profile displayed 425%. Candidate explanations: different engineering units, a scaled integer, a model-derived mass, wrong field or wrong profile. No percentage denominator or physical meaning is known. Do not clamp the display to 100% or create an alarm threshold to make the data appear credible.

Required evidence: documented request and units, payload layout, model/ECU applicability and comparison with an independent approved diagnostic reading under the same conditions. Until then, retain only a clearly experimental offline candidate.

## H003 — average interval of 2928.63 km over ten regenerations

The profile's reported mean is unverified. It might be a total, a scale error, an incomplete history or a different field. No history entries, valid-event count or formula is known. Do not divide by ten without evidence that the field is a sum and that ten events exist.

Offline work: compare raw history entries with documented structure; test aggregate and mean hypotheses on observed completed events. Record startup, shutdown and logging gaps. Missing recordings cannot be treated as evidence that no regeneration occurred.

## H004 — open-loop and closed-loop soot estimates differ

Owner observation: 24.77 versus 2.69 in the profile's displayed units. The labels may refer to distinct models, physical quantities or stale readings. Neither is selected as ground truth. Compare request/reply timestamps, byte layouts, units and same-condition samples. The difference is not sufficient to infer a failed DPF, pressure sensor or ECU.

## H005 — differential pressure near 11–16 mbar at idle

These reported numbers are not a verified Mokka diagnostic baseline. Before interpretation, verify units, signedness, pressure reference and source field. Record coolant, RPM, air flow, exhaust conditions and measurement timing alongside the raw candidate. Obtain manufacturer limits that match the actual engine/ECU and test conditions; do not infer blockage from the isolated numbers. The arithmetic unit relation is `1 mbar = 0.1 kPa`.

## Future independent regeneration history

Design recommendation: use a verified regeneration-state signal with explicit transitions, synchronized reliable distance and a coverage interval table. Store start, finish, interruption/unknown completion, source ECU, decoder version and evidence. A recording gap makes event count and distance interval incomplete. Integrated Mode 01 speed can estimate distance only within covered intervals and has quantization/timing error; it is not an odometer. This release has no verified regeneration-state signal, so it cannot claim to detect regeneration events.

## Candidate evidence record

Each proposed sensor needs: candidate ID; vehicle and ECU applicability; source URL/document revision/page; exact request and positive response; raw sample provenance and checksum; field offset/length; byte order; signedness; scale/offset; unit; validity rules; alternative hypotheses; independent comparison results; reviewer/date; and verification state. Document failed hypotheses, and retain original raw samples so a later decoder can reproduce the analysis.

Authoritative entry points and standard communication sources are documented in [RESEARCH_NOTES.md](../RESEARCH_NOTES.md). An owner manual from Mokka X or another model/year is not evidence for Mokka B manufacturer decoder semantics.
