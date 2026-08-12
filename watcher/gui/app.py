"""QApplication 入口."""
from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from watcher.config import Config
from watcher.gui.main_window import MainWindow
from watcher.gui.tray import TrayManager
from watcher.state import StateStore
from watcher.watcher_loop import WatcherLoop


def _system_font() -> str:
    if sys.platform == "darwin":
        return "PingFang SC"
    if sys.platform == "win32":
        return "Microsoft YaHei"
    return "Noto Sans CJK SC"


def run_app() -> int:
    cfg = Config.load()

    app = QApplication(sys.argv)
    app.setApplicationName(cfg.app.name)
    app.setApplicationVersion(cfg.app.version)
    app.setQuitOnLastWindowClosed(False)

    font = QFont(_system_font(), 10)
    app.setFont(font)

    store = StateStore()
    watcher = WatcherLoop(cfg, store)

    tray = TrayManager(cfg, watcher)
    window = MainWindow(cfg, store, watcher, tray)

    tray.main_window = window
    tray.show()

    # Cmd+Q / 托盘退出 / 系统注销都会走这里，确保后台线程先停
    app.aboutToQuit.connect(watcher.stop)

    watcher.start()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(run_app())
