"""信号引擎."""
from __future__ import annotations

from watcher.config import Config
from watcher.models import MinuteBar, Quote, Signal
from watcher.signals import rules


class SignalEngine:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._tech_state: dict[str, str] = {}  # code -> 'buy'/'sell' 买卖交替状态
        self._tech_date: str = ""  # 当前交易日，跨天自动重置（日内T+0不隔夜）

    def _reset_tech_state_if_new_day(self, date: str) -> None:
        """每日开盘重置买卖状态（期权T+0日内交易，不带隔夜仓位）."""
        if date != self._tech_date:
            self._tech_state.clear()
            self._tech_date = date

    def detect(self, quote: Quote, latest_bar: MinuteBar | None = None) -> list[Signal]:
        signals: list[Signal] = []
        for fn in (
            rules.detect_gap,
            rules.detect_surge_plunge,
            rules.detect_rebound,
            rules.detect_reversal,
        ):
            sig = fn(quote, self.cfg)
            if sig:
                signals.append(sig)

        if latest_bar:
            sig = rules.detect_minute_signal(latest_bar, self.cfg, quote.name)
            if sig:
                signals.append(sig)

        return signals

    def detect_technical(self, code: str, name: str, bars: list[MinuteBar]) -> list[Signal]:
        """信号检测（买认购/买认沽），日内可多次配对，每日开盘重置.

        配对逻辑：空仓→做多信号→"买认购"→持仓→做空信号→"买认沽"（平仓）→空仓→...
        """
        if len(bars) < 30:
            return []

        # 每日重置（T+0 日内交易不隔夜）
        today = bars[-1].ts[:8] if bars[-1].ts else ""
        self._reset_tech_state_if_new_day(today)

        # 读取该标的当前状态
        last_side = self._tech_state.get(code)

        # 计算昨日高低（用于关键位突破）
        today_bars = [b for b in bars if b.ts[:8] == today]
        prev_bars = [b for b in bars if b.ts[:8] != today]
        prev_high = max((b.high for b in prev_bars), default=None) if prev_bars else None
        prev_low = min((b.low for b in prev_bars), default=None) if prev_bars else None

        # 用当天数据检测（VWAP 是日内指标）
        check_bars = today_bars if len(today_bars) >= 30 else bars

        sig = rules.detect_resonance(
            check_bars, code, name, self.cfg,
            prev_high, prev_low,
            toggles=self.cfg.signal_toggles,
        )
        if sig is None:
            return []

        # 配对逻辑：空仓只能买认购，持仓只能买认沽（平仓）
        if sig.key == "resonance_long" and last_side != "buy":
            self._tech_state[code] = "buy"
            return [sig]
        elif sig.key == "resonance_short" and last_side == "buy":
            self._tech_state[code] = "sell"
            return [sig]

        return []

    def detect_option_signals(
        self, option_quotes: list[dict], underlying_code: str, underlying_name: str
    ) -> list[Signal]:
        """检测期权信号（IV 飙升、PCR 异常）."""
        signals: list[Signal] = []
        signals.extend(
            rules.detect_iv_surge(option_quotes, underlying_code, underlying_name, self.cfg)
        )
        signals.extend(
            rules.detect_pcr_anomaly(option_quotes, underlying_code, underlying_name, self.cfg)
        )
        return signals
