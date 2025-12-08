---
name: news-sentiment
description: Analyze recent news and determine sentiment impact on stock. Use when evaluating news flow, media coverage, or event-driven situations.
---

# News Sentiment Analysis

## Overview
Analyze recent company news to gauge sentiment and identify catalysts.

## Analysis Process

### Run News Sentiment Analysis
```bash
python .claude/skills/news-sentiment/scripts/analyze.py {TICKER} {END_DATE}
```

## Process
1. Fetches recent company news
2. Analyzes sentiment of headlines
3. Identifies key themes
4. Aggregates into overall sentiment score

## Key Outputs
- News count and recency
- Sentiment distribution
- Key themes identified
- Overall sentiment score

## Signal Interpretation
- **Bullish**: Positive news flow, catalysts emerging
- **Neutral**: Mixed or routine news
- **Bearish**: Negative news, concerns raised

## Example
```
Analyze AAPL as of 2024-12-01 for recent news sentiment.
```
