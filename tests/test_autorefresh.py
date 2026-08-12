"""K 线页自动刷新逻辑测试."""
import pytest
from PySide6.QtCore import QObject
from PySide6.QtCore import Signal as QtSignal

import watcher.gui.main_window as mw_mod
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
        return []

    def refresh_now(self):
        pass

    def fetch_daily_bars(self, code, limit=120):
        return []


@pytest.fixture
def win(qapp, tmp_path, monkeypatch):
    # 测试时间在非轮询时段，patch 掉时段判断聚焦可见性逻辑
    monkeypatch.setattr(mw_mod, "is_polling_hours", lambda *a, **k: True)
    cfg = Config.load()
    store = StateStore(tmp_path / "t.db")
    w = MainWindow(cfg, store, FakeWatcher(), None)
    yield w
    w._chart_timer.stop()
    w.deleteLater()


def test_auto_refresh_only_when_chart_tab_visible(win):
    calls = []
    win.chart_tab.update_chart = lambda p: calls.append(p)
    win._chart_code = "sh510300"

    # 不在 K 线页 → 不刷新
    win.tabs.setCurrentIndex(0)
    win._auto_refresh_chart()
    assert not calls

    # 切到 K 线页 → 刷新一次（_on_tab_changed 也会触发一次，先清零再测定时器路径）
    win.tabs.setCurrentIndex(1)
    calls.clear()
    win._auto_refresh_chart()
    assert len(calls) == 1
    assert calls[0]["period"] == "1分"


def test_auto_refresh_skips_without_chart(win):
    calls = []
    win.chart_tab.update_chart = lambda p: calls.append(p)
    win._chart_code = ""
    win.tabs.setCurrentIndex(1)
    calls.clear()
    win._auto_refresh_chart()
    assert not calls


def test_auto_refresh_skips_outside_polling_hours(win, monkeypatch):
    monkeypatch.setattr(mw_mod, "is_polling_hours", lambda *a, **k: False)
    calls = []
    win.chart_tab.update_chart = lambda p: calls.append(p)
    win._chart_code = "sh510300"
    win.tabs.setCurrentIndex(1)
    calls.clear()
    win._auto_refresh_chart()
    assert not calls


def test_tab_switch_back_refreshes(win):
    calls = []
    win.chart_tab.update_chart = lambda p: calls.append(p)
    win._chart_code = "sh510300"
    win.tabs.setCurrentIndex(0)
    calls.clear()
    win.tabs.setCurrentIndex(1)  # 切回 K 线页应立即补一次刷新
    assert len(calls) == 1


def test_option_chart_stale_seq_ignored(win):
    """期权后台取数：过期序号的结果不渲染（连点两个合约，慢的那个不能覆盖新的）."""
    calls = []
    win.chart_tab.update_chart = lambda p: calls.append(p)
    win._chart_seq = 2
    win._chart_inflight = 2

    # seq=1 的过期结果返回：只释放 inflight，不渲染
    win._on_option_chart_ready(1, {"title": "旧合约", "bars": [1]}, {"price": 1})
    assert win._chart_inflight == 1
    assert not calls

    # seq=2 的最新结果返回：正常渲染并带 quote
    win._on_option_chart_ready(2, {"title": "新合约", "bars": []}, {"price": 1.5})
    assert win._chart_inflight == 0
    assert len(calls) == 1
    assert calls[0]["title"] == "新合约"
    assert calls[0]["quote"] == {"price": 1.5}


def test_option_chart_failure_not_rendered(win):
    """取数异常（payload=None）渲染空态而不是永远"加载中"，并释放 inflight."""
    calls = []
    win.chart_tab.update_chart = lambda p: calls.append(p)
    win._chart_seq = 1
    win._chart_inflight = 1
    win._chart_code = "10011799"
    win._chart_name = "50ETF购7月2700"
    win._chart_period = "1分"
    win._on_option_chart_ready(1, None, None)
    assert win._chart_inflight == 0
    assert len(calls) == 1
    assert calls[0]["bars"] == []  # 空态 payload（页面显示"暂无数据"）


def test_auto_refresh_skips_while_option_fetch_inflight(win):
    """期权取数进行中，定时刷新跳过本轮（防请求堆积）."""
    calls = []
    win.chart_tab.update_chart = lambda p: calls.append(p)
    win._chart_code = "10011799"  # 期权代码
    win._chart_inflight = 1
    win.tabs.setCurrentIndex(1)
    calls.clear()
    win._auto_refresh_chart()
    assert not calls
