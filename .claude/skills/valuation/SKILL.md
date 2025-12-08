---
name: valuation
description: Perform multi-model stock valuation including DCF, comparables, and asset-based methods. Use when determining fair value or comparing valuation methods.
---

# Valuation Analysis

## Overview
Comprehensive valuation using multiple methodologies to determine fair value range.

## Analysis Process

### Run Valuation Analysis
```bash
python .claude/skills/valuation/scripts/analyze.py {TICKER} {END_DATE}
```

## Models Applied

### DCF (Discounted Cash Flow)
- Free Cash Flow projection
- Terminal value calculation
- Risk-adjusted discount rate

### Relative Valuation
- P/E comparison to growth
- EV/EBITDA analysis
- P/B vs ROE

### Owner Earnings
- Buffett-style valuation
- Maintenance capex adjustment

### Dividend Discount Model
- If applicable for dividend payers

## Key Outputs
- Intrinsic value estimate
- Valuation gap (vs market cap)
- Confidence range

## Signal Interpretation
- **Bullish**: Trading significantly below fair value (>20% discount)
- **Neutral**: Trading near fair value (±20%)
- **Bearish**: Trading significantly above fair value (>20% premium)

## Example
```
Analyze AAPL as of 2024-12-01 to determine fair value.
```
