"""yfinance adapter — OHLCV / market_cap / basic_info.

Public functions (signatures pinned to PROJECT_SPEC.md § 1.3):
    get_prices(ticker, start, end)        — OHLCV DataFrame, tz UTC
    get_market_cap(ticker)                — float | None, validated > 0
    get_basic_info(ticker)                — BasicInfo (sector/industry/country/shares)

Architecture mirrors sec_edgar:
  - ``_fetch_history`` / ``_fetch_info`` are the only places we call yfinance —
    tests monkeypatch these to use ``tests/unit/fixtures/yfinance/*.pkl|json``.
  - ``_normalize_history_frame`` is a pure function: takes a raw yfinance
    DataFrame, returns canonicalized OHLCV (lowercase cols, tz UTC, no NaN).
  - Public functions orchestrate fetch → normalize → cache (basic_info only).

TTL strategy:
  - get_basic_info:  30d cache (CacheTTL.YFINANCE_BASIC_INFO).
                     sector/industry/country/shares are slow-moving.
  - get_market_cap:  no cache here (market cap moves intraday — caller can
                     decide to wrap with the aggregator's prices TTL or finer).
  - get_prices:      no cache here (the aggregator layer caches under
                     "aggregator/prices" with 1d TTL per spec).
"""
from __future__ import annotations

import datetime as dt
import json
import logging
from typing import Any, Final

import numpy as np
import pandas as pd
import yfinance as yf
from pydantic import BaseModel, ConfigDict

from src.data_sources.cache import Cache, CacheTTL


logger = logging.getLogger(__name__)


_OHLCV_COLUMNS: Final[tuple[str, ...]] = ("open", "high", "low", "close", "volume")


# ---------------------------------------------------------------------------
# exceptions
# ---------------------------------------------------------------------------


class YFinanceError(Exception):
    """Base class for yfinance_adapter errors."""


class YFinanceMissingPriceData(YFinanceError):
    """Raised when an OHLCV column has NaN at intermediate dates.

    We don't forward-fill: a gap usually signals either a yfinance API
    regression or an exchange-level halt that the caller should know about.
    """


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class BasicInfo(BaseModel):
    """Slow-moving metadata extracted from ``Ticker.info``.

    Only fields persona code actually reads (sector, industry, country,
    shares_outstanding); the full ``.info`` dict has 180+ keys and 90% are
    derived metrics we either compute ourselves or skip per spec.
    """

    model_config = ConfigDict(frozen=True)

    ticker: str
    sector: str | None
    industry: str | None
    country: str | None
    shares_outstanding: int | None


# ---------------------------------------------------------------------------
# network seam — only place we touch yfinance. Tests monkeypatch these.
# ---------------------------------------------------------------------------


def _fetch_history(ticker: str, start: dt.date, end: dt.date) -> pd.DataFrame:
    return yf.Ticker(ticker).history(
        start=str(start), end=str(end), auto_adjust=True
    )


def _fetch_info(ticker: str) -> dict[str, Any]:
    info = yf.Ticker(ticker).info
    return dict(info) if info else {}


# ---------------------------------------------------------------------------
# pure normalizer
# ---------------------------------------------------------------------------


def _normalize_history_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Return a canonical OHLCV DataFrame: lowercase cols, tz UTC, no NaN.

    Always returns the canonical 5-column schema (open/high/low/close/volume).
    For empty input — which is yfinance's signal for invalid ticker or pre-
    listing window — we still return that schema so callers can do
    ``df['close']`` without a KeyError.

    Raises ``YFinanceMissingPriceData`` if a non-empty input has NaN in any
    OHLCV column.
    """
    if df.empty:
        empty_idx = pd.DatetimeIndex([], tz="UTC", name=df.index.name)
        return pd.DataFrame({c: pd.Series(dtype="float64") for c in _OHLCV_COLUMNS}, index=empty_idx)

    df = df.rename(columns=str.lower)

    missing = [c for c in _OHLCV_COLUMNS if c not in df.columns]
    if missing:
        raise YFinanceMissingPriceData(
            f"yfinance frame is missing required columns {missing}; got {list(df.columns)}"
        )
    df = df[list(_OHLCV_COLUMNS)].copy()

    # tz-aware UTC index
    idx = df.index
    if not isinstance(idx, pd.DatetimeIndex):
        idx = pd.DatetimeIndex(idx)
    if idx.tz is None:
        idx = idx.tz_localize("UTC")
    else:
        idx = idx.tz_convert("UTC")
    df.index = idx

    nan_mask = df.isna().any(axis=1)
    if bool(nan_mask.any()):
        nan_dates = [ts.date().isoformat() for ts in df.index[nan_mask]]
        logger.warning(
            "yfinance OHLCV has NaN at %d intermediate date(s): %s",
            len(nan_dates), nan_dates,
        )
        raise YFinanceMissingPriceData(
            f"NaN in OHLCV columns at dates: {nan_dates}"
        )

    return df


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------


def get_prices(ticker: str, start: dt.date, end: dt.date) -> pd.DataFrame:
    raw = _fetch_history(ticker, start, end)
    return _normalize_history_frame(raw)


def get_market_cap(ticker: str) -> float | None:
    """Read ``info['marketCap']`` and validate it's a positive number.

    Per spec § 1.3: yfinance has been observed to return strings, ``None``,
    or zero on quirky tickers. We only return a float if it's strictly > 0;
    otherwise ``None``.

    Caching delegated to underlying components: shares_outstanding via
    basic_info (30d TTL), price via OHLCV (1h or 30d TTL by recency).
    Top-level cache would create staleness mismatch between numerator
    and denominator.
    """
    info = _fetch_info(ticker)
    raw = info.get("marketCap")
    if not isinstance(raw, (int, float)):
        return None
    if isinstance(raw, bool):  # bool is a subclass of int in Python
        return None
    if raw <= 0 or not np.isfinite(raw):
        return None
    return float(raw)


def get_basic_info(ticker: str, *, cache: Cache | None = None) -> BasicInfo:
    """Cached (30d) sector/industry/country/shares_outstanding."""
    cache = cache or Cache()
    key = ticker.upper()
    cached = cache.get("yfinance", "basic_info", key)
    if cached is None:
        info = _fetch_info(ticker)
        subset: dict[str, Any] = {
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "country": info.get("country"),
            "shares_outstanding": info.get("sharesOutstanding"),
        }
        cache.set(
            "yfinance", "basic_info", key,
            json.dumps(subset).encode(),
            CacheTTL.YFINANCE_BASIC_INFO,
        )
    else:
        subset = json.loads(cached)

    return BasicInfo(
        ticker=key,
        sector=subset.get("sector"),
        industry=subset.get("industry"),
        country=subset.get("country"),
        shares_outstanding=subset.get("shares_outstanding"),
    )
