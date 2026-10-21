"""数据完整性体检：一眼看出今天哪些数据齐了、哪些有缺口.

用法：
  PYTHONPATH=. python scripts/diag_data_health.py

覆盖：行情快照 / 分钟 K（ETF+指数）/ 期权合约与报价 / 期权分钟 K /
今日信号 / 交易日历 / 每日期权快照。
盘中跑会按「现在应该有多少根」估算完整度，收盘后跑按 240 根算满。
"""
from __future__ import annotations

import sqlite3
import sys
from collections import Counter
from datetime import datetime

from watcher.config import Config
from watcher.state import StateStore

# A 股交易时段
SESSIONS = ((9 * 60 + 30, 11 * 60 + 30), (13 * 60, 15 * 60))
FULL_DAY_MINUTES = sum(b - a for a, b in SESSIONS)   # 240


def expected_minutes(now: datetime) -> int:
    """从开盘到 now 之间应该产生多少根 1 分钟 K."""
    cur = now.hour * 60 + now.minute
    total = 0
    for a, b in SESSIONS:
        if cur >= b:
            total += b - a
        elif cur > a:
            total += cur - a
    return total


def bar(pct: float, width: int = 18) -> str:
    n = max(0, min(width, round(pct / 100 * width)))
    return "█" * n + "·" * (width - n)


def section(title: str) -> None:
    print()
    print(f"── {title} " + "─" * max(0, 74 - len(title)))


def main() -> int:
    cfg = Config.load()
    store = StateStore()
    now = datetime.now()
    today = now.strftime("%Y%m%d")
    exp = expected_minutes(now)
    closed = exp >= FULL_DAY_MINUTES

    print("=" * 80)
    print(f"数据体检  {now:%Y-%m-%d %H:%M:%S}  "
          f"{'（已收盘）' if closed else f'（盘中，开盘至今应有 {exp} 根 1 分 K）'}")
    print("=" * 80)

    con = sqlite3.connect(store.db_path)
    con.row_factory = sqlite3.Row

    problems: list[str] = []
    warnings: list[str] = []

    # ---------- 1. 行情快照 ----------
    section("1. 行情快照（每轮轮询覆盖全部标的+指数）")
    quotes = store.latest_quotes()
    codes = cfg.all_quote_codes()
    stale = []
    print(f"{'代码':10s} {'名称':16s} {'最新价':>9s} {'涨跌幅':>8s} {'快照时间':>10s}  状态")
    for c in codes:
        q = quotes.get(c)
        if not q:
            print(f"{c:10s} {cfg.name_for(c):16s} {'—':>9s} {'—':>8s} {'—':>10s}  ✗ 无快照")
            problems.append(f"{c} 无行情快照")
            continue
        pct = ((q.price - q.prev_close) / q.prev_close * 100) if q.prev_close else None
        ts = (q.ts or "")[-8:] or "—"
        ok = q.price > 0
        if not ok:
            problems.append(f"{c} 快照价格为 0")
        print(f"{c:10s} {cfg.name_for(c):16s} {q.price:9.3f} "
              f"{(f'{pct:+.2f}%' if pct is not None else '—'):>8s} {ts:>10s}  "
              f"{'✓' if ok else '✗ 价格为0'}")
    print(f"  → {len(quotes)}/{len(codes)} 个标的有快照")

    # ---------- 2. 分钟 K ----------
    section("2. 今日分钟 K 线（信号检测与 K 线图的数据源）")
    print(f"{'类别':5s} {'代码':10s} {'名称':16s} {'今日根数':>7s} {'完整度':>7s} "
          f"{'进度':20s} {'最后时间':>8s}")
    idx_codes = set(cfg.index_codes())
    rows = con.execute(
        "SELECT code, COUNT(*) n, MAX(ts) last FROM minute_bars "
        "WHERE substr(ts,1,8)=? GROUP BY code", (today,)).fetchall()
    got = {r["code"]: (r["n"], r["last"]) for r in rows}
    for c in codes:
        n, last = got.get(c, (0, ""))
        pct = min(100.0, n / exp * 100) if exp else 0.0
        kind = "指数" if c in idx_codes else "ETF"
        hhmm = f"{last[8:10]}:{last[10:12]}" if len(last) >= 12 else "—"
        flag = ""
        if n == 0:
            flag = " ✗ 无数据"
            problems.append(f"{c} 今日无分钟 K")
        elif pct < 80:
            flag = " ⚠ 偏少"
            warnings.append(f"{c} 今日分钟 K 只有 {n}/{exp} 根")
        print(f"{kind:5s} {c:10s} {cfg.name_for(c):16s} {n:7d} {pct:6.0f}% "
              f"{bar(pct):20s} {hhmm:>8s}{flag}")

    # 脏数据分两类，成因不同别混在一起看：
    #  - 负价 / 年份异常：指数取数用错 API 的产物（2026-09 已修，改用 get_index_bars）
    #  - 全零 bar：新浪期权零成交分钟返回 p=0（2026-09 已修，解析时丢弃）
    print()
    neg = con.execute(
        "SELECT code, COUNT(*) n FROM minute_bars "
        "WHERE close < 0 OR substr(ts,1,4) NOT BETWEEN '2000' AND ? GROUP BY code",
        (str(now.year),)).fetchall()
    if neg:
        print("  ⚠ 负价 / 年份异常的 bar（指数取数用错 API 的历史残留）：")
        for r in neg:
            print(f"     {r['code']} {r['n']} 行")
            problems.append(f"{r['code']} 有 {r['n']} 行负价/异常年份 bar")
    else:
        print("  ✓ 无负价、无异常年份的 bar")

    zero = con.execute(
        "SELECT COUNT(DISTINCT code) c, COUNT(*) n FROM minute_bars "
        "WHERE close = 0").fetchone()
    if zero["n"]:
        print(f"  ⚠ 全零 bar：{zero['n']} 行，涉及 {zero['c']} 个代码"
              f"（新浪期权零成交分钟；会把 K 线纵轴拉到 0）")
        problems.append(f"有 {zero['n']} 行全零 bar")
    else:
        print("  ✓ 无全零 bar")

    # ---------- 3. 期权合约与报价 ----------
    section("3. 期权合约与报价")
    n_contracts = con.execute("SELECT COUNT(*) c FROM option_contracts").fetchone()["c"]
    n_under = con.execute(
        "SELECT COUNT(DISTINCT underlying_code) c FROM option_contracts").fetchone()["c"]
    print(f"合约 {n_contracts} 个，覆盖 {n_under} 个标的")
    q = con.execute("""
        SELECT c.underlying_code u, COUNT(*) total,
               SUM(CASE WHEN q.price > 0 THEN 1 ELSE 0 END) priced,
               SUM(CASE WHEN q.option_code IS NULL THEN 1 ELSE 0 END) missing,
               MAX(q.ts) last
        FROM option_contracts c LEFT JOIN option_quotes q ON q.option_code = c.option_code
        GROUP BY c.underlying_code ORDER BY c.underlying_code""").fetchall()
    print(f"\n{'标的':10s} {'名称':16s} {'合约':>5s} {'有价':>5s} {'无报价记录':>10s} "
          f"{'覆盖率':>7s} {'最后报价':>19s}")
    for r in q:
        cov = (r["priced"] or 0) / r["total"] * 100
        print(f"{r['u']:10s} {cfg.name_for(r['u']):16s} {r['total']:5d} {r['priced'] or 0:5d} "
              f"{r['missing'] or 0:10d} {cov:6.1f}% {str(r['last'] or '—'):>19s}")
        if r["missing"]:
            problems.append(f"{r['u']} 有 {r['missing']} 个合约完全没有报价记录")
    no_opt = [i.name for i in cfg.watchlist
              if not store.get_option_contracts(i.code)]
    if no_opt:
        print(f"\n  说明：{'、'.join(no_opt)} 没有期权上市（正常，非缺数据）")
    print("  说明：price=0 但有买卖挂单的是当天零成交（深市虚值/实值档常见），非抓取失败")

    # ---------- 4. 期权分钟 K ----------
    section("4. 期权分钟 K（近价合约盘中入库，盘后东财停供时兜底）")
    orow = con.execute(
        "SELECT COUNT(DISTINCT code) c, COUNT(*) n, MAX(ts) last FROM minute_bars "
        "WHERE substr(ts,1,8)=? AND length(code)=8 AND code GLOB '[0-9]*'",
        (today,)).fetchone()
    print(f"今日有分钟 K 的期权合约：{orow['c']} 个，共 {orow['n']} 根，"
          f"最后 {orow['last'] or '—'}")
    if not orow["c"]:
        warnings.append("今日没有期权分钟 K（盘中未运行或东财受限）")

    # ---------- 5. 今日信号 ----------
    section("5. 今日信号")
    srows = con.execute(
        "SELECT code, signal_key, label, ts FROM signals WHERE date=? ORDER BY ts",
        (today,)).fetchall()
    if not srows:
        print("今日暂无信号")
    else:
        kinds = Counter()
        for r in srows:
            k = r["signal_key"]
            base = ("买卖点-买" if k.startswith("resonance_long")
                    else "买卖点-卖" if k.startswith("resonance_short")
                    else k.split("_")[0])
            kinds[base] += 1
        print(f"共 {len(srows)} 条：" + "  ".join(f"{k}×{v}" for k, v in kinds.most_common()))
        tr = [r for r in srows if r["signal_key"].startswith("resonance")]
        if tr:
            print(f"\n买卖点明细（{len(tr)} 条）：")
            print(f"  {'时间':8s} {'代码':10s} {'名称':16s} {'方向':4s} 类别")
            for r in tr:
                t = r["ts"]
                hhmm = f"{t[8:10]}:{t[10:12]}" if len(t) >= 12 else "—"
                side = "买" if "long" in r["signal_key"] else "卖"
                is_idx = r["code"] in idx_codes
                print(f"  {hhmm:8s} {r['code']:10s} {cfg.name_for(r['code']):16s} "
                      f"{side:4s} {'指数（仅查看）' if is_idx else 'ETF（含提醒）'}")

    # ---------- 6. 交易日历 & 每日期权快照 ----------
    section("6. 交易日历 / 每日期权快照")
    cal = con.execute("SELECT COUNT(*) c, MIN(cal_date) a, MAX(cal_date) b "
                      "FROM trade_calendar").fetchone()
    print(f"交易日历：{cal['c']} 个交易日（{cal['a']} ~ {cal['b']}）")
    if not cal["c"]:
        warnings.append("交易日历为空（无 Tushare token 时会退回周末判断）")
    snap = con.execute(
        "SELECT date, COUNT(*) n FROM option_daily_snapshot "
        "GROUP BY date ORDER BY date DESC LIMIT 4").fetchall()
    print("每日期权快照（收盘前 14:55 自动存）：")
    for r in snap:
        mark = "  ← 今日" if r["date"] == today else ""
        print(f"  {r['date']}  {r['n']} 条{mark}")
    if not any(r["date"] == today for r in snap):
        if now.hour * 60 + now.minute < 14 * 60 + 55:
            print(f"  今日快照未生成（14:55 才触发，现在 {now:%H:%M}）")
        else:
            warnings.append("已过 14:55 但今日期权快照未生成")

    # ---------- 汇总 ----------
    print()
    print("=" * 80)
    if problems:
        print(f"✗ 发现 {len(problems)} 个问题：")
        for p in problems[:15]:
            print(f"   - {p}")
        if len(problems) > 15:
            print(f"   … 另 {len(problems) - 15} 个")
    if warnings:
        print(f"⚠ {len(warnings)} 个提示：")
        for w in warnings[:10]:
            print(f"   - {w}")
    if not problems and not warnings:
        print("✓ 数据完整，未发现问题")
    print("=" * 80)
    con.close()
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
