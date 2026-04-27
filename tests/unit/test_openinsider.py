"""Unit tests for src/data_sources/openinsider.py.

覆盖 PROJECT_SPEC.md § 1.4 的 4 个 edge case + 3 个 helper + happy path.

Fixtures 在 tests/unit/fixtures/openinsider/:
  NVDA_screener.html         — 真实 100 行(全 S - Sale)
  VTI_screener.html          — ETF, openinsider 不返 tinytable; 真实 zero 案例
  broken_NVDA_screener.html  — 手工破坏(table class 改名), schema drift
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import pytest

from src.data.models import InsiderTrade
from src.data_sources.cache import Cache
from src.data_sources.openinsider import (
    OpenInsiderSchemaError,
    TRANSACTION_CODE_LABELS,
    _extract_transaction_code,
    _is_director,
    _parse_amount,
    _parse_int_with_commas,
    _parse_screener_html,
    get_insider_trades,
)


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "openinsider"


def _read(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8", errors="replace")


@pytest.fixture
def cache(tmp_path: Path) -> Cache:
    return Cache(tmp_path / "cache.db")


# ---------------------------------------------------------------------------
# spec edge case 1 — unknown / no-data ticker returns empty list
# ---------------------------------------------------------------------------


def test_unknown_ticker_returns_empty_list(monkeypatch: pytest.MonkeyPatch, cache: Cache) -> None:
    """VTI fixture: openinsider returns a page WITHOUT tinytable when no
    insider data is tracked. Parser must yield empty list, not raise.

    This is the canonical empty-schema case (spec § Common Conventions).
    Caller can do ``if not trades:`` without first checking for a list.
    """
    monkeypatch.setattr(
        "src.data_sources.openinsider._fetch_screener_html",
        lambda ticker: _read("VTI_screener.html").encode("utf-8"),
    )
    trades = get_insider_trades("VTI", cache=cache)
    assert trades == []
    assert isinstance(trades, list)


def test_empty_tbody_also_returns_empty_list() -> None:
    """Other empty path: tinytable present but tbody has 0 rows.

    Some real tickers have the table rendered but no recent trades; that
    path must not crash differently from the no-tinytable case.
    """
    html = """
    <html><body>
      <table class="tinytable">
        <thead><tr>
          <th>X</th><th>Filing Date</th><th>Trade Date</th><th>Ticker</th>
          <th>Insider Name</th><th>Title</th><th>Trade Type</th><th>Price</th>
          <th>Qty</th><th>Owned</th><th>ΔOwn</th><th>Value</th>
          <th>1d</th><th>1w</th><th>1m</th><th>6m</th>
        </tr></thead>
        <tbody></tbody>
      </table>
    </body></html>
    """
    assert _parse_screener_html(html) == []


# ---------------------------------------------------------------------------
# spec edge case 2 — schema drift raises OpenInsiderSchemaError
# ---------------------------------------------------------------------------


def test_broken_fixture_actually_differs_from_clean() -> None:
    """Early warning: if openinsider adds attributes that make the
    `class="tinytable"` substring no longer match the fetcher's corruption
    regex, ``broken_NVDA_screener.html`` would silently end up identical
    to the clean ``NVDA_screener.html`` — and the schema-drift test would
    pass for the wrong reason (parsing succeeds because nothing was broken).

    This guard fails loudly on the *next* fetcher re-run that misses the
    corruption, before the bug propagates into trusted-but-vacuous coverage.
    """
    clean = (FIXTURE_DIR / "NVDA_screener.html").read_text(encoding="utf-8", errors="replace")
    broken = (FIXTURE_DIR / "broken_NVDA_screener.html").read_text(encoding="utf-8", errors="replace")
    assert broken != clean, "broken fixture must differ from clean — fetcher corruption did not fire"
    assert 'class="tinytable"' not in broken, (
        "broken fixture still contains literal class=\"tinytable\"; "
        "the schema-drift fetcher step likely failed to match the data table "
        "(check scripts/fetch_openinsider_fixtures.py write_broken_fixture)"
    )


def test_schema_drift_raises_OpenInsiderSchemaError(
    monkeypatch: pytest.MonkeyPatch, cache: Cache
) -> None:
    """Hand-corrupted NVDA fixture renames ``table class="tinytable"`` to
    ``table class="formerly-tinytable"``. Parser refuses to silently fall
    back to "no tinytable → empty list" — that would mask real upstream
    breakage. Instead it raises ``OpenInsiderSchemaError``.

    Distinction from VTI case: VTI's HTML has ``no <table class="tinytable">
    anywhere``. Broken NVDA still has ``<tr>`` rows that LOOK like data but
    aren't in the right container — the parser must detect this difference.
    """
    monkeypatch.setattr(
        "src.data_sources.openinsider._fetch_screener_html",
        lambda ticker: _read("broken_NVDA_screener.html").encode("utf-8"),
    )
    with pytest.raises(OpenInsiderSchemaError):
        get_insider_trades("NVDA", cache=cache)


def test_schema_drift_wrong_column_count_raises() -> None:
    """tinytable present with wrong column count → schema error, not silent corruption."""
    html = """
    <html><body><table class="tinytable">
      <thead><tr><th>OnlyTwo</th><th>Cols</th></tr></thead>
      <tbody><tr><td>foo</td><td>bar</td></tr></tbody>
    </table></body></html>
    """
    with pytest.raises(OpenInsiderSchemaError, match="column"):
        _parse_screener_html(html)


def test_schema_drift_correct_count_but_renamed_headers_raises() -> None:
    """tinytable present, 16 headers (count OK), but header NAMES drifted →
    raise with "header drift" message. Distinguishes from column-count case
    so debugging is faster — operators know which kind of upstream change occurred.
    """
    bogus_headers = "".join(f"<th>Bogus{i}</th>" for i in range(16))
    bogus_cells = "".join("<td>x</td>" for _ in range(16))
    html = f"""
    <html><body><table class="tinytable">
      <thead><tr>{bogus_headers}</tr></thead>
      <tbody><tr>{bogus_cells}</tr></tbody>
    </table></body></html>
    """
    with pytest.raises(OpenInsiderSchemaError, match="header drift"):
        _parse_screener_html(html)


# ---------------------------------------------------------------------------
# spec edge case 3 — amount parsing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        # Real openinsider formats from NVDA fixture
        ("$173.68", 173.68),
        ("$1,234,567.89", 1_234_567.89),
        ("-$38,502,524", -38_502_524.0),
        ("-$3,357,549", -3_357_549.0),
        # Boundaries
        ("$0", 0.0),
        ("$0.00", 0.0),
        ("-$0.01", -0.01),
        # Defensive: scale-suffix support (other openinsider pages do use these)
        ("$1.2M", 1_200_000.0),
        ("$1.5K", 1_500.0),
        ("$3B", 3_000_000_000.0),
        ("-$2.5M", -2_500_000.0),
        # Empty / missing
        ("", None),
        (None, None),
        ("   ", None),
    ],
    ids=lambda x: repr(x),
)
def test_amount_parsing_handles_dollar_sign_and_commas(raw: str | None, expected: float | None) -> None:
    """Spec edge case 3 + defensive K/M/B suffix support.

    Why parametrize: the failure mode for amount parsing is wrong sign or
    misplaced decimal — both silent. Pinning each format with an explicit
    expected value makes regressions impossible to miss.
    """
    assert _parse_amount(raw) == expected


def test_amount_parsing_returns_none_on_only_commas() -> None:
    """Edge: regex matches ``[0-9,]+`` but after stripping commas the numeric
    core is empty → float() ValueError → return None (no raise out of helper)."""
    assert _parse_amount("$,,,") is None


def test_parse_int_returns_none_on_only_commas() -> None:
    assert _parse_int_with_commas(",,,") is None


def test_parse_int_returns_none_on_non_numeric_text() -> None:
    """Non-numeric input survives strip+replace and fails int() — go via
    the except ValueError branch (returns None + warning), not raise."""
    assert _parse_int_with_commas("abc") is None
    assert _parse_int_with_commas("1.5") is None  # int() rejects decimals


def test_amount_parsing_returns_none_on_garbage_no_raise(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Unparseable garbage → None + log warning, not exception.

    Reasoning: openinsider's Value column is consistent in practice but a
    layout bug elsewhere on the row could leave junk in cells[11]. Returning
    None localises the damage to one row instead of crashing the whole page.
    The warning log keeps the failure visible (no silent failure rule).
    """
    import logging
    with caplog.at_level(logging.WARNING, logger="src.data_sources.openinsider"):
        assert _parse_amount("$abc.xy") is None
    # Exactly one warning logged so we notice in production
    assert any("$abc.xy" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# spec edge case 4 — transaction codes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw_cell,expected_code",
    [
        # Codes called out in spec
        ("P - Purchase", "P"),
        ("S - Sale", "S"),
        ("A - Award", "A"),
        ("M - Option Exercise", "M"),
        ("G - Gift", "G"),
        ("D - Sale-to-Issuer", "D"),
        # Common adjacent codes (Form 4 alphabet)
        ("F - Tax Withholding", "F"),
        ("X - Option Exercise (in-the-money)", "X"),
        ("C - Conversion", "C"),
        # Edge: lowercase letter in cell (defensive)
        ("p - purchase", "P"),
        # Edge: just a code letter, no description
        ("S", "S"),
        # Edge: empty
        ("", None),
        ("   ", None),
    ],
)
def test_transaction_codes_mapped_correctly(raw_cell: str, expected_code: str | None) -> None:
    """Spec edge case 4: P/S/A/M/G/D plus F/X/C. Code letter extracted from
    the standard openinsider ``"<letter> - <description>"`` cell format.

    Documented behavior on UNKNOWN codes (see test below): pass-through, not
    raise. A new SEC Form 4 code letter on one row should not block parsing
    of the other 99 rows on the page.
    """
    assert _extract_transaction_code(raw_cell) == expected_code


def test_unknown_transaction_code_passes_through_does_not_raise() -> None:
    """Documented choice (sec_edgar.openinsider.TRANSACTION_CODE_LABELS dict
    documents known codes; unknown letters are returned verbatim, uppercased).

    Why pass-through over raise: spec § 工程标准 #5 (no silent failure)
    cuts both ways — raising on a single bad row would hide all other rows
    too. The compromise: return the letter unchanged AND log a warning so
    the unknown code is visible in production logs.
    """
    # Z is not in TRANSACTION_CODE_LABELS — simulate a future Form 4 code.
    assert "Z" not in TRANSACTION_CODE_LABELS, "test fixture invariant: Z must remain unmapped"
    assert _extract_transaction_code("Z - Some New Thing") == "Z"


# ---------------------------------------------------------------------------
# Happy path — real NVDA fixture
# ---------------------------------------------------------------------------


def test_get_insider_trades_happy_path_nvda(
    monkeypatch: pytest.MonkeyPatch, cache: Cache
) -> None:
    """End-to-end: real NVDA HTML → 100 InsiderTrade objects.

    All 100 NVDA rows in the fixture are sales (recent NVDA insider activity
    is exclusively selling at high prices), so we assert that's correctly
    captured but use synthetic HTML in other tests to exercise other codes.
    """
    monkeypatch.setattr(
        "src.data_sources.openinsider._fetch_screener_html",
        lambda ticker: _read("NVDA_screener.html").encode("utf-8"),
    )
    trades = get_insider_trades("NVDA", cache=cache)
    assert len(trades) == 100
    assert all(isinstance(t, InsiderTrade) for t in trades)
    assert all(t.ticker == "NVDA" for t in trades)
    # All recent NVDA insider activity is sales
    assert {t.transaction_type for t in trades} == {"S"}
    # value populated (Phase 0 决策 #1) — NVDA sales have negative values
    assert all(t.value is not None and t.value < 0 for t in trades)
    # transaction_value duplicate of value (model invariant for Phase 0)
    for t in trades[:5]:
        assert t.transaction_value == t.value
    # transaction_shares are negative for sales
    for t in trades[:5]:
        assert t.transaction_shares is not None and t.transaction_shares < 0
    # filing_date is parseable as ISO date string (not datetime)
    for t in trades[:5]:
        assert t.filing_date and len(t.filing_date) >= 10
        dt.date.fromisoformat(t.filing_date[:10])  # raises if malformed


def test_get_insider_trades_uses_cache(
    monkeypatch: pytest.MonkeyPatch, cache: Cache
) -> None:
    """Spec TTL 表:openinsider screener cached 4h. Second call hits cache."""
    calls = [0]

    def fake_fetch(ticker: str) -> bytes:
        calls[0] += 1
        return _read("NVDA_screener.html").encode("utf-8")

    monkeypatch.setattr("src.data_sources.openinsider._fetch_screener_html", fake_fetch)
    a = get_insider_trades("NVDA", cache=cache)
    b = get_insider_trades("NVDA", cache=cache)
    assert len(a) == len(b) == 100
    assert calls[0] == 1, f"expected 1 fetch (cache hit on second), got {calls[0]}"


# ---------------------------------------------------------------------------
# Synthetic HTML — exercises code variety not present in real NVDA fixture
# ---------------------------------------------------------------------------


SYNTHETIC_TEMPLATE = """
<html><body>
<table class="tinytable">
  <thead><tr>
    <th>X</th><th>Filing Date</th><th>Trade Date</th><th>Ticker</th>
    <th>Insider Name</th><th>Title</th><th>Trade Type</th><th>Price</th>
    <th>Qty</th><th>Owned</th><th>ΔOwn</th><th>Value</th>
    <th>1d</th><th>1w</th><th>1m</th><th>6m</th>
  </tr></thead>
  <tbody>
__ROWS__
  </tbody>
</table>
</body></html>
"""


def _make_row(
    *,
    filing_date: str = "2024-06-15 09:00:00",
    trade_date: str = "2024-06-14",
    ticker: str = "TEST",
    insider: str = "Doe John",
    title: str = "CEO, Dir",
    trade_type: str = "P - Purchase",
    price: str = "$10.00",
    qty: str = "1,000",
    owned: str = "5,000",
    delta_own: str = "+25%",
    value: str = "$10,000",
) -> str:
    return f"""<tr>
      <td></td><td>{filing_date}</td><td>{trade_date}</td><td>{ticker}</td>
      <td>{insider}</td><td>{title}</td><td>{trade_type}</td><td>{price}</td>
      <td>{qty}</td><td>{owned}</td><td>{delta_own}</td><td>{value}</td>
      <td></td><td></td><td></td><td></td>
    </tr>"""


def test_parse_handles_purchase_with_director_title() -> None:
    """Purchase + "Dir" in title → is_board_director=True, value > 0."""
    html = SYNTHETIC_TEMPLATE.replace(
        "__ROWS__",
        _make_row(trade_type="P - Purchase", qty="1,000", value="$10,000", title="Dir"),
    )
    trades = _parse_screener_html(html)
    assert len(trades) == 1
    t = trades[0]
    assert t.transaction_type == "P"
    assert t.transaction_shares == 1_000
    assert t.value == 10_000.0
    assert t.is_board_director is True


def test_parse_distinguishes_director_from_executive_only() -> None:
    """Title 'CFO' (no 'Dir') → is_board_director=False."""
    html = SYNTHETIC_TEMPLATE.replace(
        "__ROWS__", _make_row(title="CFO", trade_type="A - Award")
    )
    trades = _parse_screener_html(html)
    assert trades[0].is_board_director is False
    assert trades[0].transaction_type == "A"


def test_parse_multiple_rows_with_mixed_codes() -> None:
    """Several rows, different transaction codes — each parsed correctly."""
    rows = "\n".join([
        _make_row(trade_type="P - Purchase", qty="500", value="$5,000"),
        _make_row(trade_type="S - Sale", qty="-200", value="-$2,000"),
        _make_row(trade_type="M - Option Exercise", qty="1,000", value="$0"),
        _make_row(trade_type="G - Gift", qty="100", value="$0"),
    ])
    trades = _parse_screener_html(SYNTHETIC_TEMPLATE.replace("__ROWS__", rows))
    assert [t.transaction_type for t in trades] == ["P", "S", "M", "G"]
    assert [t.transaction_shares for t in trades] == [500, -200, 1_000, 100]
    assert [t.value for t in trades] == [5_000.0, -2_000.0, 0.0, 0.0]


def test_parse_filing_date_keeps_iso_compatible_string() -> None:
    """openinsider filing date format is "YYYY-MM-DD HH:MM:SS"; we keep
    the full string but ensure it's parseable by date.fromisoformat(s[:10]).
    """
    html = SYNTHETIC_TEMPLATE.replace(
        "__ROWS__",
        _make_row(filing_date="2024-06-15 09:30:42", trade_date="2024-06-14"),
    )
    trades = _parse_screener_html(html)
    assert trades[0].filing_date == "2024-06-15 09:30:42"
    assert trades[0].transaction_date == "2024-06-14"
    # Round-trip the date prefix
    assert dt.date.fromisoformat(trades[0].filing_date[:10]) == dt.date(2024, 6, 15)


# ---------------------------------------------------------------------------
# Helper-function micro-tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("33,960,922", 33_960_922),
        ("-221,682", -221_682),
        ("0", 0),
        ("", None),
        (None, None),
    ],
)
def test_parse_int_with_commas(raw: str | None, expected: int | None) -> None:
    assert _parse_int_with_commas(raw) == expected


@pytest.mark.parametrize(
    "title,expected",
    [
        ("Dir", True),
        ("CEO, Dir", True),
        ("Director", True),
        ("CFO", False),
        ("CEO", False),
        ("10%", False),
        ("", False),
    ],
)
def test_is_director(title: str, expected: bool) -> None:
    assert _is_director(title) is expected


# ---------------------------------------------------------------------------
# Phase 0 决策 #1 model invariants
# ---------------------------------------------------------------------------


def test_insider_trade_model_has_transaction_type_and_value_fields() -> None:
    """Phase 0 决策 #1: persona scripts (michael-burry, news-sentiment)
    rely on these two fields. Without defaults, paid-backend call sites
    would fail validation. Defaults must be ``None``.
    """
    # Construct without the new fields — must not raise
    t = InsiderTrade(
        ticker="NVDA",
        issuer=None,
        name=None,
        title=None,
        is_board_director=None,
        transaction_date=None,
        transaction_shares=None,
        transaction_price_per_share=None,
        transaction_value=None,
        shares_owned_before_transaction=None,
        shares_owned_after_transaction=None,
        security_title=None,
        filing_date="2024-06-15",
    )
    assert t.transaction_type is None
    assert t.value is None

    # And explicitly supplying them works
    t2 = InsiderTrade(
        ticker="NVDA", issuer=None, name=None, title=None, is_board_director=None,
        transaction_date=None, transaction_shares=None, transaction_price_per_share=None,
        transaction_value=None, shares_owned_before_transaction=None,
        shares_owned_after_transaction=None, security_title=None,
        filing_date="2024-06-15",
        transaction_type="S", value=-100_000.0,
    )
    assert t2.transaction_type == "S"
    assert t2.value == -100_000.0


# ---------------------------------------------------------------------------
# Network seam smoke — exercise _fetch_screener_html itself
# ---------------------------------------------------------------------------


def test_fetch_screener_html_calls_correct_url(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def fake_http_get(url: str) -> bytes:
        seen["url"] = url
        return b"<html></html>"

    monkeypatch.setattr("src.data_sources.openinsider._http_get", fake_http_get)
    from src.data_sources.openinsider import _fetch_screener_html

    _fetch_screener_html("NVDA")
    assert seen["url"] == "http://openinsider.com/screener?s=NVDA"


def test_http_get_uses_user_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    """Adapter must send a UA — many sites including openinsider rate-limit empty UAs."""
    import httpx

    seen: dict[str, Any] = {}

    def fake_get(self: Any, url: str, **kw: Any) -> httpx.Response:
        seen["url"] = url
        seen["headers"] = dict(kw.get("headers") or {})
        return httpx.Response(200, content=b"<html></html>", request=httpx.Request("GET", url))

    monkeypatch.setattr("httpx.Client.get", fake_get)
    from src.data_sources.openinsider import _http_get

    _http_get("http://openinsider.com/screener?s=NVDA")
    assert "User-Agent" in seen["headers"]
    assert seen["headers"]["User-Agent"]
