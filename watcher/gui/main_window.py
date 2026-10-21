"""主窗口（HTML/ECharts 版）."""
from __future__ import annotations

import os

from PySide6.QtCore import QObject, QPoint, Qt, QRunnable, QThreadPool, QTimer, Slot
from PySide6.QtCore import Signal as QtSignal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from watcher.bars import aggregate_minute_bars
from watcher.calendar import is_polling_hours, parse_quote_time, signal_display_time, today_str
from watcher.config import Config
from watcher.gui.web.webtab import VueTab
from watcher.models import AppState, MinuteBar, Quote, Signal
from watcher.notify.desktop import Notifier
from watcher.option_meta import (
    build_tshape_data,
    fetch_option_daily_bars,
    fetch_option_minute_bars,
    fetch_option_minute_bars_em,
)
from watcher.state import StateStore
from watcher.watcher_loop import WatcherLoop


class _ChartJobSignals(QObject):
    """期权图表后台取数完成信号（QRunnable 不能有信号，借它转发）."""

    finished = QtSignal(int, object, object)  # seq, payload, quote
    ai_finished = QtSignal(object)            # AI 策略结果


class _ChartJob(QRunnable):
    """在工作线程拉期权图表数据（网络请求可能秒级，绝不能跑在 GUI 线程）."""

    def __init__(self, mw: "MainWindow", seq: int, code: str, name: str, period: str, signals: _ChartJobSignals):
        super().__init__()
        self._mw = mw
        self._seq = seq
        self._code = code
        self._name = name
        self._period = period
        self._signals = signals

    def run(self) -> None:
        payload = quote = None
        if self._seq == self._mw._chart_seq:  # 已被更新的点击取代的请求直接丢弃
            try:
                bars, mode, label_fmt, periods = self._mw._option_chart_data(self._code, self._period)
                payload = self._mw._build_chart_payload(
                    self._code, self._name, bars, mode, label_fmt, self._period, periods
                )
                quote = self._mw._chart_quote(self._code)
            except Exception:  # noqa: BLE001
                import traceback

                traceback.print_exc()
                payload = None
        self._signals.finished.emit(self._seq, payload, quote)


class _ChartWindow(QWidget):
    """K 线图的顶层窗口.

    只为了在关闭时通知主窗口一声（把焦点交还回去），别的行为跟裸 QWidget 一样。
    刻意不设 parent —— 有 parent 就不是独立窗口了，不能单独摆放/最小化。
    也刻意不设 WA_DeleteOnClose：关掉只是隐藏，里面的 QWebEngineView 要复用，
    销毁重建既慢又容易踩 WebEngine 的 profile 生命周期问题。
    """

    def __init__(self, owner: MainWindow):
        super().__init__()
        self._owner = owner

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        super().closeEvent(event)
        if event.isAccepted():
            self._owner._on_chart_window_closed()


class MainWindow(QWidget):
    def __init__(self, cfg: Config, store: StateStore, watcher: WatcherLoop, tray):
        super().__init__()
        self.cfg = cfg
        self.store = store
        self.watcher = watcher
        self.tray = tray

        self.setWindowTitle(cfg.app.name)
        self.resize(1200, 760)
        # 窗口图标（红底金字）
        if tray:
            self.setWindowIcon(tray.icon())

        self._apply_styles()

        self.notifier = Notifier(tray, cfg)
        self.notifier.signal_received.connect(self._show_alert)
        self.notifier.notification_clicked.connect(self._on_notification_clicked)

        self._build_ui()
        self._connect_signals()
        # 从 DB 恢复信号开关配置（覆盖 config.yaml 默认值）
        self.cfg.signal_toggles = self._load_signal_toggles()
        # 从 DB 加载 API keys 到环境变量（覆盖 secrets.env，方便 GUI 内修改后生效）
        self._restore_api_keys()
        self._load_cached_quotes()
        self._populate_option_underlyings()

        # K 线页自动刷新（跟随轮询周期；只在页签可见且轮询时段内真正发请求）
        self._chart_timer = QTimer(self)
        self._chart_timer.timeout.connect(self._auto_refresh_chart)
        self._chart_timer.start(max(5, cfg.app.poll_interval_seconds) * 1000)

        # 期权图表后台取数线程池（网络请求不占 GUI 线程；序号防乱序覆盖）
        self._chart_pool = QThreadPool(self)
        self._chart_pool.setMaxThreadCount(2)
        self._chart_job_signals = _ChartJobSignals(self)
        self._chart_job_signals.finished.connect(self._on_option_chart_ready)
        self._chart_job_signals.ai_finished.connect(self._deliver_ai_result)
        self._chart_seq = 0
        self._chart_inflight = 0
        # 点 K 线买卖点跳 T 型页时要带的方向（'call'/'put'），渲染一次即清空
        self._pending_tshape_filter = ""

        if self.cfg.watch_codes():
            # 只记下默认标的，不弹窗也不取数：K 线是独立窗口，
            # 等用户点标的时 _load_chart 才会打开并刷新。
            first_code = self.cfg.watch_codes()[0]
            self._chart_code = first_code
            self._chart_name = self.cfg.name_for(first_code)

    def _apply_styles(self) -> None:
        self.setStyleSheet("""
            QWidget { background-color: #1e1e1e; color: #e0e0e0; font-size: 13px; }
            QPushButton {
                background-color: #3a3a3a; color: #ffffff; border: none;
                border-radius: 6px; padding: 8px 16px;
            }
            QPushButton:hover { background-color: #ff9800; color: #1a1a1a; }
            QTabWidget::pane {
                border: 1px solid #3a3a3a; border-radius: 6px;
                background-color: #1e1e1e; top: -1px;
            }
            QTabBar::tab {
                background-color: #2d2d2d; color: #aaaaaa; padding: 10px 22px;
                border-top-left-radius: 6px; border-top-right-radius: 6px; margin-right: 2px;
            }
            QTabBar::tab:selected { background-color: #ff9800; color: #1a1a1a; font-weight: bold; }
            QTabBar::tab:hover:!selected { background-color: #3d3d3d; color: #ffffff; }
            QListWidget {
                background-color: #252525; border: 1px solid #3a3a3a;
                border-radius: 6px; outline: none;
            }
            QListWidget::item { padding: 10px; border-bottom: 1px solid #333333; }
            QListWidget::item:selected { background-color: #ff9800; color: #1a1a1a; font-weight: bold; }
            QListWidget::item:hover:!selected { background-color: #3d3d3d; }
            QLabel { color: #e0e0e0; }
            QSplitter::handle { background-color: #3a3a3a; }
        """)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        header = QHBoxLayout()
        self.status_label = QLabel("状态: 初始化...")
        header.addWidget(self.status_label)
        header.addStretch()

        self.refresh_btn = QPushButton("立即刷新")
        self.refresh_btn.clicked.connect(self._manual_refresh)
        header.addWidget(self.refresh_btn)

        self.test_btn = QPushButton("测试预警")
        self.test_btn.clicked.connect(self._test_alert)
        header.addWidget(self.test_btn)

        self.signal_cfg_btn = QPushButton("信号配置")
        self.signal_cfg_btn.clicked.connect(self._show_signal_config)
        header.addWidget(self.signal_cfg_btn)

        self.api_key_btn = QPushButton("API 设置")
        self.api_key_btn.clicked.connect(self._show_api_key_config)
        header.addWidget(self.api_key_btn)

        layout.addLayout(header)

        self.tabs = QTabWidget()

        # 行情看板已迁到 Vue（frontend/src/views/QuotesView.vue）：
        # 分组、涨跌计算、折叠、文案都在前端，这里只推原始数据。
        self.quote_tab = VueTab(route="quotes")
        self.quote_tab.row_clicked.connect(self._on_quote_row_clicked)
        self.quote_tab.alert_toggled.connect(self._on_alert_toggled)
        self.tabs.addTab(self.quote_tab, "行情看板")

        self.options_tab = self._build_options_tab()
        self.tabs.addTab(self.options_tab, "期权T型")

        self.analysis_tab = self._build_analysis_tab()
        self.tabs.addTab(self.analysis_tab, "期权分析")

        layout.addWidget(self.tabs)

        # K 线图不占页签：它总是从看板/期权表点进来的，常驻一个空页签没意义。
        # 放进独立窗口，点标的时弹出，可以和主窗口并排看。
        self._build_chart_window()

        self.footer = QLabel("数据源: - | -")
        layout.addWidget(self.footer)

    def _build_options_tab(self) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)

        left = QVBoxLayout()
        left.addWidget(QLabel("ETF 期权标的"))
        self.option_underlying_list = QListWidget()
        self.option_underlying_list.currentItemChanged.connect(self._on_option_underlying_changed)
        left.addWidget(self.option_underlying_list)
        self.option_stats_label = QLabel("合约数: -")
        left.addWidget(self.option_stats_label)

        left_widget = QWidget()
        left_widget.setLayout(left)
        left_widget.setMaximumWidth(220)

        # 期权 T 型已迁到 Vue（frontend/src/views/TshapeView.vue）。
        # AI 推荐入口没有搬过去（用不上），所以不连 ai_strategy_requested；
        # Python 侧的 AI 代码还留着，老 tshape.html 回退时仍可用。
        self.option_table = VueTab(route="tshape")
        self.option_table.row_clicked.connect(self._on_option_row_clicked)
        self.option_table.strategy_requested.connect(self._on_strategy_requested)

        splitter = QSplitter()
        splitter.addWidget(left_widget)
        splitter.addWidget(self.option_table)
        splitter.setSizes([200, 900])
        layout.addWidget(splitter)

        return widget

    def _build_analysis_tab(self) -> QWidget:
        """期权分析页：左侧标的列表 + 右侧分析面板（波动率微笑/持仓量分布/卖方指标）."""
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)

        left = QVBoxLayout()
        left.addWidget(QLabel("ETF 期权标的"))
        self.analysis_underlying_list = QListWidget()
        self.analysis_underlying_list.currentItemChanged.connect(self._on_analysis_underlying_changed)
        left.addWidget(self.analysis_underlying_list)

        left_widget = QWidget()
        left_widget.setLayout(left)
        left_widget.setMaximumWidth(220)

        # 期权分析页已迁到 Vue（frontend/src/views/AnalysisView.vue）：
        # payload 仍是 build_tshape_data 的产物，契约没变。
        self.analysis_view = VueTab(route="analysis")

        splitter = QSplitter()
        splitter.addWidget(left_widget)
        splitter.addWidget(self.analysis_view)
        splitter.setSizes([200, 900])
        layout.addWidget(splitter)

        return widget

    def _connect_signals(self) -> None:
        self.watcher.signals.quotes_updated.connect(self._on_quotes_updated)
        self.watcher.signals.signals_fired.connect(self._on_signals_fired)
        self.watcher.signals.state_changed.connect(self._on_state_changed)
        self.watcher.signals.option_quotes_updated.connect(self._on_option_quotes_updated)

    # ---------- 行情看板 ----------

    def _load_cached_quotes(self) -> None:
        quotes = self.store.latest_quotes()
        if quotes:
            self._on_quotes_updated(quotes)

    def _build_quotes_payload(self, quotes: dict[str, Quote]) -> dict:
        """行情看板 payload（新契约）：只发事实，展示怎么组织交给前端.

        这里不算涨跌幅、不分组、不拼文案 —— 那些是视图决策，放前端才能
        改样式不动 Python。Python 只负责它独有的东西：配置、DB 里的提醒
        偏好和今日信号。

        约定：alertCodes 为空 = 全部提醒（沿用 state_meta 的语义）。
        """
        # 按配置顺序发，保证前端「其他」组和整体顺序稳定
        # （quotes 的 dict 顺序取决于 FetchChain 返回顺序，不可靠）
        order = self.cfg.all_quote_codes()
        known = set(order)
        ordered = [quotes[c] for c in order if c in quotes]
        ordered += [q for c, q in quotes.items() if c not in known]

        return {
            "quotes": [
                {
                    "code": q.code,
                    "name": q.name,
                    "price": q.price,
                    "open": q.open,
                    "prevClose": q.prev_close,
                    "volume": q.volume,
                    "ts": q.ts,
                    "source": q.source,
                }
                for q in ordered
            ],
            "indices": [{"code": i.code, "name": i.name} for i in self.cfg.indices],
            "indexMap": dict(self.cfg.index_map),
            "alertCodes": sorted(self.store.get_alert_codes()),
            "signals": self._latest_trade_signals(),
            "source": next((q.source for q in ordered if q.source), ""),
        }

    # 看板列定义（指数行的小数位由行内 _digits 覆盖）
    def _latest_trade_signals(self) -> dict[str, dict]:
        """今日每个标的、每个周期的最新一条买卖点.

        返回 {code: {"1m": {...}|缺, "5m": {...}|缺, "15m": {...}|缺}}，
        每档是 {side, time, label}。看板据此分列展示，用户能一眼对比
        某标的在 1/5/15 分上各自的最新买卖点（解决「K 线图上有、列表没有」）。

        DB 里 signal_key 形如 `resonance_long_5m_1435`：方向前缀 + 周期标签 + 时间。
        get_today_signals_with_ts 按 created_at DESC 返回，故每 (code,周期) 第一条即最新。
        兼容旧数据：没有 `_Nm_` 周期标签的老信号归到 5m 档（那时只检测 5 分）。
        """
        import re

        out: dict[str, dict] = {}
        try:
            rows = self.store.get_today_signals_with_ts(today_str())
        except Exception:  # noqa: BLE001
            return out
        for r in rows:
            code = r.get("code") or ""
            key = r.get("signal_key") or ""
            if not code:
                continue
            if key.startswith("resonance_long"):
                side = "buy"
            elif key.startswith("resonance_short"):
                side = "sell"
            else:
                continue
            m = re.search(r"_(\d+)m_", key)
            period = f"{m.group(1)}m" if m else "5m"  # 老数据没标签 → 归 5m
            slot = out.setdefault(code, {})
            if period in slot:
                continue  # 已有更新的（rows 已按时间倒序）
            t = signal_display_time(r.get("ts") or "", r.get("created_at") or "")
            slot[period] = {
                "side": side,
                "time": t[:5] if len(t) >= 5 else t,   # HH:MM:SS -> HH:MM
                "label": r.get("label") or "",
            }
        return out

    def _on_quotes_updated(self, quotes: dict[str, Quote]) -> None:
        self.quote_tab.render_quotes(self._build_quotes_payload(quotes))
        # T 型报价页：如果当前选中标的的 ETF 价格有更新，刷新 T 型页的现价
        current = self.option_underlying_list.currentItem()
        if current:
            u_code = current.data(Qt.UserRole)
            if u_code and u_code in quotes:
                self._load_option_quotes(u_code)

    def _on_quote_row_clicked(self, code: str, name: str) -> None:
        self._load_chart(code, name)

    def _on_alert_toggled(self, code: str) -> None:
        """行情看板提醒开关切换."""
        self.store.toggle_alert(code)

    # ---------- K 线图（独立窗口） ----------

    _CHART_PERIODS = ["分时", "1分", "5分", "15分", "30分", "60分", "日K"]

    def _build_chart_window(self) -> None:
        """K 线图窗口。不设 parent 才是真正的顶层窗口（能独立摆放/最小化）。"""
        self.chart_tab = VueTab(route="chart")
        self.chart_tab.refresh_requested.connect(self._refresh_chart)
        self.chart_tab.period_requested.connect(self._on_chart_period)
        self.chart_tab.view_option_requested.connect(self._on_view_option)
        self._chart_period = "1分"

        self.chart_window = _ChartWindow(self)
        self.chart_window.setWindowTitle("K 线图")
        self.chart_window.resize(1200, 820)
        lay = QVBoxLayout(self.chart_window)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.chart_tab)

    def _on_chart_window_closed(self) -> None:
        """K 线窗口被关掉后，把焦点交还主窗口.

        macOS 上关掉当前活动窗口后，主窗口虽然还看得见却不是活动窗口，
        这时点它里面的内容，第一下只会用来激活窗口、不会传给网页视图，
        表现就是「点了没反应」。这里主动激活一次，省掉那一次空点击。
        """
        if not self.isVisible():
            return  # 主窗口已收进托盘，不要把它拽出来
        self.raise_()
        self.activateWindow()

    def _show_chart_window(self, title: str = "") -> None:
        w = self.chart_window
        if title:
            w.setWindowTitle(f"K 线图 · {title}")
        # 最小化状态下 show() 不还原（窗口留在 Dock 里），必须走 showNormal
        if w.isMinimized():
            w.showNormal()
        else:
            w.show()
        self._ensure_on_screen(w)
        w.raise_()
        w.activateWindow()

    @staticmethod
    def _ensure_on_screen(w: QWidget) -> None:
        """窗口跑到当前不存在的屏幕上时搬回主屏中间.

        外接屏拔掉后，之前记住的位置会落在不可见区域，
        重新 show() 出来是看不到的，同样表现为「点了没反应」。
        """
        from PySide6.QtGui import QGuiApplication

        geo = w.frameGeometry()
        if any(s.availableGeometry().intersects(geo) for s in QGuiApplication.screens()):
            return
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        avail = screen.availableGeometry()
        w.move(avail.center() - QPoint(w.width() // 2, w.height() // 2))

    def _load_chart(self, code: str, name: str) -> None:
        self._chart_code = code
        self._chart_name = name
        self._show_chart_window(f"{name} ({code})")
        self._refresh_chart()

    def _on_chart_period(self, period: str) -> None:
        self._chart_period = period
        self._refresh_chart()

    def _on_view_option(self, underlying_code: str, side: str = "") -> None:
        """从 K 线窗口跳到主窗口的 T 型页并选中对应标的.

        side 为 'call'/'put' 时（点 K 线上的买卖点跳过来），让 T 型页只看那一侧。
        方向通过下一次 render_tshape 的 initialFilter 字段带给前端。
        """
        self._pending_tshape_filter = side if side in ("call", "put") else ""
        self.showNormal()
        self.raise_()
        self.activateWindow()
        self.tabs.setCurrentIndex(self.tabs.indexOf(self.options_tab))
        for i in range(self.option_underlying_list.count()):
            item = self.option_underlying_list.item(i)
            if item and item.data(Qt.UserRole) == underlying_code:
                # 已经选中这一行时 setCurrentRow 不会触发 currentItemChanged，
                # 那就自己推一发，否则 initialFilter 没机会送出去
                already = self.option_underlying_list.currentRow() == i
                self.option_underlying_list.setCurrentRow(i)
                if already:
                    self._load_option_quotes(underlying_code)
                return
        # 没找到对应标的（该 ETF 没有期权），别把方向留给下一次无关的渲染
        self._pending_tshape_filter = ""

    def _auto_refresh_chart(self) -> None:
        """定时自动刷新 K 线：窗口没开就不折腾，避免无效请求."""
        if not self.chart_window.isVisible():
            return
        code = getattr(self, "_chart_code", "")
        if not code:
            return
        if not (is_polling_hours() or self.cfg.dev.mock_mode):
            return
        # 期权上一发还没回来（网络慢），跳过本轮避免请求堆积
        if code.isdigit() and len(code) == 8 and self._chart_inflight > 0:
            return
        self._refresh_chart()

    def _refresh_chart(self) -> None:
        code = getattr(self, "_chart_code", "")
        name = getattr(self, "_chart_name", code)
        if not code:
            return
        period = getattr(self, "_chart_period", "1分")
        if code.isdigit() and len(code) == 8:
            # 期权：网络取数放工作线程（东财慢/封时单次最长 ~17s，跑 GUI 线程会卡死界面）
            periods = list(self._CHART_PERIODS if code.startswith("10") else self._CHART_PERIODS[:-1])
            if period not in periods:
                period = "1分"
                self._chart_period = period
            self._chart_seq += 1
            self._chart_inflight += 1
            self.chart_tab.update_chart({
                "title": f"{name} ({code})",
                "loading": True,
                "period": period,
                "periods": periods,
            })
            self._chart_pool.start(
                _ChartJob(self, self._chart_seq, code, name, period, self._chart_job_signals)
            )
        else:
            # ETF：本地 SQLite，直接同步算
            bars, mode, label_fmt, periods = self._etf_chart_data(code, period)
            payload = self._build_chart_payload(code, name, bars, mode, label_fmt, period, periods)
            payload["quote"] = self._chart_quote(code)
            self.chart_tab.update_chart(payload)

    def _on_option_chart_ready(self, seq: int, payload: dict | None, quote: dict | None) -> None:
        """期权图表后台取数完成（GUI 线程）：只渲染最新一次请求的结果."""
        self._chart_inflight = max(0, self._chart_inflight - 1)
        if seq != self._chart_seq:
            return  # 已被更新的点击取代
        if payload is None:
            # 取数异常：渲染空态，避免永远停在"加载中"
            code = getattr(self, "_chart_code", "")
            name = getattr(self, "_chart_name", code)
            period = getattr(self, "_chart_period", "1分")
            periods = list(self._CHART_PERIODS if code.startswith("10") else self._CHART_PERIODS[:-1])
            payload = self._build_chart_payload(code, name, [], "candle", "time", period, periods)
        payload["quote"] = quote
        self.chart_tab.update_chart(payload)

    def _chart_quote(self, code: str) -> dict | None:
        """K 线图右侧信息面板的报价数据（期权/ETF 两种来源）."""
        if code.isdigit() and len(code) == 8:
            row = self.store.get_option_quote(code)
            if not row or not row.get("price"):
                return None
            price = row["price"]
            pct = row.get("change_pct")
            prev_close = round(price / (1 + pct / 100), 4) if pct else None
            change = round(price - prev_close, 4) if prev_close else None
            extras = []
            if row.get("buy_price"):
                extras.append(["买一", f"{row['buy_price']:.4f} x{max(0, row.get('buy_vol') or 0)}"])
            if row.get("sell_price"):
                extras.append(["卖一", f"{row['sell_price']:.4f} x{max(0, row.get('sell_vol') or 0)}"])
            if row.get("open_interest") is not None:
                extras.append(["持仓量", str(max(0, row.get("open_interest") or 0))])
            if row.get("iv"):
                extras.append(["IV", f"{row['iv'] * 100:.1f}%"])
            # 新浪快照成交量字段偶发负值（字段偏移），展示夹到 0
            volume = row.get("volume")
            return {
                "price": price, "change": change, "changePct": pct,
                "open": None, "high": None, "low": None,
                # 期权涨跌幅官方口径是对昨结算价，面板也标注"昨结"
                "prevClose": prev_close, "prevCloseLabel": "昨结",
                "volume": max(0, volume) if volume is not None else None,
                "extras": extras,
            }
        q = self.store.latest_quotes().get(code)
        if not q or q.price <= 0:
            return None
        # 用 bars 最后一根的 close 作为更准确的现价（快照可能比 bars 旧）
        bars = self.store.get_bars(code, limit=1)
        price = q.price
        if bars and bars[0].close > 0 and bars[0].ts > (q.ts or ""):
            price = bars[0].close
        change = round(price - q.prev_close, 4) if q.prev_close else None
        pct = round((price - q.prev_close) / q.prev_close * 100, 2) if q.prev_close and q.prev_close > 0 else None
        return {
            "price": price, "change": change, "changePct": pct,
            "open": q.open, "high": q.high, "low": q.low,
            "prevClose": q.prev_close or None, "volume": q.volume, "extras": [],
        }

    def _atm_shortcuts(self, code: str) -> dict | None:
        """ETF K 线图用：返回 underlying code 供"查看期权"按钮跳转 T 型页.

        只有 ETF 标的（sh/sz 开头）且有期权合约时才显示按钮。
        """
        if code.isdigit() and len(code) == 8:
            return None  # 期权合约自身不需要
        contracts = self.store.get_option_contracts(code)
        if not contracts:
            return None
        return {"underlying": code}

    def _option_chart_data(self, code: str, period: str) -> tuple[list[MinuteBar], str, str, list[str]]:
        """期权图表数据：东财 1 分（真实 OHLC，聚合多周期）为主，新浪降级."""
        sse = code.startswith("10")
        periods = list(self._CHART_PERIODS if sse else self._CHART_PERIODS[:-1])  # 深市无日K源
        if period not in periods:
            period = "1分"
            self._chart_period = period

        if period == "分时":
            if sse:
                bars = fetch_option_minute_bars(code)  # 新浪当日分时（价+均价）
                if bars:
                    self.store.save_bars(bars, today_str())
                    return bars, "intraday", "time", periods
                cached = self.store.get_option_bars(code, limit=300, source="sina_option")
                if cached:
                    return cached, "intraday", "time", periods
            # 深市或新浪失败：东财当日 1 分收盘价画折线（无均价）
            bars, _ = self._em_option_bars(code)
            if bars:
                day = bars[-1].ts[:8]
                return [b for b in bars if b.ts[:8] == day], "intraday", "time", periods
            return [], "intraday", "time", periods

        if period == "日K":
            # Tushare 优先（历史最全、含持仓量），失败降级新浪，再退本地缓存
            bars = self._tushare_option_daily(code)
            if not bars:
                bars = fetch_option_daily_bars(code)  # 新浪日K（真实 OHLC）
            if bars:
                self.store.save_bars(bars, today_str())
            else:
                bars = self.store.get_option_bars(code, limit=240, source="%daily%")
            # 补充：用本地分钟K聚合出日K（覆盖新浪没有的天数）
            minute_bars = self.store.get_option_bars(code, limit=2000, source="eastmoney_option")
            if minute_bars:
                daily_from_minutes = self._aggregate_daily_from_minutes(code, minute_bars)
                # 合并：新浪日K + 本地聚合日K（去重取新浪优先）
                existing_dates = {b.ts[:8] for b in bars} if bars else set()
                for db in daily_from_minutes:
                    if db.ts[:8] not in existing_dates:
                        bars.append(db) if bars else None
                if not bars:
                    bars = daily_from_minutes
                else:
                    bars = sorted(bars + [b for b in daily_from_minutes if b.ts[:8] not in existing_dates],
                                  key=lambda b: b.ts)
            return bars or [], "candle", "date", periods

        # N 分（1/5/15/30/60）：东财 1 分聚合
        n = int(period[:-1])
        bars1, has_ohlc = self._em_option_bars(code)
        if bars1:
            # 1 分钟只看当天（期权T+0日内交易），多周期用跨天数据聚合
            if n == 1:
                today = today_str().replace("-", "")
                bars1 = [b for b in bars1 if b.ts[:8] == today]
            if has_ohlc:
                bars = aggregate_minute_bars(bars1, n)
                fmt = "datetime" if len({b.ts[:8] for b in bars}) > 1 else "time"
                return bars, "candle", fmt, periods
            else:
                # 新浪数据无真实OHLC，画折线
                bars = aggregate_minute_bars(bars1, n) if n > 1 else bars1
                return bars, "intraday", "time", periods
        # 东财失败：读本地 DB 缓存
        em_cached = self.store.get_option_bars(code, limit=1300, source="eastmoney_option")
        sina_cached = self.store.get_option_bars(code, limit=1300, source="sina_option")
        if len(em_cached) >= 30:
            cached = em_cached
            mode = "candle"
        elif sina_cached:
            cached = sina_cached
            mode = "intraday"
        else:
            cached = em_cached
            mode = "candle"
        if cached:
            bars = aggregate_minute_bars(cached, n)
            fmt = "datetime" if len({b.ts[:8] for b in bars}) > 1 else "time"
            return bars, mode, fmt, periods
        if sse:
            # 东财+DB 都没有：用新浪分时数据画折线（1分和分时本质相同）
            bars = fetch_option_minute_bars(code)
            if bars:
                self.store.save_bars(bars, today_str())
                return bars, "intraday", "time", periods
            cached = self.store.get_option_bars(code, limit=300, source="sina_option")
            if cached:
                return cached, "intraday", "time", periods
        return [], "candle", "time", periods

    def _tushare_option_daily(self, code: str) -> list[MinuteBar]:
        """Tushare 期权历史日 K（未启用 / 无 token / 失败时返回空，由调用方降级）."""
        ts_cfg = self.cfg.tushare
        if not (ts_cfg.enabled and ts_cfg.option_daily):
            return []
        try:
            from watcher.fetchers.tushare_src import get_client, is_available

            if not is_available():
                return []
            return get_client().fetch_option_daily(code, limit=250)
        except Exception:  # noqa: BLE001
            return []

    @staticmethod
    def _aggregate_daily_from_minutes(code: str, minute_bars: list[MinuteBar]) -> list[MinuteBar]:
        """把分钟K按天聚合为日K（补充新浪日K缺失的天数）."""
        from collections import defaultdict
        days: dict[str, list[MinuteBar]] = defaultdict(list)
        for b in minute_bars:
            days[b.ts[:8]].append(b)
        result: list[MinuteBar] = []
        for day in sorted(days.keys()):
            bs = days[day]
            if not bs:
                continue
            result.append(MinuteBar(
                code=code,
                ts=day + "150000",
                open=bs[0].open,
                high=max(b.high for b in bs),
                low=min(b.low for b in bs),
                close=bs[-1].close,
                volume=sum(b.volume for b in bs),
                source="aggregated_daily",
            ))
        return result

    def _em_option_bars(self, code: str) -> tuple[list[MinuteBar], bool]:
        """期权分钟K：优先东财（有真实OHLC画蜡烛），否则新浪（只能画折线）.

        返回 (bars, has_ohlc)：has_ohlc=True 可画蜡烛图，False 只能画折线。
        """
        bars = fetch_option_minute_bars_em(code)
        if bars:
            self.store.save_bars(bars, today_str())
        # 从 DB 读分钟数据
        em_cached = self.store.get_option_bars(code, limit=1300, source="eastmoney_option")
        sina_cached = self.store.get_option_bars(code, limit=1300, source="sina_option")
        # 优先东财（有真实OHLC），条数够用就用东财
        if len(em_cached) >= 30:
            return em_cached, True
        # 东财不够，用新浪（条数更多但无真实OHLC）
        if len(sina_cached) > len(em_cached):
            return sina_cached, False
        return em_cached or bars or [], bool(em_cached or bars)

    def _etf_chart_data(self, code: str, period: str) -> tuple[list[MinuteBar], str, str, list[str]]:
        """ETF 图表数据：本地分钟 K（TDX 轮询积累）+ TDX 日K."""
        periods = list(self._CHART_PERIODS)
        if period not in periods:
            period = "1分"
            self._chart_period = period

        if period == "分时":
            recent = self.store.get_bars(code, limit=300)
            if recent:
                day = recent[-1].ts[:8]
                return [b for b in recent if b.ts[:8] == day], "intraday", "time", periods
            return [], "intraday", "time", periods
        if period == "日K":
            bars = self.watcher.fetch_daily_bars(code, limit=160)
            if not bars and self.cfg.tushare.enabled and self.cfg.tushare.fund_daily_fallback:
                # TDX 日K 拿不到时用 Tushare 兜底
                try:
                    from watcher.fetchers.tushare_src import get_client, is_available

                    if is_available():
                        bars = get_client().fetch_fund_daily(code, limit=160)
                except Exception:  # noqa: BLE001
                    bars = []
            return bars, "candle", "date", periods
        if period == "1分":
            bars = self.store.get_bars(code, limit=480)
        else:
            bars1 = self.store.get_bars(code, limit=960)
            bars = aggregate_minute_bars(bars1, int(period[:-1]))
        fmt = "datetime" if len({b.ts[:8] for b in bars}) > 1 else "time"
        return bars, "candle", fmt, periods

    def _build_chart_payload(
        self,
        code: str,
        name: str,
        bars: list[MinuteBar],
        mode: str,
        label_fmt: str = "time",
        period: str = "1分",
        periods: list[str] | None = None,
    ) -> dict:
        out_bars = []
        for b in bars:
            label = self._bar_label(b.ts, label_fmt)
            if label is None:
                continue
            item = {
                # label 是给老 chart.html 用的（保留以便回退）；
                # Vue 版只用 ts，自己按 labelFmt 格式化，不依赖 Python 拼好的字符串
                "label": label,
                "ts": b.ts,
                "open": b.open, "high": b.high, "low": b.low, "close": b.close,
                # 均价线只有新浪分时数据才有（存在 open 字段）；东财数据无均价
                "avg": b.open if (mode == "intraday" and b.source == "sina_option") else None,
                "volume": b.volume,
            }
            out_bars.append(item)

        # 买卖标记：实时计算（不存 DB，每次打开 K 线跑一遍检测直接画）
        sigs = []
        if label_fmt != "date" and len(bars) >= 30:
            computed = self._compute_chart_signals(code, name, bars, label_fmt, period)
            sigs = computed

        if mode == "intraday":
            suffix = " 分时走势" if period == "分时" else f" 分时走势"
        elif label_fmt == "date":
            suffix = " 日 K 线"
        else:
            suffix = f" {period} K 线"
        return {
            "title": f"{name} ({code}){suffix}",
            "mode": mode,
            "period": period,
            "periods": periods or [],
            # 前端按此决定 x 轴标签格式：date=YYYY-MM-DD / datetime=MM-DD HH:MM / time=HH:MM
            "labelFmt": label_fmt,
            "bars": out_bars,
            "signals": sigs,
            "quote": self._chart_quote(code),
            "digits": 4 if (code.isdigit() and len(code) == 8) else 3,
            "atm": self._atm_shortcuts(code),
        }

    @staticmethod
    def _bar_label(ts: str, fmt: str = "time") -> str | None:
        if fmt == "date":
            return f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}" if len(ts) >= 8 else None
        parsed = parse_quote_time(ts)
        if not parsed:
            return None
        if fmt == "datetime":
            return f"{ts[4:6]}-{ts[6:8]} {parsed[:5]}"
        return parsed[:5]

    # ---------- 今日信号 ----------

    def _on_signals_fired(self, signals: list[Signal]) -> None:
        import time as _time

        from watcher.calendar import is_polling_hours

        for sig in signals:
            if not self.store.should_alert(sig.code):
                continue
            if not is_polling_hours():
                continue
            sig_age = self._signal_age_seconds(sig)
            if sig_age is not None and sig_age > 300:
                continue
            self.notifier.notify(sig)

    @staticmethod
    def _signal_age_seconds(sig: Signal) -> float | None:
        """信号产生距离现在的秒数。无法解析时返回 None（放行弹窗）."""
        import time as _time
        from datetime import datetime

        ts = sig.ts
        if not ts or len(ts) < 12:
            return None
        try:
            dt = datetime(int(ts[:4]), int(ts[4:6]), int(ts[6:8]),
                          int(ts[8:10]), int(ts[10:12]), int(ts[12:14]) if len(ts) >= 14 else 0)
            return _time.time() - dt.timestamp()
        except (ValueError, OSError):
            return None

    def _compute_chart_signals(self, code: str, name: str, bars: list[MinuteBar], label_fmt: str, period: str = "5分") -> list[dict]:
        """实时计算 K 线上的买/卖标记（不存 DB，每次打开都重新跑）.

        信号检测周期与图表当前显示周期一致：
        - ETF：直接用传入的 bars（已按 period 聚合）滑窗检测。
        - 期权：找对应 ETF 标的的 1 分 bars，按 period 聚合后检测。
        """
        from watcher.bars import aggregate_minute_bars
        from watcher.signals import rules
        from watcher.signals.engine import SignalEngine

        # 解析周期分钟数（分时按 1 分处理）
        if period == "分时":
            period_min = 1
        elif period.endswith("分"):
            period_min = int(period[:-1])
        else:
            return []  # 日K不做检测

        # 确定要检测的标的和 bars
        detect_code = code
        detect_name = name
        detect_bars = bars
        if code.isdigit() and len(code) == 8:
            # 期权合约：用对应 ETF 标的的 bars，按当前 period 聚合
            contracts = self.store.get_option_contracts_by_code(code)
            if contracts:
                u_code = contracts[0].underlying_code
                detect_code = u_code
                detect_name = self.cfg.name_for(u_code)
                raw_bars = self.store.get_bars(u_code, limit=960)
                if period_min == 1:
                    detect_bars = raw_bars
                else:
                    detect_bars = aggregate_minute_bars(raw_bars, period_min)
            if len(detect_bars) < 30:
                return []
        else:
            # ETF：bars 已经是按当前 period 聚合好的，直接用
            detect_bars = bars

        # 筛当日（或数据不足时用全部）
        today = today_str().replace("-", "")
        today_bars = [b for b in detect_bars if b.ts[:8] == today]
        if len(today_bars) < 30:
            today_bars = detect_bars

        if len(today_bars) < 6:
            return []

        # 昨日高低
        prev_bars = [b for b in detect_bars if b.ts[:8] != today]
        prev_high = max((b.high for b in prev_bars), default=None) if prev_bars else None
        prev_low = min((b.low for b in prev_bars), default=None) if prev_bars else None

        # 滑窗检测（每步加一根 bar，检测配对的买/卖）
        engine = SignalEngine(self.cfg)
        sigs: list[dict] = []
        prefix = f"{today_str()[5:]} " if label_fmt == "datetime" else ""

        # MACD 需要 26 根预热，MA 需要 10 根，从 26 根起步检测
        start = min(26, len(today_bars) - 1)
        if start < 6:
            return []
        for i in range(start, len(today_bars) + 1):
            window = today_bars[:i]
            sig = rules.detect_resonance(
                window, detect_code, detect_name, self.cfg,
                prev_high, prev_low, toggles=self.cfg.signal_toggles,
            )
            if sig is None:
                continue
            last_side = engine._tech_state.get(detect_code)
            if sig.key == "resonance_long" and last_side != "buy":
                engine._tech_state[detect_code] = "buy"
            elif sig.key == "resonance_short" and last_side == "buy":
                engine._tech_state[detect_code] = "sell"
            else:
                continue
            # 时间标签（用窗口末尾 bar 的实际时间）
            bar_ts = today_bars[i - 1].ts
            label = parse_quote_time(bar_ts)
            if label:
                label = label[:5]
            else:
                continue
            sigs.append({
                "key": sig.key,
                # label 供老 chart.html 做字符串匹配定位（保留以便回退）
                "label": prefix + label,
                # ts 是原始时间戳，Vue 版按它匹配 bar —— 比匹配格式化后的
                # 字符串稳：信号是在 today_bars 上检测的（期权时甚至是另一个
                # 标的的 bars），与 payload.bars 索引不对应，只能按时间对齐。
                "ts": bar_ts,
                "labelText": f"【{sig.label}】{sig.detail}",
            })
        return sigs

    def _show_alert(self, signal: Signal) -> None:
        from watcher.gui.alert_popup import AlertPopup

        popup = AlertPopup(signal, self)
        # 点弹窗也跳到对应标的（跟系统通知一致）
        popup.jump_requested.connect(self._on_notification_clicked)
        popup.show()

    def _on_notification_clicked(self, code: str, name: str) -> None:
        """点击通知 / 预警弹窗 → 唤起窗口并跳到该标的的 K 线图."""
        if not code:
            return
        self.showNormal()
        self.raise_()
        self.activateWindow()

        if code.isdigit() and len(code) == 8:
            # 期权合约：直接开它自己的 K 线
            self._load_chart(code, name or code)
        else:
            self._load_chart(code, name or self.cfg.name_for(code))

    # ---------- 期权 T 型 ----------

    def _populate_option_underlyings(self) -> None:
        self.option_underlying_list.clear()
        self.analysis_underlying_list.clear()
        # 只展示有期权合约的标的（交易所实际 9 个；588050/159952 无合约不进期权页）
        codes = self.store.option_underlyings() or self.cfg.watch_codes()
        from watcher.option_meta import ETF_OPTION_UNDERLYINGS

        for code in codes:
            name = self.cfg.name_for(code)
            # name_for 找不到时会返回 code 本身，用 ETF_OPTION_UNDERLYINGS 兜底
            if name == code:
                pure = code[2:] if code[:2] in ("sh", "sz") else code
                name = ETF_OPTION_UNDERLYINGS.get(pure, code)
            item = QListWidgetItem(name)
            item.setData(Qt.UserRole, code)
            self.option_underlying_list.addItem(item)
            # 同步填充分析页列表
            item2 = QListWidgetItem(name)
            item2.setData(Qt.UserRole, code)
            self.analysis_underlying_list.addItem(item2)
        if self.option_underlying_list.count() > 0:
            self.option_underlying_list.setCurrentRow(0)
        if self.analysis_underlying_list.count() > 0:
            self.analysis_underlying_list.setCurrentRow(0)

    def _on_option_underlying_changed(self, current: QListWidgetItem | None, previous=None) -> None:
        if not current:
            return
        code = current.data(Qt.UserRole)
        self._load_option_quotes(code)
        # 后台拉取该标的全部月份的最新行情
        self._trigger_option_full_refresh(code)

    def _on_analysis_underlying_changed(self, current: QListWidgetItem | None, previous=None) -> None:
        if not current:
            return
        code = current.data(Qt.UserRole)
        self._load_analysis_data(code)

    def _load_analysis_data(self, underlying_code: str) -> None:
        """加载期权分析页数据（波动率微笑 + 持仓量分布 + 卖方指标）."""
        contracts = self.store.get_option_contracts(underlying_code)
        quotes = {q["option_code"]: q for q in self.store.get_option_quotes(underlying_code)}
        underlying_quote = self.store.latest_quotes().get(underlying_code)
        name = self.cfg.name_for(underlying_code)
        if name == underlying_code:
            from watcher.option_meta import ETF_OPTION_UNDERLYINGS
            pure = underlying_code[2:] if underlying_code[:2] in ("sh", "sz") else underlying_code
            name = ETF_OPTION_UNDERLYINGS.get(pure, underlying_code)
        payload = build_tshape_data(
            contracts, quotes, underlying_code, name, underlying_quote,
        )
        self.analysis_view.render_analysis(payload)

    def _trigger_option_full_refresh(self, underlying_code: str) -> None:
        """在工作线程中拉取指定标的全部月份期权行情."""
        if not hasattr(self, "_chart_pool"):
            return  # 初始化阶段，pool 还没创建

        class _OptionFullJob(QRunnable):
            def __init__(self, watcher, code):
                super().__init__()
                self._watcher = watcher
                self._code = code

            def run(self):
                try:
                    self._watcher.refresh_option_full(self._code)
                except Exception:  # noqa: BLE001
                    pass

        job = _OptionFullJob(self.watcher, underlying_code)
        self._chart_pool.start(job)

    def _load_option_quotes(self, underlying_code: str) -> None:
        self._strategy_underlying = underlying_code
        contracts = self.store.get_option_contracts(underlying_code)
        quotes = {q["option_code"]: q for q in self.store.get_option_quotes(underlying_code)}
        underlying_quote = self.store.latest_quotes().get(underlying_code)
        if contracts:
            self.option_stats_label.setText(f"合约数: {len(contracts)}")
        else:
            self.option_stats_label.setText("该标的暂无期权合约")
        payload = build_tshape_data(
            contracts,
            quotes,
            underlying_code,
            self.cfg.name_for(underlying_code),
            underlying_quote,
        )
        # 从 K 线买卖点跳过来时带上方向，一次性消费（定时刷新不该反复改用户的过滤）
        if getattr(self, "_pending_tshape_filter", ""):
            payload["initialFilter"] = self._pending_tshape_filter
            self._pending_tshape_filter = ""
        self.option_table.render_tshape(payload)

    def _on_option_row_clicked(self, code: str, name: str) -> None:
        # _load_chart 会把 K 线窗口带到前台
        self._load_chart(code, name)

    # ---------- 期权策略工具 ----------

    def _strategy_chain(self, underlying_code: str) -> tuple[list[dict], float]:
        """组装策略计算用的合约链 + 标的现价."""
        contracts = self.store.get_option_contracts(underlying_code)
        quotes = {q["option_code"]: q for q in self.store.get_option_quotes(underlying_code)}
        chain: list[dict] = []
        for c in contracts:
            q = quotes.get(c.option_code) or {}
            chain.append({
                "code": c.option_code,
                "name": c.option_name,
                "option_type": c.option_type,
                "strike": c.strike,
                # 到期日统一用合约表的 8 位格式（两表格式不同，关联只用 option_code）
                "expire_date": c.expire_date,
                "price": q.get("price") or 0.0,
                "buy_price": q.get("buy_price") or 0.0,
                "sell_price": q.get("sell_price") or 0.0,
                "iv": q.get("iv") or 0.0,
                "oi": q.get("open_interest") or 0,
                "volume": q.get("volume") or 0,
            })
        uq = self.store.latest_quotes().get(underlying_code)
        spot = uq.price if uq and uq.price > 0 else 0.0
        return chain, spot

    @staticmethod
    def _fix_leg_ivs(legs: list, spot: float) -> None:
        """修正腿上的 IV：缺失或明显失真时用市场价反解，最后用同组均值兜底.

        新浪 CON_SO 的 IV 偶尔给出 4% 这种不合理值（ETF 期权正常在 10%-40%），
        IV 失真会直接把 theta / 时间损耗算歪，所以宁可自己反解。
        """
        from watcher.strategy.pricing import days_to_expiry, implied_vol

        PLAUSIBLE = (0.05, 2.0)
        for l in legs:
            if PLAUSIBLE[0] <= l.iv <= PLAUSIBLE[1]:
                continue
            t = days_to_expiry(l.expire_date) / 365.0
            solved = implied_vol(l.price, spot, l.strike, t, l.option_type)
            if solved and PLAUSIBLE[0] <= solved <= PLAUSIBLE[1]:
                l.iv = solved
        good = [l.iv for l in legs if PLAUSIBLE[0] <= l.iv <= PLAUSIBLE[1]]
        fallback = (sum(good) / len(good)) if good else 0.20
        for l in legs:
            if not (PLAUSIBLE[0] <= l.iv <= PLAUSIBLE[1]):
                l.iv = fallback

    def _on_strategy_requested(self, payload_json: str) -> None:
        """JS 提交组合（腿列表或预设名）→ 计算损益/希腊字母/时间损耗 → 回推 UI."""
        import json as _json

        from watcher.strategy import (
            Leg,
            PRESETS,
            build_preset,
            combo_greeks,
            decay_schedule,
            payoff_curve,
            summarize,
        )
        from watcher.strategy.pricing import days_to_expiry

        try:
            req = _json.loads(payload_json or "{}")
        except ValueError:
            return

        preset_list = [{"key": k, "label": v[0], "desc": v[1]} for k, v in PRESETS.items()]

        underlying = req.get("underlying") or getattr(self, "_strategy_underlying", "") or ""
        if not underlying:
            self.option_table.render_strategy({"error": "请先在左侧选择标的", "presets": preset_list})
            return

        chain, spot = self._strategy_chain(underlying)
        by_code = {c["code"]: c for c in chain}
        if spot <= 0:
            self.option_table.render_strategy(
                {"error": "暂无标的行情，无法计算", "presets": preset_list}
            )
            return

        preset = req.get("preset")
        if preset:
            # 预设内部会锁定同一到期月（跨月叠加的到期损益没有意义）
            legs = build_preset(
                preset, chain, spot,
                qty=int(req.get("qty") or 1),
                expiry=req.get("expiry"),
            )
            if not legs:
                self.option_table.render_strategy({
                    "error": f"{PRESETS.get(preset, (preset,))[0]}：该到期月合约或报价不足，挑不出腿",
                    "presets": preset_list,
                })
                return
        else:
            legs = []
            for item in req.get("legs") or []:
                src = by_code.get(item.get("code"))
                if not src:
                    continue
                px = float(item.get("price") or 0) or float(src["price"]) or (
                    (float(src["buy_price"]) + float(src["sell_price"])) / 2
                    if src["buy_price"] and src["sell_price"] else 0.0
                )
                if px <= 0:
                    continue
                legs.append(Leg(
                    option_code=src["code"],
                    option_type=src["option_type"],
                    strike=float(src["strike"]),
                    side="sell" if item.get("side") == "sell" else "buy",
                    price=px,
                    qty=max(1, int(item.get("qty") or 1)),
                    expire_date=src["expire_date"],
                    iv=float(src["iv"]) or 0.0,
                    name=src["name"],
                ))

        if not legs:
            self.option_table.render_strategy(
                {"empty": True, "spot": spot, "presets": preset_list}
            )
            return

        self._fix_leg_ivs(legs, spot)

        summary = summarize(legs, spot)
        greeks_total = combo_greeks(legs, spot)
        decay = decay_schedule(legs, spot, horizons=(1, 3, 7))
        curve = payoff_curve(legs, spot, points=161)

        self.option_table.render_strategy({
            "underlying": underlying,
            "underlyingName": self.cfg.name_for(underlying),
            "spot": spot,
            "legs": [{
                "code": l.option_code,
                "name": l.name,
                "type": l.option_type,
                "strike": l.strike,
                "side": l.side,
                "price": l.price,
                "qty": l.qty,
                "iv": l.iv,
                "expire": l.expire_date,
                "days": days_to_expiry(l.expire_date),
                "cost": l.cost,
            } for l in legs],
            "summary": summary.as_dict(),
            "greeks": greeks_total,
            "decay": decay,
            "curve": [{"s": round(s, 4), "p": round(p, 2)} for s, p in curve],
            "presets": [{"key": k, "label": v[0], "desc": v[1]} for k, v in PRESETS.items()],
        })

    def _on_ai_strategy_requested(self, payload_json: str) -> None:
        """AI 策略推荐：后台线程调 DeepSeek API，完成后回推结果到 UI."""
        import json as _json

        try:
            req = _json.loads(payload_json or "{}")
        except ValueError:
            self.option_table.render_ai_result({"error": "请求参数错误"})
            return

        underlying = req.get("underlying") or getattr(self, "_strategy_underlying", "") or ""
        if not underlying:
            self.option_table.render_ai_result({"error": "请先在左侧选择标的"})
            return

        # 在工作线程中执行 AI 调用（网络请求不能阻塞 GUI）
        class _AiJob(QRunnable):
            def __init__(self, mw, underlying_code, params_dict, signals):
                super().__init__()
                self._mw = mw
                self._underlying = underlying_code
                self._params = params_dict
                self._signals = signals

            def run(self):
                try:
                    result = self._mw._run_ai_strategy(self._underlying, self._params)
                except Exception as e:  # noqa: BLE001
                    import traceback
                    traceback.print_exc()
                    result = {"error": f"AI 调用异常: {e}"}
                # 通过信号回到主线程
                self._signals.ai_finished.emit(result)

        job = _AiJob(self, underlying, req, self._chart_job_signals)
        self._chart_pool.start(job)

    def _run_ai_strategy(self, underlying_code: str, params_dict: dict) -> dict:
        """在工作线程执行：收集数据 + 调 AI + 解析结果."""
        from watcher.ai.strategy_prompt import UserParams, recommend_strategy

        # 组装用户参数
        params = UserParams(
            capital=float(params_dict.get("capital", 10000)),
            max_loss=float(params_dict.get("max_loss", 3000)),
            holding_days=int(params_dict.get("holding_days", 3)),
            style=str(params_dict.get("style", "中性")),
            etf_shares=int(params_dict.get("etf_shares", 0)),
            direction=str(params_dict.get("direction", "AI判断")),
            target_price=str(params_dict.get("target_price", "")),
            expiry_pref=str(params_dict.get("expiry_pref", "AI决定")),
            allow_naked_sell=bool(params_dict.get("allow_naked_sell", False)),
        )

        # 获取合约链和标的价格
        chain, spot = self._strategy_chain(underlying_code)
        if spot <= 0:
            return {"error": "暂无标的行情，无法分析"}
        if not chain:
            return {"error": "暂无期权合约数据"}

        # 获取 1 分钟 bars 用于技术面分析
        bars_1min = self.store.get_bars(underlying_code, limit=960)

        # 获取 Tushare 历史日 K（近 20 日）用于趋势分析
        daily_bars = None
        if self.cfg.tushare.enabled:
            try:
                from watcher.fetchers.tushare_src import get_client, is_available
                if is_available():
                    daily_bars = get_client().fetch_fund_daily(underlying_code, limit=30)
            except Exception:  # noqa: BLE001
                pass

        # 调用 AI
        result = recommend_strategy(
            self.cfg,
            underlying_code,
            self.cfg.name_for(underlying_code),
            chain,
            spot,
            bars_1min,
            params,
            daily_bars=daily_bars,
        )

        # 补全 legs 的展示字段。
        # AI 只回 code/side/qty/price，但界面要显示认购/认沽和行权价 ——
        # 以前没补 option_type/strike，导致 AI 结果里恒显示「K=0.000」且
        # 认购/认沽为空。这些信息 chain 里都有，按 code 查出来填上。
        if "legs" in result and not result.get("error"):
            by_code = {c["code"]: c for c in chain}
            for leg in result["legs"]:
                src = by_code.get(leg.get("code", ""))
                if src:
                    leg["name"] = src.get("name", leg.get("code", ""))
                    leg["option_type"] = src.get("option_type")
                    leg["strike"] = src.get("strike")
                    if not leg.get("price"):
                        leg["price"] = src.get("price") or 0

        return result

    def _deliver_ai_result(self, result) -> None:
        """主线程回调：将 AI 结果推到 UI."""
        self.option_table.render_ai_result(result)

    def _on_option_quotes_updated(self, underlying_code: str) -> None:
        # 首次启动合约表后于窗口加载：列表为空时补一次填充
        if self.option_underlying_list.count() == 0:
            self._populate_option_underlyings()
        current = self.option_underlying_list.currentItem()
        if current and current.data(Qt.UserRole) == underlying_code:
            self._load_option_quotes(underlying_code)
        # 同步刷新分析页
        analysis_current = self.analysis_underlying_list.currentItem()
        if analysis_current and analysis_current.data(Qt.UserRole) == underlying_code:
            self._load_analysis_data(underlying_code)

    # ---------- 状态 / 其他 ----------

    def _on_state_changed(self, state: AppState) -> None:
        if state.connected:
            self.status_label.setText("状态: 已连接")
            self.footer.setText(f"数据源: {state.data_source} | 运行中")
        else:
            self.status_label.setText(f"状态: 未连接 ({state.error_message})")
            self.footer.setText(f"数据源: {state.data_source or '-'} | {state.error_message}")

    def _manual_refresh(self) -> None:
        self.status_label.setText("状态: 请求刷新中...")
        self.watcher.refresh_now()

    def _test_alert(self) -> None:
        sig = Signal(
            key="test",
            code="sh510300",
            name="沪深300ETF",
            label="测试预警",
            detail="这是一条测试预警，用于验证系统通知是否正常工作。",
            level="warning",
            ts="",
        )
        self.notifier.notify(sig)

    def _show_signal_config(self) -> None:
        """弹出买卖点信号配置对话框（量价形态开关 + 形态清单说明）."""
        from watcher.config import SignalToggleConfig

        toggles = self._load_signal_toggles()
        dlg = QDialog(self)
        dlg.setWindowTitle("买卖点信号配置")
        dlg.setMinimumWidth(430)
        layout = QVBoxLayout(dlg)

        cb = QCheckBox("启用量价形态买卖点提醒")
        cb.setChecked(getattr(toggles, "volume_pattern", True))
        cb.setStyleSheet("QCheckBox { font-weight: bold; padding: 2px 0; }")
        layout.addWidget(cb)

        desc = QLabel(
            "用最近 10+ 根 K 线的量价序列推断当前是不是买卖点，"
            "比 MACD 金叉早 3-5 根。得分 ≥3 报买、≤-3 报卖，见顶形态一票否决买入。"
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(desc)

        buy_box = QGroupBox("看多形态")
        buy_layout = QVBoxLayout(buy_box)
        for text in [
            "量爆跟随 +3　巨量换手后突破该根高点（量先于价，最具领先性）",
            "量堆积启动 +3　窄幅蓄势后放量大涨创新高",
            "挤压突破 +3　振幅极度收缩后放量突破",
            "缩量回调反包 +2　缩量回调后放量阳线吞没",
            "洗盘拉回 +2　放量下跌→缩量止跌→放量收复",
            "跳空不回补 +2　向上跳空且低点未跌回缺口",
        ]:
            lb = QLabel(text)
            lb.setStyleSheet("color: #ef5350; font-size: 11px;")
            buy_layout.addWidget(lb)
        layout.addWidget(buy_box)

        sell_box = QGroupBox("看空 / 抑制形态")
        sell_layout = QVBoxLayout(sell_box)
        for text in [
            "放量滞涨见顶 -3　高位连续放量但价格不涨（抛压重）",
            "巨量见顶 -3　连涨后巨量长上影",
            "高位长上影 -3　涨上来后放量长上影",
            "冲高回落 -3　创新高后放量阴线吃掉一半实体",
            "高位破位 -3　收阴跌破前 5 根最低（不要求放量，抓无量滞涨顶）",
            "放量破位 -3　低位放量大跌创新低",
            "量价背离 -2　创新高但量明显萎缩",
            "跳空回补 -2　跳空被放量打回缺口内",
        ]:
            lb = QLabel(text)
            lb.setStyleSheet("color: #26a69a; font-size: 11px;")
            sell_layout.addWidget(lb)
        layout.addWidget(sell_box)

        mom_box = QGroupBox("市场日内动量（14:30 方向参考）")
        mom_layout = QVBoxLayout(mom_box)
        cb_mom = QCheckBox("启用尾盘方向提醒")
        cb_mom.setChecked(getattr(toggles, "intraday_momentum", True))
        cb_mom.setStyleSheet("QCheckBox { font-weight: bold; }")
        mom_layout.addWidget(cb_mom)
        mom_desc = QLabel(
            "依据 Gao/Han/Li/Zhou (2018) 市场日内动量。本地 11 个 ETF × 243 个"
            "交易日实测：早盘半小时与 14:00-14:30 同为上涨时，做多末半小时\n"
            "687 次、胜率 55.0%、单笔均 +0.087%（已扣双边成本）、t=+5.00。\n"
            "只发看多信号——加入做空后收益被抹平（t=0.02），早盘走弱只作提示。"
        )
        mom_desc.setWordWrap(True)
        mom_desc.setStyleSheet("color: #888; font-size: 10px;")
        mom_layout.addWidget(mom_desc)
        layout.addWidget(mom_box)

        tip = QLabel("阈值调整见 watcher/signals/patterns.py 顶部常量；"
                     "回测用 scripts/backtest_patterns.py、"
                     "scripts/test_intraday_momentum.py")
        tip.setWordWrap(True)
        tip.setStyleSheet("color: #666; font-size: 10px;")
        layout.addWidget(tip)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        layout.addWidget(btns)

        if dlg.exec() == QDialog.Accepted:
            new_toggles = SignalToggleConfig(
                volume_pattern=cb.isChecked(),
                intraday_momentum=cb_mom.isChecked(),
            )
            self._save_signal_toggles(new_toggles.model_dump())
            self.cfg.signal_toggles = new_toggles

    def _show_api_key_config(self) -> None:
        """弹出 API Key 设置对话框，保存 Tushare Token 和 DeepSeek Key 到 DB."""
        dlg = QDialog(self)
        dlg.setWindowTitle("API 密钥设置")
        dlg.setMinimumWidth(420)
        layout = QVBoxLayout(dlg)
        layout.addWidget(QLabel("配置数据源和 AI 服务的 API 密钥（保存到本地数据库，不上传）："))

        form = QFormLayout()

        # 当前值
        current_ts = self._load_api_key("tushare_token") or ""
        current_ds = self._load_api_key("deepseek_api_key") or ""

        ts_input = QLineEdit(current_ts)
        ts_input.setPlaceholderText("Tushare Pro Token（用于历史日K和交易日历）")
        ts_input.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Tushare Token:", ts_input)

        ds_input = QLineEdit(current_ds)
        ds_input.setPlaceholderText("DeepSeek API Key（用于 AI 策略推荐）")
        ds_input.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("DeepSeek Key:", ds_input)

        layout.addLayout(form)

        # 显示/隐藏按钮
        show_btn = QPushButton("显示密钥")
        show_btn.setCheckable(True)

        def toggle_echo(checked):
            mode = QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
            ts_input.setEchoMode(mode)
            ds_input.setEchoMode(mode)
            show_btn.setText("隐藏密钥" if checked else "显示密钥")

        show_btn.toggled.connect(toggle_echo)
        layout.addWidget(show_btn)

        hint = QLabel("保存后立即生效。Tushare 用于拉取历史走势数据，DeepSeek 用于 AI 策略分析。")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(hint)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        layout.addWidget(btns)

        if dlg.exec() == QDialog.Accepted:
            new_ts = ts_input.text().strip()
            new_ds = ds_input.text().strip()
            self._save_api_key("tushare_token", new_ts)
            self._save_api_key("deepseek_api_key", new_ds)
            # 立即生效：设置环境变量
            if new_ts:
                os.environ["TUSHARE_TOKEN"] = new_ts
            if new_ds:
                os.environ["DEEPSEEK_API_KEY"] = new_ds

    def _load_api_key(self, key_name: str) -> str:
        """从 DB 读 API key."""
        import sqlite3
        try:
            with sqlite3.connect(self.store.db_path) as conn:
                row = conn.execute(
                    "SELECT value FROM state_meta WHERE key = ?", (key_name,)
                ).fetchone()
            return row[0] if row and row[0] else ""
        except Exception:  # noqa: BLE001
            return ""

    def _save_api_key(self, key_name: str, value: str) -> None:
        """保存 API key 到 DB."""
        import sqlite3
        with sqlite3.connect(self.store.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO state_meta (key, value) VALUES (?, ?)",
                (key_name, value),
            )
            conn.commit()

    def _restore_api_keys(self) -> None:
        """启动时从 DB 加载 API keys 到环境变量（如果 env 中还没有的话）."""
        ts = self._load_api_key("tushare_token")
        if ts and not os.environ.get("TUSHARE_TOKEN"):
            os.environ["TUSHARE_TOKEN"] = ts
        ds = self._load_api_key("deepseek_api_key")
        if ds and not os.environ.get("DEEPSEEK_API_KEY"):
            os.environ["DEEPSEEK_API_KEY"] = ds

    def _load_signal_toggles(self):
        """从 DB 读信号开关，缺失时用 config 默认值."""
        from watcher.config import SignalToggleConfig
        import json as _json
        import sqlite3
        try:
            with sqlite3.connect(self.store.db_path) as conn:
                row = conn.execute(
                    "SELECT value FROM state_meta WHERE key = 'signal_toggles'"
                ).fetchone()
            if row and row[0]:
                data = _json.loads(row[0])
                return SignalToggleConfig(**data)
        except Exception:  # noqa: BLE001
            pass
        return self.cfg.signal_toggles

    def _save_signal_toggles(self, vals: dict) -> None:
        import json as _json
        import sqlite3
        with sqlite3.connect(self.store.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO state_meta (key, value) VALUES ('signal_toggles', ?)",
                (_json.dumps(vals),),
            )
            conn.commit()

    def closeEvent(self, event) -> None:
        # K 线窗口是顶层窗口（没有 parent），不会跟着主窗口隐藏，手动收起来
        if getattr(self, "chart_window", None):
            self.chart_window.hide()
        event.ignore()
        self.hide()
        if self.tray:
            self.tray.showMessage(
                self.cfg.app.name,
                "程序已最小化到系统托盘，右键图标可退出。",
                self.tray.icon(),
                3000,
            )
