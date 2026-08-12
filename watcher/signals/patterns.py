"""量价形态识别：滑动窗口序列形态 → 买卖点打分.

单指标（MACD/MA 金叉）是「点」判断且滞后；本模块把最近 N 根 K 线翻译成
「量价形态标签」序列（放量大涨 / 巨量滞涨 / 平量横盘 ...），再用**形态组合**
打分判买卖，典型场景比 MACD 金叉早 3-5 根 bar。

三层结构：
  1. compute_features  单根 K 线 → 无量纲特征（量比/实体/影线/跳空/振幅）
  2. _label            特征 → 形态标签（人可读，进 signal detail 方便回看）
  3. detect_patterns   窗口序列 → 命中形态 + 加权得分 + 方向

阈值策略：涨跌幅阈值**自适应**（取窗口内 abs(chg) 分位数），因为不同 ETF、
不同周期的波动量级差一个数量级，固定阈值必然一边过松一边过严。
量比本身已是相对值，用固定门槛。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from watcher.models import MinuteBar

# 涨跌幅阈值兜底值（样本不足时用；1 分钟基准，按 sqrt(周期) 放大）
BASE_BIG_MOVE = 0.0030
BASE_SMALL_MOVE = 0.0010
BASE_GAP = 0.0020

# 量比门槛（实测 ETF 1 分钟 vr 的 p95 约 1.8，故巨量取 2.5 而非 3）
VOL_SPIKE = 2.5    # 巨量（换手/洗盘）
VOL_HIGH = 1.6     # 放量
VOL_QUIET = 1.4    # 蓄势期的量比上限
VOL_LOW = 1.0      # 缩量

MIN_BARS = 10      # 形态识别最少需要的 bar 数
# 权重 3 = 可单独触发的主形态；权重 2 = 辅助形态，需与其他形态共振才够线
BUY_THRESHOLD = 3
SELL_THRESHOLD = -3

# 见顶形态一票否决买信号（有量拉不动 / 冲高被砸时不追）
VETO_PATTERNS = {"放量滞涨见顶", "巨量见顶", "高位长上影", "量价背离"}


def _scale(period_min: int) -> float:
    return max(1.0, float(period_min) ** 0.5)


def _ts_minutes(ts: str) -> int | None:
    """'202607281429' / '20260728142900' → 日内分钟数."""
    if len(ts) < 12 or not ts[:12].isdigit():
        return None
    return int(ts[8:10]) * 60 + int(ts[10:12])


def infer_period_min(bars: list[MinuteBar]) -> int:
    """从相邻 bar 时间戳推断周期分钟数（取众数），失败退回 1."""
    if len(bars) < 3:
        return 1
    diffs: dict[int, int] = {}
    for a, b in zip(bars, bars[1:]):
        ta, tb = _ts_minutes(a.ts), _ts_minutes(b.ts)
        if ta is None or tb is None:
            continue
        d = tb - ta
        if 0 < d <= 240:          # 过滤跨日/午休造成的异常间隔
            diffs[d] = diffs.get(d, 0) + 1
    if not diffs:
        return 1
    return max(diffs, key=lambda k: diffs[k])


# ---------- 第一层：单根 K 线特征 ----------

@dataclass(slots=True)
class BarFeature:
    """单根 K 线的无量纲特征（跨标的、跨周期可比）."""
    vr: float = 1.0      # 量比：当前量 / 前 5 根均量
    chg: float = 0.0     # 实体涨跌幅 (close-open)/open
    net: float = 0.0     # 相对前收涨跌幅
    body: float = 0.0    # 实体占振幅比（1=光头光脚，0=十字星）
    upper: float = 0.0   # 上影占振幅比（抛压）
    lower: float = 0.0   # 下影占振幅比（承接）
    gap: float = 0.0     # 跳空幅度 (open-prev_close)/prev_close
    amp: float = 0.0     # 振幅 (high-low)/prev_close
    label: str = ""      # 形态标签


@dataclass(slots=True)
class Thresholds:
    """当前窗口的自适应阈值."""
    big: float
    small: float
    gap: float


def make_thresholds(feats: list[BarFeature], period_min: int) -> Thresholds:
    """自适应阈值：big 取窗口 abs(chg) 的 p75，small 取 p30."""
    scale = _scale(period_min)
    moves = sorted(abs(f.chg) for f in feats)
    if len(moves) >= 20:
        n = len(moves)
        return Thresholds(
            big=max(moves[int(n * 0.75)], 1e-5),
            small=max(moves[int(n * 0.30)], 1e-6),
            gap=BASE_GAP * scale,
        )
    return Thresholds(BASE_BIG_MOVE * scale, BASE_SMALL_MOVE * scale, BASE_GAP * scale)


def compute_features(bars: list[MinuteBar], period_min: int | None = None) -> list[BarFeature]:
    """逐根计算特征并打标签（标签用自适应阈值，两趟：先算特征再定阈值）."""
    if period_min is None:
        period_min = infer_period_min(bars)

    out: list[BarFeature] = []
    for i, b in enumerate(bars):
        prev = bars[i - 1] if i > 0 else None
        rng = b.high - b.low
        upper_wick = b.high - max(b.open, b.close)
        lower_wick = min(b.open, b.close) - b.low
        prev_vols = [x.volume for x in bars[max(0, i - 5):i] if x.volume > 0]
        avg_vol = (sum(prev_vols) / len(prev_vols)) if prev_vols else 0.0
        pc = prev.close if (prev and prev.close > 0) else 0.0

        out.append(BarFeature(
            vr=(b.volume / avg_vol) if avg_vol > 0 else 1.0,
            chg=((b.close - b.open) / b.open) if b.open > 0 else 0.0,
            net=((b.close - pc) / pc) if pc else 0.0,
            body=(abs(b.close - b.open) / rng) if rng > 0 else 0.0,
            upper=(upper_wick / rng) if rng > 0 else 0.0,
            lower=(lower_wick / rng) if rng > 0 else 0.0,
            gap=((b.open - pc) / pc) if pc else 0.0,
            amp=(rng / pc) if pc else ((rng / b.open) if b.open > 0 else 0.0),
        ))

    th = make_thresholds(out, period_min)
    for f in out:
        f.label = _label(f, th)
    return out


# ---------- 第二层：单根形态标签 ----------

def _label(f: BarFeature, th: Thresholds) -> str:
    """量维度 × 价维度 → 人可读标签（滞涨/长上影优先，是关键抛压特征）."""
    if f.vr >= VOL_SPIKE:
        vol = "巨量"
    elif f.vr >= VOL_HIGH:
        vol = "放量"
    elif f.vr >= 0.7:
        vol = "平量"
    else:
        vol = "缩量"

    # 有量但拉不动 = 抛压重，比单纯看涨跌重要，优先判定
    if f.vr >= VOL_HIGH and abs(f.chg) < th.small:
        return f"{vol}滞涨"
    if f.vr >= VOL_HIGH and f.chg > 0 and f.upper >= 0.5:
        return f"{vol}长上影"

    if f.chg > th.big:
        price = "大涨"
    elif f.chg > th.small:
        price = "小涨"
    elif f.chg < -th.big:
        price = "大跌"
    elif f.chg < -th.small:
        price = "小跌"
    else:
        price = "横盘"
    return f"{vol}{price}"


# ---------- 位置辅助（区分底部形态与顶部形态） ----------

def _pos_in_range(bars: list[MinuteBar], n: int = 20) -> float:
    """当前收盘在最近 n 根区间中的相对位置（0=最低，1=最高）."""
    win = bars[-n:]
    hi = max(b.high for b in win)
    lo = min(b.low for b in win)
    return ((bars[-1].close - lo) / (hi - lo)) if hi > lo else 0.5


def _run_up(bars: list[MinuteBar], n: int = 20) -> float:
    """相对 n 根前的累计涨幅（判断是否已经涨上来了）."""
    ref = bars[-min(n, len(bars))].close
    return ((bars[-1].close - ref) / ref) if ref > 0 else 0.0


# ---------- 第三层：窗口序列形态（看多） ----------

def _p_spike_follow(bars, feats, th) -> bool:
    """量爆跟随：前 1-4 根出现巨量（换手/洗盘）→ 当前根突破该巨量根高点.

    量先于价：巨量那根往往是十字星/小实体，真正的拉升在随后 1-3 根。
    本模块最具领先性的形态，对应「成交量突然拉升，紧接着价格开始上拉」。
    注意突破根本身不要求放量——量已经在巨量根释放过了。
    """
    if len(feats) < 5:
        return False
    if feats[-1].chg <= th.small:                  # 突破根本身要是根实质阳线
        return False
    for j in range(-5, -1):                        # 前 1-4 根里找巨量根
        if feats[j].vr < VOL_SPIKE:
            continue
        spike = bars[j]
        if bars[-1].close <= spike.high:           # 必须突破巨量根高点
            continue
        if bars[-2].close > spike.high:            # 前一根已站上=不是首次突破
            continue
        if min(b.low for b in bars[j:]) < spike.low:   # 期间破巨量根低点=出货
            continue
        return True
    return False


def _p_bottom_reversal(bars, feats, th) -> bool:
    """探底回升：最近 2-4 根内创过阶段新低 → 当前根实体阳线突破探底根高点.

    底部反转常常是**缩量**拉起的（抛压枯竭，而非资金涌入），所以本形态不要求
    放量，否则「温和量探底 + 缩量反弹」这类底部完全抓不到。
    用「创阶段新低 + 突破探底根高点 + 收盘仍在区间下半部」三重约束控制误报。
    """
    if len(bars) < 22:
        return False
    cur = feats[-1]
    if not (cur.chg > th.big * 0.5 and cur.body >= 0.5):
        return False
    if _pos_in_range(bars, 20) > 0.5:          # 只在区间下半部找底
        return False
    n = len(bars)
    for j in range(-5, -1):                    # 前 1-4 根里找探底根
        abs_i = n + j
        ref = bars[max(0, abs_i - 20):abs_i]
        if len(ref) < 10:
            continue
        low_bar = bars[j]
        if low_bar.low >= min(b.low for b in ref):      # 必须**严格**创阶段新低
            continue
        # 探底区间要有承接量，纯无量漂移不算底
        if max(f.vr for f in feats[j:]) < 1.5:
            continue
        # 突破要有幅度（避免平价并列造成的噪声）
        if bars[-1].close <= low_bar.high * (1 + th.small * 0.5):
            continue
        # 自探底以来还没有任何一根收盘站上过 → 本根是首次突破
        if max(b.close for b in bars[j:-1]) > low_bar.high:
            continue
        return True
    return False


def _p_ignition(bars, feats, th) -> bool:
    """量堆积启动：前 3 根平/缩量窄幅蓄势 → 当前根放量大涨且创窗口新高."""
    if len(feats) < 5:
        return False
    cur = feats[-1]
    if not (cur.vr >= VOL_HIGH + 0.2 and cur.chg > th.big and cur.body >= 0.5):
        return False
    if not all(p.vr < VOL_QUIET and abs(p.chg) < th.big for p in feats[-4:-1]):
        return False
    return bars[-1].close >= max(b.close for b in bars[-6:])


def _p_squeeze_breakout(bars, feats, th) -> bool:
    """挤压突破：窗口振幅极度收缩（蓄势）→ 当前根放量突破前 5 根高点."""
    if len(bars) < 15:
        return False
    recent = [f.amp for f in feats[-6:-1]]
    base = [f.amp for f in feats[-15:-6]]
    if not recent or not base:
        return False
    r, b0 = sum(recent) / len(recent), sum(base) / len(base)
    if b0 <= 0 or r > b0 * 0.7:          # 振幅未收缩到基准的 70% 以下
        return False
    cur = feats[-1]
    return (cur.vr >= VOL_HIGH and cur.chg > 0
            and bars[-1].close > max(x.high for x in bars[-6:-1]))


def _p_pullback_engulf(bars, feats, th) -> bool:
    """缩量回调反包：连续 2 根缩量回调 → 当前根放量阳线吞没前一根实体."""
    if len(feats) < 5:
        return False
    cur = feats[-1]
    if not (cur.vr >= VOL_HIGH and cur.chg > th.small):
        return False
    if not all(p.vr < VOL_LOW and p.chg < 0 for p in feats[-3:-1]):
        return False
    return bars[-1].close > max(bars[-2].open, bars[-2].close)


def _p_shakeout(bars, feats, th) -> bool:
    """洗盘拉回：放量下跌 → 缩量止跌 → 当前根放量收复失地."""
    if len(feats) < 5:
        return False
    cur = feats[-1]
    if not (cur.vr >= VOL_HIGH and cur.chg > th.big * 0.6):
        return False
    idx = None
    for j in range(-5, -2):              # 找最近的放量下跌根（留出止跌空间）
        if feats[j].vr >= VOL_HIGH and feats[j].chg < -th.big * 0.6:
            idx = j
    if idx is None:
        return False
    between = feats[idx + 1:-1]
    if not between or not all(f.vr < 1.3 for f in between):
        return False
    return bars[-1].close > bars[idx].open


def _p_gap_hold(bars, feats, th) -> bool:
    """跳空不回补：向上跳空后低点未跌回缺口 + 当前根放量走高."""
    if len(bars) < 4:
        return False
    cur = feats[-1]
    if not (cur.vr >= VOL_HIGH and cur.chg > 0):
        return False
    for j in (-1, -2):
        if feats[j].gap <= th.gap:
            continue
        base = bars[j - 1].close
        if base > 0 and all(b.low >= base for b in bars[j:]):
            return True
    return False


# ---------- 第三层：窗口序列形态（看空 / 抑制） ----------
# 顶部形态额外要求「价格已在区间上沿且有累计涨幅」，否则底部的巨量换手
# 会被误判成见顶（13:01 那种巨量十字星其实是启动点，不是顶）。

def _p_stall_top(bars, feats, th) -> bool:
    """放量滞涨见顶：高位连续 2 根放量但价格没涨 → 上方抛压重."""
    if len(feats) < 4:
        return False
    if not all(f.vr >= VOL_HIGH for f in feats[-2:]):
        return False
    if _pos_in_range(bars) < 0.65 or _run_up(bars) <= th.big:
        return False
    base = bars[-3].close
    return base > 0 and ((bars[-1].close - base) / base) < th.small


def _p_blowoff_top(bars, feats, th) -> bool:
    """巨量见顶：高位连涨 3 根后出现巨量长上影 → 冲高被砸."""
    if len(feats) < 5:
        return False
    cur = feats[-1]
    if not (cur.vr >= VOL_SPIKE and cur.upper >= 0.45):
        return False
    if _pos_in_range(bars) < 0.7:
        return False
    return all(f.chg > 0 for f in feats[-4:-1])


def _p_divergence(bars, feats, th) -> bool:
    """量价背离：高位创新高但量明显小于窗口内前高的量."""
    if len(feats) < 10:
        return False
    if bars[-1].close < max(b.close for b in bars[-10:]):
        return False
    if _pos_in_range(bars) < 0.7 or _run_up(bars) <= th.big:
        return False
    max_vr = max(f.vr for f in feats[-10:-1])
    return feats[-1].chg > 0 and feats[-1].vr < max_vr * 0.6


def _p_breakdown(bars, feats, th) -> bool:
    """放量破位：低位区当前根放量大跌且创窗口新低."""
    if len(bars) < 8:
        return False
    cur = feats[-1]
    if not (cur.vr >= VOL_HIGH and cur.chg < -th.big):
        return False
    if _pos_in_range(bars) > 0.35:
        return False
    return bars[-1].close < min(b.low for b in bars[-8:-1])


def _p_upper_wick_top(bars, feats, th) -> bool:
    """高位长上影：涨上来之后出现放量长上影 → 上方有人在砸（常见顶部信号）."""
    if len(feats) < 5:
        return False
    cur = feats[-1]
    if not (cur.vr >= VOL_HIGH and cur.upper >= 0.5):
        return False
    if feats[-2].upper >= 0.5:              # 前一根已是长上影 → 不重复报
        return False
    return _pos_in_range(bars) >= 0.65 and _run_up(bars) > th.big


def _p_trend_break(bars, feats, th) -> bool:
    """高位破位：已有累计涨幅后，收阴且跌破前 5 根最低价 → 上涨结构走坏.

    实测顶部经常是「平量滞涨」做出来的（涨不动而非被砸），所以本形态
    **不要求放量**，否则无量下跌的顶部完全抓不到。
    """
    if len(bars) < 8:
        return False
    cur = feats[-1]
    if cur.chg >= -th.big:                  # 必须是根实质阴线
        return False
    if _pos_in_range(bars) < 0.45 or _run_up(bars) <= th.big:
        return False
    return bars[-1].close < min(b.low for b in bars[-6:-1])


def _p_reversal_bar(bars, feats, th) -> bool:
    """冲高回落：前一根创窗口新高 → 当前根放量阴线吃掉前一根一半以上实体."""
    if len(bars) < 8:
        return False
    cur = feats[-1]
    if not (cur.vr >= VOL_HIGH and cur.chg < -th.small):
        return False
    if _pos_in_range(bars) < 0.6:
        return False
    prev = bars[-2]
    if prev.high < max(b.high for b in bars[-8:-1]):    # 前一根不是窗口高点
        return False
    mid = (prev.open + prev.close) / 2
    return bars[-1].close < mid


def _p_gap_fill(bars, feats, th) -> bool:
    """跳空回补：向上跳空后被放量打回缺口内 → 假突破."""
    if len(bars) < 3 or feats[-1].vr < VOL_HIGH:
        return False
    for j in (-1, -2):
        if feats[j].gap <= th.gap:
            continue
        base = bars[j - 1].close
        if base > 0 and bars[-1].close < base:
            return True
    return False


# ---------- 打分与汇总 ----------

# (形态名, 权重, 检测函数)；正权重看多，负权重看空
_PATTERNS = [
    ("量爆跟随", 3, _p_spike_follow),
    ("量堆积启动", 3, _p_ignition),
    # 以下为**辅助**形态（权重 2 < BUY_THRESHOLD）：单独命中不足以触发，
    # 必须与其他形态共振。5 天回测显示它们单独触发时是净亏损的
    # （探底回升 99 笔 -0.026%/笔、挤压突破 29 笔 -0.200%/笔）。
    ("探底回升", 2, _p_bottom_reversal),
    ("挤压突破", 2, _p_squeeze_breakout),
    ("缩量回调反包", 2, _p_pullback_engulf),
    ("洗盘拉回", 2, _p_shakeout),
    ("跳空不回补", 2, _p_gap_hold),
    ("放量滞涨见顶", -3, _p_stall_top),
    ("巨量见顶", -3, _p_blowoff_top),
    ("高位长上影", -3, _p_upper_wick_top),
    ("冲高回落", -3, _p_reversal_bar),
    ("高位破位", -3, _p_trend_break),
    ("放量破位", -3, _p_breakdown),
    ("量价背离", -2, _p_divergence),
    ("跳空回补", -2, _p_gap_fill),
]


@dataclass(slots=True)
class PatternResult:
    score: int = 0
    hits: list[str] = field(default_factory=list)
    direction: str | None = None      # 'long' / 'short' / None
    bar_label: str = ""               # 当前根的单根标签


def detect_patterns(bars: list[MinuteBar], period_min: int | None = None) -> PatternResult:
    """对窗口末尾那根 bar 做形态判定（bars 传完整窗口，判定对象是 bars[-1]）."""
    res = PatternResult()
    if len(bars) < MIN_BARS:
        return res
    if period_min is None:
        period_min = infer_period_min(bars)

    feats = compute_features(bars, period_min)
    th = make_thresholds(feats, period_min)
    res.bar_label = feats[-1].label

    for name, weight, fn in _PATTERNS:
        try:
            if fn(bars, feats, th):
                res.score += weight
                res.hits.append(name)
        except (IndexError, ZeroDivisionError):
            continue

    veto = VETO_PATTERNS & set(res.hits)
    if res.score >= BUY_THRESHOLD and not veto:
        res.direction = "long"
    elif res.score <= SELL_THRESHOLD:
        res.direction = "short"
    return res


def trigger_volume_pattern(bars: list[MinuteBar]) -> tuple[str | None, list[str]]:
    """接入 detect_resonance 的触发器：返回 (方向, 命中形态名列表)."""
    r = detect_patterns(bars)
    return r.direction, r.hits
