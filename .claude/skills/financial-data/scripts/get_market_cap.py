#!/usr/bin/env python3
"""Fetch market cap for a ticker."""
import sys
import json

sys.path.insert(0, '.')
from src.tools.api import get_market_cap

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: get_market_cap.py TICKER END_DATE")
        print("Example: get_market_cap.py AAPL 2024-12-01")
        sys.exit(1)

    ticker = sys.argv[1]
    end_date = sys.argv[2]

    market_cap = get_market_cap(ticker, end_date)
    print(json.dumps({"ticker": ticker, "market_cap": market_cap}, indent=2))
