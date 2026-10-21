<script setup lang="ts">
import type { TradeSignal } from '@/bridge/types'

const props = defineProps<{ signal: TradeSignal | null }>()
</script>

<template>
  <span v-if="props.signal" class="wrap">
    <span
      class="sig"
      :class="props.signal.side === 'buy' ? 'sig-buy' : 'sig-sell'"
      :title="props.signal.label"
    >{{ props.signal.side === 'buy' ? '买' : '卖' }}</span>
    <span class="time">{{ props.signal.time }}</span>
  </span>
  <span v-else class="flat">-</span>
</template>

<style scoped>
.sig {
  display: inline-block;
  padding: 1px 7px;
  border-radius: 3px;
  color: var(--fg-strong);
  font-size: 12px;
  font-weight: bold;
}

.sig-buy {
  background: var(--up);
}

.sig-sell {
  background: var(--down);
}

.time {
  margin-left: 6px;
  color: #999;
  font-size: 12px;
}
</style>
