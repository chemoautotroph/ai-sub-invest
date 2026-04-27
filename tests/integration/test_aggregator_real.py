"""Integration smoke tests — hit real SEC + yfinance + openinsider for NVDA.

Marked @pytest.mark.integration so the default ``pytest`` (which uses
``testpaths = ["tests/unit"]``) doesn't run these. Trigger with:

    SEC_EDGAR_USER_AGENT="Your Name your-email@example.com" \\
        pytest tests/integration -m integration

These tests verify SHAPE not exact values — real data drifts every quarter,
and the point is to confirm the wiring works end-to-end. Exact-value checks
live in unit tests with frozen fixtures.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.data.models import (
    CompanyNews,
    FinancialMetrics,
    InsiderTrade,
    LineItem,
    Price,
)
from src.data_sources import aggregator as agg
from src.data_sources.cache import Cache


pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _require_user_agent() -> None:
    if not os.environ.get("SEC_EDGAR_USER_AGENT", "").strip():
        pytest.skip("SEC_EDGAR_USER_AGENT not set; skipping integration tests")


@pytest.fixture
def cache(tmp_path: Path) -> Cache:
    return Cache(tmp_path / "cache.db")


def test_real_get_prices_nvda_recent_window(cache: Cache) -> None:
    """OHLCV pulls. Just verify shape + magnitude: non-empty, valid Price models."""
    prices = agg.get_prices("NVDA", "2024-06-01", "2024-06-30", cache=cache)
    assert prices, "expected NVDA prices for June 2024"
    assert all(isinstance(p, Price) for p in prices)
    # Reasonable magnitude check (NVDA traded $100-$130 around then)
    closes = [p.close for p in prices]
    assert all(50.0 < c < 500.0 for c in closes), f"close out of range: min={min(closes)}, max={max(closes)}"


def test_real_get_market_cap_nvda_within_reasonable_band(cache: Cache) -> None:
    """NVDA market cap should be in the trillions — sanity bound."""
    mc = agg.get_market_cap("NVDA", "2024-12-31", cache=cache)
    assert mc is not None
    assert 5e11 < mc < 1e14, f"NVDA market cap looks wrong: ${mc:,.0f}"


def test_real_get_financial_metrics_nvda(cache: Cache) -> None:
    """End-to-end: SEC concepts → FY rows → FinancialMetrics with filled+unfilled split."""
    metrics = agg.get_financial_metrics("NVDA", "2026-04-26", limit=3, cache=cache)
    assert metrics, "expected at least one FY of NVDA financial metrics"
    m = metrics[0]
    assert isinstance(m, FinancialMetrics)
    # Filled fields must not be None for NVDA (a public US filer with full coverage)
    assert m.return_on_equity is not None
    assert m.operating_margin is not None
    assert m.gross_margin is not None
    assert m.market_cap is not None and m.market_cap > 0
    # Unfilled fields per Phase 0 决策 #3 must stay None
    for f in agg.INTENTIONALLY_UNFILLED_FIELDS:
        assert getattr(m, f) is None, f"{f} must stay None per Phase 0 决策 #3"


def test_real_search_line_items_nvda(cache: Cache) -> None:
    """LineItem build for the persona-frequent fields."""
    items = agg.search_line_items(
        "NVDA",
        ["revenue", "net_income", "capital_expenditure", "free_cash_flow",
         "outstanding_shares", "earnings_per_share"],
        "2026-04-26", limit=3, cache=cache,
    )
    assert items, "expected NVDA line items"
    item = items[0]
    assert isinstance(item, LineItem)
    # Sign convention: capex must be negative, free_cash_flow positive (NVDA prints cash)
    capex = getattr(item, "capital_expenditure")
    assert capex is not None and capex < 0
    fcf = getattr(item, "free_cash_flow")
    assert fcf is not None and fcf > 0  # NVDA's been FCF-positive forever
    # Unit checks
    eps = getattr(item, "earnings_per_share")
    assert eps is not None and -100.0 < eps < 100.0  # USD/shares, single-digit-ish
    shares = getattr(item, "outstanding_shares")
    assert shares is not None and 1e9 < shares < 1e11  # ~24B for NVDA


def test_real_get_insider_trades_nvda(cache: Cache) -> None:
    """OpenInsider scrape — NVDA has 100 trades on its screener page."""
    trades = agg.get_insider_trades("NVDA", "2026-04-26", cache=cache)
    assert trades, "expected NVDA insider trades"
    assert all(isinstance(t, InsiderTrade) for t in trades)
    # Phase 0 决策 #1 fields populated
    assert all(t.transaction_type in {"S", "P", "A", "M", "G", "D", "F", "X", "C"} or t.transaction_type for t in trades), (
        "transaction_type must be a recognized Form 4 code letter (or pass-through)"
    )


def test_real_get_company_news_nvda(cache: Cache) -> None:
    """yfinance news scrape — sentiment is None per Phase 0 决策 #2."""
    news = agg.get_company_news("NVDA", "2026-04-26", limit=20, cache=cache)
    if not news:
        pytest.skip("yfinance returned no news at this moment — flaky upstream, not our bug")
    assert all(isinstance(n, CompanyNews) for n in news)
    assert all(n.sentiment is None for n in news), "sentiment must be None (Phase 0 决策 #2)"
    assert all(n.ticker == "NVDA" for n in news)
