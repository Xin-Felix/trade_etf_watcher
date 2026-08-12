"""冒烟：Tushare 真实拉取（期权历史日K / ETF日K / 交易日历）并落地 SQLite.

用法：PYTHONPATH=. python scripts/smoke_tushare.py
需要 ~/.config/etf_watcher/secrets.env 里的 TUSHARE_TOKEN（或环境变量）。
"""
from __future__ import annotations

from datetime import datetime

from watcher import calendar as cal
from watcher.fetchers.tushare_src import get_client, is_available
from watcher.state import StateStore


def main() -> int:
    if not is_available():
        print("未配置 TUSHARE_TOKEN（~/.config/etf_watcher/secrets.env），跳过")
        return 1

    store = StateStore()
    c = get_client()
    fails: list[str] = []

    # 1. 交易日历
    print("=== 交易日历 ===")
    dates = c.fetch_trade_dates_around_today(back_days=60, forward_days=180)
    if not dates:
        fails.append(f"交易日历为空：{c.last_error}")
    else:
        n = store.save_trade_dates(dates)
        print(f"拉到 {len(dates)} 个交易日（{dates[0]} ~ {dates[-1]}），落库 {n} 条")
        today = datetime.now().strftime("%Y%m%d")
        cal.set_trade_day_checker(store.is_trade_date)
        print(f"今天 {today} 是交易日: {store.is_trade_date(today)}；"
              f"is_trading_day={cal.is_trading_day()}  is_polling_hours={cal.is_polling_hours()}")
        # 抽查国庆
        oct_days = [d for d in dates if d.startswith("202610") and d <= "20261008"]
        print(f"10/1~10/8 之间的交易日: {oct_days or '无（假期正确）'}")

    # 2. 期权历史日 K（挑一个 DB 里真实存在的合约）
    print("\n=== 期权历史日 K ===")
    contracts = []
    for u in store.option_underlyings():
        contracts = store.get_option_contracts(u)
        if contracts:
            break
    if not contracts:
        print("DB 里没有期权合约，先跑一次 python -m watcher")
    else:
        code = contracts[len(contracts) // 2].option_code
        bars = c.fetch_option_daily(code, limit=250)
        if not bars:
            fails.append(f"期权日K为空({code})：{c.last_error}")
        else:
            print(f"{code}: {len(bars)} 根日K（{bars[0].ts[:8]} ~ {bars[-1].ts[:8]}）")
            for b in bars[-3:]:
                print(f"   {b.ts[:8]} O={b.open} H={b.high} L={b.low} C={b.close} V={b.volume}")
            bad = [b for b in bars if b.high < max(b.open, b.close) or b.low > min(b.open, b.close)]
            if bad:
                fails.append(f"{len(bad)} 根日K 的 high/low 越界")
            store.save_bars(bars, datetime.now().strftime("%Y-%m-%d"))
            print(f"   已落库；DB 内该合约 tushare 日K 共 "
                  f"{len(store.get_option_bars(code, limit=500, source='tushare_option_daily'))} 根")

    # 3. ETF 日 K
    print("\n=== ETF 日 K ===")
    etf = c.fetch_fund_daily("sh510300", limit=10)
    if not etf:
        fails.append(f"ETF日K为空：{c.last_error}")
    else:
        print(f"sh510300: {len(etf)} 根，最近一根 "
              f"{etf[-1].ts[:8]} C={etf[-1].close} V={etf[-1].volume}")

    print("\n" + "=" * 56)
    if fails:
        print(f"失败 {len(fails)} 项：")
        for f in fails:
            print(f"  - {f}")
        return 1
    print("Tushare 三个接口全部正常，数据已落地 SQLite")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
