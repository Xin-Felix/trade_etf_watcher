"""诊断：统计本地分钟 K 线覆盖了哪些交易日、每天多少根."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from watcher.state import StateStore


def main() -> None:
    store = StateStore()
    with sqlite3.connect(store.db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT code, substr(ts, 1, 8) AS day, COUNT(*) AS n
            FROM minute_bars
            WHERE length(code) <= 8 AND code NOT GLOB '[0-9]*'
            GROUP BY code, day
            ORDER BY day, code
            """
        ).fetchall()

    by_day: dict[str, dict[str, int]] = {}
    for r in rows:
        by_day.setdefault(r["day"], {})[r["code"]] = r["n"]

    print(f"分钟 K 线覆盖 {len(by_day)} 个交易日\n")
    print(f"{'日期':<12}{'标的数':<8}{'总根数':<10}明细（根数 < 200 的标的标注）")
    for day in sorted(by_day):
        codes = by_day[day]
        total = sum(codes.values())
        thin = [f"{c}:{n}" for c, n in sorted(codes.items()) if n < 200]
        note = ("  少数据→ " + " ".join(thin)) if thin else ""
        print(f"{day:<12}{len(codes):<8}{total:<10}{note}")


if __name__ == "__main__":
    main()
