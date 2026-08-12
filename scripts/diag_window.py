"""诊断：打印指定时间段的逐根量价特征."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from watcher.signals.patterns import compute_features
from watcher.state import StateStore


def main() -> None:
    code = sys.argv[1] if len(sys.argv) > 1 else "sh588000"
    start = sys.argv[2] if len(sys.argv) > 2 else "1255"
    end = sys.argv[3] if len(sys.argv) > 3 else "1320"

    store = StateStore()
    bars = store.get_bars(code, limit=2000)
    day = bars[-1].ts[:8]
    bars = [b for b in bars if b.ts[:8] == day]
    feats = compute_features(bars, 1)

    print(f"{code} {day}  {start}~{end}")
    print(f"{'时间':<7}{'开':<8}{'高':<8}{'低':<8}{'收':<8}{'量比':<7}{'涨幅':<9}"
          f"{'实体':<6}{'上影':<6}标签")
    for b, f in zip(bars, feats):
        t = b.ts[8:12]
        if start <= t <= end:
            print(f"{t[:2]}:{t[2:]:<4}{b.open:<8.3f}{b.high:<8.3f}{b.low:<8.3f}"
                  f"{b.close:<8.3f}{f.vr:<7.2f}{f.chg * 100:<+9.3f}"
                  f"{f.body:<6.2f}{f.upper:<6.2f}{f.label}")


if __name__ == "__main__":
    main()
