"""AI 策略推荐：市场数据收集、Prompt 组装、响应解析."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from watcher.ai.client import DeepSeekClient
from watcher.config import Config

logger = logging.getLogger(__name__)


# ---------- 数据收集 ----------

@dataclass
class MarketContext:
    """收集后的市场上下文，用于组装 prompt."""
    underlying_code: str = ""
    underlying_name: str = ""
    spot: float = 0.0
    change_pct: float = 0.0
    prev_close: float = 0.0
    today_high: float = 0.0
    today_low: float = 0.0
    today_amplitude: float = 0.0    # 今日振幅
    # 技术面
    macd_status: str = ""       # "金叉"/"死叉"/"多头排列"/"空头排列"
    macd_position: str = ""     # "零轴上方"/"零轴下方"/"零轴附近"
    macd_bar_trend: str = ""    # "柱子放大"/"柱子缩小"/"翻红"/"翻绿"
    rsi: float = 0.0
    vwap_direction: str = ""    # "上方"/"下方"/"贴线"
    vwap_value: float = 0.0
    trend_5d: str = ""          # "上涨"/"下跌"/"震荡"
    ma5: float = 0.0
    ma10: float = 0.0
    ma20: float = 0.0
    # 近几日走势摘要
    recent_bars_summary: str = ""  # 近 3-5 天每天的 OHLC 摘要
    intraday_pattern: str = ""     # 日内形态描述
    # 支撑阻力
    support: float = 0.0           # 近期低点支撑
    resistance: float = 0.0        # 近期高点阻力
    # 量能
    today_volume: int = 0          # 今日成交量
    avg_volume_5d: int = 0         # 5日均量
    volume_ratio: float = 0.0      # 量比（今日/5日均量）
    # 时间信息
    market_session: str = ""       # "早盘"/"午盘"/"尾盘"/"盘后"
    # 期权面
    avg_iv_call: float = 0.0
    avg_iv_put: float = 0.0
    iv_skew: float = 0.0           # put IV - call IV（正=看跌情绪重）
    atm_iv: float = 0.0            # ATM 合约 IV
    pcr_oi: float = 0.0            # 持仓量 PCR
    pcr_vol: float = 0.0           # 成交量 PCR
    near_expiry: str = ""          # 最近到期日
    near_expiry_days: int = 0
    far_expiry: str = ""           # 次近到期日
    far_expiry_days: int = 0
    days_to_expiry: int = 0
    total_call_oi: int = 0
    total_put_oi: int = 0
    max_pain: float = 0.0          # 最大痛苦点（持仓量最集中的行权价）
    # ATM theta 预估
    atm_theta_per_day: float = 0.0  # ATM 合约每天时间损耗（元/张）
    # 合约链摘要（ATM±5 档）
    chain_summary: list[dict] = field(default_factory=list)
    # 远月合约摘要
    far_month_summary: list[dict] = field(default_factory=list)


@dataclass
class UserParams:
    """用户输入的约束条件."""
    capital: float = 10000.0        # 投入金额（元）
    max_loss: float = 3000.0        # 最大可承受亏损（元）
    holding_days: int = 3           # 预期持仓天数
    style: str = "中性"             # 保守/中性/激进
    etf_shares: int = 0             # 持有现货份数（用于备兑策略，0=无现货）
    direction: str = "AI判断"       # 用户方向预判：看涨/看跌/震荡/大波动/AI判断
    target_price: str = ""          # 目标价位（选填）
    expiry_pref: str = "AI决定"     # 到期月偏好：近月/远月/AI决定
    allow_naked_sell: bool = False  # 是否允许裸卖（卖方策略风险大）


def collect_market_context(
    underlying_code: str,
    underlying_name: str,
    chain: list[dict],
    spot: float,
    bars_1min: list | None = None,
    cfg: Config | None = None,
    daily_bars: list | None = None,
) -> MarketContext:
    """从现有数据收集市场上下文."""
    ctx = MarketContext(
        underlying_code=underlying_code,
        underlying_name=underlying_name,
        spot=spot,
    )

    # 技术面（从 1 分钟 bars 聚合 5 分钟计算）
    if bars_1min and len(bars_1min) >= 30:
        _fill_technicals(ctx, bars_1min)

    # Tushare 日 K 历史（覆盖/补充近日走势）
    if daily_bars and len(daily_bars) >= 3:
        _fill_daily_history(ctx, daily_bars)

    # 期权面
    if chain:
        _fill_option_context(ctx, chain, spot)

    return ctx


def _fill_technicals(ctx: MarketContext, bars: list) -> None:
    """从 bars 计算技术指标填入 ctx."""
    from watcher.signals.rules import _ema, _macd, _rsi, _sma, _vwap, direction_vwap
    from watcher.bars import aggregate_minute_bars

    # 基础价格数据
    if len(bars) >= 2:
        first_open = bars[0].open
        if first_open > 0:
            ctx.change_pct = (bars[-1].close - first_open) / first_open
        ctx.prev_close = first_open
        ctx.today_high = max(b.high for b in bars)
        ctx.today_low = min(b.low for b in bars)
        if first_open > 0:
            ctx.today_amplitude = (ctx.today_high - ctx.today_low) / first_open

    # 日内形态判断
    if len(bars) >= 30:
        q1 = len(bars) // 4
        q3 = q1 * 3
        avg_early = sum(b.close for b in bars[:q1]) / q1
        avg_mid = sum(b.close for b in bars[q1:q3]) / (q3 - q1)
        avg_late = sum(b.close for b in bars[q3:]) / (len(bars) - q3)
        if avg_late > avg_mid > avg_early:
            ctx.intraday_pattern = "逐步走高（多头趋势）"
        elif avg_late < avg_mid < avg_early:
            ctx.intraday_pattern = "逐步走低（空头趋势）"
        elif avg_mid < avg_early and avg_mid < avg_late:
            ctx.intraday_pattern = "V型反转（先跌后涨）"
        elif avg_mid > avg_early and avg_mid > avg_late:
            ctx.intraday_pattern = "倒V型（冲高回落）"
        else:
            ctx.intraday_pattern = "窄幅震荡"

    # 支撑阻力（近期高低点）
    if len(bars) >= 60:
        # 将 bars 按天分组，取近几天的高低
        days_data: dict[str, list] = {}
        for b in bars:
            days_data.setdefault(b.ts[:8], []).append(b)
        sorted_days = sorted(days_data.keys())
        if len(sorted_days) >= 2:
            # 支撑 = 前几日最低点
            prev_day_bars = []
            for d in sorted_days[:-1]:
                prev_day_bars.extend(days_data[d])
            if prev_day_bars:
                ctx.support = min(b.low for b in prev_day_bars)
                ctx.resistance = max(b.high for b in prev_day_bars)

    # 成交量
    if len(bars) >= 10:
        ctx.today_volume = sum(b.volume for b in bars)
        # 5日均量需要按天算
        days_data2: dict[str, int] = {}
        for b in bars:
            days_data2[b.ts[:8]] = days_data2.get(b.ts[:8], 0) + b.volume
        day_vols = [v for _, v in sorted(days_data2.items())]
        if len(day_vols) >= 2:
            prev_vols = day_vols[:-1][-5:]
            ctx.avg_volume_5d = sum(prev_vols) // len(prev_vols) if prev_vols else 0
            if ctx.avg_volume_5d > 0:
                ctx.volume_ratio = ctx.today_volume / ctx.avg_volume_5d

    # 市场时段判断
    if bars:
        last_ts = bars[-1].ts
        if len(last_ts) >= 12:
            hh = int(last_ts[8:10])
            mm = int(last_ts[10:12])
            t = hh * 60 + mm
            if t < 10 * 60 + 30:
                ctx.market_session = "早盘（开盘30分钟内）"
            elif t < 11 * 60 + 30:
                ctx.market_session = "上午盘"
            elif t < 13 * 60 + 30:
                ctx.market_session = "午盘开盘"
            elif t < 14 * 60 + 30:
                ctx.market_session = "下午盘"
            else:
                ctx.market_session = "尾盘（收盘前30分钟）"

    # 聚合 5 分钟做 MACD
    bars5 = aggregate_minute_bars(bars, 5)
    if len(bars5) >= 26:
        closes = [b.close for b in bars5]
        dif, dea, macd_bar = _macd(closes)
        # MACD 状态
        if len(dif) >= 2:
            if dif[-2] <= dea[-2] and dif[-1] > dea[-1]:
                ctx.macd_status = "金叉（刚发生）"
            elif dif[-2] >= dea[-2] and dif[-1] < dea[-1]:
                ctx.macd_status = "死叉（刚发生）"
            elif dif[-1] > dea[-1]:
                ctx.macd_status = "多头排列"
            else:
                ctx.macd_status = "空头排列"
        # MACD 零轴位置
        if dif[-1] > 0.001:
            ctx.macd_position = "零轴上方"
        elif dif[-1] < -0.001:
            ctx.macd_position = "零轴下方"
        else:
            ctx.macd_position = "零轴附近"
        # MACD 柱子趋势
        if len(macd_bar) >= 3:
            if macd_bar[-1] > 0 and macd_bar[-2] <= 0:
                ctx.macd_bar_trend = "柱子刚翻红"
            elif macd_bar[-1] < 0 and macd_bar[-2] >= 0:
                ctx.macd_bar_trend = "柱子刚翻绿"
            elif macd_bar[-1] > macd_bar[-2] > 0:
                ctx.macd_bar_trend = "红柱放大（动能增强）"
            elif 0 < macd_bar[-1] < macd_bar[-2]:
                ctx.macd_bar_trend = "红柱缩小（动能减弱）"
            elif macd_bar[-1] < macd_bar[-2] < 0:
                ctx.macd_bar_trend = "绿柱放大（下跌加速）"
            elif macd_bar[-2] < macd_bar[-1] < 0:
                ctx.macd_bar_trend = "绿柱缩小（跌势趋缓）"

    # RSI
    if len(bars5) >= 20:
        closes = [b.close for b in bars5]
        rsi_list = _rsi(closes, 14)
        valid = [v for v in rsi_list if v is not None]
        if valid:
            ctx.rsi = valid[-1]

    # VWAP
    vwap_dir = direction_vwap(bars)
    if vwap_dir == "long":
        ctx.vwap_direction = "上方"
    elif vwap_dir == "short":
        ctx.vwap_direction = "下方"
    else:
        ctx.vwap_direction = "贴线"
    vwap_val = _vwap(bars)
    if vwap_val:
        ctx.vwap_value = vwap_val

    # 均线
    if len(bars5) >= 20:
        closes = [b.close for b in bars5]
        ma5_list = _sma(closes, 5)
        ma10_list = _sma(closes, 10)
        ma20_list = _sma(closes, 20)
        if ma5_list[-1] is not None:
            ctx.ma5 = ma5_list[-1]
        if ma10_list[-1] is not None:
            ctx.ma10 = ma10_list[-1]
        if ma20_list[-1] is not None:
            ctx.ma20 = ma20_list[-1]

    # 近期走势摘要（按天聚合）
    days_data: dict[str, list] = {}
    for b in bars:
        day = b.ts[:8]
        days_data.setdefault(day, []).append(b)
    day_summaries = []
    for day in sorted(days_data.keys())[-5:]:
        db = days_data[day]
        o, h, l, c = db[0].open, max(x.high for x in db), min(x.low for x in db), db[-1].close
        chg = (c - o) / o * 100 if o > 0 else 0
        day_summaries.append(f"{day[4:6]}-{day[6:8]}: O={o:.3f} H={h:.3f} L={l:.3f} C={c:.3f} ({chg:+.2f}%)")
    ctx.recent_bars_summary = "\n".join(day_summaries)

    # 趋势判断（用天级数据）
    if len(day_summaries) >= 3:
        day_closes = []
        for day in sorted(days_data.keys())[-5:]:
            db = days_data[day]
            day_closes.append(db[-1].close)
        if len(day_closes) >= 3:
            up_days = sum(1 for i in range(1, len(day_closes)) if day_closes[i] > day_closes[i-1])
            down_days = len(day_closes) - 1 - up_days
            total_change = (day_closes[-1] - day_closes[0]) / day_closes[0] if day_closes[0] > 0 else 0
            if total_change > 0.01:
                ctx.trend_5d = f"上涨（累计{total_change*100:+.2f}%，{up_days}阳{down_days}阴）"
            elif total_change < -0.01:
                ctx.trend_5d = f"下跌（累计{total_change*100:+.2f}%，{up_days}阳{down_days}阴）"
            else:
                ctx.trend_5d = f"震荡（累计{total_change*100:+.2f}%，{up_days}阳{down_days}阴）"


def _fill_daily_history(ctx: MarketContext, daily_bars: list) -> None:
    """从 Tushare 日 K 数据填充历史走势（覆盖分钟 bars 不足的部分）."""
    from watcher.signals.rules import _macd, _rsi, _sma

    # 近 20 日摘要
    recent = daily_bars[-20:]
    day_lines = []
    for b in recent:
        d = b.ts[:8]
        chg = (b.close - b.open) / b.open * 100 if b.open > 0 else 0
        vol_wan = b.volume / 10000  # 转万手
        day_lines.append(
            f"{d[4:6]}-{d[6:8]}: O={b.open:.3f} H={b.high:.3f} L={b.low:.3f} "
            f"C={b.close:.3f} ({chg:+.2f}%) 量={vol_wan:.0f}万"
        )
    # 用日 K 覆盖 recent_bars_summary（比分钟级聚合更准确）
    ctx.recent_bars_summary = "\n".join(day_lines[-10:])  # 最多展示 10 天

    # 日线级别趋势判断
    if len(recent) >= 5:
        closes = [b.close for b in recent]
        last5 = closes[-5:]
        up_days = sum(1 for i in range(1, len(last5)) if last5[i] > last5[i-1])
        total_chg = (last5[-1] - last5[0]) / last5[0] if last5[0] > 0 else 0
        # 更详细的趋势描述
        if total_chg > 0.02:
            ctx.trend_5d = f"明显上涨（5日累计{total_chg*100:+.2f}%，{up_days}阳{4-up_days}阴）"
        elif total_chg > 0.005:
            ctx.trend_5d = f"温和上涨（5日累计{total_chg*100:+.2f}%，{up_days}阳{4-up_days}阴）"
        elif total_chg < -0.02:
            ctx.trend_5d = f"明显下跌（5日累计{total_chg*100:+.2f}%，{up_days}阳{4-up_days}阴）"
        elif total_chg < -0.005:
            ctx.trend_5d = f"温和下跌（5日累计{total_chg*100:+.2f}%，{up_days}阳{4-up_days}阴）"
        else:
            ctx.trend_5d = f"横盘震荡（5日累计{total_chg*100:+.2f}%，{up_days}阳{4-up_days}阴）"

    # 日线级别技术指标（比分钟级更有趋势参考价值）
    if len(recent) >= 20:
        closes = [b.close for b in recent]
        # 日线均线
        ma5 = _sma(closes, 5)
        ma10 = _sma(closes, 10)
        ma20 = _sma(closes, 20)
        if ma5[-1] is not None:
            ctx.ma5 = ma5[-1]
        if ma10[-1] is not None:
            ctx.ma10 = ma10[-1]
        if ma20[-1] is not None:
            ctx.ma20 = ma20[-1]

    # 日线 RSI（若分钟级没算到就用日线补）
    if len(recent) >= 16 and ctx.rsi == 0:
        closes = [b.close for b in recent]
        rsi_list = _rsi(closes, 14)
        valid = [v for v in rsi_list if v is not None]
        if valid:
            ctx.rsi = valid[-1]

    # 近期波动率（用于判断 IV 是否偏贵）
    if len(recent) >= 10:
        returns = []
        for i in range(1, len(recent)):
            if recent[i-1].close > 0:
                returns.append((recent[i].close - recent[i-1].close) / recent[i-1].close)
        if returns:
            import math
            hist_vol = (sum(r*r for r in returns) / len(returns)) ** 0.5 * math.sqrt(252)
            # 存到 ctx 用于 prompt 中比较 IV vs 历史波动率
            ctx._hist_vol = hist_vol  # type: ignore[attr-defined]


def _fill_option_context(ctx: MarketContext, chain: list[dict], spot: float) -> None:
    """从期权链数据计算 IV/PCR/MaxPain 等指标."""
    from watcher.strategy.presets import pick_expiry, _norm_expiry
    from watcher.strategy.pricing import days_to_expiry

    # 确定最近到期月
    exp = pick_expiry(chain)
    if exp:
        ctx.near_expiry = exp
        ctx.days_to_expiry = days_to_expiry(exp)
        ctx.near_expiry_days = ctx.days_to_expiry

    # 筛选有报价的合约
    quoted = [c for c in chain if (c.get("price") or 0) > 0]
    near_month = [c for c in quoted if _norm_expiry(c.get("expire_date")) == exp] if exp else quoted

    # 平均 IV
    call_ivs = [c["iv"] for c in near_month if c.get("option_type") == "call" and c.get("iv", 0) > 0]
    put_ivs = [c["iv"] for c in near_month if c.get("option_type") == "put" and c.get("iv", 0) > 0]
    ctx.avg_iv_call = sum(call_ivs) / len(call_ivs) if call_ivs else 0.0
    ctx.avg_iv_put = sum(put_ivs) / len(put_ivs) if put_ivs else 0.0
    ctx.iv_skew = ctx.avg_iv_put - ctx.avg_iv_call

    # ATM IV（最接近现价的合约 IV）
    atm_contracts = [c for c in near_month if abs(float(c.get("strike", 0)) - spot) < spot * 0.02]
    atm_ivs = [c["iv"] for c in atm_contracts if c.get("iv", 0) > 0]
    ctx.atm_iv = sum(atm_ivs) / len(atm_ivs) if atm_ivs else ctx.avg_iv_call

    # PCR（持仓量 / 成交量）
    call_oi = sum(c.get("oi", 0) for c in near_month if c.get("option_type") == "call")
    put_oi = sum(c.get("oi", 0) for c in near_month if c.get("option_type") == "put")
    call_vol = sum(c.get("volume", 0) for c in near_month if c.get("option_type") == "call")
    put_vol = sum(c.get("volume", 0) for c in near_month if c.get("option_type") == "put")
    ctx.pcr_oi = put_oi / call_oi if call_oi > 0 else 0.0
    ctx.pcr_vol = put_vol / call_vol if call_vol > 0 else 0.0
    ctx.total_call_oi = call_oi
    ctx.total_put_oi = put_oi

    # 最大痛苦点（持仓量最集中的行权价）
    strike_oi: dict[float, int] = {}
    for c in near_month:
        k = float(c.get("strike", 0))
        if k > 0:
            strike_oi[k] = strike_oi.get(k, 0) + int(c.get("oi", 0))
    if strike_oi:
        ctx.max_pain = max(strike_oi, key=strike_oi.get)

    # ATM±5 档合约摘要（比之前多给 2 档）
    strikes = sorted({c.get("strike", 0) for c in near_month if c.get("strike", 0) > 0})
    if strikes:
        atm_idx = min(range(len(strikes)), key=lambda i: abs(strikes[i] - spot))
        keep_strikes = set(strikes[max(0, atm_idx - 5): atm_idx + 6])
        for c in near_month:
            if c.get("strike") in keep_strikes:
                ctx.chain_summary.append({
                    "type": c.get("option_type", ""),
                    "strike": c.get("strike", 0),
                    "price": c.get("price", 0),
                    "buy_price": c.get("buy_price", 0),
                    "sell_price": c.get("sell_price", 0),
                    "iv": c.get("iv", 0),
                    "volume": c.get("volume", 0),
                    "oi": c.get("oi", 0),
                })

    # 远月合约（第二个到期月，ATM±3 档，给 AI 更多选择）
    all_expiries = sorted({_norm_expiry(c.get("expire_date")) for c in quoted if _norm_expiry(c.get("expire_date"))})
    if len(all_expiries) >= 2:
        far_exp = all_expiries[1]
        ctx.far_expiry = far_exp
        ctx.far_expiry_days = days_to_expiry(far_exp)
        far_month = [c for c in quoted if _norm_expiry(c.get("expire_date")) == far_exp]
        far_strikes = sorted({c.get("strike", 0) for c in far_month if c.get("strike", 0) > 0})
        if far_strikes:
            fi = min(range(len(far_strikes)), key=lambda i: abs(far_strikes[i] - spot))
            fkeep = set(far_strikes[max(0, fi - 3): fi + 4])
            for c in far_month:
                if c.get("strike") in fkeep:
                    ctx.far_month_summary.append({
                        "type": c.get("option_type", ""),
                        "strike": c.get("strike", 0),
                        "price": c.get("price", 0),
                        "iv": c.get("iv", 0),
                    })

    # ATM Theta 预估（每张每天损耗多少元）
    if ctx.atm_iv > 0 and ctx.days_to_expiry > 0:
        from watcher.strategy.pricing import bs_price, greeks
        t_years = ctx.days_to_expiry / 365.0
        atm_strike = min(strikes, key=lambda k: abs(k - spot)) if strikes else spot
        g = greeks(spot, atm_strike, t_years, ctx.atm_iv, "call")
        # theta 是每份每天，乘 10000（合约单位）得每张每天
        ctx.atm_theta_per_day = abs(g["theta"]) * 10000


# ---------- Prompt 组装 ----------

SYSTEM_PROMPT = """你是一个资深的 A 股 ETF 期权策略分析师，拥有丰富的实战经验。

用户会提供：标的 ETF 的价格走势、技术指标、期权链实时数据（IV/成交量/持仓量/买卖价差）和投资约束。
你需要综合分析后推荐最优策略。

**分析框架（按顺序思考）：**
1. 方向判断：根据 MACD/RSI/均线/VWAP/近日走势 判断未来 N 天最可能的方向
2. 波动率判断：ATM IV 水平是高是低？IV Skew 正常吗？适合买波动率还是卖波动率？
3. 时间因素：距到期多少天？Theta 衰减对买方不利（<7天时间价值损耗加速）
4. 资金效率：用户资金有限，价差策略能降低成本控制风险
5. PCR 情绪：PCR>1 看空情绪重（实际可能是底部信号），PCR<0.6 看多情绪过热

**策略选择逻辑：**
- 看涨+IV低 → 买认购 或 牛市认购价差
- 看跌+IV低 → 买认沽 或 熊市认沽价差
- 方向不明+预期大波动 → 买跨式/宽跨式
- 看涨+IV高 → 牛市认购价差（降低 Vega 敞口）
- 震荡+IV高 → 卖跨式 或 蝶式（赚时间价值）
- 持有现货+温和看涨/震荡 → 备兑开仓（卖虚值认购）
- 持有现货+担心下跌 → 保护性认沽（买认沽保险）

**行权价选择原则：**
- 买方：选 ATM 或轻度 OTM（1-2档虚值），Delta 0.3-0.5 性价比最优
- 卖方：选 OTM（2-3档虚值），Delta 0.2-0.3 安全垫足够
- 价差：买 ATM + 卖 OTM 2-3 档，控制最大亏损
- 备兑：卖 OTM 1-2 档认购，Delta -0.2~-0.3

**严格约束：**
- 行权价必须从用户给出的合约链中选（不能编造）
- 张数 × 权利金 × 10000 不超过用户资金
- 最大亏损不超过用户给定上限
- ETF 期权合约单位 = 10000 份/张
- 备兑时卖出认购张数 ≤ etf_shares / 10000
- 如果用户指定了方向预判（非"AI判断"），策略方向必须与之一致
- 如果用户指定了目标价，选择能在该价位附近获利的行权价
- 如果用户不允许裸卖，不能推荐无保护的卖出认购/认沽（价差和备兑可以）
- 如果用户指定了到期月偏好，优先选择对应月份

**返回严格 JSON 格式：**
{
    "strategy_name": "策略中文名称",
    "reasoning": "基于数据的分析理由（150字以内，需引用具体数据）",
    "legs": [
        {"option_type": "call或put", "strike": 行权价数字, "side": "buy或sell", "qty": 张数}
    ],
    "risk_summary": {
        "estimated_cost": 预估建仓成本（元，正数为支出）,
        "max_loss": 最大亏损（元，负数）,
        "max_profit": 最大盈利（元，null=无限）,
        "breakeven": 盈亏平衡点（标的价格）,
        "win_probability": "高/中/低"
    },
    "notes": "具体入场时机和止损建议（80字以内）",
    "expire_date": "YYYYMMDD"
}

重要：你的输出必须是且仅是一个合法 JSON 对象，不要输出任何其他文字、解释或 markdown 格式。"""


def build_user_message(ctx: MarketContext, params: UserParams) -> str:
    """组装发给 AI 的用户消息."""
    # 合约链表格（按行权价分组，call/put 对齐）
    chain_lines = []
    # 按 strike 分组
    by_strike: dict[float, dict] = {}
    for c in ctx.chain_summary:
        k = c["strike"]
        if k not in by_strike:
            by_strike[k] = {}
        by_strike[k][c["type"]] = c
    for strike in sorted(by_strike.keys()):
        row = by_strike[strike]
        call = row.get("call")
        put = row.get("put")
        c_str = (f"C: 价={call['price']:.4f} 买={call.get('buy_price',0):.4f} "
                 f"卖={call.get('sell_price',0):.4f} IV={call['iv']*100:.1f}% "
                 f"量={call['volume']} 仓={call['oi']}" if call else "C: --")
        p_str = (f"P: 价={put['price']:.4f} 买={put.get('buy_price',0):.4f} "
                 f"卖={put.get('sell_price',0):.4f} IV={put['iv']*100:.1f}% "
                 f"量={put['volume']} 仓={put['oi']}" if put else "P: --")
        atm_mark = " ◀ATM" if abs(strike - ctx.spot) < ctx.spot * 0.005 else ""
        chain_lines.append(f"  K={strike:.3f}{atm_mark}")
        chain_lines.append(f"    {c_str}")
        chain_lines.append(f"    {p_str}")
    chain_text = "\n".join(chain_lines) if chain_lines else "  暂无可用合约数据"

    # 均线排列描述
    ma_desc = ""
    if ctx.ma5 and ctx.ma10 and ctx.ma20:
        if ctx.spot > ctx.ma5 > ctx.ma10 > ctx.ma20:
            ma_desc = "多头排列（价>MA5>MA10>MA20）"
        elif ctx.spot < ctx.ma5 < ctx.ma10 < ctx.ma20:
            ma_desc = "空头排列（价<MA5<MA10<MA20）"
        elif ctx.ma5 > ctx.ma10 and ctx.spot > ctx.ma5:
            ma_desc = "偏多（价格在短期均线上方）"
        elif ctx.ma5 < ctx.ma10 and ctx.spot < ctx.ma5:
            ma_desc = "偏空（价格在短期均线下方）"
        else:
            ma_desc = "交织（无明确方向）"

    msg = f"""## 标的信息
- 标的：{ctx.underlying_name}（{ctx.underlying_code}）
- 现价：{ctx.spot:.3f}
- 今日涨跌：{ctx.change_pct*100:+.2f}%
- 今日振幅：{ctx.today_amplitude*100:.2f}%（最高{ctx.today_high:.3f}，最低{ctx.today_low:.3f}）
- 日内形态：{ctx.intraday_pattern}
- 当前时段：{ctx.market_session or '未知'}
- 支撑位：{ctx.support:.3f} | 阻力位：{ctx.resistance:.3f}

## 近日走势（近5-10个交易日）
{ctx.recent_bars_summary or '数据不足'}
- 趋势判断：{ctx.trend_5d}

## 技术指标（5分钟级别）
- MACD：{ctx.macd_status}，{ctx.macd_position}，{ctx.macd_bar_trend}
- RSI(14)：{ctx.rsi:.1f}{'（超买区>70）' if ctx.rsi > 70 else '（超卖区<30）' if ctx.rsi < 30 else '（中性区间）'}
- VWAP：{ctx.vwap_value:.3f}，价格在VWAP{ctx.vwap_direction}
- 均线：MA5={ctx.ma5:.3f} MA10={ctx.ma10:.3f} MA20={ctx.ma20:.3f}
- 均线排列：{ma_desc}
- 量比：{ctx.volume_ratio:.2f}{'（放量）' if ctx.volume_ratio > 1.5 else '（缩量）' if ctx.volume_ratio < 0.7 else '（正常）'} 今日量={ctx.today_volume} 5日均量={ctx.avg_volume_5d}

## 期权市场数据
### 近月（{ctx.near_expiry}到期，剩余{ctx.near_expiry_days or ctx.days_to_expiry}天）
- ATM IV：{ctx.atm_iv*100:.1f}%{f"（历史波动率{getattr(ctx, '_hist_vol', 0)*100:.1f}%，{'IV偏高适合卖方' if ctx.atm_iv > getattr(ctx, '_hist_vol', ctx.atm_iv) * 1.2 else 'IV偏低适合买方' if ctx.atm_iv < getattr(ctx, '_hist_vol', ctx.atm_iv) * 0.8 else 'IV合理'}）" if getattr(ctx, '_hist_vol', 0) > 0 else ''}
- ATM Theta损耗：≈{ctx.atm_theta_per_day:.1f}元/张/天{'（持有成本高，不宜长持买方）' if ctx.atm_theta_per_day > 50 else ''}
- 认购均IV：{ctx.avg_iv_call*100:.1f}% | 认沽均IV：{ctx.avg_iv_put*100:.1f}%
- IV Skew（沽-购）：{ctx.iv_skew*100:+.1f}% {'（认沽贵=看跌情绪）' if ctx.iv_skew > 0.02 else '（认购贵=看涨情绪）' if ctx.iv_skew < -0.02 else '（正常）'}
- PCR持仓量：{ctx.pcr_oi:.2f} {'（>1.0看空情绪重）' if ctx.pcr_oi > 1.0 else '（<0.6看多过热）' if ctx.pcr_oi < 0.6 else '（正常）'}
- PCR成交量：{ctx.pcr_vol:.2f}
- 总持仓：认购{ctx.total_call_oi}张 / 认沽{ctx.total_put_oi}张
- Max Pain：{ctx.max_pain:.3f}{'（现价高于MP，有回落压力）' if ctx.spot > ctx.max_pain * 1.01 else '（现价低于MP，有回升动力）' if ctx.spot < ctx.max_pain * 0.99 else '（接近）'}"""

    # 远月信息
    if ctx.far_expiry and ctx.far_month_summary:
        far_lines = []
        for c in ctx.far_month_summary[:10]:
            far_lines.append(f"  {c['type']:4s} K={c['strike']:.3f} 价={c['price']:.4f} IV={c['iv']*100:.1f}%")
        msg += f"""

### 远月（{ctx.far_expiry}到期，剩余{ctx.far_expiry_days}天）
{chr(10).join(far_lines)}"""

    msg += f"""

## 近月合约链（{ctx.near_expiry}到期，ATM附近±5档）
{chain_text}

## 投资约束
- 可投入资金：{params.capital:.0f} 元
- 最大可承受亏损：{params.max_loss:.0f} 元
- 预期持仓：{params.holding_days} 天
- 风格偏好：{params.style}
- 持有现货：{params.etf_shares} 份（≈{params.etf_shares // 10000}张）{'，可备兑' if params.etf_shares >= 10000 else ''}
- 方向预判：{params.direction}{'（请尊重用户方向判断）' if params.direction != 'AI判断' else '（请根据数据自行判断方向）'}
- 目标价位：{params.target_price if params.target_price else '未指定，AI自行判断'}
- 到期月偏好：{params.expiry_pref}
- 裸卖权限：{'允许（可推荐卖出认购/认沽）' if params.allow_naked_sell else '不允许（只能买方或价差/备兑等有保护的卖方策略）'}

请综合以上数据分析，推荐最适合当前市场状况的策略。如果近月时间价值损耗过快（剩余<7天），优先考虑远月。"""
    return msg


# ---------- 响应解析 ----------

def parse_ai_response(
    response: dict[str, Any],
    chain: list[dict],
    spot: float,
) -> dict[str, Any]:
    """解析 AI 返回的策略推荐，匹配到实际合约.

    返回格式与 _on_strategy_requested 的 legs 输入兼容。
    """
    if "error" in response:
        return {"error": response["error"]}

    legs_raw = response.get("legs", [])
    if not legs_raw:
        return {"error": "AI 未返回有效策略腿"}

    # 按 expire_date 过滤合约
    from watcher.strategy.presets import _norm_expiry
    expire = _norm_expiry(response.get("expire_date", ""))

    # 匹配每条腿到实际合约
    matched_legs = []
    for leg in legs_raw:
        opt_type = leg.get("option_type", "")
        strike = float(leg.get("strike", 0))
        side = leg.get("side", "buy")
        qty = max(1, int(leg.get("qty", 1)))

        # 在 chain 中找匹配的合约
        best = _find_contract(chain, opt_type, strike, expire)
        if best is None:
            # 容错：找最接近的行权价
            best = _find_nearest_contract(chain, opt_type, strike, expire)
        if best is None:
            continue

        matched_legs.append({
            "code": best["code"],
            "side": side,
            "qty": qty,
            "price": best.get("price") or 0,
        })

    if not matched_legs:
        return {"error": "AI 推荐的合约在当前链中未找到匹配"}

    return {
        "legs": matched_legs,
        "strategy_name": response.get("strategy_name", "AI推荐"),
        "reasoning": response.get("reasoning", ""),
        "risk_summary": response.get("risk_summary", {}),
        "notes": response.get("notes", ""),
        "thinking": response.get("_thinking", ""),
    }


def _find_contract(
    chain: list[dict], opt_type: str, strike: float, expire: str
) -> dict | None:
    """精确匹配合约."""
    from watcher.strategy.presets import _norm_expiry
    for c in chain:
        if (c.get("option_type") == opt_type
                and abs(float(c.get("strike", 0)) - strike) < 0.001
                and (not expire or _norm_expiry(c.get("expire_date")) == expire)
                and (c.get("price") or 0) > 0):
            return c
    return None


def _find_nearest_contract(
    chain: list[dict], opt_type: str, strike: float, expire: str
) -> dict | None:
    """找最接近行权价的合约（容错）."""
    from watcher.strategy.presets import _norm_expiry
    candidates = [
        c for c in chain
        if c.get("option_type") == opt_type
        and (not expire or _norm_expiry(c.get("expire_date")) == expire)
        and (c.get("price") or 0) > 0
    ]
    if not candidates:
        # 放宽到期月限制
        candidates = [
            c for c in chain
            if c.get("option_type") == opt_type and (c.get("price") or 0) > 0
        ]
    if not candidates:
        return None
    return min(candidates, key=lambda c: abs(float(c.get("strike", 0)) - strike))


# ---------- 主入口 ----------

def recommend_strategy(
    cfg: Config,
    underlying_code: str,
    underlying_name: str,
    chain: list[dict],
    spot: float,
    bars_1min: list | None,
    params: UserParams,
    daily_bars: list | None = None,
) -> dict[str, Any]:
    """完整流程：收集数据 → 组 prompt → 调 AI → 解析返回."""
    if not cfg.deepseek.enabled:
        return {"error": "AI 策略推荐未启用，请在设置中开启"}

    from watcher.ai.client import is_available
    if not is_available():
        return {"error": "未配置 DEEPSEEK_API_KEY"}

    # 收集市场数据
    ctx = collect_market_context(
        underlying_code, underlying_name, chain, spot, bars_1min, cfg, daily_bars
    )

    # 组装消息
    user_msg = build_user_message(ctx, params)
    logger.info("AI strategy prompt length: %d chars", len(user_msg))

    # 调用 AI
    client = DeepSeekClient(cfg.deepseek)
    response = client.chat(SYSTEM_PROMPT, user_msg)

    # 解析并匹配合约
    return parse_ai_response(response, chain, spot)
