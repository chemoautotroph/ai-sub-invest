---
name: peter-lynch
description: Analyze stocks using Peter Lynch's growth at reasonable price (GARP) methodology. Use when looking for 10-baggers, analyzing PEG ratios, or evaluating growth stocks.
---

# Peter Lynch Investment Analysis

## Investment Philosophy
I analyze stocks using Peter Lynch's principles:
1. **Know What You Own**: Invest in what you understand
2. **PEG Ratio**: Growth relative to valuation
3. **Stock Categories**: Slow growers, stalwarts, fast growers, cyclicals, turnarounds, asset plays
4. **10-Baggers**: Find stocks that can grow 10x
5. **The Story**: Every stock should have a simple story

## Analysis Process

### Step 1: Gather Financial Data
```bash
python .claude/skills/financial-data/scripts/get_metrics.py {TICKER} {END_DATE} ttm 10
python .claude/skills/financial-data/scripts/search_line_items.py {TICKER} {END_DATE} ttm 10
```

### Step 2: Run Lynch Analysis
```bash
python .claude/skills/peter-lynch/scripts/analyze.py {TICKER} {END_DATE}
```

## Key Metrics
- **PEG Ratio** = P/E ÷ Earnings Growth Rate
  - PEG < 1.0: Potentially undervalued
  - PEG 1.0-2.0: Fairly valued
  - PEG > 2.0: Potentially overvalued
- **Earnings growth** consistency
- **Debt levels** < 35% of assets
- **Inventory** not growing faster than sales

## Stock Categories
- **Slow Growers**: 2-4% growth, dividend focus
- **Stalwarts**: 10-12% growth, steady performers
- **Fast Growers**: 20-50% growth, Lynch's favorites
- **Cyclicals**: Tied to economic cycles
- **Turnarounds**: Recovering from troubles
- **Asset Plays**: Hidden asset value

## Signal Interpretation
- **Bullish**: Low PEG, strong growth, reasonable debt
- **Neutral**: Fair PEG, moderate growth
- **Bearish**: High PEG, slowing growth, or high debt

## Example
```
Analyze AAPL as of 2024-12-01 using Peter Lynch's methodology.
```
