"""Explicit constructed GUI benchmark validation; never a default or LIVE action."""
import json,time
from pathlib import Path
from PySide6.QtCore import QTimer
from mokka_ecu_lab.transport.simulator import Simulator
from mokka_ecu_lab.analysis.obd import analyze_obd
from mokka_ecu_lab.logging import list_sessions


def install_benchmark_validation(ui,app,root,*,scale=None,output=None,sequential=False):
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
    rates=[2,3,4] if sequential else [2];run_index=0;runs=[];handles=[];idle_since=None;idle_wire_count=0
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
        nonlocal stage,last,run_index,idle_since,idle_wire_count
        now=time.monotonic();gaps.append(now-last);last=now;ui.drain()
        now=time.monotonic() # Compare against the latest send after UI processing.
        try:
            if now-started>len(rates)*100+20:raise AssertionError('Benchmark GUI deadline')
            if stage=='start':
                assert not ui.recording_id and not ui.worker.transport
                screenshots('benchmark-idle');ui.benchmark_panel.rate.setCurrentText(str(rates[0]));ui.benchmark_panel.start.click();stage='benchmark'
            elif stage=='benchmark':
                state=getattr(ui,'benchmark_state',{})
                if state.get('active') and state.get('requests',0)>=6:
                    screenshots('benchmark-active' if not sequential else f'benchmark-{rates[run_index]}-active');stage='finish'
            elif stage=='finish':
                state=getattr(ui,'benchmark_state',{})
                if not state.get('active') and state.get('bundle_path'):
                    rate=rates[run_index]
                    assert 50*rate<=state['requests']<=60*rate and state['rate']==rate and not state['disconnected'] and ui.worker.transport
                    assert state['state']=='CONNECTED_IDLE' and not ui.worker.polling and not ui.worker.recorder
                    assert state['completed'] and 59.99<=state['measurement_duration_seconds']<=61.5
                    report=analyze_obd([state['bundle_path']]);bench=report['sessions'][0]['benchmark'];perf=bench['performance'][0]
                    assert perf['transmitted_requests']==state['requests'] and perf['wire_send_gap_ms']['minimum']>=1000/rate-1e-6
                    assert bench['preflight_sent_requests']>0 and set(bench['pids'])=={'010B','010C','010D','0110'}
                    assert len(list_sessions(root))==run_index+1
                    handles.append((id(ui.worker.transport),ui.worker.context_id));assert len(set(handles))==1
                    runs.append(dict(session_id=state['session_id'],rate=rate,requests=state['requests'],duration_seconds=state['measurement_duration_seconds'],bundle_path=state['bundle_path'],minimum_wire_gap_ms=perf['wire_send_gap_ms']['minimum'],connected_idle=True))
                    screenshots('benchmark-finished' if not sequential else f'benchmark-{rate}-finished')
                    idle_since=time.monotonic();idle_wire_count=len(wire);stage='idle-proof'
            elif stage=='idle-proof' and now-idle_since>=1:
                    assert len(wire)==idle_wire_count and ui.worker.transport.operation_deadline_ns is None
                    if run_index+1<len(rates):
                        run_index+=1;ui.benchmark_panel.rate.setCurrentText(str(rates[run_index]));ui.benchmark_panel.start.click();stage='benchmark'
                    else:ui.benchmark_panel.disconnect.click();stage='explicit-disconnect'
            elif stage=='explicit-disconnect' and not ui.worker.transport and not ui.adapter_open:
                    timer.stop();first=runs[0]
                    result.update(passed=True,source='SIMULATED',private_input_used=False,hardware_connected=False,requests=first['requests'],fixed_rate=2,
                        duration_seconds=first['duration_seconds'],preflight_separate=True,old_48_send_early_stop_absent=True,bundle_path=first['bundle_path'],runs=runs,
                        minimum_recorded_wire_gap_ms=first['minimum_wire_gap_ms'],all_wire_gaps_at_least_250ms=all(b['ns']-a['ns']>=250000000 for a,b in zip(wire,wire[1:])),
                        automatic_bundle_verified=True,connected_idle_after_success=True,idle_requests=0,one_transport_reused=True,explicit_disconnect_verified=True,disconnected=True,native_geometry=geometry,maximum_gui_tick_gap_seconds=max(gaps))
                    result['requests']=first['requests']
                    assert result['all_wire_gaps_at_least_250ms'];target.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8');ui.close();app.exit(0)
        except Exception as exc:failure.append(str(exc));target.write_text(json.dumps(dict(passed=False,error=failure,stage=stage)),encoding='utf-8');timer.stop();ui.close();app.exit(1)
    timer=QTimer();timer.timeout.connect(tick);timer.start(50)
    def cleanup():
        timer.stop();timer.timeout.disconnect(tick);Simulator._exchange=original
    return timer,cleanup
