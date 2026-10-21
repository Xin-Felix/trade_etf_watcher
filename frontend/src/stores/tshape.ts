/**
 * 期权 T 型页状态。
 *
 * payload 是 Python 侧 option_meta.build_tshape_data 的产物（与分析页同一份），
 * 这页消费 rows / underlying / expiries。策略计算走另一条链路：
 * 前端维护篮子 → requestStrategy → Python 算 → renderStrategy 回推。
 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import type {
  ExpiryItem,
  PresetItem,
  StrategyPayload,
  StrategyRequest,
  StrikeRow,
  TShapePayload,
} from '@/bridge/types'

export type SideFilter = 'all' | 'call' | 'put'

export interface BasketLeg {
  code: string
  name: string
  side: 'buy' | 'sell'
  qty: number
  /** 由 Python 回推填充，前端加腿时不知道 */
  price?: number
}

/**
 * 已到期的月份不显示 —— 没有交易价值，只会占着 chips 位置。
 * days 算不出来（null）时保留，宁可多显示也别误删。
 */
function isActive(e: ExpiryItem): boolean {
  return e.days === null || e.days === undefined || e.days >= 0
}

export const useTshapeStore = defineStore('tshape', () => {
  const payload = ref<TShapePayload | null>(null)
  const expiry = ref<string | null>(null)
  const filter = ref<SideFilter>('all')

  /** 本地篮子。Python 只负责算，腿的增删改都在前端。 */
  const basket = ref<BasketLeg[]>([])
  /** Python 回推的策略计算结果。 */
  const strategy = ref<StrategyPayload | null>(null)

  const stratCollapsed = ref(true)
  /** 换标的时给视图一个信号：滚回现价带 */
  const scrollToStripToken = ref(0)

  /* --------------------------- 接收 payload --------------------------- */

  function apply(p: TShapePayload): void {
    const sameUnderlying = payload.value?.underlying?.code === p.underlying?.code
    payload.value = p

    // 从 K 线买卖点跳过来：Python 一次性带上方向，直接切到对应那一侧。
    // 字段缺省时不动用户当前的选择（定时刷新走的就是缺省这条路）。
    if (p.initialFilter === 'call' || p.initialFilter === 'put') {
      filter.value = p.initialFilter
    }

    // 只在有效（未到期）月份里选。Python 的 defaultExpiry 取的是 expiries[0]，
    // 而 expiries 含已过期的月份，所以它本身可能就是个过期月，得先验一下。
    const valid = (p.expiries ?? []).filter(isActive)
    if (!valid.some((e) => e.date === expiry.value)) {
      const preferred = valid.find((e) => e.date === p.defaultExpiry)
      expiry.value = preferred?.date ?? valid[0]?.date ?? null
    }

    if (!sameUnderlying) {
      // 跨标的的组合没有意义，换标的就清空
      basket.value = []
      strategy.value = null
      scrollToStripToken.value += 1
    }
  }

  function applyStrategy(p: StrategyPayload): void {
    strategy.value = p
    // 预设返回的腿要同步回本地篮子，用户可以接着微调
    if (p.legs && p.legs.length > 0) {
      basket.value = p.legs.map((l) => ({
        code: l.code,
        name: l.name,
        side: l.side,
        qty: l.qty,
        price: l.price,
      }))
      stratCollapsed.value = false
    }
  }

  /* ----------------------------- 视图状态 ----------------------------- */

  function selectExpiry(date: string): void {
    expiry.value = date
  }

  function setFilter(f: SideFilter): void {
    filter.value = f
  }

  function toggleStrat(): void {
    stratCollapsed.value = !stratCollapsed.value
  }

  function openStrat(): void {
    stratCollapsed.value = false
  }

  function requestScrollToStrip(): void {
    scrollToStripToken.value += 1
  }

  /* ------------------------------ 篮子 ------------------------------ */

  function addLeg(code: string, name: string, side: 'buy' | 'sell'): void {
    const hit = basket.value.find((l) => l.code === code && l.side === side)
    if (hit) hit.qty += 1
    else basket.value.push({ code, name, side, qty: 1 })
    stratCollapsed.value = false
  }

  function removeLeg(i: number): void {
    basket.value.splice(i, 1)
  }

  function flipLeg(i: number): void {
    const l = basket.value[i]
    if (l) l.side = l.side === 'buy' ? 'sell' : 'buy'
  }

  function setQty(i: number, v: number | string): void {
    const l = basket.value[i]
    if (!l) return
    const n = Number.parseInt(String(v), 10)
    l.qty = Math.max(1, Math.min(999, Number.isNaN(n) ? 1 : n))
  }

  function clearBasket(): void {
    basket.value = []
  }

  /* --------------------------- 出站请求组装 --------------------------- */

  function strategyRequest(preset?: string): StrategyRequest {
    const req: StrategyRequest = {
      underlying: payload.value?.underlying?.code ?? null,
      expiry: expiry.value,
      // 点预设时不带腿：Python 会按预设自己挑腿
      legs: preset
        ? []
        : basket.value.map((l) => ({ code: l.code, side: l.side, qty: l.qty })),
    }
    if (preset) req.preset = preset
    return req
  }

  /**
   * 行情刷新时该不该重新提交策略计算。
   *
   * 旧版 renderTShape 末尾无条件 submitStrategy()，等于每轮行情（5 秒）都
   * 往 Python 发一次策略计算，篮子空着也发。这里收窄成两种情况：
   *   - 篮子非空：价格变了，指标和损益图确实要跟着更新
   *   - 还没拿到预设列表：首次得靠这一发把 presets 取回来
   */
  function shouldResubmitOnRefresh(): boolean {
    return basket.value.length > 0 || presets.value.length === 0
  }

  /* ------------------------------ 派生 ------------------------------ */

  const underlying = computed(() => payload.value?.underlying ?? null)
  const meta = computed(() => payload.value?.meta ?? '')
  const emptyHint = computed(
    () => payload.value?.emptyHint ?? '暂无数据（先选择左侧 ETF 期权标的）',
  )
  /** 只暴露未到期的月份，过期的不进 chips。 */
  const expiries = computed<ExpiryItem[]>(() =>
    (payload.value?.expiries ?? []).filter(isActive),
  )
  const spot = computed(() => underlying.value?.price ?? null)

  const currentExpiryItem = computed<ExpiryItem | null>(
    () => expiries.value.find((e) => e.date === expiry.value) ?? null,
  )

  const rows = computed<StrikeRow[]>(() =>
    expiry.value ? (payload.value?.rows?.[expiry.value] ?? []) : [],
  )

  const hasRows = computed(() => rows.value.length > 0)

  /**
   * 现价带插在哪一行之前。
   * 第一个行权价高于现价的位置；全都低于现价时排在最后；无现价则不插（-1）。
   */
  const stripIndex = computed(() => {
    const s = spot.value
    if (s === null || s === undefined) return -1
    const i = rows.value.findIndex((r) => r.strike > s)
    return i < 0 ? rows.value.length : i
  })

  const presets = computed<PresetItem[]>(() => strategy.value?.presets ?? [])

  const totalQty = computed(() => basket.value.reduce((a, l) => a + l.qty, 0))

  /** 策略腿的剩余到期天数（取第一条腿，预设会锁定同一到期月）。 */
  const legDays = computed(() => strategy.value?.legs?.[0]?.days ?? null)

  const basketSummary = computed(() => {
    if (basket.value.length === 0) return '未选合约 · 点表格里的「买/卖」加腿'
    const d = legDays.value
    const tail = d !== null ? ` · 剩余 ${d} 天到期` : ''
    return `${basket.value.length} 条腿 / ${totalQty.value} 张${tail}`
  })

  return {
    payload,
    expiry,
    filter,
    basket,
    strategy,
    stratCollapsed,
    scrollToStripToken,
    apply,
    applyStrategy,
    selectExpiry,
    setFilter,
    toggleStrat,
    openStrat,
    requestScrollToStrip,
    addLeg,
    removeLeg,
    flipLeg,
    setQty,
    clearBasket,
    strategyRequest,
    shouldResubmitOnRefresh,
    underlying,
    meta,
    emptyHint,
    expiries,
    spot,
    currentExpiryItem,
    rows,
    hasRows,
    stripIndex,
    presets,
    totalQty,
    legDays,
    basketSummary,
  }
})
