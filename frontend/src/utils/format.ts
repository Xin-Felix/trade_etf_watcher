/**
 * 数值格式化。
 * 口径沿用迁移前各 HTML 里的写法：null/NaN 一律显示占位符，
 * 涨跌带正负号，A 股习惯涨红跌绿。
 */

const DASH = '-'

export function fmtNum(v: number | null | undefined, digits = 3): string {
  if (v === null || v === undefined || Number.isNaN(v)) return DASH
  return v.toFixed(digits)
}

/** 涨跌额：带正负号。 */
export function fmtChg(v: number | null | undefined, digits = 3): string {
  if (v === null || v === undefined || Number.isNaN(v)) return DASH
  return (v > 0 ? '+' : '') + v.toFixed(digits)
}

/** 涨跌幅：带正负号和百分号。 */
export function fmtPct(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return DASH
  return (v > 0 ? '+' : '') + v.toFixed(2) + '%'
}

/** 跟踪偏离：百分点，带正负号和 pp 单位。 */
export function fmtDev(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return DASH
  return (v > 0 ? '+' : '') + v.toFixed(2) + 'pp'
}

/** 成交量等大数：万/亿 缩写。 */
export function fmtCompact(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return DASH
  if (Math.abs(v) >= 1e8) return (v / 1e8).toFixed(2) + '亿'
  if (Math.abs(v) >= 1e4) return (v / 1e4).toFixed(1) + '万'
  return String(v)
}

/**
 * 隐含波动率。入参是小数（0.2536），展示成百分数（25.4%）。
 *
 * 低于 1% 的当没有：深度实值/虚值合约上，数据源的 IV 求解器求不出来会
 * 返回触底值（实测 0.0009，对应 delta 已经是 1.0），显示成「0.1%」
 * 会被误读成这合约波动率极低，不如直接留空。
 *
 * 注意 smile.callIV 那类字段已经是百分数了，别用这个函数。
 *
 * dash 可以覆盖占位符：T 型页那几个表用的是 '--'，与本模块缺省的 '-' 不同。
 */
export function fmtIv(v: number | null | undefined, dash = DASH): string {
  if (v === null || v === undefined || Number.isNaN(v) || v < 0.01) return dash
  return (v * 100).toFixed(1) + '%'
}

export type TrendClass = 'up' | 'down' | 'flat'

export function trendClass(v: number | null | undefined): TrendClass {
  if (v === null || v === undefined || Number.isNaN(v) || v === 0) return 'flat'
  return v > 0 ? 'up' : 'down'
}

export type DevClass = 'dev-pos' | 'dev-neg' | 'dev-flat'

/** 跟踪偏离用弱色，避免和涨跌红绿抢注意力。 */
export function devClass(v: number | null | undefined): DevClass {
  if (v === null || v === undefined || Number.isNaN(v) || v === 0) return 'dev-flat'
  return v > 0 ? 'dev-pos' : 'dev-neg'
}

/* ------------------------- K 线时间标签 ------------------------- */

import type { LabelFmt } from '@/bridge/types'

/**
 * 把 bar 的原始时间戳格式化成 x 轴标签。
 *
 * 输入是 12 位 YYYYMMDDHHMM 或 14 位 YYYYMMDDHHMMSS（bars 的 ts 由
 * fetchers 归一化过，一定是纯数字）。三种格式与 Python 侧 _bar_label 对齐：
 *   date     → 2026-09-01     （日 K）
 *   datetime → 09-01 14:35    （跨天的分钟 K）
 *   time     → 14:35          （当日分钟 K / 分时）
 */
export function formatBarLabel(ts: string, fmt: LabelFmt = 'time'): string {
  if (!ts || ts.length < 8) return ts || ''
  const y = ts.slice(0, 4)
  const mo = ts.slice(4, 6)
  const d = ts.slice(6, 8)
  if (fmt === 'date') return `${y}-${mo}-${d}`
  if (ts.length < 12) return `${y}-${mo}-${d}`
  const hh = ts.slice(8, 10)
  const mi = ts.slice(10, 12)
  return fmt === 'datetime' ? `${mo}-${d} ${hh}:${mi}` : `${hh}:${mi}`
}

/** 时间戳归一化到分钟精度，用于信号与 bar 对齐（两边可能一个 12 位一个 14 位）。 */
export function tsToMinute(ts: string): string {
  return (ts || '').slice(0, 12)
}
