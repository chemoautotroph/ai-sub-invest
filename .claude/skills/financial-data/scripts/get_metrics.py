#!/usr/bin/env python3
"""Fetch financial metrics for a stock ticker."""
import sys
import json

sys.path.insert(0, '.')
from src.tools.api import get_financial_metrics

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: get_metrics.py TICKER END_DATE [PERIOD] [LIMIT]")
        print("Example: get_metrics.py AAPL 2024-12-01 ttm 10")
        sys.exit(1)

    ticker = sys.argv[1]
    end_date = sys.argv[2]
    period = sys.argv[3] if len(sys.argv) > 3 else "ttm"
    limit = int(sys.argv[4]) if len(sys.argv) > 4 else 10

    metrics = get_financial_metrics(ticker, end_date, period, limit)
    print(json.dumps([m.model_dump() for m in metrics], indent=2, default=str))
