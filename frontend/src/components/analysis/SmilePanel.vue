<script setup lang="ts">
/** 波动率微笑：当前到期月的 Call/Put IV 对行权价曲线。 */
import { computed } from 'vue'

import EChart from '@/components/EChart.vue'
import type { ChartOption } from '@/chart/echarts'
import {
  axisLabel,
  axisLine,
  baseOption,
  darkTooltip,
  labelInterval,
  legendStyle,
  nameTextStyle,
  splitLine,
  spotMarkLine,
} from '@/chart/presets'
import { useAnalysisStore } from '@/stores/analysis'

const store = useAnalysisStore()

const option = computed<ChartOption | null>(() => {
  const d = store.smile
  if (!d) return null
  const strikes = d.strikes.map((s) => s.toFixed(3))

  return {
    ...baseOption(),
    grid: { left: 52, right: 20, top: 30, bottom: 30 },
    legend: { ...legendStyle, data: ['Call IV', 'Put IV'] },
    tooltip: darkTooltip({
      trigger: 'axis',
      formatter: (params: Array<{ axisValue: string; color: string; seriesName: string; data: number | null }>) => {
        if (!params?.length) return ''
        let html = `行权价 ${params[0]!.axisValue}<br/>`
        for (const p of params) {
          if (p.data !== null && p.data !== undefined) {
            html += `<span style="color:${p.color}">●</span> ${p.seriesName}: ${p.data.toFixed(2)}%<br/>`
          }
        }
        return html
      },
    }),
    xAxis: {
      type: 'category',
      data: strikes,
      boundaryGap: false,
      axisLine,
      axisLabel: axisLabel({ interval: labelInterval(strikes.length, 10) }),
    },
    yAxis: {
      type: 'value',
      name: 'IV%',
      nameTextStyle,
      splitLine,
      axisLabel: axisLabel({ formatter: '{value}%' }),
    },
    series: [
      {
        name: 'Call IV',
        type: 'line',
        data: d.callIV,
        symbol: 'circle',
        symbolSize: 4,
        // 中间档位缺 IV 时把线连起来，否则曲线会断成一截截
        connectNulls: true,
        lineStyle: { width: 2, color: '#26a69a' },
        itemStyle: { color: '#26a69a' },
      },
      {
        name: 'Put IV',
        type: 'line',
        data: d.putIV,
        symbol: 'circle',
        symbolSize: 4,
        connectNulls: true,
        lineStyle: { width: 2, color: '#ef5350' },
        itemStyle: { color: '#ef5350' },
      },
      ...spotMarkLine(store.spot),
    ],
  }
})
</script>

<template>
  <EChart :option="option" />
</template>
