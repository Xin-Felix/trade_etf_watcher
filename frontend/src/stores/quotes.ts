/**
 * 行情看板状态。
 *
 * Python 只发原始快照（QuotesPayload），这里负责所有展示决策：
 * 按跟踪指数分组、算涨跌与跟踪偏离、同组重名去歧义、折叠状态。
 * 逻辑等价于迁移前 main_window.py 的 _build_quote_rows / _quote_row，
 * 数值口径也刻意保持一致（见 devOf 的注释）。
 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import type { PeriodSignals, QuotesPayload, RawQuote } from '@/bridge/types'

/** 「其他」组（未配置跟踪指数的标的）的折叠键。 */
export const OTHER_GROUP = '_other_'

export type RowKind = 'group' | 'item'

/** 看板上的一行。group = 指数组头，item = ETF。 */
export interface DisplayRow {
  kind: RowKind
  /** 组头是指数代码；「其他」组头为空串（不可点击） */
  code: string
  /** 折叠键：所属指数代码，或 OTHER_GROUP */
  groupKey: string
  /** 展示名，同组重名时带 (沪)/(深) */
  name: string
  /** 原始名，回传 onRowClicked 用 */
  rawName: string
  /** 小数位：指数 2、ETF 3 */
  digits: number
  price: number | null
  chgAmt: number | null
  changePct: number | null
  open: number | null
  /** 跟踪偏离（百分点）；组头为 null */
  dev: number | null
  /** null = 指数行，不显示提醒开关 */
  alert: boolean | null
  /** 三个周期各自的最新买卖点（1m/5m/15m 分列展示） */
  signals: PeriodSignals
  /** 仅组头：组内 ETF 数 */
  count: number
  /** 仅组头：组内买卖点数 */
  sigCount: number
}

function round2(v: number): number {
  return Math.round(v * 100) / 100
}

function changePctOf(q: RawQuote | undefined): number | null {
  if (!q || !(q.prevClose > 0)) return null
  return round2((q.price / q.prevClose - 1) * 100)
}

function chgAmtOf(q: RawQuote | undefined): number | null {
  if (!q || !(q.prevClose > 0)) return null
  return q.price - q.prevClose
}

/** sh→沪 / sz→深，用于同组重名去歧义。 */
function marketLabel(code: string): string {
  if (code.startsWith('sh')) return '沪'
  if (code.startsWith('sz')) return '深'
  return ''
}

export const useQuotesStore = defineStore('quotes', () => {
  const payload = ref<QuotesPayload | null>(null)
  /** 已收起的分组键。默认全收起（全展开太花），且跨轮询重绘保持。 */
  const collapsed = ref<Set<string>>(new Set())
  /** 是否已经用首帧数据初始化过折叠状态 */
  const foldInited = ref(false)
  const updatedAt = ref(0)

  /* ------------------------- 派生数据 ------------------------- */

  const byCode = computed<Map<string, RawQuote>>(() => {
    const m = new Map<string, RawQuote>()
    for (const q of payload.value?.quotes ?? []) m.set(q.code, q)
    return m
  })

  const indexCodes = computed<Set<string>>(
    () => new Set((payload.value?.indices ?? []).map((i) => i.code)),
  )

  /** 提醒状态。alertCodes 为空 = 全部提醒（沿用 DB 语义）。 */
  function alertOf(code: string): boolean {
    const list = payload.value?.alertCodes ?? []
    return list.length === 0 ? true : list.includes(code)
  }

  function signalsOf(code: string): PeriodSignals {
    return payload.value?.signals?.[code] ?? {}
  }

  /** 该 code 是否在任一周期出过买卖点（给组头角标计数用）。 */
  function hasAnySignal(code: string): boolean {
    const s = payload.value?.signals?.[code]
    return !!s && (!!s['1m'] || !!s['5m'] || !!s['15m'])
  }

  /**
   * 跟踪偏离 = ETF 涨跌幅 − 指数涨跌幅（百分点）。
   * 刻意沿用迁移前的算法：两边各自先 round 到 2 位再相减，
   * 否则会和旧版差 0.01，验收对不上。
   */
  function devOf(etfChange: number | null, refChange: number | null): number | null {
    if (etfChange === null || refChange === null) return null
    return round2(etfChange - refChange)
  }

  function itemRow(code: string, groupKey: string, nameOverride: string,
                   refChange: number | null): DisplayRow {
    const q = byCode.value.get(code)!
    const changePct = changePctOf(q)
    return {
      kind: 'item',
      code,
      groupKey,
      name: nameOverride || q.name,
      rawName: q.name,
      digits: 3,
      price: q.price,
      chgAmt: chgAmtOf(q),
      changePct,
      open: q.open,
      dev: devOf(changePct, refChange),
      alert: alertOf(code),
      signals: signalsOf(code),
      count: 0,
      sigCount: 0,
    }
  }

  /**
   * 看板行（已按分组展开，不含被折叠的成员）。
   * 与旧版一致的几个边界：组内 ETF 全无行情则整组不显示；
   * 指数快照没拉到仍占一行组头（保持结构稳定）；孤立指数不单独成行。
   */
  const rows = computed<DisplayRow[]>(() => {
    const p = payload.value
    if (!p) return []

    const out: DisplayRow[] = []
    const covered = new Set<string>()
    // payload.quotes 的下标 = Python 按 all_quote_codes 发的顺序，
    // 用它给组内成员排序，结果与旧版按 watchlist 顺序一致
    const order = new Map(p.quotes.map((q, i) => [q.code, i]))
    const orderOf = (c: string) => order.get(c) ?? Number.MAX_SAFE_INTEGER

    for (const idx of p.indices) {
      const members = Object.entries(p.indexMap)
        .filter(([etf, index]) => index === idx.code && byCode.value.has(etf))
        .map(([etf]) => etf)
        .sort((a, b) => orderOf(a) - orderOf(b))
      if (members.length === 0) continue

      const iq = byCode.value.get(idx.code)
      const refChange = changePctOf(iq)
      // 组头行的每一列都是指数自己的（价格/涨跌/今开），买卖点也用指数自己的，
      // 免得一列显示成员 ETF 的信号、旁边几列却是指数的数据，看着对不上。
      // 「组内有几个成员出了买卖点」由 sigCount 那个角标表达。
      const groupSignals = signalsOf(idx.code)

      out.push({
        kind: 'group',
        code: idx.code,
        groupKey: idx.code,
        name: idx.name,
        rawName: idx.name,
        digits: 2,
        price: iq ? iq.price : null,
        chgAmt: chgAmtOf(iq),
        changePct: refChange,
        open: iq ? iq.open : null,
        dev: null,
        alert: null,
        signals: groupSignals,
        count: members.length,
        sigCount: members.filter(hasAnySignal).length,
      })
      if (iq) covered.add(idx.code)

      // 同组重名（如两只「沪深300ETF」）加沪/深后缀
      const names = members.map((c) => byCode.value.get(c)!.name)
      for (const c of members) {
        const q = byCode.value.get(c)!
        const dup = names.filter((n) => n === q.name).length > 1
        out.push(itemRow(c, idx.code, dup ? `${q.name}(${marketLabel(c)})` : '', refChange))
        covered.add(c)
      }
    }

    // 未映射到指数的标的；孤立指数跳过，避免出现没有组的指数行
    const rest = (p.quotes ?? [])
      .map((q) => q.code)
      .filter((c) => !covered.has(c) && !indexCodes.value.has(c))
    if (rest.length > 0) {
      out.push({
        kind: 'group',
        code: '',
        groupKey: OTHER_GROUP,
        name: '其他',
        rawName: '',
        digits: 2,
        price: null,
        chgAmt: null,
        changePct: null,
        open: null,
        dev: null,
        alert: null,
        signals: {},   // 「其他」组头无对应指数，不显示汇总买卖点
        count: rest.length,
        sigCount: rest.filter(hasAnySignal).length,
      })
      for (const c of rest) out.push(itemRow(c, OTHER_GROUP, '', null))
    }

    return out
  })

  /** 实际渲染的行：折叠组的成员被过滤掉。 */
  const visibleRows = computed<DisplayRow[]>(() =>
    rows.value.filter((r) => r.kind === 'group' || !collapsed.value.has(r.groupKey)),
  )

  const groupKeys = computed<string[]>(() =>
    rows.value.filter((r) => r.kind === 'group').map((r) => r.groupKey),
  )

  const stats = computed(() => {
    const items = rows.value.filter((r) => r.kind === 'item')
    return {
      groups: groupKeys.value.length,
      items: items.length,
      signals: items.filter(
        (r) => r.signals['1m'] || r.signals['5m'] || r.signals['15m'],
      ).length,
    }
  })

  const meta = computed(() => {
    const s = stats.value
    const parts = [`${s.groups} 个指数`, `${s.items} 只 ETF`]
    if (s.signals) parts.push(`${s.signals} 个买卖点`)
    parts.push('点组名展开/收起，点标的看 K 线')
    return parts.join(' · ')
  })

  /**
   * 是否存在收起的组。
   *
   * 「全部展开/全部收起」按钮的文案和 toggleAll 的行为**必须用同一个条件**，
   * 否则会出现按钮写着「全部收起」、点下去却全部展开的错位
   * （toggleAll 是「只要有收起的就全部展开」）。
   */
  const hasCollapsed = computed(() => collapsed.value.size > 0)

  /* --------------------------- 动作 --------------------------- */

  function apply(p: QuotesPayload): void {
    payload.value = p
    updatedAt.value = Date.now()
    // 首帧默认全部收起
    if (!foldInited.value && groupKeys.value.length > 0) {
      collapsed.value = new Set(groupKeys.value)
      foldInited.value = true
    }
  }

  function toggleGroup(key: string): void {
    // 用替换而不是 mutate：对 Set 的增删响应式行为在不同版本下不一致，替换最稳
    const next = new Set(collapsed.value)
    if (next.has(key)) next.delete(key)
    else next.add(key)
    collapsed.value = next
  }

  function toggleAll(): void {
    collapsed.value = collapsed.value.size > 0 ? new Set() : new Set(groupKeys.value)
  }

  function isCollapsed(key: string): boolean {
    return collapsed.value.has(key)
  }

  /** 本地乐观翻转提醒状态，不等 Python 回执（下一轮推送会用 DB 值覆盖）。 */
  function optimisticToggleAlert(code: string): void {
    const p = payload.value
    if (!p) return
    const cur = new Set(p.alertCodes.length === 0 ? allItemCodes(p) : p.alertCodes)
    if (cur.has(code)) cur.delete(code)
    else cur.add(code)
    p.alertCodes = [...cur]
  }

  return {
    payload,
    collapsed,
    updatedAt,
    rows,
    visibleRows,
    groupKeys,
    stats,
    meta,
    hasCollapsed,
    apply,
    toggleGroup,
    toggleAll,
    isCollapsed,
    optimisticToggleAlert,
  }
})

/** 「空 alertCodes = 全部提醒」展开成显式集合，供乐观翻转用。 */
function allItemCodes(p: QuotesPayload): string[] {
  const idx = new Set(p.indices.map((i) => i.code))
  return p.quotes.map((q) => q.code).filter((c) => !idx.has(c))
}
