<script setup lang="ts">
/**
 * 期权分析页。
 *
 * payload 直接用 Python 的 build_tshape_data 产物（与 T 型页同一份），
 * 这页只消费 smile / oi / seller / ivTerm / surface 这几块。
 */
import OiPanel from '@/components/analysis/OiPanel.vue'
import PanelBox from '@/components/analysis/PanelBox.vue'
import SellerPanel from '@/components/analysis/SellerPanel.vue'
import SmileAllPanel from '@/components/analysis/SmileAllPanel.vue'
import SmilePanel from '@/components/analysis/SmilePanel.vue'
import SurfacePanel from '@/components/analysis/SurfacePanel.vue'
import TermPanel from '@/components/analysis/TermPanel.vue'
import { useAnalysisStore } from '@/stores/analysis'
import { fmtNum, fmtPct, trendClass } from '@/utils/format'

const store = useAnalysisStore()
</script>

<template>
  <div class="page">
    <header class="hd">
      <span class="title">期权分析</span>
      <span
        v-if="store.underlying && store.underlying.price !== null"
        class="price-chip"
        :class="trendClass(store.underlying.change_pct)"
        data-probe="uprice"
      >
        {{ store.underlying.name || store.underlying.code }}
        {{ fmtNum(store.underlying.price, 3) }}
        {{ fmtPct(store.underlying.change_pct) }}
      </span>
      <span class="meta" data-probe="meta">{{ store.meta }}</span>
    </header>

    <div v-if="store.hasExpiries" class="expiry-bar" data-probe="expiry-bar">
      <span
        v-for="e in store.expiries"
        :key="e.date"
        class="chip"
        :class="{ active: e.date === store.expiry }"
        :data-expiry="e.date"
        data-probe="expiry-chip"
        @click="store.selectExpiry(e.date)"
      >{{ e.label }}{{ e.days !== null ? `(${e.days})` : '' }}</span>
    </div>

    <div class="content">
      <div v-if="!store.hasExpiries" class="empty" data-probe="empty">
        暂无数据（先在左侧选择 ETF 期权标的）
      </div>

      <template v-else>
        <PanelBox v-if="store.available.seller" id="seller" :hint="store.sellerHint">
          <SellerPanel :data="store.seller!" />
        </PanelBox>

        <PanelBox v-if="store.available.smile" id="smile" :hint="store.smileHint">
          <SmilePanel />
        </PanelBox>

        <PanelBox v-if="store.available.oi" id="oi" :hint="store.oiHint">
          <OiPanel />
        </PanelBox>

        <PanelBox
          v-if="store.available.smileAll"
          id="smileAll"
          hint="各到期月 IV 曲线叠加"
        >
          <SmileAllPanel />
        </PanelBox>

        <PanelBox
          v-if="store.available.surface"
          id="surface"
          hint="到期月 × 行权价 热力图"
        >
          <SurfacePanel />
        </PanelBox>

        <PanelBox v-if="store.available.term" id="term" :hint="store.termHint">
          <TermPanel />
        </PanelBox>
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
  /* 数字等宽，各面板的数值才对得齐 */
  font-variant-numeric: tabular-nums;
}

.hd {
  display: flex;
  gap: 12px;
  align-items: center;
  padding: 8px 14px;
  border-bottom: 1px solid var(--line);
}

.title {
  color: var(--accent);
  font-size: 15px;
  font-weight: bold;
}

.price-chip {
  padding: 3px 10px;
  border: 1px solid #3a3a3a;
  border-radius: 4px;
  background: #252525;
  font-size: 13px;
  font-weight: bold;
}

.meta {
  color: var(--fg-weak);
  font-size: 12px;
}

.expiry-bar {
  display: flex;
  flex-shrink: 0;
  gap: 8px;
  padding: 8px 14px;
  overflow-x: auto;
  border-bottom: 1px solid var(--line);
}

.chip {
  padding: 5px 14px;
  border: 1px solid #3a3a3a;
  border-radius: 5px;
  background: #252525;
  color: var(--fg-dim);
  white-space: nowrap;
  cursor: pointer;
}

.chip:hover {
  border-color: var(--accent);
  color: var(--fg-strong);
}

.chip.active {
  border-color: var(--accent);
  background: #2d2519;
  color: var(--accent);
  font-weight: bold;
}

.content {
  flex: 1;
  overflow-y: auto;
  min-height: 0;
}

.empty {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 60px 0;
  color: #666;
  font-size: 15px;
  text-align: center;
}
</style>
