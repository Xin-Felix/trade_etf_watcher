"""数据采集层."""
from watcher.fetchers.base import Fetcher, FetchResult
from watcher.fetchers.eastmoney import EastMoneyFetcher
from watcher.fetchers.tdx import TdxFetcher

__all__ = ["Fetcher", "FetchResult", "TdxFetcher", "EastMoneyFetcher"]
