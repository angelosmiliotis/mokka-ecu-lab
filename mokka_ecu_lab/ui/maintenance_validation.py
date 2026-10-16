"""Explicit synthetic library/managed-version Windows acceptance; never default startup."""
from datetime import datetime,timedelta,timezone
from pathlib import Path
import json,time
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from mokka_ecu_lab.library import ReportLibrary,digest
from mokka_ecu_lab.logging import Recorder,connect_database
from mokka_ecu_lab.logging.bundle import export_research_bundle
from mokka_ecu_lab.analysis.obd import analyze_obd,export_obd_report
from mokka_ecu_lab.research.evidence import read_bundle
from mokka_ecu_lab.versions import ManagedVersions,release_info

def prepare_constructed_maintenance(root,references):
    root=Path(root);legacy=root/'constructed-legacy';legacy.mkdir();journal_root=root/'constructed-journals';hashes={}
    for i in range(6):
        recorder=Recorder(journal_root,'SIMULATED',dict(purpose='CONSTRUCTED_STORAGE_CLASSIFICATION; not a throughput measurement'))
        start=datetime(2000,1,2,10,i,tzinfo=timezone.utc)
        if i<5:
            failed=i in (3,4)
            recorder.evidence(dict(application_version='SYNTHETIC',stationary_benchmark=dict(kind='AUTO_60S_V1',completed=not failed,rate=(2,3,4,3,4)[i],requests=0,session_id=recorder.id,
                measurement_duration_seconds=0 if failed else 60,measurement_started_monotonic=None if failed else 100,mode='SIMULATED',reason='Preflight aborted: could not open port CONSTRUCTED semaphore 121' if failed else 'Constructed COMPLETED class; no throughput claim')))
        recorder.close();db=connect_database(journal_root)
        db.execute('UPDATE sessions SET started=?,ended=? WHERE id=?',(start.isoformat(),(start+timedelta(seconds=65)).isoformat(),recorder.id));db.commit();db.close()
        bundle=legacy/(recorder.id+'-constructed.zip');export_research_bundle(journal_root,recorder.id,bundle);export_obd_report(analyze_obd([bundle]),bundle.with_suffix('.html'))
    for p in legacy.iterdir():hashes[p]=digest(p)
    assert len(hashes)==18
    library=ReportLibrary(root);plan=library.preview_migration(legacy);library.migrate(plan,plan['approval_token']);library.migrate(plan,plan['approval_token'])
    rows=library.rows();assert len(rows)==6 and sum(r['status']=='FAILED_COM_OPEN' for r in rows)==2
    for r in rows:library.label(r['library_id'],'CONSTRUCTED classification fixture')
    wrapper=root.parent/(root.name+'-synthetic-run.zip');library.export_run(rows[0]['library_id'],wrapper)
    assert read_bundle(wrapper)[0]==rows[0]['evidence_id']
    assert all(digest(p)==sha for p,sha in hashes.items())
    manager=ManagedVersions(root.parent/(root.name+'-managed-versions'),root);installed=[]
    if len(references)!=2:raise ValueError('Two exact previously published Windows release ZIPs are required for isolated upgrade/rollback validation')
    for path in references:
        path=Path(path);tag=path.name.removeprefix('MokkaECULab-').removesuffix('-Windows11-x64.zip')
        release=release_info(tag);preview=manager.preview_install(path,release);row=manager.install(preview,preview['approval_token']);installed.append(row)
        activation=manager.preview_activation(row['key']);manager.activate(activation,activation['approval_token'])
    previous=manager.state()['previous'];assert previous==installed[0]['key']
    rollback=manager.preview_activation(previous);manager.rollback(rollback['approval_token'])
    assert manager.state()['current']==installed[0]['key'] and all(manager.verify(r['key'])['verified'] for r in installed)
    return dict(library_rows=library.rows(),migration=plan,manager=manager,inventory=manager.inventory(),install_preview=preview,
        validation=dict(passed=True,source='SIMULATED',hardware_connected=False,private_input_used=False,synthetic_run_groups=6,synthetic_original_files=18,original_bytes_unchanged=True,
            copy_only_migration_idempotent=True,failed_com_open_groups=2,wrapper_identity_verified=True,actual_old_executable_smoke_exit_codes=[r['smoke']['exit_code'] for r in installed],
            current_and_rollback_verified=True,personal_data_untouched=True,cleanup_actions=[]))

def install_maintenance_validation(ui,app,root,references,*,observer=None):
    root=Path(root);target=root/'maintenance-smoke.json';state='prepare';began=time.monotonic();prepared=None;geometry=[]
    ui.connection_panel.hide();ui.session_panel.advanced.setChecked(False);app.setQuitOnLastWindowClosed(False)
    def accept_prepared(value):
        nonlocal prepared,state
        prepared=value;ui.history_panel.loaded(value['library_rows']);ui.versions_panel.manager=value['manager']
        report=value['inventory'];ui.versions_panel.last_inventory=report;ui.versions_panel.build.clear()
        for b in report['builds']:ui.versions_panel.build.addItem(b['key']+' · '+b['role'],b['key'])
        ui.versions_panel.identity.setText('SYNTHETIC managed-copy validation · CURRENT '+str(report['state']['current'])+' · ROLLBACK '+str(report['state']['previous']))
        state='views'
    def tick():
        nonlocal state
        try:
            if time.monotonic()-began>180:raise AssertionError('Bounded maintenance validation timeout')
            ui.drain()
            if state=='prepare' and not ui.history_panel.jobs.busy():
                ui.history_panel.jobs.start(lambda:prepare_constructed_maintenance(root,references),accept_prepared);state='working'
            elif state=='working' and ui.history_panel.jobs.future is None:
                if prepared is None:raise AssertionError(ui.history_panel.status.text())
            elif state=='views':
                timer.stop()
                for name,index in (('history-all',9),('history-failed-com',9),('managed-versions',10)):
                    ui.tabs.setCurrentIndex(index)
                    ui.history_panel.outcome.setCurrentText('FAILED_COM_OPEN' if name=='history-failed-com' else 'All statuses')
                    if observer:observer(name,ui)
                    else:
                        app.processEvents();ui.grab().save(str(root/(name+'.png')))
                assert ui.history_panel.table.rowCount()==6
                result=prepared['validation'];result.update(native_geometry=geometry,zero_obd_requests=ui.worker.transport is None and ui.worker.recorder is None)
                target.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8');ui.close();app.exit(0);state='done'
        except Exception as exc:
            target.write_text(json.dumps(dict(passed=False,error=str(exc),stage=state),indent=2),encoding='utf-8');timer.stop();ui.close();app.exit(1)
    timer=QTimer();timer.timeout.connect(tick);timer.start(80)
    def cleanup():timer.stop();timer.timeout.disconnect(tick)
    return timer,cleanup
