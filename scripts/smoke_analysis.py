"""冒烟：期权分析页（Vue 版）在真实 Qt WebEngine 里的 6 个面板.

用法：
  QT_QPA_PLATFORM=offscreen QTWEBENGINE_CHROMIUM_FLAGS="--disable-gpu --in-process-gpu" \
    PYTHONPATH=. python scripts/smoke_analysis.py [标的代码]

从本地 SQLite 取真实期权合约与报价 → build_tshape_data（契约未变）
→ 推给 VueTab → 回读 DOM 断言。

重点验证：
  - 6 个面板按数据可用性渲染（缺数据的整块不出现）
  - 卖方指标 14 张卡
  - 5 张图表的 canvas 真的画出来了（EChart 实例建起来 + 有尺寸）
  - 到期月切换生效
  - 面板折叠/展开后图表仍在且尺寸正确（旧版这里漏 resize 过 3 个图表）
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
    texts_of,
    wait_loaded,
    wait_mounted,
)
from watcher.config import Config
from watcher.gui.web.webtab import VueTab
from watcher.option_meta import build_tshape_data
from watcher.state import StateStore

# 图表面板 → 是否应有 canvas
CHART_PANELS = ["smile", "oi", "smileAll", "surface", "term"]


def build_payload(code: str | None) -> tuple[dict, str]:
    cfg = Config.load()
    store = StateStore()
    unders = store.option_underlyings()
    if not unders:
        raise SystemExit("✗ 本地库里没有期权合约，先跑一次主程序攒数据")
    target = code or ("sh510300" if "sh510300" in unders else unders[0])
    if target not in unders:
        raise SystemExit(f"✗ {target} 没有合约数据，可选：{unders}")

    contracts = store.get_option_contracts(target)
    quotes = {q["option_code"]: q for q in store.get_option_quotes(target)}
    underlying_quote = store.latest_quotes().get(target)
    name = cfg.name_for(target)
    payload = build_tshape_data(contracts, quotes, target, name, underlying_quote)
    print(f"标的 {target}（{name}）：{len(contracts)} 合约 / {len(quotes)} 报价 / "
          f"{len(payload['expiries'])} 个到期月")
    print(f"  标的现价: {payload['underlying']['price']}")
    return payload, target


def expected_panels(payload: dict) -> dict[str, bool]:
    """独立算一遍各面板该不该出现（与前端 available 的判定对齐）。"""
    exp = payload["expiries"]
    default = payload.get("defaultExpiry")
    smile = payload.get("smile") or {}
    oi = payload.get("oi") or {}
    seller = payload.get("seller") or {}
    surface = payload.get("surface")
    iv_term = payload.get("ivTerm") or []

    cur_smile = smile.get(default) or {}
    cur_oi = oi.get(default) or {}
    valid_smile_months = [e for e in exp if (smile.get(e["date"]) or {}).get("strikes")]

    return {
        "seller": default in seller,
        "smile": bool(cur_smile.get("strikes")),
        "oi": bool(cur_oi.get("strikes"))
        and (max(cur_oi.get("callOI") or [0]) > 0 or max(cur_oi.get("putOI") or [0]) > 0),
        "smileAll": len(valid_smile_months) >= 2,
        "surface": bool(surface)
        and bool(surface.get("strikes"))
        and any(v is not None for r in surface.get("rows", []) for v in r["ivs"]),
        "term": len(iv_term) >= 2,
    }


def case_panels(tab, errs: list[str], want: dict[str, bool]) -> None:
    print("[1] 面板按数据可用性渲染")
    for pid, should in want.items():
        got = count(tab, f'section[data-panel="{pid}"]') > 0
        flag = "✓" if got == should else "✗"
        print(f"    {flag} {pid:9s} 期望={'显示' if should else '自隐'} 实际={'显示' if got else '自隐'}")
        if got != should:
            errs.append(f"[1] 面板 {pid} 可用性判定不对（期望 {should}，实际 {got}）")


def case_expiry_chips(tab, errs: list[str], payload: dict) -> None:
    print("[2] 到期月 chips")
    n = count(tab, "[data-probe=expiry-chip]")
    active = texts_of(tab, "[data-probe=expiry-chip].active")
    want_n = len(payload["expiries"])
    print(f"    chips={n}（期望 {want_n}）选中={active}")
    if n != want_n:
        errs.append(f"[2] chips 数 {n} != {want_n}")
    if len(active) != 1:
        errs.append(f"[2] 应恰好选中 1 个到期月，实际 {len(active)}")
    else:
        default = payload.get("defaultExpiry")
        label = next((e["label"] for e in payload["expiries"] if e["date"] == default), "")
        if label and label not in active[0]:
            errs.append(f"[2] 默认选中的不是 defaultExpiry：{active[0]!r} 不含 {label!r}")


def case_seller_cards(tab, errs: list[str], want: dict[str, bool]) -> None:
    print("[3] 卖方指标 14 张卡")
    if not want["seller"]:
        print("    该月无卖方指标，跳过")
        return
    n = count(tab, "[data-probe=seller-card]")
    labels = texts_of(tab, "[data-probe=seller-card] .s-label")
    print(f"    卡片={n}")
    print(f"    标签={labels}")
    if n != 14:
        errs.append(f"[3] 卖方指标卡应为 14 张，实际 {n}")
    for must in ["平值 IV", "25Δ 偏斜", "PCR 持仓", "Gamma Exp"]:
        if must not in labels:
            errs.append(f"[3] 缺少卡片：{must}")
    # 阈值文案应该真的拼上去了（note 不能只是基础说明）
    notes = texts_of(tab, "[data-probe=seller-card] .s-note")
    if not any("·" in nt for nt in notes):
        errs.append("[3] 卡片 note 里没有阈值判定文案（应形如「Put/Call 持仓量比 · 正常」）")


def case_charts(tab, errs: list[str], want: dict[str, bool]) -> None:
    """逐面板确认图表画出来了。

    不按 canvas 总数断言：echarts 6 会按 zlevel 分层建多个 canvas，
    一个图表可能对应 1~2 个，总数不是稳定契约。
    """
    print("[4] 图表 canvas 真的画出来了")
    for pid in CHART_PANELS:
        if not want[pid]:
            print(f"    {pid:9s} 面板自隐，跳过")
            continue
        sel = f'section[data-panel="{pid}"] [data-echart] canvas'
        n = count(tab, sel)
        sizes = eval_json(
            tab,
            f"Array.prototype.map.call(document.querySelectorAll('{sel}'),"
            "function(c){return [c.width, c.height];})",
        ) or []
        bad = [s for s in sizes if not s or s[0] <= 0 or s[1] <= 0]
        flag = "✓" if n >= 1 and not bad else "✗"
        print(f"    {flag} {pid:9s} canvas={n} 尺寸={sizes}")
        if n < 1:
            errs.append(f"[4] {pid} 面板没有 canvas（图表没渲染）")
        if bad:
            errs.append(f"[4] {pid} 面板有 canvas 尺寸为 0：{bad}")


def case_switch_expiry(tab, errs: list[str], payload: dict) -> None:
    print("[5] 切换到期月")
    exp = payload["expiries"]
    if len(exp) < 2:
        print("    只有一个到期月，跳过")
        return
    default = payload.get("defaultExpiry")
    other = next((e for e in exp if e["date"] != default), None)
    if not other:
        print("    找不到另一个月，跳过")
        return

    before_hint = text_of(tab, "[data-probe=hint-smile]")
    click(tab, f'[data-expiry="{other["date"]}"]')
    settle(400)
    active = texts_of(tab, "[data-probe=expiry-chip].active")
    after_hint = text_of(tab, "[data-probe=hint-smile]")
    print(f"    切到 {other['label']}；选中={active}")
    print(f"    微笑面板 hint: {before_hint!r} → {after_hint!r}")
    if len(active) != 1 or other["label"] not in active[0]:
        errs.append(f"[5] 切换后选中态不对：{active}")
    if before_hint and after_hint == before_hint:
        errs.append("[5] 切月后 hint 没变（面板可能没跟着更新）")

    # 切回去，后面的断言基于默认月
    if default:
        click(tab, f'[data-expiry="{default}"]')
        settle(400)


def case_collapse(tab, errs: list[str], want: dict[str, bool]) -> None:
    print("[6] 面板折叠/展开后图表仍正常（旧版这里漏 resize 过 3 个图表）")
    pid = next((p for p in CHART_PANELS if want[p]), None)
    if not pid:
        print("    没有可用图表面板，跳过")
        return

    sel = f'section[data-panel="{pid}"] [data-echart] canvas'
    before = eval_json(tab, f"(function(c){{return c?[c.width,c.height]:null}})(document.querySelector('{sel}'))")

    # 收起
    click(tab, f"[data-probe=panel-head-{pid}]")
    settle(300)
    hidden = eval_js(
        tab,
        f"(function(e){{return e? getComputedStyle(e).display : 'missing'}})"
        f"(document.querySelector('[data-probe=body-{pid}]'))",
    )
    toggle = text_of(tab, f'section[data-panel="{pid}"] .toggle')
    print(f"    收起后 body display={hidden!r} 箭头={toggle!r}")
    if hidden != "none":
        errs.append(f"[6] 收起后 body 应 display:none，实际 {hidden!r}")
    if toggle != "▲":
        errs.append(f"[6] 收起后箭头应为 ▲，实际 {toggle!r}")

    # 展开
    click(tab, f"[data-probe=panel-head-{pid}]")
    settle(500)
    after = eval_json(tab, f"(function(c){{return c?[c.width,c.height]:null}})(document.querySelector('{sel}'))")
    toggle2 = text_of(tab, f'section[data-panel="{pid}"] .toggle')
    print(f"    展开后 canvas {before} → {after} 箭头={toggle2!r}")
    if toggle2 != "▼":
        errs.append(f"[6] 展开后箭头应为 ▼，实际 {toggle2!r}")
    if not after or after[0] <= 0 or after[1] <= 0:
        errs.append(f"[6] 展开后 canvas 尺寸异常：{after}（resize 没生效）")


def main() -> int:
    code = sys.argv[1] if len(sys.argv) > 1 else None
    payload, target = build_payload(code)
    want = expected_panels(payload)
    print(f"  期望面板：{ {k: ('显示' if v else '自隐') for k, v in want.items()} }")

    app = QApplication([])
    errs: list[str] = []

    tab = VueTab(route="analysis")
    tab.resize(1280, 900)
    # 必须 show()：不显示时 WebEngine 视口是 0×0，图表容器宽度为 0，
    # EChart 会（正确地）跳过初始化，canvas 一个都不会有。
    tab.show()
    if not wait_loaded(tab):
        print("✗ 页面加载失败")
        return 1
    install_error_hook(tab)
    if not wait_mounted(tab):
        print("✗ Vue 没有 mount")
        return 1

    tab.render_analysis(payload)
    settle(900)  # 等 6 个面板 + 5 张图表渲染

    print()
    case_panels(tab, errs, want)
    print()
    case_expiry_chips(tab, errs, payload)
    print()
    case_seller_cards(tab, errs, want)
    print()
    case_charts(tab, errs, want)
    print()
    case_switch_expiry(tab, errs, payload)
    print()
    case_collapse(tab, errs, want)

    err = js_errors(tab)
    print()
    print(f"页面 JS 错误: {err or '无'}")
    if err:
        errs.append(f"页面有 JS 错误：{err}")

    print()
    print(f"标的现价 chip: {text_of(tab, '[data-probe=uprice]')!r}")
    print(f"meta: {text_of(tab, '[data-probe=meta]')!r}")

    dispose(tab)
    print()
    if errs:
        print("✗ 验收失败：")
        for e in errs:
            print("   -", e)
        rc = 1
    else:
        print(f"✓ 期权分析页（Vue 版）验收通过 —— {target}")
        rc = 0
    settle(200)
    app.quit()
    return rc


if __name__ == "__main__":
    finish(main())
