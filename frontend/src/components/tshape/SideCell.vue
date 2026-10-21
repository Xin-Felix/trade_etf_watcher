<script setup lang="ts">
/**
 * T 型表格里一侧（CALL 或 PUT）的一个合约块。
 *
 * 结构：固定列（最新价 + 涨跌幅 + 买卖加腿按钮）+ 三列指标区。
 * CALL 在左侧，固定列靠右贴着行权价；PUT 反过来。
 *
 * 指标区原来是横向 3 页、要左右滑才能看全（卖买 / 量持仓 / IV Delta）。
 * 改成每列上下两行后 6 个指标一屏全在，不用滑，行高反而更矮。
 */
import { computed } from 'vue'

import type { OptionSide } from '@/bridge/types'
import { fmtIv, trendClass } from '@/utils/format'

const props = defineProps<{
  item: OptionSide | null
  type: 'call' | 'put'
}>()

const emit = defineEmits<{
  open: [code: string, name: string]
  addLeg: [code: string, name: string, side: 'buy' | 'sell']
  copy: [text: string]
}>()

/** price 为 null 就是没行情（0 价在 Python 侧已转 null）。 */
const hasQuote = computed(() => props.item?.price !== null && props.item?.price !== undefined)

/** CALL 的数值靠左、PUT 靠右，视觉上向中间的行权价收拢。 */
const align = computed(() => (props.type === 'call' ? 'l' : 'r'))
const pc = computed(() => (hasQuote.value ? trendClass(props.item?.change_pct) : 'na'))

function f(v: number | null | undefined, d = 4): string {
  return v === null || v === undefined || Number.isNaN(v) ? '--' : v.toFixed(d)
}

function vol(v: number | null | undefined): string {
  return v === null || v === undefined ? '' : `x${v}`
}

function compact(v: number | null | undefined): string {
  if (v === null || v === undefined) return '--'
  if (v >= 1e8) return (v / 1e8).toFixed(2) + '亿'
  if (v >= 1e4) return (v / 1e4).toFixed(1) + '万'
  return String(v)
}

/** 本表占位符是 '--'（fmtIv 缺省是 '-'），传进去保持一致，也才会套上灰字样式。 */
const ivText = computed(() => fmtIv(props.item?.iv, '--'))

const pctText = computed(() => {
  const p = props.item?.change_pct
  if (p === null || p === undefined) return '--'
  return (p > 0 ? '+' : '') + p.toFixed(2) + '%'
})

/**
 * 数值指标三列，每列两行 [标签, 值, 尾注]。
 * 尾注放挂单手数（x12），没有就留空。
 * 第一列（合约代码 + 涨跌幅）渲染方式不同，单独写在模板里。
 */
const cols = computed(() => {
  const it = props.item
  if (!it || !hasQuote.value) {
    return [
      [['卖', '--', ''], ['买', '--', '']],
      [['量', '--', ''], ['持', '--', '']],
      [['IV', '--', ''], ['Δ', '--', '']],
    ]
  }
  return [
    [
      ['卖', f(it.sell_price), vol(it.sell_vol)],
      ['买', f(it.buy_price), vol(it.buy_vol)],
    ],
    [
      ['量', compact(it.volume), ''],
      ['持', compact(it.oi), ''],
    ],
    [
      ['IV', ivText.value, ''],
      ['Δ', f(it.delta), ''],
    ],
  ]
})

/** 悬浮提示：名称代码 / 买卖报价 / 量持仓IV Delta / 操作提示。 */
const tip = computed(() => {
  const it = props.item
  if (!it) return ''
  if (!hasQuote.value) return `${it.name} (${it.code})\n暂无行情\n点击查看分时 K 线`
  return (
    `${it.name} (${it.code})\n` +
    `买 ${f(it.buy_price)} ${vol(it.buy_vol)} / 卖 ${f(it.sell_price)} ${vol(it.sell_vol)}\n` +
    `量 ${it.volume ?? '--'} · 持仓 ${it.oi ?? '--'} · IV ${ivText.value} · Delta ${f(it.delta)}\n` +
    `点击查看分时 K 线`
  )
})

/** 点代码只复制，不连带触发「看 K 线」。 */
function onCopy(): void {
  if (props.item) emit('copy', props.item.code)
}
</script>

<template>
  <div
    class="cblock"
    :class="{ blank: !props.item }"
    :title="tip"
    :data-code="props.item?.code"
    @click="props.item && emit('open', props.item.code, props.item.name)"
  >
    <!-- PUT：固定列在左，贴着中间的行权价 -->
    <div v-if="props.type === 'put'" class="cell fixed l">
      <div class="v" :class="pc">{{ hasQuote ? f(props.item!.price) : '--' }}</div>
      <div class="sub">
        <span v-if="props.item" class="leg-btns" data-stop>
          <button
            class="legbtn b"
            data-probe="add-buy"
            @click.stop="emit('addLeg', props.item!.code, props.item!.name, 'buy')"
          >买</button>
          <button
            class="legbtn s"
            data-probe="add-sell"
            @click.stop="emit('addLeg', props.item!.code, props.item!.name, 'sell')"
          >卖</button>
        </span>
      </div>
    </div>

    <!-- 四列指标，每列上下两行。第一列是合约代码 + 涨跌幅 -->
    <div class="metrics">
      <div class="cell" :class="align">
        <div class="mrow">
          <span
            v-if="props.item"
            class="ocode"
            data-stop
            data-probe="ocode"
            :title="`点击复制合约代码 ${props.item.code}`"
            @click.stop="onCopy"
          >{{ props.item.code }}</span>
          <span v-else class="num na">--</span>
        </div>
        <div class="mrow">
          <span class="num" :class="hasQuote ? pc : 'na'">{{ hasQuote ? pctText : '--' }}</span>
        </div>
      </div>
      <div v-for="(col, ci) in cols" :key="ci" class="cell" :class="align">
        <div v-for="(row, ri) in col" :key="ri" class="mrow">
          <span class="lbl">{{ row[0] }}</span>
          <span class="num" :class="{ na: row[1] === '--' }">{{ row[1] }}</span>
          <span v-if="row[2]" class="qty">{{ row[2] }}</span>
        </div>
      </div>
    </div>

    <!-- CALL：固定列在右，贴着中间的行权价 -->
    <div v-if="props.type === 'call'" class="cell fixed r">
      <div class="v" :class="pc">{{ hasQuote ? f(props.item!.price) : '--' }}</div>
      <div class="sub">
        <span v-if="props.item" class="leg-btns" data-stop>
          <button
            class="legbtn b"
            data-probe="add-buy"
            @click.stop="emit('addLeg', props.item!.code, props.item!.name, 'buy')"
          >买</button>
          <button
            class="legbtn s"
            data-probe="add-sell"
            @click.stop="emit('addLeg', props.item!.code, props.item!.name, 'sell')"
          >卖</button>
        </span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.cblock {
  display: flex;
  flex: 1;
  min-width: 0;
  cursor: pointer;
}

.cblock.blank {
  cursor: default;
}

.cblock + .cblock {
  border-top: 1px dashed var(--line);
}

.cblock:not(.blank):hover {
  background: var(--bg-hover);
}

/* 四列等宽。表头 .thead 里的结构要跟这里一致，否则标题和数据会错位 */
.metrics {
  display: grid;
  flex: 1 1 auto;
  grid-template-columns: repeat(4, 1fr);
  min-width: 0;
}

.cell {
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 1px;
  min-width: 0;
  min-height: 34px;
  padding: 3px 8px;
  overflow: hidden;
}

.cell.fixed {
  flex: 0 0 112px;
}

.cell.l {
  text-align: left;
}

.cell.r {
  text-align: right;
}

/* 指标的一行：标签 + 数值 + 挂单手数 */
.mrow {
  display: flex;
  gap: 4px;
  align-items: baseline;
  overflow: hidden;
  font-size: 11.5px;
  line-height: 1.35;
  white-space: nowrap;
}

.cell.r .mrow {
  justify-content: flex-end;
}

.lbl {
  flex: 0 0 auto;
  color: var(--fg-weak);
  font-size: 10px;
}

.num {
  color: var(--fg-strong);
  font-weight: bold;
}

.qty {
  color: var(--fg-weak);
  font-size: 10px;
}

/* 合约代码：下单要抄到别的软件，点一下就复制 */
.ocode {
  border-bottom: 1px dashed #4a4a4a;
  color: var(--fg-dim);
  font-size: 11.5px;
  font-variant-numeric: tabular-nums;
  letter-spacing: 0.3px;
  cursor: copy;
}

.ocode:hover {
  border-bottom-color: var(--accent);
  color: var(--accent);
}

/* 固定列的最新价 + 涨跌幅 */
.cell .v {
  font-size: 14px;
  font-weight: bold;
  white-space: nowrap;
}

.cell .sub {
  color: var(--fg-weak);
  font-size: 11px;
  white-space: nowrap;
}

.na {
  color: #555;
}

.leg-btns {
  display: inline-flex;
  gap: 3px;
  margin-left: 6px;
}

.legbtn {
  padding: 1px 5px;
  border: 1px solid #3a3a3a;
  border-radius: 3px;
  background: #252525;
  color: #999;
  font-family: var(--font);
  font-size: 10px;
  line-height: 1.5;
  cursor: pointer;
}

.legbtn.b:hover {
  border-color: var(--up);
  color: var(--up);
}

.legbtn.s:hover {
  border-color: var(--down);
  color: var(--down);
}
</style>
