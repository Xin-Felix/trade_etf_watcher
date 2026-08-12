# 日进斗金

跨平台 ETF / ETF 期权盯盘提醒程序（macOS + Windows）。

> **开发者请读 [PROJECT.md](PROJECT.md)** —— 完整交接文档：架构、数据源、数据库、
> 信号回测结论、已知坑与解决方案。
> 原始设计依据：[etf-watcher-design.md](etf-watcher-design.md)

## 功能

**行情与图表**
- 通达信 + 东财双源轮询（5s 一轮，自动探测最快节点、断线重连）
- ECharts K 线：分时 / 1 / 5 / 15 / 30 / 60 分 / 日K，MA5-10-20 + MACD 副图
- 期权 T 型报价：9 个标的 1200+ 合约，买卖价量 / IV / Delta / 持仓量分页浏览

**买卖点信号**
- 量价形态（`signals/patterns.py`）：把最近 10+ 根 K 线翻译成量价序列形态
  （量爆跟随 / 量堆积启动 / 挤压突破 / 高位破位 等 14 种），加权打分判买卖
- 市场日内动量（`signals/intraday_momentum.py`）：每天 14:30 推送末半小时方向参考，
  依据 Gao/Han/Li/Zhou (2018)，本地一年 ETF 数据实测 t=+5.00
- 8 类行情异动提醒：跳空、急涨急跌、探底回升、冲高回落、分钟急涨跌、IV 飙升、PCR 异常

**期权工具**
- 策略组合：7 个预设模板（价差 / 跨式 / 蝶式 / 备兑等）+ BS 定价 + 希腊字母
  + 到期损益图 + 时间损耗表
- AI 策略推荐（DeepSeek）：喂入行情 / 技术面 / 期权链 / 历史走势，返回结构化策略建议，
  一键填入策略篮子；支持深度思考模式，可展开查看完整推理链

**通知**
- macOS 原生系统通知（横幅弹出 + 点击跳转到对应标的 K 线图）
- 应用内浮窗 + 系统托盘，三条路径都支持点击跳转

## 运行

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m watcher
```

## 配置

**`config.yaml`**：监控标的、信号阈值、数据源优先级、TDX 服务器池、通知开关。

**API 密钥**：启动后点界面上的「API 设置」填写，保存在本地 SQLite（不进配置文件）：
- `Tushare Token` — 历史日K、交易日历、分钟线
- `DeepSeek Key` — AI 策略推荐

也可写入 `~/.config/etf_watcher/secrets.env`（环境变量优先级最高）：

```bash
TUSHARE_TOKEN=xxx
DEEPSEEK_API_KEY=sk-xxx
# 可选：高积分代理，支持 stk_mins 等高级接口
TUSHARE_PROXY_URL=https://example.com/
TUSHARE_PROXY_TOKEN=xxx
```

## 打包

```bash
# macOS → dist/日进斗金.app
pyinstaller build/macos.spec --distpath dist --workpath build/work --noconfirm

# Windows → dist/日进斗金.exe
pyinstaller build/windows.spec --noconfirm --clean
```

## 回测与调参工具

```bash
python scripts/backtest_multi.py 1              # 本地全标的多日回测（含手续费）
python scripts/sweep_patterns.py 1              # 形态权重配置对比（带缓存）
python scripts/test_intraday_momentum.py etf    # 日内动量检验（回归 + 策略 + 分档）
python scripts/diag_edge.py stocks 5            # 信号预测力诊断（远期收益 vs 基准）
python scripts/diag_features.py sh588000 1      # 量价特征分布（调阈值用）
python scripts/fetch_etf_mins.py 365            # 下载一年 ETF 5 分钟线到缓存
```

## 声明

行情数据来自公开接口（通达信、东方财富、新浪、Tushare、akshare），**可能存在延迟或
间歇性不可用**。

信号基于历史统计，**已知局限见 [PROJECT.md 第 8 节](PROJECT.md)**：量价形态的买入信号
在 387 笔个股样本上未表现出正期望；日内动量虽统计显著（t=+5.00），但单笔幅度
（标的 +0.087%）小于 ETF 期权的买卖价差，**适合作为方向参考，不适合作为机械交易依据**。

本程序仅供盯盘提醒，**不构成投资建议**。
