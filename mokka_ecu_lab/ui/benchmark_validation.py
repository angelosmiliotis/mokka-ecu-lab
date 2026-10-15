"""Explicit constructed GUI benchmark validation; never a default or LIVE action."""
import json,time
from pathlib import Path
from PySide6.QtCore import QTimer
from mokka_ecu_lab.transport.simulator import Simulator
from mokka_ecu_lab.analysis.obd import analyze_obd
from mokka_ecu_lab.logging import list_sessions


def install_benchmark_validation(ui,app,root,*,scale=None,output=None):
    root=Path(root);target=Path(output) if output else root/'benchmark-smoke.json';out=target.parent
    if target.exists() or list_sessions(root):raise ValueError('Fresh constructed benchmark output required')
    scale=ui.devicePixelRatioF() if scale is None else scale
    ui.source.setCurrentIndex(0);ui.scenario.setCurrentText('Diesel thirteen sensors');ui.session_panel.advanced.setChecked(False);ui.tabs.setCurrentIndex(8);ui.connection_panel.hide()
    app.setQuitOnLastWindowClosed(False)
    original=Simulator._exchange;wire=[]
    def trace(self,command,stop,timeout):
        wire.append(dict(command=command,ns=self.last_wire_ns));return original(self,command,stop,timeout)
    Simulator._exchange=trace
    stage='start';started=time.monotonic();last=started;gaps=[];geometry=[];result={};failure=[]
    def screenshots(name):
        nonlocal last
        timer.stop();ui.statusBar().showMessage('Synthetic stationary benchmark validation · no hardware or private input')
        for width,height in ((1280,720),(1366,768),(1536,864),(1920,1080)):
            ui.resize(round(width/scale),round(height/scale));app.processEvents()
            area=ui.tabs.widget(8);area.verticalScrollBar().setValue(0);app.processEvents()
            assert area.widget().width()<=area.viewport().width()+1
            panel=ui.benchmark_panel
            for widget in (panel.start,panel.stop,panel.timer):assert widget.mapTo(area.viewport(),widget.rect().bottomRight()).y()<area.viewport().height(),('Primary control below viewport',width,height,scale)
            assert ui.sidebar.buttons[8].isVisible()
            assert ui.grab().save(str(out/f'{width}x{height}-{name}.png'))
            geometry.append(dict(state=name,physical=[width,height],scale=scale,horizontal_page_overflow=False))
        last=time.monotonic();timer.start(50)
    def tick():
        nonlocal stage,last
        now=time.monotonic();gaps.append(now-last);last=now;ui.drain()
        now=time.monotonic() # Compare against the latest send after UI processing.
        try:
            if now-started>110:raise AssertionError('Benchmark GUI deadline')
            if stage=='start':
                assert not ui.recording_id and not ui.worker.transport
                screenshots('benchmark-idle');ui.benchmark_panel.start.click();stage='benchmark'
            elif stage=='benchmark':
                state=getattr(ui,'benchmark_state',{})
                if state.get('active') and state.get('requests',0)>=6:
                    screenshots('benchmark-active');stage='finish'
            elif stage=='finish':
                state=getattr(ui,'benchmark_state',{})
                if not state.get('active') and state.get('bundle_path'):
                    assert 105<=state['requests']<=120 and state['rate']==2 and state['disconnected'] and not ui.worker.transport
                    assert state['completed'] and 59.99<=state['measurement_duration_seconds']<=61.5
                    report=analyze_obd([state['bundle_path']]);bench=report['sessions'][0]['benchmark'];perf=bench['performance'][0]
                    assert perf['transmitted_requests']==state['requests'] and perf['wire_send_gap_ms']['minimum']>=500
                    assert bench['preflight_sent_requests']>0 and set(bench['pids'])=={'010B','010C','010D','0110'}
                    assert len(list_sessions(root))==1
                    screenshots('benchmark-finished');timer.stop()
                    result.update(passed=True,source='SIMULATED',private_input_used=False,hardware_connected=False,requests=state['requests'],fixed_rate=2,
                        duration_seconds=state['measurement_duration_seconds'],preflight_separate=True,old_48_send_early_stop_absent=True,bundle_path=state['bundle_path'],
                        minimum_recorded_wire_gap_ms=perf['wire_send_gap_ms']['minimum'],all_wire_gaps_at_least_250ms=all(b['ns']-a['ns']>=250000000 for a,b in zip(wire,wire[1:])),
                        automatic_bundle_verified=True,disconnected=True,native_geometry=geometry,maximum_gui_tick_gap_seconds=max(gaps))
                    assert result['all_wire_gaps_at_least_250ms'];target.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8');ui.close();app.exit(0)
        except Exception as exc:failure.append(str(exc));target.write_text(json.dumps(dict(passed=False,error=failure,stage=stage)),encoding='utf-8');timer.stop();ui.close();app.exit(1)
    timer=QTimer();timer.timeout.connect(tick);timer.start(50)
    def cleanup():
        timer.stop();timer.timeout.disconnect(tick);Simulator._exchange=original
    return timer,cleanup
