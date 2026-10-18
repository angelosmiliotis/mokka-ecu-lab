"""Explicit verified-install/current/rollback previews; never automatic cleanup."""
import os,tempfile,subprocess,sys,uuid
from pathlib import Path
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QWidget,QVBoxLayout,QLineEdit,QComboBox,QFileDialog,QCheckBox
from .components import caption,FlowLayout,page_heading
from .local_jobs import LocalJobs,preview_dialog
from mokka_ecu_lab.versions import ManagedVersions,release_info,latest_release_info
from mokka_ecu_lab.upgrade import ApprovedUpgrade
from mokka_ecu_lab.library import write_json
from mokka_ecu_lab.launcher import CurrentLauncher,shortcut_folders
from mokka_ecu_lab import __version__

class VersionsPanel(QWidget):
    def __init__(self,window):
        super().__init__();self.window=window
        root=Path(tempfile.mkdtemp(prefix='mokka-synthetic-versions-'))/'Versions' if window.validation else Path(os.environ.get('LOCALAPPDATA',Path.home()))/'MokkaECULab/Versions'
        self.manager=ManagedVersions(root,window.root);layout=QVBoxLayout(self);layout.setSpacing(8)
        self.launcher=CurrentLauncher(self.manager,root.parent/'Launcher')
        page_heading(layout,'App Versions','Managed CURRENT + verified ROLLBACK. Personal data is separate. No automatic install, cleanup, file moves or deletion.')
        self.identity=caption('Running version '+__version__+' · Managed CURRENT not checked · GitHub latest known: not checked (explicit lookup only)');layout.addWidget(self.identity)
        self.latest_known=None
        try:
            initial=self.manager.state()
            self.identity.setText('Running version '+__version__+' · Managed CURRENT '+str(initial['current'])+' · Rollback '+str(initial['previous'])+'\nGitHub latest known: not checked · Shortcut target '+str(self.launcher.exe)+' · pointer read only; Inventory verifies files.')
        except Exception as exc:self.identity.setText('Running version '+__version__+' · Managed state INVALID / upgrade blocked: '+str(exc))
        self.build=QComboBox();self.build.setAccessibleName('Verified managed build');layout.addWidget(self.build)
        row=FlowLayout()
        for text,fn in [('Inventory / dry-run preview',self.inventory),('Set as CURRENT…',self.activate),('Rollback preview…',self.rollback),('Open managed versions',self.open_root),('Launch CURRENT',self.launch)]:row.addWidget(window.button(text,fn))
        layout.addLayout(row)
        self.tag=QLineEdit('v'+__version__);self.tag.setAccessibleName('Exact official release tag');layout.addWidget(self.tag)
        row=FlowLayout()
        for text,fn in [('Install & activate verified release…',self.install),('Check latest official release',self.check_latest),('Inspect exact standalone folder…',self.inspect),('Open GitHub releases',lambda:QDesktopServices.openUrl(QUrl('https://github.com/angelosmiliotis/mokka-ecu-lab/releases')))]:row.addWidget(window.button(text,fn))
        layout.addLayout(row);layout.addWidget(caption('One approval: install, isolated startup, atomic CURRENT activation and stable shortcut verification. The approving app closes first; no switching during LIVE use. Existing shortcuts keep the same target. Previous CURRENT remains ROLLBACK; personal data and old builds are preserved. Publication alone does not install a release.'))
        page_heading(layout,'One-click CURRENT launcher','Create a stable shortcut once, after installing and selecting a verified CURRENT build. It follows later CURRENT changes and rollback, and always starts disconnected.')
        self.launcher_identity=caption('Stable target: '+str(self.launcher.exe)+' · not installed or checked on this page visit.');layout.addWidget(self.launcher_identity)
        row=FlowLayout();self.desktop_shortcut=QCheckBox('Desktop shortcut');self.desktop_shortcut.setChecked(True)
        self.programs_shortcut=QCheckBox('Start Menu shortcut');row.addWidget(self.desktop_shortcut);row.addWidget(self.programs_shortcut);layout.addLayout(row)
        row=FlowLayout()
        self.setup_launcher_button=window.button('Preview CURRENT launcher setup…',self.setup_launcher);self.setup_launcher_button.setObjectName('primary');row.addWidget(self.setup_launcher_button)
        self.verify_launcher_button=window.button('Verify stable launcher',self.verify_launcher);row.addWidget(self.verify_launcher_button)
        row.addWidget(window.button('Open launcher folder',self.open_launcher_root));layout.addLayout(row)
        layout.addWidget(caption('The preview lists every new file and shortcut, target, size and SHA-256. Nothing existing is overwritten or deleted. Existing launcher installations need no reinstallation after an approved CURRENT change.'))
        self.status=caption('No maintenance operation started. Offline inventory requires no network.');layout.addWidget(self.status);layout.addStretch();self.jobs=LocalJobs(self,self.status)
    def open_root(self):
        if self.manager.root.exists():QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.manager.root)))
        else:self.status.setText('No managed versions installed yet. Use an official ZIP and review its installation preview.')
    def inventory(self):self.jobs.start(self.manager.inventory,self.show_inventory)
    def show_inventory(self,report):
        self.last_inventory=report;self.build.clear()
        for b in report['builds']:
            if b.get('verified'):self.build.addItem(b['key']+' · '+b['role'],b['key'])
        current=report['state']['current'];older=bool(current and tuple(map(int,__version__.split('.')))<tuple(map(int,current.split('-')[0][1:].split('.'))))
        self.identity.setText('Running version '+__version__+' · Managed CURRENT '+str(current)+' · Rollback '+str(report['state']['previous'])+'\nGitHub latest known: '+str(self.latest_known or 'not checked')+' · Shortcut target '+str(self.launcher.exe)+'\nLaunch: '+report['actual_launch_target']+(' · WARNING: this running app is older than installed CURRENT; close and reopen the Desktop shortcut.' if older else ''))
        preview_dialog(self.window,'Exact managed version inventory · no cleanup actions',report)
    def install(self):
        path,_=QFileDialog.getOpenFileName(self,'Choose downloaded official Windows ZIP','','ZIP (*.zip)');tag=self.tag.text().strip()
        if path:
            if self.window.adapter_open or self.window.recording_id:self.status.setText('Finish Session and Disconnect before preparing an upgrade.');return
            def prepare():
                folders=shortcut_folders()
                return ApprovedUpgrade(self.manager,self.launcher).preview(path,release_info(tag),folders['desktop'],folders['programs'],caller_pid=os.getpid())
            self.jobs.start(prepare,self.show_install)
    def show_install(self,plan):
        self.last_install_preview=plan
        preview_dialog(self.window,'Approve install + activate + verify · app closes before changes',plan,lambda:self.begin_approved_upgrade(plan),
            approve_label='Approve this exact upgrade and close application safely')
    def check_latest(self):
        def received(info):
            self.latest_known=info['tag'];self.tag.setText(info['tag']);self.status.setText('Latest published verified metadata: '+info['tag']+' · no download or installation performed. Choose its downloaded official ZIP.');self.identity.setText('Running '+__version__+' · GitHub latest known '+info['tag']+' · publication is not local installation. Refresh inventory for CURRENT/rollback/shortcut.')
        self.jobs.start(latest_release_info,received)
    def begin_approved_upgrade(self,plan):
        if self.window.adapter_open or self.window.recording_id or self.window.capture_active or self.window.benchmark_state.get('active'):
            self.status.setText('Upgrade cancelled: Finish and Disconnect first. No helper started.');return
        folder=self.manager.root.parent/'Development/approved-upgrades'/uuid.uuid4().hex;folder.mkdir(parents=True)
        path=folder/'approved-plan.json';receipt=folder/'result.json';write_json(path,plan)
        helper=Path(sys.executable).parent/'_internal/launcher/MokkaECULabLauncher.exe'
        command=[str(helper)] if getattr(sys,'frozen',False) else [sys.executable,str(Path(__file__).resolve().parents[2]/'run_launcher.py')]
        if getattr(sys,'frozen',False) and not helper.is_file():self.status.setText('Packaged upgrade helper missing; no changes.');return
        subprocess.Popen(command+['--apply-upgrade-plan',str(path),'--approval-token',plan['approval_token'],'--wait-parent',str(os.getpid()),'--receipt',str(receipt),'--show-upgrade-result'],creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        self.status.setText('Approved helper waiting for this app to close. Result: '+str(receipt));self.window.close()
    def activate(self):
        key=self.build.currentData()
        if not key:self.status.setText('Load inventory and select a verified build.');return
        def prepare():
            folders=shortcut_folders();return ApprovedUpgrade(self.manager,self.launcher).preview_installed(key,folders['desktop'],folders['programs'],caller_pid=os.getpid())
        self.jobs.start(prepare,self.show_install)
    def show_activation(self,plan):
        self.last_activation_preview=plan
        preview_dialog(self.window,'CURRENT / ROLLBACK pointer preview · no executable moves',plan,
            lambda:self.jobs.start(lambda:self.manager.activate(plan,plan['approval_token']),lambda r:self.status.setText('Managed pointers saved: '+str(r))),
            approve_label='Set CURRENT pointer · retain previous rollback and all files')
    def rollback(self):
        try:
            key=self.manager.state()['previous']
            if not key:raise ValueError('No verified managed rollback available yet')
            def prepare():
                folders=shortcut_folders();return ApprovedUpgrade(self.manager,self.launcher).preview_installed(key,folders['desktop'],folders['programs'],caller_pid=os.getpid())
            self.jobs.start(prepare,self.show_install)
        except Exception as exc:self.status.setText(str(exc))
    def inspect(self):
        folder=QFileDialog.getExistingDirectory(self,'Select one exact unmanaged executable folder for read-only inspection')
        if folder:self.jobs.start(lambda:self.manager.preview_external(folder),lambda r:preview_dialog(self.window,'Standalone build dry run · no mutations',r))
    def launch(self):
        if self.window.adapter_open or self.window.recording_id:self.status.setText('Finish acquisition and Disconnect before launching another application.');return
        self.jobs.start(self.manager.launch_current,lambda r:self.status.setText(str(r)))
    def setup_launcher(self):
        desktop=self.desktop_shortcut.isChecked();programs=self.programs_shortcut.isChecked()
        if not desktop and not programs:self.status.setText('Choose Desktop and/or Start Menu for the exact shortcut preview.');return
        def prepare():
            current=self.manager.state()['current']
            if not current:raise ValueError('Install a verified release and Set as CURRENT before creating its shortcut.')
            folders=shortcut_folders()
            return self.launcher.preview(current,folders['desktop'] if desktop else None,folders['programs'] if programs else None,
                self.manager.root.parent/'Development/launcher-previews')
        self.jobs.start(prepare,self.show_launcher_setup)
    def show_launcher_setup(self,plan):
        self.last_launcher_preview=plan
        preview_dialog(self.window,'Exact CURRENT launcher setup · new files and shortcuts only',plan,
            lambda:self.jobs.start(lambda:self.launcher.install(plan,plan['approval_token']),self.show_launcher_verified),
            approve_label='Approve these exact new launcher files and shortcuts · no overwrite')
    def show_launcher_verified(self,report):
        self.last_launcher_verification=report
        self.launcher_identity.setText('Verified stable target: '+report['target']+' · CURRENT '+str(report['current']['current'])+' · starts disconnected.')
        self.status.setText('Stable launcher verified. Use the Desktop / Start Menu shortcut; it follows verified CURRENT and rollback automatically.')
    def verify_launcher(self):
        self.jobs.start(self.launcher.verify,self.show_launcher_verified)
    def open_launcher_root(self):
        if self.launcher.root.exists():QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.launcher.root)))
        else:self.status.setText('No stable launcher installed yet. Review CURRENT launcher setup first.')
