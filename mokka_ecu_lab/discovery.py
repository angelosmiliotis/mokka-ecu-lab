"""Portable ECU-specific discovery reports. No transport or transmit API."""
from .protocols import support_state
from .sensors import load_registry
from .sensors.diesel import STANDARD_DIESEL, RESEARCH_CANDIDATES


def discovery_report(support, pages, observations, *, mode='Disconnected', context_id=None):
    entries = []
    ecus = sorted(set(support) | {ecu for ecu, _ in observations}) or ['unknown']
    for ecu in ecus:
        for pid, sensor in {**load_registry(), **STANDARD_DIESEL}.items():
            metadata = (sensor.metadata() if pid in STANDARD_DIESEL else
                        dict(sensor.metadata, name=sensor.name, system='Engine', request=f'01{pid:02X}'))
            state = support_state(support.get(ecu, set()), pages.get(ecu, set()), pid)
            sample = observations.get((ecu,pid), {})
            fields = sample.get('fields', [])
            availability = ('AVAILABLE' if any(f['state']=='AVAILABLE' for f in fields) else
                            'UNSUPPORTED' if state == 'unsupported' else
                            'UNKNOWN' if state == 'unknown' else
                            'NO_SUPPORTED_FIELDS' if fields else 'UNVERIFIED')
            if sample.get('error'): availability = 'INVALID / UNVERIFIED'
            if sample.get('raw_only'): availability = 'RAW ONLY / DECODER UNVERIFIED'
            entries.append(dict(metadata, ecu=ecu, support=state.upper(), availability=availability,
                                vehicle_verification='UNVERIFIED', sample=sample,
                                evidence=sample.get('source_kind','NO_SAMPLE')))
    return {'schema_version': 1, 'record_type':'discovery_report', 'mode':mode, 'context_id':context_id,
            'standard':entries, 'manufacturer_candidates':list(RESEARCH_CANDIDATES),
            'limitations':['Support is ECU-specific; no claim of vehicle verification.',
                           'Functional OBD requests are broadcast; decoding only uses independently advertising ECUs.',
                           'Samples are timestamped observations, never a health verdict or continuous-live claim.',
                           'RAW-only bypasses numeric interpretation; complete frames do not prove a documented layout.',
                           '0185 warning-mode engine time is a counter, not a current SCR warning indicator.']}
