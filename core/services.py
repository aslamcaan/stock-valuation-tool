"""Builds the data clients from settings. One place to wire config, cache and fetchers."""
from __future__ import annotations

from dataclasses import dataclass

from core.cache import Cache
from core.config import Settings, load_settings
from datasources.damodaran import DamodaranClient
from datasources.edgar import EdgarClient
from datasources.fmp import FmpClient
from datasources.fred import FredClient


@dataclass
class Services:
    settings: Settings
    cache: Cache
    edgar: EdgarClient
    fmp: FmpClient
    fred: FredClient
    damodaran: DamodaranClient


def build_services(settings: Settings | None = None) -> Services:
    s = settings or load_settings()
    cache = Cache(s.cache_dir, offline=s.offline)
    return Services(
        settings=s,
        cache=cache,
        edgar=EdgarClient(cache, s.sec_user_agent),
        fmp=FmpClient(cache, s.fmp_api_key),
        fred=FredClient(cache, s.fred_api_key),
        damodaran=DamodaranClient(cache),
    )
