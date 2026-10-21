<script setup lang="ts">
/**
 * 波动率曲面：到期月 × 行权价 的 IV 热力图。
 *
 * 是 2D heatmap 而不是 3D 曲面（旧版就是这样，不需要 echarts-gl）。
 * 每行的平值档加黑框标注，方便顺着 ATM 看期限结构。
 */
import { computed } from 'vue'

import EChart from '@/components/EChart.vue'
import type { ChartOption } from '@/chart/echarts'
import { axisLabel, axisLine, baseOption, darkTooltip, labelInterval } from '@/chart/presets'
import { useAnalysisStore } from '@/stores/analysis'

const store = useAnalysisStore()

const option = computed<ChartOption | null>(() => {
  const sf = store.surface
  if (!sf) return null

  const strikes = sf.strikes.map((s) => s.toFixed(3))
  const expiries = sf.rows.map((r) => `${r.expiry}\n(${r.days ?? '?'}天)`)

  // heatmap 数据是 [xIndex, yIndex, value] 三元组
  const data: Array<[number, number, number]> = []
  let minIV = Infinity
  let maxIV = 0
  sf.rows.forEach((row, yi) => {
    row.ivs.forEach((iv, xi) => {
      if (iv !== null && iv !== undefined) {
        data.push([xi, yi, iv])
        if (iv < minIV) minIV = iv
        if (iv > maxIV) maxIV = iv
      }
    })
  })
  if (data.length === 0) return null

  // 平值档 = 离现价最近的行权价，整列标出来
  const spot = store.spot
  let atmIdx = -1
  if (spot !== null && spot > 0) {
    let best = Infinity
    sf.strikes.forEach((s, i) => {
      const dist = Math.abs(s - spot)
      if (dist < best) {
        best = dist
        atmIdx = i
      }
    })
  }

  return {
    ...baseOption(),
    grid: { left: 80, right: 60, top: 20, bottom: 50 },
    tooltip: darkTooltip({
      formatter: (p: { data?: [number, number, number] }) => {
        if (!p.data) return ''
        const [xi, yi, iv] = p.data
        return `到期: ${sf.rows[yi]?.expiry}<br/>行权价: ${sf.strikes[xi]?.toFixed(3)}<br/>IV: ${iv.toFixed(2)}%`
      },
    }),
    xAxis: {
      type: 'category',
      data: strikes,
      splitArea: { show: false },
      axisLine,
      axisLabel: axisLabel({
        fontSize: 9,
        interval: labelInterval(strikes.length, 15),
        rotate: strikes.length > 20 ? 45 : 0,
      }),
    },
    yAxis: {
      type: 'category',
      data: expiries,
      splitArea: { show: false },
      axisLine,
      axisLabel: { color: '#ccc', fontSize: 11 },
    },
    visualMap: {
      min: Math.floor(minIV),
      max: Math.ceil(maxIV),
      calculable: false,
      orient: 'vertical',
      right: 6,
      top: 20,
      bottom: 50,
      textStyle: { color: '#aaa', fontSize: 10 },
      inRange: { color: ['#26a69a', '#66bb6a', '#ffee58', '#ffa726', '#ef5350'] },
      formatter: (v: number) => v.toFixed(1) + '%',
    },
    series: [
      {
        type: 'heatmap',
        data,
        emphasis: { itemStyle: { borderColor: '#fff', borderWidth: 1 } },
        itemStyle: { borderColor: '#1e1e1e', borderWidth: 1 },
        // 档位太多时数字挤在一起没法看，只在 15 档以内显示
        label: {
          show: strikes.length <= 15,
          color: '#222',
          fontSize: 9,
          formatter: (p: { data?: [number, number, number] }) =>
            p.data ? p.data[2].toFixed(1) : '',
        },
        markPoint:
          atmIdx >= 0
            ? {
                data: sf.rows.map((_, yi) => ({
                  coord: [atmIdx, yi],
                  symbol: 'rect',
                  symbolSize: [14, 14],
                  itemStyle: { color: 'transparent', borderColor: '#000', borderWidth: 2 },
                  label: { show: false },
                })),
              }
            : undefined,
      },
    ],
  }
})
</script>

<template>
  <EChart :option="option" height="300px" />
</template>
