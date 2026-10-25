"""Shared desktop app; runtimes are bundled, user dictionaries/models are not."""
from pathlib import Path
import subprocess
import sys
from PyInstaller.utils.hooks import collect_all, copy_metadata

root = Path(SPECPATH)
ranking_dir = root / "build" / "turkish-ranking"
subprocess.run([sys.executable, "-m", "wordcel.scripts.build_turkish_ranking", str(ranking_dir)], check=True)
datas = [(str(root / "src/wordcel/resources"), "wordcel/resources"),
         (str(ranking_dir / "*.json"), "wordcel/resources/turkish"),
         (str(root / "src/wordcel/scripts/deconjugator.json"), "wordcel/scripts"),
         (str(root / "LICENSE"), "licenses/wordcel")]
binaries, hiddenimports = [], ["PyQt6.QtTextToSpeech", "pynput.keyboard._win32", "pynput.mouse._win32"]
for package in ("stanza", "zeyrek", "paddle", "paddleocr", "paddlex", "imagesize", "mss", "meikiocr", "winrt"):
    data, binary, hidden = collect_all(package)
    datas += data
    binaries += binary
    hiddenimports += hidden
# PaddleX checks OCR extras through distribution metadata, including in bundles.
for distribution in ("wordcel", "stanza", "zeyrek", "torch", "paddlepaddle", "paddleocr", "paddlex",
                     "imagesize", "opencv-contrib-python", "pyclipper", "pypdfium2", "python-bidi", "shapely"):
    datas += copy_metadata(distribution, recursive=True)

a = Analysis([str(root / "src/wordcel/scripts/quick_lookup.py")],
             pathex=[str(root / "src")], binaries=binaries, datas=datas,
             hiddenimports=hiddenimports, runtime_hooks=[str(root / "packaging/runtime.py")],
             excludes=["tkinter", "tensorflow", "jax", "IPython", "pytest"], optimize=0)
pyz = PYZ(a.pure)
options = dict(exclude_binaries=True, debug=False, strip=False, upx=False,
               icon=str(root / "src/wordcel/resources/icon.ico"))
exe = EXE(pyz, a.scripts, [], name="wordcel", console=False, **options)
cli = EXE(pyz, a.scripts, [], name="wordcel-cli", console=True, **options)
coll = COLLECT(exe, cli, a.binaries, a.datas, strip=False, upx=False, name="wordcel")
