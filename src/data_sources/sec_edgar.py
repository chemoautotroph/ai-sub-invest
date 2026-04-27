"""SEC EDGAR XBRL adapter.

Public functions (signatures pinned to PROJECT_SPEC.md § 1.2):
    get_cik_for_ticker(ticker)
    get_company_facts(cik)
    get_concept_series(cik, concept, unit="USD")
    get_filings_index(cik, form="10-K")
    get_8k_items(cik, since)

Plus the LineItem-sign-convention helper required by Phase 0 决议 #4:
    lineitem_value_for_concept(concept, raw_val)

Architecture:
    - Pure parsers (`_parse_*`) operate on bytes — easy to unit-test against
      ``tests/unit/fixtures/sec/*.json`` with no HTTP.
    - Thin HTTP fetchers (`_fetch_*`) are the only network surface and are
      mocked in tests via monkeypatch.
    - Public functions orchestrate cache → fetch → parse → cache.

Spec deviation logged in test_extract_concept_quarterly_and_ytd_kept_separate:
    spec § 1.2 edge case 6 says dedup by (end, fp, fy). Real-data probing showed
    XBRL routinely reports the SAME (end, fp, fy) twice within one filing
    (quarter-only row vs YTD row, distinguished by `start`). Using the literal
    spec key would silently drop one. We dedup by (start, end, fp, fy) instead,
    which preserves the quarter/YTD pair and still removes restatement duplicates.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
from typing import Any, Final

import httpx
from pydantic import BaseModel, ConfigDict

from src.data_sources.cache import Cache, CacheTTL


logger = logging.getLogger(__name__)


SEC_TICKER_MAP_URL: Final[str] = "https://www.sec.gov/files/company_tickers.json"
SEC_COMPANYFACTS_URL: Final[str] = (
    "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
)
SEC_SUBMISSIONS_URL: Final[str] = "https://data.sec.gov/submissions/CIK{cik}.json"

_HTTP_TIMEOUT_SEC: Final[float] = 30.0

# Taxonomies searched for a concept, in priority order. us-gaap covers ~99%
# of US filers; dei has entity-level facts; srt is rare; ifrs-full is for
# foreign filers using IFRS.
_TAXONOMY_PRIORITY: Final[tuple[str, ...]] = ("us-gaap", "dei", "ifrs-full", "srt")


# ---------------------------------------------------------------------------
# exceptions
# ---------------------------------------------------------------------------


class SecEdgarError(Exception):
    """Base class for sec_edgar errors."""


class SecEdgarUserAgentMissing(SecEdgarError):
    """Raised when SEC_EDGAR_USER_AGENT env var is unset or blank.

    SEC rate-limits and blocks requests without a UA. Per spec we never fall
    back to a default — making the failure mode obvious is the whole point.
    """


class SecEdgarNotFound(SecEdgarError):
    """Raised when SEC returns 404 or a ticker/concept lookup misses."""


class SecEdgarNetworkError(SecEdgarError):
    """Raised when the SEC host is unreachable.

    Wraps ``httpx.ConnectError`` with a hint about firewall whitelist drift —
    the most common cause when adding a new SEC subdomain or running in a
    locked-down container. Saves debug time vs. a raw connect-error trace.
    """


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class ConceptDataPoint(BaseModel):
    """One row from a XBRL concept's time series, with unit annotation."""

    model_config = ConfigDict(frozen=True)

    start: dt.date | None
    end: dt.date
    val: float
    accn: str
    fy: int | None
    fp: str | None
    form: str
    filed: dt.date
    frame: str | None
    unit: str  # NOT in raw JSON — injected at parse time so callers can branch on per-share vs USD


class FilingMeta(BaseModel):
    model_config = ConfigDict(frozen=True)

    accession: str
    filing_date: dt.date
    report_date: dt.date | None
    form: str
    primary_document: str


class EightKItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    date: dt.date
    items: list[str]
    primary_doc_url: str


class CompanyFacts(BaseModel):
    """Parsed XBRL companyfacts JSON.

    ``raw`` keeps the full nested ``facts`` dict so concept extraction can
    walk the taxonomy without requiring us to model every taxonomy/concept/
    unit upfront (there are thousands of distinct concepts).
    """

    model_config = ConfigDict(frozen=False, arbitrary_types_allowed=True)

    cik: int
    entity_name: str
    raw: dict[str, Any]


# ---------------------------------------------------------------------------
# LineItem sign convention — Phase 0 决议 #4
# ---------------------------------------------------------------------------


# SEC reports cash outflows (capex, dividends paid) as POSITIVE values.
# financialdatasets stored them NEGATIVE on the way out, and persona code
# (e.g. fundamentals: FCF = OCF + capex) relies on that convention.
# Mapping each SEC concept name → (LineItem field, sign multiplier).
LINEITEM_CONCEPT_MAP: Final[dict[str, tuple[str, int]]] = {
    # Capex: SEC reports outflow as positive; flip to negative for LineItem.
    # Both the legacy and modern concepts must carry the convention — see
    # Known Risks #2 (XBRL concept evolution) for why both appear.
    "PaymentsToAcquirePropertyPlantAndEquipment": ("capital_expenditure", -1),
    "PaymentsToAcquireProductiveAssets": ("capital_expenditure", -1),
    "PaymentsOfDividends": ("dividends_and_other_cash_distributions", -1),
    "PaymentsOfDividendsCommonStock": ("dividends_and_other_cash_distributions", -1),
}


def lineitem_value_for_concept(concept: str, raw_val: float) -> tuple[str, float]:
    """Map ``(SEC concept, raw val)`` → ``(LineItem field, signed val)``.

    Raises ``KeyError`` for unmapped concepts — silent fallthrough would
    violate the no-silent-failure rule and produce wrong-sign cash flows.
    """
    field, sign = LINEITEM_CONCEPT_MAP[concept]
    return field, raw_val * sign


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _normalize_cik(raw: str) -> str:
    """Return the zero-padded 10-digit CIK string. Strips ``CIK`` prefix and whitespace."""
    s = str(raw).strip()
    if s.upper().startswith("CIK"):
        s = s[3:]
    return f"{int(s):010d}"


def _parse_iso_date(s: str | None) -> dt.date | None:
    if not s:
        return None
    return dt.date.fromisoformat(s)


def _required_user_agent() -> str:
    ua = os.environ.get("SEC_EDGAR_USER_AGENT", "").strip()
    if not ua:
        raise SecEdgarUserAgentMissing(
            "SEC_EDGAR_USER_AGENT env var is required (format: "
            "'Your Name your-email@example.com'). SEC blocks requests without it."
        )
    return ua


# ---------------------------------------------------------------------------
# pure parsers (HTTP-free; tests pass fixture bytes directly)
# ---------------------------------------------------------------------------


def _parse_ticker_map(body: bytes) -> dict[str, str]:
    """Parse SEC company_tickers.json → ``{TICKER: zero-padded CIK}``."""
    raw = json.loads(body)
    out: dict[str, str] = {}
    for entry in raw.values():
        ticker = str(entry["ticker"]).upper()
        out[ticker] = f"{int(entry['cik_str']):010d}"
    return out


def _parse_companyfacts(body: bytes) -> CompanyFacts:
    raw = json.loads(body)
    return CompanyFacts(
        cik=int(raw["cik"]),
        entity_name=str(raw.get("entityName", "")),
        raw=raw,
    )


def _datapoints_for_concept(
    facts: CompanyFacts, concept: str, unit: str
) -> list[ConceptDataPoint]:
    """Extract ``concept``'s time series in the requested ``unit``.

    Dedup rule: same ``(start, end, fp, fy)`` collapses to the row with the
    latest ``filed`` date (handles 10-K/A restatements and follow-on filings).
    See module docstring for why ``start`` is part of the key.
    """
    facts_dict = facts.raw.get("facts", {})
    rows: list[dict[str, Any]] = []
    for tax in _TAXONOMY_PRIORITY:
        c = facts_dict.get(tax, {}).get(concept)
        if c is None:
            continue
        units_dict = c.get("units", {})
        if unit not in units_dict:
            return []  # concept exists but not in requested unit — explicit miss, no fallback
        rows = list(units_dict[unit])
        break

    if not rows:
        return []

    # Dedup: keep latest filed for each (start, end, fp, fy).
    by_key: dict[tuple[Any, ...], dict[str, Any]] = {}
    for dp in rows:
        key = (dp.get("start"), dp.get("end"), dp.get("fp"), dp.get("fy"))
        existing = by_key.get(key)
        if existing is None or str(dp.get("filed", "")) > str(existing.get("filed", "")):
            by_key[key] = dp

    deduped = sorted(
        by_key.values(),
        key=lambda d: (str(d.get("end") or ""), str(d.get("filed") or "")),
    )
    return [
        ConceptDataPoint(
            start=_parse_iso_date(dp.get("start")),
            end=_parse_iso_date(dp["end"]),  # type: ignore[arg-type]
            val=float(dp["val"]),
            accn=str(dp["accn"]),
            fy=dp.get("fy"),
            fp=dp.get("fp"),
            form=str(dp.get("form", "")),
            filed=_parse_iso_date(dp["filed"]),  # type: ignore[arg-type]
            frame=dp.get("frame"),
            unit=unit,
        )
        for dp in deduped
    ]


# ---------------------------------------------------------------------------
# HTTP fetchers (only network surface; tests monkeypatch these)
# ---------------------------------------------------------------------------


def _http_get(url: str) -> bytes:
    headers = {"User-Agent": _required_user_agent()}
    try:
        with httpx.Client(timeout=_HTTP_TIMEOUT_SEC, headers=headers) as client:
            resp = client.get(url, headers=headers)
            if resp.status_code == 404:
                raise SecEdgarNotFound(f"SEC 404 for {url}")
            resp.raise_for_status()
            return resp.content
    except httpx.ConnectError as e:
        raise SecEdgarNetworkError(
            f"Cannot reach {url}. If new SEC domain, may need firewall "
            f"whitelist update. Original: {e}"
        ) from e


def _fetch_ticker_map() -> bytes:
    return _http_get(SEC_TICKER_MAP_URL)


def _fetch_companyfacts(cik_padded: str) -> bytes:
    return _http_get(SEC_COMPANYFACTS_URL.format(cik=cik_padded))


def _fetch_submissions(cik_padded: str) -> bytes:
    return _http_get(SEC_SUBMISSIONS_URL.format(cik=cik_padded))


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------


def get_cik_for_ticker(ticker: str, *, cache: Cache | None = None) -> str:
    cache = cache or Cache()
    body = cache.get("sec_edgar", "cik_mapping", "_global_")
    if body is None:
        body = _fetch_ticker_map()
        cache.set(
            "sec_edgar", "cik_mapping", "_global_",
            body, CacheTTL.SEC_EDGAR_CIK_MAPPING,
        )
    mapping = _parse_ticker_map(body)
    target = ticker.strip().upper()
    if target not in mapping:
        raise SecEdgarNotFound(f"ticker {ticker!r} not found in SEC ticker map")
    return mapping[target]


def get_company_facts(cik: str, *, cache: Cache | None = None) -> CompanyFacts:
    cache = cache or Cache()
    cik_padded = _normalize_cik(cik)
    body = cache.get("sec_edgar", "company_facts", cik_padded)
    if body is None:
        body = _fetch_companyfacts(cik_padded)
        cache.set(
            "sec_edgar", "company_facts", cik_padded,
            body, CacheTTL.SEC_EDGAR_COMPANY_FACTS,
        )
    return _parse_companyfacts(body)


def get_concept_series(
    cik: str,
    concept: str,
    unit: str = "USD",
    *,
    cache: Cache | None = None,
) -> list[ConceptDataPoint]:
    facts = get_company_facts(cik, cache=cache)
    return _datapoints_for_concept(facts, concept, unit)


def _get_submissions_dict(cik: str, *, cache: Cache | None = None) -> dict[str, Any]:
    """Cached fetch+parse of ``submissions/CIK*.json``.

    TTL reuses ``SEC_EDGAR_COMPANY_FACTS`` (1d) — both endpoints are SEC
    daily-refreshed JSON; no need for a dedicated constant until we observe
    different freshness behavior in production. 1d TTL adequate for
    daily/weekly batch use; reduce to 1h if intraday 8-K event monitoring
    is added.
    """
    cache = cache or Cache()
    cik_padded = _normalize_cik(cik)
    body = cache.get("sec_edgar", "submissions", cik_padded)
    if body is None:
        body = _fetch_submissions(cik_padded)
        cache.set(
            "sec_edgar", "submissions", cik_padded,
            body, CacheTTL.SEC_EDGAR_COMPANY_FACTS,
        )
    return json.loads(body)  # type: ignore[no-any-return]


def get_filings_index(
    cik: str,
    form: str | None = "10-K",
    *,
    cache: Cache | None = None,
) -> list[FilingMeta]:
    sub = _get_submissions_dict(cik, cache=cache)
    recent = sub.get("filings", {}).get("recent", {})
    n = len(recent.get("accessionNumber", []))
    out: list[FilingMeta] = []
    forms = recent.get("form", [])
    accs = recent.get("accessionNumber", [])
    fdates = recent.get("filingDate", [])
    rdates = recent.get("reportDate", [""] * n)
    pdocs = recent.get("primaryDocument", [""] * n)
    for i in range(n):
        f = forms[i]
        if form is not None and f != form:
            continue
        out.append(
            FilingMeta(
                accession=accs[i],
                filing_date=_parse_iso_date(fdates[i]),  # type: ignore[arg-type]
                report_date=_parse_iso_date(rdates[i]) if rdates[i] else None,
                form=f,
                primary_document=pdocs[i],
            )
        )
    return out


def get_8k_items(
    cik: str,
    since: dt.date,
    *,
    cache: Cache | None = None,
) -> list[EightKItem]:
    sub = _get_submissions_dict(cik, cache=cache)
    recent = sub.get("filings", {}).get("recent", {})
    n = len(recent.get("accessionNumber", []))
    cik_int = int(_normalize_cik(cik))
    forms = recent.get("form", [])
    accs = recent.get("accessionNumber", [])
    fdates = recent.get("filingDate", [])
    items_col = recent.get("items", [""] * n)
    pdocs = recent.get("primaryDocument", [""] * n)
    out: list[EightKItem] = []
    for i in range(n):
        if forms[i] != "8-K":
            continue
        filed = _parse_iso_date(fdates[i])
        assert filed is not None  # filingDate is mandatory in SEC submissions schema
        if filed < since:
            continue
        items_csv = items_col[i] or ""
        items = [s.strip() for s in items_csv.split(",") if s.strip()]
        accn_clean = accs[i].replace("-", "")
        url = (
            f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{accn_clean}/{pdocs[i]}"
        )
        out.append(EightKItem(date=filed, items=items, primary_doc_url=url))
    return out
