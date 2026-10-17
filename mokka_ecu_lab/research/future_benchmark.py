"""Offline-only higher-rate design. This module cannot obtain a transport.

All timestamps below are constructed integer virtual nanoseconds. Modeled sends
are deliberately separate from actual transmissions, which always remain zero.
"""
from dataclasses import dataclass
import math

LIVE_HIGH_RATE_ENABLED=False
FIXED_PIDS=('010D','010C','010B','0110')
PREFLIGHT_REQUESTS=12
FAULTS=('STOP','SUSPEND','CONTEXT_CHANGE','ECU_CHANGE','PROMPT_DESYNC',
        'SPEED_MISSING','SPEED_NONZERO','NRC','INVALID_FRAMING','NO_DATA',
        'TIMEOUT','EXCESSIVE_LATENCY')
BEFORE_SEND_FAULTS=frozenset(FAULTS[:7])
SINGLE_LATENCY_ABORT_MS=250


def engineering_brief():
    """A proposal for a future reviewed implementation, never an unlock token."""
    return dict(
        schema='mokka-higher-rate-proposal-1',live_state='LOCKED',live_enabled=False,
        actual_transmissions=0,normal_live_ceiling_req_s=4,
        proposed_first_step=dict(rate_req_s=5,measurement_seconds=60,
            minimum_all_send_gap_ms=200,preflight_requests=12,
            planned_measurement_requests=300,maximum_total_requests=312,
            fixed_mode01_pids=list(FIXED_PIDS),automatic_ramp=False,
            automatic_retry=False),
        prerequisites=[
            'Separate explicit human authorization of exactly one 5 req/s, 60-second hardware experiment after engineering review.',
            'Independent automotive professional review is preferred; absence of such review must be stated.',
            'Review a fresh matched normal 4 req/s reference; proposed p95 application/adapter latency threshold is 150 ms, no errors and synchronized prompt.',
            'Use its existing verified healthy connection and already-confirmed support. Any required extra initialization/discovery/wakeup ends the proposal and returns to normal <=4 preparation; the experimental fixed mix has no hidden setup sends.',
            'Confirm safe outdoor stationary conditions, brake, transmission, ventilation and no competing OBD client for every run; these are operator reports.',
            'Verify current speed 0, ECU, connection context and synchronized prompt; speed 0 does not prove brake or safe parking.',
            'Audit a separate, non-user-editable experimental policy and every send path, including preparation, against one serialized all-request accountant.',
            'Implement and validate immediate Stop, shutdown/suspend/port-loss closure and immutable partial evidence before any real experiment.',
        ],
        abort_policy=dict(single_application_latency_ms=SINGLE_LATENCY_ABORT_MS,
            reasons=list(FAULTS),speed_freshness='Required on every speed reply and before next send; define maximum age in reviewed LIVE implementation.',
            error_action='Stop the run immediately, retain partial evidence, close the experimental connection, no automatic retry.'),
        later_six_req_s='LOCKED separately: review the completed first 5 req/s hardware result and obtain new precise authorization before proposing 6.',
        evidence_limits=[
            'Synthetic virtual timing is not a hardware test, throughput guarantee, safety validation or authorization.',
            'Application/adapter end-to-end latency is not ECU service time, CAN utilization or unused capacity.',
            'Normal driving, sessions and normal benchmarks retain the independent hard ceiling of 4 total req/s.',
            'No physical higher-rate implementation, transport object, live Start action, environment variable or configuration unlock exists here.',
        ])


@dataclass(frozen=True)
class SyntheticFault:
    """Inject a constructed condition at a zero-based all-phase request index."""
    request_index:int
    kind:str

    def __post_init__(self):
        if type(self.request_index) is not int or not 0<=self.request_index<=400:
            raise ValueError('Fault index must be an integer from 0 to 400')
        if self.kind not in FAULTS:raise ValueError('Unknown synthetic abort condition')


class SyntheticBenchmark:
    """Deterministic serialized model with one shared preflight/send timeline.

    advance() models at most one request/response, without clocks, sleep, threads,
    sockets, serial ports, callbacks or acquisition-worker imports. UI Stop is a
    direct state change; it cannot send a request. No real payload is consumed.
    """
    def __init__(self,rate=5,*,response_ms=100,duration_seconds=60,fault=None):
        if type(rate) is not int or not 1<=rate<=6:raise ValueError('Synthetic rate must be 1–6')
        if type(response_ms) not in (int,float) or not math.isfinite(response_ms) or not 0<response_ms<=1000:
            raise ValueError('Constructed response time must be finite and within 0–1000 ms')
        if type(duration_seconds) is not int or not 1<=duration_seconds<=60:
            raise ValueError('Synthetic measurement duration must be 1–60 seconds')
        if fault is not None and not isinstance(fault,SyntheticFault):raise ValueError('Use a SyntheticFault')
        self.rate=rate;self.duration_seconds=duration_seconds;self.response_ms=response_ms;self.fault=fault
        self.minimum_gap_ns=math.ceil(1_000_000_000/rate);self.response_ns=math.ceil(response_ms*1_000_000)
        self.state='PREFLIGHT';self.reason='Constructed preparation; no connection is opened.'
        self.events=[];self.virtual_ns=0;self.measurement_start_ns=None;self.measurement_end_ns=None
        self._last_send_ns=None;self._next_send_ns=0;self._speed_verified=False

    @property
    def active(self):return self.state in ('PREFLIGHT','MEASUREMENT')

    def abort(self,reason):
        if not self.active:return
        if reason not in FAULTS:raise ValueError('Unknown synthetic abort condition')
        self.state='ABORTED';self.reason=reason+' · partial constructed evidence retained; no retry.'

    def stop(self):self.abort('STOP')

    def advance(self):
        if not self.active:return self.snapshot()
        index=len(self.events)
        if index==PREFLIGHT_REQUESTS and self.measurement_start_ns is None:
            self.measurement_start_ns=self._next_send_ns
            self.measurement_end_ns=self.measurement_start_ns+self.duration_seconds*1_000_000_000
            self.state='MEASUREMENT';self.reason='Fixed bounded virtual measurement; no automatic rate change.'
        if self.measurement_end_ns is not None and self._next_send_ns>=self.measurement_end_ns:
            self.virtual_ns=self.measurement_end_ns;self.state='COMPLETED'
            self.reason='Offline model completed. No hardware capacity or safety result.'
            return self.snapshot()
        fault=self.fault if self.fault and self.fault.request_index==index else None
        if fault and fault.kind in BEFORE_SEND_FAULTS:
            self.abort(fault.kind);return self.snapshot()
        command=FIXED_PIDS[index%len(FIXED_PIDS)]
        if command!='010D' and not self._speed_verified:
            self.abort('SPEED_MISSING');return self.snapshot()
        send=self._next_send_ns
        response=self.response_ns
        category=fault.kind if fault else 'OK'
        if category=='EXCESSIVE_LATENCY':response=max(response,SINGLE_LATENCY_ABORT_MS*1_000_000)
        if response>=SINGLE_LATENCY_ABORT_MS*1_000_000 and category=='OK':category='EXCESSIVE_LATENCY'
        finish=send+response
        if self.measurement_end_ns is not None and finish>self.measurement_end_ns:
            finish=self.measurement_end_ns;category='TIMEOUT'
        self.events.append(dict(index=index,phase=self.state,command=command,send_ns=send,
            response_end_ns=finish,category=category,source='CONSTRUCTED_OFFLINE',
            speed_kmh=0 if command=='010D' and category=='OK' else None,
            context_id='SYNTHETIC_CONTEXT',ecu='SYNTHETIC_ECU'))
        self._last_send_ns=send;self.virtual_ns=finish
        self._next_send_ns=max(send+self.minimum_gap_ns,finish)
        if category!='OK':self.abort(category)
        elif command=='010D':self._speed_verified=True
        return self.snapshot()

    def snapshot(self):
        preflight=sum(e['phase']=='PREFLIGHT' for e in self.events)
        measurement=len(self.events)-preflight
        elapsed=0 if self.measurement_start_ns is None else max(0,min(self.duration_seconds*1e9,self.virtual_ns-self.measurement_start_ns))/1e9
        gaps=[b['send_ns']-a['send_ns'] for a,b in zip(self.events,self.events[1:])]
        return dict(mode='CONSTRUCTED_OFFLINE',live_enabled=False,actual_transmissions=0,
            hardware_capacity_verified=False,state=self.state,reason=self.reason,
            requested_rate=self.rate,measurement_seconds=self.duration_seconds,
            virtual_elapsed_seconds=elapsed,virtual_remaining_seconds=self.duration_seconds-elapsed,
            minimum_required_gap_ns=self.minimum_gap_ns,minimum_modeled_gap_ns=min(gaps) if gaps else None,
            modeled_preflight_requests=preflight,modeled_measurement_requests=measurement,
            modeled_total_requests=len(self.events),planned_measurement_requests=self.duration_seconds*self.rate,
            modeled_spacing_violations=sum(gap<self.minimum_gap_ns for gap in gaps),
            modeled_response_overlap=sum(b['send_ns']<a['response_end_ns'] for a,b in zip(self.events,self.events[1:])),
            categories={c:sum(e['category']==c for e in self.events) for c in sorted({e['category'] for e in self.events})},
            phase_boundaries=dict(measurement_start_ns=self.measurement_start_ns,measurement_end_ns=self.measurement_end_ns),
            events=[dict(e) for e in self.events],evidence_note='Virtual constructed nanoseconds; not elapsed hardware measurement or permission.')

def illustrative_feasibility(response_ms,rates=(4,5,6),seconds=60):
    if type(response_ms) not in (int,float) or not math.isfinite(response_ms) or response_ms<=0 or type(seconds) not in (int,float) or not 1<=seconds<=60:raise ValueError('Finite synthetic assumptions required')
    if not rates or len(rates)>3 or any(type(r) is not int or r not in (4,5,6) for r in rates):raise ValueError('Only the illustrative 4/5/6 proposal is modeled; no authorization')
    return dict(live_enabled=False,transmissions=0,hardware_capacity_verified=False,
        assumptions='Pure constructed serialized service-time arithmetic; ignores variable latency, link, ECU, thermal and UI load. Not permission or a safety prediction.',
        rows=[dict(illustrative_requested_rate=r,assumed_minimum_interval_seconds=max(1/r,response_ms/1000),theoretical_count_upper_bound=math.floor(seconds/max(1/r,response_ms/1000))) for r in rates])
