"""Native Windows Drive Capture and bundle verification; simulator only."""
import argparse
import hashlib
import json
import sys
import time
import zipfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication, QFileDialog
from PySide6.QtCore import QTimer
from mokka_ecu_lab.ui.window import MainWindow
from mokka_ecu_lab.capture import DRIVE_WEIGHTS
from mokka_ecu_lab.logging import list_sessions
from mokka_ecu_lab import __version__

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output-dir',type=Path,default=Path('release/v0.2.1-validation'))
args=parser.parse_args(); output=args.output_dir.resolve(); output.mkdir(parents=True,exist_ok=True)
app=QApplication([]); window=MainWindow(output/'data',validation=True)
window.session_panel.advanced.setChecked(True)
window.scenario.setCurrentText('Diesel discovery'); window.tabs.setCurrentIndex(6); window.show()
stage='connect'; started=time.monotonic(); result={}; baseline={}; session_id=None
window.connect_adapter()

def tick():
    global stage, baseline, session_id
    window.drain()
    if time.monotonic()-started>45:
        result['error']='Capture verification deadline exceeded'; timer.stop(); window.close(); return
    if stage=='connect' and window.connected:
        window.send('record'); stage='record'
    elif stage=='record' and window.recording_id:
        session_id=window.recording_id; window.send('discover',ecu='7E8'); stage='discovery'
    elif stage=='discovery' and window.discovery_prepared and not window.discovery_active:
        before=window.worker.transport.last_send
        window.capture_preset.click()
        assert window.worker.transport.last_send==before,'Preset selection transmitted a request'
        assert set(window.capture_selected())==set(DRIVE_WEIGHTS)
        baseline={pid:len(window.capture_history.get(('7E8',pid),[])) for pid in DRIVE_WEIGHTS}
        window.capture_focus.setChecked(True); window.journey_start.click(); window.capture_start.click(); stage='monitor'
    elif stage=='monitor' and all(len(window.capture_history.get(('7E8',p),[]))-baseline[p]>=2 for p in DRIVE_WEIGHTS):
        assert window.recording_id==session_id and window.capture_active
        result.update(version=__version__,mode=window.mode,tabs=window.tabs.count(),
                      selected=[f'01{p:02X}' for p in window.capture_selected()],weights=window.capture_weights,
                      focused_rows=window.capture_table.rowCount(),errors=window.error_count,
                      same_recording_through_transition=True,vehicle_verified=False,
                      states=[window.capture_table.item(r,3).text() for r in range(window.capture_table.rowCount())])
        window.grab().save(str(output/'drive-capture.png'))
        window.marker_note.setText('Synthetic fixture note'); window.note_button.click(); window.journey_end.click()
        window.finish_session(); window.send('disconnect'); stage='finish'
    elif stage=='finish' and not window.recording_id and window.worker.transport is None:
        session=next(s for s in list_sessions(output/'data') if s['id']==session_id)
        original=(output/'data'/session['raw_path']).read_bytes()
        path=output/'research-bundle.zip'
        original_dialog=QFileDialog.getSaveFileName
        try:
            QFileDialog.getSaveFileName=lambda *a,**k:(str(path),'ZIP')
            window.capture_bundle.click()
        finally: QFileDialog.getSaveFileName=original_dialog
        assert (output/'data'/session['raw_path']).read_bytes()==original
        with zipfile.ZipFile(path) as z:
            for line in z.read('SHA256SUMS.txt').decode().splitlines():
                digest,name=line.split('  '); assert hashlib.sha256(z.read(name)).hexdigest()==digest
            summary=json.loads(z.read('session-summary.json')); stats=json.loads(z.read('polling-statistics.json'))
            markers=json.loads(z.read('markers.json')); assert [m['event'] for m in markers]==['Journey Start','Note','Journey End']
            assert markers[1]['note_redacted'] and markers[1]['note']=='REDACTED_USER_NOTE'
            assert all(stats[f'7E8:{p:02X}']['decoded_samples']>=2 for p in DRIVE_WEIGHTS)
            result.update(bundle_files=len(z.namelist()),bundle_checksums_verified=True,raw_unchanged=True,
                          sessions_closed=bool(session['ended']),recorded_requests=summary['requests'])
            result['journey_markers']=len(markers)
        window.grab().save(str(output/'finished-session.png'))
        timer.stop(); window.close()

timer=QTimer(); timer.timeout.connect(tick); timer.start(100); app.exec()
(output/'validation.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
assert result.get('bundle_checksums_verified') and result['focused_rows']==7 and result['errors']==0,result
assert result['sessions_closed'] and not window.worker.is_alive(),result
print(json.dumps(result))
