<script setup lang="ts">
/**
 * 左上角 legend，股票软件风格：跟随十字光标显示那根 bar 的数据，
 * 鼠标移出图表时回到最新一根。
 */
import { computed } from 'vue'

import { useChartStore } from '@/stores/chart'
import { fmtCompact, trendClass } from '@/utils/format'

const store = useChartStore()

const bar = computed(() => store.bars[store.activeIndex] ?? null)
const label = computed(() => store.times[store.activeIndex] ?? '')

const change = computed(() => store.changeAt(store.activeIndex))

function p(v: number | null | undefined): string {
  return v === null || v === undefined || Number.isNaN(v) ? '--' : v.toFixed(store.digits)
}

const chgText = computed(() => {
  const [chg, pct] = change.value
  if (chg === null || pct === null) return '--'
  const s = chg > 0 ? '+' : ''
  return `${s}${chg.toFixed(store.digits)} ${s}${pct.toFixed(2)}%`
})
</script>

<template>
  <div v-if="bar" class="legend" data-probe="legend">
    <span class="t">{{ label }}</span>
    <template v-if="store.mode === 'candle'">
      开 {{ p(bar.open) }} 高 {{ p(bar.high) }} 低 {{ p(bar.low) }} 收 {{ p(bar.close) }}
    </template>
    <template v-else>
      价 {{ p(bar.close) }}<template v-if="bar.avg !== null"> 均 {{ p(bar.avg) }}</template>
    </template>
    <span :class="trendClass(change[0])">{{ chgText }}</span>
    <span>量 {{ fmtCompact(bar.volume) }}</span>
  </div>
</template>

<style scoped>
.legend {
  position: absolute;
  top: 6px;
  left: 64px;
  z-index: 10;
  display: flex;
  gap: 10px;
  color: #bbb;
  font-size: 12px;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
  pointer-events: none;
  text-shadow: 0 1px 2px #000;
}
</style>
