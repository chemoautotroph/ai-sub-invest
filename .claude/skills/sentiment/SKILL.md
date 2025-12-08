---
name: sentiment
description: Analyze market sentiment including insider trades, institutional ownership, and social signals. Use when gauging market psychology or smart money movements.
---

# Sentiment Analysis

## Overview
Analyze market sentiment through insider activity and institutional signals.

## Analysis Process

### Run Sentiment Analysis
```bash
python .claude/skills/sentiment/scripts/analyze.py {TICKER} {END_DATE}
```

## Signals Analyzed

### Insider Activity
- Recent buy/sell transactions
- Net insider position changes
- Executive trading patterns

### Fundamental Sentiment
- Valuation sentiment (P/E, P/B levels)
- Growth expectations
- Quality metrics

## Key Indicators
- **Insider buying** = Bullish signal
- **Heavy insider selling** = Bearish signal
- **Low valuation + quality** = Positive sentiment

## Signal Interpretation
- **Bullish**: Net insider buying, undervaluation signals
- **Neutral**: Mixed or no significant activity
- **Bearish**: Heavy insider selling, overvaluation signals

## Example
```
Analyze AAPL as of 2024-12-01 for sentiment signals.
```
