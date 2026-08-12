"""分钟 K 线聚合工具（A 股交易时段感知）."""
from __future__ import annotations

from watcher.models import MinuteBar


# A 股连续竞价时段：09:30-11:30 / 13:00-15:00，共 240 分钟
_MORNING_START = 9 * 60 + 30   # 570
_MORNING_END = 11 * 60 + 30    # 690
_AFTERNOON_START = 13 * 60     # 780
_SESSION_MINUTES = 240


def _session_index(ts: str) -> int | None:
    """把 14 位时间戳映射为交易时段分钟序号（0-239）.

    集合竞价（09:30 前）并入第一分钟；11:30/15:00 收盘点并入当段最后一分钟；
    午休时间（不应出现）并入上午最后一分钟。无法解析返回 None.
    """
    if len(ts) < 12 or not ts[:12].isdigit():
        return None
    t = int(ts[8:10]) * 60 + int(ts[10:12])
    if t < _MORNING_START:
        return 0
    if t <= _MORNING_END:
        return min(t - _MORNING_START, 119)
    if t < _AFTERNOON_START:
        return 119
    return 120 + min(t - _AFTERNOON_START, 119)


def aggregate_minute_bars(bars: list[MinuteBar], n: int) -> list[MinuteBar]:
    """把 1 分钟 K 线聚合为 n 分钟 K 线（跨天不串，按交易时段对齐）.

    open=首根 open，close=末根 close，high/low=区间极值，volume=求和，
    ts=末根时间戳。n<=1 时原样返回。
    """
    if n <= 1:
        return list(bars)

    out: list[MinuteBar] = []
    cur_key: tuple[str, int] | None = None
    for b in bars:
        idx = _session_index(b.ts)
        if idx is None:
            continue
        key = (b.ts[:8], idx // n)
        if cur_key == key and out:
            prev = out[-1]
            out[-1] = MinuteBar(
                code=prev.code,
                ts=b.ts,
                open=prev.open,
                high=max(prev.high, b.high),
                low=min(prev.low, b.low),
                close=b.close,
                volume=prev.volume + b.volume,
                source=prev.source,
            )
        else:
            out.append(b)
            cur_key = key
    return out
