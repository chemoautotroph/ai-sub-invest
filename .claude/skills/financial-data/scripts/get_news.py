#!/usr/bin/env python3
"""Fetch company news for a ticker."""
import sys
import json

sys.path.insert(0, '.')
from src.tools.api import get_company_news

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: get_news.py TICKER END_DATE [LIMIT]")
        print("Example: get_news.py AAPL 2024-12-01 10")
        sys.exit(1)

    ticker = sys.argv[1]
    end_date = sys.argv[2]
    limit = int(sys.argv[3]) if len(sys.argv) > 3 else 10

    news = get_company_news(ticker, end_date, limit)
    print(json.dumps([n.model_dump() for n in news], indent=2, default=str))
