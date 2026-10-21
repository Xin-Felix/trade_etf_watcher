/**
 * 期权分析页状态。
 *
 * payload 直接是 Python 侧 option_meta.build_tshape_data 的产物（契约不变，
 * 那 363 行数学不动）。这里只做展示层的事：选到期月、面板折叠、
 * 判断每个面板有没有数据、以及多月对比需要的行权价对齐。
 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import type { AnalysisPayload, ExpiryItem } from '@/bridge/types'

/** 六个面板的标识，也是折叠状态的键。 */
export const PANELS = ['seller', 'smile', 'oi', 'smileAll', 'surface', 'term'] as const
export type PanelId = (typeof PANELS)[number]

export const PANEL_TITLES: Record<PanelId, string> = {
  seller: '卖方指标',
  smile: '波动率微笑',
  oi: '持仓量分布',
  smileAll: '波动率微笑（多月对比）',
  surface: '波动率曲面',
  term: '平值 IV 期限结构',
}

/** 多月对比的调色板（7 色轮转，与旧版一致）。 */
export const SMILE_COLORS = [
  '#26a69a',
  '#ef5350',
  '#ff9800',
  '#42a5f5',
  '#ab47bc',
  '#8d6e63',
  '#78909c',
]

export interface SmileAllSeries {
  name: string
  color: string
  /** 已按全局行权价并集对齐，缺失补 null */
  data: Array<number | null>
}

export const useAnalysisStore = defineStore('analysis', () => {
  const payload = ref<AnalysisPayload | null>(null)
  /** 当前选中的到期月（前端状态，切换不回 Python） */
  const expiry = ref<string | null>(null)
  /** 收起的面板。分析页默认全展开——这些图本来就是要看的 */
  const collapsed = ref<Set<PanelId>>(new Set())

  function apply(p: AnalysisPayload): void {
    payload.value = p
    // 只有当前选择失效时才回落，这样行情刷新不会把用户切的月份重置
    const list = p.expiries ?? []
    if (!list.some((e) => e.date === expiry.value)) {
      expiry.value = p.defaultExpiry ?? list[0]?.date ?? null
    }
  }

  function selectExpiry(date: string): void {
    expiry.value = date
  }

  function togglePanel(id: PanelId): void {
    const next = new Set(collapsed.value)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    collapsed.value = next
  }

  function isCollapsed(id: PanelId): boolean {
    return collapsed.value.has(id)
  }

  /* ------------------------- 基础派生 ------------------------- */

  const underlying = computed(() => payload.value?.underlying ?? null)
  const meta = computed(() => payload.value?.meta ?? '')
  const expiries = computed<ExpiryItem[]>(() => payload.value?.expiries ?? [])
  const hasExpiries = computed(() => expiries.value.length > 0)
  const spot = computed(() => underlying.value?.price ?? null)

  const currentExpiryItem = computed<ExpiryItem | null>(
    () => expiries.value.find((e) => e.date === expiry.value) ?? null,
  )

  /* ------------------------- 各面板数据 ------------------------- */

  const seller = computed(() =>
    expiry.value ? (payload.value?.seller?.[expiry.value] ?? null) : null,
  )

  const smile = computed(() =>
    expiry.value ? (payload.value?.smile?.[expiry.value] ?? null) : null,
  )

  const oi = computed(() => (expiry.value ? (payload.value?.oi?.[expiry.value] ?? null) : null))

  const ivTerm = computed(() => payload.value?.ivTerm ?? [])
  const surface = computed(() => payload.value?.surface ?? null)

  /**
   * 多月微笑对比：取所有有数据的月，按全局行权价并集对齐。
   * 每月的值 = Call/Put 平均 IV（只有一边就用那一边），与旧版算法一致。
   */
  const smileAll = computed<{ strikes: number[]; series: SmileAllSeries[] }>(() => {
    const p = payload.value
    if (!p?.smile) return { strikes: [], series: [] }

    const valid = expiries.value.filter((e) => (p.smile[e.date]?.strikes?.length ?? 0) > 0)
    if (valid.length < 2) return { strikes: [], series: [] }

    const all = new Set<number>()
    for (const e of valid) for (const s of p.smile[e.date]!.strikes) all.add(s)
    const strikes = [...all].sort((a, b) => a - b)

    const series = valid.map((e, i) => {
      const sm = p.smile[e.date]!
      const ivByStrike = new Map<number, number>()
      sm.strikes.forEach((k, j) => {
        const c = sm.callIV[j]
        const put = sm.putIV[j]
        if (c !== null && c !== undefined && put !== null && put !== undefined) {
          ivByStrike.set(k, (c + put) / 2)
        } else if (c !== null && c !== undefined) {
          ivByStrike.set(k, c)
        } else if (put !== null && put !== undefined) {
          ivByStrike.set(k, put)
        }
      })
      return {
        name: `${e.label}(${e.days ?? ''}天)`,
        color: SMILE_COLORS[i % SMILE_COLORS.length]!,
        data: strikes.map((k) => ivByStrike.get(k) ?? null),
      }
    })

    return { strikes, series }
  })

  /* ----------------------- 面板可用性判定 ----------------------- */
  /* 与旧版一致：数据缺失的面板整块自隐，而不是显示空图 */

  const available = computed<Record<PanelId, boolean>>(() => {
    const sm = smile.value
    const o = oi.value
    const sf = surface.value
    return {
      seller: seller.value !== null,
      smile: (sm?.strikes?.length ?? 0) > 0,
      // 全 0 持仓（比如新挂月份）也算没数据
      oi:
        (o?.strikes?.length ?? 0) > 0 &&
        (Math.max(0, ...(o?.callOI ?? [])) > 0 || Math.max(0, ...(o?.putOI ?? [])) > 0),
      smileAll: smileAll.value.series.length >= 2,
      surface:
        !!sf &&
        (sf.strikes?.length ?? 0) > 0 &&
        (sf.rows?.length ?? 0) > 0 &&
        sf.rows.some((r) => r.ivs.some((v) => v !== null && v !== undefined)),
      term: ivTerm.value.length >= 2,
    }
  })

  /* --------------------------- hint 文案 --------------------------- */

  const sellerHint = computed(() => {
    const d = seller.value
    const e = currentExpiryItem.value
    if (!d) return '当前到期月 · 卖方参考'
    const head = e ? `${e.label} · ` : ''
    const atm = d.atmStrike !== null ? d.atmStrike.toFixed(3) : '--'
    return `${head}剩余${d.days ?? '--'}天 · 平值档 ${atm}`
  })

  const smileHint = computed(() => {
    const e = currentExpiryItem.value
    return e ? `${e.label} · ${e.days}天 · IV vs 行权价` : 'IV vs 行权价'
  })

  const oiHint = computed(() => {
    const d = oi.value
    const e = currentExpiryItem.value
    const head = e ? `${e.label} · ` : ''
    if (!d) return `${head}各行权价 OI`
    const parts: string[] = []
    if (d.callWall !== null) parts.push(`Call墙 ${d.callWall.toFixed(3)}`)
    if (d.putWall !== null) parts.push(`Put墙 ${d.putWall.toFixed(3)}`)
    if (d.maxPain !== null) parts.push(`MaxPain ${d.maxPain.toFixed(3)}`)
    return head + (parts.length ? parts.join(' · ') : '各行权价 OI')
  })

  /** 期限结构倒挂判定（近月 IV 高于远月 = 市场在为近期风险定价）。 */
  const termHint = computed(() => {
    const t = ivTerm.value
    if (t.length < 2) return '各到期月 ATM IV'
    return t[0]!.atmIV > t[t.length - 1]!.atmIV
      ? '近月 > 远月 = 倒挂（市场为近期风险定价）'
      : '远月 > 近月 = 正常上斜'
  })

  return {
    payload,
    expiry,
    collapsed,
    apply,
    selectExpiry,
    togglePanel,
    isCollapsed,
    underlying,
    meta,
    expiries,
    hasExpiries,
    spot,
    currentExpiryItem,
    seller,
    smile,
    oi,
    ivTerm,
    surface,
    smileAll,
    available,
    sellerHint,
    smileHint,
    oiHint,
    termHint,
  }
})
