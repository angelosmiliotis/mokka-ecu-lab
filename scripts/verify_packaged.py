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
args=parser.parse_args(); exe=args.exe.resolve(); output=args.output_dir.resolve()
if not exe.is_file(): parser.error('Executable not found')
if output.exists(): parser.error('Choose a fresh validation output directory')
output.mkdir(parents=True)
exits=[]
for name,flag,timeout in (('startup-1','--smoke-test',30),('startup-2','--smoke-test',30),
                         ('full-auto','--full-auto-smoke-test',90),('session','--session-smoke-test',100)):
    run=subprocess.run([str(exe),flag,'--data-dir',str(output/name)],capture_output=True,timeout=timeout)
    exits.append(run.returncode)
    assert run.returncode==0,(name,'Actual Windows process exit',run.returncode,run.stderr[:400])
    sessions=list_sessions(output/name)
    assert len(sessions)==1 and sessions[0]['ended'],(name,'Unclosed recording')
    if name.startswith('startup'): assert sessions[0]['requests']==11 and sessions[0]['errors']==0
receipt=json.loads((output/'full-auto/full-auto-smoke.json').read_text(encoding='utf-8'))
assert receipt['passed'] and receipt['stored_017a_raw_frames']>=2 and receipt['monitoring_errors']==0
assert len(receipt['scheduled_pids'])==21 and receipt['adapter_remained_open']
bundle=output/'full-auto/full-auto-smoke-research.zip'
report=analyze_bundles([bundle]); stored=report['sessions'][0]['acquisition_receipt']
assert stored['closed_at'] and stored['dpf_proof_met_before_close']
assert all(g['source_kind']=='SIMULATED' for s in report['sessions'] for g in s['groups'])
standard=json.loads((output/'session/session-smoke.json').read_text(encoding='utf-8'))
assert standard['passed'] and standard['primary_actions']==['Connect','Start Session','Finish Session']
assert len(standard['scheduled_pids'])==13 and standard['stored_017a_raw_frames']>=2
assert standard['adapter_disconnected'] and standard['automatic_bundle_verified'] and standard['monitoring_errors']==0
_,members=__import__('mokka_ecu_lab.research.evidence',fromlist=['read_bundle']).read_bundle(standard['bundle_path'])
assert json.loads(members['acquisition-receipt.json'])['dpf_proof_met_before_close']
result=dict(actual_process_exits=exits,source='SIMULATED',private_input_used=False,
    hardware_connected=False,startup_transactions=11,startup_errors=0,
    automatic_scheduled_pids=21,stored_017a_raw_frames=receipt['stored_017a_raw_frames'],
    monitoring_errors=0,closed_recording=True,worker_receipt_checksums_verified=True,
    standard_primary_actions=standard['primary_actions'],standard_scheduled_pids=13,
    standard_stored_017a_raw_frames=standard['stored_017a_raw_frames'],standard_automatic_bundle_verified=True,
    standard_disconnected_after_export=True)
(output/'packaged-validation.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
print(json.dumps(result))
