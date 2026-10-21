# -*- mode: python ; coding: utf-8 -*-

import sys
from pathlib import Path

block_cipher = None

ROOT = Path(SPECPATH).parent
SRC = ROOT / "watcher"
CONFIG = ROOT / "config.yaml"
ICON = ROOT / "assets" / "icon.icns"

a = Analysis(
    [str(SRC / "main.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        (str(CONFIG), "."),
        # akshare 的 file_fold 数据文件（期权合约加载必须）
        (str(ROOT / ".venv/lib/python3.12/site-packages/akshare/file_fold"), "akshare/file_fold"),
    ],
    hiddenimports=[
        "pytdx.hq",
        "pytdx.exhq",
        "PySide6",
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtWidgets",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebChannel",
        # 网络层（打包后拉数据必须完整）
        "httpx",
        "httpx._transports",
        "httpx._transports.default",
        "httpcore",
        "httpcore._async",
        "httpcore._sync",
        "anyio",
        "anyio._backends",
        "anyio._backends._asyncio",
        "sniffio",
        "h11",
        "certifi",
        "ssl",
        "socksio",
        "pytz",
        # macOS 原生通知（横幅弹出 + 点击跳转），delegate 靠运行时反射，
        # PyInstaller 静态分析扫不到，必须显式声明
        "objc",
        "Foundation",
        "UserNotifications",
        # 信号 / AI / 策略子模块（部分为延迟导入，同样扫不到）
        "watcher.signals.patterns",
        "watcher.signals.intraday_momentum",
        "watcher.ai",
        "watcher.ai.client",
        "watcher.ai.strategy_prompt",
        "watcher.strategy",
        "watcher.strategy.pricing",
        "watcher.strategy.payoff",
        "watcher.strategy.decay",
        "watcher.strategy.presets",
        "watcher.fetchers.tushare_src",
        # akshare 及其依赖（期权合约元数据加载）
        "akshare",
        "pandas",
        "numpy",
        "lxml",
        "lxml.etree",
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
    name="日进斗金",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=str(ROOT / "build" / "entitlements.plist"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="日进斗金",
)

app = BUNDLE(
    coll,
    name="日进斗金.app",
    icon=str(ICON),
    bundle_identifier="com.rjdj.option-watcher",
    info_plist={
        "CFBundleDisplayName": "日进斗金",
        "CFBundleName": "日进斗金",
        "CFBundleShortVersionString": "0.9.0",
        "NSRequiresAquaSystemAppearance": False,
        "NSHighResolutionCapable": True,
        # 网络权限声明（打包后拉数据必须）
        "NSAppTransportSecurity": {
            "NSAllowsArbitraryLoads": True,  # 允许 HTTP（TDX/新浪是 HTTP）
        },
    },
)
