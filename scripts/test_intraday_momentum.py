"""检验市场日内动量（Gao, Han, Li & Zhou 2018）在 A 股 ETF / 个股上的表现.

原文结论（标普500 ETF 1993-2013）：当日第一个半小时收益（自前收盘起算）
正向预测最后一个半小时收益，R²≈2%；与倒数第二个半小时结合后 R²≈3.5%。

A 股 4 小时 = 8 个半小时（bar 时间戳为结束时刻）：
    h1  09:30-10:00   ← first
    h2  10:00-10:30
    ...
    h7  14:00-14:30   ← penultimate
    h8  14:30-15:00   ← last

检验内容：
    1. 预测性回归 r_last ~ r_first、r_last ~ r_pen（t 值 / R²）
    2. 策略：14:30 按信号入场、15:00 平仓，扣双边成本
       M1  只看 r_first 符号
       M2  r_first 与 r_pen 同向才做（原文的组合版本）
用法:
    python scripts/test_intraday_momentum.py etf
    python scripts/test_intraday_momentum.py stocks
"""
from __future__ import annotations

import pickle
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

CACHE = Path(__file__).resolve().parent / ".cache"
FEE = 0.05          # 双边成本（ETF 佣金；个股另有印花税，见 --stock）

# bar 结束时刻 → 各半小时的边界
T_OPEN_END = "1000"     # 第一个半小时结束
T_PEN_START = "1400"    # 倒数第二个半小时起点（该 bar 收盘）
T_PEN_END = "1430"      # 倒数第二个半小时结束 = 最后半小时起点
T_CLOSE = "1500"        # 收盘


def build_days(bars: list) -> list[dict]:
    """按日提取各关键时点价格，需前一日收盘作为 r_first 的基准."""
    by_day: dict[str, dict[str, float]] = {}
    for b in bars:
        d, t = b.ts[:8], b.ts[8:12]
        by_day.setdefault(d, {})[t] = b.close

    days = sorted(by_day)
    out = []
    for i in range(1, len(days)):
        prev, cur = by_day[days[i - 1]], by_day[days[i]]
        pc = prev.get(T_CLOSE)
        p10 = cur.get(T_OPEN_END)
        p1400 = cur.get(T_PEN_START)
        p1430 = cur.get(T_PEN_END)
        p1500 = cur.get(T_CLOSE)
        if not all((pc, p10, p1400, p1430, p1500)):
            continue
        out.append({
            "day": days[i],
            "r_first": (p10 - pc) / pc * 100,
            "r_pen": (p1430 - p1400) / p1400 * 100,
            "r_last": (p1500 - p1430) / p1430 * 100,
        })
    return out


def ols(xs: list[float], ys: list[float]) -> tuple[float, float, float]:
    """一元回归 y = a + b·x，返回 (斜率, t值, R²)."""
    n = len(xs)
    if n < 20:
        return 0.0, 0.0, 0.0
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx <= 0:
        return 0.0, 0.0, 0.0
    sxy = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
    b = sxy / sxx
    a = my - b * mx
    resid = [ys[i] - (a + b * xs[i]) for i in range(n)]
    sse = sum(r * r for r in resid)
    sst = sum((y - my) ** 2 for y in ys)
    if n <= 2 or sse <= 0:
        return b, 0.0, 0.0
    se_b = (sse / (n - 2) / sxx) ** 0.5
    t = b / se_b if se_b > 0 else 0.0
    r2 = 1 - sse / sst if sst > 0 else 0.0
    return b, t, r2


def strategy(days: list[dict], mode: str, fee: float) -> dict:
    """M1: 只看 r_first 符号；M2: r_first 与 r_pen 同向才做."""
    rets = []
    for d in days:
        rf, rp, rl = d["r_first"], d["r_pen"], d["r_last"]
        if mode == "M1":
            sig = 1 if rf > 0 else (-1 if rf < 0 else 0)
        elif mode == "M2":
            if rf > 0 and rp > 0:
                sig = 1
            elif rf < 0 and rp < 0:
                sig = -1
            else:
                sig = 0
        elif mode == "M3":                    # 只做多，早盘涨才买
            sig = 1 if rf > 0 else 0
        elif mode == "M4":                    # 只做多，双条件
            sig = 1 if (rf > 0 and rp > 0) else 0
        elif mode == "M5":                    # 反向：早盘跌才买（低吸）
            sig = 1 if rf < 0 else 0
        else:
            sig = 0
        if sig == 0:
            continue
        rets.append(sig * rl - fee)

    if not rets:
        return {"n": 0, "total": 0.0, "avg": 0.0, "win": 0.0, "t": 0.0}
    n = len(rets)
    total = sum(rets)
    avg = total / n
    sd = (sum((r - avg) ** 2 for r in rets) / (n - 1)) ** 0.5 if n > 1 else 0.0
    return {
        "n": n, "total": total, "avg": avg,
        "win": sum(1 for r in rets if r > 0) / n * 100,
        "t": (avg / (sd / n ** 0.5)) if sd > 0 else 0.0,
        "rets": rets,
    }


def main() -> None:
    src = sys.argv[1] if len(sys.argv) > 1 else "etf"
    if src == "etf":
        raw = pickle.loads((CACHE / "etf_5m_365d.pkl").read_bytes())
        fee, names = FEE, {c: c for c in raw}
        try:
            from watcher.config import Config
            names = {i.code: i.name for i in Config.load().watchlist}
        except Exception:  # noqa: BLE001
            pass
    else:
        raw = pickle.loads((CACHE / "stocks_5m_180d.pkl").read_bytes())
        fee = 0.10      # 个股含印花税
        names = {c: c for c in raw}

    print(f"\n{'=' * 92}")
    print(f"市场日内动量检验 (Gao et al. 2018) · {src} · 双边成本 {fee}%")
    print("=" * 92)

    # ---- 1. 预测性回归 ----
    print(f"\n--- 预测性回归 r_last ~ r_first ---")
    print(f"{'标的':<20}{'天数':<7}{'斜率':<10}{'t值':<9}{'R²':<9}{'r_pen斜率':<11}{'t值'}")
    print("-" * 92)
    pool: list[dict] = []
    for code, bars in raw.items():
        days = build_days(bars)
        if len(days) < 30:
            print(f"{names.get(code, code):<20}数据不足({len(days)})")
            continue
        pool.extend(days)
        b1, t1, r2 = ols([d["r_first"] for d in days], [d["r_last"] for d in days])
        b2, t2, _ = ols([d["r_pen"] for d in days], [d["r_last"] for d in days])
        star = " *" if abs(t1) > 2 else ""
        print(f"{names.get(code, code):<20}{len(days):<7}{b1:>+8.4f}  {t1:>+7.2f}  "
              f"{r2 * 100:>6.2f}%  {b2:>+9.4f}  {t2:>+7.2f}{star}")

    if not pool:
        print("\n无有效数据")
        return

    b1, t1, r2 = ols([d["r_first"] for d in pool], [d["r_last"] for d in pool])
    b2, t2, r2b = ols([d["r_pen"] for d in pool], [d["r_last"] for d in pool])
    print("-" * 92)
    print(f"{'全样本合并':<20}{len(pool):<7}{b1:>+8.4f}  {t1:>+7.2f}  "
          f"{r2 * 100:>6.2f}%  {b2:>+9.4f}  {t2:>+7.2f}")
    print(f"\n原文基准: r_first 斜率显著为正、R²≈2%（标普500 ETF）")
    print(f"本样本  : r_first R²={r2 * 100:.2f}%  |  r_pen R²={r2b * 100:.2f}%")

    # ---- 2. 策略表现 ----
    print(f"\n--- 策略表现（14:30 入场 / 15:00 平仓，全样本池化）---")
    print(f"{'策略':<28}{'笔数':<8}{'胜率':<9}{'累计':<11}{'单笔均':<11}{'t值'}")
    print("-" * 92)
    for mode, desc in [("M1", "M1 仅看第一个半小时"),
                       ("M2", "M2 首半小时+倒二半小时同向"),
                       ("M3", "M3 只做多(r_first>0 才买)"),
                       ("M4", "M4 只做多(首+倒二均>0)"),
                       ("M5", "M5 只做多(r_first<0 才买/反向)")]:
        r = strategy(pool, mode, fee)
        if r["n"] == 0:
            print(f"{desc:<28}无交易")
            continue
        print(f"{desc:<28}{r['n']:<8}{r['win']:>5.1f}%   {r['total']:>+8.2f}%  "
              f"{r['avg']:>+8.4f}%  {r['t']:>+6.2f}")

    # 基准：无条件做多最后半小时（同样扣费，保证口径一致）
    bh = [d["r_last"] - fee for d in pool]
    n = len(bh)
    avg = sum(bh) / n
    sd = (sum((x - avg) ** 2 for x in bh) / (n - 1)) ** 0.5
    print(f"{'基准 无条件做多末半小时':<28}{n:<8}"
          f"{sum(1 for x in bh if x > 0) / n * 100:>5.1f}%   {sum(bh):>+8.2f}%  "
          f"{avg:>+8.4f}%  {avg / (sd / n ** 0.5):>+6.2f}")
    print("\n注：以上全部已扣双边成本；t 值 > 2 才有统计意义")

    # 毛收益对比（看信号本身的信息量，剔除成本影响）
    print(f"\n--- 毛收益（未扣费，衡量信号本身）---")
    gross_bh = sum(d["r_last"] for d in pool) / len(pool)
    print(f"{'无条件做多':<28}{gross_bh:>+8.4f}%")
    for mode, desc in [("M3", "只做多(r_first>0)"), ("M4", "只做多(首+倒二均>0)")]:
        r = strategy(pool, mode, 0.0)
        if r["n"]:
            lift = r["avg"] / gross_bh if gross_bh > 0 else 0
            print(f"{desc:<28}{r['avg']:>+8.4f}%   （基准的 {lift:.2f} 倍）")

    # ---- 3. 末半小时漂移的按月稳定性 ----
    by_month: dict[str, list[float]] = {}
    for d in pool:
        by_month.setdefault(d["day"][:6], []).append(d["r_last"])
    print(f"\n--- 末半小时收益按月（无条件做多，未扣费）---")
    print(f"{'月份':<10}{'天数':<8}{'平均':<11}{'合计':<11}{'上涨占比'}")
    pos_m = 0
    for m in sorted(by_month):
        v = by_month[m]
        a = sum(v) / len(v)
        pos_m += 1 if a > 0 else 0
        print(f"{m[:4]}-{m[4:]:<5}{len(v):<8}{a:>+8.4f}%  {sum(v):>+8.2f}%  "
              f"{sum(1 for x in v if x > 0) / len(v) * 100:>5.1f}%")
    print(f"平均为正的月份: {pos_m}/{len(by_month)}")

    # ---- 4. 分组：按 r_first 分档看末半小时收益 ----
    print(f"\n--- 按早盘涨跌分档，看末半小时平均收益 ---")
    buckets = [("早盘大跌 <-1%", lambda r: r < -1),
               ("早盘小跌 -1~0%", lambda r: -1 <= r < 0),
               ("早盘小涨 0~1%", lambda r: 0 <= r < 1),
               ("早盘大涨 >1%", lambda r: r >= 1)]
    print(f"{'分档':<18}{'天数':<8}{'末半小时均值':<14}{'上涨占比'}")
    for label, fn in buckets:
        v = [d["r_last"] for d in pool if fn(d["r_first"])]
        if not v:
            continue
        print(f"{label:<18}{len(v):<8}{sum(v) / len(v):>+10.4f}%    "
              f"{sum(1 for x in v if x > 0) / len(v) * 100:>5.1f}%")


if __name__ == "__main__":
    main()
