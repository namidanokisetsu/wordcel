"""Standalone capture diagnostic; no models, dictionaries, or application startup."""
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules, copy_metadata

root = Path(SPECPATH).parent
datas = [(str(root / "LICENSE"), "licenses/wordcel")]
for package in ("mss", "Pillow", "winrt-runtime", "winrt-Windows.Graphics.Capture"):
    datas += copy_metadata(package)

a = Analysis([str(root / "src/wordcel/scripts/diagnose_capture.py")],
             pathex=[str(root / "src")], datas=datas,
             hiddenimports=collect_submodules("mss") + collect_submodules("winrt"),
             excludes=["tkinter", "numpy", "torch", "paddle", "stanza", "PyQt6.QtQml"],
             optimize=0)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name="wordcel-capture-check",
          console=False, debug=False, strip=False, upx=False,
          icon=str(root / "src/wordcel/resources/icon.ico"))
