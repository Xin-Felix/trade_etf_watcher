"""信号规则."""
from __future__ import annotations

from watcher.config import Config
from watcher.models import MinuteBar, Quote, Signal


def detect_gap(quote: Quote, cfg: Config) -> Signal | None:
    thr = cfg.threshold_for(quote.code, "gap")
    gap = quote.gap_pct
    if gap >= thr:
        return Signal(
            key="gap_up",
            code=quote.code,
            name=quote.name,
            label="跳空高开",
            detail=f"今开 {quote.open:.3f}，较昨收 {quote.prev_close:.3f} 高开 {gap*100:.2f}%",
            level="warning",
            ts=quote.ts,
        )
    if gap <= -thr:
        return Signal(
            key="gap_down",
            code=quote.code,
            name=quote.name,
            label="跳空低开",
            detail=f"今开 {quote.open:.3f}，较昨收 {quote.prev_close:.3f} 低开 {abs(gap)*100:.2f}%",
            level="warning",
            ts=quote.ts,
        )
    return None


def detect_surge_plunge(quote: Quote, cfg: Config) -> Signal | None:
    surge_thr = cfg.threshold_for(quote.code, "surge")
    plunge_thr = cfg.threshold_for(quote.code, "plunge")
    chg = quote.change_pct
    if chg >= surge_thr:
        level = "critical" if chg >= surge_thr * 2 else "warning"
        return Signal(
            key="surge",
            code=quote.code,
            name=quote.name,
            label="急涨",
            detail=f"最新价 {quote.price:.3f}，较昨收上涨 {chg*100:.2f}%",
            level=level,  # type: ignore[arg-type]
            ts=quote.ts,
        )
    if chg <= -plunge_thr:
        level = "critical" if chg <= -plunge_thr * 2 else "warning"
        return Signal(
            key="plunge",
            code=quote.code,
            name=quote.name,
            label="急跌",
            detail=f"最新价 {quote.price:.3f}，较昨收下跌 {abs(chg)*100:.2f}%",
            level=level,  # type: ignore[arg-type]
            ts=quote.ts,
        )
    return None


def detect_rebound(quote: Quote, cfg: Config) -> Signal | None:
    start = cfg.threshold_for(quote.code, "rebound_start")
    bounce = cfg.threshold_for(quote.code, "rebound_bounce")
    if quote.prev_close == 0 or quote.low == 0:
        return None
    # 曾跌破昨收 -start，且自低点反弹 >= bounce，且最新价站上今开
    if (
        quote.low <= quote.prev_close * (1 - start)
        and quote.price >= quote.low * (1 + bounce)
        and quote.price > quote.open
    ):
        return Signal(
            key="rebound",
            code=quote.code,
            name=quote.name,
            label="探底回升",
            detail=(
                f"盘中最低 {quote.low:.3f}（{(quote.low/quote.prev_close-1)*100:.2f}%），"
                f"已自低点反弹 {(quote.price/quote.low-1)*100:.2f}% 至 {quote.price:.3f}"
            ),
            level="warning",
            ts=quote.ts,
        )
    return None


def detect_reversal(quote: Quote, cfg: Config) -> Signal | None:
    start = cfg.threshold_for(quote.code, "reversal_start")
    pullback = cfg.threshold_for(quote.code, "reversal_pullback")
    if quote.prev_close == 0 or quote.high == 0:
        return None
    if (
        quote.high >= quote.prev_close * (1 + start)
        and quote.price <= quote.high * (1 - pullback)
        and quote.price < quote.open
    ):
        return Signal(
            key="reversal",
            code=quote.code,
            name=quote.name,
            label="冲高回落",
            detail=(
                f"盘中最高 {quote.high:.3f}（{(quote.high/quote.prev_close-1)*100:.2f}%），"
                f"已自高点回落 {(1-quote.price/quote.high)*100:.2f}% 至 {quote.price:.3f}"
            ),
            level="warning",
            ts=quote.ts,
        )
    return None


def detect_minute_signal(bar: MinuteBar, cfg: Config, name: str) -> Signal | None:
    if bar.open == 0:
        return None
    chg = bar.close / bar.open - 1
    surge_thr = cfg.threshold_for(bar.code, "minute_surge")
    plunge_thr = cfg.threshold_for(bar.code, "minute_plunge")
    if chg >= surge_thr:
        return Signal(
            key="minute_surge",
            code=bar.code,
            name=name,
            label="分时急涨",
            detail=f"{bar.ts[8:12]} 这根分时 K 上涨 {chg*100:.2f}%（开 {bar.open:.3f} 收 {bar.close:.3f}）",
            level="warning",
            ts=bar.ts,
        )
    if chg <= -plunge_thr:
        return Signal(
            key="minute_plunge",
            code=bar.code,
            name=name,
            label="分时急跌",
            detail=f"{bar.ts[8:12]} 这根分时 K 下跌 {abs(chg)*100:.2f}%（开 {bar.open:.3f} 收 {bar.close:.3f}）",
            level="warning",
            ts=bar.ts,
        )
    return None


# ===== 期权信号 =====


def detect_iv_surge(
    option_quotes: list[dict], underlying_code: str, underlying_name: str, cfg: Config
) -> list[Signal]:
    """检测 IV 飙升：ATM 附近合约 IV 超过阈值时触发.

    对同一标的只取最高 IV 合约发一个信号（避免同一标的几十个合约全报）。
    """
    iv_thr = cfg.threshold_for(underlying_code, "iv_surge")
    if iv_thr <= 0:
        return []

    max_iv = 0.0
    max_contract: dict | None = None
    for q in option_quotes:
        iv = q.get("iv") or 0.0
        if iv > max_iv:
            max_iv = iv
            max_contract = q

    if max_iv < iv_thr or max_contract is None:
        return []

    name = max_contract.get("option_name") or max_contract.get("name") or ""
    option_code = max_contract.get("option_code", "")
    return [
        Signal(
            key="iv_surge",
            code=underlying_code,
            name=underlying_name,
            label="IV 飙升",
            detail=(
                f"{name}({option_code}) IV={max_iv*100:.1f}%，"
                f"超过阈值 {iv_thr*100:.0f}%"
            ),
            level="warning",
            ts=max_contract.get("ts", ""),
        )
    ]


def detect_pcr_anomaly(
    option_quotes: list[dict], underlying_code: str, underlying_name: str, cfg: Config
) -> list[Signal]:
    """检测 PCR 异常：认沽/认购持仓量比超出阈值时触发.

    PCR > pcr_high → 极度看空（大量认沽持仓）
    PCR < pcr_low  → 极度看多（大量认购持仓）
    """
    pcr_high = cfg.threshold_for(underlying_code, "pcr_high")
    pcr_low = cfg.threshold_for(underlying_code, "pcr_low")
    if pcr_high <= 0 and pcr_low <= 0:
        return []

    put_oi = 0
    call_oi = 0
    for q in option_quotes:
        oi = q.get("open_interest") or 0
        otype = q.get("option_type", "")
        if otype == "put":
            put_oi += oi
        elif otype == "call":
            call_oi += oi

    if call_oi == 0:
        return []

    pcr = put_oi / call_oi
    signals: list[Signal] = []

    if pcr_high > 0 and pcr >= pcr_high:
        signals.append(
            Signal(
                key="pcr_high",
                code=underlying_code,
                name=underlying_name,
                label="PCR 偏高",
                detail=f"认沽/认购持仓比 PCR={pcr:.2f}（PUT {put_oi:,} / CALL {call_oi:,}），超过 {pcr_high:.1f}",
                level="warning",
                ts="",
            )
        )
    elif pcr_low > 0 and pcr <= pcr_low:
        signals.append(
            Signal(
                key="pcr_low",
                code=underlying_code,
                name=underlying_name,
                label="PCR 偏低",
                detail=f"认沽/认购持仓比 PCR={pcr:.2f}（PUT {put_oi:,} / CALL {call_oi:,}），低于 {pcr_low:.1f}",
                level="warning",
                ts="",
            )
        )

    return signals


# ===== 三件套共振开仓信号（方向 + 触发 + 量确认） =====
#
# 方向：VWAP（日内分时均线）定多空 —— 价格在 VWAP 上方只做多，下方只做空
# 触发：5分 MA5/MA10 金叉死叉 | 5分 MACD 金叉死叉 | 连续3同向K线 | 关键位突破（昨高低/ORB）
# 确认：成交量 > 均量 × 倍数
# 过滤：RSI > 75 不做多、RSI < 25 不做空（极值保护）
#
# 三者齐备才出信号；买卖配对，日内不隔夜。


def _ema(data: list[float], n: int) -> list[float]:
    """指数移动平均."""
    if not data:
        return []
    k = 2.0 / (n + 1)
    out = [data[0]]
    for i in range(1, len(data)):
        out.append(data[i] * k + out[-1] * (1 - k))
    return out


def _sma(data: list[float], n: int) -> list[float | None]:
    """简单移动平均."""
    out: list[float | None] = [None] * (n - 1)
    for i in range(n - 1, len(data)):
        out.append(sum(data[i - n + 1: i + 1]) / n)
    return out


def _rsi(closes: list[float], period: int = 14) -> list[float | None]:
    """计算 RSI 序列."""
    if len(closes) < period + 1:
        return [None] * len(closes)
    result: list[float | None] = [None] * period
    gains = []
    losses = []
    for i in range(1, period + 1):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        result.append(100.0)
    else:
        result.append(100.0 - 100.0 / (1 + avg_gain / avg_loss))
    for i in range(period + 1, len(closes)):
        diff = closes[i] - closes[i - 1]
        avg_gain = (avg_gain * (period - 1) + max(diff, 0)) / period
        avg_loss = (avg_loss * (period - 1) + max(-diff, 0)) / period
        if avg_loss == 0:
            result.append(100.0)
        else:
            result.append(100.0 - 100.0 / (1 + avg_gain / avg_loss))
    return result


def _macd(closes: list[float]) -> tuple[list[float], list[float], list[float]]:
    """MACD(12,26,9) 返回 (dif, dea, macd_bar)."""
    ema12 = _ema(closes, 12)
    ema26 = _ema(closes, 26)
    dif = [ema12[i] - ema26[i] for i in range(len(closes))]
    dea = _ema(dif, 9)
    bar = [(dif[i] - dea[i]) * 2 for i in range(len(closes))]
    return dif, dea, bar


def _vwap(bars: list[MinuteBar]) -> float | None:
    """计算日内 VWAP（成交量加权平均价）."""
    total_pv = 0.0
    total_vol = 0
    for b in bars:
        typical = (b.high + b.low + b.close) / 3
        total_pv += typical * b.volume
        total_vol += b.volume
    if total_vol == 0:
        return None
    return total_pv / total_vol


# ---------- 方向判断 ----------

def direction_vwap(bars: list[MinuteBar]) -> str | None:
    """VWAP 方向：价格在 VWAP 上方 → 'long'，下方 → 'short'，贴线 → None."""
    vwap = _vwap(bars)
    if vwap is None or vwap <= 0:
        return None
    price = bars[-1].close
    margin = vwap * 0.001  # 0.1% 容差（贴线不做）
    if price > vwap + margin:
        return "long"
    elif price < vwap - margin:
        return "short"
    return None


# ---------- 触发条件（任一满足即可） ----------

def trigger_macd_cross(bars: list[MinuteBar]) -> str | None:
    """MACD DIF/DEA 金叉=long, 死叉=short."""
    if len(bars) < 30:
        return None
    closes = [b.close for b in bars]
    dif, dea, _ = _macd(closes)
    if len(dif) < 2:
        return None
    if dif[-2] <= dea[-2] and dif[-1] > dea[-1]:
        return "long"
    if dif[-2] >= dea[-2] and dif[-1] < dea[-1]:
        return "short"
    return None


# ---------- 买卖点主函数 ----------

def detect_resonance(
    bars: list[MinuteBar],
    code: str,
    name: str,
    cfg: Config,
    prev_high: float | None = None,
    prev_low: float | None = None,
    toggles=None,
) -> Signal | None:
    """买卖点检测：量价形态（滑动窗口序列判定，见 signals/patterns.py）.

    MACD/MA 金叉这类滞后指标已移除——实测在 ETF 日内会大量来回打脸，
    且常把主升浪砍在半路，改为纯量价形态判定。

    prev_high / prev_low 为历史兼容参数，当前实现不使用。
    返回 Signal（做多=买认购，做空=买认沽），或 None.
    """
    from watcher.signals.patterns import trigger_volume_pattern

    if len(bars) < 30:
        return None
    if toggles is None:
        from watcher.config import SignalToggleConfig
        toggles = SignalToggleConfig()

    if not getattr(toggles, "volume_pattern", True):
        return None

    final_dir, hits = trigger_volume_pattern(bars)
    if not final_dir:
        return None

    detail = "+".join(hits[:3]) if hits else "量价形态"

    if final_dir == "long":
        return Signal(
            key="resonance_long",
            code=code,
            name=name,
            label="买认购",
            detail=f"{detail}，买认购",
            level="warning",
            ts=bars[-1].ts,
        )
    else:
        return Signal(
            key="resonance_short",
            code=code,
            name=name,
            label="买认沽",
            detail=f"{detail}，买认沽",
            level="warning",
            ts=bars[-1].ts,
        )

