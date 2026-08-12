"""11 个期权标的上主页+期权页 冒烟验证."""
import shutil
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QObject, QTimer
from PySide6.QtCore import Signal as QtSignal
from PySide6.QtWidgets import QApplication

from watcher.config import Config
from watcher.gui.main_window import MainWindow
from watcher.models import AppState, Quote
from watcher.state import StateStore

REAL_DB = Path.home() / "Library/Application Support/ETFWatcher/etf_watcher.db"


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
        return []

    def refresh_now(self):
        pass

    def fetch_daily_bars(self, code, limit=120):
        return []


def main():
    app = QApplication([])
    cfg = Config.load()
    codes = cfg.watch_codes()
    print("watchlist:", len(codes), codes)

    tmp_db = Path(tempfile.mkdtemp()) / "smoke.db"
    shutil.copy(REAL_DB, tmp_db)
    store = StateStore(tmp_db)
    win = MainWindow(cfg, store, FakeWatcher(), None)
    win.resize(1280, 800)
    win.show()

    def step1():
        # 模拟 13 个标的的行情到达 → 行情看板
        quotes = {}
        for i, c in enumerate(codes):
            quotes[c] = Quote(code=c, name=cfg.name_for(c), price=3.0 + i * 0.1,
                              open=3.0, high=3.1, low=2.9, prev_close=2.95, source="tdx")
        win._on_quotes_updated(quotes)
        win.tabs.setCurrentIndex(0)
        QTimer.singleShot(900, lambda: grab(win.quote_tab, "/tmp/board_11.png", step2))

    def step2():
        # 期权页：左侧列表应为 9 项（只保留有合约的标的）
        n = win.option_underlying_list.count()
        print("option underlying list items:", n)
        assert n == 9, f"expected 9, got {n}"
        win.tabs.setCurrentIndex(3)
        QTimer.singleShot(600, lambda: grab(win.options_tab, "/tmp/opt_list_9.png", step3))

    def step3():
        # 无合约标的（sh588050/sz159952）不应出现在期权页列表
        from PySide6.QtCore import Qt
        codes = [win.option_underlying_list.item(i).data(Qt.UserRole)
                 for i in range(win.option_underlying_list.count())]
        print("list codes:", codes)
        assert "sh588050" not in codes and "sz159952" not in codes
        print("无合约标的已排除 ✓")
        app.quit()

    def step4():
        print("stats label:", win.option_stats_label.text())
        app.quit()

    def grab(widget, path, next_fn):
        widget.grab().save(path)
        print("saved", path)
        next_fn()

    QTimer.singleShot(700, step1)
    app.exec()


if __name__ == "__main__":
    sys.exit(main())
