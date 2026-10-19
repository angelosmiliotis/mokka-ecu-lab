"""Code-owned research boundaries; no vehicle examples or request authority."""
CATALOG='https://saemobilus.sae.org/standards/j1979da_202607-j1979-da-digital-annex-e-e-diagnostic-test-modes'


def research_status(pid):
    common=dict(current_revision_catalog=CATALOG,catalog_is_byte_definition=False,
        licensed_current_byte_table_obtained=False,physical_calibration='UNVERIFIED',new_live_requests_authorized=False)
    notes={
        0x01:'Pure offline readiness definition: APR2002 B2/B3 byte basis plus EPA2013 ignition mapping. No positive reply is implied; no LIVE admission. Completion is not absence of faults or DPF regeneration.',
        0x7A:'OCT2011 B102 requires exactly seven data bytes. A different complete length remains RAW_ONLY. An unsigned byte-pair hypothesis has no established physical unit. Require exact normative revision/table, reserved/sentinel rules and independent calibrated comparison before promotion. No pressure, soot, ash or regeneration inferred.',
        0x8C:'OCT2011 B119 requires exactly seventeen data bytes. Preserve every byte of alternate-length responses; no padding, shifting, slot collapse or alternate revision inferred. Exact licensed alternate table and controlled evidence required.',
        0x9D:'No exact definition verified in the consulted OCT2011 source. Support bit alone cannot identify a measurement or authorize a request. No guessed field, length, unit or scaling.',
        0x4F:'Range configuration, not a current physical measurement. Only exact same-source prior supported configuration can change MAP scaling; selector zero retains the default. Byte ceiling is not an independently measured pressure beyond the encoded value.',
        0x50:'MAF range configuration, not a current flow reading or sensor count. Apply only the prior supported configuration in this recording/source context; no carryover between sessions.',
        0x0B:'MAP is absolute manifold pressure. One-byte endpoint can be censored; the valid current range selector determines the encoding ceiling. No boost extrapolation above the endpoint.',
        0x71:'VGT commanded and measured positions are separate channels. Preserve validity flags; same-frame differences are descriptive. Asynchronous RPM/MAP/MAF samples cannot establish physical turbo lag or a defect.',
        0x83:'NOx per-slot support and invalid encodings gate each channel. Unsupported or invalid slots are unavailable, never numeric zero. Unaligned upstream/downstream samples do not establish SCR conversion efficiency.',
        0x85:'Reagent tank level is quantized; a level step is not calibrated consumption. Pump demand is not tank filling. Each supported subfield has separate validity and physical uncertainty.',
        0x88:'Current inducement status and historical engine-time counters have different temporal meanings. Several flags from one reply are not several physical sensors, and a history counter is not a current malfunction diagnosis.',
        0x8F:'PM sensor activity/regeneration and normalized signal describe the PM sensor. They do not prove DPF filter regeneration, soot mass, ash loading or filter health.'}
    return dict(common,interpretation=notes.get(pid,'Standard field replay is separate from sensor identity, calibration and vehicle health.'))
