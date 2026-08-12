"""市场日内动量信号测试."""
from __future__ import annotations

from watcher.models import MinuteBar
from watcher.signals import intraday_momentum as im


def _bars(points: list[tuple[str, float]], day: str = "20260729") -> list[MinuteBar]:
    return [
        MinuteBar(code="sh510500", ts=f"{day}{hhmm}00", open=px, high=px,
                  low=px, close=px, volume=1000, source="test")
        for hhmm, px in points
    ]


FULL_DAY = [("0935", 1.005), ("1000", 1.015), ("1200", 1.018),
            ("1400", 1.020), ("1430", 1.023), ("1435", 1.024)]


def test_long_signal_when_both_halves_positive():
    ctx = im.compute(_bars(FULL_DAY), prev_close=1.0)
    assert ctx is not None
    assert ctx.direction == "long"
    assert ctx.bucket == "早盘大涨"          # r_first = +1.5%
    assert ctx.r_first > 1.0
    assert ctx.r_pen > 0
    assert "上涨概率" in ctx.detail


def test_no_signal_when_morning_negative():
    pts = [("0935", 0.995), ("1000", 0.985), ("1400", 0.990),
           ("1430", 0.995), ("1435", 0.996)]
    ctx = im.compute(_bars(pts), prev_close=1.0)
    assert ctx is not None
    assert ctx.direction is None            # 早盘跌 → 不做多（也不发做空）
    assert ctx.bucket == "早盘大跌"


def test_no_signal_when_penultimate_negative():
    pts = [("0935", 1.005), ("1000", 1.015), ("1400", 1.020),
           ("1430", 1.016), ("1435", 1.017)]
    ctx = im.compute(_bars(pts), prev_close=1.0)
    assert ctx is not None
    assert ctx.direction is None            # 倒二半小时跌 → 不满足 M4
    assert ctx.r_pen < 0


def test_returns_none_before_1430():
    pts = [("0935", 1.005), ("1000", 1.015), ("1400", 1.020)]
    assert im.compute(_bars(pts), prev_close=1.0) is None


def test_returns_none_without_prev_close():
    assert im.compute(_bars(FULL_DAY), prev_close=0.0) is None


def test_returns_none_on_empty_bars():
    assert im.compute([], prev_close=1.0) is None


def test_bucket_boundaries_are_monotonic():
    """分档的历史均值必须随早盘涨幅单调递增（实测结论）."""
    exps = [exp for _lo, _label, exp, _p in im.BUCKETS]
    assert exps == sorted(exps, reverse=True)   # BUCKETS 按下界降序排列


def test_bucket_selection():
    cases = [(2.0, "早盘大涨"), (0.5, "早盘小涨"),
             (-0.5, "早盘小跌"), (-2.0, "早盘大跌")]
    for r, expect in cases:
        label, _exp, _p = im._bucket_of(r)
        assert label == expect, f"r_first={r} 应属于 {expect}，实际 {label}"
