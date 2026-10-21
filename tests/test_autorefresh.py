"""K 线窗口自动刷新逻辑测试.

K 线图不再是页签，改成点标的时弹出的独立窗口，所以"要不要自动刷新"
的判断依据从「页签是否当前」变成「窗口是否可见」。
"""
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


def test_auto_refresh_only_when_chart_window_visible(win):
    calls = []
    win.chart_tab.update_chart = lambda p: calls.append(p)
    win._chart_code = "sh510300"

    # 窗口没开 → 不刷新（省掉无人看时的取数）
    win.chart_window.hide()
    win._auto_refresh_chart()
    assert not calls

    # 窗口打开 → 定时刷新生效
    win.chart_window.show()
    calls.clear()
    win._auto_refresh_chart()
    assert len(calls) == 1
    assert calls[0]["period"] == "1分"


def test_auto_refresh_skips_without_chart(win):
    calls = []
    win.chart_tab.update_chart = lambda p: calls.append(p)
    win._chart_code = ""
    win.chart_window.show()
    calls.clear()
    win._auto_refresh_chart()
    assert not calls


def test_auto_refresh_skips_outside_polling_hours(win, monkeypatch):
    monkeypatch.setattr(mw_mod, "is_polling_hours", lambda *a, **k: False)
    calls = []
    win.chart_tab.update_chart = lambda p: calls.append(p)
    win._chart_code = "sh510300"
    win.chart_window.show()
    calls.clear()
    win._auto_refresh_chart()
    assert not calls


def test_startup_does_not_open_chart_window(win):
    """启动只记住默认标的，不该弹窗也不该取数."""
    assert not win.chart_window.isVisible()
    assert win._chart_code  # 默认标的已记下


def test_load_chart_opens_window_and_refreshes(win):
    """点标的 → 打开 K 线窗口、标题带标的名、并立即取数一次."""
    calls = []
    win.chart_tab.update_chart = lambda p: calls.append(p)
    win.chart_window.hide()
    win._load_chart("sh510300", "沪深300ETF")
    assert win.chart_window.isVisible()
    assert "沪深300ETF" in win.chart_window.windowTitle()
    assert len(calls) == 1


def test_main_window_close_hides_chart_window(win):
    """K 线窗口是顶层窗口，主窗口收起时要一起收，别留个孤儿窗口."""
    win.chart_window.show()
    assert win.chart_window.isVisible()
    win.close()
    assert not win.chart_window.isVisible()


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
    win.chart_window.show()
    calls.clear()
    win._auto_refresh_chart()
    assert not calls


def test_closing_chart_window_returns_focus_to_main(win, monkeypatch):
    """关掉 K 线窗口要把焦点交还主窗口.

    macOS 上关掉活动窗口后主窗口不是活动窗口，点它里面的内容第一下会被
    用来激活窗口、不传给网页视图，表现就是「点了没反应」。
    """
    activated = []
    monkeypatch.setattr(win, "raise_", lambda: activated.append("raise"))
    monkeypatch.setattr(win, "activateWindow", lambda: activated.append("activate"))

    win.show()
    win.chart_window.show()
    win.chart_window.close()

    assert not win.chart_window.isVisible()
    assert activated == ["raise", "activate"]


def test_closing_chart_window_does_not_wake_tray_hidden_main(win, monkeypatch):
    """主窗口已收进托盘时，关 K 线窗口不该把主窗口拽出来."""
    activated = []
    monkeypatch.setattr(win, "raise_", lambda: activated.append("raise"))
    monkeypatch.setattr(win, "activateWindow", lambda: activated.append("activate"))

    win.hide()  # 模拟已最小化到托盘
    win.chart_window.show()
    win.chart_window.close()

    assert not activated


def test_show_chart_window_restores_minimized(win):
    """最小化状态下 show() 不还原，必须走 showNormal，否则就是「点了没反应」."""
    win.chart_window.show()
    win.chart_window.showMinimized()
    assert win.chart_window.isMinimized()

    win._load_chart("sh510300", "沪深300ETF")

    assert not win.chart_window.isMinimized()
    assert win.chart_window.isVisible()


def test_show_chart_window_recenters_when_offscreen(win):
    """窗口落在已不存在的屏幕上（外接屏拔掉）时搬回主屏，否则看不见."""
    from PySide6.QtGui import QGuiApplication

    screen = QGuiApplication.primaryScreen().availableGeometry()
    win.chart_window.show()
    win.chart_window.move(screen.right() + 5000, screen.bottom() + 5000)

    win._show_chart_window("测试")

    geo = win.chart_window.frameGeometry()
    assert any(s.availableGeometry().intersects(geo) for s in QGuiApplication.screens()), (
        f"窗口仍在屏幕外：{geo}"
    )


def test_show_chart_window_keeps_normal_position(win):
    """位置正常时不要乱搬窗口."""
    win.chart_window.show()
    win.chart_window.move(120, 90)
    before = win.chart_window.pos()

    win._show_chart_window("测试")

    assert win.chart_window.pos() == before
