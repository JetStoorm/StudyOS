# Сборка: python -m PyInstaller --noconfirm --clean StudyOS.spec
from pathlib import Path

root = Path(SPECPATH)
a = Analysis(
    [str(root / 'main.py')],
    pathex=[str(root)],
    binaries=[],
    datas=[(str(root / 'ui'), 'ui')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter'],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name='StudyOS', debug=False, bootloader_ignore_signals=False,
    strip=False, upx=False, console=False,
)
