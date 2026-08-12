"""冒烟：期权策略工具端到端（真实点击预设按钮 → JS→bridge→Python→JS → 校验 DOM）.

用法：PYTHONPATH=. python scripts/smoke_strategy.py
说明：不截图（QWebEngineView.grab() 抓不到 GPU 合成的网页内容），直接读 DOM 断言。
"""
from __future__ import annotations

import json
import sys

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QApplication

from watcher.config import Config
from watcher.state import StateStore

PRESETS_TO_TEST = ["long_call", "bull_call_spread", "long_straddle", "call_butterfly"]

DOM_PROBE = """
JSON.stringify({
  rows: document.querySelectorAll('#twrap .srow').length,
  chips: document.querySelectorAll('#expiry-bar .chip').length,
  presetBtns: document.querySelectorAll('.prebtn').length,
  legBtns: document.querySelectorAll('.legbtn').length,
  basketLegs: document.querySelectorAll('#basket .bleg').length,
  metricCards: document.querySelectorAll('#metrics .m').length,
  metrics: Array.from(document.querySelectorAll('#metrics .m')).map(
             m => m.querySelector('.k').textContent + '=' + m.querySelector('.v').textContent),
  collapsed: document.getElementById('strat').classList.contains('collapsed'),
  payoffCanvas: !!document.querySelector('#payoff canvas'),
  msg: document.getElementById('strat-msg').style.display === 'none'
         ? '' : document.getElementById('strat-msg').textContent
})
"""


class _FakeSignals(QObject):
    quotes_updated = Signal(dict)
    signals_fired = Signal(list)
    option_quotes_updated = Signal(str)
    state_changed = Signal(object)


class _FakeWatcher:
    def __init__(self, store: StateStore):
        self.signals = _FakeSignals()
        self._store = store

    def option_underlyings(self):
        return self._store.option_underlyings()

    def fetch_daily_bars(self, code, limit=120):
        return []

    def refresh_now(self):
        pass


def main() -> int:
    app = QApplication(sys.argv)
    cfg = Config.load()
    store = StateStore()

    from watcher.gui.main_window import MainWindow

    win = MainWindow(cfg, store, _FakeWatcher(store), tray=None)
    win.resize(1500, 950)
    win.show()
    win.tabs.setCurrentIndex(3)  # 期权 T 型

    page = win.option_table.page()
    failures: list[str] = []
    steps: list = []

    def js(code: str, cb=None):
        page.runJavaScript(code, 0, cb or (lambda _r: None))

    def probe(tag: str, expect_legs: int | None = None):
        def run():
            def on_result(raw):
                try:
                    d = json.loads(raw) if raw else {}
                except (TypeError, ValueError):
                    d = {}
                if not d:
                    failures.append(f"{tag}: DOM 探测无返回")
                    print(f"  !! {tag}: DOM 探测无返回")
                    return
                print(f"\n[{tag}]")
                print(f"  T型行数={d['rows']} 到期chips={d['chips']} 加腿按钮={d['legBtns']}")
                print(f"  预设按钮={d['presetBtns']} 篮子腿数={d['basketLegs']} "
                      f"指标卡={d['metricCards']} 抽屉收起={d['collapsed']} 损益图canvas={d['payoffCanvas']}")
                if d["msg"]:
                    print(f"  提示: {d['msg']}")
                for m in d["metrics"]:
                    print(f"    {m}")

                if d["rows"] == 0:
                    failures.append(f"{tag}: T 型表格没有行")
                if d["presetBtns"] == 0:
                    failures.append(f"{tag}: 预设按钮未渲染")
                if d["legBtns"] == 0:
                    failures.append(f"{tag}: 表格里没有加腿按钮")
                if expect_legs is not None:
                    if d["basketLegs"] != expect_legs:
                        failures.append(
                            f"{tag}: 篮子腿数={d['basketLegs']}，期望 {expect_legs}")
                    if d["metricCards"] != 8:
                        failures.append(f"{tag}: 指标卡={d['metricCards']}，期望 8")
                    if not d["payoffCanvas"]:
                        failures.append(f"{tag}: 损益图未渲染")
                    if d["collapsed"]:
                        failures.append(f"{tag}: 有腿时抽屉仍是收起状态")
            js(DOM_PROBE, on_result)
        return run

    def click_preset(key: str):
        def run():
            js(f"document.querySelector('.prebtn[data-k=\"{key}\"]').click()")
        return run

    def click_leg_button(idx: int):
        def run():
            js(f"document.querySelectorAll('.legbtn')[{idx}].click()")
        return run

    def clear_basket():
        def run():
            js("document.getElementById('strat-clear').click()")
        return run

    def pick_underlying():
        lst = win.option_underlying_list
        if lst.count() == 0:
            failures.append("期权标的列表为空（DB 无合约表？先跑一次 python -m watcher）")
            app.quit()
            return
        lst.setCurrentRow(0)
        code = lst.currentItem().data(0x0100)
        chain, spot = win._strategy_chain(code)
        quoted = [c for c in chain if (c["price"] or 0) > 0]
        print(f"标的 {code}：合约 {len(chain)} 条（有报价 {len(quoted)}），现价 {spot}")
        if spot <= 0:
            failures.append("标的无现价，策略无法计算")

    steps.append(pick_underlying)
    steps.append(probe("初始（空篮子）"))
    expect = {"long_call": 1, "bull_call_spread": 2, "long_straddle": 2, "call_butterfly": 3}
    for key in PRESETS_TO_TEST:
        steps.append(click_preset(key))
        steps.append(probe(f"预设 {key}", expect[key]))
    # 手动加腿路径：清空后点表格里的「买」
    steps.append(clear_basket())
    steps.append(click_leg_button(0))
    steps.append(probe("手动点「买」加腿", 1))

    def finish():
        print("\n" + "=" * 60)
        if failures:
            print(f"失败 {len(failures)} 项：")
            for f in failures:
                print(f"  - {f}")
        else:
            print("全部通过：T型表格 / 预设 / 篮子 / 指标卡 / 损益图 / 手动加腿 均正常")
        app.exit(1 if failures else 0)

    steps.append(finish)

    # 每步间隔要够：一次交互是 JS→bridge→Python→JS 的异步往返，间隔太短会误判
    delay = 3000  # 等 WebEngine 首屏 + qrc 资源加载
    for i, fn in enumerate(steps):
        QTimer.singleShot(delay + i * 1100, fn)

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
