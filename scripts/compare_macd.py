"""对比：量价形态信号 vs MACD 金叉死叉的触发时点."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from watcher.bars import aggregate_minute_bars
from watcher.signals.patterns import detect_patterns
from watcher.signals.rules import trigger_macd_cross
from watcher.state import StateStore


def main() -> None:
    code = sys.argv[1] if len(sys.argv) > 1 else "sh588000"
    period = int(sys.argv[2]) if len(sys.argv) > 2 else 1

    store = StateStore()
    bars = store.get_bars(code, limit=2000)
    day = bars[-1].ts[:8]
    bars = [b for b in bars if b.ts[:8] == day]
    if period > 1:
        bars = aggregate_minute_bars(bars, period)

    rows = []
    for i in range(10, len(bars) + 1):
        w = bars[:i]
        b = w[-1]
        pat = detect_patterns(w, period)
        macd = trigger_macd_cross(w) if len(w) >= 30 else None
        if pat.direction or macd:
            rows.append((b.ts, b.close, pat.direction, pat.hits, macd))

    print(f"\n{code} {day} {period}分  形态 vs MACD")
    print(f"{'时间':<8}{'价格':<9}{'形态信号':<28}{'MACD'}")
    print("-" * 70)
    for ts, px, pdir, hits, macd in rows:
        t = f"{ts[8:10]}:{ts[10:12]}"
        p = ""
        if pdir:
            p = ("买▲ " if pdir == "long" else "卖▼ ") + "+".join(hits)
        m = ""
        if macd:
            m = "金叉▲" if macd == "long" else "死叉▼"
        print(f"{t:<8}{px:<9.3f}{p:<28}{m}")


if __name__ == "__main__":
    main()
