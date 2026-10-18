"""Constructed private receipts; no transport, vehicle identifiers or recordings."""
import json
from pathlib import Path
import pytest
from mokka_ecu_lab.idle_evidence import SilentIdle,read_idle_receipt


def completed(tmp_path):
    original=tmp_path/'synthetic.zip';original.write_bytes(b'synthetic immutable original')
    idle=SilentIdle('SYNTHETIC',original,'SIMULATED',3,10.);idle.request(11.)
    for n in range(1,62):idle.observe(10.+n,3,True,True)
    assert idle.data['state']=='VERIFIED'
    return idle


def test_terminal_snapshot_and_saved_bytes_survive_later_time_loss_and_disconnect(tmp_path):
    idle=completed(tmp_path);before=idle.snapshot();path=Path(idle.save(tmp_path/'ιδιωτικά'));raw=path.read_bytes()
    for now in (72.,500.,float('nan'),1.):idle.observe(now,99,False,False)
    idle.end('Explicit Disconnect')
    assert idle.data=={k:v for k,v in before.items() if k!='receipt_path'}
    assert idle.save(path.parent)==str(path) and path.read_bytes()==raw
    assert read_idle_receipt(path)['verification_elapsed_seconds']==60


def test_interrupted_is_also_immutable(tmp_path):
    p=tmp_path/'source';p.write_bytes(b'synthetic');idle=SilentIdle('SYNTHETIC',p,'SIMULATED',1,0.)
    idle.request(0.);idle.observe(16.,1,True,True);before=idle.snapshot()
    idle.observe(500.,20,False,False);assert idle.snapshot()==before


def test_atomic_publish_failure_leaves_no_partial_and_retry_is_safe(tmp_path,monkeypatch):
    import mokka_ecu_lab.idle_evidence as module
    idle=completed(tmp_path);original_fsync=module.os.fsync
    monkeypatch.setattr(module.os,'fsync',lambda fd:(_ for _ in ()).throw(OSError('constructed write interruption')))
    with pytest.raises(OSError):idle.save(tmp_path/'private')
    assert not list((tmp_path/'private').iterdir()) and idle.receipt is None
    monkeypatch.setattr(module.os,'fsync',original_fsync)
    target=Path(idle.save(tmp_path/'private'));idle.receipt=None
    assert idle.save(tmp_path/'private')==str(target)
    idle.receipt=None;target.write_text('{}',encoding='utf-8')
    with pytest.raises(ValueError,match='no overwrite'):idle.save(target.parent)
    assert target.read_text(encoding='utf-8')=='{}'


def test_receipt_reader_rejects_tampering_and_git(tmp_path):
    idle=completed(tmp_path);path=Path(idle.save(tmp_path/'private'));data=json.loads(path.read_text(encoding='utf-8'))
    data['verification_elapsed_seconds']=900;path.write_text(json.dumps(data),encoding='utf-8')
    with pytest.raises(ValueError,match='Inconsistent'):read_idle_receipt(path)
    (path.parent/'.git').mkdir()
    with pytest.raises(ValueError,match='Git'):read_idle_receipt(path)
