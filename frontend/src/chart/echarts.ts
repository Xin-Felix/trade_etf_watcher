/**
 * ECharts 按需引入。
 *
 * 只注册项目实际用到的图表和组件，避免把完整包（旧版 echarts.min.js 有 1MB）
 * 打进产物。清单依据现有 4 个页面的用法逐一核对：
 *   - chart.html    candlestick + line + bar，多 grid、dataZoom(inside+slider)、
 *                   markPoint、axisPointer(cross + link)
 *   - tshape.html   line(areaStyle) + markLine + title
 *   - analysis.html line + bar + heatmap + legend + visualMap + markLine/markPoint
 * 「波动率曲面」是 2D heatmap，不是 3D，所以不需要 echarts-gl。
 *
 * 新增图表类型时记得回来加，否则运行时报 "Series xxx is not exists"。
 */
import { BarChart, CandlestickChart, HeatmapChart, LineChart } from 'echarts/charts'
import {
  AxisPointerComponent,
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  MarkLineComponent,
  MarkPointComponent,
  TitleComponent,
  TooltipComponent,
  VisualMapComponent,
} from 'echarts/components'
import * as echarts from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([
  // 图表类型
  LineChart,
  BarChart,
  CandlestickChart,
  HeatmapChart,
  // 组件
  GridComponent,
  TooltipComponent,
  LegendComponent,
  TitleComponent,
  AxisPointerComponent,
  DataZoomComponent,
  MarkLineComponent,
  MarkPointComponent,
  VisualMapComponent,
  // 渲染器
  CanvasRenderer,
])

export default echarts

/**
 * option 的类型。
 *
 * 刻意用宽松类型而不是 ComposeOption：按需引入的严格联合类型对
 * markLine.data / markPoint.data 这类嵌套结构非常挑，写起来到处要断言，
 * 收益不如成本。图表配置的正确性由验收脚本兜（真实渲染 + 回读 DOM）。
 */
export type ChartOption = Record<string, unknown>

export type ChartInstance = ReturnType<typeof echarts.init>
