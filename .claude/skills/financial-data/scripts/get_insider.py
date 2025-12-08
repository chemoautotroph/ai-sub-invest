#!/usr/bin/env python3
"""Fetch insider trades for a ticker."""
import sys
import json

sys.path.insert(0, '.')
from src.tools.api import get_insider_trades

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: get_insider.py TICKER END_DATE [LIMIT]")
        print("Example: get_insider.py AAPL 2024-12-01 20")
        sys.exit(1)

    ticker = sys.argv[1]
    end_date = sys.argv[2]
    limit = int(sys.argv[3]) if len(sys.argv) > 3 else 20

    trades = get_insider_trades(ticker, end_date, limit)
    print(json.dumps([t.model_dump() for t in trades], indent=2, default=str))
