"""One-shot fetcher for yfinance test fixtures.

Pulls real ``Ticker.history(...)`` and ``Ticker.info`` for NVDA, MSFT, and
a deliberately-invalid ticker (FAKE_NVDA_X) into ``tests/unit/fixtures/yfinance/``.

Choice of tickers:
    NVDA          — happy path, large-cap with steady history & rich info dict
    MSFT          — second valid ticker, sanity-check shape across companies
    FAKE_NVDA_X   — known-invalid; verifies "ticker not found" returns empty
                    DataFrame + sparse info (without raising) — the spec § 1.3
                    edge case we must not accidentally regress on

History window is 2024-06-01..2024-12-31 (~7 months of trading days), small
enough to keep fixture pickles in single-digit KB.

Format choices:
    history → pickle (.pkl). The DataFrame has a tz-aware DatetimeIndex
              ("America/New_York" by default); pickle round-trips that
              cleanly while CSV would mangle it. Pickles are committed
              alongside fixture JSONs — they're tiny and deterministic
              for a given ticker+window+yfinance version.
    info    → JSON (.json), pretty-printed for grep-ability. Non-serializable
              values get coerced via ``default=str``.

Re-run only when yfinance behavior changes or a new ticker case is needed.

Usage:
    uv run python scripts/fetch_yfinance_fixtures.py
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import yfinance as yf


TICKERS: list[str] = ["NVDA", "MSFT", "FAKE_NVDA_X"]
START = dt.date(2024, 6, 1)
END = dt.date(2024, 12, 31)

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "tests" / "unit" / "fixtures" / "yfinance"


def main() -> int:
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Fixture dir: {FIXTURE_DIR}")
    print(f"History window: {START} → {END}")

    for ticker in TICKERS:
        print(f"\n[{ticker}]")
        t = yf.Ticker(ticker)

        print(f"  fetching history({START}..{END}, auto_adjust=True)")
        hist = t.history(start=str(START), end=str(END), auto_adjust=True)
        hist_path = FIXTURE_DIR / f"{ticker}_history.pkl"
        hist.to_pickle(hist_path)
        rows = len(hist)
        cols = list(hist.columns)
        tz = hist.index.tz if hasattr(hist.index, "tz") else None
        print(f"  → {hist_path.name}: rows={rows} cols={cols} tz={tz} size={hist_path.stat().st_size:,} bytes")

        print(f"  fetching info")
        info = t.info if t.info else {}
        info_path = FIXTURE_DIR / f"{ticker}_info.json"
        info_path.write_text(json.dumps(info, indent=2, default=str, sort_keys=True))
        print(f"  → {info_path.name}: {len(info)} keys size={info_path.stat().st_size:,} bytes")

    print("\nSummary:")
    total = 0
    for f in sorted(FIXTURE_DIR.iterdir()):
        size = f.stat().st_size
        total += size
        print(f"  {f.name:35s} {size:>10,} bytes")
    print(f"\nTotal: {total:,} bytes ({total / 1024:.1f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
