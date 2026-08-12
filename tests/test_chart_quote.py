"""K 线图信息面板报价组装测试."""
import pytest
from PySide6.QtCore import QObject
from PySide6.QtCore import Signal as QtSignal

from watcher.config import Config
from watcher.gui.main_window import MainWindow
from watcher.models import AppState, Quote
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
        return []

    def refresh_now(self):
        pass

    def fetch_daily_bars(self, code, limit=120):
        return []


@pytest.fixture
def win(qapp, tmp_path):
    cfg = Config.load()
    store = StateStore(tmp_path / "t.db")
    # 播种：期权行情（含负成交量脏数据）+ ETF 快照
    store.save_option_quotes([{
        "option_code": "10011256", "underlying_code": "sh510050", "name": "50ETF购9月2700",
        "option_type": "call", "strike": 2.7, "price": 0.3689, "change_pct": 5.76,
        "volume": -4, "open_interest": 1301, "iv": 0.385, "delta": 0.9,
        "buy_price": 0.3682, "buy_vol": 30, "sell_price": 0.3712, "sell_vol": 35,
    }])
    store.save_quote(Quote(code="sh510300", name="沪深300ETF", price=4.779, open=4.774,
                           high=4.795, low=4.765, prev_close=4.765, volume=1236000,
                           ts="20260723104300", source="tdx"), "2026-07-23")
    w = MainWindow(cfg, store, FakeWatcher(), None)
    yield w
    w._chart_timer.stop()
    w.deleteLater()


def test_option_quote_panel(win):
    q = win._chart_quote("10011256")
    assert q["price"] == 0.3689
    assert q["changePct"] == 5.76
    # 昨收由 price/(1+pct) 反推
    assert abs(q["prevClose"] - 0.3689 / 1.0576) < 0.0001
    assert q["change"] == round(q["price"] - q["prevClose"], 4)
    # 负成交量/持仓夹到 >=0
    assert q["volume"] == 0
    extras = dict(q["extras"])
    assert extras["持仓量"] == "1301"
    assert extras["IV"] == "38.5%"
    assert extras["买一"].startswith("0.3682")


def test_etf_quote_panel(win):
    q = win._chart_quote("sh510300")
    assert q["price"] == 4.779
    assert q["open"] == 4.774 and q["high"] == 4.795 and q["low"] == 4.765
    assert q["prevClose"] == 4.765
    assert q["changePct"] == round((4.779 / 4.765 - 1) * 100, 2)
    assert q["volume"] == 1236000


def test_unknown_code_returns_none(win):
    assert win._chart_quote("99999999") is None
    assert win._chart_quote("sz999999") is None
