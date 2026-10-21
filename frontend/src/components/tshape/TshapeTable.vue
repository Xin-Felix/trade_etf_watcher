<script setup lang="ts">
/**
 * T 型报价表：CALL 在左、行权价居中、PUT 在右。
 *
 * 每个合约块的 6 个指标由 SideCell 用三列两行一屏铺开，
 * 不再有横向分页，所以这里也不需要同步各行的 scrollLeft 了。
 */
import { onBeforeUnmount, onMounted, ref } from 'vue'

import SideCell from '@/components/tshape/SideCell.vue'
import { useStripScroll } from '@/composables/useStripScroll'
import { useTshapeStore } from '@/stores/tshape'
import { fmtNum, fmtPct, trendClass } from '@/utils/format'

const store = useTshapeStore()

const emit = defineEmits<{
  open: [code: string, name: string]
  addLeg: [code: string, name: string, side: 'buy' | 'sell']
  copy: [text: string]
}>()

const wrap = ref<HTMLDivElement | null>(null)
const { scrollToStrip } = useStripScroll(wrap)

/**
 * 把纵向滚动条占掉的宽度量出来，写进 CSS 变量给表头用。
 *
 * 表头在滚动容器外面，拿到的是完整宽度，而表体被滚动条挤窄了，
 * 两边各按 1fr 分列就会差出几个像素、列标题和数据对不齐。
 * 滚动条宽度各平台不同（macOS 覆盖式是 0），只能量不能写死。
 */
let ro: ResizeObserver | null = null

function measureScrollbar(): void {
  const w = wrap.value
  if (!w) return
  const sbw = Math.max(0, w.offsetWidth - w.clientWidth)
  document.documentElement.style.setProperty('--tshape-sbw', `${sbw}px`)
}

onMounted(() => {
  measureScrollbar()
  const w = wrap.value
  if (w && typeof ResizeObserver !== 'undefined') {
    ro = new ResizeObserver(measureScrollbar)
    ro.observe(w)
  }
})

onBeforeUnmount(() => {
  ro?.disconnect()
  ro = null
})

defineExpose({ scrollToStrip })
</script>

<template>
  <div ref="wrap" class="twrap" data-probe="twrap">
    <template v-for="(r, i) in store.rows" :key="r.strike">
      <!-- 现价带：插在第一个高于现价的行权价之前 -->
      <div
        v-if="i === store.stripIndex"
        class="strip"
        :class="trendClass(store.underlying?.change_pct)"
        data-probe="strip"
      >
        现价： {{ fmtNum(store.spot, 3) }}
        <template v-if="store.underlying?.change !== null && store.underlying?.change !== undefined">
          {{ (store.underlying.change > 0 ? '+' : '') + fmtNum(store.underlying.change, 3) }}
        </template>
        {{ fmtPct(store.underlying?.change_pct) }}
      </div>

      <div class="srow" :data-strike="r.strike">
        <div class="side call">
          <SideCell
            v-for="n in Math.max(r.calls.length, r.puts.length, 1)"
            :key="`c${n}`"
            :item="r.calls[n - 1] ?? null"
            type="call"
            @open="(c, nm) => emit('open', c, nm)"
            @add-leg="(c, nm, s) => emit('addLeg', c, nm, s)"
            @copy="(t) => emit('copy', t)"
          />
        </div>
        <div class="strike">{{ fmtNum(r.strike, 3) }}</div>
        <div class="side put">
          <SideCell
            v-for="n in Math.max(r.calls.length, r.puts.length, 1)"
            :key="`p${n}`"
            :item="r.puts[n - 1] ?? null"
            type="put"
            @open="(c, nm) => emit('open', c, nm)"
            @add-leg="(c, nm, s) => emit('addLeg', c, nm, s)"
            @copy="(t) => emit('copy', t)"
          />
        </div>
      </div>
    </template>

    <!-- 所有行权价都低于现价时，现价带落在末尾 -->
    <div
      v-if="store.stripIndex === store.rows.length && store.rows.length > 0"
      class="strip"
      :class="trendClass(store.underlying?.change_pct)"
      data-probe="strip"
    >
      现价： {{ fmtNum(store.spot, 3) }} {{ fmtPct(store.underlying?.change_pct) }}
    </div>
  </div>
</template>

<style scoped>
.twrap {
  flex: 1;
  overflow-x: hidden;
  overflow-y: auto;
}

.srow {
  display: grid;
  grid-template-columns: 1fr 84px 1fr;
  border-bottom: 1px solid #2a2a2a;
}

.srow:nth-child(even) {
  background: #222;
}

.side {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.strike {
  display: flex;
  align-items: center;
  justify-content: center;
  background: #262626;
  color: var(--fg);
  font-weight: bold;
}

.strip {
  padding: 5px 0;
  border-top: 1px solid #3a3a3a;
  border-bottom: 1px solid #3a3a3a;
  font-size: 12px;
  font-weight: bold;
  letter-spacing: 1px;
  text-align: center;
}

.strip.up {
  background: rgba(239, 83, 80, 0.08);
  color: var(--up);
}

.strip.down {
  background: rgba(38, 166, 154, 0.08);
  color: var(--down);
}

.strip.flat {
  background: #252525;
  color: var(--fg-dim);
}
</style>
