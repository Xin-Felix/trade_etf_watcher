<script setup lang="ts">
/**
 * 平值 IV 期限结构：各到期月的 ATM IV 连线。
 * 近月高于远月（倒挂）说明市场在为近期风险定价 —— 判定文案在 store 的 termHint。
 */
import { computed } from 'vue'

import EChart from '@/components/EChart.vue'
import type { ChartOption } from '@/chart/echarts'
import {
  axisLabel,
  axisLine,
  baseOption,
  darkTooltip,
  nameTextStyle,
  splitLine,
} from '@/chart/presets'
import { useAnalysisStore } from '@/stores/analysis'

const store = useAnalysisStore()

const option = computed<ChartOption | null>(() => {
  const data = store.ivTerm
  if (data.length < 2) return null

  return {
    ...baseOption(),
    grid: { left: 52, right: 20, top: 30, bottom: 30 },
    tooltip: darkTooltip({
      trigger: 'axis',
      formatter: (params: Array<{ dataIndex: number }>) => {
        if (!params?.length) return ''
        const d = data[params[0]!.dataIndex]
        if (!d) return ''
        return `${d.expiry}（${d.days}天）<br/>ATM IV: <b>${d.atmIV.toFixed(2)}%</b>`
      },
    }),
    xAxis: {
      type: 'category',
      data: data.map((d) => d.expiry),
      boundaryGap: false,
      axisLine,
      axisLabel: axisLabel({ fontSize: 11 }),
    },
    yAxis: {
      type: 'value',
      name: 'ATM IV%',
      nameTextStyle,
      splitLine,
      axisLabel: axisLabel({ formatter: '{value}%' }),
    },
    series: [
      {
        type: 'line',
        data: data.map((d) => d.atmIV),
        symbol: 'circle',
        symbolSize: 8,
        lineStyle: { width: 2.5, color: '#42a5f5' },
        itemStyle: { color: '#42a5f5' },
        areaStyle: { color: 'rgba(66,165,245,0.10)' },
        label: {
          show: true,
          formatter: (p: { data: number }) => p.data.toFixed(1) + '%',
          color: '#42a5f5',
          fontSize: 11,
          position: 'top',
        },
      },
    ],
  }
})
</script>

<template>
  <EChart :option="option" />
</template>
