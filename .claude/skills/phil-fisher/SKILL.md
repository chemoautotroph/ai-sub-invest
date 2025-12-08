---
name: phil-fisher
description: Analyze stocks using Phil Fisher's scuttlebutt method and 15-point checklist. Use when evaluating growth companies, R&D investment, or management quality.
---

# Phil Fisher Investment Analysis

## Investment Philosophy
I analyze stocks using Phil Fisher's principles:
1. **Scuttlebutt Method**: Research through industry sources
2. **15-Point Checklist**: Comprehensive quality assessment
3. **Long-term Growth**: Hold excellent companies forever
4. **Management Quality**: Critical success factor
5. **R&D Focus**: Innovation drives growth

## Analysis Process

### Run Fisher Analysis
```bash
python .claude/skills/phil-fisher/scripts/analyze.py {TICKER} {END_DATE}
```

## 15-Point Checklist (Key Items)
1. Does company have products with sufficient market potential?
2. Does management have determination to develop new products?
3. How effective is R&D relative to company size?
4. Does company have above-average sales organization?
5. Does company have worthwhile profit margin?
6. What is company doing to maintain/improve margins?
7. Does company have outstanding labor relations?
8. Does company have outstanding executive relations?
9. Does company have depth of management?
10. How good is cost analysis and accounting controls?
11. Are there other aspects that give competitive edge?
12. Does company have short-term or long-term outlook?
13. Will growth require equity financing that dilutes existing shares?
14. Does management talk freely when things are going well but clam up when trouble?
15. Does company have management of unquestionable integrity?

## Signal Interpretation
- **Bullish**: Meets most checklist items, strong R&D, quality management
- **Neutral**: Mixed checklist results
- **Bearish**: Fails key checklist items

## Example
```
Analyze AAPL as of 2024-12-01 using Phil Fisher's methodology.
```
