"""Managed-path guards, including Windows junctions. Never follows linked subtrees."""
from pathlib import Path
import os

def linked(path):
    path=Path(path)
    return path.is_symlink() or getattr(path,'is_junction',lambda:False)()

def inside(base,path):
    base=Path(base).absolute();path=Path(path).absolute()
    if not path.is_relative_to(base):raise ValueError('Path must stay inside its managed root')
    for p in [path,*path.parents]:
        if linked(p):raise ValueError('Symbolic links/junctions cannot be managed')
        if p==base:break
    if not path.resolve().is_relative_to(base.resolve()):raise ValueError('Resolved path escapes managed root')
    return path

def regular_files(folder,limit=6000):
    folder=Path(folder)
    if linked(folder):raise ValueError('Linked folder is not a managed tree')
    count=0
    def fail(error):
        raise error
    for base,dirs,files in os.walk(folder,followlinks=False,onerror=fail):
        for name in dirs+files:
            if linked(Path(base)/name):raise ValueError('Managed tree contains a symbolic link/junction')
        for name in files:
            count+=1
            if count>limit:raise ValueError('Managed inventory file limit exceeded')
            yield Path(base)/name
