# -*- mode: python ; coding: utf-8 -*-

import tomllib
import subprocess
import sys
from pathlib import Path

from PyInstaller.config import CONF
from PyInstaller.utils.hooks import collect_all, copy_metadata


def _get_build_version() -> str:
    with (Path(CONF['specpath']) / 'pyproject.toml').open('rb') as manifest:
        return tomllib.load(manifest)['project']['version']


BUILD_VERSION = _get_build_version()
sys.path.insert(0, str(Path(CONF['specpath']) / 'packaging'))
from optional_runtimes import prepare, strip
runtime_manifest, external_files = prepare(Path(CONF['specpath']))
ranking_dir = Path(CONF['specpath']) / 'build' / 'turkish-ranking'
subprocess.run([sys.executable, '-m', 'wordcel.scripts.build_turkish_ranking', str(ranking_dir)], check=True)
model_data, model_binaries, model_imports = collect_all('stanza')
model_data += copy_metadata('stanza', recursive=True)
model_data += copy_metadata('wordcel')
data, binaries, imports = collect_all('zeyrek')
model_data += data + copy_metadata('zeyrek', recursive=True)
model_binaries += binaries
model_imports += imports

a = Analysis(
    ['src/wordcel/scripts/quick_lookup.py'],
    pathex=['src'],
    binaries=model_binaries,
    datas=model_data + [
        (str(runtime_manifest), 'wordcel/resources'),
        (str(ranking_dir / '*.json'), 'wordcel/resources/turkish'),
        ('src/wordcel/resources/icon.ico', 'wordcel/resources'),
        ('src/wordcel/scripts/deconjugator.json', 'wordcel/scripts'),
        ('src/wordcel/resources/licenses/*.txt', 'wordcel/resources/licenses'),
    ],
    hiddenimports=model_imports + ['PyQt6.QtTextToSpeech', 'Vision', 'Foundation', 'Quartz', 'AppKit', 'pynput.keyboard._darwin', 'pynput.mouse._darwin'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['packaging/runtime.py'],
    excludes=['paddleocr', 'paddlex', 'paddle', 'meikiocr', 'onnxruntime', 'tkinter', 'IPython', 'pytest'],
    noarchive=False,
    optimize=0,
)
strip(a, external_files)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='wordcel',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
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
    upx=False,
    upx_exclude=[],
    name='wordcel',
)

app = BUNDLE(
    coll,
    name='wordcel.app',
    icon='src/wordcel/resources/icon.ico',
    bundle_identifier='io.github.namidanokisetsu.wordcel',
    version=BUILD_VERSION,
    info_plist={
        'CFBundleVersion': BUILD_VERSION,
        'CFBundleDisplayName': 'Wordcel',
        'NSHighResolutionCapable': True,
        'NSScreenCaptureUsageDescription': 'Recognize text under the pointer for dictionary lookup.',
        'NSAppleEventsUsageDescription': 'Look up text selected in another app when you use its shortcut.',
    },
)
