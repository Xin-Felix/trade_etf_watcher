"""个股长周期回测（Tushare 官方直连，分钟线）：覆盖大/中/小市值.

用法:
    python scripts/backtest_stocks.py 5              # 5分钟，用缓存
    python scripts/backtest_stocks.py 5 rebuild      # 重新下载
    python scripts/backtest_stocks.py 15             # 由5分聚合成15分
    python scripts/backtest_stocks.py 5 rebuild 180  # 只取近180天
"""
from __future__ import annotations

import pickle
import sys
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from watcher.bars import aggregate_minute_bars
from watcher.fetchers.tushare_src import TushareClient
from watcher.models import MinuteBar
from watcher.signals.patterns import detect_patterns

# (ts_code, 名称, 市值档)
STOCKS = [
    ("600519.SH", "贵州茅台", "大盘"),
    ("601318.SH", "中国平安", "大盘"),
    ("000858.SZ", "五粮液", "大盘"),
    ("600036.SH", "招商银行", "大盘"),
    ("300750.SZ", "宁德时代", "大盘"),
    ("002415.SZ", "海康威视", "中盘"),
    ("600585.SH", "海螺水泥", "中盘"),
    ("002304.SZ", "洋河股份", "中盘"),
    ("600009.SH", "上海机场", "中盘"),
    ("300142.SZ", "沃森生物", "小盘"),
    ("002050.SZ", "三花智控", "小盘"),
    ("300033.SZ", "同花顺", "小盘"),
    ("002241.SZ", "歌尔股份", "小盘"),
    ("603259.SH", "药明康德", "中盘"),
]

CACHE = Path(__file__).resolve().parent / ".cache"
FEE = 0.05        # 双边手续费+印花税近似（个股卖出还有千一印花税，见 FEE_SELL）
FEE_SELL = 0.10   # 个股卖出印花税 0.05% + 佣金，合计按 0.10% 计
WINDOW = 60
MIN_START = 25


def fetch_mins(client: TushareClient, ts_code: str,
               days: int, freq: str = "5min") -> list[MinuteBar]:
    today = date.today()
    stop = today - timedelta(days=days)
    bars: list[MinuteBar] = []
    seen: set[str] = set()
    cursor = today
    while cursor > stop:
        seg = max(stop, cursor - timedelta(days=25))
        rows = client.call(
            "stk_mins",
            {"ts_code": ts_code, "freq": freq,
             "start_date": f"{seg.strftime('%Y-%m-%d')} 09:00:00",
             "end_date": f"{cursor.strftime('%Y-%m-%d')} 15:00:00"},
            "trade_time,open,high,low,close,vol",
        )
        for r in rows:
            t = str(r.get("trade_time") or "")
            if len(t) < 19 or t in seen:
                continue
            seen.add(t)
            try:
                close = float(r.get("close") or 0)
                if close <= 0:
                    continue
                bars.append(MinuteBar(
                    code=ts_code, source="tushare_mins",
                    ts=t[:4] + t[5:7] + t[8:10] + t[11:13] + t[14:16] + t[17:19],
                    open=float(r.get("open") or 0) or close,
                    high=float(r.get("high") or 0) or close,
                    low=float(r.get("low") or 0) or close,
                    close=close, volume=int(float(r.get("vol") or 0)),
                ))
            except (TypeError, ValueError):
                continue
        cursor = seg
        time.sleep(0.3)
    bars.sort(key=lambda b: b.ts)
    return bars


def run_intraday(bars: list[MinuteBar], period_min: int) -> list[dict]:
    """按日分段跑形态，每日收盘强平（T+1 无法日内平仓，此处仅评估信号质量）."""
    by_day: dict[str, list[MinuteBar]] = {}
    for b in bars:
        by_day.setdefault(b.ts[:8], []).append(b)

    trades: list[dict] = []
    for day in sorted(by_day):
        db = by_day[day]
        if len(db) < MIN_START + 2:
            continue
        sigs = []
        for i in range(MIN_START, len(db) + 1):
            r = detect_patterns(db[max(0, i - WINDOW):i], period_min)
            if r.direction:
                sigs.append((db[i - 1], r.direction, r.hits))

        pos = None
        for bar, d, hits in sigs:
            if d == "long" and pos is None:
                pos = (bar, hits)
            elif d == "short" and pos is not None:
                trades.append(_mk(pos, bar))
                pos = None
        if pos is not None:
            trades.append(_mk(pos, db[-1]))
    return trades


def _mk(pos: tuple, sell_bar: MinuteBar) -> dict:
    buy_bar, hits = pos
    gross = (sell_bar.close - buy_bar.close) / buy_bar.close * 100
    return {
        "buy_ts": buy_bar.ts, "buy": buy_bar.close, "hits": hits,
        "sell_ts": sell_bar.ts, "sell": sell_bar.close,
        "pnl": gross - FEE_SELL, "gross": gross,
    }


def summarize(name: str, tag: str, trades: list[dict], bh: float) -> dict | None:
    if not trades:
        print(f"{name:<10}{tag:<6}{'0':<7}{'—':<9}{'无信号':<12}{bh:>+8.2f}%")
        return None
    n = len(trades)
    win = sum(1 for t in trades if t["pnl"] > 0)
    total = sum(t["pnl"] for t in trades)
    wins = [t["pnl"] for t in trades if t["pnl"] > 0]
    ls = abs(sum(t["pnl"] for t in trades if t["pnl"] <= 0))
    pf = f"{sum(wins) / ls:.2f}" if ls > 0 else "∞"
    print(f"{name:<10}{tag:<6}{n:<7}{win / n * 100:>5.1f}%   "
          f"{total:>+8.2f}%    {bh:>+8.2f}%    {pf}")
    return {"n": n, "win": win, "total": total}


def main() -> None:
    period = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    rebuild = len(sys.argv) > 2 and sys.argv[2] == "rebuild"
    days = int(sys.argv[3]) if len(sys.argv) > 3 else 365

    CACHE.mkdir(exist_ok=True)
    path = CACHE / f"stocks_5m_{days}d.pkl"
    if path.exists() and not rebuild:
        raw = pickle.loads(path.read_bytes())
        print(f"用缓存: {len(raw)} 只股票，共 {sum(len(v) for v in raw.values())} 根")
    else:
        client = TushareClient()
        print(f"下载 {len(STOCKS)} 只个股 5 分钟线（近 {days} 天）...")
        raw = {}
        for ts_code, name, cap in STOCKS:
            bars = fetch_mins(client, ts_code, days)
            raw[ts_code] = bars
            nd = len({b.ts[:8] for b in bars})
            print(f"  {name:<8}{ts_code}  {len(bars):>6} 根 / {nd} 日")
        path.write_bytes(pickle.dumps(raw))

    print(f"\n{'=' * 84}")
    print(f"个股量价形态回测 · {period}分钟 · 卖出成本 {FEE_SELL}%/笔（含印花税）")
    print("=" * 84)
    print(f"\n{'名称':<10}{'档位':<6}{'笔数':<7}{'胜率':<9}{'策略累计':<12}"
          f"{'买入持有':<12}盈亏比")
    print("-" * 84)

    all_trades: list[dict] = []
    by_cap: dict[str, list[dict]] = {}
    hit_stat: dict[str, list[float]] = {}

    for ts_code, name, cap in STOCKS:
        bars = raw.get(ts_code) or []
        if len(bars) < MIN_START + 10:
            print(f"{name:<10}{cap:<6}数据不足({len(bars)})")
            continue
        if period != 5:
            bars = aggregate_minute_bars(bars, period)
        bh = ((bars[-1].close - bars[0].close) / bars[0].close * 100)
        trades = run_intraday(bars, period)
        for t in trades:
            t["name"], t["cap"] = name, cap
            all_trades.append(t)
            by_cap.setdefault(cap, []).append(t)
            for h in t["hits"]:
                hit_stat.setdefault(h, []).append(t["pnl"])
        summarize(name, cap, trades, bh)

    _report(all_trades, by_cap, hit_stat)


def _report(all_trades: list[dict], by_cap: dict[str, list[dict]],
            hit_stat: dict[str, list[float]]) -> None:
    if not all_trades:
        print("\n无交易")
        return

    print("\n--- 按市值档 ---")
    for cap in ("大盘", "中盘", "小盘"):
        ts = by_cap.get(cap)
        if not ts:
            continue
        n = len(ts)
        win = sum(1 for t in ts if t["pnl"] > 0)
        total = sum(t["pnl"] for t in ts)
        print(f"  {cap}  {n:>5}笔  胜率{win / n * 100:>5.1f}%  "
              f"累计{total:>+8.2f}%  单笔均{total / n:>+7.3f}%")

    print("\n--- 按买入形态 ---")
    print(f"{'形态':<16}{'次数':<8}{'胜率':<9}{'单笔均'}")
    for h, pnls in sorted(hit_stat.items(), key=lambda x: -len(x[1])):
        n = len(pnls)
        win = sum(1 for p in pnls if p > 0)
        print(f"{h:<16}{n:<8}{win / n * 100:>5.1f}%   {sum(pnls) / n:>+7.3f}%")

    by_month: dict[str, float] = {}
    cnt: dict[str, int] = {}
    for t in all_trades:
        m = t["buy_ts"][:6]
        by_month[m] = by_month.get(m, 0.0) + t["pnl"]
        cnt[m] = cnt.get(m, 0) + 1
    print("\n--- 按月（全部个股合计）---")
    pos_m = 0
    for m in sorted(by_month):
        v = by_month[m]
        pos_m += 1 if v > 0 else 0
        print(f"  {m[:4]}-{m[4:]}  {v:>+9.2f}%  ({cnt[m]:>4}笔)")
    print(f"  盈利月份: {pos_m}/{len(by_month)}")

    n = len(all_trades)
    win = sum(1 for t in all_trades if t["pnl"] > 0)
    total = sum(t["pnl"] for t in all_trades)
    gross = sum(t["gross"] for t in all_trades)
    wins = [t["pnl"] for t in all_trades if t["pnl"] > 0]
    losses = [t["pnl"] for t in all_trades if t["pnl"] <= 0]

    eq = peak = mdd = 0.0
    for t in sorted(all_trades, key=lambda x: x["buy_ts"]):
        eq += t["pnl"]
        peak = max(peak, eq)
        mdd = min(mdd, eq - peak)

    print("\n--- 总计 ---")
    print(f"交易笔数: {n}   胜: {win}   负: {n - win}   胜率: {win / n * 100:.1f}%")
    print(f"毛收益: {gross:+.2f}%   扣成本: {total:+.2f}%   "
          f"单笔平均: {total / n:+.3f}%")
    if wins:
        print(f"平均盈利: {sum(wins) / len(wins):+.3f}%   最大盈利: {max(wins):+.2f}%")
    if losses:
        print(f"平均亏损: {sum(losses) / len(losses):+.3f}%   最大亏损: {min(losses):+.2f}%")
    if wins and losses:
        print(f"盈亏比: {sum(wins) / abs(sum(losses)):.2f}")
    print(f"最大回撤: {mdd:.2f}%   成本合计: {n * FEE_SELL:.2f}%")


if __name__ == "__main__":
    main()
