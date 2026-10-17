"""Private inventory and passive performance UI; never submits worker commands."""
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QDialog,QVBoxLayout,QLabel,QComboBox,QTabWidget,QTextEdit,QPushButton,QFileDialog,QWidget
from .components import caption
from mokka_ecu_lab.analysis.obd import analyze_obd,export_obd_report,LIMITATIONS


class ObdDialog(QDialog):
    def __init__(self,paths,parent=None):
        super().__init__(parent);self.paths=[Path(p) for p in paths];self.report=None
        self.setWindowTitle('Private ECU inventory / passive OBD performance');self.resize(1100,740)
        layout=QVBoxLayout(self);layout.addWidget(caption(LIMITATIONS))
        self.status=QLabel('Checking original bundle checksums offline…');self.status.setWordWrap(True);layout.addWidget(self.status)
        self.groups=QComboBox();self.groups.setAccessibleName('Separate recorded ECU/source inventory');layout.addWidget(self.groups)
        self.tabs=QTabWidget();self.inventory_view=QTextEdit();self.performance_view=QTextEdit()
        for widget,title in ((self.inventory_view,'Inventory / provenance'),(self.performance_view,'Passive performance / limits')):
            widget.setReadOnly(True);self.tabs.addTab(widget,title)
        explorer=QWidget();explorer_layout=QVBoxLayout(explorer)
        explorer_layout.addWidget(caption('Offline PID Explorer · each gate is separate evidence, never a health rating. No requests are sent.'))
        self.pid_selector=QComboBox();self.pid_selector.setAccessibleName('Recorded PID research evidence');explorer_layout.addWidget(self.pid_selector)
        self.evidence_view=QTextEdit();self.evidence_view.setReadOnly(True);explorer_layout.addWidget(self.evidence_view,1)
        self.tabs.addTab(explorer,'PID Explorer / research status');self.pid_selector.currentIndexChanged.connect(self.render_evidence)
        layout.addWidget(self.tabs,1)
        self.export_button=QPushButton('Export fresh private HTML + JSON');self.export_button.setEnabled(False);self.export_button.clicked.connect(self.export);layout.addWidget(self.export_button)
        self.groups.currentIndexChanged.connect(self.render)
        self.executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='offline-obd')
        self.future=self.executor.submit(analyze_obd,self.paths);self.timer=QTimer(self);self.timer.timeout.connect(self.poll);self.timer.start(100)
    def poll(self):
        if not self.future.done():return
        self.timer.stop()
        try:
            self.report=self.future.result();self.groups.blockSignals(True)
            for i,session in enumerate(self.report['sessions']):
                if not session['inventory']:self.groups.addItem(f'Bundle {i+1} · no verified ECU / preflight outcome',(i,None))
                for j,g in enumerate(session['inventory']):self.groups.addItem(f'Bundle {i+1} · {g["ecu"]} · {g["mode"]} · {g["source_kind"]}',(i,j))
            self.groups.blockSignals(False);self.render();self.export_button.setEnabled(True)
            self.status.setText('Checksum-verified offline report. Compare source groups separately; opening sent no requests.')
        except Exception as exc:self.status.setText(str(exc))
    def render(self,*_):
        if self.report is None:return
        selected=self.groups.currentData()
        if selected is None:return
        i,j=selected;session=self.report['sessions'][i]
        if j is None:
            self.inventory_view.setPlainText('No current ECU inventory. Port-open/preflight failure is not ECU overload.\n'+json.dumps(session.get('benchmark'),indent=2));self.performance_view.setPlainText(json.dumps(self.report.get('benchmark_comparisons',[]),indent=2));self.pid_selector.clear();self.evidence_view.setPlainText('No recorded ECU evidence. Unknown is not a healthy state.');return
        g=session['inventory'][j]
        lines=[f'Declared {g["declared_count"]} non-bitmap identifiers · outside legacy scope {g["outside_legacy_scope_count"]} · implemented {g["implemented_declared_count"]}',
            'Bitmap coverage '+g['bitmap_coverage']+' · '+g['inventory_scope_note'],
            'Support is not observation. Decoder tests do not establish vehicle calibration. No unknown identifier is probed.']
        for r in g['rows']:
            if r['advertised_support']=='SUPPORTED' or r['response_observed']:
                lines.append(f'{r["request"]} · {r["name"]}\n'+ '; '.join(r['facts'])+f' · valid numeric replies {r["valid_numeric_responses"]}\n'+r['reason'])
        lines.append('Original ordered bitmap ledger:\n'+json.dumps(g['bitmap_ledger'],indent=2))
        if self.report.get('inventory_comparisons'):lines.append('Separate address/source inventory comparisons:\n'+json.dumps(self.report['inventory_comparisons'],indent=2))
        self.inventory_view.setPlainText('\n\n'.join(lines))
        previous=self.pid_selector.currentData();self.pid_selector.blockSignals(True);self.pid_selector.clear()
        for row in g['rows']:
            if row['advertised_support']=='SUPPORTED' or row['response_observed']:self.pid_selector.addItem(row['request']+' · '+row['name'],row['pid'])
        selected_pid=self.pid_selector.findData(previous)
        if selected_pid>=0:self.pid_selector.setCurrentIndex(selected_pid)
        self.pid_selector.blockSignals(False);self.render_evidence()
        perf=[p for p in session['performance'] if (p['mode'],p['source_kind'],p['context_id'])==(g['mode'],g['source_kind'],g['context_id'])]
        rate_lines=['Throughput denominators remain separate:', 'COUNT_OVER_SEND_SPAN = N sends / (last send − first send).',
            'INTERVALS_OVER_SEND_SPAN = (N − 1) intervals / the same send span.']
        for p in perf:rate_lines.append(f'Send-span count {p["actual_transmitted_rate_hz"]} req/s; intervals {p["interval_rate_hz"]} req/s.')
        if b:=session.get('benchmark'):rate_lines.append(f'COUNT_OVER_MEASUREMENT_WINDOW = {b["sent_requests"]} measurement sends / {b["measurement_duration_seconds"]} s = {b["actual_sustained_rate"]} req/s; preflight excluded.')
        self.performance_view.setPlainText('\n'.join(rate_lines)+'\n\n'+json.dumps(dict(performance=perf,benchmark=session.get('benchmark'),field_quality=session.get('field_quality',[]),separate_benchmark_comparisons=self.report.get('benchmark_comparisons',[])),indent=2)+'\n\nApplication/adapter timings and policy slack are not ECU capacity. No higher-than-four request-rate validation.')
    def render_evidence(self,*_):
        selected=self.groups.currentData();pid=self.pid_selector.currentData()
        if self.report is None or selected is None or pid is None:return
        i,j=selected
        if j is None:return
        g=self.report['sessions'][i]['inventory'][j];row=next(r for r in g['rows'] if r['pid']==pid);e=row['evidence_progression']
        lines=[row['request']+' · '+row['name'],f'ECU {g["ecu"]} · {g["mode"]} · {g["source_kind"]}',
            'ADVERTISED: '+e['advertised']['state'],f'RECORDED POSITIVE / FRAMED: {e["framed"]["samples"]} replies',
            f'LENGTH VERIFIED: {e["length_verified"]["samples"]} replies; documented data bytes: {e["length_verified"]["expected_data_bytes"]}',
            f'LAYOUT VERIFIED: {e["layout_verified"]["samples"]} replies',f'NUMERIC: {e["numeric"]["samples"]} exact-layout replies with available fields',
            'PHYSICAL UNVERIFIED: software arithmetic does not calibrate this vehicle.',
            'Sampling coverage: '+e['sampling']['pattern']+'\n'+str(e['sampling']['role_counts'])+'\n'+e['sampling']['interpretation'],
            f'Observed data lengths: {row["positive_payload_lengths"]}',row['reason'],
            'Original evidence references (bounded preview):\n'+json.dumps(e,indent=2),
            'No soot, ash, regeneration, pressure or health inference is supplied for an unknown layout.']
        self.evidence_view.setPlainText('\n\n'.join(lines))
    def export(self):
        path,_=QFileDialog.getSaveFileName(self,'Fresh private OBD report','private-obd-report.html','HTML (*.html)')
        if path:
            try:self.status.setText('Saved private report: '+str(export_obd_report(self.report,path,self.paths)))
            except Exception as exc:self.status.setText(str(exc))
    def closeEvent(self,event):
        self.timer.stop();self.executor.shutdown(wait=False,cancel_futures=True);event.accept()
