"""Explicit packaged GUI validation of memory-only COM; no vehicle backend."""
import json,time
from pathlib import Path
from PySide6.QtCore import QTimer
from mokka_ecu_lab.logging import list_sessions


def install_experimental_validation(window,app,root):
    root=Path(root);target=root/'experimental-engine-smoke.json'
    if target.exists() or list_sessions(root):raise ValueError('Fresh synthetic experimental validation required')
    window.source.setCurrentIndex(0);window.tabs.setCurrentIndex(11);window.connection_panel.hide()
    page=window.higher_rate_panel;began=time.monotonic();stage='start';result={}
    app.setQuitOnLastWindowClosed(False)
    timer=QTimer()
    def tick():
        nonlocal stage
        try:
            assert not window.worker.transport and not window.recording_id
            assert not page.live_start.isEnabled()
            if time.monotonic()-began>35:raise AssertionError('Bounded fake COM GUI deadline')
            if stage=='start':page.fake_start.click();stage='engine'
            elif stage=='engine' and page.fake_engine and not page.fake_engine.active:
                s=page.fake_engine.snapshot()
                assert s['state']=='COMPLETED' and s['fake_com_writes']==312 and s['measurement_requests']==300
                assert s['actual_hardware_transmissions']==0 and not s['live_enabled']
                assert s['minimum_preflight_fake_send_gap_ns']>=250000000
                assert s['minimum_measured_fake_send_gap_ns']==200000000
                assert s['fake_send_spacing_violations']==s['fake_response_overlaps']==0
                assert not list_sessions(root)
                result.update(passed=True,source='CONSTRUCTED_FAKE_COM_BYTES',hardware_connected=False,engine=s,
                    separate_legacy_scalar_model=page.model is None,physical_live_enabled=False,normal_worker_transport_open=False)
                window.statusBar().showMessage('CONSTRUCTED FAKE COM / virtual time / zero hardware traffic')
                assert window.grab().save(str(root/'experimental-fake-com-completed.png'))
                page.export_brief(root/'constructed-engineering-brief.json')
                page.fake_start.click();page.advance_fake();page.fake_stop.click()
                assert page.fake_engine.state=='ABORTED' and not page.fake_timer.isActive()
                result['explicit_stop_verified']=True
                target.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
                timer.stop();window.close();app.exit(0);stage='done'
        except Exception as exc:
            target.write_text(json.dumps(dict(passed=False,error=str(exc),stage=stage),indent=2),encoding='utf-8')
            timer.stop();window.close();app.exit(1)
    timer.timeout.connect(tick);timer.start(50)
    def cleanup():timer.stop();timer.timeout.disconnect(tick)
    return timer,cleanup
