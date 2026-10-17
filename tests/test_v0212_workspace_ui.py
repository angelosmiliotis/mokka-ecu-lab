"""Explicit GUI approval flows on newly constructed temporary workspaces only."""
import json
from pathlib import Path
import subprocess
import time
from PySide6.QtCore import QSettings,Qt
from PySide6.QtWidgets import QWidget
import pytest
import mokka_ecu_lab.ui.workspace as ui_module
from mokka_ecu_lab.workspace import tree_snapshot


@pytest.fixture
def panel(qt_app,tmp_path,monkeypatch):
    repo=tmp_path/'OneDrive-like Ελληνικό source';repo.mkdir()
    subprocess.run(['git','init',str(repo)],capture_output=True,check=True)
    root=repo/'release';root.mkdir()
    for name in ('constructed-keep','constructed-A','constructed-B'):
        path=root/name;path.mkdir();(path/'fixture.txt').write_text('New synthetic storage fixture '+name)
    subprocess.run(['git','-C',str(repo),'add','-f','release/constructed-keep'],capture_output=True,check=True)
    window=QWidget();window.resize(1000,700);window.settings=QSettings(str(tmp_path/'settings.ini'),QSettings.Format.IniFormat)
    window.settings.setValue('workspace_release_root',str(root))
    monkeypatch.setattr('mokka_ecu_lab.workspace.running_executables',lambda:dict(processes=[]))
    page=ui_module.WorkspacePanel(window);page.show()
    yield page
    page.jobs.close();page.close();window.close()


def wait(page,qt_app):
    deadline=time.monotonic()+8
    while page.jobs.future is not None and time.monotonic()<deadline:
        qt_app.processEvents();time.sleep(.005)
    qt_app.processEvents()
    assert page.jobs.future is None


def check_reviews(page):
    for row in range(page.table.rowCount()):
        if page.table.item(row,2).text()=='REVIEW':page.table.item(row,0).setCheckState(Qt.CheckState.Checked)


def test_page_visit_and_inventory_do_not_move_or_start_obd_and_keep_cannot_select(panel,qt_app):
    root=Path(panel.root_edit.text());before=tree_snapshot(root)
    assert panel.jobs.future is None and panel.last_inventory is None
    panel.inventory_button.click();wait(panel,qt_app)
    assert panel.last_inventory['entry_count']==3 and tree_snapshot(root)==before
    keep=next(row for row in range(3) if panel.table.item(row,2).text()=='KEEP')
    assert not panel.table.item(keep,0).flags() & Qt.ItemFlag.ItemIsUserCheckable
    assert panel.selected_paths()==[] and 'No entries changed' in panel.summary.text()


def test_preview_requires_review_exact_selection_and_explicit_approval(panel,qt_app,tmp_path,monkeypatch):
    previews=[]
    monkeypatch.setattr(ui_module,'preview_dialog',lambda parent,title,plan,approve=None,**kw:previews.append((plan,approve)))
    panel.inventory();wait(panel,qt_app);root=panel.storage.root;before=tree_snapshot(root)
    panel.preview();assert 'acknowledge' in panel.status.text()
    panel.reviewed.setChecked(True);panel.preview();assert 'Check exact' in panel.status.text()
    check_reviews(panel);panel.destination.setText(str(tmp_path/'private new quarantine'))
    panel.preview();wait(panel,qt_app)
    plan,approved=previews[-1]
    assert plan['entry_count']==2 and plan['disk_bytes_freed']==0
    assert tree_snapshot(root)==before and not Path(plan['destination']).exists()
    assert len(plan['kept'])==1 and Path(plan['kept'][0]['path']).name=='constructed-keep'
    approved();wait(panel,qt_app)
    assert len(list(root.iterdir()))==1 and panel.last_receipt.exists()
    assert json.loads(panel.last_receipt.read_text(encoding='utf-8'))['state']=='COMPLETE'
    assert not panel.cancel_button.isEnabled()


def test_cancel_resume_restore_receipts_require_new_visible_approval(panel,qt_app,tmp_path,monkeypatch):
    previews=[]
    monkeypatch.setattr(ui_module,'preview_dialog',lambda parent,title,plan,approve=None,**kw:previews.append((title,plan,approve)))
    panel.inventory();wait(panel,qt_app);root=panel.storage.root;before=tree_snapshot(root)
    check_reviews(panel);panel.reviewed.setChecked(True);panel.destination.setText(str(tmp_path/'quarantine'))
    panel.preview();wait(panel,qt_app)
    execute=panel.storage.execute
    def cancel_before_first(plan,token,*,cancel):
        panel.cancel();return execute(plan,token,cancel=cancel)
    monkeypatch.setattr(panel.storage,'execute',cancel_before_first)
    previews[-1][2]();wait(panel,qt_app)
    receipt=panel.last_receipt
    assert json.loads(receipt.read_text(encoding='utf-8'))['state']=='CANCELLED_PRESERVED'
    assert tree_snapshot(root)==before
    panel.preview_resume(receipt);wait(panel,qt_app)
    assert 'RESUME' in previews[-1][0] and tree_snapshot(root)==before
    previews[-1][2]();wait(panel,qt_app)
    assert len(list(root.iterdir()))==1
    panel.preview_restore(receipt);wait(panel,qt_app)
    assert 'RESTORE' in previews[-1][0] and len(list(root.iterdir()))==1
    previews[-1][2]();wait(panel,qt_app)
    assert tree_snapshot(root)==before
    assert json.loads(receipt.read_text(encoding='utf-8'))['state']=='RESTORED'


def test_private_export_is_outside_git_new_only_and_root_changes_block_old_plan(panel,qt_app,tmp_path,monkeypatch):
    previews=[]
    monkeypatch.setattr(ui_module,'preview_dialog',lambda parent,title,plan,approve=None,**kw:previews.append((plan,approve)))
    panel.inventory();wait(panel,qt_app)
    destination=tmp_path/'private-inventory.json';panel.export_private(destination)
    assert json.loads(destination.read_text(encoding='utf-8'))['entry_count']==3
    before=destination.read_bytes()
    with pytest.raises(FileExistsError):panel.export_private(destination)
    assert destination.read_bytes()==before
    with pytest.raises(ValueError,match='outside Git'):panel.export_private(panel.storage.repo/'PRIVATE.json')
    check_reviews(panel);panel.reviewed.setChecked(True);panel.destination.setText(str(tmp_path/'new private'))
    panel.preview();wait(panel,qt_app);root=panel.storage.root;before=tree_snapshot(root)
    panel.root_edit.setText(str(tmp_path/'not a release'))
    previews[-1][1]();wait(panel,qt_app)
    assert tree_snapshot(root)==before and not (tmp_path/'new private').exists()


def test_failed_execute_clears_cancel_state_without_discarding_originals(panel,qt_app,tmp_path,monkeypatch):
    previews=[]
    monkeypatch.setattr(ui_module,'preview_dialog',lambda parent,title,plan,approve=None,**kw:previews.append((plan,approve)))
    panel.inventory();wait(panel,qt_app);root=panel.storage.root
    check_reviews(panel);panel.reviewed.setChecked(True);panel.destination.setText(str(tmp_path/'new quarantine'))
    panel.preview();wait(panel,qt_app)
    (root/'constructed-A'/'added.txt').write_text('Additional synthetic user item')
    before=tree_snapshot(root);previews[-1][1]();wait(panel,qt_app)
    assert 'changed' in panel.status.text().lower() and tree_snapshot(root)==before
    assert not panel.executing and not panel.cancel_button.isEnabled()
