"""趋势信号层（signals/trend.py）单元测试.

覆盖：EMA/ADX/ATR 指标口径、周线闸门方向、三层对齐判定、出场规则，
以及最关键的**无未来函数**性质（截断数据后历史状态不得改变）。
"""
from __future__ import annotations

from datetime import date, timedelta

from watcher.models import MinuteBar
from watcher.signals.trend import (
    TrendParams,
    TrendState,
    ema_series,
    rolling_median_ratio,
    trend_states,
    weekly_gate_series,
    wilder_adx,
    wilder_atr,
)


def make_bars(closes: list[float], start: date = date(2023, 1, 2),
              spread: float = 0.01) -> list[MinuteBar]:
    """按收盘价序列合成日 K（跳过周末），high/low 带确定性抖动避免退化对称."""
    bars = []
    d = start
    prev = closes[0]
    for i, c in enumerate(closes):
        while d.weekday() >= 5:
            d += timedelta(days=1)
        jit_h = 1 + 0.001 * ((i * 7) % 3)
        jit_l = 1 + 0.001 * ((i * 13) % 3)
        hi = max(c, prev) * (1 + spread / 2) * jit_h
        lo = min(c, prev) * (1 - spread / 2) / jit_l
        bars.append(MinuteBar(
            code="sh510300", ts=d.strftime("%Y%m%d") + "150000",
            open=prev, high=hi, low=lo, close=c, volume=1000, source="test",
        ))
        prev = c
        d += timedelta(days=1)
    return bars


def trend_closes(n: int, daily_pct: float, start_px: float = 3.0) -> list[float]:
    """线性趋势价格序列（daily_pct 每日涨跌幅，如 0.003 / -0.003）."""
    out, px = [], start_px
    for _ in range(n):
        px *= 1 + daily_pct
        out.append(px)
    return out


def chop_closes(n: int, start_px: float = 3.0) -> list[float]:
    """窄幅震荡（正弦 + 小幅高频抖动），无趋势."""
    import math
    out = []
    for i in range(n):
        out.append(start_px * (1 + 0.012 * math.sin(i / 6.0)
                               + 0.003 * math.sin(i / 1.7)))
    return out


# ---------- 指标原语 ----------


def test_ema_constant_series_is_constant():
    vals = [2.5] * 30
    e = ema_series(vals, 10)
    assert e[8] is None                 # 播种期未就绪
    assert abs(e[9] - 2.5) < 1e-12      # SMA 播种
    assert all(abs(v - 2.5) < 1e-12 for v in e[9:] if v is not None)


def test_ema_seed_equals_sma():
    vals = [float(i) for i in range(1, 21)]
    e = ema_series(vals, 10)
    assert abs(e[9] - sum(vals[:10]) / 10) < 1e-12
    k = 2 / 11
    expect = e[9] * (1 - k) + vals[10] * k
    assert abs(e[10] - expect) < 1e-12


def test_ema_insufficient_data_all_none():
    assert ema_series([1.0, 2.0], 10) == [None, None]


def test_adx_high_in_trend_low_in_chop():
    up = make_bars(trend_closes(120, 0.004))
    adx_up, di_p, di_m = wilder_adx(up, 14)
    assert adx_up[-1] is not None and adx_up[-1] > 40       # 单边趋势 ADX 应很高
    assert (di_p[-1] or 0) > (di_m[-1] or 0)                # 上涨 DI+ 占优

    chop = make_bars(chop_closes(120))
    adx_chop, _, _ = wilder_adx(chop, 14)
    assert adx_chop[-1] is not None and adx_chop[-1] < adx_up[-1]


def test_atr_scales_with_volatility():
    calm = make_bars(trend_closes(60, 0.001), spread=0.002)
    wild = make_bars(trend_closes(60, 0.001), spread=0.05)
    a_calm = wilder_atr(calm, 14)[-1]
    a_wild = wilder_atr(wild, 14)[-1]
    assert a_calm and a_wild and a_wild > a_calm * 5


def test_rolling_median_ratio_needs_full_window():
    vals = [1.0] * 10
    out = rolling_median_ratio(vals, 5)
    assert out[:4] == [None] * 4
    assert all(v == 1.0 for v in out[4:])


# ---------- 周线闸门 ----------


def test_weekly_gate_follows_sustained_trend():
    up = make_bars(trend_closes(160, 0.004))
    gates, _, _ = weekly_gate_series(up, 10, 20)
    assert gates[0] == 0                       # 早期数据不足 → 观望
    assert gates[-1] == 1                      # 持续升势 → 只做多

    down = make_bars(trend_closes(160, -0.004))
    gates_d, _, _ = weekly_gate_series(down, 10, 20)
    assert gates_d[-1] == -1                   # 持续跌势 → 只做空


def test_weekly_gate_needs_20_weeks():
    short = make_bars(trend_closes(60, 0.005))   # ~12 周，不足 20 周
    gates, _, _ = weekly_gate_series(short, 10, 20)
    assert all(g == 0 for g in gates)


# ---------- 三层合成 ----------


def test_trend_states_long_in_strong_uptrend():
    bars = make_bars(trend_closes(400, 0.003))
    states = trend_states(bars)
    tail = [s.direction() for s in states[-60:]]
    assert 1 in tail                           # 强上升趋势后段应出现做多信号
    assert -1 not in tail                      # 且绝不出做空


def test_trend_states_short_in_strong_downtrend():
    bars = make_bars(trend_closes(400, -0.003))
    states = trend_states(bars)
    tail = [s.direction() for s in states[-60:]]
    assert -1 in tail
    assert 1 not in tail


def test_trend_states_flat_in_chop():
    bars = make_bars(chop_closes(400))
    states = trend_states(bars)
    assert all(s.direction() == 0 for s in states[-60:])   # 震荡市后段不开仓


def test_atr_ratio_warmup_blocks_early_signals():
    bars = make_bars(trend_closes(400, 0.003))
    states = trend_states(bars)
    # ATR 250 日中位数窗口未就绪前 atr_ratio=0 → strong=False → 无信号
    assert all(s.atr_ratio == 0.0 for s in states[:260])
    assert all(s.direction() == 0 for s in states[:260])


def test_exit_only_on_opposite_gate():
    long_state = TrendState(gate=-1)
    assert long_state.exit_for(1)              # 多头遇空头闸门 → 出
    assert not TrendState(gate=1).exit_for(1)  # 同向不出
    assert not TrendState(gate=0).exit_for(1)  # 闸门中性不平仓


def test_direction_requires_di_gap_on_trade_side():
    params = TrendParams()
    st = TrendState(gate=1, strong=True, structure=1, di_gap=5.0)
    assert st.direction(params) == 0           # DI+ 领先不够 → 不做多
    st.di_gap = 15.0
    assert st.direction(params) == 1
    st2 = TrendState(gate=-1, strong=True, structure=-1, di_gap=15.0)
    assert st2.direction(params) == 0          # 做空需 DI− 领先（di_gap 为负）
    st2.di_gap = -15.0
    assert st2.direction(params) == -1


def test_no_lookahead_truncation_invariance():
    """截断到第 t+1 天重算，第 t 天的状态必须与全量计算完全一致（无未来函数）."""
    bars = make_bars(trend_closes(320, 0.002))
    full = trend_states(bars)
    for t in (150, 200, 250, 300):
        part = trend_states(bars[:t + 1])
        a, b = full[t], part[t]
        assert a.gate == b.gate
        assert a.strong == b.strong
        assert a.structure == b.structure
        assert abs(a.adx - b.adx) < 1e-9
        assert abs(a.atr_ratio - b.atr_ratio) < 1e-9
