# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['run_official_pipeline.py'],  # プロジェクトのメイン起動スクリプト
    pathex=[],
    binaries=[],
    datas=[
        ('bin/ffmpeg.exe', 'bin'),
        ('bin/ffprobe.exe', 'bin'),
    ],
    hiddenimports=[
        'backend.services.preflight_validator',
        'backend.agents.memory.technical_debt',
        'backend.services.workspace_sync',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='video_automation_studio',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,  # プレフライト検証の標準出力を確認できるようにコンソールを有効化
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='video_automation_studio',
)
