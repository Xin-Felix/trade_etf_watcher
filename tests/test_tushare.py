"""Tushare 数据源测试（mock 网络）+ 交易日历落地与节假日判断."""
from datetime import datetime

import pytest
import pytz

from watcher import calendar as cal
from watcher.fetchers import tushare_src as ts
from watcher.state import StateStore

TZ = pytz.timezone("Asia/Shanghai")


# ===== 代码格式转换 =====

def test_option_code_conversion():
    assert ts.to_ts_option_code("10012055") == "10012055.SH"
    assert ts.to_ts_option_code("90000123") == "90000123.SZ"
    # 非法输入
    assert ts.to_ts_option_code("") == ""
    assert ts.to_ts_option_code("1001205") == ""      # 位数不对
    assert ts.to_ts_option_code("abcdefgh") == ""
    assert ts.to_ts_option_code("20012055") == ""     # 未知市场前缀


def test_fund_code_conversion():
    assert ts.to_ts_fund_code("sh510300") == "510300.SH"
    assert ts.to_ts_fund_code("sz159915") == "159915.SZ"
    assert ts.to_ts_fund_code("SH510050") == "510050.SH"   # 大写也认
    assert ts.to_ts_fund_code("510300") == ""              # 没前缀不猜


# ===== HTTP 层 mock =====

class _FakeResp:
    def __init__(self, body, status=200):
        self._body = body
        self.status_code = status

    def raise_for_status(self):
        if self.status_code != 200:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._body


def _client_with(monkeypatch, body, capture: dict | None = None):
    c = ts.TushareClient(token="fake-token")

    class _FakeHttp:
        def post(self, url, json=None):
            if capture is not None:
                capture.update(json or {})
            return _FakeResp(body)

    monkeypatch.setattr(c, "_http", lambda: _FakeHttp())
    monkeypatch.setattr(ts, "_MIN_INTERVAL", 0.0)   # 测试不限速
    return c


def test_call_parses_rows_into_dicts(monkeypatch):
    body = {"code": 0, "data": {"fields": ["a", "b"], "items": [[1, 2], [3, 4]]}}
    c = _client_with(monkeypatch, body)
    rows = c.call("whatever", {})
    assert rows == [{"a": 1, "b": 2}, {"a": 3, "b": 4}]
    assert c.last_error == ""


def test_call_error_code_returns_empty(monkeypatch):
    body = {"code": 40203, "msg": "积分不足"}
    c = _client_with(monkeypatch, body)
    assert c.call("opt_daily", {}) == []
    assert "积分不足" in c.last_error


def test_call_network_failure_returns_empty(monkeypatch):
    c = ts.TushareClient(token="fake-token")

    class _Boom:
        def post(self, url, json=None):
            raise RuntimeError("Server disconnected")

    monkeypatch.setattr(c, "_http", lambda: _Boom())
    monkeypatch.setattr(ts, "_MIN_INTERVAL", 0.0)
    assert c.call("opt_daily", {}) == []
    assert "请求失败" in c.last_error


def test_no_token_disabled(monkeypatch):
    c = ts.TushareClient(token="")
    assert c.call("opt_daily", {}) == []
    assert "TUSHARE_TOKEN" in c.last_error


# ===== 期权日 K 解析 =====

_OPT_BODY = {
    "code": 0,
    "data": {
        "fields": ["trade_date", "open", "high", "low", "close", "vol", "oi", "pre_settle"],
        "items": [
            # 故意乱序，验证会排序
            ["20260724", 0.19, 0.2236, 0.1626, 0.1626, 123856.0, 54721.0, 0.2259],
            ["20260722", 0.30, 0.3100, 0.2600, 0.2645, 90000.0, 40000.0, 0.3000],
            ["20260723", 0.2767, 0.2916, 0.2070, 0.2259, 114060.0, 48732.0, 0.2645],
        ],
    },
}


def test_option_daily_parse_and_sort(monkeypatch):
    c = _client_with(monkeypatch, _OPT_BODY)
    bars = c.fetch_option_daily("10012055")
    assert len(bars) == 3
    assert [b.ts for b in bars] == ["20260722150000", "20260723150000", "20260724150000"]
    last = bars[-1]
    assert last.code == "10012055"
    assert last.open == pytest.approx(0.19)
    assert last.close == pytest.approx(0.1626)
    assert last.volume == 123856
    assert last.source == "tushare_option_daily"
    # ts 统一补 15:00:00，方便和其他日K源共存
    assert all(b.ts.endswith("150000") for b in bars)


def test_option_daily_sends_right_params(monkeypatch):
    cap: dict = {}
    c = _client_with(monkeypatch, _OPT_BODY, capture=cap)
    c.fetch_option_daily("10012055", start_date="2026-07-01", end_date="20260724")
    assert cap["api_name"] == "opt_daily"
    assert cap["params"]["ts_code"] == "10012055.SH"
    # 日期里的横线要去掉
    assert cap["params"]["start_date"] == "20260701"
    assert cap["params"]["end_date"] == "20260724"


def test_option_daily_high_low_bounded(monkeypatch):
    """脏数据（high 比 close 小）时要夹住，避免蜡烛跑出影线."""
    body = {
        "code": 0,
        "data": {
            "fields": ["trade_date", "open", "high", "low", "close", "vol"],
            "items": [["20260724", 0.20, 0.15, 0.30, 0.25, 100]],
        },
    }
    c = _client_with(monkeypatch, body)
    b = c.fetch_option_daily("10012055")[0]
    assert b.high >= max(b.open, b.close)
    assert b.low <= min(b.open, b.close)


def test_option_daily_skips_bad_rows(monkeypatch):
    body = {
        "code": 0,
        "data": {
            "fields": ["trade_date", "open", "high", "low", "close", "vol"],
            "items": [
                ["20260724", 0.19, 0.22, 0.16, 0.16, 100],
                ["bad-date", 0.19, 0.22, 0.16, 0.16, 100],   # 日期非法
                ["20260723", 0.19, 0.22, 0.16, 0, 100],      # 收盘价 0
                ["20260722", None, None, None, None, None],  # 全空
            ],
        },
    }
    c = _client_with(monkeypatch, body)
    bars = c.fetch_option_daily("10012055")
    assert len(bars) == 1


def test_option_daily_bad_code_no_request(monkeypatch):
    cap: dict = {}
    c = _client_with(monkeypatch, _OPT_BODY, capture=cap)
    assert c.fetch_option_daily("nope") == []
    assert cap == {}      # 代码非法时不该发请求


def test_option_daily_limit(monkeypatch):
    items = [[f"202607{d:02d}", 0.1, 0.2, 0.05, 0.15, 10] for d in range(1, 21)]
    body = {"code": 0, "data": {"fields":
            ["trade_date", "open", "high", "low", "close", "vol"], "items": items}}
    c = _client_with(monkeypatch, body)
    bars = c.fetch_option_daily("10012055", limit=5)
    assert len(bars) == 5
    assert bars[-1].ts.startswith("20260720")   # 保留最近的


# ===== ETF 日 K =====

def test_fund_daily_parse_volume_unit(monkeypatch):
    """fund_daily 的 vol 单位是手，要 ×100 换成股，和 TDX 口径一致."""
    body = {
        "code": 0,
        "data": {
            "fields": ["trade_date", "open", "high", "low", "close", "vol"],
            "items": [["20260724", 4.75, 4.759, 4.699, 4.701, 10247631.52]],
        },
    }
    c = _client_with(monkeypatch, body)
    b = c.fetch_fund_daily("sh510300")[0]
    assert b.code == "sh510300"
    assert b.close == pytest.approx(4.701)
    assert b.volume == int(10247631.52 * 100)
    assert b.source == "tushare_daily"


# ===== 交易日历 =====

def test_trade_dates_filters_closed_days(monkeypatch):
    body = {
        "code": 0,
        "data": {
            "fields": ["cal_date", "is_open"],
            "items": [
                ["20260731", 1],
                ["20260801", 0],   # 周六
                ["20260802", 0],   # 周日
                ["20260803", 1],
            ],
        },
    }
    c = _client_with(monkeypatch, body)
    assert c.fetch_trade_dates("20260731", "20260803") == ["20260731", "20260803"]


def test_trade_dates_ignores_bad_rows(monkeypatch):
    body = {
        "code": 0,
        "data": {
            "fields": ["cal_date", "is_open"],
            "items": [["20260731", 1], ["oops", 1], ["20260803", None]],
        },
    }
    c = _client_with(monkeypatch, body)
    assert c.fetch_trade_dates("20260701", "20260831") == ["20260731"]


# ===== 日历落地 SQLite + 节假日判断 =====

@pytest.fixture()
def store(tmp_path):
    return StateStore(db_path=tmp_path / "t.db")


def test_save_and_query_trade_dates(store):
    n = store.save_trade_dates(["20260724", "20260727", "bad", "2026072"])
    assert n == 2                                  # 非法的被过滤
    assert store.trade_dates() == ["20260724", "20260727"]
    assert store.has_trade_calendar() is True
    # 幂等：重复写不产生重复行
    store.save_trade_dates(["20260724"])
    assert store.trade_dates() == ["20260724", "20260727"]


def test_is_trade_date_three_states(store):
    store.save_trade_dates(["20260724", "20260727"])
    assert store.is_trade_date("20260724") is True     # 交易日
    assert store.is_trade_date("20260725") is False    # 区间内但不在表里 → 非交易日
    assert store.is_trade_date("20991231") is None     # 超出已知区间 → 不知道
    assert store.is_trade_date("20200101") is None
    assert store.is_trade_date("2026-07-24") is True   # 带横线也认
    assert store.is_trade_date("bad") is None


def test_empty_calendar_returns_unknown(store):
    assert store.has_trade_calendar() is False
    assert store.is_trade_date("20260724") is None


class _CalendarGuard:
    """测试完把 checker 复位，避免污染其他用例."""

    def __enter__(self):
        return self

    def __exit__(self, *a):
        cal.set_trade_day_checker(None)


def test_holiday_not_polling(store):
    """国庆假期：日历说不是交易日 → 不轮询、不做信号."""
    store.save_trade_dates(["20260930", "20261009"])   # 10/1~10/8 放假
    with _CalendarGuard():
        cal.set_trade_day_checker(store.is_trade_date)
        holiday = TZ.localize(datetime(2026, 10, 1, 10, 30))   # 周四但放假
        assert cal.is_trading_day(holiday) is False
        assert cal.is_polling_hours(holiday) is False
        assert cal.is_trading_hours(holiday) is False

        workday = TZ.localize(datetime(2026, 9, 30, 10, 30))
        assert cal.is_trading_day(workday) is True
        assert cal.is_polling_hours(workday) is True
        assert cal.is_trading_hours(workday) is True


def test_weekend_makeup_trading_day(store):
    """调休：周六开市，日历说是交易日就要轮询（光看 weekday 会漏）."""
    store.save_trade_dates(["20260926"])   # 假设周六调休开市
    with _CalendarGuard():
        cal.set_trade_day_checker(store.is_trade_date)
        sat = TZ.localize(datetime(2026, 9, 26, 10, 30))
        assert sat.weekday() == 5
        assert cal.is_trading_day(sat) is True
        assert cal.is_polling_hours(sat) is True


def test_no_calendar_falls_back_to_weekday(store):
    """没有日历数据时退回周末判断，不能把工作日误判成休市."""
    with _CalendarGuard():
        cal.set_trade_day_checker(store.is_trade_date)   # 空日历
        weekday = TZ.localize(datetime(2026, 7, 24, 10, 30))   # 周五
        weekend = TZ.localize(datetime(2026, 7, 25, 10, 30))   # 周六
        assert cal.is_trading_day(weekday) is True
        assert cal.is_polling_hours(weekday) is True
        assert cal.is_trading_day(weekend) is False


def test_checker_exception_does_not_break(store):
    """日历查询抛异常时要退回周末判断，不能让轮询整体挂掉."""
    def boom(_d):
        raise RuntimeError("db locked")

    with _CalendarGuard():
        cal.set_trade_day_checker(boom)
        weekday = TZ.localize(datetime(2026, 7, 24, 10, 30))
        assert cal.is_trading_day(weekday) is True


def test_outside_hours_still_not_polling(store):
    store.save_trade_dates(["20260724"])
    with _CalendarGuard():
        cal.set_trade_day_checker(store.is_trade_date)
        early = TZ.localize(datetime(2026, 7, 24, 8, 30))
        late = TZ.localize(datetime(2026, 7, 24, 16, 0))
        assert cal.is_polling_hours(early) is False
        assert cal.is_polling_hours(late) is False
        assert cal.is_trading_hours(TZ.localize(datetime(2026, 7, 24, 12, 0))) is False  # 午休
        assert cal.is_polling_hours(TZ.localize(datetime(2026, 7, 24, 12, 0))) is True   # 午休照常刷
