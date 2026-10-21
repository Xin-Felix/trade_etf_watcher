/**
 * 页面路由标识。
 *
 * 迁移期：Qt 侧每个 QWebEngineView 加载同一份 app.html，通过 index.html 里的
 * `window.__RJDJ_ROUTE__` 占位符决定本实例显示哪一页（VueTab 负责替换）。
 * 阶段 5 收敛成单 SPA 后，改为应用内导航，这套常量继续复用。
 */
export const ROUTES = ['quotes', 'chart', 'tshape', 'analysis', 'signals', '__probe__'] as const

export type RouteName = (typeof ROUTES)[number]

export const ROUTE_TITLES: Record<RouteName, string> = {
  quotes: '行情看板',
  chart: 'K 线图',
  tshape: '期权T型',
  analysis: '期权分析',
  signals: '今日信号',
  // 骨架诊断页，永远渲染 Placeholder。
  // smoke_vue_shell.py 靠它验证桥接与时序，这样骨架验收不会随着
  // 某个页面迁移完成、Placeholder 被真实视图替换而失效。
  __probe__: '骨架诊断',
}

const FALLBACK: RouteName = 'quotes'

/** 读取 Qt 注入的初始路由；未替换或非法值时回落到行情看板。 */
export function initialRoute(): RouteName {
  const raw = (window as { __RJDJ_ROUTE__?: string }).__RJDJ_ROUTE__ ?? ''
  return (ROUTES as readonly string[]).includes(raw) ? (raw as RouteName) : FALLBACK
}
