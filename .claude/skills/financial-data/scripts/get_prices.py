#!/usr/bin/env python3
"""Fetch stock prices for a ticker."""
import sys
import json

sys.path.insert(0, '.')
from src.tools.api import get_prices

if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Usage: get_prices.py TICKER START_DATE END_DATE")
        print("Example: get_prices.py AAPL 2024-01-01 2024-12-01")
        sys.exit(1)

    ticker = sys.argv[1]
    start_date = sys.argv[2]
    end_date = sys.argv[3]

    prices = get_prices(ticker, start_date, end_date)
    print(json.dumps([p.model_dump() for p in prices], indent=2, default=str))
