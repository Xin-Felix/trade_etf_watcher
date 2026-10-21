"""指数参与买卖点检测的口径测试.

指数也跑量价形态检测，但**只入库供查看、不进提醒** —— 指数不可交易，
弹窗和系统通知只会是噪音。
"""
from watcher.config import Config
from watcher.models import Signal
from watcher.watcher_loop import WatcherLoop


def _session_minutes(n: int) -> list[str]:
    """跨交易日的分钟时间戳 YYYYMMDDHHMM（09:30-11:29 + 13:00-14:59）.

    必须落在真实时段内：`aggregate_minute_bars` 按 A 股时段分桶，
    盘前/午休的时间戳会被丢掉。15 分档聚合要 ≥25 根，单日 240 分钟不够，
    所以铺到多个交易日。
    """
    hhmm: list[str] = []
    for h, m0, m1 in ((9, 30, 60), (10, 0, 60), (11, 0, 30),
                      (13, 0, 60), (14, 0, 60)):
        for m in range(m0, m1):
            hhmm.append(f"{h:02d}{m:02d}")
    # 跨多个交易日铺满 n 根：单日 240 分钟，15 分聚合要 ≥25 根 → 至少 2 天
    days = ["20260901", "20260902", "20260903"]
    out: list[str] = []
    for d in days:
        for t in hhmm:
            out.append(d + t)
            if len(out) >= n:
                return out
    return out


class _ProbeStore:
    """记录入库调用；bars 给足数量让检测不被长度门槛挡掉."""

    def __init__(self):
        self.saved: list[Signal] = []

    def get_bars(self, code, limit=200):
        from watcher.models import MinuteBar

        return [
            MinuteBar(code=code, ts=ts,
                      open=10.0, high=10.1, low=9.9, close=10.0,
                      volume=1000, source="t")
            for ts in _session_minutes(limit)
        ]

    def save_signal(self, sig, date):
        self.saved.append(sig)
        return True


class _HitEngine:
    """必定命中，用来验证路由而不是形态算法."""

    def __init__(self):
        self.called: list[str] = []

    def detect_technical(self, code, name, bars, state_key=None):
        # state_key 带周期后缀（code@1m 等）；记录以便断言三周期都检测了
        self.called.append(state_key or code)
        return [Signal(key="resonance_long", code=code, name=name,
                       label="多头共振", detail="", level="info", ts="202609031030")]


class _Emitter:
    def __init__(self):
        self.batches: list[list[Signal]] = []

    def emit(self, v):
        self.batches.append(v)


class _Loop:
    """只借 _detect_technical_signals 这一个方法（连同它用到的类属性）."""

    _detect_technical_signals = WatcherLoop._detect_technical_signals
    _TECH_PERIODS = WatcherLoop._TECH_PERIODS
    _ALERT_PERIOD = WatcherLoop._ALERT_PERIOD

    def __init__(self, cfg):
        self.cfg = cfg
        self.store = _ProbeStore()
        self.engine = _HitEngine()
        self.signals = type("S", (), {"signals_fired": _Emitter()})()


def _run():
    cfg = Config.load()
    loop = _Loop(cfg)
    loop._detect_technical_signals()
    idx = {i.code for i in cfg.indices}
    wl = {i.code for i in cfg.watchlist}
    saved = {s.code for s in loop.store.saved}
    fired = {s.code for b in loop.signals.signals_fired.batches for s in b}
    return cfg, idx, wl, saved, fired, loop


def test_indices_are_detected():
    """指数要进检测循环（原来只遍历 watchlist），且每个标的三周期都检测."""
    cfg, idx, wl, _, _, loop = _run()
    # called 形如 'sh510300@1m'，剥掉周期后缀比对标的
    called_codes = {c.split("@")[0] for c in loop.engine.called}
    assert idx <= called_codes, f"漏了这些指数：{sorted(idx - called_codes)}"
    assert wl <= called_codes, f"漏了这些 ETF：{sorted(wl - called_codes)}"
    # 每个标的应在 1m/5m/15m 三个周期各检测一次
    for code in idx | wl:
        periods = {c.split("@")[1] for c in loop.engine.called if c.split("@")[0] == code}
        assert periods == {"1m", "5m", "15m"}, f"{code} 只检测了 {periods}"


def test_index_signals_are_stored_for_viewing():
    """指数信号要入库，看板的「最新买卖点」列和今日信号才看得到."""
    _, idx, _, saved, _, _ = _run()
    assert idx <= saved, f"这些指数没入库：{sorted(idx - saved)}"


def test_index_signals_never_alert():
    """指数不可交易，不该弹窗/通知."""
    _, idx, _, _, fired, _ = _run()
    assert not (idx & fired), f"指数进了提醒：{sorted(idx & fired)}"


def test_etf_signals_still_alert():
    """ETF 的提醒行为不变（每个 ETF 至少有一条进提醒）."""
    _, _, wl, _, fired, _ = _run()
    assert wl <= fired, f"这些 ETF 没进提醒：{sorted(wl - fired)}"


def test_only_5m_period_alerts():
    """三周期都检测入库，但只有 5 分档进提醒（1 分太吵、15 分太钝）."""
    _, _, _, _, _, loop = _run()
    fired_keys = [s.key for b in loop.signals.signals_fired.batches for s in b]
    assert fired_keys, "没有任何提醒（桩必定命中，应有 5m 的）"
    assert all("_5m_" in k for k in fired_keys), \
        f"提醒里混进了非 5 分周期的信号：{[k for k in fired_keys if '_5m_' not in k]}"


def test_all_periods_stored():
    """1/5/15 分三档都要入库（看板要分列显示）."""
    _, _, _, _, _, loop = _run()
    keys = [s.key for s in loop.store.saved]
    for tag in ("_1m_", "_5m_", "_15m_"):
        assert any(tag in k for k in keys), f"没有 {tag} 档的信号入库"
