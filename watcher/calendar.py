"""交易时段判断."""
from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Callable, Optional

import pytz


TZ = pytz.timezone("Asia/Shanghai")

# 真实交易时段（信号提醒只在这些时段触发）
MORNING_START = time(9, 25)
MORNING_END = time(11, 30)
AFTERNOON_START = time(13, 0)
AFTERNOON_END = time(15, 0)

# 数据轮询时段（放宽覆盖盘前、午休、盘尾，保证界面始终有数据）
POLL_START = time(9, 0)
POLL_END = time(15, 30)


def now_sh() -> datetime:
    return datetime.now(TZ)


# 交易日判定回调（由 app 启动时注入：读 SQLite 里的 Tushare 交易日历）
# 返回 True=交易日 / False=节假日 / None=日历没覆盖（此时只按周末判断）
_trade_day_checker: Callable[[str], Optional[bool]] | None = None


def set_trade_day_checker(fn: Callable[[str], Optional[bool]] | None) -> None:
    """注入交易日历查询函数（避免 calendar 模块反向依赖 StateStore）."""
    global _trade_day_checker
    _trade_day_checker = fn


def is_trading_day(dt: datetime | None = None) -> bool:
    """是否交易日：先看周末，再查交易日历（节假日 / 调休上班都靠日历兜住）."""
    if dt is None:
        dt = now_sh()
    known: Optional[bool] = None
    if _trade_day_checker is not None:
        try:
            known = _trade_day_checker(dt.strftime("%Y%m%d"))
        except Exception:  # noqa: BLE001
            known = None
    if known is not None:
        return known                 # 日历说了算（含"周六调休开市"这种反常情况）
    return dt.weekday() < 5          # 没日历时退回周末判断


def is_trading_hours(dt: datetime | None = None) -> bool:
    """真实交易时段（用于信号提醒）."""
    if dt is None:
        dt = now_sh()
    if not is_trading_day(dt):
        return False
    t = dt.time()
    return (
        MORNING_START <= t <= MORNING_END
        or AFTERNOON_START <= t <= AFTERNOON_END
    )


def is_polling_hours(dt: datetime | None = None) -> bool:
    """数据轮询时段（交易日 9:00–15:30，含午休；节假日不轮询）."""
    if dt is None:
        dt = now_sh()
    if not is_trading_day(dt):
        return False
    t = dt.time()
    return POLL_START <= t <= POLL_END


def today_str() -> str:
    return now_sh().strftime("%Y-%m-%d")


def ts_now() -> str:
    return now_sh().strftime("%Y%m%d%H%M%S")


def _valid_hms(h: str, m: str, s: str) -> bool:
    try:
        return 0 <= int(h) <= 23 and 0 <= int(m) <= 59 and 0 <= int(s) <= 59
    except ValueError:
        return False


def parse_quote_time(ts: str) -> str | None:
    """解析行情时间戳为 HH:MM:SS，无法可靠解析时返回 None（不瞎猜）.

    支持格式：
    - 14 位 yyyyMMddHHmmss
    - 12 位 yyyyMMddHHmm（分钟 K 线时间戳，补 :00）
    - HH:MM:SS(.mmm) 正常格式
    不支持：TDX 异常 servertime（如 "153:04:31"，3 位小时段）→ None
    """
    if not ts:
        return None
    if ts.isdigit():
        if len(ts) == 14:
            h, m, s = ts[8:10], ts[10:12], ts[12:14]
            return f"{h}:{m}:{s}" if _valid_hms(h, m, s) else None
        if len(ts) == 12:
            h, m = ts[8:10], ts[10:12]
            return f"{h}:{m}:00" if _valid_hms(h, m, "00") else None
        return None
    if ":" in ts:
        parts = ts.split(":")
        if len(parts) >= 3 and len(parts[0]) <= 2:
            h = parts[0].zfill(2)
            m = parts[1].zfill(2)
            s = parts[2].split(".")[0].zfill(2)
            return f"{h}:{m}:{s}" if _valid_hms(h, m, s) else None
    return None


def signal_display_time(ts: str, created_at: str = "") -> str:
    """信号显示时间：优先行情时间，解析失败回退 created_at（UTC 转北京时间）."""
    parsed = parse_quote_time(ts)
    if parsed:
        return parsed
    if created_at:
        try:
            dt = datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S") + timedelta(hours=8)
            return dt.strftime("%H:%M:%S")
        except ValueError:
            pass
    return ts or "-"
