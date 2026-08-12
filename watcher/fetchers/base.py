"""Fetcher 抽象基类与降级链."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

from watcher.models import MinuteBar, Quote


@dataclass
class FetchResult:
    quotes: dict[str, Quote] = field(default_factory=dict)
    bars: list[MinuteBar] = field(default_factory=list)
    source: str = ""
    error: str = ""
    success: bool = False

    def __bool__(self) -> bool:
        return self.success


class Fetcher(ABC):
    name: str = ""

    @abstractmethod
    def fetch(self, codes: list[str]) -> FetchResult:
        """获取给定 code 列表的行情快照."""
        ...

    def fetch_minute_bars(self, code: str, limit: int = 120) -> list[MinuteBar]:
        """可选：获取分钟 K 线，子类可覆盖."""
        return []

    def close(self) -> None:
        """清理资源."""
        pass


class FetchChain:
    """按优先级依次尝试多个 Fetcher."""

    def __init__(self, fetchers: list[Fetcher]):
        self.fetchers = fetchers

    def fetch(self, codes: list[str]) -> FetchResult:
        errors: list[str] = []
        for fetcher in self.fetchers:
            try:
                result = fetcher.fetch(codes)
                if result:
                    return result
                errors.append(f"{fetcher.name}: {result.error or 'empty'}")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{fetcher.name}: {exc}")
        return FetchResult(error="; ".join(errors), source="none")

    def fetch_minute_bars(self, code: str, limit: int = 120) -> list[MinuteBar]:
        for fetcher in self.fetchers:
            try:
                bars = fetcher.fetch_minute_bars(code, limit)
                if bars:
                    return bars
            except Exception:  # noqa: BLE001
                continue
        return []

    def fetch_minute_bars_batch(self, codes: list[str], limit: int = 120) -> dict[str, list[MinuteBar]]:
        """批量拉分钟 K：优先用有并发实现的 fetcher（TDX 多连接并发），
        没拉到的 code 逐个走普通降级链（单连接 TDX 重试 → 东财）."""
        out: dict[str, list[MinuteBar]] = {}
        remaining = list(codes)
        for fetcher in self.fetchers:
            fn = getattr(fetcher, "fetch_minute_bars_batch", None)
            if fn is None:
                continue
            try:
                batch = fn(remaining, limit) or {}
            except Exception:  # noqa: BLE001
                continue
            for code, bars in batch.items():
                if bars and code not in out:
                    out[code] = bars
            remaining = [c for c in remaining if c not in out]
            if not remaining:
                break
        for code in remaining:
            bars = self.fetch_minute_bars(code, limit)
            if bars:
                out[code] = bars
        return out

    def fetch_daily_bars(self, code: str, limit: int = 120) -> list[MinuteBar]:
        """日 K（可选能力，fetcher 没有该方法则跳过）."""
        for fetcher in self.fetchers:
            fn = getattr(fetcher, "fetch_daily_bars", None)
            if fn is None:
                continue
            try:
                bars = fn(code, limit)
                if bars:
                    return bars
            except Exception:  # noqa: BLE001
                continue
        return []

    def close(self) -> None:
        for fetcher in self.fetchers:
            try:
                fetcher.close()
            except Exception:  # noqa: BLE001
                pass
