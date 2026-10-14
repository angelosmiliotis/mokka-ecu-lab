"""Native Qt screenshot and offline acquisition assertion; never uses COM ports."""
import sys
import json
import argparse
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
from mokka_ecu_lab.ui.window import MainWindow
from mokka_ecu_lab import __version__
from mokka_ecu_lab.transport.simulator import SCENARIOS

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--scenario', choices=SCENARIOS, default='Normal idle')
parser.add_argument('--output-dir', type=Path, default=root / 'samples')
options = parser.parse_args()
output = options.output_dir
app = QApplication([])
window = MainWindow(output / 'ui-validation',validation=True)
window.session_panel.advanced.setChecked(True)
window.scenario.setCurrentText(options.scenario)
window.show()
result = {}

def finish():
    window.drain()
    result.update(mode=window.mode, tabs=window.tabs.count(), readings=len(window.readings),
                  raw_transactions=len(window.raw_records), errors=window.error_count,
                  connected=window.connected, simulation=window.source.currentIndex() == 0,
                  version=__version__, scenario=options.scenario, polling=window.polling_active,
                  requires_reconnect=window.requires_reconnect, coverage=window.coverage.text(),
                  states=[window.dashboard.item(row, 3).text() for row in range(window.dashboard.rowCount())],
                  source_kinds=sorted({r['source_kind'] for r in window.readings.values()}))
    output.mkdir(parents=True, exist_ok=True)
    window.grab().save(str(output / 'dashboard.png'))
    window.tabs.setCurrentIndex(2)
    window.raw_table.selectRow(max(0,window.raw_table.rowCount()-1))
    window.grab().save(str(output / 'raw-data.png'))
    (output / 'ui-validation.json').write_text(json.dumps(result, indent=2),encoding='utf-8')
    window.close()

QTimer.singleShot(100, window.connect_adapter)
QTimer.singleShot(8000, finish)
app.exec()
assert result['connected'] and result['simulation'] and result['source_kinds'] == ['SIMULATED'], result
if options.scenario == 'Normal idle':
    assert result['readings'] == 10 and result['polling'] and result['errors'] == 0, result
    assert result['states'].count('Valid') == 10, result
elif options.scenario == 'Conditions Not Correct':
    assert not result['polling'] and result['requires_reconnect'] and result['errors'] == 3, result
    assert 'Valid' not in result['states'] and 'current: 0/' in result['coverage'], result
assert not window.worker.is_alive()
print(json.dumps(result))
