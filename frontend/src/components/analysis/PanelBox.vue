<script setup lang="ts">
/**
 * 可折叠面板容器。
 *
 * body 用 v-show 而不是 v-if：v-if 会在收起时销毁里面的图表实例，
 * 展开要重建（慢，且丢掉缩放等状态）。v-show 只切 display，
 * EChart 里的 ResizeObserver 会在容器重新有尺寸时自动 resize。
 */
import { PANEL_TITLES, useAnalysisStore, type PanelId } from '@/stores/analysis'

const props = defineProps<{ id: PanelId; hint: string }>()
const store = useAnalysisStore()
</script>

<template>
  <section class="panel" :data-panel="props.id">
    <div class="panel-head" :data-probe="`panel-head-${props.id}`" @click="store.togglePanel(props.id)">
      <span class="t">{{ PANEL_TITLES[props.id] }}</span>
      <span class="hint" :data-probe="`hint-${props.id}`">{{ props.hint }}</span>
      <span class="spacer" />
      <span class="toggle">{{ store.isCollapsed(props.id) ? '▲' : '▼' }}</span>
    </div>
    <div v-show="!store.isCollapsed(props.id)" class="panel-body" :data-probe="`body-${props.id}`">
      <slot />
    </div>
  </section>
</template>

<style scoped>
.panel {
  border-bottom: 1px solid var(--line);
}

.panel-head {
  display: flex;
  gap: 10px;
  align-items: center;
  padding: 9px 14px;
  background: #252525;
  cursor: pointer;
}

.panel-head .t {
  color: var(--accent);
  font-size: 13px;
  font-weight: bold;
}

.panel-head .hint {
  color: var(--fg-weak);
  font-size: 11px;
}

.spacer {
  flex: 1;
}

.panel-head .toggle {
  color: var(--fg-weak);
}
</style>
