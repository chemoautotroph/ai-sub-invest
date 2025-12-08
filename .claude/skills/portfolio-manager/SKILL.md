---
name: portfolio-manager
description: Make final trading decisions by aggregating analyst signals and applying portfolio strategy. Use when making buy/sell decisions or generating trading recommendations.
---

# Portfolio Manager

## Overview
Aggregates analyst signals and generates final trading decisions with risk management.

## Analysis Process

### Step 1: Collect Analyst Signals
Run relevant analyst skills for each ticker:
- warren-buffett, ben-graham, fundamentals
- technicals, valuation, sentiment
- Any other relevant analysts

### Step 2: Aggregate Signals
```bash
python .claude/skills/portfolio-manager/scripts/aggregate.py '{signals_json}'
```

## Decision Framework

### Signal Aggregation
- Weight signals by analyst type and confidence
- Combine into consensus recommendation

### Position Actions
- **Strong Buy**: 4+ bullish signals, avg confidence >70%
- **Buy**: 3+ bullish signals, avg confidence >60%
- **Hold**: Mixed signals or low confidence
- **Sell**: 3+ bearish signals, avg confidence >60%
- **Strong Sell**: 4+ bearish signals, avg confidence >70%

### Risk Constraints
- Max position size: 20% of portfolio
- Max single trade: 10% of cash
- Maintain cash buffer: 10%

## Output Format
```json
{
  "ticker": "AAPL",
  "action": "buy",
  "quantity": 100,
  "reasoning": "Strong consensus bullish signal",
  "confidence": 75
}
```

## Example
```
Aggregate signals for AAPL and generate trading decision.
```
