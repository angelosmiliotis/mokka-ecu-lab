"""Native synthetic-only report/version UI acceptance; old public builds copied only."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QTimer,QCoreApplication,QEvent
from PySide6.QtWidgets import QApplication
from mokka_ecu_lab.ui.window import MainWindow
from mokka_ecu_lab.ui.maintenance_validation import install_maintenance_validation
from mokka_ecu_lab.ui.local_jobs import preview_dialog

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--output-dir',type=Path,required=True);p.add_argument('--data-dir',type=Path,required=True)
p.add_argument('--scale',type=float,default=1);p.add_argument('--references',type=Path,nargs=2,required=True)
p.add_argument('--release-metadata',type=Path,nargs=2,help='Optional cached official metadata from an earlier successful online validation; never changes product trust checks')
a=p.parse_args();out=a.output_dir.resolve();data=a.data_dir.resolve()
if out.exists() or data.exists():p.error('Fresh isolated synthetic output/data roots required')
out.mkdir(parents=True);app=QApplication([]);ui=MainWindow(data,validation=True);ui.show();checks=[]
if a.release_metadata:
    import mokka_ecu_lab.ui.maintenance_validation as validation
    cached=[json.loads(p.read_text(encoding='utf-8')) for p in a.release_metadata]
    assert {r['asset'] for r in cached}=={p.name for p in a.references}
    validation.release_info=lambda tag:next(r for r in cached if r['tag']==tag)
assert abs(ui.devicePixelRatioF()-a.scale)<.02
def observe(name,window):
    for w,h in ((1280,720),(1366,768),(1536,864),(1920,1080)):
        logical=(round(w/a.scale),round(h/a.scale));window.resize(*logical);app.processEvents()
        area=window.tabs.currentWidget();area.verticalScrollBar().setValue(0);app.processEvents()
        assert (window.width(),window.height())==logical
        assert area.widget().width()<=area.viewport().width()+1,(name,logical)
        window.statusBar().showMessage('CONSTRUCTED local fixtures / public release copies only / no hardware')
        assert window.grab().save(str(out/f'{w}x{h}-{name}.png'))
        checks.append(dict(view=name,physical=[w,h],scale=a.scale,horizontal_page_overflow=False))
    if name=='managed-versions':
        window.resize(round(1280/a.scale),round(720/a.scale));app.processEvents()
        def capture():
            dialog=app.activeModalWidget();assert dialog is not None
            assert dialog.width()<=window.width() and dialog.height()<=window.height()
            assert dialog.grab().save(str(out/'install-preview.png'));dialog.reject()
        QTimer.singleShot(100,capture)
        release=next(b['release'] for b in window.versions_panel.last_inventory['builds'] if b['release']['asset']==a.references[1].name)
        preview_dialog(window,'CONSTRUCTED validation: exact verified install COPY preview',window.versions_panel.manager.preview_install(a.references[1],release))
timer,cleanup=install_maintenance_validation(ui,app,data,a.references,observer=observe)
code=app.exec();cleanup();ui.deleteLater();QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
result=json.loads((data/'maintenance-smoke.json').read_text());result['native_geometry']=checks
(out/'maintenance-validation.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
assert code==0 and result['passed'] and len(checks)==12,result
print(json.dumps(dict(passed=True,checks=len(checks),scale=a.scale,old_executable_exit_codes=result['actual_old_executable_smoke_exit_codes'])))
