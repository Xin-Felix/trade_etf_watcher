"""T 型报价页视觉冒烟：真实数据渲染 + 截图."""
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
OUT = "/tmp/tshape"


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
        return ["sh510050", "sz159915"]

    def refresh_now(self):
        pass

    def fetch_daily_bars(self, code, limit=120):
        return []


def main():
    app = QApplication([])
    cfg = Config.load()

    tmp_db = Path(tempfile.mkdtemp()) / "smoke.db"
    shutil.copy(REAL_DB, tmp_db)  # 用真实库副本（顺带验证列迁移）
    store = StateStore(tmp_db)

    win = MainWindow(cfg, store, FakeWatcher(), None)
    win.resize(1280, 800)
    win.show()
    win.tabs.setCurrentIndex(3)  # 期权T型

    def shot1():
        win._load_option_quotes("sh510050")
        QTimer.singleShot(1200, lambda: grab("shot1", shot2))

    def shot2():
        # 指标分页 → 第2页（成交量/持仓量）
        win.option_table.page().runJavaScript(
            "document.getElementById('pg-right').click();"
        )
        QTimer.singleShot(800, lambda: grab("shot2", shot3))

    def shot3():
        # 指标分页 → 第3页（IV/Delta）
        win.option_table.page().runJavaScript(
            "document.getElementById('pg-right').click();"
        )
        QTimer.singleShot(800, lambda: grab("shot3", quit_app))

    def grab(name, next_fn):
        pix = win.option_table.grab()
        path = f"{OUT}_{name}.png"
        pix.save(path)
        print("saved", path)
        next_fn()

    def quit_app():
        app.quit()

    QTimer.singleShot(800, shot1)
    app.exec()


if __name__ == "__main__":
    sys.exit(main())
