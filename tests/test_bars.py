"""分钟 K 聚合测试（交易时段感知）."""
from watcher.bars import aggregate_minute_bars
from watcher.models import MinuteBar


def _bar(hh, mm, o, h, l, c, v=10, day="20260722"):
    return MinuteBar(code="10011799", ts=f"{day}{hh:02d}{mm:02d}00",
                     open=o, high=h, low=l, close=c, volume=v, source="eastmoney_option")


def test_aggregate_5min_basic():
    bars = [_bar(9, 30+i, 1.0+i*0.01, 1.02+i*0.01, 0.99+i*0.01, 1.01+i*0.01) for i in range(10)]
    out = aggregate_minute_bars(bars, 5)
    assert len(out) == 2
    # 第一根：open=首根open，close=第5根close，high=区间最高，volume求和
    assert out[0].open == 1.0
    assert out[0].close == 1.05
    assert out[0].high == 1.06
    assert out[0].low == 0.99
    assert out[0].volume == 50
    assert out[0].ts.endswith("093400")
    assert out[1].open == 1.05


def test_aggregate_60min_session_alignment():
    """60 分应得 4 根：09:30-10:30 / 10:30-11:30 / 13:00-14:00 / 14:00-15:00."""
    bars = []
    # 上午 121 根（09:30-11:30，含 11:30 收盘点）
    for i in range(121):
        t = 570 + i
        bars.append(_bar(t // 60, t % 60, 1.0, 1.1, 0.9, 1.05, v=1))
    # 下午 121 根（13:00-15:00，含 15:00）
    for i in range(121):
        t = 780 + i
        bars.append(_bar(t // 60, t % 60, 1.1, 1.2, 1.0, 1.15, v=2))
    out = aggregate_minute_bars(bars, 60)
    assert len(out) == 4
    # 11:30 并入上午最后一根（volume=61），不串到下午
    assert out[1].volume == 61
    assert out[1].ts.endswith("113000")
    # 15:00 并入下午最后一根
    assert out[3].volume == 122
    assert out[3].ts.endswith("150000")
    # 每根 OHLC 关系合法
    for b in out:
        assert b.low <= min(b.open, b.close) <= max(b.open, b.close) <= b.high


def test_aggregate_cross_day_not_mixed():
    bars = [_bar(14, 59, 1.0, 1.1, 0.9, 1.05, day="20260721"),
            _bar(9, 30, 2.0, 2.1, 1.9, 2.05, day="20260722")]
    out = aggregate_minute_bars(bars, 60)
    assert len(out) == 2  # 跨天不合并


def test_aggregate_auction_into_first_bucket():
    bars = [_bar(9, 25, 1.0, 1.0, 1.0, 1.0, v=5),  # 集合竞价
            _bar(9, 30, 1.1, 1.2, 1.0, 1.15, v=10),
            _bar(9, 31, 1.15, 1.2, 1.1, 1.12, v=10)]
    out = aggregate_minute_bars(bars, 5)
    assert len(out) == 1
    assert out[0].volume == 25
    assert out[0].open == 1.0  # 开盘价取集合竞价那根


def test_aggregate_n1_passthrough():
    bars = [_bar(9, 30, 1, 1, 1, 1), _bar(9, 31, 2, 2, 2, 2)]
    assert aggregate_minute_bars(bars, 1) == bars
