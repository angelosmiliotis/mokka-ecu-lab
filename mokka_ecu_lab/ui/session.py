"""Projection of the worker's canonical session state; no acquisition state machine."""
from pathlib import Path
import time
from datetime import datetime,timezone
from PySide6.QtCore import Qt,QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QWidget,QVBoxLayout,QLabel,QGroupBox,QTableWidget,QTableWidgetItem,QCheckBox,QTextEdit,QHeaderView,QAbstractItemView,QComboBox
from .components import FlowLayout,caption,page_heading
from .theme import style_table
from mokka_ecu_lab.auto_capture import ALL_SENSOR_PIDS
from mokka_ecu_lab.sensors.diesel import STANDARD_DIESEL
from mokka_ecu_lab.protocols import support_state


class SessionPanel(QWidget):
    def __init__(self,window):
        super().__init__(); self.window=window; self.snapshot={}; self.last_table_update=0.
        layout=QVBoxLayout(self); layout.setSpacing(10)
        page_heading(layout,'Session Dashboard','Connect → Start Session → Finish Session. All evidence stays on this computer.')
        self.identity=QLabel(); self.identity.setObjectName('badge'); self.identity.setWordWrap(True); layout.addWidget(self.identity)
        row=FlowLayout(spacing=10)
        self.connect=window.button('Connect',self.connect_action,'primary')
        self.start=window.button('Start Session',self.start_action,'primary')
        self.finish=window.button('Finish Session',lambda:window.send('session_finish'),'stop')
        for button in (self.connect,self.start,self.finish): button.setMinimumHeight(44); row.addWidget(button)
        layout.addLayout(row)
        self.profile=QComboBox();self.profile.addItem('Comprehensive · all eligible sensors','DPF Research Priority');self.profile.addItem('DPF + Turbo · critical subset only','DPF + Turbo / Critical subset');self.profile.setAccessibleName('Optional pre-drive sampling profile');layout.addWidget(self.profile)
        layout.addWidget(caption('Default includes every eligible PID. Optional critical subset improves cadence within the same 4 req/s budget; no fast turbo-response claim. Select while parked.'))
        layout.addWidget(caption('Start Session authorizes the fixed READ-ONLY research profile: all eligible standard sensors, eligible RAW-only 017A/0188, DPF Priority, ≤4 total req/s. No individual selection or additional consent step.'))
        self.state=QLabel(); self.state.setWordWrap(True); layout.addWidget(self.state)
        self.metrics=QLabel(); self.metrics.setWordWrap(True); layout.addWidget(self.metrics)
        dpf_box=QGroupBox('017A RAW research evidence'); dpf_layout=QVBoxLayout(dpf_box)
        self.dpf=QLabel(); self.dpf.setWordWrap(True); dpf_layout.addWidget(self.dpf)
        dpf_layout.addWidget(caption('Six-byte replies have no verified pressure, soot, ash or regeneration meaning. READY requires two stored polling replies and worker-confirmed scheduling; Discovery does not count.'))
        layout.addWidget(dpf_box)
        self.path=QLabel('No export yet'); self.path.setWordWrap(True); self.path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse); layout.addWidget(self.path)
        secondary=FlowLayout()
        self.folder=window.button('Open Folder',self.open_folder)
        self.retry=window.button('Retry private export offline',lambda:window.send('session_export_retry',session_id=self.snapshot.get('session_id')))
        secondary.addWidget(self.folder); secondary.addWidget(self.retry); layout.addLayout(secondary)
        self.catalog_toggle=QCheckBox('Sensor catalog · all fields, sampling and omissions'); self.catalog_toggle.setChecked(True)
        layout.addWidget(self.catalog_toggle)
        self.catalog=QTableWidget(0,11)
        self.catalog.setHorizontalHeaderLabels(['PID / field','Value','Unit','Evidence / last query','ECU / source','Samples','Last valid UTC','Age s','Nominal s','Observed mean / max s','Omission / limit'])
        style_table(self.catalog); self.catalog.setMinimumHeight(200); self.catalog.setMaximumHeight(320)
        self.catalog.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.catalog.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        for column,width in enumerate((320,100,65,280,160,70,240,75,95,170,280)): self.catalog.setColumnWidth(column,width)
        self.catalog_toggle.toggled.connect(self.catalog.setVisible); layout.addWidget(self.catalog)
        self.field_detail=QTextEdit(); self.field_detail.setReadOnly(True); self.field_detail.setMaximumHeight(100)
        self.field_detail.setPlaceholderText('Select a field for its complete value, source, validity, cadence and omission detail.')
        self.catalog.itemSelectionChanged.connect(self.describe_field)
        layout.addWidget(self.field_detail); self.catalog_toggle.toggled.connect(self.field_detail.setVisible)
        layout.addWidget(caption('No single temperature, NOx, MAP or reagent snapshot diagnoses health. NOx absent slots are unavailable; reagent level is quantized, not measured consumption. SCR current state and historical counters have separate meanings.'))
        self.advanced=QCheckBox('Advanced / Developer · manual diagnostics and offline tools')
        self.advanced.toggled.connect(self.update); layout.addWidget(self.advanced)
        self.benchmark_group=QGroupBox('Stationary benchmark · Advanced only · fixed ≤4 aggregate req/s')
        bench_layout=QVBoxLayout(self.benchmark_group)
        bench_layout.addWidget(caption('Requires idle connected adapter, completed current Discovery and already positive RPM/MAP/MAF. No active session/recording. Maximum 48 requests / 60 seconds; aborts on errors and disconnects. Conditions are user-reported.'))
        bench_layout.addWidget(caption('Confirm: parked, transmission safe, brake engaged, adequate ventilation, and no other OBD client connected.'))
        self.bench_consent=QCheckBox('Stationary conditions above confirmed')
        self.bench_consent.toggled.connect(self.update)
        self.bench_consent.setStyleSheet('QCheckBox { padding: 4px; }');bench_layout.addWidget(self.bench_consent)
        bench_row=FlowLayout();self.bench_rate=QComboBox();self.bench_rate.addItems(['1','2','4']);self.bench_rate.setCurrentText('2');bench_row.addWidget(self.bench_rate)
        self.bench_start=window.button('Start stationary benchmark',lambda:window.send('benchmark_start',parked_consent=self.bench_consent.isChecked(),rate=float(self.bench_rate.currentText())))
        self.bench_stop=window.button('Stop benchmark',lambda:window.send('benchmark_stop'));bench_row.addWidget(self.bench_start);bench_row.addWidget(self.bench_stop);bench_layout.addLayout(bench_row)
        self.bench_status=caption('No benchmark started; normal session workflow remains three actions.');bench_layout.addWidget(self.bench_status);layout.addWidget(self.benchmark_group)
        layout.addStretch()
        self.update()

    def connect_action(self):
        w=self.window
        w.send('session_connect',simulation=w.source.currentIndex()==0,port=w.port.currentText().strip(),
            baud=115200,scenario=w.scenario.currentText(),ecu=w.source_key())

    def start_action(self):
        self.window.send('session_start',simulation=self.window.source.currentIndex()==0,profile=self.profile.currentData())

    def acknowledge(self,data):
        self.snapshot=data
        for action in ('session_connect','session_start','session_finish','session_export_retry'): self.window.pending_actions.pop(action,None)
        if data['state']=='CONNECTED':
            self.window.settings.setValue('session_last_source',0 if data['mode']=='SIMULATED' else 1)
            if data['mode'].startswith('LIVE'): self.window.settings.setValue('session_outgoing_port',data['port'])
        if data.get('bundle_path'):
            self.window.bundle_destination=data['bundle_path']; self.window.exported_session_id=data.get('session_id')
            self.window.refresh_sessions()
        self.update()

    def open_folder(self):
        path=self.snapshot.get('bundle_path') or self.snapshot.get('journal_path')
        if path: QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).parent)))

    def update(self,*_):
        w=self.window; d=self.snapshot; state=d.get('state','DISCONNECTED'); active=d.get('active',False)
        pending=any(a.startswith('session_') for a in w.pending_actions)
        self.connect.setEnabled(not active and not pending and state not in {'CONNECTED','CONNECTING','FINALIZING'} and not w.recording_id)
        self.start.setEnabled(state=='CONNECTED' and not active and not pending and not w.requires_reconnect and not w.recording_id and not w.capture_active)
        self.finish.setEnabled(active and not pending and state!='FINALIZING')
        self.advanced.setEnabled(not active and not pending)
        developer=self.advanced.isChecked() and not active and not pending
        self.profile.setEnabled(not active and not pending and not getattr(w,'benchmark_state',{}).get('active'))
        self.benchmark_group.setVisible(False) # Deprecated internal API; one public start path on Benchmark page.
        benchmark=getattr(w,'benchmark_state',{})
        if benchmark.get('active'):
            for button in (self.connect,self.start,self.finish,self.advanced):button.setEnabled(False)
            for widget in (w.source,w.port,w.baud,w.scenario,w.rate,w.refresh_port_button):widget.setEnabled(False)
            w.status_indicators['Activity'].setText('Activity · Stationary benchmark')
        self.bench_start.setEnabled(developer and self.bench_consent.isChecked() and w.connected and not w.recording_id and not w.polling_active and not benchmark.get('active'))
        self.bench_stop.setEnabled(bool(benchmark.get('active')))
        self.bench_status.setText(str(benchmark.get('reason','No benchmark started; normal session workflow remains three actions.'))+
            (f' · {benchmark.get("requests",0)} / 48 requests · {benchmark.get("rate",0):g} total req/s' if benchmark else '')+
            ('\nPrivate bundle: '+benchmark['bundle_path'] if benchmark.get('bundle_path') else ''))
        for i in (0,2,3,5,6):
            if hasattr(w,'sidebar'): w.sidebar.buttons[i].setVisible(developer)
        for button in (w.connect_button,w.disconnect_button): button.setVisible(developer)
        if not developer and w.tabs.currentIndex() in (0,2,3,5,6): w.tabs.setCurrentIndex(7)
        if active or pending:
            for widget in (w.source,w.port,w.baud,w.scenario,w.rate,w.refresh_port_button): widget.setEnabled(False)
        if state!='DISCONNECTED' and not developer: w.status_indicators['Activity'].setText('Activity · Session / '+state)
        recorded_mode=d.get('recorded_mode') if state=='EXPORTED' else None
        source_label=('EXPORTED RECORDING: '+('LIVE · hardware unverified' if recorded_mode.startswith('LIVE') else 'SIMULATION — synthetic data' if recorded_mode=='SIMULATED' else 'UNKNOWN recorded source')) if recorded_mode else ('SIMULATION — synthetic data' if w.source.currentIndex()==0 else 'LIVE · hardware unverified')
        ecu_display=', '.join(d.get('recorded_ecus',[])) if recorded_mode else d.get('ecu')
        self.identity.setText(source_label+
            f'   ·   Port {"CLOSED" if recorded_mode else d.get("port") or w.port.currentText()}   ·   ECU {ecu_display or "not confirmed"}')
        self.state.setText(state+' · '+d.get('reason','Connect explicitly; no recording is open')+
            (' · awaiting worker acknowledgment' if pending else '')+(('\n'+d['export_error']) if d.get('export_error') else ''))
        r=d.get('receipt') or {}; schedule=r.get('effective_schedule',{}); observed=r.get('observed',{})
        elapsed=d.get('duration_seconds',0.)
        if active and d.get('started_at'): elapsed=(datetime.now(timezone.utc)-datetime.fromisoformat(d['started_at'])).total_seconds()
        self.metrics.setText(f'Session {d.get("session_id") or "—"}  ·  {elapsed:.1f} s  ·  recording {"ACTIVE / worker confirmed" if d.get("recording_active") else "closed / off"}\n'
            f'Scheduled {len(schedule)}  ·  observed {sum(v.get("positive_samples",0)>0 for v in observed.values())}  ·  omitted {len({e["pid"] for e in r.get("requested_plan",{}).get("omitted",[])+r.get("runtime_omissions",[])})} / {len(ALL_SENSOR_PIDS)} known PIDs  ·  ≤{d.get("rate_limit",w.rate.value()):g} total req/s\n'
            f'Recorded transactions {d.get("recorded_transactions",0)}  ·  transaction errors {d.get("transaction_errors",0)}\n'+
            'Quality: '+', '.join(f'{name} {r.get("acquisition_error_categories",{}).get(category,0)}' for name,category in
                (('layout mismatches','DECODER_LAYOUT'),('transport failures','TRANSPORT_FAILURE'),('intentional cancellations','INTENTIONAL_CANCELLATION'),('ECU/framing failures','ECU_OR_FRAMING'))))
        proof=r.get('dpf',{}); count=proof.get('recorded_positive_six_byte_frames',0)
        pacing=r.get('adaptive_pacing',{})
        if pacing:self.metrics.setText(self.metrics.text()+f'\nAdaptive effective rate {pacing["rate"]:g} req/s · ceiling {pacing["policy_ceiling"]:g} · '+pacing['reason'])
        proof_state=proof.get('state','WAITING') if active else ('RECORDED PROOF' if count>=2 else 'NOT CAPTURING')
        self.dpf.setText(f'{proof_state}  ·  worker scheduled {"YES" if proof.get("worker_scheduled") else "NO"}  ·  stored six-byte positives {count} / 2\n'+
            f'Last stored UTC: {proof.get("last_timestamp") or "—"}  ·  {proof.get("last_payload_hex") or "No stored RAW reply"}\n'+proof.get('reason','Start Session performs fresh recorded Discovery'))
        self.path.setText(('Verified private bundle: '+d['bundle_path']) if d.get('checksums_verified') and d.get('bundle_path') else ('Original journal: '+d['journal_path']) if d.get('journal_path') else 'No recorded session / export yet')
        if benchmark.get('active'):
            self.identity.setText('STATIONARY BENCHMARK · '+benchmark.get('mode','UNKNOWN')+' · ECU '+str(benchmark.get('ecu')))
            self.state.setText('BENCHMARK ACTIVE · fixed verified subset; conditions USER_REPORTED')
            self.metrics.setText(f'Benchmark {benchmark.get("session_id")} · {benchmark.get("requests",0)} / 48 requests · {benchmark.get("rate",0):g} total req/s · maximum 60 seconds')
            self.dpf.setText('NOT CAPTURING · This fixed benchmark samples RPM / MAP / MAF. Normal DPF capture starts through Start Session.')
        self.folder.setEnabled(bool(d.get('bundle_path') or d.get('journal_path')))
        self.retry.setEnabled(state=='FAILED' and d.get('retry_export',False) and not active and not pending and not d.get('adapter_open'))
        if time.monotonic()-self.last_table_update>=1:
            self.last_table_update=time.monotonic(); self.refresh_catalog(r)

    def refresh_catalog(self,receipt):
        w=self.window; ecu=self.snapshot.get('ecu') or w.source_key(); self.catalog.setRowCount(0)
        matrix={e['pid']:e for e in receipt.get('requested_plan',{}).get('matrix',[])}
        omitted={e['pid']:e['reason'] for e in receipt.get('requested_plan',{}).get('omitted',[])+receipt.get('runtime_omissions',[])}
        for pid in sorted(ALL_SENSOR_PIDS):
            key=f'{pid:02X}'; stats=receipt.get('observed',{}).get(key,{})
            plan=receipt.get('effective_schedule',{}).get(key,{})
            fields=stats.get('fields',{})
            definitions=STANDARD_DIESEL[pid].fields if pid in STANDARD_DIESEL else ()
            names={f'sae_{pid:02x}_{f.id}':(f.name,f.unit) for f in definitions}
            if pid in w.registry: names={w.registry[pid].id:(w.registry[pid].name,w.registry[pid].unit)}
            if pid in w.capture_raw_pids or key in receipt.get('confirmed_raw_pids',[]): names={key+' RAW':('RAW ONLY / numeric unavailable','bytes')}
            for sid,(name,unit) in (names or {key:('No field definition','—')}).items():
                sample=fields.get(sid); age=(time.monotonic_ns()-sample['monotonic_ns'])/1e9 if sample and self.snapshot.get('active') else None
                nominal=plan.get('nominal_interval_seconds')
                state=('STALE' if age is not None and nominal and age>max(2,nominal*2) else 'LAST VALID' if sample else 'RAW ONLY' if 'RAW' in sid else 'UNAVAILABLE')
                if sample: state='DECODED / '+sample.get('verification','UNVERIFIED')+' / '+state
                support=matrix.get(key,{}).get('support') or support_state(w.support.get(ecu,set()),w.support_pages.get(ecu,set()),pid)
                state=support.upper()+' / '+state
                state+=' / '+stats.get('last_status','no polling sample')
                reason=omitted.get(key) or matrix.get(key,{}).get('reason') or ('Independent timestamps; no health verdict' if sample else 'Absent/unsupported field is not zero')
                row=self.catalog.rowCount(); self.catalog.insertRow(row)
                gap=lambda x:'—' if x is None else f'{x:.3g}'
                value='—' if not sample else f'{sample["value"]:.6g}'
                if sample and isinstance(sample.get('display'),str):value+=' · '+sample['display']
                values=[f'01{key} · {name}',value,unit,state,f'{ecu or "—"} / {self.snapshot.get("source_kind","UNKNOWN")}',sample['samples'] if sample else stats.get('raw_only_samples',0) if 'RAW' in sid else 0,
                    sample['timestamp'] if sample else stats.get('last_timestamp','—'),gap(age),gap(nominal),gap(stats.get('mean_interval_seconds'))+' / '+gap(stats.get('maximum_gap_seconds')),reason]
                for column,text in enumerate(values):
                    item=QTableWidgetItem(str(text)); item.setToolTip(str(text)); self.catalog.setItem(row,column,item)

    def describe_field(self):
        row=self.catalog.currentRow()
        if row>=0:
            self.field_detail.setPlainText('\n'.join(self.catalog.horizontalHeaderItem(c).text()+': '+self.catalog.item(row,c).text() for c in range(self.catalog.columnCount())))
