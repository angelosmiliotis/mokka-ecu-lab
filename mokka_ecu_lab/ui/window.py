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
    QFileDialog, QMessageBox, QCheckBox, QLineEdit, QSpinBox, QGroupBox)
from PySide6.QtCharts import QChart, QChartView, QLineSeries
from PySide6.QtGui import QColor
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

STYLE = """
QWidget { background: #121923; color: #e4eaf2; font-family: 'Segoe UI'; font-size: 13px; }
QMainWindow { background: #121923; }
QPushButton { background: #273647; border: 1px solid #3b4c60; border-radius: 5px; padding: 7px 13px; }
QPushButton:hover { background: #354c63; }
QPushButton:disabled { color: #607080; }
QPushButton#primary { background: #176b66; border: 1px solid #248b83; }
QPushButton#stop { background: #67353c; }
QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox { background: #1c2735; border: 1px solid #34465b; padding: 5px; }
QTabWidget::pane { border: 1px solid #304157; }
QTabBar::tab { background: #1c2735; padding: 10px 18px; }
QTabBar::tab:selected { background: #2a4050; color: #76d8cb; }
QHeaderView::section { background: #263549; padding: 7px; border: 0px; }
QTableWidget, QListWidget, QTextEdit { background: #172230; border: 1px solid #304157; }
QTableWidget::item:selected, QListWidget::item:selected { background: #2e5260; }
QGroupBox { border: 1px solid #304157; border-radius: 5px; margin-top: 14px; padding-top: 14px; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; color: #91a8bf; }
"""

def table(headers):
    widget = QTableWidget(0, len(headers))
    widget.setHorizontalHeaderLabels(headers)
    widget.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    widget.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    widget.verticalHeader().setVisible(False)
    widget.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    widget.horizontalHeader().setStretchLastSection(True)
    return widget

def add_row(widget, values):
    row = widget.rowCount()
    widget.insertRow(row)
    for col, value in enumerate(values): widget.setItem(row, col, QTableWidgetItem(str(value)))

def update_row(widget, row, values):
    for col, value in enumerate(values):
        value = str(value)
        item = widget.item(row, col)
        if item is None: widget.setItem(row, col, QTableWidgetItem(value))
        elif item.text() != value: item.setText(value)

class MainWindow(QMainWindow):
    def __init__(self, root: Path):
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
        self.discovery_reason = 'No discovery started'
        self.raw_records = deque(maxlen=500)
        self.sessions = []
        self.recording_id = None
        self.recording_started = None
        self.request_count = self.error_count = 0
        self.connected = False
        self.polling_active = False
        self.user_paused = False
        self.requires_reconnect = False
        self.acquisition_reason = "No acquisition"
        self.context_id = None
        self.priorities = {pid: 3 if pid == 12 else 2 if pid == 5 else 1 for pid in self.registry}
        self.mode = "Disconnected"
        self.analysis_rows, self.analysis_report, self.comparison_summary = [], {}, []
        self.settings = QSettings("MokkaECULab", "Desktop")
        self.setWindowTitle("Mokka ECU Lab · read-only diagnostics")
        self.resize(1320, 860)
        self.setStyleSheet(STYLE)
        central = QWidget(); self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        title = QLabel("MOKKA ECU LAB")
        title.setStyleSheet("font-size: 23px; font-weight: 600; color: #8cddd0; padding: 6px;")
        layout.addWidget(title)
        layout.addWidget(QLabel("Local acquisition • Mode 01 allowlist • No manufacturer live queries • No telemetry"))
        self.build_connection(layout)
        self.status = QLabel("Adapter: disconnected   |   ECU: unavailable   |   No connection starts automatically")
        self.status.setWordWrap(True); layout.addWidget(self.status)
        self.tabs = QTabWidget(); layout.addWidget(self.tabs)
        self.build_dashboard(); self.build_sessions(); self.build_raw(); self.build_explorer(); self.build_research()
        self.build_discovery()
        self.statusBar().showMessage("Ready. Select Simulation and Connect to develop without a vehicle.")
        self.timer = QTimer(self); self.timer.timeout.connect(self.drain); self.timer.start(100)
        self.refresh_sessions(); self.refresh_ports()

    def button(self, label, callback, object_name=""):
        b = QPushButton(label); b.clicked.connect(callback)
        if object_name: b.setObjectName(object_name)
        return b

    def send(self, action, **kwargs):
        if action in {'discover','monitor_discovery'}:
            self.user_paused = False
        if action == 'discover': self.polling_active = False
        if action in {'stop','disconnect','replay','shutdown','connect'}:
            self.discovery_active = False
        if action in {"stop", "disconnect", "replay", "shutdown", "connect"}:
            self.polling_active = False
            self.user_paused = action != "connect"
            self.acquisition_reason = "Polling stopped by user" if action == "stop" else "Connection changing / offline"
        elif action == "start": self.user_paused = False
        try: self.worker.submit(action, **kwargs)
        except Exception as exc: self.notice(str(exc))

    def finish_session(self):
        self.send("stop")
        self.send("record_stop")

    def notice(self, message):
        self.statusBar().showMessage(message, 20000)
        self.messages.append(f"{datetime.now().isoformat(timespec='seconds')}  {message}")

    def build_connection(self, layout):
        row = QHBoxLayout()
        self.source = QComboBox(); self.source.addItems(["Simulation", "Bluetooth serial"])
        self.port = QComboBox(); self.port.setEditable(True)
        self.port.setMinimumContentsLength(8)
        self.port.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.port.setMaximumWidth(240)
        self.port.currentIndexChanged.connect(lambda i: self.port.setToolTip(self.port.itemData(i, Qt.ItemDataRole.ToolTipRole) or "Manual outgoing serial port"))
        self.baud = QComboBox(); self.baud.addItems(["115200", "38400", "9600"])
        self.scenario = QComboBox(); self.scenario.addItems(SCENARIOS)
        self.rate = QDoubleSpinBox(); self.rate.setRange(.25, 4); self.rate.setValue(4); self.rate.setSuffix(" total req/s")
        self.rate.valueChanged.connect(lambda v: self.send("rate", rate=v))
        self.connect_button = self.button("Connect", self.connect_adapter, "primary")
        self.disconnect_button = self.button("Disconnect", lambda: self.send("disconnect"), "stop")
        self.stop_button = self.button("Stop polling", lambda: self.send("stop"), "stop")
        self.start_button = self.button("Resume", lambda: self.send("start"))
        for w in (self.source, self.port, self.button("Refresh ports", self.refresh_ports), self.baud, self.scenario, self.rate,
                  self.connect_button, self.disconnect_button, self.stop_button, self.start_button): row.addWidget(w)
        layout.addLayout(row)
        self.source.currentIndexChanged.connect(self.update_connection_controls)
        self.update_connection_controls()

    def update_connection_controls(self):
        live = self.source.currentIndex() == 1
        self.port.setEnabled(live); self.baud.setEnabled(live); self.scenario.setEnabled(not live)

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
        self.readings.clear(); self.support.clear(); self.history.clear(); self.sensor_errors.clear(); self.ecu.clear(); self.ecu.addItem("Automatic first responding ECU", "")
        self.support_pages.clear()
        self.mode = "Connecting"
        self.connected = False
        self.request_count = self.error_count = 0
        self.connect_button.setEnabled(False)
        self.send("connect", simulation=self.source.currentIndex() == 0,
                  port=self.port.currentText().strip(),
                  baud=int(self.baud.currentText()), scenario=self.scenario.currentText())

    def build_dashboard(self):
        tab = QWidget(); layout = QVBoxLayout(tab)
        self.banner = QLabel("OFFLINE · no measurements")
        self.banner.setStyleSheet("font-size: 20px; font-weight: 600; color: #eabf75; padding: 10px;")
        layout.addWidget(self.banner)
        row = QHBoxLayout()
        self.ecu = QComboBox(); self.ecu.addItem("Automatic first responding ECU", "")
        self.units = QCheckBox("Alternate units (°F, mph, bar, kg/h)")
        self.greek = QCheckBox("Ελληνικές ετικέτες")
        self.greek.toggled.connect(self.update_language)
        self.record_button = self.button("Start Recording", lambda: self.send("record"), "primary")
        self.record_stop_button = self.button("Stop Recording", lambda: self.send("record_stop"))
        for w in (QLabel("ECU source:"), self.ecu, self.units, self.greek, self.record_button, self.record_stop_button): row.addWidget(w)
        layout.addLayout(row)
        instructions = QLabel("Before switching ignition OFF: Stop Recording and Stop polling, then Disconnect. Finish session stops both; Disconnect also closes any open recording.")
        instructions.setWordWrap(True); layout.addWidget(instructions)
        priority_row = QHBoxLayout()
        self.use_priorities = QCheckBox("Use sensor priorities (same total rate ceiling)")
        self.priority_sensor = QComboBox()
        for pid, sensor in self.registry.items(): self.priority_sensor.addItem(sensor.name, pid)
        self.priority_weight = QSpinBox(); self.priority_weight.setRange(1, 4)
        self.priority_weight.setValue(self.priorities[self.priority_sensor.currentData()])
        self.priority_sensor.currentIndexChanged.connect(self.select_priority)
        self.priority_weight.valueChanged.connect(self.change_priority)
        self.use_priorities.toggled.connect(self.send_priorities)
        self.priority_sensor.setEnabled(False); self.priority_weight.setEnabled(False)
        for w in (self.use_priorities, self.priority_sensor, QLabel("Priority 1–4:"), self.priority_weight,
                  self.button("Finish session", self.finish_session)): priority_row.addWidget(w)
        layout.addLayout(priority_row)
        self.rejection_reason = QLabel(""); self.rejection_reason.setWordWrap(True); layout.addWidget(self.rejection_reason)
        self.coverage = QLabel("No current connection coverage"); self.coverage.setWordWrap(True); layout.addWidget(self.coverage)
        split = QSplitter()
        self.sensor_list = QListWidget(); self.sensor_list.setMaximumWidth(285)
        self.sensor_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        stored = self.settings.value("sensor_order", list(self.registry), type=list)
        order = [int(x) for x in stored if int(x) in self.registry]
        order += [x for x in self.registry if x not in order]
        for pid in order:
            item = QListWidgetItem(self.registry[pid].name)
            item.setData(Qt.ItemDataRole.UserRole, pid)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            self.sensor_list.addItem(item)
        self.sensor_list.itemChanged.connect(self.select_sensors)
        self.sensor_list.model().rowsMoved.connect(self.select_sensors)
        split.addWidget(self.sensor_list)
        self.dashboard = table(["Measurement", "Value", "Units", "State", "Rate", "Last success (UTC)", "ECU", "Evidence", "Actual interval", "Gap / age", "Priority"])
        split.addWidget(self.dashboard); split.setStretchFactor(1, 1)
        layout.addWidget(QLabel("Choose sensors with checkboxes; drag to reorder. Base units remain unchanged in recordings."))
        layout.addWidget(split, 1)
        self.stats = QLabel("Recording: off   |   Requests: 0   |   Errors: 0")
        layout.addWidget(self.stats)
        self.messages = QTextEdit(); self.messages.setReadOnly(True); self.messages.setMaximumHeight(95)
        self.messages.document().setMaximumBlockCount(150)
        layout.addWidget(self.messages)
        self.tabs.addTab(tab, "Dashboard")

    def update_language(self, enabled):
        labels = ["Πίνακας", "Συνεδρίες", "Ακατέργαστα", "Αισθητήρες", "Έρευνα", "Ανακάλυψη"] if enabled else ["Dashboard", "Sessions", "Raw Data", "Sensor Explorer", "Research", "Discovery"]
        for i, label in enumerate(labels): self.tabs.setTabText(i, label)
        self.connect_button.setText("Σύνδεση" if enabled else "Connect")
        self.disconnect_button.setText("Αποσύνδεση" if enabled else "Disconnect")
        self.stop_button.setText("Διακοπή" if enabled else "Stop")

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
        tab = QWidget(); layout = QVBoxLayout(tab); row = QHBoxLayout()
        for label, callback in [("Start Recording", lambda: self.send("record")), ("Stop Recording", lambda: self.send("record_stop")),
                                ("Refresh", self.refresh_sessions), ("Replay selected", self.replay_session),
                                ("Open JSONL replay…", self.open_replay), ("Export CSV…", self.csv_export), ("Export JSONL…", self.jsonl_export)]:
            row.addWidget(self.button(label, callback))
        layout.addLayout(row)
        instructions = QLabel("Before ignition OFF: Stop Recording and Stop polling, then Disconnect. Either Stop order is supported. Disconnect finalizes an open journal and SQLite session.")
        instructions.setWordWrap(True); layout.addWidget(instructions)
        self.diagnostic_export = QCheckBox("Diagnostic support export: include unredacted adapter/port and identification bytes")
        layout.addWidget(self.diagnostic_export)
        layout.addWidget(QLabel("Vehicle: Opel Mokka B, 2022, 1.5 diesel. VIN is never queried. Adapter identifiers are redacted by default."))
        self.session_table = table(["Session", "Started (UTC)", "Ended (UTC)", "Duration", "Source", "Requests", "Errors"])
        layout.addWidget(self.session_table)
        self.session_info = QLabel(str(self.root)); self.session_info.setWordWrap(True); layout.addWidget(self.session_info)
        controls = QHBoxLayout()
        self.replay_speed = QComboBox(); self.replay_speed.addItems(["1× original", "2×", "5×", "10×"])
        controls.addWidget(self.replay_speed)
        controls.addWidget(self.button("Play replay", lambda: self.send("replay_play", speed=[1., 2., 5., 10.][self.replay_speed.currentIndex()])))
        controls.addWidget(self.button("Pause / Stop", lambda: self.send("stop")))
        controls.addWidget(self.button("Step one transaction", lambda: self.send("step")))
        controls.addStretch(); layout.addLayout(controls)
        self.tabs.addTab(tab, "Sessions")

    def refresh_sessions(self):
        try:
            previous = self.current_session()
            self.sessions = list_sessions(self.root)
            self.session_table.setRowCount(0)
            for index, s in enumerate(self.sessions):
                end = datetime.fromisoformat(s["ended"]) if s["ended"] else datetime.now().astimezone()
                duration = (end - datetime.fromisoformat(s["started"])).total_seconds()
                add_row(self.session_table, [s["id"][:12], s["started"], s["ended"] or "Open / interrupted", f"{duration:.1f} s", s["mode"], s["requests"], s["errors"]])
                if previous and s["id"] == previous["id"]: self.session_table.selectRow(index)
        except Exception as exc: self.notice(str(exc))

    def current_session(self):
        row = self.session_table.currentRow() if hasattr(self, "session_table") else -1
        return self.sessions[row] if 0 <= row < len(self.sessions) else None

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
            try: export_csv(self.root, s["id"], Path(path)); self.notice("CSV exported")
            except Exception as exc: self.notice(str(exc))

    def jsonl_export(self):
        s = self.current_session()
        if not s: return self.notice("Select a session to export")
        path, _ = QFileDialog.getSaveFileName(self, "Export raw journal", str(self.root / (s["id"] + "-export.jsonl")), "JSONL (*.jsonl)")
        if path:
            try: export_jsonl(self.root / s["raw_path"], Path(path), self.diagnostic_export.isChecked()); self.notice("JSONL exported")
            except Exception as exc: self.notice(str(exc))

    def build_raw(self):
        tab = QWidget(); layout = QVBoxLayout(tab)
        layout.addWidget(QLabel("Latest 500 transactions shown. All recorded transactions are retained on disk. Select a row for the complete reply."))
        self.raw_table = table(["UTC timestamp", "Command", "Status", "Latency ms", "ECU", "Parsed payload", "Decoder", "Error"])
        layout.addWidget(self.raw_table)
        self.raw_detail = QTextEdit(); self.raw_detail.setReadOnly(True); self.raw_detail.setMaximumHeight(230)
        layout.addWidget(self.raw_detail)
        self.raw_table.itemSelectionChanged.connect(self.show_raw_detail)
        self.tabs.addTab(tab, "Raw Data")

    def show_raw_detail(self):
        row = self.raw_table.currentRow()
        if 0 <= row < len(self.raw_records):
            record = self.raw_records[row]
            raw = base64.b64decode(record["raw_b64"])
            self.raw_detail.setPlainText("Original response (text):\n" + raw.decode('ascii', 'replace') +
                "\nOriginal response (hex):\n" + raw.hex(' ') + "\n\nTransaction metadata:\n" + json.dumps(record, indent=2, ensure_ascii=False))

    def build_explorer(self):
        tab = QWidget(); layout = QVBoxLayout(tab)
        layout.addWidget(QLabel("STANDARD_VERIFIED validates the published formula; it does not assert support or accuracy on your vehicle. No DPF decoder is registered."))
        self.explorer = table(["Sensor", "Request", "Service / positive", "ECU", "Layout", "Formula", "Units", "Poll rate", "Verification", "Last value", "Last UTC", "State / evidence"])
        layout.addWidget(self.explorer)
        self.sensor_detail = QTextEdit(); self.sensor_detail.setReadOnly(True); self.sensor_detail.setMaximumHeight(230)
        layout.addWidget(self.sensor_detail)
        self.explorer.itemSelectionChanged.connect(self.show_sensor_detail)
        self.tabs.addTab(tab, "Sensor Explorer")

    def show_sensor_detail(self):
        row = self.explorer.currentRow()
        if 0 <= row < len(self.registry):
            self.sensor_detail.setPlainText(json.dumps(list(self.registry.values())[row].metadata, indent=2, ensure_ascii=False))

    def build_research(self):
        tab = QWidget(); layout = QVBoxLayout(tab)
        warning = QLabel("OFFLINE ONLY · EXPERIMENTAL hypotheses · no live request input")
        warning.setStyleSheet("color: #eabf75; font-weight: 600;"); layout.addWidget(warning)
        layout.addWidget(QLabel("Enter payload hex, one sample per line. Select a byte slice to compare byte order, signedness, scale and offset.\nOptional measured values must be paired in the same row order and use the same units."))
        row = QHBoxLayout()
        self.payloads = QTextEdit(); self.payloads.setPlaceholderText("04 80\n04 90\n04 A0"); self.payloads.setMaximumHeight(90)
        self.measured = QTextEdit(); self.measured.setPlaceholderText("Measured reference (one numeric value per line)"); self.measured.setMaximumHeight(90)
        row.addWidget(self.payloads); row.addWidget(self.measured); layout.addLayout(row)
        options = QHBoxLayout()
        self.byte_start = QSpinBox(); self.byte_start.setRange(0, 63)
        self.byte_length = QSpinBox(); self.byte_length.setRange(1, 8); self.byte_length.setValue(2)
        self.scale = QDoubleSpinBox(); self.scale.setRange(-1e9, 1e9); self.scale.setDecimals(8); self.scale.setValue(1)
        self.offset = QDoubleSpinBox(); self.offset.setRange(-1e9, 1e9); self.offset.setDecimals(8)
        for label, w in [("Byte start", self.byte_start), ("Length", self.byte_length), ("Scale", self.scale), ("Offset", self.offset)]:
            options.addWidget(QLabel(label)); options.addWidget(w)
        options.addWidget(self.button("Evaluate hypotheses", self.evaluate))
        options.addWidget(self.button("Save report…", self.save_report))
        layout.addLayout(options)
        actions = QHBoxLayout()
        actions.addWidget(self.button("Load payloads from JSONL…", self.load_analysis))
        actions.addWidget(self.button("Compare recordings…", self.compare_recordings))
        self.analysis_pid = QLineEdit("0C"); self.analysis_pid.setMaximumWidth(65)
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
        self.tabs.addTab(tab, "Research")

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
            try: Path(path).write_text(json.dumps(self.analysis_report, indent=2), encoding="utf-8"); self.notice("Experimental report saved")
            except Exception as exc: self.notice(str(exc))

    def recording_payloads(self, path):
        pid = int(self.analysis_pid.text(), 16)
        source = self.analysis_ecu.text().strip().upper()
        playback = Replay(Path(path)); payloads, counts, invalid = [], 0, 0
        try:
            while (record := playback.next()) is not None:
                counts += 1
                if record.get("status") != "OK": invalid += 1
                if record.get("pid") == f"{pid:02X}":
                    for item in record.get("parsed", []):
                        if (item.get("ecu") or "headerless").upper() == source and len(payloads) < 1000:
                            payloads.append(item["data_hex"])
        finally: playback.close()
        return payloads, {"file": str(path), "pid": f"{pid:02X}", "ecu": source, "transactions": counts,
            "errors": invalid, "sample_count": len(payloads), "truncated_preview_limit": 1000, "warnings": playback.warnings}

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
            self.comparison_summary = [r[1] for r in result]
            self.payloads.setPlainText('\n'.join(x for r in result for x in r[0])[:250000])
            self.analysis_summary.setText(json.dumps(self.comparison_summary))
            self.notice("Comparison loaded in file order. Counts/errors are per file; report preserves file boundaries. Evaluate a byte hypothesis to plot samples.")
        except Exception as exc: self.notice(str(exc))

    def source_key(self):
        return self.ecu.currentData() or (next(iter(self.support), None))

    def build_discovery(self):
        tab = QWidget(); layout = QVBoxLayout(tab)
        message = QLabel('Standard Mode 01 only. Start discovery explicitly for the selected ECU. Unsupported/unknown PIDs are never probed. Samples remain vehicle-unverified; OEM candidates are offline only.')
        message.setWordWrap(True); layout.addWidget(message)
        source_row = QHBoxLayout(); source_row.addWidget(QLabel('ECU:'))
        self.discovery_ecu = QComboBox(); self.discovery_ecu.setModel(self.ecu.model())
        self.discovery_ecu.currentIndexChanged.connect(self.ecu.setCurrentIndex)
        self.ecu.currentIndexChanged.connect(self.discovery_ecu.setCurrentIndex)
        source_row.addWidget(self.discovery_ecu,1)
        self.discovery_filter = QComboBox(); self.discovery_filter.addItems(['All systems','Engine','DPF','Exhaust','SCR/AdBlue'])
        self.discovery_filter.currentTextChanged.connect(self.update_discovery)
        source_row.addWidget(self.discovery_filter); layout.addLayout(source_row)
        row = QHBoxLayout()
        self.discovery_start = self.button('Scan standard PIDs for selected ECU', lambda: self.send('discover', ecu=self.source_key()))
        self.discovery_monitor = self.button('Monitor available standard PIDs', lambda: self.send('monitor_discovery', ecu=self.source_key()))
        for w in (self.discovery_start,self.discovery_monitor,self.button('Stop',lambda:self.send('stop')),
                  self.button('Export discovery report…',self.export_discovery)): row.addWidget(w)
        layout.addLayout(row)
        self.discovery_status = QLabel(); self.discovery_status.setWordWrap(True); layout.addWidget(self.discovery_status)
        self.discovery_status.setMinimumHeight(64)
        self.discovery_table = table(['System','Parameter / request','ECU','PID support','Availability','Evidence','Verification','Latest sample (UTC)'])
        self.discovery_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        for col,width in enumerate([100,290,100,110,155,160,175,200]): self.discovery_table.setColumnWidth(col,width)
        self.discovery_table.itemSelectionChanged.connect(self.discovery_details)
        layout.addWidget(self.discovery_table,1)
        self.discovery_detail = QTextEdit(); self.discovery_detail.setReadOnly(True); self.discovery_detail.setMinimumHeight(160)
        layout.addWidget(self.discovery_detail,1)
        self.tabs.addTab(tab,'Discovery')
        self.update_discovery()

    def update_discovery(self, *args):
        self.discovery_data = discovery_report(self.support,self.support_pages,self.discovery_observations,
                                                mode=self.mode,context_id=self.context_id)
        system = self.discovery_filter.currentText()
        self.discovery_rows = [e for e in self.discovery_data['standard']+self.discovery_data['manufacturer_candidates']
                               if system == 'All systems' or e['system']==system]
        self.discovery_table.setRowCount(len(self.discovery_rows))
        for row,e in enumerate(self.discovery_rows):
            sample = e.get('sample',{})
            update_row(self.discovery_table,row,[e['system'],e['name']+' / '+e['request'],e.get('ecu','Offline candidate'),
                       e['support'],e.get('availability','RESEARCH_ONLY'),
                       ('REPLAY · ' if sample.get('replay') else 'SAMPLE · ' if sample else '')+(e.get('evidence','NO_SAMPLE') if 'sample' in e else 'RESEARCH_ONLY'),
                       e['verification']+' / vehicle UNVERIFIED',sample.get('timestamp','—')])
        counts = {s:sum(e.get('availability')==s for e in self.discovery_data['standard'])
                  for s in ('AVAILABLE','UNSUPPORTED','UNKNOWN','UNVERIFIED','NO_SUPPORTED_FIELDS','INVALID / UNVERIFIED')}
        self.discovery_status.setText(f'ECU selected: {self.source_key() or "—"} | {self.mode} | {self.discovery_reason} | '+
                                      ', '.join(f'{s}: {n}' for s,n in counts.items()))
        allowed = self.connected and self.mode != 'REPLAY' and not self.requires_reconnect and not self.discovery_active
        self.discovery_start.setEnabled(allowed)
        self.discovery_monitor.setEnabled(allowed and self.discovery_prepared and self.source_key()==self.discovery_target)
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
        schedule_weights = dict(weights)
        if self.discovery_active and self.polling_active:
            schedule_weights.update(priority_weights(DISCOVERY_PIDS & self.support.get(self.discovery_target,set()),
                                                     {},allow_discovery=True))
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
                age = now - reading["received_at"]
                expected = nominal_interval(pid, schedule_weights, self.rate.value()) if pid in weights else 0
                threshold = max(5., expected * 2.5)
                replay = reading["mode"].startswith("REPLAY")
                evidence = ("REPLAY · " if replay else "") + reading.get("source_kind", "UNKNOWN")
                valid = (not replay and self.connected and self.polling_active and reading["mode"] == self.mode
                         and pid in weights and age <= threshold and not reading.get("invalid")
                         and not reading.get("stale_reason"))
                state = "Recorded (offline)" if replay else "Valid" if valid else "Stale (last success)"
                reason = reading.get("stale_reason") or error or (self.acquisition_reason if not replay and not self.polling_active else "")
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
            self.dashboard.item(index, 3).setToolTip(error or self.acquisition_reason)
            color = "#eabf75" if state.startswith("Stale") else "#e89494" if "Invalid" in state or "rejected" in state else "#8cddd0" if state == "Valid" else "#91a0b0"
            self.dashboard.item(index, 3).setForeground(QColor(color))
        self.coverage.setText(f'ECU: {source or "—"} | selected supported: {len(weights)}/{len(checked)} | current: {current}/{len(weights)} | {self.acquisition_reason}')
        self.banner.setText(self.mode + (" · recorded evidence, offline" if self.mode == "REPLAY" else " · polling" if self.polling_active else " · polling stopped; values stale"))
        if self.explorer.rowCount() == 0:
            for s in self.registry.values():
                add_row(self.explorer, [s.name, f"01{s.pid:02X}", f'01 / {s.metadata["positive_response"]}', "—", s.metadata["layout"], s.metadata["formula"], s.unit, "—", s.metadata["verification"], "—", "—", "Unavailable"])
        for row, sensor in enumerate(self.registry.values()):
            reading = self.readings.get((source, sensor.pid))
            verification = "UNSUPPORTED" if source in self.support and support_state(self.support[source], self.support_pages.get(source, set()), sensor.pid) == "unsupported" else sensor.metadata["verification"]
            nominal = f"{nominal_interval(sensor.pid, schedule_weights, self.rate.value()):.2f} s nominal" if sensor.pid in weights else "Not scheduled"
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
            elif kind == "context":
                self.context_id, self.mode = value["id"], value["mode"]
                self.readings.clear(); self.history.clear(); self.sensor_errors.clear()
                self.support.clear(); self.support_pages.clear()
                self.discovery_observations.clear(); self.discovery_active = False
                self.discovery_prepared = False; self.discovery_target = None
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
                if not self.polling_active and not self.discovery_active:
                    self.discovery_reason = 'Polling stopped; latest samples are recorded evidence'
            elif kind == 'discovery':
                if value.get('context_id') != self.context_id: continue
                self.discovery_active = value['active']; self.discovery_reason = value['reason']
                self.discovery_prepared = value.get('prepared',False); self.discovery_target = value.get('target')
            elif kind == "connection":
                self.mode = value["mode"]
                self.connected = value["ecu"] == "Connected"
                self.status.setText(f'Adapter: {value["adapter"]}   |   ECU: {value["ecu"]}   |   Protocol: {value["protocol"]}')
                self.connect_button.setEnabled(value["adapter"] == "Disconnected" or value["ecu"] in {"Connected", "No verified ECU response", "Replay paused"})
            elif kind == "support":
                self.support = value
                for source in value:
                    if self.ecu.findData(source) < 0: self.ecu.addItem(source, source)
            elif kind == "support_pages": self.support_pages = value
            elif kind == "recording":
                self.recording_id = value; self.recording_started = time.monotonic() if value else None
                self.refresh_sessions()
            elif kind == "transaction":
                record, readings = value
                if self.context_id and record.get("context_id", self.context_id) != self.context_id: continue
                self.request_count += 1; self.error_count += record["status"] != "OK"
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
                    self.readings[key] = dict(reading, received_at=time.monotonic() if replay else sent_at, invalid=False)
                    self.sensor_errors.pop(key, None)
                    self.history.setdefault(key, deque(maxlen=20)).append(sent_at)
                    self.discovery_observations[key] = {'ecu':reading['ecu'],'pid':reading['pid'],
                        'fields':[dict(state='AVAILABLE',name=self.registry[reading['pid']].name,value=reading['value'],unit=self.registry[reading['pid']].unit)],
                        'timestamp':reading['timestamp'],'source_kind':reading.get('source_kind','UNKNOWN'),'replay':replay}
                for sample in record.get('discovery_samples',[]):
                    self.discovery_observations[sample['ecu'] or 'headerless',sample['pid']] = sample
                for problem in record.get('protocol_errors',[]):
                    source = problem['ecu'] or 'unknown'
                    if record.get('pid'):
                        pid = int(record['pid'],16)
                        self.sensor_errors[source,pid] = problem['reason']
                        if (source,pid) in self.readings: self.readings[source,pid]['invalid'] = True
                        previous = self.discovery_observations.get((source,pid),{})
                        self.discovery_observations[source,pid] = dict(previous,error=problem['reason'])
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
                if record["status"] in {"INVALID", "TRANSPORT_ERROR"} and not record.get('protocol_errors') and record.get("pid"):
                    pid = int(record["pid"], 16)
                    for source in self.support: self.sensor_errors[source, pid] = record["error"]
                    for (source, p), reading in self.readings.items():
                        if p == pid: reading["invalid"] = True
        self.update_measurements()
        self.update_discovery()
        duration = time.monotonic() - self.recording_started if self.recording_started else 0
        self.stats.setText(f'Recording: {self.recording_id[:12] if self.recording_id else "off"}  {duration:.1f}s   |   Requests: {self.request_count}   |   Errors: {self.error_count}   |   Dropped UI previews: {self.worker.dropped}')
        self.record_button.setEnabled(not self.recording_id)
        self.record_stop_button.setEnabled(bool(self.recording_id))
        self.start_button.setEnabled(self.connected and not self.polling_active and not self.requires_reconnect)

    def closeEvent(self, event):
        self.timer.stop()
        self.settings.setValue("sensor_order", [self.sensor_list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.sensor_list.count())])
        self.send("shutdown")
        self.worker.join(timeout=8)
        if self.worker.is_alive():
            self.timer.start(100); self.notice("Waiting for recording flush. Close again when finished."); event.ignore()
        else: event.accept()
