#!/usr/bin/env python3
"""Search financial line items for a ticker."""
import sys
import json

sys.path.insert(0, '.')
from src.tools.api import search_line_items

# Common line items for analysis
DEFAULT_LINE_ITEMS = [
    "capital_expenditure",
    "depreciation_and_amortization",
    "net_income",
    "outstanding_shares",
    "total_assets",
    "total_liabilities",
    "shareholders_equity",
    "dividends_and_other_cash_distributions",
    "issuance_or_purchase_of_equity_shares",
    "gross_profit",
    "revenue",
    "free_cash_flow",
]

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: search_line_items.py TICKER END_DATE [PERIOD] [LIMIT]")
        print("Example: search_line_items.py AAPL 2024-12-01 ttm 10")
        sys.exit(1)

    ticker = sys.argv[1]
    end_date = sys.argv[2]
    period = sys.argv[3] if len(sys.argv) > 3 else "ttm"
    limit = int(sys.argv[4]) if len(sys.argv) > 4 else 10

    line_items = search_line_items(ticker, DEFAULT_LINE_ITEMS, end_date, period, limit)
    print(json.dumps([item.model_dump() for item in line_items], indent=2, default=str))
