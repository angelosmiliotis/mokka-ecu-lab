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
from mokka_ecu_lab.protocols import parse_obd, supported_pids, LIVE_PIDS, BITMAP_PIDS, DISCOVERY_PIDS
from mokka_ecu_lab.protocols.isotp import parse_reply
from mokka_ecu_lab.sensors.diesel import STANDARD_DIESEL
from mokka_ecu_lab.discovery import discovery_report
from mokka_ecu_lab.sensors import load_registry
from mokka_ecu_lab.logging import Recorder, utc_now
from mokka_ecu_lab.replay import Replay
from .scheduling import PollScheduler
from mokka_ecu_lab.capture import capture_plan, DECODER_VERSION
from mokka_ecu_lab.layouts import RAW_ONLY_PIDS, layout_evidence
from mokka_ecu_lab.auto_capture import auto_plan, AcquisitionReceipt, PRESETS, affirmative_bitmap
from mokka_ecu_lab import __version__

class AcquisitionWorker(threading.Thread):
    def __init__(self, root: Path):
        super().__init__(name="serialized-obd-worker", daemon=False)
        self.root = root
        self.commands = queue.Queue(maxsize=64)
        self.events = queue.Queue(maxsize=512)
        self.stop_io = threading.Event()
        self.quit_event = threading.Event()
        self.transport = self.recorder = self.replay = None
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
        self.can_protocol = False
        self.polling = False
        self.priorities = {}
        self.scheduler = PollScheduler()
        self.failures = 0
        self.requires_reconnect = False
        self.context_id = uuid.uuid4().hex
        self.rate = 4.0
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
        if action=='marker':
            token=uuid.uuid4().hex
            recorder=self.recorder
            with self.marker_lock:
                self.pending_markers[token]=dict(kwargs,session_id=recorder.id if recorder else None,
                                                timestamp=utc_now(),monotonic_ns=time.monotonic_ns())
            kwargs={'marker_id':token}
        if action in {"connect", "start", "discover", "monitor_discovery", "drive_capture", "full_auto", "retry_auto"}:
            # Clear only at user submission, so a later Stop cancels queued Connect too.
            self.stop_io.clear()
        if action in {"disconnect", "stop", "shutdown", "replay"}:
            self.stop_io.set()
        try: self.commands.put_nowait((action, kwargs))
        except queue.Full:
            if action=='marker':
                with self.marker_lock: self.pending_markers.pop(kwargs['marker_id'],None)
            raise

    def transaction(self, command):
        sent_ns, stamp = time.monotonic_ns(), utc_now()
        raw, error, status, readings, parsed, rejections = b"", "", "OK", [], [], []
        protocol_errors, discovery_samples = [], []
        try:
            raw = self.transport.exchange(command, self.stop_io)
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
                    if pid in self.registry:
                        if pid not in self.support.get(source, set()):
                            continue
                        sensor = self.registry[pid]
                        try: decoded = sensor.decode(reply.data)
                        except ValueError as exc:
                            protocol_errors.append({'ecu':reply.header, 'reason':str(exc), 'state':'INVALID'}); continue
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
        record['raw_only'] = bool(self.capture_mode and command.startswith('01') and int(command[2:],16) in self.capture_raw_pids)
        record['raw_samples'] = [s for s in discovery_samples if s.get('raw_only')]
        if command.startswith('01') and int(command[2:],16) in DISCOVERY_PIDS:
            record['support_evidence'] = {e:sorted(p) for e,p in self.support.items()}
            record['support_pages'] = {e:sorted(p) for e,p in self.support_pages.items()}
        self.retain_discovery_errors(record)
        if self.recorder: self.recorder.append(record, readings)
        if self.auto_receipt:
            if self.recorder and (self.auto_starting or self.auto_receipt.data['state'] in {'WAITING_RAW','PARTIAL','READY'}):
                self.auto_receipt.track_transaction(record)
            self.auto_receipt.observe(record, readings, recorded=bool(self.recorder),
                active=self.capture_mode and self.auto_receipt.data['state'] in {'WAITING_RAW','PARTIAL','READY'})
            self.update_auto_receipt()
        self.emit("transaction", (record, readings))
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
            sample = dict(self.discovery_observations.get((source,pid),{}),
                          ecu=problem['ecu'] or (source if source!='unknown' else None),pid=pid,error=problem['reason'],
                          error_timestamp=record['timestamp'],raw_b64=record['raw_b64'],
                          replay=record.get('replay',False),source_kind=record.get('source_kind','UNKNOWN'))
            if problem.get('category')!='DECODER_LAYOUT':
                sample.update(framing_valid=False,raw_only=False,layout_status='INVALID_RESPONSE')
            self.discovery_observations[source,pid] = sample
        # Raw framing belongs to the whole transaction, including failed replies.
        for sample in record.get('discovery_samples',[]): sample['raw_b64'] = record['raw_b64']

    def diesel_readings(self, sample, pid, stamp, sent_ns):
        return [dict(sensor_id=f['sensor_id'], pid=pid, ecu=sample['ecu'], value=f['value'], unit=f['unit'],
                     verification=f['verification'], timestamp=stamp, monotonic_ns=sent_ns,
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
                support={e:sorted(p) for e,p in self.support.items()},
                support_pages={e:sorted(p) for e,p in self.support_pages.items()},
                report=discovery_report(self.support,self.support_pages,self.discovery_observations,mode=self.mode,context_id=self.context_id))

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
            self.auto_stage('RECORDING','Recording acknowledged before connection; initialization retained')
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
            for pid in sorted(DISCOVERY_PIDS & self.support[target]):
                if self.auto_starting and (not affirmative_bitmap(self.support,self.support_pages,target,pid) or
                                          any(e==target for e,base in self.bitmap_conflicts)):
                    continue
                if self.stop_io.is_set(): raise Cancelled('Discovery stopped before send')
                record = self.transaction(f'01{pid:02X}')
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
        self.polling = active
        self.requires_reconnect = requires_reconnect
        self.emit("acquisition", {"polling": active, "reason": reason, "requires_reconnect": requires_reconnect})

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
        self.transport = Simulator(options.get("scenario", "Normal idle")) if options["simulation"] else SerialTransport(self.port, options.get("baud", 115200))
        self.transport.rate = self.rate
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
                    record['discovery_samples'].append(sample)
                    for reading in self.diesel_readings(sample,pid,record['timestamp'],record['monotonic_ns']):
                        reading['mode'] = 'REPLAY · '+record.get('mode','unknown'); readings.append(reading)
                self.emit_discovery()
            if pid in self.registry:
                sensor = self.registry[pid]
                try:
                    for reply in positive_replies:
                        readings.append({"sensor_id": sensor.id, "pid": pid, "ecu": reply.header,
                            "value": sensor.decode(reply.data), "unit": sensor.unit,
                            "verification": sensor.metadata["verification"], "timestamp": record["timestamp"],
                            "monotonic_ns": record["monotonic_ns"], "mode": "REPLAY · " + record.get("mode", "unknown"),
                            "source_kind": "SIMULATED" if record.get("mode") == "SIMULATED" else "ECU_READING" if record.get("mode", "").startswith("LIVE") else "UNKNOWN"})
                except ValueError as exc: self.emit("notice", str(exc))
        self.retain_discovery_errors(record)
        self.emit("transaction", (record, readings))

    def handle(self, action, options):
        if action == 'full_auto': self.full_auto(options)
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
        elif action == "disconnect": self.disconnect()
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
        elif action == "shutdown": self.quit_event.set()

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
                    if self.transport and self.transport.last_wire_ns is not None:
                        self.disconnect(); self.emit("notice", "Receive canceled after send; reconnect to restore prompt synchronization")
                except Exception as exc:
                    self.emit("notice", str(exc)); self.disconnect()
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
                        if self.transport and self.transport.last_wire_ns is not None:
                            self.disconnect(); self.emit("notice", "Receive canceled after send; reconnect to restore prompt synchronization")
                    except Exception as exc:
                        self.emit("notice", str(exc)); self.disconnect()
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
            self.disconnect()
            if self.replay: self.replay.close()
