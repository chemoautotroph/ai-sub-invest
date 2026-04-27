"""OpenInsider HTML scraper for SEC Form 4 insider trades.

Public function:
    get_insider_trades(ticker)  →  list[InsiderTrade]

OpenInsider doesn't expose JSON; we scrape ``http://openinsider.com/screener?s={ticker}``
and parse the ``<table class="tinytable">`` body. Schema is verified against
a fixed expected-headers list — any deviation raises ``OpenInsiderSchemaError``
rather than returning silently-wrong data (spec § 工程标准 #5).

Architecture follows PROJECT_SPEC.md § Common Conventions:
  - ``_fetch_screener_html`` is the only network entry; tests monkeypatch it.
  - ``_parse_screener_html`` is a pure str-in / list-out function — fixtures
    feed it directly.
  - 4h cache shares ``CacheTTL.AGGREGATOR_INSIDER_TRADES`` value (numerically
    same; semantically "Form 4 freshness window").

Documented decisions:
  - Unknown transaction code letters are pass-through (uppercase) with a
    warning log, not raise. Refusing to parse the whole page because of
    one new SEC code letter would be worse than reporting it as-is.
  - Garbage in the Value cell returns ``None`` for that one trade's value
    and logs a warning. Localises damage rather than blowing up the row.
  - Fields not present in the screener (issuer, security_title,
    shares_owned_before_transaction) are populated as ``None``; aggregator
    can fill them from other sources if needed.
"""
from __future__ import annotations

import logging
import re
from typing import Final

import httpx
from bs4 import BeautifulSoup

from src.data.models import InsiderTrade
from src.data_sources.cache import Cache, CacheTTL


logger = logging.getLogger(__name__)


SCREENER_URL: Final[str] = "http://openinsider.com/screener?s={ticker}"
USER_AGENT: Final[str] = "ai-sub-invest free-backend (test@example.com)"
_HTTP_TIMEOUT_SEC: Final[float] = 30.0


# Form 4 transaction codes we can label nicely. Used only for documentation
# (not for validation) — the parser stores the letter regardless of whether
# it appears here.
TRANSACTION_CODE_LABELS: Final[dict[str, str]] = {
    "P": "Purchase",
    "S": "Sale",
    "A": "Award/Grant",
    "M": "Option Exercise (non-derivative)",
    "F": "Tax Withholding",
    "G": "Gift",
    "D": "Sale-to-Issuer",
    "X": "Option Exercise (in-the-money)",
    "C": "Conversion",
    "I": "Discretionary Plan",
    "J": "Other Acquisition",
    "K": "Equity Swap",
    "L": "Small Acquisition",
    "U": "Tender to Issuer",
    "V": "Voluntary Reported",
    "W": "Will/Inheritance",
}


# Locked headers — must match exactly (case-folded, NBSP-stripped). Order
# matters: parsing is positional. Any column add/remove/rename → schema error.
_EXPECTED_HEADERS: Final[tuple[str, ...]] = (
    "x", "filing date", "trade date", "ticker",
    "insider name", "title", "trade type", "price",
    "qty", "owned", "δown", "value",
    "1d", "1w", "1m", "6m",
)
_EXPECTED_COL_COUNT: Final[int] = len(_EXPECTED_HEADERS)


# Column indices (kept as named constants so the parser doesn't sprout magic numbers)
_COL_FILING_DATE = 1
_COL_TRADE_DATE = 2
_COL_TICKER = 3
_COL_INSIDER = 4
_COL_TITLE = 5
_COL_TRADE_TYPE = 6
_COL_PRICE = 7
_COL_QTY = 8
_COL_OWNED = 9
_COL_VALUE = 11


# ---------------------------------------------------------------------------
# exceptions
# ---------------------------------------------------------------------------


class OpenInsiderError(Exception):
    """Base class for openinsider errors."""


class OpenInsiderSchemaError(OpenInsiderError):
    """openinsider HTML structure changed — refuse to silently return wrong data."""


# ---------------------------------------------------------------------------
# pure helpers — easy to unit-test in isolation
# ---------------------------------------------------------------------------


_AMOUNT_PATTERN = re.compile(r"^([+-]?)\$?([0-9,]+(?:\.[0-9]+)?)\s*([KMB]?)$", re.IGNORECASE)


def _parse_amount(raw: str | None) -> float | None:
    """Parse openinsider money strings → float.

    Accepted forms (in addition to the openinsider-emitted ones):
        "$1,234.56"  "$0"  "-$38,502,524"  "$1.2M"  "$1.5K"  "$3B"

    Returns ``None`` for empty / whitespace / unparseable input. Logs a
    warning for the unparseable case so missing values stay visible.
    """
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    m = _AMOUNT_PATTERN.match(s)
    if m is None:
        logger.warning("openinsider _parse_amount: cannot parse %r — returning None", raw)
        return None
    sign_str, num_str, suffix = m.groups()
    try:
        value = float(num_str.replace(",", ""))
    except ValueError:
        logger.warning("openinsider _parse_amount: numeric core %r failed float() — returning None", num_str)
        return None
    if sign_str == "-":
        value = -value
    suffix = suffix.upper()
    if suffix == "K":
        value *= 1_000.0
    elif suffix == "M":
        value *= 1_000_000.0
    elif suffix == "B":
        value *= 1_000_000_000.0
    return value


def _parse_int_with_commas(raw: str | None) -> int | None:
    """Parse "33,960,922" / "-221,682" → int. Empty → None."""
    if raw is None:
        return None
    s = str(raw).strip().replace(",", "")
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        logger.warning("openinsider _parse_int_with_commas: cannot parse %r", raw)
        return None


def _extract_transaction_code(cell_text: str) -> str | None:
    """Map openinsider Trade Type cell text → single-letter code.

    Cell formats observed:
        "S - Sale", "P - Purchase", ...        (code + label)
        "S"                                     (bare letter, rare)
        ""                                      (empty)

    Unknown letter codes are returned as-is (uppercased). This is a
    documented choice: a new SEC Form 4 code shouldn't block parsing of
    other rows. We log if the code isn't in TRANSACTION_CODE_LABELS so it
    stays visible.
    """
    s = (cell_text or "").strip()
    if not s:
        return None
    code: str
    if " - " in s:
        code = s.split(" - ", 1)[0].strip().upper()
    else:
        code = s.upper()
    if code and code not in TRANSACTION_CODE_LABELS:
        logger.warning(
            "openinsider: unknown transaction code %r — passing through (consider extending TRANSACTION_CODE_LABELS)",
            code,
        )
    return code or None


def _is_director(title: str) -> bool:
    """openinsider title strings: comma-separated roles. "Dir" or "Director"
    appearing as a token means the insider sits on the board.

    Examples:
        "Dir"            → True
        "CEO, Dir"       → True
        "Director"       → True
        "CFO"            → False
    """
    if not title:
        return False
    tokens = [t.strip().lower() for t in title.split(",")]
    return any(t == "dir" or t.startswith("director") for t in tokens)


# ---------------------------------------------------------------------------
# pure parser
# ---------------------------------------------------------------------------


def _parse_screener_html(html: str) -> list[InsiderTrade]:
    """Parse openinsider screener HTML → list of InsiderTrade.

    Returns ``[]`` for the canonical empty cases:
      - tinytable element absent (e.g., ETF page that doesn't render the
        insider screener)
      - tinytable present but tbody empty

    Raises ``OpenInsiderSchemaError`` when the table is present but its
    structure no longer matches our expectations (header drift, column
    count change). Failing loudly here is deliberate — silently returning
    misaligned data would propagate wrong values into persona analyses.
    """
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", class_="tinytable")
    if table is None:
        # Discriminator: did the page render a data-shaped table that just
        # lost its class (= schema/class drift), or is there genuinely no
        # insider data table at all (= empty case)?
        # We detect drift by header-signature matching: if any table in the
        # page has our expected header sequence, the page IS the screener,
        # but the class moved — refuse to silently fall through to [].
        for candidate in soup.find_all("table"):
            cand_thead = candidate.find("thead")
            if cand_thead is None:
                continue
            cand_first = cand_thead.find("tr")
            if cand_first is None:
                continue
            cand_headers = tuple(
                _normalize_header(th.get_text())
                for th in cand_first.find_all("th")
            )
            if cand_headers == _EXPECTED_HEADERS:
                raise OpenInsiderSchemaError(
                    f"openinsider data table located by header signature but "
                    f"its class is {candidate.get('class')!r} instead of "
                    f"'tinytable' — schema/class drift"
                )
        return []

    # Validate headers exist and match expected schema.
    thead = table.find("thead")
    headers: list[str] = []
    if thead is not None:
        first_header_row = thead.find("tr")
        if first_header_row is not None:
            headers = [
                _normalize_header(th.get_text())
                for th in first_header_row.find_all("th")
            ]

    tbody = table.find("tbody")
    rows = tbody.find_all("tr") if tbody is not None else []

    # If there are rows, schema validation is mandatory. Check column count
    # before header values so the error message names the more fundamental
    # mismatch first (a column-count mismatch makes header-value mismatch
    # comparisons meaningless).
    if rows:
        if len(headers) != _EXPECTED_COL_COUNT:
            raise OpenInsiderSchemaError(
                f"openinsider header column count drift: expected "
                f"{_EXPECTED_COL_COUNT} columns, got {len(headers)} ({headers!r})"
            )
        if tuple(headers) != _EXPECTED_HEADERS:
            raise OpenInsiderSchemaError(
                f"openinsider header drift: expected {_EXPECTED_HEADERS}, got {tuple(headers)}"
            )
        sample_cells = rows[0].find_all("td")
        if len(sample_cells) != _EXPECTED_COL_COUNT:
            raise OpenInsiderSchemaError(
                f"openinsider column count drift: expected {_EXPECTED_COL_COUNT}, "
                f"got {len(sample_cells)} on first row"
            )

    out: list[InsiderTrade] = []
    for tr in rows:
        cells = [td.get_text(strip=True) for td in tr.find_all("td")]
        if len(cells) != _EXPECTED_COL_COUNT:
            raise OpenInsiderSchemaError(
                f"openinsider row column count drift: expected {_EXPECTED_COL_COUNT}, "
                f"got {len(cells)} (row text: {cells!r})"
            )

        title = cells[_COL_TITLE]
        trade_value = _parse_amount(cells[_COL_VALUE])
        out.append(
            InsiderTrade(
                ticker=cells[_COL_TICKER],
                issuer=None,                  # openinsider screener doesn't expose issuer name separately
                name=cells[_COL_INSIDER] or None,
                title=title or None,
                is_board_director=_is_director(title),
                transaction_date=cells[_COL_TRADE_DATE] or None,
                transaction_shares=_int_or_float(cells[_COL_QTY]),
                transaction_price_per_share=_parse_amount(cells[_COL_PRICE]),
                transaction_value=trade_value,
                shares_owned_before_transaction=None,  # not in screener output
                shares_owned_after_transaction=_int_or_float(cells[_COL_OWNED]),
                security_title=None,
                filing_date=cells[_COL_FILING_DATE],
                transaction_type=_extract_transaction_code(cells[_COL_TRADE_TYPE]),
                value=trade_value,
            )
        )
    return out


def _normalize_header(s: str) -> str:
    """Header cells use NBSP and varying case; normalise so comparison works.

    NBSP (\\xa0) is what BeautifulSoup returns for ``&nbsp;`` in the HTML;
    casefold + strip handles whitespace and unicode case (handles "Δ" too).
    """
    return s.replace("\xa0", " ").strip().casefold()


def _int_or_float(raw: str | None) -> float | None:
    """openinsider Qty/Owned cells are large integers with thousands commas.

    We parse to ``float`` (matching InsiderTrade's float typing) but via the
    int helper so "1,000,000" works. Empty → None.
    """
    n = _parse_int_with_commas(raw)
    return float(n) if n is not None else None


# ---------------------------------------------------------------------------
# network seam — single point monkey-patched in tests
# ---------------------------------------------------------------------------


def _http_get(url: str) -> bytes:
    headers = {"User-Agent": USER_AGENT}
    with httpx.Client(timeout=_HTTP_TIMEOUT_SEC, headers=headers) as client:
        resp = client.get(url, headers=headers)
        resp.raise_for_status()
        return resp.content


def _fetch_screener_html(ticker: str) -> bytes:
    return _http_get(SCREENER_URL.format(ticker=ticker))


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------


def get_insider_trades(ticker: str, *, cache: Cache | None = None) -> list[InsiderTrade]:
    """Fetch and parse insider trades from openinsider screener.

    4h cache TTL — Form 4 filings show up on the same trading day they're
    submitted, but openinsider re-renders on its own schedule. 4h matches
    the spec ``aggregator.insider_trades`` value.
    """
    cache = cache or Cache()
    key = ticker.upper()
    body = cache.get("openinsider", "screener", key)
    if body is None:
        body = _fetch_screener_html(ticker)
        cache.set(
            "openinsider", "screener", key,
            body, CacheTTL.AGGREGATOR_INSIDER_TRADES,
        )
    html = body.decode("utf-8", errors="replace")
    return _parse_screener_html(html)
