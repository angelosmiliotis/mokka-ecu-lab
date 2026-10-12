import argparse
import os
from pathlib import Path

def main():
    parser = argparse.ArgumentParser(description="Mokka ECU Lab — read-only local diagnostics")
    parser.add_argument("--data-dir", type=Path, default=Path(os.environ.get("LOCALAPPDATA", Path.home())) / "MokkaECULab" / "data")
    parser.add_argument("--smoke-test", action="store_true", help="Offline UI test; never connects to hardware")
    parser.add_argument('--analyze-bundles',nargs='+',type=Path,help='Offline local Research Bundle analysis; starts no GUI or transport')
    parser.add_argument('--research-output',type=Path,help='Separate private JSON analysis destination')
    args = parser.parse_args()
    if args.analyze_bundles:
        if not args.research_output: parser.error('--research-output is required with --analyze-bundles')
        from mokka_ecu_lab.research.evidence import analyze_bundles,save_analysis
        save_analysis(analyze_bundles(args.analyze_bundles),args.research_output,args.analyze_bundles)
        return 0
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QTimer
    from mokka_ecu_lab.ui.window import MainWindow
    app = QApplication([])
    app.setApplicationName("Mokka ECU Lab")
    window = MainWindow(args.data_dir); window.show()
    if args.smoke_test:
        QTimer.singleShot(100, window.connect_adapter)  # Default source is explicitly simulation.
        QTimer.singleShot(3500, lambda: window.send("record"))
        QTimer.singleShot(6500, lambda: window.send("record_stop"))
        QTimer.singleShot(7200, window.close)
    return app.exec()

if __name__ == "__main__":
    raise SystemExit(main())
