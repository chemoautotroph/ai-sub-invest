---
name: warren-buffett
description: Analyze stocks using Warren Buffett's value investing principles. Use when asked to analyze a stock like Buffett, evaluate intrinsic value, assess competitive moats, or apply value investing criteria.
---

# Warren Buffett Investment Analysis

## Investment Philosophy
I analyze stocks using Warren Buffett's core principles:
1. **Circle of Competence**: Only invest in businesses I understand
2. **Competitive Moat**: Look for durable competitive advantages
3. **Management Quality**: Assess capital allocation and integrity
4. **Margin of Safety**: Buy below intrinsic value
5. **Long-term Focus**: Think like a business owner

## Analysis Process

### Step 1: Gather Financial Data
Use the financial-data skill to fetch metrics:
```bash
python .claude/skills/financial-data/scripts/get_metrics.py {TICKER} {END_DATE} ttm 10
python .claude/skills/financial-data/scripts/search_line_items.py {TICKER} {END_DATE} ttm 10
python .claude/skills/financial-data/scripts/get_market_cap.py {TICKER} {END_DATE}
```

### Step 2: Run Buffett Analysis
```bash
python .claude/skills/warren-buffett/scripts/analyze.py {TICKER} {END_DATE}
```

### Step 3: Interpret Results
The analysis evaluates:
- **ROE Consistency**: >15% for 5+ years indicates moat
- **Debt Levels**: Debt/Equity <0.5 preferred
- **Margin Stability**: Operating margin >15%
- **Owner Earnings**: True earnings power via DCF
- **Intrinsic Value**: Conservative 3-stage DCF model
- **Book Value Growth**: Consistent BVPS appreciation
- **Pricing Power**: Ability to maintain/expand margins
- **Management Quality**: Share buybacks, dividends, capital allocation

## Signal Interpretation
- **Bullish**: Strong business with margin of safety >0
- **Neutral**: Good business but fairly/over valued
- **Bearish**: Weak moat or significantly overvalued

## Key Metrics Thresholds
| Metric | Bullish | Neutral | Bearish |
|--------|---------|---------|---------|
| ROE | >15% | 10-15% | <10% |
| Debt/Equity | <0.5 | 0.5-1.0 | >1.0 |
| Operating Margin | >15% | 10-15% | <10% |
| Margin of Safety | >20% | 0-20% | <0% |

## Example
```
Analyze AAPL as of 2024-12-01 using Buffett's principles.
```
