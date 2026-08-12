"""期权策略计算包（纯函数，无网络无 GUI 依赖）.

- pricing.py : Black-Scholes 定价 + 希腊字母 + 隐含波动率
- payoff.py  : 组合到期损益、最大盈亏、盈亏平衡点
- decay.py   : 时间价值衰减、组合希腊字母汇总
- presets.py : 常用策略模板（单腿/价差/跨式/蝶式）
"""
from watcher.strategy.decay import (
    combo_greeks,
    decay_schedule,
    theoretical_value,
)
from watcher.strategy.payoff import (
    Leg,
    CONTRACT_MULTIPLIER,
    breakevens,
    payoff_at_expiry,
    payoff_curve,
    summarize,
)
from watcher.strategy.presets import PRESETS, build_preset, pick_expiry
from watcher.strategy.pricing import bs_price, greeks, implied_vol, years_to_expiry

__all__ = [
    "Leg",
    "CONTRACT_MULTIPLIER",
    "bs_price",
    "greeks",
    "implied_vol",
    "years_to_expiry",
    "payoff_at_expiry",
    "payoff_curve",
    "breakevens",
    "summarize",
    "theoretical_value",
    "combo_greeks",
    "decay_schedule",
    "PRESETS",
    "build_preset",
    "pick_expiry",
]
