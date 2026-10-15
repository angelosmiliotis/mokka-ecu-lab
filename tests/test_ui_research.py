from test_ui_freshness import window
from test_research import bundle,transaction
from mokka_ecu_lab.research.evidence import save_analysis
import pytest


def test_research_import_view_and_charts_never_submit_to_worker(window,tmp_path,monkeypatch):
    path=bundle(tmp_path/'synthetic.zip',[transaction(0x7A,bytes(6),1),transaction(0x7A,b'\x00\x01'+bytes(4),10**9),
        transaction(0x88,bytes(13),2*10**9),transaction(0x7A,bytes(6),3*10**9,mode='LIVE CAN')])
    calls=[]
    with monkeypatch.context() as patch:
        patch.setattr(window.worker,'submit',lambda *a,**k:calls.append(a))
        view=window.research_view; view.load_paths([path])
        assert view.group.count()==2 and view.definitions.rowCount()==49
        assert 'HW: UNKNOWN' in view.profile.text()
        for i in range(view.group.count()):
            view.group.setCurrentIndex(i)
            assert view.matrix.rowCount()>=12 and view.chart.series()
        assert calls==[] and window.worker.transport is None
        with pytest.raises(ValueError): save_analysis(view.report,path,[path])


def test_hypothesis_import_does_not_join_live_and_simulation(window,tmp_path,monkeypatch):
    import json
    records=[transaction(0x7A,bytes(6),1),transaction(0x7A,bytes(6),2,mode='LIVE CAN')]
    for r in records: r.update(status='OK',parsed=[dict(ecu='7E8',data_hex='00 00 00 00 00 00')])
    path=tmp_path/'constructed.jsonl';path.write_text('\n'.join(json.dumps(r) for r in records)+'\n')
    with pytest.raises(ValueError,match='Mixed source'): window.recording_payloads(path)


def test_compatibility_displays_separate_snapshot_raw_and_unobserved(window,tmp_path):
    import json
    p=bundle(tmp_path/'synthetic.zip',[transaction(0x85,bytes(10),1,mode='LIVE CAN'),transaction(0x60,bytes(4),2,mode='LIVE CAN')],
        {'pid-support.json':json.dumps([dict(ecu='7E8',pid='85',support='SUPPORTED'),dict(ecu='7E8',pid='8B',support='UNSUPPORTED')]).encode()})
    v=window.research_view; v.load_paths([p])
    index=next(i for i in range(v.matrix.rowCount()) if v.matrix.item(i,0).text()=='0185')
    assert v.matrix.item(index,1).text()=='SUPPORTED' and v.matrix.item(index,2).text()=='UNKNOWN'
    assert v.matrix.item(index,3).text()=='1'
    index=next(i for i in range(v.matrix.rowCount()) if v.matrix.item(i,0).text()=='018B')
    assert v.matrix.item(index,10).text()=='NOT OBSERVED'
    v.matrix.selectRow(index)
    assert 'OEM equivalent' in v.matrix_detail.toPlainText()
    index=next(i for i in range(v.matrix.rowCount()) if v.matrix.item(i,0).text()=='0160')
    assert v.matrix.item(index,7).text()=='Bitmap · chain unavailable'
    assert v.matrix.item(index,7).toolTip()=='BITMAP_VALID_UNANCHORED' and v.matrix.item(index,8).text()=='0'


def test_scr_view_and_private_export_do_not_use_worker(window,tmp_path,monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    p=bundle(tmp_path/'a.zip',[transaction(0x88,bytes.fromhex('00 01 00 00 01 00 03 00 00 00 00 00 00'),1)])
    v=window.research_view; v.load_paths([p]); calls=[]
    assert 'Inactive at recorded time' in v.scr_detail.toPlainText()
    assert 'Historical evidence — not current fault' in v.scr_detail.toPlainText()
    assert not v.detailed_report.isChecked()
    target=tmp_path/'private.html'
    monkeypatch.setattr(QFileDialog,'getSaveFileName',lambda *a,**k:(str(target),'HTML'))
    with monkeypatch.context() as patch:
        patch.setattr(window.worker,'submit',lambda *a,**k:calls.append(a))
        v.save_button.click()
        assert target.exists() and target.with_suffix('.json').exists() and not calls
        patch.setattr(QFileDialog,'getOpenFileName',lambda *a,**k:(str(target.with_suffix('.json')),'JSON'))
        v.import_analysis_button.click()
        assert v.report['analysis_origin']=='SAVED_ANALYSIS_NOT_REVALIDATED' and not calls
