"""Unit tests for src/data_sources/yfinance_adapter.py.

覆盖 PROJECT_SPEC.md § 1.3 的 5 个 edge case + 3 个公开函数 happy path:
  edge cases:
    1. 不存在的 ticker (FAKE_NVDA_X)        → 返回空 DataFrame,不抛异常
    2. ticker 在请求时间段内还没上市         → 返回空 DataFrame
    3. yfinance column 大小写飘忽            → 统一小写
    4. 索引必须 tz-aware UTC
    5. 中间日 NaN                            → 抛 YFinanceMissingPriceData + log

Pattern 复用 sec_edgar 的"网络一个入口、parser mock 化":
  - _fetch_history / _fetch_info 是网络层 (yfinance 调用) 的唯一入口,测试 monkeypatch
  - _normalize_history_frame 是纯函数,直接传 DataFrame 测
  - 公开函数 get_prices / get_market_cap / get_basic_info 协调 fetch + normalize + cache
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import pickle
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from src.data_sources.cache import Cache
from src.data_sources.yfinance_adapter import (
    BasicInfo,
    YFinanceMissingPriceData,
    _normalize_history_frame,
    get_basic_info,
    get_market_cap,
    get_prices,
)


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "yfinance"


def _load_history(ticker: str) -> pd.DataFrame:
    return pickle.loads((FIXTURE_DIR / f"{ticker}_history.pkl").read_bytes())


def _load_info(ticker: str) -> dict[str, Any]:
    return json.loads((FIXTURE_DIR / f"{ticker}_info.json").read_text())


@pytest.fixture
def cache(tmp_path: Path) -> Cache:
    return Cache(tmp_path / "cache.db")


# ---------------------------------------------------------------------------
# get_prices — five spec edge cases
# ---------------------------------------------------------------------------


def test_get_prices_happy_path_returns_lowercase_ohlcv_in_utc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Real NVDA fixture (tz=America/New_York) should come out:
       - cols lowercase: open / high / low / close / volume
       - index tz-aware UTC
       - row count matches fixture
       - Dividends & Stock Splits dropped (we return OHLCV only)
    """
    monkeypatch.setattr(
        "src.data_sources.yfinance_adapter._fetch_history",
        lambda ticker, start, end: _load_history("NVDA"),
    )
    df = get_prices("NVDA", dt.date(2024, 6, 1), dt.date(2024, 12, 31))

    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert df.index.tz is not None
    assert str(df.index.tz) == "UTC"
    assert len(df) == 146  # NVDA fixture has 146 trading days


def test_get_prices_unknown_ticker_returns_empty_no_raise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Spec edge case 1: FAKE_NVDA_X yields empty DataFrame, no exception.

    Why: persona scripts that try a list of candidate tickers must not crash on
    the first invalid one — they expect to filter empty results out themselves.
    """
    monkeypatch.setattr(
        "src.data_sources.yfinance_adapter._fetch_history",
        lambda ticker, start, end: _load_history("FAKE_NVDA_X"),
    )
    df = get_prices("FAKE_NVDA_X", dt.date(2024, 6, 1), dt.date(2024, 12, 31))
    assert df.empty
    # Even on empty result, schema must be canonical so downstream column access doesn't KeyError
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]


def test_get_prices_pre_listing_window_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Spec edge case 2: valid ticker but request range predates listing.

    yfinance returns an empty DataFrame in that case (same shape as invalid
    ticker basically). Adapter must not synthesize fake rows or raise.
    """
    empty_df = pd.DataFrame(
        columns=["Open", "High", "Low", "Close", "Adj Close", "Volume"]
    )
    monkeypatch.setattr(
        "src.data_sources.yfinance_adapter._fetch_history",
        lambda ticker, start, end: empty_df,
    )
    df = get_prices("NVDA", dt.date(1990, 1, 1), dt.date(1990, 12, 31))
    assert df.empty
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]


def test_get_prices_normalizes_arbitrary_column_case() -> None:
    """Spec edge case 3: yfinance has been observed to flip column case
    across versions (Close vs close vs CLOSE). Normalizer must handle all.
    """
    df_in = pd.DataFrame(
        {
            "OPEN": [100.0, 101.0],
            "high": [101.0, 102.0],
            "Low": [99.0, 100.0],
            "Close": [100.5, 101.5],
            "VoLuMe": [1000, 2000],
        },
        index=pd.DatetimeIndex(["2024-06-03", "2024-06-04"], tz="UTC"),
    )
    out = _normalize_history_frame(df_in)
    assert list(out.columns) == ["open", "high", "low", "close", "volume"]
    assert out["open"].tolist() == [100.0, 101.0]


def test_get_prices_index_is_tz_aware_utc(monkeypatch: pytest.MonkeyPatch) -> None:
    """Spec edge case 4: tz must be UTC, not exchange-local.

    yfinance returns America/New_York for US tickers. We normalize to UTC
    for cross-source consistency (SEC dates are date-only, no tz).
    """
    monkeypatch.setattr(
        "src.data_sources.yfinance_adapter._fetch_history",
        lambda ticker, start, end: _load_history("MSFT"),
    )
    df = get_prices("MSFT", dt.date(2024, 6, 1), dt.date(2024, 12, 31))
    assert df.index.tz is not None
    assert str(df.index.tz) == "UTC"
    # Smoke check: a known US trading day appears in the UTC-converted index
    # (NYSE 09:30 EDT on 2024-06-03 = 13:30 UTC; date-stripped == 2024-06-03)
    assert dt.date(2024, 6, 3) in {ts.date() for ts in df.index}


def test_get_prices_raises_on_intermediate_nan_with_logged_dates(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Spec edge case 5: intermediate NaN must raise with which-dates info.

    Why raise rather than forward-fill: spec § 1.3 explicitly says "抛异常 +
    在 log 里说明哪些日期缺失"。 Silent ffill would hide a real data gap that
    might indicate a yfinance API regression.
    """
    df = pd.DataFrame(
        {
            "Open": [100.0, 101.0, 102.0],
            "High": [101.0, 102.0, 103.0],
            "Low": [99.0, 100.0, 101.0],
            "Close": [100.5, np.nan, 102.5],  # ← gap on 2024-06-04
            "Volume": [1000, 2000, 3000],
        },
        index=pd.DatetimeIndex(
            ["2024-06-03", "2024-06-04", "2024-06-05"], tz="UTC"
        ),
    )
    monkeypatch.setattr(
        "src.data_sources.yfinance_adapter._fetch_history",
        lambda t, s, e: df,
    )
    with caplog.at_level(logging.WARNING, logger="src.data_sources.yfinance_adapter"):
        with pytest.raises(YFinanceMissingPriceData, match="2024-06-04"):
            get_prices("NVDA", dt.date(2024, 6, 3), dt.date(2024, 6, 6))
    assert "2024-06-04" in caplog.text


# ---------------------------------------------------------------------------
# get_market_cap — spec § 1.3 line: validate float > 0 else None
# ---------------------------------------------------------------------------


def test_get_market_cap_returns_float_when_valid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "src.data_sources.yfinance_adapter._fetch_info",
        lambda ticker: _load_info("NVDA"),
    )
    mc = get_market_cap("NVDA")
    assert mc is not None and mc > 0
    assert isinstance(mc, float)


def test_get_market_cap_returns_none_when_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "src.data_sources.yfinance_adapter._fetch_info",
        lambda ticker: {"sector": "Technology"},  # no marketCap key
    )
    assert get_market_cap("NVDA") is None


def test_get_market_cap_returns_none_when_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """yfinance has historically returned the string 'N/A' on quirky tickers."""
    monkeypatch.setattr(
        "src.data_sources.yfinance_adapter._fetch_info",
        lambda ticker: {"marketCap": "N/A"},
    )
    assert get_market_cap("NVDA") is None


@pytest.mark.parametrize("bad_value", [0, -1, -1_000_000_000.0])
def test_get_market_cap_returns_none_when_non_positive(
    monkeypatch: pytest.MonkeyPatch, bad_value: float
) -> None:
    monkeypatch.setattr(
        "src.data_sources.yfinance_adapter._fetch_info",
        lambda ticker: {"marketCap": bad_value},
    )
    assert get_market_cap("NVDA") is None


def test_get_market_cap_returns_none_for_invalid_ticker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAKE_NVDA_X info dict is essentially empty — must yield None gracefully."""
    monkeypatch.setattr(
        "src.data_sources.yfinance_adapter._fetch_info",
        lambda ticker: _load_info("FAKE_NVDA_X"),
    )
    assert get_market_cap("FAKE_NVDA_X") is None


# ---------------------------------------------------------------------------
# get_basic_info — sector / industry / country / shares_outstanding + cache 30d
# ---------------------------------------------------------------------------


def test_get_basic_info_happy_path(
    cache: Cache, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "src.data_sources.yfinance_adapter._fetch_info",
        lambda ticker: _load_info("NVDA"),
    )
    info = get_basic_info("NVDA", cache=cache)
    assert isinstance(info, BasicInfo)
    assert info.ticker == "NVDA"
    assert info.sector == "Technology"
    assert info.industry == "Semiconductors"
    assert info.country == "United States"
    assert info.shares_outstanding == 24_300_000_000


def test_get_basic_info_uses_30d_cache(
    cache: Cache, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spec TTL 表:yfinance.basic_info = 30d. Second call must hit cache."""
    calls = [0]

    def fake_fetch(ticker: str) -> dict[str, Any]:
        calls[0] += 1
        return _load_info("NVDA")

    monkeypatch.setattr("src.data_sources.yfinance_adapter._fetch_info", fake_fetch)
    a = get_basic_info("NVDA", cache=cache)
    b = get_basic_info("NVDA", cache=cache)
    assert a.sector == b.sector == "Technology"
    assert calls[0] == 1, f"expected 1 fetch, got {calls[0]}"


def test_get_basic_info_handles_sparse_info_dict(
    cache: Cache, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FAKE_NVDA_X-style sparse info dict → BasicInfo with None fields, not exception."""
    monkeypatch.setattr(
        "src.data_sources.yfinance_adapter._fetch_info",
        lambda ticker: _load_info("FAKE_NVDA_X"),
    )
    info = get_basic_info("FAKE_NVDA_X", cache=cache)
    assert info.ticker == "FAKE_NVDA_X"
    assert info.sector is None
    assert info.industry is None
    assert info.country is None
    assert info.shares_outstanding is None


def test_basic_info_is_frozen() -> None:
    info = BasicInfo(
        ticker="NVDA",
        sector="Technology",
        industry="Semiconductors",
        country="United States",
        shares_outstanding=24_300_000_000,
    )
    with pytest.raises((TypeError, ValueError)):
        info.sector = "Healthcare"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# normalizer edge cases (pure-function tests)
# ---------------------------------------------------------------------------


def test_normalize_empty_dataframe_returns_canonical_schema() -> None:
    """Empty DataFrame in → empty DataFrame out, with canonical OHLCV columns.

    Why canonical: persona code does df['close'].mean() etc; raising KeyError
    on an empty result would force every caller to defend twice.
    """
    df_in = pd.DataFrame(columns=["Open", "High", "Low", "Close", "Adj Close", "Volume"])
    out = _normalize_history_frame(df_in)
    assert out.empty
    assert list(out.columns) == ["open", "high", "low", "close", "volume"]


def test_normalize_drops_dividends_and_splits_columns() -> None:
    """yfinance happy path includes Dividends + Stock Splits — drop them.

    Reasoning: get_prices is OHLCV; persona code that wants dividends has to
    go through a different path (we don't have one yet, that's fine).
    """
    df_in = pd.DataFrame(
        {
            "Open": [100.0],
            "High": [101.0],
            "Low": [99.0],
            "Close": [100.5],
            "Volume": [1000],
            "Dividends": [0.0],
            "Stock Splits": [0.0],
        },
        index=pd.DatetimeIndex(["2024-06-03"], tz="UTC"),
    )
    out = _normalize_history_frame(df_in)
    assert list(out.columns) == ["open", "high", "low", "close", "volume"]


def test_normalize_naive_index_is_localized_to_utc() -> None:
    """Some yfinance code paths return a tz-naive index — we localize to UTC."""
    df_in = pd.DataFrame(
        {"Open": [100.0], "High": [101.0], "Low": [99.0], "Close": [100.5], "Volume": [1000]},
        index=pd.DatetimeIndex(["2024-06-03"]),  # naive
    )
    out = _normalize_history_frame(df_in)
    assert out.index.tz is not None
    assert str(out.index.tz) == "UTC"


def test_normalize_aware_non_utc_index_is_converted_to_utc() -> None:
    df_in = pd.DataFrame(
        {"Open": [100.0], "High": [101.0], "Low": [99.0], "Close": [100.5], "Volume": [1000]},
        index=pd.DatetimeIndex(["2024-06-03 09:30:00"], tz="America/New_York"),
    )
    out = _normalize_history_frame(df_in)
    assert str(out.index.tz) == "UTC"
    # 09:30 EDT (UTC-4 in June) = 13:30 UTC
    assert out.index[0].hour == 13 and out.index[0].minute == 30


def test_normalize_non_datetime_index_is_coerced() -> None:
    """If the input index isn't a DatetimeIndex (rare yfinance code path),
    coerce it before tz-localizing — don't blow up with AttributeError."""
    df_in = pd.DataFrame(
        {"Open": [100.0], "High": [101.0], "Low": [99.0], "Close": [100.5], "Volume": [1000]},
        index=["2024-06-03"],  # plain object index, not DatetimeIndex
    )
    out = _normalize_history_frame(df_in)
    assert isinstance(out.index, pd.DatetimeIndex)
    assert str(out.index.tz) == "UTC"


def test_normalize_non_empty_with_missing_ohlcv_raises() -> None:
    """Defensive: yfinance schema drift dropping (say) Volume → loud raise.

    This is *not* an empty-DF case (which we tolerate) — it's the dangerous
    middle ground of rows present but schema broken.
    """
    df_in = pd.DataFrame(
        {"Open": [100.0], "High": [101.0], "Low": [99.0], "Close": [100.5]},
        index=pd.DatetimeIndex(["2024-06-03"], tz="UTC"),
    )
    with pytest.raises(YFinanceMissingPriceData, match="missing required columns"):
        _normalize_history_frame(df_in)


def test_get_market_cap_rejects_bool() -> None:
    """Edge case: yfinance returning ``True`` would slip past isinstance(int, float)
    because ``bool`` subclasses ``int``. We special-case to reject.
    """
    import src.data_sources.yfinance_adapter as ya

    # Direct test of the bool guard via monkeypatch on _fetch_info at attribute level
    saved = ya._fetch_info
    ya._fetch_info = lambda ticker: {"marketCap": True}  # type: ignore[assignment]
    try:
        assert ya.get_market_cap("NVDA") is None
    finally:
        ya._fetch_info = saved  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# network seam smoke tests — exercise _fetch_history / _fetch_info directly
# ---------------------------------------------------------------------------


def test_fetch_history_calls_yfinance_with_iso_dates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_fetch_history wraps yf.Ticker.history with str(date) and auto_adjust=True."""
    seen: dict[str, Any] = {}

    class FakeTicker:
        def __init__(self, sym: str) -> None:
            seen["symbol"] = sym

        def history(self, start: str, end: str, auto_adjust: bool) -> pd.DataFrame:
            seen["start"] = start
            seen["end"] = end
            seen["auto_adjust"] = auto_adjust
            return pd.DataFrame()

    monkeypatch.setattr("src.data_sources.yfinance_adapter.yf.Ticker", FakeTicker)
    from src.data_sources.yfinance_adapter import _fetch_history

    _fetch_history("NVDA", dt.date(2024, 6, 1), dt.date(2024, 12, 31))
    assert seen == {
        "symbol": "NVDA",
        "start": "2024-06-01",
        "end": "2024-12-31",
        "auto_adjust": True,
    }


def test_fetch_info_returns_empty_dict_when_yfinance_returns_falsy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """yfinance occasionally returns None / {} for invalid tickers — coerce to empty dict."""

    class FakeTicker:
        def __init__(self, sym: str) -> None:
            pass

        @property
        def info(self) -> dict[str, Any]:
            return {}

    monkeypatch.setattr("src.data_sources.yfinance_adapter.yf.Ticker", FakeTicker)
    from src.data_sources.yfinance_adapter import _fetch_info

    assert _fetch_info("FAKE_NVDA_X") == {}


def test_fetch_info_returns_dict_copy_when_yfinance_returns_dict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeTicker:
        def __init__(self, sym: str) -> None:
            pass

        @property
        def info(self) -> dict[str, Any]:
            return {"marketCap": 1234.0, "sector": "Technology"}

    monkeypatch.setattr("src.data_sources.yfinance_adapter.yf.Ticker", FakeTicker)
    from src.data_sources.yfinance_adapter import _fetch_info

    out = _fetch_info("NVDA")
    assert out["marketCap"] == 1234.0
    assert out["sector"] == "Technology"
