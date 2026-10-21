"""冒烟：行情看板（Vue 版）在真实 Qt WebEngine 里的渲染与交互.

用法：
  QT_QPA_PLATFORM=offscreen QTWEBENGINE_CHROMIUM_FLAGS="--disable-gpu --in-process-gpu" \
    PYTHONPATH=. python scripts/smoke_quote_board.py

拉真实 TDX 行情 → 走 main_window 的 _build_quotes_payload（新契约，只发事实）
→ 推给 VueTab → 回读 DOM 断言。

期望值在本脚本里**独立算一遍**（不复用前端代码），这样才能真正验证
Vue 侧的分组、涨跌、跟踪偏离算得对，而不是自证自明。
"""
from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from scripts.webengine_probe import (
    click,
    count,
    dispose,
    eval_js,
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
from watcher.fetchers.tdx import TdxFetcher
from watcher.gui.main_window import MainWindow
from watcher.gui.web.webtab import VueTab

# 造两条买卖点信号，验证徽标与组头汇总
SIG_BUY_CODE = "sh510300"
SIG_SELL_CODE = "sz159915"
#: 指数也会产生买卖点（只入库供查看、不提醒），显示在自己那一行
SIG_INDEX_CODE = "sh000300"
#: 这个指数自己没有买卖点，但组内成员 sz159915 有 —— 组头不该借用成员的
NO_SIG_INDEX_CODE = "sz399006"


class _FakeStore:
    """只实现看板 payload 用到的两个查询。"""

    def __init__(self, alerts: set[str], signals: list[dict]) -> None:
        self._alerts = alerts
        self._signals = signals

    def get_alert_codes(self) -> set[str]:
        return self._alerts

    def get_today_signals_with_ts(self, date: str, code: str | None = None) -> list[dict]:
        return self._signals


class _Board:
    """借用 MainWindow 的 payload 组装，不构造真正的主窗口。"""

    _latest_trade_signals = MainWindow._latest_trade_signals
    _build_quotes_payload = MainWindow._build_quotes_payload

    def __init__(self, cfg, store) -> None:
        self.cfg = cfg
        self.store = store


def r2(v: float) -> float:
    return round(v + 0.0, 2)


def build_payload() -> tuple[dict, dict]:
    """返回 (payload, expect)。expect 是本脚本独立算出的期望值。"""
    cfg = Config.load()
    codes = cfg.all_quote_codes()
    print(f"拉取行情：{len(codes)} 个代码（{len(cfg.watchlist)} ETF + {len(cfg.indices)} 指数）…")
    fetcher = TdxFetcher([s.model_dump() for s in cfg.tdx_servers])
    result = fetcher.fetch(codes)
    fetcher.close()
    if not result.quotes:
        raise SystemExit("✗ 行情拉取失败，无法冒烟")
    for c, q in result.quotes.items():
        if not q.name or q.name == c:
            q.name = cfg.name_for(c)
    print(f"  拿到 {len(result.quotes)} 条")

    day = "20260101"
    # signal_key 形如 resonance_long_5m_1035：方向 + 周期标签 + 时间
    signals = [
        # SIG_BUY_CODE 在 5 分档有买点、1 分档也有一条（更早），验证分列
        {"code": SIG_BUY_CODE, "signal_key": "resonance_long_5m_1035", "label": "多头共振",
         "ts": f"{day}103500", "created_at": "2026-01-01 10:35:00"},
        {"code": SIG_BUY_CODE, "signal_key": "resonance_long_1m_0942", "label": "多头共振",
         "ts": f"{day}094200", "created_at": "2026-01-01 09:42:00"},
        # SIG_SELL_CODE 在 5 分档有卖点
        {"code": SIG_SELL_CODE, "signal_key": "resonance_short_5m_1420", "label": "空头共振",
         "ts": f"{day}142000", "created_at": "2026-01-01 14:20:00"},
        # 事件类信号不该出现在买卖点列
        {"code": "sh510500", "signal_key": "surge", "label": "急涨",
         "ts": f"{day}110000", "created_at": ""},
        # 指数自己的买卖点（15 分档）：显示在指数行（组头）上
        {"code": SIG_INDEX_CODE, "signal_key": "resonance_long_15m_0940", "label": "多头共振",
         "ts": f"{day}094000", "created_at": "2026-01-01 09:40:00"},
    ]
    board = _Board(cfg, _FakeStore({SIG_BUY_CODE, "sh510050"}, signals))
    payload = board._build_quotes_payload(result.quotes)

    # ---- 独立算期望值 ----
    by_code = {q["code"]: q for q in payload["quotes"]}
    idx_codes = [i["code"] for i in payload["indices"]]

    groups: list[str] = []
    items: list[str] = []
    devs: dict[str, float] = {}
    for idx in idx_codes:
        members = [e for e, i in payload["indexMap"].items() if i == idx and e in by_code]
        if not members:
            continue
        groups.append(idx)
        iq = by_code.get(idx)
        ref = r2((iq["price"] / iq["prevClose"] - 1) * 100) if iq and iq["prevClose"] > 0 else None
        for e in members:
            items.append(e)
            q = by_code[e]
            if q["prevClose"] > 0 and ref is not None:
                devs[e] = r2(r2((q["price"] / q["prevClose"] - 1) * 100) - ref)

    expect = {
        "groups": groups,
        "items": items,
        "devs": devs,
        "byCode": by_code,
        # 同一组里重名的 ETF 应该带 (沪)/(深)
        "dupNames": _dup_names(payload, by_code, idx_codes),
    }
    print(f"  期望：{len(groups)} 组头 + {len(items)} 只 ETF")
    return payload, expect


def _dup_names(payload: dict, by_code: dict, idx_codes: list[str]) -> list[str]:
    """找出需要加市场后缀的 ETF 代码。"""
    out: list[str] = []
    for idx in idx_codes:
        members = [e for e, i in payload["indexMap"].items() if i == idx and e in by_code]
        names = [by_code[e]["name"] for e in members]
        out += [e for e in members if names.count(by_code[e]["name"]) > 1]
    return out


# ------------------------------ 各断言 ------------------------------


def case_default_collapsed(tab, errs: list[str], expect: dict) -> None:
    print("[1] 默认全部收起")
    g = count(tab, "tbody tr[data-row=group]")
    i = count(tab, "tbody tr[data-row=item]")
    btn = text_of(tab, "[data-probe=toggle-all]")
    meta = text_of(tab, "[data-probe=meta]")
    print(f"    组头={g} ETF={i} 按钮={btn!r}")
    print(f"    meta={meta!r}")
    if g != len(expect["groups"]):
        errs.append(f"[1] 组头数 {g} != {len(expect['groups'])}")
    if i != 0:
        errs.append(f"[1] 默认应收起，不该有 ETF 行，实际 {i}")
    if btn != "全部展开":
        errs.append(f"[1] 按钮文案应为「全部展开」，实际 {btn!r}")
    if f"{len(expect['groups'])} 个指数" not in meta:
        errs.append(f"[1] meta 指数数不对：{meta!r}")
    if f"{len(expect['items'])} 只 ETF" not in meta:
        errs.append(f"[1] meta ETF 数不对：{meta!r}")
    # 收起时组头应显示组内买卖点汇总
    sigs = count(tab, "tbody tr[data-row=group] .sig")
    if sigs < 1:
        errs.append("[1] 收起时组头没显示组内买卖点汇总")
    print(f"    收起时组头买卖点徽标={sigs}（避免折叠漏信号）")


def case_expand_all(tab, errs: list[str], expect: dict) -> None:
    print("[2] 全部展开")
    click(tab, "[data-probe=toggle-all]")
    settle(250)
    g = count(tab, "tbody tr[data-row=group]")
    i = count(tab, "tbody tr[data-row=item]")
    btn = text_of(tab, "[data-probe=toggle-all]")
    print(f"    组头={g} ETF={i} 按钮={btn!r}")
    if g != len(expect["groups"]):
        errs.append(f"[2] 组头数 {g} != {len(expect['groups'])}")
    if i != len(expect["items"]):
        errs.append(f"[2] ETF 行数 {i} != {len(expect['items'])}")
    if btn != "全部收起":
        errs.append(f"[2] 按钮文案应为「全部收起」，实际 {btn!r}")


def case_index_rows(tab, errs: list[str], expect: dict) -> None:
    print("[3] 指数组头行：无提醒开关 / 无偏离 / 2 位小数")
    n_group = len(expect["groups"])
    bells = count(tab, "tbody tr[data-row=group] [data-probe=bell]")
    flats = count(tab, "tbody tr[data-row=group] td.dev-flat")
    if bells != 0:
        errs.append(f"[3] 指数行不该有提醒开关，实际 {bells} 个")
    if flats != n_group:
        errs.append(f"[3] 指数行偏离应全为占位，实际 {flats}/{n_group}")

    # 取第一个指数的价格，验证 2 位小数
    code = expect["groups"][0]
    px = text_of(tab, f'tbody tr[data-code="{code}"] td:nth-child(4)')
    q = expect["byCode"].get(code)
    want = f"{q['price']:.2f}" if q else "?"
    print(f"    {code} 最新价 DOM={px!r} 期望={want!r}")
    if px != want:
        errs.append(f"[3] 指数价格小数位不对：{px!r} != {want!r}")


def case_etf_rows(tab, errs: list[str], expect: dict) -> None:
    print("[4] ETF 行：有提醒开关 / 缩进 / 3 位小数 / 跟踪偏离")
    bells = count(tab, "tbody tr[data-row=item] [data-probe=bell]")
    indents = count(tab, "tbody tr[data-row=item] td .indent")
    if bells != len(expect["items"]):
        errs.append(f"[4] ETF 提醒开关 {bells} != {len(expect['items'])}")
    if indents != len(expect["items"]):
        errs.append(f"[4] ETF 名称缩进 {indents} != {len(expect['items'])}")

    # 逐个核对最新价（3 位）与跟踪偏离
    bad_px: list[str] = []
    bad_dev: list[str] = []
    for code in expect["items"]:
        q = expect["byCode"][code]
        px = text_of(tab, f'tbody tr[data-code="{code}"] td:nth-child(4)')
        if px != f"{q['price']:.3f}":
            bad_px.append(f"{code}: {px} != {q['price']:.3f}")
        if code in expect["devs"]:
            dev = text_of(tab, f'tbody tr[data-code="{code}"] td:nth-child(8)')
            d = expect["devs"][code]
            want = ("+" if d > 0 else "") + f"{d:.2f}pp"
            if dev != want:
                bad_dev.append(f"{code}: {dev} != {want}")
    print(f"    最新价核对 {len(expect['items'])} 只，偏离核对 {len(expect['devs'])} 只")
    if bad_px:
        errs.append(f"[4] 最新价不匹配: {bad_px[:3]}")
    if bad_dev:
        errs.append(f"[4] 跟踪偏离不匹配: {bad_dev[:3]}")


def case_dup_names(tab, errs: list[str], expect: dict) -> None:
    print("[5] 同组重名 ETF 加 (沪)/(深) 后缀")
    dups = expect["dupNames"]
    if not dups:
        print("    本次数据无重名，跳过")
        return
    bad: list[str] = []
    for code in dups:
        name = text_of(tab, f'tbody tr[data-code="{code}"] td .indent')
        if "(" not in name:
            bad.append(f"{code}: {name}")
    shown = [text_of(tab, f'tbody tr[data-code="{c}"] td .indent') for c in dups[:4]]
    print(f"    重名 {len(dups)} 只，样例: {shown}")
    if bad:
        errs.append(f"[5] 重名未加后缀: {bad}")


def _sig_cell(tab, code: str, period: str) -> str:
    """读某行某周期列的文字（1m/5m/15m）。"""
    return text_of(tab, f'tbody tr[data-code="{code}"] td[data-period="{period}"]')


def case_signals(tab, errs: list[str]) -> None:
    print("[6] 三周期分列：各显示自己周期的买卖点 + 事件类被过滤")
    # 表头应有三列
    heads = count(tab, "thead th.c-sig")
    print(f"    买卖点列数={heads}（期望 3：1分/5分/15分）")
    if heads != 3:
        errs.append(f"[6] 应有 3 个周期列，实际 {heads}")

    # SIG_BUY_CODE：5 分档有买点(10:35)、1 分档有买点(09:42)、15 分档无
    b5 = _sig_cell(tab, SIG_BUY_CODE, "5m")
    b1 = _sig_cell(tab, SIG_BUY_CODE, "1m")
    b15 = _sig_cell(tab, SIG_BUY_CODE, "15m")
    print(f"    {SIG_BUY_CODE}: 1分={b1!r} 5分={b5!r} 15分={b15!r}")
    if "买" not in b1 or "09:42" not in b1:
        errs.append(f"[6] {SIG_BUY_CODE} 1分列应显示买点09:42，实际 {b1!r}")
    if "买" not in b5 or "10:35" not in b5:
        errs.append(f"[6] {SIG_BUY_CODE} 5分列应显示买点10:35，实际 {b5!r}")
    if b15.strip() not in ("", "-", "--"):
        errs.append(f"[6] {SIG_BUY_CODE} 15分列应为空，实际 {b15!r}")

    # SIG_SELL_CODE：5 分档卖点，1/15 分空
    s5 = _sig_cell(tab, SIG_SELL_CODE, "5m")
    s1 = _sig_cell(tab, SIG_SELL_CODE, "1m")
    print(f"    {SIG_SELL_CODE}: 1分={s1!r} 5分={s5!r}")
    if "卖" not in s5 or "14:20" not in s5:
        errs.append(f"[6] {SIG_SELL_CODE} 5分列应显示卖点14:20，实际 {s5!r}")
    if s1.strip() not in ("", "-", "--"):
        errs.append(f"[6] {SIG_SELL_CODE} 1分列应为空，实际 {s1!r}")

    # 指数自己的买卖点（15 分档）显示在指数行
    idx15 = _sig_cell(tab, SIG_INDEX_CODE, "15m")
    print(f"    指数 {SIG_INDEX_CODE} 15分列={idx15!r}")
    if "买" not in idx15 or "09:40" not in idx15:
        errs.append(f"[6] 指数 15分买卖点没显示在指数行: {idx15!r}")

    # 指数自己没信号、但组内成员有 → 组头三列都不该借用成员的
    borrow = "".join(_sig_cell(tab, NO_SIG_INDEX_CODE, p) for p in ("1m", "5m", "15m"))
    print(f"    无信号指数 {NO_SIG_INDEX_CODE} 三列合计={borrow!r}（组内 {SIG_SELL_CODE} 有卖点）")
    if "买" in borrow or "卖" in borrow:
        errs.append(f"[6] 指数行借用了成员 ETF 的买卖点: {borrow!r}")

    # 组内有几个成员出信号，由名称旁的角标表达
    badge = text_of(tab, f'tbody tr[data-code="{NO_SIG_INDEX_CODE}"] .gsig')
    print(f"    组内买卖点角标={badge!r}（成员里有 1 个）")
    if badge.strip() != "1":
        errs.append(f"[6] 组内买卖点角标应为 1，实际 {badge!r}")

    # 事件类（surge）不该出现在任何周期列
    ev = "".join(_sig_cell(tab, "sh510500", p) for p in ("1m", "5m", "15m"))
    if "买" in ev or "卖" in ev:
        errs.append(f"[6] 事件类信号泄漏到买卖点列: {ev!r}")


def case_single_toggle(tab, errs: list[str], expect: dict) -> None:
    print("[7] 单组折叠")
    first = expect["groups"][0]
    n_first = sum(1 for c in expect["items"] if _group_of(expect, c) == first)
    click(tab, f'tbody tr[data-code="{first}"] [data-probe=caret]')
    settle(250)
    i = count(tab, "tbody tr[data-row=item]")
    want = len(expect["items"]) - n_first
    print(f"    收起 {first}（{n_first} 只）后 ETF 行={i}，期望={want}")
    if i != want:
        errs.append(f"[7] 单组折叠后行数 {i} != {want}")


def case_redraw_keeps_fold(tab, errs: list[str], payload: dict, expect: dict) -> None:
    print("[8] 重绘不丢折叠态（模拟 5 秒轮询）")
    before = count(tab, "tbody tr[data-row=item]")
    tab.render_quotes(payload)
    settle(400)
    after = count(tab, "tbody tr[data-row=item]")
    print(f"    重绘前={before} 重绘后={after}")
    if before != after:
        errs.append(f"[8] 重绘后折叠态变了：{before} → {after}")


def case_callbacks(tab, errs: list[str], expect: dict,
                   clicks: list[tuple[str, str]], alerts: list[str]) -> None:
    print("[9] 出站回调：行点击跳 K 线 / 铃铛切提醒")
    # 上一步收起过一组，目标行可能不在 DOM 里（折叠的行不渲染）。
    # 按钮文案是「全部展开」就说明还有收起的组，先展开。
    if text_of(tab, "[data-probe=toggle-all]") == "全部展开":
        click(tab, "[data-probe=toggle-all]")
        settle(300)
    target = expect["items"][0]
    if count(tab, f'tbody tr[data-code="{target}"]') == 0:
        errs.append(f"[9] 目标行 {target} 不在 DOM 里，无法测回调")
        return

    # 点行（代码单元格，不在 data-stop 区域内）
    click(tab, f'tbody tr[data-code="{target}"] td:nth-child(3)')
    settle(250)
    print(f"    行点击回调: {clicks}")
    if not clicks:
        errs.append("[9] 没收到 row_clicked")
    elif clicks[0][0] != target:
        errs.append(f"[9] row_clicked code 不对：{clicks[0][0]} != {target}")

    # 点铃铛：应触发 alert_toggled，且不触发行点击
    n_click_before = len(clicks)
    before_bell = text_of(tab, f'tbody tr[data-code="{target}"] [data-probe=bell]')
    click(tab, f'tbody tr[data-code="{target}"] [data-probe=bell]')
    settle(250)
    after_bell = text_of(tab, f'tbody tr[data-code="{target}"] [data-probe=bell]')
    print(f"    铃铛回调: {alerts}；图标 {before_bell!r} → {after_bell!r}（乐观翻转）")
    if not alerts:
        errs.append("[9] 没收到 alert_toggled")
    elif alerts[0] != target:
        errs.append(f"[9] alert_toggled code 不对：{alerts[0]} != {target}")
    if before_bell == after_bell:
        errs.append(f"[9] 铃铛图标没有乐观翻转（仍为 {after_bell!r}）")
    if len(clicks) != n_click_before:
        errs.append("[9] 点铃铛不该同时触发行点击（data-stop 失效）")


def _group_of(expect: dict, code: str) -> str:
    return expect["groupOf"].get(code, "")


def main() -> int:
    payload, expect = build_payload()
    # 建 code → 组 的反查，供单组折叠断言用
    expect["groupOf"] = {}
    for q in payload["quotes"]:
        gi = payload["indexMap"].get(q["code"])
        if gi:
            expect["groupOf"][q["code"]] = gi

    app = QApplication(sys.argv)
    errs: list[str] = []
    clicks: list[tuple[str, str]] = []
    alerts: list[str] = []

    tab = VueTab(route="quotes")
    tab.resize(1200, 760)
    tab.row_clicked.connect(lambda c, n: clicks.append((c, n)))
    tab.alert_toggled.connect(lambda c: alerts.append(c))

    if not wait_loaded(tab):
        print("✗ 页面加载失败")
        return 1
    install_error_hook(tab)
    if not wait_mounted(tab):
        print("✗ Vue 没有 mount")
        return 1

    tab.render_quotes(payload)
    settle(500)

    print()
    case_default_collapsed(tab, errs, expect)
    print()
    case_expand_all(tab, errs, expect)
    print()
    case_index_rows(tab, errs, expect)
    print()
    case_etf_rows(tab, errs, expect)
    print()
    case_dup_names(tab, errs, expect)
    print()
    case_signals(tab, errs)
    print()
    case_single_toggle(tab, errs, expect)
    print()
    case_redraw_keeps_fold(tab, errs, payload, expect)
    print()
    case_callbacks(tab, errs, expect, clicks, alerts)

    err = js_errors(tab)
    print()
    print(f"页面 JS 错误: {err or '无'}")
    if err:
        errs.append(f"页面有 JS 错误：{err}")

    # 顺带打印一屏渲染结果，肉眼也能核一遍
    print()
    print("渲染结果（全部展开后前 8 行）：")
    for line in texts_of(tab, "tbody tr")[:8]:
        print("   ", " ".join(line.split()))

    dispose(tab)
    print()
    if errs:
        print("✗ 验收失败：")
        for e in errs:
            print("   -", e)
        rc = 1
    else:
        print("✓ 行情看板（Vue 版）验收通过")
        rc = 0
    settle(200)
    app.quit()
    return rc


if __name__ == "__main__":
    finish(main())
