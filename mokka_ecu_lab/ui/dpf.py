"""Offline-only background report view. No acquisition worker reference."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QDialog,QVBoxLayout,QLabel,QPushButton,QTextEdit,QFileDialog
from .components import caption,FlowLayout
from mokka_ecu_lab.analysis.dpf import analyze_dpf,export_dpf_report,LIMITATIONS


class DpfDialog(QDialog):
    def __init__(self,paths,parent=None):
        super().__init__(parent); self.paths=[Path(p) for p in paths]; self.report=None
        self.setWindowTitle('Private offline DPF RAW evolution · HYPOTHESIS ONLY'); self.resize(1000,700)
        layout=QVBoxLayout(self); note=caption(LIMITATIONS); layout.addWidget(note)
        self.status=QLabel('Loading checksum-verified private bundles offline…'); self.status.setWordWrap(True); layout.addWidget(self.status)
        self.preview=QTextEdit(); self.preview.setReadOnly(True); layout.addWidget(self.preview,1)
        buttons=FlowLayout(); self.export_button=QPushButton('Export private HTML plots + JSON'); self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self.export); buttons.addWidget(self.export_button); layout.addLayout(buttons)
        self.executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='offline-dpf')
        self.future=self.executor.submit(analyze_dpf,self.paths); self.timer=QTimer(self); self.timer.timeout.connect(self.poll); self.timer.start(100)

    def poll(self):
        if not self.future.done(): return
        self.timer.stop()
        try:
            self.report=self.future.result()
            lines=[]
            for group in self.report['groups']:
                lines.append(f'{group["ecu"]} / {group["mode"]} / {group["source_kind"]}: {group["samples"]} samples, {group["dynamic_evidence"]}')
                for p in group['points'][:2000]:
                    ages='; '.join(f'{n}: {c["value"]} {c["unit"]}, age {c["age_seconds"]} s / {c["state"]}' for n,c in p['context'].items())
                    lines.append(f'{p["timestamp"]}  RAW {p["payload_hex"]}\nHYPOTHESIS A={p["byte_A_HYPOTHESIS"]}, AB(BE)={p["AB_big_endian_HYPOTHESIS"]}, AB(LE)={p["AB_little_endian_HYPOTHESIS"]}\n{ages}')
            self.preview.setPlainText('\n\n'.join(lines) or 'No complete recorded six-byte 017A replies. No formula or DPF conclusion.')
            self.status.setText('Private analysis ready · preview ≤2000 points per group; full statistics and JSON on export')
            self.export_button.setEnabled(True)
        except Exception as exc: self.status.setText(str(exc))

    def export(self):
        path,_=QFileDialog.getSaveFileName(self,'Fresh private DPF report','private-dpf-evolution.html','HTML (*.html)')
        if path:
            try:
                result=export_dpf_report(self.report,path,self.paths); self.status.setText('Private report saved: '+str(result))
            except Exception as exc: self.status.setText(str(exc))

    def closeEvent(self,event):
        self.timer.stop(); self.executor.shutdown(wait=False,cancel_futures=True); event.accept()
