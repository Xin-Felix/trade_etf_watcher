"""诊断信号是否有预测力：信号后 N 根的远期收益 vs 无条件基准.

回答一个关键问题：亏钱是因为「入场信号没用」还是「出场逻辑差」？
  - 若信号后远期收益 ≈ 基准 → 入场信号没有预测力，整套思路要推翻
  - 若显著为正但实盘亏 → 是出场/配对逻辑的问题，改出场即可
"""
from __future__ import annotations

import pickle
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from watcher.bars import aggregate_minute_bars
from watcher.signals.patterns import detect_patterns

CACHE = Path(__file__).resolve().parent / ".cache"
WINDOW, MIN_START = 60, 25
HORIZONS = (1, 3, 5, 10, 20)


def main() -> None:
    src = sys.argv[1] if len(sys.argv) > 1 else "stocks"
    period = int(sys.argv[2]) if len(sys.argv) > 2 else 5

    if src == "stocks":
        raw = pickle.loads((CACHE / "stocks_5m_180d.pkl").read_bytes())
    else:
        raw = pickle.loads((CACHE / "tushare_mins5.pkl").read_bytes())

    fwd_long: dict[int, list[float]] = {h: [] for h in HORIZONS}
    fwd_short: dict[int, list[float]] = {h: [] for h in HORIZONS}
    base: dict[int, list[float]] = {h: [] for h in HORIZONS}

    for code, bars in raw.items():
        if period != 5:
            bars = aggregate_minute_bars(bars, period)
        by_day: dict[str, list] = {}
        for b in bars:
            by_day.setdefault(b.ts[:8], []).append(b)

        for day in sorted(by_day):
            db = by_day[day]
            if len(db) < MIN_START + max(HORIZONS) + 2:
                continue
            for i in range(MIN_START, len(db) + 1):
                cur = db[i - 1]
                # 无条件基准（同一批 bar，不看信号）
                for h in HORIZONS:
                    if i - 1 + h < len(db):
                        base[h].append(
                            (db[i - 1 + h].close - cur.close) / cur.close * 100)
                r = detect_patterns(db[max(0, i - WINDOW):i], period)
                if not r.direction:
                    continue
                tgt = fwd_long if r.direction == "long" else fwd_short
                for h in HORIZONS:
                    if i - 1 + h < len(db):
                        tgt[h].append(
                            (db[i - 1 + h].close - cur.close) / cur.close * 100)

    def line(tag: str, d: dict[int, list[float]]) -> None:
        parts = []
        for h in HORIZONS:
            v = d[h]
            if v:
                avg = sum(v) / len(v)
                winr = sum(1 for x in v if x > 0) / len(v) * 100
                parts.append(f"+{h:<2}根 {avg:>+6.3f}%/{winr:>4.1f}%")
            else:
                parts.append(f"+{h:<2}根    —    ")
        n = len(d[HORIZONS[0]])
        print(f"{tag:<12}(n={n:>5})  " + "  ".join(parts))

    print(f"\n{'=' * 96}")
    print(f"信号预测力诊断 · {src} · {period}分钟 · 格式: 平均收益/上涨概率")
    print("=" * 96)
    line("无条件基准", base)
    line("买入信号后", fwd_long)
    line("卖出信号后", fwd_short)

    def welch(a: list[float], b: list[float]) -> tuple[float, float]:
        """Welch t 检验：返回 (均值差, t值)."""
        na, nb = len(a), len(b)
        if na < 5 or nb < 5:
            return 0.0, 0.0
        ma, mb = sum(a) / na, sum(b) / nb
        va = sum((x - ma) ** 2 for x in a) / (na - 1)
        vb = sum((x - mb) ** 2 for x in b) / (nb - 1)
        se = ((va / na) + (vb / nb)) ** 0.5
        return ma - mb, ((ma - mb) / se if se > 0 else 0.0)

    print("\n--- 超额收益与显著性（vs 无条件基准，Welch t 检验）---")
    print(f"{'周期':<8}{'买入超额':<12}{'t值':<10}{'卖出超额':<12}{'t值':<10}结论")
    for h in HORIZONS:
        dl, tl = welch(fwd_long[h], base[h])
        ds, ts = welch(fwd_short[h], base[h])
        # |t| > 2 才算有统计意义
        verdict = []
        if abs(tl) > 2:
            verdict.append("买入" + ("正" if dl > 0 else "负") + "向显著")
        if abs(ts) > 2:
            verdict.append("卖出" + ("正" if ds > 0 else "负") + "向显著")
        print(f"+{h:<7}{dl:>+9.4f}%  {tl:>+7.2f}   {ds:>+9.4f}%  {ts:>+7.2f}   "
              f"{' / '.join(verdict) or '无显著性'}")

    # 存下数组便于后续分析，不用重跑
    (CACHE / f"edge_{src}_{period}m.pkl").write_bytes(
        pickle.dumps({"base": base, "long": fwd_long, "short": fwd_short})
    )
    print(f"\n原始数组已缓存: .cache/edge_{src}_{period}m.pkl")


if __name__ == "__main__":
    main()
