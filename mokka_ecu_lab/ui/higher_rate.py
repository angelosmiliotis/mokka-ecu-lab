"""Visible locked LIVE proposal and a separate pure, accelerated offline model.

This page has no AcquisitionWorker or transport reference. The LIVE button has
no action handler. Checking, importing or editing a file cannot unlock it.
"""
import json
import math
from pathlib import Path
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QLabel,QComboBox,QSpinBox,
    QPushButton,QTextEdit,QFileDialog)
from mokka_ecu_lab.research.future_benchmark import (
    SyntheticBenchmark,SyntheticFault,FAULTS,engineering_brief)
from mokka_ecu_lab.research.experimental_benchmark import (
    ExperimentalFakeCOMBenchmark,FakeScenario,FakeFault,FAULTS as COM_FAULTS,implementation_brief)
from .components import caption,FlowLayout


class HigherRatePanel(QWidget):
    def __init__(self,parent=None):
        super().__init__(parent);self.model=None;self.snapshot={};self.fake_engine=None
        layout=QVBoxLayout(self);layout.setSpacing(6)
        title=QLabel('Higher-rate research');title.setObjectName('pageTitle');layout.addWidget(title)
        self.lock_state=caption('LIVE >4: LOCKED · Separate precise authorization and engineering review required.')
        self.lock_state.setObjectName('sourceIdentity');layout.addWidget(self.lock_state)
        layout.addWidget(caption('1–4 req/s: normal LIVE policy. 5 req/s: FAKE COM only, physical LOCKED. 6 req/s: not authorized. Hardware capacity above four has not been established.'))
        row=FlowLayout();self.live_start=QPushButton('Experimental LIVE · LOCKED');self.live_start.setEnabled(False)
        self.live_start.setAccessibleName('Experimental LIVE locked; fake COM engine implemented, physical backend unavailable')
        self.live_start.setToolTip('The separate 5/s byte engine is validated with fake COM. A separately reviewed hardware build and precise operator authorization are still required; no configuration unlock exists.')
        row.addWidget(self.live_start)
        self.export=QPushButton('Export engineering brief');self.export.clicked.connect(self.choose_export);row.addWidget(self.export);layout.addLayout(row)
        layout.addWidget(caption('First proposal: ONE stationary 5 req/s ×60 s run, fixed 010D/010C/010B/0110. Preparation and transition remain ≥250 ms; the separate measurement uses ≥200 ms. Later 6 req/s needs separate review and authorization.'))
        layout.addWidget(caption('Before any future LIVE run: fresh matched 4/s reference; per-run operator confirmation of brake, safe transmission, outdoor ventilation and no competing client; verified speed zero, ECU/context/prompt. Speed zero alone does not prove safe parking.'))
        heading=QLabel('Experimental 5 req/s engine · FAKE COM BYTES');heading.setObjectName('nextActionTitle');layout.addWidget(heading)
        layout.addWidget(caption('Implemented serialized byte requests, fragmented serial reads, strict frame/prompt checks, one global send ledger and fail-closed aborts. Fixed 12-request preflight ≤4/s, then at most 300 requests / 60 virtual seconds at 5/s. Physical serial is unavailable in this pathway.'))
        row=FlowLayout();self.fake_start=QPushButton('Validate 5/s engine · FAKE COM');self.fake_start.clicked.connect(self.start_fake)
        self.fake_stop=QPushButton('Stop fake COM');self.fake_stop.clicked.connect(self.stop_fake)
        row.addWidget(self.fake_start);row.addWidget(self.fake_stop);layout.addLayout(row)
        row=FlowLayout();self.fake_fault=QComboBox();self.fake_fault.addItems(['NONE',*sorted(COM_FAULTS)]);self.fake_fault.setAccessibleName('Fake COM injected fault')
        self.fake_fault_at=QSpinBox();self.fake_fault_at.setRange(0,311);self.fake_fault_at.setValue(20);self.fake_fault_at.setAccessibleName('Fake COM zero-based request index including preflight')
        row.addWidget(QLabel('Fake COM fault'));row.addWidget(self.fake_fault);row.addWidget(QLabel('at request'));row.addWidget(self.fake_fault_at);layout.addLayout(row)
        self.fake_status=caption('NOT RUN · no physical backend; actual hardware transmissions 0');layout.addWidget(self.fake_status)
        self.fake_details=QTextEdit();self.fake_details.setReadOnly(True);self.fake_details.setMinimumHeight(110);self.fake_details.setMaximumHeight(180);layout.addWidget(self.fake_details)
        self.fake_timer=QTimer(self);self.fake_timer.setInterval(25);self.fake_timer.timeout.connect(self.advance_fake)
        heading=QLabel('Offline timing model · virtual time');heading.setObjectName('nextActionTitle');layout.addWidget(heading)
        row=FlowLayout();self.rate=QComboBox();self.rate.addItems([str(i) for i in range(1,7)]);self.rate.setCurrentText('5');self.rate.setAccessibleName('Offline model requests per second')
        row.addWidget(QLabel('Constructed rate'));row.addWidget(self.rate)
        self.response_ms=QSpinBox();self.response_ms.setRange(1,1000);self.response_ms.setValue(100);self.response_ms.setSuffix(' ms');self.response_ms.setAccessibleName('Constructed response time in milliseconds')
        row.addWidget(QLabel('Response'));row.addWidget(self.response_ms);layout.addLayout(row)
        row=FlowLayout();self.fault_kind=QComboBox();self.fault_kind.addItems(['NONE',*FAULTS]);self.fault_kind.setAccessibleName('Offline injected abort condition')
        self.fault_at=QSpinBox();self.fault_at.setRange(0,400);self.fault_at.setValue(20);self.fault_at.setAccessibleName('Zero-based constructed request index including preflight')
        row.addWidget(QLabel('Inject'));row.addWidget(self.fault_kind);row.addWidget(QLabel('at request'));row.addWidget(self.fault_at);layout.addLayout(row)
        row=FlowLayout();self.start=QPushButton('Run OFFLINE model');self.start.setObjectName('primary');self.start.clicked.connect(self.start_model)
        self.stop=QPushButton('Stop model');self.stop.setObjectName('stop');self.stop.clicked.connect(self.stop_model)
        row.addWidget(self.start);row.addWidget(self.stop);layout.addLayout(row)
        self.state=caption('IDLE · no connection, files or diagnostic requests on page visit.');layout.addWidget(self.state)
        self.countdown=caption('Virtual measurement remaining 01:00 · actual OBD transmissions 0');layout.addWidget(self.countdown)
        self.details=QTextEdit();self.details.setReadOnly(True);self.details.setMinimumHeight(100);layout.addWidget(self.details,1)
        layout.addWidget(caption('The model runs faster than wall time. Synthetic spacing, Stop and injected aborts test design only; they do not establish ECU safety, CAN load or available throughput.'))
        self.timer=QTimer(self);self.timer.setInterval(35);self.timer.timeout.connect(self.advance_model)
        self.refresh()

    def start_model(self):
        if self.model is not None and self.model.active or self.fake_engine is not None and self.fake_engine.active:return
        fault=None if self.fault_kind.currentText()=='NONE' else SyntheticFault(self.fault_at.value(),self.fault_kind.currentText())
        self.model=SyntheticBenchmark(int(self.rate.currentText()),response_ms=self.response_ms.value(),fault=fault)
        self.timer.start();self.refresh()

    def advance_model(self):
        if self.model is None:return
        self.model.advance()
        if not self.model.active:self.timer.stop()
        self.refresh()

    def stop_model(self):
        self.timer.stop()
        if self.model:self.model.stop()
        self.refresh()

    def refresh(self):
        active=bool(self.model and self.model.active)
        fake_active=bool(self.fake_engine and self.fake_engine.active)
        self.start.setEnabled(not active and not fake_active);self.stop.setEnabled(active)
        self.fake_start.setEnabled(not active and not fake_active);self.fake_stop.setEnabled(fake_active)
        self.fake_fault.setEnabled(not fake_active);self.fake_fault_at.setEnabled(not fake_active)
        for control in (self.rate,self.response_ms,self.fault_kind,self.fault_at):control.setEnabled(not active)
        if self.model:
            self.snapshot=self.model.snapshot();s=self.snapshot
            self.state.setText(s['state']+' · '+s['reason'])
            remain=math.ceil(s['virtual_remaining_seconds'])
            self.countdown.setText(f'Virtual measurement remaining {remain//60:02d}:{remain%60:02d} · actual OBD transmissions 0')
            displayed={k:v for k,v in s.items() if k!='events'}
            self.details.setPlainText(json.dumps(displayed,indent=2,ensure_ascii=False))
        else:
            self.details.setPlainText('The upper section runs the implemented five-request engine over memory-backed COM bytes. This lower section remains the legacy scalar timing model. Both use virtual time and send ZERO hardware requests.\n\nPhysical LIVE is LOCKED: independent safety review, a separate reviewed hardware-enabled build and exact operator approval are required. No checkbox, JSON file or environment setting enables it.')

    def start_fake(self):
        if self.model and self.model.active or self.fake_engine and self.fake_engine.active:return
        try:
            fault=None if self.fake_fault.currentText()=='NONE' else FakeFault(self.fake_fault_at.value(),self.fake_fault.currentText())
            engine=ExperimentalFakeCOMBenchmark(FakeScenario(fault=fault))
        except ValueError as exc:
            self.fake_status.setText('BLOCKED · '+str(exc)+' · hardware transmissions 0');return
        self.fake_engine=engine;self.fake_timer.start();self.refresh_fake()

    def advance_fake(self):
        if self.fake_engine:
            self.fake_engine.advance()
            if not self.fake_engine.active:self.fake_timer.stop()
            self.refresh_fake()

    def stop_fake(self):
        self.fake_timer.stop()
        if self.fake_engine:self.fake_engine.stop()
        self.refresh_fake()

    def refresh_fake(self):
        if self.fake_engine:
            s=self.fake_engine.snapshot()
            self.fake_status.setText(f"{s['state']} · {s['reason']} · fake writes {s['fake_com_writes']} · hardware transmissions 0")
            self.fake_details.setPlainText(json.dumps({k:v for k,v in s.items() if k!='events'},indent=2))
        self.refresh()

    def export_brief(self,path):
        """Create one new generic brief at the explicitly selected destination."""
        payload=engineering_brief()
        payload['experimental_implementation']=implementation_brief()
        if self.fake_engine:payload['fake_com_validation']=self.fake_engine.snapshot()
        if self.model:payload['last_constructed_model']=self.model.snapshot()
        destination=Path(path)
        with destination.open('x',encoding='utf-8',newline='\n') as stream:
            json.dump(payload,stream,indent=2,ensure_ascii=False);stream.write('\n')
        return destination

    def choose_export(self):
        path,_=QFileDialog.getSaveFileName(self,'Export generic engineering proposal','Mokka-higher-rate-engineering-brief.json','JSON (*.json)')
        if not path:return
        try:self.export_brief(path);self.state.setText('Engineering proposal exported locally. LIVE remains LOCKED.')
        except (OSError,ValueError) as exc:self.state.setText('Export failed; no replacement performed: '+str(exc))

    def closeEvent(self,event):
        self.timer.stop()
        self.fake_timer.stop()
        if self.fake_engine:self.fake_engine.shutdown()
        if self.model:self.model.stop()
        super().closeEvent(event)
