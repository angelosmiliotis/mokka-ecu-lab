"""Offline-only research leads. Nothing here is loaded by transport or decoders."""
SAE='https://saemobilus.sae.org/standards/j1979da_202607-j1979-da-digital-annex-e-e-diagnostic-test-modes'
DPS='https://www.bosch-mobility.com/en/solutions/sensors/differential-pressure-sensor/'
NOX='https://www.bosch-mobility.com/en/solutions/sensors/nox-sensor/'
ASH='https://saemobilus.sae.org/articles/ash-effects-diesel-particulate-filter-pressure-drop-sensitivity-soot-implications-regeneration-frequency-dpf-control-2010-01-0811'
VENDOR='https://www.dashlogic.com/docs/technical/obdii_pids'


def research_roadmap():
    base=dict(ecu_applicability='UNKNOWN exact hardware/software/calibration; family name is not proof',
        validation_status='OFFLINE_RESEARCH_ONLY',live_enabled=False,version='Research revision 0.2.8; consulted 2026-10-14',
        validation_required='Authoritative applicable revision/definition, ECU provenance, strict frame tests and independent reference under matched conditions; separate future authorization before any new live scope')
    def entry(name,request,sources,unit=None,formula=None,length=None,contradictions='',risk='UNVERIFIED'):
        return dict(base,name=name,candidate_request=request,sources=sources,units=unit or 'UNKNOWN',
            decoding_formula=formula,expected_data_bytes=length,contradictions=contradictions,risk=risk)
    rows=[
        entry('Six-byte DPF-related RAW layout','017A',[SAE,DPS],contradictions='Existing OCT2011 numeric definition requires seven bytes. A six-byte complete frame is not a shortened verified formula; sensor variant/range/signedness unknown.'),
        entry('Standard regeneration indicator','018B',[SAE],contradictions='A generic documented PID does not imply this ECU supports it. Current per-session bitmap/valid sample gates remain mandatory.'),
        entry('Soot mass',None,[DPS,ASH],contradictions='Pressure drop is affected by flow, temperature, soot and ash. No applicable mass decoder or unique identifier established.'),
        entry('Ash mass',None,[ASH],contradictions='Ash changes pressure sensitivity; a raw pressure-related number does not uniquely measure ash mass.'),
        entry('Distance/time since last regeneration',None,[SAE],contradictions='No applicable instantaneous/last-event field established; standard averages or engine runtime cannot substitute.'),
        entry('Exhaust gas temperatures','0178 / 0179 / 017C',[SAE],contradictions='Existing definitions remain gated by ECU and individual field support; generic availability is not vehicle availability.'),
        entry('AdBlue quality / pressure',None,[SAE],contradictions='0185 reagent level/demand fields are not quality/pressure sensors; quantized tank movement is not actual consumption.'),
        entry('NOx upstream / downstream SCR','0183',[SAE,NOX],contradictions='Supported slots are independent; bank/sensor label alone does not prove physical placement. A missing second sensor prevents conversion-efficiency validation.'),
        entry('Absolute throttle position future standard lead','0111',[VENDOR,SAE],'%', 'A / 2.55 (vendor reference; current applicable SAE revision not revalidated)',1,
            'Vendor listing is not ECU support evidence; diesel throttle is not accelerator pedal and does not establish commanded boost.'),
        entry('Relative accelerator pedal future standard lead','015A',[VENDOR,SAE],'%', 'A / 2.55 (vendor reference; current applicable SAE revision not revalidated)',1,
            'Not in the v0.2.8 allowlist; support and applicability unknown. Serial sampling cannot establish sub-second turbo lag.'),
        entry('Absolute rail pressure future standard lead','0159',[VENDOR,SAE],'kPa', '(256*A+B)*10 (vendor reference; applicable revision unverified)',2,
            'Not in the allowlist; absolute versus gauge units and ECU applicability must be independently checked.')]
    for request in ('22 D525','22 D526','22 D52F','22 D532'):
        rows.append(entry('Legacy speculative OEM DID',request,[SAE],contradictions='SAE reference gives only generic OBD scope, not this DID. No authoritative same-calibration DID definition located. Existing community/family leads are unverified.',risk='HIGH: wrong ECU mapping and broader diagnostic service; prohibited live'))
    return rows
