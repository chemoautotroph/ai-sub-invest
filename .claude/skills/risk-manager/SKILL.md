---
name: risk-manager
description: Apply risk management rules to trading decisions including position sizing and portfolio constraints. Use when sizing positions or validating trades against risk limits.
---

# Risk Management

## Overview
Volatility-adjusted position sizing and portfolio risk constraints.

## Analysis Process

### Run Risk Analysis
```bash
python .claude/skills/risk-manager/scripts/calculate.py {TICKER} {START_DATE} {END_DATE} {PORTFOLIO_VALUE}
```

## Risk Rules

### Position Sizing
- Max position size: 20% of portfolio
- Max single trade: 10% of available cash
- Volatility-adjusted sizing

### Risk Limits
- Low volatility (<15%): Up to 25% allocation
- Medium volatility (15-30%): 15-20% allocation
- High volatility (>30%): 10-15% allocation
- Very high volatility (>50%): Max 10% allocation

### Portfolio Constraints
- Maintain cash buffer: 10% minimum
- Correlation limits for diversification
- Sector concentration limits

## Output
- Position limits per ticker
- Recommended position sizes
- Risk warnings if any

## Example
```
Calculate position limits for AAPL with $100,000 portfolio.
```
