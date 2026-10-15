"""One-click benchmark lifecycle, owned only by the existing serialized worker."""
import math,time,uuid
from collections import Counter,deque
from copy import deepcopy
from mokka_ecu_lab.analysis.obd import distribution,symptom
from mokka_ecu_lab.auto_capture import affirmative_bitmap
from mokka_ecu_lab.logging import Recorder,utc_now
from mokka_ecu_lab.session import export_closed_session
from mokka_ecu_lab.protocols.isotp import parse_reply
import base64

BENCH_PIDS=(0x0D,0x0C,0x0B,0x10) # identical mix at every rate; speed checked once per four sends


class AutoBenchmark:
    maximum_seconds=60.
    maximum_requests=240
    preflight_seconds=30.
    def __init__(self,rate,now,mode):
        if isinstance(rate,bool) or rate not in (1,2,3,4):raise ValueError('Choose 1, 2, 3 or 4 requests/second')
        self.rate=float(rate);self.started=None;self.created=now;self.preflight_deadline=now+self.preflight_seconds
        self.active=True;self.session_id=None;self.ecu=None;self.context_id=None;self.mode=mode
        self.phase='CONNECTING';self.reason='Explicit Start BENCH: parked, brake, ventilation and no competing client acknowledged'
        self.requests=0;self.completed=False;self.ended=None;self.transitions=[];self.categories=Counter();self.latencies=deque(maxlen=240)
        self.last_speed=None;self.pretest={};self.minimum_gap=None;self.previous_wire=None;self.violations=0
    def transition(self,phase,reason):
        self.phase=phase;self.reason=reason;self.transitions.append(dict(phase=phase,reason=reason,timestamp=utc_now()));self.transitions=self.transitions[-32:]
    def begin(self,now):
        self.started=now;self.transition('RUNNING_60S','Fixed 60-second measurement; speed included in shared wire budget')
    def due_pid(self,now):
        if self.started is None or not self.active or now>=self.started+self.maximum_seconds or self.requests>=self.maximum_requests:return None
        return BENCH_PIDS[self.requests%len(BENCH_PIDS)]
    def snapshot(self,now=None):
        now=time.monotonic() if now is None else now
        elapsed=0. if self.started is None else max(0.,(self.ended if self.ended is not None else now)-self.started)
        return dict(kind='AUTO_60S_V1',active=self.active,state=self.phase,reason=self.reason,rate=self.rate,
            pids=[f'{p:02X}' for p in BENCH_PIDS],requests=self.requests,planned_requests=int(self.rate*60),maximum_requests=240,
            maximum_seconds=60,measurement_started_monotonic=self.started,elapsed_seconds=elapsed,remaining_seconds=max(0.,60-elapsed),
            measurement_duration_seconds=elapsed,wall_duration_seconds=max(0.,now-self.created),completed=self.completed,
            ecu=self.ecu,context_id=self.context_id,mode=self.mode,source_kind='SIMULATED' if self.mode=='SIMULATED' else 'ECU_READING',
            session_id=self.session_id,conditions='USER_REPORTED; speed zero is not parking-brake proof',
            speed_check_cadence='One per four transmitted measurement requests, identical at all rates',pretest=self.pretest,
            categories=dict(self.categories),latency_ms=distribution(list(self.latencies)),minimum_wire_gap_ms=self.minimum_gap,
            hard_four_hz_spacing_violations=self.violations,adaptive=False,higher_rate_authorized=False,transitions=deepcopy(self.transitions))


class BenchmarkWorkflow:
    def bench_emit(self,phase=None,reason=None):
        if phase:self.benchmark.transition(phase,reason)
        self.emit('benchmark',self.benchmark.snapshot())
    def bench_check(self,record,pid=None):
        category=symptom(record)
        if category!='OK':raise ValueError(category+': '+record.get('error','invalid reply')+'; not a capacity conclusion')
        if record.get('latency_ms',0)>1000:raise ValueError('EXCESSIVE_LATENCY: application/adapter response exceeded 1000 ms')
        if pid is not None:
            result=parse_reply(base64.b64decode(record['raw_b64']),pid,record['command'])
            if result.errors or len(result.responses)!=1 or result.responses[0].header!=self.benchmark.ecu:raise ValueError('ECU_MISMATCH: exactly the reserved same ECU must respond')
            reply=result.responses[0]
            if reply.negative_code is not None:raise ValueError('ECU_NRC')
            if pid==0x0D:
                if len(reply.data)!=1 or reply.data[0]!=0:raise ValueError('STATIONARY_CHECK: speed missing, invalid or moving')
                self.benchmark.last_speed=record['monotonic_ns']
        return category
    def begin_auto_benchmark(self,options):
        from mokka_ecu_lab.transport import Cancelled
        # Validate before changing any existing operation or recorder.
        if options.get('parked_consent') is not True:raise ValueError('Start BENCH explicitly acknowledges parked conditions')
        rate=options.get('rate',2)
        if isinstance(rate,bool) or not isinstance(rate,(int,float)) or not math.isfinite(rate) or rate not in (1,2,3,4):raise ValueError('Benchmark rate must be 1, 2, 3 or 4 req/s')
        if self.session.active or self.recorder or self.replay or self.polling or self.capture_mode or self.discovery_active or self.requires_reconnect:
            raise ValueError('Existing acquisition/replay owns the adapter. Finish it explicitly before Start BENCH.')
        if self.transport and bool(options.get('simulation'))!=(self.mode=='SIMULATED'):raise ValueError('Selected source differs from idle connection; disconnect explicitly')
        if not options.get('simulation') and not options.get('port','').strip():raise ValueError('Select an outgoing LIVE COM port')
        self.benchmark=AutoBenchmark(rate,time.monotonic(),'SIMULATED' if options.get('simulation') else 'LIVE · hardware unverified')
        self.benchmark_previous_rate=self.rate;self.rate=float(rate);self.auto_receipt=None
        self.emit('auto_reset',dict(context_id=self.context_id));self.bench_emit()
        try:
            self.recorder=Recorder(self.root,self.benchmark.mode,dict(purpose='AUTO_STATIONARY_BENCHMARK',conditions='EXPLICIT_START_BENCH_USER_REPORTED'))
            self.benchmark.session_id=self.recorder.id;self.emit('recording',self.recorder.id)
            reuse=bool(self.transport)
            if not reuse:self.initialize(options)
            self.set_polling(False,'Benchmark owns one serialized acquisition path')
            if not self.can_protocol:raise ValueError('Benchmark requires identified CAN ECU')
            self.benchmark.mode=self.mode;self.benchmark.context_id=self.context_id
            if reuse:self.bench_emit('REUSING_IDLE_CONNECTION','Refresh current bitmap and positive evidence on selected idle connection')
            self.support={};self.support_pages={};self.bitmap_evidence={};self.bitmap_conflicts=set();self.range_configuration={};self.positive_wire_evidence={};self.discovery_observations={}
            record=self.transaction('0100');self.bench_check(record);self.ingest_bitmap(record,0)
            if len(self.support)!=1 or 'headerless' in self.support:raise ValueError('Exactly one identified positive ECU required; no automatic responder choice')
            ecu=next(iter(self.support));self.discovery_target=ecu;self.benchmark.ecu=ecu
            self.bench_emit('ECU_CONFIRMED','One reserved response address; exact calibration remains unverified')
            self.bench_emit('DISCOVERY','Bounded known bitmap/configuration discovery; no full sensor scan')
            self.transport.rate=float(rate);self.transport.discovery_enabled=True
            for cmd in ('ATCAF1','ATCFC1','ATAL'):
                r=self.transaction(cmd);self.bench_check(r)
                if 'OK' not in r['raw_text'].upper():raise ValueError('Adapter CAN setup rejected')
            # Only pages needed by the known MAP/MAF range selectors.
            for base in (32,64):
                if base in self.support[ecu]:
                    r=self.transaction(f'01{base:02X}');self.bench_check(r,base);self.ingest_bitmap(r,base)
            if self.bitmap_conflicts:raise ValueError('Conflicting current bitmaps')
            self.transport.discovery_supported=set(self.support[ecu])
            self.bench_emit('VERIFYING_PRETEST','Verify current configuration, RPM/MAP/MAF and stationary speed')
            for pid in (0x4F,0x50)+BENCH_PIDS:
                if pid in (0x4F,0x50) and not affirmative_bitmap(self.support,self.support_pages,ecu,pid):continue
                if not affirmative_bitmap(self.support,self.support_pages,ecu,pid):raise ValueError(f'Unsupported or unknown required PID 01{pid:02X}')
                r=self.transaction(f'01{pid:02X}');self.bench_check(r,pid)
                sample=self.discovery_observations.get((ecu,pid),{})
                if not sample.get('fields') or not any(f['state']=='AVAILABLE' for f in sample['fields']):raise ValueError('No strictly decoded positive pretest field')
                self.benchmark.pretest[f'{pid:02X}']=dict(transaction_id=r['id'],timestamp=r['timestamp'],context_id=self.context_id,recorded=True)
            if self.stop_io.is_set():raise Cancelled('Explicit Stop during preflight')
            self.discovery_completed=self.discovery_prepared=True
            self.bench_emit('READY','Current stationary pretest valid; recorded separately from measurement')
            self.benchmark.begin(time.monotonic());self.save_capture_evidence();self.bench_emit()
        except Exception as exc:self.end_auto_benchmark(('INTENTIONAL_STOP during preflight: ' if self.stop_io.is_set() else 'PREFLIGHT_TIMEOUT: ' if time.monotonic()>=self.benchmark.preflight_deadline else 'Preflight aborted: ')+str(exc))

    def auto_benchmark_tick(self):
        b=self.benchmark;now=time.monotonic()
        if self.stop_io.is_set():return self.end_auto_benchmark('INTENTIONAL_STOP: user Stop & save')
        pid=b.due_pid(now)
        if pid is None:
            if now<b.started+60:
                # Reaching the send cap never shortens the sixty-second timer.
                self.stop_io.wait(min(.05,b.started+60-now));return
            return self.end_auto_benchmark('Completed fixed 60-second measurement',completed=True)
        # A last-second send must not fabricate a transport failure at window close.
        # Keep the same bounded one-second receive allowance at every fixed rate.
        if max(now,self.transport.last_send+1/b.rate)+1>=b.started+60:
            self.stop_io.wait(min(.05,max(0,b.started+60-now)));return
        r=self.transaction(f'01{pid:02X}')
        if r.get('sent'):
            b.requests+=1;ns=r['monotonic_ns']
            if b.previous_wire is not None:
                gap=(ns-b.previous_wire)/1e6;b.minimum_gap=gap if b.minimum_gap is None else min(b.minimum_gap,gap);b.violations+=gap<250-1e-6
            b.previous_wire=ns
        if r.get('benchmark_phase')!='WINDOW_END_UNSENT':b.categories[symptom(r)]+=1
        if r.get('sent') and symptom(r)=='OK':b.latencies.append(r['latency_ms'])
        if not r.get('sent') and time.monotonic()>=b.started+60:return self.end_auto_benchmark('Completed fixed 60-second measurement',completed=True)
        try:self.bench_check(r,pid)
        except Exception as exc:return self.end_auto_benchmark(str(exc))
        self.bench_emit()
        if b.requests%8==0:self.save_capture_evidence()

    def end_auto_benchmark(self,reason,completed=False):
        b=self.benchmark
        if not isinstance(b,AutoBenchmark):return
        b.ended=time.monotonic();b.completed=completed;b.active=False
        b.transition('FINALIZING' if completed else 'ABORTING',reason);self.bench_emit()
        sid=b.session_id;result=None
        try:
            self.save_capture_evidence();self.close_recording();self.disconnect(finish_recording=False)
            b.transition('FINALIZING','Original journal closed; verifying private export')
            if sid:result=export_closed_session(self.root,sid)
            if result:b.transition('EXPORTED','Private ZIP checksum verified; companion report created')
            b.transition('DISCONNECTED' if completed else 'ABORTED',reason)
            state=b.snapshot();state.update(result or {},disconnected=True,exported=bool(result),outcome='EXPORTED' if completed else 'ABORTED')
        except Exception as exc:
            # Original journal remains recoverable; explicit offline retry only.
            if self.recorder:
                try:self.recorder.file.close();self.recorder.db.close()
                except Exception:pass
                self.recorder=None;self.emit('recording',None)
            try:
                if self.transport:self.disconnect(finish_recording=False)
            except Exception as close_error:
                self.requires_reconnect=True;self.emit('notice','Adapter close failed; explicit cleanup required: '+str(close_error))
            state=b.snapshot();state.update(active=False,state='ABORTED',reason=reason,export_error=str(exc),retry_export=bool(sid),disconnected=not bool(self.transport))
        finally:
            self.rate=getattr(self,'benchmark_previous_rate',4.);self.benchmark=None
        if self.session.data['state']=='CONNECTED':
            self.session.transition('DISCONNECTED','Benchmark closed its idle connection',active=False,adapter_open=False)
            self.publish_session(True)
        self.benchmark_result=state;self.emit('benchmark',state)

    def retry_benchmark_export(self,session_id):
        if self.transport or self.recorder or self.session.active or self.benchmark:raise ValueError('Offline export retry requires idle disconnected app')
        if session_id!=getattr(self,'benchmark_result',{}).get('session_id'):raise ValueError('Unknown failed benchmark')
        from mokka_ecu_lab.session import recover_interrupted_session
        recover_interrupted_session(self.root,session_id)
        state=dict(self.benchmark_result);state.update(export_closed_session(self.root,session_id),retry_export=False,exported=True)
        state.pop('export_error',None);self.benchmark_result=state;self.emit('benchmark',state)
