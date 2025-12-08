---
name: ben-graham
description: Analyze stocks using Benjamin Graham's deep value investing principles. Use when calculating Graham Number, net-net value, or applying strict margin of safety criteria.
---

# Benjamin Graham Investment Analysis

## Investment Philosophy
I analyze stocks using Benjamin Graham's classic value principles:
1. **Margin of Safety**: Never pay full price
2. **Net-Net Investing**: Buy below net current asset value
3. **Graham Number**: Conservative valuation formula
4. **Mr. Market**: Exploit market irrationality
5. **Defensive Investing**: Focus on safety over speculation

## Analysis Process

### Step 1: Gather Financial Data
```bash
python .claude/skills/financial-data/scripts/get_metrics.py {TICKER} {END_DATE} annual 10
python .claude/skills/financial-data/scripts/search_line_items.py {TICKER} {END_DATE} annual 10
python .claude/skills/financial-data/scripts/get_market_cap.py {TICKER} {END_DATE}
```

### Step 2: Run Graham Analysis
```bash
python .claude/skills/ben-graham/scripts/analyze.py {TICKER} {END_DATE}
```

## Key Metrics
- **Graham Number** = √(22.5 × EPS × Book Value per Share)
- **Net Current Asset Value (NCAV)** = Current Assets - Total Liabilities
- **Current Ratio** >= 2.0 (required for defensive investor)
- **Debt/Equity** < 1.0
- **Positive earnings** for 10+ years
- **Dividend record** preferred

## Signal Interpretation
- **Bullish**: NCAV > Market Cap, or price well below Graham Number with >=50% margin
- **Neutral**: Some margin of safety but not compelling
- **Bearish**: Price above Graham Number, weak financials

## Example
```
Analyze AAPL as of 2024-12-01 using Graham's principles.
```
