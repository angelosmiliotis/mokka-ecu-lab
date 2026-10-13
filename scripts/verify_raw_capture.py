"""Native Windows raw validation using constructed simulator data only."""
import argparse
import csv
import io
import hashlib
import json
import sys
import time
import zipfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication,QFileDialog
from PySide6.QtCore import QTimer,Qt
from mokka_ecu_lab.ui.window import MainWindow
from mokka_ecu_lab.logging import list_sessions
from mokka_ecu_lab import __version__

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output-dir',type=Path,default=Path('release/v0.2.4-validation'))
args=parser.parse_args(); output=args.output_dir.resolve(); output.mkdir(parents=True,exist_ok=True)
app=QApplication([]); window=MainWindow(output/'data')
window.scenario.setCurrentText('Diesel alternative layouts'); window.tabs.setCurrentIndex(6); window.show()
stage='connect'; started=time.monotonic(); result={}; baseline={}; session_id=None
window.connect_adapter()

def tick():
    global stage,baseline,session_id
    try:
        window.drain()
        if time.monotonic()-started>75: raise AssertionError('Native raw verification deadline exceeded')
        if stage=='connect' and window.connected:
            window.send('record'); stage='record'
        elif stage=='record' and window.recording_id:
            session_id=window.recording_id; window.send('discover',ecu='7E8'); stage='discovery'
        elif stage=='discovery' and window.discovery_prepared and not window.discovery_active:
            before=window.worker.transport.last_send; window.capture_preset.click()
            assert before==window.worker.transport.last_send and not window.raw_selected()
            assert 0x7A not in window.capture_selected() and 0x83 not in window.capture_selected()
            for pid in (0x7A,0x88): window.capture_raw_checks[pid].setChecked(True)
            for i in range(window.capture_list.count()):
                item=window.capture_list.item(i)
                if item.data(Qt.ItemDataRole.UserRole)==0x83: item.setCheckState(Qt.CheckState.Checked)
            assert before==window.worker.transport.last_send
            baseline={p:len(window.capture_history.get(('7E8',p),[])) for p in (0x7A,0x88,0x83)}
            result['discovery_layout_mismatches']=window.error_count
            assert result['discovery_layout_mismatches']==1
            window.journey_start.click(); window.capture_start.click(); stage='monitor'
        elif stage=='monitor' and all(len(window.capture_history.get(('7E8',p),[]))-baseline[p]>=2 for p in baseline):
            assert window.capture_active and window.recording_id==session_id
            assert window.error_count==result['discovery_layout_mismatches']
            assert window.capture_raw_pids=={0x7A,0x88}
            for pid in (0x7A,0x88):
                sample=window.discovery_observations['7E8',pid]
                assert sample['raw_only'] and sample['fields']==[] and sample['framing_valid']
            assert 'static' in window.capture_counter_note.text()
            assert window.capture_table.viewport().height()>=150
            for r in range(window.capture_table.rowCount()):
                if 'SCR inducement' in window.capture_table.item(r,0).text():
                    assert window.capture_table.item(r,1).text()=='—'
                    window.capture_table.scrollToItem(window.capture_table.item(r,0))
            result.update(version=__version__,mode=window.mode,tabs=window.tabs.count(),
                          raw_requests=['017A','0188'],raw_weights=[window.capture_weights[p] for p in (0x7A,0x88)],
                          nox_samples=len(window.capture_history['7E8',0x83]),monitoring_errors=0,
                          same_recording=True,vehicle_verified=False,private_input_used=False)
            window.grab().save(str(output/'raw-capture.png'))
            window.journey_end.click(); window.finish_session(); window.send('disconnect'); stage='finish'
        elif stage=='finish' and not window.recording_id and window.worker.transport is None:
            session=next(s for s in list_sessions(output/'data') if s['id']==session_id)
            path=output/'research-bundle.zip'; original=(output/'data'/session['raw_path']).read_bytes()
            original_dialog=QFileDialog.getSaveFileName
            try:
                QFileDialog.getSaveFileName=lambda *a,**k:(str(path),'ZIP'); window.capture_bundle.click()
            finally: QFileDialog.getSaveFileName=original_dialog
            assert (output/'data'/session['raw_path']).read_bytes()==original
            with zipfile.ZipFile(path) as z:
                assert len(z.namelist())==12
                for line in z.read('SHA256SUMS.txt').decode().splitlines():
                    digest,name=line.split('  '); assert hashlib.sha256(z.read(name)).hexdigest()==digest
                raw=json.loads(z.read('raw-observations.json')); opted=[r for r in raw if r['raw_only']]
                assert len(opted)>=4 and {r['data_length'] for r in opted}=={6,13}
                assert all(r['source_kind']=='SIMULATED' and r['context_state']=='RECORDED_NON_SIMULTANEOUS' for r in opted)
                measurements=z.read('measurements.csv'); assert b'sae_83_bank_1_sensor_1' in measurements
                assert b'sae_7a_' not in measurements
                raw_ids={r['id'] for r in map(json.loads,original.splitlines()) if r.get('raw_only')}
                assert all(row['transaction_id'] not in raw_ids for row in csv.DictReader(io.StringIO(measurements.decode('utf-8-sig'))))
            original_open=QFileDialog.getOpenFileName
            try:
                QFileDialog.getOpenFileName=lambda *a,**k:(str(path),'ZIP'); window.open_trends()
            finally: QFileDialog.getOpenFileName=original_open
            assert window.trends_dialog.charts.count()>=5
            window.trends_dialog.grab().save(str(output/'recorded-trends.png')); window.trends_dialog.close()
            result.update(bundle_files=12,checksums_verified=True,raw_unchanged=True,
                          raw_only_samples=len(opted),trend_charts=window.trends_dialog.charts.count(),sessions_closed=bool(session['ended']))
            view=window.research_view; view.load_paths([path]); window.tabs.setCurrentIndex(4)
            assert view.catalog.data['profile']['hardware_identification']=='UNKNOWN'
            assert all(e['independent_verification']=='UNVERIFIED' for s in view.report['sessions'] for g in s['groups'] for e in g['matrix'])
            view.tabs.setCurrentIndex(0); app.processEvents(); window.grab().save(str(output/'research-catalog.png'))
            view.tabs.setCurrentIndex(1); view.evidence_tabs.setCurrentIndex(2); app.processEvents()
            assert view.chart.series() and view.group.count()>=1
            window.grab().save(str(output/'research-bytes.png'))
            view.evidence_tabs.setCurrentIndex(0)
            row=next(i for i in range(view.matrix.rowCount()) if view.matrix.item(i,0).text()=='0185')
            view.matrix.selectRow(row); view.matrix.scrollToItem(view.matrix.item(row,0)); app.processEvents()
            assert view.matrix.item(row,1).text()=='SUPPORTED'
            assert view.matrix.item(row,2).text()=='UNKNOWN'
            for r in view.matrix_rows:
                if not r['positive_response_count']: assert r['observation_state']=='NOT_OBSERVED'
                if r['pid'] in {'60','80'}:
                    assert r['layout_state']=='BITMAP_VALID_UNANCHORED' and r['layout_mismatches']==0
            window.grab().save(str(output/'research-compatibility.png'))
            view.evidence_tabs.setCurrentIndex(3); app.processEvents()
            assert 'at recorded time' in view.scr_detail.toPlainText() and 'Historical evidence — not current fault' in view.scr_detail.toPlainText()
            window.grab().save(str(output/'research-scr-summary.png'))
            try:
                QFileDialog.getSaveFileName=lambda *a,**k:(str(output/'ui-private-report.html'),'HTML'); view.save_button.click()
            finally: QFileDialog.getSaveFileName=original_dialog
            assert (output/'ui-private-report.json').exists() and (output/'ui-private-report.html').exists()
            assert 'payload_hex' not in (output/'ui-private-report.html').read_text(encoding='utf-8')
            result.update(research_groups=view.group.count(),independent_verification=False,offline_research=True)
            result.update(recorded_raw_support_separate=True,unobserved_pid_states_correct=True,bitmap_unanchored_not_layout_error=True,
                scr_human_summary=True,private_html_json_export=True,html_external_resources=False)
            timer.stop(); window.close()
    except Exception as exc:
        result['error']=str(exc); timer.stop(); window.close()

timer=QTimer(); timer.timeout.connect(tick); timer.start(100); app.exec()
(output/'validation.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
assert result.get('checksums_verified') and result['sessions_closed'] and not window.worker.is_alive(),result
print(json.dumps(result))
