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
    viewOptionRequested = QtSignal(str)
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

    @Slot(str)
    def viewOption(self, underlying_code: str) -> None:
        self.viewOptionRequested.emit(underlying_code)

    @Slot(str)
    def toggleAlert(self, code: str) -> None:
        """用户在行情看板切换提醒开关."""
        self.alertToggled.emit(code)


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
        self.setHtml(self._read_html(html_path), QUrl("qrc:/web/"))

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


class ChartTab(_BaseTab):
    """K 线 / 分时图表页."""

    period_requested = QtSignal(str)
    view_option_requested = QtSignal(str)

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
