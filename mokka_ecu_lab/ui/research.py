"""Offline catalog and evidence UI, with no worker/transport reference."""
import json
from html import escape
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QComboBox,
    QTabWidget,QTextEdit,QTableWidget,QTableWidgetItem,QHeaderView,QFileDialog,QMessageBox,QSplitter,QCheckBox,QLineEdit)
from PySide6.QtCharts import QChart,QChartView,QScatterSeries
from mokka_ecu_lab.research.catalog import KnowledgeBase,STATUSES,new_catalog
from mokka_ecu_lab.research.evidence import analyze_bundles,save_analysis
from mokka_ecu_lab.research.report import load_analysis,export_private_report,RECOMMENDATIONS
from mokka_ecu_lab.research.summary import summary_lines
from mokka_ecu_lab.sensors import load_registry
from mokka_ecu_lab.sensors.diesel import STANDARD_DIESEL
from .theme import style_table,style_chart
from .components import page_heading,caption,FlowLayout


def grid(headers):
    widget=QTableWidget(0,len(headers)); widget.setHorizontalHeaderLabels(headers)
    widget.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    widget.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    widget.horizontalHeader().setStretchLastSection(True)
    style_table(widget)
    return widget


def fill(widget,rows):
    widget.setRowCount(len(rows))
    for i,row in enumerate(rows):
        for j,value in enumerate(row): widget.setItem(i,j,QTableWidgetItem(str(value)))


class ResearchView(QWidget):
    def __init__(self,root,hypotheses,parent=None):
        super().__init__(parent); self.root=root; self.report=None
        self.catalog=KnowledgeBase(root/'research'/'catalog.json')
        layout=QVBoxLayout(self); layout.setContentsMargins(0,4,0,0)
        page_heading(layout,'Research workspace','Local evidence, documented definitions and independent verification. Importing or browsing sends no ECU commands.')
        self.tabs=QTabWidget(); layout.addWidget(self.tabs)
        catalog_tab=QWidget(); c=QVBoxLayout(catalog_tab)
        self.profile=QLabel(); self.profile.setWordWrap(True); c.addWidget(self.profile)
        self.definitions=grid(['Request','Definition status','Vehicle observation','Independent verification','Length','Source'])
        c.addWidget(self.definitions,1)
        self.details=QTextEdit(); self.details.setReadOnly(True); self.details.setMinimumHeight(120); self.details.setMaximumHeight(200); c.addWidget(self.details)
        self.definitions.itemSelectionChanged.connect(self.show_definition)
        self.tabs.addTab(catalog_tab,'Knowledge & provenance')
        evidence_tab=QWidget(); e=QVBoxLayout(evidence_tab)
        actions=FlowLayout()
        self.import_button=QPushButton('Import local Research Bundles…'); self.import_button.clicked.connect(self.import_bundles); actions.addWidget(self.import_button)
        self.import_analysis_button=QPushButton('Open saved analysis…'); self.import_analysis_button.clicked.connect(self.open_analysis); actions.addWidget(self.import_analysis_button)
        self.save_button=QPushButton('Export private research report…'); self.save_button.clicked.connect(self.save_analysis); self.save_button.setEnabled(False); actions.addWidget(self.save_button)
        e.addLayout(actions)
        self.detailed_report=QCheckBox('Include private raw preview and timestamps in HTML (explicit detailed mode)'); e.addWidget(self.detailed_report)
        privacy=QLabel('Before sharing: review both files. JSON preserves full private evidence; compact HTML omits identity fields and raw timelines. HTML covers the selected source group. Existing files are preserved.'); privacy.setWordWrap(True)
        self.privacy_details=QCheckBox('Report privacy details'); self.privacy_details.toggled.connect(privacy.setVisible); e.addWidget(self.privacy_details); e.addWidget(privacy); privacy.hide()
        self.group=QComboBox(); self.group.currentIndexChanged.connect(self.show_group); e.addWidget(self.group)
        self.group.setAccessibleName('Recorded session, ECU and source group')
        self.overview=caption('No evidence selected · import a local bundle or open a saved analysis.'); e.addWidget(self.overview)
        self.export_result=caption(''); e.addWidget(self.export_result)
        self.evidence_tabs=QTabWidget(); e.addWidget(self.evidence_tabs,1)
        compatibility=QWidget(); compat=QVBoxLayout(compatibility)
        unknown=QLabel('What does UNKNOWN mean? Raw support needs the original ordered bitmap chain. A recorded snapshot is separate evidence. Positive replies prove observation, not decoder certification or component health.'); unknown.setWordWrap(True); compat.addWidget(unknown)
        filters=QHBoxLayout(); self.matrix_search=QLineEdit(); self.matrix_search.setPlaceholderText('Search PID or sensor name')
        self.matrix_search.setAccessibleName('Search compatibility by PID or sensor name')
        self.matrix_filter=QComboBox(); self.matrix_filter.addItems(['All evidence','Recorded supported','Recorded unsupported','Observed replies','Unverified layouts'])
        self.matrix_technical=QCheckBox('Technical columns')
        filters.addWidget(self.matrix_search,1); filters.addWidget(self.matrix_filter); filters.addWidget(self.matrix_technical); compat.addLayout(filters)
        self.matrix=grid(['PID','Recorded support','Raw support','Samples','Frame validity (valid / invalid)','Negative','Lengths: count','Decoder / layout','Layout errors','Definition','Observed source','Notes'])
        self.matrix.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        for i,width in enumerate((70,175,145,100,220,85,140,235,100,195,180,400)): self.matrix.setColumnWidth(i,width)
        for col in (4,5,6,8,9,11): self.matrix.setColumnHidden(col,True)
        self.matrix_technical.toggled.connect(lambda show: [self.matrix.setColumnHidden(c,not show) for c in (4,5,6,8,9,11)])
        self.matrix_search.textChanged.connect(self.filter_matrix); self.matrix_filter.currentIndexChanged.connect(self.filter_matrix)
        self.matrix.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.matrix.itemSelectionChanged.connect(self.show_matrix_detail)
        split=QSplitter(Qt.Orientation.Vertical); split.addWidget(self.matrix)
        self.matrix.setMinimumHeight(170)
        self.matrix_detail=QTextEdit(); self.matrix_detail.setReadOnly(True); self.matrix_detail.setMinimumHeight(130); split.addWidget(self.matrix_detail); split.setSizes([320,140]); compat.addWidget(split,1)
        self.evidence_tabs.addTab(compatibility,'Compatibility')
        self.samples=grid(['PID','Acquired UTC','Data bytes','Layout','RPM / age','MAF / age','Speed / age'])
        self.evidence_tabs.addTab(self.samples,'Byte samples & context')
        chart_tab=QWidget(); chart_layout=QVBoxLayout(chart_tab); chart_row=QHBoxLayout()
        self.byte=QComboBox(); self.byte.addItems([f'017A byte {chr(65+i)}' for i in range(7)]); self.byte.currentIndexChanged.connect(self.show_chart); chart_row.addWidget(self.byte)
        chart_layout.addLayout(chart_row); self.chart=QChart(); self.chart.setTheme(QChart.ChartTheme.ChartThemeDark)
        chart_layout.addWidget(caption('017A · RAW ONLY for six-byte responses. Numeric meaning is unverified. Bytes do not establish pressure, soot, health or regeneration.'))
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
        rows=g['matrix']; observed=sum(r['positive_response_count']>0 for r in rows)
        documented=sum(r['definition_state']=='STANDARD_DOCUMENTED' for r in rows)
        unverified=sum('UNVERIFIED' in r['layout_state'] for r in rows)
        integrity='Original bundle checksums verified' if session.get('checksum_verified') and self.report.get('analysis_origin')!='SAVED_ANALYSIS_NOT_REVALIDATED' else 'Saved analysis · original bundle not revalidated'
        self.overview.setText(f"{g['ecu']} · {g['source_kind']} · {session['transactions']} session transactions · {observed} observed PIDs · {documented} documented definitions · {unverified} unverified layouts\n{integrity} (file integrity, not ECU verification) · {len(session['missing_evidence'])+len(g['missing_evidence'])} evidence gaps")
        self.scr_detail.setHtml(scr_html(g['scr_summary']))
        self.matrix_rows=g['matrix']
        self.matrix.setSortingEnabled(False)
        fill(self.matrix,[[e['request'],e['recorded_discovery_support'],e['raw_bitmap_support'],e['positive_response_count'],
            f"{e['frame_validity']} · {e['valid_framing']} / {e['invalid_framing']}",e['negative_responses'],
            e['lengths'],layout_label(e['layout_state']),e['layout_mismatches'],e['definition_state'],e['observation_state'].replace('_',' '),
            e['evidence_explanation'][:160]] for e in g['matrix']])
        for row,e in enumerate(g['matrix']):
            self.matrix.item(row,0).setData(Qt.ItemDataRole.UserRole,e)
            for column,key in ((3,'positive_response_count'),(5,'negative_responses'),(8,'layout_mismatches')):
                number=QTableWidgetItem(); number.setData(Qt.ItemDataRole.DisplayRole,e[key])
                self.matrix.setItem(row,column,number)
            self.matrix.item(row,0).setToolTip(self.sensor_name(e['pid']))
            self.matrix.item(row,7).setToolTip(e['layout_state'])
            self.matrix.item(row,11).setToolTip(e['evidence_explanation'])
        self.matrix.setSortingEnabled(True); self.filter_matrix()
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
        item=self.matrix.item(row,0)
        if item:
            evidence=item.data(Qt.ItemDataRole.UserRole)
            if evidence:
                self.matrix_detail.setPlainText(self.sensor_name(evidence['pid'])+' · '+evidence['request']+'\n\n'+evidence['evidence_explanation']+'\n\nExact evidence metadata:\n'+json.dumps(evidence,ensure_ascii=False,indent=2))

    @staticmethod
    def sensor_name(pid):
        number=int(pid,16); definition=STANDARD_DIESEL.get(number) or load_registry().get(number)
        return definition.name if definition else 'Support bitmap / recorded parameter'

    def filter_matrix(self,*args):
        query=self.matrix_search.text().lower().strip(); selected=self.matrix_filter.currentIndex()
        for row in range(self.matrix.rowCount()):
            item=self.matrix.item(row,0); evidence=item.data(Qt.ItemDataRole.UserRole) if item else None
            if not evidence: continue
            allowed=(selected==0 or selected==1 and evidence['recorded_discovery_support']=='SUPPORTED'
                or selected==2 and evidence['recorded_discovery_support']=='UNSUPPORTED'
                or selected==3 and evidence['positive_response_count']>0
                or selected==4 and 'UNVERIFIED' in evidence['layout_state'])
            match=query in (evidence['request']+' '+self.sensor_name(evidence['pid'])).lower()
            self.matrix.setRowHidden(row,not (allowed and match))

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
        self.chart.setTitle('Recorded 017A byte vs elapsed seconds · no formula or correlation proof' if len(samples)>1 else 'Insufficient samples for a trend · raw observations only')
        if self.chart.axes(Qt.Orientation.Horizontal): self.chart.axes(Qt.Orientation.Horizontal)[0].setTitleText('Elapsed seconds · selected ECU/source')
        if self.chart.axes(Qt.Orientation.Vertical):
            self.chart.axes(Qt.Orientation.Vertical)[0].setTitleText('Raw byte (0–255)'); self.chart.axes(Qt.Orientation.Vertical)[0].setRange(0,255)
        style_chart(self.chart)

    def save_analysis(self):
        if not self.report: return
        path,_=QFileDialog.getSaveFileName(self,'Export private research report (HTML + full JSON, or JSON only)',str(self.root/'private-research-report.html'),'HTML (*.html);;JSON (*.json)')
        if path:
            try:
                selected=self.group.currentData()
                selection=next(((si,gi) for si,s in enumerate(self.report['sessions']) for gi,g in enumerate(s['groups']) if s is selected[0] and g is selected[1]),None) if selected else None
                export_private_report(self.report,path,self.input_paths,selection,self.detailed_report.isChecked())
                self.export_result.setText(f'Private report saved locally: {path} · review HTML and full JSON before sharing.')
            except Exception as exc: QMessageBox.warning(self,'Save analysis',str(exc))


def scr_html(summary):
    """Present existing summary evidence in distinct sections; no new decoding."""
    def text(value): return escape(str(value))
    def table(rows):
        return '<table width="100%" cellspacing="0" cellpadding="8">'+''.join('<tr>'+''.join('<td>'+text(v)+'</td>' for v in row)+'</tr>' for row in rows)+'</table>'
    current=summary['current']; adblue=summary['adblue']; nox=summary['nox']
    result=['<style>h2 {color:#77d5c6;font-size:20px} h3 {color:#c7d6e2;font-size:15px} td {border-bottom:1px solid #30404f} p {color:#a4b3c2}</style>',
            '<h2>SCR / AdBlue</h2><p>Independent vehicle verification: UNVERIFIED · recorded evidence only</p>',
            '<h3>Current inducement at the recorded timestamp</h3>', '<b>'+text(current['state'])+'</b>',
            '<p>'+text(current.get('timestamp') or current.get('unavailable_reason','No complete sample'))+'</p>',
            '<p>Inactive inducement does not mean that the SCR system is disabled.</p>']
    result.append('<h3>Current reasons</h3>')
    result.append(table([(r['reason'],'Set at recorded time' if r['set'] else 'Not set at recorded time') for r in current['reasons']]) if current['reasons'] else '<p>No documented current reason sample.</p>')
    result.append('<h3>Historical evidence — not current fault</h3><p>A past low AdBlue flag does not establish a current warning.</p>')
    result.append(table([(f"Block {b['block']}",', '.join(r['reason'] for r in b['reasons'] if r['set']) or 'No reason flags set',b['meaning']) for b in current['historical']]))
    result.append('<h3>Historical distance counters</h3>'+table([(c['name'],f"{c['value']:g} {c['unit']}",c['meaning']) for c in current['counters']]))
    result.append('<h3>AdBlue tank level</h3>')
    tank=adblue['tank_level']; warning=adblue['warning_time']
    result.append('<p>'+ (f"{tank['count']} observations · quantized range {tank['minimum']:.3f}–{tank['maximum']:.3f} %" if tank else 'No documented tank-level observation.')+'</p>')
    result.append('<h3>Warning engine-time counter</h3><p>'+ (f"{warning['minimum']:g}–{warning['maximum']:g} s · "+('Static in these observations' if adblue['warning_time_static'] else 'Recorded counter evidence') if warning else 'No documented warning-time counter.')+'</p>')
    result.append('<p>'+text(adblue['interpretation'])+'</p><h3>NOx observations</h3><p>'+text(f"{nox['decoded_observations']} documented samples · {nox['availability']}")+'</p>')
    result.append(table([(name.replace('sae_83_','').replace('_',' ').title(),f"{stats['minimum']:g}–{stats['maximum']:g} {stats['unit']}",f"{stats['count']} samples") for name,stats in nox['fields'].items()]))
    result.extend('<p>'+text(line)+'</p>' for line in [nox['interpretation'],*current['semantic_warnings'],summary['limitations']])
    return ''.join(result)


def layout_label(state):
    return {'DOCUMENTED_LAYOUT':'Documented layout','UNVERIFIED_LAYOUT':'Decoder not verified',
            'NO_POSITIVE_RESPONSE':'No sample observed','BITMAP_VALID_UNANCHORED':'Bitmap · chain unavailable',
            'BITMAP_VALID_ANCHORED':'Bitmap · ordered chain valid'}.get(state,state.replace('_',' ').capitalize())
