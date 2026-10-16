"""Bounded offline file work; never owns a diagnostic transport."""
from concurrent.futures import ThreadPoolExecutor
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QDialog,QVBoxLayout,QTextEdit,QPushButton
import json

class LocalJobs:
    def __init__(self,parent,status):
        self.status=status;self.executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='private-local-files');self.future=None
        self.timer=QTimer(parent);self.timer.timeout.connect(self.poll);self.callback=None

    def start(self,fn,callback=lambda result:None):
        if self.busy():self.status.setText('An offline operation is still running.');return False
        self.callback=callback;self.future=self.executor.submit(fn);self.status.setText('Working locally; no OBD requests or upload…');self.timer.start(80);return True

    def busy(self):return self.future is not None and not self.future.done()

    def poll(self):
        if self.future is None or not self.future.done():return
        self.timer.stop();future=self.future;self.future=None
        try:result=future.result();self.status.setText('Local operation complete.');self.callback(result)
        except Exception as exc:self.status.setText(str(exc))

    def close(self):self.timer.stop();self.executor.shutdown(wait=False,cancel_futures=True)

def preview_dialog(parent,title,plan,approve=None,approve_label='Approve this copy preview · retain every original'):
    dialog=QDialog(parent);dialog.setWindowTitle(title);dialog.resize(min(900,max(500,parent.width()-60)),min(650,max(300,parent.height()-60)));layout=QVBoxLayout(dialog)
    text=QTextEdit();text.setReadOnly(True);text.setPlainText(json.dumps(plan,ensure_ascii=False,indent=2));layout.addWidget(text)
    if approve:
        button=QPushButton(approve_label)
        button.clicked.connect(lambda:(dialog.accept(),approve()));layout.addWidget(button)
    close=QPushButton('Close preview');close.clicked.connect(dialog.reject);layout.addWidget(close);dialog.exec()
