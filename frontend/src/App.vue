<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { installRenderHandlers } from '@/bridge'
import type {
  AnalysisPayload,
  ChartPayload,
  QuotesPayload,
  StrategyPayload,
  TShapePayload,
} from '@/bridge/types'
import { useAnalysisStore } from '@/stores/analysis'
import { useBridgeStore } from '@/stores/bridge'
import { useChartStore } from '@/stores/chart'
import { useQuotesStore } from '@/stores/quotes'
import { useTshapeStore } from '@/stores/tshape'

import { initialRoute, ROUTE_TITLES, type RouteName } from './routes'
import AnalysisView from './views/AnalysisView.vue'
import ChartView from './views/ChartView.vue'
import Placeholder from './views/Placeholder.vue'
import QuotesView from './views/QuotesView.vue'
import TshapeView from './views/TshapeView.vue'

const route = ref<RouteName>(initialRoute())
const bridge = useBridgeStore()
const quotes = useQuotesStore()
const analysis = useAnalysisStore()
const chart = useChartStore()
const tshape = useTshapeStore()

onMounted(async () => {
  // 先注册渲染入口再连通道：Python 可能在 mount 之前就推过数据，
  // installRenderHandlers 会把 index.html 缓存的那批重放出来。
  installRenderHandlers({
    renderQuotes: (p: QuotesPayload) => {
      quotes.apply(p)
      bridge.notePush(`renderQuotes:${p.quotes?.length ?? 0}条`)
    },
    renderAnalysis: (p: AnalysisPayload) => {
      analysis.apply(p)
      bridge.notePush(`renderAnalysis:${p.expiries?.length ?? 0}月`)
    },
    updateChart: (p: ChartPayload) => {
      chart.apply(p)
      bridge.notePush(`updateChart:${p.bars?.length ?? 0}根`)
    },
    renderTShape: (p: TShapePayload) => {
      tshape.apply(p)
      bridge.notePush(`renderTShape:${p.expiries?.length ?? 0}月`)
      // 行情每轮都推，但没必要每次都让 Python 重算策略：
      // 篮子空着就只有首次（为了取预设列表）才发。
      if (tshape.shouldResubmitOnRefresh()) {
        bridge.requestStrategy(tshape.strategyRequest())
      }
    },
    renderStrategy: (p: StrategyPayload) => {
      tshape.applyStrategy(p)
      bridge.notePush(`renderStrategy:${p.legs?.length ?? 0}腿`)
    },
  })
  await bridge.connect()

  // 探针：验收脚本据此确认 Vue 真的 mount 了（而不是白屏）
  document.documentElement.dataset.rjdjMounted = '1'
})
</script>

<template>
  <div class="app-root">
    <QuotesView v-if="route === 'quotes'" />
    <AnalysisView v-else-if="route === 'analysis'" />
    <ChartView v-else-if="route === 'chart'" />
    <TshapeView v-else-if="route === 'tshape'" />
    <Placeholder v-else :route="route" :title="ROUTE_TITLES[route]" />
  </div>
</template>

<style scoped>
.app-root {
  height: 100%;
  display: flex;
  flex-direction: column;
  min-height: 0;
}
</style>
