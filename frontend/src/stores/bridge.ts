/**
 * 桥接状态与出站调用的唯一出口。
 *
 * 组件不直接碰 window.pyBridge：一是浏览器开发环境下它不存在，
 * 二是集中在这里才好统计/调试（pushCount、lastPushName 就是给验收脚本看的）。
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'

import { connectBridge, getBridge, inQtHost } from '@/bridge'
import type { AiStrategyRequest, StrategyRequest } from '@/bridge/types'

export const useBridgeStore = defineStore('bridge', () => {
  const connected = ref(false)
  const inQt = ref(inQtHost())
  /** Python 推过来的渲染次数（含 mount 前缓存的重放） */
  const pushCount = ref(0)
  const lastPushName = ref('')

  async function connect(): Promise<void> {
    const b = await connectBridge()
    connected.value = !!b
  }

  /** 各 store 收到 Python 推送后调一下，便于观测数据流是否真的通。 */
  function notePush(name: string): void {
    pushCount.value += 1
    lastPushName.value = name
  }

  /* ---------- 出站调用（对应 _Bridge 的 7 个 Slot） ---------- */

  function requestRefresh(): void {
    getBridge()?.requestRefresh()
  }

  function rowClicked(code: string, name: string): void {
    getBridge()?.onRowClicked(code, name)
  }

  function requestPeriod(period: string): void {
    getBridge()?.requestPeriod(period)
  }

  function requestStrategy(req: StrategyRequest): void {
    getBridge()?.requestStrategy(JSON.stringify(req))
  }

  function requestAiStrategy(req: AiStrategyRequest): void {
    getBridge()?.requestAiStrategy(JSON.stringify(req))
  }

  /** side 传 'call'/'put' 时，T 型页会直接切到那一侧（买卖点跳转用）。 */
  function viewOption(underlyingCode: string, side: '' | 'call' | 'put' = ''): void {
    getBridge()?.viewOption(underlyingCode, side)
  }

  function toggleAlert(code: string): void {
    getBridge()?.toggleAlert(code)
  }

  /** 复制到系统剪贴板。浏览器里没有 bridge 时退回 navigator.clipboard。 */
  function copyText(text: string): void {
    const b = getBridge()
    if (b?.copyText) {
      b.copyText(text)
      return
    }
    navigator.clipboard?.writeText(text)
  }

  return {
    connected,
    inQt,
    pushCount,
    lastPushName,
    connect,
    notePush,
    requestRefresh,
    rowClicked,
    requestPeriod,
    requestStrategy,
    requestAiStrategy,
    viewOption,
    toggleAlert,
    copyText,
  }
})
