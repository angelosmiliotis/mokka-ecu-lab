"""Synthetic launcher setup UI: visiting and rejecting previews change nothing."""
from pathlib import Path
from types import SimpleNamespace
import time
import pytest
from PySide6.QtWidgets import QPushButton
import mokka_ecu_lab.ui.versions as module


@pytest.fixture
def panel(qt_app,tmp_path):
    def button(label,callback):
        widget=QPushButton(label);widget.clicked.connect(callback);return widget
    window=SimpleNamespace(root=tmp_path/'synthetic personal data',validation=True,
        adapter_open=False,recording_id=None,button=button)
    page=module.VersionsPanel(window)
    yield page
    page.jobs.close();page.close()


def wait(page,app):
    end=time.monotonic()+5
    while page.jobs.future is not None and time.monotonic()<end:
        app.processEvents();time.sleep(.005)
    app.processEvents();assert page.jobs.future is None


def test_visit_and_missing_current_do_not_create_launcher_or_find_desktop(panel,qt_app,monkeypatch):
    monkeypatch.setattr(module,'shortcut_folders',lambda:(_ for _ in ()).throw(AssertionError('No CURRENT')))
    assert panel.desktop_shortcut.isChecked() and not panel.programs_shortcut.isChecked()
    assert not panel.manager.root.exists() and not panel.launcher.root.exists()
    assert panel.jobs.future is None
    panel.setup_launcher_button.click();wait(panel,qt_app)
    assert 'Set as CURRENT' in panel.status.text()
    assert not panel.manager.root.exists() and not panel.launcher.root.exists()


def test_exact_setup_requires_preview_approval_and_uses_current_not_selected_build(panel,qt_app,tmp_path,monkeypatch):
    calls=[];previews=[]
    monkeypatch.setattr(panel.manager,'state',lambda:dict(current='verified-current',previous='verified-rollback'))
    panel.build.addItem('Different selected build','some-other-build')
    folders=dict(desktop=str(tmp_path/'constructed Desktop'),programs=str(tmp_path/'constructed Start Menu'))
    monkeypatch.setattr(module,'shortcut_folders',lambda:folders)
    plan=dict(kind='INSTALL_CURRENT_LAUNCHER',approval_token='constructed approval',
        assets=[dict(source='constructed stage',destination=str(panel.launcher.exe),bytes=42,sha256='f'*64)],
        no_overwrites=True,no_deletions=True)
    def preview(*args):calls.append(('preview',args));return plan
    def install(found,token):
        calls.append(('install',found,token))
        return dict(target=str(panel.launcher.exe),current=dict(current='verified-current'),verified=True)
    monkeypatch.setattr(panel.launcher,'preview',preview)
    monkeypatch.setattr(panel.launcher,'install',install)
    monkeypatch.setattr(module,'preview_dialog',lambda parent,title,found,approve=None,**kw:previews.append((title,found,approve)))
    panel.setup_launcher_button.click();wait(panel,qt_app)
    assert calls==[('preview',('verified-current',folders['desktop'],None,panel.manager.root.parent/'Development/launcher-previews'))]
    assert previews[0][1] is plan and 'new files' in previews[0][0]
    assert not panel.launcher.root.exists() and not Path(folders['desktop']).exists()
    previews[0][2]();wait(panel,qt_app)
    assert calls[-1]==('install',plan,plan['approval_token'])
    assert 'verified-current' in panel.launcher_identity.text() and 'starts disconnected' in panel.launcher_identity.text()
    panel.programs_shortcut.setChecked(True);panel.setup_launcher_button.click();wait(panel,qt_app)
    assert calls[-1][1][1:3]==(folders['desktop'],folders['programs'])


def test_unchecked_destinations_and_failed_existing_launcher_leave_targets_untouched(panel,qt_app,monkeypatch):
    panel.desktop_shortcut.setChecked(False);panel.setup_launcher_button.click()
    assert 'Choose Desktop' in panel.status.text() and panel.jobs.future is None
    monkeypatch.setattr(panel.manager,'state',lambda:dict(current='verified-current'))
    monkeypatch.setattr(module,'shortcut_folders',lambda:dict(desktop='constructed Desktop',programs='constructed Programs'))
    def existing(*args):raise ValueError('Existing shortcut preserved: constructed Desktop/Mokka ECU Lab.lnk')
    monkeypatch.setattr(panel.launcher,'preview',existing)
    panel.desktop_shortcut.setChecked(True);panel.setup_launcher_button.click();wait(panel,qt_app)
    assert 'Existing shortcut preserved' in panel.status.text()
    assert not panel.launcher.root.exists()
