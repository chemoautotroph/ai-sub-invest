"""Aggregator — public API for the free-backend data layer.

Signatures **mirror** ``src/tools/api.py`` so Phase 2 can env-route between
paid and free implementations with zero changes to persona code.

Architecture per spec § Common Conventions:
  - Network calls live in adapters (sec_edgar / yfinance_adapter / openinsider)
  - This module composes them; no new HTTP here
  - Cache is at the (source="aggregator", endpoint=<func>, key=<param-tuple>) layer
  - Composite/derived values are NOT cached (Common Convention #3) — only
    raw adapter outputs are cached at their respective adapter layers, and
    composed payloads are cached at this layer keyed by the input tuple

Module-level safety net:
  ``INTENTIONALLY_UNFILLED_FIELDS`` is verified against ``FinancialMetrics``
  schema at import time; a model rename / removal raises ``RuntimeError``
  before the first call.

Spec deviations (each documented at the call site that introduces them):
  - ``get_market_cap`` ignores ``end_date`` (Phase 1 simple version per
    Phase 0 决策 #5; ±10% precision noted)
  - ``period`` parameter is honored only nominally; FY annual rows are
    returned regardless (TTM aliases to latest FY for Phase 1)
"""
from __future__ import annotations

import datetime as dt
import json
import logging
from collections.abc import Sequence
from typing import Any, Final

import pandas as pd
from pydantic import BaseModel

from src.data.models import (
    CompanyNews,
    FinancialMetrics,
    InsiderTrade,
    LineItem,
    Price,
)
from src.data_sources import (
    computed,
    openinsider as _openinsider_mod,
    sec_edgar as _sec_edgar_mod,
    yfinance_adapter as _yfinance_mod,
)
from src.data_sources.cache import Cache, CacheTTL


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# adapter-call shims — single point of indirection so tests can monkeypatch
# without juggling multiple module names. Real flow: call through to adapter.
# ---------------------------------------------------------------------------


def _yf_get_prices(ticker: str, start: str, end: str) -> pd.DataFrame:
    return _yfinance_mod.get_prices(
        ticker, dt.date.fromisoformat(start), dt.date.fromisoformat(end)
    )


def _yf_get_market_cap(ticker: str) -> float | None:
    return _yfinance_mod.get_market_cap(ticker)


def _yf_get_news(ticker: str) -> list[dict[str, Any]]:
    """Read ``Ticker.news`` directly. yfinance returns a list of dicts with
    title / publisher / link / providerPublishTime (epoch seconds)."""
    import yfinance as yf
    raw = yf.Ticker(ticker).news
    return list(raw) if raw else []


def _sec_company_facts(ticker: str) -> Any:
    cik = _sec_edgar_mod.get_cik_for_ticker(ticker)
    return _sec_edgar_mod.get_company_facts(cik)


def _oi_get_insider_trades(ticker: str, cache: Cache) -> list[InsiderTrade]:
    return _openinsider_mod.get_insider_trades(ticker, cache=cache)


# ---------------------------------------------------------------------------
# Phase 0 决策 #3 — INTENTIONALLY_UNFILLED_FIELDS contract
# ---------------------------------------------------------------------------


INTENTIONALLY_UNFILLED_FIELDS: Final[frozenset[str]] = frozenset({
    "enterprise_value",
    "enterprise_value_to_ebitda_ratio",
    "enterprise_value_to_revenue_ratio",
    "peg_ratio",
    "return_on_assets",
    "inventory_turnover",
    "receivables_turnover",
    "days_sales_outstanding",
    "operating_cycle",
    "working_capital_turnover",
    "quick_ratio",
    "cash_ratio",
    "operating_cash_flow_ratio",
    "debt_to_assets",
    "interest_coverage",
    "earnings_per_share_growth",
    "free_cash_flow_growth",
    "operating_income_growth",
    "ebitda_growth",
    "payout_ratio",
    "book_value_growth",
    "free_cash_flow_yield",
})

FILLED_FIELDS: Final[frozenset[str]] = frozenset({
    # The 17 metrics persona scripts read from FinancialMetrics
    # (data_inventory.md § 3.1, minus market_cap which goes via get_market_cap).
    "market_cap",
    "price_to_earnings_ratio",
    "price_to_book_ratio",
    "price_to_sales_ratio",
    "gross_margin",
    "operating_margin",
    "net_margin",
    "return_on_equity",
    "return_on_invested_capital",
    "asset_turnover",
    "current_ratio",
    "debt_to_equity",
    "revenue_growth",
    "earnings_growth",
    "earnings_per_share",
    "book_value_per_share",
    "free_cash_flow_per_share",
})


# Module-level safety: catch schema drift at import time.
_model_fields = set(FinancialMetrics.model_fields.keys())
_unknown_unfilled = INTENTIONALLY_UNFILLED_FIELDS - _model_fields
if _unknown_unfilled:
    raise RuntimeError(
        f"INTENTIONALLY_UNFILLED_FIELDS contains names not on FinancialMetrics: "
        f"{_unknown_unfilled}"
    )
_unknown_filled = FILLED_FIELDS - _model_fields
if _unknown_filled:
    raise RuntimeError(
        f"FILLED_FIELDS contains names not on FinancialMetrics: {_unknown_filled}"
    )
del _model_fields, _unknown_unfilled, _unknown_filled


# ---------------------------------------------------------------------------
# Phase 0 决策 #4 + Known Risk #2 — LINEITEM_CONCEPT_MAP fallback
# ---------------------------------------------------------------------------


# Semantic LineItem field → ordered list of SEC concepts. First non-empty wins.
LINEITEM_CONCEPT_MAP: Final[dict[str, list[str]]] = {
    "revenue": [
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",  # ASC 606
        "SalesRevenueNet",  # legacy
    ],
    "net_income": ["NetIncomeLoss"],
    "operating_income": ["OperatingIncomeLoss"],
    "gross_profit": ["GrossProfit"],
    "operating_cash_flow": ["NetCashProvidedByUsedInOperatingActivities"],
    "capital_expenditure": [
        # NVDA switched concepts FY2014; modern first
        "PaymentsToAcquireProductiveAssets",
        "PaymentsToAcquirePropertyPlantAndEquipment",
    ],
    "depreciation_and_amortization": [
        "DepreciationDepletionAndAmortization",
        "DepreciationAndAmortization",
    ],
    "current_assets": ["AssetsCurrent"],
    "current_liabilities": ["LiabilitiesCurrent"],
    "total_assets": ["Assets"],
    "total_liabilities": ["Liabilities"],
    "total_debt": ["LongTermDebt"],
    "stockholders_equity": ["StockholdersEquity"],
    "shareholders_equity": ["StockholdersEquity"],  # alias used by some persona
    "outstanding_shares": [
        "EntityCommonStockSharesOutstanding",  # dei taxonomy
        "CommonStockSharesOutstanding",
    ],
    "shares_outstanding": [
        "EntityCommonStockSharesOutstanding",
        "CommonStockSharesOutstanding",
    ],
    "dividends_and_other_cash_distributions": [
        "PaymentsOfDividendsCommonStock",
        "PaymentsOfDividends",
    ],
    "earnings_per_share": [
        "EarningsPerShareBasic",
        "EarningsPerShareDiluted",
    ],
    # Derived; aggregator computes specially (not via LINEITEM_CONCEPT_MAP)
    "free_cash_flow": [],
    "book_value_per_share": [],
    "issuance_or_purchase_of_equity_shares": [
        "StockRepurchasedAndRetiredDuringPeriodValue",
    ],
}


# Sibling map — most fields are USD; per-share ones are USD/shares; raw share
# counts are 'shares'. SEC reports each concept under exactly one unit.
LINEITEM_FIELD_UNIT: Final[dict[str, str]] = {
    "earnings_per_share": "USD/shares",
    "outstanding_shares": "shares",
    "shares_outstanding": "shares",
}


def _unit_for_field(field: str) -> str:
    return LINEITEM_FIELD_UNIT.get(field, "USD")


# ---------------------------------------------------------------------------
# concept resolution — fallback iterator
# ---------------------------------------------------------------------------


def _resolve_field_concept(
    facts: Any, field: str
) -> tuple[str, str | None, list[Any]]:
    """Walk ``LINEITEM_CONCEPT_MAP[field]`` in order, return (field, concept_used, datapoints).

    First concept yielding a non-empty list wins. ``concept_used`` is
    ``None`` if every fallback returned empty (caller stores ``None`` value).
    """
    candidates = LINEITEM_CONCEPT_MAP.get(field, [])
    unit = _unit_for_field(field)
    for concept in candidates:
        dps = _sec_edgar_mod._datapoints_for_concept(facts, concept, unit)
        if dps:
            logger.info(
                "aggregator: field %r resolved via SEC concept %r (%d datapoints)",
                field, concept, len(dps),
            )
            return field, concept, dps
    if candidates:
        logger.warning(
            "aggregator: field %r — none of the fallback concepts yielded data: %s",
            field, candidates,
        )
    return field, None, []


# ---------------------------------------------------------------------------
# cache key builders — explicit so tests can pin them
# ---------------------------------------------------------------------------


def _prices_cache_key(ticker: str, start: str, end: str) -> str:
    return f"{ticker.upper()}|{start}|{end}"


def _financial_metrics_cache_key(
    ticker: str, end: str, period: str, limit: int
) -> str:
    return f"{ticker.upper()}|{end}|{period}|{limit}"


def _line_items_cache_key(
    ticker: str, items: list[str], end: str, period: str, limit: int
) -> str:
    """Sorted items list → order-invariant cache key (per spec § 1.6)."""
    items_part = ",".join(sorted(items))
    return f"{ticker.upper()}|{items_part}|{end}|{period}|{limit}"


def _insider_trades_cache_key(
    ticker: str, end: str, start: str | None, limit: int
) -> str:
    return f"{ticker.upper()}|{end}|{start or 'none'}|{limit}"


def _company_news_cache_key(
    ticker: str, end: str, start: str | None, limit: int
) -> str:
    return f"{ticker.upper()}|{end}|{start or 'none'}|{limit}"


# ---------------------------------------------------------------------------
# (de)serialization helpers — Pydantic ↔ JSON-bytes for cache layer
# ---------------------------------------------------------------------------


def _serialize_models(models: Sequence[BaseModel]) -> bytes:
    return json.dumps([m.model_dump(mode="json") for m in models]).encode()


def _deserialize_models(body: bytes, cls: type[Any]) -> list[Any]:
    return [cls(**d) for d in json.loads(body)]


# ===========================================================================
# Public API — signatures mirror src/tools/api.py
# ===========================================================================


def get_prices(
    ticker: str,
    start_date: str,
    end_date: str,
    api_key: str | None = None,
    *,
    cache: Cache | None = None,
) -> list[Price]:
    """OHLCV time series. Cache 1d (spec TTL 表 § aggregator.prices)."""
    cache = cache or Cache()
    key = _prices_cache_key(ticker, start_date, end_date)
    cached = cache.get("aggregator", "prices", key)
    if cached is not None:
        return _deserialize_models(cached, Price)

    df = _yf_get_prices(ticker, start_date, end_date)
    if df.empty:
        return []
    prices = [
        Price(
            open=float(row.open), high=float(row.high), low=float(row.low),
            close=float(row.close), volume=int(row.volume),
            time=ts.date().isoformat(),
        )
        for ts, row in df.iterrows()
    ]
    cache.set("aggregator", "prices", key, _serialize_models(prices), CacheTTL.AGGREGATOR_PRICES)
    return prices


def get_market_cap(
    ticker: str,
    end_date: str,
    api_key: str | None = None,
    *,
    cache: Cache | None = None,
) -> float | None:
    """Current market cap, ``end_date`` ignored in Phase 1 simple version.

    Phase 0 决策 #5: simple = ``close × current_shares``, ±10% precision
    (split-adjusted close × current shares ≠ true historical market cap;
    error grows for small-caps and aggressive buyback companies). Stretch
    goal #1 covers a precise version using per-period EntityCommonStock-
    SharesOutstanding paired with split-adjusted close.

    NOT cached at this layer (Common Convention #3 — derived/composite).
    Underlying ``yfinance.basic_info`` and prices are cached at their own layers.
    """
    # cache parameter accepted for signature symmetry but not used for market_cap
    return _yf_get_market_cap(ticker)


def get_financial_metrics(
    ticker: str,
    end_date: str,
    period: str = "ttm",
    limit: int = 10,
    api_key: str | None = None,
    *,
    cache: Cache | None = None,
) -> list[FinancialMetrics]:
    """FinancialMetrics rows for the latest ``limit`` fiscal years on/before ``end_date``.

    Phase 1 simple version: returns annual FY rows regardless of ``period``;
    TTM aliases to latest FY. Phase 2 A/B testing will reveal whether persona
    scripts depend on quarterly granularity.

    Cache 7d (spec TTL 表 § aggregator.financial_metrics).
    """
    cache = cache or Cache()
    key = _financial_metrics_cache_key(ticker, end_date, period, limit)
    cached = cache.get("aggregator", "financial_metrics", key)
    if cached is not None:
        return _deserialize_models(cached, FinancialMetrics)

    facts = _sec_company_facts(ticker)
    market_cap = _yf_get_market_cap(ticker)

    # FY series for each filled field
    fy_rows = _build_financial_metrics(ticker, facts, market_cap, end_date, limit)

    cache.set(
        "aggregator", "financial_metrics", key,
        _serialize_models(fy_rows), CacheTTL.AGGREGATOR_FINANCIAL_METRICS,
    )
    return fy_rows


def search_line_items(
    ticker: str,
    line_items: list[str],
    end_date: str,
    period: str = "ttm",
    limit: int = 10,
    api_key: str | None = None,
    *,
    cache: Cache | None = None,
    _facts: Any = None,  # test seam; production callers don't supply this
) -> list[LineItem]:
    """LineItem rows with the requested semantic fields populated.

    Cache 7d (reuses financial_metrics TTL — both come from the same
    SEC daily JSON, no need for a separate constant).
    """
    cache = cache or Cache()
    key = _line_items_cache_key(ticker, line_items, end_date, period, limit)
    if _facts is None:  # only consult cache when the call is real
        cached = cache.get("aggregator", "line_items", key)
        if cached is not None:
            return _deserialize_models(cached, LineItem)

    facts = _facts if _facts is not None else _sec_company_facts(ticker)
    out = _build_line_items(ticker, facts, line_items, end_date, period, limit)

    if _facts is None:
        cache.set(
            "aggregator", "line_items", key,
            _serialize_models(out), CacheTTL.AGGREGATOR_FINANCIAL_METRICS,
        )
    return out


def get_insider_trades(
    ticker: str,
    end_date: str,
    start_date: str | None = None,
    limit: int = 1000,
    api_key: str | None = None,
    *,
    cache: Cache | None = None,
) -> list[InsiderTrade]:
    """OpenInsider-sourced trades filtered to ``[start_date, end_date]`` filing window.

    4h cache (spec TTL 表 § aggregator.insider_trades).
    """
    cache = cache or Cache()
    key = _insider_trades_cache_key(ticker, end_date, start_date, limit)
    cached = cache.get("aggregator", "insider_trades", key)
    if cached is not None:
        return _deserialize_models(cached, InsiderTrade)

    raw = _oi_get_insider_trades(ticker, cache)
    filtered = [
        t for t in raw
        if (not end_date or t.filing_date <= end_date)
        and (not start_date or (t.filing_date and t.filing_date >= start_date))
    ][:limit]
    cache.set(
        "aggregator", "insider_trades", key,
        _serialize_models(filtered), CacheTTL.AGGREGATOR_INSIDER_TRADES,
    )
    return filtered


def get_company_news(
    ticker: str,
    end_date: str,
    start_date: str | None = None,
    limit: int = 1000,
    api_key: str | None = None,
    *,
    cache: Cache | None = None,
) -> list[CompanyNews]:
    """Company news from yfinance ``Ticker.news``.

    Phase 0 决策 #2: ``sentiment`` field is **always None** — free backend
    does not auto-tag sentiment. ``news-sentiment`` persona does its own
    keyword scoring downstream.

    1h cache (spec TTL 表 § aggregator.company_news).
    """
    cache = cache or Cache()
    key = _company_news_cache_key(ticker, end_date, start_date, limit)
    cached = cache.get("aggregator", "company_news", key)
    if cached is not None:
        return _deserialize_models(cached, CompanyNews)

    raw = _yf_get_news(ticker)
    out: list[CompanyNews] = []
    for item in raw:
        ts_epoch = item.get("providerPublishTime")
        date_str = (
            dt.datetime.fromtimestamp(ts_epoch, tz=dt.timezone.utc).date().isoformat()
            if ts_epoch else ""
        )
        if end_date and date_str > end_date:
            continue
        if start_date and date_str and date_str < start_date:
            continue
        out.append(CompanyNews(
            ticker=ticker.upper(),
            title=str(item.get("title", "")),
            author="",  # yfinance doesn't expose author
            source=str(item.get("publisher", "")),
            date=date_str,
            url=str(item.get("link", "")),
            sentiment=None,  # Phase 0 决策 #2
        ))
    out = out[:limit]
    cache.set(
        "aggregator", "company_news", key,
        _serialize_models(out), CacheTTL.AGGREGATOR_COMPANY_NEWS,
    )
    return out


# ===========================================================================
# Internal builders — helpers for the public functions above
# ===========================================================================


def _build_line_items(
    ticker: str,
    facts: Any,
    requested_fields: list[str],
    end_date: str,
    period: str,
    limit: int,
) -> list[LineItem]:
    """Build LineItem rows keyed by fiscal year.

    Why fy-keyed (not end-date keyed): SEC reports flow concepts (NetIncomeLoss,
    Revenues) with end = fiscal year close, but instant concepts (shares
    outstanding, balance-sheet items) often have end = a few weeks LATER (10-K
    cover-page date). Aligning by ``fy`` collapses that fuzz so a single
    LineItem captures one fiscal year's worth of mixed-temporal-shape concepts.
    """
    # Pre-resolve each requested field to its {fy: signed_val} map
    field_value_by_fy: dict[str, dict[int, float]] = {}
    for field in requested_fields:
        if field == "free_cash_flow":
            ocf_map = _values_by_fy(facts, "operating_cash_flow")
            capex_map = _values_by_fy(facts, "capital_expenditure")
            merged: dict[int, float] = {}
            for fy, ocf_val in ocf_map.items():
                if fy in capex_map:
                    merged[fy] = ocf_val + capex_map[fy]
            field_value_by_fy[field] = merged
            continue

        if field == "book_value_per_share":
            se_map = _values_by_fy(facts, "stockholders_equity")
            sh_map = _values_by_fy(facts, "outstanding_shares")
            merged = {}
            for fy, se in se_map.items():
                shares = sh_map.get(fy)
                if shares and shares != 0:
                    merged[fy] = se / shares
            field_value_by_fy[field] = merged
            continue

        field_value_by_fy[field] = _values_by_fy(facts, field)

    # Anchor: NetIncomeLoss FY rows (every US public filer has them) → maps fy → end-date
    anchor_dps = _sec_edgar_mod._datapoints_for_concept(facts, "NetIncomeLoss", "USD")
    end_cap = dt.date.fromisoformat(end_date)
    fy_to_end: dict[int, dt.date] = {}
    for dp in anchor_dps:
        if (
            dp.fp == "FY"
            and dp.fy is not None
            and dp.start is not None
            and (dp.end - dp.start).days > 350
            and dp.end <= end_cap
        ):
            # latest filing wins (sec_edgar already deduped by start/end/fp/fy)
            fy_to_end[dp.fy] = dp.end

    # Fallback anchor: synthetic-data path or non-NIL companies — union of
    # resolved fields' fy keys, dates approximated as fiscal-year-end-of-fy
    if not fy_to_end:
        all_fys: set[int] = set()
        for fy_map in field_value_by_fy.values():
            all_fys.update(fy_map.keys())
        # No NetIncomeLoss anchor → use the resolved fields' end-dates directly
        # (taken from any concept's _datapoints_for_concept output for that fy)
        fy_to_end = _approx_fy_ends(facts, all_fys, end_cap)

    fy_list = sorted(
        (fy for fy in fy_to_end if fy_to_end[fy] <= end_cap),
        reverse=True,
    )[:limit]

    out: list[LineItem] = []
    for fy in fy_list:
        kwargs: dict[str, Any] = {
            "ticker": ticker.upper(),
            "report_period": fy_to_end[fy].isoformat(),
            "period": period,
            "currency": "USD",
        }
        for field in requested_fields:
            kwargs[field] = field_value_by_fy.get(field, {}).get(fy)
        out.append(LineItem(**kwargs))
    return out


def _approx_fy_ends(facts: Any, target_fys: set[int], end_cap: dt.date) -> dict[int, dt.date]:
    """For synthetic / NIL-less data: pick any concept's fy→end mapping."""
    out: dict[int, dt.date] = {}
    if not target_fys:
        return out
    facts_dict = facts.raw.get("facts", {})
    for tax in ("us-gaap", "dei", "ifrs-full", "srt"):
        for concept_block in facts_dict.get(tax, {}).values():
            for unit_rows in concept_block.get("units", {}).values():
                for r in unit_rows:
                    fy = r.get("fy")
                    if fy in target_fys and fy not in out:
                        end_str = r.get("end")
                        if end_str:
                            d = dt.date.fromisoformat(end_str)
                            if d <= end_cap:
                                out[fy] = d
                if len(out) == len(target_fys):
                    return out
    return out


def _values_by_fy(facts: Any, field: str) -> dict[int, float]:
    """Resolve a field via fallback list, return ``{fy: signed_val}``.

    Keying by ``fy`` instead of period-end-date sidesteps the SEC quirk where
    instant concepts (shares, equity) report end-date a few weeks past the
    period anchor concepts (revenue, NI).
    """
    field, concept_used, dps = _resolve_field_concept(facts, field)
    if not dps:
        return {}

    sign_map = _sec_edgar_mod.LINEITEM_CONCEPT_MAP
    sign = sign_map.get(concept_used or "", (None, 1))[1]

    out: dict[int, float] = {}
    for dp in dps:
        if dp.fp != "FY" or dp.fy is None:
            continue
        # Flow concepts: require ~year-long duration. Instant: skip duration check.
        if dp.start is not None and (dp.end - dp.start).days < 350:
            continue
        # Same fy may appear multiple times (10-K + amendments); sec_edgar
        # already dedups by (start, end, fp, fy) so we just take what's here
        out[dp.fy] = dp.val * sign
    return out


def _build_financial_metrics(
    ticker: str,
    facts: Any,
    market_cap: float | None,
    end_date: str,
    limit: int,
) -> list[FinancialMetrics]:
    """Compose the 17 filled fields per FY; leave 22 unfilled fields as None.

    Keys by fiscal year (see ``_build_line_items`` for why fy beats end-date).
    """
    revenue_map = _values_by_fy(facts, "revenue")
    ni_map = _values_by_fy(facts, "net_income")
    op_inc_map = _values_by_fy(facts, "operating_income")
    gross_map = _values_by_fy(facts, "gross_profit")
    ocf_map = _values_by_fy(facts, "operating_cash_flow")
    capex_map = _values_by_fy(facts, "capital_expenditure")
    se_map = _values_by_fy(facts, "stockholders_equity")
    debt_map = _values_by_fy(facts, "total_debt")
    ca_map = _values_by_fy(facts, "current_assets")
    cl_map = _values_by_fy(facts, "current_liabilities")
    ta_map = _values_by_fy(facts, "total_assets")
    sh_map = _values_by_fy(facts, "outstanding_shares")
    eps_map = _values_by_fy(facts, "earnings_per_share")

    # Period anchor: NetIncomeLoss FY → end-date map (every US filer reports it).
    anchor_dps = _sec_edgar_mod._datapoints_for_concept(facts, "NetIncomeLoss", "USD")
    end_cap = dt.date.fromisoformat(end_date)
    fy_to_end: dict[int, dt.date] = {}
    for dp in anchor_dps:
        if (
            dp.fp == "FY"
            and dp.fy is not None
            and dp.start is not None
            and (dp.end - dp.start).days > 350
            and dp.end <= end_cap
        ):
            fy_to_end[dp.fy] = dp.end

    fy_list = sorted(fy_to_end.keys(), reverse=True)[:limit]

    out: list[FinancialMetrics] = []
    for i, fy in enumerate(fy_list):
        end = fy_to_end[fy]
        rev = revenue_map.get(fy)
        ni = ni_map.get(fy)
        op_inc = op_inc_map.get(fy)
        gross = gross_map.get(fy)
        ocf = ocf_map.get(fy)
        capex = capex_map.get(fy)
        se = se_map.get(fy)
        debt = debt_map.get(fy)
        ca = ca_map.get(fy)
        cl = cl_map.get(fy)
        ta = ta_map.get(fy)
        shares = sh_map.get(fy)
        eps = eps_map.get(fy)

        free_cash = computed.fcf(ocf, capex) if ocf is not None and capex is not None else None
        # Growth: compare to next-older fy
        prior_fy = fy_list[i + 1] if i + 1 < len(fy_list) else None
        rev_growth = _safe_growth(rev, revenue_map.get(prior_fy) if prior_fy else None)
        ni_growth = _safe_growth(ni, ni_map.get(prior_fy) if prior_fy else None)

        # NOPAT for ROIC: approximate effective tax rate by ni / pretax_income;
        # fallback to operating_income × (1 - 0.21) if pretax not available.
        # Phase 1 simplification: use operating_income × 0.79 as NOPAT proxy.
        nopat = (op_inc * 0.79) if op_inc is not None else None
        invested_capital = (
            (se + debt) if (se is not None and debt is not None) else None
        )

        kwargs: dict[str, Any] = {
            # Required
            "ticker": ticker.upper(),
            "report_period": end.isoformat(),
            "period": "annual",
            "currency": "USD",
            # 17 filled
            "market_cap": market_cap,
            "price_to_earnings_ratio": _safe_div(market_cap, ni),
            "price_to_book_ratio": _safe_div(market_cap, se),
            "price_to_sales_ratio": _safe_div(market_cap, rev),
            "gross_margin": computed.gross_margin(gross, rev) if gross is not None and rev is not None else None,
            "operating_margin": computed.operating_margin(op_inc, rev) if op_inc is not None and rev is not None else None,
            "net_margin": _safe_div(ni, rev),
            "return_on_equity": computed.roe(ni, se) if ni is not None and se is not None else None,
            "return_on_invested_capital": (
                computed.roic(nopat, invested_capital)
                if nopat is not None and invested_capital is not None else None
            ),
            "asset_turnover": _safe_div(rev, ta),
            "current_ratio": (
                computed.current_ratio(ca, cl) if ca is not None and cl is not None else None
            ),
            "debt_to_equity": (
                computed.debt_to_equity(debt, se) if debt is not None and se is not None else None
            ),
            "revenue_growth": rev_growth,
            "earnings_growth": ni_growth,
            "earnings_per_share": eps,
            "book_value_per_share": _safe_div(se, shares),
            "free_cash_flow_per_share": _safe_div(free_cash, shares),
        }
        # Fill the unfilled with None
        for f in INTENTIONALLY_UNFILLED_FIELDS:
            kwargs[f] = None

        out.append(FinancialMetrics(**kwargs))
    return out


def _safe_div(a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return None
    if b == 0:
        return None
    return a / b


def _safe_growth(current: float | None, prior: float | None) -> float | None:
    """Simple YoY growth = (current - prior) / abs(prior)."""
    if current is None or prior is None or prior == 0:
        return None
    return (current - prior) / abs(prior)
