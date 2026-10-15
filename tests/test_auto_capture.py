"""Constructed evidence and the existing simulator; no private telemetry."""
import hashlib
import json
import time
from zipfile import ZipFile
import pytest
from mokka_ecu_lab.auto_capture import auto_plan, PRESETS, AcquisitionReceipt, affirmative_bitmap
from mokka_ecu_lab.adapter import AcquisitionWorker
from mokka_ecu_lab.adapter.scheduling import PollScheduler
from mokka_ecu_lab.logging import list_sessions
from mokka_ecu_lab.logging.bundle import export_research_bundle
from mokka_ecu_lab.protocols import LIVE_PIDS, DISCOVERY_PIDS
from mokka_ecu_lab.transport.simulator import Simulator
from test_raw_capture import raw_evidence
from test_discovery import fast_clock
from test_negative_responses import wait_event, shutdown


def evidence_all():
    support,pages,samples=raw_evidence()
    for pid in LIVE_PIDS:
        if pid in support['7E8']:
            samples['7E8',pid]=dict(fields=[dict(state='AVAILABLE',value=1)])
    return support,pages,samples


def test_all_eligible_not_only_old_drive_weights_and_one_raw_consent():
    support,pages,samples=evidence_all()
    # Construct an extra basic positive, outside the former recommended subset.
    support['7E8'].add(0x0B); samples['7E8',0x0B]=dict(fields=[dict(state='AVAILABLE',value=110)])
    p=auto_plan(support,pages,samples,'7E8',prepared=True,consent=True)
    assert p['weights'][0x0B]==1 and p['weights'][0x83]==1
    assert 0x7A in p['raw_pids'] and 0x88 not in p['raw_pids']
    assert p['weights'][0x88]==1  # One numeric representation, raw journal retained.
    denied=auto_plan(support,pages,samples,'7E8',prepared=True,consent=False)
    assert 0x7A not in denied['weights'] and 0x88 in denied['weights']
    assert all(w==1 for w in p['weights'].values())
    assert {int(r['pid'],16) for r in p['matrix']}==LIVE_PIDS|DISCOVERY_PIDS


def test_missing_unknown_cross_ecu_and_unframed_samples_are_never_included():
    support,pages,samples=evidence_all()
    pages['7E8'].discard(0x60)
    assert not affirmative_bitmap(support,pages,'7E8',0x7A)
    p=auto_plan(support,pages,samples,'7E8',prepared=True,consent=True)
    assert not set(p['weights']) & {0x7A,0x83,0x85,0x88}
    assert not auto_plan(support,pages,samples,'7E9',prepared=True,consent=True)['weights']
    support,pages,samples=evidence_all(); samples['7E8',0x7A]['framing_valid']=False
    assert 0x7A not in auto_plan(support,pages,samples,'7E8',prepared=True,consent=True)['weights']
    samples.pop(('7E8',0x0B),None)
    assert 0x0B not in auto_plan(support,pages,samples,'7E8',prepared=True,consent=True)['weights']


@pytest.mark.parametrize('preset',PRESETS)
def test_fair_schedule_has_no_starvation_or_duplicate_requests(preset):
    support,pages,samples=evidence_all()
    plan=auto_plan(support,pages,samples,'7E8',prepared=True,consent=True,preset=preset)
    scheduler=PollScheduler(); n=sum(plan['weights'].values())
    calls=[scheduler.next(plan['weights'],plan['weights'],allow_discovery=True) for _ in range(n*10)]
    assert all(calls.count(pid)==weight*10 for pid,weight in plan['weights'].items())
    assert all(pid in calls[i:i+2*n] for i in range(0,len(calls)-2*n,n) for pid in plan['weights'])
    assert plan['weights'].get(0x7A)==(4 if preset in PRESETS[1:] else 1)


def proof_receipt():
    receipt=AcquisitionReceipt(PRESETS[0],True,'2000-01-01T00:00:00+00:00')
    receipt.configure(dict(ecu='7E8',weights={0x7A:1},raw_pids=[0x7A],matrix=[]),
                      session_id='synthetic',context_id='test',mode='SIMULATED',bitmap_evidence={},rate=4)
    receipt.acknowledge({0x7A:1},{0x7A},'7E8','2000-01-01T00:00:00+00:00')
    return receipt


def test_long_drive_receipt_history_is_bounded_and_quality_categories_stay_separate():
    receipt=proof_receipt()
    for index in range(200):
        receipt.transition('READY' if index%2 else 'PARTIAL','Synthetic intermittent result',str(index))
    assert len(receipt.data['transitions'])==64 and receipt.data['older_transition_count']==136
    for status in ('OK','INVALID','TRANSPORT_ERROR','CANCELLED'):
        receipt.track_transaction(dict(status=status,protocol_errors=[dict(category='DECODER_LAYOUT')] if status=='INVALID' else []))
    assert receipt.data['acquisition_status_counts']==dict(OK=1,INVALID=1,TRANSPORT_ERROR=1,CANCELLED=1)
    assert receipt.data['acquisition_error_categories']==dict(DECODER_LAYOUT=1,TRANSPORT_FAILURE=1,INTENTIONAL_CANCELLATION=1)


def frame(index,**changes):
    r=dict(id=str(index),pid='7A',context_id='test',mode='SIMULATED',source_kind='SIMULATED',sent=True,status='OK',
        parsed=[dict(ecu='7E8')],timestamp=f'2000-01-01T00:00:0{index}+00:00',monotonic_ns=index*1000000000,
        raw_samples=[dict(ecu='7E8',framing_valid=True,raw_only=True,data_length=6,payload_hex='00 A0 00 00 00 00')])
    r.update(changes); return r


def test_proof_requires_two_post_append_six_byte_current_ecu_samples():
    receipt=proof_receipt()
    assert receipt.readiness()=='WAITING'
    for r,recorded,active in [(frame(1),False,True),(frame(1),True,False),
        (frame(1,context_id='other'),True,True),(frame(1,mode='LIVE'),True,True),
        (frame(1,parsed=[dict(ecu='7E9')]),True,True),(frame(1,raw_samples=[]),True,True)]:
        receipt.observe(r,[],recorded=recorded,active=active)
    assert receipt.data['dpf']['recorded_positive_six_byte_frames']==0
    receipt.observe(frame(1),[],recorded=True,active=True); assert receipt.readiness()=='WAITING'
    receipt.observe(frame(2),[],recorded=True,active=True); assert receipt.readiness()=='READY'
    assert receipt.data['observed']['7A']['mean_interval_seconds']==1
    assert len(receipt.data['dpf']['first_two_stored_frames'])==2
    assert receipt.readiness(False)=='PARTIAL'


def test_proposed_plan_is_not_a_worker_ack_and_duplicate_frame_is_not_two():
    receipt=AcquisitionReceipt(PRESETS[0],True,'2000-01-01T00:00:00+00:00')
    receipt.configure(dict(ecu='7E8',weights={0x7A:1},raw_pids=[0x7A],matrix=[]),
        session_id='synthetic',context_id='test',mode='SIMULATED',bitmap_evidence={},rate=4)
    assert not receipt.data['effective_schedule'] and not receipt.data['confirmed_raw_pids']
    with pytest.raises(ValueError): receipt.acknowledge({0x7A:2},{0x7A},'7E8','synthetic')
    receipt.acknowledge({0x7A:1},{0x7A},'7E8','synthetic')
    receipt.observe(frame(1),[],recorded=True,active=True)
    receipt.observe(frame(1),[],recorded=True,active=True)
    receipt.observe(frame(2,source_kind='ECU_READING'),[],recorded=True,active=True)
    receipt.observe(frame(2,replay=True),[],recorded=True,active=True)
    assert receipt.data['dpf']['recorded_positive_six_byte_frames']==1
    assert receipt.readiness()=='WAITING'


def test_full_auto_worker_acks_record_connect_discover_schedule_proof_and_export(tmp_path,fast_clock):
    w=AcquisitionWorker(tmp_path)
    try:
        w.submit('full_auto',simulation=True,port='COM4',scenario='Diesel alternative layouts',consent=True,preset=PRESETS[0])
        receipt=wait_event(w,'auto_capture',lambda r:r['state']=='READY',timeout=20)
        assert receipt['dpf']['recorded_positive_six_byte_frames']>=2
        assert receipt['dpf']['worker_scheduled'] and w.recorder
        plan=auto_plan(w.support,w.support_pages,w.discovery_observations,'7E8',prepared=True,consent=True)
        assert w.capture_weights==plan['weights'] and w.capture_raw_pids=={0x7A}
        assert {0x7A,0x83,0x85,0x88,0x0B,0x04} <= w.capture_weights.keys()
        journal=tmp_path/list_sessions(tmp_path)[0]['raw_path']
        records=[json.loads(l) for l in journal.read_text().splitlines()]
        assert records[0]['command']=='ATI'  # Initialization really recorded.
        assert sum(r.get('raw_only',False) and r['command']=='017A' for r in records)>=2
        assert all(not r['decoder'] for r in records if r.get('raw_only'))
        stages=[s['state'] for s in receipt['transitions']]
        assert stages[:4]==['RECORDING','CONNECTING','DISCOVERING','CONFIGURED']
        assert len(receipt['bitmap_evidence'])>=5
        assert all(e['recorded'] for e in receipt['bitmap_evidence'].values())
        w.submit('stop'); w.submit('disconnect'); wait_event(w,'connection',lambda r:r['adapter']=='Disconnected')
        s=list_sessions(tmp_path)[0]; before=hashlib.sha256(journal.read_bytes()).hexdigest()
        export_research_bundle(tmp_path,s['id'],tmp_path/'bundle.zip')
        assert hashlib.sha256(journal.read_bytes()).hexdigest()==before
        with ZipFile(tmp_path/'bundle.zip') as z:
            exported=json.loads(z.read('acquisition-receipt.json'))
            assert exported['dpf_proof_met_before_close']
            assert exported['effective_schedule']==receipt['effective_schedule']
            for line in z.read('SHA256SUMS.txt').decode().splitlines():
                digest,name=line.split('  '); assert hashlib.sha256(z.read(name)).hexdigest()==digest
    finally: shutdown(w)


def test_denied_preset_consent_transmits_nothing(tmp_path,fast_clock):
    w=AcquisitionWorker(tmp_path)
    try:
        w.submit('full_auto',simulation=True,consent=False,preset=PRESETS[0])
        wait_event(w,'notice',lambda r:'consent' in r)
        assert w.transport is None and w.recorder is None
    finally: shutdown(w)


def test_full_auto_wire_cap_all_commands_and_non_starving_capture(tmp_path,monkeypatch):
    calls=[]; original=Simulator._exchange
    def spy(self,command,*args):
        calls.append((self.last_wire_ns,command)); return original(self,command,*args)
    monkeypatch.setattr(Simulator,'_exchange',spy)
    w=AcquisitionWorker(tmp_path)
    try:
        w.submit('full_auto',simulation=True,port='COM4',scenario='Diesel alternative layouts',consent=True,preset=PRESETS[1])
        receipt=wait_event(w,'auto_capture',lambda r:r['state']=='READY',timeout=35)
        deadline=time.monotonic()+20
        while time.monotonic()<deadline:
            receipt=wait_event(w,'auto_capture',lambda r:r['state']=='READY',timeout=10)
            if all(receipt['observed'].get(pid,{}).get('positive_samples',0)>=2 for pid in receipt['effective_schedule']): break
        assert all(receipt['observed'].get(pid,{}).get('positive_samples',0)>=2 for pid in receipt['effective_schedule'])
        assert all(b[0]-a[0]>=250000000 for a,b in zip(calls,calls[1:]))
        assert receipt['rate_limit']==4 and all(1<=v['weight']<=4 for v in receipt['effective_schedule'].values())
        assert not any(c.startswith(('22','27','2E','31','04','ATSH')) for _,c in calls)
        w.submit('stop'); w.submit('disconnect'); wait_event(w,'connection',lambda r:r['adapter']=='Disconnected')
        count=len(calls); time.sleep(.3); assert len(calls)==count
    finally: shutdown(w)


def test_bluetooth_failure_aborts_records_reason_and_never_reconnects(tmp_path,monkeypatch):
    import mokka_ecu_lab.adapter as adapter
    from mokka_ecu_lab.transport import TransportError
    attempts=[]
    def fail(*args,**kwargs): attempts.append(args); raise TransportError('synthetic serial unavailable')
    monkeypatch.setattr(adapter,'SerialTransport',fail)
    w=AcquisitionWorker(tmp_path)
    try:
        w.submit('full_auto',simulation=False,port='COM4',consent=True,preset=PRESETS[0])
        receipt=wait_event(w,'auto_capture',lambda r:r['state']=='FINISHED',timeout=10)
        assert len(attempts)==1 and receipt['capture_outcome']['state']=='ABORTED'
        assert not w.transport and not w.recorder and not receipt['dpf_proof_met_before_close']
        assert list_sessions(tmp_path)[0]['ended']
        w.submit('retry_auto',simulation=False); wait_event(w,'notice',lambda s:'Retry requires' in s)
        assert len(attempts)==1
    finally: shutdown(w)


def test_preflight_timeout_continues_other_sensors_without_retry(tmp_path,monkeypatch):
    monkeypatch.setattr(AcquisitionWorker,'start',lambda self:None)
    w=AcquisitionWorker(tmp_path); w.auto_receipt=proof_receipt()
    w.auto_receipt.transition('WAITING_RAW','waiting','synthetic')
    from types import SimpleNamespace
    w.capture_mode=w.polling=True; w.recorder=SimpleNamespace(id='synthetic'); w.auto_deadline=time.monotonic()-1
    monkeypatch.setattr(w,'save_capture_evidence',lambda:None)
    w.update_auto_receipt()
    assert w.auto_receipt.data['state']=='PARTIAL' and w.polling
    assert w.commands.empty()


@pytest.mark.parametrize('missing',['unsupported','malformed'])
def test_missing_dpf_is_partial_while_other_sensors_continue_without_raw_probes(tmp_path,fast_clock,monkeypatch,missing):
    calls=[]; original=Simulator._exchange; original_init=Simulator.__init__
    def initialize(self,*a,**k):
        original_init(self,*a,**k)
        if missing=='unsupported': self.supported_fixture.discard(0x7A)
    def exchange(self,command,*a):
        calls.append(command)
        if command=='017A' and missing=='malformed': return b'7E8 10 08 41 7A 00 AA 00 00\r>'
        return original(self,command,*a)
    monkeypatch.setattr(Simulator,'__init__',initialize); monkeypatch.setattr(Simulator,'_exchange',exchange)
    w=AcquisitionWorker(tmp_path)
    try:
        w.submit('full_auto',simulation=True,port='COM4',scenario='Diesel alternative layouts',consent=True,preset=PRESETS[0])
        receipt=wait_event(w,'auto_capture',lambda r:r['state']=='PARTIAL',timeout=15)
        assert w.polling and w.recorder and 0x7A not in w.capture_weights
        assert receipt['dpf']['recorded_positive_six_byte_frames']==0
        assert {0x83,0x85,0x88}<=w.capture_weights.keys()
        for _ in range(3): wait_event(w,'transaction',lambda r:r[0]['command']=='0183')
        assert calls.count('017A')==(0 if missing=='unsupported' else 1)
    finally: shutdown(w)


def test_duplicate_initial_bitmap_frames_abort_before_unknown_sensor_probing(tmp_path,fast_clock,monkeypatch):
    calls=[]; original=Simulator._exchange
    def exchange(self,command,*a):
        calls.append(command)
        if command=='0100': return b'7E8 06 41 00 18 18 00 01\r7E8 06 41 00 00 00 00 00\r>'
        return original(self,command,*a)
    monkeypatch.setattr(Simulator,'_exchange',exchange); w=AcquisitionWorker(tmp_path)
    try:
        w.submit('full_auto',simulation=True,port='COM4',scenario='Diesel alternative layouts',consent=True,preset=PRESETS[0])
        receipt=wait_event(w,'auto_capture',lambda r:r['state']=='FINISHED',timeout=15)
        assert receipt['capture_outcome']['state']=='ABORTED'
        # Strict framing rejects duplicate same-source replies before bitmap
        # ingestion, so no ECU can be positively selected from this response.
        assert 'No unique verified ECU' in receipt['capture_outcome']['reason']
        assert [c for c in calls if c.startswith('01')]==['0100']
        assert not w.transport and not w.recorder
    finally: shutdown(w)
