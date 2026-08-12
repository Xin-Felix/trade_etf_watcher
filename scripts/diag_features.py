"""诊断：打印某标的某周期的量价特征分布，用于校准形态阈值."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from watcher.bars import aggregate_minute_bars
from watcher.signals.patterns import compute_features
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
    feats = compute_features(bars, period)

    chgs = sorted(abs(f.chg) for f in feats)
    vrs = sorted(f.vr for f in feats)
    amps = sorted(f.amp for f in feats)
    n = len(chgs)

    def q(arr, p):
        return arr[min(n - 1, int(n * p))]

    print(f"{code} {day} {period}分 共 {n} 根")
    print("abs(chg)%%: p50=%.3f p70=%.3f p85=%.3f p95=%.3f max=%.3f"
          % (q(chgs, .5) * 100, q(chgs, .7) * 100, q(chgs, .85) * 100,
             q(chgs, .95) * 100, chgs[-1] * 100))
    print("vr:        p50=%.2f p70=%.2f p85=%.2f p95=%.2f max=%.2f"
          % (q(vrs, .5), q(vrs, .7), q(vrs, .85), q(vrs, .95), vrs[-1]))
    print("amp%%:      p50=%.3f p85=%.3f max=%.3f"
          % (q(amps, .5) * 100, q(amps, .85) * 100, amps[-1] * 100))

    print("\n量比最大的 12 根:")
    top = sorted(zip(bars, feats), key=lambda x: -x[1].vr)[:12]
    for b, f in sorted(top, key=lambda x: x[0].ts):
        print(f"  {b.ts[8:10]}:{b.ts[10:12]} C={b.close:.3f} vr={f.vr:5.2f} "
              f"chg={f.chg * 100:+.3f}% body={f.body:.2f} up={f.upper:.2f} {f.label}")


if __name__ == "__main__":
    main()
