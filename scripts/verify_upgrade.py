"""Actual packaged updater/Windows shortcuts in an isolated synthetic workspace.

Uses two already published official reference ZIPs. The candidate helper supplies
the new software; no unpublished candidate is presented as an official release.
Never touches the actual Desktop, Start Menu, owner Versions or private records.
"""
from pathlib import Path
import argparse,json,subprocess,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from mokka_ecu_lab.versions import ManagedVersions,release_info
from mokka_ecu_lab.launcher import CurrentLauncher,inspect_shortcuts
from mokka_ecu_lab.upgrade import ApprovedUpgrade,gui_processes
from mokka_ecu_lab.library import digest,write_json
from mokka_ecu_lab.local_paths import linked

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--helper',type=Path,required=True)
    parser.add_argument('--previous-zip',type=Path,required=True)
    parser.add_argument('--next-zip',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args();helper=args.helper.resolve();root=args.output_dir.absolute()
    if root.exists() or any(linked(p) or (p/'.git').exists() for p in [root,*root.parents]):parser.error('Fresh unlinked output outside Git required')
    if not root.is_relative_to(Path(root.anchor)/'MokkaECULabSynthetic'):parser.error('Use the dedicated drive-root MokkaECULabSynthetic workspace')
    if gui_processes():parser.error('Close Mokka GUI processes before isolated updater validation')
    if not helper.is_file():parser.error('Packaged candidate helper missing')
    refs=[]
    for path in (args.previous_zip.resolve(),args.next_zip.resolve()):
        tag=path.name.removeprefix('MokkaECULab-').removesuffix('-Windows11-x64.zip');info=release_info(tag)
        assert digest(path)==info['sha256'] and path.stat().st_size==info['bytes'];refs.append((path,info))
    root.mkdir(parents=True);original_hashes={str(path):digest(path) for path,_ in refs};results=[]
    data=root/'Συνθετικά προσωπικά δεδομένα';data.mkdir();sentinel=data/'constructed-sentinel.txt';sentinel.write_bytes(b'CONSTRUCTED DATA: preserve throughout approved upgrades');sentinel_sha=digest(sentinel)
    manager=ManagedVersions(root/'Εκδόσεις',data);launcher=CurrentLauncher(manager,root/'Σταθερός Launcher')
    desktop=root/'OneDrive redirected Desktop Ω';programs=root/'Start Menu Ω'
    previous=manager.preview_install(*refs[0]);old=manager.install(previous,previous['approval_token']);activation=manager.preview_activation(old['key']);manager.activate(activation,activation['approval_token'])
    setup=launcher.preview(old['key'],desktop,programs,root/'private staging');launcher.install(setup,setup['approval_token'])
    stable={str(p):digest(p) for p in (launcher.exe,launcher.config,launcher.receipt,desktop/'Mokka ECU Lab.lnk',programs/'Mokka ECU Lab.lnk')}
    updater=ApprovedUpgrade(manager,launcher)
    def run(plan,name):
        path=root/(name+'-approved.json');receipt=root/(name+'-receipt.json');write_json(path,plan)
        result=subprocess.run([str(helper),'--apply-upgrade-plan',str(path),'--approval-token',plan['approval_token'],'--receipt',str(receipt)],capture_output=True,timeout=180)
        assert result.returncode==0,(name,result.returncode,result.stderr[:500],receipt.read_text(encoding='utf-8') if receipt.exists() else 'No receipt')
        payload=json.loads(receipt.read_text(encoding='utf-8'));assert payload['completed'] and payload['activated'] and payload['verified_dispatch'] and not payload['ordinary_gui_launch_verified']
        assert manager.state()==plan['pointer_after'];results.append(dict(stage=name,exit_code=0,current=manager.state(),receipt=str(receipt)))
        return payload
    plan=updater.preview(*refs[1],desktop,programs);run(plan,'install-activate');new_key=plan['selected_key']
    assert manager.state()==dict(current=new_key,previous=old['key'])
    run(updater.preview(*refs[1],desktop,programs),'same-version-repeat')
    run(updater.preview_installed(old['key'],desktop,programs),'explicit-rollback')
    run(updater.preview_installed(new_key,desktop,programs),'return-current')
    assert all(digest(p)==sha for p,sha in stable.items())
    shortcuts=inspect_shortcuts([desktop/'Mokka ECU Lab.lnk',programs/'Mokka ECU Lab.lnk'])
    assert all(Path(row['target']).resolve()==launcher.exe and not row['arguments'] for row in shortcuts)
    fresh=ManagedVersions(root/'Fresh Versions',root/'Fresh private data');fresh_launcher=CurrentLauncher(fresh,root/'Fresh stable launcher');fresh_updater=ApprovedUpgrade(fresh,fresh_launcher)
    fresh_plan=fresh_updater.preview(*refs[1],root/'Fresh Desktop Ω',root/'Fresh Start Menu Ω')
    path=root/'fresh-approved.json';receipt=root/'fresh-receipt.json';write_json(path,fresh_plan)
    result=subprocess.run([str(helper),'--apply-upgrade-plan',str(path),'--approval-token',fresh_plan['approval_token'],'--receipt',str(receipt)],capture_output=True,timeout=180)
    assert result.returncode==0,receipt.read_text(encoding='utf-8') if receipt.exists() else result.stderr
    assert fresh_launcher.verify()['verified'];results.append(dict(stage='fresh-install-activate-shortcuts',exit_code=0,current=fresh.state()))
    assert all(digest(p)==sha for p,sha in original_hashes.items()) and digest(sentinel)==sentinel_sha
    proof=dict(passed=True,all_inputs_synthetic_or_public_releases=True,private_vehicle_data_used=False,actual_owner_desktop_touched=False,real_existing_files_moved_or_deleted=0,
        packaged_update_processes=len(results),processes=results,stable_links_and_dispatcher_byte_unchanged=True,windows_shortcuts_verified=shortcuts,
        current_and_rollback_verified=True,same_version_idempotent=True,fresh_shortcuts_verified=True,personal_sentinel_unchanged=True,official_reference_archives_unchanged=True,
        candidate_helper_sha256=digest(helper),ordinary_desktop_doubleclick_verified=False,ordinary_desktop_note='Owner Desktop acceptance is separate and requires authorization')
    write_json(root/'packaged-upgrade-validation.json',proof)
    print(json.dumps(dict(passed=True,packaged_update_processes=len(results),owner_desktop_touched=False,all_public_or_synthetic=True)))

if __name__=='__main__':main()
