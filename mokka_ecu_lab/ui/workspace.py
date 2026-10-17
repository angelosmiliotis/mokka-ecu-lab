"""Explicit exact-root storage inspection and approved reversible quarantine.

Merely opening this page performs no inventory, filesystem mutation or OBD work.
Every move, resume and restore requires a complete new visible exact preview.
"""
import json
import os
from pathlib import Path
import sys
import threading
import uuid
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QLineEdit,QFileDialog,QPushButton,
    QLabel,QTableWidget,QTableWidgetItem,QAbstractItemView,QHeaderView,QCheckBox)
from mokka_ecu_lab.workspace import WorkspaceStorage,approve
from mokka_ecu_lab.local_paths import linked
from .components import caption,FlowLayout,page_heading
from .local_jobs import LocalJobs,preview_dialog


def source_release_default():
    """Source-only narrow default; frozen apps never guess the user's checkout."""
    if getattr(sys,'frozen',False):return ''
    repo=Path(__file__).resolve().parents[2]
    return str(repo/'release') if (repo/'.git').exists() else ''


def formatted_bytes(size):
    return f'{size:,} bytes ({size/1024**2:,.2f} MiB)'


class WorkspacePanel(QWidget):
    def __init__(self,window):
        super().__init__();self.window=window;self.storage=None;self.last_inventory=None;self.last_plan=None
        self.cancel_event=threading.Event();self.executing=False;self.last_receipt=None
        layout=QVBoxLayout(self);layout.setSpacing(6)
        page_heading(layout,'Workspace / Storage','Inspect the exact developer release folder. No automatic cleanup, file movement, deletion or vehicle request.')
        self.root_edit=QLineEdit(str(window.settings.value('workspace_release_root','') or source_release_default()))
        self.root_edit.setAccessibleName('Exact Git workspace release folder');self.root_edit.setPlaceholderText('Select the exact checkout / release folder')
        layout.addWidget(self.root_edit)
        row=FlowLayout();self.browse=QPushButton('Choose exact release…');self.browse.clicked.connect(self.choose_root);row.addWidget(self.browse)
        self.inventory_button=QPushButton('Inventory exact folder');self.inventory_button.setObjectName('primary');self.inventory_button.clicked.connect(self.inventory);row.addWidget(self.inventory_button)
        self.export_button=QPushButton('Export private inventory / plan…');self.export_button.clicked.connect(self.choose_export);row.addWidget(self.export_button);layout.addLayout(row)
        self.summary=caption('No inventory run. Existing release entries and personal data have not been changed.');layout.addWidget(self.summary)
        self.table=QTableWidget(0,7);self.table.setHorizontalHeaderLabels(['Review / select','Entry','Policy','Files','Bytes','Tree SHA-256','Reason / provenance'])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False);self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents);self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setMinimumHeight(130);layout.addWidget(self.table,1)
        self.reviewed=QCheckBox('I reviewed the checked REVIEW entries; unknown files require my own assessment.')
        self.reviewed.setChecked(False);layout.addWidget(self.reviewed)
        layout.addWidget(caption('KEEP and BLOCKED cannot be selected. REVIEW is not proof of disposability. Quarantine reduces workspace clutter; it frees zero disk bytes and preserves recoverable originals.'))
        self.destination=QLineEdit();self.destination.setAccessibleName('Exact fresh quarantine folder outside the entire repository');self.destination.setPlaceholderText('New same-volume private quarantine folder outside the entire checkout')
        layout.addWidget(self.destination)
        row=FlowLayout();self.choose_destination_button=QPushButton('Choose quarantine parent…');self.choose_destination_button.clicked.connect(self.choose_destination);row.addWidget(self.choose_destination_button)
        self.preview_button=QPushButton('Preview checked moves…');self.preview_button.clicked.connect(self.preview);row.addWidget(self.preview_button)
        self.cancel_button=QPushButton('Cancel between entries');self.cancel_button.setEnabled(False);self.cancel_button.clicked.connect(self.cancel);row.addWidget(self.cancel_button);layout.addLayout(row)
        row=FlowLayout();self.resume_button=QPushButton('Resume receipt preview…');self.resume_button.clicked.connect(self.choose_resume);row.addWidget(self.resume_button)
        self.restore_button=QPushButton('Restore receipt preview…');self.restore_button.clicked.connect(self.choose_restore);row.addWidget(self.restore_button);layout.addLayout(row)
        self.receipt=caption('Receipt: none. Resume and restore also require exact path-level approval.');layout.addWidget(self.receipt)
        self.status=caption('Local only. No inventory starts on page visit.');layout.addWidget(self.status)
        self.jobs=LocalJobs(self,self.status)
        self.jobs.timer.timeout.connect(self.finish_job_controls)

    def finish_job_controls(self):
        if self.jobs.future is None and self.executing:
            self.executing=False;self.cancel_button.setEnabled(False)

    def choose_root(self):
        path=QFileDialog.getExistingDirectory(self,'Select ONE exact Git checkout release folder',self.root_edit.text())
        if path:self.root_edit.setText(path);self.clear_inventory()

    def clear_inventory(self):
        self.last_inventory=None;self.last_plan=None;self.storage=None;self.table.setRowCount(0);self.reviewed.setChecked(False)
        self.summary.setText('Root changed. Run a fresh inventory; no existing entries changed.')

    def selected_root(self):
        value=self.root_edit.text().strip()
        if not value:raise ValueError('Choose the exact Git checkout release folder first')
        return WorkspaceStorage(value)

    def inventory(self):
        if self.jobs.busy():self.status.setText('Wait for the current offline operation.');return
        try:storage=self.selected_root()
        except (OSError,ValueError) as exc:self.status.setText(str(exc));return
        self.storage=storage;self.reviewed.setChecked(False);self.last_plan=None
        self.window.settings.setValue('workspace_release_root',str(storage.root))
        self.jobs.start(storage.inventory,self.show_inventory)

    def show_inventory(self,report):
        self.last_inventory=report;self.table.setRowCount(len(report['entries']))
        for row,entry in enumerate(report['entries']):
            selectable=entry['action']=='REVIEW'
            check=QTableWidgetItem('Review contents' if selectable else 'Protected')
            check.setData(Qt.ItemDataRole.UserRole,entry['path'])
            if selectable:
                check.setFlags(Qt.ItemFlag.ItemIsEnabled|Qt.ItemFlag.ItemIsSelectable|Qt.ItemFlag.ItemIsUserCheckable)
                check.setCheckState(Qt.CheckState.Unchecked)
            else:check.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.table.setItem(row,0,check)
            values=(Path(entry['path']).name,entry['action'],entry['file_count'],entry['bytes'],entry.get('tree_sha256','—'),entry['reason'] or entry['provenance'])
            for col,value in enumerate(values,1):
                item=QTableWidgetItem(str(value));item.setToolTip(entry['path']+'\n'+str(value));self.table.setItem(row,col,item)
        protected=sum(e['action'] in ('KEEP','BLOCKED') for e in report['entries'])
        review_bytes=sum(e['bytes'] for e in report['entries'] if e['action']=='REVIEW')
        self.summary.setText(f"{report['entry_count']} entries · {formatted_bytes(report['bytes'])} · {protected} KEEP/BLOCKED · REVIEW {formatted_bytes(review_bytes)}. No entries changed; provenance requires review.")

    def selected_paths(self):
        return [self.table.item(r,0).data(Qt.ItemDataRole.UserRole) for r in range(self.table.rowCount()) if self.table.item(r,0).checkState()==Qt.CheckState.Checked and self.table.item(r,2).text()=='REVIEW']

    def choose_destination(self):
        path=QFileDialog.getExistingDirectory(self,'Select private same-volume quarantine PARENT outside the repository')
        if path:self.destination.setText(str(Path(path)/('Mokka-workspace-quarantine-'+uuid.uuid4().hex[:10])))

    def inventory_matches_root(self):
        if self.storage is None or self.last_inventory is None:raise ValueError('Run an exact inventory first')
        if self.selected_root().root!=self.storage.root:raise ValueError('Selected root changed; inventory it again')

    def preview(self):
        if self.jobs.busy():self.status.setText('Wait for the current offline operation.');return
        try:
            self.inventory_matches_root()
            if not self.reviewed.isChecked():raise ValueError('Review and acknowledge the checked REVIEW entries first')
            selected=self.selected_paths()
            if not selected:raise ValueError('Check exact REVIEW entries after examining their contents')
            destination=self.destination.text().strip()
            if not destination:raise ValueError('Choose an exact fresh private quarantine destination')
        except (OSError,ValueError) as exc:self.status.setText(str(exc));return
        self.jobs.start(lambda:self.storage.preview_quarantine(self.last_inventory,destination,selected),self.show_quarantine)

    def show_quarantine(self,plan):
        self.last_plan=plan
        preview_dialog(self.window,'Exact workspace MOVE preview · originals retained in reversible quarantine',plan,
            lambda:self.execute_plan(plan),approve_label=f"Approve these {plan['entry_count']} exact moves · no deletion")

    def execute_plan(self,plan):
        if self.jobs.busy():self.status.setText('Wait for the current offline operation.');return
        try:
            if self.selected_root().root!=self.storage.root:raise ValueError('Root changed; create a new preview')
            approve(plan,plan['approval_token'])
        except (OSError,ValueError,KeyError) as exc:self.status.setText(str(exc));return
        self.cancel_event.clear();self.executing=True;self.cancel_button.setEnabled(True)
        if not self.jobs.start(lambda:self.storage.execute(plan,plan['approval_token'],cancel=self.cancel_event.is_set),self.show_receipt):
            self.executing=False;self.cancel_button.setEnabled(False)

    def show_receipt(self,record):
        self.executing=False;self.cancel_button.setEnabled(False)
        self.last_receipt=Path(record['plan']['destination'])/'operation.json'
        self.receipt.setText('Receipt: '+str(self.last_receipt))
        self.status.setText(record['state']+f" · {len(record['completed'])}/{len(record['plan']['entries'])} entries preserved. No deletion; disk bytes freed 0.")
        self.last_inventory=None;self.last_plan=None;self.table.setRowCount(0);self.reviewed.setChecked(False)
        self.summary.setText('Operation recorded. Run a fresh inventory to view current workspace entries.')

    def cancel(self):
        if self.executing:self.cancel_event.set();self.status.setText('Cancellation requested; the current atomic item completes and remaining originals stay in place.')

    def receipt_path(self,title):
        path,_=QFileDialog.getOpenFileName(self,title,str(self.last_receipt or ''),'Operation receipt (operation.json);;JSON (*.json)')
        return Path(path) if path else None

    def choose_resume(self):
        path=self.receipt_path('Choose exact private quarantine receipt to preview RESUME')
        if path:self.preview_resume(path)

    def preview_resume(self,path):
        if self.jobs.busy():self.status.setText('Wait for the current offline operation.');return
        try:storage=self.selected_root();self.storage=storage
        except (OSError,ValueError) as exc:self.status.setText(str(exc));return
        def prepare():
            record=self.read_receipt(path);plan=record['plan'];approve(plan,plan['approval_token'])
            if plan['root']!=str(storage.root):raise ValueError('Receipt belongs to another workspace')
            return record
        self.jobs.start(prepare,self.show_resume)

    def show_resume(self,record):
        plan=record['plan'];self.last_plan=plan
        preview_dialog(self.window,'Exact RESUME preview · completed entries are verified again',record,
            lambda:self.execute_plan(plan),approve_label='Approve resume of this exact preserved receipt')

    def choose_restore(self):
        path=self.receipt_path('Choose exact private quarantine receipt to preview RESTORE')
        if path:self.preview_restore(path)

    def preview_restore(self,path):
        if self.jobs.busy():self.status.setText('Wait for the current offline operation.');return
        try:self.storage=self.selected_root()
        except (OSError,ValueError) as exc:self.status.setText(str(exc));return
        self.jobs.start(lambda:self.storage.preview_restore(path),self.show_restore)

    def show_restore(self,plan):
        self.last_plan=plan
        preview_dialog(self.window,'Exact RESTORE preview · preserve all original paths and bytes',plan,
            lambda:self.execute_restore(plan),approve_label='Approve these exact reverse moves · no deletion')

    def execute_restore(self,plan):
        if self.jobs.busy():self.status.setText('Wait for the current offline operation.');return
        try:
            if self.selected_root().root!=self.storage.root:raise ValueError('Root changed; create a new preview')
        except (OSError,ValueError,AttributeError) as exc:self.status.setText(str(exc));return
        self.cancel_event.clear();self.executing=True;self.cancel_button.setEnabled(True)
        if not self.jobs.start(lambda:self.storage.restore(plan,plan['approval_token'],cancel=self.cancel_event.is_set),self.show_receipt):
            self.executing=False;self.cancel_button.setEnabled(False)

    @staticmethod
    def read_receipt(path):
        path=Path(path)
        if path.stat().st_size>64*1024**2:raise ValueError('Receipt exceeds 64 MiB bound')
        return json.loads(path.read_text(encoding='utf-8'))

    def export_private(self,path):
        payload=self.last_plan or self.last_inventory
        if payload is None:raise ValueError('Run inventory or create an exact plan first')
        target=Path(path).absolute()
        if linked(target) or any(linked(p) for p in target.parents):raise ValueError('Private export cannot follow links')
        if any((p/'.git').exists() for p in target.parents) or (self.storage and target.resolve().is_relative_to(self.storage.repo)):raise ValueError('Private inventory/plan must remain outside Git')
        with target.open('x',encoding='utf-8',newline='\n') as stream:json.dump(payload,stream,ensure_ascii=False,indent=2);stream.write('\n')
        return target

    def choose_export(self):
        start=Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'MokkaECULab'/('Workspace-private-'+uuid.uuid4().hex[:8]+'.json')
        path,_=QFileDialog.getSaveFileName(self,'Export PRIVATE exact inventory / plan outside Git',str(start),'JSON (*.json)')
        if not path:return
        try:self.export_private(path);self.status.setText('Private inventory exported locally. No originals changed.')
        except (OSError,ValueError) as exc:self.status.setText(str(exc))
