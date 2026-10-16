"""Explicit verified-install/current/rollback previews; never automatic cleanup."""
import os,tempfile
from pathlib import Path
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QWidget,QVBoxLayout,QLineEdit,QComboBox,QFileDialog
from .components import caption,FlowLayout,page_heading
from .local_jobs import LocalJobs,preview_dialog
from mokka_ecu_lab.versions import ManagedVersions,release_info

class VersionsPanel(QWidget):
    def __init__(self,window):
        super().__init__();self.window=window
        root=Path(tempfile.mkdtemp(prefix='mokka-synthetic-versions-')) if window.validation else Path(os.environ.get('LOCALAPPDATA',Path.home()))/'MokkaECULab/Versions'
        self.manager=ManagedVersions(root,window.root);layout=QVBoxLayout(self);layout.setSpacing(8)
        page_heading(layout,'App Versions','Managed CURRENT + verified ROLLBACK. Personal data is separate. No automatic install, cleanup, file moves or deletion.')
        self.identity=caption('Actual launch target and managed state are shown by Inventory preview.');layout.addWidget(self.identity)
        self.build=QComboBox();self.build.setAccessibleName('Verified managed build');layout.addWidget(self.build)
        row=FlowLayout()
        for text,fn in [('Inventory / dry-run preview',self.inventory),('Set as CURRENT…',self.activate),('Rollback preview…',self.rollback),('Open managed versions',self.open_root),('Launch CURRENT',self.launch)]:row.addWidget(window.button(text,fn))
        layout.addLayout(row)
        self.tag=QLineEdit('v0.2.11');self.tag.setAccessibleName('Exact official release tag');layout.addWidget(self.tag)
        row=FlowLayout()
        for text,fn in [('Install official release ZIP…',self.install),('Inspect exact standalone folder…',self.inspect),('Open GitHub releases',lambda:QDesktopServices.openUrl(QUrl('https://github.com/angelosmiliotis/mokka-ecu-lab/releases')))]:row.addWidget(window.button(text,fn))
        layout.addLayout(row);layout.addWidget(caption('Install copies a SHA-verified official ZIP into a fresh managed folder and runs an isolated synthetic startup check. Activation changes a pointer only; the previous verified build remains available. Unmanaged versions require inspection and are never deleted here. GitHub assets are available only while retained upstream.'))
        self.status=caption('No maintenance operation started. Offline inventory requires no network.');layout.addWidget(self.status);layout.addStretch();self.jobs=LocalJobs(self,self.status)
    def open_root(self):
        if self.manager.root.exists():QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.manager.root)))
        else:self.status.setText('No managed versions installed yet. Use an official ZIP and review its installation preview.')
    def inventory(self):self.jobs.start(self.manager.inventory,self.show_inventory)
    def show_inventory(self,report):
        self.last_inventory=report;self.build.clear()
        for b in report['builds']:
            if b.get('verified'):self.build.addItem(b['key']+' · '+b['role'],b['key'])
        self.identity.setText('Launch: '+report['actual_launch_target']+' · CURRENT '+str(report['state']['current'])+' · ROLLBACK '+str(report['state']['previous']))
        preview_dialog(self,'Exact managed version inventory · no cleanup actions',report)
    def install(self):
        path,_=QFileDialog.getOpenFileName(self,'Choose downloaded official Windows ZIP','','ZIP (*.zip)');tag=self.tag.text().strip()
        if path:self.jobs.start(lambda:self.manager.preview_install(path,release_info(tag)),self.show_install)
    def show_install(self,plan):
        self.last_install_preview=plan
        preview_dialog(self,'Install COPY preview · official SHA / files / destination',plan,
            lambda:self.jobs.start(lambda:self.manager.install(plan,plan['approval_token']),lambda r:self.status.setText('Verified build installed without activation: '+r['key'])))
    def activate(self):
        key=self.build.currentData()
        if not key:self.status.setText('Load inventory and select a verified build.');return
        self.jobs.start(lambda:self.manager.preview_activation(key),self.show_activation)
    def show_activation(self,plan):
        self.last_activation_preview=plan
        preview_dialog(self,'CURRENT / ROLLBACK pointer preview · no executable moves',plan,
            lambda:self.jobs.start(lambda:self.manager.activate(plan,plan['approval_token']),lambda r:self.status.setText('Managed pointers saved: '+str(r))),
            approve_label='Set CURRENT pointer · retain previous rollback and all files')
    def rollback(self):
        try:
            key=self.manager.state()['previous']
            if not key:raise ValueError('No verified managed rollback available yet')
            self.jobs.start(lambda:self.manager.preview_activation(key),self.show_activation)
        except Exception as exc:self.status.setText(str(exc))
    def inspect(self):
        folder=QFileDialog.getExistingDirectory(self,'Select one exact unmanaged executable folder for read-only inspection')
        if folder:self.jobs.start(lambda:self.manager.preview_external(folder),lambda r:preview_dialog(self,'Standalone build dry run · no mutations',r))
    def launch(self):
        if self.window.adapter_open or self.window.recording_id:self.status.setText('Finish acquisition and Disconnect before launching another application.');return
        self.jobs.start(self.manager.launch_current,lambda r:self.status.setText(str(r)))
