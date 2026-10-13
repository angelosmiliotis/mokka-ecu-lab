"""Native Windows v0.2.6 UX/state checks using only the existing simulator."""
import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QTimer,Qt
from PySide6.QtWidgets import QApplication,QFileDialog
from mokka_ecu_lab.ui.window import MainWindow
from mokka_ecu_lab.ui.presentation import StepState
from mokka_ecu_lab import __version__

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output-dir',type=Path,required=True)
args=parser.parse_args(); output=args.output_dir.resolve(); output.mkdir(parents=True,exist_ok=True)
app=QApplication([]); ui=MainWindow(output/'synthetic-data'); ui.timer.stop()
ui.resize(1366,768); ui.scenario.setCurrentText('Diesel alternative layouts'); ui.tabs.setCurrentIndex(6); ui.show()
app.processEvents(); started=time.monotonic(); stage='record'; result={}; baseline={}; session_id=None


def screenshot(name):
    ui.statusBar().showMessage('Synthetic simulator only · no hardware verification or vehicle data')
    app.processEvents(); assert ui.grab().save(str(output/(name+'.png')))


def state(pid):
    row=next(r for r in range(ui.capture_table.rowCount()) if ui.capture_table.item(r,0).data(Qt.ItemDataRole.UserRole)==pid)
    return ui.capture_table.item(row,3).text()


def between_simulated_replies():
    # Exercise the normal stop path between replies. Existing receive-cancel
    # safety deliberately disconnects if a reply is still in flight.
    transport=ui.worker.transport
    return bool(transport and transport.last_wire_ns is None and .05<time.monotonic()-transport.last_send<.18)


assert ui.worker.transport is None and not ui.recording_id and not ui.capture_finish.isEnabled()
screenshot('capture-startup')
ui.capture_record.click()
assert not ui.recording_id and ui.capture_stepper.states[1]!=StepState.COMPLETED
screenshot('capture-awaiting-record')


def tick():
    global stage,session_id,baseline
    try:
        ui.drain()
        if time.monotonic()-started>85: raise AssertionError('Native workflow deadline')
        if stage=='record' and ui.recording_id:
            session_id=ui.recording_id
            assert ui.worker.transport is None and ui.capture_stepper.states[1]==StepState.IN_PROGRESS
            screenshot('record-before-connect')
            assert ui.next_capture_action=='connect'; ui.capture_next.click(); stage='basic'
        elif stage=='basic' and ui.connected and len(ui.history.get(('7E8',12),[]))>=2:
            assert ui.recording_id==session_id and not ui.capture_active
            assert 'Current sample · Basic polling' in state(12)
            assert 'Current sample · Basic polling' in ui.sensor_cards[0].state.text()
            screenshot('capture-basic-current'); ui.tabs.setCurrentIndex(0); screenshot('dashboard'); ui.tabs.setCurrentIndex(6)
            stage='stop-ready'
        elif stage=='stop-ready' and between_simulated_replies():
            ui.stop_button.click(); stage='stopped'
        elif stage=='stopped' and not ui.polling_active and 'stop' not in ui.pending_actions:
            assert 'Stale' in state(12) and ui.recording_id==session_id
            screenshot('capture-stopped'); ui.start_button.click(); stage='resumed'
        elif stage=='resumed' and ui.polling_active and 'Current sample' in state(12):
            assert ui.next_capture_action=='discover'; ui.capture_next.click(); stage='discovered'
        elif stage=='discovered' and ui.discovery_prepared and not ui.discovery_active:
            assert ui.capture_stepper.states[2]==StepState.COMPLETED and ui.next_capture_action=='configure'
            before=ui.worker.transport.last_send; ui.capture_next.click()
            assert ui.worker.transport.last_send==before and not ui.raw_selected() and 0x83 not in ui.capture_selected()
            for pid in (0x7A,0x88): ui.capture_raw_checks[pid].setChecked(True)
            for i in range(ui.capture_list.count()):
                item=ui.capture_list.item(i)
                if item.data(Qt.ItemDataRole.UserRole)==0x83: item.setCheckState(Qt.CheckState.Checked)
            assert ui.worker.transport.last_send==before
            baseline={p:len(ui.capture_history.get(('7E8',p),[])) for p in (0x7A,0x88,0x83)}
            baseline['errors']=ui.error_count
            ui.update_capture(); assert ui.next_capture_action=='capture'; ui.capture_next.click(); stage='capture'
        elif stage=='capture' and ui.capture_active and all(len(ui.capture_history.get(('7E8',p),[]))-baseline[p]>=2 for p in (0x7A,0x88,0x83)):
            assert ui.capture_stepper.states[4]==StepState.IN_PROGRESS and ui.recording_id==session_id
            assert ui.error_count==baseline['errors'] and ui.capture_raw_pids=={0x7A,0x88}
            assert 'RAW ONLY' in state(0x7A) and 'No verified numeric decoder' in state(0x7A)
            screenshot('capture-active'); ui.capture_technical.setChecked(True); screenshot('capture-technical'); ui.capture_technical.setChecked(False)
            stage='finish-ready'
        elif stage=='finish-ready' and between_simulated_replies():
            ui.capture_next.click(); stage='finished'
        elif stage=='finished' and not ui.recording_id and not ui.polling_active and not ui.pending_actions:
            assert ui.connected and ui.worker.transport is not None and ui.latest_closed_session()
            assert ui.capture_stepper.states[1]!=StepState.COMPLETED and ui.capture_stepper.states[5]==StepState.COMPLETED
            assert ui.next_capture_action=='export' and not ui.capture_finish.isEnabled()
            assert ui.capture_monitor_errors==0
            session=ui.latest_closed_session()
            records=[json.loads(line) for line in (ui.root/session['raw_path']).read_text(encoding='utf-8').splitlines()]
            result['transaction_status_counts']=dict(Counter(r['status'] for r in records if 'status' in r))
            screenshot('capture-finished')
            before=ui.worker.transport.last_send; original=QFileDialog.getSaveFileName
            try:
                QFileDialog.getSaveFileName=lambda *a,**k:(str(output/'synthetic-research-bundle.zip'),'ZIP')
                ui.capture_next.click()
            finally: QFileDialog.getSaveFileName=original
            assert ui.worker.transport.last_send==before and ui.capture_stepper.states[6]==StepState.COMPLETED
            assert ui.bundle_destination==str(output/'synthetic-research-bundle.zip')
            screenshot('capture-exported'); ui.disconnect_button.click(); stage='live-preparation'
        elif stage=='live-preparation' and not ui.adapter_open and ui.worker.transport is None and not ui.pending_actions:
            count=ui.request_count; ui.source.setCurrentIndex(1); ui.port.setEditText('COM4'); ui.connection_panel.show(); ui.drain()
            assert ui.worker.transport is None and not ui.readings and not ui.discovery_prepared
            assert ui.request_count==0 and 'LIVE — Bluetooth / Serial ECU' in ui.capture_identity.text()
            assert not ui.capture_start.isEnabled() and not ui.capture_finish.isEnabled()
            screenshot('live-preparation')
            result.update(version=__version__,source='SIMULATED',private_input_used=False,hardware_connected=False,
                recording_before_connection=True,worker_confirmed_steps=True,basic_polling_current_in_both_views=True,
                stopped_values_stale=True,resume_basic_polling=True,explicit_discovery=True,raw_nox_opt_ins=True,
                monitoring_errors=0,closed_session=True,finish_keeps_adapter_connected=True,successful_bundle_receipt=True,
                source_change_discards_previous_values=True,live_preparation_no_connection=True,
                requests=count,aggregate_rate_limit=ui.rate.maximum())
            timer.stop(); ui.close()
    except Exception as exc:
        result['error']=str(exc); result['stage']=stage; timer.stop(); ui.close()


timer=QTimer(); timer.timeout.connect(tick); timer.start(100); app.exec()
(output/'workflow-validation.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
assert result.get('successful_bundle_receipt') and not ui.worker.is_alive(),result
print(json.dumps(result))
