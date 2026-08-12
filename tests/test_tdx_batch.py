"""TDX 批量并发分钟 K 测试（mock pytdx 连接）."""
import sys
import types

from watcher.fetchers.tdx import TdxFetcher


class _FakeApi:
    """模拟 pytdx TdxHq_API：记录连接数，返回固定 bar."""

    connect_calls = []

    def __init__(self):
        self._connected = False

    def connect(self, host, port, time_out=4):
        _FakeApi.connect_calls.append((host, port))
        self._connected = True
        return True

    def get_security_bars(self, category, market, code, start, count):
        assert self._connected
        return [
            {"datetime": "2026-07-22 14:59", "open": 1.0, "high": 1.1, "low": 0.9, "close": 1.05, "vol": 100},
            {"datetime": "2026-07-22 15:00", "open": 1.05, "high": 1.08, "low": 1.0, "close": 1.02, "vol": 200},
        ]

    def disconnect(self):
        self._connected = False


def _make_fetcher():
    """绕过 __init__ 里的真实网络连接."""
    f = TdxFetcher.__new__(TdxFetcher)
    f._candidates = []
    f.timeout = 1
    f._api = None
    f._current_server = ("127.0.0.1", 7709)
    f._probed = []
    f._probe_time = 0.0
    return f


def _patch_pytdx(monkeypatch, api_cls):
    fake_module = types.ModuleType("pytdx.hq")
    fake_module.TdxHq_API = api_cls
    monkeypatch.setitem(sys.modules, "pytdx.hq", fake_module)


def test_batch_fetch_all_codes(monkeypatch):
    _patch_pytdx(monkeypatch, _FakeApi)
    _FakeApi.connect_calls.clear()
    f = _make_fetcher()
    out = f.fetch_minute_bars_batch(["sh510300", "sz159915", "sh510050"], limit=10)

    assert set(out) == {"sh510300", "sz159915", "sh510050"}
    for bars in out.values():
        assert len(bars) == 2
        assert bars[0].open == 1.0
        assert bars[1].close == 1.02
        assert bars[0].source == "tdx"
        assert bars[0].ts == "202607221459"  # TDX 分钟线是 12 位（yyyyMMddHHmm）
    # 每个 code 一条独立连接（pytdx 非线程安全，不能共享）
    assert len(_FakeApi.connect_calls) == 3
    assert all(h == "127.0.0.1" for h, _ in _FakeApi.connect_calls)


def test_batch_fetch_connect_failure_returns_empty(monkeypatch):
    class _DeadApi(_FakeApi):
        def connect(self, host, port, time_out=4):
            return False

    _patch_pytdx(monkeypatch, _DeadApi)
    f = _make_fetcher()
    out = f.fetch_minute_bars_batch(["sh510300", "sz159915"], limit=10)
    assert out == {"sh510300": [], "sz159915": []}


def test_batch_fetch_no_server(monkeypatch):
    f = _make_fetcher()
    f._current_server = None
    f._ensure_api = lambda: False  # 连不上
    out = f.fetch_minute_bars_batch(["sh510300"], limit=10)
    assert out == {"sh510300": []}
