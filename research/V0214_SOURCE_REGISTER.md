# v0.2.14 controlled PID source register

Evidence stages remain separate: advertised, same-ECU positive response, valid
framing, exact documented layout, numeric decoding and independent physical
verification. Neither a bitmap nor agreement with historical decoder arithmetic
proves units, applicability or physical calibration. No command/decoder is added.

| Scope | Source and applicable limit | Release decision |
|---|---|---|
| SAE editions | [Official J1979DA 202607 metadata](https://saemobilus.sae.org/standards/j1979da_202607-j1979-da-digital-annex-e-e-diagnostic-test-modes) identifies revision 202607 and historical editions including OCT2011. Metadata is not the licensed byte/flag table. | No new full applicable table was acquired or copied; do not claim edition equivalence. |
| 017A | Existing OCT2011 definition expects seven data bytes. Six-byte variants retain framed RAW evidence. | No padding, truncation, inferred pressure unit/scale, soot/ash or DPF regeneration decoder. |
| 018C | Existing exact numeric definition expects seventeen data bytes. Other lengths remain layout mismatches. | No speculative fifteen-byte lambda decoder. |
| 0101 | Exact ignition-specific readiness/support-vs-incomplete bits and reserved states need applicable primary-table review. | Advertised-only is insufficient; no live probe or decoder expansion. |
| 019D | [Official CARB workshop, slide 39](https://ww2.arb.ca.gov/sites/default/files/classic/msprog/obdprog/obd2014_wspresentation.pdf) is a primary research lead about engine/vehicle fuel mass rate. It does not provide the complete applicable byte layout. | Flags, scale, sentinels, edition and same-ECU applicability remain unresolved; live blocked. |
| 014F/0150 | Existing standard range-selector definitions/configuration gates remain mandatory when advertised. | A zero selector is configuration semantics, not a zero physical sensor value. No speculative scale override. |
| 0171 | Existing documented support/value fields distinguish commanded VGT, position and status. | Report actual cadence and independent ages; no turbo-lag/causality claim from sparse or stationary samples. |
| 0183 | Existing supported/available NOx slots remain separate. | One available channel cannot establish SCR conversion efficiency. |
| 0185 | Existing reagent fields retain validity and quantization metadata. | Reported level is not measured consumption or overall AdBlue health. |
| 0188 | Existing exact-layout SCR status/counter fields remain separate. | Current inducement, historical counters and exhaust-system health are different claims. |
| 018F | Existing documented PM-sensor support/status fields remain separate. | PM-sensor regeneration is not DPF regeneration. |

MAP is absolute pressure; its encoding ceiling is not a measurement above that
ceiling or gauge boost. Unknown and unavailable are not numeric zero or healthy.
Critical, broad-priority and correlated profiles share the same aggregate budget.
Compare observed cadence and previous-only context ages across conditions; idle
and driving captures are not matched-condition mechanical experiments. All actual
data, byte distributions, timing histories and private comparisons stay outside Git.
