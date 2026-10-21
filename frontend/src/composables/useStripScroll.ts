/**
 * 把 T 型表格的「现价带」滚到可视区正中。
 *
 * T 型表和单方向列表两个视图都有现价带，定位逻辑一模一样，抽出来共用。
 * 同一时刻只有一个视图挂载，另一个的 wrap 是 null，会直接返回。
 */
import { nextTick, onMounted, watch, type Ref } from 'vue'

import { useTshapeStore } from '@/stores/tshape'

export function useStripScroll(wrap: Ref<HTMLElement | null>) {
  const store = useTshapeStore()

  /**
   * 现价带用 querySelector 找，不用模板 ref —— 它渲染在 v-for 内部，
   * Vue 3 会把那种 ref 收成数组，`.offsetTop` 拿到的是 undefined，
   * 算出来的 scrollTop 是 NaN，赋值被静默忽略，表格就一直停在顶部（原来的 bug）。
   *
   * 位移用 getBoundingClientRect 算差值而不是 offsetTop：滚动容器没有定位属性，
   * offsetParent 是更外层的元素，offsetTop 不是相对滚动容器的偏移。
   */
  function scrollToStrip(retry = 2): void {
    const w = wrap.value
    const s = w?.querySelector<HTMLElement>('[data-probe=strip]')
    if (!w || !s) return
    // 页签没激活时 QWebEngineView 视口是 0 高，这时算出来的位置没意义，
    // 等下一帧再试（切回页签就有高度了）
    if (w.clientHeight === 0) {
      if (retry > 0) requestAnimationFrame(() => scrollToStrip(retry - 1))
      return
    }
    const delta = s.getBoundingClientRect().top - w.getBoundingClientRect().top
    w.scrollTop = Math.max(0, w.scrollTop + delta - (w.clientHeight - s.offsetHeight) / 2)
  }

  // 换标的（含首次加载）/ 点「回到现价」
  watch(
    () => store.scrollToStripToken,
    () => nextTick(() => scrollToStrip()),
  )

  // 换到期月后行重建，现价带位置会变（各月行权价范围不同）
  watch(
    () => store.expiry,
    () => nextTick(() => scrollToStrip()),
  )

  // 切换「全部/CALL/PUT」会换掉整个表格组件，新挂载的这个收不到上面的
  // token 变化，得自己定位一次
  onMounted(() => nextTick(() => scrollToStrip()))

  return { scrollToStrip }
}
