"""端到端冒烟：构建主窗口，模拟双击期权合约，捕获图表 payload."""
import json
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


def main():
    app = QApplication([])
    cfg = Config.load()
    store = StateStore(Path(tempfile.mkdtemp()) / "smoke.db")
    win = MainWindow(cfg, store, FakeWatcher(), None)

    captured: dict = {}
    orig = win.chart_tab.update_chart

    def capture(payload):
        captured.clear()
        captured.update(payload)

    win.chart_tab.update_chart = capture

    results = {}

    def step_sse():
        win._on_option_row_clicked("10011799", "50ETF购7月2700")
        results["sse"] = {
            "title": captured.get("title"),
            "mode": captured.get("mode"),
            "n_bars": len(captured.get("bars") or []),
            "first": (captured.get("bars") or [{}])[0],
            "last": (captured.get("bars") or [{}])[-1],
        }

    def step_szse():
        win._on_option_row_clicked("90007051", "深证100ETF购9月3100")
        results["szse"] = {
            "title": captured.get("title"),
            "mode": captured.get("mode"),
            "n_bars": len(captured.get("bars") or []),
        }
        print(json.dumps(results, ensure_ascii=False, indent=2, default=str))
        app.quit()

    QTimer.singleShot(500, step_sse)
    QTimer.singleShot(1200, step_szse)
    app.exec()


if __name__ == "__main__":
    sys.exit(main())
