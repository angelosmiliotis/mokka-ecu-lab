from pathlib import Path
import os,subprocess
import pytest
from mokka_ecu_lab.local_paths import inside,regular_files

def test_lexical_traversal_rejected(tmp_path):
    root=tmp_path/'managed';root.mkdir()
    with pytest.raises(ValueError):inside(root,root/'..'/'outside')

def test_linked_tree_rejected_without_visiting_target(tmp_path):
    root=tmp_path/'managed';root.mkdir();outside=tmp_path/'outside';outside.mkdir();(outside/'private.txt').write_text('sentinel')
    link=root/'redirect'
    if os.name=='nt':
        result=subprocess.run(['cmd','/c','mklink','/J',str(link),str(outside)],capture_output=True)
        if result.returncode:pytest.skip('Junction creation unavailable')
    else:link.symlink_to(outside,target_is_directory=True)
    with pytest.raises(ValueError):inside(root,link/'private.txt')
    with pytest.raises(ValueError):list(regular_files(root))
    assert (outside/'private.txt').read_text()=='sentinel'
