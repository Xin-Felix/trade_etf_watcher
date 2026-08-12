"""市场日内动量（Market Intraday Momentum, Gao/Han/Li/Zhou 2018）.

原文：标普500 ETF 第一个半小时收益（自前收盘起算）正向预测最后一个半小时收益，
R²≈2%，与倒数第二个半小时结合后预测力更强。

本项目 11 个 ETF × 243 个交易日实测（Tushare 5 分钟线，2025-07~2026-07）：
    预测性回归  r_last ~ r_first:  斜率 +0.0555, t=+7.32, R²=1.97%（与原文一致）
    分档单调性  早盘<-1%→末半小时均值 -0.0085%；-1~0%→+0.0115%
               0~1%→+0.0637%；>+1%→+0.1808%（四档完全单调）
    组合信号    早盘>0 且 倒二半小时>0 时做多末半小时：
               687 次, 胜率 55.0%, 单笔均 +0.0867%(已扣0.05%双边成本), t=+5.00

**只发看多信号**：多空双向版本 t=0.02（加入做空反而抹平收益），
早盘走弱时的末半小时均值只有 -0.0085%，做空没有统计意义，故弱势只作提示不报信号。

A 股 4 小时 = 8 个半小时：h1 09:30-10:00(first) ... h7 14:00-14:30(pen) h8 14:30-15:00(last)
"""
from __future__ import annotations

from dataclasses import dataclass

from watcher.models import MinuteBar

T_FIRST_END = "1000"     # 第一个半小时结束
T_PEN_START = "1400"     # 倒数第二个半小时起点
T_PEN_END = "1430"       # 倒数第二个半小时结束 = 最后半小时起点

# 实测分档统计：(下界, 标签, 末半小时历史均值%, 历史上涨概率%)
BUCKETS = [
    (1.0, "早盘大涨", 0.1808, 61.2),
    (0.0, "早盘小涨", 0.0637, 57.3),
    (-1.0, "早盘小跌", 0.0115, 51.6),
    (float("-inf"), "早盘大跌", -0.0085, 46.1),
]


@dataclass(slots=True)
class MomentumContext:
    """日内动量上下文（14:30 时点的方向参考）."""
    r_first: float = 0.0          # 早盘半小时涨幅 %（自前收盘起算）
    r_pen: float = 0.0            # 倒数第二个半小时涨幅 %
    bucket: str = ""              # 所处分档
    exp_last: float = 0.0         # 该档末半小时历史均值 %
    up_prob: float = 0.0          # 该档历史上涨概率 %
    direction: str | None = None  # 'long' 或 None（不发做空信号，见模块说明）
    detail: str = ""


def _price_at(bars: list[MinuteBar], hhmm: str) -> float | None:
    """取不晚于 hhmm 的最后一根 bar 收盘价（bar 时间戳为结束时刻）."""
    best = None
    for b in bars:
        if len(b.ts) >= 12 and b.ts[8:12] <= hhmm:
            best = b
        else:
            break
    return best.close if best and best.close > 0 else None


def _bucket_of(r_first: float) -> tuple[str, float, float]:
    for lo, label, exp, prob in BUCKETS:
        if r_first >= lo:
            return label, exp, prob
    return BUCKETS[-1][1], BUCKETS[-1][2], BUCKETS[-1][3]


def compute(today_bars: list[MinuteBar], prev_close: float) -> MomentumContext | None:
    """计算 14:30 时点的日内动量上下文；数据不足返回 None.

    today_bars 需按时间升序，且已覆盖到 14:30。
    """
    if prev_close <= 0 or not today_bars:
        return None
    bars = sorted(today_bars, key=lambda b: b.ts)
    p_first = _price_at(bars, T_FIRST_END)
    p_1400 = _price_at(bars, T_PEN_START)
    p_1430 = _price_at(bars, T_PEN_END)
    if not (p_first and p_1400 and p_1430):
        return None
    # 必须真的到了 14:30 之后（否则 p_1430 只是早于 14:30 的替代值）
    if bars[-1].ts[8:12] < T_PEN_END:
        return None

    r_first = (p_first - prev_close) / prev_close * 100
    r_pen = (p_1430 - p_1400) / p_1400 * 100
    label, exp_last, up_prob = _bucket_of(r_first)

    ctx = MomentumContext(
        r_first=r_first, r_pen=r_pen, bucket=label,
        exp_last=exp_last, up_prob=up_prob,
    )
    # M4：早盘与倒二半小时同为正 → 做多末半小时（实测 t=+5.00）
    if r_first > 0 and r_pen > 0:
        ctx.direction = "long"
        ctx.detail = (f"{label}{r_first:+.2f}%、尾盘前半小时{r_pen:+.2f}%，"
                      f"末半小时历史均值{exp_last:+.3f}%、上涨概率{up_prob:.0f}%")
    else:
        ctx.detail = (f"{label}{r_first:+.2f}%、尾盘前半小时{r_pen:+.2f}%，"
                      f"不满足做多条件（需两者均为正）")
    return ctx
