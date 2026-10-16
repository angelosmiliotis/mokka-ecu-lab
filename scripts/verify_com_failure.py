"""Native zero-send COM-open failure using a constructor that cannot open hardware."""
import argparse,json,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QTimer,QCoreApplication,QEvent
from PySide6.QtWidgets import QApplication
import mokka_ecu_lab.adapter as adapter
from mokka_ecu_lab.transport import SerialOpenError
from mokka_ecu_lab.ui.window import MainWindow
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output-dir',type=Path,required=True);p.add_argument('--data-dir',type=Path,required=True);p.add_argument('--scale',type=float,required=True)
a=p.parse_args()
if a.output_dir.exists() or a.data_dir.exists():p.error('Fresh synthetic roots required')
a.output_dir.mkdir(parents=True)
def unopened(*args,**kwargs):raise SerialOpenError('FAILED_COM_OPEN: CONSTRUCTED semaphore timeout / WinError 121; no handle and no wire sends')
adapter.SerialTransport=unopened
app=QApplication([]);ui=MainWindow(a.data_dir,validation=True);ui.source.setCurrentIndex(1);ui.port.setCurrentText('CONSTRUCTED-COM');ui.tabs.setCurrentIndex(8);ui.show();started=time.monotonic();checks=[]
def tick():
    ui.drain();s=ui.benchmark_state
    if time.monotonic()-started>25:app.exit(1);ui.close();return
    if s.get('exported'):
        assert s['outcome']=='FAILED_COM_OPEN' and s['requests']==0 and ui.worker.transport is None
        timer.stop()
        for w,h in ((1280,720),(1366,768),(1536,864),(1920,1080)):
            ui.resize(round(w/a.scale),round(h/a.scale));app.processEvents();assert abs(ui.devicePixelRatioF()-a.scale)<.02
            area=ui.tabs.currentWidget();assert area.widget().width()<=area.viewport().width()+1
            ui.statusBar().showMessage('CONSTRUCTED serial constructor failure / zero requests / no hardware')
            assert ui.grab().save(str(a.output_dir/f'{w}x{h}-failed-com.png'));checks.append([w,h])
        (a.output_dir/'failure-validation.json').write_text(json.dumps(dict(passed=True,source='CONSTRUCTED_FAKE_SERIAL',hardware_connected=False,requests=0,scale=a.scale,geometry=checks)))
        ui.close();app.exit(0)
ui.benchmark_panel.start.click();timer=QTimer();timer.timeout.connect(tick);timer.start(100)
code=app.exec();timer.stop();timer.timeout.disconnect(tick);ui.deleteLater();QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
assert code==0 and len(checks)==4
print(json.dumps(dict(passed=True,requests=0,checks=len(checks),scale=a.scale)))
