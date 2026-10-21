<script setup lang="ts">
/**
 * 持仓量分布：各行权价的 Call/Put OI 双柱，
 * 叠加 Call墙/Put墙（持仓最大档）和 MaxPain（最大痛点）标注。
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
} from '@/chart/presets'
import { useAnalysisStore } from '@/stores/analysis'
import { fmtCompact } from '@/utils/format'

const store = useAnalysisStore()

/** 墙的标注要落在具体柱子上，按行权价数值找下标（浮点比较留容差）。 */
function wallMark(
  wall: number | null,
  strikes: number[],
  values: number[],
  label: string,
): Record<string, unknown>[] {
  if (wall === null) return []
  const idx = strikes.findIndex((s) => Math.abs(s - wall) < 0.0001)
  if (idx < 0) return []
  return [
    {
      coord: [strikes[idx]!.toFixed(3), values[idx]],
      symbol: 'rect',
      symbolSize: [20, 20],
      itemStyle: { color: 'transparent', borderColor: '#ffd700', borderWidth: 2 },
      label: { show: true, formatter: label, position: 'top', color: '#ffd700', fontSize: 10 },
    },
  ]
}

const option = computed<ChartOption | null>(() => {
  const d = store.oi
  if (!d) return null
  const strikes = d.strikes.map((s) => s.toFixed(3))
  const spot = store.spot

  const markLines: Record<string, unknown>[] = []
  if (spot !== null && spot > 0) {
    markLines.push({
      xAxis: spot.toFixed(3),
      lineStyle: { color: '#4fc3f7', type: 'dashed', width: 1.5 },
      label: { show: true, formatter: '现价', color: '#4fc3f7', fontSize: 10, position: 'insideEndTop' },
    })
  }
  if (d.maxPain !== null) {
    markLines.push({
      xAxis: d.maxPain.toFixed(3),
      lineStyle: { color: '#ff9800', type: 'solid', width: 1.5 },
      label: { show: true, formatter: 'MaxPain', color: '#ff9800', fontSize: 10, position: 'insideStartTop' },
    })
  }

  return {
    ...baseOption(),
    grid: { left: 58, right: 20, top: 30, bottom: 30 },
    legend: { ...legendStyle, data: ['Call 持仓', 'Put 持仓'] },
    tooltip: darkTooltip({
      trigger: 'axis',
      formatter: (params: Array<{ axisValue: string; color: string; seriesName: string; data: number | null }>) => {
        if (!params?.length) return ''
        let html = `行权价 ${params[0]!.axisValue}<br/>`
        for (const p of params) {
          if (p.data !== null && p.data !== undefined) {
            html += `<span style="color:${p.color}">●</span> ${p.seriesName}: ${fmtCompact(p.data)}<br/>`
          }
        }
        return html
      },
    }),
    xAxis: {
      type: 'category',
      data: strikes,
      axisLine,
      axisLabel: axisLabel({ interval: labelInterval(strikes.length, 12) }),
    },
    yAxis: {
      type: 'value',
      name: '持仓量',
      nameTextStyle,
      splitLine,
      axisLabel: axisLabel({ formatter: (v: number) => fmtCompact(v) }),
    },
    series: [
      {
        name: 'Call 持仓',
        type: 'bar',
        data: d.callOI,
        itemStyle: { color: 'rgba(38,166,154,0.75)' },
        barMaxWidth: 18,
        markPoint: { data: wallMark(d.callWall, d.strikes, d.callOI, 'Call墙') },
        markLine: { symbol: 'none', silent: true, data: markLines },
      },
      {
        name: 'Put 持仓',
        type: 'bar',
        data: d.putOI,
        itemStyle: { color: 'rgba(239,83,80,0.75)' },
        barMaxWidth: 18,
        markPoint: { data: wallMark(d.putWall, d.strikes, d.putOI, 'Put墙') },
      },
    ],
  }
})
</script>

<template>
  <EChart :option="option" />
</template>
