import base64
import csv
import json
import time
from datetime import datetime
from pathlib import Path
from collections import deque
from PySide6.QtCore import Qt, QTimer, QSettings
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QComboBox, QDoubleSpinBox, QTabWidget, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QListWidget, QListWidgetItem, QSplitter, QTextEdit,
    QFileDialog, QMessageBox, QCheckBox, QLineEdit, QSpinBox, QGroupBox, QFrame, QGridLayout, QApplication, QSizePolicy)
from PySide6.QtCharts import QChart, QChartView, QLineSeries, QScatterSeries
from PySide6.QtGui import QColor, QFont, QKeySequence, QShortcut
from mokka_ecu_lab.adapter import AcquisitionWorker
from mokka_ecu_lab.sensors import load_registry, convert
from mokka_ecu_lab.transport import discover_ports
from mokka_ecu_lab.transport.simulator import SCENARIOS
from mokka_ecu_lab.logging import list_sessions, export_csv, export_jsonl
from mokka_ecu_lab.analysis import interpretations, compare
from mokka_ecu_lab.replay import Replay
from mokka_ecu_lab.protocols import support_state, DISCOVERY_PIDS
from mokka_ecu_lab.sensors.diesel import STANDARD_DIESEL
from mokka_ecu_lab.discovery import discovery_report
from mokka_ecu_lab.adapter.scheduling import priority_weights, nominal_interval
from mokka_ecu_lab.capture import capture_plan, manual_options, DRIVE_WEIGHTS
from mokka_ecu_lab.auto_capture import PRESETS
from mokka_ecu_lab.logging.bundle import export_research_bundle
from mokka_ecu_lab.layouts import RAW_ONLY_PIDS, raw_eligibility
from mokka_ecu_lab.analysis.trends import load_trends
from .trends import TrendsDialog
from .research import ResearchView
from .session import SessionPanel
from mokka_ecu_lab.session import CONFLICTS
from .theme import stylesheet, style_table, style_chart, icon, COLORS
from .components import Sidebar, SensorCard, CaptureStepper, FlowLayout, caption, page_heading, scroll_page
from .presentation import StepState, HUMAN_NAMES, source_description, measurement_status
from mokka_ecu_lab import __version__

STYLE = stylesheet()

def table(headers):
    widget = QTableWidget(0, len(headers))
    widget.setHorizontalHeaderLabels(headers)
    widget.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    widget.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    widget.verticalHeader().setVisible(False)
    widget.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    widget.horizontalHeader().setStretchLastSection(True)
    style_table(widget)
    return widget

def add_row(widget, values):
    row = widget.rowCount()
    widget.insertRow(row)
    for col, value in enumerate(values):
        item=QTableWidgetItem(str(value))
        if widget.objectName()=='rawTransactions' and col in (0,1,5):
            font=QFont('Consolas'); font.setPixelSize(12); item.setFont(font)
        widget.setItem(row,col,item)

def update_row(widget, row, values):
    for col, value in enumerate(values):
        value = str(value)
        item = widget.item(row, col)
        if item is None: widget.setItem(row, col, QTableWidgetItem(value))
        elif item.text() != value: item.setText(value)

class MainWindow(QMainWindow):
    def __init__(self, root: Path, *, validation=False):
        super().__init__()
        self.root = root
        self.registry = load_registry()
        self.worker = AcquisitionWorker(root)
        self.readings, self.support, self.history, self.sensor_errors = {}, {}, {}, {}
        self.support_pages = {}
        self.discovery_observations = {}
        self.discovery_active = False
        self.discovery_prepared = False
        self.discovery_target = None
        self.capture_active = False
        self.capture_weights = {}
        self.capture_raw_pids = set()
        self.capture_ecu = None
        self.capture_history = {}
        self.capture_monitor_errors = 0
        self.auto_receipt = {}
        self.auto_rejection_reason=''
        self.warning_history = {}
        self.last_recording_id = None
        self.discovery_reason = 'No discovery started'
        self.raw_records = deque(maxlen=500)
        self.sessions = []
        self.recording_id = None
        self.recording_started = None
        self.request_count = self.error_count = 0
        self.connected = False
        self.adapter_open = False
        self.connection_phase = 'Disconnected'
        self.connection_protocol = ''
        self.accept_transactions = True
        self.pending_actions = {}
        self.exported_session_id = None
        self.bundle_destination = None
        self.polling_active = False
        self.user_paused = False
        self.requires_reconnect = False
        self.acquisition_reason = "No acquisition"
        self.context_id = None
        self.priorities = {pid: 3 if pid == 12 else 2 if pid == 5 else 1 for pid in self.registry}
        self.mode = "Disconnected"
        self.analysis_rows, self.analysis_report, self.comparison_summary = [], {}, []
        if validation:
            root.mkdir(parents=True,exist_ok=True)
            self.settings=QSettings(str(root/'validation-settings.ini'),QSettings.Format.IniFormat)
        else: self.settings = QSettings("MokkaECULab", "Desktop")
        self.setWindowTitle(f"Mokka ECU Lab {__version__} · read-only diagnostics")
        self.resize(1366, 768); self.setMinimumSize(760, 480)
        self.setWindowIcon(icon('research', 48)); self.setStyleSheet(STYLE)
        self.signal_values = {}; self._chart_signature = None
        central = QWidget(); self.setCentralWidget(central)
        shell = QVBoxLayout(central); shell.setContentsMargins(0, 0, 0, 0); shell.setSpacing(0)
        header = QHBoxLayout(); header.setContentsMargins(16, 10, 16, 10); header.setSpacing(16)
        brand = QLabel("MOKKA ECU LAB"); brand.setObjectName('brand'); header.addWidget(brand)
        subtitle=caption(f"v{__version__}  ·  Read-only vehicle diagnostics"); subtitle.setWordWrap(False)
        header.addWidget(subtitle); header.addStretch()
        header.addWidget(caption('LOCAL / PRIVATE'))
        self.connection_toggle = self.button('Connection settings', self.toggle_connection)
        header.addWidget(self.connection_toggle); shell.addLayout(header)
        body = QHBoxLayout(); body.setSpacing(0)
        workspace = QWidget(); layout = QVBoxLayout(workspace); layout.setContentsMargins(16, 0, 16, 8); layout.setSpacing(8)
        self.build_connection(layout)
        self.status = QLabel("Disconnected · no connection starts automatically"); self.status.setObjectName('caption')
        self.status.setWordWrap(True); self.status.setVisible(False)
        self.status_indicators = {}
        states = FlowLayout(spacing=6)
        for name in ('Source', 'Connection', 'ECU', 'Polling', 'Recording', 'Activity'):
            label = QLabel(); label.setObjectName('badge'); label.setAccessibleName(name)
            states.addWidget(label); self.status_indicators[name] = label
        states.addStretch(); layout.addLayout(states)
        self.tabs = QTabWidget(); self.tabs.tabBar().hide(); layout.addWidget(self.tabs, 1)
        self.build_dashboard(); self.build_sessions(); self.build_raw(); self.build_explorer(); self.build_research()
        self.build_discovery(); self.build_capture()
        self.session_panel=SessionPanel(self); self.tabs.addTab(self.session_panel,'Session Dashboard')
        self.ensurePolished()
        for widget in self.findChildren(QWidget): widget.ensurePolished()
        # Keep the established seven page indices/API, with scrollable content.
        self.tabs.blockSignals(True)
        for i in range(self.tabs.count()):
            page = self.tabs.widget(i); title = self.tabs.tabText(i)
            self.tabs.removeTab(i); self.tabs.insertTab(i, scroll_page(page), title)
        self.tabs.setCurrentIndex(7); self.tabs.blockSignals(False)
        self.sidebar = Sidebar(self.tabs); body.addWidget(self.sidebar); body.addWidget(workspace, 1); shell.addLayout(body, 1)
        self.statusBar().showMessage("Ready · choose a source and connect explicitly. All evidence stays local.")
        self.statusBar().setSizeGripEnabled(False)
        QShortcut(QKeySequence('Ctrl+Shift+R'), self, activated=self.record_button.click)
        self.refresh_presentation()
        self.timer = QTimer(self); self.timer.timeout.connect(self.drain); self.timer.start(100)
        self.refresh_sessions(); self.refresh_ports()
        saved_port=self.settings.value('session_outgoing_port','')
        if saved_port: self.port.setCurrentText(str(saved_port))
        self.source.setCurrentIndex(self.settings.value('session_last_source',0,type=int))
        self.session_panel.update()

    def button(self, label, callback, object_name=""):
        b = QPushButton(label); b.clicked.connect(callback)
        if object_name: b.setObjectName(object_name)
        return b

    def send(self, action, **kwargs):
        if hasattr(self,'session_panel') and action in CONFLICTS-{'session_connect','rate'} and not self.session_panel.advanced.isChecked():
            self.notice('Manual acquisition is available only in Advanced / Developer. Use Connect → Start Session → Finish Session.'); return
        if hasattr(self,'session_panel') and (self.session_panel.snapshot.get('active') or 'session_start' in self.pending_actions) and action in CONFLICTS:
            self.notice('Automatic session owns acquisition; Finish Session first'); return
        if action in {'discover','monitor_discovery','drive_capture','full_auto','retry_auto'}:
            self.user_paused = False
        if action == 'discover': self.polling_active = False
        if action in {"stop", "disconnect", "replay", "shutdown", "connect"}:
            self.polling_active = False
            self.user_paused = action != "connect"
            self.acquisition_reason = "Polling stopped by user" if action == "stop" else "Connection changing / offline"
        elif action == "start":
            self.user_paused = False
        try:
            if self.worker.submit(action, **kwargs) is False: return
            if action in {'connect','record','record_stop','discover','drive_capture','stop','disconnect','start','full_auto','retry_auto'}:
                self.pending_actions[action] = self.context_id
            if action == 'disconnect': self.pending_actions.pop('connect', None)
            if action.startswith('session_'): self.pending_actions[action]=self.context_id
        except Exception as exc: self.notice(str(exc))
        if hasattr(self, 'capture_next'): self.refresh_presentation(); self.update_capture()
        if hasattr(self,'session_panel'): self.session_panel.update()

    def finish_session(self):
        self.send("stop")
        self.send("record_stop")

    def notice(self, message):
        self.statusBar().showMessage(message)
        self.messages.append(f"{datetime.now().isoformat(timespec='seconds')}  {message}")

    def build_connection(self, layout):
        self.connection_panel = QFrame(); self.connection_panel.setObjectName('panel')
        panel = QVBoxLayout(self.connection_panel); panel.setContentsMargins(12, 8, 12, 8); panel.setSpacing(6)
        row = FlowLayout(spacing=8)
        self.source = QComboBox(); self.source.addItems(["Simulation", "Bluetooth / Serial LIVE"])
        self.source.setAccessibleName('Connection source'); self.source.setMinimumWidth(170)
        self.port = QComboBox(); self.port.setEditable(True); self.port.setMinimumContentsLength(6)
        self.port.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.port.setMaximumWidth(180); self.port.setAccessibleName('Outgoing serial port')
        self.port.currentIndexChanged.connect(lambda i: self.port.setToolTip(self.port.itemData(i, Qt.ItemDataRole.ToolTipRole) or "Manual outgoing serial port"))
        self.port.editTextChanged.connect(self.update_connection_controls)
        self.baud = QComboBox(); self.baud.addItems(["115200", "38400", "9600"]); self.baud.setAccessibleName('Serial baud rate')
        self.scenario = QComboBox(); self.scenario.addItems(SCENARIOS); self.scenario.setAccessibleName('Simulation scenario')
        self.scenario.setMinimumContentsLength(12); self.scenario.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.live_config = QWidget(); live = QHBoxLayout(self.live_config); live.setContentsMargins(0,0,0,0)
        self.refresh_port_button = self.button('Refresh', self.refresh_ports)
        for w in (QLabel('Port'), self.port, self.refresh_port_button, QLabel('Baud'), self.baud): live.addWidget(w)
        self.sim_config = QWidget(); sim = QHBoxLayout(self.sim_config); sim.setContentsMargins(0,0,0,0)
        sim.addWidget(QLabel('Scenario')); sim.addWidget(self.scenario, 1)
        self.rate = QDoubleSpinBox(); self.rate.setRange(.25, 4); self.rate.setValue(4); self.rate.setSuffix(" total req/s")
        self.rate.setAccessibleName('Aggregate request rate; maximum four per second')
        self.rate.valueChanged.connect(lambda v: self.send("rate", rate=v))
        self.connect_button = self.button("Start Simulation", self.connect_adapter, "primary")
        self.disconnect_button = self.button("Disconnect", lambda: self.send("disconnect"))
        self.stop_button = self.button("Stop polling", lambda: self.send("stop"), "stop")
        self.start_button = self.button("Resume polling", lambda: self.send("start"))
        for w in (self.source, self.live_config, self.sim_config, self.connect_button, self.disconnect_button): row.addWidget(w)
        row.addStretch(); panel.addLayout(row)
        row2 = FlowLayout()
        safety=caption('READ ONLY  ·  Maximum 4 requests/s'); safety.setWordWrap(False); row2.addWidget(safety)
        self.advanced_connection = self.button('Rate settings', lambda: self.rate.setVisible(not self.rate.isVisible()))
        row2.addWidget(self.advanced_connection); row2.addWidget(self.rate); self.rate.hide(); row2.addStretch()
        row2.addWidget(self.stop_button); row2.addWidget(self.start_button); panel.addLayout(row2)
        layout.addWidget(self.connection_panel)
        self.source.currentIndexChanged.connect(self.source_selection_changed)
        self.scenario.currentIndexChanged.connect(self.source_selection_changed); self.update_connection_controls()

    def toggle_connection(self):
        self.connection_panel.setVisible(not self.connection_panel.isVisible())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'sidebar'): self.sidebar.set_compact(self.width() < 1120)
        if hasattr(self, 'sensor_cards'): self.arrange_cards()

    def update_connection_controls(self):
        live = self.source.currentIndex() == 1
        self.live_config.setVisible(live); self.sim_config.setVisible(not live)
        changing = self.connected or self.adapter_open or self.mode == 'Connecting' or any(a in self.pending_actions for a in ('connect','full_auto','retry_auto'))
        self.port.setEnabled(live and not changing); self.baud.setEnabled(live and not changing)
        self.scenario.setEnabled(not live and not changing); self.source.setEnabled(not changing)
        self.refresh_port_button.setEnabled(live and not changing)
        self.connect_button.setText('Connected' if self.connected else 'Connecting…' if self.mode == 'Connecting' or 'connect' in self.pending_actions else 'Adapter connected' if self.adapter_open else 'Connect' if live else 'Start Simulation')
        if hasattr(self,'greek') and self.greek.isChecked():
            self.connect_button.setText('Συνδέθηκε' if self.connected else 'Σύνδεση…' if self.mode=='Connecting' else 'Σύνδεση')
        self.connect_button.setEnabled(not changing and (not live or bool(self.port.currentText().strip())))
        self.connect_button.setToolTip('Disconnect the current adapter first' if self.adapter_open else
                                      'LIVE: choose an outgoing Bluetooth / Serial port; connection does not certify vehicle compatibility' if live else
                                      'Explicitly start synthetic simulation; no vehicle is connected')
        self.disconnect_button.setEnabled(changing)
        self.stop_button.setEnabled(self.polling_active or self.discovery_active)
        self.start_button.setEnabled(self.connected and not self.polling_active and not self.requires_reconnect and not self.discovery_active and not any(a in self.pending_actions for a in ('start','stop')))
        self.start_button.setToolTip('Reconnect explicitly after an acquisition failure' if self.requires_reconnect else 'Resume basic polling on the current connection')
        self.stop_button.setToolTip('Stop acquisition; recording is independent. Receive cancellation may require reconnect.' if self.stop_button.isEnabled() else 'Polling and Discovery are already stopped')
        self.disconnect_button.setToolTip('Close the adapter and finalize any active recording' if changing else 'No open adapter connection to disconnect')

    def source_selection_changed(self, *args):
        if hasattr(self, 'capture_list') and self.mode!='REPLAY' and not self.connected and not self.adapter_open and 'connect' not in self.pending_actions:
            self.auto_receipt={}; self._auto_signature=None; self.auto_rejection_reason=''
            if hasattr(self,'auto_consent'): self.auto_consent.setChecked(False)
            self.mode = 'Disconnected'
            self.accept_transactions = False
            self.readings.clear(); self.signal_values.clear(); self.history.clear(); self.sensor_errors.clear()
            self.support.clear(); self.support_pages.clear(); self.discovery_observations.clear()
            self.discovery_prepared = False; self.discovery_target = None
            self.capture_plan_ecu = None; self.capture_list.clear(); self.capture_history.clear(); self.warning_history.clear()
            self.discovery_active=False; self.capture_active=False; self.capture_weights.clear(); self.capture_raw_pids.clear()
            self.capture_monitor_errors=0; self.request_count=self.error_count=0
            self.raw_records.clear(); self.raw_table.setRowCount(0)
            self.capture_status.setText('No Discovery in this source selection. Connect explicitly; earlier sessions remain in Sessions.')
            self.exported_session_id = None; self.bundle_destination = None
            if not self.recording_id: self.last_recording_id = None
            self.ecu.clear(); self.ecu.addItem('Automatic first responding ECU', '')
            for check in self.capture_raw_checks.values(): check.setChecked(False); check.setEnabled(False)
        self.update_connection_controls()
        if hasattr(self, 'capture_next'): self.update_measurements(); self.update_capture(); self.refresh_presentation()

    def refresh_ports(self):
        current = self.port.currentText().strip()
        self.port.clear()
        try:
            for name, description in discover_ports():
                self.port.addItem(name, name)
                self.port.setItemData(self.port.count()-1, description, Qt.ItemDataRole.ToolTipRole)
            index = self.port.findData(current or "COM4"); self.port.setCurrentIndex(max(0, index))
        except Exception as exc: self.port.addItem("COM4", "COM4"); self.notice(str(exc))

    def connect_adapter(self):
        self.accept_transactions = False
        self.readings.clear(); self.support.clear(); self.history.clear(); self.sensor_errors.clear(); self.ecu.clear(); self.ecu.addItem("Automatic first responding ECU", "")
        self.support_pages.clear()
        self.mode = "Connecting"
        self.connected = False
        self.request_count = self.error_count = 0
        self.connect_button.setEnabled(False)
        self.update_connection_controls()
        self.send("connect", simulation=self.source.currentIndex() == 0,
                  port=self.port.currentText().strip(),
                  baud=int(self.baud.currentText()), scenario=self.scenario.currentText())

    def build_dashboard(self):
        tab = QWidget(); layout = QVBoxLayout(tab); layout.setContentsMargins(0, 4, 0, 0); layout.setSpacing(8)
        page_heading(layout, 'Vehicle overview', 'Measured signals, with source and freshness. Availability never implies component health.')
        row = FlowLayout()
        self.ecu = QComboBox(); self.ecu.addItem("Automatic first responding ECU", ""); self.ecu.setAccessibleName('Selected ECU')
        self.record_button = self.button("Start recording", self.start_recording, "primary")
        self.record_stop_button = self.button("Finish recording", lambda: self.send("record_stop"))
        self.focus_dashboard = QCheckBox('Focused capture'); self.focus_dashboard.setToolTip('At most seven indications from supported evidence; no automatic requests')
        for w in (QLabel('ECU'), self.ecu, self.focus_dashboard, self.record_button, self.record_stop_button): row.addWidget(w)
        row.addStretch(); layout.addLayout(row)
        self.banner = caption('OFFLINE · no measurements'); layout.addWidget(self.banner)
        self.rejection_reason = caption(''); layout.addWidget(self.rejection_reason)
        self.coverage = caption('No current connection coverage'); self.coverage.setVisible(False)
        self.cards_grid = QGridLayout(); self.cards_grid.setSpacing(8)
        self.sensor_cards = [SensorCard() for _ in range(7)]; layout.addLayout(self.cards_grid)
        self.arrange_cards()
        self.dashboard_sections = QTabWidget(); layout.addWidget(self.dashboard_sections, 1)
        trend = QWidget(); t = QVBoxLayout(trend); t.setContentsMargins(0,8,0,0)
        trend_row = QHBoxLayout(); self.trend_sensor = QComboBox()
        for pid, sensor in self.registry.items(): self.trend_sensor.addItem(sensor.name, pid)
        self.trend_sensor.currentIndexChanged.connect(self.refresh_signal_chart)
        trend_row.addWidget(QLabel('Signal history')); trend_row.addWidget(self.trend_sensor); trend_row.addStretch()
        self.trend_note = caption('At least two acquired samples are needed.'); trend_row.addWidget(self.trend_note); t.addLayout(trend_row)
        self.signal_chart = QChart(); self.signal_chart_view = QChartView(self.signal_chart); self.signal_chart_view.setMinimumHeight(150)
        t.addWidget(self.signal_chart_view,1); self.dashboard_sections.addTab(trend, 'Signal history')
        self.dashboard = table(["Measurement", "Value", "Units", "State", "Rate", "Last success (UTC)", "ECU", "Evidence", "Actual interval", "Gap / age", "Priority"])
        self.dashboard.setMinimumHeight(140); self.dashboard_sections.addTab(self.dashboard, 'All measurements')
        settings = QWidget(); config = QVBoxLayout(settings)
        self.units = QCheckBox("Alternate units (°F, mph, bar, kg/h)")
        self.greek = QCheckBox("Ελληνικές ετικέτες"); self.greek.toggled.connect(self.update_language)
        preferences = QHBoxLayout(); preferences.addWidget(self.units); preferences.addWidget(self.greek); preferences.addStretch(); config.addLayout(preferences)
        priority_row = QHBoxLayout(); self.use_priorities = QCheckBox("Use sensor priorities")
        self.priority_sensor = QComboBox()
        for pid, sensor in self.registry.items(): self.priority_sensor.addItem(sensor.name, pid)
        self.priority_weight = QSpinBox(); self.priority_weight.setRange(1, 4); self.priority_weight.setValue(self.priorities[self.priority_sensor.currentData()])
        self.priority_sensor.currentIndexChanged.connect(self.select_priority); self.priority_weight.valueChanged.connect(self.change_priority)
        self.use_priorities.toggled.connect(self.send_priorities); self.priority_sensor.setEnabled(False); self.priority_weight.setEnabled(False)
        for w in (self.use_priorities, self.priority_sensor, QLabel('Weight'), self.priority_weight): priority_row.addWidget(w)
        config.addLayout(priority_row)
        replacement_row=FlowLayout(); replacement_row.addWidget(QLabel('Focused indication replacement'))
        self.focus_replacement=QComboBox(); self.focus_replacement.addItem('Automatic eligible readings',None)
        self.focus_replacement.setAccessibleName('Replace a focused indication using a recorded supported reading')
        self.focus_replacement.currentIndexChanged.connect(self.refresh_cards); replacement_row.addWidget(self.focus_replacement); config.addLayout(replacement_row)
        self.sensor_list = QListWidget(); self.sensor_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        stored = self.settings.value("sensor_order", list(self.registry), type=list)
        order = [int(x) for x in stored if int(x) in self.registry]; order += [x for x in self.registry if x not in order]
        for pid in order:
            item = QListWidgetItem(self.registry[pid].name); item.setData(Qt.ItemDataRole.UserRole, pid)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable); item.setCheckState(Qt.CheckState.Checked); self.sensor_list.addItem(item)
        self.sensor_list.itemChanged.connect(self.select_sensors); self.sensor_list.model().rowsMoved.connect(self.select_sensors)
        config.addWidget(caption('Choose sensors; drag to reorder. Recordings always retain original base units.'))
        config.addWidget(self.sensor_list); self.dashboard_sections.addTab(settings, 'Sensor selection')
        self.messages = QTextEdit(); self.messages.setReadOnly(True); self.messages.document().setMaximumBlockCount(150)
        self.dashboard_sections.addTab(self.messages, 'Activity log')
        self.stats = caption('Recording: off · Requests: 0 · Errors: 0'); layout.addWidget(self.stats)
        self.tabs.addTab(tab, "Dashboard")

    def update_language(self, enabled):
        labels = ["Πίνακας", "Συνεδρίες", "Ακατέργαστα", "Αισθητήρες", "Έρευνα", "Ανακάλυψη", "Drive Capture"] if enabled else ["Dashboard", "Sessions", "Raw Data", "Sensor Explorer", "Research", "Discovery", "Drive Capture"]
        for i, label in enumerate(labels): self.tabs.setTabText(i, label)
        if hasattr(self, "sidebar"): self.sidebar.set_compact(self.sidebar.compact)
        self.connect_button.setText("Σύνδεση" if enabled else "Start Simulation" if self.source.currentIndex()==0 else "Connect")
        self.disconnect_button.setText("Αποσύνδεση" if enabled else "Disconnect")
        self.stop_button.setText("Διακοπή" if enabled else "Stop polling")

    def select_sensors(self, *args):
        self.send("select", pids=[self.sensor_list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.sensor_list.count()) if self.sensor_list.item(i).checkState() == Qt.CheckState.Checked])

    def select_priority(self, *args):
        self.priority_weight.blockSignals(True)
        self.priority_weight.setValue(self.priorities[self.priority_sensor.currentData()])
        self.priority_weight.blockSignals(False)

    def change_priority(self, weight):
        self.priorities[self.priority_sensor.currentData()] = weight
        self.send_priorities()

    def send_priorities(self, *args):
        enabled = self.use_priorities.isChecked()
        self.priority_sensor.setEnabled(enabled); self.priority_weight.setEnabled(enabled)
        self.send("priorities", enabled=enabled, weights=dict(self.priorities))

    def build_sessions(self):
        tab = QWidget(); layout = QVBoxLayout(tab); layout.setContentsMargins(0,4,0,0)
        page_heading(layout, 'Recorded sessions', 'Local journals and measurements. Finish a recording before creating an evidence bundle.')
        row = FlowLayout()
        self.session_record_button=self.button('Start recording',self.start_recording)
        self.session_finish_button=self.button('Finish recording',lambda:self.send('record_stop'))
        row.addWidget(self.session_record_button); row.addWidget(self.session_finish_button)
        for label, callback in [("Refresh", self.refresh_sessions), ("Replay selected", self.replay_session), ("Open replay…", self.open_replay)]: row.addWidget(self.button(label, callback))
        row.addStretch(); layout.addLayout(row)
        self.session_table = table(["Session", "Started (UTC)", "Ended (UTC)", "Duration", "Source", "Transactions", "Errors", "Completion", "ECU"])
        self.session_table.setMinimumHeight(150); layout.addWidget(self.session_table,1)
        self.session_table.itemSelectionChanged.connect(self.session_selection_changed)
        exports = QGroupBox('Export selected session · private local files'); export_layout = QGridLayout(exports)
        self.bundle_button = self.button('Research Bundle ZIP…',self.bundle_export, 'primary')
        self.csv_button = self.button('Measurements CSV…',self.csv_export); self.jsonl_button = self.button('Raw journal JSONL…',self.jsonl_export)
        for col, (b, text) in enumerate(((self.bundle_button,'Complete evidence, checksums and source context'),(self.csv_button,'Decoded measurements in original units'),(self.jsonl_button,'Recorded original diagnostic transactions'))):
            export_layout.addWidget(b,0,col); export_layout.addWidget(caption(text),1,col)
        export_layout.addWidget(self.button('Private HTML / JSON report…',self.open_private_report),2,0)
        export_layout.addWidget(caption('Import a bundle in Research, select its source, then export the offline report.'),2,1,1,2)
        layout.addWidget(exports)
        self.diagnostic_export = QCheckBox('Include original adapter/port, identification bytes and marker notes in diagnostic JSONL')
        self.diagnostic_export.setToolTip('Private identifying metadata. Redaction is enabled by default. Review before sharing.'); layout.addWidget(self.diagnostic_export)
        self.private_phase_export=QCheckBox('Include private phase labels in Research Bundle · local only')
        self.private_phase_export.setToolTip('Default bundle redacts phase labels and notes. This opt-in includes phase labels, uncertainty and provenance; notes remain redacted.'); layout.addWidget(self.private_phase_export)
        layout.addWidget(caption('Files stay on this computer. No automatic uploads. VIN is never queried; adapter metadata is redacted by default.'))
        self.session_info = caption(str(self.root)); layout.addWidget(self.session_info)
        controls = FlowLayout(); self.replay_speed = QComboBox(); self.replay_speed.addItems(["1× original", "2×", "5×", "10×"])
        controls.addWidget(QLabel('Offline replay')); controls.addWidget(self.replay_speed)
        controls.addWidget(self.button("Play", lambda: self.send("replay_play", speed=[1., 2., 5., 10.][self.replay_speed.currentIndex()])))
        controls.addWidget(self.button("Pause replay", lambda: self.send("stop")))
        controls.addWidget(self.button("Step transaction", lambda: self.send("step")))
        controls.addWidget(self.button('Recorded trends…',self.open_trends)); controls.addStretch(); layout.addLayout(controls)
        layout.addWidget(self.button('Offline Sport / Normal comparison…',self.open_phase_comparison))
        layout.addWidget(self.button('Offline DPF RAW evolution…',self.open_dpf_evolution))
        layout.addWidget(self.button('Offline ECU inventory / OBD performance…',self.open_obd_report))
        layout.addWidget(self.button('Recover / retry selected session export offline',self.recover_selected_session))
        self.tabs.addTab(tab, "Sessions")

    def session_selection_changed(self):
        session = self.current_session()
        for button in (self.csv_button, self.jsonl_button): button.setEnabled(bool(session))
        if session:
            self.session_info.setText(f"Selected {session['id'][:12]} · {session['mode']} · {session['requests']} transactions · " + ('Closed' if session['ended'] else 'Open / interrupted') + f" · Stored in {self.root}")
        self.update_capture()

    def open_private_report(self):
        self.tabs.setCurrentIndex(4); self.research_view.tabs.setCurrentIndex(1)
        self.notice('Import a local Research Bundle, choose a source group, then export a private report.')

    def refresh_sessions(self):
        try:
            previous = self.current_session()
            self.sessions = list_sessions(self.root)
            self.session_table.setRowCount(0)
            for index, s in enumerate(self.sessions):
                end = datetime.fromisoformat(s["ended"]) if s["ended"] else datetime.now().astimezone()
                duration = (end - datetime.fromisoformat(s["started"])).total_seconds()
                evidence=json.loads(s.get('metadata') or '{}').get('capture_evidence',{})
                add_row(self.session_table, [s["id"][:12], s["started"], s["ended"] or "Open / interrupted", f"{duration:.1f} s", s["mode"], s["requests"], s["errors"], "Closed" if s["ended"] else "Open / interrupted", ", ".join(evidence.get("support", {})) or "Not recorded"])
                if previous and s["id"] == previous["id"]: self.session_table.selectRow(index)
            self.session_selection_changed()
        except Exception as exc: self.notice(str(exc))

    def open_trends(self):
        path,_=QFileDialog.getOpenFileName(self,'Local recorded comparisons',str(self.root),'Recorded data (*.csv *.zip)')
        if not path: return
        try:
            report=load_trends(path)
            self.trends_dialog=TrendsDialog(report,self); self.trends_dialog.show()
        except Exception as exc: self.notice(str(exc))

    def current_session(self):
        row = self.session_table.currentRow() if hasattr(self, "session_table") else -1
        return self.sessions[row] if 0 <= row < len(self.sessions) else None

    def open_phase_comparison(self):
        path,_=QFileDialog.getOpenFileName(self,'Private offline Sport / Normal comparison',str(self.root),'Research Bundle (*.zip)')
        if path:
            from .phases import PhaseDialog
            self.phase_dialog=PhaseDialog(path,self); self.phase_dialog.show()

    def replay_session(self):
        s = self.current_session()
        if s: self.load_replay(self.root / s["raw_path"])
        else: self.notice("Select a recorded session first")

    def open_replay(self):
        path, _ = QFileDialog.getOpenFileName(self, "Replay raw journal", str(self.root), "Raw journal (*.jsonl)")
        if path: self.load_replay(Path(path))

    def load_replay(self, path):
        self.readings.clear(); self.history.clear(); self.support.clear(); self.sensor_errors.clear()
        self.support_pages.clear()
        self.raw_table.setRowCount(0); self.raw_records.clear()
        self.ecu.clear(); self.ecu.addItem("Automatic first responding ECU", "")
        self.send("replay", path=str(path))
        self.tabs.setCurrentIndex(1)

    def csv_export(self):
        s = self.current_session()
        if not s: return self.notice("Select a session to export")
        path, _ = QFileDialog.getSaveFileName(self, "Export original decoded units", str(self.root / (s["id"] + ".csv")), "CSV (*.csv)")
        if path:
            try: export_csv(self.root, s["id"], Path(path)); self.notice(f"CSV saved locally: {path}")
            except Exception as exc: self.notice(str(exc))

    def jsonl_export(self):
        s = self.current_session()
        if not s: return self.notice("Select a session to export")
        path, _ = QFileDialog.getSaveFileName(self, "Export raw journal", str(self.root / (s["id"] + "-export.jsonl")), "JSONL (*.jsonl)")
        if path:
            try: export_jsonl(self.root / s["raw_path"], Path(path), self.diagnostic_export.isChecked()); self.notice(f"JSONL saved locally: {path}")
            except Exception as exc: self.notice(str(exc))

    def bundle_export(self,latest=False):
        if self.recording_id: return self.notice('Finish session / Stop Recording before exporting')
        self.refresh_sessions()
        session = self.latest_closed_session() if latest else self.current_session()
        if not session or not session['ended']: return self.notice('Select a closed session; use Finish session first')
        path,_ = QFileDialog.getSaveFileName(self,'Export Research Bundle',str(self.root/(session['id']+'-research.zip')),'ZIP (*.zip)')
        if path:
            try:
                export_research_bundle(self.root,session['id'],Path(path),include_private_phases=self.private_phase_export.isChecked())
                self.exported_session_id = session['id']; self.bundle_destination = str(Path(path).resolve())
                self.notice(f'Private Research Bundle saved locally: {self.bundle_destination} · SHA-256 checksums; original journal unchanged.')
                self.session_info.setText(f'Private diagnostic evidence saved: {self.bundle_destination}')
                self.update_capture()
            except Exception as exc: self.notice(str(exc))

    def open_dpf_evolution(self):
        from .dpf import DpfDialog
        paths,_=QFileDialog.getOpenFileNames(self,'Private offline DPF bundles','','ZIP (*.zip)')
        if paths:
            self.dpf_dialog=DpfDialog(paths,self); self.dpf_dialog.show()

    def recover_selected_session(self):
        session=self.current_session()
        if session: self.send('session_export_retry',session_id=session['id'])

    def open_obd_report(self):
        from .obd import ObdDialog
        paths,_=QFileDialog.getOpenFileNames(self,'Private offline ECU inventory / performance','','ZIP (*.zip)')
        if paths:self.obd_dialog=ObdDialog(paths,self);self.obd_dialog.show()

    def build_raw(self):
        tab = QWidget(); layout = QVBoxLayout(tab); layout.setContentsMargins(0,4,0,0)
        page_heading(layout, 'Raw transactions', 'Original replies remain intact. Latest 500 shown; recording retains every transaction on disk.')
        row = QHBoxLayout()
        self.raw_search = QLineEdit(); self.raw_search.setPlaceholderText('Filter ECU, PID / command, status or error'); self.raw_search.setAccessibleName('Filter raw transactions')
        self.raw_status_filter = QComboBox(); self.raw_status_filter.addItems(['All statuses','Successful','Errors'])
        self.raw_search.textChanged.connect(self.filter_raw); self.raw_status_filter.currentIndexChanged.connect(self.filter_raw)
        row.addWidget(self.raw_search,1); row.addWidget(self.raw_status_filter); row.addWidget(self.button('Copy original response',self.copy_raw_response)); layout.addLayout(row)
        self.raw_table = table(["UTC timestamp", "Command", "Status", "Latency ms", "ECU", "Parsed payload", "Decoder", "Error"])
        self.raw_table.setObjectName('rawTransactions')
        self.raw_table.setMinimumHeight(160); layout.addWidget(self.raw_table,1)
        self.raw_detail = QTextEdit(); self.raw_detail.setReadOnly(True); self.raw_detail.setFont(QFont('Consolas',10)); self.raw_detail.setMinimumHeight(160)
        self.raw_detail.setObjectName('byteText')
        self.raw_detail.setPlaceholderText('Select a transaction to inspect original text and hex separately from interpretation.'); layout.addWidget(self.raw_detail,1)
        self.raw_table.itemSelectionChanged.connect(self.show_raw_detail); self.tabs.addTab(tab, "Raw Data")

    def filter_raw(self, *args):
        query = self.raw_search.text().strip().lower(); status = self.raw_status_filter.currentIndex()
        for row in range(self.raw_table.rowCount()):
            cells = [self.raw_table.item(row,col).text() if self.raw_table.item(row,col) else '' for col in range(self.raw_table.columnCount())]
            ok = cells[2] == 'OK'
            self.raw_table.setRowHidden(row, (query not in ' '.join(cells).lower()) or (status==1 and not ok) or (status==2 and ok))

    def copy_raw_response(self):
        row = self.raw_table.currentRow()
        if not 0 <= row < len(self.raw_records): return self.notice('Select a raw transaction first')
        raw = base64.b64decode(self.raw_records[row].get('raw_b64',''))
        QApplication.clipboard().setText(raw.decode('ascii','replace')); self.notice('Original response copied locally')

    def show_raw_detail(self):
        row = self.raw_table.currentRow()
        if 0 <= row < len(self.raw_records):
            record = self.raw_records[row]
            raw = base64.b64decode(record.get("raw_b64", ""))
            self.raw_detail.setPlainText("Original response (text):\n" + raw.decode('ascii', 'replace') +
                "\nOriginal response (hex):\n" + raw.hex(' ') + "\n\nTransaction metadata:\n" + json.dumps(record, indent=2, ensure_ascii=False))

    def build_explorer(self):
        tab = QWidget(); layout = QVBoxLayout(tab); layout.setContentsMargins(0,4,0,0)
        page_heading(layout, 'Sensor explorer', 'Documented formulas and actual ECU availability are separate. Inspect a sensor for its exact metadata.')
        row = QHBoxLayout(); self.explorer_search = QLineEdit(); self.explorer_search.setPlaceholderText('Search sensor, PID, units or evidence')
        self.explorer_category = QComboBox(); self.explorer_category.addItems(['All categories','Engine','Temperature','Air / pressure','Vehicle'])
        self.explorer_search.textChanged.connect(self.filter_explorer); self.explorer_category.currentIndexChanged.connect(self.filter_explorer)
        row.addWidget(self.explorer_search,1); row.addWidget(self.explorer_category); layout.addLayout(row)
        self.explorer = table(["Sensor", "Request", "Service / positive", "ECU", "Layout", "Formula", "Units", "Poll rate", "Verification", "Last value", "Last UTC", "State / evidence"])
        self.explorer.setMinimumHeight(180); layout.addWidget(self.explorer,2)
        for col in (2,4,5,10): self.explorer.setColumnHidden(col,True)
        self.explorer_technical = QCheckBox('Show technical columns'); self.explorer_technical.toggled.connect(lambda show: [self.explorer.setColumnHidden(c,not show) for c in (2,4,5,10)])
        layout.addWidget(self.explorer_technical)
        self.sensor_detail = QTextEdit(); self.sensor_detail.setReadOnly(True); self.sensor_detail.setMinimumHeight(150); layout.addWidget(self.sensor_detail,1)
        self.sensor_detail.setPlaceholderText('Select a sensor to inspect its formula, units and exact verification metadata.')
        self.explorer.itemSelectionChanged.connect(self.show_sensor_detail); self.tabs.addTab(tab, "Sensor Explorer")

    def filter_explorer(self, *args):
        query = self.explorer_search.text().lower(); category = self.explorer_category.currentText()
        for row,sensor in enumerate(self.registry.values()):
            pid = sensor.pid
            group = 'Temperature' if pid in {5,15} else 'Air / pressure' if pid in {11,16,51} else 'Vehicle' if pid==13 else 'Engine'
            text = ' '.join(self.explorer.item(row,c).text() for c in range(self.explorer.columnCount()) if self.explorer.item(row,c))
            self.explorer.setRowHidden(row, query not in text.lower() or (category!='All categories' and category!=group))

    def show_sensor_detail(self):
        row = self.explorer.currentRow()
        if 0 <= row < len(self.registry):
            sensor=list(self.registry.values())[row]
            self.sensor_detail.setPlainText(f'{sensor.name} · 01{sensor.pid:02X} · {sensor.unit}\nPublished formula documentation does not establish vehicle support or independent accuracy.\n\nExact metadata:\n'+json.dumps(sensor.metadata, indent=2, ensure_ascii=False))

    def build_research(self):
        tab = QWidget(); layout = QVBoxLayout(tab)
        warning = QLabel("OFFLINE ONLY · EXPERIMENTAL hypotheses · no live request input")
        warning.setStyleSheet("color: #eabf75; font-weight: 600;"); layout.addWidget(warning)
        layout.addWidget(QLabel("Enter payload hex, one sample per line. Select a byte slice to compare byte order, signedness, scale and offset.\nOptional measured values must be paired in the same row order and use the same units."))
        row = QHBoxLayout()
        self.payloads = QTextEdit(); self.payloads.setPlaceholderText("04 80\n04 90\n04 A0"); self.payloads.setMaximumHeight(90)
        self.measured = QTextEdit(); self.measured.setPlaceholderText("Measured reference (one numeric value per line)"); self.measured.setMaximumHeight(90)
        row.addWidget(self.payloads); row.addWidget(self.measured); layout.addLayout(row)
        options = FlowLayout()
        self.byte_start = QSpinBox(); self.byte_start.setRange(0, 63)
        self.byte_length = QSpinBox(); self.byte_length.setRange(1, 8); self.byte_length.setValue(2)
        self.scale = QDoubleSpinBox(); self.scale.setRange(-1e9, 1e9); self.scale.setDecimals(8); self.scale.setValue(1)
        self.offset = QDoubleSpinBox(); self.offset.setRange(-1e9, 1e9); self.offset.setDecimals(8)
        for label, w in [("Byte start", self.byte_start), ("Length", self.byte_length), ("Scale", self.scale), ("Offset", self.offset)]:
            options.addWidget(QLabel(label)); options.addWidget(w)
        options.addWidget(self.button("Evaluate hypotheses", self.evaluate))
        options.addWidget(self.button("Save report…", self.save_report))
        layout.addLayout(options)
        actions = FlowLayout()
        actions.addWidget(self.button("Load payloads from JSONL…", self.load_analysis))
        actions.addWidget(self.button("Compare recordings…", self.compare_recordings))
        self.analysis_pid = QLineEdit("7A"); self.analysis_pid.setMaximumWidth(65)
        actions.addWidget(QLabel("Recorded PID:")); actions.addWidget(self.analysis_pid)
        self.analysis_ecu = QLineEdit("7E8"); self.analysis_ecu.setMaximumWidth(90)
        actions.addWidget(QLabel("ECU:")); actions.addWidget(self.analysis_ecu)
        self.hypothesis = QComboBox(); self.hypothesis.addItems(["big unsigned", "big signed", "little unsigned", "little signed"])
        self.hypothesis.currentIndexChanged.connect(self.plot_hypothesis)
        actions.addWidget(QLabel("Plot:")); actions.addWidget(self.hypothesis); layout.addLayout(actions)
        self.analysis_table = table(["Sample", "Selected bytes", "Byte order", "Signed", "Raw integer", "Candidate", "Verification"])
        self.analysis_table.setMaximumHeight(170); layout.addWidget(self.analysis_table)
        self.chart = QChart(); self.chart.setTheme(QChart.ChartTheme.ChartThemeDark)
        self.chart.setTitle("Raw integer and candidate value vs sample index (different units; experimental)")
        self.chart_view = QChartView(self.chart); layout.addWidget(self.chart_view)
        self.analysis_summary = QLabel("No hypotheses evaluated"); self.analysis_summary.setWordWrap(True); layout.addWidget(self.analysis_summary)
        self.research_view = ResearchView(self.root,tab,self)
        self.tabs.addTab(self.research_view, "Research")

    def evaluate(self):
        try:
            lines = [line for line in self.payloads.toPlainText().splitlines() if line.strip()]
            if not lines or len(lines) > 1000: raise ValueError("Enter 1–1000 samples")
            reference = [float(x) for x in self.measured.toPlainText().splitlines() if x.strip()]
            rows = []
            for line in lines:
                payload = bytes.fromhex(line)
                selected = payload[self.byte_start.value():self.byte_start.value() + self.byte_length.value()]
                if len(selected) != self.byte_length.value(): raise ValueError("Byte slice exceeds a sample")
                rows.append((selected.hex(' '), interpretations(selected, self.scale.value(), self.offset.value())))
            metrics = [compare([r[1][i]["candidate"] for r in rows], reference) for i in range(4)] if reference else []
            self.analysis_rows = rows
            self.analysis_report = {"verification": "EXPERIMENTAL", "source_payloads": lines,
                "byte_start": self.byte_start.value(), "length": self.byte_length.value(), "scale": self.scale.value(),
                "offset": self.offset.value(), "measured": reference, "candidates": rows, "metrics": metrics,
                "recording_comparison": self.comparison_summary}
            self.analysis_table.setRowCount(0)
            for index, (payload, variants) in enumerate(rows):
                for v in variants: add_row(self.analysis_table, [index, payload, v["order"], v["signed"], v["integer"], f'{v["candidate"]:.6f}', "EXPERIMENTAL"])
            self.plot_hypothesis()
        except Exception as exc: self.notice(str(exc))

    def plot_hypothesis(self, *args):
        if not self.analysis_rows: return
        self.chart.removeAllSeries()
        selected = self.hypothesis.currentIndex()
        for key, name in [("integer", "Raw integer"), ("candidate", "Candidate value")]:
            series = QLineSeries(); series.setName(name)
            for index, row in enumerate(self.analysis_rows): series.append(index, row[1][selected][key])
            self.chart.addSeries(series)
        if self.analysis_report.get("measured"):
            series = QLineSeries(); series.setName("Measured reference")
            for i, value in enumerate(self.analysis_report["measured"]): series.append(i, value)
            self.chart.addSeries(series)
        self.chart.createDefaultAxes()
        metrics = self.analysis_report.get("metrics", [])
        self.analysis_summary.setText("EXPERIMENTAL · " + (json.dumps(metrics[selected]) if metrics else "No physical reference supplied; numerical plausibility does not verify meaning."))

    def save_report(self):
        if not self.analysis_report: return self.notice("Evaluate a hypothesis first")
        path, _ = QFileDialog.getSaveFileName(self, "Save reproducible experimental report", str(self.root / "hypothesis-report.json"), "JSON (*.json)")
        if path:
            try:
                self.analysis_report['request'] = '01'+self.analysis_pid.text().strip().upper()
                self.analysis_report['ecu'] = self.analysis_ecu.text().strip().upper()
                self.research_view.catalog.add_hypothesis(self.analysis_report)
                Path(path).write_text(json.dumps(self.analysis_report, indent=2), encoding="utf-8")
                self.notice("Experimental report saved locally; no decoder promotion")
            except Exception as exc: self.notice(str(exc))

    def recording_payloads(self, path):
        pid = int(self.analysis_pid.text(), 16)
        source = self.analysis_ecu.text().strip().upper()
        playback = Replay(Path(path)); payloads, counts, invalid = [], 0, 0
        source_groups = set()
        try:
            while (record := playback.next()) is not None:
                counts += 1
                if record.get("status") != "OK": invalid += 1
                if record.get("pid") == f"{pid:02X}":
                    for item in record.get("parsed", []):
                        if (item.get("ecu") or "headerless").upper() == source and len(payloads) < 1000:
                            payloads.append(item["data_hex"])
                            mode=record.get('mode','UNKNOWN')
                            kind=record.get('source_kind') or ('SIMULATED' if mode=='SIMULATED' else 'ECU_READING' if mode.startswith('LIVE') else 'UNKNOWN')
                            source_groups.add((mode,kind))
        finally: playback.close()
        if len(source_groups)>1: raise ValueError('Mixed source groups: use the offline evidence analyzer to view each separately')
        return payloads, {"file": str(path), "pid": f"{pid:02X}", "ecu": source, "transactions": counts,
            "errors": invalid, "sample_count": len(payloads), "source_groups":sorted(source_groups), "truncated_preview_limit": 1000, "warnings": playback.warnings}

    def load_analysis(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load recorded payloads", str(self.root), "JSONL (*.jsonl)")
        if path:
            try:
                payloads, summary = self.recording_payloads(path)
                self.payloads.setPlainText('\n'.join(payloads)); self.comparison_summary = [summary]
                self.notice(f"Loaded {len(payloads)} payloads; verify ECU and PID before evaluating")
            except Exception as exc: self.notice(str(exc))

    def compare_recordings(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Compare recorded payload sequences", str(self.root), "JSONL (*.jsonl)")
        if not paths: return
        try:
            result = [self.recording_payloads(path) for path in paths]
            groups={tuple(group) for _,summary in result for group in summary['source_groups']}
            if len(groups)>1: raise ValueError('LIVE, SIMULATED and unknown sources cannot be joined; use the offline evidence analyzer')
            self.comparison_summary = [r[1] for r in result]
            self.payloads.setPlainText('\n'.join(x for r in result for x in r[0])[:250000])
            self.analysis_summary.setText(json.dumps(self.comparison_summary))
            self.notice("Comparison loaded in file order. Counts/errors are per file; report preserves file boundaries. Evaluate a byte hypothesis to plot samples.")
        except Exception as exc: self.notice(str(exc))

    def source_key(self):
        return self.ecu.currentData() or (next(iter(self.support), None))

    def build_capture(self):
        tab=QWidget(); layout=QVBoxLayout(tab); layout.setContentsMargins(0,4,0,0); layout.setSpacing(8)
        page_heading(layout, 'Drive capture', 'Prepare while stationary. During a journey, use passive monitoring; a passenger operates the laptop.')
        auto=QFrame(); auto.setObjectName('panel'); a=QVBoxLayout(auto)
        heading=QLabel('Full Auto Research Drive'); heading.setObjectName('nextActionTitle'); a.addWidget(heading)
        a.addWidget(caption('One deliberate action: record → connect → safe Discovery → all eligible sensors → RAW proof. Prepare while parked.'))
        row=FlowLayout(); self.auto_preset=QComboBox(); self.auto_preset.addItems(PRESETS)
        self.auto_start=self.button('Start Full Auto Research Drive',self.start_full_auto,'primary')
        self.auto_retry=self.button('Retry Capture Setup',self.retry_full_auto)
        for w in (self.auto_preset,self.auto_start,self.auto_retry): row.addWidget(w)
        a.addLayout(row)
        self.auto_consent=QCheckBox('I am parked: allow all eligible standard sensors + RAW-only evidence for this preset')
        self.auto_consent.setToolTip('Single consent for this run, including eligible 017A / 0188 RAW. Existing read-only allowlist; maximum 4 total requests/s; no numeric formula for unverified RAW layouts.')
        self.auto_consent.toggled.connect(self.update_capture); a.addWidget(self.auto_consent)
        self.auto_status=caption('Select Simulation or LIVE explicitly. Give preset consent, then Start. No requests on page visits.')
        a.addWidget(self.auto_status)
        self.auto_dpf=QLabel('017A RAW: NOT READY · no worker schedule or stored samples'); self.auto_dpf.setObjectName('sourceIdentity'); self.auto_dpf.setWordWrap(True); a.addWidget(self.auto_dpf)
        layout.addWidget(auto)
        self.capture_stepper = CaptureStepper(self.show_capture_step); layout.addWidget(self.capture_stepper)
        self.capture_step_help = caption('Full Auto above runs the acknowledged sequence. Manual / advanced actions below start only when you press their buttons.'); layout.addWidget(self.capture_step_help)
        next_panel=QFrame(); next_panel.setObjectName('panel'); next_row=QHBoxLayout(next_panel)
        next_text=QVBoxLayout(); title=QLabel('Next recommended action'); title.setObjectName('nextActionTitle'); next_text.addWidget(title)
        self.capture_next_help=caption('Select a source and connect explicitly.'); next_text.addWidget(self.capture_next_help)
        next_row.addLayout(next_text,1); self.capture_next=self.button('Connection settings',self.perform_next_capture_action,'primary'); next_row.addWidget(self.capture_next)
        layout.addWidget(next_panel)
        self.capture_identity=QLabel(); self.capture_identity.setObjectName('sourceIdentity'); self.capture_identity.setWordWrap(True); layout.addWidget(self.capture_identity)
        recording_row=FlowLayout()
        self.capture_record=self.button('Start recording',self.start_recording)
        self.capture_record_stop=self.button('Finish recording',lambda:self.send('record_stop'))
        self.capture_recording_note=caption('Recording Off'); self.capture_recording_note.setWordWrap(False); recording_row.addWidget(self.capture_recording_note)
        recording_row.addWidget(self.capture_record); recording_row.addWidget(self.capture_record_stop); layout.addLayout(recording_row)
        controls=FlowLayout(); self.capture_source=QComboBox(); self.capture_source.setModel(self.ecu.model())
        self.capture_source.currentIndexChanged.connect(self.ecu.setCurrentIndex); self.ecu.currentIndexChanged.connect(self.capture_source.setCurrentIndex)
        self.capture_preset=self.button('Prepare recommended preset',self.prepare_capture)
        self.capture_start=self.button('Start Drive Capture',self.start_capture)
        self.capture_bundle=self.button('Export Research Bundle',lambda:self.bundle_export(latest=True))
        self.capture_finish=self.button('Finish session',self.finish_session,'stop')
        for w in (QLabel('ECU'),self.capture_source,self.capture_preset,self.capture_start,self.capture_finish,self.capture_bundle): controls.addWidget(w)
        layout.addLayout(controls)
        self.capture_status=caption('Complete standard discovery before preparing a drive preset.'); layout.addWidget(self.capture_status)
        self.capture_summary=caption('Capture not started'); layout.addWidget(self.capture_summary)
        self.capture_technical=QCheckBox('Technical details · PID, weights, intervals, gaps and original evidence')
        self.capture_technical.toggled.connect(self.capture_view_changed); layout.addWidget(self.capture_technical)
        self.capture_sections=QTabWidget(); layout.addWidget(self.capture_sections,1)
        monitor=QWidget(); m=QVBoxLayout(monitor); m.setContentsMargins(0,8,0,0)
        self.capture_table=table(['Measurement','Value','Units','State / evidence','Observed mean interval','Age / maximum gap','Weight'])
        self.capture_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.capture_table.horizontalHeader().setStretchLastSection(False)
        for col,width in enumerate([210,95,55,320,150,170,65]): self.capture_table.setColumnWidth(col,width)
        self.capture_table.setMinimumHeight(220); m.addWidget(self.capture_table,1)
        self.capture_focus=QCheckBox('Focused dashboard · at most seven readings'); m.addWidget(self.capture_focus)
        self.focus_dashboard.toggled.connect(self.capture_focus.setChecked); self.capture_focus.toggled.connect(self.focus_dashboard.setChecked)
        self.capture_focus.toggled.connect(self.update_capture)
        self.capture_counter_note=caption(''); m.addWidget(self.capture_counter_note); self.capture_sections.addTab(monitor,'Capture monitor')
        configure=QWidget(); c=QVBoxLayout(configure)
        c.addWidget(caption('The preset sends nothing. Checkbox edits apply only after Start Drive Capture. NOx is an unchecked manual option.'))
        self.capture_list=QListWidget(); self.capture_list.setMinimumHeight(140); c.addWidget(self.capture_list,1)
        self.capture_list.itemChanged.connect(self.update_capture)
        self.capture_raw_checks={}
        for pid in sorted(RAW_ONLY_PIDS):
            check=QCheckBox(f'Opt in 01{pid:02X} RAW ONLY · no numeric interpretation · weight 1')
            check.setEnabled(False); check.stateChanged.connect(self.update_capture); self.capture_raw_checks[pid]=check; c.addWidget(check)
        self.capture_raw_detail=QTextEdit(); self.capture_raw_detail.setReadOnly(True)
        self.capture_omissions=QTextEdit(); self.capture_omissions.setReadOnly(True)
        self.capture_evidence_tabs=QTabWidget(); self.capture_evidence_tabs.setMinimumHeight(150); self.capture_evidence_tabs.addTab(self.capture_raw_detail,'Raw evidence'); self.capture_evidence_tabs.addTab(self.capture_omissions,'Numeric omissions'); c.addWidget(self.capture_evidence_tabs,1)
        self.capture_sections.addTab(configure,'Configure & evidence')
        journey=QWidget(); j=QVBoxLayout(journey); marker_row=FlowLayout()
        self.journey_start=self.button('Journey Start',lambda:self.send('marker',event='Journey Start'))
        self.journey_end=self.button('Journey End',lambda:self.send('marker',event='Journey End'))
        self.marker_note=QLineEdit(); self.marker_note.setMaxLength(512); self.marker_note.setPlaceholderText('Passenger note · local original only; bundle redacts text')
        self.note_button=self.button('Add note',self.add_note)
        for w in (self.journey_start,self.journey_end,self.marker_note,self.note_button): marker_row.addWidget(w)
        j.addLayout(marker_row); self.marker_table=table(['Marker UTC','Event','Note / evidence']); j.addWidget(self.marker_table,1)
        phase_row=FlowLayout(); self.journey_phase=QComboBox(); self.journey_phase.addItems(('Normal','Sport on','Sport off','City','Open road'))
        self.journey_uncertainty=QSpinBox(); self.journey_uncertainty.setRange(0,3600); self.journey_uncertainty.setValue(30); self.journey_uncertainty.setSuffix(' s uncertainty ±')
        self.phase_note_button=self.button('Add USER_REPORTED phase',lambda:self.send('marker',event='Phase',phase=self.journey_phase.currentText(),uncertainty_seconds=self.journey_uncertainty.value()))
        for w in (self.journey_phase,self.journey_uncertainty,self.phase_note_button): phase_row.addWidget(w)
        j.addLayout(phase_row); j.addWidget(caption('User phases are private notes, never ECU-confirmed. Add only while parked or by a passenger; edit approximate time offline in Sessions.'))
        j.addWidget(caption('Markers never send ECU requests. Page changes never finish recording. Finish session stops polling and closes recording; Disconnect also finalizes an open recording.'))
        self.capture_sections.addTab(journey,'Journey markers')
        matrix=QWidget(); ml=QVBoxLayout(matrix)
        ml.addWidget(caption('Current ECU only. All eligible known allowlisted PIDs; bitmap pages are metadata. Estimated intervals may increase with adapter and disk delays.'))
        self.auto_matrix=table(['Group / measurement / PID','ECU','Bitmap support','Positive / decoder','Representation / reason','Worker scheduled / weight','Stored positives','Mean / max gap / age (s)'])
        self.auto_matrix.setMinimumHeight(220); ml.addWidget(self.auto_matrix)
        self.auto_receipt_detail=QTextEdit(); self.auto_receipt_detail.setReadOnly(True); self.auto_receipt_detail.setMaximumHeight(180); ml.addWidget(self.auto_receipt_detail)
        self.capture_sections.addTab(matrix,'Auto preflight & coverage')
        self.tabs.addTab(tab,'Drive Capture'); self.capture_view_changed(); self.update_capture()

    def start_full_auto(self):
        if not self.auto_consent.isChecked(): return self.notice('Give the single preset RAW consent while parked first')
        self.auto_receipt={}; self.auto_rejection_reason=''; self.auto_consent.setChecked(False)
        self.accept_transactions=False; self.user_paused=False
        self.send('full_auto',simulation=self.source.currentIndex()==0,port=self.port.currentText().strip(),
            baud=int(self.baud.currentText()),scenario=self.scenario.currentText(),
            preset=self.auto_preset.currentText(),consent=True,reuse=self.connected,
            ecu=self.source_key() if self.connected else None)
        if self.connected: self.accept_transactions=True
        self.capture_sections.setCurrentIndex(3)

    def retry_full_auto(self):
        self.send('retry_auto',simulation=self.source.currentIndex()==0,ecu=self.source_key(),
                  port=self.port.currentText().strip(),baud=int(self.baud.currentText()),scenario=self.scenario.currentText())

    def update_auto_capture(self):
        data=self.auto_receipt; state=data.get('state','NOT_STARTED')
        pending=any(a in self.pending_actions for a in ('full_auto','retry_auto'))
        working=state in {'STARTING','RECORDING','CONNECTING','DISCOVERING','CONFIGURED','WAITING_RAW','READY','PARTIAL'} and bool(self.recording_id or pending)
        self.auto_start.setEnabled(self.auto_consent.isChecked() and not pending and not working and not self.requires_reconnect and self.mode!='REPLAY' and
                                  (self.connected or not self.adapter_open) and (self.source.currentIndex()==0 or bool(self.port.currentText().strip())))
        self.auto_preset.setEnabled(not working); self.auto_consent.setEnabled(not working)
        self.auto_retry.setEnabled(state in {'PARTIAL','STOPPED'} and self.connected and bool(self.recording_id) and self.discovery_prepared and not self.requires_reconnect and not pending)
        self.auto_start.setToolTip('Explicitly record, connect, discover and start all eligible sensors for '+self.source_identity())
        self.auto_retry.setToolTip('Parked only: one explicit bounded setup pass on the current healthy connection. No automatic reconnect.')
        signature=(state,pending,self.capture_active,self.polling_active,len(data.get('transitions',[])),sum(e.get('positive_samples',0) for e in data.get('observed',{}).values()),int(time.monotonic()))
        if signature==getattr(self,'_auto_signature',None): return
        self._auto_signature=signature
        if data:
            closure=(' · recording CLOSED · adapter '+('OPEN' if data.get('adapter_open') else 'CLOSED')) if data.get('closed_at') else ''
            self.auto_status.setText(f"{state} · {data.get('reason','')} · ECU {data.get('ecu','awaiting response')} · {len(data.get('effective_schedule',{}))} scheduled PIDs · preset RAW consent acknowledged"+closure)
            dpf=data['dpf']; outcome=data.get('capture_outcome',{})
            display_state='RECORDED PROOF · capture inactive' if dpf['recorded_positive_six_byte_frames']>=2 and not(self.capture_active and self.polling_active and self.recording_id) else dpf['state']
            self.auto_dpf.setText(f"017A RAW: {display_state} · worker scheduled {'YES' if dpf.get('worker_scheduled') and self.capture_active and self.polling_active else 'NO'} · stored six-byte positives {dpf['recorded_positive_six_byte_frames']} / 2\n"+
                'Bitmap '+dpf.get('bitmap_support','UNKNOWN')+' · '+dpf.get('bitmap_provenance','No current evidence')+' · prior complete reply '+str(dpf.get('discovery_data_length','—'))+' bytes · decoder '+dpf.get('discovery_decoder','UNVERIFIED')+'\n'+dpf.get('reason','')+
                ('\nLast stored: '+str(dpf.get('last_timestamp'))+' · '+str(dpf.get('last_length'))+' bytes · '+str(dpf.get('last_payload_hex')) if dpf.get('last_timestamp') else '')+
                ('\nSetup ended: '+outcome.get('reason','') if outcome.get('state')=='ABORTED' else ''))
            rows=data.get('requested_plan',{}).get('matrix',[]); self.auto_matrix.setRowCount(len(rows))
            for i,item in enumerate(rows):
                pid=int(item['pid'],16); sensor=STANDARD_DIESEL.get(pid) or self.registry[pid]
                units='RAW bytes; no numeric unit' if item['representation']=='RAW ONLY' else ' / '.join(sorted({f.unit for f in sensor.fields})) if pid in STANDARD_DIESEL else sensor.unit
                group='NOx' if pid==0x83 else 'DPF' if pid in {0x7A,0x7B,0x7C,0x8B} else 'SCR / AdBlue' if pid in {0x85,0x86,0x88} else 'Exhaust' if pid in DISCOVERY_PIDS else 'Engine'
                schedule=data.get('effective_schedule',{}).get(item['pid'],{}); sample=data.get('observed',{}).get(item['pid'],{})
                age=(time.monotonic_ns()-sample['last_monotonic_ns'])/1e9 if sample.get('last_monotonic_ns') else None
                gaps=' / '.join(f'{v:.2f}' if v is not None else '—' for v in [sample.get('mean_interval_seconds'),sample.get('maximum_gap_seconds'),age])
                update_row(self.auto_matrix,i,[f'{group} · {HUMAN_NAMES.get(pid,sensor.name)} · 01{pid:02X} ({units})',data.get('ecu','—'),
                    item['support'].upper()+(' · ordered raw bitmap' if item['bitmap_affirmative'] else ' · no affirmative chain'),
                    f"{'YES' if item['positive_observed'] else 'NO'} / {item['layout']}",item['representation']+(' · automatically included' if item['included'] else ' · omitted')+' · '+item['reason']+(' · '+sample['last_error'] if sample.get('last_error') else ''),
                    f"{'YES' if schedule and self.capture_active and self.polling_active else 'NO'} / {schedule.get('weight','—')} · estimate {schedule.get('nominal_interval_seconds','—')} s",
                    sample.get('positive_samples',0),gaps])
            self.auto_receipt_detail.setPlainText(json.dumps(data,ensure_ascii=False,indent=2))
        elif pending:
            self.auto_status.setText('Awaiting worker acknowledgment; no stage completed yet')
        else:
            self.auto_status.setText(self.auto_rejection_reason or 'Select Simulation or LIVE explicitly. Give preset consent, then Start. No requests on page visits.')
            self.auto_dpf.setText('017A RAW: NOT READY · no worker schedule or stored samples in this source selection')
            self.auto_matrix.setRowCount(0); self.auto_receipt_detail.clear()

    def capture_view_changed(self, *args):
        if not hasattr(self,'capture_evidence_tabs'): return
        technical=self.capture_technical.isChecked()
        self.capture_status.setVisible(technical)
        for col in (4,5,6): self.capture_table.setColumnHidden(col,not technical)
        self.capture_evidence_tabs.setVisible(technical)
        self.capture_list.blockSignals(True)
        for i in range(self.capture_list.count()):
            item=self.capture_list.item(i); pid=item.data(Qt.ItemDataRole.UserRole)
            sensor=STANDARD_DIESEL.get(pid) or self.registry[pid]
            name=HUMAN_NAMES.get(pid,sensor.name)
            item.setText(f'{name} · PID 01{pid:02X}'+(f' · weight {item.data(Qt.ItemDataRole.UserRole+1)}' if technical else '')+(' · optional NOx monitoring' if pid==0x83 else ''))
        self.capture_list.blockSignals(False)
        self.update_capture()

    def show_capture_step(self, stage):
        hints = ('Choose Simulation or LIVE in connection settings, then connect explicitly.',
                 'Start recording before connecting to retain initialization. Finish recording closes the journal; it does not stop polling.',
                 'Use Discovery to scan standard PIDs explicitly, while stationary, for this ECU.',
                 'Prepare a preset, review eligible choices and unchecked NOx / RAW-only options. Preparing sends nothing.',
                 'Start Drive Capture explicitly. Monitor the actual source, PID count, intervals and errors.',
                 'Finish session stops polling and finishes recording. Disconnect is a separate connection action.',
                 'Export a closed session as a Research Bundle. Files remain local and private.')
        self.capture_step_help.setText(hints[stage])
        if stage==0: self.connection_panel.show()
        elif stage==1:
            self.tabs.setCurrentIndex(0); self.record_button.setFocus()
        elif stage==2: self.tabs.setCurrentIndex(5)
        elif stage==3: self.capture_sections.setCurrentIndex(1)
        elif stage==4: self.capture_sections.setCurrentIndex(0)
        elif stage==6: self.tabs.setCurrentIndex(1)

    def prepare_capture(self):
        ecu=self.source_key(); prepared=self.discovery_prepared and ecu==self.discovery_target and self.connected and not self.requires_reconnect
        preset=capture_plan(self.support,self.support_pages,self.discovery_observations,ecu,prepared=prepared)
        options=manual_options(self.support,self.support_pages,self.discovery_observations,ecu,prepared=prepared)
        self.capture_list.clear()
        for pid,weight in options['weights'].items():
            sensor=STANDARD_DIESEL.get(pid) or self.registry[pid]
            item=QListWidgetItem(f'{sensor.name} / 01{pid:02X} · weight {weight}'+(' · NOx trend opt-in' if pid==0x83 else ''))
            item.setData(Qt.ItemDataRole.UserRole,pid); item.setFlags(item.flags()|Qt.ItemFlag.ItemIsUserCheckable)
            item.setData(Qt.ItemDataRole.UserRole+1,weight); item.setToolTip(f'{sensor.name}\nPID 01{pid:02X} · existing schedule weight {weight}')
            item.setCheckState(Qt.CheckState.Checked if pid in preset['weights'] else Qt.CheckState.Unchecked)
            self.capture_list.addItem(item)
        for pid,check in self.capture_raw_checks.items():
            check.setChecked(False)
            raw_plan=capture_plan(self.support,self.support_pages,self.discovery_observations,ecu,
                                  prepared=prepared,selected=[],raw_selected=[pid])
            check.setEnabled(pid in raw_plan['weights'])
            check.setToolTip('Complete positive response; numeric interpretation remains disabled' if check.isEnabled()
                             else '; '.join(e['reason'] for e in raw_plan['omitted']))
        self.capture_plan_ecu=ecu
        self.capture_omissions.setPlainText('\n'.join(f"01{e['pid']} {e['name']}: {e['reason']}" for e in options['omitted']) or 'All documented choices have valid support evidence.')
        self.capture_status.setText('Preset prepared; no requests started. Check choices, then press Start Drive Capture.')
        self.capture_sections.setCurrentIndex(1); self.capture_view_changed()
        self.update_capture()

    def capture_selected(self):
        return [self.capture_list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.capture_list.count())
                if self.capture_list.item(i).checkState()==Qt.CheckState.Checked]

    def raw_selected(self):
        return [pid for pid,check in self.capture_raw_checks.items() if check.isEnabled() and check.isChecked()]

    def add_note(self):
        self.send('marker',event='Note',note=self.marker_note.text())
        self.marker_note.clear()

    def start_capture(self):
        if self.source_key()!=getattr(self,'capture_plan_ecu',None):
            return self.notice('ECU changed; prepare the Drive Capture preset for this ECU first')
        self.send('drive_capture',ecu=self.source_key(),pids=self.capture_selected(),raw_pids=self.raw_selected())

    def source_identity(self):
        active=self.connected or self.adapter_open or 'connect' in self.pending_actions or bool(self.readings or self.discovery_observations)
        mode=self.mode if active or self.mode=='REPLAY' else 'Disconnected'
        text=source_description(mode,live_selected=self.source.currentIndex()==1)
        if 'SIMULATION' in text: text+=' · '+self.scenario.currentText()
        elif text.startswith('LIVE'): text+=' · port '+(self.port.currentText().strip() or 'not selected')
        return text

    def start_recording(self):
        self.notice(self.source_identity()+' · recording begins only after worker confirmation; initialization can be recorded before connection.')
        self.send('record')

    def acquisition_mode(self):
        if self.mode=='REPLAY': return 'Replay'
        if self.capture_active: return 'Drive Capture'
        if self.discovery_active: return 'Discovery monitoring' if self.polling_active else 'Discovery'
        return 'Basic polling'

    def schedule_weights(self):
        # Presentation of the existing scheduler, never a new scheduling model.
        if self.capture_active: return dict(self.capture_weights) if self.capture_ecu==self.source_key() else {}
        selected=[self.sensor_list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.sensor_list.count())
                  if self.sensor_list.item(i).checkState()==Qt.CheckState.Checked]
        supported=set().union(*self.support.values()) if self.support else set()
        weights=priority_weights([p for p in selected if p in supported],self.priorities if self.use_priorities.isChecked() else {})
        if self.discovery_active and self.source_key()==self.discovery_target:
            if not self.polling_active: return priority_weights(DISCOVERY_PIDS & self.support.get(self.discovery_target,set()),{},allow_discovery=True)
            weights.update(priority_weights(DISCOVERY_PIDS & self.support.get(self.discovery_target,set()),{},allow_discovery=True))
        return weights

    def sample_presentation(self, pid, sample):
        source=self.source_key(); replay=bool(sample.get('replay') or sample.get('mode','').startswith('REPLAY'))
        raw=bool(sample.get('raw_only') or (pid in RAW_ONLY_PIDS and raw_eligibility(sample) and sample.get('layout_status')=='DECODER_UNVERIFIED'))
        times=self.history.get((source,pid),[]) if pid in self.registry else self.capture_history.get((source,pid),[])
        gaps=[b-a for a,b in zip(times,list(times)[1:]) if b>a]
        weights=self.schedule_weights(); expected=nominal_interval(pid,weights,self.rate.value()) if pid in weights else 0
        sent_at=sample.get('received_at')
        if sent_at is None and sample.get('monotonic_ns') is not None: sent_at=sample['monotonic_ns']/1e9
        supported=support_state(self.support.get(source,set()),self.support_pages.get(source,set()),pid)=='supported'
        same_context=(sample.get('context_id',self.context_id)==self.context_id
                      and (not sample.get('mode') or sample['mode']==self.mode)
                      and sample.get('source_kind','UNKNOWN')==('SIMULATED' if self.mode=='SIMULATED' else 'ECU_READING'))
        active=self.connected and not self.requires_reconnect and not self.user_paused and (self.polling_active or self.discovery_active)
        valid=not sample.get('invalid') and not sample.get('stale_reason') and (not sample.get('error') or raw)
        status=measurement_status(now=time.monotonic(),sent_at=sent_at,replay=replay,active=active,
                                  scheduled=pid in weights and supported,valid=valid,same_context=same_context,
                                  expected=expected,intervals=gaps)
        acquisition=sample.get('acquisition_mode',self.acquisition_mode())
        provenance=sample.get('source_kind','UNKNOWN'); origin='SIMULATED · synthetic' if provenance=='SIMULATED' else 'LIVE' if provenance=='ECU_READING' else 'UNKNOWN'
        if replay: origin='REPLAY · '+origin
        recorded=bool(self.recording_id and sample.get('recording_session')==self.recording_id)
        reason=sample.get('stale_reason') or sample.get('error') or self.sensor_errors.get((source,pid),'')
        if not status['current'] and not replay:
            reason=reason or ('Reconnect required after communication failure' if self.requires_reconnect else
                              'Disconnected' if not self.connected else 'Polling currently stopped' if not active else
                              'PID not currently scheduled' if pid not in weights else 'No recent valid sample')
        status.update(acquisition=acquisition,origin=origin,raw=raw,gaps=gaps,reason=reason,
                      recording='Recorded in current session' if recorded else 'Not recorded in current session')
        status['text']=status['label']+' · '+acquisition+' · '+origin
        status['detail']=status['text']+'\n'+status['recording']+('\n'+reason if reason else '')
        return status

    def unavailable_reason(self, pid):
        support=support_state(self.support.get(self.source_key(),set()),self.support_pages.get(self.source_key(),set()),pid)
        if support=='unsupported':
            return 'Not supported in selected simulation scenario' if self.mode=='SIMULATED' else 'Not supported by selected ECU'
        if support=='unknown': return 'Support unknown · Discovery not completed for this ECU'
        sample=self.discovery_observations.get((self.source_key(),pid),{})
        if raw_eligibility(sample) and sample.get('layout_status')=='DECODER_UNVERIFIED': return 'RAW data available · No verified numeric decoder'
        if sample.get('error'): return 'Invalid / unavailable · '+sample['error']
        if sample: return 'No valid supported field / unavailable'
        return 'No observed positive response · unavailable'

    def latest_closed_session(self):
        if self.last_recording_id:
            return next((s for s in self.sessions if s['id']==self.last_recording_id and s['ended']),None)
        return None

    def capture_plan_status(self):
        ready=self.connected and self.discovery_prepared and self.source_key()==self.discovery_target and not self.requires_reconnect
        if ready and self.auto_receipt.get('context_id')==self.context_id and self.auto_receipt.get('ecu')==self.source_key() and self.capture_active and self.auto_receipt.get('worker_schedule_acknowledged_at'):
            return ready,True,dict(weights=self.capture_weights,raw_pids=list(self.capture_raw_pids),omitted=self.auto_receipt['requested_plan'].get('omitted',[]))
        plan=capture_plan(self.support,self.support_pages,self.discovery_observations,self.source_key(),prepared=ready,
                          selected=self.capture_selected(),raw_selected=self.raw_selected())
        configured=ready and self.source_key()==getattr(self,'capture_plan_ecu',None) and bool(plan['weights'])
        return ready,configured,plan

    def workflow_presentation(self):
        ready,configured,plan=self.capture_plan_status(); closed=self.latest_closed_session()
        finalized=bool(closed and not self.recording_id and not self.polling_active and not self.discovery_active
                       and not any(a in self.pending_actions for a in ('stop','record_stop')))
        pending=bool(self.pending_actions)
        if self.adapter_open and not self.connected and 'connect' not in self.pending_actions:
            key='reconnect'
        elif self.requires_reconnect and not self.recording_id and not finalized:
            key='reconnect'
        elif self.requires_reconnect and self.recording_id:
            key='finish'
        elif finalized:
            key='done' if self.exported_session_id==closed['id'] else 'export'
        elif self.capture_active and self.polling_active: key='finish'
        elif not self.connected: key='connect'
        elif not self.recording_id: key='record'
        elif not ready: key='discover'
        elif not configured: key='configure'
        else: key='capture'
        states=[(StepState.CURRENT if key=='reconnect' else StepState.COMPLETED if self.connected and self.source_key() in self.support else StepState.CURRENT if key=='connect' else StepState.AVAILABLE,
                 'ECU response observed on this connection' if self.connected else 'Select a source and connect; serial opening alone is not ECU verification'),
                (StepState.IN_PROGRESS if self.recording_id else StepState.CURRENT if key=='record' else StepState.AVAILABLE,
                 'Worker confirmed an active recording' if self.recording_id else 'Recording Off. Start before connection to retain initialization evidence'),
                (StepState.COMPLETED if ready else StepState.IN_PROGRESS if self.discovery_active else StepState.CURRENT if key=='discover' else StepState.BLOCKED,
                 'Discovery completed for this ECU in this context' if ready else 'Connect to an identified ECU; explicitly run standard Discovery'),
                (StepState.COMPLETED if configured else StepState.CURRENT if key=='configure' else StepState.AVAILABLE if ready else StepState.BLOCKED,
                 f'{len(plan["weights"])} eligible configured PIDs; preparation sends nothing' if configured else 'Complete Discovery for this ECU, prepare and review eligible choices'),
                (StepState.IN_PROGRESS if self.capture_active and self.polling_active else StepState.CURRENT if key=='capture' else StepState.AVAILABLE if configured else StepState.BLOCKED,
                 'Worker acknowledged active Drive Capture' if self.capture_active else 'Eligible configured PID selection and current ECU Discovery are required'),
                (StepState.COMPLETED if finalized else StepState.CURRENT if key=='finish' else StepState.AVAILABLE if self.recording_id else StepState.NOT_STARTED,
                 'Polling stopped and the recording is confirmed closed' if finalized else 'Finish an active recording or capture; connection remains a separate action'),
                (StepState.COMPLETED if finalized and self.exported_session_id==closed['id'] else StepState.CURRENT if key=='export' else StepState.AVAILABLE if closed else StepState.BLOCKED,
                 f'Private bundle saved: {self.bundle_destination}' if finalized and self.exported_session_id==closed['id'] else 'A confirmed closed recording is required')]
        self.capture_stepper.present(states); self.next_capture_action=key
        descriptions={
            'connect':('Connect' if self.source.currentIndex()==1 else 'Start Simulation','Choose the source above. You may start recording first to preserve initialization.'),
            'reconnect':('Disconnect before reconnecting' if self.adapter_open or self.connected else 'Connect explicitly','Reconnect required after communication failure. Disconnect the adapter, then connect explicitly; no automatic retry.'),
            'record':('Start recording','Recording is Off. '+self.source_identity()+'.'),
            'discover':('Start standard Discovery','Explicit scan for ECU '+str(self.source_key())+'. No automatic Discovery.'),
            'configure':('Prepare / review sensors','Prepare supported choices. NOx and RAW-only remain unchecked opt-ins.'),
            'capture':('Start Drive Capture',f'{len(plan["weights"])} eligible PIDs. '+('Recording active.' if self.recording_id else 'Monitoring only; no session is being recorded.')),
            'finish':('Finish session' if self.recording_id else 'Stop capture (not recording)','Drive Capture active. '+('Finish stops polling and closes the journal.' if self.recording_id else 'Monitoring only; no recording to export.')),
            'export':('Export Research Bundle','Polling stopped; recording completed. '+('Adapter remains connected.' if self.adapter_open or self.connected else 'Adapter disconnected.')+' Export private diagnostic evidence.'),
            'done':('Bundle exported','Private diagnostic evidence saved: '+str(self.bundle_destination))}
        label,help_text=descriptions[key]
        if key=='reconnect' and not self.requires_reconnect:
            help_text='The adapter is open but no ECU response is confirmed. Disconnect it before an explicit new connection. Any active recording is finalized by Disconnect.'
        if self.requires_reconnect and key=='finish': help_text='Communication failed; finish the active recording. Reconnect explicitly before further acquisition.'
        if pending: help_text='Awaiting worker confirmation: '+', '.join(self.pending_actions)+'. '+help_text
        self.capture_next.setText(label); self.capture_next_help.setText(help_text)
        self.capture_next.setEnabled(key!='done' and not pending and {'connect':self.connect_button,'record':self.record_button,
            'discover':self.discovery_start,'configure':self.capture_preset,'capture':self.capture_start,'finish':self.capture_finish,'export':self.capture_bundle,
            'reconnect':self.disconnect_button if self.adapter_open or self.connected else self.connect_button}.get(key,self.capture_next).isEnabled())
        self.capture_next.setToolTip(help_text)

    def perform_next_capture_action(self):
        action=getattr(self,'next_capture_action',None)
        buttons={'connect':self.connect_button,'record':self.record_button,'discover':self.discovery_start,
                 'configure':self.capture_preset,'capture':self.capture_start,'finish':self.capture_finish,'export':self.capture_bundle,
                 'reconnect':self.disconnect_button if self.adapter_open or self.connected else self.connect_button}
        if action=='connect': self.connection_panel.show()
        if action in buttons: buttons[action].click()

    def update_capture(self):
        if not hasattr(self,'capture_list'): return
        if hasattr(self,'auto_receipt_detail'): self.update_auto_capture()
        prepared,configured,plan=self.capture_plan_status()
        scanning=self.discovery_active and not self.polling_active
        automatic=self.auto_receipt.get('state') in {'WAITING_RAW','READY','PARTIAL'} and self.capture_active
        pending_auto=any(a in self.pending_actions for a in ('full_auto','retry_auto'))
        self.capture_preset.setEnabled(prepared and not scanning and 'discover' not in self.pending_actions and not automatic and not pending_auto)
        self.capture_start.setEnabled(configured and not scanning and 'drive_capture' not in self.pending_actions and not automatic and not pending_auto)
        closed=self.latest_closed_session()
        self.capture_bundle.setEnabled(not self.recording_id and bool(closed) and 'record_stop' not in self.pending_actions)
        selected=self.current_session()
        self.bundle_button.setEnabled(not self.recording_id and bool(selected and selected['ended']) and 'record_stop' not in self.pending_actions)
        self.capture_finish.setEnabled(bool(self.recording_id or self.capture_active) and not any(a in self.pending_actions for a in ('stop','record_stop')))
        self.capture_finish.setText('Stop capture (not recording)' if self.capture_active and not self.recording_id else 'Finish session')
        self.capture_finish.setToolTip('Stops polling and closes the active recording; adapter stays open unless the existing receive-cancel/failure safety requires reconnect' if self.recording_id else
                                       'Stops monitoring only; no active recording exists' if self.capture_active else 'No active recording or Drive Capture to finish')
        export_reason='Export a closed session as private diagnostic evidence; review before sharing' if closed else 'Finish a recording to make a closed session available'
        self.capture_bundle.setToolTip(export_reason)
        self.bundle_button.setToolTip('Select a closed session and finish any active recording before exporting private evidence')
        self.capture_identity.setText(self.source_identity()+' · ECU '+str(self.source_key() or 'no response observed'))
        recording='Active — worker confirmed' if self.recording_id else 'Off — no observations being recorded'
        if 'record' in self.pending_actions: recording='Off — awaiting worker start confirmation'
        if 'record_stop' in self.pending_actions: recording='Active — awaiting worker finish confirmation'
        self.capture_recording_note.setText('Recording: '+recording)
        values=self.warning_history.get(self.source_key(),[])
        counter=('No warning-time counter observations' if not values else 'One counter sample; trend unavailable' if len(values)==1
                 else f'Warning-time counter static across {len(values)} recent samples' if len(set(values))==1
                 else f'Warning-time counter changed across {len(values)} recent samples')
        self.capture_counter_note.setText(counter+'. Counter alone cannot establish a current SCR warning or fault. NOx (0183) is an unchecked manual option. RAW-only provides no numeric DPF pressure or SCR state.')
        for widget in (self.journey_start,self.journey_end,self.note_button,self.marker_note,self.phase_note_button,self.journey_phase,self.journey_uncertainty):
            widget.setEnabled(bool(self.recording_id) and self.mode!='REPLAY')
        pids=[0x8B,0x7A,0x7C,0x0C,0x0D,0x05,0x85] if self.capture_focus.isChecked() else (list(self.capture_weights) if self.capture_active else list(dict.fromkeys(self.capture_selected()+self.raw_selected())) or list(dict.fromkeys([12,13,5,16]+list(DRIVE_WEIGHTS))))
        if not self.capture_focus.isChecked() and not self.capture_technical.isChecked():
            order=[12,13,5,0x8B,0x7A,0x85,0x83,0x88,0x7C,0x78,0x10]
            pids=[p for p in order if p in pids]+[p for p in pids if p not in order]
        self.capture_table.setRowCount(len(pids))
        for row,pid in enumerate(pids):
            sensor=STANDARD_DIESEL.get(pid) or self.registry[pid]
            sample=self.discovery_observations.get((self.source_key(),pid),{})
            suffix={0x8B:'_regeneration',0x7A:'_delta_pressure',0x7C:'_bank_1_inlet',0x78:'_bank_1_sensor_1',0x85:'_tank_level'}.get(pid)
            field=next((f for f in sample.get('fields',[]) if not suffix or f.get('sensor_id','').endswith(suffix)),{})
            value,unit='—',field.get('unit','')
            state=self.unavailable_reason(pid)
            times=self.capture_history.get((self.source_key(),pid),[])
            gaps=[b-a for a,b in zip(times,list(times)[1:]) if b>a]
            interval=f'{sum(gaps)/len(gaps):.2f} s' if gaps else 'No interval yet'
            presentation=self.sample_presentation(pid,sample); age=presentation['age']; current=presentation['current']
            if field.get('state')=='AVAILABLE' and field.get('value') is not None and support_state(self.support.get(self.source_key(),set()),self.support_pages.get(self.source_key(),set()),pid)=='supported':
                value=field.get('display',field['value'])
                if isinstance(value,(int,float)): value=f'{value:.2f}'
                state=presentation['text']
            if presentation['raw']:
                value,unit='—',''
                layout='Numeric interpretation disabled' if sample.get('layout_status')=='STANDARD_DOCUMENTED' else 'No verified numeric decoder'
                state=('Current raw sample' if current else 'REPLAY / recorded raw' if sample.get('replay') else 'Stale raw sample')+' · RAW ONLY · '+layout+' · '+presentation['acquisition']+' · '+presentation['origin']
            gap=f'age {max(0,age):.2f} s' if age is not None else '—'
            if gaps: gap+=f' / max {max(gaps):.2f} s'
            name=HUMAN_NAMES.get(pid,field.get('name',sensor.name))
            update_row(self.capture_table,row,[name,value,unit,state,interval,gap,self.capture_weights.get(pid,'—')])
            self.capture_table.item(row,0).setData(Qt.ItemDataRole.UserRole,pid)
            self.capture_table.item(row,0).setToolTip(f'{sensor.name} · PID 01{pid:02X} · current ECU/scenario evidence only')
            self.capture_table.item(row,3).setToolTip(presentation['detail']+'\n'+state+'\n'+str(sample.get('layout_status','')))
        monitor_errors=self.capture_monitor_errors
        details=f'Capture: {"ACTIVE" if self.capture_active and self.polling_active else "not active"} · ECU {self.source_key() or "—"} · {len(self.capture_weights) if self.capture_active else len(self.capture_selected())+len(self.raw_selected())} PIDs · Polling {"active" if self.polling_active else "stopped"} · Recording {"active" if self.recording_id else "off"} · Monitoring errors {monitor_errors} · Total transaction errors {self.error_count} (includes intentional cancellations)'
        simple=f'Drive Capture {"running" if self.capture_active and self.polling_active else "not running"} · {len(self.capture_weights) if self.capture_active else len(plan["weights"])} configured PIDs · '+('Discovery complete for this ECU' if prepared else 'Discovery needed for this ECU')
        if monitor_errors: simple+=f' · {monitor_errors} monitoring errors; inspect technical details'
        self.capture_summary.setText(details if self.capture_technical.isChecked() else simple); self.capture_summary.setToolTip(details)
        self.capture_preset.setToolTip('Prepare choices; no commands sent' if prepared else 'Complete standard Discovery for the selected ECU in this connection; reconnect after failures')
        self.capture_start.setToolTip('Start acquisition explicitly; '+('recording active' if self.recording_id else 'monitoring only, Recording Off') if configured else
                                      'Complete current ECU Discovery, prepare a preset and select at least one eligible PID')
        self.workflow_presentation()
        raw_details=[]
        for pid in sorted(RAW_ONLY_PIDS):
            sample=self.discovery_observations.get((self.source_key(),pid),{})
            if sample.get('payload_hex'):
                raw_details.append(dict(request=f'01{pid:02X}',**sample))
        self.capture_raw_detail.setPlainText(json.dumps(raw_details,ensure_ascii=False,indent=2) if raw_details else 'RAW evidence appears after discovery; no numerical interpretation of an unknown layout.')

    def build_discovery(self):
        tab = QWidget(); layout = QVBoxLayout(tab); layout.setContentsMargins(0,4,0,0)
        page_heading(layout, 'Standard PID discovery', 'Explicit scans for the selected ECU. Support and a positive reply are separate evidence.')
        message = QLabel('Standard Mode 01 only. Start discovery explicitly for the selected ECU. Unsupported/unknown PIDs are never probed. Samples remain vehicle-unverified; OEM candidates are offline only.')
        message.setWordWrap(True); layout.addWidget(message)
        source_row = QHBoxLayout(); source_row.addWidget(QLabel('ECU:'))
        self.discovery_ecu = QComboBox(); self.discovery_ecu.setModel(self.ecu.model())
        self.discovery_ecu.currentIndexChanged.connect(self.ecu.setCurrentIndex)
        self.ecu.currentIndexChanged.connect(self.discovery_ecu.setCurrentIndex)
        source_row.addWidget(self.discovery_ecu,1)
        self.discovery_filter = QComboBox(); self.discovery_filter.addItems(['All systems','Engine','DPF','Exhaust','SCR/AdBlue','NOx'])
        self.discovery_filter.currentTextChanged.connect(self.update_discovery)
        source_row.addWidget(self.discovery_filter); layout.addLayout(source_row)
        row = FlowLayout()
        self.discovery_start = self.button('Scan standard PIDs for selected ECU', lambda: self.send('discover', ecu=self.source_key()))
        self.discovery_monitor = self.button('Monitor available standard PIDs', lambda: self.send('monitor_discovery', ecu=self.source_key()))
        self.discovery_stop=self.button('Stop polling / discovery',lambda:self.send('stop'),'stop')
        for w in (self.discovery_start,self.discovery_monitor,self.discovery_stop,
                  self.button('Export discovery report…',self.export_discovery)): row.addWidget(w)
        layout.addLayout(row)
        self.discovery_status = QLabel(); self.discovery_status.setWordWrap(True); layout.addWidget(self.discovery_status)
        self.discovery_status.setMinimumHeight(32)
        self.discovery_table = table(['System','Parameter / request','ECU','PID support','Availability','Evidence','Verification','Latest sample (UTC)'])
        self.discovery_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        for col,width in enumerate([100,290,100,110,155,160,175,200]): self.discovery_table.setColumnWidth(col,width)
        self.discovery_table.itemSelectionChanged.connect(self.discovery_details)
        layout.addWidget(self.discovery_table,1)
        self.discovery_inspect=QCheckBox('Inspect selected parameter · original bytes and exact evidence'); layout.addWidget(self.discovery_inspect)
        self.discovery_detail = QTextEdit(); self.discovery_detail.setReadOnly(True); self.discovery_detail.setMinimumHeight(130); self.discovery_detail.setMaximumHeight(190)
        self.discovery_inspect.toggled.connect(self.discovery_detail.setVisible); layout.addWidget(self.discovery_detail); self.discovery_detail.hide()
        self.tabs.addTab(tab,'Discovery')
        self.update_discovery()

    def update_discovery(self, *args):
        self.discovery_data = discovery_report(self.support,self.support_pages,self.discovery_observations,
                                                mode=self.mode,context_id=self.context_id)
        system = self.discovery_filter.currentText()
        self.discovery_rows = [e for e in self.discovery_data['standard']+self.discovery_data['manufacturer_candidates']
                               if system == 'All systems' or e['system']==system or (system=='NOx' and e.get('pid')=='83')]
        self.discovery_table.setRowCount(len(self.discovery_rows))
        for row,e in enumerate(self.discovery_rows):
            sample = e.get('sample',{})
            pid=int(e['pid'],16) if e.get('pid') else None
            update_row(self.discovery_table,row,[e['system'],HUMAN_NAMES.get(pid,e['name'])+' / '+e['request'],e.get('ecu','Offline candidate'),
                       e['support'],e.get('availability','RESEARCH_ONLY'),
                       ('REPLAY · ' if sample.get('replay') else 'SAMPLE · ' if sample else '')+(e.get('evidence','NO_SAMPLE') if 'sample' in e else 'RESEARCH_ONLY'),
                       e['verification']+' / vehicle UNVERIFIED',sample.get('timestamp','—')])
            self.discovery_table.item(row,1).setToolTip(e['name']+' · '+e['request']+'\nCurrent ECU/scenario evidence only')
            if pid is not None:
                support=e['support']
                explanation=('Not supported in selected simulation scenario' if self.mode=='SIMULATED' else 'Not supported by this ECU') if support=='UNSUPPORTED' else 'Discovery support not completed / unknown' if support=='UNKNOWN' else self.unavailable_reason(pid)
                self.discovery_table.item(row,4).setToolTip(explanation+'\n'+e.get('availability','UNKNOWN'))
        counts = {s:sum(e.get('availability')==s for e in self.discovery_data['standard'])
                  for s in ('AVAILABLE','UNSUPPORTED','UNKNOWN','UNVERIFIED','NO_SUPPORTED_FIELDS','INVALID / UNVERIFIED')}
        selected=[e for e in self.discovery_data['standard'] if e.get('ecu')==self.source_key()]
        supported=sum(e['support']=='SUPPORTED' for e in selected); unsupported=sum(e['support']=='UNSUPPORTED' for e in selected)
        unknown=sum(e['support']=='UNKNOWN' for e in selected)
        positive=sum(bool(e.get('sample')) and not e.get('sample',{}).get('error') for e in selected)
        unverified=sum('UNVERIFIED' in e.get('availability','') for e in selected)
        self.discovery_status.setText(f'ECU {self.source_key() or "—"} · {"Discovery running" if self.discovery_active else self.discovery_reason}\nSupported {supported} · Unsupported {unsupported} · Unknown {unknown} · Observed samples {positive} · Unverified layouts {unverified}')
        self.discovery_status.setToolTip(', '.join(f'{s}: {n}' for s,n in counts.items()))
        can=self.connection_protocol.upper() in {'6','7','8','9','A6','A7','A8','A9'} or '15765' in self.connection_protocol
        allowed = self.connected and self.source_key() in self.support and self.source_key()!='headerless' and can and self.mode != 'REPLAY' and not self.requires_reconnect and not self.discovery_active and 'discover' not in self.pending_actions
        self.discovery_start.setEnabled(allowed)
        self.discovery_monitor.setEnabled(allowed and self.discovery_prepared and self.source_key()==self.discovery_target)
        self.discovery_start.setToolTip('Connect explicitly; hardware failure requires reconnect' if not allowed else 'Read standard supported PIDs only; selected ECU')
        self.discovery_monitor.setToolTip('Complete discovery for this ECU first; unknown or unsupported PIDs cannot be monitored')
        self.discovery_stop.setEnabled(self.stop_button.isEnabled()); self.discovery_stop.setToolTip('Stop acquisition; recording and adapter connection remain independent' if self.discovery_stop.isEnabled() else 'Polling and Discovery are already stopped')
        self.discovery_details()

    def discovery_details(self):
        row = self.discovery_table.currentRow()
        if 0 <= row < len(getattr(self,'discovery_rows',[])):
            self.discovery_detail.setPlainText(json.dumps(self.discovery_rows[row],ensure_ascii=False,indent=2))
        else: self.discovery_detail.setPlainText('Select a parameter for its raw payload, fields, support flags, formula, units, edition, source links and verification evidence. OEM requests have no transmit control.')

    def export_discovery(self):
        path,_ = QFileDialog.getSaveFileName(self,'Export discovery evidence',str(self.root/'discovery-report.json'),'JSON (*.json)')
        if path:
            try:
                self.update_discovery()
                Path(path).write_text(json.dumps(self.discovery_data,ensure_ascii=False,indent=2),encoding='utf-8')
                self.notice('Discovery report exported; timestamps and source evidence retained. Vehicle verification remains pending.')
            except Exception as exc: self.notice(str(exc))

    def update_measurements(self):
        source = self.source_key()
        checked = [self.sensor_list.item(i) for i in range(self.sensor_list.count())
                   if self.sensor_list.item(i).checkState() == Qt.CheckState.Checked]
        self.dashboard.setRowCount(len(checked))
        now = time.monotonic()
        weights = priority_weights([i.data(Qt.ItemDataRole.UserRole) for i in checked
                                    if i.data(Qt.ItemDataRole.UserRole) in self.support.get(source, set())],
                                   self.priorities if self.use_priorities.isChecked() else {})
        schedule_weights = self.schedule_weights()
        if self.capture_active:
            weights={p:w for p,w in self.capture_weights.items() if p in weights}
        current, states = 0, {}
        for index, item in enumerate(checked):
            pid = item.data(Qt.ItemDataRole.UserRole); sensor = self.registry[pid]
            reading = self.readings.get((source, pid))
            key = source, pid
            state, value, unit, stamp, hz = "Unavailable", "—", sensor.unit, "—", "—"
            evidence, interval, gap = "No evidence", "—", "—"
            if source in self.support:
                availability = support_state(self.support[source], self.support_pages.get(source, set()), pid)
                if availability == "unsupported": state = "Not supported"
                elif availability == "unknown": state = "Support unknown"
            error = self.sensor_errors.get(key, "")
            if error and state != "Not supported": state = "ECU rejected / unavailable" if "7F 01" in error else "Invalid / unavailable"
            if reading:
                presentation=self.sample_presentation(pid,reading)
                age = now - reading["received_at"]
                replay = reading["mode"].startswith("REPLAY")
                evidence = ("REPLAY · " if replay else "") + reading.get("source_kind", "UNKNOWN")
                valid = presentation['current']
                state = "Recorded (offline)" if replay else "Valid" if valid else "Stale (last success)"
                reason = presentation['reason']
                if reason and not valid: state += " · " + reason
                current += valid
                converted, unit = convert(reading["value"], sensor.unit, self.units.isChecked())
                value, stamp = f"{converted:.2f}" + (" (last)" if not valid and not replay else ""), reading["timestamp"]
                times = self.history.get(key, [])
                deltas = [b - a for a, b in zip(times, list(times)[1:]) if b > a]
                if deltas:
                    interval = f"{sum(deltas)/len(deltas):.2f} s"
                    hz = f"{len(deltas)/sum(deltas):.2f} Hz"
                gap = (f"recorded max {max(deltas):.2f} s" if deltas else "recorded") if replay else f"age {max(0., age):.2f} s"
                if deltas and not replay: gap += f" / max {max(deltas):.2f} s"
            states[pid] = state + " / " + evidence
            update_row(self.dashboard, index, [sensor.name, value, unit, state, hz, stamp, source or "—", evidence,
                                              interval, gap, weights.get(pid, "—")])
            self.dashboard.item(index, 3).setToolTip(self.sample_presentation(pid,reading)['detail'] if reading else self.unavailable_reason(pid))
            color = COLORS['warning'] if state.startswith("Stale") else COLORS['error'] if "Invalid" in state or "rejected" in state else COLORS['accent'] if state == "Valid" else COLORS['muted']
            self.dashboard.item(index, 3).setForeground(QColor(color))
        self.coverage.setText(f'ECU: {source or "—"} | selected supported: {len(weights)}/{len(checked)} | current: {current}/{len(weights)} | {self.acquisition_reason}')
        self.banner.setText(self.source_identity()+' · ECU '+str(source or 'no response observed')+
                            (' · offline replay' if self.mode=='REPLAY' else ' · '+self.acquisition_mode() if self.polling_active or self.discovery_active else ' · polling stopped; values stale')+
                            (' · Recording active' if self.recording_id else ' · Recording Off'))
        if self.explorer.rowCount() == 0:
            for s in self.registry.values():
                add_row(self.explorer, [s.name, f"01{s.pid:02X}", f'01 / {s.metadata["positive_response"]}', "—", s.metadata["layout"], s.metadata["formula"], s.unit, "—", s.metadata["verification"], "—", "—", "Unavailable"])
            self.explorer.selectRow(0)
        for row, sensor in enumerate(self.registry.values()):
            reading = self.readings.get((source, sensor.pid))
            verification = "UNSUPPORTED" if source in self.support and support_state(self.support[source], self.support_pages.get(source, set()), sensor.pid) == "unsupported" else sensor.metadata["verification"]
            nominal = f"{nominal_interval(sensor.pid, schedule_weights, self.rate.value()):.2f} s nominal" if sensor.pid in schedule_weights else "Not scheduled"
            for col, val in [(3, source or "—"), (7, nominal),
                             (8, verification), (9, f'{reading["value"]:.3f}' if reading else "—"), (10, reading["timestamp"] if reading else "—"),
                             (11, states.get(sensor.pid, "Not selected / last evidence only"))]:
                self.explorer.item(row, col).setText(val)

    def drain(self):
        import queue
        for _ in range(100):
            try: kind, value = self.worker.events.get_nowait()
            except queue.Empty: break
            if kind == "notice": self.notice(value)
            elif kind=='benchmark':self.benchmark_state=value;self.session_panel.update()
            elif kind=='session_state': self.session_panel.acknowledge(value)
            elif kind=='session_rejected':
                self.notice(value)
                for action in ('session_start','session_finish','session_export_retry'): self.pending_actions.pop(action,None)
            elif kind == 'auto_reset':
                if value.get('context_id')==self.context_id: self.auto_receipt={}; self._auto_signature=None
            elif kind == 'auto_rejected':
                if value.get('context_id')==self.context_id:
                    self.pending_actions.pop('full_auto',None); self.pending_actions.pop('retry_auto',None)
                    self.auto_rejection_reason=value['reason']; self._auto_signature=None
            elif kind == 'auto_capture':
                if value.get('context_id')!=self.context_id and value.get('state') not in {'RECORDING','CONNECTING'}: continue
                self.auto_receipt=value
                if value.get('state') in {'WAITING_RAW','READY','PARTIAL','ABORTED','FINISHED'}:
                    self.pending_actions.pop('full_auto',None); self.pending_actions.pop('retry_auto',None)
                if value.get('state') in {'WAITING_RAW','READY','PARTIAL'}:
                    self.capture_plan_ecu=value.get('ecu')
                    if self.ecu.findData(value.get('ecu'))>=0: self.ecu.setCurrentIndex(self.ecu.findData(value.get('ecu')))
            elif kind == "context":
                if not any(a in self.pending_actions for a in ('full_auto','retry_auto')): self.auto_receipt={}
                self.context_id, self.mode = value["id"], value["mode"]
                self.connection_protocol=''
                self.accept_transactions=True
                self.pending_actions={a:c for a,c in self.pending_actions.items() if a in {'connect','record','full_auto','retry_auto'}}
                self.exported_session_id=None; self.bundle_destination=None
                if not self.recording_id: self.last_recording_id=None
                self.readings.clear(); self.history.clear(); self.sensor_errors.clear(); self.signal_values.clear()
                self.support.clear(); self.support_pages.clear()
                self.discovery_observations.clear(); self.discovery_active = False
                self.discovery_prepared = False; self.discovery_target = None
                self.capture_active=False; self.capture_weights.clear(); self.capture_raw_pids.clear(); self.capture_history.clear(); self.warning_history.clear()
                self.capture_monitor_errors=0
                self.capture_list.clear(); self.capture_plan_ecu=None
                for check in self.capture_raw_checks.values(): check.setChecked(False); check.setEnabled(False)
                self.marker_table.setRowCount(0)
                self.discovery_reason = 'New connection/replay context; no discovery evidence'
                self.ecu.clear(); self.ecu.addItem("Automatic first responding ECU", "")
                self.rejection_reason.clear()
                self.polling_active = False
                self.connected = False
                self.acquisition_reason = "Replay paused" if self.mode == "REPLAY" else "Opening connection"
                self.requires_reconnect = False
            elif kind == "acquisition":
                self.polling_active = value["polling"] and not self.user_paused
                self.acquisition_reason = value["reason"]
                self.requires_reconnect = value["requires_reconnect"]
                if value['polling']: self.pending_actions.pop('start',None)
                else: self.pending_actions.pop('stop',None)
                if not self.polling_active and not self.discovery_active:
                    self.discovery_reason = 'Polling stopped; latest samples are recorded evidence'
            elif kind == 'discovery':
                if value.get('context_id') != self.context_id: continue
                self.discovery_active = value['active']; self.discovery_reason = value['reason']
                self.discovery_prepared = value.get('prepared',False); self.discovery_target = value.get('target')
                if value['active'] and not self.polling_active and not self.capture_active:
                    self.capture_plan_ecu=None; self.capture_list.clear()
                    for check in self.capture_raw_checks.values(): check.setChecked(False); check.setEnabled(False)
                if value['active'] or value.get('prepared') or 'ended' in value.get('reason','').lower(): self.pending_actions.pop('discover',None)
            elif kind == 'capture':
                if value.get('context_id')!=self.context_id: continue
                if value['active'] and not self.capture_active: self.capture_error_baseline=self.error_count; self.capture_monitor_errors=0
                self.capture_active=value['active']; self.capture_weights=value['weights']; self.capture_ecu=value['ecu']
                self.capture_raw_pids=set(value.get('raw_pids',[]))
                if value['active'] or 'eligible' in value.get('reason','').lower(): self.pending_actions.pop('drive_capture',None)
                if value['active']: self.capture_sections.setCurrentIndex(0)
                self.capture_status.setText(value['reason'])
            elif kind == 'marker':
                if value.get('context_id')!=self.context_id: continue
                if self.marker_table.rowCount()>=100: self.marker_table.removeRow(0)
                add_row(self.marker_table,[value['timestamp'],value['event']+(' · '+value.get('phase','') if value['event']=='Phase' else ''),
                        value.get('note','')+(' · REPLAY / recorded' if value.get('replay') else ' · local marker; no ECU request')])
            elif kind == "connection":
                self.mode = value["mode"]
                self.connected = value["ecu"] == "Connected"
                self.connection_phase=value['ecu']
                self.connection_protocol=value['protocol']
                self.adapter_open=value['adapter'] not in {'Disconnected','Offline'} and self.mode!='REPLAY'
                if self.connected or value['ecu']=='No verified ECU response': self.pending_actions.pop('connect',None)
                if value['adapter']=='Disconnected':
                    self.pending_actions.pop('disconnect',None)
                    for action in ('drive_capture','discover','start','stop'): self.pending_actions.pop(action,None)
                    if 'connect' in self.pending_actions and self.pending_actions['connect']!=self.context_id: self.pending_actions.pop('connect',None)
                if self.connected: self.connection_panel.hide()
                self.status.setText(f'Adapter: {value["adapter"]}   |   ECU: {value["ecu"]}   |   Protocol: {value["protocol"]}')
                self.connect_button.setEnabled(value["adapter"] == "Disconnected" or value["ecu"] in {"Connected", "No verified ECU response", "Replay paused"})
            elif kind == "support":
                self.support = value
                for source in value:
                    if self.ecu.findData(source) < 0: self.ecu.addItem(source, source)
            elif kind == "support_pages": self.support_pages = value
            elif kind == "recording":
                if value:
                    if value!=self.recording_id: self.exported_session_id=None; self.bundle_destination=None
                    self.last_recording_id=value
                    self.pending_actions.pop('record',None)
                else: self.pending_actions.pop('record_stop',None)
                self.recording_id = value; self.recording_started = time.monotonic() if value else None
                self.refresh_sessions()
            elif kind == "transaction":
                record, readings = value
                if not self.accept_transactions: continue
                if self.context_id and record.get("context_id", self.context_id) != self.context_id: continue
                self.request_count += 1; self.error_count += record["status"] != "OK"
                if self.capture_active and record['status'] not in {'OK','CANCELLED'} and record.get('pid') and int(record['pid'],16) in self.capture_weights:
                    self.capture_monitor_errors+=1
                if len(self.raw_records) == 500: self.raw_table.removeRow(0)
                self.raw_records.append(record)
                add_row(self.raw_table, [record["timestamp"], record["command"], record["status"], f'{record["latency_ms"]:.1f}',
                    ', '.join(x["ecu"] or "headerless" for x in record["parsed"] + record.get("negative_responses", [])),
                    ' / '.join(x["data_hex"] for x in record["parsed"]), ', '.join(record["decoder"]), record["error"]])
                for reading in readings:
                    source = reading["ecu"] or "headerless"
                    if self.ecu.findData(source) < 0: self.ecu.addItem(source, source)
                    if not self.source_key(): self.ecu.setCurrentIndex(self.ecu.findData(source))
                    if reading['pid'] in STANDARD_DIESEL: continue
                    key = source, reading["pid"]
                    replay = record.get("replay", False)
                    sent_at = reading["monotonic_ns"] / 1e9
                    metadata=dict(context_id=self.context_id,acquisition_mode=self.acquisition_mode(),recording_session=self.recording_id)
                    self.readings[key] = dict(reading, **metadata, received_at=time.monotonic() if replay else sent_at, invalid=False)
                    self.sensor_errors.pop(key, None)
                    self.history.setdefault(key, deque(maxlen=20)).append(sent_at)
                    self.signal_values.setdefault((source,reading['pid'],reading['mode'],reading.get('source_kind','UNKNOWN')),deque(maxlen=240)).append((sent_at,reading['value']))
                    self.discovery_observations[key] = {'ecu':reading['ecu'],'pid':reading['pid'],
                        'fields':[dict(state='AVAILABLE',name=self.registry[reading['pid']].name,value=reading['value'],unit=self.registry[reading['pid']].unit)],
                        'timestamp':reading['timestamp'],'source_kind':reading.get('source_kind','UNKNOWN'),'replay':replay}
                    self.discovery_observations[key].update(metadata,mode=reading['mode'])
                    self.discovery_observations[key]['monotonic_ns']=reading['monotonic_ns']
                    self.capture_history.setdefault(key,deque(maxlen=30)).append(sent_at)
                for sample in record.get('discovery_samples',[]):
                    self.discovery_observations[sample['ecu'] or 'headerless',sample['pid']] = dict(sample,context_id=self.context_id,
                        acquisition_mode=self.acquisition_mode(),recording_session=self.recording_id,mode=self.mode)
                    if sample['pid']==0x85 and not sample.get('error'):
                        field=next((f for f in sample['fields'] if f.get('sensor_id','').endswith('_warning_time') and f.get('state')=='AVAILABLE'),None)
                        if field: self.warning_history.setdefault(sample['ecu'] or 'headerless',deque(maxlen=30)).append(field['value'])
                    if sample.get('monotonic_ns') and not sample.get('error') and (sample.get('raw_only') or any(f['state']=='AVAILABLE' for f in sample['fields'])):
                        self.capture_history.setdefault((sample['ecu'] or 'headerless',sample['pid']),deque(maxlen=30)).append(sample['monotonic_ns']/1e9)
                for problem in record.get('protocol_errors',[]):
                    source = problem['ecu'] or (self.capture_ecu if self.capture_active else None) or 'unknown'
                    if record.get('pid'):
                        pid = int(record['pid'],16)
                        self.sensor_errors[source,pid] = problem['reason']
                        if (source,pid) in self.readings: self.readings[source,pid]['invalid'] = True
                        previous = self.discovery_observations.get((source,pid),{})
                        self.discovery_observations[source,pid] = dict(previous,error=problem['reason'])
                        if problem.get('category')!='DECODER_LAYOUT':
                            self.discovery_observations[source,pid].update(framing_valid=False,raw_only=False,layout_status='INVALID_RESPONSE')
                for rejection in record.get("negative_responses", []):
                    source = rejection["ecu"] or "headerless"
                    reason = f'{source}: {rejection["reason"]} (7F 01 {rejection["nrc"]})'
                    self.rejection_reason.setText(("Recorded " if record.get("replay") else "ECU rejection: ") + reason + "; not a transport timeout. Ignition state is not confirmed.")
                    if record.get("pid"):
                        pid = int(record["pid"], 16)
                        previous = self.discovery_observations.get((source,pid),{})
                        self.discovery_observations[source,pid] = dict(previous,error=reason)
                        self.sensor_errors[source, pid] = reason
                        for (ecu, p), reading in self.readings.items():
                            if ecu == source and (p == pid or rejection["nrc"] == "22"):
                                reading["stale_reason"] = reason
                        for (ecu,p), sample in self.discovery_observations.items():
                            if ecu==source and (p==pid or rejection['nrc']=='22'): sample['stale_reason']=reason
                if record["status"] in {"INVALID", "TRANSPORT_ERROR"} and not record.get('protocol_errors') and record.get("pid"):
                    pid = int(record["pid"], 16)
                    for source in self.support: self.sensor_errors[source, pid] = record["error"]
                    for (source, p), reading in self.readings.items():
                        if p == pid: reading["invalid"] = True
        self.update_measurements()
        self.update_discovery()
        self.update_capture()
        duration = time.monotonic() - self.recording_started if self.recording_started else 0
        self.stats.setText(f'Recording: {self.recording_id[:12] if self.recording_id else "off"}  {duration:.1f}s   |   Requests: {self.request_count}   |   Errors: {self.error_count}   |   Dropped UI previews: {self.worker.dropped}')
        self.record_button.setEnabled(not self.recording_id)
        self.record_stop_button.setEnabled(bool(self.recording_id))
        self.session_panel.update()
        self.refresh_presentation()

    def arrange_cards(self):
        cols = 3 if self.width() < 1600 else 4
        for i,card in enumerate(self.sensor_cards): self.cards_grid.addWidget(card,i//cols,i%cols)

    def refresh_presentation(self):
        self.update_connection_controls()
        record_allowed=not self.recording_id and self.mode!='REPLAY' and not any(a in self.pending_actions for a in ('record','record_stop','disconnect'))
        finish_allowed=bool(self.recording_id) and 'record_stop' not in self.pending_actions
        for button in (self.record_button,self.session_record_button,self.capture_record):
            button.setEnabled(record_allowed); button.setToolTip(self.source_identity()+'\nSynthetic evidence only.' if 'SIMULATION' in self.source_identity() else
                self.source_identity()+'\nECU '+str(self.source_key() or 'not yet observed')+'. Recording can begin before connection.')
            if self.mode=='REPLAY': button.setToolTip('Replay is offline evidence; recording replay is disabled')
        for button in (self.record_stop_button,self.session_finish_button,self.capture_record_stop):
            button.setEnabled(finish_allowed); button.setToolTip('Close the active journal; polling and connection are independent' if self.recording_id else 'Recording is Off; no active journal to finish')
        self.rejection_reason.setVisible(bool(self.rejection_reason.text()))
        state = 'Connected' if self.connected else 'Adapter connected / no ECU response' if self.adapter_open and self.connection_phase=='No verified ECU response' else 'Adapter initializing / no ECU confirmed' if self.adapter_open else 'Connecting' if 'connect' in self.pending_actions else 'Disconnected'
        source = self.source_identity()
        activity = 'Replay' if self.mode=='REPLAY' else 'Drive Capture' if self.capture_active else 'Discovery' if self.discovery_active else 'Idle'
        ecu_state=self.source_key()+' · last response; reconnect required' if self.requires_reconnect and self.source_key() else self.source_key()+' · response observed' if self.connected and self.source_key() else self.source_key()+' · recorded' if self.mode=='REPLAY' and self.source_key() else 'No current ECU confirmed'
        values = {'Source':source,'Connection':state,'ECU':ecu_state,'Polling':'Active' if self.polling_active else 'Stopped','Recording':'Active' if self.recording_id else 'Off','Activity':activity}
        for name,value in values.items():
            label=self.status_indicators[name]; label.setText(f'{name}: {value}'); label.setAccessibleName(f'{name}: {value}'); label.setToolTip(self.status.text() if name=='Connection' else label.text())
        self.filter_raw(); self.filter_explorer(); self.refresh_cards(); self.refresh_signal_chart()
        if hasattr(self,'session_panel'): self.session_panel.update()

    def refresh_cards(self):
        if not hasattr(self,'capture_focus'): return
        rows=[]
        if self.focus_dashboard.isChecked():
            for i in range(self.capture_table.rowCount()):
                cells=[self.capture_table.item(i,c).text() for c in range(self.capture_table.columnCount())]
                pid=self.capture_table.item(i,0).data(Qt.ItemDataRole.UserRole)
                if support_state(self.support.get(self.source_key(),set()),self.support_pages.get(self.source_key(),set()),pid)=='unsupported': continue
                rows.append((cells[0],cells[1],cells[2],cells[3],f'ECU {self.source_key() or "—"} · {cells[5]}'))
            # UI-only replacements come from positive, supported basic readings.
            # This never selects, schedules or probes a sensor.
            eligible=[]
            for i in range(self.dashboard.rowCount()):
                cells=[self.dashboard.item(i,c).text() for c in range(self.dashboard.columnCount())]
                if cells[1]=='—' or cells[3].startswith(('Invalid','ECU rejected','Not supported')): continue
                pid=next(p for p,d in self.registry.items() if d.name==cells[0])
                if support_state(self.support.get(self.source_key(),set()),self.support_pages.get(self.source_key(),set()),pid)!='supported': continue
                eligible.append((pid,(cells[0],cells[1],cells[2],cells[3],f'ECU {cells[6]} · {cells[9]} · {cells[7]}')))
            choice=self.focus_replacement.currentData()
            options=[(None,'Automatic eligible readings')]+[(pid,entry[0]) for pid,entry in eligible]
            if [(self.focus_replacement.itemData(i),self.focus_replacement.itemText(i)) for i in range(self.focus_replacement.count())]!=options:
                self.focus_replacement.blockSignals(True); self.focus_replacement.clear()
                for pid,name in options: self.focus_replacement.addItem(name,pid)
                self.focus_replacement.setCurrentIndex(max(0,self.focus_replacement.findData(choice))); self.focus_replacement.blockSignals(False)
            if choice is not None:
                replacement=next((entry for pid,entry in eligible if pid==choice),None)
                if replacement and not any(row[0]==replacement[0] for row in rows): rows=(rows[:6]+[replacement])
            for _,entry in eligible:
                if len(rows)>=7: break
                if not any(row[0]==entry[0] for row in rows): rows.append(entry)
        else:
            for pid in (12,13,5,16,11,15):
                sensor=self.registry.get(pid)
                if not sensor: continue
                i=next((r for r in range(self.dashboard.rowCount()) if self.dashboard.item(r,0).text()==sensor.name),None)
                if i is None: rows.append((sensor.name,'—',sensor.unit,'Not selected',f'ECU {self.source_key() or "—"} · no sample'))
                else:
                    cells=[self.dashboard.item(i,c).text() for c in range(self.dashboard.columnCount())]
                    state={'Unavailable':'No sample yet','Not supported':'Unsupported PID','Support unknown':'Support not observed','Valid':'Current sample'}.get(cells[3],cells[3])
                    reading=self.readings.get((self.source_key(),pid))
                    if reading:
                        presentation=self.sample_presentation(pid,reading)
                        state=presentation['text']
                    else: state=self.unavailable_reason(pid)
                    age=(f'age {max(0,presentation["age"]):.2f} s' if presentation['age'] is not None else 'recorded time') if reading else 'no sample'
                    recorded=('Recorded' if presentation['recording']=='Recorded in current session' else 'Not recorded') if reading else ''
                    rows.append((cells[0],cells[1].replace(' (last)',''),cells[2],state,f'ECU {cells[6]} · {age}'+(' · '+recorded if recorded else '')))
        for i,card in enumerate(self.sensor_cards):
            card.setVisible(i<len(rows))
            if i<len(rows):
                card.present(*rows[i])
                pid=next((p for p,s in self.registry.items() if s.name==rows[i][0]),None)
                reading=self.readings.get((self.source_key(),pid))
                if reading: card.setToolTip(card.toolTip()+'\n'+self.sample_presentation(pid,reading)['detail'])

    def refresh_signal_chart(self, *args):
        if not hasattr(self,'signal_chart'): return
        pid=self.trend_sensor.currentData(); source=self.source_key()
        reading=self.readings.get((source,pid),{})
        key=(source,pid,reading.get('mode'),reading.get('source_kind','UNKNOWN'))
        points=list(self.signal_values.get(key,[])); alternate=self.units.isChecked()
        signature=(key,tuple(points),alternate)
        if signature==self._chart_signature: return
        self._chart_signature=signature; self.signal_chart.removeAllSeries()
        sensor=self.registry[pid]
        if len(points)<2:
            self.signal_chart.setTitle('No trend yet · at least two acquired samples required'); self.trend_note.setText('No interpolation or additional requests')
        else:
            series=QScatterSeries(); series.setMarkerSize(5); series.setColor(QColor('#77d5c6'))
            anchor=points[0][0]; unit=sensor.unit
            for stamp,value in points:
                converted,unit=convert(value,sensor.unit,alternate); series.append(stamp-anchor,converted)
            self.signal_chart.addSeries(series); self.signal_chart.createDefaultAxes()
            self.signal_chart.axes(Qt.Orientation.Horizontal)[0].setTitleText('Elapsed seconds · current ECU/source context')
            self.signal_chart.axes(Qt.Orientation.Vertical)[0].setTitleText(unit)
            self.signal_chart.setTitle(f'{sensor.name} · {reading.get("source_kind","UNKNOWN")} · acquired points')
            self.trend_note.setText(f'{len(points)} samples · {points[-1][0]-anchor:.1f} s window')
        style_chart(self.signal_chart)

    def closeEvent(self, event):
        self.timer.stop()
        self.settings.setValue("sensor_order", [self.sensor_list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.sensor_list.count())])
        self.send("shutdown")
        self.worker.join(timeout=8)
        if self.worker.is_alive():
            self.timer.start(100); self.notice("Waiting for recording flush. Close again when finished."); event.ignore()
        else: event.accept()
