"""冒烟：Vue 前端骨架在真实 Qt WebEngine 里的完整链路（阶段 0 建立，持续回归）.

用法：
  QT_QPA_PLATFORM=offscreen QTWEBENGINE_CHROMIUM_FLAGS="--disable-gpu --in-process-gpu" \
    PYTHONPATH=. python scripts/smoke_vue_shell.py

验证四件事（都是机制层面，与具体页面无关）：
  1. route 注入        —— 同一份 app.html，不同 VueTab 显示不同页
  2. Vue mount + 桥接  —— 应用真的起来了，QWebChannel 双向通
  3. mount 前推送不丢  —— 构造后立刻推数据（此时页面还没加载完），
                          经 Python 的 _pending_js + 前端 __RJDJ_PENDING__
                          两层兜底后，mount 时应被重放出来
  4. 路由分发          —— route 注入真的切到了对应视图
  5. 老页面无回归      —— 手写 HTML 的 Tab 仍能加载、渲染入口仍在

注：探针（pushes / bridge / route）挂在 Placeholder 页上，所以这里用专门的
    诊断路由 __probe__（永远渲染 Placeholder），这样某个页面迁移完成后
    本脚本不会失效。各页面的功能验收见对应的 smoke_*.py。
"""
from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from scripts.webengine_probe import (
    dispose,
    eval_js,
    finish,
    install_error_hook,
    js_errors,
    settle,
    text_of,
    wait_loaded,
    wait_mounted,
)
from watcher.gui.web.webtab import (
    AnalysisTab,
    ChartTab,
    TableTab,
    TShapeTab,
    VueTab,
)


def sample_payload(n: int) -> dict:
    """最小 QuotesPayload：骨架验收只看条数是否送达，不看渲染细节。"""
    return {
        "quotes": [
            {
                "code": f"sh51000{i}",
                "name": f"标的{i}",
                "price": 1.0 + i,
                "open": 1.0 + i,
                "prevClose": 1.0 + i,
                "volume": 100 * i,
                "ts": "",
                "source": "smoke",
            }
            for i in range(n)
        ],
        "indices": [],
        "indexMap": {},
        "alertCodes": [],
        "signals": {},
        "source": "smoke",
    }


def probe(view, name: str) -> str:
    return text_of(view, f"[data-probe={name}]")


def case_route_and_bridge(errs: list[str]) -> None:
    """场景 1+2：route 注入、Vue mount、桥接双向（含 JS → Python 出站回调）."""
    print("[1] route 注入 + Vue mount + 桥接双向")
    tab = VueTab(route="__probe__")
    tab.resize(900, 600)

    got: list[tuple[str, str]] = []
    tab.row_clicked.connect(lambda c, n: got.append((c, n)))

    if not wait_loaded(tab):
        errs.append("[1] 页面加载失败")
        return
    install_error_hook(tab)
    if not wait_mounted(tab):
        errs.append("[1] Vue 没有 mount")
        dispose(tab)
        return
    settle(300)  # 等 QWebChannel 握手

    route = probe(tab, "route")
    bridge = probe(tab, "bridge")
    err = js_errors(tab)
    print(f"    route={route!r} bridge={bridge!r} jsErr={err or '无'}")
    if route != "__probe__":
        errs.append(f"[1] route 注入失败：期望 __probe__，实际 {route!r}")
    if bridge != "已连接":
        errs.append(f"[1] QWebChannel 未连通：{bridge!r}")
    if err:
        errs.append(f"[1] 页面有 JS 错误：{err}")

    # 入站：Python → Vue
    tab.render_quotes(sample_payload(3))
    settle(300)
    pushes = probe(tab, "pushes")
    last = probe(tab, "last")
    print(f"    推送后 pushes={pushes!r} last={last!r}")
    if pushes != "1":
        errs.append(f"[1] Vue 没收到推送：pushes={pushes!r}")
    if "3条" not in last:
        errs.append(f"[1] payload 内容没进 Vue：last={last!r}")

    # 出站：Vue → Python
    eval_js(tab, "document.querySelector('[data-probe=ping]').click()")
    settle(300)
    print(f"    出站回调收到 {len(got)} 条: {got}")
    if not got:
        errs.append("[1] 没收到 JS → Python 的 row_clicked 回调")
    elif got[0][0] != "probe:__probe__":
        errs.append(f"[1] 回调参数不对：{got[0]}")

    dispose(tab)


def case_push_before_mount(errs: list[str]) -> None:
    """场景 3：构造后立刻推送（页面尚未加载），验证两层兜底把数据重放出来."""
    print("[2] mount 前推送不丢（关键路径）")
    tab = VueTab(route="__probe__")
    tab.resize(900, 600)

    # 此刻 _page_loaded=False，JS 进 Python 侧的 _pending_js 队列。
    # loadFinished 时补发，但那一瞬 Vue 可能还没 mount，
    # 于是落到前端 __RJDJ_PENDING__ 缓冲，mount 后由 installRenderHandlers 重放。
    tab.render_quotes(sample_payload(7))
    print("    已在加载完成前推送 7 条")

    if not wait_loaded(tab):
        errs.append("[2] 页面加载失败")
        return
    if not wait_mounted(tab):
        errs.append("[2] Vue 没有 mount")
        dispose(tab)
        return
    settle(300)

    route = probe(tab, "route")
    pushes = probe(tab, "pushes")
    last = probe(tab, "last")
    leftover = str(eval_js(tab, "JSON.stringify(Object.keys(window.__RJDJ_PENDING__||{}))"))
    print(f"    route={route!r} pushes={pushes!r} last={last!r} 残留缓冲={leftover}")

    if route != "__probe__":
        errs.append(f"[2] route 注入失败：{route!r}")
    if pushes != "1":
        errs.append(f"[2] mount 前的推送丢了：pushes={pushes!r}（期望 1）")
    if "7条" not in last:
        errs.append(f"[2] 重放的 payload 不对：last={last!r}")
    if leftover != "[]":
        errs.append(f"[2] 缓冲未清空：{leftover}")

    dispose(tab)


def case_route_dispatch(errs: list[str]) -> None:
    """场景 4：route 注入真的切到了不同视图（不只是值传进去了）。

    随着迁移推进，这里的 selector 要跟着更新：已迁移的路由认真实视图，
    未迁移的认 Placeholder 探针。
    """
    print("[3] 路由分发到对应视图")
    cases = [
        ("quotes", ".board", "行情看板"),
        ("analysis", ".expiry-bar, [data-probe=empty]", "期权分析"),
        ("__probe__", "[data-probe=route]", "骨架诊断"),
    ]
    for route, selector, desc in cases:
        tab = VueTab(route=route)
        tab.resize(900, 600)
        ok = wait_loaded(tab)
        mounted = wait_mounted(tab) if ok else False
        settle(200)
        hit = int(eval_js(tab, f"document.querySelectorAll({selector!r}).length") or 0)
        print(f"    {route:10s} → {desc:6s} 命中 {selector!r}: {hit}")
        if not mounted:
            errs.append(f"[3] {route} 没 mount")
        elif hit < 1:
            errs.append(f"[3] {route} 没渲染出 {desc}（选择器 {selector} 命中 0）")
        dispose(tab)


def case_legacy_pages(errs: list[str]) -> None:
    """场景 4：手写 HTML 页面没被动坏（迁移期两套并存，随时可回退）."""
    print("[4] 老页面无回归")
    cases = [
        ("TableTab", TableTab, "renderTable"),
        ("ChartTab", ChartTab, "updateChart"),
        ("TShapeTab", TShapeTab, "renderTShape"),
        ("AnalysisTab", AnalysisTab, "renderAnalysis"),
    ]
    for name, cls, fn in cases:
        tab = cls()
        tab.resize(800, 500)
        ok = wait_loaded(tab)
        settle(200)
        typ = str(eval_js(tab, f"typeof window.{fn}"))
        print(f"    {name:12s} loaded={ok} window.{fn}={typ}")
        if not ok:
            errs.append(f"[4] {name} 加载失败")
        if typ != "function":
            errs.append(f"[4] {name} 的 window.{fn} 不是函数（{typ}）")
        dispose(tab)


def main() -> int:
    app = QApplication(sys.argv)
    errs: list[str] = []

    case_route_and_bridge(errs)
    print()
    case_push_before_mount(errs)
    print()
    case_route_dispatch(errs)
    print()
    case_legacy_pages(errs)

    print()
    if errs:
        print("✗ 验收失败：")
        for e in errs:
            print("   -", e)
        rc = 1
    else:
        print("✓ Vue 骨架验收通过"
              "（route 注入 / Vue mount / 桥接双向 / mount 前推送不丢 / 老页面无回归）")
        rc = 0

    settle(300)
    app.quit()
    settle(100)
    return rc


if __name__ == "__main__":
    finish(main())
