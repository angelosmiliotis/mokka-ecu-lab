"""Local-only recorded trends, with separate ECU and source selections."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog,QVBoxLayout,QLabel,QComboBox,QTabWidget,QWidget,QTableWidget,QTableWidgetItem
from PySide6.QtCharts import QChart,QChartView,QScatterSeries
from .theme import style_chart,style_table,stylesheet


class TrendsDialog(QDialog):
    def __init__(self,report,parent=None):
        super().__init__(parent)
        self.setStyleSheet(stylesheet())
        self.report=report; self.setWindowTitle('Recorded trends · local only'); self.resize(1100,750)
        layout=QVBoxLayout(self)
        label=QLabel(report['limitations']); label.setWordWrap(True); layout.addWidget(label)
        self.source=QComboBox()
        for index,group in enumerate(report['groups']):
            self.source.addItem(f"{group['ecu']} · {group['mode']} · {group['source_kind']}",index)
        layout.addWidget(self.source)
        self.summary=QTableWidget(0,7); self.summary.setHorizontalHeaderLabels(['Field','Unit','Samples','Min','Max','Max gap (s)','Interpretation limit'])
        self.summary.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.summary.horizontalHeader().setStretchLastSection(True)
        style_table(self.summary)
        layout.addWidget(self.summary,1)
        self.charts=QTabWidget(); layout.addWidget(self.charts,2)
        layout.addWidget(QLabel(f"Invalid rows omitted: {report['ignored_invalid_rows']}. Chart preview: at most 2000 points per field; summaries use all loaded samples."))
        self.source.currentIndexChanged.connect(self.show_group); self.show_group()

    def show_group(self,*args):
        self.summary.setRowCount(0)
        while self.charts.count():
            widget=self.charts.widget(0); self.charts.removeTab(0); widget.deleteLater()
        if not self.report['groups']: return
        group=self.report['groups'][self.source.currentData()]
        for row,item in enumerate(group['summary']):
            self.summary.insertRow(row)
            for col,key in enumerate(['sensor_id','unit','samples','minimum','maximum','max_gap_seconds','note']):
                self.summary.setItem(row,col,QTableWidgetItem(str(item[key] if item[key] is not None else '—')))
            if item['sensor_id'] in {'sae_85_warning_time','sae_85_consumption','sae_85_demand'}: continue
            series=QScatterSeries(); series.setMarkerSize(5)
            points=group['series'][item['sensor_id']]
            step=max(1,(len(points)+1999)//2000)
            for elapsed,value in points[::step]: series.append(elapsed,value)
            chart=QChart(); chart.addSeries(series); chart.createDefaultAxes()
            chart.setTitle(f"{item['sensor_id']} ({item['unit']}) · recorded points · {group['source_kind']}")
            chart.axes(Qt.Orientation.Horizontal)[0].setTitleText('Elapsed seconds in selected ECU/source group')
            chart.axes(Qt.Orientation.Vertical)[0].setTitleText(item['unit'])
            chart.legend().hide()
            style_chart(chart)
            view=QChartView(chart); self.charts.addTab(view,item['sensor_id'])
        self.summary.resizeColumnsToContents()
