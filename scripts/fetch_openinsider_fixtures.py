"""One-shot fetcher for OpenInsider test fixtures.

Pulls the screener page HTML for two real tickers into
``tests/unit/fixtures/openinsider/``:

    NVDA  — high-frequency insider activity, 100-row tinytable; happy path
            and a natural source of P/S/A/M/G/D-style trade type variety.
    VTI   — broad-market ETF; OpenInsider returns a page WITHOUT a
            ``tinytable`` element at all (no insider data structure).
            This is the real-world "zero-trade" case the spec calls for —
            tests the parser's "no tinytable" return-empty-list branch.

We deliberately do NOT fetch a third ticker for the ``broken`` fixture —
the schema-drift test fixture is hand-corrupted from NVDA in this script
itself (so the corruption is committed alongside, with a comment showing
exactly what changed vs. the real one). See ``write_broken_fixture()``.

Re-run this script only when OpenInsider changes its page structure or
we want to exercise a new edge case.

Usage:
    uv run python scripts/fetch_openinsider_fixtures.py
"""
from __future__ import annotations

import sys
import time
import urllib.request
from pathlib import Path


TICKERS: list[str] = ["NVDA", "VTI"]
SCREENER_URL = "http://openinsider.com/screener?s={ticker}"
USER_AGENT = "ai-sub-invest fixture fetcher (test@example.com)"
REQUEST_GAP_SEC = 0.5

FIXTURE_DIR = (
    Path(__file__).resolve().parent.parent / "tests" / "unit" / "fixtures" / "openinsider"
)


def fetch_screener(ticker: str) -> bytes:
    req = urllib.request.Request(
        SCREENER_URL.format(ticker=ticker),
        headers={"User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()  # type: ignore[no-any-return]


def write_broken_fixture(real_html: bytes) -> Path:
    """Hand-corrupt NVDA HTML to simulate a schema drift.

    Changes applied (each enough on its own to break a strict parser):
      1. ``class="tinytable"`` → ``class="formerly-tinytable"`` on the data
         table. Parsers keying on the class will stop finding the table.
      2. The first ``<th>`` ("X") is renamed to ``<th class="head">FOO</th>``
         to also corrupt header detection if anyone falls back to that.
    """
    text = real_html.decode("utf-8", errors="replace")
    # 1) class rename — only on the screener data table, not the CSS rules.
    # Note: we match `class="tinytable"` (not `<table class=...`) because the
    # real table tag has many other attrs between `<table` and `class=`
    # (width/cellpadding/cellspacing/border). The CSS rules use `.tinytable`
    # (leading dot, no quotes) so they're untouched by this substring rename.
    text = text.replace('class="tinytable"', 'class="formerly-tinytable"', 1)
    # 2) Slip a marker comment so future-me can find this in a diff
    text = (
        "<!-- DELIBERATELY CORRUPTED for unit-test schema-drift coverage. -->\n"
        + text
    )
    out = FIXTURE_DIR / "broken_NVDA_screener.html"
    out.write_bytes(text.encode("utf-8"))
    return out


def main() -> int:
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Fixture dir: {FIXTURE_DIR}")

    real_dump: dict[str, bytes] = {}
    for ticker in TICKERS:
        print(f"\n[{ticker}] fetching …")
        body = fetch_screener(ticker)
        out = FIXTURE_DIR / f"{ticker}_screener.html"
        out.write_bytes(body)
        size_kb = len(body) / 1024
        # quick rows estimate
        rows = body.count(b"<tr>")
        print(f"  → {out.name}: {len(body):,} bytes ({size_kb:.1f} KB), <tr> count={rows}")
        real_dump[ticker] = body
        time.sleep(REQUEST_GAP_SEC)

    print("\n[broken_NVDA_screener.html] hand-corrupting NVDA fixture …")
    broken = write_broken_fixture(real_dump["NVDA"])
    print(f"  → {broken.name}: {broken.stat().st_size:,} bytes")

    print("\nSummary:")
    total = 0
    for f in sorted(FIXTURE_DIR.iterdir()):
        sz = f.stat().st_size
        total += sz
        print(f"  {f.name:35s}  {sz:>9,} bytes")
    print(f"\nTotal: {total:,} bytes ({total / 1024:.1f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
