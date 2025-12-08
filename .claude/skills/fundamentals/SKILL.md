---
name: fundamentals
description: Analyze company fundamentals including financial statements, ratios, and profitability metrics. Use when evaluating financial health, profitability, or balance sheet strength.
---

# Fundamental Analysis

## Overview
Comprehensive analysis of company financial fundamentals including profitability, growth, financial health, and valuation ratios.

## Analysis Process

### Run Fundamental Analysis
```bash
python .claude/skills/fundamentals/scripts/analyze.py {TICKER} {END_DATE}
```

## Metrics Analyzed

### Profitability
- ROE (Return on Equity) > 15%
- Net Margin > 20%
- Operating Margin > 15%

### Growth
- Revenue Growth > 10%
- Earnings Growth > 10%
- Book Value Growth > 10%

### Financial Health
- Current Ratio > 1.5
- Debt/Equity < 0.5
- FCF Conversion > 80%

### Valuation
- P/E Ratio < 25
- P/B Ratio < 3
- P/S Ratio < 5

## Signal Interpretation
- **Bullish**: Strong profitability, healthy balance sheet, reasonable valuation
- **Neutral**: Mixed signals across categories
- **Bearish**: Weak fundamentals or expensive valuation

## Example
```
Analyze MSFT as of 2024-12-01 using fundamental analysis.
```
