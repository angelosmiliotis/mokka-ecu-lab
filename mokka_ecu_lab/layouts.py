"""Layout evidence only: alternative DPF/SCR layouts have no numeric decoder.

Lengths identify a candidate shape, never a revision or a verified formula.
Public fixtures are synthetic; private journals are not distributed.
"""
from .sensors.diesel import STANDARD_DIESEL, SAE

RAW_ONLY_PIDS = frozenset({0x7A, 0x88})
REVISION_CATALOG = 'https://saemobilus.sae.org/standards/j1979da_202203-j1979-da-digital-annex-e-e-diagnostic-test-modes'


def layout_evidence(pid, payload):
    sensor = STANDARD_DIESEL[pid]
    evidence = dict(data_length=len(payload), isotp_payload_length=len(payload)+2,
                    documented_data_length=sensor.length, documented_edition='OCT2011',
                    documented_source=SAE, source_table=sensor.table,
                    alternative_format_source=None, alternative_revision=None,
                    vehicle_verification='UNVERIFIED')
    try:
        sensor.decode(payload)  # Validation uses the same strict documented decoder.
    except ValueError as exc:
        evidence.update(layout_status='DECODER_UNVERIFIED', decoder_error=str(exc))
    else:
        evidence.update(layout_status='STANDARD_DOCUMENTED', decoder_error=None)
    return evidence


def raw_eligibility(sample):
    # A previous complete positive response is required in addition to the
    # per-ECU support bitmap and completed discovery checked by capture_plan.
    return bool(sample.get('framing_valid') and sample.get('payload_hex')
                and sample.get('layout_status') in {'STANDARD_DOCUMENTED','DECODER_UNVERIFIED'})
