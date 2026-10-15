"""Bounded single-worker feedback; never a higher-rate capacity search."""
from collections import deque
import statistics
from mokka_ecu_lab.analysis.obd import symptom,finite


class AdaptivePacing:
    def __init__(self,ceiling=4.):
        self.ceiling=max(.25,min(4.,float(ceiling)));self.rate=self.ceiling
        self.baselines={};self.good=0;self.last_change=None;self.cooldown_until=0.;self.history=[]
        self.reason='Approved policy ceiling; no hardware capacity claim'
    def observe(self,record,now):
        category=symptom(record);pid=record.get('command','UNKNOWN')
        if category in {'INTENTIONAL_CANCELLATION','DECODER_LAYOUT','ECU_NRC','ECU_NO_DATA'}:return False
        latency=record.get('latency_ms');prior=self.baselines.setdefault(pid,deque(maxlen=32))
        threshold=max(250.,2.5*statistics.median(prior)) if len(prior)>=8 else 500.
        trouble=category in {'TRANSPORT_FAILURE','FRAMING_OR_PROTOCOL'} or finite(latency) and latency>threshold
        previous=self.rate
        if trouble:
            self.rate=max(.25,self.rate*.5);self.good=0;self.cooldown_until=now+30
            self.reason='Communication deterioration; '+category+'; no automatic retry/reconnect'
        elif category=='OK':
            if finite(latency):prior.append(float(latency))
            self.good+=1
            if self.good>=96 and now>=self.cooldown_until and (self.last_change is None or now-self.last_change>=30):
                self.rate=min(self.ceiling,self.rate+.25);self.good=0
                self.reason='Sustained stable communication; cautious recovery within approved ceiling'
        if self.rate!=previous:
            self.last_change=now;self.history.append(dict(monotonic_seconds=now,previous_rate=previous,rate=self.rate,reason=self.reason));self.history=self.history[-64:]
            return True
        return False
    def snapshot(self):
        return dict(enabled=True,rate=self.rate,policy_ceiling=self.ceiling,minimum_rate=.25,maximum_live_rate=4.,reason=self.reason,
            cooldown_until_monotonic=self.cooldown_until,stable_replies=self.good,per_pid_baseline_samples={p:len(v) for p,v in self.baselines.items()},transitions=list(self.history),
            feedback='Communication timing/protocol only; values, decoder layout and source staleness excluded')


class StationaryBenchmark:
    """A fixed bounded experiment; authorization does not verify vehicle conditions."""
    def __init__(self,pids,rate,now,*,ecu=None,context_id=None,mode='UNKNOWN'):
        if not pids or len(pids)>3 or not .25<=rate<=4:raise ValueError('Benchmark scope/rate outside fixed limits')
        self.pids=tuple(pids);self.rate=rate;self.started=now;self.requests=0;self.maximum_requests=48;self.maximum_seconds=60
        self.active=True;self.reason='Explicit parked consent; conditions user-reported, not ECU-confirmed'
        self.ecu=ecu;self.context_id=context_id;self.mode=mode;self.session_id=None
    def next_pid(self,now):
        if not self.active or self.requests>=self.maximum_requests or now-self.started>=self.maximum_seconds:return None
        return self.pids[self.requests%len(self.pids)]
    def observe(self,record):
        self.requests+=bool(record.get('sent'))
        if symptom(record)!='OK':self.active=False;self.reason='Aborted immediately: '+symptom(record)
        elif finite(record.get('latency_ms')) and record['latency_ms']>1000:self.active=False;self.reason='Aborted: end-to-end latency exceeds bounded benchmark allowance; no ECU capacity inference'
    def snapshot(self):
        return dict(active=self.active,pids=[f'{p:02X}' for p in self.pids],rate=self.rate,requests=self.requests,maximum_requests=self.maximum_requests,
            maximum_seconds=self.maximum_seconds,reason=self.reason,adaptive=False,conditions='USER_REPORTED',higher_rate_authorized=False,
            ecu=self.ecu,context_id=self.context_id,mode=self.mode,session_id=self.session_id)
