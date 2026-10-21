"""下载 watchlist 全部 ETF 的 5 分钟线到缓存（Tushare 官方直连）."""
from __future__ import annotations

import pickle
import sys
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from watcher.config import Config
from watcher.fetchers.tushare_src import TushareClient, to_ts_fund_code
from watcher.models import MinuteBar

CACHE = Path(__file__).resolve().parent / ".cache"


def fetch(client: TushareClient, ts_code: str, code: str, days: int) -> list[MinuteBar]:
    today = date.today()
    stop = today - timedelta(days=days)
    bars: list[MinuteBar] = []
    seen: set[str] = set()
    cursor = today
    while cursor > stop:
        seg = max(stop, cursor - timedelta(days=25))
        rows = client.call(
            "stk_mins",
            {"ts_code": ts_code, "freq": "5min",
             "start_date": f"{seg.strftime('%Y-%m-%d')} 09:00:00",
             "end_date": f"{cursor.strftime('%Y-%m-%d')} 15:00:00"},
            "trade_time,open,high,low,close,vol",
        )
        if not rows and client.last_error:
            print(f"    {seg}~{cursor}: {client.last_error}")
        for r in rows:
            t = str(r.get("trade_time") or "")
            if len(t) < 19 or t in seen:
                continue
            seen.add(t)
            try:
                close = float(r.get("close") or 0)
                if close <= 0:
                    continue
                bars.append(MinuteBar(
                    code=code, source="tushare_mins",
                    ts=t[:4] + t[5:7] + t[8:10] + t[11:13] + t[14:16] + t[17:19],
                    open=float(r.get("open") or 0) or close,
                    high=float(r.get("high") or 0) or close,
                    low=float(r.get("low") or 0) or close,
                    close=close, volume=int(float(r.get("vol") or 0)),
                ))
            except (TypeError, ValueError):
                continue
        cursor = seg
        time.sleep(0.3)
    bars.sort(key=lambda b: b.ts)
    return bars


def main() -> None:
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 365
    CACHE.mkdir(exist_ok=True)
    cfg = Config.load()
    client = TushareClient()
    print(f"数据源: {client.api_url} | 近 {days} 天 5 分钟线")

    out: dict[str, list[MinuteBar]] = {}
    for item in cfg.watchlist:
        ts_code = to_ts_fund_code(item.code)
        if not ts_code:
            print(f"  {item.code} 代码转换失败，跳过")
            continue
        bars = fetch(client, ts_code, item.code, days)
        out[item.code] = bars
        print(f"  {item.name:<16}{item.code}  {len(bars):>6} 根 / "
              f"{len({b.ts[:8] for b in bars})} 日")

    path = CACHE / f"etf_5m_{days}d.pkl"
    path.write_bytes(pickle.dumps(out))
    print(f"\n已保存 {path.name}（{sum(len(v) for v in out.values())} 根）")


if __name__ == "__main__":
    main()
