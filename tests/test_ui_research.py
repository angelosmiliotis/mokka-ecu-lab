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
        assert view.group.count()==2 and view.definitions.rowCount()==26
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
