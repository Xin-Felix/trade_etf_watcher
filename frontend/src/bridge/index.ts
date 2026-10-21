/**
 * QWebChannel 桥接封装。
 *
 * 解决两件事：
 *  1. 连接 Qt 注入的 bridge 对象（异步回调，且离线环境下可能压根没有 qt 对象）。
 *  2. 渲染入口的时序：index.html 里的同步脚本先把 window.renderXxx 占位成
 *     「写进 __RJDJ_PENDING__」，Vue mount 后调 installRenderHandlers 换成真实实现
 *     并重放缓存，避免 loadFinished 到 mount 之间的推送丢失。
 */
import type { PyBridge, RenderHandlers, RenderName } from './types'

type PendingMap = Partial<Record<RenderName, unknown>>

interface BridgeWindow {
  qt?: { webChannelTransport?: unknown }
  QWebChannel?: new (transport: unknown, cb: (ch: { objects: Record<string, unknown> }) => void) => void
  pyBridge?: PyBridge
  __RJDJ_PENDING__?: PendingMap
}

const w = window as unknown as BridgeWindow & Record<string, unknown>

let bridge: PyBridge | null = null

/** 是否运行在 Qt 容器内（浏览器里 npm run dev 时为 false）。 */
export function inQtHost(): boolean {
  return !!w.qt?.webChannelTransport && typeof w.QWebChannel === 'function'
}

/**
 * 建立通道。浏览器开发环境下不会有 qt 对象，直接 resolve(null)，
 * 让页面在没有 Python 的情况下也能跑（配合 mock 数据）。
 */
export function connectBridge(): Promise<PyBridge | null> {
  if (bridge) return Promise.resolve(bridge)
  if (!inQtHost()) return Promise.resolve(null)
  return new Promise((resolve) => {
    // 兜底超时：通道建不起来也不要卡死界面
    const timer = window.setTimeout(() => resolve(null), 5000)
    try {
      new w.QWebChannel!(w.qt!.webChannelTransport, (channel) => {
        window.clearTimeout(timer)
        bridge = (channel.objects.bridge as PyBridge) ?? null
        w.pyBridge = bridge ?? undefined
        resolve(bridge)
      })
    } catch {
      window.clearTimeout(timer)
      resolve(null)
    }
  })
}

export function getBridge(): PyBridge | null {
  return bridge
}

/**
 * 注册真实渲染入口，并重放 mount 之前 Python 已经推来的数据。
 * 返回重放的入口名，便于验收脚本断言。
 */
export function installRenderHandlers(handlers: RenderHandlers): RenderName[] {
  const names = Object.keys(handlers) as RenderName[]
  for (const name of names) {
    const fn = handlers[name]
    if (fn) w[name] = fn as unknown
  }

  const pending = w.__RJDJ_PENDING__ ?? {}
  const replayed: RenderName[] = []
  for (const name of names) {
    const payload = pending[name]
    const fn = handlers[name]
    if (payload !== undefined && fn) {
      // 类型在 RenderHandlers 里已按入口区分，这里统一放行
      ;(fn as (p: unknown) => void)(payload)
      delete pending[name]
      replayed.push(name)
    }
  }
  return replayed
}
