/**
 * K 线图 option 组装。
 *
 * 三个 grid 上下叠：主图（蜡烛/分时 + MA + 买卖标记）、成交量（+均量线）、
 * MACD。三个 x 轴通过 axisPointer.link 联动，十字光标同步移动。
 *
 * 指标数值由 stores/chart.ts 算好传进来，这里只管画。
 */
import type { ChartOption } from '@/chart/echarts'
import type { ChartBar } from '@/bridge/types'
import { DOWN_COLOR, UP_COLOR, type PlacedSignal, type ZoomWindow } from '@/stores/chart'
import { fmtCompact } from '@/utils/format'

export interface KlineInput {
  times: string[]
  bars: ChartBar[]
  mode: 'candle' | 'intraday'
  digits: number
  ma: Record<number, Array<number | null>>
  volMa5: Array<number | null>
  macd: { dif: number[]; dea: number[]; bar: number[] }
  signals: PlacedSignal[]
  signalsByIndex: Map<number, Array<{ text: string; color: string }>>
  changeAt: (i: number) => [number | null, number | null]
  /** 用户当前缩放窗口；null 表示用默认（末尾 60 根） */
  zoom: ZoomWindow | null
}

const MA_DEFS: Array<[number, string]> = [
  [5, '#ffffff'],
  [10, '#ffeb3b'],
  [20, '#9c27b0'],
]

function signColor(v: number | null): string {
  if (v === null || v === 0) return '#aaa'
  return v > 0 ? UP_COLOR : DOWN_COLOR
}

/** 买卖点用 pin（醒目），行情事件用小三角（区别于交易建议）。 */
function markPointData(input: KlineInput): Record<string, unknown>[] {
  const out: Record<string, unknown>[] = []
  for (const s of input.signals) {
    const bar = input.bars[s.index]
    if (!bar) continue
    if (s.kind === 'buy') {
      out.push({
        coord: [s.index, bar.low],
        value: s.text,
        // sigKind 会随 click 事件的 params.data 回来，用于判断点的是不是买卖点
        sigKind: 'buy',
        symbol: 'pin',
        symbolSize: 28,
        symbolOffset: [0, 8],
        itemStyle: { color: '#ff1744' },
        label: { show: true, formatter: '买', color: '#fff', fontSize: 10, fontWeight: 'bold' },
      })
    } else if (s.kind === 'sell') {
      out.push({
        coord: [s.index, bar.high],
        value: s.text,
        sigKind: 'sell',
        symbol: 'pin',
        symbolSize: 28,
        symbolRotate: 180,
        symbolOffset: [0, -8],
        itemStyle: { color: '#00c853' },
        label: {
          show: true,
          formatter: '卖',
          color: '#fff',
          fontSize: 10,
          fontWeight: 'bold',
          offset: [0, -3],
        },
      })
    } else if (s.kind === 'eventUp') {
      out.push({
        coord: [s.index, bar.low],
        value: s.text,
        symbol: 'triangle',
        symbolSize: 12,
        symbolOffset: [0, 14],
        itemStyle: { color: '#ff9800' },
        label: { show: false },
      })
    } else {
      out.push({
        coord: [s.index, bar.high],
        value: s.text,
        symbol: 'triangle',
        symbolSize: 12,
        symbolRotate: 180,
        symbolOffset: [0, -14],
        itemStyle: { color: '#ff9800' },
        label: { show: false },
      })
    }
  }
  return out
}

export function buildKlineOption(input: KlineInput): ChartOption | null {
  const { times, bars, mode, digits } = input
  if (bars.length === 0) return null

  const fmtP = (v: number | null | undefined): string =>
    v === null || v === undefined || Number.isNaN(v) ? '--' : v.toFixed(digits)

  const series: Record<string, unknown>[] = []

  if (mode === 'candle') {
    series.push({
      name: 'K线',
      type: 'candlestick',
      data: bars.map((b) => [b.open, b.close, b.low, b.high]),
      itemStyle: {
        color: UP_COLOR,
        color0: DOWN_COLOR,
        borderColor: UP_COLOR,
        borderColor0: DOWN_COLOR,
      },
    })
    for (const [n, color] of MA_DEFS) {
      series.push({
        name: `MA${n}`,
        type: 'line',
        data: input.ma[n] ?? [],
        smooth: true,
        symbol: 'none',
        lineStyle: { width: 1, color },
        z: 5,
      })
    }
  } else {
    series.push({
      name: '最新价',
      type: 'line',
      data: bars.map((b) => b.close),
      symbol: 'none',
      lineStyle: { width: 1.5, color: '#ffffff' },
      z: 5,
    })
    if (bars.some((b) => b.avg !== null && b.avg !== undefined)) {
      series.push({
        name: '均价',
        type: 'line',
        data: bars.map((b) => b.avg),
        symbol: 'none',
        lineStyle: { width: 1.2, color: '#ffeb3b' },
        z: 4,
      })
    }
  }

  // 买卖标记挂在主 series 上，带独立 tooltip（悬停看信号详情）
  series[0]!.markPoint = {
    // z 要高于 MA 线（z:5）。zrender 命中检测按 z 从高到低走，
    // markPoint 默认 z 比线低，导致 MA 线横穿 pin 时把点击抢走，
    // pin 上会出现点不动的死区（买卖点是可点的，不能被线挡住）。
    z: 12,
    data: markPointData(input),
    tooltip: {
      show: true,
      formatter: (p: { data?: { value?: string } }) => p.data?.value ?? '',
      backgroundColor: '#2d2d2d',
      borderColor: '#555',
      textStyle: { color: '#eee' },
    },
  }

  // 成交量：红涨绿跌。蜡烛模式看开收，分时模式看是否高于前一分钟
  series.push({
    name: '成交量',
    type: 'bar',
    xAxisIndex: 1,
    yAxisIndex: 1,
    data: bars.map((b, i) => {
      const up =
        mode === 'candle'
          ? b.close >= b.open
          : i > 0
            ? b.close >= bars[i - 1]!.close
            : b.close >= b.open
      return { value: b.volume, itemStyle: { color: up ? UP_COLOR : DOWN_COLOR } }
    }),
  })
  series.push({
    name: '均量',
    type: 'line',
    xAxisIndex: 1,
    yAxisIndex: 1,
    data: input.volMa5,
    symbol: 'none',
    smooth: true,
    lineStyle: { width: 1, color: '#ffeb3b' },
    z: 5,
  })

  // MACD
  series.push({
    name: 'DIF',
    type: 'line',
    xAxisIndex: 2,
    yAxisIndex: 2,
    data: input.macd.dif,
    symbol: 'none',
    lineStyle: { width: 1, color: '#ffffff' },
    z: 5,
  })
  series.push({
    name: 'DEA',
    type: 'line',
    xAxisIndex: 2,
    yAxisIndex: 2,
    data: input.macd.dea,
    symbol: 'none',
    lineStyle: { width: 1, color: '#ffeb3b' },
    z: 5,
  })
  series.push({
    name: 'MACD',
    type: 'bar',
    xAxisIndex: 2,
    yAxisIndex: 2,
    data: input.macd.bar.map((v) => ({
      value: v,
      itemStyle: { color: v >= 0 ? UP_COLOR : DOWN_COLOR },
    })),
  })

  // 默认只看末尾约 60 根，太多根挤在一起看不清
  const defaultStart = Math.max(0, 100 - 6000 / times.length)
  const zs = input.zoom?.start ?? defaultStart
  const ze = input.zoom?.end ?? 100

  const axisCommon = {
    type: 'category',
    data: times,
    boundaryGap: true,
    axisLine: { lineStyle: { color: '#555' } },
  }

  return {
    backgroundColor: '#1e1e1e',
    animation: false,
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' },
      backgroundColor: '#2d2d2d',
      borderColor: '#555',
      textStyle: { color: '#eee', fontSize: 12 },
      formatter: (params: Array<{ dataIndex: number; seriesName?: string; value?: unknown }>) => {
        const i = params.length ? params[0]!.dataIndex : -1
        const b = bars[i]
        if (!b) return ''
        const [chg, pct] = input.changeAt(i)
        const sgn = chg !== null && chg > 0 ? '+' : ''
        const chgTxt =
          chg === null || pct === null
            ? '--'
            : `${sgn}${chg.toFixed(digits)} (${sgn}${pct.toFixed(2)}%)`
        let html: string
        if (mode === 'candle') {
          html =
            `${times[i]}<br/>开 ${fmtP(b.open)}&nbsp;&nbsp;高 ${fmtP(b.high)}<br/>` +
            `低 ${fmtP(b.low)}&nbsp;&nbsp;收 ${fmtP(b.close)}<br/>` +
            `涨跌 <span style="color:${signColor(chg)}">${chgTxt}</span><br/>` +
            `成交量 ${fmtCompact(b.volume)}`
        } else {
          const avg = b.avg !== null && b.avg !== undefined ? `&nbsp;&nbsp;均价 ${fmtP(b.avg)}` : ''
          html =
            `${times[i]}<br/>最新 ${fmtP(b.close)}${avg}<br/>` +
            `涨跌 <span style="color:${signColor(chg)}">${chgTxt}</span><br/>` +
            `成交量 ${fmtCompact(b.volume)}`
        }
        // 只追加均线值。注意必须精确匹配 MA+数字：
        // 旧版用 startsWith('MA')，把 MACD 也算进来了（'MACD'.startsWith('MA') 为真）
        for (const p of params) {
          if (p.seriesName && /^MA\d+$/.test(p.seriesName) && p.value !== null && p.value !== undefined) {
            html += `<br/>${p.seriesName} ${fmtP(p.value as number)}`
          }
        }
        const sigs = input.signalsByIndex.get(i)
        if (sigs?.length) {
          for (const s of sigs) {
            html += `<br/><span style="color:${s.color}">⚡ ${s.text}</span>`
          }
        }
        return html
      },
    },
    // 三个 grid 的十字光标联动
    axisPointer: { link: [{ xAxisIndex: 'all' }] },
    grid: [
      { left: 60, right: 20, top: 30, height: '42%' },
      { left: 60, right: 20, top: '56%', height: '14%' },
      { left: 60, right: 20, top: '74%', height: '14%' },
    ],
    xAxis: [
      { ...axisCommon, gridIndex: 0, axisLabel: { color: '#aaa' } },
      { ...axisCommon, gridIndex: 1, axisLabel: { show: false } },
      { ...axisCommon, gridIndex: 2, axisLabel: { show: false } },
    ],
    yAxis: [
      {
        scale: true,
        gridIndex: 0,
        splitLine: { lineStyle: { color: '#333' } },
        axisLabel: { color: '#aaa' },
      },
      {
        scale: true,
        gridIndex: 1,
        splitNumber: 2,
        splitLine: { show: false },
        axisLabel: { color: '#aaa' },
      },
      {
        scale: true,
        gridIndex: 2,
        splitNumber: 2,
        splitLine: { show: false },
        axisLabel: { color: '#aaa' },
      },
    ],
    dataZoom: [
      { type: 'inside', xAxisIndex: [0, 1, 2], start: zs, end: ze },
      {
        type: 'slider',
        xAxisIndex: [0, 1, 2],
        start: zs,
        end: ze,
        bottom: 6,
        height: 18,
        borderColor: '#444',
        backgroundColor: '#252525',
        fillerColor: 'rgba(255,152,0,0.15)',
        handleStyle: { color: '#ff9800' },
        textStyle: { color: '#888' },
      },
    ],
    series,
  }
}
