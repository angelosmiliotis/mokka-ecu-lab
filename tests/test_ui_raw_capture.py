from PySide6.QtCore import Qt
from test_ui_freshness import window,connected
from test_raw_capture import raw_evidence
from mokka_ecu_lab.layouts import layout_evidence
from mokka_ecu_lab.transport.simulator import ALTERNATIVE_PAYLOADS
from mokka_ecu_lab.analysis.trends import recorded_trends
from mokka_ecu_lab.ui.trends import TrendsDialog
from test_trends import row


def prepared(ui):
    connected(ui,mode='SIMULATED')
    ui.support,ui.support_pages,ui.discovery_observations=raw_evidence()
    ui.discovery_prepared=True; ui.discovery_target='7E8'; ui.update_capture()


def test_raw_and_nox_opt_ins_are_unchecked_no_send_and_separate_from_numeric(window,monkeypatch):
    prepared(window); calls=[]
    with monkeypatch.context() as patch:
        patch.setattr(window,'send',lambda action,**options:calls.append((action,options)))
        window.prepare_capture()
        assert calls==[] and window.raw_selected()==[] and 0x83 not in window.capture_selected()
        assert 0x7A not in window.capture_selected()
        window.capture_raw_checks[0x7A].setChecked(True)
        assert calls==[]
        window.start_capture(); assert calls[-1][1]['raw_pids']==[0x7A]
    connected(window,context='new')
    assert not window.raw_selected() and all(not w.isEnabled() for w in window.capture_raw_checks.values())


def test_raw_value_is_always_dash_and_becomes_stale_on_stop(window):
    prepared(window); window.prepare_capture(); window.capture_raw_checks[0x7A].setChecked(True)
    sample=dict(ecu='7E8',pid=0x7A,fields=[],framing_valid=True,raw_only=True,source_kind='SIMULATED',
                monotonic_ns=109*10**9,timestamp='synthetic',payload_hex=ALTERNATIVE_PAYLOADS[0x7A].hex(' '),
                **layout_evidence(0x7A,ALTERNATIVE_PAYLOADS[0x7A]))
    window.discovery_observations['7E8',0x7A]=sample
    window.capture_active=True; window.capture_weights={0x7A:1}; window.capture_ecu='7E8'
    window.update_capture()
    index=next(i for i in range(window.capture_table.rowCount()) if 'DPF pressures' in window.capture_table.item(i,0).text())
    assert window.capture_table.item(index,1).text()=='—'
    assert 'Current raw sample' in window.capture_table.item(index,3).text()
    assert 'RAW ONLY / DECODER UNVERIFIED' in window.capture_table.item(index,3).text()
    window.send('stop'); window.update_capture()
    assert 'Stale raw' in window.capture_table.item(index,3).text()


def test_local_trend_charts_switch_source_without_any_transport_calls(window,monkeypatch):
    calls=[]
    with monkeypatch.context() as patch:
        patch.setattr(window.worker,'submit',lambda *a,**k:calls.append(a))
        dialog=TrendsDialog(recorded_trends([row(),row('rpm',800,unit='rpm'),row(ecu='7E9')]),window)
        assert dialog.charts.count()==2 and dialog.source.count()==2
        dialog.source.setCurrentIndex(1)
        assert dialog.charts.count()==1 and calls==[]
        dialog.close()
