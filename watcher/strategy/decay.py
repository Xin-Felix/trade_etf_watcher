"""时间价值衰减与组合希腊字母汇总.

核心用途：回答"我现在买进去，标的不动的话每天亏多少"。
做法是按 BS 用「剩余天数 - N」重新定价，而不是拿 theta 线性外推——
临近到期时 theta 本身会加速，线性外推会低估损耗。
"""
from __future__ import annotations

from datetime import date

from watcher.strategy.payoff import Leg
from watcher.strategy.pricing import (
    DEFAULT_RISK_FREE,
    DAYS_PER_YEAR,
    bs_price,
    days_to_expiry,
    greeks,
)


def theoretical_value(
    legs: list[Leg],
    spot: float,
    days_forward: int = 0,
    vol_shift: float = 0.0,
    today: date | None = None,
    r: float = DEFAULT_RISK_FREE,
) -> float:
    """组合在 days_forward 天后的理论市值（元，不含建仓成本）.

    vol_shift: 波动率绝对变动（0.02 = IV 上升 2 个百分点），用于压力测试。
    """
    total = 0.0
    for leg in legs:
        remain = max(0, days_to_expiry(leg.expire_date, today) - days_forward)
        t = remain / DAYS_PER_YEAR
        vol = max(0.0001, (leg.iv or 0.0) + vol_shift)
        px = bs_price(spot, leg.strike, t, vol, leg.option_type, r)
        total += leg.scale * px
    return total


def decay_schedule(
    legs: list[Leg],
    spot: float,
    horizons: tuple[int, ...] = (1, 3, 7),
    today: date | None = None,
    r: float = DEFAULT_RISK_FREE,
) -> dict:
    """时间损耗表：标的价不动时，未来若干天的理论盈亏.

    返回 {
      'currentValue': 现在的理论市值,
      'entryCost': 建仓净成本,
      'items': [{'days':1,'value':..,'pnl':..,'decay':..}, ...],
      'perDay': 明日相对今日的损耗（负数=亏损）,
    }
    pnl  = 该时点理论市值 - 建仓净成本（相对建仓的浮动盈亏）
    decay= 该时点理论市值 - 当前理论市值（纯时间造成的变化）
    """
    entry_cost = sum(leg.cost for leg in legs)
    cur = theoretical_value(legs, spot, 0, today=today, r=r)
    items = []
    for d in horizons:
        val = theoretical_value(legs, spot, d, today=today, r=r)
        items.append({
            "days": d,
            "value": val,
            "pnl": val - entry_cost,
            "decay": val - cur,
        })
    per_day = items[0]["decay"] if items and items[0]["days"] == 1 else None
    if per_day is None:
        one = theoretical_value(legs, spot, 1, today=today, r=r)
        per_day = one - cur
    return {
        "currentValue": cur,
        "entryCost": entry_cost,
        "items": items,
        "perDay": per_day,
    }


def combo_greeks(
    legs: list[Leg],
    spot: float,
    today: date | None = None,
    r: float = DEFAULT_RISK_FREE,
) -> dict[str, float]:
    """组合希腊字母汇总（已乘方向、张数、合约单位）.

    delta: 标的涨 1 元，组合盈亏（元）
    gamma: 标的涨 1 元，delta 的变化（元/元）
    theta: 每过一自然日，组合盈亏（元，通常为负）
    vega : IV 涨 1 个百分点，组合盈亏（元）
    """
    total = {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0, "rho": 0.0}
    for leg in legs:
        t = days_to_expiry(leg.expire_date, today) / DAYS_PER_YEAR
        vol = max(0.0001, leg.iv or 0.0)
        g = greeks(spot, leg.strike, t, vol, leg.option_type, r)
        for k in total:
            total[k] += g[k] * leg.scale
    return total


def stress_matrix(
    legs: list[Leg],
    spot: float,
    spot_moves: tuple[float, ...] = (-0.02, -0.01, 0.0, 0.01, 0.02),
    days_forward: int = 1,
    vol_shifts: tuple[float, ...] = (-0.05, 0.0, 0.05),
    today: date | None = None,
) -> list[dict]:
    """压力测试：标的涨跌 × IV 变动，days_forward 天后的浮动盈亏（元）."""
    entry_cost = sum(leg.cost for leg in legs)
    out: list[dict] = []
    for dv in vol_shifts:
        row = {"volShift": dv, "cells": []}
        for mv in spot_moves:
            s = spot * (1 + mv)
            val = theoretical_value(legs, s, days_forward, vol_shift=dv, today=today)
            row["cells"].append({"spotMove": mv, "spot": s, "pnl": val - entry_cost})
        out.append(row)
    return out
