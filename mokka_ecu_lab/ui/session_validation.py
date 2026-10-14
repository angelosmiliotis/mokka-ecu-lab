"""Explicit synthetic GUI validation only; never a user acquisition profile."""
import hashlib,json,time
from pathlib import Path
from PySide6.QtCore import QTimer
from mokka_ecu_lab.logging import list_sessions
from mokka_ecu_lab.research.evidence import read_bundle
from mokka_ecu_lab.transport.simulator import Simulator
from mokka_ecu_lab import __version__


def install_session_validation(window,app,root,*,minimum_samples=2,observer=None):
    root=Path(root); output=root/'session-smoke.json'
    if output.exists() or list_sessions(root): raise ValueError('Choose fresh synthetic session validation data')
    window.source.setCurrentIndex(0); window.scenario.setCurrentText('Diesel thirteen sensors')
    window.session_panel.advanced.setChecked(False); window.tabs.setCurrentIndex(7)
    app.setQuitOnLastWindowClosed(False)
    stage='connect'; began=time.monotonic(); last=began; gaps=[]; wire=[]; sid=None; states=[]
    original=Simulator._exchange
    def traced(self,command,stop,timeout):
        wire.append(dict(command=command,monotonic_ns=self.last_wire_ns))
        return original(self,command,stop,timeout)
    Simulator._exchange=traced
    timer=QTimer(); result={}
    def observe(name):
        nonlocal last
        was_active=timer.isActive(); timer.stop()
        if observer: observer(name,window)
        if was_active: timer.start(50)
        last=time.monotonic()  # Exclude deliberate validation screenshots/resizing.
    observe('session-disconnected')
    window.session_panel.connect.click()
    def tick():
        nonlocal stage,last,sid
        now=time.monotonic(); gaps.append(now-last); last=now; window.drain()
        try:
            d=window.session_panel.snapshot; state=d.get('state'); r=d.get('receipt') or {}
            if state and (not states or states[-1]!=state): states.append(state)
            if now-began>80: raise AssertionError('Three-action validation deadline: '+str(d))
            if state=='FAILED': raise AssertionError(d.get('reason')+' '+str(d.get('export_error')))
            if stage=='connect' and state=='CONNECTED':
                assert not window.recording_id and not list_sessions(root) and not window.polling_active
                assert d['source_kind']=='SIMULATED' and d['ecu']=='7E8'
                observe('session-connected'); window.session_panel.start.click(); stage='capture'
            elif stage=='capture':
                if d.get('session_id'):
                    if sid is None: sid=d['session_id']
                    assert sid==d['session_id'] and len(list_sessions(root))==1
                if r.get('dpf',{}).get('state')=='READY' and len(r.get('observed',{}))==13 and all(
                        v.get('positive_samples',0)>=minimum_samples for v in r['observed'].values()):
                    assert len(r['effective_schedule'])==13 and r['confirmed_raw_pids']==['7A']
                    assert r['effective_schedule']['7A']['weight']==4 and r['effective_schedule']['0C']['weight']==3
                    assert all(b['recorded'] for b in r['bitmap_evidence'].values())
                    assert not r['pre_connect_initialization_recorded'] and window.recording_id==sid
                    observe('session-ready')
                    result['capture_receipt']=r; window.session_panel.finish.click(); stage='export'
            elif stage=='export' and state=='EXPORTED':
                assert not d['adapter_open'] and not d['recording_active'] and not window.worker.transport
                assert d['session_id']==sid and d['checksums_verified']
                _,members=read_bundle(d['bundle_path']); saved=json.loads(members['acquisition-receipt.json'])
                assert saved['closed_at'] and saved['dpf_proof_met_before_close']
                session=list_sessions(root); assert len(session)==1 and session[0]['ended']
                journal=root/session[0]['raw_path']; assert hashlib.sha256(journal.read_bytes()).hexdigest()==d['original_journal_sha256']
                tx=[json.loads(l) for l in members['raw-redacted.jsonl'].splitlines() if json.loads(l).get('record_type')=='transaction']
                assert tx[0]['command']=='0100' and not any(t['command']=='ATI' for t in tx)
                assert len(list((root/'bundles').glob('*.zip')))==1
                assert all(b['monotonic_ns']-a['monotonic_ns']>=250000000 for a,b in zip(wire,wire[1:]))
                assert not any(w['command'].startswith('22') for w in wire)
                assert window.capture_monitor_errors==0
                observe('session-exported')
                result.update(passed=True,version=__version__,source='SIMULATED',private_input_used=False,hardware_connected=False,
                    primary_actions=['Connect','Start Session','Finish Session'],session_id=sid,bundle_path=d['bundle_path'],
                    one_session=True,closed_recording=True,adapter_disconnected=True,automatic_bundle_verified=True,
                    scheduled_pids=list(result['capture_receipt']['effective_schedule']),
                    stored_017a_raw_frames=saved['dpf']['recorded_positive_six_byte_frames'],
                    observed_samples={p:s['positive_samples'] for p,s in result['capture_receipt']['observed'].items()},
                    wire_spacing_min_seconds=min((b['monotonic_ns']-a['monotonic_ns'])/1e9 for a,b in zip(wire,wire[1:])),
                    wire_requests=len(wire),pre_connect_initialization_recorded=False,stages=states,
                    monitoring_errors=window.capture_monitor_errors,maximum_gui_tick_gap_seconds=max(gaps),
                    original_journal_unchanged=True,full_acquisition_receipt=True)
                assert max(gaps)<1.5,('UI responsiveness',max(gaps))
                output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
                timer.stop(); window.close(); app.exit(0); stage='done'
        except Exception as exc:
            output.write_text(json.dumps(dict(passed=False,error=str(exc),stage=stage),indent=2),encoding='utf-8')
            timer.stop(); window.close(); app.exit(1)
    timer.timeout.connect(tick); timer.start(50)
    def cleanup():
        timer.stop(); timer.timeout.disconnect(tick); Simulator._exchange=original
    return timer,cleanup
