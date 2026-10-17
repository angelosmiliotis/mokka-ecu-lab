"""Native synthetic 545-entry storage and locked higher-rate UI acceptance.

Requires fresh explicitly supplied output/data roots. It never inventories the
real checkout release folder and never approves or executes quarantine moves.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QTimer,Qt,QCoreApplication,QEvent
from PySide6.QtWidgets import QApplication
from mokka_ecu_lab.ui.window import MainWindow
from mokka_ecu_lab.ui.local_jobs import preview_dialog
from mokka_ecu_lab.workspace import tree_snapshot


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--data-dir',type=Path,required=True)
    parser.add_argument('--scale',type=float,default=1,choices=(1,1.25,1.5))
    args=parser.parse_args();output=args.output_dir.resolve();data=args.data_dir.resolve()
    if output.exists() or data.exists():parser.error('Fresh isolated synthetic output/data roots are required')
    if any((p/'.git').exists() for base in (data,output) for p in [base,*base.parents]):parser.error('Use isolated synthetic roots outside any repository')
    if 'MokkaECULabSynthetic' not in data.parts:parser.error('Data root must be inside an explicitly named MokkaECULabSynthetic folder')
    output.mkdir(parents=True);data.mkdir(parents=True)
    repo=data/'Constructed workspace';repo.mkdir();release=repo/'release';release.mkdir()
    subprocess.run(['git','init',str(repo)],capture_output=True,check=True)
    for i in range(545):
        folder=release/f'constructed-storage-{i:03d}';folder.mkdir()
        (folder/'fixture.txt').write_text(f'Newly constructed synthetic UI storage item {i}\n',encoding='utf-8')
    subprocess.run(['git','-C',str(repo),'add','-f','release/constructed-storage-000'],capture_output=True,check=True)
    initial=tree_snapshot(release);app=QApplication([]);window=MainWindow(data/'app-data',validation=True)
    panel=window.workspace_panel;panel.root_edit.setText(str(release))
    window.show();assert abs(window.devicePixelRatioF()-args.scale)<.02
    checks=[];failed=[];began=time.monotonic();stage='inventory';panel.inventory()

    def capture(view,index):
        window.tabs.setCurrentIndex(index)
        for width,height in ((1280,720),(1366,768),(1536,864),(1920,1080)):
            logical=(round(width/args.scale),round(height/args.scale));window.resize(*logical);app.processEvents()
            area=window.tabs.currentWidget();area.verticalScrollBar().setValue(0);app.processEvents()
            assert (window.width(),window.height())==logical,(view,logical,window.size())
            assert area.widget().width()<=area.viewport().width()+1,(view,logical)
            window.statusBar().showMessage('CONSTRUCTED 545-folder fixture / OFFLINE model only / no hardware or real cleanup')
            assert window.grab().save(str(output/f'{width}x{height}-{view}.png'))
            checks.append(dict(view=view,physical=[width,height],scale=args.scale,horizontal_page_overflow=False))

    def validate():
        nonlocal stage
        if time.monotonic()-began>90:raise AssertionError('Bounded workspace UI acceptance deadline')
        if stage=='inventory':
            if panel.jobs.future is not None:return
            assert panel.last_inventory and panel.last_inventory['entry_count']==545,panel.status.text()
            assert panel.table.rowCount()==545
            assert sum(e['action']=='KEEP' for e in panel.last_inventory['entries'])>=1
            assert initial==tree_snapshot(release)
            stage='capturing';timer.stop()
            capture('workspace-545-inventory',12)
            row=next(r for r in range(panel.table.rowCount()) if panel.table.item(r,2).text()=='REVIEW')
            panel.table.item(row,0).setCheckState(Qt.CheckState.Checked);panel.reviewed.setChecked(True)
            destination=data/'Private quarantine not created';panel.destination.setText(str(destination))
            plan=panel.storage.preview_quarantine(panel.last_inventory,destination,panel.selected_paths())
            panel.last_plan=plan
            for width,height in ((1280,720),(1366,768),(1536,864),(1920,1080)):
                window.resize(round(width/args.scale),round(height/args.scale));app.processEvents()
                modal_errors=[]
                def reject_preview():
                    dialog=app.activeModalWidget()
                    try:
                        assert dialog is not None
                        assert dialog.width()<=window.width() and dialog.height()<=window.height()
                        assert dialog.grab().save(str(output/f'{width}x{height}-exact-move-preview.png'))
                    except Exception as exc:modal_errors.append(repr(exc))
                    finally:
                        if dialog is not None:dialog.reject()
                QTimer.singleShot(100,reject_preview)
                preview_dialog(window,'CONSTRUCTED exact MOVE preview · approval deliberately withheld',plan,
                    lambda:(_ for _ in ()).throw(AssertionError('Synthetic visual inspection must never approve a move')),
                    approve_label='Approve these exact moves · preview test NEVER clicks this')
                assert not modal_errors,modal_errors
                checks.append(dict(view='exact-move-preview-rejected',physical=[width,height],scale=args.scale,horizontal_page_overflow=False))
            assert not destination.exists() and initial==tree_snapshot(release)
            research=window.higher_rate_panel
            assert not research.live_start.isEnabled()
            capture('higher-rate-locked',11)
            research.start_model();research.timer.stop()
            for _ in range(500):
                if not research.model.active:break
                research.advance_model()
            assert research.snapshot['state']=='COMPLETED' and research.snapshot['actual_transmissions']==0
            capture('higher-rate-constructed-complete',11)
            assert initial==tree_snapshot(release) and not window.adapter_open and not window.polling_active and window.recording_id is None
            result=dict(passed=True,scale=args.scale,private_input_used=False,real_workspace_inspected=False,
                constructed_entries=545,entry_count_unchanged=545,original_fixture_bytes_preserved=True,
                quarantine_preview_only=True,moves=0,deletions=0,actual_transmissions=0,
                higher_rate_live_state='LOCKED',geometry=checks)
            (output/'workspace-validation.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
            stage='done';timer.stop();window.close()

    def tick():
        try:validate()
        except Exception as exc:
            failed.append(repr(exc));timer.stop();window.close();app.exit(1)
    timer=QTimer();timer.timeout.connect(tick);timer.start(100)
    code=app.exec();window.deleteLater();QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    assert not failed and code==0 and stage=='done' and len(checks)==16,(failed,code,stage)
    print(json.dumps(dict(passed=True,checks=len(checks),scale=args.scale,constructed_entries=545,moves=0,live_above_four='LOCKED')))


if __name__=='__main__':main()
