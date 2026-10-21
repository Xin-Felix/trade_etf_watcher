<script setup lang="ts">
/**
 * ECharts 容器组件。
 *
 * 解决旧版三个手工维护的麻烦事：
 *  1. 面板折叠展开后要手动 resize —— 旧版 analysis.html 只 resize 了
 *     smileChart/oiChart，另外 3 个图表漏了（展开后尺寸不对）。
 *  2. window.resize 要逐个列举实例，新增图表容易忘。
 *  3. 容器从 display:none 恢复时尺寸为 0，echarts 初始化会拿到 0 宽高。
 *
 * 这里统一用 ResizeObserver 驱动：容器尺寸有变化（含从 0 变成有值）
 * 就跑一次 sync()，该初始化的初始化、该 resize 的 resize。
 */
import { onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'

import echarts, { type ChartInstance, type ChartOption } from '@/chart/echarts'

const props = withDefaults(
  defineProps<{
    option: ChartOption | null
    /** 容器高度，默认与旧版 .chart-box 一致 */
    height?: string
  }>(),
  { height: '250px' },
)

const emit = defineEmits<{
  /** 实例创建完成（只触发一次），外部可挂 updateAxisPointer 之类的事件 */
  ready: [inst: ChartInstance]
  /** 用户拖动/滚轮缩放后的窗口，调用方存下来可跨刷新保持视图 */
  zoom: [window: { start: number; end: number }]
}>()

const host = ref<HTMLDivElement | null>(null)
// shallowRef：echarts 实例是个大对象，不要被 Vue 深度代理
const chart = shallowRef<ChartInstance | null>(null)
let observer: ResizeObserver | null = null

/**
 * 初始化（或复用）实例并套用最新 option。
 * 容器不可见（宽或高为 0）时直接返回 —— 等 ResizeObserver 下一次回调再来。
 */
function sync(): void {
  const el = host.value
  if (!el) return
  if (el.clientWidth === 0 || el.clientHeight === 0) return

  if (!chart.value) {
    const inst = echarts.init(el, null, { renderer: 'canvas' })
    // 缩放窗口上报：调用方存下来，下次 setOption 时写回，
    // 这样定时自动刷新不会把用户拉好的视图重置掉
    inst.on('dataZoom', () => {
      const opt = inst.getOption() as { dataZoom?: Array<{ start?: number; end?: number }> }
      const dz = opt?.dataZoom?.[0]
      if (dz && typeof dz.start === 'number' && typeof dz.end === 'number') {
        emit('zoom', { start: dz.start, end: dz.end })
      }
    })
    // 把实例挂到宿主元素上，验收脚本可以从 DOM 拿到它去 dispatchAction /
    // 读 getOption()。按需引入模式下没有全局 window.echarts，也没有稳定的
    // 内部注册表可查，所以显式留这个出口。生产环境只是多一个属性引用。
    ;(el as unknown as { __echarts__?: ChartInstance }).__echarts__ = inst
    chart.value = inst
    emit('ready', inst)
  }
  if (props.option) {
    // notMerge=true：与旧版各 setOption(opt, true) 一致。
    // 换到期月时 series 数量会变，合并模式会残留上一次的系列。
    chart.value.setOption(props.option, true)
  }
  chart.value.resize()
}

watch(() => props.option, sync)

onMounted(() => {
  observer = new ResizeObserver(sync)
  if (host.value) observer.observe(host.value)
  sync()
})

onBeforeUnmount(() => {
  observer?.disconnect()
  observer = null
  if (host.value) {
    delete (host.value as unknown as { __echarts__?: ChartInstance }).__echarts__
  }
  chart.value?.dispose()
  chart.value = null
})

defineExpose({
  /** 供验收脚本/调试用：实例是否已建起来 */
  ready: () => chart.value !== null,
})
</script>

<template>
  <div ref="host" class="chart-box" :style="{ height: props.height }" data-echart />
</template>

<style scoped>
.chart-box {
  width: 100%;
}
</style>
