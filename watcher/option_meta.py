"""ETF 期权合约元数据管理."""
from __future__ import annotations

import json
import re
import time
from datetime import date
from typing import Literal

import httpx

from watcher.models import MinuteBar, OptionContract, Quote


# ETF 期权标的清单（code -> 名称），共 11 个：沪市 6 + 深市 5
ETF_OPTION_UNDERLYINGS: dict[str, str] = {
    "510050": "上证50ETF",
    "510300": "沪深300ETF",
    "510500": "中证500ETF",
    "588000": "科创50ETF",
    "588080": "科创50ETF易方达",
    "588050": "科创50ETF工银",
    "159919": "沪深300ETF",
    "159915": "创业板ETF",
    "159922": "中证500ETF",
    "159901": "深证100ETF",
    "159952": "创业板ETF易方达",
}

# 标的前缀映射（code -> sh/sz）
UNDERLYING_PREFIX: dict[str, str] = {
    "510050": "sh",
    "510300": "sh",
    "510500": "sh",
    "588000": "sh",
    "588080": "sh",
    "588050": "sh",
    "159919": "sz",
    "159915": "sz",
    "159922": "sz",
    "159901": "sz",
    "159952": "sz",
}


def _extract_code(text: str) -> str:
    m = re.search(r"\((\d{6})\)", text)
    return m.group(1) if m else ""


def _parse_sse_contracts() -> list[OptionContract]:
    try:
        import akshare as ak
    except ImportError:  # pragma: no cover
        return []

    try:
        df = ak.option_current_day_sse()
    except Exception:  # noqa: BLE001
        return []

    contracts: list[OptionContract] = []
    for _, row in df.iterrows():
        underlying = _extract_code(str(row.get("标的券名称及代码", "")))
        if not underlying or underlying not in ETF_OPTION_UNDERLYINGS:
            continue
        option_code = str(row.get("合约编码", "")).strip()
        option_name = str(row.get("合约简称", "")).strip()
        option_type: Literal["call", "put"] = "call" if "购" in option_name or str(row.get("类型", "")) == "认购" else "put"
        strike = float(row.get("行权价", 0))
        expire = str(row.get("到期日", "")).strip()
        contracts.append(
            OptionContract(
                option_code=option_code,
                underlying_code=f"{UNDERLYING_PREFIX[underlying]}{underlying}",
                option_name=option_name,
                exchange="SSE",
                option_type=option_type,
                strike=strike,
                expire_date=expire,
            )
        )
    return contracts


def _parse_szse_contracts() -> list[OptionContract]:
    try:
        import akshare as ak
    except ImportError:  # pragma: no cover
        return []

    try:
        df = ak.option_current_day_szse()
    except Exception:  # noqa: BLE001
        return []

    contracts: list[OptionContract] = []
    for _, row in df.iterrows():
        underlying = _extract_code(str(row.get("标的证券简称(代码)", "")))
        if not underlying or underlying not in ETF_OPTION_UNDERLYINGS:
            continue
        option_code = str(row.get("合约编码", "")).strip()
        option_name = str(row.get("合约简称", "")).strip()
        option_type: Literal["call", "put"] = "call" if "购" in option_name or str(row.get("合约类型", "")) == "认购" else "put"
        strike = float(row.get("行权价", 0))
        expire = str(row.get("到期日", "")).replace("-", "").strip()
        contracts.append(
            OptionContract(
                option_code=option_code,
                underlying_code=f"{UNDERLYING_PREFIX[underlying]}{underlying}",
                option_name=option_name,
                exchange="SZSE",
                option_type=option_type,
                strike=strike,
                expire_date=expire,
            )
        )
    return contracts


def load_all_contracts() -> list[OptionContract]:
    """从 akshare 加载全部 ETF 期权合约元数据."""
    return _parse_sse_contracts() + _parse_szse_contracts()


def _get_sina_client() -> httpx.Client:
    global _sina_client
    if _sina_client is None:
        _sina_client = httpx.Client(
            timeout=8.0,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                "Referer": "https://stock.finance.sina.com.cn/option/quotes.html",
            },
        )
    return _sina_client


_sina_client: httpx.Client | None = None


def fetch_option_minute_bars(option_code: str) -> list[MinuteBar]:
    """拉取单个沪市期权合约的分时数据（新浪接口，深市暂不支持）.

    新浪只给「每分钟最新价 + 当日累计均价 + 成交 + 持仓」，**没有 OHLC，
    不能合成蜡烛图**（会全绿失真），只画分时折线（价格线 + 均价线）.
    返回的 bar 以均价填充 open 供折线模式使用.
    """
    if not option_code.startswith("10"):
        return []
    try:
        resp = _get_sina_client().get(
            "https://stock.finance.sina.com.cn/futures/api/openapi.php/StockOptionDaylineService.getOptionMinline",
            params={"symbol": f"CON_OP_{option_code}"},
        )
        resp.raise_for_status()
        data = (resp.json().get("result") or {}).get("data") or []
    except Exception:  # noqa: BLE001
        return []

    bars: list[MinuteBar] = []
    if not isinstance(data, list):
        return bars
    cur_date = ""
    for item in data:
        # 每项: {i:时间, p:价格, v:成交, t:持仓, a:均价, d:日期}（日期仅首行有，需向下继承）
        if not isinstance(item, dict):
            continue
        try:
            d = str(item.get("d") or "").replace("-", "") or cur_date
            if not d:
                continue
            cur_date = d
            price = float(item["p"])
            avg = float(item.get("a") or price)
            bars.append(
                MinuteBar(
                    code=option_code,
                    ts=d + str(item["i"]).replace(":", ""),
                    open=avg,
                    high=max(price, avg),
                    low=min(price, avg),
                    close=price,
                    volume=int(float(item.get("v") or 0)),
                    source="sina_option",
                )
            )
        except (ValueError, TypeError, IndexError, KeyError):
            continue
    return bars


# 东财期权市场代码：沪市期权 secid=10.代码，深市期权 secid=12.代码
_EM_OPTION_MARKET = {"10": "10", "90": "12"}

# 东财结果内存缓存：盘中 60s 避免连续请求触发封禁，盘后永不过期（减少无效请求）
_EM_CACHE: dict[str, tuple[float, list[MinuteBar]]] = {}
_EM_CACHE_TTL_POLLING = 60.0  # 轮询时段内 TTL

_em_client: httpx.Client | None = None


def _get_em_client() -> httpx.Client:
    global _em_client
    if _em_client is None:
        _em_client = httpx.Client(
            timeout=8.0,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                "Referer": "https://quote.eastmoney.com/",
            },
        )
    return _em_client


def _fetch_em_trends(option_code: str, market: str, ndays: int) -> list[MinuteBar]:
    """请求东财 trends2 并解析为 1 分钟 K 线（open=前一分钟收盘价）."""
    params = {
        "secid": f"{market}.{option_code}",
        "ndays": str(ndays),
        "iscr": "0",
        "iscca": "0",
        "fields1": "f1,f2,f3,f4,f5,f6,f7,f8",
        "fields2": "f51,f53,f54,f55,f56,f57,f58",
    }
    url = "https://push2.eastmoney.com/api/qt/stock/trends2/get"
    client = _get_em_client()
    trends: list[str] = []
    for attempt in range(2):  # 首次失败重试一次（东财间歇断连）
        try:
            resp = client.get(url, params=params)
            resp.raise_for_status()
            trends = (resp.json().get("data") or {}).get("trends") or []
            break
        except Exception:  # noqa: BLE001
            if attempt == 0:
                time.sleep(1.0)
    if not trends:
        return []

    bars: list[MinuteBar] = []
    prev_close = 0.0
    for line in trends:
        # 格式: yyyy-MM-dd HH:mm,最新价,最高,最低,成交量,成交额,均价
        parts = line.split(",")
        if len(parts) < 6:
            continue
        try:
            close = float(parts[1])
            high = float(parts[2])
            low = float(parts[3])
            if close <= 0:
                continue
            open_ = prev_close if prev_close > 0 else close
            high = max(high, open_)
            low = min(low, open_)
            ts = parts[0].replace("-", "").replace(":", "").replace(" ", "") + "00"
            bars.append(
                MinuteBar(
                    code=option_code,
                    ts=ts,
                    open=open_,
                    high=high,
                    low=low,
                    close=close,
                    volume=int(float(parts[4] or 0)),
                    source="eastmoney_option",
                )
            )
            prev_close = close
        except (ValueError, IndexError):
            continue
    return bars


def fetch_option_minute_bars_em(option_code: str) -> list[MinuteBar]:
    """拉取单个期权合约的分时 K 线（东财 trends2 接口，含真实分钟高低价）.

    支持沪市（10 开头，market=10）和深市（90 开头，market=12）期权.
    trends2 每股息点给 时间/最新价/最高/最低/成交/成交额/均价，open 用前一分钟
    收盘价填充（1 分钟 K 惯例），可画真实蜡烛图。默认取 5 天（聚合 5/15/30/60 分用），
    接口不支持时降级 1 天。结果内存缓存 60s.
    注意：东财对单 IP 敏感会间歇断连，失败重试一次，仍失败返回 [] 由调用方降级.
    """
    market = _EM_OPTION_MARKET.get(option_code[:2]) if len(option_code) == 8 else None
    if not market:
        return []
    now = time.monotonic()
    hit = _EM_CACHE.get(option_code)
    if hit:
        # 盘中 60s 过期；盘后/非轮询时段不过期（避免无效请求被封）
        from watcher.calendar import is_polling_hours
        ttl = _EM_CACHE_TTL_POLLING if is_polling_hours() else float("inf")
        if now - hit[0] < ttl:
            return hit[1]
    bars = _fetch_em_trends(option_code, market, 5)
    if not bars:
        bars = _fetch_em_trends(option_code, market, 1)
    if bars:
        _EM_CACHE[option_code] = (now, bars)
    return bars


def fetch_option_daily_bars(option_code: str) -> list[MinuteBar]:
    """拉取单个沪市期权合约的日 K 线（新浪接口，有真实 OHLC）."""
    if not option_code.startswith("10"):
        return []
    try:
        resp = _get_sina_client().get(
            "https://stock.finance.sina.com.cn/futures/api/jsonp_v2.php//StockOptionDaylineService.getSymbolInfo",
            params={"symbol": f"CON_OP_{option_code}"},
        )
        resp.raise_for_status()
        text = resp.text
        data = json.loads(text[text.find("(") + 1: text.rfind(")")])
    except Exception:  # noqa: BLE001
        return []

    bars: list[MinuteBar] = []
    if not isinstance(data, list):  # 到期/异常合约可能返回 dict 错误体
        return bars
    for item in data:
        # 每项: {d:日期, o:开盘, h:最高, l:最低, c:收盘, v:成交量}
        if not isinstance(item, dict):
            continue
        try:
            bars.append(
                MinuteBar(
                    code=option_code,
                    ts=str(item["d"]).replace("-", "") + "150000",
                    open=float(item["o"]),
                    high=float(item["h"]),
                    low=float(item["l"]),
                    close=float(item["c"]),
                    volume=int(float(item.get("v") or 0)),
                    source="sina_option_daily",
                )
            )
        except (ValueError, TypeError, IndexError, KeyError):
            continue
    return bars


def underlying_codes() -> list[str]:
    return [f"{prefix}{code}" for code, prefix in UNDERLYING_PREFIX.items()]


def select_atm_contracts(
    contracts: list[OptionContract],
    underlying_price: float,
    n_strikes: int = 3,
    n_expiries: int = 2,
) -> list[OptionContract]:
    """筛选最近 n_expiries 个到期月、ATM±n_strikes 档的合约（认购认沽都在内），用于重点缓存分时 K."""
    if not contracts or underlying_price <= 0:
        return []
    expiries = sorted({c.expire_date for c in contracts})[:n_expiries]
    pool = [c for c in contracts if c.expire_date in expiries]
    strikes = sorted({c.strike for c in pool})
    if not strikes:
        return []
    atm = min(range(len(strikes)), key=lambda i: abs(strikes[i] - underlying_price))
    keep = set(strikes[max(0, atm - n_strikes): atm + n_strikes + 1])
    return [c for c in pool if c.strike in keep]


# ---------- T 型报价数据组装 ----------

def _nn(v) -> int | None:
    """非负整数或 None（深市期权行情字段偏移可能出现负成交量，夹到 0）."""
    if v is None:
        return None
    try:
        return max(0, int(v))
    except (ValueError, TypeError):
        return None


def _fmt_expire(e: str) -> str:
    """'20260722' -> '2026-07-22'（已是带横线格式则原样返回）."""
    if len(e) == 8 and e.isdigit():
        return f"{e[:4]}-{e[4:6]}-{e[6:]}"
    return e


def _days_left(e: str, today: date) -> int | None:
    try:
        if len(e) == 8 and e.isdigit():
            d = date(int(e[:4]), int(e[4:6]), int(e[6:]))
        else:
            d = date.fromisoformat(e)
        return (d - today).days
    except ValueError:
        return None


def _side_payload(c: OptionContract, q: dict | None) -> dict:
    """单个合约（T 型一侧）的展示数据；q 为 None 时只有代码/名称（无行情）."""
    side: dict = {"code": c.option_code, "name": c.option_name}
    if q:
        price = q.get("price") or None  # 0 价 = 无成交/无行情，按 None 显示 --
        side.update({
            "price": price,
            "change_pct": q.get("change_pct") if price is not None else None,
            "sell_price": q.get("sell_price") or None,
            "sell_vol": _nn(q.get("sell_vol")),
            "buy_price": q.get("buy_price") or None,
            "buy_vol": _nn(q.get("buy_vol")),
            "volume": _nn(q.get("volume")),
            "oi": _nn(q.get("open_interest")),
            "iv": q.get("iv") or None,
            "delta": q.get("delta") or None,
        })
    return side


def build_tshape_data(
    contracts: list[OptionContract],
    quotes: dict[str, dict],
    underlying_code: str,
    underlying_name: str,
    underlying_quote: Quote | None,
    today: date | None = None,
) -> dict:
    """组装 T 型报价页 payload（纯函数，便于测试）.

    contracts: 该标的全部合约（expire_date 统一 8 位格式，来自 option_contracts 表）.
    quotes: {option_code: 行情 dict}（来自 option_quotes 表，expire_date 格式与此无关）.
    """
    if today is None:
        today = date.today()

    expiries = sorted({c.expire_date for c in contracts if c.expire_date})
    rows_by_expiry: dict[str, list[dict]] = {}
    for expiry in expiries:
        strikes: dict[float, dict] = {}
        for c in contracts:
            if c.expire_date != expiry:
                continue
            slot = strikes.setdefault(c.strike, {"strike": c.strike, "calls": [], "puts": []})
            side = _side_payload(c, quotes.get(c.option_code))
            slot["calls" if c.option_type == "call" else "puts"].append(side)
        # 同一行权价可能有多个合约（带 A 的调整合约），按代码排序保证稳定
        rows = []
        for strike in sorted(strikes):
            slot = strikes[strike]
            slot["calls"].sort(key=lambda s: s["code"])
            slot["puts"].sort(key=lambda s: s["code"])
            rows.append(slot)
        rows_by_expiry[expiry] = rows

    underlying = {"code": underlying_code, "name": underlying_name,
                  "price": None, "change": None, "change_pct": None}
    if underlying_quote and underlying_quote.price > 0:
        underlying.update({
            "price": underlying_quote.price,
            "change": round(underlying_quote.price - underlying_quote.prev_close, 4),
            "change_pct": round(underlying_quote.change_pct * 100, 2),
        })

    # 默认选最近到期（合约清单都是当日有效的，取第一个即当月）
    default_expiry = expiries[0] if expiries else None

    # 波动率微笑数据：各到期月按行权价排列的 Call IV / Put IV
    smile_by_expiry: dict[str, dict] = {}
    for expiry, rows in rows_by_expiry.items():
        strikes_list: list[float] = []
        call_ivs: list[float | None] = []
        put_ivs: list[float | None] = []
        for row in rows:
            strikes_list.append(row["strike"])
            # 取第一个有 IV 的合约（跳过调整合约）
            c_iv = None
            for c in row.get("calls", []):
                if c.get("iv") is not None:
                    c_iv = round(c["iv"] * 100, 2)
                    break
            p_iv = None
            for p in row.get("puts", []):
                if p.get("iv") is not None:
                    p_iv = round(p["iv"] * 100, 2)
                    break
            call_ivs.append(c_iv)
            put_ivs.append(p_iv)
        smile_by_expiry[expiry] = {
            "strikes": strikes_list,
            "callIV": call_ivs,
            "putIV": put_ivs,
        }

    # 持仓量分布数据：各到期月按行权价的 Call OI / Put OI + Max Pain + Call墙/Put墙
    oi_by_expiry: dict[str, dict] = {}
    for expiry, rows in rows_by_expiry.items():
        strikes_list_oi: list[float] = []
        call_ois: list[int] = []
        put_ois: list[int] = []
        for row in rows:
            strikes_list_oi.append(row["strike"])
            # 汇总同一行权价所有合约的 OI（含调整合约）
            c_oi = sum((c.get("oi") or 0) for c in row.get("calls", []))
            p_oi = sum((p.get("oi") or 0) for p in row.get("puts", []))
            call_ois.append(c_oi)
            put_ois.append(p_oi)

        # Call墙 / Put墙：持仓量最大的行权价
        call_wall = strikes_list_oi[call_ois.index(max(call_ois))] if call_ois and max(call_ois) > 0 else None
        put_wall = strikes_list_oi[put_ois.index(max(put_ois))] if put_ois and max(put_ois) > 0 else None

        # Max Pain（最大痛点）：到期在该行权价结算时，全部期权买方行权价值总和最小
        max_pain = None
        if strikes_list_oi and (sum(call_ois) + sum(put_ois)) > 0:
            min_pain_value = float("inf")
            for settle in strikes_list_oi:
                pain = 0.0
                for i, k in enumerate(strikes_list_oi):
                    # Call 买方在 settle > k 时行权，价值 = (settle - k) * call_oi
                    if settle > k:
                        pain += (settle - k) * call_ois[i]
                    # Put 买方在 settle < k 时行权，价值 = (k - settle) * put_oi
                    if settle < k:
                        pain += (k - settle) * put_ois[i]
                if pain < min_pain_value:
                    min_pain_value = pain
                    max_pain = settle

        oi_by_expiry[expiry] = {
            "strikes": strikes_list_oi,
            "callOI": call_ois,
            "putOI": put_ois,
            "callWall": call_wall,
            "putWall": put_wall,
            "maxPain": max_pain,
        }

    # 卖方指标面板：各到期月的核心卖方参考指标
    seller_by_expiry: dict[str, dict] = {}
    spot = underlying_quote.price if underlying_quote and underlying_quote.price > 0 else None
    for expiry, rows in rows_by_expiry.items():
        if not rows or not spot:
            continue
        # 找平值档（行权价最接近现价）
        atm_idx = min(range(len(rows)), key=lambda i: abs(rows[i]["strike"] - spot))
        atm_strike = rows[atm_idx]["strike"]

        # ATM Call IV / Put IV
        atm_call_iv = None
        for c in rows[atm_idx].get("calls", []):
            if c.get("iv") is not None:
                atm_call_iv = c["iv"]
                break
        atm_put_iv = None
        for p in rows[atm_idx].get("puts", []):
            if p.get("iv") is not None:
                atm_put_iv = p["iv"]
                break

        # 平值 IV = (Call IV + Put IV) / 2
        if atm_call_iv is not None and atm_put_iv is not None:
            atm_iv = (atm_call_iv + atm_put_iv) / 2
        elif atm_call_iv is not None:
            atm_iv = atm_call_iv
        elif atm_put_iv is not None:
            atm_iv = atm_put_iv
        else:
            atm_iv = None

        # 25Δ 偏斜：Put 25Δ IV - Call 25Δ IV（正值=Put更贵=恐慌）
        # 找 delta 最接近 -0.25 的 Put 和 +0.25 的 Call
        iv_25d_put = None
        iv_25d_call = None
        best_put_dist = 1.0
        best_call_dist = 1.0
        for row in rows:
            for c in row.get("calls", []):
                d = c.get("delta")
                iv = c.get("iv")
                if d is not None and iv is not None:
                    dist = abs(d - 0.25)
                    if dist < best_call_dist:
                        best_call_dist = dist
                        iv_25d_call = iv
            for p in row.get("puts", []):
                d = p.get("delta")
                iv = p.get("iv")
                if d is not None and iv is not None:
                    dist = abs(d - (-0.25))
                    if dist < best_put_dist:
                        best_put_dist = dist
                        iv_25d_put = iv
        skew_25d = None
        if iv_25d_put is not None and iv_25d_call is not None:
            skew_25d = round((iv_25d_put - iv_25d_call) * 100, 2)  # 百分点

        # PCR（持仓量）
        total_call_oi = sum((c.get("oi") or 0) for row in rows for c in row.get("calls", []))
        total_put_oi = sum((p.get("oi") or 0) for row in rows for p in row.get("puts", []))
        pcr_oi = round(total_put_oi / total_call_oi, 3) if total_call_oi > 0 else None

        # 预期波动幅度 = ATM 跨式价格 / 标的价（到期前的隐含涨跌幅）
        atm_call_price = None
        atm_put_price = None
        for c in rows[atm_idx].get("calls", []):
            if c.get("price") is not None and c["price"] > 0:
                atm_call_price = c["price"]
                break
        for p in rows[atm_idx].get("puts", []):
            if p.get("price") is not None and p["price"] > 0:
                atm_put_price = p["price"]
                break
        expected_move = None
        if atm_call_price and atm_put_price and spot > 0:
            straddle = atm_call_price + atm_put_price
            expected_move = round(straddle / spot * 100, 2)  # 百分比

        # 剩余天数
        days = _days_left(expiry, today)

        seller_by_expiry[expiry] = {
            "atmStrike": atm_strike,
            "atmIV": round(atm_iv * 100, 2) if atm_iv else None,  # 百分比
            "skew25D": skew_25d,  # 百分点（正=Put贵）
            "pcrOI": pcr_oi,
            "expectedMove": expected_move,  # 百分比
            "totalCallOI": total_call_oi,
            "totalPutOI": total_put_oi,
            "days": days,
        }

    # IV 期限结构：各到期月的 ATM IV（从 seller_by_expiry 提取）
    iv_term = []
    for expiry in expiries:
        s = seller_by_expiry.get(expiry)
        if s and s.get("atmIV") is not None:
            iv_term.append({
                "expiry": _fmt_expire(expiry),
                "days": s["days"],
                "atmIV": s["atmIV"],
            })

    # 波动率曲面：到期月 × 行权价 的 IV 矩阵（Call/Put 平均）
    # 同时提供全到期月的微笑数据用于多月对比
    all_strikes_set: set[float] = set()
    for expiry in expiries:
        sm = smile_by_expiry.get(expiry)
        if sm:
            all_strikes_set.update(sm["strikes"])
    all_strikes = sorted(all_strikes_set)

    surface_rows: list[dict] = []
    for expiry in expiries:
        sm = smile_by_expiry.get(expiry)
        if not sm:
            continue
        # 构建该到期月的 IV map（按行权价索引）
        iv_map: dict[float, float | None] = {}
        for i, k in enumerate(sm["strikes"]):
            c_iv = sm["callIV"][i]
            p_iv = sm["putIV"][i]
            if c_iv is not None and p_iv is not None:
                iv_map[k] = round((c_iv + p_iv) / 2, 2)
            elif c_iv is not None:
                iv_map[k] = c_iv
            elif p_iv is not None:
                iv_map[k] = p_iv
            else:
                iv_map[k] = None
        # 按全局行权价顺序填充
        row_ivs: list[float | None] = []
        for k in all_strikes:
            row_ivs.append(iv_map.get(k))
        surface_rows.append({
            "expiry": _fmt_expire(expiry),
            "days": _days_left(expiry, today),
            "ivs": row_ivs,
        })

    vol_surface = {
        "strikes": all_strikes,
        "rows": surface_rows,
    } if all_strikes and surface_rows else None

    payload = {
        "title": "期权T型",
        "meta": f"{underlying_name} · {len(contracts)} 合约 · 点击合约查看分时 K 线",
        "underlying": underlying,
        "expiries": [
            {"date": e, "label": _fmt_expire(e), "days": _days_left(e, today)}
            for e in expiries
        ],
        "rows": rows_by_expiry,
        "defaultExpiry": default_expiry,
        "smile": smile_by_expiry,
        "oi": oi_by_expiry,
        "seller": seller_by_expiry,
        "ivTerm": iv_term,
        "surface": vol_surface,
    }
    if not contracts:
        payload["meta"] = f"{underlying_name} · 暂无合约"
        payload["emptyHint"] = f"{underlying_name} 暂无期权合约（目前共 9 个标的有合约）"
    return payload


class OptionQuoteFetcher:
    """用新浪接口获取单个期权合约行情 + Greeks."""

    def __init__(self, timeout: float = 10.0):
        self.client = httpx.Client(timeout=timeout, headers={"Referer": "https://finance.sina.com.cn"})

    def fetch(self, option_codes: list[str]) -> dict[str, dict]:
        """批量获取期权行情，返回 {option_code: fields}."""
        if not option_codes:
            return {}
        symbols = ",".join(f"CON_OP_{c}" for c in option_codes)
        url = f"http://hq.sinajs.cn/list={symbols}"
        try:
            resp = self.client.get(url)
            resp.raise_for_status()
            text = resp.content.decode("gbk", errors="replace")
        except Exception:  # noqa: BLE001
            return {}

        result: dict[str, dict] = {}
        for line in text.split(";"):
            line = line.strip()
            if not line or "=" not in line:
                continue
            prefix, value = line.split("=", 1)
            option_code = prefix.replace("var hq_str_CON_OP_", "").strip()
            value = value.strip().strip('"')
            if not value:
                continue
            parts = value.split(",")
            parsed = self._parse_op(parts)
            if parsed:
                result[option_code] = parsed

        # 补充 Greeks
        self._append_greeks(result)
        return result

    def _parse_op(self, parts: list[str]) -> dict | None:
        if len(parts) < 38:
            return None

        def _f(idx: int, default: float = 0.0) -> float:
            try:
                return float(parts[idx]) if parts[idx] else default
            except (ValueError, IndexError):
                return default

        def _i(idx: int, default: int = 0) -> int:
            try:
                return int(float(parts[idx])) if parts[idx] else default
            except (ValueError, IndexError):
                return default

        try:
            # 关键字段（2026-07 实网验证）：
            #   [6]=涨跌幅%(对昨结，官方口径，方向与K线一致)
            #   [38]=另一种涨幅（对除息重述基准，除息日两边全红失真，勿用）
            #   [41]=成交量（[6]曾被误当成交量导致负值）
            change_pct = _f(6) or _f(38)
            return {
                "buy_vol": _i(0),
                "buy_price": _f(1),
                "price": _f(2),
                "sell_price": _f(3),
                "sell_vol": _i(4),
                "open_interest": _i(5),
                "volume": _i(41),
                "strike": _f(7),
                "prev_settle": _f(44),
                "open": _f(39),
                "ts": parts[32] if len(parts) > 32 else "",
                "underlying_code": parts[36] if len(parts) > 36 else "",
                "name": parts[37] if len(parts) > 37 else "",
                "change_pct": change_pct,
                "expire_date": parts[46] if len(parts) > 46 else "",
            }
        except (ValueError, IndexError):
            return None

    def _append_greeks(self, result: dict[str, dict]) -> None:
        if not result:
            return
        symbols = ",".join(f"CON_SO_{c}" for c in result.keys())
        url = f"http://hq.sinajs.cn/list={symbols}"
        try:
            resp = self.client.get(url)
            resp.raise_for_status()
            text = resp.content.decode("gbk", errors="replace")
        except Exception:  # noqa: BLE001
            return

        for line in text.split(";"):
            line = line.strip()
            if not line or "=" not in line:
                continue
            prefix, value = line.split("=", 1)
            option_code = prefix.replace("var hq_str_CON_SO_", "").strip()
            value = value.strip().strip('"')
            if not value or option_code not in result:
                continue
            parts = value.split(",")
            if len(parts) < 11:
                continue
            try:
                greeks = {
                    "delta": float(parts[6]) if parts[6] else 0.0,
                    "gamma": float(parts[7]) if parts[7] else 0.0,
                    "theta": float(parts[8]) if parts[8] else 0.0,
                    "vega": float(parts[9]) if parts[9] else 0.0,
                    "iv": float(parts[10]) if parts[10] else 0.0,
                }
                result[option_code].update(greeks)
            except (ValueError, IndexError):
                continue

    def close(self) -> None:
        self.client.close()
