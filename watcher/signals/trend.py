"""ETF 期权趋势策略 · 信号层（§11.6 Step 0，回测与实盘共用）.

来源：《ETF期权趋势策略映射文档》第三节（crypto RegimeBigTFLev5 → A 股日线映射）。
三个时间尺度中的两层：周线定方向、日线出信号。EMA/ADX/ATR 全部手算，无外部依赖。

规则（参数均为先验估值，过线后才接实盘，见 PROJECT.md §11.6）：

    第1层 方向闸门（周线，日线重采样）
        close > 周EMA20 且 周EMA10 抬头 → 只做多（买认购）
        close < 周EMA20 且 周EMA10 走低 → 只做空（买认沽）
        其余 → 观望
    第2层 趋势强度（日线）
        ADX(14) > adx_min(30) 且 方向 DI 差值 > di_gap_min(10)
        且 ATR 比率 > atr_ratio_min(0.8)（ATR(14)/close ÷ 其 250 日滚动中位数）
    第3层 结构确认（日线）
        多: close > EMA50 且 EMA10 > EMA20；空: 反之
    出场: 周线明确反向（多头遇空头闸门 / 空头遇多头闸门；闸门中性不平仓）

无未来函数约定：每日状态只用截至当日收盘的数据；周线把当日收盘当作
「未完成本周」的最新收盘参与周 EMA —— 与实盘盘中/收盘评估口径完全一致。
"""
from __future__ import annotations

from dataclasses import dataclass
from statistics import median

from watcher.models import MinuteBar


@dataclass(frozen=True, slots=True)
class TrendParams:
    """三层规则参数（先验值，回测可调；接实盘时进 config.yaml）."""
    # 第1层 周线闸门
    weekly_ema_fast: int = 10
    weekly_ema_slow: int = 20
    # 第2层 日线强度
    adx_period: int = 14
    adx_min: float = 30.0
    di_gap_min: float = 10.0
    atr_period: int = 14
    atr_median_window: int = 250     # ATR 比率的滚动中位数窗口（交易日）
    atr_ratio_min: float = 0.8
    # 第3层 日线结构
    ema_fast: int = 10
    ema_mid: int = 20
    ema_slow: int = 50


DEFAULT_PARAMS = TrendParams()


@dataclass(slots=True)
class TrendState:
    """某一天的信号层状态（仅用截至当日收盘的数据计算）."""
    gate: int = 0                # 第1层方向闸门: +1 只多 / -1 只空 / 0 观望
    strong: bool = False         # 第2层趋势强度是否达标（方向无关部分见 adx/atr_ratio）
    structure: int = 0           # 第3层结构: +1 多 / -1 空 / 0 无
    adx: float = 0.0
    di_gap: float = 0.0          # 带符号 DI 差值（DI+ − DI−），强度判定按方向取用
    atr_ratio: float = 0.0       # 0 = 历史不足（<250 日中位数窗口）无法计算
    weekly_ema_fast: float = 0.0
    weekly_ema_slow: float = 0.0

    def direction(self, params: TrendParams = DEFAULT_PARAMS) -> int:
        """三层全对齐的交易方向: +1 做多 / -1 做空 / 0 不开仓."""
        if self.gate == 0 or self.structure == 0 or self.gate != self.structure:
            return 0
        if not self.strong:
            return 0
        # DI 差值按方向要求：做多要 DI+ 显著在上，做空要 DI− 显著在上
        if self.gate * self.di_gap <= params.di_gap_min:
            return 0
        return self.gate

    def exit_for(self, pos_direction: int) -> bool:
        """周线明确反向 → 持仓出场（闸门中性不平仓）."""
        return self.gate != 0 and self.gate == -pos_direction


# ---------- 指标原语（全部因果序列：返回与输入等长，前缀为 None 表示未就绪） ----------


def ema_series(values: list[float], period: int) -> list[float | None]:
    """EMA，首值用前 period 个 SMA 播种（TA-Lib 口径），前 period-1 个为 None."""
    out: list[float | None] = [None] * len(values)
    if period <= 0 or len(values) < period:
        return out
    k = 2.0 / (period + 1)
    e = sum(values[:period]) / period
    out[period - 1] = e
    for i in range(period, len(values)):
        e = values[i] * k + e * (1 - k)
        out[i] = e
    return out


def wilder_adx(bars: list[MinuteBar], period: int
               ) -> tuple[list[float | None], list[float | None], list[float | None]]:
    """Wilder ADX/DI。返回 (adx, di_plus, di_minus)，未就绪位置为 None."""
    n = len(bars)
    adx: list[float | None] = [None] * n
    di_p: list[float | None] = [None] * n
    di_m: list[float | None] = [None] * n
    if n < period * 2:
        return adx, di_p, di_m

    tr = [0.0] * n
    pdm = [0.0] * n
    ndm = [0.0] * n
    for i in range(1, n):
        h, l, pc = bars[i].high, bars[i].low, bars[i - 1].close
        tr[i] = max(h - l, abs(h - pc), abs(l - pc))
        up, down = bars[i].high - bars[i - 1].high, bars[i - 1].low - bars[i].low
        pdm[i] = up if up > down and up > 0 else 0.0
        ndm[i] = down if down > up and down > 0 else 0.0

    # Wilder 平滑和（seed = 前 period 个之和，之后递推 s -= s/period; s += x）
    def smooth(xs: list[float]) -> list[float | None]:
        out: list[float | None] = [None] * n
        s = sum(xs[1:period + 1])
        out[period] = s
        for i in range(period + 1, n):
            s = s - s / period + xs[i]
            out[i] = s
        return out

    tr_s, pdm_s, ndm_s = smooth(tr), smooth(pdm), smooth(ndm)
    dx: list[float | None] = [None] * n
    for i in range(period, n):
        ts = tr_s[i]
        if not ts:
            continue
        p = 100.0 * (pdm_s[i] or 0.0) / ts
        m = 100.0 * (ndm_s[i] or 0.0) / ts
        di_p[i], di_m[i] = p, m
        if p + m > 0:
            dx[i] = 100.0 * abs(p - m) / (p + m)

    first = 2 * period - 1                      # ADX 播种点：前 period 个 DX 的均值
    seed = [d for d in dx[period:first + 1] if d is not None]
    if len(seed) < period:
        return adx, di_p, di_m
    a = sum(dx[period:first + 1]) / period      # type: ignore[arg-type]
    adx[first] = a
    for i in range(first + 1, n):
        if dx[i] is None:
            continue
        a = (a * (period - 1) + dx[i]) / period  # type: ignore[operator]
        adx[i] = a
    return adx, di_p, di_m


def wilder_atr(bars: list[MinuteBar], period: int) -> list[float | None]:
    """Wilder ATR（首值 = 前 period 个 TR 的均值）."""
    n = len(bars)
    out: list[float | None] = [None] * n
    if n < period + 1:
        return out
    tr = [0.0] * n
    for i in range(1, n):
        h, l, pc = bars[i].high, bars[i].low, bars[i - 1].close
        tr[i] = max(h - l, abs(h - pc), abs(l - pc))
    a = sum(tr[1:period + 1]) / period
    out[period] = a
    for i in range(period + 1, n):
        a = (a * (period - 1) + tr[i]) / period
        out[i] = a
    return out


def rolling_median_ratio(values: list[float | None], window: int) -> list[float | None]:
    """values[i] ÷ 其过去 window 个（含当前）的中位数；窗口不齐为 None."""
    out: list[float | None] = [None] * len(values)
    for i in range(len(values)):
        lo = max(0, i - window + 1)
        seg = [v for v in values[lo:i + 1] if v is not None]
        if len(seg) < window:
            continue
        med = median(seg)
        if med > 0 and values[i] is not None:
            out[i] = values[i] / med           # type: ignore[operator]
    return out


# ---------- 三层信号 ----------


def _iso_week_key(ts: str) -> tuple[int, int]:
    """ts(YYYYMMDD...) → (ISO 年, ISO 周)，用于日线 → 周线重采样."""
    from datetime import date
    d = date(int(ts[:4]), int(ts[4:6]), int(ts[6:8]))
    y, w, _wd = d.isocalendar()
    return y, w


def weekly_gate_series(bars: list[MinuteBar], fast: int, slow: int
                       ) -> tuple[list[int], list[float], list[float]]:
    """逐日计算周线闸门（当日收盘视为未完成本周的最新收盘）.

    返回与 bars 等长的 (gate, 周EMA_fast, 周EMA_slow)；数据不足时 gate=0、EMA=0。
    每周重建周收盘序列重算 EMA：O(日数×周数)，3 年数据约 10 万次运算，足够快且
    逻辑直白（比增量更新更不易错）。
    """
    n = len(bars)
    gates = [0] * n
    f_out, s_out = [0.0] * n, [0.0] * n
    if n < slow * 5:                     # 至少 slow 周（每周约 5 个交易日）才可能有值
        return gates, f_out, s_out

    week_keys = [_iso_week_key(b.ts) for b in bars]
    # 每个已完成周的收盘（不含当前所在周）
    completed: list[float] = []
    i = 0
    while i < n:
        j = i
        while j + 1 < n and week_keys[j + 1] == week_keys[i]:
            j += 1
        # 本周覆盖 bars[i..j]；逐日评估（周内的每一天都把当天收盘当本周收盘）
        for t in range(i, j + 1):
            series = completed + [bars[t].close]
            ef = ema_series(series, fast)
            es = ema_series(series, slow)
            cur_f, cur_s = ef[-1], es[-1]
            prev_f = ef[-2] if len(ef) >= 2 else None
            if cur_f is not None and cur_s is not None and prev_f is not None:
                f_out[t], s_out[t] = cur_f, cur_s
                rising = cur_f > prev_f
                falling = cur_f < prev_f
                c = bars[t].close
                if c > cur_s and rising:
                    gates[t] = 1
                elif c < cur_s and falling:
                    gates[t] = -1
        completed.append(bars[j].close)
        i = j + 1
    return gates, f_out, s_out


def trend_states(bars: list[MinuteBar], params: TrendParams = DEFAULT_PARAMS
                 ) -> list[TrendState]:
    """对整段日 K 逐日计算三层状态（因果、无未来函数）.

    bars 需按时间升序。实盘盘中评估时把当日未完成 bar 追加在末尾即可，
    与回测共用同一份实现（§11.6 要求）。
    """
    n = len(bars)
    closes = [b.close for b in bars]
    gates, w_fast, w_slow = weekly_gate_series(
        bars, params.weekly_ema_fast, params.weekly_ema_slow)
    adx, di_p, di_m = wilder_adx(bars, params.adx_period)
    atr = wilder_atr(bars, params.atr_period)
    atr_pct: list[float | None] = [
        (atr[i] / closes[i]) if atr[i] and closes[i] > 0 else None for i in range(n)
    ]
    atr_ratio = rolling_median_ratio(atr_pct, params.atr_median_window)
    e_fast = ema_series(closes, params.ema_fast)
    e_mid = ema_series(closes, params.ema_mid)
    e_slow = ema_series(closes, params.ema_slow)

    out: list[TrendState] = []
    for i in range(n):
        st = TrendState(gate=gates[i])
        st.weekly_ema_fast = w_fast[i]
        st.weekly_ema_slow = w_slow[i]
        if adx[i] is not None:
            st.adx = adx[i] or 0.0
            st.di_gap = (di_p[i] or 0.0) - (di_m[i] or 0.0)
        if atr_ratio[i] is not None:
            st.atr_ratio = atr_ratio[i] or 0.0
        # 第2层：ADX 与 ATR 比率达标（DI 差值按方向在 direction() 里判定）
        st.strong = (st.adx > params.adx_min
                     and st.atr_ratio > params.atr_ratio_min)
        # 第3层：结构确认
        if e_slow[i] is not None and e_fast[i] is not None and e_mid[i] is not None:
            c = closes[i]
            if c > (e_slow[i] or 0.0) and (e_fast[i] or 0.0) > (e_mid[i] or 0.0):
                st.structure = 1
            elif c < (e_slow[i] or 0.0) and (e_fast[i] or 0.0) < (e_mid[i] or 0.0):
                st.structure = -1
        out.append(st)
    return out
