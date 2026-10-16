"""Worker owns transport, recorder, discovery, polling and streaming replay."""
import base64
import queue
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from mokka_ecu_lab.transport import SerialTransport, TransportError, Cancelled
from mokka_ecu_lab.transport.simulator import Simulator
from mokka_ecu_lab.protocols import parse_obd, supported_pids, LIVE_PIDS, BITMAP_PIDS, DISCOVERY_PIDS, EXTENSION_PIDS
from mokka_ecu_lab.protocols.isotp import parse_reply
from mokka_ecu_lab.sensors.diesel import STANDARD_DIESEL
from mokka_ecu_lab.discovery import discovery_report
from mokka_ecu_lab.sensors import load_registry
from mokka_ecu_lab.sensors.extended import basic_range
from .pacing import AdaptivePacing, StationaryBenchmark
from .benchmark import AutoBenchmark, BenchmarkWorkflow
from mokka_ecu_lab.logging import Recorder, utc_now
from mokka_ecu_lab.replay import Replay
from .scheduling import PollScheduler
from mokka_ecu_lab.capture import capture_plan, DECODER_VERSION
from mokka_ecu_lab.layouts import RAW_ONLY_PIDS, layout_evidence
from mokka_ecu_lab.auto_capture import auto_plan, AcquisitionReceipt, PRESETS, affirmative_bitmap
from mokka_ecu_lab import __version__
from mokka_ecu_lab.session import SessionCoordinator, CONFLICTS, export_closed_session, recover_interrupted_session

class AcquisitionWorker(BenchmarkWorkflow,threading.Thread):
    def __init__(self, root: Path):
        super().__init__(name="serialized-obd-worker", daemon=False)
        self.root = root
        self.commands = queue.Queue(maxsize=64)
        self.events = queue.Queue(maxsize=512)
        self.stop_io = threading.Event()
        self.quit_event = threading.Event()
        self.transport = self.recorder = self.replay = None
        self.benchmark=None
        self.connection_state={'stage':'DISCONNECTED','reason':'No open handle; OS pairing state unknown'}
        self.idle_health_checked=time.monotonic()
        self.registry = load_registry()
        self.selected = list(self.registry)
        self.adapter, self.protocol, self.port, self.mode = "Unknown", "Unknown", "", "Disconnected"
        self.support = {}
        self.support_pages = {}
        self.discovery_observations = {}
        self.discovery_active = False
        self.discovery_target = None
        self.discovery_prepared = False
        self.discovery_completed = False
        self.capture_mode = False
        self.capture_weights = {}
        self.capture_raw_pids = set()
        self.auto_receipt = None
        self.auto_starting = False
        self.auto_deadline = None
        self.auto_last_save = 0.
        self.bitmap_evidence = {}
        self.bitmap_conflicts = set()
        self.session = SessionCoordinator()
        self.session_internal = False
        self.session_last_publish = 0.
        self.last_application_send_ns = 0
        self.can_protocol = False
        self.polling = False
        self.priorities = {}
        self.scheduler = PollScheduler()
        self.failures = 0
        self.requires_reconnect = False
        self.context_id = uuid.uuid4().hex
        self.rate = 4.0
        self.pacing=AdaptivePacing(self.rate)
        self.range_configuration={}
        self.positive_wire_evidence={}
        self.dropped = 0
        self.replay_playing = False
        self.replay_speed = 1.0
        self.pending_record = None
        self.pending_markers = {}
        self.marker_lock = threading.Lock()
        self.replay_previous = None
        self.replay_due = 0.0
        self.start()

    def emit(self, kind, value):
        try: self.events.put_nowait((kind, value))
        except queue.Full:
            self.dropped += 1  # Only UI preview is bounded/dropped, never recorded transactions.
            if kind != "transaction":
                try: self.events.get_nowait()
                except queue.Empty: pass
                try: self.events.put_nowait((kind, value))
                except queue.Full: pass

    def submit(self, action, **kwargs):
        if self.benchmark and self.benchmark.active and action not in {'benchmark_stop','bench_auto_stop','shutdown','disconnect','system_suspend'}:
            self.emit('notice','Stationary benchmark owns acquisition; stop it first');return False
        if self.session.active and action in CONFLICTS:
            self.emit('session_rejected', 'Automatic session owns acquisition; Finish Session first')
            return False
        if action in {'session_finish','shutdown'}: self.session.finish_requested=True
        if action in {'benchmark_stop','bench_auto_stop'}:self.stop_io.set()
        if action=='bench_auto_start':self.stop_io.clear()
        if action=='marker':
            token=uuid.uuid4().hex
            recorder=self.recorder
            with self.marker_lock:
                self.pending_markers[token]=dict(kwargs,session_id=recorder.id if recorder else None,
                                                timestamp=utc_now(),monotonic_ns=time.monotonic_ns())
            kwargs={'marker_id':token}
        if action in {"connect", "start", "discover", "monitor_discovery", "drive_capture", "full_auto", "retry_auto", "session_connect", "session_start", "benchmark_start"}:
            # Clear only at user submission, so a later Stop cancels queued Connect too.
            self.stop_io.clear()
        if action in {"disconnect", "stop", "shutdown", "replay", "session_finish",'system_suspend'}:
            self.stop_io.set()
        try: self.commands.put_nowait((action, kwargs))
        except queue.Full:
            if action=='marker':
                with self.marker_lock: self.pending_markers.pop(kwargs['marker_id'],None)
            raise
        return True

    def transaction(self, command,timeout=6.):
        sent_ns, stamp = time.monotonic_ns(), utc_now()
        raw, error, status, readings, parsed, rejections = b"", "", "OK", [], [], []
        protocol_errors, discovery_samples = [], []
        try:
            if isinstance(self.benchmark,AutoBenchmark):
                deadline=self.benchmark.preflight_deadline if self.benchmark.started is None else self.benchmark.started+60
                self.transport.operation_deadline_ns=int(deadline*1e9)
                if time.monotonic()>=deadline:raise Cancelled('Benchmark phase monotonic deadline')
            raw = self.transport.exchange(command, self.stop_io,timeout=timeout)
            if command.startswith("01"):
                pid = int(command[2:], 16)
                result = parse_reply(raw, pid, command)
                replies = result.responses
                protocol_errors.extend(result.errors)
                for reply in replies:
                    if reply.negative_code is not None:
                        rejections.append(reply.rejection())
                        continue
                    source = reply.header or "headerless"
                    if pid in BITMAP_PIDS and len(reply.data) != 4:
                        protocol_errors.append({'ecu': reply.header, 'reason':'Support bitmap must contain exactly four bytes', 'state':'INVALID'})
                        continue
                    parsed.append({"ecu": reply.header, "data_hex": reply.data.hex(' ').upper()})
                    if pid in STANDARD_DIESEL:
                        sample = self.diesel_sample(reply, pid, stamp, sent_ns,
                                                    raw_only=self.capture_mode and pid in self.capture_raw_pids)
                        discovery_samples.append(sample)
                        if sample.get('error'):
                            protocol_errors.append({'ecu':reply.header, 'reason':sample['error'], 'state':'INVALID',
                                                    'category':'DECODER_LAYOUT'})
                        else:
                            readings.extend(self.diesel_readings(sample, pid, stamp, sent_ns))
                            if pid in {0x4F,0x50}:self.range_configuration.setdefault(source,{})[pid]=reply.data
                    if pid in self.registry:
                        if pid not in self.support.get(source, set()):
                            continue
                        sensor = self.registry[pid]
                        try: decoded = basic_range(sensor,reply.data,self.range_configuration.get(source,{}),self.support.get(source,set()))
                        except ValueError as exc:
                            protocol_errors.append({'ecu':reply.header, 'reason':str(exc), 'state':'INVALID','category':'DECODER_LAYOUT'}); continue
                        readings.append({"sensor_id": sensor.id, "pid": pid, "ecu": reply.header,
                            "value": decoded, "unit": sensor.unit,
                            "verification": sensor.metadata["verification"], "timestamp": stamp,
                            "monotonic_ns": sent_ns, "decoder": sensor.id, "mode": self.mode,
                            "source_kind": "SIMULATED" if self.mode == "SIMULATED" else "ECU_READING"})
                if rejections:
                    status = "ECU_NEGATIVE_RESPONSE"
                    error = '; '.join(f'{r["ecu"] or "headerless"}: {r["reason"]} (7F 01 {r["nrc"]})' for r in rejections)
                if protocol_errors:
                    status = 'INVALID'
                    error = '; '.join(filter(None, [error] + [f'{e["ecu"] or "unknown source"}: {e["reason"]}' for e in protocol_errors]))
        except TransportError as exc:
            raw, error, status = exc.raw, str(exc), "CANCELLED" if isinstance(exc, Cancelled) else "TRANSPORT_ERROR"
        except ValueError as exc:
            error, status = str(exc), "INVALID"
        wire_ns = self.transport.last_wire_ns
        if wire_ns is not None:
            self.last_application_send_ns=wire_ns
            stamp = datetime.fromtimestamp(time.time() - (time.monotonic_ns() - wire_ns) / 1e9, timezone.utc).isoformat(timespec='microseconds')
            sent_ns = wire_ns
            for reading in readings:
                reading["timestamp"], reading["monotonic_ns"] = stamp, sent_ns
        for reading in readings:
            if reading['pid'] in self.registry:
                sensor=self.registry[reading['pid']]
                self.discovery_observations[reading['ecu'] or 'headerless',reading['pid']] = dict(
                    ecu=reading['ecu'],pid=reading['pid'],timestamp=stamp,monotonic_ns=sent_ns,
                    source_kind=reading['source_kind'],replay=False,
                    fields=[dict(sensor_id=sensor.id,name=sensor.name,value=reading['value'],unit=sensor.unit,state='AVAILABLE')])
        for sample in discovery_samples:
            sample['timestamp'], sample['monotonic_ns'] = stamp, sent_ns
            if sample.get('raw_only'):
                sample['context_readings'] = self.raw_context(sample['ecu'] or 'headerless', sent_ns)
            self.discovery_observations[sample['ecu'] or 'headerless', int(command[2:],16)] = sample
        record = {"id": uuid.uuid4().hex, "timestamp": stamp, "monotonic_ns": sent_ns,
            "port": self.port, "adapter": self.adapter, "protocol": self.protocol, "mode": self.mode,
            "context_id": self.context_id, "source_kind": "SIMULATED" if self.mode == "SIMULATED" else "ECU_READING",
            "serial_settings": {"baud": getattr(self.transport, "baud", None), "data_bits": 8, "parity": "N", "stop_bits": 1},
            "request_id": command, "pid": command[2:] if command.startswith("01") else None,
            "command": command, "outbound_b64": base64.b64encode((command + '\r').encode()).decode(),
            "sent": wire_ns is not None,
            "raw_b64": base64.b64encode(raw).decode(), "raw_text": raw.decode("ascii", "replace"),
            "latency_ms": (time.monotonic_ns() - sent_ns) / 1e6, "status": status,
            "parsed": parsed, "negative_responses": rejections, "decoder": [r["decoder"] for r in readings],
            "protocol_errors": protocol_errors, "discovery_samples": discovery_samples,
            "verification": [r["verification"] for r in readings], "error": error}
        record.update(application_version=__version__,decoder_version=DECODER_VERSION)
        if isinstance(self.benchmark,AutoBenchmark):
            record.update(benchmark_run_id=self.benchmark.session_id,benchmark_phase='MEASUREMENT' if self.benchmark.started is not None else 'PREFLIGHT',benchmark_requested_rate=self.benchmark.rate,benchmark_ecu=self.benchmark.ecu)
            if self.benchmark.started is not None and not record['sent'] and not self.stop_io.is_set() and time.monotonic()>=self.benchmark.started+60:record['benchmark_phase']='WINDOW_END_UNSENT'
        record['range_configuration']={ecu:{f'{pid:02X}':value.hex(' ').upper() for pid,value in ranges.items()} for ecu,ranges in self.range_configuration.items()}
        record.update(effective_request_rate_hz=self.transport.rate,policy_ceiling_hz=min(4.,self.rate),
            pacing_mode='FIXED_STATIONARY_BENCHMARK' if self.benchmark and self.benchmark.active else 'ADAPTIVE' if self.session.active and self.capture_mode else 'FIXED_POLICY')
        record['raw_only'] = bool(self.capture_mode and command.startswith('01') and int(command[2:],16) in self.capture_raw_pids)
        record['raw_samples'] = [s for s in discovery_samples if s.get('raw_only')]
        if record['sent'] and record['status']=='OK':
            for reading in readings:
                if reading['pid'] not in {0x0C,0x0B,0x10}:continue
                key=(reading['ecu'],reading['pid'])
                self.positive_wire_evidence[key]={k:record[k] for k in ('id','command','timestamp','monotonic_ns','raw_b64','context_id','mode','source_kind','status')}
            while len(self.positive_wire_evidence)>128:self.positive_wire_evidence.pop(next(iter(self.positive_wire_evidence)))
        if command.startswith('01') and int(command[2:],16) in DISCOVERY_PIDS:
            record['support_evidence'] = {e:sorted(p) for e,p in self.support.items()}
            record['support_pages'] = {e:sorted(p) for e,p in self.support_pages.items()}
        self.retain_discovery_errors(record)
        if self.recorder: self.recorder.append(record, readings)
        if self.session.active and self.capture_mode and not self.auto_starting and not self.benchmark:
            if self.pacing.observe(record,time.monotonic()):
                self.transport.rate=self.pacing.rate
                self.emit('notice',f'Adaptive aggregate pacing {self.pacing.rate:g} req/s: {self.pacing.reason}')
            if self.auto_receipt:
                self.auto_receipt.data['adaptive_pacing']=self.pacing.snapshot()
                for entry in self.auto_receipt.data['effective_schedule'].values():
                    entry['nominal_interval_seconds']=sum(self.capture_weights.values())/(entry['weight']*self.transport.rate)
        if self.auto_receipt:
            if self.recorder and (self.auto_starting or self.auto_receipt.data['state'] in {'WAITING_RAW','PARTIAL','READY'}):
                self.auto_receipt.track_transaction(record)
            self.auto_receipt.observe(record, readings, recorded=bool(self.recorder),
                active=self.capture_mode and self.auto_receipt.data['state'] in {'WAITING_RAW','PARTIAL','READY'})
            self.update_auto_receipt()
        if self.session.active and not self.auto_starting:
            self.publish_session()
        self.emit("transaction", (record, readings))
        if isinstance(self.benchmark,AutoBenchmark):
            if self.benchmark.started is None:
                from mokka_ecu_lab.analysis.obd import symptom
                if status!='OK':raise ValueError(symptom(record)+': '+error)
                if record['latency_ms']>1000:raise ValueError('EXCESSIVE_LATENCY: preflight response exceeded 1000 ms')
            return record # Already journaled; coordinator classifies/counts even failed measurement sends.
        if status == "TRANSPORT_ERROR":
            raise TransportError(error, raw)
        if status == "CANCELLED": raise Cancelled(error, raw)
        return record

    def raw_context(self, ecu, sent_ns):
        context = {}
        for pid, name in ((0x0C,'rpm'),(0x0D,'speed')):
            sample = self.discovery_observations.get((ecu,pid),{})
            field = next((f for f in sample.get('fields',[]) if f.get('state')=='AVAILABLE'),None)
            if field and not sample.get('error') and sample.get('monotonic_ns',sent_ns+1)<=sent_ns:
                context[name] = dict(value=field['value'],unit=field['unit'],ecu=ecu,
                    timestamp=sample['timestamp'],monotonic_ns=sample['monotonic_ns'],
                    age_seconds=(sent_ns-sample['monotonic_ns'])/1e9,source_kind=sample['source_kind'],
                    simultaneous=False)
            else: context[name] = dict(value=None,state='UNAVAILABLE',simultaneous=False)
        return context

    def diesel_sample(self, reply, pid, stamp, sent_ns, replay_mode=None, raw_only=False):
        sample = {'ecu':reply.header, 'pid':pid, 'payload_hex':reply.data.hex(' ').upper(),
                  'timestamp':stamp, 'monotonic_ns':sent_ns,
                  'source_kind':'SIMULATED' if (replay_mode or self.mode) == 'SIMULATED' else 'ECU_READING' if (replay_mode or self.mode).startswith('LIVE') else 'UNKNOWN',
                  'replay':replay_mode is not None, 'fields':[], 'framing_valid':True,
                  **layout_evidence(pid,reply.data)}
        source = reply.header or 'headerless'
        if pid not in self.support.get(source, set()):
            sample['not_decoded'] = 'No ECU-specific support evidence; payload retained without measurements'
            sample['layout_status'] = 'NO_SUPPORT_EVIDENCE'
            return sample
        if raw_only and pid in RAW_ONLY_PIDS:
            sample.update(raw_only=True,acquisition='RAW ONLY / '+sample['layout_status'],
                          numeric_decoder_enabled=False)
            return sample
        try: sample['fields'] = STANDARD_DIESEL[pid].decode(reply.data)
        except ValueError as exc: sample['error'] = str(exc)
        return sample

    def retain_discovery_errors(self, record):
        if not record.get('pid') or int(record['pid'],16) not in (STANDARD_DIESEL.keys() | self.registry.keys()): return
        pid = int(record['pid'],16)
        problems = list(record.get('protocol_errors',[]))
        problems += [dict(ecu=e['ecu'],reason=f"{e['reason']} (7F 01 {e['nrc']})")
                     for e in record.get('negative_responses',[])]
        if not problems and record['status'] in {'INVALID','TRANSPORT_ERROR','CANCELLED'}:
            problems = [dict(ecu=self.discovery_target,reason=record['error'])]
        for problem in problems:
            source = problem['ecu'] or (self.discovery_target if self.capture_mode else None) or 'unknown'
            prior=self.discovery_observations.get((source,pid),{})
            last_valid=prior.get('last_valid_sample')
            if prior.get('fields') and not prior.get('error'):
                last_valid={k:prior[k] for k in ('ecu','pid','timestamp','monotonic_ns','fields','source_kind') if k in prior}
            sample = dict(prior,
                          ecu=problem['ecu'] or (source if source!='unknown' else None),pid=pid,error=problem['reason'],
                          error_timestamp=record['timestamp'],raw_b64=record['raw_b64'],
                          replay=record.get('replay',False),source_kind=record.get('source_kind','UNKNOWN'))
            sample.update(last_valid_sample=last_valid,last_attempt=dict(status=record['status'],timestamp=record['timestamp'],reason=problem['reason']))
            if problem.get('category')!='DECODER_LAYOUT':
                sample.update(framing_valid=False,raw_only=False,layout_status='INVALID_RESPONSE')
            self.discovery_observations[source,pid] = sample
        # Raw framing belongs to the whole transaction, including failed replies.
        for sample in record.get('discovery_samples',[]): sample['raw_b64'] = record['raw_b64']

    def diesel_readings(self, sample, pid, stamp, sent_ns):
        return [dict(sensor_id=f['sensor_id'], pid=pid, ecu=sample['ecu'], value=f['value'], unit=f['unit'],
                     verification=f['verification'], timestamp=stamp, monotonic_ns=sent_ns,
                     display=f.get('display'),
                     decoder=f['sensor_id'], mode=self.mode, source_kind=sample['source_kind'])
                for f in sample['fields'] if f['state']=='AVAILABLE']

    def emit_discovery(self, active=False, reason='Recorded samples; vehicle unverified'):
        self.emit('discovery', dict(discovery_report(self.support, self.support_pages, self.discovery_observations,
                                                   mode=self.mode, context_id=self.context_id), active=active, reason=reason,
                                     prepared=self.discovery_prepared,target=self.discovery_target))
        self.save_capture_evidence()

    def save_capture_evidence(self):
        if self.recorder:
            self.recorder.evidence(self.capture_evidence())

    def capture_evidence(self):
        return dict(application_version=__version__,decoder_version=DECODER_VERSION,
                evidence_saved_at=utc_now(),
                context_id=self.context_id,mode=self.mode,discovery_prepared=self.discovery_prepared,
                discovery_completed=self.discovery_completed,
                discovery_target=self.discovery_target,capture_weights=self.capture_weights,
                capture_raw_pids=sorted(self.capture_raw_pids),
                acquisition_receipt=self.auto_receipt.snapshot() if self.auto_receipt else None,
                stationary_benchmark=self.benchmark.snapshot() if self.benchmark else None,
                session_coordinator=self.session.snapshot() if self.session.active else None,
                support={e:sorted(p) for e,p in self.support.items()},
                support_pages={e:sorted(p) for e,p in self.support_pages.items()},
                report=discovery_report(self.support,self.support_pages,self.discovery_observations,mode=self.mode,context_id=self.context_id))

    def start_benchmark(self,options):
        if options.get('parked_consent') is not True:raise ValueError('Explicit parked/brake/ventilation/no-other-client consent required')
        if self.session.active or self.recorder or self.replay or not self.transport or not self.can_protocol or self.polling or self.requires_reconnect or not self.discovery_completed:
            raise ValueError('Benchmark requires connected idle current Discovery, no recording/automatic session; use Advanced while parked')
        target=self.discovery_target
        pids=[p for p in (0x0C,0x0B,0x10) if affirmative_bitmap(self.support,self.support_pages,target,p) and
              self.positive_wire_evidence.get((target,p),{}).get('context_id')==self.context_id and
              0<=(time.monotonic_ns()-self.discovery_observations.get((target,p),{}).get('monotonic_ns',0))/1e9<=60 and
              not self.discovery_observations.get((target,p),{}).get('error') and any(f.get('state')=='AVAILABLE' for f in self.discovery_observations.get((target,p),{}).get('fields',[]))]
        rate=float(options.get('rate',2.))
        if not .25<=rate<=min(self.rate,4.):raise ValueError('Benchmark exceeds configured approved ceiling')
        self.benchmark=StationaryBenchmark(pids,rate,time.monotonic(),ecu=target,context_id=self.context_id,mode=self.mode)
        self.auto_receipt=None;self.emit('auto_reset',dict(context_id=self.context_id))
        self.recorder=Recorder(self.root,self.mode,{'purpose':'EXPLICIT_STATIONARY_BENCHMARK','conditions':'USER_REPORTED','higher_rate_authorized':False,
            'pretest_evidence_provenance':'UNRECORDED_CURRENT_CONNECTION; not benchmark polling proof',
            'pretest_positive_wire_evidence':{f'{p:02X}':self.positive_wire_evidence[target,p] for p in pids},
            'pretest_original_bitmap_evidence':self.bitmap_evidence.get(target,{})})
        self.emit('recording',self.recorder.id)
        self.benchmark.session_id=self.recorder.id
        self.transport.rate=rate;self.save_capture_evidence();self.emit('benchmark',self.benchmark.snapshot())

    def finish_benchmark(self,reason=None):
        if isinstance(self.benchmark,AutoBenchmark):return self.end_auto_benchmark(reason or 'INTENTIONAL_STOP: Stop & save')
        if not self.benchmark:return
        self.benchmark.active=False
        if reason:self.benchmark.reason=reason
        result=self.benchmark.snapshot();sid=self.recorder.id if self.recorder else None
        self.close_recording();self.disconnect(finish_recording=False)
        try:
            if sid:result.update(export_closed_session(self.root,sid))
        except Exception as exc:result['export_error']=str(exc)
        result.update(active=False,disconnected=True);self.emit('benchmark',result);self.benchmark=None

    def benchmark_tick(self):
        if isinstance(self.benchmark,AutoBenchmark):return self.auto_benchmark_tick()
        pid=self.benchmark.next_pid(time.monotonic())
        if pid is None:return self.finish_benchmark('Fixed benchmark completed at request/time bound')
        remaining=self.benchmark.maximum_seconds-(time.monotonic()-self.benchmark.started)-1/self.benchmark.rate
        if remaining<=.1:return self.finish_benchmark('Fixed benchmark duration bound reached')
        record=self.transaction(f'01{pid:02X}',timeout=min(6.,remaining));self.benchmark.observe(record)
        self.emit('benchmark',self.benchmark.snapshot())
        if not self.benchmark.active:self.finish_benchmark()

    def emit_capture(self,reason):
        self.emit('capture',dict(active=self.capture_mode,weights=dict(self.capture_weights),
                                 raw_pids=sorted(self.capture_raw_pids),
                                 ecu=self.discovery_target,reason=reason,context_id=self.context_id))

    def auto_stage(self, state, reason):
        if not self.auto_receipt: return
        self.auto_receipt.transition(state, reason, utc_now())
        self.auto_receipt.data.update(context_id=self.context_id,mode=self.mode,
            adapter_open=bool(self.transport), recording_active=bool(self.recorder),
            source_kind='SIMULATED' if self.mode=='SIMULATED' else 'ECU_READING' if self.mode.startswith('LIVE') else 'UNKNOWN',
            session_id=self.recorder.id if self.recorder else self.auto_receipt.data.get('session_id'))
        self.auto_receipt.readiness(state in {'WAITING_RAW','PARTIAL','READY'} and self.capture_mode and self.polling and bool(self.recorder))
        self.emit('auto_capture',self.auto_receipt.snapshot())
        self.save_capture_evidence()
        if self.session.active:
            mapping={'RECORDING':'RECORDING_SETUP','DISCOVERING':'DISCOVERING','CONFIGURED':'CONFIGURING',
                     'WAITING_RAW':'CAPTURING','READY':'CAPTURING','PARTIAL':'PARTIAL','ABORTED':'FAILED','STOPPED':'PARTIAL'}
            if state in mapping: self.session_stage(mapping[state],reason)

    def update_auto_receipt(self, force=False):
        if not self.auto_receipt: return
        now=time.monotonic(); data=self.auto_receipt.data
        previous=data['dpf']['state']
        ready=self.auto_receipt.readiness(data['state'] in {'WAITING_RAW','PARTIAL','READY'} and self.capture_mode and self.polling and bool(self.recorder))
        if data['state'] in {'WAITING_RAW','PARTIAL','READY'} and ready=='READY' and data['state']!='READY':
            self.auto_stage('READY',data['dpf']['reason']); force=True
        elif data['state']=='READY' and ready=='PARTIAL':
            self.auto_stage('PARTIAL',data['dpf']['reason']); force=True
        elif data['state']=='WAITING_RAW' and self.auto_deadline is not None and now>=self.auto_deadline:
            self.auto_stage('PARTIAL','Bounded preflight expired; 017A proof incomplete. Other eligible sensors continue; inspect while parked.')
            force=True
        if force or ready!=previous or now-self.auto_last_save>=1.:
            self.emit('auto_capture',self.auto_receipt.snapshot())
        if force or now-self.auto_last_save>=5.:
            self.save_capture_evidence(); self.auto_last_save=now

    def reject_auto(self, reason):
        self.emit('notice',reason)
        self.emit('auto_rejected',dict(context_id=self.context_id,reason=reason))

    def full_auto(self, options):
        """One deliberate action; all writes use the existing serialized path."""
        preset=options.get('preset',PRESETS[0])
        if options.get('consent') is not True or preset not in PRESETS:
            self.reject_auto('Full Auto requires explicit single-preset RAW consent and a known preset'); return
        if self.replay or self.requires_reconnect:
            self.reject_auto('Leave replay / reconnect explicitly after failures before Full Auto'); return
        reuse=bool(self.transport)
        if reuse and not options.get('reuse'):
            self.reject_auto('Adapter already open; explicitly use current ECU connection or disconnect first'); return
        if reuse and bool(options.get('simulation')) != (self.mode=='SIMULATED'):
            self.reject_auto('Selected source differs from current connection; disconnect explicitly'); return
        if not reuse and not options.get('simulation') and not options.get('port','').strip():
            self.reject_auto('Select an outgoing LIVE serial port before Full Auto'); return
        if self.recorder and self.recorder.count and not reuse:
            self.reject_auto('Finish the previous recording before starting a new connection'); return
        # No previously observed session may authorize the current preset.
        previous=self.auto_receipt.snapshot() if self.auto_receipt and self.recorder and self.auto_receipt.data.get('session_id')==self.recorder.id else None
        consent_time=options.get('inherited_consent_timestamp') or utc_now()
        self.auto_receipt=AcquisitionReceipt(preset,True,consent_time)
        if options.get('session_recording'):
            self.auto_receipt.data.update(consent_provenance='EXPLICIT_START_SESSION_FIXED_READ_ONLY_PROFILE',
                pre_connect_initialization_recorded=False)
        self.auto_receipt.data['requested_source']='SIMULATION' if options.get('simulation') else 'LIVE'
        if previous:
            history=previous.pop('previous_attempts',[])
            self.auto_receipt.data['previous_attempts']=(history+[previous])[-16:]
            self.auto_receipt.data['previous_attempts_truncated']=len(history)+1>16 or previous.get('previous_attempts_truncated',False)
        if options.get('inherited_consent_timestamp'):
            self.auto_receipt.data['consent_provenance']='INHERITED_FROM_THIS_PRESET_RUN; explicit parked Retry action'
        self.auto_starting=True
        try:
            self.handle('record',{})
            if not self.recorder: raise ValueError('Recording did not start')
            self.auto_stage('RECORDING','Recording acknowledged before session Discovery; pre-Connect initialization was not recorded' if reuse else 'Recording acknowledged before connection; initialization retained')
            if not reuse:
                self.auto_stage('CONNECTING','Opening explicitly selected source; awaiting positive ECU response')
                self.initialize(options)
            if self.stop_io.is_set(): raise Cancelled('Full Auto stopped before Discovery')
            if not self.transport or not self.can_protocol:
                raise ValueError('Identified ISO 15765-4 CAN ECU required; no arbitrary probing')
            candidates=[e for e in self.support if e!='headerless']
            target=options.get('ecu')
            if not target and len(candidates)==1: target=candidates[0]
            if target not in candidates:
                raise ValueError('No unique verified ECU; select the responding ECU explicitly while parked')
            self.auto_receipt.data['ecu']=target
            if any(e==target for e,base in self.bitmap_conflicts):
                raise ValueError('Conflicting raw bitmap evidence for current ECU; no automatic sensor probing')
            self.auto_stage('DISCOVERING',f'ECU {target} confirmed; bounded standard supported-PID Discovery')
            if options.get('session_recording'):
                # Reacquire the entire chain inside this journal; old connection samples
                # must never masquerade as recorded session Discovery evidence.
                self.support={}; self.support_pages={}; self.bitmap_evidence={}; self.bitmap_conflicts=set()
                self.discovery_observations={}
                self.range_configuration={}
                self.positive_wire_evidence={}
                self.ingest_bitmap(self.transaction('0100'),0)
                if target not in self.support: raise ValueError('Current recorded bitmap does not confirm the connected ECU')
            self.discover(target)
            if not self.discovery_prepared or self.requires_reconnect or self.stop_io.is_set():
                raise ValueError('Discovery did not complete; no automatic retry')
            if any(e==target for e,base in self.bitmap_conflicts):
                raise ValueError('Conflicting raw bitmap evidence for current ECU; Full Auto aborted without sensor probing')
            # Known basic measurements also need one strict positive sample.
            for pid in sorted(LIVE_PIDS & self.support[target]):
                if not affirmative_bitmap(self.support,self.support_pages,target,pid): continue
                if self.stop_io.is_set(): raise Cancelled('Full Auto stopped before basic sample')
                record=self.transaction(f'01{pid:02X}')
                self.failures=self.failures+1 if record['status']!='OK' else 0
                if self.failures>=3:
                    self.set_polling(False,record['error'],requires_reconnect=True)
                    raise ValueError('Three consecutive failures; reconnect explicitly')
            plan=auto_plan(self.support,self.support_pages,self.discovery_observations,target,
                           prepared=True,consent=True,preset=preset)
            if not plan['weights']: raise ValueError('No eligible known standard sensors; inspect bitmap/sample evidence')
            self.auto_receipt.configure(plan,session_id=self.recorder.id,context_id=self.context_id,
                mode=self.mode,bitmap_evidence=self.bitmap_evidence.get(target,{}),rate=self.rate)
            self.auto_stage('CONFIGURED','All eligible current ECU sensors selected; omitted sensors have explicit reasons')
            self.handle('drive_capture',dict(ecu=target,auto_preset=preset,consent=True))
            if not self.capture_mode or self.capture_weights!=plan['weights'] or self.capture_raw_pids!=set(plan['raw_pids']):
                raise ValueError('Worker schedule differs from requested preset; capture aborted')
            self.auto_receipt.acknowledge(self.capture_weights,self.capture_raw_pids,self.discovery_target,utc_now())
            maximum=max(e['nominal_interval_seconds'] for e in self.auto_receipt.data['effective_schedule'].values())
            bound=min(120.,max(30.,maximum*3.))
            self.auto_deadline=time.monotonic()+bound
            self.auto_receipt.data['preflight_timeout_seconds']=bound
            if '7A' in self.auto_receipt.data['confirmed_raw_pids']:
                self.auto_stage('WAITING_RAW','Worker capture acknowledged; waiting for two recorded six-byte 017A RAW responses')
            else:
                self.auto_stage('PARTIAL','Other eligible sensors monitoring; six-byte 017A RAW target not available. Inspect reason before departure.')
        except Exception as exc:
            self.set_polling(False,str(exc),self.requires_reconnect)
            self.auto_stage('ABORTED',str(exc)+'; no automatic reconnect or retry')
            raise
        finally:
            self.auto_starting=False


    def ingest_bitmap(self, record, base, publish=True):
        for item in record['parsed']:
            source = item['ecu'] or 'headerless'
            if base == 0 or (base in self.support.get(source,set()) and base-32 in self.support_pages.get(source,set())):
                self.support.setdefault(source,set()).update(supported_pids(bytes.fromhex(item['data_hex']),base))
                self.support_pages.setdefault(source,set()).add(base)
                prior=self.bitmap_evidence.get(source,{}).get(f'{base:02X}')
                if prior and prior['payload_hex']!=item['data_hex']:
                    self.bitmap_conflicts.add((source,base))
                    self.bitmap_evidence[source][f'{base:02X}']['conflict']=True
                    continue
                self.bitmap_evidence.setdefault(source,{})[f'{base:02X}'] = dict(
                    payload_hex=item['data_hex'], timestamp=record['timestamp'],
                    transaction_id=record['id'], context_id=self.context_id,
                    provenance='POSITIVE_RAW_BITMAP', recorded=bool(self.recorder))
        if self.transport:
            self.transport.supported = set().union(*self.support.values()) if self.support else set()
            self.transport.discovery_supported = set(self.support.get(self.discovery_target,set()))
        if publish:
            self.emit('support', {e:set(s) for e,s in self.support.items()})
            self.emit('support_pages', {e:set(s) for e,s in self.support_pages.items()})

    def discover(self, target):
        if not self.transport or self.requires_reconnect or self.replay:
            raise ValueError('Connect explicitly before standard discovery; reconnect after failures')
        if target not in self.support or target == 'headerless' or not self.can_protocol:
            raise ValueError('Choose an identified ECU on ISO 15765-4 CAN; headerless/legacy live discovery is disabled')
        self.set_polling(False, 'Standard discovery; basic polling paused')
        self.capture_mode = False
        self.capture_weights = {}
        self.capture_raw_pids = set()
        self.emit_capture('Discovery; no drive monitoring')
        self.discovery_target = target
        self.range_configuration.pop(target,None)
        self.discovery_prepared = False
        self.discovery_completed = False
        self.discovery_active = False
        self.transport.discovery_enabled = True
        self.transport.discovery_supported = set(self.support[target])
        self.emit_discovery(True, f'Discovering ECU {target}; functional Mode 01 requests only')
        completed = False
        try:
            for command in ('ATCAF1','ATCFC1','ATAL'):
                if 'OK' not in self.transaction(command)['raw_text'].upper():
                    raise TransportError(f'Documented CAN setup rejected: {command}')
            for base in range(32,256,32):
                if self.auto_starting and any(e==target for e,base in self.bitmap_conflicts):
                    raise ValueError('Conflicting raw bitmap evidence; Discovery stopped without sensor probing')
                if base not in self.support[target] or base-32 not in self.support_pages[target]: break
                if base in self.support_pages[target]: continue
                record = self.transaction(f'01{base:02X}')
                self.ingest_bitmap(record,base)
                if base not in self.support_pages[target]: break
            self.failures = 0
            for pid in sorted(DISCOVERY_PIDS & self.support[target],key=lambda p:(p not in {0x4F,0x50},p)):
                if self.auto_starting and (not affirmative_bitmap(self.support,self.support_pages,target,pid) or
                                          any(e==target for e,base in self.bitmap_conflicts)):
                    continue
                if self.stop_io.is_set(): raise Cancelled('Discovery stopped before send')
                record = self.transaction(f'01{pid:02X}')
                if record['status']=='TRANSPORT_ERROR' or pid in EXTENSION_PIDS and any(r['nrc']=='22' for r in record['negative_responses']):
                    self.set_polling(False,record['error'],requires_reconnect=True);break
                # Bad candidate layouts/NO DATA are retained and omitted, not
                # repeated probes or false throughput failures.
                if pid in EXTENSION_PIDS and record['status']!='OK':continue
                self.failures = self.failures+1 if record['status']!='OK' else 0
                if self.failures >= 3:
                    self.set_polling(False, record['error'], requires_reconnect=True); break
            completed = not self.requires_reconnect
        finally:
            self.transport.discovery_enabled = False
            self.discovery_prepared = completed and not self.stop_io.is_set() and not self.requires_reconnect
            self.discovery_completed = self.discovery_prepared
            self.emit_discovery(False, 'Discovery ended; samples only. Resume basic polling or explicitly start monitoring.')

    def set_polling(self, active, reason, requires_reconnect=False):
        if self.polling and not active:self.idle_health_checked=time.monotonic()
        self.polling = active
        self.requires_reconnect = requires_reconnect
        self.emit("acquisition", {"polling": active, "reason": reason, "requires_reconnect": requires_reconnect})

    def connection_stage(self,stage,reason):
        self.connection_state=dict(stage=stage,reason=reason,port=self.port,mode=self.mode,pairing='OS_MANAGED_UNKNOWN',timestamp=utc_now())
        if isinstance(self.benchmark,AutoBenchmark):self.benchmark.connection_stages.append(dict(self.connection_state))
        self.emit('connection_status',dict(self.connection_state))

    def check_idle_connection(self):
        """OS status only, no query, keepalive, reset or hidden reconnect."""
        if not self.transport:return
        if self.polling or self.benchmark or self.auto_starting:
            self.idle_health_checked=time.monotonic();return
        now=time.monotonic();gap=now-self.idle_health_checked
        if gap<1:return
        self.idle_health_checked=now
        status=self.transport.idle_status()
        if gap>15 or not all(status.get(k) for k in ('open','prompt_synchronized')):
            reason='Idle connection invalid or possible suspension; explicit reconnect required. '+status.get('reason','')
            self.disconnect();self.set_polling(False,reason,requires_reconnect=True);self.connection_stage('RECONNECT_REQUIRED',reason);self.emit('notice',reason)

    def close_recording(self):
        if self.recorder:
            with self.marker_lock: tokens=list(self.pending_markers)
            for token in tokens: self.persist_marker({'marker_id':token})
            self.save_capture_evidence()
            final_auto=bool(self.auto_receipt and not self.auto_starting)
            if final_auto:
                self.auto_receipt.data['capture_outcome']=dict(state=self.auto_receipt.data['state'],reason=self.auto_receipt.data['reason'])
                self.auto_receipt.data['dpf_proof_met_before_close']=self.auto_receipt.data['dpf']['recorded_positive_six_byte_frames']>=2
                self.auto_receipt.data.update(recording_active=False,adapter_open=bool(self.transport))
                self.auto_receipt.readiness(False)
                self.auto_receipt.transition('FINISHED','Recording finalized; inspect stored counts and export locally',utc_now())
            ended=self.recorder.close(evidence=self.capture_evidence() if final_auto else None)
            self.recorder = None
            if final_auto:
                self.auto_receipt.data['closed_at']=ended
                self.emit('auto_capture',self.auto_receipt.snapshot())
        self.emit("recording", None)

    def disconnect(self, finish_recording=True):
        if self.auto_receipt and not self.auto_starting and self.auto_receipt.data['state'] not in {'FINISHED','ABORTED'}:
            self.auto_stage('STOPPED', 'Adapter disconnected; no automatic reconnect')
        self.capture_mode = False
        self.emit_capture('Disconnected; cached values are historical')
        self.discovery_active = False
        self.discovery_prepared = False
        if self.transport: self.transport.discovery_enabled = False
        self.set_polling(False, "Disconnected")
        if self.transport: self.transport.close()
        self.transport = None
        if finish_recording: self.close_recording()
        self.connection_stage('DISCONNECTED','Handle closed; no automatic reconnect')
        if self.session.data['state']=='CONNECTED' and not self.session.active:
            self.session.transition('DISCONNECTED','Adapter explicitly closed',adapter_open=False);self.publish_session(True)
        self.emit("connection", {"adapter": "Disconnected", "ecu": "Unavailable", "protocol": self.protocol, "mode": self.mode})

    def initialize(self, options):
        # An empty pre-connect recorder is allowed; captured sources never share a session.
        if self.recorder and self.recorder.count:
            self.close_recording()
            self.emit("notice", "Previous session closed before reconnect/source change. Start Recording for the new session.")
        self.disconnect(finish_recording=False)
        if self.replay: self.replay.close(); self.replay = None
        self.replay_playing = False
        self.support = {}
        self.support_pages = {}
        self.bitmap_evidence = {}
        self.bitmap_conflicts = set()
        self.discovery_observations = {}
        self.range_configuration={}
        self.pacing=AdaptivePacing(self.rate)
        self.positive_wire_evidence={}
        self.discovery_completed = False
        self.capture_weights = {}
        self.capture_raw_pids = set()
        self.discovery_target = None
        self.discovery_prepared = False
        self.can_protocol = False
        self.mode = "SIMULATED" if options["simulation"] else "LIVE · hardware unverified"
        self.context_id = uuid.uuid4().hex
        self.failures = 0
        self.scheduler = PollScheduler()
        self.emit("context", {"id": self.context_id, "mode": self.mode})
        if self.recorder:
            self.recorder.db.execute("UPDATE sessions SET mode=? WHERE id=?", (self.mode, self.recorder.id))
            self.recorder.db.commit()
        self.port = "SIMULATED" if options["simulation"] else options["port"]
        self.adapter, self.protocol = "Unknown", "Unknown"
        self.connection_stage('OPENING_COM' if not options['simulation'] else 'OPENING_SIMULATION','Opening explicitly selected source; OS pairing not inspected')
        self.transport = Simulator(options.get("scenario", "Normal idle")) if options["simulation"] else SerialTransport(self.port, options.get("baud", 115200))
        self.connection_stage('HANDLE_OPEN','Port handle open; adapter and ECU not yet verified')
        self.transport.rate = self.rate
        # One application budget, including a new connection/initialization.
        self.transport._last_send_ns=self.last_application_send_ns
        self.transport.last_send=self.last_application_send_ns/1e9
        self.emit("notice", f"Opening {self.port} at {options.get('baud', 115200)} baud, 8N1; bounded prompt timeout 6 s. {self.mode}")
        self.emit("connection", {"adapter": "Initializing", "ecu": "Not yet verified", "protocol": "Unknown", "mode": self.mode})
        identity = self.transaction("ATI")
        if not any(x in identity["raw_text"].upper() for x in ("ELM", "STN", "OBDLINK")):
            raise TransportError("Adapter identity not recognized; no ECU requests sent")
        self.adapter = identity["raw_text"].replace('>', '').strip()
        stn = self.transaction("STI")
        if "STN" in stn["raw_text"]: self.adapter += " / " + stn["raw_text"].replace('>', '').strip()
        for cmd in ("ATE0", "ATL0", "ATS1", "ATH1", "ATM0", "ATTP0", "ATST64"):
            response = self.transaction(cmd)
            if "OK" not in response["raw_text"].upper():
                raise TransportError(f"Required adapter configuration rejected: {cmd}")
        self.connection_stage('ADAPTER_INITIALIZED','Adapter identity and existing configuration acknowledged')
        self.emit("connection", {"adapter": self.adapter, "ecu": "Discovering support", "protocol": "Auto", "mode": self.mode})
        for base in (0, 32, 64):
            if self.auto_starting and self.bitmap_conflicts: break
            if base and not any(base in s for s in self.support.values()): break
            record = self.transaction(f"01{base:02X}")
            self.ingest_bitmap(record, base, publish=False)
        self.transport.supported = set().union(*self.support.values()) if self.support else set()
        self.protocol = self.transaction("ATDP")["raw_text"].replace('>', '').strip()
        number = self.transaction("ATDPN")['raw_text'].replace('>','').strip().upper()
        self.can_protocol = number in {'6','7','8','9','A6','A7','A8','A9'}
        self.emit("support", self.support)
        self.emit("support_pages", self.support_pages)
        self.emit("connection", {"adapter": self.adapter, "ecu": "Connected" if self.support else "No verified ECU response", "protocol": self.protocol, "mode": self.mode})
        self.connection_stage('ECU_VERIFIED' if self.support else 'ECU_UNCONFIRMED','Response address is not authenticated vehicle identity')
        self.idle_health_checked=time.monotonic()
        self.set_polling(bool(self.support), "Polling" if self.support else "No verified ECU response")
        self.emit_discovery()

    def decode_replay(self, record):
        # Reclassify legacy v0.1.0 INVALID negative replies without rewriting the journal.
        record = dict(record, replay=True, context_id=self.context_id)
        if record.get('record_type')=='marker':
            self.emit('marker',record); return
        readings = []
        if record.get("pid"):
            pid = int(record["pid"], 16)
            if pid in DISCOVERY_PIDS and record.get('support_evidence'):
                self.support = {e:set(p) for e,p in record['support_evidence'].items()}
                self.support_pages = {e:set(p) for e,p in record.get('support_pages',{}).items()}
                self.emit('support',dict(self.support)); self.emit('support_pages',dict(self.support_pages))
            result = parse_reply(base64.b64decode(record['raw_b64']), pid, record['command'])
            replies = result.responses
            record['protocol_errors'] = result.errors
            rejections = [r.rejection() for r in replies if r.negative_code is not None]
            if rejections:
                record["original_status"] = record["status"]
                record["status"] = "ECU_NEGATIVE_RESPONSE"
                record["negative_responses"] = rejections
                record["error"] = '; '.join(f'{r["ecu"] or "headerless"}: {r["reason"]} (7F 01 {r["nrc"]})' for r in rejections)
            positive_replies = [r for r in replies if r.negative_code is None]
            if pid in BITMAP_PIDS:
                try:
                    for reply in positive_replies:
                        if len(reply.data) != 4: continue
                        source = reply.header or "headerless"
                        if pid == 0 or (pid in self.support.get(source, set()) and pid-32 in self.support_pages.get(source,set())):
                            self.support.setdefault(source, set()).update(supported_pids(reply.data, pid))
                            self.support_pages.setdefault(source, set()).add(pid)
                    self.emit("support", dict(self.support))
                    self.emit("support_pages", dict(self.support_pages))
                except ValueError as exc: self.emit("notice", str(exc))
            if pid in STANDARD_DIESEL:
                record['discovery_samples'] = []
                for reply in positive_replies:
                    sample = self.diesel_sample(reply,pid,record['timestamp'],record['monotonic_ns'],record.get('mode','Unknown'),
                                                raw_only=bool(record.get('raw_only')))
                    sample['raw_b64']=record['raw_b64']
                    if sample.get('raw_only'):
                        retained=next((s for s in record.get('raw_samples',[]) if s.get('ecu')==reply.header),{})
                        sample['context_readings']=retained.get('context_readings',{})
                    if sample.get('error'):
                        record['protocol_errors'].append(dict(ecu=reply.header,reason=sample['error'],state='INVALID',category='DECODER_LAYOUT'))
                    self.discovery_observations[reply.header or 'headerless',pid] = sample
                    if pid in {0x4F,0x50} and not sample.get('error'):self.range_configuration.setdefault(reply.header or 'headerless',{})[pid]=reply.data
                    record['discovery_samples'].append(sample)
                    for reading in self.diesel_readings(sample,pid,record['timestamp'],record['monotonic_ns']):
                        reading['mode'] = 'REPLAY · '+record.get('mode','unknown'); readings.append(reading)
                self.emit_discovery()
            if pid in self.registry:
                sensor = self.registry[pid]
                try:
                    for reply in positive_replies:
                        readings.append({"sensor_id": sensor.id, "pid": pid, "ecu": reply.header,
                            "value": basic_range(sensor,reply.data,self.range_configuration.get(reply.header or 'headerless',{})), "unit": sensor.unit,
                            "verification": sensor.metadata["verification"], "timestamp": record["timestamp"],
                            "monotonic_ns": record["monotonic_ns"], "mode": "REPLAY · " + record.get("mode", "unknown"),
                            "source_kind": "SIMULATED" if record.get("mode") == "SIMULATED" else "ECU_READING" if record.get("mode", "").startswith("LIVE") else "UNKNOWN"})
                except ValueError as exc: self.emit("notice", str(exc))
        self.retain_discovery_errors(record)
        self.emit("transaction", (record, readings))

    def publish_session(self, force=False):
        now=time.monotonic()
        if not force and now-self.session_last_publish<1: return
        self.session_last_publish=now
        data=self.session.snapshot()
        data.update(context_id=self.context_id,mode=self.mode,port=self.port,rate_limit=self.rate,
            recording_active=bool(self.recorder),adapter_open=bool(self.transport),
            polling_active=self.polling,requires_reconnect=self.requires_reconnect,
            receipt=self.auto_receipt.snapshot() if self.auto_receipt and self.auto_receipt.data.get('session_id')==data.get('session_id') else data.get('exported_acquisition_receipt'))
        if self.recorder:
            data.update(session_id=self.recorder.id,journal_path=str(self.recorder.path.resolve()),
                recorded_transactions=self.recorder.count,transaction_errors=self.recorder.errors)
        self.emit('session_state',data)

    def session_stage(self,state,reason,**values):
        if self.recorder: values['session_id']=self.recorder.id
        self.session.transition(state,reason,**values)
        if self.recorder:
            self.recorder.marker('Note','Session '+state+': '+reason,self.mode)
            self.save_capture_evidence()
        self.publish_session(True)

    def connect_session(self,options):
        if self.session.active or self.recorder or self.replay:
            self.emit('session_rejected','Finish recording / leave replay before standard Connect'); return
        if self.session.data['state']=='CONNECTED' and self.transport and not self.requires_reconnect:
            if bool(options.get('simulation'))!=(self.mode=='SIMULATED') or not options.get('simulation') and options.get('port')!=self.port:
                self.emit('session_rejected','Source/port differs from retained connection; Disconnect explicitly first');return
            self.publish_session(True); return
        self.session_stage('CONNECTING','Opening the explicitly configured source; awaiting positive ECU identity',active=False)
        try:
            if not options.get('simulation'):
                from serial.tools import list_ports
                devices={p.device.upper():p for p in list_ports.comports()}
                chosen=options.get('port','').strip().upper()
                if chosen not in devices: raise ValueError('Configured outgoing port is not currently enumerated by Windows; review Connection settings. No Bluetooth pairing/reset was attempted.')
                if 'INCOMING' in (devices[chosen].description or '').upper(): raise ValueError('Select the Windows outgoing serial port')
            self.auto_receipt=None
            self.initialize(options)
            self.set_polling(False,'Connected; Start Session begins recording and acquisition')
            candidates=[e for e in self.support if e!='headerless']
            target=options.get('ecu') or (candidates[0] if len(candidates)==1 else None)
            if not self.can_protocol or target not in candidates:
                raise ValueError('A unique positively responding CAN ECU is required; multiple ECUs require explicit selection in Advanced / Developer')
            self.session_stage('CONNECTED','ECU positively confirmed; connection alone is not a recording',
                active=False,ecu=target,mode=self.mode,port=self.port,session_id=None,
                recorded_transactions=0,transaction_errors=0,duration_seconds=0,journal_path=None,journal_closed=False,
                source_kind='SIMULATED' if self.mode=='SIMULATED' else 'ECU_READING')
        except Exception as exc:
            self.disconnect()
            self.session_stage('FAILED',str(exc),active=False,session_id=None)

    def start_session(self,options):
        if self.session.active:
            self.publish_session(True); return
        if self.session.data['state']!='CONNECTED' or not self.transport or self.requires_reconnect or self.recorder or self.replay:
            self.emit('session_rejected','Connect and confirm the ECU first; no automatic reconnect or overlapping recording'); return
        if bool(options.get('simulation'))!=(self.mode=='SIMULATED'):
            self.emit('session_rejected','Selected source differs from the confirmed connection'); return
        self.session.begin(); self.publish_session(True)
        self.session_internal=True
        try:
            profile=options.get('profile',PRESETS[1])
            if profile not in {PRESETS[1],PRESETS[2]}:raise ValueError('Unknown normal session profile')
            self.session.data.update(profile=profile,sampling_scope='EXPLICIT_CRITICAL_SUBSET' if profile==PRESETS[2] else 'ALL_ELIGIBLE')
            self.full_auto(dict(options,reuse=True,consent=True,preset=profile,
                ecu=self.session.data['ecu'],session_recording=True))
            self.auto_receipt.data['consent_provenance']='EXPLICIT_START_SESSION_FIXED_READ_ONLY_PROFILE'
            self.auto_receipt.data['pre_connect_initialization_recorded']=False
            self.save_capture_evidence(); self.publish_session(True)
        except Exception as exc:
            self.session_stage('PARTIAL' if isinstance(exc,Cancelled) else 'FAILED',str(exc)+'; Finish Session preserves and exports available evidence')
            if not isinstance(exc,Cancelled): self.set_polling(False,str(exc),requires_reconnect=True)
        finally: self.session_internal=False

    def persist_closed_coordinator(self):
        import json
        from mokka_ecu_lab.logging import connect_database
        session_id=self.session.data.get('session_id')
        if not session_id: return
        db=connect_database(self.root)
        try:
            row=db.execute('SELECT metadata FROM sessions WHERE id=?',(session_id,)).fetchone()
            if row:
                data=json.loads(row[0] or '{}'); data.setdefault('capture_evidence',{})['session_coordinator']=self.session.snapshot()
                db.execute('UPDATE sessions SET metadata=? WHERE id=?',(json.dumps(data),session_id)); db.commit()
        finally: db.close()

    def finish_standard_session(self):
        if not self.session.active: self.publish_session(True); return
        session_id=self.recorder.id if self.recorder else self.session.data.get('session_id')
        self.session_stage('FINALIZING','Stopping acquisition, closing original journal, then verifying the automatic private bundle')
        if self.recorder:
            self.session.data.update(recorded_transactions=self.recorder.count,transaction_errors=self.recorder.errors,
                journal_path=str(self.recorder.path.resolve()))
        self.session.data['duration_seconds']=(datetime.now(timezone.utc)-datetime.fromisoformat(self.session.data['started_at'])).total_seconds()
        self.set_polling(False,'Session finalization',self.requires_reconnect)
        self.capture_mode=False; self.discovery_active=False
        if self.transport: self.transport.discovery_enabled=False
        self.emit_capture('Finalizing standard session')
        try:
            self.close_recording()
            if not session_id: raise ValueError('No session journal was created')
            self.session.data.update(session_id=session_id,journal_closed=True)
            result=export_closed_session(self.root,session_id)
            self.disconnect(finish_recording=False)
            self.session_stage('EXPORTED','Private bundle verified; journal closed and adapter disconnected',active=False,export_error=None,**result)
        except Exception as exc:
            self.disconnect(finish_recording=False)
            self.session_stage('FAILED','Export/finalization failed; original journal preserved. Use explicit offline export retry.',
                active=bool(self.recorder),session_id=session_id,export_error=str(exc),retry_export=not bool(self.recorder),**getattr(exc,'result',{}))
        self.persist_closed_coordinator()

    def retry_session_export(self,options):
        if self.session.active or self.recorder or self.transport:
            self.emit('session_rejected','Offline recovery/export requires no active recording or connection'); return
        session_id=options.get('session_id') or self.session.data.get('session_id')
        self.session_stage('FINALIZING','Explicit offline recovery/export; no ECU requests',active=False,session_id=session_id)
        self.auto_receipt=None
        try:
            recover_interrupted_session(self.root,session_id)
            result=export_closed_session(self.root,session_id)
            self.session_stage('EXPORTED','Offline bundle verified; original journal preserved',active=False,export_error=None,retry_export=False,**result)
        except Exception as exc:
            self.session_stage('FAILED','Offline export failed; original journal preserved',active=False,export_error=str(exc),retry_export=True)
        self.persist_closed_coordinator()

    def handle(self, action, options):
        if self.benchmark and self.benchmark.active and action not in {'benchmark_stop','bench_auto_stop','shutdown','disconnect','system_suspend'}:
            self.emit('notice','Stationary benchmark owns acquisition; stop it first');return
        if self.session.active and action in CONFLICTS and not self.session_internal:
            self.emit('session_rejected','Automatic session owns acquisition; Finish Session first'); return
        if action=='bench_auto_start':
            try:self.begin_auto_benchmark(options)
            except ValueError as exc:self.emit('benchmark_rejected',str(exc));self.emit('notice',str(exc))
        elif action=='bench_auto_stop':
            if isinstance(self.benchmark,AutoBenchmark):self.end_auto_benchmark('INTENTIONAL_STOP: Stop & save')
        elif action=='bench_export_retry':self.retry_benchmark_export(options.get('session_id'))
        elif action=='benchmark_start':
            try:self.start_benchmark(options)
            except ValueError as exc:
                self.emit('notice','Benchmark rejected: '+str(exc));self.emit('benchmark',dict(active=False,reason='Rejected: '+str(exc)))
        elif action=='benchmark_stop':self.finish_benchmark('Explicit Stop; no automatic resume/reconnect')
        elif action=='session_connect': self.connect_session(options)
        elif action=='session_start': self.start_session(options)
        elif action=='session_finish': self.finish_standard_session()
        elif action=='session_export_retry': self.retry_session_export(options)
        elif action == 'full_auto': self.full_auto(options)
        elif action == 'retry_auto':
            if not self.auto_receipt or not self.transport or self.requires_reconnect or self.replay or not self.recorder or not self.discovery_prepared:
                self.reject_auto('Retry requires an open healthy transport, active recording and completed Discovery; reconnect is explicit'); return
            self.full_auto(dict(options, reuse=True, preset=self.auto_receipt.data['preset'], consent=self.auto_receipt.data['raw_consent'],
                inherited_consent_timestamp=self.auto_receipt.data['consent_timestamp']))
        elif action == "connect":
            if self.auto_receipt: self.auto_stage('STOPPED','Explicit new connection; previous automatic run ended')
            self.auto_receipt = None
            self.initialize(options)
        elif action == 'marker':
            self.persist_marker(options)
        elif action == 'discover': self.discover(options.get('ecu'))
        elif action == 'drive_capture':
            if self.auto_receipt and not self.auto_starting:
                self.auto_stage('STOPPED','Manual capture configuration; automatic receipt no longer counts samples')
            target = options.get('ecu')
            prepared = bool(self.transport and not self.requires_reconnect and self.can_protocol
                            and self.discovery_prepared and target == self.discovery_target and not self.replay)
            if options.get('auto_preset'):
                plan = auto_plan(self.support,self.support_pages,self.discovery_observations,target,
                    prepared=prepared,consent=options.get('consent') is True,preset=options['auto_preset'])
            else:
                plan = capture_plan(self.support,self.support_pages,self.discovery_observations,target,
                                    prepared=prepared,selected=options.get('pids'),raw_selected=options.get('raw_pids',()))
            if not plan['weights']:
                if prepared:
                    self.capture_mode = self.discovery_active = False
                    self.capture_weights = {}
                    self.capture_raw_pids = set()
                    self.transport.discovery_enabled = False
                    self.set_polling(False,'No eligible Drive Capture selections; monitoring stopped')
                    self.emit_capture('No eligible selections; monitoring stopped')
                self.emit('notice','Drive Capture has no eligible selections; complete discovery and inspect omissions'); return
            self.capture_weights = plan['weights']; self.capture_mode = True
            self.capture_raw_pids = set(plan['raw_pids'])
            if plan['omitted']: self.emit('notice','Omitted selections: '+ '; '.join(f"01{e['pid']}: {e['reason']}" for e in plan['omitted']))
            self.discovery_active = bool(set(self.capture_weights)&DISCOVERY_PIDS)
            self.transport.discovery_enabled = self.discovery_active
            self.transport.discovery_supported = set(self.support.get(target,set()))
            self.failures = 0; self.scheduler = PollScheduler()
            self.set_polling(True,'Drive Capture; selected supported PIDs only')
            self.emit_capture('Drive Capture active; observed intervals are not guaranteed')
            self.emit_discovery(self.discovery_active,'Drive Capture monitoring; no repeated discovery')
        elif action == 'monitor_discovery':
            target = options.get('ecu')
            if not self.transport or self.requires_reconnect or not self.discovery_prepared or target != self.discovery_target or not self.can_protocol:
                self.emit('notice','Run standard discovery for this ECU first; reconnect after errors'); return
            self.discovery_active = True
            self.capture_mode = False
            self.emit_capture('Standard monitoring')
            self.transport.discovery_enabled = True
            self.transport.discovery_supported = set(self.support.get(target,set()))
            self.failures = 0
            self.set_polling(True,'Standard discovery monitoring')
            self.emit_discovery(True,'Monitoring supported standard PIDs; vehicle unverified')
        elif action in {'disconnect','system_suspend'}:
            if self.benchmark:self.finish_benchmark('Explicit Disconnect' if action=='disconnect' else 'Windows suspension; explicit reconnect required')
            if self.session.active:self.finish_standard_session()
            self.disconnect()
        elif action == "stop":
            if self.auto_receipt: self.auto_stage('STOPPED','Stopped by user; no automatic retry')
            self.capture_mode = False
            self.emit_capture('Stopped; cached values are historical')
            self.discovery_active = False
            if self.transport: self.transport.discovery_enabled = False
            self.emit_discovery(False, 'Stopped; all previous samples are recorded evidence')
            self.set_polling(False, "Polling stopped by user", self.requires_reconnect)
            self.replay_playing = False
        elif action == "start" and self.transport:
            if self.auto_receipt: self.auto_stage('STOPPED','Manual basic polling; automatic schedule no longer active')
            if self.requires_reconnect:
                self.emit("notice", "Polling remains stopped after ECU failures. Check ignition and explicitly reconnect.")
            else:
                self.capture_mode = False
                self.discovery_active = False
                self.transport.discovery_enabled = False
                self.emit_capture('Basic monitoring resumed')
                self.failures = 0
                self.set_polling(bool(self.support), "Polling resumed")
        elif action == "select": self.selected = options["pids"]
        elif action == "priorities": self.priorities = options["weights"] if options.get("enabled") else {}
        elif action == "rate":
            self.rate = max(0.25, min(4., options["rate"]))
            self.pacing=AdaptivePacing(self.rate)
            if self.transport: self.transport.rate = self.rate
            if self.auto_receipt and self.capture_mode:
                self.auto_receipt.data['rate_limit']=self.rate
                total=sum(self.capture_weights.values())
                for entry in self.auto_receipt.data['effective_schedule'].values():
                    entry['nominal_interval_seconds']=total/(entry['weight']*self.rate)
                self.update_auto_receipt(force=True)
        elif action == "record":
            if self.replay:
                self.emit("notice", "Replay is recorded evidence, not a new ECU session. Recording replay is disabled.")
                return
            if not self.recorder:
                if self.auto_receipt and not self.auto_starting:
                    self.auto_receipt=None
                    self.emit('auto_reset',dict(context_id=self.context_id))
                self.recorder = Recorder(self.root, self.mode if self.transport else "Pending connection", {"vehicle": "Opel Mokka B 2022 1.5 diesel", "adapter": "REDACTED", "VIN": "not queried"})
                self.save_capture_evidence()
                self.emit("recording", self.recorder.id)
        elif action == "record_stop":
            self.close_recording()
        elif action == "replay":
            self.range_configuration={}
            self.disconnect()
            if self.replay: self.replay.close()
            self.replay = Replay(Path(options["path"]))
            self.mode = "REPLAY"
            self.context_id = uuid.uuid4().hex
            self.emit("context", {"id": self.context_id, "mode": self.mode})
            self.support = {}
            self.support_pages = {}
            self.discovery_observations = {}
            self.discovery_target = None
            self.discovery_prepared = False
            self.can_protocol = False
            self.pending_record, self.replay_previous = None, None
            self.replay_playing = False
            self.emit("connection", {"adapter": "Offline", "ecu": "Replay paused", "protocol": "Recorded", "mode": "REPLAY"})
        elif action == "replay_play":
            self.replay_speed = options["speed"]; self.replay_playing = True
        elif action == "step" and self.replay:
            self.replay_playing = False
            record = self.pending_record or self.replay.next()
            self.pending_record = None
            if record: self.decode_replay(record); self.replay_previous = record["monotonic_ns"]
            else: self.emit("notice", "Replay complete. " + '; '.join(self.replay.warnings))
        elif action == "shutdown":
            if self.benchmark:self.finish_benchmark('Application shutdown; no automatic restart')
            if self.session.active: self.finish_standard_session()
            self.quit_event.set()

    def persist_marker(self, options):
        if 'marker_id' in options:
            with self.marker_lock: pending=self.pending_markers.pop(options['marker_id'],None)
            if pending is None: return  # Already flushed during canceled receive / finalization.
            options=pending
            if not self.recorder or options['session_id']!=self.recorder.id:
                self.emit('notice','Marker has no active matching recording; not attached to another session'); return
        if not self.recorder or self.replay:
            self.emit('notice','Start Recording before adding a journey marker'); return
        record=self.recorder.marker(options.get('event'),options.get('note',''),self.mode,
                                    options.get('timestamp'),options.get('monotonic_ns'),
                                    options.get('phase'),options.get('uncertainty_seconds',0),self.discovery_target)
        self.emit('marker',dict(record,context_id=self.context_id,replay=False))

    def run(self):
        try:
            while not self.quit_event.is_set():
                try:
                    action, options = self.commands.get(timeout=0.02 if self.polling or self.replay_playing else 0.1)
                    self.handle(action, options)
                except queue.Empty: pass
                except Cancelled:
                    self.set_polling(False, "Connection canceled")
                    if self.session.active and self.session.finish_requested: self.finish_standard_session()
                    elif self.transport and self.transport.last_wire_ns is not None:
                        self.disconnect(); self.emit("notice", "Receive canceled after send; reconnect to restore prompt synchronization")
                except Exception as exc:
                    self.emit("notice", str(exc))
                    if self.session.active:
                        self.close_recording(); self.session_stage('PARTIAL',str(exc)+'; explicit reconnect required after Finish Session')
                    self.disconnect()
                if self.benchmark and self.benchmark.active:
                    try:self.benchmark_tick()
                    except Exception as exc:self.finish_benchmark('Aborted: '+str(exc))
                    continue
                self.check_idle_connection()
                if self.polling and self.transport and not self.stop_io.is_set():
                    pids = list(self.capture_weights) if self.capture_mode else [p for p in self.selected if p in LIVE_PIDS and p in self.transport.supported]
                    if self.discovery_active and not self.capture_mode:
                        pids += sorted(DISCOVERY_PIDS & self.support.get(self.discovery_target,set()))
                    pid = self.scheduler.next(pids, self.capture_weights if self.capture_mode else self.priorities, allow_discovery=self.discovery_active)
                    if pid is None:
                        self.set_polling(False, "No selected supported sensors")
                        continue
                    try:
                        record = self.transaction(f"01{pid:02X}")
                        if record['status']=='TRANSPORT_ERROR':
                            self.set_polling(False,record['error'],requires_reconnect=True);self.capture_mode=False;self.discovery_active=False
                            self.transport.discovery_enabled=False;self.emit_capture('Transport failure; explicit reconnect required')
                            if self.auto_receipt:self.auto_stage('ABORTED',record['error'])
                            continue
                        if pid in EXTENSION_PIDS and record['status']!='OK' and not any(r['nrc']=='22' for r in record['negative_responses']):
                            if pid in {0x4F,0x50}:self.range_configuration.get(self.discovery_target,{}).pop(pid,None)
                            self.capture_weights.pop(pid,None)
                            if self.auto_receipt:
                                self.auto_receipt.data['effective_schedule'].pop(f'{pid:02X}',None)
                                self.auto_receipt.data.setdefault('runtime_omissions',[]).append(dict(pid=f'{pid:02X}',reason=record['error'],timestamp=record['timestamp']))
                            self.emit_capture('Candidate disabled after invalid current reply');continue
                        self.failures = self.failures + 1 if record["status"] != "OK" else 0
                        if self.failures >= 3:
                            reason = ("Conditions Not Correct (7F 01 22); ignition state is not confirmed"
                                      if any(r["nrc"] == "22" for r in record["negative_responses"])
                                      else record["error"] or "Invalid ECU reply")
                            self.set_polling(False, reason, requires_reconnect=True)
                            self.discovery_active = False
                            self.capture_mode = False
                            self.emit_capture(reason)
                            self.transport.discovery_enabled = False
                            self.emit_discovery(False, reason)
                            self.emit("notice", f"Polling stopped after three consecutive ECU failures: {reason}. Values are stale. Stop Recording, check ignition and reconnect explicitly.")
                            if self.auto_receipt: self.auto_stage('ABORTED',reason+'; reconnect explicitly')
                    except Cancelled:
                        self.set_polling(False, "Polling canceled", self.requires_reconnect)
                        if self.session.active and self.session.finish_requested: self.finish_standard_session()
                        elif self.transport and self.transport.last_wire_ns is not None:
                            self.disconnect(); self.emit("notice", "Receive canceled after send; reconnect to restore prompt synchronization")
                    except Exception as exc:
                        self.emit("notice", str(exc))
                        if self.session.active:
                            self.close_recording(); self.session_stage('PARTIAL',str(exc)+'; Finish Session exports saved evidence')
                        self.disconnect()
                if self.replay_playing and self.replay:
                    try:
                        if self.pending_record is None:
                            self.pending_record = self.replay.next()
                            if self.pending_record is None:
                                self.replay_playing = False
                                self.emit("notice", "Replay complete. " + '; '.join(self.replay.warnings)); continue
                            gap = 0 if self.replay_previous is None else max(0, (self.pending_record["monotonic_ns"] - self.replay_previous) / 1e9)
                            self.replay_due = time.monotonic() + gap / self.replay_speed
                        if time.monotonic() >= self.replay_due:
                            self.decode_replay(self.pending_record)
                            self.replay_previous = self.pending_record["monotonic_ns"]
                            self.pending_record = None
                    except Exception as exc:
                        self.replay_playing = False; self.emit("notice", str(exc))
        finally:
            if self.session.active: self.finish_standard_session()
            self.disconnect()
            if self.replay: self.replay.close()
