<script setup lang="ts">
/**
 * K 线图页。
 *
 * 三个 grid（主图 / 成交量 / MACD）由 chart/kline.ts 组装 option，
 * 这里负责外壳：周期按钮、刷新、加载态，以及悬停联动的事件接线。
 */
import { computed, onBeforeUnmount, onMounted } from 'vue'

import type { ChartInstance } from '@/chart/echarts'
import type { ChartOption } from '@/chart/echarts'
import { buildKlineOption } from '@/chart/kline'
import EChart from '@/components/EChart.vue'
import ChartSidePanel from '@/components/chart/ChartSidePanel.vue'
import KlineLegend from '@/components/chart/KlineLegend.vue'
import { useBridgeStore } from '@/stores/bridge'
import { useChartStore } from '@/stores/chart'

const store = useChartStore()
const bridge = useBridgeStore()

const option = computed<ChartOption | null>(() => {
  if (!store.hasData) return null
  return buildKlineOption({
    times: store.times,
    bars: store.bars,
    mode: store.mode,
    digits: store.digits,
    ma: store.ma,
    volMa5: store.volMa5,
    macd: store.macd,
    signals: store.placedSignals,
    signalsByIndex: store.signalsByIndex,
    changeAt: store.changeAt,
    zoom: store.zoom,
  })
})

/** 加载中且还没有旧图可看时才显示占位；有旧图就保留着别闪。 */
const showEmpty = computed(() => !store.hasData)
const emptyText = computed(() =>
  store.loading ? '加载中...' : '暂无数据（点击行情看板或期权合约加载）',
)

function onChartReady(inst: ChartInstance): void {
  // 悬停联动 legend 与右侧面板。
  // 必须用 ev.dataIndex（全量数据的绝对序号）；dataIndexInside 是缩放窗口
  // 内的相对序号，而默认只显示末尾一段，用它会取到几百根之前的 bar。
  inst.on('updateAxisPointer', (ev: unknown) => {
    const e = ev as { dataIndex?: number; dataIndexInside?: number }
    const i = e.dataIndex ?? e.dataIndexInside
    if (typeof i === 'number') store.setHover(i)
  })
  // 鼠标移出整个图表区：回到最新一根 + 最新报价
  inst.getZr().on('globalout', () => store.setHover(null))

  // 点买卖点的 pin → 跳到该标的的期权 T 型页去挑合约。
  // 买点是「买认购」所以过滤到 CALL，卖点是「买认沽」过滤到 PUT。
  // 行情事件的小三角不带 sigKind，点了不跳。
  inst.on('click', (ev: unknown) => {
    const e = ev as { componentType?: string; data?: { sigKind?: string } }
    if (e.componentType !== 'markPoint') return
    const kind = e.data?.sigKind
    if (kind !== 'buy' && kind !== 'sell') return
    const u = store.atmUnderlying
    if (!u) return // 该标的没有期权（比如指数、或没上期权的 ETF）
    bridge.viewOption(u, kind === 'buy' ? 'call' : 'put')
  })
}

/** macOS 触摸板双指捏合会产生 ctrlKey+wheel，会把整页缩放掉。 */
function blockPageZoom(e: WheelEvent): void {
  if (e.ctrlKey) e.preventDefault()
}

onMounted(() => {
  document.addEventListener('wheel', blockPageZoom, { passive: false })
})

onBeforeUnmount(() => {
  document.removeEventListener('wheel', blockPageZoom)
})
</script>

<template>
  <div class="page">
    <header class="hd">
      <span class="title" data-probe="title">{{ store.title }}</span>
      <span class="hint">滚轮缩放 / 拖动平移 · 红涨绿跌 · 标记为买卖信号</span>
      <span class="spacer" />
      <button class="btn" data-probe="refresh" @click="bridge.requestRefresh()">刷新</button>
    </header>

    <div v-if="store.periods.length" class="period-bar" data-probe="period-bar">
      <button
        v-for="p in store.periods"
        :key="p"
        class="pbtn"
        :class="{ active: p === store.period }"
        :data-period="p"
        @click="bridge.requestPeriod(p)"
      >{{ p }}</button>
    </div>

    <div class="main">
      <div v-if="showEmpty" class="empty" data-probe="empty">{{ emptyText }}</div>
      <template v-else>
        <div class="chart-wrap">
          <EChart
            :option="option"
            height="100%"
            @ready="onChartReady"
            @zoom="store.setZoom"
          />
          <KlineLegend />
        </div>
        <ChartSidePanel />
      </template>
    </div>
  </div>
</template>

<style scoped>
.page {
  display: flex;
  flex: 1;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}

.hd {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  align-items: center;
  padding: 8px 14px;
  border-bottom: 1px solid var(--line);
}

.title {
  color: var(--accent);
  font-size: 16px;
  font-weight: bold;
}

.hint {
  color: var(--fg-weak);
  font-size: 12px;
}

.spacer {
  flex: 1;
}

.btn {
  padding: 5px 14px;
  border: none;
  border-radius: 5px;
  background: #3a3a3a;
  color: var(--fg-strong);
  font-family: var(--font);
  font-size: 13px;
  cursor: pointer;
}

.btn:hover {
  background: var(--accent);
  color: #1a1a1a;
}

.period-bar {
  display: flex;
  gap: 6px;
  padding: 6px 14px;
  border-bottom: 1px solid var(--line);
}

.pbtn {
  padding: 4px 14px;
  border: 1px solid #3a3a3a;
  border-radius: 5px;
  background: #252525;
  color: var(--fg-dim);
  font-family: var(--font);
  font-size: 12px;
  cursor: pointer;
}

.pbtn:hover {
  border-color: var(--accent);
  color: var(--fg-strong);
}

.pbtn.active {
  border-color: var(--accent);
  background: var(--accent);
  color: #1a1a1a;
  font-weight: bold;
}

.main {
  display: flex;
  flex: 1;
  min-height: 0;
}

.chart-wrap {
  position: relative;
  flex: 1;
  min-width: 0;
}

.empty {
  display: flex;
  flex: 1;
  align-items: center;
  justify-content: center;
  color: #666;
  font-size: 15px;
}
</style>
