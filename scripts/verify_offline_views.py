"""Native offline dialogs; only a checksum-verified synthetic bundle is accepted."""
import argparse,json,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QTimer,QCoreApplication,QEvent
from PySide6.QtWidgets import QApplication
from mokka_ecu_lab.analysis.phases import load_phase_data
from mokka_ecu_lab.ui.dpf import DpfDialog
from mokka_ecu_lab.ui.phases import PhaseDialog
from mokka_ecu_lab.ui.obd import ObdDialog
from mokka_ecu_lab.ui.theme import stylesheet

parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('--bundle',type=Path,required=True)
parser.add_argument('--output-dir',type=Path,required=True); parser.add_argument('--scale',type=float,default=1)
args=parser.parse_args(); data=load_phase_data(args.bundle)
assert data['groups'] and all(g['source_kind']=='SIMULATED' for g in data['groups'])
out=args.output_dir.resolve(); out.mkdir(parents=True,exist_ok=True)
app=QApplication([]); app.setStyleSheet(stylesheet()); app.setQuitOnLastWindowClosed(False)
dpf=DpfDialog([args.bundle]); phase=PhaseDialog(args.bundle);obd=ObdDialog([args.bundle]); dpf.show(); phase.show();obd.show(); began=time.monotonic(); stage='load'; checks=[]; failure=[]
def tick():
    global stage
    try:
        if time.monotonic()-began>35: raise AssertionError('Offline dialog deadline')
        if stage=='load' and dpf.report and phase.data and obd.report:
            assert all(g['source_kind']=='SIMULATED' for g in dpf.report['groups']) and dpf.report['pressure'] is None
            group=phase.data['groups'][0]; rows=sorted([p for values in group['fields'].values() for p in values],key=lambda p:p['epoch'])
            phase.timestamp.setText(rows[len(rows)//2]['timestamp']); phase.uncertainty.setValue(0)
            phase.note.setText('Constructed validation only'); phase.consent.setChecked(True); phase.compare_button.click(); stage='compare'
        elif stage=='compare' and phase.report:
            assert phase.report['causal_conclusion'] is None
            timer.stop()
            for width,height in ((1280,720),(1366,768),(1536,864),(1920,1080)):
                logical=(round(width/args.scale),round(height/args.scale))
                for widget,name in ((dpf,'dpf-hypotheses'),(phase,'phase-statistics'),(phase,'phase-utc-plot'),(obd,'ecu-inventory'),(obd,'obd-performance')):
                    if widget is phase: phase.tabs.setCurrentIndex(2 if name=='phase-utc-plot' else 0)
                    if widget is obd:obd.tabs.setCurrentIndex(1 if name=='obd-performance' else 0)
                    widget.resize(*logical); app.processEvents()
                    assert abs(widget.devicePixelRatioF()-args.scale)<.02
                    assert (widget.width(),widget.height())==logical,(name,logical,widget.size())
                    if widget is phase: assert phase.scroll.widget().width()<=phase.scroll.viewport().width()+1
                    assert widget.grab().save(str(out/f'{width}x{height}-{name}.png'))
                    checks.append(dict(view=name,physical=[width,height],scale=args.scale))
            dpf.close(); phase.close();obd.close(); app.exit(0); stage='done'
    except Exception as exc:
        failure.append(str(exc)); timer.stop(); dpf.close(); phase.close();obd.close(); app.exit(1)
timer=QTimer(); timer.timeout.connect(tick); timer.start(100); code=app.exec()
dpf.deleteLater(); phase.deleteLater();obd.deleteLater(); QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
(out/'offline-views.json').write_text(json.dumps(dict(checks=checks,private_input_used=False,no_acquisition_worker=True,failures=failure),indent=2),encoding='utf-8')
assert code==0 and stage=='done',failure
print(json.dumps(dict(passed=True,checks=len(checks),scale=args.scale,no_acquisition_worker=True)))
