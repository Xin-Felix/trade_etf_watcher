<script setup lang="ts">
import { computed } from 'vue'

import { useBridgeStore } from '@/stores/bridge'
import type { RouteName } from '@/routes'

const props = defineProps<{ route: RouteName; title: string }>()

const bridge = useBridgeStore()

const status = computed(() => (bridge.connected ? '已连接' : '未连接'))

/** 回连通性测试：点一下把 route 名当 code 发回 Python，验收脚本会检查是否收到。 */
function ping(): void {
  bridge.rowClicked(`probe:${props.route}`, props.title)
}
</script>

<template>
  <div class="ph">
    <div class="card">
      <div class="t">{{ title }}</div>
      <dl>
        <dt>路由</dt>
        <dd data-probe="route">{{ route }}</dd>
        <dt>Vue</dt>
        <dd data-probe="vue">mounted</dd>
        <dt>桥接</dt>
        <dd data-probe="bridge">{{ status }}</dd>
        <dt>收到推送</dt>
        <dd data-probe="pushes">{{ bridge.pushCount }}</dd>
        <dt>最后一次</dt>
        <dd data-probe="last">{{ bridge.lastPushName || '-' }}</dd>
      </dl>
      <button data-probe="ping" @click="ping">回连测试</button>
      <p class="hint">阶段 0 骨架页：验证构建管线与 Python↔Vue 双向通道。</p>
    </div>
  </div>
</template>

<style scoped>
.ph {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}

.card {
  min-width: 320px;
  padding: 22px 26px;
  background: var(--bg-panel);
  border: 1px solid var(--line-strong);
  border-radius: 8px;
}

.t {
  margin-bottom: 14px;
  padding-bottom: 10px;
  border-bottom: 2px solid var(--accent);
  color: var(--accent);
  font-size: 16px;
  font-weight: bold;
}

dl {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 7px 18px;
  margin-bottom: 16px;
}

dt {
  color: var(--fg-weak);
}

dd {
  color: var(--fg);
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}

button {
  padding: 5px 14px;
  border: 1px solid var(--line-strong);
  border-radius: 3px;
  background: transparent;
  color: var(--fg-dim);
  font-family: var(--font);
  font-size: 12px;
  cursor: pointer;
}

button:hover {
  border-color: var(--accent);
  color: var(--accent);
}

.hint {
  margin-top: 12px;
  color: var(--fg-faint);
  font-size: 11px;
}
</style>
