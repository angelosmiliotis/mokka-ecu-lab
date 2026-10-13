"""Code-owned desktop design tokens. No bundled fonts or external assets."""
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap, QIcon
from PySide6.QtCore import Qt, QPointF

COLORS = dict(canvas='#10161d', sidebar='#131c25', surface='#19232e', raised='#202e3b',
              border='#30404f', text='#e8edf2', muted='#a4b3c2', accent='#77d5c6',
              selected='#24443f', warning='#e7bd7d', error='#f1a5a5')
SPACING = dict(xs=4, small=8, medium=12, large=20)
METRICS = dict(radius=6, control=32, row=34, icon=20, sidebar=188, compact_sidebar=56)
TYPE = dict(body=14, caption=12, badge=12, title=22, step=12, bytes=13)


def stylesheet():
    c = COLORS
    return f"""
    QWidget {{ color: {c['text']}; font-family: 'Segoe UI'; font-size: {TYPE['body']}px; }}
    QMainWindow, QScrollArea, QScrollArea > QWidget > QWidget {{ background: {c['canvas']}; }}
    QWidget#sidebar {{ background: {c['sidebar']}; border-right: 1px solid {c['border']}; }}
    QFrame#panel, QFrame#sensorCard {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 6px; }}
    QLabel#brand {{ font-size: 16px; font-weight: 700; letter-spacing: 1px; }}
    QLabel#pageTitle {{ font-size: {TYPE['title']}px; font-weight: 600; }}
    QLabel#muted, QLabel#caption {{ color: {c['muted']}; }}
    QLabel#caption {{ font-size: {TYPE['caption']}px; }}
    QLabel#sourceIdentity {{ color: {c['accent']}; font-weight: 600; }}
    QLabel#nextActionTitle {{ font-size: 16px; font-weight: 600; }}
    QLabel#sensorValue {{ font-size: 27px; font-weight: 600; }}
    QLabel#badge {{ background: {c['surface']}; border-radius: 4px; padding: 5px 8px; font-size: 12px; }}
    QPushButton {{ background: {c['raised']}; border: 1px solid {c['border']}; border-radius: 6px; padding: 6px 11px; min-height: 18px; }}
    QPushButton:hover {{ background: #2b3d4c; border-color: #657b8c; }}
    QPushButton:pressed {{ background: #334e5a; }}
    QPushButton:focus, QComboBox:focus, QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QCheckBox:focus {{ border: 1px solid {c['accent']}; }}
    QPushButton:disabled {{ color: #8593a0; background: #1a232d; border-color: #29343f; }}
    QPushButton#primary {{ background: {c['selected']}; border-color: #548e84; color: #baf1e7; font-weight: 600; }}
    QPushButton#primary:hover {{ background: #305b52; }}
    QPushButton#primary:disabled {{ background: #1a232d; color: #8593a0; border-color: #29343f; }}
    QPushButton#stop {{ color: {c['warning']}; }}
    QPushButton#stop:disabled {{ color: #8593a0; background: #1a232d; border-color: #29343f; }}
    QPushButton#nav {{ text-align: left; border: 0; padding: 9px 12px; background: transparent; }}
    QPushButton#nav:hover {{ background: {c['raised']}; }}
    QPushButton#nav:checked {{ background: {c['selected']}; color: #baf1e7; }}
    QPushButton#nav:focus {{ border: 1px solid {c['accent']}; }}
    QPushButton#step {{ font-size: {TYPE['step']}px; padding: 5px 6px; background: {c['surface']}; }}
    QPushButton#step[workflowState="COMPLETED"] {{ color: #baf1e7; border-color: #548e84; background: {c['selected']}; }}
    QPushButton#step[workflowState="CURRENT"] {{ color: {c['warning']}; border: 2px solid {c['warning']}; background: {c['surface']}; }}
    QPushButton#step[workflowState="IN_PROGRESS"] {{ color: {c['accent']}; border-color: {c['accent']}; background: {c['raised']}; }}
    QPushButton#step[workflowState="BLOCKED"], QPushButton#step[workflowState="NOT_STARTED"] {{ color: {c['muted']}; }}
    QPushButton#step:focus {{ border: 2px solid {c['text']}; }}
    QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 4px; padding: 5px 7px; min-height: 18px; selection-background-color: {c['selected']}; }}
    QComboBox QAbstractItemView {{ background: {c['raised']}; selection-background-color: {c['selected']}; }}
    QTabWidget::pane {{ border: 0; }}
    QTabBar::tab {{ background: {c['canvas']}; color: {c['muted']}; padding: 8px 12px; border-bottom: 2px solid transparent; }}
    QTabBar::tab:selected {{ color: {c['accent']}; border-bottom: 2px solid {c['accent']}; }}
    QHeaderView::section {{ background: {c['raised']}; color: {c['muted']}; padding: 7px 9px; border: 0; border-bottom: 1px solid {c['border']}; }}
    QTableWidget, QListWidget, QTextEdit {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 4px; selection-background-color: {c['selected']}; gridline-color: #293642; }}
    QTableWidget::item, QListWidget::item {{ padding: 4px; }}
    QTableWidget::item:selected, QListWidget::item:selected {{ background: {c['selected']}; color: {c['text']}; }}
    QTableWidget:focus, QListWidget:focus, QTextEdit:focus {{ border-color: {c['accent']}; }}
    QTextEdit#byteText {{ font-family: 'Consolas'; font-size: {TYPE['bytes']}px; }}
    QGroupBox {{ border: 1px solid {c['border']}; border-radius: 6px; margin-top: 14px; padding: 12px; }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 12px; color: {c['muted']}; }}
    QToolTip {{ background: {c['raised']}; color: {c['text']}; border: 1px solid #657b8c; padding: 6px; }}
    QStatusBar {{ background: {c['sidebar']}; color: {c['muted']}; }}
    QSplitter::handle {{ background: {c['canvas']}; }}
    QScrollBar:vertical {{ background: {c['canvas']}; width: 10px; }}
    QScrollBar:horizontal {{ background: {c['canvas']}; height: 10px; }}
    QScrollBar::handle {{ background: #485c6a; border-radius: 4px; min-height: 24px; min-width: 24px; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
    """


def icon(name, size=20):
    """Original line icons drawn in Qt; available identically in frozen builds."""
    pix = QPixmap(size, size); pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix); p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(size / 24, size / 24); p.setPen(QPen(QColor(COLORS['accent']), 1.6))
    if name == 'dashboard':
        for x, y in ((3, 3), (14, 3), (3, 14), (14, 14)): p.drawRoundedRect(x, y, 7, 7, 1, 1)
    elif name == 'capture':
        p.drawEllipse(3, 3, 18, 18); p.drawEllipse(8, 8, 8, 8)
    elif name == 'sessions':
        p.drawRoundedRect(4, 3, 16, 18, 2, 2)
        for y in (8, 12, 16): p.drawLine(8, y, 16, y)
    elif name == 'explorer':
        p.drawEllipse(3, 3, 12, 12); p.drawLine(14, 14, 21, 21)
    elif name == 'raw':
        for x, sign in ((9, -1), (15, 1)):
            p.drawLine(x, 6, x + sign * 5, 12); p.drawLine(x + sign * 5, 12, x, 18)
    elif name == 'discovery':
        p.drawEllipse(3, 3, 18, 18); p.drawLine(12, 3, 12, 21); p.drawLine(3, 12, 21, 12)
    else:
        p.drawLine(9, 3, 15, 3); p.drawLine(10, 3, 10, 10); p.drawLine(14, 3, 14, 10)
        p.drawPolyline([QPointF(10, 10), QPointF(4, 20), QPointF(20, 20), QPointF(14, 10)])
        p.drawLine(7, 15, 17, 15)
    p.end(); return QIcon(pix)


def style_table(table):
    table.verticalHeader().hide(); table.verticalHeader().setDefaultSectionSize(METRICS['row'])
    table.setShowGrid(False); table.setAlternatingRowColors(False)


def style_chart(chart):
    chart.setBackgroundBrush(QColor(COLORS['surface']))
    chart.setPlotAreaBackgroundVisible(False)
    chart.setTitleBrush(QColor(COLORS['muted']))
    chart.setTitleFont(QFont('Segoe UI', 9))
    chart.legend().hide()
    for axis in chart.axes():
        axis.setLabelsColor(QColor(COLORS['muted'])); axis.setTitleBrush(QColor(COLORS['muted']))
        axis.setGridLineColor(QColor(COLORS['border']))
        axis.setLinePenColor(QColor(COLORS['border']))
