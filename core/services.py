"""Builds the data clients from settings. One place to wire config, cache and fetchers."""
from __future__ import annotations

from dataclasses import dataclass

from core.cache import Cache
from core.config import Settings, load_settings
from core.store import Store
from datasources.damodaran import DamodaranClient
from datasources.edgar import EdgarClient
from datasources.finnhub import FinnhubClient
from datasources.fmp import FmpClient
from datasources.fred import FredClient
from datasources.market import MarketData
from datasources.tiingo import TiingoClient


@dataclass
class Services:
    settings: Settings
    cache: Cache
    edgar: EdgarClient
    fmp: FmpClient
    fred: FredClient
    damodaran: DamodaranClient
    tiingo: TiingoClient
    finnhub: FinnhubClient
    market: MarketData
    store: Store


def build_services(settings: Settings | None = None) -> Services:
    s = settings or load_settings()
    cache = Cache(s.cache_dir, offline=s.offline)
    fmp = FmpClient(cache, s.fmp_api_key)
    tiingo = TiingoClient(cache, s.tiingo_api_key)
    finnhub = FinnhubClient(cache, s.finnhub_api_key)
    return Services(
        settings=s,
        cache=cache,
        edgar=EdgarClient(cache, s.sec_user_agent),
        fmp=fmp,
        fred=FredClient(cache, s.fred_api_key),
        damodaran=DamodaranClient(cache),
        tiingo=tiingo,
        finnhub=finnhub,
        market=MarketData(fmp, tiingo, finnhub),
        store=Store(s.db_path),
    )
