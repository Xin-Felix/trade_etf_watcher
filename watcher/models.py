"""核心数据模型."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Optional


@dataclass(slots=True)
class Quote:
    code: str
    name: str
    price: float
    open: float
    high: float
    low: float
    prev_close: float
    volume: int = 0
    ts: str = ""  # yyyyMMddHHmmss
    source: str = ""

    @property
    def change_pct(self) -> float:
        if self.prev_close == 0:
            return 0.0
        return self.price / self.prev_close - 1.0

    @property
    def gap_pct(self) -> float:
        if self.prev_close == 0:
            return 0.0
        return self.open / self.prev_close - 1.0


@dataclass(frozen=True, slots=True)
class MinuteBar:
    code: str
    ts: str
    open: float
    high: float
    low: float
    close: float
    volume: int = 0
    source: str = ""


@dataclass(frozen=True, slots=True)
class OptionContract:
    option_code: str
    underlying_code: str
    option_name: str
    exchange: str
    option_type: Literal["call", "put"]
    strike: float
    expire_date: str


@dataclass(frozen=True, slots=True)
class Signal:
    key: str
    code: str
    name: str
    label: str
    detail: str
    level: Literal["info", "warning", "critical"] = "warning"
    ts: str = ""


@dataclass
class AppState:
    quotes: dict[str, Quote] = field(default_factory=dict)
    last_signals: list[Signal] = field(default_factory=list)
    connected: bool = False
    data_source: str = ""
    next_poll: Optional[datetime] = None
    error_message: str = ""
