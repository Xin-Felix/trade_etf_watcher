"""信号层包."""
from watcher.signals.engine import SignalEngine
from watcher.signals.patterns import (
    PatternResult,
    compute_features,
    detect_patterns,
    trigger_volume_pattern,
)
from watcher.signals.rules import (
    detect_gap,
    detect_iv_surge,
    detect_minute_signal,
    detect_pcr_anomaly,
    detect_rebound,
    detect_resonance,
    detect_reversal,
    detect_surge_plunge,
)

__all__ = [
    "SignalEngine",
    "detect_gap",
    "detect_surge_plunge",
    "detect_rebound",
    "detect_reversal",
    "detect_minute_signal",
    "detect_iv_surge",
    "detect_pcr_anomaly",
    "detect_resonance",
    "detect_patterns",
    "compute_features",
    "trigger_volume_pattern",
    "PatternResult",
]
