"""Private history projection with explicit copy previews and offline-only tools."""
from pathlib import Path
from threading import Event
from datetime import datetime
import json
from PySide6.QtCore import QUrl,Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QWidget,QVBoxLayout,QLineEdit,QComboBox,QTableWidget,QTableWidgetItem,QAbstractItemView,QFileDialog,QInputDialog,QLabel,QCheckBox,QMenu
from .components import caption,FlowLayout,page_heading
from .theme import style_table
from .local_jobs import LocalJobs,preview_dialog
from mokka_ecu_lab.library import ReportLibrary,recent_title,_approved

class HistoryPanel(QWidget):
    def __init__(self,window):
        super().__init__();self.window=window;self.library=ReportLibrary(window.root);self.rows=[];self.refresh_pending=False;self.cancel_migration=Event()
        layout=QVBoxLayout(self);layout.setSpacing(6);page_heading(layout,'History / Reports','Recent reports · Reports / type / one run folder. Open, browse or share one private ZIP. Original journals stay separate.')
        row=FlowLayout();self.search=QLineEdit();self.search.setPlaceholderText('Search date, ECU, version or display label');self.search.setAccessibleName('Search report history');row.addWidget(self.search)
        self.kind=QComboBox();self.kind.addItems(['All types','BENCHMARK','DRIVE']);self.kind.setAccessibleName('Run type');row.addWidget(self.kind)
        self.outcome=QComboBox();self.outcome.addItems(['All statuses','COMPLETED','FAILED_COM_OPEN','PREFLIGHT_FAILED','MEASUREMENT_FAILED','STOPPED','EXPORT_PARTIAL']);self.outcome.setAccessibleName('Run outcome');row.addWidget(self.outcome)
        self.rate=QComboBox();self.rate.addItems(['All rates','1','2','3','4']);self.rate.setAccessibleName('History requested rate');row.addWidget(self.rate)
        self.sort=QComboBox();self.sort.addItems(['Newest first','Oldest first']);self.sort.setAccessibleName('Report history sort order');row.addWidget(self.sort);layout.addLayout(row)
        self.table=QTableWidget(0,8);self.table.setHorizontalHeaderLabels(['Recent report · Athens time','Type','Outcome','req/s','ECU address','App version','Display label','Run ID']);style_table(self.table)
        self.table.setColumnWidth(0,330);self.table.setColumnWidth(2,150)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows);self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection);self.table.setMinimumHeight(140);layout.addWidget(self.table,1)
        row=FlowLayout()
        for name,fn in [('Refresh',self.refresh),('Open report',lambda:self.open_asset('report.html')),('Open folder',lambda:self.open_asset(None)),('Export this run ZIP…',self.export),('Compare selected offline',self.compare),('Display label…',self.label),('Retry report offline',self.retry)]:row.addWidget(window.button(name,fn))
        layout.addLayout(row)
        row=FlowLayout()
        row.addWidget(window.button('Import private run…',self.import_run))
        self.storage_menu=QMenu(self)
        for name,fn in [('Flatten existing Reports…',lambda:self.jobs.start(self.library.preview_flatten,self.show_plan)),('Preview legacy migration…',self.preview_migration),('Resume report migration…',self.resume_migration),('Rollback report migration…',self.rollback_migration),('Cancel copy migration',self.cancel_migration.set),('Recover index offline',lambda:self.jobs.start(self.library.recover_index,lambda _:self.refresh())),('Storage usage',self.usage)]:self.storage_menu.addAction(name,fn)
        self.storage_button=window.button('Organize Reports…',lambda:None);self.storage_button.setMenu(self.storage_menu);row.addWidget(self.storage_button)
        for name,fn in [('Annotate timeline offline…',self.annotate),('View annotations',self.view_annotations),('Open data folder',lambda:QDesktopServices.openUrl(QUrl.fromLocalFile(str(window.root))))]:row.addWidget(window.button(name,fn))
        row.addWidget(window.button('Post-Finish verification reports',self.idle_reports))
        layout.addLayout(row);self.include_annotations=QCheckBox('Include private USER_REPORTED annotations in exported run ZIP');layout.addWidget(self.include_annotations)
        self.status=caption('No history loaded. Legacy files stay in their existing locations until an explicit approved copy.');layout.addWidget(self.status)
        self.jobs=LocalJobs(self,self.status)
        for c in (self.search,self.kind,self.outcome,self.rate,self.sort):
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
        self.visible.sort(key=lambda r:(datetime.fromisoformat(r['started_utc']),r['library_id']),reverse=self.sort.currentIndex()==0)
        self.table.setRowCount(min(1000,len(self.visible)))
        for i,r in enumerate(self.visible[:1000]):
            values=(recent_title(r),r['kind'],r['status'],r['rate'] if r['rate'] is not None else '—',', '.join(r['ecu']),' / '.join(r['application_versions']),r['display_label'],r['session_id'])
            for j,value in enumerate(values):
                item=QTableWidgetItem(str(value));item.setToolTip(r['started_local']+'\n'+r['folder']+'\n'+str(value));self.table.setItem(i,j,item)
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
        if not 2<=len(selected)<=16:self.status.setText('Select 2–16 runs; comparison uses chronological order.');return
        from .obd import ObdDialog
        selected.sort(key=lambda r:(datetime.fromisoformat(r['started_utc']),r['library_id']))
        self.dialog=ObdDialog([Path(r['folder'])/'original-research.zip' for r in selected],self);self.dialog.show()
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
        path=QFileDialog.getExistingDirectory(self,'Select exact legacy export folder or managed Reports subtree for preview',str(self.library.reports))
        if path:self.jobs.start(lambda:self.library.preview_migration(path),self.show_plan)
    def show_plan(self,plan):
        self.last_migration_preview=plan
        preview_dialog(self,'Copy-only migration preview · exact paths / sizes / SHA-256',plan,
            lambda:self.start_migration(plan))
    def start_migration(self,plan):
        self.cancel_migration.clear()
        self.jobs.start(lambda:self.library.migrate(plan,plan['approval_token'],cancelled=self.cancel_migration.is_set),lambda _:self.refresh())
    def resume_migration(self):
        self.jobs.start(self.library.migrations,self.choose_resume)
    def choose_resume(self,rows):
        rows=[r for r in rows if r['state'] in {'COPYING','CANCELLED'}]
        if not rows:self.status.setText('No interrupted report copy migration needs resuming.');return
        labels=[r['token'][:16]+' · '+r['state']+' · '+str(r['completed'])+' runs checkpointed' for r in rows]
        choice,ok=QInputDialog.getItem(self,'Resume report migration','Choose the exact interrupted copy checkpoint:',labels,editable=False)
        if ok:
            token=rows[labels.index(choice)]['token']
            self.jobs.start(lambda:self.saved_migration_plan(token),self.show_resume_plan)
    def saved_migration_plan(self,token):
        path=self.library._audit_path(token)
        if path.stat().st_size>64*1024**2:raise ValueError('Migration checkpoint exceeds 64 MiB bound')
        record=json.loads(path.read_text(encoding='utf-8'));plan=record['plan']
        _approved(plan,token)
        if record.get('state') not in {'COPYING','CANCELLED'} or plan.get('operation')!='FLATTEN_REPORTS_COPY' or plan.get('destination')!=str(self.library.reports):raise ValueError('Checkpoint state changed; select an interrupted migration again')
        return plan
    def show_resume_plan(self,plan):
        self.last_migration_preview=plan
        preview_dialog(self,'Exact RESUME copy preview · reuse this preserved checkpoint',plan,
            lambda:self.start_migration(plan),approve_label='Approve resume of this exact copy migration · keep every original')
    def rollback_migration(self):
        self.jobs.start(self.library.migrations,self.choose_rollback)
    def choose_rollback(self,rows):
        rows=[r for r in rows if r['state']!='ROLLED_BACK' and r['completed']]
        if not rows:self.status.setText('No copied report migration has index pointers to roll back.');return
        labels=[r['token'][:16]+' · '+r['state']+' · '+str(r['completed'])+' runs' for r in rows]
        choice,ok=QInputDialog.getItem(self,'Report migration rollback','Choose a completed or interrupted copy migration:',labels,editable=False)
        if ok:
            token=rows[labels.index(choice)]['token']
            self.jobs.start(lambda:self.library.preview_migration_rollback(token),self.show_rollback)
    def show_rollback(self,plan):
        preview_dialog(self,'Rollback canonical report index · all files stay in place',plan,
            lambda:self.jobs.start(lambda:self.library.rollback_migration(plan,plan['approval_token']),lambda _:self.refresh()),
            approve_label='Approve these index pointer changes · keep both copies')
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

    def idle_reports(self):
        row=self.one()
        if not row:return
        session=row['session_id']
        if not isinstance(session,str) or not session.isalnum():self.status.setText('Invalid immutable session ID');return
        from mokka_ecu_lab.idle_evidence import read_idle_receipt
        directory=self.window.root/'PostExportEvidence'/session
        def read():
            from mokka_ecu_lab.local_paths import linked
            if any(linked(p) for p in [directory,*directory.parents]):raise ValueError('Linked receipt folder blocked')
            files=sorted(directory.glob('post-export-idle-*.json'))
            if len(files)>256:raise ValueError('Receipt folder exceeds 256 entries')
            rows=[dict(path=str(p),receipt=read_idle_receipt(p)) for p in files]
            if any(r['receipt'].get('session_id')!=session for r in rows):raise ValueError('Receipt session differs from selected history group')
            return rows
        self.jobs.start(read,self.show_idle_reports)

    def show_idle_reports(self,rows):
        if not rows:self.status.setText('No separate passive verification receipt saved for this session. Export completion alone is not idle proof.');return
        labels=[r['receipt']['state']+' · '+f"{r['receipt']['verification_elapsed_seconds']:.2f}s"+' · '+r['path'] for r in rows]
        choice,ok=QInputDialog.getItem(self,'Private post-Finish evidence','Immutable receipt; later connection state is separate:',labels,editable=False)
        if ok:
            from mokka_ecu_lab.idle_evidence import read_idle_receipt
            path=rows[labels.index(choice)]['path']
            try:read_idle_receipt(path)
            except (ValueError,OSError) as exc:self.status.setText(str(exc));return
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
