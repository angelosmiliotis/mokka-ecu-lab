"""Offline catalog and evidence UI, with no worker/transport reference."""
import json
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QComboBox,
    QTabWidget,QTextEdit,QTableWidget,QTableWidgetItem,QHeaderView,QFileDialog,QMessageBox,QSplitter,QCheckBox)
from PySide6.QtCharts import QChart,QChartView,QScatterSeries
from mokka_ecu_lab.research.catalog import KnowledgeBase,STATUSES,new_catalog
from mokka_ecu_lab.research.evidence import analyze_bundles,save_analysis
from mokka_ecu_lab.research.report import load_analysis,export_private_report,RECOMMENDATIONS
from mokka_ecu_lab.research.summary import summary_lines


def grid(headers):
    widget=QTableWidget(0,len(headers)); widget.setHorizontalHeaderLabels(headers)
    widget.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    widget.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    widget.horizontalHeader().setStretchLastSection(True)
    return widget


def fill(widget,rows):
    widget.setRowCount(len(rows))
    for i,row in enumerate(rows):
        for j,value in enumerate(row): widget.setItem(i,j,QTableWidgetItem(str(value)))


class ResearchView(QWidget):
    def __init__(self,root,hypotheses,parent=None):
        super().__init__(parent); self.root=root; self.report=None
        self.catalog=KnowledgeBase(root/'research'/'catalog.json')
        layout=QVBoxLayout(self)
        label=QLabel('LOCAL / OFFLINE · documented definitions, observations and independent verification are separate. No automatic promotion.'); label.setWordWrap(True); layout.addWidget(label)
        self.tabs=QTabWidget(); layout.addWidget(self.tabs)
        catalog_tab=QWidget(); c=QVBoxLayout(catalog_tab)
        self.profile=QLabel(); self.profile.setWordWrap(True); c.addWidget(self.profile)
        self.definitions=grid(['Request','Definition status','Vehicle observation','Independent verification','Length','Source'])
        c.addWidget(self.definitions,1)
        self.details=QTextEdit(); self.details.setReadOnly(True); self.details.setMaximumHeight(200); c.addWidget(self.details)
        self.definitions.itemSelectionChanged.connect(self.show_definition)
        self.tabs.addTab(catalog_tab,'Knowledge & provenance')
        evidence_tab=QWidget(); e=QVBoxLayout(evidence_tab)
        actions=QHBoxLayout()
        self.import_button=QPushButton('Import local Research Bundles…'); self.import_button.clicked.connect(self.import_bundles); actions.addWidget(self.import_button)
        self.import_analysis_button=QPushButton('Open saved analysis…'); self.import_analysis_button.clicked.connect(self.open_analysis); actions.addWidget(self.import_analysis_button)
        self.save_button=QPushButton('Export private research report…'); self.save_button.clicked.connect(self.save_analysis); self.save_button.setEnabled(False); actions.addWidget(self.save_button)
        e.addLayout(actions)
        self.detailed_report=QCheckBox('Include private raw preview and timestamps in HTML (explicit detailed mode)'); e.addWidget(self.detailed_report)
        privacy=QLabel('Before sharing: review both files. JSON preserves full private evidence; compact HTML omits identity fields and raw timelines. HTML covers the selected source group. Existing files are preserved.'); privacy.setWordWrap(True); e.addWidget(privacy)
        self.group=QComboBox(); self.group.currentIndexChanged.connect(self.show_group); e.addWidget(self.group)
        self.evidence_tabs=QTabWidget(); e.addWidget(self.evidence_tabs,1)
        compatibility=QWidget(); compat=QVBoxLayout(compatibility)
        unknown=QLabel('What does UNKNOWN mean? Raw support needs the original ordered bitmap chain. A recorded snapshot is separate evidence. Positive replies prove observation, not decoder certification or component health.'); unknown.setWordWrap(True); compat.addWidget(unknown)
        self.matrix=grid(['PID','Recorded support (snapshot)','Raw bitmap support','Positive samples','Frame validity (valid / invalid)','Negative','Lengths: count','Layout state','Layout errors','Definition','Observation provenance','Notes'])
        self.matrix.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        for i,width in enumerate((75,190,150,115,220,85,140,245,100,195,215,400)): self.matrix.setColumnWidth(i,width)
        self.matrix.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.matrix.itemSelectionChanged.connect(self.show_matrix_detail)
        split=QSplitter(Qt.Orientation.Vertical); split.addWidget(self.matrix)
        self.matrix_detail=QTextEdit(); self.matrix_detail.setReadOnly(True); split.addWidget(self.matrix_detail); split.setSizes([320,140]); compat.addWidget(split,1)
        self.evidence_tabs.addTab(compatibility,'Compatibility')
        self.samples=grid(['PID','Acquired UTC','Data bytes','Layout','RPM / age','MAF / age','Speed / age'])
        self.evidence_tabs.addTab(self.samples,'Byte samples & context')
        chart_tab=QWidget(); chart_layout=QVBoxLayout(chart_tab); chart_row=QHBoxLayout()
        self.byte=QComboBox(); self.byte.addItems([f'017A byte {chr(65+i)}' for i in range(7)]); self.byte.currentIndexChanged.connect(self.show_chart); chart_row.addWidget(self.byte)
        chart_layout.addLayout(chart_row); self.chart=QChart(); self.chart.setTheme(QChart.ChartTheme.ChartThemeDark)
        self.chart_view=QChartView(self.chart); chart_layout.addWidget(self.chart_view)
        self.evidence_tabs.addTab(chart_tab,'017A byte time series')
        self.scr_detail=QTextEdit(); self.scr_detail.setReadOnly(True); self.evidence_tabs.addTab(self.scr_detail,'SCR / AdBlue summary')
        self.evidence_detail=QTextEdit(); self.evidence_detail.setReadOnly(True); self.evidence_tabs.addTab(self.evidence_detail,'Findings & requirements')
        checklist=QTextEdit(); checklist.setReadOnly(True); checklist.setPlainText('OFFLINE PREPARATION ONLY · no commands are sent\n\n'+'\n\n'.join(RECOMMENDATIONS)); self.evidence_tabs.addTab(checklist,'Next recording checklist')
        self.tabs.addTab(evidence_tab,'Offline evidence analyzer'); self.tabs.addTab(hypotheses,'EXPERIMENTAL hypotheses')
        self.refresh_catalog()

    def refresh_catalog(self):
        p=self.catalog.data['profile']
        self.profile.setText(f"Provisional {p['make']} {p['model']} {p['year']} · {p['engine_family']}\nECU: {p['ecu_family']} · HW: {p['hardware_identification']} · SW: {p['software_identification']} · calibration: {p['calibration_identification']}\nStates: "+' / '.join(STATUSES))
        # Published definitions always come from this release's code, never a
        # mutable old catalog or a vehicle profile supplied by an import.
        self.definition_rows=new_catalog()['standard_definitions']+new_catalog()['manufacturer_candidates']
        observed={pid for e in self.catalog.data['evidence'] if e['source_kind']=='ECU_READING' for pid in e['payload_lengths']}
        fill(self.definitions,[[d['request'],d['evidence_state'],'VEHICLE_OBSERVED' if d.get('pid') in observed else 'UNVERIFIED',
            'UNVERIFIED',d.get('length',d.get('exact_payload_length')),d.get('source_table','Existing registry; edition unspecified' if 'pid' in d else 'Reported OEM candidate')] for d in self.definition_rows])

    def show_definition(self):
        i=self.definitions.currentRow()
        if 0<=i<len(self.definition_rows): self.details.setPlainText(json.dumps(self.definition_rows[i],ensure_ascii=False,indent=2))

    def import_bundles(self):
        paths,_=QFileDialog.getOpenFileNames(self,'Analyze existing local Research Bundles',str(self.root),'ZIP (*.zip)')
        if paths:
            try: self.load_paths(paths)
            except Exception as exc: QMessageBox.warning(self,'Offline evidence',str(exc))

    def load_paths(self,paths):
        report=analyze_bundles(paths)
        self.catalog.record_evidence(report); self.input_paths=list(paths); self.set_report(report); self.refresh_catalog()

    def open_analysis(self):
        path,_=QFileDialog.getOpenFileName(self,'Open saved private analysis (original ZIP is not revalidated)',str(self.root),'JSON (*.json)')
        if path:
            try:
                report=load_analysis(path); self.input_paths=[path]; self.set_report(report)
            except Exception as exc: QMessageBox.warning(self,'Saved analysis',str(exc))

    def set_report(self,report):
        self.report=report
        self.group.blockSignals(True); self.group.clear()
        for index,session in enumerate(report['sessions'],1):
            for g in session['groups']:
                self.group.addItem(f"Session {index} · {g['ecu']} · {g['mode']} · {g['source_kind']}",(session,g))
        self.group.blockSignals(False); self.save_button.setEnabled(True); self.show_group()

    def show_group(self):
        data=self.group.currentData()
        if not data: return
        session,g=data
        self.scr_detail.setPlainText('\n\n'.join(summary_lines(g['scr_summary'])))
        self.matrix_rows=g['matrix']
        fill(self.matrix,[[e['request'],e['recorded_discovery_support'],e['raw_bitmap_support'],e['positive_response_count'],
            f"{e['frame_validity']} · {e['valid_framing']} / {e['invalid_framing']}",e['negative_responses'],
            e['lengths'],e['layout_state'],e['layout_mismatches'],e['definition_state'],e['observation_state'].replace('_',' '),
            e['evidence_explanation'][:160]] for e in g['matrix']])
        for row,e in enumerate(g['matrix']): self.matrix.item(row,11).setToolTip(e['evidence_explanation'])
        self.matrix.selectRow(0); self.show_matrix_detail()
        def context(sample,name):
            c=sample['context'][name]
            return 'UNAVAILABLE' if c['state']=='UNAVAILABLE' else f"{c['value']:g} {c['unit']} / {c['age_seconds']:.3f}s · cached"
        fill(self.samples,[[s['pid'],s['timestamp'],s['payload_hex'],s['layout_status'],context(s,'rpm'),context(s,'maf'),context(s,'speed')] for s in g['samples']])
        self.evidence_detail.setPlainText(json.dumps(dict(missing=session['missing_evidence']+g['missing_evidence'],
            contradictions=session['contradictions'],transaction_errors=session['transaction_errors'],
            verification_requirements=self.report['verification_requirements'],limitations=self.report['limitations'],
            recorded_decoder_versions=session['recorded_decoder_versions'],current_decoder=self.report['decoder_version'],
            preview_limit=g['preview_limit'],preview_truncated=g['preview_truncated'],matrix=g['matrix'],samples=g['samples']),ensure_ascii=False,indent=2))
        self.show_chart()

    def show_matrix_detail(self):
        row=self.matrix.currentRow()
        if hasattr(self,'matrix_rows') and 0<=row<len(self.matrix_rows):
            self.matrix_detail.setPlainText(json.dumps(self.matrix_rows[row],ensure_ascii=False,indent=2))

    def show_chart(self):
        if not hasattr(self,'chart'): return
        self.chart.removeAllSeries(); data=self.group.currentData()
        if not data: return
        samples=[s for s in data[1]['samples'] if s['pid']=='7A' and s['monotonic_ns'] is not None and len(s['bytes'])>self.byte.currentIndex()]
        series=QScatterSeries(); series.setName(self.byte.currentText()+' · raw 0–255'); series.setMarkerSize(6)
        if samples:
            anchor=samples[0]['monotonic_ns']
            for s in samples: series.append((s['monotonic_ns']-anchor)/1e9,s['bytes'][self.byte.currentIndex()])
        self.chart.addSeries(series); self.chart.createDefaultAxes()
        self.chart.setTitle('Recorded 017A byte vs elapsed seconds · no formula or correlation proof')

    def save_analysis(self):
        if not self.report: return
        path,_=QFileDialog.getSaveFileName(self,'Export private research report (HTML + full JSON, or JSON only)',str(self.root/'private-research-report.html'),'HTML (*.html);;JSON (*.json)')
        if path:
            try:
                selected=self.group.currentData()
                selection=next(((si,gi) for si,s in enumerate(self.report['sessions']) for gi,g in enumerate(s['groups']) if s is selected[0] and g is selected[1]),None) if selected else None
                export_private_report(self.report,path,self.input_paths,selection,self.detailed_report.isChecked())
            except Exception as exc: QMessageBox.warning(self,'Save analysis',str(exc))
