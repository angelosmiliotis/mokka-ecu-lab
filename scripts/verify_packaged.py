"""Validate actual Windows process exit and synthetic GUI capture in a fresh folder."""
import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from mokka_ecu_lab.logging import list_sessions
from mokka_ecu_lab.research.evidence import analyze_bundles

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--exe',type=Path,required=True)
parser.add_argument('--output-dir',type=Path,required=True)
parser.add_argument('--maintenance-reference-zips',type=Path,nargs=2,required=True)
args=parser.parse_args(); exe=args.exe.resolve(); output=args.output_dir.resolve()
if not exe.is_file(): parser.error('Executable not found')
if output.exists(): parser.error('Choose a fresh validation output directory')
output.mkdir(parents=True)
exits=[]
for name,flag,timeout in (('startup-1','--smoke-test',30),('startup-2','--smoke-test',30),
                         ('full-auto','--full-auto-smoke-test',90),('session','--session-smoke-test',190),('expanded','--expanded-session-smoke-test',190),('critical','--critical-session-smoke-test',190),('benchmark','--sequential-benchmark-smoke-test',340),('experimental-engine','--experimental-engine-smoke-test',45),('maintenance','--maintenance-smoke-test',200)):
    command=[str(exe),flag,'--data-dir',str(output/name)]
    if name=='maintenance':command+=['--maintenance-reference-zips',*[str(p.resolve()) for p in args.maintenance_reference_zips]]
    run=subprocess.run(command,capture_output=True,timeout=timeout)
    exits.append(run.returncode)
    assert run.returncode==0,(name,'Actual Windows process exit',run.returncode,run.stderr[:400])
    sessions=list_sessions(output/name)
    assert len(sessions)==(3 if name=='benchmark' else 0 if name in {'maintenance','experimental-engine'} else 1) and all(s['ended'] for s in sessions),(name,'Unclosed recording')
    if name.startswith('startup'): assert sessions[0]['requests']==11 and sessions[0]['errors']==0
receipt=json.loads((output/'full-auto/full-auto-smoke.json').read_text(encoding='utf-8'))
assert receipt['passed'] and receipt['stored_017a_raw_frames']>=2 and receipt['monitoring_errors']==0
assert len(receipt['scheduled_pids'])==21 and receipt['adapter_remained_open']
bundle=output/'full-auto/full-auto-smoke-research.zip'
report=analyze_bundles([bundle]); stored=report['sessions'][0]['acquisition_receipt']
assert stored['closed_at'] and stored['dpf_proof_met_before_close']
assert all(g['source_kind']=='SIMULATED' for s in report['sessions'] for g in s['groups'])
standard=json.loads((output/'session/session-smoke.json').read_text(encoding='utf-8'))
expanded=json.loads((output/'expanded/session-smoke.json').read_text(encoding='utf-8'))
benchmark=json.loads((output/'benchmark/benchmark-smoke.json').read_text(encoding='utf-8'))
critical=json.loads((output/'critical/session-smoke.json').read_text(encoding='utf-8'))
maintenance=json.loads((output/'maintenance/maintenance-smoke.json').read_text(encoding='utf-8'))
experimental=json.loads((output/'experimental-engine/experimental-engine-smoke.json').read_text(encoding='utf-8'))
assert experimental['passed'] and not experimental['physical_live_enabled'] and experimental['engine']['fake_com_writes']==312
assert critical['passed'] and len(critical['scheduled_pids'])==13 and critical['adapter_disconnected'] and critical['automatic_bundle_verified']
assert maintenance['passed'] and maintenance['zero_obd_requests'] and maintenance['actual_old_executable_smoke_exit_codes']==[0,0]
assert [r['rate'] for r in benchmark['runs']]==[2,3,4] and benchmark['one_transport_reused'] and benchmark['idle_requests']==0 and benchmark['explicit_disconnect_verified']
assert benchmark['passed'] and benchmark['requests']>48 and benchmark['fixed_rate']==2 and benchmark['duration_seconds']>=59.99 and benchmark['minimum_recorded_wire_gap_ms']>=500
assert expanded['passed'] and len(expanded['scheduled_pids'])==36 and expanded['stored_017a_raw_frames']>=2
assert expanded['adapter_disconnected'] and expanded['automatic_bundle_verified'] and expanded['monitoring_errors']==0
assert standard['passed'] and standard['primary_actions']==['Connect','Start Session','Finish Session']
assert len(standard['scheduled_pids'])==13 and standard['stored_017a_raw_frames']>=2
assert standard['adapter_disconnected'] and standard['automatic_bundle_verified'] and standard['monitoring_errors']==0
assert all(s['connected_idle_after_finish'] and s['same_transport_retained'] and s['idle_requests']==0 and s['idle_observed_seconds']>=60 and s['explicit_disconnect_verified'] for s in (standard,expanded,critical))
_,members=__import__('mokka_ecu_lab.research.evidence',fromlist=['read_bundle']).read_bundle(standard['bundle_path'])
assert json.loads(members['acquisition-receipt.json'])['dpf_proof_met_before_close']
result=dict(actual_process_exits=exits,stationary_benchmark=benchmark,experimental_fake_com=experimental,critical_scheduled_pids=13,maintenance=maintenance,expanded_scheduled_pids=36,expanded_stored_017a_raw_frames=expanded['stored_017a_raw_frames'],source='SIMULATED',private_input_used=False,
    hardware_connected=False,startup_transactions=11,startup_errors=0,
    automatic_scheduled_pids=21,stored_017a_raw_frames=receipt['stored_017a_raw_frames'],
    monitoring_errors=0,closed_recording=True,worker_receipt_checksums_verified=True,
    standard_primary_actions=standard['primary_actions'],standard_scheduled_pids=13,
    standard_stored_017a_raw_frames=standard['stored_017a_raw_frames'],standard_automatic_bundle_verified=True,
    standard_connected_idle_after_export=True,standard_explicit_disconnect_verified=True,session_idle_observed_seconds=standard['idle_observed_seconds'])
(output/'packaged-validation.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
print(json.dumps(result))
