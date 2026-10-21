/**
 * Python ↔ JS 契约类型。
 *
 * 全部字段依据现有实现逐一核对，不是推测：
 *  - render 入口与 payload 组装：watcher/gui/main_window.py、watcher/option_meta.py
 *  - 回调签名：watcher/gui/web/webtab.py 的 _Bridge
 * 迁移期间 Python 侧不改契约，所以这里就是权威定义；后续要改字段，两边一起改。
 */

/* ========================= 通用 ========================= */

/** Python 侧大量字段在无数据时发 null（不是 undefined）。 */
export type Nullable<T> = T | null

/* ==================== 行情看板（阶段 1）==================== */

/** 买卖点信号：只取共振买/卖，事件类信号（急涨急跌等）不算。 */
export interface TradeSignal {
  side: 'buy' | 'sell'
  /** HH:MM */
  time: string
  label: string
}

/** 一个标的在三个检测周期上各自的最新买卖点（缺档表示该周期今日无信号）。 */
export interface PeriodSignals {
  '1m'?: TradeSignal
  '5m'?: TradeSignal
  '15m'?: TradeSignal
}

/** 看板里三个周期的固定顺序与列标题。 */
export const SIGNAL_PERIODS = ['1m', '5m', '15m'] as const
export type SignalPeriod = (typeof SIGNAL_PERIODS)[number]

/** 一条原始行情快照。涨跌额/涨跌幅/跟踪偏离都由前端算，Python 不再预处理。 */
export interface RawQuote {
  code: string
  name: string
  price: number
  open: number
  prevClose: number
  volume: number
  /**
   * 行情时间戳。**格式不统一**：随数据源而变
   * （TDX 直接给 servertime，形如 "153:05:17.850"；东财是另一种）。
   * 要展示的话必须先归一化，不能当 yyyyMMddHHmmss 直接切片。
   */
  ts: string
  source: string
}

export interface IndexRef {
  code: string
  name: string
}

/**
 * 行情看板 payload（入口 window.renderQuotes）。
 *
 * 与阶段 0 之前的 TablePayload 的区别：那套是 Python 把列定义、分组、
 * 小数位、meta 文案全算好再发（渲染指令）；这套只发事实，
 * 分组/重名去歧义/涨跌计算/折叠/文案都在前端。
 */
export interface QuotesPayload {
  quotes: RawQuote[]
  /** 跟踪指数，数组顺序即看板分组顺序 */
  indices: IndexRef[]
  /** ETF code → 指数 code；没配的 ETF 归「其他」组 */
  indexMap: Record<string, string>
  /** 用户勾选了提醒的标的。**空数组 = 全部提醒**（沿用 DB 语义，别当成"都不提醒"） */
  alertCodes: string[]
  /** code → 今日最新买卖点 */
  /** 每个 code → 三个周期各自的最新买卖点 */
  signals: Record<string, PeriodSignals>
  /** 当前生效的数据源，给状态条用 */
  source: string
}

/* -------- 以下是旧看板契约，table.html 还在用，迁移完成后可删 -------- */

export type CellType = 'toggle' | 'num' | 'chg' | 'pct' | 'dev' | 'signal'

export interface QuoteColumn {
  key: string
  title: string
  type?: CellType
  digits?: number
}

export interface QuoteRow {
  code: string
  /** 原始名，回传 onRowClicked 用（展示名可能带 (沪)/(深) 后缀） */
  _name: string
  name: string
  /** true = 指数组头行 */
  _isGroup: boolean
  /** 折叠分组键：指数 code，或 "_other_" */
  _group: string
  /** 行级小数位，覆盖列级 digits：指数 2、ETF 3 */
  _digits: number
  price: Nullable<number>
  chg_amt: Nullable<number>
  change: Nullable<number>
  open: Nullable<number>
  /** null = 指数行，不显示提醒开关 */
  alert: Nullable<boolean>
  /** 跟踪偏离（百分点）= ETF 涨跌幅 − 指数涨跌幅；指数行为 null */
  dev: Nullable<number>
  signal: Nullable<TradeSignal>
  /** 仅组头：组内 ETF 数 */
  _count?: number
  /** 仅组头：组内买卖点数 */
  _sigCount?: number
}

export interface TablePayload {
  title: string
  meta: string
  columns: QuoteColumn[]
  rowKey: string
  rows: QuoteRow[]
}

/* ===================== K 线图（阶段 3）===================== */

/** x 轴标签格式：随周期而定，前端据此格式化 bar.ts。 */
export type LabelFmt = 'date' | 'datetime' | 'time'

export interface ChartBar {
  /** Python 拼好的标签，仅老 chart.html 用；Vue 版用 ts 自己格式化 */
  label: string
  /** 原始时间戳，12 位 YYYYMMDDHHMM 或 14 位 YYYYMMDDHHMMSS */
  ts: string
  open: number
  high: number
  low: number
  close: number
  /** 均价，只有新浪期权分时数据才有 */
  avg: Nullable<number>
  volume: number
}

export interface ChartSignal {
  key: string
  /** 老 chart.html 靠它做字符串匹配定位 */
  label: string
  /**
   * 原始时间戳。Vue 版按它匹配 bar —— 信号是在当日 bars（期权时是对应
   * ETF 的 bars）上检测的，与 payload.bars 索引不对应，只能按时间对齐。
   */
  ts: string
  labelText: string
}

export interface ChartQuote {
  price: Nullable<number>
  change: Nullable<number>
  changePct: Nullable<number>
  open: Nullable<number>
  high: Nullable<number>
  low: Nullable<number>
  prevClose: Nullable<number>
  /** 期权是"昨结"，ETF 缺省"昨收" */
  prevCloseLabel?: string
  volume: Nullable<number>
  /** 已格式化的字符串对：[["买一","0.0123 x5"], ...] */
  extras: Array<[string, string]>
}

/** loading 占位变体只有 title/loading/period/periods。 */
export interface ChartPayload {
  title: string
  loading?: boolean
  mode?: 'candle' | 'intraday'
  period: string
  periods: string[]
  labelFmt?: LabelFmt
  bars?: ChartBar[]
  signals?: ChartSignal[]
  quote?: Nullable<ChartQuote>
  digits?: number
  atm?: Nullable<{ underlying: string }>
}

/* ============ 期权 T 型 / 期权分析（阶段 2、4）============ */
/* 两页消费同一个 payload：option_meta.build_tshape_data 的产物 */

/** 无行情时只有 code/name（前端靠 price != null 判断）。 */
export interface OptionSide {
  code: string
  name: string
  price?: Nullable<number>
  change_pct?: Nullable<number>
  sell_price?: Nullable<number>
  sell_vol?: Nullable<number>
  buy_price?: Nullable<number>
  buy_vol?: Nullable<number>
  volume?: Nullable<number>
  oi?: Nullable<number>
  /** 小数（0.183），注意与 smile.callIV 的百分数口径不同 */
  iv?: Nullable<number>
  delta?: Nullable<number>
}

export interface StrikeRow {
  strike: number
  calls: OptionSide[]
  puts: OptionSide[]
}

export interface ExpiryItem {
  /** YYYYMMDD */
  date: string
  /** YYYY-MM-DD */
  label: string
  days: Nullable<number>
}

export interface UnderlyingInfo {
  code: string
  name: string
  price: Nullable<number>
  change: Nullable<number>
  change_pct: Nullable<number>
}

/** IV 已 ×100（百分数）。 */
export interface SmileData {
  strikes: number[]
  callIV: Array<Nullable<number>>
  putIV: Array<Nullable<number>>
}

export interface OiData {
  strikes: number[]
  callOI: number[]
  putOI: number[]
  callWall: Nullable<number>
  putWall: Nullable<number>
  maxPain: Nullable<number>
}

/**
 * 卖方指标。口径注意（option_meta.py 有注释承认单位不统一）：
 * totalGamma 实为 Σ|delta|×OI，totalTheta/totalVega 实为 Σ IV×OI，
 * gammaExposure 是自定义简化式。前端只负责展示，不重算。
 */
export interface SellerMetrics {
  atmStrike: Nullable<number>
  /** % */
  atmIV: Nullable<number>
  /** 百分点，正 = Put 更贵 = 恐慌 */
  skew25D: Nullable<number>
  pcrOI: Nullable<number>
  /** % */
  expectedMove: Nullable<number>
  totalCallOI: Nullable<number>
  totalPutOI: Nullable<number>
  days: Nullable<number>
  pcrVol: Nullable<number>
  totalCallVol: Nullable<number>
  totalPutVol: Nullable<number>
  netDelta: Nullable<number>
  totalGamma: Nullable<number>
  totalTheta: Nullable<number>
  totalVega: Nullable<number>
  ivSkewRatio: Nullable<number>
  /** % */
  otmPutIV: Nullable<number>
  /** % */
  timeValueRatio: Nullable<number>
  gammaExposure: Nullable<number>
}

export interface IvTermItem {
  /** YYYY-MM-DD */
  expiry: string
  days: Nullable<number>
  atmIV: number
}

export interface VolSurface {
  strikes: number[]
  rows: Array<{
    expiry: string
    days: Nullable<number>
    ivs: Array<Nullable<number>>
  }>
}

export interface TShapePayload {
  title: string
  meta: string
  /** 仅无合约时存在 */
  emptyHint?: string
  underlying: UnderlyingInfo
  expiries: ExpiryItem[]
  defaultExpiry: Nullable<string>
  /** key = YYYYMMDD */
  rows: Record<string, StrikeRow[]>
  smile: Record<string, SmileData>
  oi: Record<string, OiData>
  /** 无标的现价时该月缺失 */
  seller: Record<string, SellerMetrics>
  ivTerm: IvTermItem[]
  surface: Nullable<VolSurface>
  /**
   * 打开时强制把方向过滤切到这一侧（'call' / 'put'）。
   * 只在从 K 线买卖点跳转过来那一次出现，Python 侧一次性下发；
   * 缺省表示沿用用户当前的选择。
   */
  initialFilter?: string
}

/** 分析页与 T 型页消费同一 payload。 */
export type AnalysisPayload = TShapePayload

/* =================== 策略工具（阶段 4）=================== */

export interface PresetItem {
  key: string
  label: string
  desc: string
}

export interface StrategyLeg {
  code: string
  name: string
  type: 'call' | 'put'
  strike: number
  side: 'buy' | 'sell'
  price: number
  qty: number
  iv: number
  /** YYYYMMDD */
  expire: string
  days: number
  cost: number
}

export interface StrategySummary {
  netCost: number
  /** null = 理论无限 */
  maxProfit: Nullable<number>
  maxLoss: Nullable<number>
  breakevens: number[]
  maxProfitAt: number
  maxLossAt: number
  pnlAtCurrentSpot: number
  riskReward: Nullable<number>
}

export interface StrategyGreeks {
  delta: number
  gamma: number
  theta: number
  vega: number
  rho: number
}

export interface StrategyDecay {
  currentValue: number
  entryCost: number
  perDay: number
  items: Array<{ days: number; value: number; pnl: number; decay: number }>
}

/** 四种形态：error / empty / 完整；presets 恒存在。 */
export interface StrategyPayload {
  error?: string
  empty?: boolean
  spot?: number
  underlying?: string
  underlyingName?: string
  legs?: StrategyLeg[]
  summary?: StrategySummary
  greeks?: StrategyGreeks
  decay?: StrategyDecay
  curve?: Array<{ s: number; p: number }>
  presets: PresetItem[]
}

/* ===================== AI 推荐（阶段 4）===================== */

export interface AiLeg {
  code: string
  side: 'buy' | 'sell'
  qty: number
  price: number
  name: string
  /** 以下两个由 Python 从合约链回填（AI 本身只回 code/side/qty/price） */
  option_type?: Nullable<'call' | 'put'>
  strike?: Nullable<number>
}

export interface AiResultPayload {
  error?: string
  legs?: AiLeg[]
  strategy_name?: string
  reasoning?: string
  notes?: string
  thinking?: string
  risk_summary?: Record<string, unknown>
}

/* ================== JS → Python 请求体 ================== */

export interface StrategyRequest {
  underlying: Nullable<string>
  expiry: Nullable<string>
  legs: Array<{ code: string; side: 'buy' | 'sell'; qty: number }>
  preset?: string
}

export interface AiStrategyRequest {
  underlying: Nullable<string>
  expiry: Nullable<string>
  capital: number
  max_loss: number
  holding_days: number
  style: string
  etf_shares: number
  direction: string
  target_price: string
  expiry_pref: string
  allow_naked_sell: boolean
}

/* ==================== QWebChannel 对象 ==================== */

/** webtab.py 的 _Bridge 暴露的 7 个 @Slot。 */
export interface PyBridge {
  requestRefresh(): void
  onRowClicked(code: string, name: string): void
  requestPeriod(period: string): void
  requestStrategy(payloadJson: string): void
  requestAiStrategy(payloadJson: string): void
  viewOption(underlyingCode: string, side: string): void
  toggleAlert(code: string): void
  /** 写系统剪贴板。qrc: 源下 navigator.clipboard 不可用，所以走 Qt。 */
  copyText?(text: string): void
}

/** Vue 侧注册的渲染入口，名字必须和 Python 拼的 JS 函数名一致。 */
export interface RenderHandlers {
  renderQuotes?: (p: QuotesPayload) => void
  renderTable?: (p: TablePayload) => void
  updateChart?: (p: ChartPayload) => void
  renderTShape?: (p: TShapePayload) => void
  renderStrategy?: (p: StrategyPayload) => void
  renderAiResult?: (p: AiResultPayload) => void
  renderAnalysis?: (p: AnalysisPayload) => void
}

export type RenderName = keyof RenderHandlers
