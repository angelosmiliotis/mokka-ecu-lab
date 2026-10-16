"""Pure illustrative queue arithmetic. No transport import or LIVE feature switch."""
import math

LIVE_HIGH_RATE_ENABLED=False

def illustrative_feasibility(response_ms,rates=(4,5,6),seconds=60):
    if type(response_ms) not in (int,float) or not math.isfinite(response_ms) or response_ms<=0 or type(seconds) not in (int,float) or not 1<=seconds<=60:raise ValueError('Finite synthetic assumptions required')
    if not rates or len(rates)>3 or any(type(r) is not int or r not in (4,5,6) for r in rates):raise ValueError('Only the illustrative 4/5/6 proposal is modeled; no authorization')
    return dict(live_enabled=False,transmissions=0,hardware_capacity_verified=False,
        assumptions='Pure constructed serialized service-time arithmetic; ignores variable latency, link, ECU, thermal and UI load. Not permission or a safety prediction.',
        rows=[dict(illustrative_requested_rate=r,assumed_minimum_interval_seconds=max(1/r,response_ms/1000),theoretical_count_upper_bound=math.floor(seconds/max(1/r,response_ms/1000))) for r in rates])
