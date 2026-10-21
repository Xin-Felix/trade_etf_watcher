<script setup lang="ts">
/**
 * 期权 T 型报价页。
 *
 * 布局：表头（CALL / 行权价 / PUT 三列）→ 到期月 chips → 表体 →
 * 底部过滤栏 → 策略抽屉。
 *
 * 指标区是三列固定网格（每列两行），表头的 .hmetrics 与表体 SideCell 的
 * .metrics 用同一套列定义，标题才不会和数据错位。
 */
import { computed, onBeforeUnmount, ref } from 'vue'

import SideListTable from '@/components/tshape/SideListTable.vue'
import StrategyPanel from '@/components/tshape/StrategyPanel.vue'
import TshapeTable from '@/components/tshape/TshapeTable.vue'
import { useBridgeStore } from '@/stores/bridge'
import { useTshapeStore } from '@/stores/tshape'
import { fmtNum, fmtPct, trendClass } from '@/utils/format'

const store = useTshapeStore()
const bridge = useBridgeStore()

/** 四列指标的表头，与 SideCell 的列顺序一一对应（每列两行）。 */
const COL_HEADS = ['代码 / 涨跌幅', '卖一 / 买一', '量 / 持仓', 'IV / Delta']

const showList = computed(() => store.filter === 'call' || store.filter === 'put')

function submitStrategy(preset?: string): void {
  bridge.requestStrategy(store.strategyRequest(preset))
}

function onOpenContract(code: string, name: string): void {
  bridge.rowClicked(code, name)
}

function onAddLeg(code: string, name: string, side: 'buy' | 'sell'): void {
  store.addLeg(code, name, side)
  submitStrategy()
}

function backToSpot(): void {
  store.requestScrollToStrip()
}

/** 看标的自己的 K 线。走和点合约同一条回调，Python 按代码格式区分 ETF / 期权。 */
function openUnderlyingChart(): void {
  const u = store.underlying
  if (!u?.code) return
  bridge.rowClicked(u.code, u.name || u.code)
}

/** 复制合约代码后在表头闪一下提示，2 秒后自己消失。 */
const copied = ref('')
let copiedTimer: ReturnType<typeof setTimeout> | null = null

function onCopyCode(text: string): void {
  bridge.copyText(text)
  copied.value = text
  if (copiedTimer) clearTimeout(copiedTimer)
  copiedTimer = setTimeout(() => {
    copied.value = ''
  }, 2000)
}

onBeforeUnmount(() => {
  if (copiedTimer) clearTimeout(copiedTimer)
})
</script>

<template>
  <div class="page" :data-filter="store.filter">
    <header class="hd">
      <span class="title">期权T型</span>
      <!-- 点标的价格看它自己的 K 线。
           原来这里也是「回到现价」，和右边那个按钮重复了 -->
      <span
        v-if="store.underlying && store.underlying.price !== null"
        class="price-chip"
        :class="trendClass(store.underlying.change_pct)"
        :title="`查看 ${store.underlying.name || store.underlying.code} 的 K 线图`"
        data-probe="uprice"
        @click="openUnderlyingChart"
      >
        {{ store.underlying.name || store.underlying.code }}
        {{ fmtNum(store.underlying.price, 3) }}
        {{ fmtPct(store.underlying.change_pct) }}
      </span>
      <span class="meta" data-probe="meta">{{ store.meta }}</span>
      <span v-if="copied" class="copied" data-probe="copied">已复制 {{ copied }}</span>
      <span class="spacer" />
      <button class="btn" data-probe="locate" @click="backToSpot">回到现价</button>
    </header>

    <div v-if="store.expiries.length" class="expiry-bar" data-probe="expiry-bar">
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

    <!-- 表头：三列结构必须和 SideCell 的 .metrics 一致，否则列会错位 -->
    <div v-if="store.hasRows && !showList" class="thead">
      <div class="side-head call-head">
        <div class="side-title">CALL 认购</div>
        <div class="hrow">
          <div class="hmetrics">
            <div v-for="(h, i) in COL_HEADS" :key="i" class="hcell l">{{ h }}</div>
          </div>
          <div class="hcell fixed r">最新价</div>
        </div>
      </div>
      <div class="strike-head">行权价</div>
      <div class="side-head put-head">
        <div class="side-title">PUT 认沽</div>
        <div class="hrow">
          <div class="hcell fixed l">最新价</div>
          <div class="hmetrics">
            <div v-for="(h, i) in COL_HEADS" :key="i" class="hcell r">{{ h }}</div>
          </div>
        </div>
      </div>
    </div>

    <div v-if="!store.hasRows" class="empty" data-probe="empty">{{ store.emptyHint }}</div>
    <SideListTable
      v-else-if="showList"
      :type="store.filter === 'call' ? 'call' : 'put'"
      @open="onOpenContract"
      @add-leg="onAddLeg"
      @copy="onCopyCode"
    />
    <TshapeTable v-else @open="onOpenContract" @add-leg="onAddLeg" @copy="onCopyCode" />

    <div class="filter-bar" data-probe="filter-bar">
      <button
        v-for="f in (['all', 'call', 'put'] as const)"
        :key="f"
        class="fbtn"
        :class="{ active: store.filter === f }"
        :data-filter-btn="f"
        @click="store.setFilter(f)"
      >{{ f === 'all' ? '全部期权' : f === 'call' ? 'CALL 认购' : 'PUT 认沽' }}</button>
      <span class="spacer" />
    </div>

    <StrategyPanel @submit="submitStrategy" />
  </div>
</template>

<style scoped>
.page {
  display: flex;
  flex: 1;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
  font-variant-numeric: tabular-nums;
}

.hd {
  display: flex;
  gap: 10px;
  align-items: center;
  padding: 6px 12px;
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
  font-weight: bold;
  cursor: pointer;
}

.meta {
  color: var(--fg-weak);
  font-size: 12px;
}

.copied {
  padding: 2px 8px;
  border-radius: 4px;
  background: #2d3d2a;
  color: #8bc34a;
  font-size: 12px;
  white-space: nowrap;
}

.spacer {
  flex: 1;
}

.btn {
  padding: 4px 12px;
  border: none;
  border-radius: 5px;
  background: #3a3a3a;
  color: var(--fg-strong);
  font-family: var(--font);
  font-size: 12px;
  cursor: pointer;
}

.btn:hover {
  background: var(--accent);
  color: #1a1a1a;
}

.expiry-bar {
  display: flex;
  flex-shrink: 0;
  gap: 6px;
  padding: 5px 12px;
  overflow-x: auto;
  border-bottom: 1px solid var(--line);
}

.expiry-bar::-webkit-scrollbar {
  height: 4px;
}

.chip {
  padding: 4px 12px;
  border: 1px solid #3a3a3a;
  border-radius: 5px;
  background: #252525;
  color: var(--fg-dim);
  font-size: 12px;
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

.thead {
  display: grid;
  flex-shrink: 0;
  grid-template-columns: 1fr 84px 1fr;
  /* 表体被纵向滚动条挤窄了，表头要留出同样的宽度，列才对得齐
     （变量由 TshapeTable 量出来写入） */
  padding-right: var(--tshape-sbw, 0px);
  border-bottom: 2px solid var(--accent);
  background: #252525;
}

.side-head {
  min-width: 0;
  padding: 4px 0 3px;
}

.side-title {
  margin: 0 8px 2px;
  font-size: 12px;
  font-weight: bold;
}

.call-head .side-title {
  color: var(--up);
}

.put-head .side-title {
  color: var(--down);
  text-align: right;
}

.strike-head {
  display: flex;
  align-items: flex-end;
  justify-content: center;
  padding-bottom: 4px;
  color: var(--fg-weak);
  font-size: 12px;
}

.hrow {
  display: flex;
  min-width: 0;
}

.hcell {
  padding: 0 8px;
  overflow: hidden;
  color: var(--fg-weak);
  font-size: 11px;
  white-space: nowrap;
}

.hcell.fixed {
  flex: 0 0 112px;
}

.hcell.l {
  text-align: left;
}

.hcell.r {
  text-align: right;
}

/* 表头的指标区，四列等宽，与 SideCell 的 .metrics 对齐 */
.hmetrics {
  display: grid;
  flex: 1 1 auto;
  grid-template-columns: repeat(4, 1fr);
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

.filter-bar {
  display: flex;
  flex-shrink: 0;
  gap: 8px;
  align-items: center;
  padding: 5px 12px;
  border-top: 1px solid var(--line);
}

.fbtn {
  flex: 0 0 auto;
  padding: 5px 18px;
  font-size: 12px;
  border: 1px solid #3a3a3a;
  border-radius: 5px;
  background: #252525;
  color: var(--fg-dim);
  font-family: var(--font);
  cursor: pointer;
}

.fbtn.active {
  border-color: var(--accent);
  background: var(--accent);
  color: #1a1a1a;
  font-weight: bold;
}

</style>

<style>
/* 方向过滤时把另一侧留白（不用 display:none，避免行高塌陷导致错位） */
.page[data-filter='call'] .side.put,
.page[data-filter='put'] .side.call {
  visibility: hidden;
}
</style>
