<script setup lang="ts">
/**
 * 单方向列表视图。
 * 过滤成只看 CALL 或只看 PUT 时，T 型的对称布局就没意义了，
 * 换成平铺表格，指标和 T 型视图保持同一套（卖一/买一 · 量/持仓 · IV/Delta）。
 */
import { ref } from 'vue'

import { useStripScroll } from '@/composables/useStripScroll'
import { useTshapeStore } from '@/stores/tshape'
import { fmtIv, fmtNum, fmtPct, trendClass } from '@/utils/format'

const props = defineProps<{ type: 'call' | 'put' }>()

const store = useTshapeStore()

const wrap = ref<HTMLDivElement | null>(null)
useStripScroll(wrap)

const emit = defineEmits<{
  open: [code: string, name: string]
  addLeg: [code: string, name: string, side: 'buy' | 'sell']
  copy: [text: string]
}>()

function f(v: number | null | undefined, d = 4): string {
  return v === null || v === undefined || Number.isNaN(v) ? '--' : v.toFixed(d)
}

function compact(v: number | null | undefined): string {
  if (v === null || v === undefined) return '--'
  if (v >= 1e8) return (v / 1e8).toFixed(2) + '亿'
  if (v >= 1e4) return (v / 1e4).toFixed(1) + '万'
  return String(v)
}


</script>

<template>
  <div ref="wrap" class="wrap" data-probe="list-view">
    <table class="list-table">
      <thead>
        <tr>
          <th>行权价</th>
          <th>合约代码</th>
          <th>最新价</th>
          <th>涨跌幅</th>
          <th>卖一价*数</th>
          <th>买一价*数</th>
          <th>量</th>
          <th>持仓</th>
          <th>IV</th>
          <th>Delta</th>
          <th>加腿</th>
        </tr>
      </thead>
      <tbody>
        <template v-for="(r, i) in store.rows" :key="r.strike">
          <tr
            v-if="i === store.stripIndex"
            class="strip-row"
            :class="trendClass(store.underlying?.change_pct)"
            data-probe="strip"
          >
            <td colspan="11">
              现价： {{ fmtNum(store.spot, 3) }} {{ fmtPct(store.underlying?.change_pct) }}
            </td>
          </tr>
          <tr
            v-for="item in props.type === 'call' ? r.calls : r.puts"
            :key="item.code"
            class="list-row"
            :data-code="item.code"
            :title="`${item.name} (${item.code})\n点击查看分时 K 线`"
            @click="emit('open', item.code, item.name)"
          >
            <td class="strike-col">{{ fmtNum(r.strike, 3) }}</td>
            <td>
              <span
                class="ocode"
                data-stop
                data-probe="ocode"
                :title="`点击复制合约代码 ${item.code}`"
                @click.stop="emit('copy', item.code)"
              >{{ item.code }}</span>
            </td>
            <td class="bold" :class="trendClass(item.change_pct)">{{ f(item.price) }}</td>
            <td class="bold" :class="trendClass(item.change_pct)">{{ fmtPct(item.change_pct) }}</td>
            <td>
              {{ f(item.sell_price) }}<span class="sub"> x{{ item.sell_vol ?? '--' }}</span>
            </td>
            <td>
              {{ f(item.buy_price) }}<span class="sub"> x{{ item.buy_vol ?? '--' }}</span>
            </td>
            <td>{{ compact(item.volume) }}</td>
            <td>{{ compact(item.oi) }}</td>
            <td>{{ fmtIv(item.iv, '--') }}</td>
            <td>{{ f(item.delta) }}</td>
            <td>
              <span class="leg-btns" data-stop>
                <button
                  class="legbtn b"
                  data-probe="add-buy"
                  @click.stop="emit('addLeg', item.code, item.name, 'buy')"
                >买</button>
                <button
                  class="legbtn s"
                  data-probe="add-sell"
                  @click.stop="emit('addLeg', item.code, item.name, 'sell')"
                >卖</button>
              </span>
            </td>
          </tr>
        </template>
      </tbody>
    </table>
  </div>
</template>

<style scoped>
.wrap {
  flex: 1;
  overflow-y: auto;
}

.list-table {
  width: 100%;
  border-collapse: collapse;
  font-variant-numeric: tabular-nums;
}

.list-table thead th {
  position: sticky;
  top: 0;
  z-index: 1;
  padding: 7px 10px;
  border-bottom: 2px solid var(--accent);
  background: var(--bg-panel);
  color: var(--accent);
  font-size: 12px;
  font-weight: bold;
  text-align: center;
  white-space: nowrap;
}

.list-table tbody td {
  padding: 5px 10px;
  border-bottom: 1px solid var(--line-soft);
  font-size: 12px;
  text-align: center;
  white-space: nowrap;
}

.list-row {
  cursor: pointer;
}

.list-row:nth-child(even) {
  background: var(--bg-row-alt);
}

.list-row:hover {
  background: var(--bg-hover);
}

.strike-col {
  color: var(--fg);
  font-weight: bold;
}

.bold {
  font-weight: bold;
}

.sub {
  color: var(--fg-weak);
  font-size: 10px;
}

/* 合约代码：下单要抄到别的软件，点一下就复制 */
.ocode {
  border-bottom: 1px dashed #4a4a4a;
  color: var(--fg-dim);
  letter-spacing: 0.3px;
  cursor: copy;
}

.ocode:hover {
  border-bottom-color: var(--accent);
  color: var(--accent);
}

.strip-row td {
  padding: 7px;
  border-top: 1px solid #3a3a3a;
  border-bottom: 1px solid #3a3a3a;
  font-weight: bold;
  letter-spacing: 1px;
  text-align: center;
}

.strip-row.up td {
  background: rgba(239, 83, 80, 0.08);
  color: var(--up);
}

.strip-row.down td {
  background: rgba(38, 166, 154, 0.08);
  color: var(--down);
}

.strip-row.flat td {
  background: #252525;
  color: var(--fg-dim);
}

.leg-btns {
  display: inline-flex;
  gap: 3px;
}

.legbtn {
  padding: 1px 6px;
  border: 1px solid #3a3a3a;
  border-radius: 3px;
  background: #252525;
  color: #999;
  font-family: var(--font);
  font-size: 10px;
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
