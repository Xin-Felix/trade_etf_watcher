<script setup lang="ts">
/**
 * 卖方指标面板：14 张卡片。
 *
 * 阈值与文案逐条照搬旧版 analysis.html 的 renderSeller —— 这些是产品知识
 * （多少算恐慌、PCR 到哪算拥挤），不是可以随手改的样式。
 *
 * 口径提醒：SellerMetrics 里还有 totalGamma/totalTheta/totalVega 三个字段，
 * 旧版刻意没做成卡片，因为 option_meta.py 里它们是 Σ|delta|×OI / Σ IV×OI 的
 * 近似，单位不统一，展示出来会误导。这里保持不展示。
 */
import { computed } from 'vue'

import type { SellerMetrics } from '@/bridge/types'
import { fmtCompact } from '@/utils/format'

const props = defineProps<{ data: SellerMetrics }>()

type CardCls = 'up' | 'down' | 'neutral' | 'warn'

interface Card {
  label: string
  value: string
  cls: CardCls
  note: string
}

const DASH = '--'

function pct(v: number | null, digits = 2): string {
  return v === null ? DASH : v.toFixed(digits) + '%'
}

/** 本页占位符是 '--'，而 fmtCompact 缺省用 '-'，这里统一一下。 */
function compact(v: number | null): string {
  return v === null ? DASH : fmtCompact(v)
}

function buildCards(d: SellerMetrics): Card[] {
  const out: Card[] = []

  out.push({
    label: '平值 IV',
    value: pct(d.atmIV, 1),
    cls: 'neutral',
    note: 'ATM Call/Put IV 均值',
  })

  // 25Δ 偏斜：正值 = Put 更贵 = 市场在为下跌付费
  let skewCls: CardCls = 'neutral'
  let skewNote = 'Put 25Δ IV − Call 25Δ IV'
  if (d.skew25D !== null) {
    if (d.skew25D > 5) {
      skewCls = 'up'
      skewNote += ' · 偏斜较大(恐慌)'
    } else if (d.skew25D > 2) {
      skewCls = 'warn'
      skewNote += ' · 轻微偏斜'
    } else {
      skewCls = 'down'
      skewNote += ' · 偏斜正常'
    }
  }
  out.push({ label: '25Δ 偏斜', value: pct(d.skew25D), cls: skewCls, note: skewNote })

  let pcrCls: CardCls = 'neutral'
  let pcrNote = 'Put/Call 持仓量比'
  if (d.pcrOI !== null) {
    if (d.pcrOI >= 1.5) {
      pcrCls = 'up'
      pcrNote += ' · 极度看空信号'
    } else if (d.pcrOI >= 1.0) {
      pcrCls = 'warn'
      pcrNote += ' · Put拥挤'
    } else if (d.pcrOI <= 0.5) {
      pcrCls = 'down'
      pcrNote += ' · 极度看多信号'
    } else {
      pcrNote += ' · 正常'
    }
  }
  out.push({
    label: 'PCR 持仓',
    value: d.pcrOI === null ? DASH : d.pcrOI.toFixed(3),
    cls: pcrCls,
    note: pcrNote,
  })

  out.push({
    label: '预期波动',
    value: d.expectedMove === null ? DASH : '±' + d.expectedMove.toFixed(2) + '%',
    cls: 'warn',
    note: 'ATM跨式/标的价 · 到期前隐含涨跌',
  })

  out.push({
    label: 'Call 总持仓',
    value: compact(d.totalCallOI),
    cls: 'down',
    note: '全月 Call 持仓量',
  })
  out.push({
    label: 'Put 总持仓',
    value: compact(d.totalPutOI),
    cls: 'up',
    note: '全月 Put 持仓量',
  })

  let pcrVolCls: CardCls = 'neutral'
  let pcrVolNote = 'Put/Call 成交量比'
  if (d.pcrVol !== null) {
    if (d.pcrVol >= 1.5) {
      pcrVolCls = 'up'
      pcrVolNote += ' · 看空情绪浓'
    } else if (d.pcrVol >= 1.0) {
      pcrVolCls = 'warn'
      pcrVolNote += ' · Put交易活跃'
    } else if (d.pcrVol <= 0.5) {
      pcrVolCls = 'down'
      pcrVolNote += ' · 看多情绪浓'
    } else {
      pcrVolNote += ' · 正常'
    }
  }
  out.push({
    label: 'PCR 成交量',
    value: d.pcrVol === null ? DASH : d.pcrVol.toFixed(3),
    cls: pcrVolCls,
    note: pcrVolNote,
  })

  out.push({
    label: 'Call 成交量',
    value: compact(d.totalCallVol),
    cls: 'down',
    note: '全月 Call 成交（张）',
  })
  out.push({
    label: 'Put 成交量',
    value: compact(d.totalPutVol),
    cls: 'up',
    note: '全月 Put 成交（张）',
  })

  let skewRCls: CardCls = 'neutral'
  let skewRNote = '虚值Put IV / ATM IV'
  if (d.ivSkewRatio !== null) {
    if (d.ivSkewRatio >= 1.5) {
      skewRCls = 'up'
      skewRNote += ' · 尾部风险定价高（恐慌）'
    } else if (d.ivSkewRatio >= 1.2) {
      skewRCls = 'warn'
      skewRNote += ' · 适度偏斜'
    } else {
      skewRNote += ' · 正常'
    }
  }
  out.push({
    label: 'IV Skew',
    value: d.ivSkewRatio === null ? DASH : d.ivSkewRatio.toFixed(2) + 'x',
    cls: skewRCls,
    note: skewRNote,
  })

  out.push({
    label: '虚值Put IV',
    value: pct(d.otmPutIV),
    cls: 'neutral',
    note: '15Δ Put 隐含波动率',
  })
  out.push({
    label: '时间价值比',
    value: pct(d.timeValueRatio, 1),
    cls: 'neutral',
    note: 'ATM Call 时间价值/权利金',
  })

  out.push({
    label: '净 Delta',
    value: compact(d.netDelta),
    cls: d.netDelta === null ? 'neutral' : d.netDelta > 0 ? 'up' : d.netDelta < 0 ? 'down' : 'neutral',
    note: '全月持仓 Delta 敞口（正=多头主导）',
  })

  // GEX 正负决定波动是收敛还是放大，对卖方最关键，所以颜色和涨跌反过来：
  // 正 GEX（波动收敛）对卖方是好事，用绿色
  let gexCls: CardCls = 'neutral'
  let gexNote = '做市商 Gamma 敞口方向'
  if (d.gammaExposure !== null) {
    if (d.gammaExposure > 0) {
      gexCls = 'down'
      gexNote += ' · 正GEX：波动收敛（利于卖方）'
    } else if (d.gammaExposure < 0) {
      gexCls = 'up'
      gexNote += ' · 负GEX：波动放大（卖方危险）'
    }
  }
  out.push({
    label: 'Gamma Exp',
    value: d.gammaExposure === null ? DASH : d.gammaExposure.toFixed(2),
    cls: gexCls,
    note: gexNote,
  })

  return out
}

const cards = computed<Card[]>(() => buildCards(props.data))
</script>

<template>
  <div class="cards" data-probe="seller-cards">
    <div v-for="c in cards" :key="c.label" class="s-card" data-probe="seller-card">
      <div class="s-label">{{ c.label }}</div>
      <div class="s-value" :class="c.cls">{{ c.value }}</div>
      <div class="s-note">{{ c.note }}</div>
    </div>
  </div>
</template>

<style scoped>
.cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(165px, 1fr));
  gap: 8px;
  padding: 12px 14px;
}

.s-card {
  padding: 10px 12px;
  border: 1px solid #3a3a3a;
  border-radius: 6px;
  background: #252525;
}

.s-label {
  margin-bottom: 3px;
  color: var(--fg-weak);
  font-size: 11px;
}

.s-value {
  font-size: 16px;
  font-weight: bold;
  font-variant-numeric: tabular-nums;
}

.s-note {
  margin-top: 3px;
  color: #666;
  font-size: 10px;
}

.s-value.up {
  color: var(--up);
}

.s-value.down {
  color: var(--down);
}

.s-value.neutral {
  color: var(--fg);
}

.s-value.warn {
  color: var(--accent);
}
</style>
