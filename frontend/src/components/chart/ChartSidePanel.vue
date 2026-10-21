<script setup lang="ts">
/**
 * 右侧信息面板：默认显示最新报价，鼠标悬停在图上时切成那根 bar 的数据
 * （store.sidePanel 已经处理了这个切换）。
 */
import { computed } from 'vue'

import { useBridgeStore } from '@/stores/bridge'
import { useChartStore } from '@/stores/chart'
import { fmtCompact, trendClass } from '@/utils/format'

const store = useChartStore()
const bridge = useBridgeStore()

const q = computed(() => store.sidePanel)

function p(v: number | null | undefined): string {
  return v === null || v === undefined || Number.isNaN(v) ? '--' : v.toFixed(store.digits)
}

const cls = computed(() => trendClass(q.value?.change))

const chgText = computed(() => {
  const d = q.value
  if (!d) return '--'
  const s = d.change !== null && d.change > 0 ? '+' : ''
  const a = d.change !== null ? `${s}${d.change.toFixed(store.digits)}` : '--'
  const b = d.changePct !== null ? ` ${s}${d.changePct.toFixed(2)}%` : ''
  return a + b
})

/** 只显示有值的行；期权的开高低恒为 null，会自动被过滤掉。 */
const rows = computed<Array<[string, string]>>(() => {
  const d = q.value
  if (!d) return []
  const out: Array<[string, string]> = []
  const base: Array<[string, number | null]> = [
    ['今开', d.open],
    ['最高', d.high],
    ['最低', d.low],
    // 期权涨跌幅官方口径是对昨结算价，标题也跟着变
    [d.prevCloseLabel || '昨收', d.prevClose],
  ]
  for (const [k, v] of base) {
    if (v !== null && v !== undefined) out.push([k, p(v)])
  }
  if (d.volume !== null && d.volume !== undefined) out.push(['成交量', fmtCompact(d.volume)])
  for (const [k, v] of d.extras || []) out.push([k, v])
  return out
})
</script>

<template>
  <div class="side" data-probe="side">
    <template v-if="q">
      <div class="price" :class="cls" data-probe="side-price">{{ p(q.price) }}</div>
      <div class="chg" :class="cls" data-probe="side-chg">{{ chgText }}</div>
      <div v-for="[k, v] in rows" :key="k" class="row">
        <span class="k">{{ k }}</span>
        <span>{{ v }}</span>
      </div>
      <div v-if="store.atmUnderlying" class="jump">
        <button data-probe="view-option" @click="bridge.viewOption(store.atmUnderlying, '')">
          查看期权 T 型
        </button>
      </div>
    </template>
    <div v-else class="none">暂无报价</div>
  </div>
</template>

<style scoped>
.side {
  flex: 0 0 172px;
  padding: 14px;
  overflow-y: auto;
  border-left: 1px solid var(--line);
}

.price {
  font-size: 26px;
  font-weight: bold;
  font-variant-numeric: tabular-nums;
}

.chg {
  margin: 4px 0 12px;
  font-size: 13px;
  font-variant-numeric: tabular-nums;
}

.row {
  display: flex;
  justify-content: space-between;
  padding: 5px 0;
  border-bottom: 1px solid #262626;
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}

.row .k {
  color: var(--fg-weak);
}

.jump {
  margin-top: 12px;
}

.jump button {
  width: 100%;
  padding: 6px;
  border: none;
  border-radius: 5px;
  background: var(--accent);
  color: #1a1a1a;
  font-family: var(--font);
  font-size: 13px;
  font-weight: bold;
  cursor: pointer;
}

.none {
  color: #555;
  font-size: 12px;
}
</style>
