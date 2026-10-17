"""Memory-only serial engine and visible hardware lock; constructed bytes only."""
import json
from mokka_ecu_lab.ui.higher_rate import HigherRatePanel


def test_fake_com_engine_has_distinct_ui_complete_ledger_and_export(qt_app,tmp_path):
    page=HigherRatePanel()
    try:
        assert page.fake_engine is None and not page.live_start.isEnabled()
        page.fake_start.click();assert page.fake_engine.active and not page.start.isEnabled()
        for _ in range(320):
            page.advance_fake()
            if not page.fake_engine.active:break
        result=page.fake_engine.snapshot()
        assert result['state']=='COMPLETED' and result['fake_com_writes']==312
        assert result['actual_hardware_transmissions']==0 and not page.fake_timer.isActive()
        destination=tmp_path/'constructed-engine-proof.json';page.export_brief(destination)
        proof=json.loads(destination.read_text(encoding='utf-8'))
        assert proof['experimental_implementation']['implemented']=='SERIALIZED_FAKE_COM_BYTE_ENGINE'
        assert proof['fake_com_validation']['measurement_requests']==300
        assert 'FAKE' in page.fake_status.text() and not page.live_start.isEnabled()
    finally:page.close()


def test_invalid_fault_selection_is_explicit_and_stop_cannot_resume(qt_app):
    page=HigherRatePanel()
    try:
        page.fake_fault.setCurrentText('UNSUPPORTED_BITMAP');page.fake_fault_at.setValue(20)
        page.fake_start.click()
        assert page.fake_engine is None and 'BLOCKED' in page.fake_status.text()
        page.fake_fault.setCurrentText('NONE');page.fake_start.click();page.advance_fake();page.fake_stop.click()
        result=page.fake_engine.snapshot();assert result['state']=='ABORTED'
        page.advance_fake();assert page.fake_engine.snapshot()==result
        assert not page.fake_timer.isActive() and not page.live_start.isEnabled()
    finally:page.close()
