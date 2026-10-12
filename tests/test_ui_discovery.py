import json
from test_ui_freshness import window, connected, transaction
from mokka_ecu_lab.sensors.diesel import STANDARD_DIESEL
from mokka_ecu_lab.transport.simulator import DIESEL_PAYLOADS


def sample_record(ui, ecu='7E8', error_ecu=None, replay=False):
    sample = dict(ecu=ecu,pid=0x85,fields=STANDARD_DIESEL[0x85].decode(DIESEL_PAYLOADS[0x85]),
                  payload_hex=DIESEL_PAYLOADS[0x85].hex(),source_kind='SIMULATED',
                  timestamp='2026-10-12T12:00:00Z',replay=replay)
    record = dict(context_id='one',timestamp=sample['timestamp'],command='0185',pid='85',
                  status='INVALID' if error_ecu else 'OK',latency_ms=1,parsed=[],decoder=[],error='',
                  discovery_samples=[sample],protocol_errors=[dict(ecu=error_ecu,reason='Truncated ISO-TP')] if error_ecu else [])
    ui.worker.events.put(('transaction',(record,[]))); ui.drain()
    return sample


def test_offline_candidates_and_explicit_ecu_action(window,monkeypatch):
    assert len(window.discovery_data['manufacturer_candidates'])==4
    assert all(not e['live_enabled'] for e in window.discovery_data['manufacturer_candidates'])
    assert not window.discovery_start.isEnabled() and not window.discovery_monitor.isEnabled()
    connected(window)
    window.discovery_ecu.setCurrentIndex(window.discovery_ecu.findData('7E9'))
    assert window.source_key()=='7E9'
    calls=[]
    with monkeypatch.context() as patch:
        patch.setattr(window,'send',lambda action,**kwargs:calls.append((action,kwargs)))
        window.discovery_start.click()
    assert calls==[('discover',{'ecu':'7E9'})]
    assert not window.discovery_monitor.isEnabled()  # Basic samples cannot authorize monitoring.


def test_error_isolation_export_and_replay_evidence(window,monkeypatch,tmp_path):
    connected(window,mode='SIMULATED')
    window.support['7E8'].add(0x85); window.support['7E9'].add(0x85)
    sample_record(window,error_ecu='7E9',replay=True)
    rows={e['ecu']:e for e in window.discovery_data['standard'] if e.get('pid')=='85'}
    assert rows['7E8']['availability']=='AVAILABLE'
    assert rows['7E9']['availability']=='INVALID / UNVERIFIED'
    assert rows['7E8']['sample']['fields'][2]['value']==80
    assert window.dashboard.rowCount()==10 and not window.readings
    row=next(i for i,e in enumerate(window.discovery_rows) if e.get('pid')=='85' and e['ecu']=='7E8')
    window.discovery_table.selectRow(row)
    assert '80.0' in window.discovery_detail.toPlainText()
    assert 'REPLAY' in window.discovery_table.item(row,5).text()
    path=tmp_path/'discovery.json'
    monkeypatch.setattr('mokka_ecu_lab.ui.window.QFileDialog.getSaveFileName',lambda *a:(str(path),'JSON'))
    window.export_discovery()
    report=json.loads(path.read_text(encoding='utf-8'))
    assert report['mode']=='SIMULATED' and all(not e['live_enabled'] for e in report['manufacturer_candidates'])
    assert all(e['vehicle_verification']=='UNVERIFIED' for e in report['standard'])
    connected(window,context='two')
    assert not window.discovery_observations and not window.discovery_prepared


def test_monitoring_changes_shared_nominal_interval_without_dashboard_expansion(window):
    connected(window); transaction(window)
    window.support['7E8'].update({0x78,0x85})
    window.discovery_active=True; window.discovery_target='7E8'
    window.update_measurements()
    rpm_row=list(window.registry).index(12)
    assert '1.00 s nominal' in window.explorer.item(rpm_row,7).text()
    assert 'selected supported: 2/10' in window.coverage.text()
