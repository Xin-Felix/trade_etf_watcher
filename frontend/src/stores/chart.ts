/**
 * K 线图状态。
 *
 * 指标（MA / 均量 / MACD）都在前端算 —— 旧版 chart.html 也是这么做的，
 * Python 只发 bars。算法逐条对齐，包括 EMA 用首值初始化这种细节。
 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import type { ChartBar, ChartPayload, ChartQuote, ChartSignal, LabelFmt } from '@/bridge/types'
import { formatBarLabel, tsToMinute } from '@/utils/format'

/** 买卖点（交易建议）。 */
const UP_KEYS = ['resonance_long']
const DOWN_KEYS = ['resonance_short']
/** 行情事件（不是交易建议，用小三角区别于买卖 pin）。 */
const EVENT_UP = ['surge', 'rebound', 'gap_up', 'minute_surge']
const EVENT_DOWN = ['plunge', 'reversal', 'gap_down', 'minute_plunge']

export const UP_COLOR = '#ef5350'
export const DOWN_COLOR = '#26a69a'

export type SignalKind = 'buy' | 'sell' | 'eventUp' | 'eventDown'

export interface PlacedSignal {
  kind: SignalKind
  /** 在 bars 里的下标 */
  index: number
  text: string
}

/** 缩放窗口，跨刷新保持用。 */
export interface ZoomWindow {
  start: number
  end: number
}

function sma(values: number[], n: number): Array<number | null> {
  return values.map((_, i) => {
    if (i < n - 1) return null
    let sum = 0
    for (let j = i - n + 1; j <= i; j++) sum += values[j]!
    return +(sum / n).toFixed(4)
  })
}

/**
 * EMA。首值直接取 data[0]（不做 SMA 预热）—— 与旧版一致，
 * 换成标准初始化会让 MACD 数值和历史对不上。
 */
function ema(values: number[], n: number): number[] {
  if (values.length === 0) return []
  const k = 2 / (n + 1)
  const out = [values[0]!]
  for (let i = 1; i < values.length; i++) {
    out.push(values[i]! * k + out[i - 1]! * (1 - k))
  }
  return out
}

export const useChartStore = defineStore('chart', () => {
  const title = ref('K 线图')
  const period = ref('')
  const periods = ref<string[]>([])
  const loading = ref(false)
  const bars = ref<ChartBar[]>([])
  const signals = ref<ChartSignal[]>([])
  const quote = ref<ChartQuote | null>(null)
  const mode = ref<'candle' | 'intraday'>('candle')
  const digits = ref(3)
  const labelFmt = ref<LabelFmt>('time')
  const atmUnderlying = ref<string | null>(null)

  /** 悬停的 bar 下标；null = 未悬停（显示最新一根 / 最新报价）。 */
  const hoverIndex = ref<number | null>(null)
  /** 用户当前的缩放窗口，定时刷新时写回，避免视图被重置。 */
  const zoom = ref<ZoomWindow | null>(null)

  function apply(p: ChartPayload): void {
    // 周期按钮在 loading 期间也要更新（允许加载中先切周期）
    title.value = p.title || 'K 线图'
    period.value = p.period || ''
    periods.value = p.periods || []

    if (p.loading) {
      // 期权后台取数中：只显示加载提示，不动旧图与侧栏
      loading.value = true
      return
    }
    loading.value = false
    bars.value = p.bars ?? []
    signals.value = p.signals ?? []
    quote.value = p.quote ?? null
    mode.value = p.mode ?? 'candle'
    digits.value = p.digits ?? 3
    labelFmt.value = p.labelFmt ?? 'time'
    atmUnderlying.value = p.atm?.underlying ?? null
    // 数据换了，悬停位置失效
    hoverIndex.value = null
  }

  function setHover(i: number | null): void {
    hoverIndex.value = i !== null && i >= 0 && i < bars.value.length ? i : null
  }

  function setZoom(w: ZoomWindow | null): void {
    zoom.value = w
  }

  /* --------------------------- 派生 --------------------------- */

  const hasData = computed(() => bars.value.length > 0)

  const times = computed(() => bars.value.map((b) => formatBarLabel(b.ts, labelFmt.value)))

  const closes = computed(() => bars.value.map((b) => b.close))
  const volumes = computed(() => bars.value.map((b) => b.volume || 0))

  /** 昨收/昨结：首根 bar 的涨跌基准。 */
  const prevClose = computed(() => quote.value?.prevClose ?? null)

  const ma = computed(() => ({
    5: sma(closes.value, 5),
    10: sma(closes.value, 10),
    20: sma(closes.value, 20),
  }))

  /** 均量线 MA5：叠在成交量区，方便看放量/缩量。 */
  const volMa5 = computed<Array<number | null>>(() =>
    volumes.value.map((_, i) => {
      if (i < 4) return null
      let sum = 0
      for (let j = i - 4; j <= i; j++) sum += volumes.value[j]!
      return Math.round(sum / 5)
    }),
  )

  /** MACD(12, 26, 9)。柱子是 (DIF - DEA) × 2，与旧版一致。 */
  const macd = computed(() => {
    const c = closes.value
    if (c.length === 0) return { dif: [], dea: [], bar: [] }
    const e12 = ema(c, 12)
    const e26 = ema(c, 26)
    const dif = e12.map((v, i) => +(v - e26[i]!).toFixed(6))
    const dea = ema(dif, 9).map((v) => +v.toFixed(6))
    const bar = dif.map((v, i) => +((v - dea[i]!) * 2).toFixed(6))
    return { dif, dea, bar }
  })

  /**
   * 信号定位到 bar 下标。
   *
   * 按时间戳（分钟精度）匹配而不是按数组下标：信号是在当日 bars 上检测的，
   * 期权模式下甚至用的是对应 ETF 的 bars，与 payload.bars 的索引没有对应关系。
   * 两边 ts 可能一个 12 位一个 14 位，所以都截到分钟。
   */
  const placedSignals = computed<PlacedSignal[]>(() => {
    const idxByMinute = new Map<string, number>()
    bars.value.forEach((b, i) => idxByMinute.set(tsToMinute(b.ts), i))

    const out: PlacedSignal[] = []
    for (const s of signals.value) {
      const i = idxByMinute.get(tsToMinute(s.ts))
      if (i === undefined) continue
      let kind: SignalKind | null = null
      if (UP_KEYS.includes(s.key)) kind = 'buy'
      else if (DOWN_KEYS.includes(s.key)) kind = 'sell'
      else if (EVENT_UP.includes(s.key)) kind = 'eventUp'
      else if (EVENT_DOWN.includes(s.key)) kind = 'eventDown'
      if (!kind) continue
      out.push({ kind, index: i, text: s.labelText })
    }
    return out
  })

  /** bar 下标 → 该根上的信号文本（tooltip 用）。 */
  const signalsByIndex = computed(() => {
    const m = new Map<number, Array<{ text: string; color: string }>>()
    const colorOf: Record<SignalKind, string> = {
      buy: '#ff1744',
      sell: '#00c853',
      eventUp: '#ff9800',
      eventDown: '#ff9800',
    }
    for (const s of placedSignals.value) {
      const list = m.get(s.index) ?? []
      list.push({ text: s.text, color: colorOf[s.kind] })
      m.set(s.index, list)
    }
    return m
  })

  /** 第 i 根的涨跌额/涨跌幅：对前一根收盘，首根对昨收。 */
  function changeAt(i: number): [number | null, number | null] {
    const b = bars.value[i]
    if (!b) return [null, null]
    const base = i > 0 ? bars.value[i - 1]!.close : prevClose.value
    if (base === null || base === undefined || base <= 0) return [null, null]
    const chg = b.close - base
    return [chg, (chg / base) * 100]
  }

  /** 当前应该显示的 bar 下标（未悬停时是最后一根）。 */
  const activeIndex = computed(() =>
    hoverIndex.value !== null ? hoverIndex.value : bars.value.length - 1,
  )

  /**
   * 右侧面板要显示的数据：悬停时用那根 bar 拼出报价结构，
   * 未悬停时用最新报价。
   */
  const sidePanel = computed<ChartQuote | null>(() => {
    if (hoverIndex.value === null) return quote.value
    const i = hoverIndex.value
    const b = bars.value[i]
    if (!b) return quote.value
    const [chg, pct] = changeAt(i)
    const extras: Array<[string, string]> = []
    if (b.avg !== null && b.avg !== undefined) {
      extras.push(['均价', b.avg.toFixed(digits.value)])
    }
    return {
      price: b.close,
      change: chg,
      changePct: pct,
      open: b.open,
      high: b.high,
      low: b.low,
      prevClose: i > 0 ? bars.value[i - 1]!.close : prevClose.value,
      volume: b.volume,
      extras,
    }
  })

  return {
    title,
    period,
    periods,
    loading,
    bars,
    signals,
    quote,
    mode,
    digits,
    labelFmt,
    atmUnderlying,
    hoverIndex,
    zoom,
    apply,
    setHover,
    setZoom,
    hasData,
    times,
    closes,
    volumes,
    prevClose,
    ma,
    volMa5,
    macd,
    placedSignals,
    signalsByIndex,
    changeAt,
    activeIndex,
    sidePanel,
  }
})
