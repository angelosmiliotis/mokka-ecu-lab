"""Pure Drive Capture planning. Selecting a plan cannot transmit anything."""
from .protocols import LIVE_PIDS, DISCOVERY_PIDS, support_state
from .sensors import load_registry
from .sensors.diesel import STANDARD_DIESEL
from .layouts import RAW_ONLY_PIDS, raw_eligibility

DRIVE_WEIGHTS = {0x8B:4,0x7A:3,0x7C:2,0x78:2,0x0C:2,0x0D:2,0x05:1,0x10:1,0x85:1}
DECODER_VERSION = 'SAE-OCT2011-v0.2.3'


def capture_plan(support, pages, observations, ecu, *, prepared=False, selected=None, raw_selected=()):
    registry = load_registry()
    eligible, omitted = {}, []
    requested = list(DRIVE_WEIGHTS) if selected is None else list(dict.fromkeys(selected))
    raw_selected = set(raw_selected)
    requested = list(dict.fromkeys(requested+sorted(raw_selected)))
    for pid in requested:
        sensor = STANDARD_DIESEL.get(pid) or registry.get(pid)
        reason = ''
        if pid in raw_selected and pid not in RAW_ONLY_PIDS: reason = 'Outside fixed RAW-only candidates (017A / 0188)'
        elif pid not in LIVE_PIDS | DISCOVERY_PIDS: reason = 'Outside fixed standard allowlist'
        elif not prepared: reason = 'Successful explicit discovery for this ECU is required'
        else:
            state = support_state(support.get(ecu,set()),pages.get(ecu,set()),pid)
            if state != 'supported': reason = f'ECU PID support is {state.upper()}'
            elif pid in raw_selected:
                if not raw_eligibility(observations.get((ecu,pid),{})):
                    reason = 'A complete positive response from this ECU in prior discovery is required'
            elif pid in DISCOVERY_PIDS:
                sample = observations.get((ecu,pid),{})
                if sample.get('error'): reason = 'Latest discovery sample is invalid: '+sample['error']
                elif not any(f.get('state')=='AVAILABLE' and f.get('value') is not None for f in sample.get('fields',[])):
                    reason = 'No valid supported fields from explicit discovery'
        name = sensor.name if sensor else f'PID {pid:02X}'
        if reason: omitted.append(dict(pid=f'{pid:02X}',name=name,reason=reason))
        else: eligible[pid] = 1 if pid in raw_selected else DRIVE_WEIGHTS.get(pid,1)
    return {'ecu':ecu,'weights':eligible,'raw_pids':sorted(raw_selected & eligible.keys()),
            'omitted':omitted,'prepared':prepared}


def manual_options(support,pages,observations,ecu,*,prepared=False):
    return capture_plan(support,pages,observations,ecu,prepared=prepared,
                        selected=list(DRIVE_WEIGHTS)+sorted((LIVE_PIDS|DISCOVERY_PIDS)-DRIVE_WEIGHTS.keys()))
