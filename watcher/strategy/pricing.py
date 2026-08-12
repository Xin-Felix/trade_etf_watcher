"""Black-Scholes 定价、希腊字母、隐含波动率（纯函数）.

约定：
- 价格单位与标的一致（ETF 期权即"元/份"），合约乘数在 payoff 层处理
- vol 为年化波动率小数（0.224 = 22.4%），与新浪 CON_SO 的 IV 字段口径一致
- theta 返回"每自然日"，vega 返回"每 1 个波动率百分点"，便于直接读数
"""
from __future__ import annotations

import math
from datetime import date

# 无风险利率（年化）。A 股期权定价惯例取短端利率，1.5% 足够用
DEFAULT_RISK_FREE = 0.015
# 一年的自然日数（用自然日贴现，与"持有到期还有几天"的直觉一致）
DAYS_PER_YEAR = 365.0
_SQRT_2PI = math.sqrt(2.0 * math.pi)


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / _SQRT_2PI


def parse_expire_date(expire_date: str) -> date | None:
    """支持 '20260826' 与 '2026-08-26' 两种格式（两张表格式不一致）."""
    s = (expire_date or "").replace("-", "").strip()
    if len(s) != 8 or not s.isdigit():
        return None
    try:
        return date(int(s[:4]), int(s[4:6]), int(s[6:8]))
    except ValueError:
        return None


def days_to_expiry(expire_date: str, today: date | None = None) -> int:
    """剩余自然日（到期当日算 0，已过期返回 0）."""
    exp = parse_expire_date(expire_date)
    if exp is None:
        return 0
    ref = today or date.today()
    return max(0, (exp - ref).days)


def years_to_expiry(expire_date: str, today: date | None = None) -> float:
    return days_to_expiry(expire_date, today) / DAYS_PER_YEAR


def intrinsic(spot: float, strike: float, opt_type: str) -> float:
    """内在价值（每份）."""
    if opt_type == "call":
        return max(0.0, spot - strike)
    return max(0.0, strike - spot)


def bs_price(
    spot: float,
    strike: float,
    t_years: float,
    vol: float,
    opt_type: str,
    r: float = DEFAULT_RISK_FREE,
) -> float:
    """欧式期权理论价（每份）。t<=0 或 vol<=0 时退化为内在价值."""
    if spot <= 0 or strike <= 0:
        return 0.0
    if t_years <= 0 or vol <= 0:
        return intrinsic(spot, strike, opt_type)

    sqrt_t = math.sqrt(t_years)
    d1 = (math.log(spot / strike) + (r + 0.5 * vol * vol) * t_years) / (vol * sqrt_t)
    d2 = d1 - vol * sqrt_t
    disc = math.exp(-r * t_years)
    if opt_type == "call":
        return spot * _norm_cdf(d1) - strike * disc * _norm_cdf(d2)
    return strike * disc * _norm_cdf(-d2) - spot * _norm_cdf(-d1)


def greeks(
    spot: float,
    strike: float,
    t_years: float,
    vol: float,
    opt_type: str,
    r: float = DEFAULT_RISK_FREE,
) -> dict[str, float]:
    """返回 delta / gamma / theta(每日) / vega(每1%波动率) / rho(每1%利率)."""
    if spot <= 0 or strike <= 0 or t_years <= 0 or vol <= 0:
        # 到期或无波动率：delta 退化为 0/±1，其余为 0
        if t_years <= 0:
            itm = (spot > strike) if opt_type == "call" else (spot < strike)
            delta = (1.0 if opt_type == "call" else -1.0) if itm else 0.0
        else:
            delta = 0.0
        return {"delta": delta, "gamma": 0.0, "theta": 0.0, "vega": 0.0, "rho": 0.0}

    sqrt_t = math.sqrt(t_years)
    d1 = (math.log(spot / strike) + (r + 0.5 * vol * vol) * t_years) / (vol * sqrt_t)
    d2 = d1 - vol * sqrt_t
    disc = math.exp(-r * t_years)
    pdf_d1 = _norm_pdf(d1)

    gamma = pdf_d1 / (spot * vol * sqrt_t)
    vega_per_1 = spot * pdf_d1 * sqrt_t          # 每 1.0 的波动率变化
    theta_term = -(spot * pdf_d1 * vol) / (2.0 * sqrt_t)

    if opt_type == "call":
        delta = _norm_cdf(d1)
        theta_per_year = theta_term - r * strike * disc * _norm_cdf(d2)
        rho_per_1 = strike * t_years * disc * _norm_cdf(d2)
    else:
        delta = _norm_cdf(d1) - 1.0
        theta_per_year = theta_term + r * strike * disc * _norm_cdf(-d2)
        rho_per_1 = -strike * t_years * disc * _norm_cdf(-d2)

    return {
        "delta": delta,
        "gamma": gamma,
        "theta": theta_per_year / DAYS_PER_YEAR,  # 每自然日
        "vega": vega_per_1 / 100.0,               # 每 1 个百分点
        "rho": rho_per_1 / 100.0,
    }


def implied_vol(
    market_price: float,
    spot: float,
    strike: float,
    t_years: float,
    opt_type: str,
    r: float = DEFAULT_RISK_FREE,
    lo: float = 0.001,
    hi: float = 5.0,
    tol: float = 1e-6,
    max_iter: int = 100,
) -> float | None:
    """二分法反解隐含波动率（行情缺 IV 时兜底）。无解返回 None."""
    if market_price <= 0 or t_years <= 0 or spot <= 0 or strike <= 0:
        return None
    # 低于内在价值或高于标的价，无有效解
    if market_price < intrinsic(spot, strike, opt_type) - 1e-9:
        return None

    f_lo = bs_price(spot, strike, t_years, lo, opt_type, r) - market_price
    f_hi = bs_price(spot, strike, t_years, hi, opt_type, r) - market_price
    if f_lo > 0 or f_hi < 0:
        return None

    for _ in range(max_iter):
        mid = 0.5 * (lo + hi)
        f_mid = bs_price(spot, strike, t_years, mid, opt_type, r) - market_price
        if abs(f_mid) < tol:
            return mid
        if f_mid < 0:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)
