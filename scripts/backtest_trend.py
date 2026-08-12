"""ETF 期权趋势策略 · 信号层回测（§11.6 Step 0，先于一切，不过线不做 P0）.

策略来源：《ETF期权趋势策略映射文档》（crypto 趋势策略 → A 股 ETF 期权映射，
设计稿参数均为先验估值）。三层规则实现见 watcher/signals/trend.py（与实盘共用）：

    第1层 周线方向闸门（close vs 周EMA20 + 周EMA10 斜率）
    第2层 日线趋势强度（ADX(14)>30 且 方向DI差值>10 且 ATR比率>0.8）
    第3层 日线结构确认（多: close>EMA50 且 EMA10>EMA20；空: 反之）
    出场：周线明确反向（中性不平仓）

口径（与 backtest_multi / diag_edge 一致）：
    - 评估标的当量（暂不模拟期权 Theta/价差，那是验证流程第 2 步）
    - 收盘出信号、次日开盘价成交（无未来函数）；做空按标的反向收益记
    - 扣双边 0.05% 费用；t 值 = 单笔均值/(标准差/√n)；PF = 总盈利/|总亏损|

过线标准（原文档第七节 + §11.6）：3 年以上、覆盖牛熊两段、PF > 1.1、t ≥ 2。
不过线按 §8.5 纪律记录负面结论并放弃。

数据：TDX 日 K（category 9，分页）为主，不足 3 年用 Tushare fund_daily 补，
缓存 .cache/etf_daily.pkl（--refresh 重新下载）。

用法:
    python scripts/backtest_trend.py              # 用缓存（没有则先下载），次日开盘成交
    python scripts/backtest_trend.py --refresh    # 强制重新下载日线
    python scripts/backtest_trend.py --exec-close # 信号日收盘成交（稳健性对照）
    python scripts/backtest_trend.py detail       # 打印每笔明细
"""
from __future__ import annotations

import pickle
import sys
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from watcher.config import Config
from watcher.fetchers.tdx import TdxFetcher, _parse_code
from watcher.models import MinuteBar
from watcher.signals.trend import DEFAULT_PARAMS, trend_states

CACHE = Path(__file__).resolve().parent / ".cache"
DAILY_PKL = CACHE / "etf_daily.pkl"

FEE_ROUND_TRIP = 0.05   # 双边手续费约 0.05%（万2.5 单边），必须扣掉才有意义
MIN_DAYS = 730          # 3 年 ≈ 730 个交易日，不足则用 Tushare 补
PASS_PF, PASS_T = 1.1, 2.0

# 牛熊分段：以沪深300ETF 自身周线闸门划分（>0 牛市段，否则熊市/震荡段）
REGIME_CODE = "sh510300"


# ---------- 数据 ----------


def adjust_corporate_actions(bars: list[MinuteBar],
                             gap_threshold: float = 0.25) -> tuple[list[MinuteBar], list[tuple[str, float]]]:
    """ETF 份额拆分/折算前复权：|日涨跌| > 25% 对宽基 ETF 不可能是真实行情
    （2024-09-30 那轮真实极限也就 ~20%），按比率回除此前全部 OHLC。
    返回 (调整后 bars, [(日期, 比率)])；分红小缺口（1-3%）不处理，属已知口径。
    """
    factors: list[tuple[int, float]] = []
    for i in range(1, len(bars)):
        prev = bars[i - 1].close
        if prev > 0:
            r = bars[i].close / prev
            if r > 1 + gap_threshold or r < 1 - gap_threshold:
                factors.append((i, r))
    if not factors:
        return bars, []
    out = list(bars)
    events: list[tuple[str, float]] = []
    for idx, r in factors:                    # 时间序处理，前缀自然累积全部因子
        events.append((bars[idx].ts[:8], r))
        for j in range(idx):
            b = out[j]
            out[j] = MinuteBar(
                code=b.code, ts=b.ts, open=b.open / r, high=b.high / r,
                low=b.low / r, close=b.close / r, volume=b.volume, source=b.source,
            )
    return out, events


def fetch_tdx_daily_paged(tdx: TdxFetcher, code: str, pages: int = 3,
                          per: int = 800) -> list[MinuteBar]:
    """分页拉 TDX 日 K（category 9 单页最多 800 根 ≈ 3.2 年，3 页 ≈ 9.6 年）."""
    if not tdx._ensure_api():
        return []
    market, pure = _parse_code(code)
    by_ts: dict[str, MinuteBar] = {}
    for p in range(pages):
        raw = tdx._call_with_timeout(
            lambda: tdx._api.get_security_bars(9, market, pure, p * per, per))
        if raw is None:                      # 超时僵死，重连后重试本页一次
            if not tdx._ensure_api():
                break
            raw = tdx._call_with_timeout(
                lambda: tdx._api.get_security_bars(9, market, pure, p * per, per))
        chunk = tdx._parse_bars(code, raw, 9)
        for b in chunk:
            by_ts[b.ts] = b
        if len(chunk) < per:                 # 不足一页 = 历史到头
            break
    bars = sorted(by_ts.values(), key=lambda b: b.ts)
    return bars


def fetch_daily_bars(codes: list[str], refresh: bool) -> dict[str, list[MinuteBar]]:
    if not refresh and DAILY_PKL.exists():
        return pickle.loads(DAILY_PKL.read_bytes())

    CACHE.mkdir(exist_ok=True)
    out: dict[str, list[MinuteBar]] = {}
    tdx = TdxFetcher()
    start = (date.today() - timedelta(days=365 * 10)).strftime("%Y%m%d")
    for code in codes:
        bars = fetch_tdx_daily_paged(tdx, code)
        days = len({b.ts[:8] for b in bars})
        if days < MIN_DAYS:                  # TDX 不够 3 年 → Tushare 补
            from watcher.fetchers.tushare_src import TushareClient
            client = TushareClient()
            extra = client.fetch_fund_daily(code, start_date=start, limit=0)
            if extra:
                merged = {b.ts: b for b in extra}
                merged.update({b.ts: b for b in bars})   # TDX 口径优先
                bars = sorted(merged.values(), key=lambda b: b.ts)
            time.sleep(0.4)                  # Tushare 限速
        bars, events = adjust_corporate_actions(bars)
        if events:
            ev = "、".join(f"{d}×{r:.3f}" for d, r in events)
            print(f"  {code} 份额拆分前复权: {ev}")
        out[code] = bars
        print(f"  {code}  {len(bars):>5} 根  "
              f"{bars[0].ts[:8] if bars else '-'} ~ {bars[-1].ts[:8] if bars else '-'}")
    tdx.close()
    DAILY_PKL.write_bytes(pickle.dumps(out))
    print(f"已缓存 {DAILY_PKL.name}")
    return out


# ---------- 回测 ----------


def backtest_one(code: str, bars: list[MinuteBar], exec_mode: str = "open") -> list[dict]:
    """收盘出信号；exec_mode=open 次日开盘价成交（主口径），close 信号日收盘价成交（稳健性对照）.
    出场 = 周线明确反向。返回逐笔交易.
    """
    states = trend_states(bars, DEFAULT_PARAMS)
    trades: list[dict] = []
    pos_dir, pos_px, pos_date = 0, 0.0, ""
    for t in range(1, len(bars)):
        sig_idx = t - 1 if exec_mode == "open" else t
        sig = states[sig_idx]
        exec_bar = bars[t]
        px = exec_bar.open if exec_mode == "open" else exec_bar.close
        if pos_dir and sig.exit_for(pos_dir):
            pnl = (px - pos_px) / pos_px * 100 * pos_dir
            trades.append({
                "code": code, "dir": pos_dir,
                "entry_date": pos_date, "entry": pos_px,
                "exit_date": exec_bar.ts[:8], "exit": px,
                "exit_reason": "周线反向", "pnl": pnl,
            })
            pos_dir = 0
        if not pos_dir:
            d = sig.direction(DEFAULT_PARAMS)
            if d:
                pos_dir, pos_px, pos_date = d, px, exec_bar.ts[:8]
    if pos_dir:                              # 样本末尾未平仓按最后收盘结算
        last = bars[-1]
        pnl = (last.close - pos_px) / pos_px * 100 * pos_dir
        trades.append({
            "code": code, "dir": pos_dir,
            "entry_date": pos_date, "entry": pos_px,
            "exit_date": last.ts[:8], "exit": last.close,
            "exit_reason": "样本截止", "pnl": pnl,
        })
    return trades


def diag_entry_edge(data: dict[str, list[MinuteBar]], horizons: tuple[int, ...] = (5, 10, 20)
                    ) -> None:
    """§8.5 诊断：三层全满足（入场信号）后的远期收益 vs 无条件基准（Welch t）.

    区分「入场信号没用」与「出场逻辑差」：信号后收益≈基准 → 入场没有预测力，
    整套思路要推翻；显著为正但回测亏 → 是出场层（周线反向太慢）的问题。
    """
    fwd: dict[int, dict[int, list[float]]] = {1: {h: [] for h in horizons},
                                              -1: {h: [] for h in horizons}}
    base: dict[int, list[float]] = {h: [] for h in horizons}
    for code, bars in data.items():
        if len(bars) < 300:
            continue
        states = trend_states(bars, DEFAULT_PARAMS)
        closes = [b.close for b in bars]
        for i in range(len(bars)):
            for h in horizons:
                if i + h < len(bars):
                    base[h].append((closes[i + h] - closes[i]) / closes[i] * 100)
            d = states[i].direction(DEFAULT_PARAMS)
            if d:
                for h in horizons:
                    if i + h < len(bars):
                        fwd[d][h].append(
                            (closes[i + h] - closes[i]) / closes[i] * 100 * d)

    def welch(a: list[float], b: list[float]) -> tuple[float, float]:
        na, nb = len(a), len(b)
        if na < 5 or nb < 5:
            return 0.0, 0.0
        ma, mb = sum(a) / na, sum(b) / nb
        va = sum((x - ma) ** 2 for x in a) / (na - 1)
        vb = sum((x - mb) ** 2 for x in b) / (nb - 1)
        se = ((va / na) + (vb / nb)) ** 0.5
        return ma - mb, ((ma - mb) / se if se > 0 else 0.0)

    print("\n--- 信号预测力诊断（信号日后 N 个交易日收益 vs 无条件基准，方向调整后）---")
    print(f"{'周期':<8}{'基准均值':<11}{'多头信号后':<12}{'超额':<10}{'t值':<8}"
          f"{'空头信号后':<12}{'超额':<10}{'t值'}")
    for h in horizons:
        b = base[h]
        bavg = sum(b) / len(b) if b else 0.0
        dl, tl = welch(fwd[1][h], b)
        ds, ts = welch(fwd[-1][h], b)
        la = sum(fwd[1][h]) / len(fwd[1][h]) if fwd[1][h] else 0.0
        sa = sum(fwd[-1][h]) / len(fwd[-1][h]) if fwd[-1][h] else 0.0
        star_l = " *" if abs(tl) > 2 else ""
        star_s = " *" if abs(ts) > 2 else ""
        print(f"+{h:<7}{bavg:>+8.3f}%  {la:>+9.3f}%  {dl:>+8.3f}%  {tl:>+6.2f}"
              f"  {sa:>+9.3f}%  {ds:>+8.3f}%  {ts:>+6.2f}{star_l}{star_s}")
    print(f"（多头信号 n={len(fwd[1][horizons[0]])}，空头信号 n={len(fwd[-1][horizons[0]])}，"
          f"|t|>2 才有统计意义）")


def stats(pnls: list[float], fee: float = FEE_ROUND_TRIP) -> dict:
    """净口径统计（fee 为 %/笔）；t 值与 PF 都对扣费后的净收益序列计算."""
    if not pnls:
        return {"n": 0}
    net = [p - fee for p in pnls]
    n = len(net)
    avg = sum(net) / n
    sd = (sum((x - avg) ** 2 for x in net) / (n - 1)) ** 0.5 if n > 1 else 0.0
    win_sum = sum(x for x in net if x > 0)
    loss_sum = sum(x for x in net if x <= 0)
    return {
        "n": n,
        "win": sum(1 for x in net if x > 0) / n * 100,
        "total_net": sum(net),
        "avg_net": avg,
        "t": avg / (sd / n ** 0.5) if sd > 0 else 0.0,
        "pf": win_sum / abs(loss_sum) if loss_sum < 0 else float("inf"),
    }


def fmt(tag: str, s: dict) -> str:
    if not s.get("n"):
        return f"{tag:<22}无交易"
    return (f"{tag:<22}{s['n']:>4}笔  胜率{s['win']:>5.1f}%  "
            f"累计净{s['total_net']:>+8.2f}%  单笔净{s['avg_net']:>+7.3f}%  "
            f"PF {s['pf']:>5.2f}  t {s['t']:>+6.2f}")


def main() -> None:
    args = [a for a in sys.argv[1:]]
    refresh = "--refresh" in args
    detail = "detail" in args
    exec_mode = "close" if "--exec-close" in args else "open"

    cfg = Config.load()
    codes = cfg.watch_codes()
    print(f"\n{'=' * 92}")
    print(f"ETF 期权趋势策略 · 信号层回测（§11.6 Step 0）· 标的当量 · 扣双边 {FEE_ROUND_TRIP}%"
          f" · {'信号日收盘' if exec_mode == 'close' else '次日开盘'}成交")
    print("=" * 92)
    data = fetch_daily_bars(codes, refresh)

    names = {i.code: i.name for i in cfg.watchlist}
    all_trades: list[dict] = []
    per_code: dict[str, list[float]] = {}
    for code in codes:
        bars = data.get(code) or []
        if len(bars) < 300:
            print(f"  {code} {names.get(code, ''):<14}数据不足({len(bars)} 根)，跳过")
            continue
        trades = backtest_one(code, bars, exec_mode)
        all_trades.extend(trades)
        per_code[code] = [t["pnl"] for t in trades]

    if not all_trades:
        print("\n全样本无交易（三层条件可能过严）")
        return

    days_span = sorted({t["entry_date"] for t in all_trades})
    print(f"\n样本: {len(per_code)} 个标的 · 首笔 {days_span[0]} ~ 末笔 {days_span[-1]}")

    # ---- 牛熊分段（sh510300 周线闸门划分，>0=牛市段，其余=熊市/震荡段）----
    regime_gates: dict[str, int] = {}
    rb = data.get(REGIME_CODE) or []
    if rb:
        rst = trend_states(rb, DEFAULT_PARAMS)
        regime_gates = {b.ts[:8]: s.gate for b, s in zip(rb, rst)}
    bull_pnls = [t["pnl"] for t in all_trades if regime_gates.get(t["entry_date"], 0) > 0]
    bear_pnls = [t["pnl"] for t in all_trades if regime_gates.get(t["entry_date"], 0) <= 0]

    print("\n--- 按标的（净口径）---")
    for code, pnls in per_code.items():
        print(fmt(f"{code} {names.get(code, ''):<12}", stats(pnls)))

    long_pnls = [t["pnl"] for t in all_trades if t["dir"] == 1]
    short_pnls = [t["pnl"] for t in all_trades if t["dir"] == -1]
    print("\n--- 按方向 ---")
    print(fmt("做多（买认购当量）", stats(long_pnls)))
    print(fmt("做空（买认沽当量）", stats(short_pnls)))

    print("\n--- 牛熊分段（sh510300 周线闸门划分）---")
    print(fmt("牛市段（闸门>0）", stats(bull_pnls)))
    print(fmt("熊市/震荡段", stats(bear_pnls)))

    by_year: dict[str, list[float]] = {}
    for t in all_trades:
        by_year.setdefault(t["entry_date"][:4], []).append(t["pnl"])
    print("\n--- 按年份 ---")
    for y in sorted(by_year):
        print(fmt(f"{y} 年", stats(by_year[y])))

    overall = stats([t["pnl"] for t in all_trades])
    print(f"\n{'=' * 92}")
    print(fmt("总计", overall))
    gross_total = sum(t["pnl"] for t in all_trades)
    print(f"{'':<22}累计毛{gross_total:>+8.2f}%  费用合计 "
          f"{-overall['n'] * FEE_ROUND_TRIP:>+8.2f}%")

    hold_days = [(_days(t["entry_date"], t["exit_date"])) for t in all_trades]
    print(f"{'':<22}平均持仓 {sum(hold_days) / len(hold_days):.1f} 个自然日  "
          f"最长 {max(hold_days)} 天")

    # ---- 过线判定 ----
    bull_bear_ok = bool(bull_pnls) and bool(bear_pnls)
    verdict = overall["pf"] > PASS_PF and overall["t"] >= PASS_T and bull_bear_ok
    print(f"\n--- 过线判定（PF>{PASS_PF} 且 t≥{PASS_T} 且牛熊两段均有交易）---")
    print(f"牛熊两段: {'✓' if bull_bear_ok else '✗'}  "
          f"PF: {overall['pf']:.2f} {'✓' if overall['pf'] > PASS_PF else '✗'}  "
          f"t: {overall['t']:+.2f} {'✓' if overall['t'] >= PASS_T else '✗'}")
    print(f"结论: {'过线 → 可做 P0 信号接入' if verdict else '不过线 → 按 §8.5 纪律记录负面结论，放弃 P0'}")

    diag_entry_edge(data)

    if detail:
        print("\n--- 每笔明细 ---")
        for t in sorted(all_trades, key=lambda x: x["entry_date"]):
            d = "多" if t["dir"] == 1 else "空"
            print(f"{t['entry_date']} {t['code']:<9}{d} "
                  f"{t['entry']:.3f} → {t['exit_date']} {t['exit']:.3f} "
                  f"{t['pnl']:>+7.2f}%  {t['exit_reason']}")

    CACHE.mkdir(exist_ok=True)
    (CACHE / "trend_trades.pkl").write_bytes(pickle.dumps(all_trades))
    print(f"\n逐笔已缓存: .cache/trend_trades.pkl")


def _days(d1: str, d2: str) -> int:
    return (date(int(d2[:4]), int(d2[4:6]), int(d2[6:8]))
            - date(int(d1[:4]), int(d1[4:6]), int(d1[6:8]))).days


if __name__ == "__main__":
    main()
