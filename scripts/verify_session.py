"""Native Windows three-action QA with generated simulator data only."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QCoreApplication,QEvent
from PySide6.QtWidgets import QApplication
from mokka_ecu_lab.ui.window import MainWindow
from mokka_ecu_lab.ui.session_validation import install_session_validation

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output-dir',type=Path,required=True); parser.add_argument('--scale',type=float,default=1)
parser.add_argument('--expanded',action='store_true',help='Constructed extended standard research profile')
args=parser.parse_args(); out=args.output_dir.resolve()
if out.exists(): parser.error('Choose fresh synthetic output')
out.mkdir(parents=True); app=QApplication([]); ui=MainWindow(out/'synthetic-data',validation=True)
ui.resize(round(1366/args.scale),round(768/args.scale)); ui.show(); app.processEvents()
assert abs(ui.devicePixelRatioF()-args.scale)<.02,(ui.devicePixelRatioF(),args.scale)
geometry=[]
def observe(name,window):
    window.statusBar().showMessage('Synthetic three-action validation · no hardware or private vehicle data')
    app.processEvents(); assert window.grab().save(str(out/(name+'.png')))
    if name in {'session-disconnected','session-connected','session-ready','session-exported'}:
        for width,height in ((1280,720),(1366,768),(1536,864),(1920,1080)):
            logical=(round(width/args.scale),round(height/args.scale)); window.resize(*logical); app.processEvents()
            area=window.tabs.widget(7); area.verticalScrollBar().setValue(0); app.processEvents()
            assert (window.width(),window.height())==logical
            assert area.widget().width()<=area.viewport().width()+1,('Session page overflow',logical)
            assert window.grab().save(str(out/f'{width}x{height}-{name}.png'))
            geometry.append(dict(state=name,physical=[width,height],logical=list(logical),scale=args.scale,horizontal_page_overflow=False))
        if name=='session-ready':
            area.verticalScrollBar().setValue(area.verticalScrollBar().maximum()); app.processEvents()
            assert window.grab().save(str(out/'session-field-catalog.png')); area.verticalScrollBar().setValue(0)
        window.resize(round(1366/args.scale),round(768/args.scale)); app.processEvents()
timer,cleanup=install_session_validation(ui,app,out/'synthetic-data',minimum_samples=3,observer=observe,expanded=args.expanded)
code=app.exec(); cleanup(); ui.deleteLater(); QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
result=json.loads((out/'synthetic-data/session-smoke.json').read_text()); result['native_geometry']=geometry
(out/'session-validation.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
assert code==0 and result['passed'],result
print(json.dumps({k:result[k] for k in ('passed','primary_actions','scheduled_pids','stored_017a_raw_frames','monitoring_errors','wire_spacing_min_seconds','maximum_gui_tick_gap_seconds')}))
