"""Native Windows Full Auto workflow QA using only the existing simulator."""
import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QTimer,Qt
from PySide6.QtWidgets import QApplication,QFileDialog
from mokka_ecu_lab.ui.window import MainWindow
from mokka_ecu_lab.ui.phases import PhaseDialog
from mokka_ecu_lab.research.evidence import analyze_bundles
from mokka_ecu_lab import __version__

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output-dir',type=Path,required=True)
parser.add_argument('--scale',type=float,default=1)
args=parser.parse_args(); output=args.output_dir.resolve(); output.mkdir(parents=True,exist_ok=True)
app=QApplication([]); ui=MainWindow(output/'synthetic-data'); ui.resize(round(1366/args.scale),round(768/args.scale))
ui.scenario.setCurrentText('Diesel alternative layouts'); ui.tabs.setCurrentIndex(6); ui.show()
app.processEvents(); result={}; stage='start'; started=time.monotonic(); previous=started; gaps=[]; dialog=None
assert abs(ui.devicePixelRatioF()-args.scale)<.02


def screenshot(name,widget=ui):
    ui.statusBar().showMessage('Synthetic simulation · no hardware connected · no private driving evidence')
    app.processEvents(); assert widget.grab().save(str(output/(name+'.png')))


screenshot('full-auto-before-consent'); ui.auto_consent.setChecked(True); ui.auto_start.click()
assert not ui.capture_active and not ui.recording_id


def tick():
    global stage,previous,dialog
    now=time.monotonic(); gaps.append(now-previous); previous=now
    try:
        ui.drain()
        if now-started>120: raise AssertionError('Native Full Auto validation deadline: '+stage)
        receipt=ui.auto_receipt
        if stage=='start' and receipt.get('state') in {'CONNECTING','DISCOVERING'}:
            screenshot('full-auto-worker-stages'); stage='ready'
        elif stage in {'start','ready'} and receipt.get('state')=='READY' and all(
                receipt['observed'].get(pid,{}).get('positive_samples',0)>=3 for pid in receipt['effective_schedule']):
            assert receipt['dpf']['recorded_positive_six_byte_frames']>=2 and receipt['dpf']['worker_scheduled']
            assert receipt['raw_consent'] and ui.capture_raw_pids=={0x7A}
            assert {0x7A,0x83,0x85,0x88,0x0B,0x04}<=ui.capture_weights.keys()
            assert all(w==1 for w in ui.capture_weights.values())
            assert 'worker scheduled YES' in ui.auto_dpf.text()
            screenshot('full-auto-ready'); ui.capture_sections.setCurrentIndex(3)
            ui.tabs.widget(6).verticalScrollBar().setValue(ui.tabs.widget(6).verticalScrollBar().maximum())
            screenshot('full-auto-coverage')
            ui.tabs.widget(6).verticalScrollBar().setValue(0)
            ui.capture_sections.setCurrentIndex(0); ui.capture_technical.setChecked(True); screenshot('full-auto-technical')
            row=next(i for i in range(ui.capture_table.rowCount()) if ui.capture_table.item(i,0).data(Qt.ItemDataRole.UserRole)==0x7A)
            assert ui.capture_table.item(row,1).text()=='—'
            result.update(version=__version__,private_input_used=False,hardware_connected=False,
                one_preset_consent=True,recorded_initialization=True,automatic_all_eligible=True,
                scheduled_pids=[f'01{p:02X}' for p in ui.capture_weights],
                stored_017a_raw_frames=receipt['dpf']['recorded_positive_six_byte_frames'],
                raw_numeric_unavailable=True,monitoring_errors=ui.capture_monitor_errors,
                observed_samples={p:s['positive_samples'] for p,s in receipt['observed'].items()},
                observed_max_gaps_seconds={p:s['maximum_gap_seconds'] for p,s in receipt['observed'].items()})
            ui.capture_technical.setChecked(False); stage='finish'
        elif stage=='finish':
            t=ui.worker.transport
            if t and t.last_wire_ns is None and .05<now-t.last_send<.18:
                ui.capture_finish.click(); stage='closed'
        elif stage=='closed' and not ui.recording_id and not ui.polling_active and receipt.get('state')=='FINISHED':
            assert ui.connected and ui.latest_closed_session() and receipt['recording_active'] is False
            assert receipt['dpf_proof_met_before_close'] and receipt['closed_at']
            screenshot('full-auto-finished')
            session=ui.latest_closed_session(); journal=ui.root/session['raw_path']; original=hashlib.sha256(journal.read_bytes()).hexdigest()
            records=[json.loads(l) for l in journal.read_text(encoding='utf-8').splitlines()]
            wire=[r['monotonic_ns'] for r in records if r.get('sent')]
            assert all(b-a>=250000000 for a,b in zip(wire,wire[1:]))
            assert records[0]['command']=='ATI'
            original_dialog=QFileDialog.getSaveFileName
            try:
                QFileDialog.getSaveFileName=lambda *a,**k:(str(output/'synthetic-research-bundle.zip'),'ZIP')
                ui.capture_bundle.click()
            finally: QFileDialog.getSaveFileName=original_dialog
            assert ui.bundle_destination==str(output/'synthetic-research-bundle.zip')
            assert hashlib.sha256(journal.read_bytes()).hexdigest()==original
            report=analyze_bundles([output/'synthetic-research-bundle.zip'])
            r=report['sessions'][0]['acquisition_receipt']; assert r['dpf_proof_met_before_close']
            coverage=report['sessions'][0]['groups'][0]['capture_coverage']
            assert next(c for c in coverage if c['pid']=='7A')['recorded_raw_only_positive_count']>=2
            screenshot('full-auto-exported')
            result.update(closed_recording=True,finish_between_replies_keeps_adapter=True,
                original_journal_unchanged=True,checksums_verified=True,wire_cap_verified=True,
                maximum_gui_tick_gap_seconds=max(gaps),gui_ticks=len(gaps),private_bundle_components=13)
            assert max(gaps)<1.5, ('GUI responsiveness',max(gaps))
            last_send=ui.worker.transport.last_send; result['offline_last_send']=last_send
            dialog=PhaseDialog(output/'synthetic-research-bundle.zip',ui); dialog.show(); stage='phase-load'
        elif stage=='phase-load' and dialog.data and dialog.data['groups']:
            group=dialog.data['groups'][0]; points=[r for rows in group['fields'].values() for r in rows]
            points.sort(key=lambda r:r['epoch']); dialog.timestamp.setText(points[len(points)//2]['timestamp'])
            dialog.uncertainty.setValue(0); dialog.note.setText('Synthetic user-reported phase for visual QA only'); dialog.consent.setChecked(True)
            dialog.compare_button.click(); stage='phase-report'
        elif stage=='phase-report' and dialog.report:
            assert dialog.report['causal_conclusion'] is None and not dialog.report['interpolation']
            assert ui.worker.transport.last_send==result.pop('offline_last_send')
            screenshot('offline-phase-statistics',dialog); dialog.tabs.setCurrentIndex(2); screenshot('offline-phase-utc-plot',dialog)
            geometry=[]
            for width,height in ((1280,720),(1366,768),(1536,864),(1920,1080)):
                logical=(round(width/args.scale),round(height/args.scale)); dialog.resize(*logical); app.processEvents()
                assert (dialog.width(),dialog.height())==logical,('Phase dialog beyond target',logical,dialog.size())
                for index,name in ((0,'phase-statistics'),(2,'phase-utc-plot')):
                    dialog.tabs.setCurrentIndex(index); app.processEvents()
                    assert dialog.scroll.widget().width()<=dialog.scroll.viewport().width()+1,('Phase horizontal page overflow',logical)
                    dialog.scroll.verticalScrollBar().setValue(0); app.processEvents(); screenshot(f'{width}x{height}-{name}',dialog)
                    geometry.append(dict(physical=[width,height],logical=list(logical),scale=args.scale,page=name,horizontal_page_overflow=False))
            result['phase_native_geometry']=geometry
            result['offline_phase_no_transport']=True; result['phase_user_reported_only']=True
            dialog.close(); timer.stop(); ui.close(); stage='done'
    except Exception as exc:
        result['error']=str(exc); result['stage']=stage; timer.stop()
        if dialog: dialog.close()
        ui.close()


timer=QTimer(); timer.timeout.connect(tick); timer.start(50); app.exec()
(output/'full-auto-validation.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
assert stage=='done' and not ui.worker.is_alive(),result
print(json.dumps(result))
