"""Private offline phase editor. Background analysis never owns an OBD worker."""
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from PySide6.QtCore import Qt,QTimer
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QLabel,QComboBox,QLineEdit,QSpinBox,
    QPushButton,QCheckBox,QFileDialog,QTabWidget,QTextEdit,QTableWidget,QTableWidgetItem,QWidget)
from PySide6.QtCharts import QChart,QChartView,QScatterSeries,QCategoryAxis,QValueAxis,QLineSeries
from PySide6.QtGui import QPen,QColor
from mokka_ecu_lab.analysis.phases import (load_phase_data,annotation,compare_phases,PHASES,LIMITS,
    save_annotations,load_annotations,export_phase_report)
from .components import FlowLayout,caption,scroll_page
from .theme import stylesheet,style_chart,style_table


class PhaseDialog(QDialog):
    def __init__(self,path,parent=None):
        super().__init__(parent); self.path=Path(path); self.data=None; self.report=None; self.previous=None
        self.setWindowTitle('Private offline Sport / Normal comparison'); self.resize(1100,800); self.setStyleSheet(stylesheet())
        self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='offline-phase-analysis'); self.future=None
        outer=QVBoxLayout(self); outer.setContentsMargins(0,0,0,0)
        content=QWidget(); self.scroll=scroll_page(content); outer.addWidget(self.scroll)
        layout=QVBoxLayout(content); layout.addWidget(caption(LIMITS))
        self.status=caption('Loading checksum-verified evidence in the background; no transport'); layout.addWidget(self.status)
        self.source=QComboBox(); self.source.currentIndexChanged.connect(self.select_source); layout.addWidget(self.source)
        row=FlowLayout(); self.phase=QComboBox(); self.phase.addItems(PHASES); self.phase.setCurrentText('Sport on')
        self.timestamp=QLineEdit(); self.timestamp.setPlaceholderText('User anchor ISO UTC, e.g. 2000-01-01T00:05:00+00:00'); self.timestamp.setMinimumWidth(280)
        self.uncertainty=QSpinBox(); self.uncertainty.setRange(0,3600); self.uncertainty.setValue(120); self.uncertainty.setSuffix(' s uncertainty ±')
        for w in (self.phase,self.timestamp,self.uncertainty): row.addWidget(w)
        layout.addLayout(row)
        self.note=QLineEdit(); self.note.setMaxLength(512); self.note.setPlaceholderText('Private user memory / reason for approximate anchor'); layout.addWidget(self.note)
        self.consent=QCheckBox('Approximate user report · Sport state is not ECU-confirmed'); layout.addWidget(self.consent)
        self.timestamp.textChanged.connect(self.invalidate_report); self.phase.currentIndexChanged.connect(self.invalidate_report)
        self.uncertainty.valueChanged.connect(self.invalidate_report); self.note.textChanged.connect(self.invalidate_report)
        row=FlowLayout()
        self.compare_button=QPushButton('Compare before / after'); self.compare_button.clicked.connect(self.compare)
        self.save_button=QPushButton('Save private annotation…'); self.save_button.clicked.connect(self.save_annotation)
        self.open_button=QPushButton('Open / edit private annotation…'); self.open_button.clicked.connect(self.open_annotation)
        self.export_button=QPushButton('Export private comparison HTML / JSON…'); self.export_button.clicked.connect(self.export)
        for w in (self.compare_button,self.save_button,self.open_button,self.export_button): row.addWidget(w)
        layout.addLayout(row); self.export_button.setEnabled(False)
        self.tabs=QTabWidget(); layout.addWidget(self.tabs,1)
        self.summary=QTableWidget(0,10); self.summary.setHorizontalHeaderLabels(['Field','Before n','After n','Before max','After max','Before median','After median','Before p95','After p95','MAP capped % before / after'])
        self.summary.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers); style_table(self.summary); self.tabs.addTab(self.summary,'Statistics')
        self.details=QTextEdit(); self.details.setReadOnly(True); self.tabs.addTab(self.details,'Overlap, context ages & limits')
        self.charts=QTabWidget(); self.tabs.addTab(self.charts,'UTC measured-point plots')
        self.timer=QTimer(self); self.timer.timeout.connect(self.receive); self.timer.start(50)
        self.enqueue(load_phase_data,self.path,kind='load')

    def enqueue(self,fn,*args,kind):
        self.kind=kind; self.future=self.pool.submit(fn,*args)
        self.export_button.setEnabled(False)
        for b in (self.compare_button,self.save_button,self.open_button): b.setEnabled(False)
        for w in (self.source,self.phase,self.timestamp,self.uncertainty,self.note,self.consent): w.setEnabled(False)

    def invalidate_report(self,*args):
        if not self.report: return
        self.report=None; self.export_button.setEnabled(False)
        self.summary.setRowCount(0); self.details.clear()
        while self.charts.count():
            widget=self.charts.widget(0); self.charts.removeTab(0); widget.deleteLater()
        self.status.setText('User annotation changed; recompute the comparison before exporting')

    def receive(self):
        if self.future is None or not self.future.done(): return
        future=self.future; self.future=None
        try:
            value=future.result()
            if self.kind=='load':
                self.data=value; self.source.blockSignals(True)
                for i,g in enumerate(value['groups']): self.source.addItem(f"{g['ecu']} · {g['mode']} · {g['source_kind']}",i)
                self.source.blockSignals(False); self.select_source()
                self.status.setText('All bundle checksums verified. Enter / edit the approximate Sport on anchor; original files remain unchanged.')
            else: self.report=value; self.show_report()
        except Exception as exc: self.status.setText(str(exc))
        for b in (self.compare_button,self.save_button,self.open_button): b.setEnabled(bool(self.data and self.data['groups']))
        for w in (self.source,self.phase,self.timestamp,self.uncertainty,self.note,self.consent): w.setEnabled(bool(self.data and self.data['groups']))

    def select_source(self,*args):
        self.report=None; self.export_button.setEnabled(False); self.previous=None; self.consent.setChecked(False)
        self.summary.setRowCount(0); self.details.clear()
        while self.charts.count():
            widget=self.charts.widget(0); self.charts.removeTab(0); widget.deleteLater()
        if not self.data or self.source.currentData() is None: return
        g=self.data['groups'][self.source.currentData()]
        candidates=[r['timestamp'] for samples in g['fields'].values() for r in samples]
        self.timestamp.setText(min(candidates) if candidates else '')
        self.note.clear()

    def current_annotation(self):
        if not self.consent.isChecked(): raise ValueError('Confirm USER_REPORTED provenance before saving / comparing')
        group=self.data['groups'][self.source.currentData()]
        return annotation(self.phase.currentText(),self.timestamp.text().strip(),self.uncertainty.value(),
            ecu=group['ecu'],mode=group['mode'],source_kind=group['source_kind'],evidence_id=self.data['evidence_id'],
            note=self.note.text(),previous=self.previous)

    def compare(self):
        try:
            anchor=self.current_annotation(); self.status.setText('Comparing measured points and bounded asynchronous context in background…')
            self.enqueue(compare_phases,self.data,self.source.currentData(),anchor,kind='compare')
        except Exception as exc: self.status.setText(str(exc))

    def show_report(self):
        report=self.report; self.summary.setRowCount(len(report['summary']))
        for i,row in enumerate(report['summary']):
            b,a=row['before'],row['after']; sat='—'
            if row['sensor_id']=='map': sat=' / '.join(f"{100*p:.1f}%" if p is not None else '—' for p in (b['saturation_fraction'],a['saturation_fraction']))
            for j,v in enumerate([row['sensor_id']+' ('+row['unit']+')',b['samples'],a['samples'],b['maximum'],a['maximum'],b['median'],a['median'],b['p95'],a['p95'],sat]):
                self.summary.setItem(i,j,QTableWidgetItem(f'{v:.6g}' if isinstance(v,float) else str(v) if v is not None else '—'))
        self.summary.resizeColumnsToContents()
        self.details.setPlainText(json.dumps(dict(anchor=report['anchor'],matched=report['matched'],
            summary=report['summary'],limitations=report['limitations']),ensure_ascii=False,indent=2))
        while self.charts.count():
            widget=self.charts.widget(0); self.charts.removeTab(0); widget.deleteLater()
        for sensor,points in report['series'].items():
            chart=QChart(); series=QScatterSeries(); series.setMarkerSize(5)
            for p in points: series.append(p['epoch']*1000,p['value'])
            # QDateTimeAxis formats generated ticks in the Windows local zone,
            # even with UTC range endpoints. Explicit UTC categories preserve
            # the actual epoch coordinates without changing the OS time zone.
            chart.addSeries(series); x=QCategoryAxis(); x.setLabelsPosition(QCategoryAxis.AxisLabelsPosition.AxisLabelsPositionOnValue)
            x.setTitleText('Measured UTC instants; no interpolation')
            unit=next(r['unit'] for r in report['summary'] if r['sensor_id']==sensor)
            y=QValueAxis(); y.setTitleText(sensor+' ('+unit+')'); chart.addAxis(x,Qt.AlignmentFlag.AlignBottom); chart.addAxis(y,Qt.AlignmentFlag.AlignLeft)
            series.attachAxis(x); series.attachAxis(y)
            epochs=[p['epoch'] for p in points]; values=[p['value'] for p in points]
            if epochs:
                low,high=min(epochs),max(epochs)+1
                x.setStartValue(low*1000-1)
                for i in range(5):
                    epoch=low+(high-low)*i/4
                    x.append(datetime.fromtimestamp(epoch,timezone.utc).strftime('%H:%M:%S.%f')[:-3]+' UTC',epoch*1000)
                padding=max(1,(high-low)*.12)
                x.setRange((low-padding)*1000,(high+padding)*1000)
            if values: y.setRange(min(values)-1,max(values)+1)
            for epoch,name in [(sum(report['uncertainty_band_seconds'])/2,'USER_REPORTED anchor'),
                               (report['uncertainty_band_seconds'][0],'Uncertainty start'),
                               (report['uncertainty_band_seconds'][1],'Uncertainty end')]:
                if epochs and min(epochs)<=epoch<=max(epochs):
                    line=QLineSeries(); line.setName(name); line.append(epoch*1000,min(values)-1); line.append(epoch*1000,max(values)+1)
                    pen=QPen(QColor('#d6a54a')); pen.setStyle(Qt.PenStyle.DashLine); line.setPen(pen)
                    chart.addSeries(line); line.attachAxis(x); line.attachAxis(y)
            chart.setTitle(sensor+' · actual asynchronously sampled points'); chart.legend().hide(); style_chart(chart)
            self.charts.addTab(QChartView(chart),sensor)
        self.export_button.setEnabled(True)
        self.status.setText('OBSERVATIONAL — NOT CAUSAL · uncertainty band excluded · '+str(sum(m['valid_overlap_bins'] for m in report['matched']))+' matched bins; no turbo response conclusion')

    def save_annotation(self):
        try:
            item=self.current_annotation()
            path,_=QFileDialog.getSaveFileName(self,'Fresh private annotation sidecar',str(self.path.parent/'phase-annotation.json'),'JSON (*.json)')
            if path: save_annotations([item],path,[self.path]); self.status.setText('Private annotation saved: '+path)
        except Exception as exc: self.status.setText(str(exc))

    def open_annotation(self):
        path,_=QFileDialog.getOpenFileName(self,'Private annotation to edit (save edits to a fresh sidecar)',str(self.path.parent),'JSON (*.json)')
        if not path: return
        try:
            items=load_annotations(path)
            item=next(i for i in items if i.get('evidence_id')==self.data['evidence_id'])
            index=next(i for i,g in enumerate(self.data['groups']) if all(g[k]==item[k] for k in ('ecu','mode','source_kind')))
            self.source.setCurrentIndex(index); self.previous=item
            self.phase.setCurrentText(item['phase']); self.timestamp.setText(item['timestamp']); self.uncertainty.setValue(int(item['uncertainty_seconds'])); self.note.setText(item['note']); self.consent.setChecked(False)
            self.status.setText('Loaded private user annotation. Edits keep previous timestamp; save to a fresh sidecar.')
        except Exception as exc: self.status.setText('Annotation not applicable: '+str(exc))

    def export(self):
        if not self.report: return
        path,_=QFileDialog.getSaveFileName(self,'Fresh private comparison output',str(self.path.parent/'phase-comparison.html'),'HTML (*.html)')
        if not path: return
        try: paths=export_phase_report(self.report,path,[self.path]); self.status.setText('Private files saved: '+' · '.join(map(str,paths)))
        except Exception as exc: self.status.setText(str(exc))

    def closeEvent(self,event):
        self.timer.stop(); self.pool.shutdown(wait=False,cancel_futures=True); event.accept()
