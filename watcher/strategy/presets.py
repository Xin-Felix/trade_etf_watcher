"""常用期权策略模板：给定合约链 + 标的现价，自动挑腿.

输入的 chain 是「合约行情字典」列表，字段沿用 T 型页 payload 的口径：
  {code, name, option_type: 'call'|'put', strike, price, iv, expire_date, buy_price, sell_price}

买方视角为主（你做 T+0 买方），价差类用于降低成本、控制单笔亏损上限。
"""
from __future__ import annotations

from watcher.strategy.payoff import Leg

# 策略清单：key -> (显示名, 说明)
PRESETS: dict[str, tuple[str, str]] = {
    "long_call": ("买认购", "看涨。成本=权利金，亏损有限，盈利无限，怕横盘（时间损耗）"),
    "long_put": ("买认沽", "看跌。成本=权利金，亏损有限，盈利大，怕横盘"),
    "bull_call_spread": ("牛市认购价差", "温和看涨。买近档+卖远档，成本降低，盈亏都有上限"),
    "bear_put_spread": ("熊市认沽价差", "温和看跌。买近档+卖远档，成本降低，盈亏都有上限"),
    "long_straddle": ("买跨式", "赌大波动（方向不明）。同行权价买购+买沽，成本高，需要大幅波动"),
    "long_strangle": ("买宽跨式", "赌大波动，比跨式便宜，但需要更大幅度才回本"),
    "call_butterfly": ("认购蝶式", "赌横盘在中间行权价附近。成本低，盈亏都有限"),
}


def _mid_price(item: dict) -> float:
    """成交价优先，缺失时用买卖中价，再退化到任一侧."""
    px = item.get("price")
    if px and px > 0:
        return float(px)
    bid = item.get("buy_price") or 0
    ask = item.get("sell_price") or 0
    if bid > 0 and ask > 0:
        return (float(bid) + float(ask)) / 2
    return float(bid or ask or 0)


def _to_leg(item: dict, side: str, qty: int = 1) -> Leg | None:
    px = _mid_price(item)
    if px <= 0:
        return None
    return Leg(
        option_code=item.get("code", ""),
        option_type=item.get("option_type", "call"),
        strike=float(item.get("strike") or 0),
        side=side,
        price=px,
        qty=qty,
        expire_date=item.get("expire_date", ""),
        iv=float(item.get("iv") or 0),
        name=item.get("name", ""),
    )


def _norm_expiry(v) -> str:
    return str(v or "").replace("-", "").strip()


def pick_expiry(chain: list[dict], expiry: str | None = None) -> str:
    """确定用哪个到期月：指定且存在则用它，否则用最近到期的那一个.

    价差/跨式/蝶式**必须同一到期月**，否则算出来的最大盈亏没有意义
    （不同月份到期时间不同，到期损益图不能简单叠加）。
    """
    quoted = [c for c in chain if _mid_price(c) > 0]
    exps = {_norm_expiry(c.get("expire_date")) for c in quoted}
    exps.discard("")
    if not exps:
        return ""
    want = _norm_expiry(expiry)
    if want and want in exps:
        return want
    return min(exps)


def _sorted_side(chain: list[dict], opt_type: str, expiry: str) -> list[dict]:
    """同一到期月、同方向、有报价的合约，按行权价升序；同行权价去重（带 A 调整合约）."""
    items = [
        c for c in chain
        if c.get("option_type") == opt_type
        and _mid_price(c) > 0
        and _norm_expiry(c.get("expire_date")) == expiry
    ]
    best: dict[float, dict] = {}
    for c in items:
        k = round(float(c.get("strike") or 0), 4)
        cur = best.get(k)
        # 同行权价多合约时保留成交量大的（主力合约，滑点小）
        if cur is None or float(c.get("volume") or 0) > float(cur.get("volume") or 0):
            best[k] = c
    return [best[k] for k in sorted(best)]


def _atm_index(items: list[dict], spot: float) -> int | None:
    if not items:
        return None
    return min(
        range(len(items)),
        key=lambda i: abs(float(items[i].get("strike") or 0) - spot),
    )


def build_preset(
    name: str,
    chain: list[dict],
    spot: float,
    qty: int = 1,
    expiry: str | None = None,
) -> list[Leg]:
    """按模板挑腿（全部腿锁定同一到期月）。挑不出时返回空列表."""
    if not chain or spot <= 0:
        return []

    exp = pick_expiry(chain, expiry)
    if not exp:
        return []
    calls = _sorted_side(chain, "call", exp)
    puts = _sorted_side(chain, "put", exp)
    ci = _atm_index(calls, spot)
    pi = _atm_index(puts, spot)

    def leg(items: list[dict], idx: int | None, side: str, offset: int = 0, n: int = qty) -> Leg | None:
        if idx is None:
            return None
        j = idx + offset
        if j < 0 or j >= len(items):
            return None
        return _to_leg(items[j], side, n)

    legs: list[Leg | None]
    if name == "long_call":
        legs = [leg(calls, ci, "buy")]
    elif name == "long_put":
        legs = [leg(puts, pi, "buy")]
    elif name == "bull_call_spread":
        legs = [leg(calls, ci, "buy"), leg(calls, ci, "sell", +2)]
    elif name == "bear_put_spread":
        legs = [leg(puts, pi, "buy"), leg(puts, pi, "sell", -2)]
    elif name == "long_straddle":
        legs = [leg(calls, ci, "buy"), leg(puts, pi, "buy")]
    elif name == "long_strangle":
        legs = [leg(calls, ci, "buy", +1), leg(puts, pi, "buy", -1)]
    elif name == "call_butterfly":
        legs = [
            leg(calls, ci, "buy", -2),
            leg(calls, ci, "sell", 0, qty * 2),
            leg(calls, ci, "buy", +2),
        ]
    else:
        return []

    return [l for l in legs if l is not None] if all(legs) else []
