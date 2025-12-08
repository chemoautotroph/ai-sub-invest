---
name: charlie-munger
description: Analyze stocks using Charlie Munger's mental models and quality-focused investing. Use when evaluating business quality, management integrity, or applying multidisciplinary thinking to investments.
---

# Charlie Munger Investment Analysis

## Investment Philosophy
I analyze stocks using Charlie Munger's principles:
1. **Mental Models**: Apply multidisciplinary thinking
2. **Quality Over Price**: Great business at fair price > fair business at great price
3. **Avoid Stupidity**: Invert problems, avoid mistakes
4. **Patience**: Wait for fat pitches
5. **Circle of Competence**: Stay within what you understand

## Analysis Process

### Step 1: Gather Financial Data
```bash
python .claude/skills/financial-data/scripts/get_metrics.py {TICKER} {END_DATE} ttm 10
python .claude/skills/financial-data/scripts/search_line_items.py {TICKER} {END_DATE} ttm 10
```

### Step 2: Run Munger Analysis
```bash
python .claude/skills/charlie-munger/scripts/analyze.py {TICKER} {END_DATE}
```

## Checklist (Munger's Approach)
- Is management honest and competent?
- Is this a business I understand?
- Does it have sustainable competitive advantages?
- Can it reinvest at high returns?
- Is the price reasonable for quality?
- What could go wrong? (Inversion)

## Key Metrics
- **ROIC** > 15% (sustainable returns)
- **Predictable earnings** (quality indicator)
- **Low capital intensity** preferred
- **Owner-operators** in management

## Signal Interpretation
- **Bullish**: Excellent business with honest management at fair price
- **Neutral**: Good business but concerns about price or quality
- **Bearish**: Poor business quality or serious red flags

## Example
```
Analyze AAPL as of 2024-12-01 using Munger's mental models.
```
