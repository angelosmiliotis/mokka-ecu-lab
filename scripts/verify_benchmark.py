"""Native synthetic Advanced-only fixed benchmark, actual GUI/process checks."""
import argparse,json,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QTimer,QCoreApplication,QEvent
from PySide6.QtWidgets import QApplication
from mokka_ecu_lab.ui.window import MainWindow
from mokka_ecu_lab.transport.simulator import Simulator
from mokka_ecu_lab.analysis.obd import analyze_obd
from mokka_ecu_lab.logging import list_sessions

p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output-dir',type=Path,required=True);p.add_argument('--scale',type=float,default=1)
a=p.parse_args();out=a.output_dir.resolve()
if out.exists():p.error('Fresh synthetic output required')
out.mkdir(parents=True);app=QApplication([]);app.setQuitOnLastWindowClosed(False);ui=MainWindow(out/'synthetic-data',validation=True)
ui.source.setCurrentIndex(0);ui.scenario.setCurrentText('Diesel thirteen sensors');ui.session_panel.advanced.setChecked(True);ui.tabs.setCurrentIndex(7);ui.show()
assert abs(ui.devicePixelRatioF()-a.scale)<.02
from mokka_ecu_lab.ui.benchmark_validation import install_benchmark_validation
timer,cleanup=install_benchmark_validation(ui,app,out/'synthetic-data',scale=a.scale,output=out/'benchmark-validation.json')
code=app.exec();cleanup();ui.deleteLater();QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
result=json.loads((out/'benchmark-validation.json').read_text(encoding='utf-8'))
assert code==0 and result.get('passed'),result
print(json.dumps({k:result[k] for k in ('passed','requests','fixed_rate','minimum_recorded_wire_gap_ms','maximum_gui_tick_gap_seconds')}))
