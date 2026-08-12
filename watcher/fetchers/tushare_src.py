"""Tushare 数据源：期权历史日 K、ETF 日 K、交易日历.

用途（补现有免费源的短板）：
- `opt_daily`：期权历史日线，**真实 OHLC + 持仓量 + 昨结算**，补东财 kline 被封留下的缺口
- `trade_cal`：交易日历，节假日不轮询
- `fund_daily`：ETF 日线兜底

约定：
- token 从 `~/.config/etf_watcher/secrets.env` 或环境变量 `TUSHARE_TOKEN` 读，**不放项目目录**
- 代码格式要转换：库里是 `10012055` / `sh510300`，Tushare 用 `10012055.SH` / `510300.SH`
- 任何失败都返回空（不抛异常），调用方走原有降级链；无 token 时整个模块静默禁用
"""
from __future__ import annotations

import os
import time
from datetime import date, timedelta
from pathlib import Path

import httpx

from watcher.models import MinuteBar

API_URL = "https://api.tushare.pro"
SECRETS_PATH = Path.home() / ".config" / "etf_watcher" / "secrets.env"


def _read_secret(key: str) -> str:
    """读 secrets.env / 环境变量里的配置项（环境变量优先）."""
    env = os.environ.get(key, "").strip()
    if env:
        return env
    if SECRETS_PATH.exists():
        try:
            for line in SECRETS_PATH.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                if k.strip() == key:
                    return v.strip().strip("\"'")
        except OSError:
            return ""
    return ""

# 免费额度有限，接口调用之间留最小间隔（秒）
_MIN_INTERVAL = 0.35
_last_call = 0.0

# 交易所后缀：沪市期权 10 开头、深市期权 90 开头
_OPT_SUFFIX = {"10": "SH", "90": "SZ"}


def load_token() -> str:
    """读 token：环境变量优先，其次 secrets.env."""
    return _read_secret("TUSHARE_TOKEN")


def is_available() -> bool:
    """有官方 token 或代理配置任一即可用."""
    if load_token():
        return True
    return bool(_read_secret("TUSHARE_PROXY_URL") and _read_secret("TUSHARE_PROXY_TOKEN"))


def to_ts_option_code(option_code: str) -> str:
    """`10012055` -> `10012055.SH`；`90000123` -> `90000123.SZ`."""
    code = (option_code or "").strip()
    if not code.isdigit() or len(code) != 8:
        return ""
    suffix = _OPT_SUFFIX.get(code[:2])
    return f"{code}.{suffix}" if suffix else ""


def to_ts_fund_code(code: str) -> str:
    """`sh510300` -> `510300.SH`；`sz159915` -> `159915.SZ`."""
    c = (code or "").strip().lower()
    if c.startswith("sh"):
        return f"{c[2:]}.SH"
    if c.startswith("sz"):
        return f"{c[2:]}.SZ"
    return ""


class TushareClient:
    """极简 Tushare HTTP 客户端（同步、带限速、失败即空）."""

    def __init__(self, token: str | None = None, timeout: float = 20.0,
                 use_proxy: bool | None = None):
        """use_proxy 默认自动：显式传入 token 时不走代理（尊重调用方指定）.

        代理（TUSHARE_PROXY_URL/TOKEN）为高积分账号，支持分钟线等高级接口。
        """
        if use_proxy is None:
            # 显式传 token（含空串，用于"无凭证"场景）时不启用代理
            use_proxy = token is None
        proxy_url = _read_secret("TUSHARE_PROXY_URL") if use_proxy else ""
        proxy_token = _read_secret("TUSHARE_PROXY_TOKEN") if use_proxy else ""
        if proxy_url and proxy_token:
            self.api_url = proxy_url.rstrip("/")
            self.token = proxy_token
            self.via_proxy = True
        else:
            self.api_url = API_URL
            self.token = token if token is not None else load_token()
            self.via_proxy = False
        self.timeout = timeout
        self._client: httpx.Client | None = None
        self.last_error = ""

    def _http(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=self.timeout)
        return self._client

    def call(self, api_name: str, params: dict, fields: str = "") -> list[dict]:
        """调接口，返回 dict 行列表；失败返回 []（错误信息在 last_error）."""
        global _last_call
        if not self.token:
            self.last_error = "未配置 TUSHARE_TOKEN"
            return []

        gap = time.monotonic() - _last_call
        if gap < _MIN_INTERVAL:
            time.sleep(_MIN_INTERVAL - gap)
        _last_call = time.monotonic()

        payload = {"api_name": api_name, "token": self.token, "params": params, "fields": fields}
        try:
            resp = self._http().post(self.api_url, json=payload)
            resp.raise_for_status()
            body = resp.json()
        except Exception as exc:  # noqa: BLE001
            self.last_error = f"{api_name} 请求失败: {exc}"
            return []

        if body.get("code") != 0:
            # 常见：积分不足 / 频率超限 / token 失效
            self.last_error = f"{api_name}: {body.get('msg', '')}"
            return []

        data = body.get("data") or {}
        cols = data.get("fields") or []
        rows = data.get("items") or []
        self.last_error = ""
        return [dict(zip(cols, r)) for r in rows]

    # ---------- 期权历史日 K ----------

    def fetch_option_daily(
        self, option_code: str, start_date: str = "", end_date: str = "", limit: int = 250
    ) -> list[MinuteBar]:
        """期权历史日线（真实 OHLC）。ts 统一补成 `YYYYMMDD150000`，升序返回."""
        ts_code = to_ts_option_code(option_code)
        if not ts_code:
            return []
        params: dict = {"ts_code": ts_code}
        if start_date:
            params["start_date"] = start_date.replace("-", "")
        if end_date:
            params["end_date"] = end_date.replace("-", "")
        rows = self.call(
            "opt_daily", params,
            "trade_date,open,high,low,close,vol,oi,pre_settle",
        )
        bars: list[MinuteBar] = []
        for r in rows:
            try:
                d = str(r.get("trade_date") or "").replace("-", "")
                if len(d) != 8 or not d.isdigit():
                    continue
                close = float(r.get("close") or 0)
                if close <= 0:
                    continue
                open_ = float(r.get("open") or 0) or close
                high = float(r.get("high") or 0) or close
                low = float(r.get("low") or 0) or close
                bars.append(MinuteBar(
                    code=option_code,
                    ts=d + "150000",
                    open=open_,
                    high=max(high, open_, close),
                    low=min(low, open_, close) if low > 0 else min(open_, close),
                    close=close,
                    volume=int(float(r.get("vol") or 0)),
                    source="tushare_option_daily",
                ))
            except (TypeError, ValueError):
                continue
        bars.sort(key=lambda b: b.ts)
        return bars[-limit:] if limit else bars

    # ---------- ETF 日 K ----------

    def fetch_fund_daily(
        self, code: str, start_date: str = "", end_date: str = "", limit: int = 250
    ) -> list[MinuteBar]:
        """ETF 历史日线（TDX 日K 的兜底源）."""
        ts_code = to_ts_fund_code(code)
        if not ts_code:
            return []
        params: dict = {"ts_code": ts_code}
        if start_date:
            params["start_date"] = start_date.replace("-", "")
        if end_date:
            params["end_date"] = end_date.replace("-", "")
        rows = self.call("fund_daily", params, "trade_date,open,high,low,close,vol")
        bars: list[MinuteBar] = []
        for r in rows:
            try:
                d = str(r.get("trade_date") or "").replace("-", "")
                if len(d) != 8 or not d.isdigit():
                    continue
                close = float(r.get("close") or 0)
                if close <= 0:
                    continue
                bars.append(MinuteBar(
                    code=code,
                    ts=d + "150000",
                    open=float(r.get("open") or 0) or close,
                    high=float(r.get("high") or 0) or close,
                    low=float(r.get("low") or 0) or close,
                    close=close,
                    # fund_daily 的 vol 单位是手，×100 换成股，与 TDX 口径一致
                    volume=int(float(r.get("vol") or 0) * 100),
                    source="tushare_daily",
                ))
            except (TypeError, ValueError):
                continue
        bars.sort(key=lambda b: b.ts)
        return bars[-limit:] if limit else bars

    # ---------- 交易日历 ----------

    def fetch_trade_dates(self, start_date: str, end_date: str) -> list[str]:
        """返回区间内的**交易日**列表（YYYYMMDD，升序）."""
        rows = self.call(
            "trade_cal",
            {
                "exchange": "SSE",
                "start_date": start_date.replace("-", ""),
                "end_date": end_date.replace("-", ""),
            },
            "cal_date,is_open",
        )
        out = []
        for r in rows:
            try:
                if int(r.get("is_open") or 0) == 1:
                    d = str(r.get("cal_date") or "").replace("-", "")
                    if len(d) == 8 and d.isdigit():
                        out.append(d)
            except (TypeError, ValueError):
                continue
        return sorted(out)

    def fetch_trade_dates_around_today(self, back_days: int = 30, forward_days: int = 120) -> list[str]:
        today = date.today()
        return self.fetch_trade_dates(
            (today - timedelta(days=back_days)).strftime("%Y%m%d"),
            (today + timedelta(days=forward_days)).strftime("%Y%m%d"),
        )

    def close(self) -> None:
        if self._client is not None:
            try:
                self._client.close()
            except Exception:  # noqa: BLE001
                pass
            self._client = None


# 模块级单例（GUI 与轮询线程共用；httpx.Client 本身线程安全）
_client: TushareClient | None = None


def get_client() -> TushareClient:
    global _client
    if _client is None:
        _client = TushareClient()
    return _client
