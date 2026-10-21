"""T 型报价数据组装测试."""
from datetime import date

from watcher.models import OptionContract, Quote
from watcher.option_meta import build_tshape_data, select_atm_contracts, underlying_codes


def _c(code, strike, otype, expiry="20260826", name=None):
    return OptionContract(
        option_code=code,
        underlying_code="sh510050",
        option_name=name or f"50ETF{'购' if otype == 'call' else '沽'}8月{int(strike*1000)}",
        exchange="SSE",
        option_type=otype,
        strike=strike,
        expire_date=expiry,
    )


def _contracts():
    return [
        _c("10000001", 2.70, "call"), _c("10000002", 2.70, "put"),
        _c("10000003", 2.75, "call"), _c("10000004", 2.75, "put"),
        # 9月合约（应归入另一到期）
        _c("10000011", 2.70, "call", expiry="20260923"), _c("10000012", 2.70, "put", expiry="20260923"),
        # 2.75 认购的调整合约（带A，同一行权价两个 call）
        _c("10000005", 2.75, "call"),
    ]


def _quote(code, price, change=1.0):
    return {
        "option_code": code, "price": price, "change_pct": change,
        "sell_price": price + 0.0005, "sell_vol": 12, "buy_price": price - 0.0005, "buy_vol": 8,
        "volume": 100, "open_interest": 500, "iv": 0.153, "delta": 0.55,
    }


def test_group_by_expiry_and_strike():
    quotes = {q["option_code"]: q for q in [_quote("10000001", 0.35), _quote("10000004", 0.01, -2.0)]}
    p = build_tshape_data(_contracts(), quotes, "sh510050", "上证50ETF", None, today=date(2026, 7, 22))

    assert [e["date"] for e in p["expiries"]] == ["20260826", "20260923"]
    assert p["expiries"][0]["label"] == "2026-08-26"
    assert p["expiries"][0]["days"] == 35
    assert p["defaultExpiry"] == "20260826"

    rows = p["rows"]["20260826"]
    assert [r["strike"] for r in rows] == [2.70, 2.75]  # 行权价升序
    assert len(rows[0]["calls"]) == 1 and len(rows[0]["puts"]) == 1
    assert len(rows[1]["calls"]) == 2  # 调整合约并入同一行权价

    # 行情按 code 关联
    c270 = rows[0]["calls"][0]
    assert c270["price"] == 0.35
    assert c270["sell_vol"] == 12
    # 无行情的合约只有代码名称
    p270 = rows[0]["puts"][0]
    assert p270["price"] is None if "price" in p270 else True
    assert p270["code"] == "10000002"


def test_underlying_quote_mapping():
    uq = Quote(code="sh510050", name="上证50ETF", price=3.086, open=3.08, high=3.09,
               low=3.07, prev_close=3.079)
    p = build_tshape_data(_contracts(), {}, "sh510050", "上证50ETF", uq, today=date(2026, 7, 22))
    u = p["underlying"]
    assert u["price"] == 3.086
    assert abs(u["change_pct"] - 0.23) < 0.01  # 比率转百分数
    assert abs(u["change"] - 0.007) < 0.0001

    p2 = build_tshape_data(_contracts(), {}, "sh510050", "上证50ETF", None, today=date(2026, 7, 22))
    assert p2["underlying"]["price"] is None


def test_negative_volume_clamped():
    """深市期权行情字段偏移导致的负成交量夹到 0."""
    q = _quote("90000001", 0.05)
    q["volume"] = -12
    q["open_interest"] = -43
    contracts = [
        OptionContract(option_code="90000001", underlying_code="sz159915",
                       option_name="创业板ETF购8月2100", exchange="SZSE",
                       option_type="call", strike=2.1, expire_date="20260826"),
    ]
    p = build_tshape_data(contracts, {"90000001": q}, "sz159915", "创业板ETF", None, today=date(2026, 7, 22))
    side = p["rows"]["20260826"][0]["calls"][0]
    assert side["volume"] == 0
    assert side["oi"] == 0


def test_zero_price_treated_as_none():
    q = _quote("10000001", 0.0)
    p = build_tshape_data(
        [_c("10000001", 2.70, "call")], {"10000001": q},
        "sh510050", "上证50ETF", None, today=date(2026, 7, 22),
    )
    side = p["rows"]["20260826"][0]["calls"][0]
    assert side["price"] is None
    assert side["change_pct"] is None


def test_no_contracts_empty_hint():
    """无合约的标的（588050/159952）给空态提示."""
    p = build_tshape_data([], {}, "sh588050", "科创50ETF工银", None, today=date(2026, 7, 22))
    assert p["expiries"] == []
    assert p["rows"] == {}
    assert p["defaultExpiry"] is None
    assert "暂无期权合约" in p["emptyHint"]
    assert "暂无合约" in p["meta"]


def test_underlying_list_has_11():
    """期权标的清单共 11 个（沪 6 + 深 5），含暂无合约的 2 个."""
    codes = underlying_codes()
    assert len(codes) == 11
    assert "sh588050" in codes
    assert "sz159952" in codes
    assert sum(1 for c in codes if c.startswith("sh")) == 6
    assert sum(1 for c in codes if c.startswith("sz")) == 5


def _mk(code, strike, otype, expiry):
    return OptionContract(option_code=code, underlying_code="sh510050",
                          option_name=code, exchange="SSE", option_type=otype,
                          strike=strike, expire_date=expiry)


def test_select_atm_contracts():
    contracts = []
    for i, s in enumerate([2.6, 2.65, 2.7, 2.75, 2.8, 2.85, 2.9]):
        contracts.append(_mk(f"C{i}", s, "call", "20260826"))
        contracts.append(_mk(f"P{i}", s, "put", "20260826"))
    # 远月合约（第二近到期月应入选）
    contracts.append(_mk("F1", 2.75, "call", "20260923"))
    contracts.append(_mk("F2", 2.75, "put", "20260923"))
    # 第三远月不应入选
    contracts.append(_mk("F3", 2.75, "call", "20261223"))

    # today 显式传入，否则用例会随真实日期推移而失效（20260826 早已过期）
    pool = select_atm_contracts(contracts, underlying_price=2.77, today="20260801")
    strikes = sorted({c.strike for c in pool})
    assert strikes == [2.6, 2.65, 2.7, 2.75, 2.8, 2.85, 2.9]  # ATM=2.75 ±3 档
    # 最近 2 个到期月都包含
    expiries = sorted({c.expire_date for c in pool})
    assert expiries == ["20260826", "20260923"]
    # 7 档 × 认购认沽 (近月) + 1 档 × 认购认沽 (次月，只有 2.75 行权价)
    assert len(pool) == 14 + 2

    # 无合约/无价格 → 空
    assert select_atm_contracts([], 2.77) == []
    assert select_atm_contracts(contracts, 0) == []


def test_select_atm_contracts_skips_expired():
    """已到期的月份不能入选.

    合约表会留着上一个到期月的合约。不过滤的话「最近 2 个到期月」会选中
    已摘牌的月份，而摘牌合约的分时接口返回空 —— 整批请求打空，
    当天期权分时 K 一根都入不了库（真实踩过）。
    """
    contracts = []
    for s in (2.7, 2.75, 2.8):
        contracts.append(_mk(f"OLD{s}", s, "call", "20260826"))   # 已摘牌
        contracts.append(_mk(f"CUR{s}", s, "call", "20260923"))   # 当月
        contracts.append(_mk(f"NXT{s}", s, "call", "20261028"))   # 次月

    pool = select_atm_contracts(contracts, underlying_price=2.75, today="20260903")
    got = sorted({c.expire_date for c in pool})
    assert "20260826" not in got, f"选中了已摘牌的月份：{got}"
    assert got == ["20260923", "20261028"], got

    # 全部已到期 → 空（而不是退回摘牌合约）
    old_only = [c for c in contracts if c.expire_date == "20260826"]
    assert select_atm_contracts(old_only, 2.75, today="20260903") == []
