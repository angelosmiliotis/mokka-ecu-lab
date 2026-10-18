# Definition sources and unresolved layouts

The [SAE J1979DA July 2026 catalog](https://saemobilus.sae.org/standards/j1979da_202607-j1979-da-digital-annex-e-e-diagnostic-test-modes) identifies the revision dated 16 July 2026. Its public catalog is not a byte-layout table. No licensed current digital-annex content was obtained for a new alternate decoder. Existing OCT2011 code-owned definitions retain their exact lengths, reserved/availability rules and source-table metadata. Matching payload length alone cannot identify a standard revision or calibrated vehicle behavior.

| Identifier | Implemented research boundary |
|---|---|
| 017A | Existing OCT2011 B101 exact seven-data-byte definition; alternate complete lengths remain RAW-only. No guessed pressure, soot, ash or regeneration. |
| 018C | Existing OCT2011 B119 exact seventeen-data-byte definition; alternate lengths retain every original byte, without padding or shifting. |
| 0101 | Pure offline composite: [SAE J1979 APR2002 B2/B3](https://law.resource.org/pub/us/cfr/ibr/005/sae.j1979.2002.pdf) supplies legacy byte positions; [EPA March 2013 Table 2](https://www.epa.gov/system/files/documents/2022-08/diesel-obd-im-readiness-14k-pounds-gwr-best-practices.pdf) supplies ignition-specific monitor mapping/B3. The old standard reserves B3; the later mapping is explicitly a composite, not a claimed current licensed definition. No LIVE admission. |
| 019D | Exact normative definition unverified; no guessed layout, unit or request admission. |
| 014F / 0150 | Configuration selectors, not independent live physical measurements; use only prior supported exact configuration in the same source context. |
| 010B | Absolute MAP, with encoding ceiling determined by valid configuration; no extrapolated boost beyond an endpoint. |
| 0171 | Command/position channels and their validity flags are distinct; comparisons remain descriptive. |
| 0183 / 0185 / 0188 | Respect NOx slot validity, reagent quantization and current versus historical SCR semantics. No conversion-efficiency or consumption conclusion from asynchronous snapshots. |
| 018F | PM sensor regeneration is distinct from DPF filter regeneration; normalized signal is not soot or ash mass. |

Promotion of an unknown layout requires an exact legitimate normative revision/table, byte length/order, reserved and sentinel rules, controlled synthetic tests, repeated same-source positive evidence and independent physical reference measurements with units, timing and uncertainty. Correlation or a public catalog entry cannot supply these gates. The application implements no new OEM/UDS request or physical experiment above the existing policy ceiling.
