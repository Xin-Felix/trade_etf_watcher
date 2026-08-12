"""冒烟测试：确认量价形态经 detect_resonance 走通（开关 → 信号 → 配对）."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from watcher.config import Config, SignalToggleConfig
from watcher.signals import rules
from watcher.signals.engine import SignalEngine
from watcher.state import StateStore


def main() -> None:
    code = sys.argv[1] if len(sys.argv) > 1 else "sh588000"
    cfg = Config.load()

    toggles = SignalToggleConfig()
    print("信号开关:", toggles.model_dump())
    assert toggles.volume_pattern is True, "量价形态应默认开启"
    assert not hasattr(toggles, "macd_cross"), "MACD 开关应已移除"

    store = StateStore()
    bars = store.get_bars(code, limit=2000)
    day = bars[-1].ts[:8]
    bars = [b for b in bars if b.ts[:8] == day]

    # 1) detect_resonance 直接产出
    raw = 0
    for i in range(30, len(bars) + 1):
        if rules.detect_resonance(bars[:i], code, cfg.name_for(code), cfg, toggles=toggles):
            raw += 1

    # 2) 经 SignalEngine 配对后的实际提醒（买→卖→买 交替）
    engine = SignalEngine(cfg)
    cfg.signal_toggles = toggles
    paired = []
    for i in range(30, len(bars) + 1):
        for sig in engine.detect_technical(code, cfg.name_for(code), bars[:i]):
            t = bars[i - 1].ts
            paired.append(f"{t[8:10]}:{t[10:12]} {sig.label} — {sig.detail}")

    print(f"\ndetect_resonance 原始信号 {raw} 个；配对后实际提醒 {len(paired)} 个:")
    for line in paired:
        print("  " + line)

    # 3) 关闭开关后应无信号
    off = SignalToggleConfig(volume_pattern=False)
    assert rules.detect_resonance(bars, code, "x", cfg, toggles=off) is None
    print("\n关闭开关后无信号 ✓")


if __name__ == "__main__":
    main()
