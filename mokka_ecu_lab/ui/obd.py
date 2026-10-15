"""Private inventory and passive performance UI; never submits worker commands."""
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QDialog,QVBoxLayout,QLabel,QComboBox,QTabWidget,QTextEdit,QPushButton,QFileDialog
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
                for j,g in enumerate(session['inventory']):self.groups.addItem(f'Bundle {i+1} · {g["ecu"]} · {g["mode"]} · {g["source_kind"]}',(i,j))
            self.groups.blockSignals(False);self.render();self.export_button.setEnabled(True)
            self.status.setText('Checksum-verified offline report. Compare source groups separately; opening sent no requests.')
        except Exception as exc:self.status.setText(str(exc))
    def render(self,*_):
        if self.report is None:return
        selected=self.groups.currentData()
        if selected is None:return
        i,j=selected;session=self.report['sessions'][i];g=session['inventory'][j]
        lines=[f'Declared {g["declared_count"]} non-bitmap identifiers · outside legacy scope {g["outside_legacy_scope_count"]} · implemented {g["implemented_declared_count"]}',
            'Support is not observation. Decoder tests do not establish vehicle calibration. No unknown identifier is probed.']
        for r in g['rows']:
            if r['advertised_support']=='SUPPORTED' or r['response_observed']:
                lines.append(f'{r["request"]} · {r["name"]}\n'+ '; '.join(r['facts'])+f' · valid numeric replies {r["valid_numeric_responses"]}\n'+r['reason'])
        lines.append('Original ordered bitmap ledger:\n'+json.dumps(g['bitmap_ledger'],indent=2))
        if self.report.get('inventory_comparisons'):lines.append('Separate address/source inventory comparisons:\n'+json.dumps(self.report['inventory_comparisons'],indent=2))
        self.inventory_view.setPlainText('\n\n'.join(lines))
        perf=[p for p in session['performance'] if (p['mode'],p['source_kind'],p['context_id'])==(g['mode'],g['source_kind'],g['context_id'])]
        self.performance_view.setPlainText(json.dumps(perf,indent=2)+'\n\nApplication/adapter timings and policy slack are not ECU capacity. No higher-than-four request-rate validation.')
    def export(self):
        path,_=QFileDialog.getSaveFileName(self,'Fresh private OBD report','private-obd-report.html','HTML (*.html)')
        if path:
            try:self.status.setText('Saved private report: '+str(export_obd_report(self.report,path,self.paths)))
            except Exception as exc:self.status.setText(str(exc))
    def closeEvent(self,event):
        self.timer.stop();self.executor.shutdown(wait=False,cancel_futures=True);event.accept()
