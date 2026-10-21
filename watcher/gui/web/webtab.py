"""QWebEngineView 封装：图表页与表格页."""
from __future__ import annotations

import json

from PySide6.QtCore import QObject, QUrl, Signal as QtSignal, Slot
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEngineSettings

# 注册 qrc 资源（echarts.min.js / chart.html / table.html）
import watcher.gui.web.web_resources  # noqa: F401


class _Bridge(QObject):
    """暴露给 JS 的回调对象（JS 通过 QWebChannel 调用 @Slot 方法）."""

    refreshRequested = QtSignal()
    rowClicked = QtSignal(str, str)
    periodRequested = QtSignal(str)
    strategyRequested = QtSignal(str)
    aiStrategyRequested = QtSignal(str)
    viewOptionRequested = QtSignal(str, str)
    alertToggled = QtSignal(str)

    @Slot()
    def requestRefresh(self) -> None:
        self.refreshRequested.emit()

    @Slot(str, str)
    def onRowClicked(self, code: str, name: str) -> None:
        self.rowClicked.emit(code, name)

    @Slot(str)
    def requestPeriod(self, period: str) -> None:
        self.periodRequested.emit(period)

    @Slot(str)
    def requestStrategy(self, payload_json: str) -> None:
        self.strategyRequested.emit(payload_json)

    @Slot(str)
    def requestAiStrategy(self, payload_json: str) -> None:
        self.aiStrategyRequested.emit(payload_json)

    # 两个重载：老 chart.html 只传标的代码，Vue 版的买卖点还会带上方向
    @Slot(str)
    @Slot(str, str)
    def viewOption(self, underlying_code: str, side: str = "") -> None:
        """跳到期权 T 型页。

        side 取 'call'/'put' 时让 T 型页只看那一侧（K 线买卖点跳过来时用：
        买点看认购、卖点看认沽）；空字符串表示不动当前的过滤。
        """
        self.viewOptionRequested.emit(underlying_code, side)

    @Slot(str)
    def toggleAlert(self, code: str) -> None:
        """用户在行情看板切换提醒开关."""
        self.alertToggled.emit(code)

    @Slot(str)
    def copyText(self, text: str) -> None:
        """写系统剪贴板（前端点合约代码用）.

        不用 JS 的 navigator.clipboard：页面是 qrc: 源，不算安全上下文，
        剪贴板 API 在那里不可用。走 Qt 的剪贴板最稳。
        """
        if not text:
            return
        from PySide6.QtGui import QGuiApplication

        clip = QGuiApplication.clipboard()
        if clip is not None:
            clip.setText(text)


class _BaseTab(QWebEngineView):
    def __init__(self, html_path: str, parent=None):
        super().__init__(parent)
        self.bridge = _Bridge(self)
        self.channel = QWebChannel(self)
        self.channel.registerObject("bridge", self.bridge)
        self.page().setWebChannel(self.channel)
        self.settings().setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        self.settings().setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
        # 页面异步加载：加载完成前的 runJavaScript 会被丢弃，先排队等 loadFinished 再补发
        self._page_loaded = False
        self._pending_js: list[str] = []
        self.loadFinished.connect(self._on_load_finished)
        self.setHtml(self._prepare_html(self._read_html(html_path)), QUrl("qrc:/web/"))

    def _prepare_html(self, html: str) -> str:
        """加载前改写 HTML 的钩子。默认原样返回，子类可注入运行期参数。"""
        return html

    def _on_load_finished(self, ok: bool) -> None:
        self._page_loaded = bool(ok)
        if not ok:
            self._pending_js.clear()
            return
        pending, self._pending_js = self._pending_js, []
        # 只补发每类渲染的最后一条（中间的已过期，没必要重放）
        for js in self._dedupe_pending(pending):
            self.page().runJavaScript(js)

    @staticmethod
    def _dedupe_pending(pending: list[str]) -> list[str]:
        """按 JS 函数名去重，保留每个函数最后一次调用（渲染是全量覆盖式的）."""
        last: dict[str, str] = {}
        for js in pending:
            fn = js.split("(", 1)[0]
            last[fn] = js
        return list(last.values())

    @staticmethod
    def _read_html(path: str) -> str:
        from PySide6.QtCore import QFile, QIODevice

        f = QFile(path)
        if not f.open(QIODevice.ReadOnly | QIODevice.Text):
            raise RuntimeError(f"cannot open {path}")
        return bytes(f.readAll().data()).decode("utf-8")

    def _run(self, js: str) -> None:
        if not self._page_loaded:
            self._pending_js.append(js)
            return
        self.page().runJavaScript(js)

    def _call(self, fn: str, payload: dict) -> None:
        """调用页面里的全局渲染函数（写法与 _dedupe_pending 的去重键保持一致）."""
        js = f"window.{fn} && window.{fn}({json.dumps(payload, ensure_ascii=False)});"
        self._run(js)


class ChartTab(_BaseTab):
    """K 线 / 分时图表页."""

    period_requested = QtSignal(str)
    view_option_requested = QtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(":/web/chart.html", parent)
        self.bridge.refreshRequested.connect(self._on_js_refresh)
        self.bridge.periodRequested.connect(self.period_requested)
        self.bridge.viewOptionRequested.connect(self.view_option_requested)
        self._pending_refresh = None

    def _on_js_refresh(self) -> None:
        if self._pending_refresh:
            self._pending_refresh()

    def set_refresh_handler(self, handler) -> None:
        self._pending_refresh = handler

    def update_chart(self, payload: dict) -> None:
        js = f"window.updateChart && window.updateChart({json.dumps(payload, ensure_ascii=False)});"
        self._run(js)


class TableTab(_BaseTab):
    """通用数据表格页."""

    row_clicked = QtSignal(str, str)
    alert_toggled = QtSignal(str)

    def __init__(self, parent=None):
        super().__init__(":/web/table.html", parent)
        self.bridge.rowClicked.connect(self.row_clicked)
        self.bridge.alertToggled.connect(self.alert_toggled)

    def render(self, payload: dict) -> None:
        js = f"window.renderTable && window.renderTable({json.dumps(payload, ensure_ascii=False)});"
        self._run(js)


class TShapeTab(_BaseTab):
    """期权 T 型报价页（含策略组合工具）."""

    row_clicked = QtSignal(str, str)
    strategy_requested = QtSignal(str)
    ai_strategy_requested = QtSignal(str)

    def __init__(self, parent=None):
        super().__init__(":/web/tshape.html", parent)
        self.bridge.rowClicked.connect(self.row_clicked)
        self.bridge.strategyRequested.connect(self.strategy_requested)
        self.bridge.aiStrategyRequested.connect(self.ai_strategy_requested)

    def render(self, payload: dict) -> None:
        js = f"window.renderTShape && window.renderTShape({json.dumps(payload, ensure_ascii=False)});"
        self._run(js)

    def render_strategy(self, payload: dict) -> None:
        js = f"window.renderStrategy && window.renderStrategy({json.dumps(payload, ensure_ascii=False)});"
        self._run(js)

    def render_ai_result(self, payload: dict) -> None:
        js = f"window.renderAiResult && window.renderAiResult({json.dumps(payload, ensure_ascii=False)});"
        self._run(js)


class AnalysisTab(_BaseTab):
    """期权分析页（波动率微笑 + 持仓量分布 + 卖方指标）."""

    def __init__(self, parent=None):
        super().__init__(":/web/analysis.html", parent)

    def render(self, payload: dict) -> None:
        js = f"window.renderAnalysis && window.renderAnalysis({json.dumps(payload, ensure_ascii=False)});"
        self._run(js)


class VueTab(_BaseTab):
    """Vue 前端页面（frontend/ 构建产物 app.html）.

    与上面 4 个手写 HTML 的 Tab 类完全并列、互不影响：迁移期两套共存，
    一页一页从老 Tab 换成 VueTab，任何一步都能单独回退。

    所有实例加载同一份 app.html，靠 route 参数决定显示哪一页
    （产物里的 `@@RJDJ_ROUTE@@` 标记在 setHtml 前被替换）。
    阶段 5 收敛成单实例 + 应用内导航后，route 只用于设置初始页。

    渲染入口与回调信号沿用既有契约，不新增也不改名，
    这样 main_window.py 换 Tab 时只改构造和 connect，不动数据组装。
    """

    # 对应 _Bridge 的 7 个 Slot（老 Tab 是按需连接子集，这里全都转发出来）
    refresh_requested = QtSignal()
    row_clicked = QtSignal(str, str)
    period_requested = QtSignal(str)
    strategy_requested = QtSignal(str)
    ai_strategy_requested = QtSignal(str)
    view_option_requested = QtSignal(str, str)
    alert_toggled = QtSignal(str)

    #: 产物里待替换的路由标记
    _ROUTE_MARK = "@@RJDJ_ROUTE@@"

    def __init__(self, route: str = "quotes", parent=None):
        # 必须先赋值：super().__init__ 内部就会调用 _prepare_html
        self._route = route
        super().__init__(":/web/app.html", parent)
        self.bridge.refreshRequested.connect(self.refresh_requested)
        self.bridge.rowClicked.connect(self.row_clicked)
        self.bridge.periodRequested.connect(self.period_requested)
        self.bridge.strategyRequested.connect(self.strategy_requested)
        self.bridge.aiStrategyRequested.connect(self.ai_strategy_requested)
        self.bridge.viewOptionRequested.connect(self.view_option_requested)
        self.bridge.alertToggled.connect(self.alert_toggled)

    @property
    def route(self) -> str:
        return self._route

    def _prepare_html(self, html: str) -> str:
        if self._ROUTE_MARK not in html:
            raise RuntimeError(
                f"app.html 里找不到 {self._ROUTE_MARK}，前端产物可能过期："
                "请跑 scripts/build_frontend.sh 重新构建"
            )
        return html.replace(self._ROUTE_MARK, self._route)

    # ---------- Python → JS 渲染入口（与老 Tab 同名同 payload） ----------

    def render_quotes(self, payload: dict) -> None:
        """行情看板（新契约：只发原始数据，视图逻辑在前端）."""
        self._call("renderQuotes", payload)

    def render_table(self, payload: dict) -> None:
        """旧看板契约，保留给回退用（老 table.html 那套）."""
        self._call("renderTable", payload)

    def update_chart(self, payload: dict) -> None:
        self._call("updateChart", payload)

    def render_tshape(self, payload: dict) -> None:
        self._call("renderTShape", payload)

    def render_strategy(self, payload: dict) -> None:
        self._call("renderStrategy", payload)

    def render_ai_result(self, payload: dict) -> None:
        self._call("renderAiResult", payload)

    def render_analysis(self, payload: dict) -> None:
        self._call("renderAnalysis", payload)
