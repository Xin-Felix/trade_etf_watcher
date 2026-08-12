"""后台盯盘轮询."""
from __future__ import annotations

import time
from datetime import datetime, timedelta

from PySide6.QtCore import QObject, QThread, Signal as QtSignal

from watcher.calendar import (
    is_polling_hours,
    is_trading_hours,
    set_trade_day_checker,
    today_str,
)
from watcher.config import Config
from watcher.fetchers.base import FetchChain
from watcher.fetchers.eastmoney import EastMoneyFetcher
from watcher.fetchers.tdx import TdxFetcher
from watcher.models import AppState, MinuteBar, Quote, Signal
from watcher.option_meta import (
    OptionQuoteFetcher,
    fetch_option_minute_bars_em,
    load_all_contracts,
    select_atm_contracts,
)
from watcher.signals import SignalEngine
from watcher.state import StateStore


class WatcherSignals(QObject):
    quotes_updated = QtSignal(dict)  # dict[str, Quote]
    signals_fired = QtSignal(list)  # list[Signal]
    option_quotes_updated = QtSignal(str)  # underlying_code
    state_changed = QtSignal(AppState)


class WatcherLoop(QThread):
    def __init__(self, cfg: Config, store: StateStore):
        super().__init__()
        self.cfg = cfg
        self.store = store
        self.signals = WatcherSignals()
        self._running = True
        self._paused = False
        self.engine = SignalEngine(cfg)
        self._fetchers = self._build_fetchers()
        self._option_fetcher = OptionQuoteFetcher()
        self._option_underlyings: list[str] = []
        self._option_index = 0
        self._last_contract_refresh: datetime | None = None
        self._force_refresh = False
        self._consecutive_failures = 0
        self._preload_done = False
        self._last_minute_refresh = 0.0
        self._atm_ptr: dict[str, int] = {}
        self._atm_em_fails = 0
        self._atm_em_cooldown_until = 0.0
        self._eod_snapshot_done = False  # 收盘前全量补数据标记（每天一次）
        self._momentum_alert_date = ""   # 日内动量提醒已推送的日期（每天一次）
        self._last_calendar_refresh: datetime | None = None
        # 交易日历查询注入 calendar 模块（节假日不轮询）
        set_trade_day_checker(self.store.is_trade_date)

    def _build_fetchers(self) -> FetchChain:
        fetchers: list = []
        for name in self.cfg.data_sources:
            if name == "tdx":
                fetchers.append(TdxFetcher([s.model_dump() for s in self.cfg.tdx_servers]))
            elif name == "eastmoney":
                fetchers.append(EastMoneyFetcher())
        return FetchChain(fetchers)

    def _refresh_trade_calendar(self) -> None:
        """从 Tushare 拉交易日历落地 SQLite（每天一次；无 token 或失败则沿用旧数据）.

        日历只影响"要不要轮询"，拉不到时 calendar 模块自动退回周末判断，不影响主流程。
        """
        if not (self.cfg.tushare.enabled and self.cfg.tushare.trade_calendar):
            return
        now = datetime.now()
        if self._last_calendar_refresh and (now - self._last_calendar_refresh) < timedelta(hours=24):
            return
        try:
            from watcher.fetchers.tushare_src import get_client, is_available

            if not is_available():
                self._last_calendar_refresh = now   # 没配 token 就别每轮都试
                return
            dates = get_client().fetch_trade_dates_around_today(back_days=60, forward_days=180)
            if dates:
                self.store.save_trade_dates(dates)
                self._last_calendar_refresh = now
                print(f"交易日历已更新：{len(dates)} 个交易日（{dates[0]}~{dates[-1]}）")
            else:
                # 失败也记时间，避免每轮重试打爆额度；下次启动再试
                self._last_calendar_refresh = now
        except Exception as exc:  # noqa: BLE001
            print(f"刷新交易日历失败: {exc}")
            self._last_calendar_refresh = now

    def _load_option_contracts(self) -> None:
        """启动时加载 ETF 期权合约元数据，每天刷新一次."""
        now = datetime.now()
        if self._last_contract_refresh and (now - self._last_contract_refresh) < timedelta(hours=6):
            return
        try:
            contracts = load_all_contracts()
            if contracts:
                self.store.save_option_contracts(contracts)
                self._option_underlyings = self.store.option_underlyings()
                self._last_contract_refresh = now
        except Exception as exc:  # noqa: BLE001
            print(f"加载期权合约失败: {exc}")

    def run(self) -> None:
        self.store.cleanup_old_data()
        self._refresh_trade_calendar()
        self._load_option_contracts()
        self._force_refresh = True  # 启动后立即刷新一次，确保非交易时段也能看到数据
        while self._running:
            if self._paused:
                self._sleep_interruptible(1)
                continue

            in_trading = is_trading_hours() or self.cfg.dev.mock_mode
            in_polling = is_polling_hours() or self.cfg.dev.mock_mode
            force = self._force_refresh
            self._force_refresh = False

            # 轮询时段之外（盘前/收盘后/周末）才跳过
            if self.cfg.app.trading_hours_only and not in_polling and not force:
                self._emit_state(connected=False, data_source="", error="非轮询时段")
                self._sleep_interruptible(self.cfg.app.poll_interval_seconds)
                continue

            # 1. ETF 标的快照轮询（最优先，保证现价实时）
            try:
                self._poll(detect_signals=in_trading or force)
            except Exception as exc:  # noqa: BLE001
                import traceback
                traceback.print_exc()
                self._emit_state(connected=False, data_source="", error=str(exc))

            # 2. 分钟 K 线刷新
            if time.monotonic() - self._last_minute_refresh >= self.cfg.app.minute_refresh_seconds:
                self._last_minute_refresh = time.monotonic()
                try:
                    self._refresh_minute_bars()
                except Exception as exc:  # noqa: BLE001
                    print(f"刷新分钟 K 线失败: {exc}")

                # 技术指标信号检测，仅交易时段
                if in_trading:
                    try:
                        self._detect_technical_signals()
                    except Exception as exc:  # noqa: BLE001
                        print(f"技术指标信号检测失败: {exc}")

            # 3. 期权全量行情（所有标的 × 所有月份）
            try:
                self._refresh_one_option_underlying()
            except Exception as exc:  # noqa: BLE001
                print(f"刷新期权行情失败: {exc}")

            # 4. 为一个标的缓存近价合约的东财分时K（轮换）
            if self._option_underlyings and (is_polling_hours() or self.cfg.dev.mock_mode):
                try:
                    cache_idx = self._option_index % len(self._option_underlyings)
                    self._option_index += 1
                    self._cache_atm_option_bars(self._option_underlyings[cache_idx])
                except Exception as exc:  # noqa: BLE001
                    print(f"缓存近价期权 K 线失败: {exc}")

            # 14:30 推送日内动量方向参考（每天一次）
            if in_trading:
                try:
                    self._try_intraday_momentum_alert()
                except Exception as exc:  # noqa: BLE001
                    print(f"日内动量提醒失败: {exc}")

            # 收盘前全量补数据（已改为每轮全量，此方法为 no-op）
            self._try_eod_snapshot()

            # 交易日历每 24 小时刷一次
            self._refresh_trade_calendar()

            # 第一轮轮询完成后再后台预加载期权分钟 K 线（避免拖慢启动）
            if not self._preload_done:
                self._preload_done = True
                try:
                    self._preload_option_bars()
                except Exception as exc:  # noqa: BLE001
                    print(f"预加载期权 K 线失败: {exc}")

            self._sleep_interruptible(self.cfg.app.poll_interval_seconds)

    def _sleep_interruptible(self, seconds: float) -> None:
        """可中断的 sleep，每秒检查一次退出标志，保证 stop() 能及时生效."""
        deadline = time.monotonic() + seconds
        while self._running and time.monotonic() < deadline:
            time.sleep(min(0.5, max(0.0, deadline - time.monotonic())))

    def _preload_option_bars(self) -> None:
        """启动时预加载沪市 ETF 期权的分钟 K 线，用于图表展示."""
        from watcher.option_meta import fetch_option_minute_bars

        date = today_str()
        # 只加载沪市标的（新浪接口支持），每次最多取前 20 个合约避免过慢
        for underlying in self._option_underlyings[:3]:
            contracts = self.store.get_option_contracts(underlying)[:20]
            for c in contracts:
                if not c.option_code.startswith("10"):
                    continue
                for bar in fetch_option_minute_bars(c.option_code):
                    self.store.save_bar(bar, date)

    def _refresh_minute_bars(self) -> None:
        """并发批量拉取全部 watchlist 标的的分钟 K 并保存."""
        codes = self.cfg.watch_codes()
        batch = self._fetchers.fetch_minute_bars_batch(codes, limit=120)
        for bars in batch.values():
            if bars:
                self.store.save_bars(bars, today_str())

    def _detect_technical_signals(self) -> None:
        """基于本地 5 分钟 K 线检测技术指标信号（RSI/布林带/KDJ/放量突破）."""
        from watcher.bars import aggregate_minute_bars

        date = today_str()
        new_signals: list[Signal] = []
        for item in self.cfg.watchlist:
            # 用 5 分钟级别检测（过滤噪音，买方日内常用周期）
            bars1 = self.store.get_bars(item.code, limit=200)
            if len(bars1) < 30:
                continue
            bars5 = aggregate_minute_bars(bars1, 5)
            if len(bars5) < 25:
                continue
            signals = self.engine.detect_technical(item.code, item.name, bars5)
            for sig in signals:
                # 技术指标信号需要一天内多次触发（买卖配对），key 加时间戳避免去重
                unique_sig = Signal(
                    key=f"{sig.key}_{sig.ts[8:12] if len(sig.ts) >= 12 else ''}",
                    code=sig.code,
                    name=sig.name,
                    label=sig.label,
                    detail=sig.detail,
                    level=sig.level,
                    ts=sig.ts,
                )
                if self.store.save_signal(unique_sig, date):
                    new_signals.append(unique_sig)
        if new_signals:
            self.signals.signals_fired.emit(new_signals)

    def _poll(self, detect_signals: bool = True) -> None:
        self._load_option_contracts()
        codes = self.cfg.watch_codes()
        result = self._fetchers.fetch(codes)

        if not result:
            self._consecutive_failures += 1
            # 失败时也发缓存数据，保证界面有内容
            cached = self.store.latest_quotes()
            if cached:
                self.signals.quotes_updated.emit(cached)
            if self._consecutive_failures >= 3:
                # 连续失败才标记未连接
                self._emit_state(connected=False, data_source=result.source, error=result.error)
            else:
                self._emit_state(
                    connected=True,
                    data_source=f"{result.source or '缓存'}(重试{self._consecutive_failures})",
                    error="",
                    quotes=cached,
                )
            return

        self._consecutive_failures = 0
        date = today_str()
        new_signals: list[Signal] = []

        for code, quote in result.quotes.items():
            # 补全中文名称
            if not quote.name or quote.name == code:
                quote.name = self.cfg.name_for(code)

            self.store.save_quote(quote, date)
            if detect_signals:
                # 从已保存的分钟 K 线中取最新一根用于信号检测
                bars = self.store.get_bars(code, limit=1)
                latest_bar = bars[0] if bars else None

                signals = self.engine.detect(quote, latest_bar)
                for sig in signals:
                    if self.store.save_signal(sig, date):
                        new_signals.append(sig)

        self.signals.quotes_updated.emit(result.quotes)
        if new_signals:
            self.signals.signals_fired.emit(new_signals)

        self._emit_state(
            connected=True,
            data_source=result.source,
            error="",
            quotes=result.quotes,
        )

    def _refresh_one_option_underlying(self) -> str | None:
        """刷新一个标的的近月期权行情（轮换），返回该标的代码."""
        if not self._option_underlyings:
            self._option_underlyings = self.store.option_underlyings()
        if not self._option_underlyings:
            return None

        underlying = self._option_underlyings[self._option_index % len(self._option_underlyings)]
        self._option_index += 1

        contracts = self.store.get_option_contracts(underlying)
        if not contracts:
            return underlying

        # 后台轮询只拉近月（保证快速 + 分时K缓存正常）
        nearest_expiry = min(c.expire_date for c in contracts)
        contracts = [c for c in contracts if c.expire_date == nearest_expiry]

        batch_size = 50
        all_quotes: list[dict] = []
        for i in range(0, len(contracts), batch_size):
            if i > 0:
                time.sleep(0.3)
            batch = contracts[i : i + batch_size]
            codes = [c.option_code for c in batch]
            quotes = self._option_fetcher.fetch(codes)
            for c in batch:
                q = quotes.get(c.option_code)
                if q:
                    q["option_code"] = c.option_code
                    q["underlying_code"] = c.underlying_code
                    q["option_type"] = c.option_type
                    q["strike"] = c.strike
                    if not q.get("name"):
                        q["name"] = c.option_name
                    if not q.get("expire_date"):
                        q["expire_date"] = c.expire_date
                    all_quotes.append(q)

        if all_quotes:
            self.store.save_option_quotes(all_quotes)
            self.signals.option_quotes_updated.emit(underlying)

            if is_trading_hours() or self.cfg.dev.mock_mode:
                underlying_name = self.cfg.name_for(underlying)
                option_sigs = self.engine.detect_option_signals(
                    all_quotes, underlying, underlying_name
                )
                new_sigs: list[Signal] = []
                date = today_str()
                for sig in option_sigs:
                    if self.store.save_signal(sig, date):
                        new_sigs.append(sig)
                if new_sigs:
                    self.signals.signals_fired.emit(new_sigs)

        return underlying

    def refresh_option_full(self, underlying: str) -> None:
        """手动触发：拉取指定标的全部月份期权行情（T型页打开时调用）."""
        contracts = self.store.get_option_contracts(underlying)
        if not contracts:
            return

        batch_size = 50
        all_quotes: list[dict] = []
        for i in range(0, len(contracts), batch_size):
            if i > 0:
                time.sleep(0.3)
            batch = contracts[i : i + batch_size]
            codes = [c.option_code for c in batch]
            quotes = self._option_fetcher.fetch(codes)
            for c in batch:
                q = quotes.get(c.option_code)
                if q:
                    q["option_code"] = c.option_code
                    q["underlying_code"] = c.underlying_code
                    q["option_type"] = c.option_type
                    q["strike"] = c.strike
                    if not q.get("name"):
                        q["name"] = c.option_name
                    if not q.get("expire_date"):
                        q["expire_date"] = c.expire_date
                    all_quotes.append(q)

        if all_quotes:
            self.store.save_option_quotes(all_quotes)
            self.signals.option_quotes_updated.emit(underlying)

    def _cache_atm_option_bars(self, underlying: str) -> None:
        """每轮为该标的缓存 1 个近价合约的东财分时 K（1 请求/轮，温和限速）.

        覆盖最近到期、ATM±2 档、认购认沽约 10 个合约/标的，轮换指针逐个刷，
        约 7-8 分钟全量一遍；盘后东财停供时，蜡烛图回落到本地缓存可看.
        连续失败 5 次判定东财疑似封禁，冷却 10 分钟避免撞墙加重封禁.
        """
        now = time.monotonic()
        if now < self._atm_em_cooldown_until:
            return
        uq = self.store.latest_quotes().get(underlying)
        if not uq or uq.price <= 0:
            return
        pool = select_atm_contracts(self.store.get_option_contracts(underlying), uq.price)
        if not pool:
            return
        idx = self._atm_ptr.get(underlying, 0)
        self._atm_ptr[underlying] = (idx + 1) % len(pool)
        code = pool[idx].option_code
        bars = fetch_option_minute_bars_em(code)
        if bars:
            self.store.save_bars(bars, today_str())
            self._atm_em_fails = 0
        else:
            self._atm_em_fails += 1
            if self._atm_em_fails >= 5:
                self._atm_em_cooldown_until = now + 600
                self._atm_em_fails = 0

    def _try_intraday_momentum_alert(self) -> None:
        """14:30-14:40 之间推送一次日内动量方向参考（每天一次）.

        依据 Gao et al.(2018) 市场日内动量，本地一年 ETF 数据实测 t=+5.00，
        详见 watcher/signals/intraday_momentum.py 模块说明。
        """
        from datetime import time as dt_time

        from watcher.calendar import now_sh
        from watcher.signals import intraday_momentum

        if not getattr(self.cfg.signal_toggles, "intraday_momentum", True):
            return

        now = now_sh()
        t = now.time()
        if not (dt_time(14, 30) <= t <= dt_time(14, 40)):
            return
        date = today_str()
        if self._momentum_alert_date == date:
            return

        today = date.replace("-", "")
        quotes = self.store.latest_quotes()
        hits: list[Signal] = []
        for item in self.cfg.watchlist:
            q = quotes.get(item.code)
            if not q or q.prev_close <= 0:
                continue
            bars = [b for b in self.store.get_bars(item.code, limit=400)
                    if b.ts[:8] == today]
            ctx = intraday_momentum.compute(bars, q.prev_close)
            if ctx is None or ctx.direction != "long":
                continue
            hits.append(Signal(
                key=f"intraday_momentum_{today}",
                code=item.code,
                name=item.name,
                label="尾盘偏多",
                detail=ctx.detail,
                level="info",
                ts=bars[-1].ts if bars else "",
            ))

        # 标记为已处理（即使今天没有标的命中，也不再重复扫）
        self._momentum_alert_date = date
        if not hits:
            print(f"[日内动量] {date} 无标的满足做多条件")
            return

        new_sigs = [s for s in hits if self.store.save_signal(s, date)]
        if new_sigs:
            names = "、".join(s.name for s in new_sigs)
            print(f"[日内动量] {date} 尾盘偏多: {names}")
            self.signals.signals_fired.emit(new_sigs)

    def _try_eod_snapshot(self) -> None:
        """收盘前（14:55-15:00）全量拉取所有月份期权行情存 DB，每天只做一次."""
        from datetime import time as dt_time
        from watcher.calendar import now_sh

        now = now_sh()
        t = now.time()
        if not (dt_time(14, 55) <= t <= dt_time(15, 0)):
            if t < dt_time(9, 0):
                self._eod_snapshot_done = False
            return
        if self._eod_snapshot_done:
            return
        self._eod_snapshot_done = True
        print("收盘前全量补数据：拉取所有月份期权行情...")
        for underlying in self._option_underlyings:
            self.refresh_option_full(underlying)
            time.sleep(0.5)
            if not self._running:
                break
        print("收盘前全量补数据完成")
        # 存储每日快照（IV/OI/价格等历史数据，用于趋势分析）
        try:
            from watcher.calendar import today_str
            date_str = today_str().replace("-", "")
            n = self.store.save_option_daily_snapshot(date_str)
            print(f"每日期权快照已存储：{date_str}，{n} 条记录")
        except Exception as exc:  # noqa: BLE001
            print(f"存储每日期权快照失败: {exc}")

    def _emit_state(
        self,
        connected: bool,
        data_source: str,
        error: str,
        quotes: dict[str, Quote] | None = None,
    ) -> None:
        state = AppState(
            quotes=quotes or {},
            connected=connected,
            data_source=data_source,
            error_message=error,
        )
        self.signals.state_changed.emit(state)

    def stop(self) -> None:
        """优雅停止：sleep 可中断所以通常 1 秒内退出；最坏等 12 秒覆盖一次网络请求."""
        self._running = False
        if not self.wait(12000):
            # 线程卡在不可中断的网络调用上，强制结束（比进程崩溃好）
            self.terminate()
            self.wait(2000)
        self._fetchers.close()
        self._option_fetcher.close()

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    def refresh_now(self) -> None:
        """由 GUI 调用，下一轮立即执行一次完整刷新."""
        self._force_refresh = True

    def option_underlyings(self) -> list[str]:
        return self._option_underlyings or self.store.option_underlyings()

    def fetch_daily_bars(self, code: str, limit: int = 120) -> list[MinuteBar]:
        """供 GUI 按需拉日 K（走 FetchChain：TDX → 其他）."""
        return self._fetchers.fetch_daily_bars(code, limit)
