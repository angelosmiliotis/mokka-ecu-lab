"""Native GUI verification using synthetic diesel CAN responses only."""
import argparse
import json
import sys
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
from mokka_ecu_lab.ui.window import MainWindow
from mokka_ecu_lab.sensors.diesel import STANDARD_DIESEL
from mokka_ecu_lab.logging import list_sessions
from mokka_ecu_lab import __version__

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output-dir',type=Path,default=Path('release/v0.2.0-validation'))
options=parser.parse_args(); output=options.output_dir.resolve(); output.mkdir(parents=True,exist_ok=True)
app=QApplication([]); window=MainWindow(output/'data',validation=True)
window.session_panel.advanced.setChecked(True)
window.scenario.setCurrentText('Diesel discovery'); window.tabs.setCurrentIndex(5); window.show()
started=time.monotonic(); stage='connect'; result={}
window.send('record'); window.connect_adapter()

def tick():
    global stage
    window.drain()
    if time.monotonic()-started>35:
        result['error']='Verification deadline exceeded'; timer.stop(); window.close(); return
    if stage=='connect' and window.connected:
        window.send('discover',ecu='7E8'); stage='discovery'
    elif stage=='discovery' and 'Discovery ended' in window.discovery_reason:
        window.update_discovery(); report=window.discovery_data
        rows=[e for e in report['standard'] if e.get('pid') in {f'{p:02X}' for p in STANDARD_DIESEL} and e['ecu']=='7E8']
        result.update(version=__version__,mode=window.mode,tabs=window.tabs.count(),
                      standard_pids=len(rows),available=sum(e['availability']=='AVAILABLE' for e in rows),
                      no_supported_fields=sum(e['availability']=='NO_SUPPORTED_FIELDS' for e in rows),
                      raw_transactions=window.request_count,errors=window.error_count,
                      dashboard_rows=window.dashboard.rowCount(),vehicle_verified=False,
                      manufacturer_live_enabled=any(e['live_enabled'] for e in report['manufacturer_candidates']))
        row=next(i for i,e in enumerate(window.discovery_rows) if e.get('pid')=='8B' and e['ecu']=='7E8')
        window.discovery_table.selectRow(row)
        window.grab().save(str(output/'discovery.png'))
        (output/'discovery-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        window.send('stop'); window.send('record_stop'); window.send('disconnect'); stage='close'
    elif stage=='close' and window.worker.transport is None and window.worker.recorder is None:
        result['sessions_closed']=all(s['ended'] for s in list_sessions(output/'data'))
        timer.stop(); window.close()

timer=QTimer(); timer.timeout.connect(tick); timer.start(100); app.exec()
(output/'validation.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
assert result.get('standard_pids')==12 and result['available']==11 and result['no_supported_fields']==1,result
assert result['errors']==0 and result['dashboard_rows']==10 and not result['manufacturer_live_enabled'],result
assert result['sessions_closed'] and not window.worker.is_alive(),result
print(json.dumps(result))
