# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files

datas = [('mokka_ecu_lab/sensors/standard.json', 'mokka_ecu_lab/sensors')]
datas += collect_data_files('mokka_ecu_lab')


a = Analysis(
    ['run_app.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

# Qt 6.12 on Windows uses the unversioned ICU API supplied by Windows 11.
# A foreign Poppler ICU can be found earlier in build-time PATH and exports
# version-suffixed symbols instead. Never bundle that incompatible ICU.
# The target is Windows 11, whose System32 ICU supplies these dependencies.
a.binaries = [entry for entry in a.binaries
              if entry[0].replace('\\', '/').split('/')[-1].lower()
              not in {'icuuc.dll', 'icuin.dll', 'icudt78.dll'}]

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='MokkaECULab',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='MokkaECULab',
)
