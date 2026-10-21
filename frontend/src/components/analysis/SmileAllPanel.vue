<script setup lang="ts">
/**
 * 多到期月微笑对比：各月的 Call/Put 平均 IV 叠在一张图上。
 * 行权价并集对齐在 store 里做完了（各月档位不一样，缺的补 null）。
 */
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
  const { strikes, series } = store.smileAll
  if (series.length < 2) return null

  return {
    ...baseOption(),
    grid: { left: 52, right: 20, top: 30, bottom: 30 },
    legend: { ...legendStyle, data: series.map((s) => s.name) },
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
      data: strikes.map((s) => s.toFixed(3)),
      boundaryGap: false,
      axisLine,
      axisLabel: axisLabel({ interval: labelInterval(strikes.length, 12) }),
    },
    yAxis: {
      type: 'value',
      name: 'IV%',
      nameTextStyle,
      splitLine,
      axisLabel: axisLabel({ formatter: '{value}%' }),
    },
    series: [
      ...series.map((s) => ({
        name: s.name,
        type: 'line',
        data: s.data,
        symbol: 'circle',
        symbolSize: 3,
        connectNulls: true,
        lineStyle: { width: 2, color: s.color },
        itemStyle: { color: s.color },
      })),
      ...spotMarkLine(store.spot),
    ],
  }
})
</script>

<template>
  <EChart :option="option" height="280px" />
</template>
