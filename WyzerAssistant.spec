# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['local_ai_assistant\\gui\\wyzer_chat_gui.py'],
    pathex=['.'],
    binaries=[],
    datas=[('local_ai_assistant\\data', 'data'), ('local_ai_assistant\\models', 'models'), ('local_ai_assistant\\tools', 'tools'), ('config.py', '.')],
    hiddenimports=['config'],
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
    [],
    exclude_binaries=True,
    name='WyzerAssistant',
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
    name='WyzerAssistant',
)
