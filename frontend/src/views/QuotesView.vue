<script setup lang="ts">
import { computed } from 'vue'

import { SIGNAL_PERIODS } from '@/bridge/types'
import SignalBadge from '@/components/SignalBadge.vue'
import { useBridgeStore } from '@/stores/bridge'
import { useQuotesStore, type DisplayRow } from '@/stores/quotes'
import { devClass, fmtChg, fmtDev, fmtNum, fmtPct, trendClass } from '@/utils/format'

const quotes = useQuotesStore()
const bridge = useBridgeStore()

const hasData = computed(() => quotes.rows.length > 0)

function rowKey(r: DisplayRow): string {
  return r.kind === 'group' ? `g:${r.groupKey}` : `i:${r.code}`
}

/**
 * 行点击 → 看 K 线。
 * 折叠箭头、组名、提醒铃铛各管各的，标了 data-stop 就不触发跳转
 * （用属性而不是 class 判断，意图更明确）。
 */
function onRowClick(r: DisplayRow, ev: MouseEvent): void {
  const el = ev.target as HTMLElement | null
  if (el?.closest('[data-stop]')) return
  if (!r.code) return // 「其他」组头没有 code
  bridge.rowClicked(r.code, r.rawName)
}

function onToggleAlert(r: DisplayRow): void {
  if (r.alert === null) return
  quotes.optimisticToggleAlert(r.code) // 先本地翻转，不等 Python 回执
  bridge.toggleAlert(r.code)
}
</script>

<template>
  <div class="board">
    <header class="hd">
      <span class="title">行情看板</span>
      <span class="meta" data-probe="meta">{{ quotes.meta }}</span>
      <button
        v-if="quotes.groupKeys.length"
        class="toggle-all"
        data-probe="toggle-all"
        @click="quotes.toggleAll()"
      >{{ quotes.hasCollapsed ? '全部展开' : '全部收起' }}</button>
    </header>

    <div v-if="!hasData" class="empty" data-probe="empty">暂无数据</div>

    <div v-else class="scroll">
      <table>
        <thead>
          <tr>
            <th class="c-alert">提醒</th>
            <th>名称</th>
            <th>代码</th>
            <th class="r">最新价</th>
            <th class="r">涨跌</th>
            <th class="r">涨跌幅</th>
            <th class="r">今开</th>
            <th class="r">跟踪偏离</th>
            <th class="c-sig">1分买卖</th>
            <th class="c-sig">5分买卖</th>
            <th class="c-sig">15分买卖</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="r in quotes.visibleRows"
            :key="rowKey(r)"
            :class="{ group: r.kind === 'group', clickable: !!r.code }"
            :data-row="r.kind"
            :data-code="r.code"
            @click="onRowClick(r, $event)"
          >
            <!-- 提醒：指数行没有开关（alert === null） -->
            <td class="c-alert">
              <span
                v-if="r.alert !== null"
                class="bell"
                :class="{ on: r.alert }"
                data-stop
                data-probe="bell"
                :title="r.alert ? '点击关闭提醒' : '点击开启提醒'"
                @click="onToggleAlert(r)"
              >{{ r.alert ? '🔔' : '🔕' }}</span>
            </td>

            <!-- 名称：组头是折叠开关，ETF 缩进一级 -->
            <td>
              <template v-if="r.kind === 'group'">
                <span
                  class="caret"
                  data-stop
                  data-probe="caret"
                  title="展开/收起"
                  @click="quotes.toggleGroup(r.groupKey)"
                >{{ quotes.isCollapsed(r.groupKey) ? '▶' : '▼' }}</span>
                <span
                  class="gname"
                  data-stop
                  @click="quotes.toggleGroup(r.groupKey)"
                >{{ r.name }}</span>
                <span class="gcount">({{ r.count }})</span>
                <span
                  v-if="r.sigCount"
                  class="gsig"
                  :title="`组内 ${r.sigCount} 个买卖点`"
                >{{ r.sigCount }}</span>
              </template>
              <span v-else class="indent">{{ r.name }}</span>
            </td>

            <td class="code">{{ r.code || '-' }}</td>
            <td class="r">{{ fmtNum(r.price, r.digits) }}</td>
            <td class="r" :class="trendClass(r.chgAmt)">{{ fmtChg(r.chgAmt, r.digits) }}</td>
            <td class="r" :class="trendClass(r.changePct)">{{ fmtPct(r.changePct) }}</td>
            <td class="r">{{ fmtNum(r.open, r.digits) }}</td>
            <td class="r" :class="devClass(r.dev)">{{ fmtDev(r.dev) }}</td>
            <!-- 三个周期各显示自己的最新买卖点。K 线图看某周期有买点，
                 就能在对应这一列找到，不会再「图上有、列表没有」。
                 组头行显示的是指数自己各周期的买卖点（与同行价格同源）。 -->
            <td v-for="p in SIGNAL_PERIODS" :key="p" class="c-sig" :data-period="p">
              <SignalBadge :signal="r.signals[p] ?? null" />
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
.board {
  display: flex;
  flex: 1;
  flex-direction: column;
  min-height: 0;
}

.hd {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: center;
  padding: 10px 14px;
  border-bottom: 1px solid var(--line);
}

.title {
  color: var(--accent);
  font-size: 16px;
  font-weight: bold;
}

.meta {
  color: var(--fg-weak);
  font-size: 12px;
}

.toggle-all {
  margin-left: auto;
  padding: 3px 10px;
  border: 1px solid var(--line-strong);
  border-radius: 3px;
  background: transparent;
  color: var(--fg-dim);
  font-family: var(--font);
  font-size: 12px;
  cursor: pointer;
  user-select: none;
}

.toggle-all:hover {
  border-color: var(--accent);
  color: var(--accent);
}

.empty {
  display: flex;
  flex: 1;
  align-items: center;
  justify-content: center;
  color: #666;
  font-size: 15px;
}

.scroll {
  flex: 1;
  overflow: auto;
  min-height: 0;
}

table {
  width: 100%;
  border-collapse: collapse;
}

thead th {
  position: sticky;
  top: 0;
  z-index: 1;
  padding: 10px 12px;
  border-bottom: 2px solid var(--accent);
  background: var(--bg-panel);
  color: var(--accent);
  text-align: left;
  font-weight: bold;
  white-space: nowrap;
}

thead th.r,
tbody td.r {
  text-align: right;
}

.c-alert {
  width: 52px;
}

/* 三个周期的买卖点列，等宽紧凑 */
.c-sig {
  width: 86px;
}

tbody td {
  padding: 9px 12px;
  border-bottom: 1px solid var(--line-soft);
  white-space: nowrap;
}

tbody tr:nth-child(even) {
  background: var(--bg-row-alt);
}

/* 组头行：底色略亮 + 上分隔线，把同组 ETF 视觉上收拢在下面 */
tbody tr.group {
  background: var(--bg-group);
}

tbody tr.group td {
  border-top: 1px solid #3d3d3d;
  font-weight: bold;
}

tbody tr:hover {
  background: var(--bg-hover);
}

tbody tr.clickable {
  cursor: pointer;
}

.code {
  color: var(--fg-dim);
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}

.indent {
  padding-left: 18px;
}

.caret {
  display: inline-block;
  width: 16px;
  color: var(--accent);
  font-size: 10px;
  cursor: pointer;
  user-select: none;
}

.gname {
  color: var(--accent-soft);
  cursor: pointer;
}

.gname:hover {
  text-decoration: underline;
}

.gcount {
  margin-left: 6px;
  color: var(--fg-faint);
  font-size: 12px;
  font-weight: normal;
}

/* 收起后仍能看到组内有几个买卖点，避免折叠漏信号 */
.gsig {
  display: inline-block;
  margin-left: 6px;
  padding: 0 5px;
  border-radius: 8px;
  background: var(--accent);
  color: var(--bg);
  font-size: 11px;
  font-weight: bold;
}

.bell {
  font-size: 16px;
  cursor: pointer;
  user-select: none;
  opacity: 0.4;
}

.bell.on {
  opacity: 1;
}

.dev-pos {
  color: var(--up-weak);
}

.dev-neg {
  color: var(--down-weak);
}

.dev-flat {
  color: var(--fg-faint);
}
</style>
