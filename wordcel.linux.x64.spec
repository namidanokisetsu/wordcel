# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['src/wordcel/main.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        ('src/wordcel/resources', 'wordcel/resources'),
        ('src/wordcel/scripts/deconjugator.json', 'wordcel/scripts'),
    ],
    hiddenimports=['PyQt6.QtTextToSpeech'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='wordcel',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)