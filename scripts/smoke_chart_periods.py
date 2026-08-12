"""K 线页周期切换视觉冒烟：真实数据渲染 + 截图."""
import shutil
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QObject, QTimer
from PySide6.QtCore import Signal as QtSignal
from PySide6.QtWidgets import QApplication

from watcher.config import Config
from watcher.gui.main_window import MainWindow
from watcher.models import AppState
from watcher.state import StateStore

REAL_DB = Path.home() / "Library/Application Support/ETFWatcher/etf_watcher.db"
OUT = "/tmp/chart"


class FakeWatcher(QObject):
    class _S(QObject):
        quotes_updated = QtSignal(dict)
        signals_fired = QtSignal(list)
        option_quotes_updated = QtSignal(str)
        state_changed = QtSignal(AppState)

    def __init__(self):
        super().__init__()
        self.signals = self._S()

    def option_underlyings(self):
        return ["sh510050"]

    def refresh_now(self):
        pass

    def fetch_daily_bars(self, code, limit=120):
        return []  # 冒烟不走 TDX 网络


def main():
    app = QApplication([])
    cfg = Config.load()
    tmp_db = Path(tempfile.mkdtemp()) / "smoke.db"
    shutil.copy(REAL_DB, tmp_db)
    store = StateStore(tmp_db)

    win = MainWindow(cfg, store, FakeWatcher(), None)
    win.resize(1280, 800)
    win.show()
    win.tabs.setCurrentIndex(1)  # K 线图

    shots = [
        # (文件名, 前置动作)
        ("etf_5min", lambda: (win._load_chart("sh510300", "沪深300ETF"), win._on_chart_period("5分"))),
        ("etf_60min", lambda: win._on_chart_period("60分")),
        ("opt_daily", lambda: (win._on_option_row_clicked("10011799", "50ETF购7月2700"), win._on_chart_period("日K"))),
        ("opt_intraday", lambda: win._on_chart_period("分时")),
        ("opt_5min", lambda: win._on_chart_period("5分")),
    ]

    def run_next(i):
        if i >= len(shots):
            app.quit()
            return
        name, act = shots[i]
        act()
        QTimer.singleShot(1800, lambda: grab(name, lambda: run_next(i + 1)))

    def grab(name, next_fn):
        path = f"{OUT}_{name}.png"
        win.chart_tab.grab().save(path)
        print("saved", path, "| title:", win.chart_tab.property("title") or "")
        next_fn()

    QTimer.singleShot(800, lambda: run_next(0))
    app.exec()


if __name__ == "__main__":
    sys.exit(main())
