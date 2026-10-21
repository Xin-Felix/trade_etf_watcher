"""冒烟：K 线图（Vue 版）在真实 Qt WebEngine 里的渲染与交互.

用法：
  QT_QPA_PLATFORM=offscreen QTWEBENGINE_CHROMIUM_FLAGS="--disable-gpu --in-process-gpu" \
    PYTHONPATH=. python scripts/smoke_chart.py [标的代码]

从本地 SQLite 取真实分钟 K → _build_chart_payload → 推给 VueTab → 回读 DOM。

重点验证：
  - 三个 grid（主图/成交量/MACD）都画出来了
  - 周期按钮渲染与点击回调
  - 悬停联动：legend 与右侧面板跟着十字光标变，移出还原到最新
  - 缩放窗口跨刷新保持（定时刷新不该把视图拉回默认）
  - loading 变体不清空旧图
  - 信号标记按时间戳定位正确
"""
from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from scripts.webengine_probe import (
    click,
    count,
    dispose,
    eval_js,
    eval_json,
    finish,
    install_error_hook,
    js_errors,
    settle,
    text_of,
    wait_loaded,
    wait_mounted,
)
from watcher.config import Config
from watcher.gui.main_window import MainWindow
from watcher.gui.web.webtab import VueTab
from watcher.state import StateStore

PERIODS = ["分时", "1分", "5分", "15分", "30分", "60分", "日K"]


class _Builder:
    """借 MainWindow 的 payload 组装，不构造主窗口。"""

    _build_chart_payload = MainWindow._build_chart_payload
    _bar_label = staticmethod(MainWindow._bar_label)

    def __init__(self, cfg, store, signals: list[dict]) -> None:
        self.cfg = cfg
        self.store = store
        self._signals = signals

    # 这两个在 payload 组装里会被调用，冒烟时给固定值
    def _chart_quote(self, code: str) -> dict | None:
        q = self.store.latest_quotes().get(code)
        if not q or q.price <= 0:
            return None
        chg = round(q.price - q.prev_close, 4) if q.prev_close else None
        pct = round((q.price - q.prev_close) / q.prev_close * 100, 2) if q.prev_close else None
        return {
            "price": q.price, "change": chg, "changePct": pct,
            "open": q.open, "high": q.high, "low": q.low,
            "prevClose": q.prev_close or None, "volume": q.volume, "extras": [],
        }

    def _atm_shortcuts(self, code: str) -> dict | None:
        return {"underlying": code} if self.store.get_option_contracts(code) else None

    def _compute_chart_signals(self, *_a, **_k) -> list[dict]:
        return self._signals


def build_payload(code: str | None) -> tuple[dict, str]:
    cfg = Config.load()
    store = StateStore()
    target = code or "sh510300"
    bars = store.get_bars(target, limit=400)
    if len(bars) < 30:
        raise SystemExit(f"✗ {target} 本地分钟 K 不足（{len(bars)} 根），先跑主程序攒数据")

    # 造两条信号，ts 取真实 bar 的时间戳（验证按时间戳定位）
    sig_bars = [bars[len(bars) // 3], bars[len(bars) * 2 // 3]]
    signals = [
        {"key": "resonance_long", "label": "x", "ts": sig_bars[0].ts,
         "labelText": "【多头共振】测试买点"},
        {"key": "resonance_short", "label": "y", "ts": sig_bars[1].ts,
         "labelText": "【空头共振】测试卖点"},
    ]
    b = _Builder(cfg, store, signals)
    payload = b._build_chart_payload(target, cfg.name_for(target), bars,
                                     "candle", "time", "1分", PERIODS)
    payload["quote"] = b._chart_quote(target)
    print(f"标的 {target}：{len(bars)} 根 bars，labelFmt={payload['labelFmt']}，"
          f"信号 {len(payload['signals'])} 条")
    print(f"  信号 ts: {[s['ts'] for s in payload['signals']]}")
    return payload, target


def series_names(tab) -> list[str]:
    """从 echarts 实例读回 series 名字，确认三个 grid 的内容都在。"""
    return eval_json(
        tab,
        "(function(){var el=document.querySelector('[data-echart]');"
        "if(!el||!window.__ec)return null;"
        "var o=window.__ec.getOption();"
        "return (o.series||[]).map(function(s){return s.name||s.type});})()",
    ) or []


def case_render(tab, errs: list[str], payload: dict) -> None:
    print("[1] 图表渲染 + 三个 grid")
    n = count(tab, "[data-echart] canvas")
    sizes = eval_json(
        tab,
        "Array.prototype.map.call(document.querySelectorAll('[data-echart] canvas'),"
        "function(c){return [c.width,c.height];})",
    ) or []
    print(f"    canvas={n} 尺寸={sizes}")
    if n < 1:
        errs.append("[1] 没有 canvas，图表没渲染")
    if any(not s or s[0] <= 0 or s[1] <= 0 for s in sizes):
        errs.append(f"[1] canvas 尺寸异常：{sizes}")

    names = series_names(tab)
    print(f"    series={names}")
    for must in ["K线", "MA5", "MA10", "MA20", "成交量", "均量", "DIF", "DEA", "MACD"]:
        if must not in names:
            errs.append(f"[1] 缺少 series：{must}")

    grids = eval_js(tab, "(window.__ec?window.__ec.getOption().grid.length:0)")
    print(f"    grid 数={grids}（主图/成交量/MACD）")
    if int(grids or 0) != 3:
        errs.append(f"[1] grid 数应为 3，实际 {grids}")

    title = text_of(tab, "[data-probe=title]")
    print(f"    标题={title!r}")
    if payload["title"] not in title:
        errs.append(f"[1] 标题不对：{title!r}")


def case_periods(tab, errs: list[str], payload: dict, got: list[str]) -> None:
    print("[2] 周期按钮")
    n = count(tab, "[data-probe=period-bar] .pbtn")
    active = text_of(tab, "[data-probe=period-bar] .pbtn.active")
    print(f"    按钮={n}（期望 {len(payload['periods'])}）当前={active!r}")
    if n != len(payload["periods"]):
        errs.append(f"[2] 周期按钮数 {n} != {len(payload['periods'])}")
    if active != payload["period"]:
        errs.append(f"[2] 高亮的周期不对：{active!r} != {payload['period']!r}")

    click(tab, '[data-period="5分"]')
    settle(250)
    print(f"    点「5分」后 Python 收到: {got}")
    if "5分" not in got:
        errs.append("[2] 没收到 period_requested('5分')")


def case_legend_and_side(tab, errs: list[str], payload: dict) -> None:
    print("[3] legend 与右侧面板（默认显示最新一根）")
    legend = text_of(tab, "[data-probe=legend]")
    price = text_of(tab, "[data-probe=side-price]")
    last = payload["bars"][-1]
    print(f"    legend={legend!r}")
    print(f"    侧栏现价={price!r}")
    if not legend:
        errs.append("[3] legend 空")
    else:
        # 默认应显示最后一根：收盘价应出现在 legend 里
        if f"{last['close']:.3f}" not in legend:
            errs.append(f"[3] legend 没显示最新一根收盘价 {last['close']:.3f}：{legend!r}")
    if not price or price == "--":
        errs.append(f"[3] 侧栏现价没渲染：{price!r}")


def case_hover(tab, errs: list[str], payload: dict) -> None:
    """派真实鼠标事件到 canvas，走完整的 updateAxisPointer 链路。

    坐标用 echarts 的 convertToPixel 算，避免手推 grid 布局。
    注意要先把缩放拉到全量：默认只显示末尾约 60 根，中间的 bar 不在可见区，
    悬停不到（第一次跑就是栽在这）。
    """
    print("[4] 悬停联动：legend 与侧栏跟着变，移出还原")
    bars = payload["bars"]
    target = len(bars) // 2
    tgt_close = f"{bars[target]['close']:.3f}"
    last_close = f"{bars[-1]['close']:.3f}"

    eval_js(tab, "window.__ec.dispatchAction({type:'dataZoom', start:0, end:100})")
    settle(300)

    before = text_of(tab, "[data-probe=legend]")
    moved = eval_json(
        tab,
        "(function(){"
        "var ec=window.__ec, c=document.querySelector('[data-echart] canvas');"
        f"var x=ec.convertToPixel({{xAxisIndex:0}}, {target});"
        "if(x==null||!c) return null;"
        "var r=c.getBoundingClientRect();"
        "var ev=new MouseEvent('mousemove',{clientX:r.left+x, clientY:r.top+150, bubbles:true});"
        "c.dispatchEvent(ev); return [x, r.left, r.top];})()",
    )
    settle(400)
    hovered = text_of(tab, "[data-probe=legend]")
    hovered_price = text_of(tab, "[data-probe=side-price]")
    print(f"    悬停第 {target} 根（收 {tgt_close}）像素坐标={moved}")
    print(f"      legend: {before!r}")
    print(f"           → {hovered!r}")
    print(f"      侧栏现价 → {hovered_price!r}")
    if moved is None:
        errs.append("[4] 算不出悬停坐标（convertToPixel 返回空）")
    if tgt_close not in hovered:
        errs.append(f"[4] 悬停后 legend 没切到第 {target} 根（应含 {tgt_close}）：{hovered!r}")
    if hovered_price != tgt_close:
        errs.append(f"[4] 悬停后侧栏现价应为 {tgt_close}，实际 {hovered_price!r}")

    # 鼠标移出图表：zrender 的 globalout 事件
    eval_js(
        tab,
        "(function(){var c=document.querySelector('[data-echart] canvas');"
        "c.dispatchEvent(new MouseEvent('mouseout',{bubbles:true,relatedTarget:document.body}));"
        "return 1;})()",
    )
    settle(400)
    restored = text_of(tab, "[data-probe=legend]")
    restored_price = text_of(tab, "[data-probe=side-price]")
    print(f"    移出后 legend={restored!r} 侧栏={restored_price!r}")
    if last_close not in restored:
        errs.append(f"[4] 移出后 legend 没还原到最新一根（应含 {last_close}）：{restored!r}")


def case_zoom_persist(tab, errs: list[str], payload: dict) -> None:
    print("[5] 缩放窗口跨刷新保持")
    # 手动缩放到 [20, 60]
    eval_js(
        tab,
        "window.__ec && window.__ec.dispatchAction({type:'dataZoom', start:20, end:60})",
    )
    settle(350)
    before = eval_json(
        tab,
        "(function(){var d=window.__ec.getOption().dataZoom[0];return [d.start,d.end]})()",
    )
    print(f"    缩放到 {before}")

    # 模拟定时刷新：重推同一份 payload
    tab.update_chart(payload)
    settle(500)
    after = eval_json(
        tab,
        "(function(){var d=window.__ec.getOption().dataZoom[0];return [d.start,d.end]})()",
    )
    print(f"    重推 payload 后 {after}")
    if not before or not after:
        errs.append("[5] 读不到 dataZoom 状态")
    elif abs(after[0] - before[0]) > 1 or abs(after[1] - before[1]) > 1:
        errs.append(f"[5] 缩放窗口被重置：{before} → {after}")


def case_signals(tab, errs: list[str], payload: dict) -> None:
    print("[6] 信号标记按时间戳定位")
    marks = eval_json(
        tab,
        "(function(){var s=window.__ec.getOption().series[0];"
        "return (s.markPoint&&s.markPoint.data||[]).map(function(d){"
        "return {coord:d.coord, label:(d.label&&d.label.formatter)||''}})})()",
    ) or []
    print(f"    markPoint={marks}")
    if len(marks) != len(payload["signals"]):
        errs.append(f"[6] markPoint 数 {len(marks)} != 信号数 {len(payload['signals'])}")

    # 用 ts 独立算出期望下标
    want = []
    for s in payload["signals"]:
        for i, b in enumerate(payload["bars"]):
            if b["ts"][:12] == s["ts"][:12]:
                want.append(i)
                break
    got = sorted(m["coord"][0] for m in marks if m.get("coord"))
    print(f"    期望下标={sorted(want)} 实际={got}")
    if sorted(want) != got:
        errs.append(f"[6] 信号定位不对：期望 {sorted(want)}，实际 {got}")
    labels = [m["label"] for m in marks]
    if "买" not in labels or "卖" not in labels:
        errs.append(f"[6] 买/卖标记缺失：{labels}")


def case_loading(tab, errs: list[str], payload: dict) -> None:
    print("[7] loading 变体不清空旧图")
    before = count(tab, "[data-echart] canvas")
    tab.update_chart({
        "title": "加载测试 (sh510300)",
        "loading": True,
        "period": "日K",
        "periods": PERIODS,
    })
    settle(400)
    after = count(tab, "[data-echart] canvas")
    active = text_of(tab, "[data-probe=period-bar] .pbtn.active")
    print(f"    canvas {before} → {after}；周期高亮切到 {active!r}")
    if after < 1:
        errs.append("[7] loading 时旧图被清空了（应保留）")
    if active != "日K":
        errs.append(f"[7] loading 时周期按钮应更新为 日K，实际 {active!r}")

    # 恢复
    tab.update_chart(payload)
    settle(400)


def main() -> int:
    code = sys.argv[1] if len(sys.argv) > 1 else None
    payload, target = build_payload(code)

    app = QApplication([])
    errs: list[str] = []
    periods_got: list[str] = []
    view_option_got: list[str] = []
    refresh_got: list[int] = []

    tab = VueTab(route="chart")
    tab.resize(1400, 900)
    tab.show()  # 不 show 视口是 0×0，图表容器没宽度，EChart 会跳过初始化
    tab.period_requested.connect(lambda p: periods_got.append(p))
    tab.view_option_requested.connect(lambda c, s: view_option_got.append((c, s)))
    tab.refresh_requested.connect(lambda: refresh_got.append(1))

    if not wait_loaded(tab):
        print("✗ 页面加载失败")
        return 1
    install_error_hook(tab)
    if not wait_mounted(tab):
        print("✗ Vue 没有 mount")
        return 1

    tab.update_chart(payload)
    settle(900)
    # EChart 组件把实例挂在宿主元素的 __echarts__ 上，
    # 拿到后用 dispatchAction 驱动真实事件链路（和鼠标操作同一条路）
    # 注意语句必须返回布尔而不是实例本身：QWebEngine 的 runJavaScript
    # 在序列化不可序列化对象时会把整个结果吞掉（赋值虽生效但拿不到确认）
    ok = eval_js(
        tab,
        "(function(){var el=document.querySelector('[data-echart]');"
        "window.__ec = el ? el.__echarts__ : null; return !!window.__ec;})();",
    )
    if not ok:
        print("✗ 拿不到 echarts 实例，无法验证图表内部状态")
        return 1
    print("  echarts 实例可访问: True")

    print()
    case_render(tab, errs, payload)
    print()
    case_periods(tab, errs, payload, periods_got)
    print()
    case_legend_and_side(tab, errs, payload)
    print()
    case_hover(tab, errs, payload)
    print()
    case_zoom_persist(tab, errs, payload)
    print()
    case_signals(tab, errs, payload)
    print()
    case_loading(tab, errs, payload)

    print()
    click(tab, "[data-probe=refresh]")
    settle(200)
    print(f"[8] 刷新按钮回调: {'收到' if refresh_got else '未收到'}")
    if not refresh_got:
        errs.append("[8] 没收到 refresh_requested")
    if count(tab, "[data-probe=view-option]"):
        click(tab, "[data-probe=view-option]")
        settle(200)
        print(f"    查看期权 T 型回调: {view_option_got}")
        if not view_option_got:
            errs.append("[8] 没收到 view_option_requested")

    err = js_errors(tab)
    print()
    print(f"页面 JS 错误: {err or '无'}")
    if err:
        errs.append(f"页面有 JS 错误：{err}")

    dispose(tab)
    print()
    if errs:
        print("✗ 验收失败：")
        for e in errs:
            print("   -", e)
        rc = 1
    else:
        print(f"✓ K 线图（Vue 版）验收通过 —— {target}")
        rc = 0
    settle(200)
    app.quit()
    return rc


if __name__ == "__main__":
    finish(main())
