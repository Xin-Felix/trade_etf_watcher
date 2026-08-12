"""多日多标的量价形态回测汇总.

用法:
    python scripts/backtest_multi.py          # 全部标的、全部本地交易日、1分
    python scripts/backtest_multi.py 5        # 5分周期
    python scripts/backtest_multi.py 1 detail # 打印每笔明细
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from watcher.bars import aggregate_minute_bars
from watcher.config import Config
from watcher.signals.patterns import detect_patterns
from watcher.state import StateStore

MIN_START = 12          # 至少多少根才开始检测
FEE_ROUND_TRIP = 0.05   # 双边手续费约 0.05%（万2.5 单边），必须扣掉才有意义


def load_days(store: StateStore) -> list[str]:
    with sqlite3.connect(store.db_path) as conn:
        rows = conn.execute(
            "SELECT DISTINCT substr(ts,1,8) d FROM minute_bars "
            "WHERE length(code) <= 8 AND code NOT GLOB '[0-9]*' ORDER BY d"
        ).fetchall()
    return [r[0] for r in rows]


def run_one(bars: list, period: int) -> tuple[list[tuple], list[dict]]:
    """返回 (信号列表, 配对交易列表)."""
    signals = []
    for i in range(MIN_START, len(bars) + 1):
        r = detect_patterns(bars[:i], period)
        if r.direction:
            b = bars[i - 1]
            signals.append((b.ts, b.close, r.direction, r.score, r.hits))

    trades, pos = [], None
    for ts, px, d, _s, hits in signals:
        if d == "long" and pos is None:
            pos = (ts, px, hits)
        elif d == "short" and pos is not None:
            trades.append({
                "buy_ts": pos[0], "buy": pos[1], "buy_hits": pos[2],
                "sell_ts": ts, "sell": px, "sell_hits": hits,
                "pnl": (px - pos[1]) / pos[1] * 100,
            })
            pos = None
    if pos is not None:      # 收盘未平仓，按收盘价结算
        last = bars[-1]
        trades.append({
            "buy_ts": pos[0], "buy": pos[1], "buy_hits": pos[2],
            "sell_ts": last.ts, "sell": last.close, "sell_hits": ["收盘平仓"],
            "pnl": (last.close - pos[1]) / pos[1] * 100,
        })
    return signals, trades


def main() -> None:
    period = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    detail = len(sys.argv) > 2 and sys.argv[2] == "detail"

    cfg = Config.load()
    store = StateStore()
    days = load_days(store)
    codes = cfg.watch_codes()

    print(f"\n{'=' * 78}")
    print(f"量价形态回测 · {period}分周期 · {len(days)} 个交易日 · {len(codes)} 个标的")
    print(f"日期范围: {days[0]} ~ {days[-1]}")
    print(f"{'=' * 78}\n")

    all_trades: list[dict] = []
    per_day: dict[str, list[dict]] = {}
    per_code: dict[str, list[dict]] = {}
    hit_stat: dict[str, list[float]] = {}

    for code in codes:
        raw = store.get_bars(code, limit=6000)
        for day in days:
            day_bars = [b for b in raw if b.ts[:8] == day]
            if len(day_bars) < 30:
                continue
            bars = day_bars if period == 1 else aggregate_minute_bars(day_bars, period)
            if len(bars) < MIN_START + 2:
                continue
            _sigs, trades = run_one(bars, period)
            for t in trades:
                t["code"] = code
                t["day"] = day
                all_trades.append(t)
                per_day.setdefault(day, []).append(t)
                per_code.setdefault(code, []).append(t)
                for h in t["buy_hits"]:
                    hit_stat.setdefault(h, []).append(t["pnl"])

    if not all_trades:
        print("无交易")
        return

    def summary(trades: list[dict]) -> str:
        n = len(trades)
        win = sum(1 for t in trades if t["pnl"] > 0)
        total = sum(t["pnl"] for t in trades)
        avg = total / n
        return f"{n:>4}笔  胜率{win / n * 100:>5.1f}%  累计{total:>+7.2f}%  单笔均{avg:>+6.3f}%"

    print("--- 按交易日 ---")
    for day in days:
        if day in per_day:
            print(f"{day}  {summary(per_day[day])}")

    print("\n--- 按标的 ---")
    for code in codes:
        if code in per_code:
            print(f"{code} {cfg.name_for(code):<16}{summary(per_code[code])}")


def _summary(trades: list[dict]) -> str:
    n = len(trades)
    win = sum(1 for t in trades if t["pnl"] > 0)
    total = sum(t["pnl"] for t in trades)
    return (f"{n:>4}笔  胜率{win / n * 100:>5.1f}%  "
            f"累计{total:>+7.2f}%  单笔均{total / n:>+6.3f}%")


def main() -> None:
    period = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    detail = len(sys.argv) > 2 and sys.argv[2] == "detail"

    cfg = Config.load()
    store = StateStore()
    days = load_days(store)
    codes = cfg.watch_codes()

    print(f"\n{'=' * 76}")
    print(f"量价形态回测 · {period}分 · {len(days)} 个交易日 "
          f"({days[0]}~{days[-1]}) · {len(codes)} 个标的")
    print("=" * 76)

    all_trades: list[dict] = []
    per_day: dict[str, list[dict]] = {}
    per_code: dict[str, list[dict]] = {}
    hit_stat: dict[str, list[float]] = {}

    for code in codes:
        raw = store.get_bars(code, limit=6000)
        for day in days:
            day_bars = [b for b in raw if b.ts[:8] == day]
            if len(day_bars) < 30:
                continue
            bars = day_bars if period == 1 else aggregate_minute_bars(day_bars, period)
            if len(bars) < MIN_START + 2:
                continue
            _sigs, trades = run_one(bars, period)
            for t in trades:
                t["code"], t["day"] = code, day
                all_trades.append(t)
                per_day.setdefault(day, []).append(t)
                per_code.setdefault(code, []).append(t)
                for h in t["buy_hits"]:
                    hit_stat.setdefault(h, []).append(t["pnl"])

    if not all_trades:
        print("\n无交易")
        return

    print("\n--- 按交易日 ---")
    for day in days:
        if day in per_day:
            print(f"{day}  {_summary(per_day[day])}")

    print("\n--- 按标的 ---")
    for code in codes:
        if code in per_code:
            print(f"{code} {cfg.name_for(code):<17}{_summary(per_code[code])}")


    print("\n--- 按买入形态（哪些形态真的赚钱）---")
    print(f"{'形态':<16}{'次数':<7}{'胜率':<9}{'单笔均收益'}")
    for name, pnls in sorted(hit_stat.items(), key=lambda x: -len(x[1])):
        n = len(pnls)
        win = sum(1 for p in pnls if p > 0)
        print(f"{name:<16}{n:<7}{win / n * 100:>5.1f}%   {sum(pnls) / n:>+7.3f}%")

    print("\n--- 总计 ---")
    n = len(all_trades)
    win = sum(1 for t in all_trades if t["pnl"] > 0)
    total = sum(t["pnl"] for t in all_trades)
    wins = [t["pnl"] for t in all_trades if t["pnl"] > 0]
    losses = [t["pnl"] for t in all_trades if t["pnl"] <= 0]
    print(f"交易笔数: {n}   胜: {win}   负: {n - win}   胜率: {win / n * 100:.1f}%")
    print(f"累计收益(毛): {total:+.2f}%   单笔平均: {total / n:+.3f}%")
    net = total - n * FEE_ROUND_TRIP
    print(f"累计收益(扣费): {net:+.2f}%   单笔平均: {net / n:+.3f}%"
          f"   [手续费 {FEE_ROUND_TRIP}%/笔 × {n} 笔 = {n * FEE_ROUND_TRIP:.2f}%]")
    if wins:
        print(f"平均盈利: {sum(wins) / len(wins):+.3f}%   最大盈利: {max(wins):+.2f}%")
    if losses:
        print(f"平均亏损: {sum(losses) / len(losses):+.3f}%   最大亏损: {min(losses):+.2f}%")
    if wins and losses:
        pf = sum(wins) / abs(sum(losses))
        print(f"盈亏比(总盈利/总亏损): {pf:.2f}")
    print(f"日均交易: {n / len(per_day):.1f} 笔/日"
          f"（{n / len(per_day) / len(per_code):.2f} 笔/标的/日）")

    if detail:
        print("\n--- 每笔明细 ---")
        for t in sorted(all_trades, key=lambda x: (x["day"], x["buy_ts"])):
            bt, st = t["buy_ts"], t["sell_ts"]
            print(f"{t['day']} {t['code']:<9} "
                  f"{bt[8:10]}:{bt[10:12]} 买{t['buy']:.3f} → "
                  f"{st[8:10]}:{st[10:12]} 卖{t['sell']:.3f} "
                  f"{t['pnl']:>+6.2f}%  {'+'.join(t['buy_hits'])}")


if __name__ == "__main__":
    main()
