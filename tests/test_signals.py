"""基础单元测试."""
from watcher.config import Config
from watcher.models import Quote
from watcher.signals import SignalEngine


def test_gap_up_signal():
    cfg = Config.load()
    engine = SignalEngine(cfg)
    quote = Quote(
        code="sh510300",
        name="沪深300ETF",
        price=4.8,
        open=4.75,
        high=4.8,
        low=4.7,
        prev_close=4.65,
    )
    sigs = engine.detect(quote)
    keys = {s.key for s in sigs}
    assert "gap_up" in keys
    assert "surge" in keys


def test_plunge_signal():
    cfg = Config.load()
    engine = SignalEngine(cfg)
    quote = Quote(
        code="sh510300",
        name="沪深300ETF",
        price=4.55,
        open=4.60,
        high=4.60,
        low=4.55,
        prev_close=4.65,
    )
    sigs = engine.detect(quote)
    keys = {s.key for s in sigs}
    assert "plunge" in keys


def test_rebound_signal():
    cfg = Config.load()
    engine = SignalEngine(cfg)
    quote = Quote(
        code="sh510300",
        name="沪深300ETF",
        price=4.67,
        open=4.66,
        high=4.67,
        low=4.60,
        prev_close=4.65,
    )
    sigs = engine.detect(quote)
    keys = {s.key for s in sigs}
    assert "rebound" in keys


def test_daily_dedup():
    import tempfile
    from pathlib import Path
    from watcher.state import StateStore
    from watcher.calendar import today_str
    from watcher.models import Signal

    with tempfile.TemporaryDirectory() as tmpdir:
        store = StateStore(Path(tmpdir) / "test.db")
        sig = Signal(
            key="surge",
            code="sh510300",
            name="沪深300ETF",
            label="急涨",
            detail="test",
            level="warning",
        )
        date = today_str()
        assert store.save_signal(sig, date) is True
        assert store.save_signal(sig, date) is False
