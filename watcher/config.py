"""配置加载与校验."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import yaml
from platformdirs import user_config_dir, user_data_dir
from pydantic import BaseModel, Field


class WatchItem(BaseModel):
    code: str
    name: str
    thresholds: dict[str, float] = Field(default_factory=dict)


class Thresholds(BaseModel):
    gap: float = 0.008
    surge: float = 0.020
    plunge: float = 0.020
    rebound_start: float = 0.010
    rebound_bounce: float = 0.010
    reversal_start: float = 0.010
    reversal_pullback: float = 0.010
    minute_surge: float = 0.005
    minute_plunge: float = 0.005
    # 期权信号阈值
    iv_surge: float = 0.50          # 单合约 IV ≥ 50% 触发
    pcr_high: float = 1.5           # Put/Call 持仓量比 ≥ 1.5
    pcr_low: float = 0.5            # Put/Call 持仓量比 ≤ 0.5
    # 技术指标信号阈值（买方入场参考）
    rsi_oversold: float = 30.0      # RSI 超卖线（低于此值后回升触发）
    rsi_overbought: float = 70.0    # RSI 超买线（高于此值后回落触发）
    kdj_low: float = 30.0           # KDJ 低位区（金叉需在此值以下）
    kdj_high: float = 70.0          # KDJ 高位区（死叉需在此值以上）
    vol_breakout_mult: float = 1.5  # 放量突破倍数（当前量 > 均量 × 此值）


class SignalToggleConfig(BaseModel):
    """买卖点信号开关.

    只保留量价形态（signals/patterns.py）：MACD/MA/RSI 等滞后指标在 ETF 日内
    实测误报多、且常把主升浪砍在半路，已移除。
    """
    volume_pattern: bool = True     # 量价形态（量爆跟随/量堆积启动/挤压突破 等）
    # 市场日内动量：14:30 推送末半小时方向参考（唯一经一年数据验证 t=+5.00 的信号）
    intraday_momentum: bool = True


class TdxServer(BaseModel):
    host: str
    port: int


class NotificationConfig(BaseModel):
    desktop_popup: bool = True
    tray_message: bool = True
    sound: bool = False


class DevConfig(BaseModel):
    mock_mode: bool = False
    mock_data_path: Optional[str] = None


class TushareConfig(BaseModel):
    """Tushare 数据源（期权历史日K + 交易日历）.

    token 不放这里，放 ~/.config/etf_watcher/secrets.env 或环境变量 TUSHARE_TOKEN，
    避免跟着 config.yaml 进 git / 打包产物。
    """
    enabled: bool = True
    option_daily: bool = True      # 期权日K 优先用 Tushare（历史最全）
    fund_daily_fallback: bool = True   # TDX 日K 失败时用 Tushare 兜底
    trade_calendar: bool = True    # 交易日历（节假日不轮询）


class DeepSeekConfig(BaseModel):
    """DeepSeek AI 策略推荐配置.

    api_key 不放这里，放 ~/.config/etf_watcher/secrets.env 的 DEEPSEEK_API_KEY，
    或环境变量 DEEPSEEK_API_KEY。
    """
    enabled: bool = True
    model: str = "deepseek-chat"    # 模型名称
    base_url: str = "https://api.deepseek.com"  # API 地址
    timeout: int = 60               # 请求超时秒数（思考模式需要更长）
    max_tokens: int = 4000          # 最大输出 token（含思考）


class AppConfig(BaseModel):
    name: str = "日进斗金"
    version: str = "0.1.0"
    poll_interval_seconds: int = 5
    minute_refresh_seconds: int = 5
    timezone: str = "Asia/Shanghai"
    trading_hours_only: bool = True


class Config(BaseModel):
    app: AppConfig = Field(default_factory=AppConfig)
    watchlist: list[WatchItem] = Field(default_factory=list)
    thresholds: Thresholds = Field(default_factory=Thresholds)
    data_sources: list[str] = Field(default_factory=lambda: ["tdx", "tencent", "eastmoney"])
    tdx_servers: list[TdxServer] = Field(default_factory=list)
    notifications: NotificationConfig = Field(default_factory=NotificationConfig)
    dev: DevConfig = Field(default_factory=DevConfig)
    tushare: TushareConfig = Field(default_factory=TushareConfig)
    deepseek: DeepSeekConfig = Field(default_factory=DeepSeekConfig)
    signal_toggles: SignalToggleConfig = Field(default_factory=SignalToggleConfig)
    # 已废弃，改用 UI 提醒开关
    option_signal_codes: list[str] = Field(default_factory=list)

    @classmethod
    def load(cls, path: Optional[Path | str] = None) -> "Config":
        if path is None:
            path = cls.default_config_path()

        path = Path(path)
        if path.exists():
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        else:
            raw = {}

        return cls.model_validate(raw)

    def save(self, path: Optional[Path | str] = None) -> None:
        path = Path(path or self.default_config_path())
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(self.model_dump(), allow_unicode=True, sort_keys=False), encoding="utf-8")

    @staticmethod
    def default_config_path() -> Path:
        cwd = Path(os.getcwd())
        local = cwd / "config.yaml"
        if local.exists():
            return local
        return Path(user_config_dir("ETFWatcher", appauthor=False)) / "config.yaml"

    @staticmethod
    def data_dir() -> Path:
        return Path(user_data_dir("ETFWatcher", appauthor=False))

    def threshold_for(self, code: str, key: str) -> float:
        for item in self.watchlist:
            if item.code == code and key in item.thresholds:
                return item.thresholds[key]
        return getattr(self.thresholds, key, 0.0)

    def watch_codes(self) -> list[str]:
        return [item.code for item in self.watchlist]

    def name_for(self, code: str) -> str:
        for item in self.watchlist:
            if item.code == code:
                return item.name
        return code
