"""Unit tests for src/data_sources/sec_edgar.py.

覆盖 PROJECT_SPEC.md § 1.2 全部要求:
  - 6 个 XBRL edge case (multi-unit, restatement, FY≠CY, 缺季度, 单位换算, dedup)
  - capex / dividends 符号约定 (SEC 正数 → LineItem 负数)
  - 缺 SEC_EDGAR_USER_AGENT 抛异常
  - 5 个公开函数 happy path + 错误分支

Spec 偏差(在数据探查时发现并 lock 进 test_*_quarterly_and_ytd_kept_separate):
spec § 1.2 第 6 条说 dedup key = (end, fp, fy),但真实 NVDA 数据里同一份 10-Q
会用同一 (end, fp, fy) 报两行(start 不同):一行季度、一行 YTD,val 完全不同。
literal 按 spec 会 silently drop 一行。本测试套件用 (start, end, fp, fy)
作为 dedup key。
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from src.data_sources.cache import Cache
from src.data_sources.sec_edgar import (
    CompanyFacts,
    ConceptDataPoint,
    EightKItem,
    FilingMeta,
    SecEdgarNetworkError,
    SecEdgarNotFound,
    SecEdgarUserAgentMissing,
    _datapoints_for_concept,
    _normalize_cik,
    _parse_companyfacts,
    _parse_ticker_map,
    get_8k_items,
    get_cik_for_ticker,
    get_company_facts,
    get_concept_series,
    get_filings_index,
    lineitem_value_for_concept,
)


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "sec"


def _read(name: str) -> bytes:
    return (FIXTURE_DIR / name).read_bytes()


@pytest.fixture(autouse=True)
def _set_user_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEC_EDGAR_USER_AGENT", "ai-sub-invest test@example.com")


@pytest.fixture
def cache(tmp_path: Path) -> Cache:
    return Cache(tmp_path / "cache.db")


@pytest.fixture
def nvda_facts() -> CompanyFacts:
    return _parse_companyfacts(_read("NVDA_companyfacts.json"))


def _synthetic_facts(concept: str, units: dict[str, list[dict[str, Any]]]) -> CompanyFacts:
    """Build a minimal CompanyFacts with controlled datapoints for edge-case tests."""
    body = json.dumps({
        "cik": 999999,
        "entityName": "Synthetic Co",
        "facts": {"us-gaap": {concept: {"label": concept, "units": units}}},
    }).encode()
    return _parse_companyfacts(body)


# ---------------------------------------------------------------------------
# parsing primitives
# ---------------------------------------------------------------------------


def test_parse_companyfacts_extracts_cik_and_entity_name(nvda_facts: CompanyFacts) -> None:
    assert nvda_facts.cik == 1045810
    assert nvda_facts.entity_name == "NVIDIA CORP"
    assert "us-gaap" in nvda_facts.raw["facts"]


def test_parse_ticker_map_returns_uppercase_ticker_to_cik() -> None:
    mapping = _parse_ticker_map(_read("company_tickers.json"))
    assert mapping["NVDA"] == "0001045810"
    assert mapping["AAPL"] == "0000320193"


# ---------------------------------------------------------------------------
# CIK normalization
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("1045810", "0001045810"),
        ("0001045810", "0001045810"),
        ("CIK0001045810", "0001045810"),
        ("CIK1045810", "0001045810"),
        ("  1045810  ", "0001045810"),
    ],
)
def test_normalize_cik_zero_pads_and_strips_prefix(raw: str, expected: str) -> None:
    assert _normalize_cik(raw) == expected


# ---------------------------------------------------------------------------
# get_cik_for_ticker
# ---------------------------------------------------------------------------


def test_get_cik_for_ticker_happy_path(
    cache: Cache, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "src.data_sources.sec_edgar._fetch_ticker_map",
        lambda: _read("company_tickers.json"),
    )
    assert get_cik_for_ticker("NVDA", cache=cache) == "0001045810"
    assert get_cik_for_ticker("aapl", cache=cache) == "0000320193"  # case-insensitive


def test_get_cik_for_ticker_unknown_raises(
    cache: Cache, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "src.data_sources.sec_edgar._fetch_ticker_map",
        lambda: _read("company_tickers.json"),
    )
    with pytest.raises(SecEdgarNotFound, match="FAKE_TICKER"):
        get_cik_for_ticker("FAKE_TICKER", cache=cache)


def test_get_cik_for_ticker_uses_cache_on_second_call(
    cache: Cache, monkeypatch: pytest.MonkeyPatch
) -> None:
    """30d cache TTL: second lookup must not refetch."""
    calls = [0]

    def fake_fetch() -> bytes:
        calls[0] += 1
        return _read("company_tickers.json")

    monkeypatch.setattr("src.data_sources.sec_edgar._fetch_ticker_map", fake_fetch)
    get_cik_for_ticker("NVDA", cache=cache)
    get_cik_for_ticker("AAPL", cache=cache)  # second call, cached map
    assert calls[0] == 1, f"expected 1 fetch, got {calls[0]}"


# ---------------------------------------------------------------------------
# XBRL concept extraction — 6 spec edge cases + sanity
# ---------------------------------------------------------------------------


def test_extract_concept_happy_path(nvda_facts: CompanyFacts) -> None:
    series = _datapoints_for_concept(nvda_facts, "NetIncomeLoss", "USD")
    assert len(series) > 50, "NVDA has 18+ years of NetIncomeLoss filings"
    for dp in series:
        assert isinstance(dp, ConceptDataPoint)
        assert dp.unit == "USD"


def test_extract_concept_unknown_returns_empty(nvda_facts: CompanyFacts) -> None:
    assert _datapoints_for_concept(nvda_facts, "NoSuchConcept_Made_Up", "USD") == []


def test_extract_concept_unknown_unit_returns_empty(nvda_facts: CompanyFacts) -> None:
    """Spec edge case 1: filtering by unit must be strict, not silently fall back."""
    # NetIncomeLoss in NVDA is USD-only; querying USD/shares must yield empty.
    assert _datapoints_for_concept(nvda_facts, "NetIncomeLoss", "USD/shares") == []


def test_extract_concept_filters_by_unit_when_multiple_present() -> None:
    """Spec edge case 1: same concept reported in two units (USD and USD/shares).

    Synthetic data: a fictional dual-unit concept. The function must return
    only the requested unit's rows, never silently merge or pick first.
    """
    facts = _synthetic_facts(
        "DualUnitConcept",
        {
            "USD": [{
                "start": "2020-01-01", "end": "2020-12-31", "val": 1_000_000,
                "accn": "1", "fy": 2020, "fp": "FY", "form": "10-K", "filed": "2021-02-15",
            }],
            "USD/shares": [{
                "start": "2020-01-01", "end": "2020-12-31", "val": 5.25,
                "accn": "1", "fy": 2020, "fp": "FY", "form": "10-K", "filed": "2021-02-15",
            }],
        },
    )
    usd = _datapoints_for_concept(facts, "DualUnitConcept", "USD")
    pershare = _datapoints_for_concept(facts, "DualUnitConcept", "USD/shares")
    assert len(usd) == 1 and usd[0].val == 1_000_000 and usd[0].unit == "USD"
    assert len(pershare) == 1 and pershare[0].val == 5.25 and pershare[0].unit == "USD/shares"


def test_extract_concept_dedup_restatement_keeps_latest_filed() -> None:
    """Spec edge case 2 & 6: same period filed twice → keep most recent filed."""
    facts = _synthetic_facts(
        "Revenues",
        {"USD": [
            {"start": "2020-01-01", "end": "2020-03-31", "val": 100, "accn": "A",
             "fy": 2020, "fp": "Q1", "form": "10-Q", "filed": "2020-04-30"},
            {"start": "2020-01-01", "end": "2020-03-31", "val": 105, "accn": "B",
             "fy": 2020, "fp": "Q1", "form": "10-Q/A", "filed": "2020-08-15"},  # restated
        ]},
    )
    series = _datapoints_for_concept(facts, "Revenues", "USD")
    assert len(series) == 1
    assert series[0].val == 105
    assert series[0].filed == dt.date(2020, 8, 15)
    assert series[0].accn == "B"


def test_extract_concept_quarterly_and_ytd_kept_separate() -> None:
    """Spec amendment: dedup key must include `start`, not just (end, fp, fy).

    Why: a 10-Q reports the SAME (end, fp, fy) twice — once for quarter only
    (start = quarter start) and once for YTD (start = fiscal year start),
    with different vals. Literal spec dedup would drop one.

    Real-data shape from NVDA fixture:
        Q2 FY2009: start=2008-01-25 end=2008-07-27 val=+55,876,000  (YTD)
        Q2 FY2009: start=2008-04-27 end=2008-07-27 val=-120,929,000 (quarter)
    """
    facts = _synthetic_facts(
        "NetIncomeLoss",
        {"USD": [
            {"start": "2020-01-01", "end": "2020-06-30", "val": 200, "accn": "X",
             "fy": 2020, "fp": "Q2", "form": "10-Q", "filed": "2020-07-30"},  # YTD
            {"start": "2020-04-01", "end": "2020-06-30", "val": 80, "accn": "X",
             "fy": 2020, "fp": "Q2", "form": "10-Q", "filed": "2020-07-30"},  # quarter
        ]},
    )
    series = _datapoints_for_concept(facts, "NetIncomeLoss", "USD")
    assert len(series) == 2, "quarter and YTD rows must coexist"
    vals = {dp.val for dp in series}
    assert vals == {200.0, 80.0}


def test_extract_concept_fiscal_year_uses_end_field_not_filed(
    nvda_facts: CompanyFacts,
) -> None:
    """Spec edge case 3: NVDA FY ends late January, not December.

    Subtlety discovered while writing this test: SEC's ``fp`` field reflects
    the ENCLOSING report's fiscal period, not the row's coverage. A 10-K
    (fp="FY") routinely includes comparative quarterly rows with fp="FY"
    but mid-year ``end``. To isolate rows that actually span a full fiscal
    year, filter by duration ≥ 350 days as well.
    """
    series = _datapoints_for_concept(nvda_facts, "NetIncomeLoss", "USD")
    fy_full_year = [
        dp
        for dp in series
        if dp.fp == "FY"
        and dp.start is not None
        and (dp.end - dp.start).days > 350
    ]
    assert fy_full_year, "expected at least one full-year FY datapoint"

    # NVDA's fiscal year ends in late Jan / early Feb consistently.
    fy_end_months = {dp.end.month for dp in fy_full_year}
    assert fy_end_months <= {1, 2}, (
        f"NVDA full-year FY rows should end Jan/Feb, got months {fy_end_months}"
    )
    # filed dates are Feb-Apr (a few weeks after FY close) — proves end != filed
    for dp in fy_full_year[:5]:
        assert dp.filed.month in {2, 3, 4}, (
            f"unexpected filed month {dp.filed.month} for end={dp.end}"
        )
        assert dp.end != dp.filed


def test_extract_concept_no_zero_fill_for_missing_quarters() -> None:
    """Spec edge case 4: gaps in reporting must not be padded with synthetic 0s."""
    facts = _synthetic_facts(
        "Revenues",
        {"USD": [
            {"start": "2020-01-01", "end": "2020-03-31", "val": 100, "accn": "1",
             "fy": 2020, "fp": "Q1", "form": "10-Q", "filed": "2020-04-30"},
            # Q2 missing
            {"start": "2020-07-01", "end": "2020-09-30", "val": 300, "accn": "3",
             "fy": 2020, "fp": "Q3", "form": "10-Q", "filed": "2020-10-30"},
        ]},
    )
    series = _datapoints_for_concept(facts, "Revenues", "USD")
    assert len(series) == 2
    fps = [dp.fp for dp in series]
    assert "Q2" not in fps, "Q2 must not be synthesized"
    assert {dp.val for dp in series} == {100.0, 300.0}


def test_extract_concept_per_share_unit_kept_as_is(nvda_facts: CompanyFacts) -> None:
    """Spec edge case 5: USD/shares concept is per-share — caller must not
    multiply by shares. Function MUST keep `unit` field intact and not silently
    relabel to USD; values stay in EPS range, not millions.
    """
    eps = _datapoints_for_concept(nvda_facts, "EarningsPerShareBasic", "USD/shares")
    assert eps, "NVDA reports EPS"
    for dp in eps:
        assert dp.unit == "USD/shares"
        # Sanity: EPS values fit in [-100, 100] dollars, never billions
        assert -100.0 < dp.val < 100.0, f"EPS out of range: {dp.val}"


# ---------------------------------------------------------------------------
# get_company_facts orchestration: cache + http
# ---------------------------------------------------------------------------


def test_get_company_facts_caches_response(
    cache: Cache, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = [0]

    def fake_fetch(cik_padded: str) -> bytes:
        calls[0] += 1
        return _read("NVDA_companyfacts.json")

    monkeypatch.setattr("src.data_sources.sec_edgar._fetch_companyfacts", fake_fetch)
    f1 = get_company_facts("1045810", cache=cache)
    f2 = get_company_facts("1045810", cache=cache)
    assert f1.cik == f2.cik == 1045810
    assert calls[0] == 1, "second call must hit cache, not refetch"


def test_get_concept_series_routes_through_company_facts(
    cache: Cache, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "src.data_sources.sec_edgar._fetch_companyfacts",
        lambda cik: _read("NVDA_companyfacts.json"),
    )
    series = get_concept_series("1045810", "NetIncomeLoss", "USD", cache=cache)
    assert len(series) > 50
    assert all(dp.unit == "USD" for dp in series)


# ---------------------------------------------------------------------------
# get_filings_index
# ---------------------------------------------------------------------------


def test_get_filings_index_filters_by_form(
    cache: Cache, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "src.data_sources.sec_edgar._fetch_submissions",
        lambda cik: _read("NVDA_submissions.json"),
    )
    ten_ks = get_filings_index("1045810", form="10-K", cache=cache)
    assert ten_ks, "NVDA has 10-K filings in last 1000 records"
    assert all(f.form == "10-K" for f in ten_ks)
    for f in ten_ks:
        assert isinstance(f.filing_date, dt.date)
        assert isinstance(f.accession, str)


def test_get_filings_index_no_filter_returns_mixed_forms(
    cache: Cache, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "src.data_sources.sec_edgar._fetch_submissions",
        lambda cik: _read("NVDA_submissions.json"),
    )
    everything = get_filings_index("1045810", form=None, cache=cache)
    forms = {f.form for f in everything}
    assert len(forms) > 3, f"expected mixed forms, got {forms}"


# ---------------------------------------------------------------------------
# get_8k_items
# ---------------------------------------------------------------------------


def test_get_8k_items_parses_items_csv_and_filters_since(
    cache: Cache, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "src.data_sources.sec_edgar._fetch_submissions",
        lambda cik: _read("NVDA_submissions.json"),
    )
    since = dt.date(2025, 1, 1)
    items = get_8k_items("1045810", since=since, cache=cache)
    assert items, "NVDA has 8-K filings in last 1000 records"
    for it in items:
        assert it.date >= since
        # NVDA 8-K items are codes like "5.02", "9.01", "2.02"
        for code in it.items:
            assert "." in code, f"bad item code {code!r}"
        assert it.primary_doc_url.startswith("https://www.sec.gov/Archives/edgar/data/1045810/")


def test_get_8k_items_returns_empty_when_since_is_future(
    cache: Cache, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "src.data_sources.sec_edgar._fetch_submissions",
        lambda cik: _read("NVDA_submissions.json"),
    )
    items = get_8k_items("1045810", since=dt.date(2099, 1, 1), cache=cache)
    assert items == []


# ---------------------------------------------------------------------------
# LineItem sign convention — Phase 0 决议第 4 条
# ---------------------------------------------------------------------------


def test_capex_sign_convention(nvda_facts: CompanyFacts) -> None:
    """Spec Phase 0 决议 #4: SEC 报正数 → LineItem 必须负数.

    Failure mode if broken: persona 代码 (e.g. fundamentals) 算 FCF =
    OCF + capex,会变成两数相加而非相减,FCF 严重错误。
    """
    capex_series = _datapoints_for_concept(
        nvda_facts, "PaymentsToAcquirePropertyPlantAndEquipment", "USD"
    )
    assert capex_series, "NVDA has CapEx data"
    raw_sample = capex_series[0]
    assert raw_sample.val > 0, "raw SEC value must be positive (otherwise this test is moot)"

    field, signed_val = lineitem_value_for_concept(
        "PaymentsToAcquirePropertyPlantAndEquipment", raw_sample.val
    )
    assert field == "capital_expenditure"
    assert signed_val < 0
    assert signed_val == -raw_sample.val


def test_dividends_sign_convention() -> None:
    """SEC concept PaymentsOfDividends (NVDA-style) → negative LineItem value."""
    field, signed_val = lineitem_value_for_concept("PaymentsOfDividends", 1_500_000_000.0)
    assert field == "dividends_and_other_cash_distributions"
    assert signed_val == -1_500_000_000.0


def test_dividends_alt_concept_name_also_supported() -> None:
    """SEC sometimes uses PaymentsOfDividendsCommonStock (AAPL-style)."""
    field, signed_val = lineitem_value_for_concept(
        "PaymentsOfDividendsCommonStock", 14_000_000_000.0
    )
    assert field == "dividends_and_other_cash_distributions"
    assert signed_val == -14_000_000_000.0


def test_lineitem_unknown_concept_raises() -> None:
    """Unknown SEC concept must NOT silently default — caller's contract violated."""
    with pytest.raises(KeyError):
        lineitem_value_for_concept("MadeUpConcept", 100.0)


# ---------------------------------------------------------------------------
# User-Agent enforcement (spec § 1.2: SEC 没 UA 给 403,不要 fallback)
# ---------------------------------------------------------------------------


def test_user_agent_required_raises_when_missing(
    monkeypatch: pytest.MonkeyPatch, cache: Cache
) -> None:
    monkeypatch.delenv("SEC_EDGAR_USER_AGENT", raising=False)
    # _fetch_ticker_map is the entry point that asks for UA
    with pytest.raises(SecEdgarUserAgentMissing):
        # Force a real fetch path by clearing cache and not mocking _fetch_*
        get_cik_for_ticker("NVDA", cache=cache)


def test_user_agent_required_blank_string_treated_as_missing(
    monkeypatch: pytest.MonkeyPatch, cache: Cache
) -> None:
    monkeypatch.setenv("SEC_EDGAR_USER_AGENT", "   ")  # whitespace-only
    with pytest.raises(SecEdgarUserAgentMissing):
        get_cik_for_ticker("NVDA", cache=cache)


# ---------------------------------------------------------------------------
# HTTP error mapping (sanity)
# ---------------------------------------------------------------------------


def test_http_404_maps_to_secedgar_not_found(
    monkeypatch: pytest.MonkeyPatch, cache: Cache
) -> None:
    """SEC 404 (e.g. invalid CIK) must surface as SecEdgarNotFound, not raw HTTPStatusError."""
    def fake_get(self: Any, url: str, **kw: Any) -> httpx.Response:
        return httpx.Response(404, request=httpx.Request("GET", url))

    monkeypatch.setattr("httpx.Client.get", fake_get)
    with pytest.raises(SecEdgarNotFound):
        get_company_facts("9999999999", cache=cache)


# ---------------------------------------------------------------------------
# Pydantic model immutability (cheap regression guard)
# ---------------------------------------------------------------------------


def test_concept_datapoint_is_frozen() -> None:
    dp = ConceptDataPoint(
        start=dt.date(2020, 1, 1), end=dt.date(2020, 12, 31), val=100.0,
        accn="A", fy=2020, fp="FY", form="10-K", filed=dt.date(2021, 2, 15),
        frame=None, unit="USD",
    )
    with pytest.raises((TypeError, ValueError)):
        dp.val = 999.0  # type: ignore[misc]


def test_filing_meta_is_frozen() -> None:
    fm = FilingMeta(
        accession="0001045810-26-000024",
        filing_date=dt.date(2026, 3, 6),
        report_date=dt.date(2026, 3, 2),
        form="8-K",
        primary_document="nvda-20260302.htm",
    )
    with pytest.raises((TypeError, ValueError)):
        fm.form = "10-K"  # type: ignore[misc]


def test_eight_k_item_is_frozen() -> None:
    it = EightKItem(
        date=dt.date(2026, 3, 6),
        items=["5.02", "9.01"],
        primary_doc_url="https://www.sec.gov/Archives/edgar/data/1045810/000104581026000024/nvda-20260302.htm",
    )
    with pytest.raises((TypeError, ValueError)):
        it.date = dt.date(2025, 1, 1)  # type: ignore[misc]


# ---------------------------------------------------------------------------
# small helpers — coverage for branches not exercised by fixture-driven tests
# ---------------------------------------------------------------------------


def test_parse_iso_date_handles_none_and_empty() -> None:
    from src.data_sources.sec_edgar import _parse_iso_date

    assert _parse_iso_date(None) is None
    assert _parse_iso_date("") is None
    assert _parse_iso_date("2020-01-15") == dt.date(2020, 1, 15)


def test_fetch_submissions_builds_correct_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """_fetch_submissions: pads CIK and hits the right SEC submissions URL."""
    from src.data_sources.sec_edgar import _fetch_submissions

    seen: list[str] = []

    def fake_http_get(url: str) -> bytes:
        seen.append(url)
        return b"{}"

    monkeypatch.setattr("src.data_sources.sec_edgar._http_get", fake_http_get)
    _fetch_submissions("0001045810")
    assert seen == ["https://data.sec.gov/submissions/CIK0001045810.json"]


def test_http_get_success_path_returns_response_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.data_sources.sec_edgar import _http_get

    def fake_get(self: Any, url: str, **kw: Any) -> httpx.Response:
        return httpx.Response(200, content=b"payload-bytes", request=httpx.Request("GET", url))

    monkeypatch.setattr("httpx.Client.get", fake_get)
    assert _http_get("https://www.sec.gov/anything") == b"payload-bytes"


def test_http_connect_error_wrapped_with_helpful_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Network unreachable → SecEdgarNetworkError with firewall hint.

    Why: this exact failure already cost us one round-trip in Phase 1.2
    (when www.sec.gov / data.sec.gov weren't on the firewall whitelist).
    A raw ``httpx.ConnectError`` doesn't suggest "check your firewall";
    the wrapper does, saving the next person 10 minutes of confusion.
    """
    from src.data_sources.sec_edgar import _http_get

    def fake_get(self: Any, url: str, **kw: Any) -> httpx.Response:
        raise httpx.ConnectError("[Errno 101] Network is unreachable")

    monkeypatch.setattr("httpx.Client.get", fake_get)
    with pytest.raises(SecEdgarNetworkError, match="firewall"):
        _http_get("https://data.sec.gov/api/xbrl/companyfacts/CIK0001045810.json")
