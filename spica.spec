# -*- mode: python ; coding: utf-8 -*-
import os
from pathlib import Path

ROOT = Path(SPECPATH)

a = Analysis(
    ['server/main.py'],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        # 前端构建产物
        (str(ROOT / 'web' / 'dist'), 'web/dist'),
        # DSH patch 配置
        (str(ROOT / 'run' / 'dsh-patch.yml'), 'run'),
        # 效果层规范（文档）
        (str(ROOT / 'docs'), 'docs'),
    ],
    hiddenimports=[
        'uvicorn.logging',
        'uvicorn.loops.auto',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.lifespan.on',
        'engineio.async_drivers',
        'sherpa_onnx',
        'qwen_tts',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'PIL', 'IPython', 'jupyter'],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='SPICA',
    debug=False,
    strip=False,
    upx=True,
    console=True,  # 需要控制台看日志
    icon=str(ROOT / 'web' / 'public' / 'favicon.svg') if (ROOT / 'web' / 'public' / 'favicon.svg').exists() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    name='SPICA',
)
