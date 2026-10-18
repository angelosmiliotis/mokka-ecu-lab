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
        # A completed observation is historical evidence, not current connection state.
        if self.data['state'] in {'INTERRUPTED','VERIFIED'}:return
        if not math.isfinite(now) or now<self.last:self.end('Monotonic clock invalid');return
        gap=now-self.last;self.last=now
        self.data.update(current_send_count=send_count,idle_requests=send_count-self.data['start_send_count'],
            observation_end_monotonic_seconds=now,passive_checks=self.data['passive_checks']+1,maximum_observation_gap_seconds=max(gap,self.data['maximum_observation_gap_seconds']),
            actual_idle_diagnostic_requests=0 if send_count==self.data['start_send_count'] else None,
            post_finish_elapsed_seconds=now-self.started,verification_elapsed_seconds=0. if self.requested is None else now-self.requested,
            same_local_handle=bool(same_handle),passive_handle_healthy=bool(healthy))
        if not healthy or not same_handle or send_count!=self.data['start_send_count'] or gap>15:
            self.end('Handle, send count or passive observation continuity changed');return
        if self.requested is not None and now-self.requested>=60:self.data.update(state='VERIFIED',reason='60 seconds passively observed; same local handle and zero admitted send attempts. ECU liveness remains untested.')

    def end(self,reason):
        if self.data['state'] not in {'VERIFIED','INTERRUPTED'}:self.data.update(state='INTERRUPTED',reason=reason)

    def save(self,directory):
        if self.receipt:return self.receipt
        if self.requested is None or self.data['state'] not in {'VERIFIED','INTERRUPTED'}:return None
        if hashlib.sha256(self.bundle.read_bytes()).hexdigest()!=self.bundle_sha:raise ValueError('Original bundle changed; passive receipt blocked')
        directory=Path(directory).absolute()
        if any(linked(p) or (p/'.git').exists() for p in [directory,*directory.parents]):raise ValueError('Private idle evidence cannot traverse links or a Git tree')
        directory.mkdir(parents=True,exist_ok=True)
        target=directory/('post-export-idle-'+self.data['observation_id']+'.json')
        expected=json.dumps(dict(self.data,original_bundle=str(self.bundle)),indent=2).encode('utf-8')
        if target.exists():
            if target.read_bytes()!=expected:raise ValueError('Existing idle receipt differs; no overwrite permitted')
        else:
            temporary=directory/('.idle-'+uuid.uuid4().hex+'.tmp')
            try:
                with temporary.open('xb') as f:f.write(expected);f.flush();os.fsync(f.fileno())
                # Exclusive atomic publish: a failed write never leaves a partial receipt.
                if os.name=='nt':os.rename(temporary,target)
                else:os.link(temporary,target)
            finally:
                if temporary.exists():temporary.unlink()
        self.receipt=str(target);return self.receipt

    def snapshot(self):return dict(self.data,receipt_path=self.receipt)


def read_idle_receipt(path):
    """Validate a private historical receipt against its immutable original bundle."""
    path=Path(path).absolute()
    if any(linked(p) or (p/'.git').exists() for p in [path,*path.parents]):raise ValueError('Private receipt cannot traverse links or Git')
    if path.stat().st_size>65536:raise ValueError('Idle receipt exceeds size limit')
    data=json.loads(path.read_text(encoding='utf-8'))
    if data.get('schema')!='mokka-post-export-idle-1' or data.get('state') not in {'VERIFIED','INTERRUPTED'}:raise ValueError('Unknown or unfinished idle receipt')
    original=Path(data['original_bundle']).absolute()
    if any(linked(p) or (p/'.git').exists() for p in [original,*original.parents]):raise ValueError('Original bundle cannot traverse links or Git')
    if hashlib.sha256(original.read_bytes()).hexdigest()!=data.get('original_bundle_sha256'):raise ValueError('Original bundle checksum differs')
    if data['state']=='VERIFIED':
        keys=('verification_elapsed_seconds','verification_start_monotonic_seconds','observation_end_monotonic_seconds','maximum_observation_gap_seconds')
        if any(not isinstance(data.get(k),(int,float)) or isinstance(data[k],bool) or not math.isfinite(data[k]) for k in keys):raise ValueError('Invalid passive observation timing')
        if not (60<=data['verification_elapsed_seconds'] and 0<=data['maximum_observation_gap_seconds']<=15 and
            math.isclose(data['verification_elapsed_seconds'],data['observation_end_monotonic_seconds']-data['verification_start_monotonic_seconds'],abs_tol=1e-7) and
            data.get('same_local_handle') is True and data.get('passive_handle_healthy') is True and
            data.get('idle_requests')==data.get('actual_idle_diagnostic_requests')==0 and
            data.get('start_send_count')==data.get('current_send_count')):raise ValueError('Inconsistent VERIFIED evidence')
    return data
