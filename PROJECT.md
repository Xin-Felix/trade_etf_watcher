# 日进斗金 项目交接文档

> 更新日期：2026-09-17 ｜ 当前版本：v0.9 可运行
> 本版重点：改名+红色图标、量价形态买卖点（替换 MACD/MA/RSI）、市场日内动量提醒、
> API 密钥 GUI 配置、macOS 原生通知+点击跳转、
> Tushare 官方直连（日K/交易日历/分钟线）、**期权分析页（波动率微笑/曲面/持仓量分布/卖方指标/IV期限结构）**、
> **每日期权快照存储（IV/OI 历史积累）**、**信号有效性回测结论（第 8 节，必读）**
> 前端已全部迁到 **Vue 3 + Vite + TS**（见 `frontend/`）：行情看板、期权 T 型、期权分析、K 线图。
> 页签只有 3 个（看板/T型/分析），**K 线图改为点标的时弹出的独立窗口**。
> 老 HTML 保留在 qrc 里可随时回退。**AI 推荐入口已从界面移除**（Python 侧代码仍在）。
> 近期修复（见 §10）：**指数 K 线取数用错 API**（`get_security_bars` → `get_index_bars`，原来指数数据全是乱码/负价）；
> **期权分时 K 请求全打在已摘牌合约上**（某日一根都没入库，根因是取合约没剔除已到期月）；新浪期权零成交分钟的全 0 bar 过滤。
> T 型页现价带打开即居中、指标四列一屏（不再横向滑）、**点合约代码复制**、**点 K 线买卖点跳期权页**；
> 指数也参与买卖点检测（只入库供查看、不提醒）；**看板买卖点按 1/5/15 分三个周期分列**（提醒仍只发 5 分档）。
> 下一步：**收敛单 SPA / 今日信号页 / 设置页 GUI**
>
> 新会话接手时：**先读「第 8 节 信号规则与回测结论」和「第 10 节 已知坑」**，
> 前者能避免重复走已经证伪的方向，后者能避开 90% 的重复踩坑。

---

## 1. 项目是什么

跨平台（macOS / Windows）桌面 GUI 程序：对 A 股 ETF 及其期权进行**定时自动盯盘**，检测到异常行情信号（跳空、急涨急跌、日内拐点、量价形态）时**系统通知 + 弹窗提醒**，并提供行情看板、K 线图、期权 T 型报价、期权分析与策略工具。

**定位**：盯盘提醒工具，不是自动交易系统。信号用于提示"该看一眼这根 K 线了"，
经回测验证的方向性参考见第 8 节。

- 原始设计文档：`etf-watcher-design.md`（信号规则、数据源评测的原始依据）
- 技术栈：Python 3.12 + PySide6（QWebEngineView + ECharts）+ SQLite + pytdx + akshare
- 运行方式：`python -m watcher` ｜ 打包：PyInstaller（`build/macos.spec` / `build/windows.spec`）

## 2. 当前已实现功能

| 模块 | 状态 |
|---|---|
| ETF 行情轮询（通达信主源 + 东财备用，5s 周期） | ✅ 稳定，watch 11 个期权标的 ETF |
| TDX 服务器并发探测自动选 IP | ✅ ~2 秒选出最快节点，断线自动重连 |
| 信号引擎（8 类信号，按日去重） | ✅ 端到端延迟 ~10s；含期权 IV 飙升 + PCR 异常 |
| 行情看板（**Vue 3**） | ✅ 11 只 ETF **按跟踪指数分组、默认收起可折叠**，每组带指数行对比；列：提醒/名称/代码/最新价/涨跌/涨跌幅/今开/跟踪偏离/**1分·5分·15分买卖点三列**。三列各显示该周期最新买卖点（解决「K 线图某周期有买点、看板看不到」）；指数行显示指数自己的，组内成员出信号数由名称旁角标表达。Python 只发原始快照，分组/涨跌/文案全在前端 |
| K 线图（ECharts 蜡烛图/分时折线、MA5/10/20、成交量红绿、信号标记点） | ✅ **独立弹出窗口**（不占页签）；**点买卖点 pin 跳期权 T 型页**：买点自动过滤 CALL、卖点过滤 PUT |
| K 线信息面板（右侧常驻：最新价/涨跌/开高低收/成交量/买一卖一/持仓/IV） | ✅ 跟随悬停 bar 联动，移开回最新价；期权标注"昨结" |
| K 线悬停 legend（左上角股票软件风格：OHLC + 涨跌额/涨跌幅 + 量，tooltip 同步增强） | ✅ |
| K 线周期切换（分时/1/5/15/30/60分/日K，期权与 ETF 均支持） | ✅ 期权 N 分=东财 1 分聚合；ETF=本地 1 分聚合；日K=新浪(期权)/TDX(ETF) |
| K 线自动刷新（窗口可见 + 轮询时段内按 5s 周期刷新，缩放窗口保持） | ✅ |
| 期权图表异步加载（工作线程取数 + 序号防乱序 + 加载中提示） | ✅ 点期权不再卡界面 |
| 今日信号页 | ✅ 时间格式已统一 |
| 期权 T 型（9 个有合约的标的、1200+ 合约） | ✅ T 型布局：到期日 chips（已过期月份不显示）+ CALL红/PUT绿 + 现价带（打开即居中）+ 过滤；指标四列一屏铺开（合约代码/涨跌幅 · 卖一/买一 · 量/持仓 · IV/Delta），**点合约代码复制到剪贴板**；列表由合约表驱动，无合约标的不进期权页 |
| 期权分时 K（东财 trends2，真实 OHLC 蜡烛图） | ⚠️ 代码在，但**东财源近期实测返回 0**（整域限流），当前实际由新浪源承担（见下） |
| 期权分时 K（新浪，当前实际主力） | ✅ **仅沪市**（10xxxxxx）；预加载 3 个沪市标的的未到期平值合约 + ATM 轮换持续入库；**深市期权两个源都取不到分时**（接口限制） |
| 近价合约分时 K 盘中持续入库（ATM±2 档，轮换限速） | ✅ 盘后源停供也有本地蜡烛图 |
| 期权策略工具（T 型页底部抽屉：预设策略 + 组合篮子 + 8 张指标卡 + 到期损益图） | ✅ 最大盈亏/盈亏平衡/每日时间损耗/组合希腊字母，7 个预设模板 |
| ~~AI 策略推荐（DeepSeek）~~ | ⚠️ **入口已从界面移除**（Vue 版没搬）。Python 侧代码与 `watcher/ai/` 仍在，老 `tshape.html` 回退时可用 |
| **期权分析页**（独立 Tab） | ✅ 卖方指标面板（ATM IV/25Δ偏斜/PCR/预期波动）+ 波动率微笑（当月+多月对比）+ 持仓量分布（OI柱状图+Call墙/Put墙+MaxPain）+ 波动率曲面热力图 + 平值IV期限结构 |
| **每日期权快照存储** | ✅ 收盘前自动存储全部合约 IV/OI/价格快照到 `option_daily_snapshot` 表（幂等），用于历史趋势分析 |
| **量价形态买卖点**（`signals/patterns.py`） | ✅ 14 种形态加权打分；**买入信号经回测未证实有效，见第 8 节**。ETF 与**跟踪指数**都检测，但指数只入库供查看、**不进提醒**（不可交易） |
| **市场日内动量**（`signals/intraday_momentum.py`） | ✅ 14:30 推末半小时方向；一年 ETF 实测 t=+5.00，唯一统计显著的信号 |
| **macOS 原生系统通知** | ✅ UNUserNotificationCenter 横幅弹出 + 点击跳转对应标的 K 线 |
| **API 密钥 GUI 配置** | ✅「API 设置」按钮，Tushare/DeepSeek key 存 SQLite，即时生效 |
| 系统托盘 + 弹窗预警 + 测试预警 | ✅ 弹窗/托盘/系统通知三条路径都支持点击跳转 |
| 优雅退出（Cmd+Q 不崩溃） | ✅ |
| macOS 打包 `.app` | ✅ `dist/日进斗金.app`（574MB，已验证可启动） |

**未做 / 待办**：~~ETF 期权趋势策略信号化~~（§11.6：Step 0 回测 PF 0.90 / t -0.45 不过线，P0 已放弃；P1 深实值筛选、P2 IV 历史为独立工具层可另行评估）、
远程推送（Bark/Server酱/企业微信）、设置页（GUI 内编辑 watchlist/阈值）、
Windows 实机打包验证、量价形态的方向重构（见第 8 节结论）。

**外部 key 存放**：`~/.config/etf_watcher/secrets.env`（权限 600，不在项目目录、不进 git/打包）。已验证：Tushare 的 `trade_cal` / `fund_daily` / `opt_basic` / `opt_daily` 全部可用（`opt_daily` 有真实 OHLC + 持仓量 + 昨结算，正好补东财 kline 被封的历史缺口，注意代码要转成 `10012055.SH` 格式）；DeepSeek 可用，模型是 `deepseek-v4-flash` / `deepseek-v4-pro`（`deepseek-chat` 是别名），支持 `response_format` JSON 输出，余额有限所以只做手动触发、不做轮询。

## 3. 目录结构

```
pythonProject/
├── config.yaml              # 标的清单、阈值、数据源、TDX 服务器补充
├── pyproject.toml           # 项目元数据 + pytest 配置
├── requirements.txt         # 运行依赖
├── requirements-dev.txt     # +pyinstaller/pytest
├── etf-watcher-design.md    # 原始设计文档
├── build/
│   ├── macos.spec           # macOS 打包（含 akshare file_fold 数据文件）
│   └── windows.spec
├── tests/
│   ├── conftest.py          # sys.path 注入
│   ├── test_signals.py      # 信号规则 + 去重测试
│   ├── test_option_bars.py  # 东财期权分时K解析（mock 网络；含 EM 缓存隔离 fixture）
│   ├── test_bars.py         # 分钟K聚合（交易时段对齐/跨天不串/集合竞价并入）
│   ├── test_tshape.py       # T 型报价数据组装 + ATM 合约筛选
│   ├── test_sina_parse.py   # 新浪 CON_OP 字段解析（[6]涨跌幅/[41]成交量）
│   ├── test_tdx_batch.py    # TDX 批量并发分钟K（mock pytdx）
│   ├── test_autorefresh.py  # K线自动刷新 + 期权异步加载乱序/失败
│   ├── test_strategy.py     # 策略计算（定价/损益/时间损耗/预设，41 用例）
│   └── test_trend.py        # 趋势信号层（指标口径/闸门/三层判定/无未来函数，15 用例）
├── assets/
│   ├── icon.icns / icon.png # 应用图标（红底金字「金」）
│   └── echarts.min.js
├── scripts/                 # 冒烟测试 + 回测调参工具
│   ├── smoke_option_chart.py # 冒烟：点击期权合约捕获图表 payload
│   ├── smoke_chart_periods.py # 冒烟：周期切换截图 /tmp/chart_*.png
│   ├── smoke_strategy.py    # 冒烟：策略工具端到端（老 tshape.html 版，真实点按钮 → 读 DOM）
│   ├── smoke_underlyings.py # 冒烟：看板 11 标的 + 期权页 9 标的列表
│   ├── smoke_quote_board.py # 冒烟：看板 9 项断言（分组/偏离/折叠/徽标/回调，真实 WebEngine）★
│   ├── smoke_vue_shell.py   # 冒烟：Vue 骨架（route 注入/桥接双向/mount 前推送不丢/路由分发/老页面无回归）★
│   ├── smoke_analysis.py    # 冒烟：期权分析页 6 面板（可用性/14卡/canvas/切月/折叠 resize）★
│   ├── smoke_chart.py       # 冒烟：K 线图（3 grid/周期/悬停联动/缩放保持/信号定位/loading）★
│   ├── smoke_tshape.py      # 冒烟：期权 T 型（过期月/现价带居中/四列指标/代码复制/过滤/篮子/预设）★
│   ├── webengine_probe.py   # 验收探针工具（同步化 WebEngine 调用，各 smoke 脚本共用）
│   ├── build_frontend.sh    # 前端构建 + qrc 编译（改前端后的唯一入口）★
│   ├── smoke_patterns_wiring.py # 冒烟：量价形态经 detect_resonance → 配对全链路
│   ├── smoke_notify_click.py    # 冒烟：发真实系统通知，验证点击回调
│   ├── backtest_multi.py    # 本地多日多标的回测（毛/净双口径）★
│   ├── backtest_trend.py    # 趋势策略信号层回测（§11.6 Step 0，含份额拆分前复权+预测力诊断）★
│   ├── backtest_stocks.py   # 个股回测（Tushare 下载分钟线）★
│   ├── backtest_patterns.py # 单标的单日形态明细
│   ├── sweep_patterns.py    # 形态权重配置对比（命中结果缓存，秒级切换配置）★
│   ├── test_intraday_momentum.py # 日内动量检验（回归+策略+分档+按月）★
│   ├── diag_edge.py         # 信号预测力诊断（远期收益 vs 基准 + Welch t 检验）★
│   ├── diag_features.py     # 量价特征分位数分布（调阈值依据）
│   ├── diag_window.py       # 指定时段逐根特征明细
│   ├── diag_data_days.py    # 本地分钟数据覆盖天数统计
│   ├── fetch_etf_mins.py    # 下载 watchlist 全部 ETF 的 5 分钟线到 .cache
│   └── .cache/              # 回测缓存（pickle，不进 git）
└── watcher/
    ├── strategy/            # 期权策略计算（纯函数，无网络无 GUI）★
    │   ├── pricing.py       # BS 定价 + 希腊字母 + 隐含波动率反解
    │   ├── payoff.py        # Leg 模型 + 到期损益曲线 + 最大盈亏 + 盈亏平衡点
    │   ├── decay.py         # 时间价值衰减（1/3/7天）+ 组合希腊字母 + 压力测试
    │   └── presets.py       # 7 个策略模板（单腿/价差/跨式/宽跨式/蝶式）
    ├── __main__.py / main.py        # 入口
    ├── config.py            # pydantic 配置模型，yaml 加载
    ├── calendar.py          # 交易时段/轮询时段判断 + 时间解析统一函数 ★
    ├── bars.py              # 分钟K聚合（1分→N分，A股时段对齐，跨天不串）★
    ├── models.py            # Quote / MinuteBar / OptionContract / Signal / AppState
    ├── watcher_loop.py      # 后台轮询线程（QThread）★
    ├── state.py             # SQLite 持久化（快照/分钟K/信号/期权合约/期权行情）
    ├── option_meta.py       # 期权合约元数据 + 行情/Greeks（新浪）+ 分时K（东财）/分时线/日K（新浪）
    ├── fetchers/
    │   ├── base.py          # Fetcher 抽象 + FetchChain 降级链
    │   ├── tdx.py           # 通达信主源：并发探测选 IP + 断线重连 ★
    │   ├── eastmoney.py     # 东财备用：单只快照 + 分钟K
    │   └── tushare_src.py   # Tushare：期权历史日K + ETF日K + 交易日历 ★
    ├── signals/
    │   ├── rules.py         # 8 类行情异动规则 + detect_resonance（现只走量价形态）
    │   ├── patterns.py      # 量价形态：单根特征→标签→窗口序列打分 ★见第8节
    │   ├── intraday_momentum.py  # 市场日内动量（14:30 末半小时方向）★唯一显著信号
    │   ├── trend.py         # 趋势策略三层规则（§11.6 Step 0 回测不过线，留档备查）
    │   └── engine.py        # 规则执行器 + 买卖配对状态机（每日重置）
    ├── ai/                  # AI 策略推荐（DeepSeek）★
    │   ├── client.py        # API 客户端（深度思考模式 + JSON 容错解析）
    │   └── strategy_prompt.py # 市场上下文收集 + Prompt 组装 + 响应→合约匹配
    ├── notify/
    │   └── desktop.py       # macOS 原生通知（UNUserNotificationCenter）+ 点击跳转 ★
    └── gui/
        ├── app.py           # QApplication 入口（aboutToQuit 统一清理）
        ├── tray.py          # 系统托盘（手动 popup 菜单，绕 macOS 崩溃）
        ├── main_window.py   # 主窗口（HTML/ECharts 版）
        ├── alert_popup.py   # 预警弹窗

        └── web/
            ├── webtab.py    # QWebEngineView 封装（ChartTab / TableTab / TShapeTab / AnalysisTab + QWebChannel bridge）
            ├── chart.html   # ECharts K 线页（JS: window.updateChart）
            ├── table.html   # 通用表格页（JS: window.renderTable）
            ├── tshape.html  # 期权 T 型报价页（JS: window.renderTShape）★
            ├── analysis.html # 期权分析页旧版（已迁 Vue，保留供回退）
            ├── echarts.min.js
            ├── app.html      # Vue 前端产物（frontend/ 构建生成，不进 git；JS: 同名 render 入口）
            ├── web_resources.py / web_resources.qrc  # qrc 资源注册（改页面后跑 scripts/build_frontend.sh）
            └── __init__.py
```

## 4. 数据源（每个都有坑，必读）

### 4.1 通达信 TDX（主源）— `fetchers/tdx.py`

- **用途**：ETF/指数实时快照 + 1 分钟 K 线
- **连接**：`pytdx.hq.TdxHq_API`，主行情端口 7709，无需认证
- **选 IP**：不用 `select_best_ip`（又慢又吵），自己实现：内置 24 个常用服务器 + config 合并，`ThreadPoolExecutor` 并发 TCP 探测（1.5s 超时），按延迟排序，前 6 个逐个 `connect` 验证，结果缓存 5 分钟
- **断线**：fetch 返回空或异常 → 强制重新探测重连一次
- **价格缩放（极易踩）**：
  - 快照 `get_security_quotes`：ETF/股票 **÷10**，指数 **不除**
  - 分钟 K：**不除**（已是实际价格）
- **指数与 ETF 要用不同的取 K 线 API（极易踩）**：指数走 `get_index_bars`，ETF/股票走 `get_security_bars`，两者互斥。
  用 `get_security_bars` 取指数会返回垃圾：datetime 是 `2004-00-55 04:01` 这类乱码、close 也是错的（实测 5582 vs 正确 4546，只有第一条对）；
  反过来用 `get_index_bars` 取 ETF 返回空。判据用 `_is_index(market, pure)` —— **要分市场**：沪市 `000xxx` 是指数，深市只有 `399xxx` 是指数（深市 `000xxx` 是个股）
- **vol 字段**：可能是 `5.877e-39` 这种极小 float 或超大值，必须 `_safe_int` 否则 SQLite 溢出
- **servertime 字段不可靠**：正常是 `14:55:10.070`，但经常出现 `153:04:31.278` 这种 3 位小时段的怪格式。**无法解析时不许瞎猜**（之前"去百位1"产生了 45:15、53:04 等非法时间），统一回退到 `created_at`（见 §6 时间处理）

### 4.2 东方财富（备用）— `fetchers/eastmoney.py`

- **用途**：TDX 全挂时的快照兜底 + 分钟 K 备用
- **接口**：`push2.eastmoney.com/api/qt/stock/get`（单只）、`push2his.eastmoney.com/api/qt/stock/kline/get`（K 线）
- **secid**：`1.` 沪市、`0.` 深市；价格 ETF **÷1000**、指数 **÷100**
- **已知问题**：单只接口对单一 IP **间歇性拒绝连接**（设计文档实测），只作兜底，必须限速（0.15s/只）

### 4.3 新浪（期权）— `option_meta.py`

- **期权合约行情**：`hq.sinajs.cn/list=CON_OP_{code}`（必须带 `Referer: https://finance.sina.com.cn`，GBK 解码）
- **CON_OP 字段位置（2026-07 实网逐字段验证，勿凭旧资料猜）**：
  - `[2]` 最新价、`[0]/[1]` 买量/买价、`[3]/[4]` 卖价/卖量、`[5]` 持仓量、`[7]` 行权价、`[32]` 时间、`[36]` 标的、`[37]` 名称、`[41]` 成交量、`[44]` 昨结算、`[46]` 到期日
  - **`[6]` = 涨跌幅%（对昨结，官方口径，方向与 K 线一致）→ 用这个**
  - **`[38]` = 另一种涨幅（对除息重述基准）：除息调整日所有合约同向暴涨（T 型两边全红），勿用**
  - 历史教训：`[6]` 曾被误当成交量 → 成交量出现负值（不是深市字段偏移，沪深同一套布局）
- **Greeks/IV**：`hq.sinajs.cn/list=CON_SO_{code}`
- **深市快照有数据**（CON_OP_900xxxxx，与沪市同一字段布局）
- **分时折线**：`StockOptionDaylineService.getOptionMinline`（httpx 直连，8s 超时；**akshare 封装无超时会无限挂起，勿用**）— 返回 dict 列表 `{i:时间, p:价格, v:成交, t:持仓, a:均价, d:日期}`（d 仅首行有，需向下继承），**没有 OHLC，不能合成蜡烛图**，画分时折线（价格线 + 均价线）
- **日 K**：`jsonp_v2.php//StockOptionDaylineService.getSymbolInfo`（httpx 直连）— 返回 dict 列表 `{d,o,h,l,c,v}` 真实 OHLC；到期/异常合约可能返回 dict 错误体（必须 `isinstance(data, list)` 判断 + KeyError 兜底）
- **分时线/日K 只支持沪市**（合约 10 开头）；深市（90 开头）K 线走东财 trends2（见 §4.4）

### 4.4 期权分时 K（东财 trends2 = 设计主源，新浪 = 当前实际主力）— `option_meta.py`

- **数据源现状（2026-09 实测）**：
  - **真正在供数的是新浪**（`fetch_option_minute_bars`），仅沪市 `10xxxxxx`，当日 232~240 根。
  - **东财 trends2**（下面详记的那套，本是设计主源）近期实测**返回 0**（整域限流未恢复），只作为代码兜底留着。
  - **深市期权（90xxxxxx）分时两个源都取不到**——新浪接口不支持深市，接口本身的限制，不是缺陷。
  - **入库口径**：只挑「未到期 + 沪市 + 平值附近」的合约。别用「合约表前 N 个」——那是上一个到期月的已摘牌合约，取不到数据（踩过，见 §10）。
  - **数据体检**：`PYTHONPATH=. python scripts/diag_data_health.py` 一览今日各类数据完整度（盘中按应有根数估算画进度条，收盘后按 240 根算满，末尾汇总问题）。
- **用途**：期权合约的分时 K 线（真实分钟 OHLC，画蜡烛图），沪深都支持
- **接口**：`push2.eastmoney.com/api/qt/stock/trends2/get`，`fields2=f51,f53,f54,f55,f56,f57,f58`
  - 每点格式：`时间,最新价,最高,最低,成交量,成交额,均价`
  - **secid**：沪市期权 `10.{code}`、深市期权 `12.{code}`（实测确认；clist 同规则：`fs=m:10` 沪市 798 合约、`fs=m:12` 深市 504 合约）
  - open 用前一分钟收盘价填充（1 分钟 K 惯例），并夹进 [low, high] 防止跑出影线
  - **期权只给当日 241 点**（ndays=5 对期权无效，实测仍返回当日）；无成交的分钟/时段不给点（K 线出现缺口是正常表现）
  - 结果内存缓存 60s（`_EM_CACHE`），避免周期切换/刷新时连续请求触发封禁
  - **盘后可用性**：trends2 盘后可能停供，因此轮询线程盘中持续把近价合约（最近到期、ATM±2 档，约 90 个）的 1 分 K 缓存进 SQLite（`_cache_atm_option_bars`，1 请求/轮温和限速 + 连败 5 次冷却 10 分钟）；盘后点击优先读这份缓存出蜡烛图
- **★ 对单 IP 极敏感（2026-07 实测）**：连续快速请求会被**整域断连**（`Server disconnected`，连 `push2his`/`www` 之外的接口全灭），几分钟到 2 小时恢复。请求必须限速：用户点击（异步工作线程）+ ATM 轮换缓存（1 请求/轮 + 连败 5 次冷却 10 分钟），**禁止批量并发预加载**；失败重试 1 次、再失败降级新浪/本地缓存
- **同族接口实测结论**（本机 IP 当时状态）：`push2his kline` 被封不可达；`push2delay` 可连但**期权行情/K线全为空**（只有股票/ETF数据）；`push2 kline` 路径被针对性封禁；`push2 trends2/clist/stock/get` 可用但间歇断连
- **TDX exhq（备选未采用）**：仅 `112.74.214.43:7727` 可连但只剩 `get_instrument_count` 有响应，行情/K线全 None，残废不可用
- **腾讯/雪球/同花顺**：腾讯无期权合约（mkline param error），雪球需登录，同花顺未找到接口

### 4.5 Tushare（期权历史日K + 交易日历）— `fetchers/tushare_src.py` ★

- **token**：`~/.config/etf_watcher/secrets.env` 的 `TUSHARE_TOKEN`（权限 600）或环境变量；**不放 config.yaml**（那个会进 git/打包）。没 token 时整个模块静默禁用，全部降级到原有源
- **开关**：`config.yaml` 的 `tushare.enabled / option_daily / fund_daily_fallback / trade_calendar`
- **代码格式必须转换**：库里是 `10012055` / `sh510300`，Tushare 要 `10012055.SH` / `510300.SH`（沪市期权 `10` 开头→`.SH`，深市 `90` 开头→`.SZ`）
- `opt_daily`：期权历史日 K，**真实 OHLC + 持仓量 + 昨结算**。实测某合约拿到 **117 根**（2026-01-29 起），而新浪同合约只有 7 根 —— 这是目前唯一能补全期权历史日 K 的免费源（东财 kline 已被封）
- `fund_daily`：ETF 日 K 兜底。**vol 单位是"手"，要 ×100 换成股**才和 TDX 口径一致
- `trade_cal`：交易日历，落地 SQLite `trade_calendar` 表（只存交易日），离线也能判断。实测国庆假期正确（10/1–10/7 无交易日、10/8 开市）
- 限速：接口间隔 ≥0.35s（模块级 `_MIN_INTERVAL`）；任何失败都返回空 + 记 `last_error`，不抛异常

### 4.6 akshare（期权元数据）

- `option_current_day_sse()` / `option_current_day_szse()`：每日合约列表（含行权价、到期日、标的），共约 1200 个合约
- **期权标的共 11 个**（`option_meta.ETF_OPTION_UNDERLYINGS`：沪 6 + 深 5），但**交易所实际有合约的只有 9 个**——科创50ETF工银（588050）、创业板ETF易方达（159952）截至 2026-07 无上柜合约（两所官网合约清单实测）；期权页列表由合约表驱动（只显示 9 个），11 个 ETF 都在主页 watchlist 看行情
- 启动时加载一次存 SQLite，每 6 小时刷新
- **打包坑**：必须带 `akshare/file_fold/calendar.json`（两个 .spec 的 datas 已加）

## 5. 后台轮询架构 — `watcher_loop.py`

```
run():
  cleanup_old_data()
  load_option_contracts()        # akshare，6 小时一次
  force_refresh = True           # 启动立即刷一轮（收盘后也有数据）
  loop:
    refresh_one_option_underlying()   # 新浪期权行情，每轮换一个标的（全量一轮 ~45s）
    cache_atm_option_bars(underlying) # 该标的近价合约东财分时K缓存 1 个（轮换，盘后可用）
    if 非轮询时段 and not force: 跳过
    poll():                           # 快照在前（6 类报价信号尽快出）
      fetch(watch_codes)              # FetchChain: TDX → 东财，5s 一轮
      失败: 发缓存数据到 UI；连续 3 次失败才标记"未连接"
      成功: 存 SQLite → 信号检测(仅交易时段) → emit quotes_updated
    if 距上次 >= minute_refresh_seconds(5s):
      refresh_minute_bars()           # 分钟K并发批量拉（分钟级信号+图表）
    首轮后: preload_option_bars()     # 期权分钟K预加载（挪到首轮后，避免拖慢启动）
    sleep_interruptible(poll_interval_seconds=5s)  # 0.5s 粒度可中断
```

**轮询节奏**（2026-07-22 起）：快照 5s 一轮（TDX 无限流，实测有效周期 ~7-10s = 5s sleep + 网络工作），信号延迟从 ~35s 降到 ~10s；分钟 K 紧随快照同频刷新（分钟级信号依赖最新 bar），`FetchChain.fetch_minute_bars_batch` 并发批量拉取（TDX 每 worker 一条独立短连接——pytdx 单连接非线程安全不能共享，4 workers × ~13 标的 ≈ 1-2s 一轮；没拉到的 code 走单连接+东财兜底）；期权行情轮换不受影响。两个周期都在 `config.yaml` 的 `app.poll_interval_seconds` / `app.minute_refresh_seconds` 可调。

**时段三个概念**（`calendar.py`）：
- `is_trading_day`：**交易日判断**。先看周末，再查交易日历（Tushare 落地的 `trade_calendar` 表）；日历返回 `True/False/None`，`None`（没覆盖该日期）时退回周末判断。调休周六开市也能认出来
- `is_trading_hours`：交易日 9:25–11:30 / 13:00–15:00，**只有此时段做信号检测**
- `is_polling_hours`：交易日 9:00–15:30（含午休），**此时段都刷新数据**（午休行情照常有，不该空屏）

日历通过 `set_trade_day_checker()` 注入（`WatcherLoop.__init__` 里注入 `store.is_trade_date`），这样 `calendar.py` 不用反向依赖 `StateStore`；查询抛异常时自动退回周末判断，不会把轮询整体搞挂。

## 6. 时间与日期的统一处理 — `calendar.py` ★

所有时间解析收敛到两个函数，**任何新代码不要再自己解析**：

- `parse_quote_time(ts) -> "HH:MM:SS" | None`：支持 14 位/12 位数字串、正常冒号格式；TDX 异常 servertime 返回 None
- `signal_display_time(ts, created_at) -> str`：先 parse_quote_time，失败回退 created_at

**关键坑**：SQLite `DEFAULT CURRENT_TIMESTAMP` 存的是 **UTC**，回退显示/匹配时必须 `+8 小时` 转北京时间。

## 7. 数据库 Schema — `state.py`

- `quote_snapshots`：ETF 快照流水（7 天清理）
- `minute_bars(code, ts)`：分钟 K，ETF（source=tdx/eastmoney）和期权（source=eastmoney_option 分时K / sina_option 分时线 / sina_option_daily 日K）共用一表，查询时注意 source 区分；同一 (code,ts) 不同源会互相覆盖（INSERT OR REPLACE），后写者生效
- `signals`：`UNIQUE(date, code, signal_key)` 实现按日去重，`INSERT OR IGNORE` + rowcount 判断是否新信号
- `option_contracts`：约 1200 个合约元数据（expire_date 为 `20260722` 8 位格式）
- `option_quotes`：期权最新行情（含 IV/Delta/买卖价量；expire_date 为新浪的 `2026-07-22` 带横线格式——两表格式不同，**关联一律用 option_code**，不要用 expire_date）
- `trade_calendar(cal_date)`：交易日历，**只存交易日**（`YYYYMMDD`）。`is_trade_date()` 返回三态：在表里=True、落在已知区间内但不在表里=False（节假日）、超出已知区间=None（不知道，退回周末判断）
- `option_daily_snapshot(date, option_code)`：每日期权快照（收盘前 14:55 自动存一次），存 IV/OI/价格/delta/strike/expire_date，用于 IV 历史趋势分析和卖方指标分位计算；同日幂等（INSERT OR REPLACE）
- 路径：`platformdirs.user_data_dir("ETFWatcher")/etf_watcher.db`（macOS: `~/Library/Application Support/ETFWatcher/`）

## 8. 信号规则与回测结论 ★★ 新会话必读

### 8.1 行情异动信号 — `signals/rules.py`

| key | 规则 | 默认阈值 |
|---|---|---|
| gap_up / gap_down | 今开/昨收 | ≥ 0.8% |
| surge / plunge | 最新/昨收 | ≥ 2%（≥4% 升 critical） |
| rebound 探底回升 | 最低曾破昨收−1%，反弹≥1%，站上今开 | 1%/1% |
| reversal 冲高回落 | 最高曾超昨收+1%，回落≥1%，跌破今开 | 1%/1% |
| minute_surge / minute_plunge | 单根分钟K 开收 | ≥ 0.5% |
| iv_surge | 某标的期权中最高 IV 超阈值 | ≥ 50% |
| pcr_high / pcr_low | 认沽/认购持仓量比 PCR 偏高/偏低 | ≥ 1.5 / ≤ 0.5 |

K 线图上的标记：涨类红点（K 线下方）、跌类绿点（上方），ECharts markPoint，悬停显示详情。

### 8.2 量价形态 — `signals/patterns.py`

三层结构：单根特征（量比/实体/影线/跳空/振幅）→ 形态标签（放量大涨/巨量滞涨/平量横盘…）
→ 窗口序列形态加权打分。得分 ≥3 报买、≤-3 报卖，见顶形态一票否决买入。

**阈值自适应**：涨跌幅阈值取窗口内 `abs(chg)` 的 p75/p30 分位数，不用固定值
（固定 0.15% 比科创50ETF 1 分钟涨跌幅中位数 0.172% 还低，导致"窄幅蓄势"永不成立）。

- 主形态（权重 3，可单独触发）：量爆跟随、量堆积启动
- 辅助形态（权重 2，需共振）：探底回升、挤压突破、缩量回调反包、洗盘拉回、跳空不回补
- 看空形态（-2 ~ -3）：放量滞涨见顶、巨量见顶、高位长上影、冲高回落、高位破位、放量破位、量价背离、跳空回补

顶部形态额外要求「价格在区间上沿且有累计涨幅」，否则底部的巨量换手会被误判成见顶。
「高位破位」不要求放量 —— 实测顶部常是"平量滞涨"做出来的，要求放量会完全抓不到。

### 8.3 ⚠️ 回测结论：量价形态的买入信号未被证实有效

**别再基于短样本调这套形态的权重，这个坑已经踩过。**

| 样本 | 规模 | 结果 |
|---|---|---|
| ETF 5 天（本地 SQLite，1分） | 130 笔 | 胜率 57.7%，扣费 +13.78%，盈亏比 1.77 ← **噪声** |
| 个股 118 天（14 只，5分） | 387 笔 | 胜率 37.2%，毛 -10.39%，扣费 **-49.09%**，0/7 个月盈利 |

预测力诊断（`scripts/diag_edge.py`，Welch t 检验，个股 5 分钟，n=450 买/878 卖）：

| 周期 | 买入信号超额 | t值 | 卖出信号超额 | t值 |
|---|---|---|---|---|
| +1根 | -0.0062% | -0.32 | -0.0078% | -0.98 |
| +3根 | -0.0194% | -0.58 | **-0.0309%** | **-2.15** |
| +5根 | -0.0327% | -0.90 | -0.0276% | -1.38 |
| +20根 | +0.0141% | +0.18 | -0.0751% | -1.53 |

- **买入信号 t 值全在 ±1 内 = 白噪声**，且信号后上涨概率（40-42%）低于随机基准（44-45%）
- 卖出形态 +3根 t=-2.15，是唯一勉强显著的部分（"放量滞涨/高位破位"本质是反转信号）

**根本原因**：所有买入形态都是"追突破"（突破巨量根高点/创窗口新高/破前 5 根高点），
而 5 分钟级别 A 股是**强均值回归**的 —— 买在局部高点，接下来几根大概率回落。
大盘股最差（-0.211%/笔），流动性越好、日内突破越容易被砸回来。

文献一致：[arXiv:1504.04254](https://arxiv.org/abs/1504.04254) 与
[arXiv:1710.07470](https://ar5iv.labs.arxiv.org/html/1710.07470) 发现中国市场 TRB（突破）
类规则计入成本后利润归零；[SSRN 487783](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=487783.)
发现技术规则在 B 股有效、**A 股无效**；[SSRN 1009054](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1009054)
发现中国市场强均值回归、反向策略优于动量；
[Park & Irwin (SSRN 603481)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=603481)
专门警告技术分析研究里的 data snooping（本项目正是典型案例：1 天设计→5 天调参→387 笔崩塌）。

**若要重构方向**：证据指向做反向（放量大跌后买 / 放量大涨后卖），**未验证**。

### 8.4 ✅ 市场日内动量 — `signals/intraday_momentum.py`

**目前唯一统计显著的信号。** 依据 Gao/Han/Li/Zhou (2018) *Market Intraday Momentum*：
第一个半小时收益（自前收盘起算）正向预测最后一个半小时收益。

本地实测（11 个 ETF × 243 个交易日，Tushare 5 分钟线，2025-07~2026-07）：

预测性回归 `r_last ~ r_first`：斜率 +0.0555，**t=+7.32，R²=1.97%**（原文标普500 ≈2.0%，复现）

分档**完全单调**（这是最干净的证据）：

| 早盘涨幅 | 末半小时均值 | 上涨占比 | 天数 |
|---|---|---|---|
| < -1% | -0.0085% | 46.1% | 362 |
| -1~0% | +0.0115% | 51.6% | 869 |
| 0~1% | +0.0637% | 57.3% | 1026 |
| > +1% | +0.1808% | 61.2% | 405 |

策略（14:30 入场、15:00 平仓，已扣 0.05% 双边成本）：

| 变体 | 笔数 | 胜率 | 单笔均 | t值 |
|---|---|---|---|---|
| 多空双向 | 2618 | 48.2% | +0.0002% | +0.02 |
| 只做多(早盘>0) | 1387 | 53.8% | +0.0498% | +3.97 |
| **只做多(早盘>0 且 14:00-14:30>0)** | 687 | 55.0% | **+0.0867%** | **+5.00** |
| 反向(早盘<0才买) | 1231 | 46.3% | -0.0444% | -3.61 |
| 无条件做多末半小时 | 2662 | 50.2% | +0.0047% | +0.53 |

**三条关键结论（改这个模块前务必理解）**：
1. **只发看多信号**。多空双向 t=0.02 —— 加做空把收益抹平了；早盘大跌档末半小时均值
   仅 -0.0085%，做空无统计意义。代码里弱势只作提示不报信号，**别想当然加做空**。
2. **收益来自信号，不是蹭尾盘漂移**。无条件做多扣费后 t=0.53 不显著，
   而条件版毛收益是无条件的 **2.50 倍**（+0.1367% vs +0.0547%）。
3. **只对 ETF 用**。个股上 t=3.71、R²=0.83%、分档不单调，扣印花税后全部为负 ——
   原文标题即 "**Market** intraday momentum"，是市场级效应，个股特质波动会淹没它。

**实操限制**：+0.0867% 是标的收益。ETF 期权 ATM 买卖价差常在 1-3%（虚值更高），
标的 0.087% 对应期权 1-2%，价差会吃掉大部分。**定位为方向参考，不是机械交易信号。**

运行时：每天 14:30-14:40 扫一次全部 watchlist ETF，命中则推系统通知（每天一次，
`_momentum_alert_date` 去重）。

### 8.5 回测方法论（避免重复犯错）

1. **必须扣手续费**。ETF 双边约 0.05%，个股含印花税约 0.10%。日内策略单笔均收益
   常在 0.05-0.1% 量级，不扣费的结论毫无意义。`backtest_multi.py` 同时打印毛/净。
2. **样本量**：单日/5 天完全不够。同一形态在 1 分钟和 5 分钟上结论可能完全相反
   （量爆跟随：1分 51.3% 胜率主力 → 5分 28.6% 胜率最差），n=19 时二项标准差约 11.5%。
3. **看 t 值不看累计收益**。t < 2 一律当噪声。
4. **先诊断预测力再调参**。`diag_edge.py` 测信号后远期收益 vs 无条件基准，
   能区分"入场信号没用"和"出场逻辑差"，比反复调权重高效得多。
5. **口径要一致**。曾犯过基准行不扣费、策略行扣费的错误，导致对比失真。

## 9. UI 架构

### 9.1 Vue 前端（当前）

- **工程**：`frontend/`（Vue 3 + Vite + TS + Pinia）。`vite-plugin-singlefile` 打成**单文件** `app.html`，
  再进 qrc 由 `VueTab` 用 `setHtml` 加载。走 `qrc:` 源是刻意的：不起本地 HTTP server（省掉无鉴权端口的安全问题）。
  代价是多文件 ESM 会被 CORS 拦，所以必须单文件产物。
- **TypeScript 锁 5.x**：`vue-tsc` 与 TS 7 不兼容（TS7 是 Go 移植版，移除了 `./lib/tsc` 导出）。别升 7。
- **一个 `app.html` 多路由**：产物里的 `@@RJDJ_ROUTE@@` 标记在 `setHtml` 前被替换成路由名，
  每个 `VueTab(route=...)` 实例各自决定显示哪页。永久诊断路由 `__probe__` 供骨架冒烟用，与迁移进度解耦。
- **契约是「事实」不是「渲染指令」**：Python 只发原始数据（如 `renderQuotes` 发快照），
  分组/格式化/文案全在前端。旧版把视图逻辑放 Python（150 行）已废弃。
- **图表**：`echarts` 按需引入（4 图表 + 9 组件，产物 ~790K，比完整包小）。
  `EChart.vue` 用 `ResizeObserver` 自适应，一次解决旧版「面板展开只 resize 部分图表」「display:none 容器初始化为 0」。
  面板折叠用 `v-show` 不用 `v-if`（`v-if` 会销毁图表实例）。
  实例挂在宿主元素的 `el.__echarts__` 上，供验收脚本读取（按需引入下没有全局 `window.echarts`）。
- **不装 vitest**：store 逻辑由真实 WebEngine 回读 DOM 覆盖，比单元测试更贴近实际（布局/渲染问题单测覆盖不到）。
- **信号定位按时间戳**，不能用数组下标：信号是在当日 bars 上检测的（期权模式下用的还是对应 ETF 的 bars），
  与 `payload.bars` 的索引没有对应关系。两边 ts 可能一个 12 位一个 14 位，都截到分钟再比。

### 9.2 老手写 HTML（已迁 Vue，保留供回退）

- `webtab.py`：`_BaseTab(QWebEngineView)` 内嵌 qrc 里的 HTML；`QWebChannel` 注册 `bridge` 对象供 JS 调用（`requestRefresh` / `onRowClicked` / `requestPeriod`）
- Python → JS：`ChartTab.update_chart(payload)` → `window.updateChart(json)`；`TableTab.render(payload)` → `window.renderTable(json)`；`TShapeTab.render(payload)` → `window.renderTShape(json)`
- JS → Python：`bridge.onRowClicked(code, name)` → 看 K 线；`bridge.requestPeriod(p)` → K 线周期切换；
  `bridge.viewOption(code, side)` → 跳 T 型页（`side` 取 `call`/`put` 时顺带切过滤，空串表示不动用户当前选择。
  声明了 `@Slot(str)` + `@Slot(str, str)` 两个重载，因为老 `chart.html` 只传一个参数）；
  `bridge.copyText(text)` → 写 Qt 剪贴板
- **方向一次性下发**：`_on_view_option` 把方向记在 `_pending_tshape_filter`，由下一次 `render_tshape` 的
  `initialFilter` 字段带给前端，发出即清空。**必须一次性**，否则每 5 秒的定时刷新会反复把用户的过滤拽回去。
  另外 `setCurrentRow` 在行本来就选中时不触发 `currentItemChanged`，那种情况要自己补一发 `_load_option_quotes`
- **改前端后必须重新编译资源**：跑 `./scripts/build_frontend.sh`（vite build → app.html → pyside6-rcc 三步串联）。
  只改老的手写 HTML 也可以单独跑 `cd watcher/gui/web && pyside6-rcc web_resources.qrc -o web_resources.py`，
  但漏跑这步的话运行时加载的仍是旧内容（页面是从 qrc 读的）。
- payload 格式见 `main_window.py` 的 `_build_chart_payload` / `_load_option_quotes`（T 型）/ 各 `render({...})` 调用
- **K 线周期切换（chart.html）**：payload 带 `period`/`periods` 渲染按钮行；期权 N 分=东财 1 分经 `bars.aggregate_minute_bars` 聚合（A股时段对齐：09:30 起桶、11:30/15:00 并入当段、跨天不串）；ETF N 分=本地 1 分聚合；日K=新浪(沪市期权)/TDX category 9(ETF)，深市期权无日K源（按钮不显示）；跨天图 label 带 `MM-DD` 前缀；成交量红涨绿跌（蜡烛跟开收、分时跟前一分钟）
- **K 线自动刷新（main_window）**：`QTimer` 跟随 `poll_interval_seconds`，只在 ①`chart_window.isVisible()` ②`is_polling_hours` 内才 `_refresh_chart()`。
  K 线已改为**独立顶层窗口**（不是页签），所以判据是窗口可见性；启动时只记住默认标的、不弹窗也不取数，等点标的才开；主窗口 `closeEvent` 里一并 `hide()`。
  前端在 `setOption` 前读回旧 `dataZoom` 窗口，**自动刷新不重置用户缩放**
- **期权图表异步加载（main_window._ChartJob）**：期权取数走网络（东财慢/封时单次 ~17s），**绝不许跑 GUI 线程**（曾因此卡死界面）。QThreadPool(2) 跑取数+组包，`_chart_seq` 序号防乱序（连点两个合约，慢返回不会覆盖新的）；点击立即显示"加载中"（period 按钮可先切）；取数进行中自动刷新跳过本轮；异常时渲染空态（不会永远"加载中"）；ETF 图只读本地 SQLite 保持同步直出
- **K 线信息面板 + 悬停 legend（chart.html）**：右侧面板显示最新价/涨跌/涨跌幅/开高低收/成交量（期权加买一/卖一/持仓/IV；昨收由涨幅反推；成交量负值夹 0）；**面板与 legend 都跟随悬停 bar 联动**（`updateAxisPointer` → `barSideData(i)` 组装该根的 OHLC/涨跌/量，`globalout` 还原最新报价）；左上角 legend 股票软件风格，tooltip formatter 同步增强；payload 新增 `quote`（`_chart_quote()` 组装）和 `digits`（期权 4 位、ETF 3 位）
- **T 型报价页**：到期日 chips + CALL红/PUT绿（A股习惯：认购红、认沽绿）+ 行权价居中 + 现价带（插在 ATM 位置）+ 底部全部/CALL/PUT 过滤；payload 由纯函数 `option_meta.build_tshape_data()` 组装；同一行权价多合约（带A调整合约）纵向堆叠；悬停 tooltip 汇总全部字段。
  老 `tshape.html` 的指标列是**横向 3 页滑动**（`.colscroll` 同步 + ◀▶ 分页）；**Vue 版已改成四列一屏铺开**，见 §9.3
- 表格页 columns 支持 `type: num/pct`（digits 控制小数位，pct 自动红涨绿跌）

### 9.3 T 型页（Vue 版）实现要点

- **指标四列一屏**：合约代码/涨跌幅 · 卖一/买一 · 量/持仓 · IV/Delta，每列上下两行。
  取代旧版的横向 3 页滑动——信息量一样，但不用再滑，行高还从 57px 降到 47px（一屏 ~10 行 → ~12 行）。
  涨跌幅从「最新价」那个固定列挪进了代码列，所以加了代码也没增加行高。
- **表头必须补滚动条宽度**：`.thead` 在滚动容器 `.twrap` 外面，表体被纵向滚动条挤窄（QWebEngine 下 10px），
  两边各按 `1fr` 分列就会差 2~3px、列标题和数据错位。`TshapeTable` 用 `ResizeObserver` 量出
  `offsetWidth - clientWidth` 写进 `--tshape-sbw`，表头 `padding-right` 吃掉它。滚动条宽度各平台不同（macOS 覆盖式是 0），只能量不能写死。
- **现价带居中**（`composables/useStripScroll.ts`）：打开/换标的/换到期月/切过滤都定位一次。
  位移用 `getBoundingClientRect` 差值算，**不能用 `offsetTop`**（滚动容器没有定位属性，`offsetParent` 是更外层的元素）。
  容器 `clientHeight` 为 0 时（Qt 页签没激活）等下一帧重试。
- **点合约代码复制**：走 bridge 的 `copyText` 交给 Qt 剪贴板。
  **不能用 `navigator.clipboard`**——页面是 `qrc:` 源，不算 secure context，剪贴板 API 在那儿不可用。
- **表头标的价格点击 = 看该 ETF 的 K 线**（原来也是「回到现价」，和旁边按钮重复了）。
  复用 `rowClicked`，Python 按代码格式分流：8 位纯数字走期权（后台线程取东财），否则走 ETF（本地 SQLite 同步直出）。
- **退化 IV 不展示**：`fmtIv` 把 `< 1%` 的当没有。深度实值合约上数据源的 IV 求解器会返回触底值
  （实测 0.0009，对应 delta 已经是 1.0），显示成「0.1%」会被误读成波动率极低。
  注意 `smile.callIV` 那类字段已经是百分数，别套这个函数。
- **`.mpage` 之类的类名别叫 `.page`**：会和页面根容器的 `.page` 撞车，把整页变成两列网格（踩过一次，T 型布局整体塌陷）。

### 9.4 买卖点的三条路径（口径不同，容易搞混）

| 路径 | 数据来源 | 覆盖范围 | 说明 |
|---|---|---|---|
| K 线图上的 pin | **实时算，不读 DB**（`_compute_chart_signals`） | ETF / 指数 / 期权（期权用对应 ETF 的 bars） | 每次打开都在当日 bars 上滑窗回溯，能看到全天买卖点。**按图表当前显示的周期检测**（你看 1 分就用 1 分算） |
| 看板「最新买卖点」三列（1分/5分/15分） | 读 DB（`_latest_trade_signals`） | ETF / 指数 | 轮询里 `_detect_technical_signals` **按 1/5/15 分三个周期分别检测**、key 带周期标签（`resonance_long_5m_1024`），看板分列展示。每轮只测**当下**窗口，一天里逐轮攒 |
| 弹窗 / 系统通知 | `signals_fired` 信号 | **只有 ETF 的 5 分档** | 只发 `_ALERT_PERIOD`（5 分）那档：1 分太吵、15 分太钝。指数三档都不进提醒（不可交易，`cfg.is_index` 挡掉） |

- **为什么看板要三列**：同一时刻不同周期结论可能不同（1 分噪音多、更易触发）。以前看板只显示 5 分那档，
  用户在 K 线图看 1 分有买点、转头看板却没有，会以为漏了。三列分开就能一眼对上是哪个周期的信号。
- 「K 线图上有 pin 但看板对应周期列是空的」仍可能发生：前者全天回溯，后者只记录轮询当刻命中的。
- **15 分档取数量**：检测循环取 `get_bars(limit=600)`——15 分聚合要 ≥25 根即 ≥375 根 1 分，取 200 根时 15 分档永远达不到门槛（踩过）。
- 指数的 bars 是 2026-09 修好 `get_index_bars` 之后才开始积累的，数据攒够之前信号会比 ETF 少
  （实测：ETF 193 根 5 分 K 出 4~8 个信号，截到指数当时的 48 根同样出 0~1 个 —— 不是被挡住，是数据不够）。
- 事件类信号（急涨/跳空/日内拐点）仍然完全不看指数，见 `_poll` 里的 `is_index` 判断。

## 10. 已知坑与解决方案（新会话必读）

| 坑 | 现象 | 解法（已实现） |
|---|---|---|
| TDX servertime 异常格式 `153:04:31` | 信号时间显示 45:15、53:04 非法值 | `parse_quote_time` 不瞎猜返回 None，回退 created_at（+8h） |
| SQLite CURRENT_TIMESTAMP 是 UTC | 时间差 8 小时 | 所有 created_at 使用处 +8h |
| TDX 快照 ÷10 与分钟K不除 | 价格差 10 倍 / K 线错位 | snapshot ETF÷10 指数不除；分钟K不除 |
| TDX vol 极小 float | SQLite INTEGER 溢出 | `_safe_int` 范围检查 |
| macOS 27 beta 托盘 `setContextMenu` 崩溃 | 点托盘图标 abort | 不用 setContextMenu，`activated(Context)` 里手动 `menu.popup(QCursor.pos())` |
| `QCandlestickSeries.append(open=..)` | TypeError 不支持关键字参数 | 用 `QCandlestickSet(o,h,l,c)`（注：现已迁移 ECharts，旧代码可删） |
| 期权分钟线无 OHLC 硬合成蜡烛 | 全绿大实体失真 | 分时折线模式（价格线+均价线），source=sina_option 判定 |
| akshare 打包缺 file_fold | 运行时 FileNotFoundError | spec datas 加 `akshare/file_fold` |
| pytdx select_best_ip | 输出几十行噪音、串行慢 | 自实现并发 TCP 探测 + redirect 静默 |
| 东财单只接口间歇拒绝 | eastmoney returned empty | 仅作 TDX 兜底、限速、失败重试 |
| QThread 强退崩溃 | Cmd+Q 报 destroyed while running | sleep 可中断 + `app.aboutToQuit.connect(watcher.stop)` + wait 12s 兜底 terminate |
| 一轮失败就"未连接" | 启动瞬间空屏吓人 | 失败发缓存数据 + 连续 3 次才标记未连接 |
| 午休显示"非交易时段"空屏 | 11:30–13:00 无数据 | 轮询时段 9:00–15:30 与信号时段分离 |
| 表格可编辑 | 单击单元格进编辑态 | 全部 `NoEditTriggers`（HTML 版后已无此问题） |
| 新浪期权接口 403 | 直接请求被拒 | 必须带 `Referer: finance.sina.com.cn`，GBK 解码 |
| 东财整域间歇断连 | `Server disconnected without sending a response`（探测时连发请求触发） | 期权分时K只在用户点击时拉、重试1次、降级新浪；不做批量预加载 |
| 东财 kline/trends2 对期权返回空 | secid 市场号错（期权不是 0/1） | 沪市期权 `10.{code}`、深市期权 `12.{code}` |
| 分时K open 跑出影线 | open=前一分钟close 可能超出本分钟 [low,high] | 构造 bar 时 high/low 夹住 open |
| 两表 expire_date 格式不一致 | option_contracts 是 `20260722`、option_quotes 是新浪的 `2026-07-22`，按 expire_date join 查不到数据 | 关联一律用 option_code |
| 除息日 T 型两边全红 | 新浪 `[38]` 涨幅是对除息重述基准的，所有合约同向暴涨 | 涨跌幅用 `[6]`（对昨结官方口径），方向与 K 线一致 |
| 期权成交量为负/面板昨收异常 | `[6]` 被误当成交量字段；昨收/昨结基准混用 | 成交量用 `[41]`；期权涨跌幅对昨结、面板标注"昨结" |
| 期权点图卡死界面 | 图表网络取数跑在 GUI 线程（东财慢时单次 ~17s，叠加 5s 自动刷新=永久卡死） | `_ChartJob` 工作线程取数 + seq 防乱序 + inflight 时自动刷新跳过 |
| akshare 新浪分时/日K 挂起 | akshare 用 requests 无 timeout，网络异常时无限等待 | httpx 直连（8s 超时），返回是 dict 列表不是位置数组 |
| 新增 HTML 后白屏/404 | qrc 是编译进 web_resources.py 的，新文件没注册 | qrc 加 file 条目 + `./scripts/build_frontend.sh` |
| 改了页面但界面没变 | 页面从 qrc 读，改源文件不重编译不生效 | `./scripts/build_frontend.sh` |
| VueTab 报「找不到 @@RJDJ_ROUTE@@」 | app.html 是旧产物或没构建 | `./scripts/build_frontend.sh` |
| 分钟聚合 60 分出 6 根 | 朴素按整点分桶会把 11:30/15:00 单独成桶 | `bars._session_index` 按交易时段对齐（240 分钟制，收盘点并入当段） |
| 期权 N 分只有当天几根 | 东财 trends2 对期权只返回当日数据（ndays=5 无效） | 正常表现；历史看日K（新浪） |
| 东财趋势接口被周期切换打爆 | 每次切换都发请求，连发触发单 IP 封禁 | `_EM_CACHE` 60s 内存缓存 + 本地 SQLite 缓存兜底 |
| 悬停 legend/面板数据错位几百根 | `updateAxisPointer` 事件用了 `dataIndexInside`（缩放窗口内序号），默认缩放只显示末尾一段 → 映射到全量数据的错误位置 | 必须用 `ev.dataIndex`（绝对序号），tooltip 同理 |
| MA 线抢走买卖点 pin 的点击 | MA 线 `z:5` 比 markPoint 默认层级高，zrender 命中检测按 z 从高到低走，线横穿 pin 的地方形成点不动的死区（实测卖点 pin 视觉 28px、只有 ~5px 能点中） | markPoint 设 `z:12`，命中区恢复成连续 24~25px |
| Vue 3 模板 ref 写在 `v-for` 里会变数组 | `ref="stripEl"` 放在 `v-for` 内部 → `stripEl.value` 是数组，`.offsetTop` 取到 `undefined`，`scrollTop = NaN` 被**静默忽略**（不报错，只是不生效；T 型页现价带一直停在顶部就是这个） | 改用 `querySelector` 找元素，或用函数 ref |
| 冒烟里连续派发 MouseEvent 会被合并成 dblclick | zrender 就不再报 `click`，扫描命中区会出现物理上不可能的非连续结果（-6 ✓ / 0 ✗ / +6 ✓） | 几何测量用 `zr.handler.findHover(x,y)`（不涉及事件语义）；逐点验证一次会话只点一次 |
| 关掉 K 线窗口后主窗口「点了没反应」 | macOS 上关掉当前活动窗口后，主窗口虽可见但不是活动窗口，点它里面的内容第一下只用于激活窗口、不传给 QWebEngineView | `_ChartWindow.closeEvent` → `_on_chart_window_closed()` 主动 `raise_()`+`activateWindow()` 主窗口（主窗口已收进托盘则不打扰） |
| K 线窗口重新打开看不见 | ①最小化状态下 `show()` 不还原，窗口留在 Dock 里；②外接屏拔掉后窗口位置落在不可见区域 | `_show_chart_window`：最小化走 `showNormal()`；`_ensure_on_screen()` 不在任何屏幕内就搬回主屏中间 |
| **offscreen 平台复现不出窗口类问题** | `QT_QPA_PLATFORM=offscreen` 明确不支持 `raise()`（会打 "This plugin does not support raise()"），窗口激活/焦点/多屏行为都测不到 | 窗口层面的 bug 别指望无头冒烟能复现；改成断言「该调的方法调了」（见 `test_closing_chart_window_returns_focus_to_main`），真实表现要在 macOS 上验 |
| pytdx 单连接多线程共用 | 并发拉分钟K时协议错乱/返回空 | 每 worker 一条独立短连接（`fetch_minute_bars_batch`） |
| **指数 K 线取数用错 API**（根因） | 指数走了 `get_security_bars`，返回的 ts 是 `2035000011207` 乱码、价格也错（库里出现过 35 行负收盘价如 -73129）。表现：点看板的分组头（指数行）看 K 线，几个指数长得都一样/几乎没数据（指数只剩 12~21 根，ETF 有 3987 根） | 已修复：按 `_is_index` 分流到 `get_index_bars`。**注意**：早期只加了 `_is_valid_bar_ts` 跳过乱码 bar，那是治症状不是根因——侥幸通过校验的 bar 价格仍是错的 |
| **期权分时 K 请求全打在已摘牌合约上**（根因） | 某日期权分时 K 一根都没入库。`_preload_option_bars` 取 `get_option_contracts(u)[:20]`，而合约表排在前面的是上一个到期月（已摘牌），新浪对摘牌合约返回空，60 次请求全打空。`select_atm_contracts` 取「最近 n 个到期月」同样会选中已摘牌月，盘中 ATM 轮换那条路也一起失效 | 已修复：`select_atm_contracts` 先剔除 `expire_date < today` 的合约（新增 `today` 参数，测试显式传值防用例随时间失效）；`_preload_option_bars` 改成「未到期 + 沪市 + 平值附近」 |
| 新浪期权分时零成交分钟返回 p=0 | 照收会造出一根 o/h/l/c 全 0 的 bar，画到 K 线上纵轴从 0 起，期权价常在 0.001~1，真实波动被压扁（库里累积过 872 行，1 个在交易合约受影响） | `fetch_option_minute_bars` 解析时 `if price <= 0: continue` 丢弃 |
| 打包版 QtCharts/WebEngine 缺模块 | ImportError | spec hiddenimports 已含 QtCharts/QtWebEngineWidgets/QtWebEngineCore |
| 页面加载完成前 render 被丢弃 | 启动时 T 型页/看板空白，要等下一轮轮询才有内容 | `_BaseTab._run` 未加载完先入队，`loadFinished` 后按 JS 函数名去重补发最后一条 |
| 策略预设跨到期月挑腿 | 牛市价差挑成「买8月+卖12月」，最大盈亏/蝶式盈利算成负数（跨月到期损益不能叠加） | `presets.pick_expiry` 锁定单一到期月（默认最近月），同行权价按成交量去重（避开 A 调整合约） |
| 新浪 IV 偶发失真 | CON_SO 给出 4.3% 这种不合理 IV（ETF 期权正常 10%-40%），theta/时间损耗跟着算歪 | `_fix_leg_ivs`：IV 不在 [5%,200%] 就用市场价 `implied_vol` 反解，仍失败用同组均值 |
| `QWebEngineView.grab()` 抓不到网页内容 | 冒烟截图是全黑/空白（GPU 合成层截不到），且两张图字节数一样 | 冒烟改为 `runJavaScript` 读 DOM 断言（`smoke_strategy.py`），别依赖像素 |
| 冒烟里连续交互误判 | 一次交互是 JS→bridge→Python→JS 异步往返，步间隔 800ms 会偶发读到旧状态 | 冒烟步间隔提到 1100ms |
| Tushare 代码格式不同 | 直接拿 `10012055` / `sh510300` 请求返回空 | `to_ts_option_code` / `to_ts_fund_code` 转成 `10012055.SH` / `510300.SH` |
| Tushare `fund_daily` 成交量单位 | vol 是"手"，直接用会比 TDX 小 100 倍 | 解析时 ×100 换成股 |
| 交易日历三态别当布尔用 | `is_trade_date` 返回 None 表示"日历没覆盖"，当 False 用会把正常交易日判成休市 | 调用方必须区分 None，`is_trading_day` 里 None 退回 weekday 判断 |
| ETF 日线不复权：份额拆分造成 -60% 级假跳空 | 159922 于 2024-12-02 拆分 ×0.385、159901 于 2021-04-12 ×0.490；回测出现 -63% 假亏损、指标跨拆分点全歪 | 宽基 ETF 单日 \|涨跌\|>25% 不可能是真实行情（2024-09 极限才 ~20%）：`backtest_trend.adjust_corporate_actions` 按比率回除前段 OHLC 做前复权；分红小缺口（1-3%）不处理 |

## 11. 运行 / 打包 / 测试

```bash
cd /Users/huangxin/Desktop/trade_notice/pythonProject
source .venv/bin/activate          # Python 3.12 venv 已建好，依赖已装

python -m watcher                  # 开发运行
pytest tests/ -v                   # 测试（150 用例）
PYTHONPATH=. python scripts/smoke_option_chart.py    # 冒烟：点击期权合约→图表 payload
PYTHONPATH=. python scripts/smoke_chart_periods.py   # 冒烟：周期切换截图 /tmp/chart_*.png
QT_QPA_PLATFORM=offscreen QTWEBENGINE_CHROMIUM_FLAGS="--disable-gpu --in-process-gpu" \
  PYTHONPATH=. python scripts/smoke_tshape.py [代码]    # 冒烟：期权 T 型（Vue 版）
PYTHONPATH=. python scripts/smoke_underlyings.py     # 冒烟：看板/期权页标的列表
QT_QPA_PLATFORM=offscreen QTWEBENGINE_CHROMIUM_FLAGS="--disable-gpu --in-process-gpu" \
  PYTHONPATH=. python scripts/smoke_quote_board.py    # 冒烟：看板分组渲染（回读真实 DOM）
./scripts/build_frontend.sh                          # 前端构建 + qrc 编译（改 frontend/ 后必跑）
QT_QPA_PLATFORM=offscreen QTWEBENGINE_CHROMIUM_FLAGS="--disable-gpu --in-process-gpu" \
  PYTHONPATH=. python scripts/smoke_vue_shell.py      # 冒烟：Vue 骨架与桥接
QT_QPA_PLATFORM=offscreen QTWEBENGINE_CHROMIUM_FLAGS="--disable-gpu --in-process-gpu" \
  PYTHONPATH=. python scripts/smoke_analysis.py [代码]  # 冒烟：期权分析页 6 面板
QT_QPA_PLATFORM=offscreen QTWEBENGINE_CHROMIUM_FLAGS="--disable-gpu --in-process-gpu" \
  PYTHONPATH=. python scripts/smoke_chart.py [代码]     # 冒烟：K 线图
PYTHONPATH=. python scripts/smoke_strategy.py        # 冒烟：策略工具（预设/篮子/指标/损益图）
python scripts/backtest_trend.py                     # 趋势策略信号层回测（§11.6 Step 0 结论：不过线）

pyinstaller build/macos.spec --noconfirm --clean   # macOS 打包 → dist/ETFWatcher.app
pyinstaller build/windows.spec --noconfirm --clean # Windows（未实机验证）
```

打包产物：`dist/ETFWatcher.app`（`build/macos/` 下的是中间文件，`ETFWatcher.pkg` 不是安装包）。首次打开被 Gatekeeper 拦时：系统设置 → 隐私与安全性 → 仍要打开。

## 11.5 期权策略工具 — `watcher/strategy/` ★

T 型页底部抽屉，点表格行里的「买」「卖」加腿，或点预设按钮自动挑腿。

- **计算全部在本地**（纯函数、无网络），BS 定价 12/26/9 之外的参数：无风险利率 1.5%（`pricing.DEFAULT_RISK_FREE`）、按**自然日/365** 贴现
- **金额口径**：ETF 期权合约单位 10000 份，`Leg.scale = 方向 × 张数 × 10000`，所有指标单位是"元"
  - delta = 标的涨 1 元的盈亏（元）｜theta = 每过一自然日的盈亏（元）｜vega = IV 涨 1 个百分点的盈亏（元）
- **时间损耗不用 theta 线性外推**，而是按「剩余天数 − N」重新 BS 定价（临近到期 theta 会加速，线性外推低估损耗）
- **最大盈亏的"无限"判定**：看极端价外侧斜率（`_slope_beyond`），不是取采样极值——否则裸卖认购会被算成"最大亏损有限"
- **预设锁定单一到期月**（见 §10 坑表），到期日两种格式（`20260826` / `2026-08-26`）都能对上
- 数据来源：合约表 `option_contracts` + 行情表 `option_quotes`，关联只用 `option_code`

```python
from watcher.strategy import Leg, build_preset, summarize, decay_schedule, combo_greeks
legs = build_preset("bull_call_spread", chain, spot)   # chain 为 T 型 payload 口径的 dict 列表
s = summarize(legs, spot)          # netCost / maxProfit(None=无限) / maxLoss / breakevens
d = decay_schedule(legs, spot)     # perDay = 标的不动时每天亏多少
g = combo_greeks(legs, spot)       # 组合希腊字母（已乘方向/张数/合约单位）
```

**JS ↔ Python**：`bridge.requestStrategy(json)` → `main_window._on_strategy_requested` → `TShapeTab.render_strategy(payload)` → `window.renderStrategy(json)`。篮子状态在 JS 侧（`BASKET`），换标的自动清空。

## 11.6 ETF 期权趋势策略信号化：Step 0 回测不过线，已终止（P1/P2 工具层可独立评估）

> 来源文档：`/Users/huangxin/Downloads/炒股/ETF期权趋势策略映射文档.md`
> （crypto 趋势策略 → A 股 ETF 期权映射，**设计稿未经回测**，所有参数为先验估值）。
> 总原则：只做信号提醒（观察员），不做自动交易；参数进 `config.yaml` 可调；
> **先回测再接提醒**（§8.5 纪律 + 原文档第 7 节验证流程：PF>1.1 才继续）。
> 与第 8 节的关系：这是**日线趋势层**，与被证伪的 5 分钟突破形态不是一个时间尺度，不冲突不重复。

### Step 0 信号层回测（先于一切，不过线不做 P0）—— ❌ 不过线（2026-08-03 已执行，结论见下）

- 新脚本 `scripts/backtest_trend.py`（复用 backtest_multi / diag_edge 基建与口径）
- 数据：11 个 watchlist ETF 日线 3 年+（TDX category 9 分页 ~2400 根 ≈ 10 年；不够用 Tushare `fund_daily` 补）
- 三层规则（回测与实盘共用同一份实现，放 `watcher/signals/trend.py`）：

```
第1层 方向闸门（周线，日线重采样）
  close > 周EMA20 且 周EMA10 抬头 → 只做多（买认购）
  close < 周EMA20 且 周EMA10 走低 → 只做空（买认沽）
  方向不明 → 观望
第2层 趋势强度（日线）
  ADX(14) > 30 且 DI差值 > 10 且 ATR比率 > 0.8（ATR/close ÷ 其250日滚动中位数）
第3层 结构确认（日线）
  多: close > EMA50 且 EMA10 > EMA20；空: 反之
出场: 周线明确反向
```

- EMA/ADX/ATR 手算（无外部依赖）；评估口径=标的当量（暂不模拟期权），扣双边 0.05%
- **过线标准**：牛熊两段、PF > 1.1、t ≥ 2；不过线就记录结论放弃（§8.5：负面结果照样记录）

#### Step 0 回测结论（2026-08-03）：不过线，P0 放弃

样本：11 个 ETF × 2016-09~2026-08 日线（TDX，已前复权处理 2 次份额拆分：
159922 于 2024-12-02 ×0.385、159901 于 2021-04-12 ×0.490——宽基 ETF 单日 |涨跌|>25%
不可能是真实行情，按比率回除）。 warmup 消耗首年（250 日 ATR 中位数 + 20 周闸门），
实际交易 2017-10 ~ 2026-08，共 195 笔，平均持仓 83 个自然日。

| 口径 | 笔数 | 胜率 | 单笔净 | PF | t 值 | 判定 |
|---|---|---|---|---|---|---|
| 次日开盘成交（主口径） | 195 | 34.4% | -0.407% | 0.90 | -0.45 | ✗ |
| 信号日收盘成交（对照） | 196 | 36.7% | +0.173% | 1.05 | +0.20 | ✗ |

按年份（主口径）：2018 +84%、2022 +56%、2025 +88%（单边市盈利），
**2024 -296%（23 笔胜率 8.7%，t=-3.42）**——V 型反转年是坟场：6~8 月空单被 9/24
行情轧空（周闸门数周才翻转），10/8 顶点多单接刀后扛 3 个月阴跌（出场只看周线反向）。
牛市段 PF 0.85、熊市/震荡段 PF 0.95，**两个时段都不过线**，不是单边依赖。

入场信号预测力诊断（同 diag_edge 口径，方向调整后超额 vs 无条件基准）：

| 周期 | 多头信号超额 | t值 | 空头信号超额 | t值 |
|---|---|---|---|---|
| +5日 | +0.136% | +1.23 | **-0.226%** | **-2.68** |
| +10日 | +0.123% | +0.92 | **-0.322%** | **-2.79** |
| +20日 | -0.443% | -1.94 | **-0.439%** | **-2.34** |

- **多头信号无预测力**（t 全在 ±2 内）——不是出场层的锅，入场本身没有 edge
- **空头信号显著为负**（信号后市场倾向上涨）——日线级别 A 股同样是均值回归，
  与 §8.3 五分钟结论在不同时间尺度上互证：追趋势在 A 股 ETF 各周期都被打脸
- crypto 原策略的盈利前提（趋势延续 + 快出场）在 A 股日线不成立；
  周线闸门在 V 型反转里的响应延迟是结构性的，调参无法解决（2024 一年亏光其他所有年份）

产物（保留备查/复用，勿删）：`watcher/signals/trend.py`（三层规则，15 个单测）、
`scripts/backtest_trend.py`（含 --exec-close 对照、份额拆分前复权、预测力诊断）、
`tests/test_trend.py`、`scripts/.cache/etf_daily.pkl`（10 年日线缓存）。
P0/P1/P2 中仅 **P1/P2 属独立工具层可另行评估**；信号路径就此终止，勿再调权重重试
（§8.5：t<2 一律当噪声，同一数据集上反复调参 = data snooping）。

### P0 趋势信号接入（Step 0 过线后）—— ❌ 已放弃（Step 0 不过线，勿再试）

- 信号类型（建议）：`trend_gate_long/short`（闸门翻转）、`trend_confirm_long/short`（三层全满足）、`trend_exit`（周线反向）
- 复用现有管道：按日去重 + 系统通知/弹窗 + 日K 打点；11 个 watchlist ETF 全算
- 触发节奏：盘中用最新（未完成）日K 评估 + 收盘定版，**状态变化才发**，不做每轮重复提醒
- 参数全部 `config.yaml` 可调（ADX 30、EMA 周期、ATR 比率 0.8 等先验值）
- 验收：构造历史日K 样例的单测（闸门方向/强度边界/结构判定/翻转只发一次）；信号时间沿用 `calendar.py` 统一函数

### P1 T 型页策略筛选器（工具层配套，独立可做）

- Delta ≥ 0.7 深实值合约高亮 +「只看深实值」过滤按钮（对应策略"深实值当杠杆标的"；数据已有 `option_quotes.delta`，加在 filter-bar）
- 到期周提示：到期日 chips 在到期周（每月第 4 个周三所在周）变色，对应"到期周不开新仓、持仓周一前移仓"纪律

### P2 IV 历史积累（IV 过滤器前置）

- 新表 `iv_history(underlying, date, atm_iv)`：每日收盘后存一次各标的 ATM IV（CON_SO 每 45s 轮换在刷，取最后一次）
- 攒够历史后实现"IV > 过去一年 80% 分位不开新仓"；过渡期可用 60 日分位

### 暂不做（文档边界，别越界）

- 出场层自动跟踪（标的 -1.6% 硬止损 / trailing +1.6% 启动回撤 0.8% / +6% 封顶递减）：需要持仓登记与成交假设，等 P0 信号实盘观察一段时间再议
- 工具层/仓位层自动化执行：原文档自己要求模拟盘验证，app 不做

## 12. 建议的后续方向（按价值排序）

0. ~~**趋势策略信号化**~~：Step 0 回测不过线（PF 0.90 / t -0.45，2024 V 型反转年 -296%），P0 已放弃，详见 §11.6 结论；P1 深实值筛选 / P2 IV 历史为独立工具层可另行评估
1. ~~**Tushare 补历史**~~：已完成（v0.6）— `opt_daily` 补期权历史日 K（实测 117 根 vs 新浪 7 根）；`trade_cal` 做交易日历节假日不轮询；`fund_daily` ETF 日K兜底
2. ~~**DeepSeek 策略推荐**~~：已完成（v0.8）— 手动触发、喂行情/技术面/期权链/Tushare历史，结构化策略+一键填篮子
3. ~~**期权信号**~~：已实现（v0.5.1）— IV 飙升（单合约 IV≥50%）+ PCR 异常（持仓量比 ≥1.5 / ≤0.5），阈值可配置
4. ~~**指数分钟K时间戳脏值**~~：已修复（v0.5.1）— `_parse_bars` 增加 `_is_valid_bar_ts` 校验，乱码 ts 的 bar 被跳过，指数分钟K自动降级到东财源
5. ~~**删除死代码**~~：已完成（v0.5.1）
6. ~~**交易日历**~~：已完成（v0.6）— Tushare `trade_cal`，节假日不轮询
7. ~~**期权分析页 + IV/OI 历史积累**~~：已完成（v0.9）— 独立 Tab：6 个分析面板（卖方指标/微笑/持仓量/多月对比/曲面/期限结构）+ `option_daily_snapshot` 每日自动存储
8. **设置页**：GUI 内编辑 watchlist / 阈值（现在改 config.yaml 需重启）
9. **远程推送**：Bark / Server酱 / 企业微信 webhook（notify/ 加通道，配置驱动）
10. **Windows 实机打包验证**
11. **量价形态方向重构**：证据指向做反向（放量大跌后买/放量大涨后卖），未验证，见 §8.3
12. **IV/OI 历史趋势图**：`option_daily_snapshot` 攒够 30+ 天后，在期权分析页加 IV/PCR 历史折线和分位计算
