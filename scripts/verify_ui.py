"""Native Qt screenshot and offline acquisition assertion; never uses COM ports."""
import sys
import json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
from mokka_ecu_lab.ui.window import MainWindow

root = Path(__file__).resolve().parents[1]
app = QApplication([])
window = MainWindow(root / 'samples' / 'ui-validation')
window.show()
result = {}

def finish():
    window.drain()
    result.update(mode=window.mode, tabs=window.tabs.count(), readings=len(window.readings),
                  raw_transactions=len(window.raw_records), errors=window.error_count,
                  connected=window.connected, simulation=window.source.currentIndex() == 0)
    (root / 'samples').mkdir(exist_ok=True)
    window.grab().save(str(root / 'samples' / 'dashboard.png'))
    window.tabs.setCurrentIndex(2)
    window.raw_table.selectRow(max(0,window.raw_table.rowCount()-1))
    window.grab().save(str(root / 'samples' / 'raw-data.png'))
    (root / 'samples' / 'ui-validation.json').write_text(json.dumps(result, indent=2),encoding='utf-8')
    window.close()

QTimer.singleShot(100, window.connect_adapter)
QTimer.singleShot(8000, finish)
app.exec()
assert result['connected'] and result['simulation'] and result['readings'] == 10, result
assert not window.worker.is_alive()
print(json.dumps(result))
