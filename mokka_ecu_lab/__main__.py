import argparse
import os
from pathlib import Path

def main():
    parser = argparse.ArgumentParser(description="Mokka ECU Lab — read-only local diagnostics")
    from mokka_ecu_lab import __version__
    parser.add_argument('--version',action='version',version=__version__)
    parser.add_argument("--data-dir", type=Path, default=Path(os.environ.get("LOCALAPPDATA", Path.home())) / "MokkaECULab" / "data")
    parser.add_argument("--smoke-test", action="store_true", help="Offline UI test; never connects to hardware")
    parser.add_argument('--full-auto-smoke-test',action='store_true',help='Explicit synthetic Windows GUI Full Auto validation; never hardware')
    parser.add_argument('--session-smoke-test',action='store_true',help='Synthetic Connect → Start Session → Finish Session GUI validation; never hardware')
    parser.add_argument('--expanded-session-smoke-test',action='store_true',help='Constructed extended standard session GUI validation; never hardware')
    parser.add_argument('--critical-session-smoke-test',action='store_true',help='Constructed critical subset session GUI validation; never hardware')
    parser.add_argument('--benchmark-smoke-test',action='store_true',help='Constructed Advanced stationary benchmark GUI validation; never hardware')
    parser.add_argument('--sequential-benchmark-smoke-test',action='store_true',help='Three actual 60-second synthetic runs over one idle connection; never hardware')
    parser.add_argument('--maintenance-smoke-test',action='store_true',help='Isolated synthetic report migration and trusted public-build rollback validation')
    parser.add_argument('--maintenance-reference-zips',nargs=2,type=Path,help='Two exact published Windows ZIPs used only by explicit maintenance validation')
    parser.add_argument('--dpf-bundles',nargs='+',type=Path,help='Private offline DPF RAW evolution; starts no GUI or transport')
    parser.add_argument('--dpf-output',type=Path,help='Fresh private DPF HTML / JSON report path')
    parser.add_argument('--obd-bundles',nargs='+',type=Path,help='Private passive inventory/performance analysis; no transport')
    parser.add_argument('--obd-output',type=Path,help='Fresh private OBD HTML / JSON report path')
    parser.add_argument('--analyze-bundles',nargs='+',type=Path,help='Offline local Research Bundle analysis; starts no GUI or transport')
    parser.add_argument('--research-output',type=Path,help='Separate private JSON analysis destination')
    parser.add_argument('--research-html',type=Path,help='Optional self-contained private HTML report; no network resources')
    parser.add_argument('--research-detailed-report',action='store_true',help='Explicitly include raw preview/timestamps in private HTML')
    parser.add_argument('--compare-phases',type=Path,help='Offline private phase comparison from one Research Bundle; no GUI or transport')
    parser.add_argument('--phase-annotations',type=Path,help='Private USER_REPORTED annotation sidecar')
    parser.add_argument('--phase-output',type=Path,help='Fresh private HTML / JSON comparison base path')
    args = parser.parse_args()
    session_validation_requested=args.session_smoke_test or args.expanded_session_smoke_test or args.critical_session_smoke_test
    if sum(bool(v) for v in (args.smoke_test,args.full_auto_smoke_test,args.session_smoke_test,args.expanded_session_smoke_test,args.critical_session_smoke_test,args.benchmark_smoke_test,args.sequential_benchmark_smoke_test,args.maintenance_smoke_test,args.analyze_bundles,args.compare_phases,args.dpf_bundles,args.obd_bundles))>1:
        parser.error('Choose one validation / offline analysis mode')
    if (args.smoke_test or args.full_auto_smoke_test or session_validation_requested or args.benchmark_smoke_test or args.sequential_benchmark_smoke_test or args.maintenance_smoke_test) and args.data_dir.exists():
        parser.error('Synthetic validation requires a fresh --data-dir; existing user data is preserved')
    if bool(args.maintenance_smoke_test)!=bool(args.maintenance_reference_zips):parser.error('Explicit maintenance validation requires two public reference ZIPs; references cannot enable normal-startup maintenance')
    if args.obd_bundles:
        if not args.obd_output:parser.error('--obd-output required with --obd-bundles')
        from mokka_ecu_lab.analysis.obd import analyze_obd,export_obd_report
        export_obd_report(analyze_obd(args.obd_bundles),args.obd_output,args.obd_bundles);return 0
    if args.obd_output:parser.error('--obd-output requires --obd-bundles')
    if args.dpf_bundles:
        if not args.dpf_output: parser.error('--dpf-output is required with --dpf-bundles')
        from mokka_ecu_lab.analysis.dpf import analyze_dpf,export_dpf_report
        export_dpf_report(analyze_dpf(args.dpf_bundles),args.dpf_output,args.dpf_bundles)
        return 0
    if args.dpf_output: parser.error('--dpf-output requires --dpf-bundles')
    if args.full_auto_smoke_test and (args.smoke_test or args.analyze_bundles or args.compare_phases):
        parser.error('Choose one validation / offline analysis mode')
    if args.compare_phases:
        if not args.phase_annotations or not args.phase_output or args.analyze_bundles:
            parser.error('--compare-phases requires --phase-annotations and --phase-output, without --analyze-bundles')
        from mokka_ecu_lab.analysis.phases import load_phase_data,load_annotations,compare_phases,export_phase_report
        data=load_phase_data(args.compare_phases)
        anchors=[a for a in load_annotations(args.phase_annotations) if a['phase']=='Sport on' and a.get('evidence_id')==data['evidence_id']]
        if len(anchors)!=1: parser.error('Select exactly one matching USER_REPORTED Sport on anchor in the sidecar')
        group=next((i for i,g in enumerate(data['groups']) if all(g[k]==anchors[0][k] for k in ('ecu','mode','source_kind'))),None)
        if group is None: parser.error('Annotation source group does not match')
        report=compare_phases(data,group,anchors[0])
        export_phase_report(report,args.phase_output,[args.compare_phases,args.phase_annotations])
        return 0
    if args.phase_annotations or args.phase_output: parser.error('Phase export arguments require --compare-phases')
    if args.analyze_bundles:
        if not args.research_output: parser.error('--research-output is required with --analyze-bundles')
        from mokka_ecu_lab.research.evidence import analyze_bundles
        from mokka_ecu_lab.research.report import export_private_report
        report=analyze_bundles(args.analyze_bundles)
        export_private_report(report,args.research_html or args.research_output,args.analyze_bundles,
            detailed=args.research_detailed_report,json_path=args.research_output)
        return 0
    if args.research_output or args.research_html or args.research_detailed_report:
        parser.error('Research export arguments require --analyze-bundles')
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QTimer,QCoreApplication,QEvent
    from mokka_ecu_lab.ui.window import MainWindow
    app = QApplication([])
    app.setApplicationName("Mokka ECU Lab")
    window = MainWindow(args.data_dir,validation=bool(args.smoke_test or args.full_auto_smoke_test or session_validation_requested or args.benchmark_smoke_test or args.sequential_benchmark_smoke_test or args.maintenance_smoke_test)); window.show()
    if args.maintenance_smoke_test:
        from mokka_ecu_lab.ui.maintenance_validation import install_maintenance_validation
        maintenance_timer,maintenance_cleanup=install_maintenance_validation(window,app,args.data_dir,args.maintenance_reference_zips)
    if args.benchmark_smoke_test or args.sequential_benchmark_smoke_test:
        from mokka_ecu_lab.ui.benchmark_validation import install_benchmark_validation
        benchmark_timer,benchmark_cleanup=install_benchmark_validation(window,app,args.data_dir,sequential=args.sequential_benchmark_smoke_test)
    if session_validation_requested:
        from mokka_ecu_lab.ui.session_validation import install_session_validation
        session_timer,session_cleanup=install_session_validation(window,app,args.data_dir,expanded=args.expanded_session_smoke_test,critical=args.critical_session_smoke_test)
    if args.full_auto_smoke_test:
        import json,time
        from mokka_ecu_lab.logging.bundle import export_research_bundle
        output=args.data_dir/'full-auto-smoke.json'; bundle=args.data_dir/'full-auto-smoke-research.zip'
        if output.exists() or bundle.exists(): parser.error('Use a fresh data directory for Full Auto validation')
        app.setQuitOnLastWindowClosed(False)
        window.source.setCurrentIndex(0); window.scenario.setCurrentText('Diesel alternative layouts')
        window.session_panel.advanced.setChecked(True)
        window.tabs.setCurrentIndex(6); started=time.monotonic(); smoke_state={'stage':'start'}
        def full_auto_tick():
            window.drain(); now=time.monotonic()
            try:
                receipt=window.auto_receipt
                if now-started>70: raise RuntimeError('Full Auto simulation validation timeout')
                if smoke_state['stage']=='start':
                    window.auto_consent.setChecked(True); window.auto_start.click(); smoke_state['stage']='capture'
                elif smoke_state['stage']=='capture' and receipt.get('state')=='READY' and all(
                        receipt['observed'].get(pid,{}).get('positive_samples',0)>=2 for pid in receipt['effective_schedule']):
                    transport=window.worker.transport
                    if transport and transport.last_wire_ns is None and .05<now-transport.last_send<.18:
                        smoke_state['ready_receipt']=receipt; window.finish_session(); smoke_state['stage']='finish'
                elif smoke_state['stage']=='finish' and not window.recording_id and receipt.get('state')=='FINISHED':
                    session=window.latest_closed_session()
                    if not session or not window.connected: raise RuntimeError('Recording closure / connection validation failed')
                    export_research_bundle(args.data_dir,session['id'],bundle)
                    result=dict(passed=True,source='SIMULATED',hardware_connected=False,
                        scheduled_pids=list(smoke_state['ready_receipt']['effective_schedule']),
                        stored_017a_raw_frames=receipt['dpf']['recorded_positive_six_byte_frames'],
                        monitoring_errors=window.capture_monitor_errors,closed_session=True,
                        adapter_remained_open=True,recorded_initialization=True,receipt=receipt)
                    if result['monitoring_errors']: raise RuntimeError('Monitoring errors in synthetic validation')
                    output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
                    smoke_timer.stop(); window.close(); app.exit(0)
            except Exception as exc:
                output.write_text(json.dumps(dict(passed=False,error=str(exc),stage=smoke_state['stage']))+'\n',encoding='utf-8')
                smoke_timer.stop(); window.close(); app.exit(1)
        smoke_timer=QTimer(); smoke_timer.timeout.connect(full_auto_tick); smoke_timer.start(50)
    if args.smoke_test:
        window.source.setCurrentIndex(0); window.scenario.setCurrentText('Normal idle'); window.session_panel.advanced.setChecked(True)
        QTimer.singleShot(100, window.connect_adapter)  # Default source is explicitly simulation.
        QTimer.singleShot(3500, lambda: window.send("record"))
        QTimer.singleShot(6500, lambda: window.send("record_stop"))
        QTimer.singleShot(7200, window.close)
    result=app.exec()
    if session_validation_requested: session_cleanup()
    if args.benchmark_smoke_test or args.sequential_benchmark_smoke_test:benchmark_cleanup()
    if args.maintenance_smoke_test:maintenance_cleanup()
    if args.full_auto_smoke_test:
        # The recurring validation callback retains the window in a closure.
        # Destroy its widgets while QApplication still exists, rather than
        # leaving Qt charts/widgets to Python interpreter finalization.
        smoke_timer.stop(); smoke_timer.timeout.disconnect(full_auto_tick)
    # Qt widgets/charts must be destroyed before QApplication in every GUI mode.
    # Their signal callbacks can otherwise keep Python wrappers alive too long.
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    return result

if __name__ == "__main__":
    raise SystemExit(main())
