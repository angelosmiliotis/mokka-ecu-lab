"""Visible one-click benchmark projection; no transport or workflow state machine."""
import math,time
from pathlib import Path
from PySide6.QtCore import Qt,QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QWidget,QVBoxLayout,QLabel,QComboBox,QProgressBar,QTextEdit
from .components import FlowLayout,caption


class BenchmarkPanel(QWidget):
    def __init__(self,window):
        super().__init__();self.window=window;self.snapshot={};self.pending=False;self.rejection=''
        layout=QVBoxLayout(self);layout.setSpacing(5)
        title=QLabel('Benchmark');title.setObjectName('pageTitle');layout.addWidget(title)
        self.identity=caption('');layout.addWidget(self.identity)
        row=FlowLayout();self.rate=QComboBox();self.rate.addItems(['1','2','3','4']);self.rate.setCurrentText('2');self.rate.setAccessibleName('Benchmark requests per second')
        row.addWidget(self.rate);row.addWidget(QLabel('requests/second · 60 seconds fixed'))
        self.start=window.button('Start BENCH',self.start_action,'primary');self.start.setMinimumHeight(40);row.addWidget(self.start)
        self.stop=window.button('Stop && save',lambda:window.send('bench_auto_stop'),'stop');self.stop.setAccessibleName('Stop & save');self.stop.setMinimumHeight(40);row.addWidget(self.stop)
        layout.addLayout(row)
        layout.addWidget(caption('Start BENCH confirms: parked, brake applied, safe transmission, ventilation, no competing OBD client. Speed must remain zero. Read-only · ≤4 total req/s.'))
        self.timer=QLabel('01:00');self.timer.setStyleSheet('font-size: 32px; font-weight: 700;');self.timer.setAccessibleName('Benchmark remaining time');layout.addWidget(self.timer)
        self.progress=QProgressBar();self.progress.setRange(0,600);self.progress.setValue(0);self.progress.setTextVisible(False);self.progress.setMaximumHeight(12);layout.addWidget(self.progress)
        self.state=caption('IDLE · Choose a rate and Start BENCH. Preparation starts only on click.');layout.addWidget(self.state)
        self.metrics=caption('');layout.addWidget(self.metrics)
        row=FlowLayout();self.report=window.button('Open report',self.open_report);self.folder=window.button('Open folder',self.open_folder)
        self.retry=window.button('Retry export offline',lambda:window.send('bench_export_retry',session_id=self.snapshot.get('session_id')))
        for b in (self.report,self.folder,self.retry):row.addWidget(b)
        layout.addLayout(row)
        self.details=QTextEdit();self.details.setReadOnly(True);self.details.setMinimumHeight(50);layout.addWidget(self.details,1)
        layout.addWidget(caption('Measures communication stability within the approved ceiling; not ECU maximum capacity. Next rate is your explicit choice in a separate run.'))
        self.update()
    def start_action(self):
        w=self.window;self.pending=True;self.rejection='';self.update()
        accepted=w.worker.submit('bench_auto_start',parked_consent=True,rate=int(self.rate.currentText()),simulation=w.source.currentIndex()==0,port=w.port.currentText(),baud=int(w.baud.currentText()),scenario=w.scenario.currentText())
        if accepted is False:self.pending=False;self.update()
    def acknowledge(self,value):
        self.snapshot=value;self.pending=False
        if value.get('state')=='ECU_CONFIRMED':
            self.window.settings.setValue('session_last_source',0 if value['mode']=='SIMULATED' else 1)
            if value['mode'].startswith('LIVE'):self.window.settings.setValue('session_outgoing_port',self.window.port.currentText())
        self.update()
    def reject(self,reason):
        self.pending=False;self.rejection=reason;self.update()
    def update(self):
        w=self.window;s=self.snapshot;active=s.get('active',False) or self.pending
        source='SIMULATION — synthetic data' if w.source.currentIndex()==0 else 'LIVE — '+w.port.currentText()
        if s.get('active'):source=s.get('mode','UNKNOWN')+' · ECU '+str(s.get('ecu') or 'confirming')
        elif s.get('session_id'):source+=' · Last run: '+s.get('mode','UNKNOWN')+' / ECU '+str(s.get('ecu') or 'unconfirmed')
        self.identity.setText(source)
        conflict=bool(w.session_panel.snapshot.get('active') or w.recording_id or w.polling_active or w.mode.startswith('REPLAY')) if hasattr(w,'session_panel') else False
        self.start.setEnabled(not active and not conflict);self.rate.setEnabled(not active);self.stop.setEnabled(active)
        if self.rejection and not active:self.state.setText('BLOCKED · '+self.rejection)
        elif not active and conflict:self.state.setText('BLOCKED · Finish the existing recording/session/polling or leave replay before Start BENCH.')
        else:self.state.setText(('PREPARING · waiting for worker' if self.pending else s.get('state','IDLE'))+' · '+s.get('reason','Choose rate; click starts automatic preparation.'))
        elapsed=s.get('elapsed_seconds',0.)
        if s.get('active') and s.get('measurement_started_monotonic') is not None:elapsed=max(0,time.monotonic()-s['measurement_started_monotonic'])
        remain=math.ceil(max(0,60-elapsed));self.timer.setText(f'{remain//60:02d}:{remain%60:02d}');self.progress.setValue(min(600,int(elapsed*10)))
        latency=s.get('latency_ms',{});fmt=lambda x:'—' if x is None else f'{x:.1f}'
        count=s.get('requests',0);rate=count/elapsed if elapsed>0 else 0
        self.metrics.setText(f'Sent {count} / {s.get("planned_requests",int(self.rate.currentText())*60)} · achieved {rate:.2f} req/s · p50 {fmt(latency.get("p50"))} ms · p95 {fmt(latency.get("p95"))} ms · errors {sum(v for k,v in s.get("categories",{}).items() if k!="OK")}')
        import json
        self.details.setPlainText(('Private ZIP: '+s.get('bundle_path','—')+'\nReport: '+s.get('obd_report_path','—')+'\n'+json.dumps({k:s[k] for k in ('session_id','pretest','categories','latency_ms','export_error') if k in s},indent=2)) if s else 'No run started. Preflight is separate from the fixed 60-second measurement.')
        self.folder.setEnabled(bool(s.get('bundle_path')));self.report.setEnabled(bool(s.get('obd_report_path')));self.retry.setVisible(bool(s.get('retry_export')))
        if active:
            for control in (w.source,w.port,w.baud,w.scenario,w.rate,w.refresh_port_button):control.setEnabled(False)
    def open_report(self):
        if self.snapshot.get('obd_report_path'):QDesktopServices.openUrl(QUrl.fromLocalFile(self.snapshot['obd_report_path']))
    def open_folder(self):
        if self.snapshot.get('bundle_path'):QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(self.snapshot['bundle_path']).parent)))
