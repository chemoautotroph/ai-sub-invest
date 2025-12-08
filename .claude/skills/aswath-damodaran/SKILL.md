---
name: aswath-damodaran
description: Analyze stocks using Aswath Damodaran's rigorous valuation methodology. Use when performing detailed DCF analysis, comparing valuation models, or understanding fair value.
---

# Aswath Damodaran Valuation Analysis

## Investment Philosophy
1. **Valuation is Storytelling**: Numbers must tell a consistent story
2. **Multiple Models**: DCF, relative valuation, option pricing
3. **Risk-Adjusted Returns**: Understand cost of capital
4. **No Sacred Cows**: Question every assumption
5. **Value vs Price**: Know the difference

## Analysis Process

### Run Damodaran Analysis
```bash
python .claude/skills/aswath-damodaran/scripts/analyze.py {TICKER} {END_DATE}
```

## Valuation Models
- **Intrinsic DCF** (FCFF/FCFE)
- **Relative Valuation** (EV/EBITDA, P/E comps)
- **Sum-of-Parts** for conglomerates
- **Real Options** for growth companies

## Key Concepts
- **Cost of Capital**: Risk-adjusted discount rate
- **Terminal Value**: Long-term growth assumptions
- **Reinvestment Rate**: Growth sustainability
- **Margin of Safety**: Valuation gap

## Signal Interpretation
- **Bullish**: Significant undervaluation across models
- **Neutral**: Fair value or mixed signals
- **Bearish**: Overvaluation or unrealistic expectations priced in

## Example
```
Analyze AAPL as of 2024-12-01 using Damodaran's valuation methods.
```
