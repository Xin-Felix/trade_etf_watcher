"""QWebEngineView 验收探针工具。

把异步的 WebEngine API 包成同步写法，验收脚本才读得懂。
各阶段的 smoke_* 脚本共用这些函数。

跑验收脚本必须带上：
  QT_QPA_PLATFORM=offscreen QTWEBENGINE_CHROMIUM_FLAGS="--disable-gpu --in-process-gpu"
否则 offscreen 下 GPU 上下文会崩，renderer 进程挂掉后所有 JS 求值都返回空。
"""
from __future__ import annotations

import json
from typing import Any

from PySide6.QtCore import QEventLoop, QTimer


def wait_loaded(view, timeout_ms: int = 20000) -> bool:
    """阻塞等 loadFinished。"""
    loop = QEventLoop()
    box = {"ok": False}

    def on_finished(ok: bool) -> None:
        box["ok"] = bool(ok)
        loop.quit()

    view.loadFinished.connect(on_finished)
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()
    return box["ok"]


def eval_js(view, expr: str, timeout_ms: int = 5000) -> Any:
    """同步求值一个 JS 表达式。

    只用标量（数字/字符串/布尔）：QWebEngine 的 runJavaScript 遇到复杂
    object 会把结果吞成空串，别指望能直接拿回 dict。要传结构就自己
    JSON.stringify 成字符串再解析。
    """
    loop = QEventLoop()
    box: dict[str, Any] = {"v": None}

    def cb(v: Any) -> None:
        box["v"] = v
        loop.quit()

    view.page().runJavaScript(expr, cb)
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()
    return box["v"]


def eval_json(view, expr: str, timeout_ms: int = 5000) -> Any:
    """求值一个表达式并按 JSON 解析（绕开 object 被吞的限制）。"""
    raw = eval_js(view, f"JSON.stringify({expr})", timeout_ms)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


def settle(ms: int) -> None:
    """让事件循环转一会儿（等 Vue mount / DOM 更新 / 图表渲染）。"""
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def wait_mounted(view, timeout_ms: int = 5000, step_ms: int = 100) -> bool:
    """轮询等 Vue 挂载完成，比固定 sleep 更稳也更快。"""
    waited = 0
    while waited < timeout_ms:
        if str(eval_js(view, "document.documentElement.dataset.rjdjMounted||''")) == "1":
            return True
        settle(step_ms)
        waited += step_ms
    return False


def count(view, selector: str) -> int:
    """匹配选择器的元素个数。"""
    v = eval_js(view, f"document.querySelectorAll({json.dumps(selector)}).length")
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def text_of(view, selector: str) -> str:
    """第一个匹配元素的 textContent（trim 后）。"""
    v = eval_js(
        view,
        f"((document.querySelector({json.dumps(selector)})||{{}}).textContent||'').trim()",
    )
    return str(v or "")


def texts_of(view, selector: str) -> list[str]:
    """所有匹配元素的 textContent 列表。"""
    expr = (
        f"Array.prototype.map.call(document.querySelectorAll({json.dumps(selector)}),"
        "function(e){return (e.textContent||'').trim();})"
    )
    return eval_json(view, expr) or []


def click(view, selector: str) -> None:
    """点击第一个匹配元素。"""
    eval_js(view, f"(document.querySelector({json.dumps(selector)})||{{click:function(){{}}}}).click()")


def install_error_hook(view) -> None:
    """挂 window.onerror，之后可用 js_errors() 读取。"""
    eval_js(view, "window.__err='';window.onerror=function(m,s,l){window.__err+=m+' @'+l+';'};")


def js_errors(view) -> str:
    return str(eval_js(view, "window.__err||''") or "")


def dispose(view) -> None:
    """销毁视图并让事件循环真正处理掉。

    QWebEngineView 必须在 QApplication 之前析构，否则退出时 segfault
    （Python 的 GC 顺序不保证）。deleteLater 需要事件循环跑一轮才生效。
    """
    try:
        view.page().setWebChannel(None)
    except Exception:  # noqa: BLE001
        pass
    view.close()
    view.deleteLater()
    settle(150)


def finish(rc: int) -> None:
    """收尾退出。

    WebEngine 的 profile 在解释器退出阶段偶发 segfault，会把已经跑完的
    验收结果变成不可靠的退出码。断言都做完了，直接结束进程最省事。
    """
    import os
    import sys

    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(rc)
