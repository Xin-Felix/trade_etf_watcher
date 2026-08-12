"""通达信行情 Fetcher（自动并发探测最快服务器）."""
from __future__ import annotations

import socket
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from watcher.fetchers.base import Fetcher, FetchResult
from watcher.models import MinuteBar, Quote


# TDX 市场代码映射
_MARKET_MAP = {
    "sh": 1,
    "sz": 0,
}

# K 线周期 category
_BAR_CATEGORY = {
    "1min": 7,
    "5min": 0,
    "daily": 9,
}

# 内置候选服务器池（与 config 里的合并，自动并发探测选最快）
DEFAULT_TDX_SERVERS: list[tuple[str, int]] = [
    ("119.147.212.81", 7709),
    ("119.147.212.82", 7709),
    ("119.147.212.83", 7709),
    ("121.14.104.69", 7709),
    ("121.14.104.70", 7709),
    ("121.14.104.71", 7709),
    ("121.14.104.72", 7709),
    ("115.238.56.198", 7709),
    ("115.238.90.165", 7709),
    ("60.12.136.250", 7709),
    ("60.191.117.167", 7709),
    ("180.153.18.170", 7709),
    ("180.153.39.51", 7709),
    ("218.75.126.9", 7709),
    ("112.74.214.43", 7709),
    ("101.227.73.20", 7709),
    ("101.227.77.254", 7709),
    ("14.215.128.18", 7709),
    ("59.173.18.140", 7709),
    ("112.90.96.124", 7709),
    ("47.107.75.159", 7709),
    ("jstdx.gtjas.com", 7709),
    ("shtdx.gtjas.com", 7709),
    ("sztdx.gtjas.com", 7709),
]

# TCP 探测超时（秒）
_TCP_PROBE_TIMEOUT = 1.5
# pytdx 连接超时（秒）
_CONNECT_TIMEOUT = 4.0
# pytdx 单次数据请求超时（秒）—— pytdx 内部无 read timeout，
# 服务器僵死时 recv() 会永久阻塞，必须从外部掐死
_READ_TIMEOUT = 8.0
# 探测结果缓存时间（秒）
_PROBE_CACHE_SECONDS = 300
# 连接时最多尝试的服务器个数
_MAX_CONNECT_TRIES = 6


def _parse_code(code: str) -> tuple[int, str]:
    """返回 (market, pure_code)."""
    for prefix in ("sh", "sz"):
        if code.startswith(prefix):
            return _MARKET_MAP[prefix], code[len(prefix):]
    return 1, code


def _tcp_latency(host: str, port: int, timeout: float = _TCP_PROBE_TIMEOUT) -> Optional[float]:
    """测量到服务器的 TCP 连接延迟（秒），失败返回 None."""
    start = time.monotonic()
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
        sock.close()
        return time.monotonic() - start
    except Exception:  # noqa: BLE001
        return None


class TdxFetcher(Fetcher):
    name = "tdx"

    def __init__(self, servers: list[dict[str, int]] | None = None, timeout: float = _CONNECT_TIMEOUT):
        # 合并内置列表与用户配置，去重，用户配置优先
        candidates: list[tuple[str, int]] = []
        seen: set[tuple[str, int]] = set()
        for srv in servers or []:
            item = (srv["host"], int(srv.get("port", 7709)))
            if item not in seen:
                seen.add(item)
                candidates.append(item)
        for item in DEFAULT_TDX_SERVERS:
            if item not in seen:
                seen.add(item)
                candidates.append(item)

        self._candidates = candidates
        self.timeout = timeout
        self._api = None
        self._current_server: Optional[tuple[str, int]] = None
        self._probed: list[tuple[str, int, float]] = []
        self._probe_time = 0.0
        self._connect()

    def _probe_servers(self) -> list[tuple[str, int, float]]:
        """并发 TCP 探测所有候选服务器，返回按延迟升序的可用列表."""
        results: list[tuple[str, int, float]] = []
        with ThreadPoolExecutor(max_workers=min(24, len(self._candidates))) as pool:
            future_map = {
                pool.submit(_tcp_latency, host, port): (host, port)
                for host, port in self._candidates
            }
            try:
                for fut in as_completed(future_map, timeout=_TCP_PROBE_TIMEOUT + 2):
                    host, port = future_map[fut]
                    try:
                        latency = fut.result()
                    except Exception:  # noqa: BLE001
                        continue
                    if latency is not None:
                        results.append((host, port, latency))
            except TimeoutError:
                pass
        results.sort(key=lambda x: x[2])
        return results

    def _refresh_probe(self, force: bool = False) -> None:
        if force or (time.monotonic() - self._probe_time > _PROBE_CACHE_SECONDS):
            probed = self._probe_servers()
            if probed:
                self._probed = probed
                self._probe_time = time.monotonic()

    def _connect(self) -> bool:
        try:
            from pytdx.hq import TdxHq_API
        except ImportError:  # pragma: no cover
            return False

        if self._api:
            try:
                self._api.disconnect()
            except Exception:  # noqa: BLE001
                pass
            self._api = None

        self._refresh_probe()
        # 探测全失败时用原始候选顺序兜底
        servers = self._probed or [(h, p, 0.0) for h, p in self._candidates]

        for host, port, _latency in servers[:_MAX_CONNECT_TRIES]:
            api = TdxHq_API()
            try:
                if api.connect(host, port, time_out=self.timeout):
                    self._api = api
                    self._current_server = (host, port)
                    return True
            except Exception:  # noqa: BLE001
                continue
        return False

    def _ensure_api(self):
        if self._api is None or not getattr(self._api, "client", None):
            self._connect()
        return self._api is not None

    def fetch(self, codes: list[str]) -> FetchResult:
        if not self._ensure_api():
            return FetchResult(source=self.name, error="tdx not connected")

        market_codes = [_parse_code(c) for c in codes]
        raw = self._call_with_timeout(lambda: self._api.get_security_quotes(market_codes))

        # 断线或返回空：强制重新探测并重连一次
        if not raw:
            self._refresh_probe(force=True)
            if not self._connect():
                return FetchResult(source=self.name, error="tdx fetch failed / reconnect failed")
            raw = self._call_with_timeout(lambda: self._api.get_security_quotes(market_codes))

        quotes: dict[str, Quote] = {}
        for item in raw or []:
            quote = self._parse_quote_item(item)
            if quote:
                quotes[quote.code] = quote

        return FetchResult(
            quotes=quotes,
            source=self.name,
            success=bool(quotes),
            error="" if quotes else "tdx returned empty",
        )

    def _call_with_timeout(self, fn, timeout: float = _READ_TIMEOUT):
        """在子线程执行 pytdx IO 调用，超时强制返回 None（防止 recv 永久阻塞）."""
        from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutTimeout
        with ThreadPoolExecutor(1) as ex:
            fut = ex.submit(fn)
            try:
                return fut.result(timeout=timeout)
            except (FutTimeout, Exception):  # noqa: BLE001
                # 超时 = socket 僵死，标记断开让下一轮重连
                self._api = None
                return None

    def _parse_quote_item(self, item) -> Quote | None:
        try:
            market = item.get("market", 1)
            pure = item.get("code", "")
            prefix = "sh" if market == 1 else "sz"
            code = f"{prefix}{pure}"

            # 指数不需要除 10；ETF/股票需要除 10
            is_index = pure.startswith("000") or pure.startswith("399")
            scale = 1.0 if is_index else 10.0

            def f(key: str) -> float:
                return float(item.get(key, 0)) / scale

            price = f("price")
            open_ = f("open")
            high = f("high")
            low = f("low")
            prev_close = f("last_close")
            volume = _safe_int(item.get("vol", 0))

            return Quote(
                code=code,
                name=item.get("name", code),
                price=price,
                open=open_,
                high=high,
                low=low,
                prev_close=prev_close,
                volume=volume,
                ts=item.get("servertime", ""),
                source=self.name,
            )
        except (ValueError, AttributeError, TypeError):
            return None

    def fetch_minute_bars(self, code: str, limit: int = 120) -> list[MinuteBar]:
        return self._fetch_bars(code, _BAR_CATEGORY["1min"], limit)

    def fetch_daily_bars(self, code: str, limit: int = 120) -> list[MinuteBar]:
        return self._fetch_bars(code, _BAR_CATEGORY["daily"], limit)

    def fetch_minute_bars_batch(self, codes: list[str], limit: int = 120) -> dict[str, list[MinuteBar]]:
        """并发拉取多只标的的分钟 K（每个 worker 一条独立 TDX 连接）.

        pytdx 单连接不是线程安全的，不能共享；每个 worker 新建短连接到当前
        已选最快节点，拉完即关。标的少（~13 只）时一轮 ~1-2s。
        返回 {code: bars}，失败的 code 对应空列表（由调用方走兜底）.
        """
        if not codes:
            return {}
        if self._current_server is None and not self._ensure_api():
            return {c: [] for c in codes}
        host, port = self._current_server  # type: ignore[misc]

        def worker(code: str) -> tuple[str, list[MinuteBar]]:
            try:
                from pytdx.hq import TdxHq_API
            except ImportError:  # pragma: no cover
                return code, []
            api = TdxHq_API()
            try:
                if not api.connect(host, port, time_out=self.timeout):
                    return code, []
                market, pure = _parse_code(code)
                raw = api.get_security_bars(_BAR_CATEGORY["1min"], market, pure, 0, limit)
                return code, self._parse_bars(code, raw)
            except Exception:  # noqa: BLE001
                return code, []
            finally:
                try:
                    api.disconnect()
                except Exception:  # noqa: BLE001
                    pass

        out: dict[str, list[MinuteBar]] = {}
        with ThreadPoolExecutor(max_workers=min(4, len(codes))) as pool:
            for code, bars in pool.map(worker, codes):
                out[code] = bars
        return out

    def _fetch_bars(self, code: str, category: int, limit: int) -> list[MinuteBar]:
        if not self._ensure_api():
            return []
        market, pure = _parse_code(code)
        raw = self._call_with_timeout(
            lambda: self._api.get_security_bars(category, market, pure, 0, limit))
        if raw is None:
            self._refresh_probe(force=True)
            if not self._connect():
                return []
            raw = self._call_with_timeout(
                lambda: self._api.get_security_bars(category, market, pure, 0, limit))
        return self._parse_bars(code, raw, category)

    def _parse_bars(self, code: str, raw, category: int | None = None) -> list[MinuteBar]:
        bars: list[MinuteBar] = []
        # TDX 分钟/日 K 线价格已经是实际价格（snapshot 才是整数 ×10）
        for item in raw or []:
            try:
                # 日 K 的 datetime 只有日期（2026-07-22），补 15:00:00 统一 14 位时间戳
                raw_ts = str(item.get("datetime", "")).replace("-", "").replace(":", "").replace(" ", "")
                if len(raw_ts) == 8:
                    raw_ts += "150000"
                # 指数分钟K的 datetime 经常是乱码（如 2035000011207），必须校验
                if not _is_valid_bar_ts(raw_ts):
                    continue
                bars.append(
                    MinuteBar(
                        code=code,
                        ts=raw_ts,
                        open=float(item.get("open", 0)),
                        high=float(item.get("high", 0)),
                        low=float(item.get("low", 0)),
                        close=float(item.get("close", 0)),
                        volume=_safe_int(item.get("vol", 0)),
                        source="tdx_daily" if category == _BAR_CATEGORY["daily"] else self.name,
                    )
                )
            except (ValueError, TypeError):
                continue
        return bars

    def current_server(self) -> Optional[tuple[str, int]]:
        return self._current_server

    def close(self) -> None:
        if self._api:
            try:
                self._api.disconnect()
            except Exception:  # noqa: BLE001
                pass
            self._api = None


def _is_valid_bar_ts(ts: str) -> bool:
    """校验时间戳是否合法（14 位 YYYYMMDDHHMMSS 或 12 位 YYYYMMDDHHMM）.

    TDX 指数分钟 K 的 datetime 经常是乱码（如 2035000011207、153:04:31.278），
    不合法就跳过该 bar，让 FetchChain 降级到东财源。
    """
    if not ts.isdigit():
        return False
    if len(ts) == 12:
        # 分钟K格式：YYYYMMDDHHMM
        year = int(ts[:4])
        month = int(ts[4:6])
        day = int(ts[6:8])
        hour = int(ts[8:10])
        minute = int(ts[10:12])
        second = 0
    elif len(ts) == 14:
        # 日K补齐格式：YYYYMMDDHHMMSS
        year = int(ts[:4])
        month = int(ts[4:6])
        day = int(ts[6:8])
        hour = int(ts[8:10])
        minute = int(ts[10:12])
        second = int(ts[12:14])
    else:
        return False
    if not (2000 <= year <= 2099):
        return False
    if not (1 <= month <= 12):
        return False
    if not (1 <= day <= 31):
        return False
    if not (0 <= hour <= 23):
        return False
    if not (0 <= minute <= 59):
        return False
    if not (0 <= second <= 59):
        return False
    return True


def _safe_int(val, default: int = 0) -> int:
    try:
        if isinstance(val, float) and (val < 1 or val > 1e18):
            return default
        return int(val)
    except (ValueError, TypeError, OverflowError):
        return default
