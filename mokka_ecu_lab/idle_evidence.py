"""Passive post-export observations; never reads from or writes to a transport."""
from pathlib import Path
import hashlib,json,math,uuid,os
from . import __version__
from .local_paths import linked

class SilentIdle:
    def __init__(self,session_id,bundle,mode,send_count,now):
        self.bundle=Path(bundle);self.bundle_sha=hashlib.sha256(self.bundle.read_bytes()).hexdigest()
        self.started=now;self.last=now;self.requested=None;self.receipt=None
        self.data=dict(schema='mokka-post-export-idle-1',application_version=__version__,session_id=session_id,
            original_bundle_sha256=self.bundle_sha,source_mode=mode,observation_id=uuid.uuid4().hex,
            evidence='PASSIVE_LOCAL_HANDLE_AND_ADMITTED_SEND_LEDGER; not ECU liveness or physical calibration',
            state='NOT_REQUESTED',start_send_count=send_count,current_send_count=send_count,idle_requests=0,
            post_finish_elapsed_seconds=0.,verification_elapsed_seconds=0.,same_local_handle=True,passive_handle_healthy=True,
            finish_monotonic_seconds=now,verification_start_monotonic_seconds=None,observation_end_monotonic_seconds=now,passive_checks=0,maximum_observation_gap_seconds=0.,
            counter_scope='ALL_ADMITTED_TRANSPORT_SEND_ATTEMPTS; includes uncertain failed writes',
            actual_idle_diagnostic_requests=0,reason='Optional verification has not been requested')

    def request(self,now):
        if self.data['state']=='NOT_REQUESTED':self.requested=now;self.data.update(state='VERIFYING',verification_start_monotonic_seconds=now,reason='Observing 60 seconds without any diagnostic request')
        elif self.data['state'] not in {'VERIFYING','VERIFIED'}:raise ValueError('Silent idle interrupted; start a new explicit Session to obtain fresh evidence')

    def observe(self,now,send_count,healthy,same_handle):
        if not math.isfinite(now) or now<self.last:self.end('Monotonic clock invalid');return
        gap=now-self.last;self.last=now
        self.data.update(current_send_count=send_count,idle_requests=send_count-self.data['start_send_count'],
            observation_end_monotonic_seconds=now,passive_checks=self.data['passive_checks']+1,maximum_observation_gap_seconds=max(gap,self.data['maximum_observation_gap_seconds']),
            actual_idle_diagnostic_requests=0 if send_count==self.data['start_send_count'] else None,
            post_finish_elapsed_seconds=now-self.started,verification_elapsed_seconds=0. if self.requested is None else now-self.requested,
            same_local_handle=bool(same_handle),passive_handle_healthy=bool(healthy))
        if self.data['state'] in {'INTERRUPTED','VERIFIED'}:return
        if not healthy or not same_handle or send_count!=self.data['start_send_count'] or gap>15:
            self.end('Handle, send count or passive observation continuity changed');return
        if self.requested is not None and now-self.requested>=60:self.data.update(state='VERIFIED',reason='60 seconds passively observed; same local handle and zero admitted send attempts. ECU liveness remains untested.')

    def end(self,reason):
        if self.data['state']!='VERIFIED':self.data.update(state='INTERRUPTED',reason=reason)

    def save(self,directory):
        if self.receipt:return self.receipt
        if self.requested is None or self.data['state'] not in {'VERIFIED','INTERRUPTED'}:return None
        if hashlib.sha256(self.bundle.read_bytes()).hexdigest()!=self.bundle_sha:raise ValueError('Original bundle changed; passive receipt blocked')
        directory=Path(directory).absolute()
        if any(linked(p) or (p/'.git').exists() for p in [directory,*directory.parents]):raise ValueError('Private idle evidence cannot traverse links or a Git tree')
        directory.mkdir(parents=True,exist_ok=True)
        target=directory/('post-export-idle-'+self.data['observation_id']+'.json')
        with target.open('x',encoding='utf-8') as f:json.dump(dict(self.data,original_bundle=str(self.bundle)),f,indent=2);f.flush();os.fsync(f.fileno())
        self.receipt=str(target);return self.receipt

    def snapshot(self):return dict(self.data,receipt_path=self.receipt)
