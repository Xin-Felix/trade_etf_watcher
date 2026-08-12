# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

block_cipher = None

ROOT = Path(SPECPATH).parent
SRC = ROOT / "watcher"
CONFIG = ROOT / "config.yaml"
VENV_SITE = ROOT / ".venv" / "Lib" / "site-packages"
AKSHARE_DIR = VENV_SITE / "akshare"

a = Analysis(
    [str(SRC / "main.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        (str(CONFIG), "."),
        (str(AKSHARE_DIR / "file_fold"), "akshare/file_fold"),
    ],
    hiddenimports=[
        "pytdx.hq",
        "pytdx.exhq",
        "akshare",
        "PySide6",
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtWidgets",
        "PySide6.QtCharts",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebChannel",
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
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="ETFWatcher.exe",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
