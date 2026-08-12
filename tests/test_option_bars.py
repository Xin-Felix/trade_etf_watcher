"""期权分时 K 线（东财 trends2）解析测试."""
import pytest

from watcher import option_meta
from watcher.option_meta import fetch_option_minute_bars_em


@pytest.fixture(autouse=True)
def _clear_em_cache():
    """东财结果有 60s 内存缓存，用例间必须隔离."""
    option_meta._EM_CACHE.clear()
    yield
    option_meta._EM_CACHE.clear()


SAMPLE = {
    "rc": 0,
    "data": {
        "code": "10011799",
        "trends": [
            # 时间,最新价,最高,最低,成交量,成交额,均价
            "2026-07-22 09:30,0.3700,0.3710,0.3690,100,37000.0,0.3700",
            "2026-07-22 09:31,0.3715,0.3725,0.3705,80,29680.0,0.3707",
            # 第三根：open=前收0.3715 高于本根最高0.3695，应被夹到 high 内
            "2026-07-22 09:32,0.3690,0.3695,0.3685,60,22140.0,0.3701",
        ],
    },
}


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, payload):
        self._payload = payload

    def get(self, url, params=None):
        return _FakeResp(self._payload)


def _patch_client(monkeypatch, payload):
    monkeypatch.setattr(option_meta, "_get_em_client", lambda: _FakeClient(payload))


def test_em_option_bars_parse(monkeypatch):
    _patch_client(monkeypatch, SAMPLE)
    bars = fetch_option_minute_bars_em("10011799")

    assert len(bars) == 3
    assert all(b.source == "eastmoney_option" for b in bars)
    assert all(len(b.ts) == 14 for b in bars)
    assert bars[0].ts == "20260722093000"

    # 第一根 open=自身 close；后续 open=前一分钟 close
    assert bars[0].open == bars[0].close == 0.3700
    assert bars[1].open == 0.3700
    assert bars[2].open == 0.3715

    # open 被夹进 [low, high]（第三根 open 高于原始 high）
    assert bars[2].high == 0.3715
    assert bars[2].low == 0.3685

    for b in bars:
        assert b.low <= min(b.open, b.close) <= max(b.open, b.close) <= b.high
        assert isinstance(b.volume, int)


def test_em_option_bars_szse_market(monkeypatch):
    """深市期权（90 开头）应使用 market=12."""
    seen = {}

    class _Client:
        def get(self, url, params=None):
            seen.update(params or {})
            return _FakeResp({"data": {"trends": [
                "2026-07-22 09:30,0.0500,0.0510,0.0490,10,500.0,0.0500",
            ]}})

    monkeypatch.setattr(option_meta, "_get_em_client", lambda: _Client())
    bars = fetch_option_minute_bars_em("90007051")
    assert seen.get("secid") == "12.90007051"
    assert len(bars) == 1


def test_em_option_bars_unsupported_code():
    """非 8 位期权代码直接返回空（不发请求）."""
    assert fetch_option_minute_bars_em("510300") == []
    assert fetch_option_minute_bars_em("sh510300") == []


def test_em_option_bars_empty(monkeypatch):
    _patch_client(monkeypatch, {"data": {"trends": []}})
    assert fetch_option_minute_bars_em("10011799") == []


def test_em_option_bars_network_error(monkeypatch):
    """网络异常（东财间歇断连）重试后仍失败 → 返回空."""

    class _BadClient:
        def get(self, url, params=None):
            raise ConnectionError("server disconnected")

    monkeypatch.setattr(option_meta, "_get_em_client", lambda: _BadClient())
    monkeypatch.setattr(option_meta.time, "sleep", lambda s: None)  # 跳过重试等待
    assert fetch_option_minute_bars_em("10011799") == []
