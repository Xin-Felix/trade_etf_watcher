"""期权策略计算测试：BS 定价、希腊字母、组合损益、时间损耗、策略模板."""
from datetime import date

import pytest

from watcher.strategy import (
    CONTRACT_MULTIPLIER,
    Leg,
    breakevens,
    build_preset,
    combo_greeks,
    decay_schedule,
    implied_vol,
    payoff_at_expiry,
    payoff_curve,
    summarize,
    theoretical_value,
)
from watcher.strategy.pricing import bs_price, days_to_expiry, greeks, years_to_expiry

TODAY = date(2026, 7, 24)
EXPIRE = "20260826"          # 33 天后
EXPIRE_DASH = "2026-08-26"   # option_quotes 表的格式


# ===== 定价 =====

def test_bs_call_put_parity():
    """看涨看跌平价：C - P = S - K*e^(-rT)."""
    import math
    s, k, t, v, r = 4.7, 4.7, 0.25, 0.20, 0.015
    c = bs_price(s, k, t, v, "call", r)
    p = bs_price(s, k, t, v, "put", r)
    assert c - p == pytest.approx(s - k * math.exp(-r * t), abs=1e-9)


def test_bs_atm_call_reasonable():
    """平值认购 1 个月、IV 20% 时，价格应在标的的 2%-3% 量级."""
    px = bs_price(4.70, 4.70, 33 / 365, 0.20, "call")
    assert 0.05 < px < 0.16


def test_bs_expired_returns_intrinsic():
    assert bs_price(4.80, 4.70, 0.0, 0.2, "call") == pytest.approx(0.10)
    assert bs_price(4.60, 4.70, 0.0, 0.2, "put") == pytest.approx(0.10)
    assert bs_price(4.60, 4.70, 0.0, 0.2, "call") == pytest.approx(0.0)


def test_bs_deep_otm_near_zero():
    assert bs_price(4.0, 6.0, 33 / 365, 0.20, "call") < 0.001


# ===== 希腊字母 =====

def test_greeks_atm_call_delta_near_half():
    g = greeks(4.70, 4.70, 33 / 365, 0.20, "call")
    assert 0.5 < g["delta"] < 0.60
    assert g["gamma"] > 0
    assert g["theta"] < 0          # 买方每天流失时间价值
    assert g["vega"] > 0


def test_greeks_put_delta_negative():
    g = greeks(4.70, 4.70, 33 / 365, 0.20, "put")
    assert -0.60 < g["delta"] < -0.40


def test_greeks_expired_delta_binary():
    itm = greeks(4.80, 4.70, 0.0, 0.2, "call")
    otm = greeks(4.60, 4.70, 0.0, 0.2, "call")
    assert itm["delta"] == 1.0 and otm["delta"] == 0.0
    assert itm["theta"] == 0.0


def test_implied_vol_roundtrip():
    px = bs_price(4.70, 4.75, 33 / 365, 0.28, "call")
    iv = implied_vol(px, 4.70, 4.75, 33 / 365, "call")
    assert iv == pytest.approx(0.28, abs=1e-3)


def test_implied_vol_invalid_returns_none():
    # 报价低于内在价值
    assert implied_vol(0.01, 5.0, 4.0, 0.1, "call") is None


# ===== 到期日解析 =====

def test_days_to_expiry_both_formats():
    assert days_to_expiry(EXPIRE, TODAY) == 33
    assert days_to_expiry(EXPIRE_DASH, TODAY) == 33
    assert days_to_expiry("20260724", TODAY) == 0
    assert days_to_expiry("20260701", TODAY) == 0   # 已过期夹到 0
    assert days_to_expiry("bad", TODAY) == 0
    assert years_to_expiry(EXPIRE, TODAY) == pytest.approx(33 / 365)


# ===== 单腿损益 =====

def _long_call(strike=4.70, price=0.10, qty=1):
    return Leg("10001", "call", strike, "buy", price, qty, EXPIRE, 0.20, "test购")


def _long_put(strike=4.70, price=0.10, qty=1):
    return Leg("10002", "put", strike, "buy", price, qty, EXPIRE, 0.20, "test沽")


def test_long_call_payoff():
    legs = [_long_call(4.70, 0.10)]
    # 到期 4.70：全损权利金 = -0.10 * 10000
    assert payoff_at_expiry(legs, 4.70) == pytest.approx(-1000.0)
    # 到期 4.90：内在 0.20 - 成本 0.10 = +0.10
    assert payoff_at_expiry(legs, 4.90) == pytest.approx(1000.0)
    # 深度虚值仍是全损（亏损有下限）
    assert payoff_at_expiry(legs, 3.00) == pytest.approx(-1000.0)


def test_long_call_summary_unlimited_profit():
    s = summarize([_long_call(4.70, 0.10)], 4.70)
    assert s.net_cost == pytest.approx(1000.0)      # 净支出
    assert s.max_profit is None                     # 盈利无限
    assert s.max_loss == pytest.approx(-1000.0)     # 亏损=权利金
    assert s.breakevens and s.breakevens[0] == pytest.approx(4.80, abs=0.01)


def test_short_call_summary_unlimited_loss():
    sell = Leg("10001", "call", 4.70, "sell", 0.10, 1, EXPIRE, 0.20)
    s = summarize([sell], 4.70)
    assert s.net_cost == pytest.approx(-1000.0)     # 净收入
    assert s.max_profit == pytest.approx(1000.0)
    assert s.max_loss is None                       # 亏损无限


def test_long_put_breakeven():
    s = summarize([_long_put(4.70, 0.10)], 4.70)
    assert s.max_loss == pytest.approx(-1000.0)
    assert s.breakevens[0] == pytest.approx(4.60, abs=0.01)


def test_qty_scales_pnl():
    one = payoff_at_expiry([_long_call(4.70, 0.10, 1)], 4.90)
    three = payoff_at_expiry([_long_call(4.70, 0.10, 3)], 4.90)
    assert three == pytest.approx(one * 3)


# ===== 组合损益 =====

def test_bull_call_spread_capped_both_sides():
    """买 4.70 认购 0.12 + 卖 4.80 认购 0.07，净支出 0.05."""
    legs = [
        Leg("A", "call", 4.70, "buy", 0.12, 1, EXPIRE, 0.20),
        Leg("B", "call", 4.80, "sell", 0.07, 1, EXPIRE, 0.19),
    ]
    s = summarize(legs, 4.70)
    assert s.net_cost == pytest.approx(500.0)
    # 最大亏损 = 净成本；最大盈利 = 价差宽度 - 净成本 = (0.10-0.05)*10000
    assert s.max_loss == pytest.approx(-500.0)
    assert s.max_profit == pytest.approx(500.0)
    assert s.risk_reward == pytest.approx(1.0)
    assert s.breakevens[0] == pytest.approx(4.75, abs=0.01)


def test_straddle_two_breakevens():
    legs = [_long_call(4.70, 0.10), _long_put(4.70, 0.10)]
    s = summarize(legs, 4.70)
    assert s.net_cost == pytest.approx(2000.0)
    assert s.max_profit is None                      # 两侧都无限
    assert s.max_loss == pytest.approx(-2000.0)
    assert len(s.breakevens) == 2
    lo, hi = s.breakevens
    assert lo == pytest.approx(4.50, abs=0.01)
    assert hi == pytest.approx(4.90, abs=0.01)


def test_butterfly_limited_both():
    legs = [
        Leg("A", "call", 4.60, "buy", 0.20, 1, EXPIRE, 0.21),
        Leg("B", "call", 4.70, "sell", 0.12, 2, EXPIRE, 0.20),
        Leg("C", "call", 4.80, "buy", 0.07, 1, EXPIRE, 0.19),
    ]
    s = summarize(legs, 4.70)
    assert s.max_profit is not None and s.max_loss is not None
    assert s.max_profit > 0
    # 最大盈利出现在中间行权价附近
    assert s.max_profit_at == pytest.approx(4.70, abs=0.05)


def test_payoff_curve_covers_strikes():
    legs = [_long_call(4.70, 0.10)]
    curve = payoff_curve(legs, 4.70)
    xs = [x for x, _ in curve]
    assert len(curve) == 201
    assert min(xs) < 4.70 < max(xs)
    assert xs == sorted(xs)


def test_empty_legs_safe():
    assert payoff_curve([], 4.70) == []
    assert breakevens([], 4.70) == []
    s = summarize([], 4.70)
    assert s.net_cost == 0.0 and s.max_profit == 0.0


# ===== 时间损耗 =====

def test_decay_long_call_loses_value():
    legs = [_long_call(4.70, 0.10)]
    d = decay_schedule(legs, 4.70, horizons=(1, 3, 7), today=TODAY)
    assert d["perDay"] < 0                       # 买方每天亏时间价值
    decays = [it["decay"] for it in d["items"]]
    assert decays[0] > decays[1] > decays[2]     # 持有越久损耗越大（负得越多）
    assert d["entryCost"] == pytest.approx(1000.0)


def test_decay_seller_gains_from_time():
    sell = Leg("A", "call", 4.70, "sell", 0.10, 1, EXPIRE, 0.20)
    d = decay_schedule([sell], 4.70, today=TODAY)
    assert d["perDay"] > 0                       # 卖方赚时间价值


def test_theoretical_value_vol_shift():
    legs = [_long_call(4.70, 0.10)]
    base = theoretical_value(legs, 4.70, 0, today=TODAY)
    up = theoretical_value(legs, 4.70, 0, vol_shift=0.05, today=TODAY)
    assert up > base                             # 买方受益于 IV 上升


def test_combo_greeks_aggregate():
    legs = [_long_call(4.70, 0.10), _long_put(4.70, 0.10)]
    g = combo_greeks(legs, 4.70, today=TODAY)
    # 跨式 delta 接近中性，gamma/vega 为正，theta 为负
    assert abs(g["delta"]) < 0.2 * CONTRACT_MULTIPLIER
    assert g["gamma"] > 0
    assert g["vega"] > 0
    assert g["theta"] < 0


def test_combo_greeks_delta_unit_is_yuan():
    """delta 已乘合约单位：标的涨 1 元的盈亏（元）."""
    legs = [_long_call(4.70, 0.10)]
    g = combo_greeks(legs, 4.70, today=TODAY)
    assert 0.4 * CONTRACT_MULTIPLIER < g["delta"] < 0.7 * CONTRACT_MULTIPLIER


# ===== 策略模板 =====

def _chain(spot=4.70):
    """构造一条测试合约链：5 档行权价 × 认购认沽."""
    out = []
    for i, k in enumerate([4.50, 4.60, 4.70, 4.80, 4.90]):
        out.append({
            "code": f"C{i}", "name": f"购{k}", "option_type": "call", "strike": k,
            "price": round(max(0.02, spot - k + 0.10), 4), "iv": 0.20, "expire_date": EXPIRE,
        })
        out.append({
            "code": f"P{i}", "name": f"沽{k}", "option_type": "put", "strike": k,
            "price": round(max(0.02, k - spot + 0.10), 4), "iv": 0.20, "expire_date": EXPIRE,
        })
    return out


def test_preset_long_call_picks_atm():
    legs = build_preset("long_call", _chain(), 4.70)
    assert len(legs) == 1
    assert legs[0].option_type == "call"
    assert legs[0].side == "buy"
    assert legs[0].strike == pytest.approx(4.70)


def test_preset_bull_call_spread_two_legs():
    legs = build_preset("bull_call_spread", _chain(), 4.70)
    assert len(legs) == 2
    buy, sell = legs
    assert buy.side == "buy" and sell.side == "sell"
    assert sell.strike > buy.strike          # 卖出更高行权价
    assert all(l.option_type == "call" for l in legs)


def test_preset_bear_put_spread():
    legs = build_preset("bear_put_spread", _chain(), 4.70)
    assert len(legs) == 2
    buy, sell = legs
    assert sell.strike < buy.strike          # 卖出更低行权价
    assert all(l.option_type == "put" for l in legs)


def test_preset_straddle_same_strike():
    legs = build_preset("long_straddle", _chain(), 4.70)
    assert len(legs) == 2
    assert legs[0].strike == pytest.approx(legs[1].strike)
    assert {l.option_type for l in legs} == {"call", "put"}


def test_preset_strangle_different_strikes():
    legs = build_preset("long_strangle", _chain(), 4.70)
    assert len(legs) == 2
    call = next(l for l in legs if l.option_type == "call")
    put = next(l for l in legs if l.option_type == "put")
    assert call.strike > put.strike          # 认购在上、认沽在下


def test_preset_butterfly_three_legs_ratio():
    legs = build_preset("call_butterfly", _chain(), 4.70)
    assert len(legs) == 3
    mid = next(l for l in legs if l.side == "sell")
    assert mid.qty == 2                      # 中间腿双倍


def test_preset_unknown_and_empty():
    assert build_preset("not_exist", _chain(), 4.70) == []
    assert build_preset("long_call", [], 4.70) == []
    assert build_preset("long_call", _chain(), 0) == []


def test_preset_insufficient_chain_returns_empty():
    """只有 1 档行权价时，价差类挑不出第二条腿."""
    tiny = [{
        "code": "C0", "name": "购", "option_type": "call", "strike": 4.70,
        "price": 0.10, "iv": 0.20, "expire_date": EXPIRE,
    }]
    assert build_preset("bull_call_spread", tiny, 4.70) == []
    assert len(build_preset("long_call", tiny, 4.70)) == 1


def _chain_two_expiries(spot=4.70):
    """近月 + 远月两个到期月混在一条链里（真实 DB 就是这样）."""
    out = []
    for exp, prem in [("20260826", 0.10), ("20261223", 0.30)]:
        for i, k in enumerate([4.50, 4.60, 4.70, 4.80, 4.90]):
            out.append({
                "code": f"C{exp}{i}", "name": f"购{exp}{k}", "option_type": "call", "strike": k,
                "price": round(max(0.02, spot - k + prem), 4), "iv": 0.20, "expire_date": exp,
            })
            out.append({
                "code": f"P{exp}{i}", "name": f"沽{exp}{k}", "option_type": "put", "strike": k,
                "price": round(max(0.02, k - spot + prem), 4), "iv": 0.20, "expire_date": exp,
            })
    return out


def test_preset_never_mixes_expiries():
    """回归：曾把牛市价差挑成「买8月+卖12月」，跨月到期损益无意义."""
    chain = _chain_two_expiries()
    for name in ("bull_call_spread", "bear_put_spread", "long_straddle",
                 "long_strangle", "call_butterfly"):
        legs = build_preset(name, chain, 4.70)
        assert legs, f"{name} 应能挑出腿"
        assert len({l.expire_date for l in legs}) == 1, f"{name} 跨了到期月"


def test_preset_defaults_to_nearest_expiry():
    legs = build_preset("bull_call_spread", _chain_two_expiries(), 4.70)
    assert all(l.expire_date == "20260826" for l in legs)


def test_preset_respects_requested_expiry():
    legs = build_preset("bull_call_spread", _chain_two_expiries(), 4.70, expiry="20261223")
    assert all(l.expire_date == "20261223" for l in legs)
    # 传入不存在的到期月 → 退回最近月，而不是挑不出腿
    legs2 = build_preset("bull_call_spread", _chain_two_expiries(), 4.70, expiry="20991231")
    assert legs2 and all(l.expire_date == "20260826" for l in legs2)


def test_preset_dedupes_same_strike_prefers_volume():
    """同行权价有普通合约和 A 调整合约时，选成交量大的那个."""
    chain = [
        {"code": "C_thin", "name": "购薄", "option_type": "call", "strike": 4.70,
         "price": 0.10, "iv": 0.20, "expire_date": EXPIRE, "volume": 5},
        {"code": "C_main", "name": "购主力", "option_type": "call", "strike": 4.70,
         "price": 0.10, "iv": 0.20, "expire_date": EXPIRE, "volume": 9999},
    ]
    legs = build_preset("long_call", chain, 4.70)
    assert legs[0].option_code == "C_main"


def test_preset_expiry_dash_format_matches():
    """option_quotes 表用 '2026-08-26'，合约表用 '20260826'，两种都要能对上."""
    chain = _chain()
    for c in chain:
        c["expire_date"] = EXPIRE_DASH
    legs = build_preset("bull_call_spread", chain, 4.70, expiry=EXPIRE)
    assert len(legs) == 2


def test_bull_spread_from_preset_has_capped_risk():
    """端到端：预设挑出的价差，最大盈亏都应有限（跨月 bug 时这里会挂）."""
    legs = build_preset("bull_call_spread", _chain_two_expiries(), 4.70)
    s = summarize(legs, 4.70)
    assert s.max_profit is not None and s.max_loss is not None
    assert s.max_profit > 0 > s.max_loss


def test_butterfly_from_preset_profit_positive():
    legs = build_preset("call_butterfly", _chain_two_expiries(), 4.70)
    s = summarize(legs, 4.70)
    assert s.max_profit is not None and s.max_profit > 0


def test_preset_uses_mid_price_when_no_last():
    chain = [{
        "code": "C0", "name": "购", "option_type": "call", "strike": 4.70,
        "price": 0, "buy_price": 0.10, "sell_price": 0.12,
        "iv": 0.20, "expire_date": EXPIRE,
    }]
    legs = build_preset("long_call", chain, 4.70)
    assert legs[0].price == pytest.approx(0.11)
