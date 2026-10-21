/**
 * 图表公用配置片段。
 * 取值来自旧版各 HTML 里重复写的那套暗色主题，集中在这里，
 * 5 个分析面板不用各自抄一遍。
 */

export const CHART_BG = '#1e1e1e'

/** 所有图表都关动画：数据每轮刷新，动画会让人眼花。 */
export function baseOption(): Record<string, unknown> {
  return { backgroundColor: CHART_BG, animation: false }
}

export const axisLine = { lineStyle: { color: '#555' } }
export const splitLine = { lineStyle: { color: '#2c2c2c' } }

export function axisLabel(extra: Record<string, unknown> = {}): Record<string, unknown> {
  return { color: '#999', fontSize: 10, ...extra }
}

export const nameTextStyle = { color: '#888', fontSize: 10 }

export function darkTooltip(extra: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    backgroundColor: '#2d2d2d',
    borderColor: '#555',
    textStyle: { color: '#eee', fontSize: 12 },
    ...extra,
  }
}

export const legendStyle = {
  show: true,
  top: 4,
  right: 14,
  textStyle: { color: '#aaa', fontSize: 11 },
}

/** x 轴刻度太密时按总数抽稀，规则与旧版一致。 */
export function labelInterval(total: number, divisor: number): number {
  return Math.max(1, Math.floor(total / divisor))
}

/**
 * 现价参考线。
 *
 * 挂在一个空 series 上（旧版同样写法）。x 轴是 category 类型，markLine 的
 * xAxis 必须精确等于某个 category 值，所以现价不在行权价档位上时线就不显示
 * —— 这是旧版既有行为，保持不变。
 */
export function spotMarkLine(spot: number | null, digits = 3): Record<string, unknown>[] {
  if (spot === null || !(spot > 0)) return []
  return [
    {
      type: 'line',
      data: [],
      markLine: {
        symbol: 'none',
        silent: true,
        data: [
          {
            xAxis: spot.toFixed(digits),
            lineStyle: { color: '#4fc3f7', type: 'dashed', width: 1 },
            label: {
              show: true,
              formatter: '现价',
              color: '#4fc3f7',
              fontSize: 10,
              position: 'insideEndTop',
            },
          },
        ],
      },
    },
  ]
}
