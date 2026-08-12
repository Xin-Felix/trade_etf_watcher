# 日进斗金 — 项目对接文档

> 版本：v0.9 | 更新：2026-08-12
> 本文档面向需要与本项目数据/功能集成的外部项目

---

## 1. 项目概述

**日进斗金** 是一个 macOS 桌面 ETF/期权盯盘程序，核心能力：

- 实时监控 11 个 A 股 ETF 期权标的（5s 轮询）
- 1200+ 期权合约的实时行情、Greeks、IV
- 期权分析：波动率微笑/曲面、持仓量分布（MaxPain/Call墙/Put墙）、卖方指标
- 信号检测：跳空/急涨急跌/量价形态/日内动量/IV飙升/PCR异常
- 策略工具：BS 定价 + 组合损益 + AI 推荐（DeepSeek）
- **每日自动存储期权快照**（IV/OI/价格），积累历史数据

技术栈：Python 3.12 + PySide6 + SQLite + pytdx + akshare + httpx

---

## 2. 数据库位置与连接

```
路径：~/Library/Application Support/ETFWatcher/etf_watcher.db
引擎：SQLite 3
编码：UTF-8
```

Python 连接示例：
```python
import sqlite3
from pathlib import Path
import platformdirs

db_path = Path(platformdirs.user_data_dir("ETFWatcher")) / "etf_watcher.db"
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
```

---

## 3. 数据库完整表结构

### 3.1 quote_snapshots — ETF 行情快照流水

存储 ETF/指数的实时行情快照（5s 一条，保留 7 天自动清理）。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增 |
| code | TEXT | 标的代码（如 `sh510050`、`sz159901`） |
| name | TEXT | 中文名（如 "上证50ETF"） |
| price | REAL | 最新价 |
| open | REAL | 今开 |
| high | REAL | 最高 |
| low | REAL | 最低 |
| prev_close | REAL | 昨收 |
| volume | INTEGER | 成交量（股） |
| ts | TEXT | 时间戳（格式 `YYYYMMDDHHmmss`，14位） |
| source | TEXT | 数据源（`tdx` / `eastmoney`） |
| created_at | TIMESTAMP | UTC 创建时间 |

索引：`(code, ts)`

### 3.2 minute_bars — 分钟 K 线

ETF 和期权合约共用一表（通过 source 区分）。

| 字段 | 类型 | 说明 |
|------|------|------|
| code | TEXT | 标的/合约代码 |
| ts | TEXT | 时间戳 `YYYYMMDDHHmmss` |
| open | REAL | 开盘价 |
| high | REAL | 最高价 |
| low | REAL | 最低价 |
| close | REAL | 收盘价 |
| volume | INTEGER | 成交量 |
| source | TEXT | 来源（见下） |
| updated_at | TIMESTAMP | UTC 更新时间 |

主键：`(code, ts)`

**source 取值**：
- `tdx` / `eastmoney`：ETF 1分钟K
- `eastmoney_option`：期权分钟K（东财 trends2，有真实 OHLC）
- `sina_option`：期权分时线（新浪，只有 close，OHLC 为模拟值）
- `sina_option_daily`：期权日K（新浪）
- `tushare_option_daily`：期权日K（Tushare）
- `aggregated_daily`：本地聚合的日K

### 3.3 option_contracts — 期权合约元数据

约 1200 个合约，每日刷新一次（akshare 从交易所拉取）。

| 字段 | 类型 | 说明 |
|------|------|------|
| option_code | TEXT PK | 合约代码（如 `10007389`=沪市、`90000651`=深市） |
| underlying_code | TEXT | 标的代码（如 `sh510050`） |
| option_name | TEXT | 合约简称（如 "50ETF购8月3500"） |
| exchange | TEXT | 交易所（`SSE` / `SZSE`） |
| option_type | TEXT | `call` / `put` |
| strike | REAL | 行权价 |
| expire_date | TEXT | 到期日（**8位格式 `20260826`**） |
| updated_at | TIMESTAMP | 更新时间 |

索引：`(underlying_code)`

### 3.4 option_quotes — 期权实时行情（最新快照）

每个合约只保留最新一条（INSERT OR REPLACE），盘中约 45s 更新一轮。

| 字段 | 类型 | 说明 |
|------|------|------|
| option_code | TEXT PK | 合约代码 |
| underlying_code | TEXT | 标的代码 |
| option_name | TEXT | 合约简称 |
| option_type | TEXT | `call` / `put` |
| strike | REAL | 行权价 |
| price | REAL | 最新价（收盘价） |
| change_pct | REAL | 涨跌幅%（对昨结算价） |
| volume | INTEGER | 成交量（张） |
| open_interest | INTEGER | 持仓量（张） |
| iv | REAL | 隐含波动率（小数，如 0.224 = 22.4%） |
| delta | REAL | Delta（如 0.55 / -0.45） |
| gamma | REAL | Gamma |
| theta | REAL | Theta |
| vega | REAL | Vega |
| ts | TEXT | 行情时间 |
| expire_date | TEXT | 到期日（**带横线格式 `2026-08-26`**，注意与 contracts 表不同） |
| buy_price | REAL | 买一价 |
| buy_vol | INTEGER | 买一量 |
| sell_price | REAL | 卖一价 |
| sell_vol | INTEGER | 卖一量 |
| updated_at | TIMESTAMP | 更新时间 |

索引：`(underlying_code)`

**注意**：`expire_date` 格式与 `option_contracts` 不同！关联两表一律用 `option_code`。

### 3.5 option_daily_snapshot — 每日期权快照（历史数据）

每天收盘前（14:55）自动存一次全部有行情合约的快照，用于 IV/OI 历史分析。

| 字段 | 类型 | 说明 |
|------|------|------|
| date | TEXT | 日期 `YYYYMMDD` |
| option_code | TEXT | 合约代码 |
| underlying_code | TEXT | 标的代码 |
| option_type | TEXT | `call` / `put` |
| strike | REAL | 行权价 |
| expire_date | TEXT | 到期日 |
| price | REAL | 收盘价 |
| volume | INTEGER | 当日成交量 |
| open_interest | INTEGER | 持仓量 |
| iv | REAL | 隐含波动率 |
| delta | REAL | Delta |
| created_at | TIMESTAMP | 创建时间 |

主键：`(date, option_code)`
索引：`(underlying_code, date)`、`(date)`

### 3.6 signals — 信号记录

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增 |
| date | TEXT | 日期 `YYYY-MM-DD` |
| code | TEXT | 标的代码 |
| name | TEXT | 标的名称 |
| signal_key | TEXT | 信号类型（如 `surge`、`iv_surge`、`pcr_high`） |
| label | TEXT | 显示标签（如 "急涨"、"IV 飙升"） |
| detail | TEXT | 详情文本 |
| level | TEXT | 级别（`info` / `warning` / `critical`） |
| ts | TEXT | 信号时间 |
| ack | INTEGER | 是否已确认（0/1） |
| created_at | TIMESTAMP | 创建时间 |

唯一约束：`(date, code, signal_key)` — 同一信号每天只记一次

### 3.7 trade_calendar — 交易日历

| 字段 | 类型 | 说明 |
|------|------|------|
| cal_date | TEXT PK | 交易日日期 `YYYYMMDD`（**只存交易日**，不在表中=休市） |
| updated_at | TIMESTAMP | 更新时间 |

### 3.8 state_meta — 键值存储

内部状态（如提醒开关、API key 等），格式 `key TEXT PK, value TEXT`。

---

## 4. 监控标的列表

共 11 个 ETF 期权标的（其中 9 个有期权合约）：

| 代码 | 名称 | 交易所 | 有期权 |
|------|------|--------|--------|
| sh510050 | 上证50ETF | 沪 | ✅ |
| sh510300 | 沪深300ETF | 沪 | ✅ |
| sh510500 | 中证500ETF | 沪 | ✅ |
| sh588000 | 科创50ETF | 沪 | ✅ |
| sh588080 | 科创50ETF易方达 | 沪 | ✅ |
| sh588050 | 科创50ETF工银 | 沪 | ❌ |
| sz159919 | 沪深300ETF | 深 | ✅ |
| sz159915 | 创业板ETF | 深 | ✅ |
| sz159922 | 中证500ETF | 深 | ✅ |
| sz159901 | 深证100ETF | 深 | ✅ |
| sz159952 | 创业板ETF易方达 | 深 | ❌ |

---

## 5. 功能模块详细说明

### 5.1 实时行情轮询

- 数据源链：通达信 TDX（主）→ 东方财富（备）
- 轮询周期：5 秒
- 输出：11 个 ETF 最新价/开高低收/成交量，存入 `quote_snapshots` 和内存

### 5.2 期权行情

- 数据源：新浪（行情 + Greeks）+ 东财（分钟K线）
- 覆盖：9 个有合约标的 × 约 1200 个合约
- 更新频率：每轮轮换一个标的全量更新（一轮约 45s 覆盖全部 9 个）
- 字段：价格、买卖盘、IV、Delta/Gamma/Theta/Vega、持仓量、成交量

### 5.3 期权分析（独立 Tab 页）

#### 卖方指标面板
| 指标 | 计算方式 | 用途 |
|------|---------|------|
| 平值 IV | ATM 档 (Call IV + Put IV) / 2 | 波动率水平参考 |
| 25Δ 偏斜 | Put 25Δ IV − Call 25Δ IV | 正值=Put贵=恐慌 |
| PCR 持仓 | Put总OI / Call总OI | >1.5极度看空，<0.5极度看多 |
| 预期波动 | ATM跨式价格 / 标的价 × 100% | 到期前隐含涨跌幅 |
| Call/Put 总持仓 | 全月合约汇总 | 市场持仓规模 |

#### 波动率微笑
- 横轴：行权价，纵轴：IV%
- 双线：Call IV（绿）/ Put IV（红）
- 标注：标的现价蓝色虚线
- 支持当月单图 + 多到期月叠加对比

#### 持仓量分布
- 柱状图：Call OI（绿）/ Put OI（红）
- 标注：
  - **Call墙**（Call OI 最大档位，上方阻力）— 金框
  - **Put墙**（Put OI 最大档位，下方支撑）— 金框
  - **MaxPain**（最大痛点，到期收敛价）— 橙线
  - **现价** — 蓝虚线

#### 波动率曲面
- 热力图：行 = 到期月，列 = 行权价
- 颜色：绿(低IV) → 红(高IV)
- ATM 档黑框标注

#### 平值 IV 期限结构
- 折线图：各到期月 ATM IV
- 自动判断倒挂（近月 > 远月）/ 正常上斜

### 5.4 信号检测

| 信号类型 | key | 触发条件 |
|---------|-----|---------|
| 跳空 | gap_up / gap_down | 今开/昨收 ≥ 0.8% |
| 急涨/急跌 | surge / plunge | 最新/昨收 ≥ 2% |
| 探底回升 | rebound | 最低曾破-1%，反弹≥1%，站上今开 |
| 冲高回落 | reversal | 最高曾超+1%，回落≥1%，跌破今开 |
| 分钟急涨/急跌 | minute_surge / minute_plunge | 单根分钟K ≥ 0.5% |
| IV 飙升 | iv_surge | 合约 IV ≥ 50% |
| PCR 偏高/偏低 | pcr_high / pcr_low | PCR ≥ 1.5 / ≤ 0.5 |
| 日内动量 | intraday_momentum | 14:30 推末半小时方向（统计显著 t=5.0） |

### 5.5 策略工具

- BS 定价（欧式期权）+ 隐含波动率反解
- 组合策略：7 个预设模板（牛市/熊市价差、跨式、蝶式等）
- 到期损益曲线 + 最大盈亏 + 盈亏平衡点
- 时间衰减（1/3/7天精确定价，非 theta 线性外推）
- 组合 Greeks
- AI 策略推荐（DeepSeek，手动触发）

### 5.6 每日快照存储

- 触发时间：每交易日 14:55-15:00
- 存储内容：全部有行情合约的 IV、OI、价格、Delta
- 表：`option_daily_snapshot`
- 用途：积累历史数据，后续可做 IV/PCR 分位计算、历史趋势图

---

## 6. 常用查询示例

### 获取某标的当前全部期权行情
```sql
SELECT * FROM option_quotes
WHERE underlying_code = 'sh510050'
ORDER BY expire_date, strike, option_type;
```

### 获取某标的 PCR（持仓量）
```sql
SELECT
  SUM(CASE WHEN option_type='put' THEN open_interest ELSE 0 END) as put_oi,
  SUM(CASE WHEN option_type='call' THEN open_interest ELSE 0 END) as call_oi,
  ROUND(1.0 * SUM(CASE WHEN option_type='put' THEN open_interest ELSE 0 END)
    / NULLIF(SUM(CASE WHEN option_type='call' THEN open_interest ELSE 0 END), 0), 3) as pcr
FROM option_quotes
WHERE underlying_code = 'sh510050';
```

### 获取历史 IV 趋势（需要积累数据后）
```sql
SELECT date,
  AVG(CASE WHEN option_type='call' THEN iv END) as avg_call_iv,
  AVG(CASE WHEN option_type='put' THEN iv END) as avg_put_iv,
  SUM(CASE WHEN option_type='call' THEN open_interest ELSE 0 END) as total_call_oi,
  SUM(CASE WHEN option_type='put' THEN open_interest ELSE 0 END) as total_put_oi
FROM option_daily_snapshot
WHERE underlying_code = 'sh510050'
GROUP BY date
ORDER BY date;
```

### 获取某日 MaxPain 计算所需数据
```sql
SELECT strike, option_type, open_interest
FROM option_daily_snapshot
WHERE underlying_code = 'sh510050'
  AND date = '20260812'
  AND expire_date = '20260826'
ORDER BY strike;
```

### 获取 ETF 最新行情
```sql
SELECT code, name, price, prev_close,
  ROUND((price - prev_close) / prev_close * 100, 2) as change_pct
FROM quote_snapshots
WHERE code IN ('sh510050', 'sh510300', 'sz159901')
GROUP BY code
HAVING ts = MAX(ts);
```

### 获取交易日历
```sql
-- 判断某天是否交易日
SELECT COUNT(*) > 0 FROM trade_calendar WHERE cal_date = '20260812';

-- 获取最近 N 个交易日
SELECT cal_date FROM trade_calendar ORDER BY cal_date DESC LIMIT 20;
```

---

## 7. 集成方式建议

### 方式 A：直接读 SQLite（推荐）

最简单，直接 attach 或 open 同一个数据库文件：

```python
import sqlite3
from pathlib import Path
import platformdirs

DB_PATH = Path(platformdirs.user_data_dir("ETFWatcher")) / "etf_watcher.db"

def get_option_analysis(underlying_code: str):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM option_quotes WHERE underlying_code = ? AND price > 0",
        (underlying_code,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
```

**注意**：SQLite 支持多读单写，本程序写入频率低（5s 写一次快照），读取不会阻塞。

### 方式 B：复用 Python 模块

如果在同一个 Python 环境中，可以直接 import：

```python
# 添加项目路径
import sys
sys.path.insert(0, "/Users/huangxin/Desktop/trade_notice/pythonProject")

from watcher.state import StateStore
from watcher.option_meta import build_tshape_data
from watcher.strategy.pricing import bs_price, greeks, implied_vol

store = StateStore()

# 获取期权行情
quotes = store.get_option_quotes("sh510050")

# 获取合约列表
contracts = store.get_option_contracts("sh510050")

# 计算 BS 价格
price = bs_price(spot=3.45, strike=3.5, t_years=14/365, vol=0.22, opt_type="call")

# 反解 IV
iv = implied_vol(market_price=0.06, spot=3.45, strike=3.5, t_years=14/365, opt_type="call")
```

### 方式 C：SQLite ATTACH（合并数据库）

如果另一个项目也用 SQLite，可以 ATTACH 进来联查：

```sql
ATTACH '/Users/huangxin/Library/Application Support/ETFWatcher/etf_watcher.db' AS watcher;

-- 联查期权行情
SELECT * FROM watcher.option_quotes WHERE underlying_code = 'sh510050';

-- 联查历史快照
SELECT * FROM watcher.option_daily_snapshot WHERE date >= '20260801';
```

---

## 8. 数据更新频率

| 数据 | 更新频率 | 时段 |
|------|---------|------|
| ETF 行情快照 | 5s | 9:00-15:30 |
| 期权实时行情 | ~45s 全量一轮 | 9:00-15:30 |
| 分钟 K 线 | 5s | 9:30-15:00 |
| 合约元数据 | 每 6 小时 | 启动时 |
| 每日快照 | 每日 1 次 | 14:55 |
| 交易日历 | 每 24 小时 | 启动时 |

---

## 9. 关键代码文件

| 文件 | 用途 |
|------|------|
| `watcher/state.py` | SQLite 存储层（所有表的 CRUD） |
| `watcher/option_meta.py` | 期权数据拉取 + 分析数据组装 |
| `watcher/strategy/pricing.py` | BS 定价 + Greeks + IV 反解（纯函数） |
| `watcher/signals/rules.py` | 信号检测规则 |
| `watcher/watcher_loop.py` | 后台轮询线程 |
| `watcher/config.py` | 配置模型 |
| `watcher/models.py` | 数据模型（Quote/MinuteBar/OptionContract/Signal） |
| `config.yaml` | 标的列表、阈值、数据源配置 |

---

## 10. 注意事项

1. **时间格式**：所有 ts 字段为 14 位数字串 `YYYYMMDDHHmmss`；SQLite `created_at` 是 UTC（北京时间 +8h）
2. **expire_date 两种格式**：`option_contracts` 表是 `20260826`，`option_quotes` 表是 `2026-08-26`，**关联用 option_code**
3. **IV 单位**：小数（0.224 = 22.4%），前端展示时 ×100
4. **价格单位**：元/份（ETF 期权合约单位 = 10000 份/张）
5. **OI/Volume**：张数（深市行情可能偶发负值，已做 clamp ≥ 0 处理）
6. **数据库并发**：SQLite WAL 模式，支持多读单写；外部项目读取无需加锁
7. **程序未运行时**：数据库文件仍可读，但数据不会更新
