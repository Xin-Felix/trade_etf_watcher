"""期权信号检测测试（IV 飙升 + PCR 异常）."""
from watcher.config import Config
from watcher.signals.rules import detect_iv_surge, detect_pcr_anomaly


def _cfg(iv_surge=0.50, pcr_high=1.5, pcr_low=0.5) -> Config:
    return Config.model_validate(
        {"thresholds": {"iv_surge": iv_surge, "pcr_high": pcr_high, "pcr_low": pcr_low}}
    )


# ===== IV 飙升 =====


def test_iv_surge_triggered():
    quotes = [
        {"option_code": "10007001", "option_name": "50ETF购8月3.0", "iv": 0.55, "ts": "14:30:00"},
        {"option_code": "10007002", "option_name": "50ETF沽8月3.0", "iv": 0.30, "ts": "14:30:00"},
    ]
    sigs = detect_iv_surge(quotes, "sh510050", "上证50ETF", _cfg())
    assert len(sigs) == 1
    assert sigs[0].key == "iv_surge"
    assert sigs[0].code == "sh510050"
    assert "55.0%" in sigs[0].detail
    assert "10007001" in sigs[0].detail


def test_iv_surge_not_triggered_below_threshold():
    quotes = [
        {"option_code": "10007001", "option_name": "50ETF购8月3.0", "iv": 0.45, "ts": "14:30:00"},
        {"option_code": "10007002", "option_name": "50ETF沽8月3.0", "iv": 0.30, "ts": "14:30:00"},
    ]
    sigs = detect_iv_surge(quotes, "sh510050", "上证50ETF", _cfg())
    assert sigs == []


def test_iv_surge_empty_quotes():
    sigs = detect_iv_surge([], "sh510050", "上证50ETF", _cfg())
    assert sigs == []


def test_iv_surge_zero_iv():
    quotes = [{"option_code": "10007001", "option_name": "test", "iv": 0.0, "ts": ""}]
    sigs = detect_iv_surge(quotes, "sh510050", "上证50ETF", _cfg())
    assert sigs == []


# ===== PCR 异常 =====


def test_pcr_high_triggered():
    quotes = [
        {"option_type": "call", "open_interest": 1000},
        {"option_type": "call", "open_interest": 2000},
        {"option_type": "put", "open_interest": 3000},
        {"option_type": "put", "open_interest": 2000},
    ]
    # PCR = 5000 / 3000 = 1.67 > 1.5
    sigs = detect_pcr_anomaly(quotes, "sh510050", "上证50ETF", _cfg())
    assert len(sigs) == 1
    assert sigs[0].key == "pcr_high"
    assert sigs[0].code == "sh510050"
    assert "1.67" in sigs[0].detail


def test_pcr_low_triggered():
    quotes = [
        {"option_type": "call", "open_interest": 5000},
        {"option_type": "put", "open_interest": 2000},
    ]
    # PCR = 2000 / 5000 = 0.4 < 0.5
    sigs = detect_pcr_anomaly(quotes, "sh510050", "上证50ETF", _cfg())
    assert len(sigs) == 1
    assert sigs[0].key == "pcr_low"
    assert "0.40" in sigs[0].detail


def test_pcr_normal_no_signal():
    quotes = [
        {"option_type": "call", "open_interest": 3000},
        {"option_type": "put", "open_interest": 3000},
    ]
    # PCR = 1.0 — 在正常区间 (0.5, 1.5)
    sigs = detect_pcr_anomaly(quotes, "sh510050", "上证50ETF", _cfg())
    assert sigs == []


def test_pcr_zero_call_oi_no_signal():
    quotes = [
        {"option_type": "call", "open_interest": 0},
        {"option_type": "put", "open_interest": 3000},
    ]
    # call_oi = 0 → 除零保护，不发信号
    sigs = detect_pcr_anomaly(quotes, "sh510050", "上证50ETF", _cfg())
    assert sigs == []


def test_pcr_empty_quotes():
    sigs = detect_pcr_anomaly([], "sh510050", "上证50ETF", _cfg())
    assert sigs == []


# ===== SignalEngine.detect_option_signals =====


def test_engine_detect_option_signals():
    from watcher.signals.engine import SignalEngine

    cfg = _cfg(iv_surge=0.40, pcr_high=1.2, pcr_low=0.3)
    engine = SignalEngine(cfg)
    quotes = [
        {"option_code": "10007001", "option_name": "高IV合约", "iv": 0.60, "ts": "",
         "option_type": "call", "open_interest": 1000},
        {"option_code": "10007002", "option_name": "沽合约", "iv": 0.20, "ts": "",
         "option_type": "put", "open_interest": 2000},
    ]
    sigs = engine.detect_option_signals(quotes, "sh510050", "上证50ETF")
    keys = {s.key for s in sigs}
    # IV=0.60 > 0.40 → iv_surge; PCR=2000/1000=2.0 > 1.2 → pcr_high
    assert "iv_surge" in keys
    assert "pcr_high" in keys
