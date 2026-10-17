"""Newly constructed packets verify evidence gates and throughput denominators."""
import base64,hashlib,json,time
from datetime import datetime,timedelta,timezone
from zipfile import ZipFile
import pytest
from mokka_ecu_lab.analysis.obd import analyze_obd,export_obd_report
from mokka_ecu_lab.transport.simulator import can_reply


def constructed_bundle(path,*,vgt=b'\xc0\x19\x20\x21\x22\x23',benchmark=False):
    identifiers={1,12,0x20,0x40,0x60,0x71,0x7A,0x80,0x8C}
    packets=[]
    for base in (0,32,64,96,128):
        mask=sum(1<<(31-(pid-base-1)) for pid in identifiers if base<pid<=base+32)
        packets.append((base,mask.to_bytes(4,'big')))
    packets.extend([(0x0C,b'\x01\xa0'),(0x7A,b'\x91\x42\x63\x84\xa5'),(0x71,vgt)])
    records=[]
    for index,(pid,payload) in enumerate(packets):
        records.append(dict(id=f'constructed-evidence-{index}',record_type='transaction',command=f'01{pid:02X}',pid=f'{pid:02X}',
            timestamp=(datetime(2001,2,3,tzinfo=timezone.utc)+timedelta(seconds=index/2)).isoformat(),
            monotonic_ns=2_000_000_000+index*500_000_000,mode='SIMULATED',source_kind='SIMULATED',context_id='constructed-evidence-context',
            sent=True,latency_ms=11,status='OK',raw_b64=base64.b64encode((can_reply('18DAF112',pid,payload)+'\r>').encode()).decode(),
            benchmark_phase='MEASUREMENT' if benchmark and index>=5 else 'PREFLIGHT',benchmark_run_id='constructed-benchmark',benchmark_requested_rate=2,
            pacing_mode='ADAPTIVE' if not benchmark and pid==0x0C else 'FIXED_POLICY'))
    members={'raw-redacted.jsonl':('\n'.join(json.dumps(r) for r in records)+'\n').encode()}
    if benchmark:members['session-summary.json']=json.dumps(dict(session_id='constructed-benchmark',stationary_benchmark=dict(kind='AUTO_60S_V1',completed=True,measurement_duration_seconds=60,rate=2))).encode()
    members['SHA256SUMS.txt']=''.join(hashlib.sha256(v).hexdigest()+'  '+k+'\n' for k,v in members.items()).encode()
    with ZipFile(path,'w') as z:
        for name,value in members.items():z.writestr(name,value)
    return path


def test_separate_gates_never_promote_advertised_or_wrong_layout(tmp_path):
    bundle=constructed_bundle(tmp_path/'constructed.zip');before=hashlib.sha256(bundle.read_bytes()).digest()
    report=analyze_obd([bundle]);g=report['sessions'][0]['inventory'][0];rows={r['pid']:r for r in g['rows']}
    absent=rows['01']['evidence_progression']
    assert absent['advertised']['state']=='SUPPORTED' and absent['advertised']['evidence']
    assert absent['framed']['samples']==absent['length_verified']['samples']==absent['numeric']['samples']==0
    raw=rows['7A']['evidence_progression']
    assert raw['framed']['samples']==1 and raw['length_verified']['expected_data_bytes']==7
    assert raw['length_verified']['samples']==raw['layout_verified']['samples']==raw['numeric']['samples']==0
    reserved=rows['71']['evidence_progression']
    assert reserved['framed']['samples']==reserved['length_verified']['samples']==1
    assert reserved['layout_verified']['samples']==reserved['numeric']['samples']==0
    numeric=rows['0C']['evidence_progression']
    assert numeric['length_verified']['samples']==numeric['layout_verified']['samples']==numeric['numeric']['samples']==1
    assert numeric['numeric']['evidence'][0]['transaction_id']=='constructed-evidence-5'
    assert numeric['sampling']['pattern']=='SINGLE_ADAPTIVE_POLLING_REPLY'
    assert raw['sampling']['pattern']=='NO_RECORDED_ONGOING_POLLING_PROOF'
    assert raw['sampling']['role_counts']=={'FIXED_PREPARATION':1}
    assert all(r['evidence_progression']['physical']['state']=='UNVERIFIED' for r in rows.values())
    assert hashlib.sha256(bundle.read_bytes()).digest()==before and report['sends_requests'] is False


def test_complete_valid_layout_can_have_no_supported_numeric_fields(tmp_path):
    report=analyze_obd([constructed_bundle(tmp_path/'unsupported-fields.zip',vgt=bytes(6))])
    row=next(r for r in report['sessions'][0]['inventory'][0]['rows'] if r['pid']=='71');e=row['evidence_progression']
    assert e['length_verified']['samples']==e['layout_verified']['samples']==1
    assert e['numeric']['samples']==0 and e['physical']['state']=='UNVERIFIED'


def test_send_span_interval_and_full_window_metrics_stay_distinct(tmp_path):
    bundle=constructed_bundle(tmp_path/'benchmark.zip',benchmark=True);report=analyze_obd([bundle]);session=report['sessions'][0]
    p=session['performance'][0]
    assert p['actual_transmitted_rate_hz']==pytest.approx(8/3.5) and p['interval_rate_hz']==2
    assert p['throughput_definitions']['actual_transmitted_rate_hz'].startswith('COUNT_OVER_SEND_SPAN:')
    assert p['throughput_definitions']['interval_rate_hz'].startswith('INTERVALS_OVER_SEND_SPAN:')
    b=session['benchmark'];measured=b['performance'][0]
    assert b['actual_sustained_rate']==pytest.approx(3/60)
    assert measured['actual_transmitted_rate_hz']==3 and measured['interval_rate_hz']==2
    row=next(r for r in session['inventory'][0]['rows'] if r['pid']=='0C')
    assert row['evidence_progression']['sampling']['role_counts']=={'BENCHMARK_MEASUREMENT':1}
    assert 'preflight excluded' in b['throughput_definitions']['actual_sustained_rate']
    export_obd_report(report,tmp_path/'constructed.html',inputs=[bundle])
    html=(tmp_path/'constructed.html').read_text(encoding='utf-8')
    assert 'Offline PID Explorer' in html and 'COUNT_OVER_SEND_SPAN' in html and 'INTERVALS_OVER_SEND_SPAN' in html
    assert 'sustained N/full measured window' in html and 'Physical calibration remains UNVERIFIED' in html


def test_pid_explorer_is_offline_and_displays_missing_evidence(tmp_path,qt_app,monkeypatch):
    from mokka_ecu_lab.ui.obd import ObdDialog
    dialog=ObdDialog([constructed_bundle(tmp_path/'view.zip')]);deadline=time.monotonic()+5
    while not dialog.future.done() and time.monotonic()<deadline:qt_app.processEvents();time.sleep(.01)
    dialog.poll();assert dialog.report and dialog.tabs.count()==3
    dialog.pid_selector.setCurrentIndex(dialog.pid_selector.findData('01'))
    text=dialog.evidence_view.toPlainText()
    assert 'ADVERTISED: SUPPORTED' in text and 'FRAMED: 0 replies' in text and 'PHYSICAL UNVERIFIED' in text
    dialog.pid_selector.setCurrentIndex(dialog.pid_selector.findData('7A'))
    assert 'LENGTH VERIFIED: 0 replies' in dialog.evidence_view.toPlainText()
    assert 'COUNT_OVER_SEND_SPAN' in dialog.performance_view.toPlainText()
    dialog.close();dialog.deleteLater();qt_app.processEvents()
