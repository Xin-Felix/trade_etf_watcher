"""东方财富行情 Fetcher（备用快照源 + 分钟 K 线）."""
from __future__ import annotations

import time

import httpx

from watcher.fetchers.base import Fetcher, FetchResult
from watcher.models import MinuteBar, Quote


class EastMoneyFetcher(Fetcher):
    name = "eastmoney"

    def __init__(self, timeout: float = 8.0):
        self.timeout = timeout
        self.client = httpx.Client(
            timeout=timeout,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                "Referer": "https://quote.eastmoney.com/",
            },
        )

    def fetch(self, codes: list[str]) -> FetchResult:
        """逐只拉取实时快照（仅作为 TDX 全挂时的兜底）."""
        quotes: dict[str, Quote] = {}
        for code in codes:
            quote = self._fetch_one(code)
            if quote:
                quotes[code] = quote
            time.sleep(0.15)  # 限速，避免被东财拒绝
        return FetchResult(
            quotes=quotes,
            source=self.name,
            success=bool(quotes),
            error="" if quotes else "eastmoney returned empty",
        )

    def _fetch_one(self, code: str) -> Quote | None:
        secid = self._to_secid(code)
        if not secid:
            return None
        url = (
            "https://push2.eastmoney.com/api/qt/stock/get"
            f"?secid={secid}&fields=f43,f44,f45,f46,f57,f58,f60,f47"
        )
        try:
            resp = self.client.get(url)
            resp.raise_for_status()
            data = resp.json().get("data") or {}
        except Exception:  # noqa: BLE001
            return None

        try:
            # ETF ÷1000，指数 ÷100
            scale = 100.0 if code[2:].startswith(("000", "399")) else 1000.0
            price = float(data.get("f43", 0)) / scale
            if price <= 0:
                return None
            return Quote(
                code=code,
                name=data.get("f58") or code,
                price=price,
                open=float(data.get("f46", 0)) / scale,
                high=float(data.get("f44", 0)) / scale,
                low=float(data.get("f45", 0)) / scale,
                prev_close=float(data.get("f60", 0)) / scale,
                volume=int(data.get("f47") or 0),
                ts=time.strftime("%Y%m%d%H%M%S"),
                source=self.name,
            )
        except (ValueError, TypeError):
            return None

    def fetch_minute_bars(self, code: str, limit: int = 120) -> list[MinuteBar]:
        secid = self._to_secid(code)
        if not secid:
            return []
        url = (
            "https://push2his.eastmoney.com/api/qt/stock/kline/get"
            f"?secid={secid}&fields1=f1&fields2=f51,f52,f53,f54,f55,f56,f57"
            f"&klt=1&fqt=0&end=20500101&lmt={limit}"
        )
        try:
            resp = self.client.get(url)
            resp.raise_for_status()
            data = resp.json()
        except Exception:  # noqa: BLE001
            return []

        klines = data.get("data", {}).get("klines", []) or []
        bars: list[MinuteBar] = []
        for line in klines:
            # 格式: date,open,close,low,high,volume,amount,...
            parts = line.split(",")
            if len(parts) < 6:
                continue
            try:
                bars.append(
                    MinuteBar(
                        code=code,
                        ts=parts[0].replace("-", "").replace(":", "").replace(" ", ""),
                        open=float(parts[1]),
                        close=float(parts[2]),
                        low=float(parts[3]),
                        high=float(parts[4]),
                        volume=int(float(parts[5])),
                        source=self.name,
                    )
                )
            except (ValueError, IndexError):
                continue
        return bars

    def _to_secid(self, code: str) -> str:
        if code.startswith("sh"):
            return f"1.{code[2:]}"
        if code.startswith("sz"):
            return f"0.{code[2:]}"
        return ""

    def close(self) -> None:
        self.client.close()
