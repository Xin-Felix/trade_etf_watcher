"""权重扫描：形态命中只算一次并缓存，再用不同权重/阈值配置快速对比.

形态检测与权重无关，所以可以先把每根 bar 命中的形态名缓存下来，
之后换权重配置只需重新打分，避免 O(n²) 的特征计算重复跑。

用法:
    python scripts/sweep_patterns.py           # 1分
    python scripts/sweep_patterns.py 5         # 5分
    python scripts/sweep_patterns.py 1 rebuild # 强制重算缓存
"""
from __future__ import annotations

import pickle
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from watcher.bars import aggregate_minute_bars
from watcher.config import Config
from watcher.signals import patterns as P
from watcher.state import StateStore

MIN_START = 12
CACHE_DIR = Path(__file__).resolve().parent / ".cache"

# 单边手续费（万2.5），一买一卖 = 2 倍
FEE_ONE_WAY = 0.025


def load_days(store: StateStore) -> list[str]:
    with sqlite3.connect(store.db_path) as conn:
        rows = conn.execute(
            "SELECT DISTINCT substr(ts,1,8) d FROM minute_bars "
            "WHERE length(code) <= 8 AND code NOT GLOB '[0-9]*' ORDER BY d"
        ).fetchall()
    return [r[0] for r in rows]


def build_cache(period: int) -> list[dict]:
    """逐 bar 跑一次形态检测，缓存命中的形态名."""
    cfg, store = Config.load(), StateStore()
    days, codes = load_days(store), cfg.watch_codes()
    out: list[dict] = []
    for code in codes:
        raw = store.get_bars(code, limit=6000)
        for day in days:
            db = [b for b in raw if b.ts[:8] == day]
            if len(db) < 30:
                continue
            bars = db if period == 1 else aggregate_minute_bars(db, period)
            if len(bars) < MIN_START + 2:
                continue
            seq = []
            for i in range(MIN_START, len(bars) + 1):
                r = P.detect_patterns(bars[:i], period)
                seq.append((bars[i - 1].ts, bars[i - 1].close, r.hits))
            out.append({"code": code, "day": day, "seq": seq,
                        "last_close": bars[-1].close})
        print(f"  缓存 {code} 完成", flush=True)
    return out


def get_cache(period: int, rebuild: bool = False) -> list[dict]:
    CACHE_DIR.mkdir(exist_ok=True)
    path = CACHE_DIR / f"hits_{period}m.pkl"
    if path.exists() and not rebuild:
        return pickle.loads(path.read_bytes())
    print(f"构建 {period}分 形态缓存（首次较慢）...")
    data = build_cache(period)
    path.write_bytes(pickle.dumps(data))
    return data


def evaluate(cache: list[dict], weights: dict[str, int],
             buy_thr: int, sell_thr: int, veto: set[str]) -> dict:
    """按给定权重配置重新打分并配对（已扣双边手续费）."""
    trades: list[dict] = []
    for item in cache:
        pos = None
        for ts, px, hits in item["seq"]:
            score = sum(weights.get(h, 0) for h in hits)
            direction = None
            if score >= buy_thr and not (veto & set(hits)):
                direction = "long"
            elif score <= sell_thr:
                direction = "short"

            if direction == "long" and pos is None:
                pos = (px, hits)
            elif direction == "short" and pos is not None:
                trades.append({
                    "pnl": (px - pos[0]) / pos[0] * 100 - FEE_ONE_WAY * 2,
                    "hits": pos[1], "day": item["day"],
                })
                pos = None
        if pos is not None:
            trades.append({
                "pnl": (item["last_close"] - pos[0]) / pos[0] * 100 - FEE_ONE_WAY * 2,
                "hits": pos[1], "day": item["day"],
            })

    if not trades:
        return {"n": 0, "win_rate": 0, "total": 0, "avg": 0,
                "per_hit": {}, "per_day": {}, "pf": 0}
    per_hit: dict[str, list[float]] = {}
    for t in trades:
        for h in t["hits"]:
            per_hit.setdefault(h, []).append(t["pnl"])
    n = len(trades)
    wins = [t["pnl"] for t in trades if t["pnl"] > 0]
    loss_sum = abs(sum(t["pnl"] for t in trades if t["pnl"] <= 0))
    total = sum(t["pnl"] for t in trades)
    per_day: dict[str, float] = {}
    for t in trades:
        per_day[t["day"]] = per_day.get(t["day"], 0.0) + t["pnl"]
    return {
        "n": n, "win_rate": len(wins) / n * 100, "total": total,
        "avg": total / n, "per_hit": per_hit, "per_day": per_day,
        "pf": (sum(wins) / loss_sum) if loss_sum > 0 else float("inf"),
    }


# 待对比的配置：名称 → (权重表, 买阈值, 卖阈值)
BEAR = {
    "放量滞涨见顶": -3, "巨量见顶": -3, "高位长上影": -3,
    "冲高回落": -3, "高位破位": -3, "放量破位": -3,
    "量价背离": -2, "跳空回补": -2,
}
VETO = {"放量滞涨见顶", "巨量见顶", "高位长上影", "量价背离"}


def _cfg(bull: dict[str, int], buy: int = 3, sell: int = -3) -> tuple:
    return ({**bull, **BEAR}, buy, sell)


CONFIGS: dict[str, tuple] = {
    "A 当前配置": _cfg({
        "量爆跟随": 3, "探底回升": 3, "量堆积启动": 3, "挤压突破": 3,
        "缩量回调反包": 2, "洗盘拉回": 2, "跳空不回补": 2,
    }),
    "B 去掉探底回升": _cfg({
        "量爆跟随": 3, "探底回升": 0, "量堆积启动": 3, "挤压突破": 3,
        "缩量回调反包": 2, "洗盘拉回": 2, "跳空不回补": 2,
    }),
    "C 去掉探底+挤压": _cfg({
        "量爆跟随": 3, "探底回升": 0, "量堆积启动": 3, "挤压突破": 0,
        "缩量回调反包": 2, "洗盘拉回": 2, "跳空不回补": 2,
    }),
    "D 探底/挤压降为辅助(2分)": _cfg({
        "量爆跟随": 3, "探底回升": 2, "量堆积启动": 3, "挤压突破": 2,
        "缩量回调反包": 2, "洗盘拉回": 2, "跳空不回补": 2,
    }),
    "E 只保留量爆跟随": _cfg({
        "量爆跟随": 3, "探底回升": 0, "量堆积启动": 0, "挤压突破": 0,
        "缩量回调反包": 0, "洗盘拉回": 0, "跳空不回补": 0,
    }),
    "F 量爆跟随+量堆积": _cfg({
        "量爆跟随": 3, "探底回升": 0, "量堆积启动": 3, "挤压突破": 0,
        "缩量回调反包": 0, "洗盘拉回": 0, "跳空不回补": 0,
    }),
    "G C配置+买阈值4(需共振)": _cfg({
        "量爆跟随": 3, "探底回升": 2, "量堆积启动": 3, "挤压突破": 2,
        "缩量回调反包": 2, "洗盘拉回": 2, "跳空不回补": 2,
    }, buy=4),
}


def main() -> None:
    period = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    rebuild = len(sys.argv) > 2 and sys.argv[2] == "rebuild"
    cache = get_cache(period, rebuild)
    days = sorted({i["day"] for i in cache})

    print(f"\n{'=' * 84}")
    print(f"权重配置对比 · {period}分 · {len(days)} 日 · {len(cache)} 个(标的×日) "
          f"· 已扣双边手续费 {FEE_ONE_WAY * 2:.2f}%")
    print("=" * 84)
    print(f"\n{'配置':<26}{'笔数':<7}{'胜率':<9}{'累计':<11}{'单笔均':<10}{'盈亏比'}")
    print("-" * 84)
    results = {}
    for name, (w, buy, sell) in CONFIGS.items():
        r = evaluate(cache, w, buy, sell, VETO)
        results[name] = r
        if r["n"] == 0:
            print(f"{name:<26}无交易")
            continue
        pf = "∞" if r["pf"] == float("inf") else f"{r['pf']:.2f}"
        print(f"{name:<26}{r['n']:<7}{r['win_rate']:>5.1f}%   "
              f"{r['total']:>+8.2f}%  {r['avg']:>+7.3f}%   {pf}")

    best = max((k for k in results if results[k]["n"]),
               key=lambda k: results[k]["total"])
    print(f"\n累计收益最好: {best}")
    r = results[best]
    print(f"\n【{best}】按日收益:")
    for d in days:
        v = r["per_day"].get(d, 0.0)
        print(f"  {d}  {v:>+8.2f}%")
    print(f"\n【{best}】按买入形态:")
    for h, pnls in sorted(r["per_hit"].items(), key=lambda x: -len(x[1])):
        if h in BEAR:
            continue
        n = len(pnls)
        win = sum(1 for p in pnls if p > 0)
        print(f"  {h:<16}{n:>4}次  胜率{win / n * 100:>5.1f}%  "
              f"均{sum(pnls) / n:>+7.3f}%")


if __name__ == "__main__":
    main()
