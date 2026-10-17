# Stable one-file dispatcher, separate from the GUI runtime and personal data.
a = Analysis(['run_launcher.py'],pathex=[],binaries=[],datas=[],hiddenimports=[],excludes=['PySide6'],noarchive=False,optimize=0)
pyz = PYZ(a.pure)
exe = EXE(pyz,a.scripts,a.binaries,a.datas,[],name='MokkaECULabLauncher',debug=False,strip=False,upx=True,console=False,icon='assets/mokka-ecu-lab.ico')
