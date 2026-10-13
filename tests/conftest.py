"""Own Qt's lifecycle explicitly, including chart widgets, across GUI tests."""
import os
from pathlib import Path
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import pytest
from PySide6.QtCore import QCoreApplication,QEvent
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFontDatabase


@pytest.fixture(scope='session')
def qt_app():
    app=QApplication.instance() or QApplication([])
    # Qt's Windows offscreen plugin has no system font database. Load the
    # installed OS font for realistic geometry instead of fallback box glyphs.
    font=Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'/'segoeui.ttf'
    if os.name=='nt' and font.exists():
        assert QFontDatabase.addApplicationFont(str(font))>=0
    yield app
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)


@pytest.fixture(autouse=True)
def release_qt_windows():
    yield
    app=QApplication.instance()
    if app:
        for widget in app.topLevelWidgets():
            widget.close(); widget.deleteLater()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        app.processEvents()
