<script setup lang="ts">
/**
 * 策略工具抽屉：左边预设 + 篮子，右边指标 + 到期损益图。
 */
import { computed } from 'vue'

import type { ChartOption } from '@/chart/echarts'
import { axisLabel, axisLine, baseOption, darkTooltip, labelInterval, splitLine } from '@/chart/presets'
import EChart from '@/components/EChart.vue'
import { useTshapeStore } from '@/stores/tshape'

const store = useTshapeStore()

const emit = defineEmits<{
  submit: [preset?: string]
}>()

/** 金额格式化：≥1 万转「x.xx万」，null 表示理论无限。 */
function money(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '无限'
  const a = Math.abs(v)
  const s = v > 0 ? '+' : v < 0 ? '-' : ''
  if (a >= 10000) return `${s}${(a / 10000).toFixed(2)}万`
  return `${s}${a.toFixed(0)}`
}

const msg = computed(() => {
  const s = store.strategy
  if (!s) return ''
  if (s.error) return s.error
  if (s.empty) return '篮子是空的，加腿后这里显示损益图与指标。'
  return ''
})

const metrics = computed(() => {
  const s = store.strategy
  if (!s || s.error || s.empty || !s.summary) return []
  const sm = s.summary
  const g = s.greeks
  const d = s.decay
  const cost = sm.netCost || 0
  const costTxt =
    cost >= 0 ? `支出 ${money(cost).replace('+', '')}` : `收入 ${money(-cost).replace('+', '')}`
  const be = (sm.breakevens || []).map((v) => v.toFixed(3)).join(' / ') || '--'
  const perDay = d?.perDay ?? 0
  return [
    { k: '净成本', v: costTxt, c: cost >= 0 ? 'flat' : 'up' },
    { k: '最大盈利', v: sm.maxProfit === null ? '理论无限' : money(sm.maxProfit), c: 'up' },
    { k: '最大亏损', v: sm.maxLoss === null ? '理论无限' : money(sm.maxLoss), c: 'down' },
    { k: '盈亏平衡', v: be, c: 'flat' },
    { k: '每日时间损耗', v: `${money(perDay)} 元/天`, c: perDay >= 0 ? 'up' : 'down' },
    { k: 'Delta', v: `${(g?.delta ?? 0).toFixed(0)} 元/元`, c: (g?.delta ?? 0) >= 0 ? 'up' : 'down' },
    { k: 'Vega', v: `${(g?.vega ?? 0).toFixed(0)} 元/1%`, c: (g?.vega ?? 0) >= 0 ? 'up' : 'down' },
    {
      k: '风险报酬比',
      v: sm.riskReward === null || sm.riskReward === undefined ? '--' : `${sm.riskReward.toFixed(2)} : 1`,
      c: 'flat',
    },
  ]
})

const payoffOption = computed<ChartOption | null>(() => {
  const s = store.strategy
  if (!s || s.error || s.empty || !s.curve?.length) return null
  const xs = s.curve.map((c) => c.s)
  const ys = s.curve.map((c) => c.p)
  const spot = s.spot ?? 0
  const items = s.decay?.items ?? []

  return {
    ...baseOption(),
    grid: { left: 58, right: 16, top: 26, bottom: 26 },
    tooltip: darkTooltip({
      trigger: 'axis',
      formatter: (ps: Array<{ axisValue: string; data: number }>) => {
        if (!ps?.length) return ''
        const x = Number(ps[0]!.axisValue)
        const v = ps[0]!.data
        const pct = spot > 0 ? ((x / spot - 1) * 100).toFixed(2) : '--'
        const c = v >= 0 ? '#ef5350' : '#26a69a'
        const sign = Number(pct) >= 0 ? '+' : ''
        return (
          `标的 ${x.toFixed(3)}（${sign}${pct}%）<br/>` +
          `到期损益 <span style="color:${c}">${money(v)} 元</span>`
        )
      },
    }),
    xAxis: {
      type: 'category',
      data: xs.map((v) => v.toFixed(3)),
      boundaryGap: false,
      axisLine,
      axisLabel: axisLabel({ interval: labelInterval(xs.length, 8) }),
    },
    yAxis: {
      type: 'value',
      splitLine,
      axisLabel: axisLabel({ formatter: (v: number) => money(v) }),
    },
    series: [
      {
        name: '到期损益',
        type: 'line',
        data: ys,
        symbol: 'none',
        lineStyle: { width: 2, color: '#ff9800' },
        areaStyle: { color: 'rgba(255,152,0,0.10)' },
        markLine: {
          symbol: 'none',
          silent: true,
          data: [
            { yAxis: 0, lineStyle: { color: '#666', type: 'solid', width: 1 } },
            ...(spot > 0
              ? [
                  {
                    xAxis: spot.toFixed(3),
                    lineStyle: { color: '#4fc3f7', type: 'dashed', width: 1 },
                    label: {
                      show: true,
                      formatter: '现价',
                      color: '#4fc3f7',
                      fontSize: 10,
                      position: 'insideEndTop',
                    },
                  },
                ]
              : []),
            ...(s.summary?.breakevens ?? []).map((b) => ({
              xAxis: b.toFixed(3),
              lineStyle: { color: '#9c27b0', type: 'dotted', width: 1 },
            })),
          ],
        },
      },
    ],
    // 副标题借 title 位显示「标的不动」的时间损耗，一眼看到持有成本
    title: {
      text: items.length
        ? `标的不动：1天 ${money(items[0]?.pnl)} · 3天 ${money(items[1]?.pnl)} · 7天 ${money(items[2]?.pnl)}`
        : '',
      left: 'center',
      top: 4,
      textStyle: { color: '#888', fontSize: 11, fontWeight: 'normal' },
    },
  }
})

function f(v: number | null | undefined, d = 4): string {
  return v === null || v === undefined || Number.isNaN(v) ? '--' : v.toFixed(d)
}
</script>

<template>
  <section class="strat" :class="{ collapsed: store.stratCollapsed }">
    <div class="head" data-probe="strat-head" @click="store.toggleStrat()">
      <span class="t">策略组合</span>
      <span class="cnt" data-probe="strat-cnt">{{ store.basketSummary }}</span>
      <span class="spacer" />
      <button
        class="btn"
        data-probe="strat-clear"
        @click.stop="store.clearBasket(); emit('submit')"
      >清空</button>
      <span class="toggle">{{ store.stratCollapsed ? '▲' : '▼' }}</span>
    </div>

    <div v-show="!store.stratCollapsed" class="body">
      <div class="left">
        <div class="presets" data-probe="preset-bar">
          <button
            v-for="p in store.presets"
            :key="p.key"
            class="prebtn"
            :title="p.desc"
            :data-preset="p.key"
            @click="store.clearBasket(); emit('submit', p.key)"
          >{{ p.label }}</button>
        </div>

        <div class="basket" data-probe="basket">
          <div v-if="store.basket.length === 0" class="basket-empty">
            篮子是空的。点上面预设策略，或在表格行里点「买」「卖」。
          </div>
          <div
            v-for="(l, i) in store.basket"
            :key="`${l.code}-${l.side}`"
            class="bleg"
            data-probe="basket-leg"
          >
            <span
              class="sd"
              :class="l.side"
              title="点击切换买/卖"
              data-probe="flip-leg"
              @click="store.flipLeg(i); emit('submit')"
            >{{ l.side === 'buy' ? '买' : '卖' }}</span>
            <span class="nm" :title="`${l.name} ${l.code}`">{{ l.name || l.code }}</span>
            <input
              class="qty"
              type="number"
              min="1"
              max="999"
              :value="l.qty"
              data-probe="leg-qty"
              @change="store.setQty(i, ($event.target as HTMLInputElement).value); emit('submit')"
            />
            <span class="px">{{ f(l.price) }}</span>
            <button
              class="del"
              title="移除"
              data-probe="del-leg"
              @click="store.removeLeg(i); emit('submit')"
            >✕</button>
          </div>
        </div>
      </div>

      <div class="right">
        <div v-if="metrics.length" class="metrics" data-probe="metrics">
          <div v-for="m in metrics" :key="m.k" class="m">
            <div class="k">{{ m.k }}</div>
            <div class="v" :class="m.c">{{ m.v }}</div>
          </div>
        </div>
        <!-- 包一层给出确定高度：抽屉用的是 max-height，直接给 EChart
             height:100% 会算成 0，图表就不会初始化（旧版这里是 flex:1 + min-height） -->
        <div v-if="payoffOption" class="payoff" data-probe="payoff">
          <EChart :option="payoffOption" height="100%" />
        </div>
        <div v-if="msg" class="msg" data-probe="strat-msg">{{ msg }}</div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.strat {
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
  max-height: 55vh;
  overflow: hidden;
  border-top: 2px solid var(--accent);
  background: #1a1a1a;
}

.head {
  display: flex;
  gap: 10px;
  align-items: center;
  padding: 7px 14px;
  background: #252525;
  cursor: pointer;
}

.head .t {
  color: var(--accent);
  font-size: 13px;
  font-weight: bold;
}

.head .cnt {
  color: var(--fg-weak);
  font-size: 12px;
}

.spacer {
  flex: 1;
}

.head .toggle {
  color: var(--fg-weak);
}

.btn {
  padding: 3px 10px;
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

.body {
  display: flex;
  min-height: 0;
  overflow: hidden;
}

.left {
  display: flex;
  flex: 0 0 46%;
  flex-direction: column;
  min-width: 0;
  overflow-y: auto;
  border-right: 1px solid var(--line);
}

.presets {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  padding: 8px 10px;
  border-bottom: 1px solid #2a2a2a;
}

.prebtn {
  padding: 4px 9px;
  border: 1px solid #3a3a3a;
  border-radius: 4px;
  background: #252525;
  color: #bbb;
  font-family: var(--font);
  font-size: 11px;
  white-space: nowrap;
  cursor: pointer;
}

.prebtn:hover {
  border-color: var(--accent);
  color: var(--fg-strong);
}

.basket {
  flex: 1;
  padding: 4px 10px 8px;
  overflow-y: auto;
}

.basket-empty {
  padding: 14px 2px;
  color: #555;
  font-size: 12px;
}

.bleg {
  display: flex;
  gap: 6px;
  align-items: center;
  padding: 5px 0;
  border-bottom: 1px solid #262626;
  font-size: 12px;
}

.bleg .sd {
  flex: 0 0 auto;
  padding: 1px 6px;
  border: 1px solid transparent;
  border-radius: 3px;
  font-size: 10px;
  font-weight: bold;
  cursor: pointer;
}

.bleg .sd.buy {
  border-color: var(--up);
  background: rgba(239, 83, 80, 0.18);
  color: var(--up);
}

.bleg .sd.sell {
  border-color: var(--down);
  background: rgba(38, 166, 154, 0.18);
  color: var(--down);
}

.bleg .nm {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.bleg .qty {
  flex: 0 0 46px;
  padding: 2px 4px;
  border: 1px solid #3a3a3a;
  border-radius: 3px;
  background: #202020;
  color: #eee;
  font-family: var(--font);
  font-size: 11px;
  text-align: center;
}

.bleg .px {
  flex: 0 0 58px;
  color: var(--fg-dim);
  font-variant-numeric: tabular-nums;
  text-align: right;
}

.bleg .del {
  flex: 0 0 auto;
  border: none;
  background: none;
  color: #666;
  font-size: 13px;
  cursor: pointer;
}

.bleg .del:hover {
  color: var(--up);
}

.right {
  display: flex;
  flex: 1;
  flex-direction: column;
  min-width: 0;
}

.metrics {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 1px;
  background: #2a2a2a;
}

.m {
  min-width: 0;
  padding: 6px 9px;
  background: var(--bg);
}

.m .k {
  color: #777;
  font-size: 10px;
  white-space: nowrap;
}

.m .v {
  overflow: hidden;
  font-size: 13px;
  font-weight: bold;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.payoff {
  flex: 1;
  min-height: 150px;
}

.msg {
  padding: 12px 14px;
  color: var(--fg-weak);
  font-size: 12px;
}
</style>
