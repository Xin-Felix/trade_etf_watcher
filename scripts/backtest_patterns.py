"""量价形态回测：在历史 bar 上滑动窗口跑形态识别，打印买卖点.

用法:
    python scripts/backtest_patterns.py            # 默认 sh588000 1分
    python scripts/backtest_patterns.py sh510500 5 # 指定标的和周期
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from watcher.bars import aggregate_minute_bars
from watcher.signals.patterns import compute_features, detect_patterns
from watcher.state import StateStore


def run(code: str, period_min: int) -> None:
    store = StateStore()
    bars1 = store.get_bars(code, limit=2000)
    if not bars1:
        print(f"{code} 无本地分钟数据")
        return

    # 只取最后一个交易日
    last_day = bars1[-1].ts[:8]
    bars1 = [b for b in bars1 if b.ts[:8] == last_day]
    bars = bars1 if period_min == 1 else aggregate_minute_bars(bars1, period_min)
    if len(bars) < 10:
        print(f"{code} 数据不足（{len(bars)} 根）")
        return

    print(f"\n=== {code} {last_day} {period_min}分 共 {len(bars)} 根 ===")
    print(f"日内区间: {min(b.low for b in bars):.3f} ~ {max(b.high for b in bars):.3f}\n")

    signals = []
    for i in range(10, len(bars) + 1):
        window = bars[:i]
        r = detect_patterns(window, period_min)
        if r.direction:
            b = window[-1]
            signals.append((b.ts, b.close, r.direction, r.score, r.hits, r.bar_label))
    print_signals(signals, bars)


def print_signals(signals, bars) -> None:
    if not signals:
        print("未触发任何信号")
        return

    print(f"{'时间':<8}{'方向':<6}{'价格':<9}{'得分':<6}{'当根标签':<12}命中形态")
    print("-" * 88)
    for ts, price, direction, score, hits, label in signals:
        t = f"{ts[8:10]}:{ts[10:12]}"
        arrow = "买 ▲" if direction == "long" else "卖 ▼"
        print(f"{t:<8}{arrow:<6}{price:<9.3f}{score:<+6d}{label:<12}{' + '.join(hits)}")

    # 简单配对收益（买入后遇到第一个卖信号平仓）
    print("\n--- 配对结果 ---")
    pos = None
    trades = []
    for ts, price, direction, *_ in signals:
        if direction == "long" and pos is None:
            pos = (ts, price)
        elif direction == "short" and pos is not None:
            pnl = (price - pos[1]) / pos[1] * 100
            trades.append((pos[0], pos[1], ts, price, pnl))
            pos = None
    for bt, bp, st, sp, pnl in trades:
        tag = "盈" if pnl > 0 else "亏"
        print(f"{bt[8:10]}:{bt[10:12]} 买 {bp:.3f} → "
              f"{st[8:10]}:{st[10:12]} 卖 {sp:.3f}  {pnl:+.2f}% [{tag}]")
    if pos:
        last = bars[-1].close
        pnl = (last - pos[1]) / pos[1] * 100
        print(f"{pos[0][8:10]}:{pos[0][10:12]} 买 {pos[1]:.3f} → 持仓中 "
              f"(收盘 {last:.3f}, {pnl:+.2f}%)")
    if trades:
        total = sum(t[4] for t in trades)
        win = sum(1 for t in trades if t[4] > 0)
        print(f"\n共 {len(trades)} 笔, 胜 {win} 笔, 累计 {total:+.2f}%")


if __name__ == "__main__":
    code = sys.argv[1] if len(sys.argv) > 1 else "sh588000"
    period = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    run(code, period)
