"""Native Qt page/scaling QA. Uses only an explicitly supplied SIMULATED bundle."""
import argparse
import json
import sys
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QPushButton
from mokka_ecu_lab.ui.window import MainWindow
from mokka_ecu_lab.research.evidence import analyze_bundles

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--bundle',type=Path,required=True)
parser.add_argument('--output-dir',type=Path,required=True)
parser.add_argument('--scale',type=float,default=1)
args=parser.parse_args(); output=args.output_dir.resolve(); output.mkdir(parents=True,exist_ok=True)
report=analyze_bundles([args.bundle])
assert all(g['source_kind']=='SIMULATED' for s in report['sessions'] for g in s['groups']), 'Synthetic simulation input only'
app=QApplication([]); ui=MainWindow(output/'synthetic-data'); ui.research_view.set_report(report)
ui.scenario.setCurrentText('Diesel alternative layouts'); ui.show(); ui.send('record'); ui.connect_adapter()
started=time.monotonic(); stage='connect'; results=[]


def capture_pages():
    ui.timer.stop(); ui.send('stop'); ui.drain()
    assert abs(ui.devicePixelRatioF()-args.scale)<0.02, (ui.devicePixelRatioF(),args.scale)
    for width,height in ((1280,720),(1366,768),(1536,864),(1920,1080)):
        logical=(round(width/args.scale),round(height/args.scale)); ui.resize(*logical); app.processEvents()
        assert (ui.width(),ui.height())==logical, ('Window forced beyond target',logical,ui.size())
        for index,name in enumerate(('dashboard','sessions','raw-data','sensor-explorer','research','discovery','drive-capture')):
            ui.tabs.setCurrentIndex(index)
            if index==4: ui.research_view.tabs.setCurrentIndex(1)
            ui.refresh_presentation(); app.processEvents()
            area=ui.tabs.widget(index); area.verticalScrollBar().setValue(0); app.processEvents()
            assert area.widget().width()<=area.viewport().width()+1, (name,logical,area.widget().width(),area.viewport().width())
            ui.statusBar().showMessage('Synthetic simulation · local-only visual validation · no vehicle data')
            filename=f'{width}x{height}-{name}.png'; assert ui.grab().save(str(output/filename))
            results.append(dict(page=name,physical=[width,height],logical=list(logical),scale=args.scale,
                compact_sidebar=ui.sidebar.compact,vertical_scroll=area.verticalScrollBar().maximum()>0,
                horizontal_page_overflow=False))
        ui.connection_panel.show(); ui.source.setCurrentIndex(1); ui.update_connection_controls(); app.processEvents()
        assert ui.connection_panel.width()<=ui.centralWidget().width()
        ui.grab().save(str(output/f'{width}x{height}-connection.png'))
        ui.connection_panel.hide()
    ui.resize(round(1366/args.scale),round(768/args.scale)); ui.tabs.setCurrentIndex(4)
    for index,name in ((0,'research-catalog'),(2,'research-hypotheses')):
        ui.research_view.tabs.setCurrentIndex(index); app.processEvents()
        ui.grab().save(str(output/f'1366x768-{name}.png'))
    ui.research_view.tabs.setCurrentIndex(1)
    for index,name in ((1,'research-samples'),(2,'research-bytes'),(3,'research-scr')):
        ui.research_view.evidence_tabs.setCurrentIndex(index); app.processEvents()
        ui.grab().save(str(output/f'1366x768-{name}.png'))
    (output/'responsive-validation.json').write_text(json.dumps(dict(scale=args.scale,private_input_used=False,checks=results),indent=2)+'\n',encoding='utf-8')
    ui.close()


def tick():
    global stage
    try:
        ui.drain()
        if time.monotonic()-started>50: raise AssertionError('Native design validation deadline')
        if stage=='connect' and ui.connected:
            ui.send('discover',ecu=ui.source_key()); stage='discover'
        elif stage=='discover' and ui.discovery_prepared and not ui.discovery_active:
            ui.prepare_capture(); ui.send('start'); stage='samples'
        elif stage=='samples' and len(ui.signal_values.get(('7E8',12,'SIMULATED','SIMULATED'),[]))>=2:
            ui.finish_session(); stage='finished'
        elif stage=='finished' and not ui.recording_id and not ui.polling_active:
            ui.refresh_sessions()
            if ui.sessions: ui.session_table.selectRow(0)
            last_ok=next((row for row in reversed(range(ui.raw_table.rowCount())) if ui.raw_table.item(row,2).text()=='OK'),0)
            ui.raw_table.selectRow(last_ok)
            ui.discovery_table.selectRow(0)
            timer.stop(); capture_pages()
    except Exception:
        timer.stop(); ui.close(); raise

timer=QTimer(); timer.timeout.connect(tick); timer.start(100); app.exec()
assert len(results)==28 and not ui.worker.is_alive()
print(json.dumps(dict(scale=args.scale,pages=28,private_input_used=False,checks='passed')))
