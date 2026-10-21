"""冒烟：期权 T 型（Vue 版）在真实 Qt WebEngine 里的渲染与交互.

用法：
  QT_QPA_PLATFORM=offscreen QTWEBENGINE_CHROMIUM_FLAGS="--disable-gpu --in-process-gpu" \
    PYTHONPATH=. python scripts/smoke_tshape.py [标的代码]

从本地 SQLite 取真实合约与报价 → build_tshape_data → 推给 VueTab → 回读 DOM。

重点验证：
  - 已到期月份不出现在 chips 里，且默认选中落在有效月份
  - T 型行数、现价带位置、同行权价多合约堆叠
  - 指标三页切换（表头与表体同步）
  - 方向过滤切列表视图
  - 加腿 → 提交 → 指标与损益图；空篮子不提交
  - 界面上没有 AI 入口
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
from watcher.gui.main_window import MainWindow
from watcher.gui.web.webtab import VueTab
from watcher.option_meta import build_tshape_data
from watcher.state import StateStore


class _Strategy:
    """借 MainWindow 的策略计算，不构造主窗口。"""

    _strategy_chain = MainWindow._strategy_chain
    _fix_leg_ivs = staticmethod(MainWindow._fix_leg_ivs)

    def __init__(self, cfg, store) -> None:
        self.cfg = cfg
        self.store = store


def build_payload(code: str | None) -> tuple[dict, str, object]:
    cfg = Config.load()
    store = StateStore()
    unders = store.option_underlyings()
    if not unders:
        raise SystemExit("✗ 本地库里没有期权合约，先跑一次主程序攒数据")
    target = code or ("sh510300" if "sh510300" in unders else unders[0])

    contracts = store.get_option_contracts(target)
    quotes = {q["option_code"]: q for q in store.get_option_quotes(target)}
    uq = store.latest_quotes().get(target)
    payload = build_tshape_data(contracts, quotes, target, cfg.name_for(target), uq)

    exp = payload["expiries"]
    expired = [e for e in exp if e["days"] is not None and e["days"] < 0]
    print(f"标的 {target}：{len(contracts)} 合约 / {len(exp)} 个到期月"
          f"（其中已过期 {len(expired)} 个：{[e['label'] for e in expired]}）")
    print(f"  defaultExpiry={payload['defaultExpiry']}"
          f"{'（已过期，前端应跳过）' if payload['defaultExpiry'] in [e['date'] for e in expired] else ''}")
    print(f"  标的现价: {payload['underlying']['price']}")
    return payload, target, _Strategy(cfg, store)


def case_layout(tab, errs: list[str]) -> None:
    """布局健全性。

    加这条是因为踩过一次：TshapeView 的 scoped style 里有两个同名 .page
    规则块（页面根容器 + 指标分页），后者把根容器变成了两列网格且只占
    1/3 宽度，整页塌掉。而当时的断言只查 DOM 结构和数量，全都通过了。
    """
    print("[0] 布局健全性")
    root = eval_json(
        tab,
        "(function(){var e=document.querySelector('.page');if(!e)return null;"
        "var s=getComputedStyle(e), r=e.getBoundingClientRect();"
        "return {display:s.display, dir:s.flexDirection,"
        "w:Math.round(r.width), h:Math.round(r.height),"
        "vw:window.innerWidth, vh:window.innerHeight};})()",
    )
    print(f"    根容器: {root}")
    if not root:
        errs.append("[0] 找不到页面根容器 .page")
        return
    if root["display"] != "flex":
        errs.append(f"[0] 根容器 display 应为 flex，实际 {root['display']}（可能被同名 class 覆盖）")
    if root["dir"] != "column":
        errs.append(f"[0] 根容器 flex-direction 应为 column，实际 {root['dir']}")
    # 根容器应该基本铺满视口，宽度只占一小半就是塌了
    if root["w"] < root["vw"] * 0.9:
        errs.append(f"[0] 根容器宽度 {root['w']} 远小于视口 {root['vw']}（布局塌陷）")

    # 纵向顺序：到期月 chips → 表头 → 表体
    order = eval_json(
        tab,
        "(function(){var q=function(s){var e=document.querySelector(s);"
        "return e?Math.round(e.getBoundingClientRect().top):null};"
        "return {chips:q('[data-probe=expiry-bar]'), thead:q('.thead'),"
        "body:q('[data-probe=twrap]'), bar:q('[data-probe=filter-bar]')};})()",
    )
    print(f"    纵向位置(top): {order}")
    seq = [order.get(k) for k in ("chips", "thead", "body", "bar")]
    if any(v is None for v in seq):
        errs.append(f"[0] 关键区块缺失：{order}")
    elif seq != sorted(seq):
        errs.append(f"[0] 纵向顺序不对（应 chips<thead<body<filter-bar）：{order}")

    # 表头三列宽度应与表体行一致，否则列会错位
    widths = eval_json(
        tab,
        "(function(){var h=document.querySelector('.thead'),"
        "r=document.querySelector('.srow');"
        "if(!h||!r)return null;"
        "return [Math.round(h.getBoundingClientRect().width),"
        "Math.round(r.getBoundingClientRect().width)];})()",
    )
    print(f"    表头/表体行宽度: {widths}")
    if widths and abs(widths[0] - widths[1]) > 20:
        errs.append(f"[0] 表头与表体宽度不一致（列会错位）：{widths}")


def case_expiry_filter(tab, errs: list[str], payload: dict) -> None:
    print("[1] 已到期月份不显示")
    exp = payload["expiries"]
    want = [e for e in exp if e["days"] is None or e["days"] >= 0]
    expired = [e for e in exp if e["days"] is not None and e["days"] < 0]

    n = count(tab, "[data-probe=expiry-chip]")
    labels = texts_of(tab, "[data-probe=expiry-chip]")
    print(f"    chips={n}（应为未过期的 {len(want)} 个，总共 {len(exp)} 个）")
    print(f"    {labels}")
    if n != len(want):
        errs.append(f"[1] chips 数 {n} != 未过期月份数 {len(want)}")
    for e in expired:
        if any(e["label"] in t for t in labels):
            errs.append(f"[1] 已过期月份 {e['label']} 仍显示在 chips 里")

    active = texts_of(tab, "[data-probe=expiry-chip].active")
    print(f"    默认选中={active}")
    if len(active) != 1:
        errs.append(f"[1] 应恰好选中 1 个月份，实际 {len(active)}")
    else:
        for e in expired:
            if e["label"] in active[0]:
                errs.append(f"[1] 默认选中了已过期月份 {active[0]!r}")


def case_table(tab, errs: list[str], payload: dict) -> None:
    print("[2] T 型表格：行数 / 现价带 / 多合约堆叠")
    active = texts_of(tab, "[data-probe=expiry-chip].active")
    date = None
    for e in payload["expiries"]:
        if active and e["label"] in active[0]:
            date = e["date"]
            break
    rows = payload["rows"].get(date or "", [])
    n = count(tab, ".srow")
    print(f"    当前月 {date}：期望 {len(rows)} 行，DOM {n} 行")
    if n != len(rows):
        errs.append(f"[2] 行数 {n} != {len(rows)}")

    strip = count(tab, "[data-probe=strip]")
    strip_txt = text_of(tab, "[data-probe=strip]")
    spot = payload["underlying"]["price"]
    print(f"    现价带={strip} 个，内容={strip_txt!r}")
    if spot is not None and strip != 1:
        errs.append(f"[2] 有现价时应恰好一条现价带，实际 {strip}")
    if spot is not None and f"{spot:.3f}" not in strip_txt:
        errs.append(f"[2] 现价带没显示现价 {spot:.3f}：{strip_txt!r}")

    # 同行权价多合约（带 A 的调整合约）应垂直堆叠成多个 cblock
    multi = [r for r in rows if max(len(r["calls"]), len(r["puts"])) > 1]
    if multi:
        k = multi[0]["strike"]
        got = count(tab, f'.srow[data-strike="{k}"] .side.call .cblock')
        want = max(len(multi[0]["calls"]), len(multi[0]["puts"]))
        print(f"    行权价 {k} 有 {want} 个合约，DOM 堆叠 {got} 块")
        if got != want:
            errs.append(f"[2] 多合约堆叠 {got} != {want}")
    else:
        print("    本次数据没有同行权价多合约，跳过堆叠检查")


def case_metrics(tab, errs: list[str]) -> None:
    """指标区：代码 + 6 个指标一屏铺开，不再横向分页，表头与数据列对齐。"""
    print("[3] 指标区一屏（代码 + 6 项）+ 表头对齐")

    stale = eval_js(
        tab,
        "document.querySelectorAll('.colscroll,.cinner,.mpage,"
        "[data-probe=pg-left],[data-probe=pg-right]').length",
    )
    print(f"    旧横滑/分页元素残留={int(stale or 0)}")
    if int(stale or 0):
        errs.append(f"[3] 还有 {int(stale)} 个旧横滑/分页元素")

    m = eval_json(
        tab,
        "(function(){var cb=document.querySelector('.srow .side.call .cblock');"
        "if(!cb)return null;var mt=cb.querySelector('.metrics');"
        "var rows=cb.querySelectorAll('.metrics .mrow');"
        "return {cols:cb.querySelectorAll('.metrics .cell').length,rows:rows.length,"
        "texts:Array.prototype.map.call(rows,function(r){"
        "return r.textContent.replace(/\\s+/g,' ').trim();}),"
        "overflow: mt.scrollWidth > mt.clientWidth+1};})()",
    )
    if not m:
        errs.append("[3] 找不到合约块")
        return
    print(f"    列数={m['cols']} 指标行数={m['rows']} 溢出={m['overflow']}")
    print(f"    指标内容={m['texts']}")
    if m["cols"] != 4:
        errs.append(f"[3] 指标应 4 列（代码+3组），实际 {m['cols']}")
    if m["rows"] != 8:
        errs.append(f"[3] 指标应 8 行（4列×2行），实际 {m['rows']}")
    if m["overflow"]:
        errs.append("[3] 指标区溢出，说明还需要横向滚动")
    for kw in ("卖", "买", "量", "持", "IV", "Δ"):
        if not any(kw in t for t in m["texts"]):
            errs.append(f"[3] 缺少指标 {kw}")
    # 合约代码：8 位数字，下单要抄到别的软件
    import re as _re
    if not any(_re.search(r"\d{8}", t) for t in m["texts"]):
        errs.append(f"[3] 指标区没显示 8 位合约代码：{m['texts']}")

    # 退化 IV 不展示：深度实值合约上数据源的 IV 求解器会返回触底值（0.0009），
    # 显示成 0.1% 会被误读成波动率极低，应该留空
    ivs = eval_json(
        tab,
        "(function(){var out=[];"
        "document.querySelectorAll('.srow .cblock .metrics .mrow').forEach(function(r){"
        "var l=r.querySelector('.lbl'), n=r.querySelector('.num');"
        "if(l&&l.textContent.trim()==='IV'&&n) out.push(n.textContent.trim());});"
        "return out;})()",
    ) or []
    tiny = [x for x in ivs if x.endswith("%") and float(x[:-1]) < 1.0]
    blank = [x for x in ivs if x == "--"]
    print(f"    IV 单元 {len(ivs)} 个：留空 {len(blank)} 个，仍显示 <1% 的 {len(tiny)} 个")
    if tiny:
        errs.append(f"[3] 退化 IV 没隐藏，仍显示 {tiny[:5]}")

    # 表头在滚动容器外，靠 --tshape-sbw 补偿滚动条宽度才能和数据对齐
    sbw = eval_js(
        tab,
        "getComputedStyle(document.documentElement).getPropertyValue('--tshape-sbw')",
    )
    print(f"    滚动条补偿 --tshape-sbw={str(sbw).strip()!r}")
    for side in ("call", "put"):
        pairs = eval_json(
            tab,
            f"(function(){{var hs=document.querySelectorAll("
            f"'.thead .{side}-head .hmetrics .hcell');"
            f"var ds=document.querySelectorAll("
            f"'.srow .side.{side} .cblock .metrics .cell');"
            "if(!hs.length||!ds.length)return null;var o=[];"
            "for(var i=0;i<Math.min(hs.length,ds.length);i++)"
            "o.push([Math.round(hs[i].getBoundingClientRect().left),"
            "Math.round(ds[i].getBoundingClientRect().left)]);return o;})()",
        )
        if not pairs:
            errs.append(f"[3] {side} 拿不到列位置")
            continue
        desc = "  ".join(
            f"{i + 1}:{h}/{d}{'✓' if abs(h - d) <= 1 else '✗'}"
            for i, (h, d) in enumerate(pairs)
        )
        print(f"    {side.upper():4s} 表头x/数据x  {desc}")
        for i, (h, d) in enumerate(pairs):
            if abs(h - d) > 1:
                errs.append(f"[3] {side} 第{i + 1}列表头与数据错位（{h} vs {d}）")


def case_filter(tab, errs: list[str]) -> None:
    print("[4] 方向过滤：单方向切列表视图")
    click(tab, '[data-filter-btn="call"]')
    settle(400)
    listv = count(tab, "[data-probe=list-view]")
    tw = count(tab, "[data-probe=twrap]")
    cols = count(tab, "[data-probe=list-view] thead th")
    heads = eval_json(
        tab,
        "Array.prototype.map.call(document.querySelectorAll("
        "'[data-probe=list-view] thead th'),function(t){return t.textContent.trim()})",
    ) or []
    print(f"    CALL：列表视图={listv} T型={tw} 列数={cols}")
    print(f"    列表表头={heads}")
    if listv != 1:
        errs.append("[4] 切 CALL 后没出现列表视图")
    if tw != 0:
        errs.append("[4] 切 CALL 后 T 型表体应隐藏")
    # 列表视图与 T 型视图口径一致：
    # 行权价/合约代码/最新价/涨跌幅/卖一/买一/量/持仓/IV/Delta/加腿
    if cols != 11:
        errs.append(f"[4] 列表视图应 11 列，实际 {cols}")
    for kw in ("合约代码", "量", "持仓", "IV", "Delta"):
        if not any(kw in h for h in heads):
            errs.append(f"[4] 列表视图表头缺少 {kw}")

    click(tab, '[data-filter-btn="all"]')
    settle(400)
    print(f"    回到全部：T型={count(tab, '[data-probe=twrap]')}")
    if count(tab, "[data-probe=twrap]") != 1:
        errs.append("[4] 回到全部后 T 型表体没恢复")


def case_basket(tab, errs: list[str], payload: dict, reqs: list[str]) -> None:
    print("[5] 加腿 → 提交 → 指标与损益图")
    n_before = len(reqs)
    click(tab, "[data-probe=add-buy]")
    settle(500)
    legs = count(tab, "[data-probe=basket-leg]")
    cnt = text_of(tab, "[data-probe=strat-cnt]")
    print(f"    加一腿后：篮子={legs} 摘要={cnt!r} 新增请求={len(reqs) - n_before}")
    if legs != 1:
        errs.append(f"[5] 篮子应有 1 条腿，实际 {legs}")
    if len(reqs) <= n_before:
        errs.append("[5] 加腿没触发 requestStrategy")
    if "1 条腿" not in cnt:
        errs.append(f"[5] 摘要不对：{cnt!r}")


def case_strategy_result(tab, errs: list[str]) -> None:
    print("[6] 策略计算结果：8 个指标 + 损益图")
    ms = count(tab, "[data-probe=metrics] .m")
    labels = texts_of(tab, "[data-probe=metrics] .m .k")
    canvas = count(tab, "[data-probe=payoff] canvas")
    print(f"    指标={ms} 标签={labels}")
    print(f"    损益图 canvas={canvas}")
    if ms != 8:
        errs.append(f"[6] 指标应 8 个，实际 {ms}")
    for must in ["净成本", "最大盈利", "最大亏损", "盈亏平衡", "风险报酬比"]:
        if must not in labels:
            errs.append(f"[6] 缺少指标：{must}")
    if canvas < 1:
        errs.append("[6] 损益图没渲染")


def case_presets(tab, errs: list[str], reqs: list[str]) -> None:
    print("[7] 预设按钮")
    n = count(tab, "[data-probe=preset-bar] .prebtn")
    labels = texts_of(tab, "[data-probe=preset-bar] .prebtn")
    print(f"    预设={n} {labels}")
    if n != 7:
        errs.append(f"[7] 预设应 7 个，实际 {n}")

    before = len(reqs)
    click(tab, '[data-preset="long_call"]')
    settle(600)
    legs = count(tab, "[data-probe=basket-leg]")
    print(f"    点「买入认购」后：篮子={legs} 新增请求={len(reqs) - before}")
    if len(reqs) <= before:
        errs.append("[7] 点预设没触发 requestStrategy")
    if legs < 1:
        errs.append("[7] 预设没把腿填进篮子")


def case_no_ai(tab, errs: list[str]) -> None:
    print("[8] 界面上没有 AI 入口")
    hits = eval_js(
        tab,
        "(document.body.innerText.match(/AI/g)||[]).length",
    )
    probes = count(tab, "[data-probe=ai-panel], [data-probe=ai-go], [data-probe=ai-result]")
    print(f"    正文出现 'AI' 次数={hits} AI 相关探针={probes}")
    if int(hits or 0) != 0:
        errs.append(f"[8] 界面仍出现 AI 字样（{hits} 处）")
    if probes != 0:
        errs.append(f"[8] 仍存在 AI 相关元素（{probes} 个）")


def case_copy_code(tab, errs: list[str]) -> None:
    """点合约代码 → 走 Qt 剪贴板，并在表头给出「已复制」反馈。"""
    from PySide6.QtGui import QGuiApplication

    print("[9] 点合约代码复制到系统剪贴板")
    clip = QGuiApplication.clipboard()
    clip.setText("__before__")

    shown = eval_js(tab, "(function(){var e=document.querySelector('[data-probe=ocode]');"
                         "return e?e.textContent.trim():'';})()")
    print(f"    DOM 里第一个代码={shown!r}")
    if not (shown and str(shown).strip().isdigit()):
        errs.append(f"[9] 没找到合约代码元素：{shown!r}")
        return

    click(tab, "[data-probe=ocode]")
    settle(400)
    got = clip.text()
    tip = text_of(tab, "[data-probe=copied]")
    print(f"    剪贴板={got!r}  界面提示={tip!r}")
    if got != str(shown).strip():
        errs.append(f"[9] 剪贴板内容应为 {shown!r}，实际 {got!r}")
    if str(shown).strip() not in tip:
        errs.append(f"[9] 没有「已复制」反馈：{tip!r}")

    # 点代码不该顺带触发「看 K 线」（那是整行的点击行为）
    print("    （点代码不应触发看 K 线，由 main 里的 opened 列表核对）")


def case_underlying_chart(tab, errs: list[str], opened: list, code: str) -> None:
    """点表头的标的价格 → 看这个 ETF 自己的 K 线；「回到现价」只滚动不跳转。"""
    print("[10] 点标的价格看 ETF K 线 / 「回到现价」只滚动")

    tip = eval_js(
        tab,
        "(function(){var e=document.querySelector('[data-probe=uprice]');"
        "return e?e.getAttribute('title'):'';})()",
    )
    n0 = len(opened)
    click(tab, "[data-probe=uprice]")
    settle(400)
    got = opened[-1] if len(opened) > n0 else None
    print(f"    chip={text_of(tab, '[data-probe=uprice]')!r} 提示={tip!r}")
    print(f"    → Python 收到 {got}")
    if got is None or got[0] != code:
        errs.append(f"[10] 点标的价格应回传 ({code}, ...)，实际 {got}")
    if "K 线" not in str(tip):
        errs.append(f"[10] 标的价格的提示文案没更新：{tip!r}")

    # 「回到现价」是另一个功能，不该跟着跳 K 线
    n1 = len(opened)
    click(tab, "[data-probe=locate]")
    settle(450)
    if len(opened) > n1:
        errs.append(f"[10] 点「回到现价」不该跳 K 线，却收到 {opened[-1]}")
    else:
        print("    点「回到现价」：未触发跳转 ✓")


def case_empty_basket_no_submit(tab, errs: list[str], payload: dict, reqs: list[str]) -> None:
    print("[11] 空篮子时行情刷新不重复提交策略计算")
    click(tab, "[data-probe=strat-clear]")
    settle(500)
    n0 = len(reqs)
    # 模拟两轮行情刷新
    tab.render_tshape(payload)
    settle(400)
    tab.render_tshape(payload)
    settle(400)
    added = len(reqs) - n0
    legs = count(tab, "[data-probe=basket-leg]")
    print(f"    清空后篮子={legs}，两轮刷新新增请求={added}（应为 0）")
    if legs != 0:
        errs.append(f"[11] 清空后篮子应为空，实际 {legs}")
    if added != 0:
        errs.append(f"[11] 空篮子刷新仍提交了 {added} 次策略计算（旧版行为）")


def main() -> int:
    code = sys.argv[1] if len(sys.argv) > 1 else None
    payload, target, calc = build_payload(code)

    app = QApplication([])
    errs: list[str] = []
    opened: list[tuple[str, str]] = []
    reqs: list[str] = []

    tab = VueTab(route="tshape")
    tab.resize(1500, 1000)
    tab.show()  # 不 show 视口是 0×0，损益图容器没宽度
    tab.row_clicked.connect(lambda c, n: opened.append((c, n)))

    # 把策略请求真正算出来回推，才能验证指标与损益图
    def on_strategy(js: str) -> None:
        reqs.append(js)
        _reply_strategy(tab, calc, js)

    tab.strategy_requested.connect(on_strategy)

    if not wait_loaded(tab):
        print("✗ 页面加载失败")
        return 1
    install_error_hook(tab)
    if not wait_mounted(tab):
        print("✗ Vue 没有 mount")
        return 1

    tab.render_tshape(payload)
    settle(900)

    print()
    case_layout(tab, errs)
    print()
    case_expiry_filter(tab, errs, payload)
    print()
    case_table(tab, errs, payload)
    print()
    case_metrics(tab, errs)
    print()
    case_filter(tab, errs)
    print()
    case_basket(tab, errs, payload, reqs)
    print()
    case_strategy_result(tab, errs)
    print()
    case_presets(tab, errs, reqs)
    print()
    case_no_ai(tab, errs)
    print()
    # 复制要在「点合约跳 K 线」之前验：这样能顺带确认点代码没触发跳转
    before_open = len(opened)
    case_copy_code(tab, errs)
    if len(opened) > before_open:
        errs.append(f"[9] 点代码不该触发看 K 线，却收到 {opened[before_open:]}")
    print()
    case_underlying_chart(tab, errs, opened, target)
    print()
    case_empty_basket_no_submit(tab, errs, payload, reqs)

    print()
    # 点合约应跳 K 线
    n0 = len(opened)
    click(tab, ".cblock")
    settle(250)
    got = opened[n0:]
    print(f"[12] 点合约跳 K 线回调: {got[:1]}")
    if not got:
        errs.append("[12] 点合约没收到 row_clicked")
    elif not (got[0][0].isdigit() and len(got[0][0]) == 8):
        errs.append(f"[12] 点合约应回传 8 位期权代码，实际 {got[0]}")

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
        print(f"✓ 期权 T 型（Vue 版）验收通过 —— {target}")
        rc = 0
    settle(200)
    app.quit()
    return rc


def _reply_strategy(tab, calc, payload_json: str) -> None:
    """复刻 main_window._on_strategy_requested 的核心，把结果回推给页面。"""
    import json as _json

    from watcher.strategy import (
        PRESETS,
        Leg,
        build_preset,
        combo_greeks,
        decay_schedule,
        payoff_curve,
        summarize,
    )
    from watcher.strategy.pricing import days_to_expiry

    req = _json.loads(payload_json or "{}")
    preset_list = [{"key": k, "label": v[0], "desc": v[1]} for k, v in PRESETS.items()]
    underlying = req.get("underlying") or ""
    if not underlying:
        tab.render_strategy({"error": "请先在左侧选择标的", "presets": preset_list})
        return

    chain, spot = calc._strategy_chain(underlying)
    by_code = {c["code"]: c for c in chain}
    if spot <= 0:
        tab.render_strategy({"error": "暂无标的行情，无法计算", "presets": preset_list})
        return

    preset = req.get("preset")
    if preset:
        legs = build_preset(preset, chain, spot, qty=1, expiry=req.get("expiry"))
        if not legs:
            tab.render_strategy({
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
            px = float(item.get("price") or 0) or float(src["price"]) or 0.0
            if px <= 0:
                continue
            legs.append(Leg(
                option_code=src["code"], option_type=src["option_type"],
                strike=float(src["strike"]),
                side="sell" if item.get("side") == "sell" else "buy",
                price=px, qty=max(1, int(item.get("qty") or 1)),
                expire_date=src["expire_date"], iv=float(src["iv"]) or 0.0,
                name=src["name"],
            ))

    if not legs:
        tab.render_strategy({"empty": True, "spot": spot, "presets": preset_list})
        return

    calc._fix_leg_ivs(legs, spot)
    tab.render_strategy({
        "underlying": underlying,
        "underlyingName": calc.cfg.name_for(underlying),
        "spot": spot,
        "legs": [{
            "code": l.option_code, "name": l.name, "type": l.option_type,
            "strike": l.strike, "side": l.side, "price": l.price, "qty": l.qty,
            "iv": l.iv, "expire": l.expire_date,
            "days": days_to_expiry(l.expire_date), "cost": l.cost,
        } for l in legs],
        "summary": summarize(legs, spot).as_dict(),
        "greeks": combo_greeks(legs, spot),
        "decay": decay_schedule(legs, spot, horizons=(1, 3, 7)),
        "curve": [{"s": round(s, 4), "p": round(p, 2)}
                  for s, p in payoff_curve(legs, spot, points=161)],
        "presets": preset_list,
    })


if __name__ == "__main__":
    finish(main())
