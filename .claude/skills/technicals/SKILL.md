---
name: technicals
description: Perform technical analysis on stocks including chart patterns, indicators, and momentum signals. Use when analyzing price trends, support/resistance, or timing entries/exits.
---

# Technical Analysis

## Overview
Multi-strategy technical analysis combining trend following, mean reversion, momentum, volatility, and statistical signals.

## Analysis Process

### Run Technical Analysis
```bash
python .claude/skills/technicals/scripts/analyze.py {TICKER} {START_DATE} {END_DATE}
```

## Indicators Calculated

### Trend Following
- EMA 8, 21, 55
- ADX (Average Directional Index)
- Trend direction and strength

### Mean Reversion
- Bollinger Bands
- Z-Score from 50-day MA
- RSI (14, 28 periods)

### Momentum
- 1/3/6 month returns
- Volume momentum
- Price momentum score

### Volatility
- Historical volatility
- Volatility regime
- ATR ratio

### Statistical
- Hurst exponent
- Skewness/Kurtosis
- Mean reversion tendency

## Signal Interpretation
- **Bullish**: Price above key MAs, RSI rising, positive MACD, bullish momentum
- **Bearish**: Price below key MAs, RSI falling, negative MACD, bearish momentum
- **Neutral**: Mixed signals, consolidation pattern

## Example
```
Analyze AAPL from 2024-06-01 to 2024-12-01 using technical analysis.
```
