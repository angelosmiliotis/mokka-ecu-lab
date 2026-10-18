"""Offline evidence view; no worker commands or transport ownership."""
import json
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget,QVBoxLayout,QComboBox,QLineEdit,QFileDialog,QTreeWidget,QTreeWidgetItem,QTextEdit,QHeaderView,QInputDialog,QCheckBox
from .components import page_heading,caption,FlowLayout
from .local_jobs import LocalJobs
from mokka_ecu_lab.analysis.explorer import analyze_explorer,export_explorer,select_rows,FILTERS,LIMITS


class EvidenceExplorer(QWidget):
    def __init__(self,window):
        super().__init__();self.window=window;self.report=None;self.paths=[];self.scopes=[]
        layout=QVBoxLayout(self);page_heading(layout,'Sensor / PID Evidence Explorer','Import original Research Bundles. Evidence replay is entirely offline; changing a filter sends no requests.')
        limits=caption('PID identifiers, decoded fields and physical sensors are different. Counts apply only to the selected original source; physical calibration and hardware identity remain UNVERIFIED.');limits.setToolTip(LIMITS);layout.addWidget(limits)
        actions=FlowLayout();actions.addWidget(window.button('Import private bundles…',self.import_bundles))
        self.export_button=window.button('Export private CSV + JSON…',self.export);self.export_button.setEnabled(False);actions.addWidget(self.export_button);layout.addLayout(actions)
        actions.addWidget(window.button('Offline 0101 readiness bytes…',self.readiness))
        self.groups=QComboBox();self.groups.setAccessibleName('Original bundle responder and source context');layout.addWidget(self.groups)
        filters=FlowLayout();self.search=QLineEdit();self.search.setMinimumWidth(230);self.search.setPlaceholderText('Search PID, field, unit or source');self.search.setAccessibleName('Search PID and field evidence');filters.addWidget(self.search)
        self.filter=QComboBox();self.filter.addItems(FILTERS);self.filter.setAccessibleName('Independent evidence filter');filters.addWidget(self.filter);layout.addLayout(filters)
        self.counts=caption('No original bundle selected. Vehicle support is unknown.');layout.addWidget(self.counts)
        self.tree=QTreeWidget();self.tree.setColumnCount(9);self.tree.setHeaderLabels(['PID / field','Bitmap','Positive','Polling','Representation / state','Value / unit','Age s','Median / p95 / max s','Physical accuracy'])
        self.tree.setAccessibleName('PID groups and individual decoded fields');self.tree.setMinimumHeight(260);self.tree.setUniformRowHeights(True)
        self.tree.header().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        for i,width in enumerate((330,115,75,75,190,150,85,195,145)):self.tree.setColumnWidth(i,width)
        layout.addWidget(self.tree,2)
        self.technical=QCheckBox('Show complete technical evidence JSON');layout.addWidget(self.technical)
        self.detail=QTextEdit();self.detail.setReadOnly(True);self.detail.setMinimumHeight(170);self.detail.setAccessibleName('Selected evidence definition and limitations');layout.addWidget(self.detail,1)
        self.status=caption('Private files stay local. No automatic analysis of user folders.');layout.addWidget(self.status);self.jobs=LocalJobs(self,self.status)
        self.search.textChanged.connect(self.render);self.filter.currentTextChanged.connect(self.render);self.groups.currentIndexChanged.connect(self.render)
        self.tree.currentItemChanged.connect(self.describe)
        self.technical.toggled.connect(lambda *_:self.describe(self.tree.currentItem()))

    def import_bundles(self):
        paths,_=QFileDialog.getOpenFileNames(self,'Choose private original bundles; histories remain separate','', 'Research ZIP (*.zip)')
        if paths:self.load_paths(paths)

    def load_paths(self,paths):
        chosen=[Path(p) for p in paths]
        return self.jobs.start(lambda:analyze_explorer(chosen),lambda report:self.loaded(report,chosen))

    def loaded(self,report,paths):
        self.report=report;self.paths=paths;self.scopes=[];self.groups.blockSignals(True);self.groups.clear()
        for session in report['sessions']:
            for group in session['groups']:
                self.scopes.append((session,group));self.groups.addItem(session['evidence_id'][:12]+' · '+group['ecu']+' · '+group['mode']+' / '+group['source_kind']+' / '+group['context_id'])
        self.groups.blockSignals(False);self.export_button.setEnabled(True);self.render()

    def render(self,*_):
        self.tree.clear();self.detail.clear();index=self.groups.currentIndex()
        if not 0<=index<len(self.scopes):self.counts.setText('No responder group with original positive or bitmap evidence. No vehicle facts inferred.');return
        session,g=self.scopes[index];rows=select_rows(g,self.search.text(),self.filter.currentText())
        self.counts.setText(f"Selected source: advertised {g['declared_count']} · positive PIDs {g['positive_pid_count']} · numeric PIDs {g['numeric_pid_count']} · valid field IDs {g['valid_field_ids']} · physical sensor count UNKNOWN\nBitmap {g['bitmap_coverage']} · showing {len(rows)} PID groups. Expand a PID to inspect its fields; ages refer to the end of this recording.")
        def show(v):return '—' if v is None else f'{v:.2f}' if isinstance(v,float) else str(v)
        for row in rows:
            gaps=row['polling_timing']['gap_seconds'];age=row['positive_timing']['age_at_recording_end_seconds']
            item=QTreeWidgetItem([row['request']+' · '+row['name'],row['advertised_support'],str(row['same_ecu_positive']),str(row['polling_replies']),row['representation'],f"{row['valid_field_count']} / {row['field_count']} fields",show(age),' / '.join(show(gaps[k]) for k in ('p50','p95','maximum')),'UNVERIFIED'])
            item.setData(0,Qt.ItemDataRole.UserRole,row);self.tree.addTopLevelItem(item)
            for f in row['fields']:
                gaps=f['gap_seconds'];value=show(f['last_valid_value'])+' '+(f['last_valid_unit'] or '')
                child=QTreeWidgetItem([f['sensor_id']+' · '+f['name'],'',str(f['samples']),'',f['kind']+' / '+f['numeric_validity'],value,show(f['age_at_recording_end_seconds']),' / '.join(show(gaps[k]) for k in ('p50','p95','maximum')),'UNVERIFIED'])
                child.setData(0,Qt.ItemDataRole.UserRole,dict(request=row['request'],definition=row['definition'],field=f,unknowns=row['unknowns']));item.addChild(child)
        if self.tree.topLevelItemCount():self.tree.setCurrentItem(self.tree.topLevelItem(0))

    def describe(self,item,*_):
        if item is None:return
        data=item.data(0,Qt.ItemDataRole.UserRole)
        definition=data['definition'];field=data.get('field')
        lines=[data['request']+' · '+(field['name'] if field else data['name']),
            'Physical sensor identity and calibration: UNVERIFIED. PID identifiers and derived fields do not count physical sensors.',
            'Definition: '+definition['implementation']+' · '+str(definition['revision'])+' · table '+str(definition['table']),
            'Source: '+str(definition['source'])]
        index=self.groups.currentIndex()
        if 0<=index<len(self.scopes):
            session,_=self.scopes[index]
            lines.extend(['Selected input container SHA-256: '+session['input_container_sha256'],
                'Verified member-manifest SHA-256: '+session['verified_member_manifest_sha256'],session['container_scope']])
        if field:
            lines.extend(['Field: '+field['sensor_id']+' · '+field['kind']+' · definition unit '+field.get('unit','')+' · last valid replay unit '+str(field['last_valid_unit']),
                'Validity: '+field['numeric_validity']+' · observed states '+str(field['observed_states']),
                'Formula / support: '+str(field.get('formula'))+' / '+str(field.get('support',field.get('validity'))),
                'Last valid: '+str(field['last_timestamp'])+' · value '+str(field['last_valid_value']),
                'Age at recording end: '+str(field['age_at_recording_end_seconds'])+' s · '+field['staleness'],
                'Interval median / p95 / max: '+str([field['gap_seconds'][k] for k in ('p50','p95','maximum')])+' s'])
        else:
            gates=data['evidence_progression']
            lines.extend(['Anchored bitmap: '+data['advertised_support']+' · same responder positives '+str(data['same_ecu_positive'])+' · ongoing polling replies '+str(data['polling_replies']),
                'Independent checks: '+', '.join(k+' '+str(gates[k]['samples']) for k in ('framed','length_verified','layout_verified','numeric')),
                'Expected exact data length: '+str(definition['expected_bytes'])+' · observed lengths '+str(data['positive_payload_lengths']),
                'Representation: '+data['representation']+' · roles '+str(data['role_counts']),
                'Last attempted request: '+str(data['last_attempt']),
                'Polling interval median / p95 / max: '+str([data['polling_timing']['gap_seconds'][k] for k in ('p50','p95','maximum')])+' s',
                'Recorded profile: '+str(data['profile'])+' · expected '+str(data['polling_timing']['expected_interval_seconds'])+' s · severe gaps '+str(data['polling_timing']['severe_gaps_over_twice_profile']),
                data['research']['interpretation']])
            lines.extend('RAW evidence '+str(e['transaction_id'])+' · '+str(e['timestamp'])+' · '+e['payload_hex'] for e in data['bounded_raw_examples'])
        lines.append('Unknowns: '+'; '.join(data['unknowns']))
        if self.technical.isChecked():lines.append('\nComplete technical evidence:\n'+json.dumps(data,ensure_ascii=False,indent=2))
        self.detail.setPlainText('\n'.join(lines))

    def export(self):
        if not self.report:return
        path,_=QFileDialog.getSaveFileName(self,'Choose fresh PRIVATE CSV and JSON filenames outside Git','sensor-pid-evidence.json','JSON (*.json)')
        if path:
            report=self.report;inputs=tuple(self.paths)
            self.jobs.start(lambda:export_explorer(report,path,inputs),lambda paths:self.status.setText('Saved privately: '+' · '.join(map(str,paths))))

    def readiness(self):
        from mokka_ecu_lab.analysis.readiness import decode_readiness
        text,ok=QInputDialog.getText(self,'Offline 0101 research only','Paste exactly four DATA bytes, without 41 01. No request is sent; vehicle support/accuracy is not inferred:')
        if not ok:return
        try:result=decode_readiness(bytes.fromhex(text))
        except ValueError as exc:self.status.setText('Offline readiness rejected: '+str(exc));return
        self.detail.setPlainText('OFFLINE PASTED BY USER · no link to imported vehicle evidence is implied.\n'+json.dumps(result,ensure_ascii=False,indent=2))

    def closeEvent(self,event):self.jobs.close();super().closeEvent(event)
