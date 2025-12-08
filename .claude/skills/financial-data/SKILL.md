---
name: financial-data
description: Fetch stock financial data including metrics, prices, news, and insider trades. Use when analyzing stocks, getting financial metrics, or researching company fundamentals.
---

# Financial Data Fetcher

## Overview
Provides financial data from the Financial Datasets API for stock analysis.

## Requirements
Ensure `FINANCIAL_DATASETS_API_KEY` is set in environment.

## Usage

### Get Financial Metrics
```bash
python .claude/skills/financial-data/scripts/get_metrics.py AAPL 2024-12-01 ttm 10
```
Returns: ROE, debt/equity, margins, P/E, current ratio, etc.

### Get Stock Prices
```bash
python .claude/skills/financial-data/scripts/get_prices.py AAPL 2024-01-01 2024-12-01
```
Returns: Daily OHLCV price data.

### Get Company News
```bash
python .claude/skills/financial-data/scripts/get_news.py AAPL 2024-12-01 10
```
Returns: Recent news articles with sentiment.

### Get Insider Trades
```bash
python .claude/skills/financial-data/scripts/get_insider.py AAPL 2024-12-01 20
```
Returns: Recent insider buying/selling activity.

### Get Market Cap
```bash
python .claude/skills/financial-data/scripts/get_market_cap.py AAPL 2024-12-01
```
Returns: Current market capitalization.

### Search Financial Line Items
```bash
python .claude/skills/financial-data/scripts/search_line_items.py AAPL 2024-12-01 ttm 10
```
Returns: Detailed financial statement line items (revenue, net income, etc.)

## Output Format
All scripts return JSON with the requested financial data.
