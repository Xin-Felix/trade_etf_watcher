"""组合到期损益、最大盈亏、盈亏平衡点（纯函数）.

金额单位：元。ETF 期权合约单位 10000 份，所以「每份价差 × 10000 × 张数」= 盈亏。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from watcher.strategy.pricing import intrinsic

# ETF 期权合约单位（1 张 = 10000 份标的）
CONTRACT_MULTIPLIER = 10000


@dataclass(slots=True)
class Leg:
    """组合中的一条腿.

    price: 建仓权利金（每份）。买入=付出，卖出=收取，符号由 side 决定，这里始终填正数。
    qty:   张数（正整数）
    """
    option_code: str
    option_type: str          # 'call' | 'put'
    strike: float
    side: str                 # 'buy' | 'sell'
    price: float
    qty: int = 1
    expire_date: str = ""
    iv: float = 0.0
    name: str = ""
    multiplier: int = CONTRACT_MULTIPLIER

    @property
    def sign(self) -> int:
        """买入 +1（持有多头），卖出 -1."""
        return 1 if self.side == "buy" else -1

    @property
    def scale(self) -> float:
        """每份价格变动对应的金额系数（含方向、张数、合约单位）."""
        return self.sign * self.qty * self.multiplier

    @property
    def cost(self) -> float:
        """建仓现金流：买入为正（支出），卖出为负（收入），单位元."""
        return self.sign * self.price * self.qty * self.multiplier


def net_cost(legs: list[Leg]) -> float:
    """净成本（>0 净支出/借记，<0 净收入/贷记），单位元."""
    return sum(leg.cost for leg in legs)


def payoff_at_expiry(legs: list[Leg], spot: float) -> float:
    """到期时组合总盈亏（已扣建仓成本），单位元."""
    total = 0.0
    for leg in legs:
        value = intrinsic(spot, leg.strike, leg.option_type)
        total += leg.scale * value - leg.cost
    return total


def _spot_range(legs: list[Leg], current_spot: float, points: int = 201) -> list[float]:
    strikes = [leg.strike for leg in legs if leg.strike > 0]
    anchors = strikes + ([current_spot] if current_spot > 0 else [])
    if not anchors:
        return []
    lo_anchor, hi_anchor = min(anchors), max(anchors)
    span = max(hi_anchor - lo_anchor, hi_anchor * 0.15, 0.01)
    lo = max(0.0, lo_anchor - span * 0.6)
    hi = hi_anchor + span * 0.6
    if hi <= lo:
        hi = lo + 0.01
    step = (hi - lo) / (points - 1)
    return [lo + step * i for i in range(points)]


def payoff_curve(
    legs: list[Leg], current_spot: float, points: int = 201
) -> list[tuple[float, float]]:
    """到期损益曲线 [(标的价, 盈亏元), ...]，横轴覆盖各行权价与现价并留余量."""
    if not legs:
        return []
    return [(s, payoff_at_expiry(legs, s)) for s in _spot_range(legs, current_spot, points)]


def breakevens(legs: list[Leg], current_spot: float) -> list[float]:
    """盈亏平衡点（曲线过零点，线性插值）."""
    curve = payoff_curve(legs, current_spot, points=801)
    out: list[float] = []
    for (s0, p0), (s1, p1) in zip(curve, curve[1:]):
        if p0 == 0.0:
            out.append(s0)
        elif (p0 < 0 < p1) or (p1 < 0 < p0):
            out.append(s0 + (s1 - s0) * (-p0) / (p1 - p0))
    # 去重（相邻插值可能重复）
    dedup: list[float] = []
    for v in out:
        if not dedup or abs(v - dedup[-1]) > 1e-6:
            dedup.append(v)
    return dedup


def _slope_beyond(legs: list[Leg], side: str) -> float:
    """极端价格外侧的斜率（判断盈亏是否无限）.

    side='up' 看标的涨到极高处，'down' 看跌到 0 附近。
    """
    total = 0.0
    for leg in legs:
        if leg.option_type == "call":
            # 高价区 call 斜率 +1/份；低价区为 0
            if side == "up":
                total += leg.scale
        else:
            # 低价区 put 斜率 -1/份（标的越低盈利越多）；高价区为 0
            if side == "down":
                total -= leg.scale
    return total


@dataclass(slots=True)
class Summary:
    net_cost: float                    # >0 净支出，<0 净收入
    max_profit: float | None           # None = 理论无限
    max_loss: float | None             # None = 理论无限（负数表示亏损额）
    breakevens: list[float] = field(default_factory=list)
    max_profit_at: float | None = None
    max_loss_at: float | None = None
    current_pnl_at_expiry: float = 0.0  # 若标的停在现价，到期损益
    risk_reward: float | None = None     # 最大盈利 / 最大亏损绝对值

    def as_dict(self) -> dict:
        return {
            "netCost": self.net_cost,
            "maxProfit": self.max_profit,
            "maxLoss": self.max_loss,
            "breakevens": self.breakevens,
            "maxProfitAt": self.max_profit_at,
            "maxLossAt": self.max_loss_at,
            "pnlAtCurrentSpot": self.current_pnl_at_expiry,
            "riskReward": self.risk_reward,
        }


def summarize(legs: list[Leg], current_spot: float) -> Summary:
    """组合关键指标：净成本、最大盈亏（含无限判定）、盈亏平衡点."""
    if not legs:
        return Summary(net_cost=0.0, max_profit=0.0, max_loss=0.0)

    curve = payoff_curve(legs, current_spot, points=801)
    up_slope = _slope_beyond(legs, "up")
    down_slope = _slope_beyond(legs, "down")

    # 曲线内的极值（转折点必在行权价上，采样足够密即可）
    best_s, best_p = max(curve, key=lambda x: x[1])
    worst_s, worst_p = min(curve, key=lambda x: x[1])

    # 向上无限盈利 / 向下（标的跌）无限盈利
    profit_unlimited = up_slope > 1e-9 or down_slope < -1e-9
    loss_unlimited = up_slope < -1e-9 or down_slope > 1e-9

    max_profit = None if profit_unlimited else best_p
    max_loss = None if loss_unlimited else worst_p

    rr: float | None = None
    if max_profit is not None and max_loss is not None and abs(max_loss) > 1e-9:
        rr = max_profit / abs(max_loss)

    return Summary(
        net_cost=net_cost(legs),
        max_profit=max_profit,
        max_loss=max_loss,
        breakevens=breakevens(legs, current_spot),
        max_profit_at=None if profit_unlimited else best_s,
        max_loss_at=None if loss_unlimited else worst_s,
        current_pnl_at_expiry=payoff_at_expiry(legs, current_spot),
        risk_reward=rr,
    )
