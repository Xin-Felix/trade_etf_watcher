"""配置加载与校验."""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Optional

import yaml
from platformdirs import user_config_dir, user_data_dir
from pydantic import BaseModel, Field


class WatchItem(BaseModel):
    code: str
    name: str
    thresholds: dict[str, float] = Field(default_factory=dict)


# 跟踪指数与 ETF→指数映射的内置默认值。
# 这是产品知识（哪只 ETF 跟哪个指数）而不是用户偏好，所以内置：
# 老版本 config.yaml 没有这两段时，看板分组依然可用。
# config.yaml 里显式配置会整体覆盖。
DEFAULT_INDICES: list[dict[str, str]] = [
    {"code": "sh000016", "name": "上证50"},
    {"code": "sh000300", "name": "沪深300"},
    {"code": "sh000905", "name": "中证500"},
    {"code": "sh000688", "name": "科创50"},
    {"code": "sz399006", "name": "创业板指"},
    {"code": "sz399330", "name": "深证100"},
]

DEFAULT_INDEX_MAP: dict[str, str] = {
    "sh510050": "sh000016",
    "sh510300": "sh000300",
    "sz159919": "sh000300",
    "sh510500": "sh000905",
    "sz159922": "sh000905",
    "sh588000": "sh000688",
    "sh588080": "sh000688",
    "sh588050": "sh000688",
    "sz159915": "sz399006",
    "sz159952": "sz399006",
    "sz159901": "sz399330",
}


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
    # 跟踪指数（只拉快照做对比，不做信号检测）
    indices: list[WatchItem] = Field(
        default_factory=lambda: [WatchItem(**d) for d in DEFAULT_INDICES])
    # ETF code -> 指数 code
    index_map: dict[str, str] = Field(
        default_factory=lambda: dict(DEFAULT_INDEX_MAP))
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
    def bundled_config_path() -> Optional[Path]:
        """PyInstaller 打包目录内的 config.yaml（只读模板）.

        非打包环境返回 None。
        """
        base = getattr(sys, "_MEIPASS", None)
        if not base:
            return None
        candidate = Path(base) / "config.yaml"
        return candidate if candidate.exists() else None

    @staticmethod
    def user_config_path() -> Path:
        return Path(user_config_dir("ETFWatcher", appauthor=False)) / "config.yaml"

    @staticmethod
    def default_config_path() -> Path:
        """解析实际使用的配置文件路径.

        打包环境（.app 双击启动时 cwd 是 `/`，不能依赖 cwd）：
          用户配置目录优先；不存在则把包内模板 seed 过去，用户后续可直接编辑。
        开发环境：
          保持项目目录 ./config.yaml 优先，行为不变。
        """
        user_path = Config.user_config_path()

        if getattr(sys, "frozen", False):
            if not user_path.exists():
                bundled = Config.bundled_config_path()
                if bundled is not None:
                    try:
                        user_path.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(bundled, user_path)
                    except OSError:
                        # 用户目录不可写时直接读包内模板兜底
                        return bundled
            return user_path

        local = Path(os.getcwd()) / "config.yaml"
        if local.exists():
            return local
        return user_path

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
        for item in self.indices:
            if item.code == code:
                return item.name
        return code

    # ---------- 跟踪指数 ----------

    def index_codes(self) -> list[str]:
        """所有跟踪指数代码（按 indices 配置顺序）."""
        return [item.code for item in self.indices]

    def all_quote_codes(self) -> list[str]:
        """需要拉快照的全部代码 = watchlist + 指数（去重，保持顺序）."""
        out: list[str] = []
        seen: set[str] = set()
        for code in self.watch_codes() + self.index_codes():
            if code not in seen:
                seen.add(code)
                out.append(code)
        return out

    def is_index(self, code: str) -> bool:
        return code in {item.code for item in self.indices}

    def index_for(self, etf_code: str) -> str:
        """某 ETF 跟踪的指数代码；未配置返回空串."""
        return self.index_map.get(etf_code, "")

    def etfs_for_index(self, index_code: str) -> list[str]:
        """跟踪该指数的 ETF 代码列表（按 watchlist 顺序）."""
        return [item.code for item in self.watchlist
                if self.index_map.get(item.code) == index_code]
