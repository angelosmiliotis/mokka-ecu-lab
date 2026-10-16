"""Small reusable presentation widgets; none owns acquisition or transport."""
from PySide6.QtCore import Qt, QRect, QSize
from PySide6.QtWidgets import QWidget, QFrame, QLabel, QPushButton, QVBoxLayout, QHBoxLayout, QScrollArea, QLayout
from PySide6.QtGui import QKeySequence, QShortcut,QIcon
from .theme import icon, METRICS
from .presentation import StepState, STEP_LABELS


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
        self.evidence = QLabel(); self.evidence.setObjectName('caption'); self.evidence.setWordWrap(True); layout.addWidget(self.evidence)

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
    ORDER = ((7, 'Session Dashboard', 'dashboard'), (8, 'Benchmark', 'discovery'), (9,'History / Reports','sessions'),(10,'App Versions','research'),(0, 'Dashboard', 'dashboard'), (6, 'Drive Capture', 'capture'),
             (1, 'Sessions', 'sessions'), (3, 'Sensor Explorer', 'explorer'), (2, 'Raw Data', 'raw'),
             (5, 'Discovery', 'discovery'), (4, 'Research', 'research'))

    def __init__(self, tabs, parent=None):
        super().__init__(parent); self.setObjectName('sidebar'); self.tabs = tabs
        self.compact = False; self.buttons = {}; self.group_labels = []
        layout = QVBoxLayout(self); layout.setContentsMargins(8, 14, 8, 12); layout.setSpacing(4)
        more=QWidget();more_layout=QVBoxLayout(more);more_layout.setContentsMargins(0,0,0,0);more_layout.setSpacing(4)
        area=QScrollArea();area.setWidgetResizable(True);area.setFrameShape(QFrame.Shape.NoFrame);area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff);area.setWidget(more)
        keys={7:'Alt+1',8:'Alt+2',0:'Alt+3',6:'Alt+4',1:'Alt+5',3:'Alt+6',2:'Alt+7',5:'Alt+8',4:'Alt+9',9:'Ctrl+Alt+H',10:'Ctrl+Alt+V'}
        for n, (index, label, symbol) in enumerate(self.ORDER):
            target=layout if n<4 else more_layout
            if n in (0, 4, 7):
                group = QLabel(('OVERVIEW', 'DATA', 'RESEARCH')[(0, 4, 7).index(n)])
                group.setObjectName('caption');target.addWidget(group);self.group_labels.append(group)
            b = QPushButton(label); b.setObjectName('nav'); b.setIcon(icon(symbol)); b.setCheckable(True)
            b.setAccessibleName(label); b.setToolTip(label+' · '+keys[index])
            b.clicked.connect(lambda checked=False, i=index: self.activate(i))
            shortcut = QShortcut(QKeySequence(keys[index]), self)
            shortcut.activated.connect(lambda i=index: self.activate(i))
            self.buttons[index] = b; target.addWidget(b)
        more_layout.addStretch();layout.addWidget(area,1);self.local = caption('LOCAL ONLY\nRead-only · ≤ 4 req/s'); layout.addWidget(self.local)
        tabs.currentChanged.connect(self.select); self.select(tabs.currentIndex()); self.set_compact(False)

    def activate(self, index):
        self.tabs.setCurrentIndex(index); self.select(index); self.buttons[index].setFocus()

    def select(self, index):
        for i, button in self.buttons.items(): button.setChecked(i == index)

    def set_compact(self, compact):
        self.compact = compact; self.setFixedWidth(max(100,METRICS['compact_sidebar']) if compact else METRICS['sidebar'])
        for index, label, symbol in self.ORDER:
            self.buttons[index].setText(({8:'Benchmark',7:'Session',9:'History',10:'Versions'}.get(index,'')) if compact else self.tabs.tabText(index))
            self.buttons[index].setIcon(QIcon() if compact and index in (7,8,9,10) else icon(symbol))
            self.buttons[index].setStyleSheet('padding-left: 4px; padding-right: 4px;' if compact and index in (7,8,9,10) else '')
        for label in self.group_labels: label.setVisible(not compact)
        self.local.setVisible(not compact)


class CaptureStepper(QWidget):
    LABELS = ('Connect', 'Record', 'Discover', 'Configure', 'Capture', 'Finish', 'Export')

    def __init__(self, navigate, parent=None):
        super().__init__(parent); row = QHBoxLayout(self); row.setContentsMargins(0, 0, 0, 0); row.setSpacing(4)
        self.buttons = []; self.states = []; self.selected_stage = None
        for index, label in enumerate(self.LABELS):
            button = QPushButton(); button.setObjectName('step')
            button.clicked.connect(lambda checked=False, i=index: self.visit(i, navigate)); row.addWidget(button); self.buttons.append(button)
        self.present([(StepState.NOT_STARTED, 'No confirmed action yet') for _ in self.LABELS])

    def visit(self, index, navigate):
        self.show_stage(index); navigate(index)

    def show_stage(self, index):
        # Navigation focus is deliberately independent of operational success.
        self.selected_stage = index
        self.buttons[index].setFocus()

    def present(self, steps):
        self.states = [state for state, _ in steps]
        for i, (state, reason) in enumerate(steps):
            button = self.buttons[i]
            button.setText(f'{i + 1}  {self.LABELS[i]}\n{STEP_LABELS[state]}')
            changed=button.property('workflowState')!=state.value
            button.setProperty('workflowState', state.value)
            button.setAccessibleName(f'{self.LABELS[i]}: {STEP_LABELS[state]}. {reason}. Navigation only')
            button.setToolTip(reason + '\nVisiting this step sends no commands and changes no recording.')
            if changed: button.style().unpolish(button); button.style().polish(button)
