"""One-shot fetcher for SEC EDGAR test fixtures.

Pulls the global ticker→CIK map plus companyfacts + submissions JSON for
NVDA / AAPL / BRK.A into ``tests/unit/fixtures/sec/``. These files are the
ground truth that ``test_sec_edgar.py`` mocks against.

Choice of tickers (PROJECT_SPEC.md § 1.2):
    NVDA   — fiscal year ends late January (FY ≠ calendar year)
    AAPL   — fiscal year ends late September
    BRK.A  — Berkshire, atypical statement layout, very large filer

Usage:
    SEC_EDGAR_USER_AGENT="Your Name your-email@example.com" \\
        uv run python scripts/fetch_test_fixtures.py

Re-run only when a new XBRL edge case is needed; fixtures are committed.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# (ticker, CIK as int).  CIKs are stable; hardcoding avoids a chicken-and-egg
# bootstrap (looking them up needs the same SEC fetch we're trying to test).
TICKERS: list[tuple[str, int]] = [
    ("NVDA", 1045810),
    ("AAPL", 320193),
    ("BRK.A", 1067983),
]

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "tests" / "unit" / "fixtures" / "sec"
TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"

# SEC rate limit is 10 req/s; we make ~7 here. 0.2s gap is plenty respectful.
REQUEST_GAP_SEC = 0.2


def fetch(url: str, ua: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": ua})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()  # type: ignore[no-any-return]


def save(name: str, data: bytes) -> Path:
    out = FIXTURE_DIR / name
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    print(f"  wrote {out.relative_to(FIXTURE_DIR.parent.parent.parent)} ({len(data):,} bytes)")
    return out


def main() -> int:
    ua = os.environ.get("SEC_EDGAR_USER_AGENT", "").strip()
    if not ua:
        print(
            "ERROR: SEC_EDGAR_USER_AGENT env var is required.\n"
            "  export SEC_EDGAR_USER_AGENT='Your Name your-email@example.com'",
            file=sys.stderr,
        )
        return 2

    print(f"User-Agent: {ua}")
    print(f"Fixture dir: {FIXTURE_DIR}")

    print("\n[1/3] global ticker→CIK map")
    save("company_tickers.json", fetch(TICKER_MAP_URL, ua))
    time.sleep(REQUEST_GAP_SEC)

    print("\n[2/3] companyfacts (XBRL concept time series)")
    for ticker, cik in TICKERS:
        url = COMPANYFACTS_URL.format(cik=cik)
        print(f"  {ticker} CIK={cik:010d} <- {url}")
        try:
            save(f"{ticker}_companyfacts.json", fetch(url, ua))
        except urllib.error.HTTPError as exc:
            print(f"  HTTPError for {ticker}: {exc.code} {exc.reason}")
            return 1
        time.sleep(REQUEST_GAP_SEC)

    print("\n[3/3] submissions (filings index)")
    for ticker, cik in TICKERS:
        url = SUBMISSIONS_URL.format(cik=cik)
        print(f"  {ticker} CIK={cik:010d} <- {url}")
        try:
            save(f"{ticker}_submissions.json", fetch(url, ua))
        except urllib.error.HTTPError as exc:
            print(f"  HTTPError for {ticker}: {exc.code} {exc.reason}")
            return 1
        time.sleep(REQUEST_GAP_SEC)

    # Quick sanity print so we can spot obvious garbage without parsing
    print("\nSummary:")
    total = 0
    for f in sorted(FIXTURE_DIR.iterdir()):
        size = f.stat().st_size
        total += size
        # Probe top-level keys as a smoke-test that the JSON is structured
        try:
            top = list(json.loads(f.read_bytes()).keys())[:5]
        except json.JSONDecodeError:
            top = ["<not JSON>"]
        print(f"  {f.name:35s} {size:>11,} bytes  top-keys={top}")
    print(f"\nTotal: {total:,} bytes ({total / 1024 / 1024:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
