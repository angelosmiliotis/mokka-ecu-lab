"""Private history projection with explicit copy previews and offline-only tools."""
from pathlib import Path
from PySide6.QtCore import QUrl,Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QWidget,QVBoxLayout,QLineEdit,QComboBox,QTableWidget,QTableWidgetItem,QAbstractItemView,QFileDialog,QInputDialog,QLabel,QCheckBox
from .components import caption,FlowLayout,page_heading
from .theme import style_table
from .local_jobs import LocalJobs,preview_dialog
from mokka_ecu_lab.library import ReportLibrary

class HistoryPanel(QWidget):
    def __init__(self,window):
        super().__init__();self.window=window;self.library=ReportLibrary(window.root);self.rows=[];self.refresh_pending=False
        layout=QVBoxLayout(self);layout.setSpacing(6);page_heading(layout,'History / Reports','One private folder per logical run. Original journals remain separate. No upload, automatic migration or purge.')
        row=FlowLayout();self.search=QLineEdit();self.search.setPlaceholderText('Search date, ECU, version or display label');self.search.setAccessibleName('Search report history');row.addWidget(self.search)
        self.kind=QComboBox();self.kind.addItems(['All types','BENCHMARK','DRIVE']);self.kind.setAccessibleName('Run type');row.addWidget(self.kind)
        self.outcome=QComboBox();self.outcome.addItems(['All statuses','COMPLETED','FAILED_COM_OPEN','PREFLIGHT_FAILED','MEASUREMENT_FAILED','STOPPED','EXPORT_PARTIAL']);self.outcome.setAccessibleName('Run outcome');row.addWidget(self.outcome)
        self.rate=QComboBox();self.rate.addItems(['All rates','1','2','3','4']);self.rate.setAccessibleName('History requested rate');row.addWidget(self.rate);layout.addLayout(row)
        self.table=QTableWidget(0,8);self.table.setHorizontalHeaderLabels(['Athens local start','Type','Outcome','req/s','ECU address','App version','Display label','Run ID']);style_table(self.table)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows);self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection);self.table.setMinimumHeight(140);layout.addWidget(self.table,1)
        row=FlowLayout()
        for name,fn in [('Refresh',self.refresh),('Open report',lambda:self.open_asset('report.html')),('Open folder',lambda:self.open_asset(None)),('Export this run ZIP…',self.export),('Compare selected offline',self.compare),('Display label…',self.label),('Retry report offline',self.retry)]:row.addWidget(window.button(name,fn))
        layout.addLayout(row)
        row=FlowLayout()
        for name,fn in [('Import private run…',self.import_run),('Preview legacy migration…',self.preview_migration),('Recover index offline',lambda:self.jobs.start(self.library.recover_index,lambda _:self.refresh())),('Annotate timeline offline…',self.annotate),('View annotations',self.view_annotations),('Storage usage',self.usage),('Open data folder',lambda:QDesktopServices.openUrl(QUrl.fromLocalFile(str(window.root))))]:row.addWidget(window.button(name,fn))
        layout.addLayout(row);self.include_annotations=QCheckBox('Include private USER_REPORTED annotations in exported run ZIP');layout.addWidget(self.include_annotations)
        self.status=caption('No history loaded. Legacy files stay in their existing locations until an explicit approved copy.');layout.addWidget(self.status)
        self.jobs=LocalJobs(self,self.status)
        for c in (self.search,self.kind,self.outcome,self.rate):
            (c.textChanged if isinstance(c,QLineEdit) else c.currentTextChanged).connect(self.render)
        self.refresh()

    def refresh(self):
        if self.jobs.busy():self.refresh_pending=True;return
        self.jobs.start(self.library.rows,self.loaded)
    def loaded(self,rows):
        self.rows=rows;self.render()
        if self.refresh_pending:self.refresh_pending=False;self.refresh()
    def render(self,*_):
        import json
        query=self.search.text().casefold();self.visible=[r for r in self.rows if query in json.dumps(r,ensure_ascii=False).casefold() and (self.kind.currentIndex()==0 or r['kind']==self.kind.currentText()) and (self.outcome.currentIndex()==0 or r['status']==self.outcome.currentText()) and (self.rate.currentIndex()==0 or r['rate']==int(self.rate.currentText()))]
        self.table.setRowCount(min(1000,len(self.visible)))
        for i,r in enumerate(self.visible[:1000]):
            values=(r['started_local'],r['kind'],r['status'],r['rate'] if r['rate'] is not None else '—',', '.join(r['ecu']),' / '.join(r['application_versions']),r['display_label'],r['session_id'])
            for j,value in enumerate(values):self.table.setItem(i,j,QTableWidgetItem(str(value)))
        self.status.setText(f'{len(self.visible)} matching private runs · preview up to 1000 · data root {self.window.root}')
    def selected(self):
        return [self.visible[i.row()] for i in self.table.selectionModel().selectedRows()]
    def one(self):
        selected=self.selected()
        if len(selected)!=1:self.status.setText('Select exactly one run.');return None
        return selected[0]
    def open_asset(self,name):
        row=self.one()
        if row:
            try:self.library.verify(row['library_id'])
            except Exception as exc:self.status.setText(str(exc));return
            path=Path(row['folder'])/name if name else Path(row['folder'])
            if path.exists():QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
            else:self.status.setText('Report incomplete; use Retry report offline.')
    def export(self):
        row=self.one()
        if not row:return
        path,_=QFileDialog.getSaveFileName(self,'Export one complete private run',row['session_id']+'-private-run.zip','ZIP (*.zip)')
        include=self.include_annotations.isChecked()
        if path:self.jobs.start(lambda:self.library.export_run(row['library_id'],path,include_annotations=include),lambda p:self.status.setText('Saved privately: '+str(p)))
    def compare(self):
        selected=self.selected()
        if not 2<=len(selected)<=16:self.status.setText('Select 2–16 runs in comparison order.');return
        from .obd import ObdDialog
        self.dialog=ObdDialog([Path(r['folder'])/'original-research.zip' for r in reversed(selected)],self);self.dialog.show()
    def label(self):
        row=self.one()
        if row:
            label,ok=QInputDialog.getText(self,'Display label only','Immutable run ID/files are retained:',text=row['display_label'])
            if ok:self.library.label(row['library_id'],label);self.refresh()
    def retry(self):
        row=self.one()
        if row:self.jobs.start(lambda:self.library.retry(row['library_id']),lambda _:self.refresh())
    def import_run(self):
        path,_=QFileDialog.getOpenFileName(self,'Import a copy of a private run','', 'Private ZIP (*.zip)')
        if path:self.jobs.start(lambda:self.library.publish_bundle(path),lambda _:self.refresh())
    def preview_migration(self):
        path=QFileDialog.getExistingDirectory(self,'Select the exact legacy flat export folder for preview')
        if path:self.jobs.start(lambda:self.library.preview_migration(path),self.show_plan)
    def show_plan(self,plan):
        self.last_migration_preview=plan
        preview_dialog(self,'Copy-only migration preview · exact paths / sizes / SHA-256',plan,
            lambda:self.jobs.start(lambda:self.library.migrate(plan,plan['approval_token']),lambda _:self.refresh()))
    def annotate(self):
        row=self.one()
        if not row:return
        event,ok=QInputDialog.getItem(self,'Offline user annotation','Event (not ECU-confirmed):',['Stop','Sport on','Sport off','Acceleration','Note'],editable=False)
        if not ok:return
        stamp,ok=QInputDialog.getText(self,'Approximate time','ISO timestamp with explicit UTC offset:',text=row['started_utc'])
        if not ok:return
        uncertainty,ok=QInputDialog.getInt(self,'Time uncertainty','± seconds:',30,0,3600)
        if ok:
            try:self.library.annotate(row['library_id'],event,stamp,uncertainty);self.status.setText('USER_REPORTED_OFFLINE annotation saved; original journal unchanged.')
            except Exception as exc:self.status.setText(str(exc))
    def usage(self):self.jobs.start(self.library.usage,lambda r:preview_dialog(self,'Private storage usage · no automatic purge',r))
    def view_annotations(self):
        row=self.one()
        if row:preview_dialog(self,'Offline timeline · user reported with uncertainty',self.library.annotations(row['library_id']))
