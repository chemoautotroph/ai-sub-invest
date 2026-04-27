"""Unit tests for src/data_sources/aggregator.py.

aggregator 是 Phase 1 拼装层 + 对外接口(签名 mirror src/tools/api.py)。
测试策略:全部 mock underlying adapter(sec_edgar / yfinance_adapter / openinsider),
让 aggregator 自身的拼装/缓存/契约逻辑接受 TDD。

测试分组:
  - 模块级 invariants(INTENTIONALLY_UNFILLED 与模型同步)
  - LINEITEM_CONCEPT_MAP fallback / sign convention 行为
  - 各 public 函数(get_prices / get_market_cap / get_financial_metrics /
    search_line_items / get_insider_trades / get_company_news)
  - cache key 不变量(line_items 排序、各 endpoint 参数完整)
  - Phase 0 决策 #2 / #3 / #4 / #5 contracts
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

import pandas as pd
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


SEC_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "sec"


@pytest.fixture
def cache(tmp_path: Path) -> Cache:
    return Cache(tmp_path / "cache.db")


@pytest.fixture
def nvda_facts() -> Any:
    """Real NVDA companyfacts CompanyFacts object (used for line-item integration)."""
    from src.data_sources.sec_edgar import _parse_companyfacts
    return _parse_companyfacts((SEC_FIXTURE_DIR / "NVDA_companyfacts.json").read_bytes())


# ===========================================================================
# Module-level invariants — Phase 0 决策 #3
# ===========================================================================


def test_intentionally_unfilled_fields_are_subset_of_model_fields() -> None:
    """Every name in INTENTIONALLY_UNFILLED_FIELDS must exist on FinancialMetrics.

    Why: spec § Phase 0 决策 #3 says these 22 fields are filled with ``None``.
    If the model adds/removes a field, the constant goes stale and the
    aggregator silently stops filling a now-required field. Catch that here.
    """
    model_fields = set(FinancialMetrics.model_fields.keys())
    unknown = agg.INTENTIONALLY_UNFILLED_FIELDS - model_fields
    assert not unknown, (
        f"INTENTIONALLY_UNFILLED_FIELDS contains names not on FinancialMetrics: {unknown}"
    )


def test_intentionally_unfilled_count_matches_phase0_decision() -> None:
    """Phase 0 决策 #3 lists 22 unfilled fields. Pinning the count protects
    against accidental drift (e.g., adding a field without spec update)."""
    assert len(agg.INTENTIONALLY_UNFILLED_FIELDS) == 22


def test_unfilled_and_filled_are_disjoint() -> None:
    """A field can't be both intentionally unfilled and actively computed."""
    overlap = agg.INTENTIONALLY_UNFILLED_FIELDS & agg.FILLED_FIELDS
    assert not overlap, f"Fields appear in both unfilled and filled: {overlap}"


# ===========================================================================
# LINEITEM_CONCEPT_MAP fallback semantics — user-required tests
# ===========================================================================


def test_lineitem_fallback_uses_secondary_concept_when_primary_empty(
    monkeypatch: pytest.MonkeyPatch, cache: Cache
) -> None:
    """Spec § Known Risks 'XBRL concept evolution': resolver tries the list
    in order and the first concept with non-empty data wins.

    Synthetic data: primary concept 'Revenues' has 0 datapoints, secondary
    'RevenueFromContractWithCustomerExcludingAssessedTax' has 1.
    """
    from src.data_sources.sec_edgar import CompanyFacts

    facts = CompanyFacts(
        cik=999,
        entity_name="Test Co",
        raw={
            "cik": 999,
            "entityName": "Test Co",
            "facts": {
                "us-gaap": {
                    # Primary missing entirely (or empty)
                    "RevenueFromContractWithCustomerExcludingAssessedTax": {
                        "units": {"USD": [{
                            "start": "2023-01-01", "end": "2023-12-31", "val": 50000.0,
                            "accn": "X", "fy": 2023, "fp": "FY",
                            "form": "10-K", "filed": "2024-02-01",
                        }]}
                    },
                }
            }
        },
    )

    field, concept_used, dps = agg._resolve_field_concept(facts, "revenue")
    assert field == "revenue"
    assert concept_used == "RevenueFromContractWithCustomerExcludingAssessedTax"
    assert len(dps) == 1 and dps[0].val == 50000.0


def test_lineitem_all_concepts_empty_returns_field_none(
    monkeypatch: pytest.MonkeyPatch, cache: Cache
) -> None:
    """If every concept in the fallback list returns empty, the resolver
    yields (field, None, []) — caller stores None in the LineItem field
    (spec § Common Conventions 'Canonical empty schema')."""
    from src.data_sources.sec_edgar import CompanyFacts

    facts = CompanyFacts(
        cik=999,
        entity_name="Test Co",
        raw={"cik": 999, "entityName": "Test Co", "facts": {"us-gaap": {}}},
    )
    field, concept_used, dps = agg._resolve_field_concept(facts, "revenue")
    assert field == "revenue"
    assert concept_used is None
    assert dps == []


def test_capex_real_nvda_uses_productive_assets_concept(nvda_facts: Any) -> None:
    """End-to-end on real NVDA fixture: capex resolver should pick
    PaymentsToAcquireProductiveAssets (FY2014+) over the deprecated
    PaymentsToAcquirePropertyPlantAndEquipment (FY2011 only).

    Failure here means LINEITEM_CONCEPT_MAP['capital_expenditure'] is in the
    wrong fallback order or the resolver short-circuited too early.
    """
    field, concept_used, dps = agg._resolve_field_concept(nvda_facts, "capital_expenditure")
    assert field == "capital_expenditure"
    # Both concepts exist in NVDA fixture; resolver should pick the modern one
    # because it has more datapoints (FY2014+) than the deprecated one (FY2011 only).
    assert concept_used == "PaymentsToAcquireProductiveAssets", (
        f"Expected modern concept to win, got {concept_used!r}"
    )
    assert len(dps) > 5, "PaymentsToAcquireProductiveAssets has 9+ FY rows in NVDA fixture"


def test_lineitem_capex_sign_flipped_to_negative(nvda_facts: Any) -> None:
    """Phase 0 决策 #4: SEC reports capex as positive; aggregator must
    flip to negative on the LineItem (mirrors financialdatasets convention)."""
    items = agg.search_line_items("NVDA", ["capital_expenditure"], "2026-04-26", limit=3,
                                   _facts=nvda_facts)
    assert items, "expected at least one capex line item"
    for item in items:
        capex = getattr(item, "capital_expenditure", None)
        assert capex is not None and capex < 0, (
            f"capex sign convention violated: got {capex} on {item.report_period}"
        )


def test_lineitem_dividends_sign_flipped_to_negative() -> None:
    """Same Phase 0 决策 #4 sign convention for dividends."""
    from src.data_sources.sec_edgar import CompanyFacts

    facts = CompanyFacts(
        cik=320193, entity_name="Apple Inc",
        raw={"cik": 320193, "entityName": "Apple Inc", "facts": {"us-gaap": {
            "PaymentsOfDividendsCommonStock": {"units": {"USD": [{
                "start": "2023-01-01", "end": "2023-12-31", "val": 14_000_000_000.0,
                "accn": "X", "fy": 2023, "fp": "FY", "form": "10-K", "filed": "2024-02-01",
            }]}}
        }}}
    )
    items = agg.search_line_items(
        "AAPL", ["dividends_and_other_cash_distributions"], "2024-12-31", limit=3,
        _facts=facts,
    )
    assert items
    div = getattr(items[0], "dividends_and_other_cash_distributions")
    assert div < 0, f"dividends sign convention violated: got {div}"
    assert div == -14_000_000_000.0


# ===========================================================================
# Cache key invariants — user-required
# ===========================================================================


def test_line_items_cache_key_order_invariant() -> None:
    """search_line_items called with ['a','b'] vs ['b','a'] must hit the same
    cache row. The cache key sorts the items list."""
    k1 = agg._line_items_cache_key("NVDA", ["revenue", "net_income"], "2024-12-31", "ttm", 10)
    k2 = agg._line_items_cache_key("NVDA", ["net_income", "revenue"], "2024-12-31", "ttm", 10)
    assert k1 == k2


def test_prices_cache_key_includes_dates() -> None:
    k1 = agg._prices_cache_key("NVDA", "2024-01-01", "2024-12-31")
    k2 = agg._prices_cache_key("NVDA", "2024-01-01", "2025-01-01")
    assert k1 != k2


def test_market_cap_not_cached_at_aggregator_level(
    monkeypatch: pytest.MonkeyPatch, cache: Cache
) -> None:
    """Common Convention #3: don't cache derived/composite. market_cap is
    derived from price × shares; aggregator MUST NOT cache it under
    'aggregator/market_cap'. Underlying components (basic_info, prices)
    have their own caches at their respective layers."""
    monkeypatch.setattr(
        "src.data_sources.aggregator._yf_get_market_cap",
        lambda ticker: 1_000_000_000.0,
    )
    agg.get_market_cap("NVDA", "2024-12-31", cache=cache)
    # Verify no aggregator/market_cap row was written
    assert cache.get("aggregator", "market_cap", "NVDA") is None


# ===========================================================================
# get_prices(ticker, start_date, end_date)
# ===========================================================================


def _fake_history_df() -> pd.DataFrame:
    idx = pd.DatetimeIndex(
        ["2024-06-03", "2024-06-04", "2024-06-05"], tz="UTC", name="Date"
    )
    return pd.DataFrame({
        "open":   [100.0, 101.0, 102.0],
        "high":   [101.0, 102.0, 103.0],
        "low":    [99.0, 100.0, 101.0],
        "close":  [100.5, 101.5, 102.5],
        "volume": [1000, 2000, 3000],
    }, index=idx)


def test_get_prices_returns_list_of_price_models(
    monkeypatch: pytest.MonkeyPatch, cache: Cache
) -> None:
    monkeypatch.setattr(
        "src.data_sources.aggregator._yf_get_prices",
        lambda ticker, start, end: _fake_history_df(),
    )
    prices = agg.get_prices("NVDA", "2024-06-01", "2024-06-30", cache=cache)
    assert len(prices) == 3
    assert all(isinstance(p, Price) for p in prices)
    assert prices[0].close == 100.5


def test_get_prices_empty_when_no_data(
    monkeypatch: pytest.MonkeyPatch, cache: Cache
) -> None:
    """Common Convention 'Canonical empty schema': empty input → empty list."""
    empty = pd.DataFrame(
        columns=["open", "high", "low", "close", "volume"],
        index=pd.DatetimeIndex([], tz="UTC"),
    )
    monkeypatch.setattr(
        "src.data_sources.aggregator._yf_get_prices",
        lambda ticker, start, end: empty,
    )
    assert agg.get_prices("NVDA", "1990-01-01", "1990-12-31", cache=cache) == []


def test_get_prices_uses_cache_on_second_call(
    monkeypatch: pytest.MonkeyPatch, cache: Cache
) -> None:
    """1d TTL per spec — second call within window must not re-fetch."""
    calls = [0]

    def fake_yf(ticker: str, start: str, end: str) -> pd.DataFrame:
        calls[0] += 1
        return _fake_history_df()

    monkeypatch.setattr("src.data_sources.aggregator._yf_get_prices", fake_yf)
    a = agg.get_prices("NVDA", "2024-06-01", "2024-06-30", cache=cache)
    b = agg.get_prices("NVDA", "2024-06-01", "2024-06-30", cache=cache)
    assert len(a) == len(b) == 3
    assert calls[0] == 1


# ===========================================================================
# get_market_cap(ticker, end_date) — Phase 1 simple version
# ===========================================================================


def test_get_market_cap_calls_yfinance(
    monkeypatch: pytest.MonkeyPatch, cache: Cache
) -> None:
    monkeypatch.setattr(
        "src.data_sources.aggregator._yf_get_market_cap",
        lambda ticker: 5_000_000_000_000.0,
    )
    mc = agg.get_market_cap("NVDA", "2024-12-31", cache=cache)
    assert mc == 5_000_000_000_000.0


def test_get_market_cap_returns_none_for_invalid_ticker(
    monkeypatch: pytest.MonkeyPatch, cache: Cache
) -> None:
    monkeypatch.setattr(
        "src.data_sources.aggregator._yf_get_market_cap",
        lambda ticker: None,
    )
    assert agg.get_market_cap("FAKE", "2024-12-31", cache=cache) is None


def test_get_market_cap_signature_matches_original_api() -> None:
    """Phase 2 routing depends on signature parity with src/tools/api.py.

    Persona scripts call ``get_market_cap(ticker, end_date)`` positionally.
    """
    import inspect
    sig = inspect.signature(agg.get_market_cap)
    params = list(sig.parameters)
    assert params[:2] == ["ticker", "end_date"], f"signature drift: {params}"


# ===========================================================================
# get_financial_metrics — Phase 0 决策 #3 (22 unfilled fields)
# ===========================================================================


def test_financial_metrics_unfilled_fields_are_none(
    monkeypatch: pytest.MonkeyPatch, cache: Cache, nvda_facts: Any
) -> None:
    """Spec § Phase 0 决策 #3: these 22 fields stay None even when we
    successfully build a FinancialMetrics row from real data."""
    monkeypatch.setattr("src.data_sources.aggregator._sec_company_facts", lambda t: nvda_facts)
    monkeypatch.setattr("src.data_sources.aggregator._yf_get_market_cap", lambda t: 5e12)

    metrics = agg.get_financial_metrics("NVDA", "2026-04-26", limit=1, cache=cache)
    assert metrics, "expected at least one FY metric row"
    m = metrics[0]
    for name in agg.INTENTIONALLY_UNFILLED_FIELDS:
        assert getattr(m, name) is None, (
            f"{name} should be None per Phase 0 决策 #3, got {getattr(m, name)!r}"
        )


def test_financial_metrics_filled_fields_are_populated(
    monkeypatch: pytest.MonkeyPatch, cache: Cache, nvda_facts: Any
) -> None:
    """The 18 fields persona scripts actually access must come back populated
    when source data is available."""
    monkeypatch.setattr("src.data_sources.aggregator._sec_company_facts", lambda t: nvda_facts)
    monkeypatch.setattr("src.data_sources.aggregator._yf_get_market_cap", lambda t: 5e12)

    metrics = agg.get_financial_metrics("NVDA", "2026-04-26", limit=1, cache=cache)
    m = metrics[0]
    # Core ratios that the audit (data_inventory.md § 3.1) flagged as required
    assert m.return_on_equity is not None
    assert m.operating_margin is not None
    assert m.gross_margin is not None
    assert m.net_margin is not None
    assert m.current_ratio is not None
    assert m.market_cap is not None and m.market_cap > 0
    # Required string fields
    assert m.ticker == "NVDA"
    assert m.report_period
    assert m.period
    assert m.currency == "USD"


def test_financial_metrics_uses_cache(
    monkeypatch: pytest.MonkeyPatch, cache: Cache, nvda_facts: Any
) -> None:
    calls = [0]

    def fake_facts(t: str) -> Any:
        calls[0] += 1
        return nvda_facts

    monkeypatch.setattr("src.data_sources.aggregator._sec_company_facts", fake_facts)
    monkeypatch.setattr("src.data_sources.aggregator._yf_get_market_cap", lambda t: 5e12)

    agg.get_financial_metrics("NVDA", "2026-04-26", limit=1, cache=cache)
    agg.get_financial_metrics("NVDA", "2026-04-26", limit=1, cache=cache)
    assert calls[0] == 1


# ===========================================================================
# search_line_items
# ===========================================================================


def test_search_line_items_returns_lineitem_models(
    monkeypatch: pytest.MonkeyPatch, cache: Cache, nvda_facts: Any
) -> None:
    items = agg.search_line_items(
        "NVDA", ["revenue", "net_income"], "2026-04-26", limit=3,
        _facts=nvda_facts,
    )
    assert items
    for item in items:
        assert isinstance(item, LineItem)
        assert item.ticker == "NVDA"
        assert getattr(item, "revenue", None) is not None
        assert getattr(item, "net_income", None) is not None


def test_search_line_items_unknown_field_yields_none(
    monkeypatch: pytest.MonkeyPatch, cache: Cache, nvda_facts: Any
) -> None:
    items = agg.search_line_items(
        "NVDA", ["totally_made_up_field"], "2026-04-26", limit=1,
        _facts=nvda_facts,
    )
    assert items
    # Unknown fields still get attribute access (extra=allow), value is None
    assert getattr(items[0], "totally_made_up_field", "MISSING") is None


def test_search_line_items_eps_uses_per_share_unit(
    monkeypatch: pytest.MonkeyPatch, cache: Cache, nvda_facts: Any
) -> None:
    """EPS comes from a USD/shares concept — value should land in single-digit
    range, not in billions (which would mean we mistakenly read the USD-unit
    fallback or multiplied by shares)."""
    items = agg.search_line_items(
        "NVDA", ["earnings_per_share"], "2026-04-26", limit=1,
        _facts=nvda_facts,
    )
    eps = getattr(items[0], "earnings_per_share", None)
    assert eps is not None
    assert -100.0 < eps < 100.0, f"EPS out of expected range: {eps}"


def test_search_line_items_outstanding_shares_uses_shares_unit(
    monkeypatch: pytest.MonkeyPatch, cache: Cache, nvda_facts: Any
) -> None:
    """outstanding_shares is in 'shares' unit (not USD). Value should be
    in billions (NVDA has ~24B shares) not trillions (which would mean
    we read a USD concept)."""
    items = agg.search_line_items(
        "NVDA", ["outstanding_shares"], "2026-04-26", limit=1,
        _facts=nvda_facts,
    )
    shares = getattr(items[0], "outstanding_shares", None)
    assert shares is not None
    # Order-of-magnitude check: NVDA has ~24B shares; bound 1B-100B
    assert 1e9 < shares < 1e11, f"outstanding_shares magnitude looks wrong: {shares}"


# ===========================================================================
# get_insider_trades — Phase 0 决策 #1 transaction_type pass-through
# ===========================================================================


def _fake_insider_trades_list() -> list[InsiderTrade]:
    return [
        InsiderTrade(
            ticker="NVDA", issuer=None, name="Doe John", title="Dir",
            is_board_director=True,
            transaction_date="2026-03-20", transaction_shares=-1000.0,
            transaction_price_per_share=170.0, transaction_value=-170000.0,
            shares_owned_before_transaction=None,
            shares_owned_after_transaction=5000.0,
            security_title=None, filing_date="2026-03-24",
            transaction_type="S", value=-170000.0,
        ),
    ]


def test_get_insider_trades_returns_list(
    monkeypatch: pytest.MonkeyPatch, cache: Cache
) -> None:
    monkeypatch.setattr(
        "src.data_sources.aggregator._oi_get_insider_trades",
        lambda ticker, cache: _fake_insider_trades_list(),
    )
    trades = agg.get_insider_trades("NVDA", "2026-04-26", cache=cache)
    assert len(trades) == 1
    assert trades[0].transaction_type == "S"
    assert trades[0].value == -170000.0


def test_get_insider_trades_uses_cache(
    monkeypatch: pytest.MonkeyPatch, cache: Cache
) -> None:
    calls = [0]

    def fake_oi(ticker: str, cache: Cache) -> list[InsiderTrade]:
        calls[0] += 1
        return _fake_insider_trades_list()

    monkeypatch.setattr("src.data_sources.aggregator._oi_get_insider_trades", fake_oi)
    agg.get_insider_trades("NVDA", "2026-04-26", cache=cache)
    agg.get_insider_trades("NVDA", "2026-04-26", cache=cache)
    assert calls[0] == 1


def test_insider_trades_filtered_by_end_date(
    monkeypatch: pytest.MonkeyPatch, cache: Cache
) -> None:
    """end_date acts as a filing_date_lte upper bound — trades after end_date are filtered."""
    trades = [
        InsiderTrade(
            ticker="NVDA", issuer=None, name=f"Person{i}", title="Dir",
            is_board_director=True,
            transaction_date=f"2026-0{i+1}-15", transaction_shares=-100.0,
            transaction_price_per_share=100.0, transaction_value=-10000.0,
            shares_owned_before_transaction=None,
            shares_owned_after_transaction=1000.0,
            security_title=None, filing_date=f"2026-0{i+1}-20",
            transaction_type="S", value=-10000.0,
        )
        for i in range(1, 6)  # filing dates 2026-02-20 through 2026-06-20
    ]
    monkeypatch.setattr(
        "src.data_sources.aggregator._oi_get_insider_trades",
        lambda t, c: trades,
    )
    result = agg.get_insider_trades("NVDA", "2026-03-31", cache=cache)
    # Only filings on/before 2026-03-31 included
    assert all(t.filing_date <= "2026-03-31" for t in result)
    assert len(result) <= 2


# ===========================================================================
# get_company_news — Phase 0 决策 #2 (sentiment 永远 None)
# ===========================================================================


def test_company_news_sentiment_is_always_none(
    monkeypatch: pytest.MonkeyPatch, cache: Cache
) -> None:
    """Phase 0 决策 #2: free backend never auto-tags sentiment. yfinance
    gives us title/publisher/link/timestamp; news-sentiment persona does
    its own keyword scoring downstream.
    """
    fake_yf_news = [
        {"title": "NVDA hits new high", "publisher": "Reuters",
         "link": "https://example.com/1",
         "providerPublishTime": 1716000000},  # epoch ts
        {"title": "Big Tech rally", "publisher": "Bloomberg",
         "link": "https://example.com/2",
         "providerPublishTime": 1716100000},
    ]
    monkeypatch.setattr(
        "src.data_sources.aggregator._yf_get_news",
        lambda ticker: fake_yf_news,
    )
    news = agg.get_company_news("NVDA", "2024-12-31", cache=cache)
    assert news, "expected at least one news item"
    for item in news:
        assert isinstance(item, CompanyNews)
        assert item.sentiment is None, (
            f"sentiment must be None per Phase 0 决策 #2, got {item.sentiment!r}"
        )


def test_company_news_uses_cache(
    monkeypatch: pytest.MonkeyPatch, cache: Cache
) -> None:
    calls = [0]

    def fake_news(ticker: str) -> list[dict]:
        calls[0] += 1
        return [{"title": "T", "publisher": "P", "link": "L", "providerPublishTime": 1716000000}]

    monkeypatch.setattr("src.data_sources.aggregator._yf_get_news", fake_news)
    agg.get_company_news("NVDA", "2024-12-31", cache=cache)
    agg.get_company_news("NVDA", "2024-12-31", cache=cache)
    assert calls[0] == 1


# ===========================================================================
# Public-API signature parity with src/tools/api.py — Phase 2 routing
# ===========================================================================


@pytest.mark.parametrize(
    "fn_name,expected_first_params",
    [
        ("get_prices", ["ticker", "start_date", "end_date"]),
        ("get_market_cap", ["ticker", "end_date"]),
        ("get_financial_metrics", ["ticker", "end_date"]),
        ("search_line_items", ["ticker", "line_items", "end_date"]),
        ("get_insider_trades", ["ticker", "end_date"]),
        ("get_company_news", ["ticker", "end_date"]),
    ],
)
def test_public_function_signatures_mirror_api_py(
    fn_name: str, expected_first_params: list[str]
) -> None:
    """Phase 2 routing in src/tools/api.py expects these positional args.
    Drift here breaks every persona script that uses the free backend."""
    import inspect
    fn = getattr(agg, fn_name)
    actual = list(inspect.signature(fn).parameters)
    assert actual[: len(expected_first_params)] == expected_first_params, (
        f"{fn_name} signature drift: actual {actual} vs expected start {expected_first_params}"
    )


# ===========================================================================
# Derived fields (free_cash_flow, book_value_per_share) — coverage for the
# special-case branches in _build_line_items
# ===========================================================================


def test_search_line_items_free_cash_flow_is_ocf_plus_signed_capex(
    nvda_facts: Any,
) -> None:
    """free_cash_flow is derived: ocf + capex (capex already signed negative).
    Build NVDA, verify FCF for the latest FY equals ocf + (-capex_raw).
    """
    items = agg.search_line_items(
        "NVDA", ["free_cash_flow", "operating_cash_flow", "capital_expenditure"],
        "2026-04-26", limit=1, _facts=nvda_facts,
    )
    assert items
    item = items[0]
    fcf = getattr(item, "free_cash_flow", None)
    ocf = getattr(item, "operating_cash_flow", None)
    capex = getattr(item, "capital_expenditure", None)
    assert fcf is not None and ocf is not None and capex is not None
    assert fcf == ocf + capex, (
        f"free_cash_flow {fcf} != ocf {ocf} + capex {capex}; "
        "likely sign-convention regression"
    )


def test_search_line_items_book_value_per_share_is_equity_over_shares(
    nvda_facts: Any,
) -> None:
    """book_value_per_share is derived: SE / outstanding_shares."""
    items = agg.search_line_items(
        "NVDA", ["book_value_per_share", "stockholders_equity", "outstanding_shares"],
        "2026-04-26", limit=1, _facts=nvda_facts,
    )
    assert items
    item = items[0]
    bvps = getattr(item, "book_value_per_share", None)
    se = getattr(item, "stockholders_equity", None)
    shares = getattr(item, "outstanding_shares", None)
    assert bvps is not None and se is not None and shares is not None
    assert bvps == pytest.approx(se / shares, rel=1e-9)


# ===========================================================================
# Company news date filtering
# ===========================================================================


def test_company_news_filters_by_start_and_end_date(
    monkeypatch: pytest.MonkeyPatch, cache: Cache
) -> None:
    """end_date upper-bounds AND start_date lower-bounds the publish dates."""
    fake = [
        {"title": "Old", "publisher": "P", "link": "L1", "providerPublishTime": 1700000000},  # 2023-11
        {"title": "Mid", "publisher": "P", "link": "L2", "providerPublishTime": 1717200000},  # 2024-06
        {"title": "Recent", "publisher": "P", "link": "L3", "providerPublishTime": 1735600000},  # 2024-12-31
    ]
    monkeypatch.setattr("src.data_sources.aggregator._yf_get_news", lambda t: fake)
    out = agg.get_company_news(
        "NVDA", end_date="2024-09-30", start_date="2024-01-01", cache=cache,
    )
    titles = [n.title for n in out]
    assert titles == ["Mid"]


def test_company_news_limit_truncates_results(
    monkeypatch: pytest.MonkeyPatch, cache: Cache
) -> None:
    fake = [
        {"title": f"News{i}", "publisher": "P", "link": f"L{i}",
         "providerPublishTime": 1717200000 + i}
        for i in range(10)
    ]
    monkeypatch.setattr("src.data_sources.aggregator._yf_get_news", lambda t: fake)
    out = agg.get_company_news("NVDA", "2024-12-31", limit=3, cache=cache)
    assert len(out) == 3


# ===========================================================================
# Internal _safe_div / _safe_growth — micro tests for helper coverage
# ===========================================================================


def test_safe_div_returns_none_on_none_inputs() -> None:
    assert agg._safe_div(None, 100.0) is None
    assert agg._safe_div(100.0, None) is None
    assert agg._safe_div(None, None) is None


def test_safe_div_returns_none_on_zero_denominator() -> None:
    assert agg._safe_div(100.0, 0.0) is None


def test_safe_div_normal() -> None:
    assert agg._safe_div(20.0, 100.0) == 0.2


def test_safe_growth_returns_none_when_prior_zero_or_missing() -> None:
    assert agg._safe_growth(110.0, None) is None
    assert agg._safe_growth(110.0, 0.0) is None
    assert agg._safe_growth(None, 100.0) is None


def test_safe_growth_uses_abs_of_prior() -> None:
    """Growth = (current - prior) / |prior| so a negative-base loss-to-profit
    swing reads as positive growth, which matches typical earnings-growth conventions."""
    assert agg._safe_growth(120.0, 100.0) == pytest.approx(0.20)
    # Loss-to-smaller-loss: from -100 → -50 is improvement, growth +50%
    assert agg._safe_growth(-50.0, -100.0) == pytest.approx(0.50)


# ===========================================================================
# total_debt as sum of components — replaces single-concept fallback
# (cleanup post-Phase 1.6 per Known Risks #2 generalised to multi-concept)
# ===========================================================================


def _synthetic_debt_facts(component_values: dict[str, float], fy: int = 2023) -> Any:
    """Build a CompanyFacts with the given debt components populated for one FY."""
    from src.data_sources.sec_edgar import _parse_companyfacts
    us_gaap: dict[str, Any] = {}
    for concept, val in component_values.items():
        us_gaap[concept] = {"units": {"USD": [{
            "end": "2023-12-31", "val": val,
            "accn": "X", "fy": fy, "fp": "FY",
            "form": "10-K", "filed": "2024-02-15",
        }]}}
    body = json.dumps({
        "cik": 999, "entityName": "Test Co",
        "facts": {"us-gaap": us_gaap},
    }).encode()
    return _parse_companyfacts(body)


def test_total_debt_sums_long_and_short_term() -> None:
    """LongTermDebt 100 + ShortTermBorrowings 50 → total 150.

    Synthetic edge case (per Common Conventions Mixed Test Inputs).
    Validates the aggregation arithmetic on a value pair where overlap
    isn't possible (long-term umbrella vs short-term).
    """
    facts = _synthetic_debt_facts({
        "LongTermDebt": 100.0,
        "ShortTermBorrowings": 50.0,
    })
    out = agg._values_by_fy(facts, "total_debt")
    assert out == {2023: 150.0}


def test_total_debt_partial_components_logs_which_hit(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Only LongTermDebt populated → total = LongTermDebt; log identifies which
    components contributed (operations team needs traceability for unexpected
    debt levels)."""
    import logging
    facts = _synthetic_debt_facts({"LongTermDebt": 100.0})
    with caplog.at_level(logging.INFO, logger="src.data_sources.aggregator"):
        out = agg._values_by_fy(facts, "total_debt")
    assert out == {2023: 100.0}
    assert "LongTermDebt" in caplog.text
    assert "ShortTermBorrowings" not in caplog.text  # missing component absent from "hit" list


def test_total_debt_all_empty_returns_none() -> None:
    """No debt-related concepts populated → empty dict (downstream FinancialMetrics
    sees None for debt_to_equity)."""
    facts = _synthetic_debt_facts({})  # no concepts at all
    out = agg._values_by_fy(facts, "total_debt")
    assert out == {}


def test_total_debt_drops_subcomponents_when_umbrella_present(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """When ``LongTermDebt`` (umbrella) AND its sub-components are both
    reported, drop the sub-components — the umbrella already includes them.

    Before this dedup NVDA total_debt ran ~2x too high, since NVDA's 10-K
    reports BOTH ``LongTermDebt`` (umbrella, e.g. $10B) AND
    ``LongTermDebtCurrent`` + ``LongTermDebtNoncurrent`` (the same $10B
    split into current + non-current portions). Naive summing → ~$20B.
    """
    import logging
    facts = _synthetic_debt_facts({
        "LongTermDebt": 100.0,           # umbrella; its sub-components total 90
        "LongTermDebtCurrent": 30.0,
        "LongTermDebtNoncurrent": 60.0,
        "ShortTermBorrowings": 25.0,     # not part of LongTermDebt umbrella; keep
    })
    with caplog.at_level(logging.INFO, logger="src.data_sources.aggregator"):
        out = agg._values_by_fy(facts, "total_debt")
    # Expected: umbrella (100) + ShortTermBorrowings (25) = 125
    # NOT umbrella + sub-components + short-term = 100+30+60+25 = 215 (the bug)
    assert out == {2023: 125.0}, f"umbrella dedup failed; got {out}"
    # Log mentions the umbrella dedup happened
    assert "umbrella" in caplog.text.lower()
    assert "LongTermDebtCurrent" in caplog.text or "LongTermDebtNoncurrent" in caplog.text


def test_total_debt_keeps_subcomponents_when_no_umbrella() -> None:
    """When the umbrella ``LongTermDebt`` is absent, sub-components ARE summed
    (because nothing else captures the long-term debt total)."""
    facts = _synthetic_debt_facts({
        "LongTermDebtCurrent": 30.0,      # no umbrella present
        "LongTermDebtNoncurrent": 60.0,
        "ShortTermBorrowings": 25.0,
    })
    out = agg._values_by_fy(facts, "total_debt")
    # All three sum together: 30 + 60 + 25 = 115
    assert out == {2023: 115.0}, f"expected sub-component sum without umbrella; got {out}"


def test_total_debt_real_nvda_no_double_count_warning(
    nvda_facts: Any, caplog: pytest.LogCaptureFixture,
) -> None:
    """End-to-end on real NVDA fixture — pre-fix this would fire the
    double-count warning every fy. Post-fix the umbrella dedup runs silently
    (info-level log, not warning) and total_debt comes back at the umbrella
    LongTermDebt value, not 2x.
    """
    import logging
    with caplog.at_level(logging.WARNING, logger="src.data_sources.aggregator"):
        out = agg._values_by_fy(nvda_facts, "total_debt")
    # Real NVDA reports both umbrella + components — verify dedup engaged
    # and no WARNING-level double-count message fired
    assert out, "NVDA must have at least one FY of total_debt"
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    double_count_warnings = [r for r in warnings if "double-count" in r.message]
    assert not double_count_warnings, (
        "umbrella dedup did not engage on NVDA; double-count warnings fired: "
        f"{[r.message for r in double_count_warnings]}"
    )
    # Sanity: NVDA latest debt should be in the single-digit billions, not 20B+
    latest_fy = max(out.keys())
    assert 1e9 < out[latest_fy] < 2e10, (
        f"NVDA total_debt fy={latest_fy} = {out[latest_fy]:.2e} looks wrong "
        "(if this fires, dedup may be over-aggressive or another umbrella exists)"
    )
