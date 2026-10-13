"""Small reusable presentation widgets; none owns acquisition or transport."""
from PySide6.QtCore import Qt, QRect, QSize
from PySide6.QtWidgets import QWidget, QFrame, QLabel, QPushButton, QVBoxLayout, QHBoxLayout, QScrollArea, QLayout
from PySide6.QtGui import QKeySequence, QShortcut
from .theme import icon, METRICS


def caption(text):
    label = QLabel(text); label.setObjectName('muted'); label.setWordWrap(True)
    return label


def page_heading(layout, title, description):
    label = QLabel(title); label.setObjectName('pageTitle'); layout.addWidget(label)
    layout.addWidget(caption(description))


def scroll_page(widget):
    area = QScrollArea(); area.setWidgetResizable(True); area.setFrameShape(QFrame.Shape.NoFrame)
    area.setWidget(widget); return area


class SensorCard(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent); self.setObjectName('sensorCard')
        self.setMinimumHeight(104)
        layout = QVBoxLayout(self); layout.setContentsMargins(12, 8, 12, 8); layout.setSpacing(3)
        self.name = QLabel(); self.name.setObjectName('muted'); layout.addWidget(self.name)
        row = QHBoxLayout(); self.value = QLabel('—'); self.value.setObjectName('sensorValue')
        self.unit = QLabel(); self.unit.setObjectName('muted'); row.addWidget(self.value); row.addWidget(self.unit); row.addStretch(); layout.addLayout(row)
        self.state = QLabel('No sample yet'); self.state.setObjectName('caption'); self.state.setWordWrap(True); layout.addWidget(self.state)
        self.evidence = QLabel(); self.evidence.setObjectName('caption'); layout.addWidget(self.evidence)

    def present(self, name, value, unit, state, evidence):
        self.name.setText(name); self.value.setText(str(value)); self.unit.setText(unit)
        self.state.setText(state); self.evidence.setText(evidence)
        self.setAccessibleName(f'{name}: {value} {unit}. {state}. {evidence}')
        self.setToolTip(f'{name}\n{state}\n{evidence}')


class FlowLayout(QLayout):
    """Wrap action/configuration rows at narrow desktop widths."""
    def __init__(self, parent=None, spacing=8):
        super().__init__(parent); self.items=[]; self.setSpacing(spacing); self.setContentsMargins(0,0,0,0)
    def addItem(self,item): self.items.append(item)
    def count(self): return len(self.items)
    def itemAt(self,index): return self.items[index] if 0<=index<len(self.items) else None
    def takeAt(self,index): return self.items.pop(index) if 0<=index<len(self.items) else None
    def addStretch(self,*args): pass
    def expandingDirections(self): return Qt.Orientation(0)
    def hasHeightForWidth(self): return True
    def heightForWidth(self,width): return self.arrange(QRect(0,0,width,0),True)
    def setGeometry(self,rect):
        super().setGeometry(rect); self.arrange(rect,False)
    def sizeHint(self): return self.minimumSize()
    def minimumSize(self):
        result=QSize()
        for item in self.items: result=result.expandedTo(item.minimumSize())
        return result
    def arrange(self,rect,test):
        x,y,height=rect.x(),rect.y(),0
        for item in self.items:
            if item.isEmpty(): continue
            size=item.sizeHint(); width=min(size.width(),rect.width())
            if x>rect.x() and x+width>rect.right()+1: x=rect.x(); y+=height+self.spacing(); height=0
            if not test: item.setGeometry(QRect(x,y,width,size.height()))
            x+=width+self.spacing(); height=max(height,size.height())
        return y+height-rect.y()


class Sidebar(QWidget):
    ORDER = ((0, 'Dashboard', 'dashboard'), (6, 'Drive Capture', 'capture'),
             (1, 'Sessions', 'sessions'), (3, 'Sensor Explorer', 'explorer'), (2, 'Raw Data', 'raw'),
             (5, 'Discovery', 'discovery'), (4, 'Research', 'research'))

    def __init__(self, tabs, parent=None):
        super().__init__(parent); self.setObjectName('sidebar'); self.tabs = tabs
        self.compact = False; self.buttons = {}; self.group_labels = []
        layout = QVBoxLayout(self); layout.setContentsMargins(8, 14, 8, 12); layout.setSpacing(4)
        for n, (index, label, symbol) in enumerate(self.ORDER):
            if n in (0, 2, 5):
                group = QLabel(('OVERVIEW', 'DATA', 'RESEARCH')[(0, 2, 5).index(n)])
                group.setObjectName('caption'); layout.addWidget(group); self.group_labels.append(group)
            b = QPushButton(label); b.setObjectName('nav'); b.setIcon(icon(symbol)); b.setCheckable(True)
            b.setAccessibleName(label); b.setToolTip(f'{label} · Alt+{n + 1}')
            b.clicked.connect(lambda checked=False, i=index: self.activate(i))
            shortcut = QShortcut(QKeySequence(f'Alt+{n + 1}'), self)
            shortcut.activated.connect(lambda i=index: self.activate(i))
            self.buttons[index] = b; layout.addWidget(b)
        layout.addStretch(); self.local = caption('LOCAL ONLY\nRead-only · ≤ 4 req/s'); layout.addWidget(self.local)
        tabs.currentChanged.connect(self.select); self.select(tabs.currentIndex()); self.set_compact(False)

    def activate(self, index):
        self.tabs.setCurrentIndex(index); self.select(index); self.buttons[index].setFocus()

    def select(self, index):
        for i, button in self.buttons.items(): button.setChecked(i == index)

    def set_compact(self, compact):
        self.compact = compact; self.setFixedWidth(METRICS['compact_sidebar'] if compact else METRICS['sidebar'])
        for index, label, _ in self.ORDER: self.buttons[index].setText('' if compact else self.tabs.tabText(index))
        for label in self.group_labels: label.setVisible(not compact)
        self.local.setVisible(not compact)


class CaptureStepper(QWidget):
    LABELS = ('Connect', 'Record', 'Discover', 'Configure', 'Capture', 'Finish', 'Export')

    def __init__(self, navigate, parent=None):
        super().__init__(parent); row = QHBoxLayout(self); row.setContentsMargins(0, 0, 0, 0); row.setSpacing(4)
        self.buttons = []
        for index, label in enumerate(self.LABELS):
            button = QPushButton(f'{index + 1}  {label}'); button.setObjectName('step'); button.setCheckable(True)
            button.setAccessibleName(f'Show {label.lower()} step; does not start an action')
            button.clicked.connect(lambda checked=False, i=index: navigate(i)); row.addWidget(button); self.buttons.append(button)

    def show_stage(self, index):
        for i, button in enumerate(self.buttons): button.setChecked(i == index)
