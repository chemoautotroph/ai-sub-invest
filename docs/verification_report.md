# Free Backend Verification Report

**Run date**: 2026-04-26
**Matrix**: 5 tickers × 7 personas = 35 cases
**End date used**: 2026-04-26
**Confidence delta tolerance**: ≤ 30 pts

## Summary

- **PASS**: 24 / 35
- **PARTIAL**: 1
- **FAIL**: 0
- **SKIP** (paid degraded): 10

**Delivery thresholds**:

- *Absolute* (PASS ≥ 28 / 35, FAIL ≤ 3): **NOT MET**
- *Rate-based, SKIPs excluded from denominator* (PASS / (PASS+PARTIAL+FAIL) ≥ 80%, FAIL ≤ 3): 24 / 25 = 96% — **MET**

Spec § Phase 3 says "SKIP 不计入 PASS/FAIL 分母" so the rate-based view is the operational delivery gate. Absolute count is reported for transparency.

## Result Matrix

| Persona | NVDA | MSFT | AVGO | INTU | ZETA |
|---|:---:|:---:|:---:|:---:|:---:|
| `warren-buffett` | PASS | PASS | SKIP | SKIP | SKIP |
| `ben-graham` | PASS | PASS | PASS | PASS | PASS |
| `charlie-munger` | PASS | PASS | PASS | PASS | PASS |
| `stanley-druckenmiller` | PARTIAL | PASS | PASS | PASS | PASS |
| `fundamentals` | PASS | PASS | SKIP | SKIP | SKIP |
| `valuation` | PASS | PASS | PASS | PASS | PASS |
| `technicals` | PASS | SKIP | SKIP | SKIP | SKIP |

## Per-cell Detail

### `warren-buffett` / `NVDA` — PASS

- **Paid**: signal='neutral' confidence=60
- **Free**: signal='bearish' confidence=40
  - reasoning: [fundamentals] Strong ROE of 76.3%; Conservative debt levels; Strong operating margins; Good liquidity position
- _Note_: signals differ (neutral vs bearish) but conf delta = 20 ≤ 30 — close call either way

### `warren-buffett` / `MSFT` — PASS

- **Paid**: signal='neutral' confidence=55
- **Free**: signal='neutral' confidence=51
  - reasoning: [fundamentals] Strong ROE of 29.6%; Conservative debt levels; Operating margin data not available; Weak liquidity with current ratio of 1.4
- _Note_: signals match (neutral), conf delta = 4

### `warren-buffett` / `AVGO` — SKIP

- **Paid**: crashed (rc=1)
  - stderr tail: `KeyError: 'max_score'`
- **Free**: signal='bearish' confidence=80
  - reasoning: [fundamentals] ROE data not available; Debt to equity data not available; Operating margin data not available; Weak liquidity with current ratio of 1.2
- _Note_: paid backend crashed/no-data (rc=1)

### `warren-buffett` / `INTU` — SKIP

- **Paid**: crashed (rc=1)
  - stderr tail: `KeyError: 'max_score'`
- **Free**: signal='neutral' confidence=55
  - reasoning: [fundamentals] Strong ROE of 19.6%; Conservative debt levels; Strong operating margins; Weak liquidity with current ratio of 1.4
- _Note_: paid backend crashed/no-data (rc=1)

### `warren-buffett` / `ZETA` — SKIP

- **Paid**: crashed (rc=1)
  - stderr tail: `KeyError: 'max_score'`
- **Free**: signal='bearish' confidence=80
  - reasoning: [fundamentals] Weak ROE of -3.9%; Conservative debt levels; Weak operating margin of 0.4%; Good liquidity position
- _Note_: paid backend crashed/no-data (rc=1)

### `ben-graham` / `NVDA` — PASS

- **Paid**: signal='neutral' confidence=52
- **Free**: signal='neutral' confidence=52
  - reasoning: [earnings_stability] EPS was positive in all available periods; EPS grew from earliest to latest period
- _Note_: signals match (neutral), conf delta = 0

### `ben-graham` / `MSFT` — PASS

- **Paid**: signal='neutral' confidence=52
- **Free**: signal='neutral' confidence=52
  - reasoning: [earnings_stability] EPS was positive in all available periods; EPS grew from earliest to latest period
- _Note_: signals match (neutral), conf delta = 0

### `ben-graham` / `AVGO` — PASS

- **Paid**: signal='bearish' confidence=80
- **Free**: signal='neutral' confidence=57
  - reasoning: [earnings_stability] EPS was positive in all available periods; EPS did not grow from earliest to latest period
- _Note_: signals differ (bearish vs neutral) but conf delta = 23 ≤ 30 — close call either way

### `ben-graham` / `INTU` — PASS

- **Paid**: signal='bearish' confidence=80
- **Free**: signal='neutral' confidence=52
  - reasoning: [earnings_stability] EPS was positive in all available periods; EPS grew from earliest to latest period
- _Note_: signals differ (bearish vs neutral) but conf delta = 28 ≤ 30 — close call either way

### `ben-graham` / `ZETA` — PASS

- **Paid**: signal='bearish' confidence=80
- **Free**: signal='bearish' confidence=75
  - reasoning: [earnings_stability] EPS was negative in multiple periods; EPS grew from earliest to latest period
- _Note_: signals match (bearish), conf delta = 5

### `charlie-munger` / `NVDA` — PASS

- **Paid**: signal='bullish' confidence=80
- **Free**: signal='bullish' confidence=75
  - reasoning: [business_quality] Excellent returns on capital (avg: 29.0%) - Munger loves this; Reasonably stable margins; Conservative debt levels - Munger approved
- _Note_: signals match (bullish), conf delta = 5

### `charlie-munger` / `MSFT` — PASS

- **Paid**: signal='bullish' confidence=70
- **Free**: signal='neutral' confidence=50
  - reasoning: [business_quality] Good returns on capital (avg: 17.7%); Conservative debt levels - Munger approved
- _Note_: signals differ (bullish vs neutral) but conf delta = 20 ≤ 30 — close call either way

### `charlie-munger` / `AVGO` — PASS

- **Paid**: signal='bearish' confidence=80
- **Free**: signal='bearish' confidence=80
  - reasoning: [business_quality] Insufficient data
- _Note_: signals match (bearish), conf delta = 0

### `charlie-munger` / `INTU` — PASS

- **Paid**: signal='bearish' confidence=80
- **Free**: signal='neutral' confidence=50
  - reasoning: [business_quality] Good returns on capital (avg: 26.6%); Highly predictable margins (24.7% avg) - quality business; Moderate debt levels; Strong free cash flow conversion
- _Note_: signals differ (bearish vs neutral) but conf delta = 30 ≤ 30 — close call either way

### `charlie-munger` / `ZETA` — PASS

- **Paid**: signal='bearish' confidence=80
- **Free**: signal='bearish' confidence=80
  - reasoning: [business_quality] Mediocre returns on capital (avg: -35.8%); Conservative debt levels - Munger approved
- _Note_: signals match (bearish), conf delta = 0

### `stanley-druckenmiller` / `NVDA` — PARTIAL

- **Paid**: signal='neutral' confidence=50
- **Free**: signal='bullish' confidence=85
  - reasoning: [price_momentum] Strong 1M momentum (+21.6%); Positive 3M momentum (+11.7%); Price above rising moving averages - strong trend
- _Note_: signals differ (neutral vs bullish) AND conf delta = 35 > 30

### `stanley-druckenmiller` / `MSFT` — PASS

- **Paid**: signal='bearish' confidence=66
- **Free**: signal='neutral' confidence=50
  - reasoning: [price_momentum] Strong 1M momentum (+16.0%)
- _Note_: signals differ (bearish vs neutral) but conf delta = 16 ≤ 30 — close call either way

### `stanley-druckenmiller` / `AVGO` — PASS

- **Paid**: signal='bearish' confidence=75
- **Free**: signal='neutral' confidence=50
  - reasoning: [price_momentum] Strong 1M momentum (+36.6%); Strong 3M momentum (+30.4%); Price above rising moving averages - strong trend
- _Note_: signals differ (bearish vs neutral) but conf delta = 25 ≤ 30 — close call either way

### `stanley-druckenmiller` / `INTU` — PASS

- **Paid**: signal='bearish' confidence=75
- **Free**: signal='bearish' confidence=46
  - reasoning: [price_momentum] Neutral momentum
- _Note_: signals match (bearish), conf delta = 29

### `stanley-druckenmiller` / `ZETA` — PASS

- **Paid**: signal='bearish' confidence=75
- **Free**: signal='bearish' confidence=46
  - reasoning: [price_momentum] Positive 1M momentum (+9.0%)
- _Note_: signals match (bearish), conf delta = 29

### `fundamentals` / `NVDA` — PASS

- **Paid**: signal='bullish' confidence=75
- **Free**: signal='bullish' confidence=75
  - reasoning: [profitability_signal] ROE: 76.3%, Net Margin: 55.6%, Op Margin: 60.4%
- _Note_: signals match (bullish), conf delta = 0

### `fundamentals` / `MSFT` — PASS

- **Paid**: signal='bullish' confidence=50
- **Free**: signal='bearish' confidence=25
  - reasoning: [profitability_signal] ROE: 29.6%
- _Note_: signals differ (bullish vs bearish) but conf delta = 25 ≤ 30 — close call either way

### `fundamentals` / `AVGO` — SKIP

- **Paid**: signal='neutral' confidence=0
- **Free**: signal='bearish' confidence=50
  - reasoning: [profitability_signal] N/A
- _Note_: paid returned no-data signal (likely no API key)

### `fundamentals` / `INTU` — SKIP

- **Paid**: signal='neutral' confidence=0
- **Free**: signal='bullish' confidence=75
  - reasoning: [profitability_signal] ROE: 19.6%, Net Margin: 20.5%, Op Margin: 26.1%
- _Note_: paid returned no-data signal (likely no API key)

### `fundamentals` / `ZETA` — SKIP

- **Paid**: signal='neutral' confidence=0
- **Free**: signal='bullish' confidence=50
  - reasoning: [profitability_signal] ROE: -3.9%, Net Margin: -2.4%, Op Margin: 0.4%
- _Note_: paid returned no-data signal (likely no API key)

### `valuation` / `NVDA` — PASS

- **Paid**: signal='neutral' confidence=50
- **Free**: signal='bearish' confidence=80
  - reasoning: [dcf_valuation] DCF Value: $1,864,399,260,224
- _Note_: signals differ (neutral vs bearish) but conf delta = 30 ≤ 30 — close call either way

### `valuation` / `MSFT` — PASS

- **Paid**: signal='neutral' confidence=50
- **Free**: signal='bearish' confidence=80
  - reasoning: [dcf_valuation] DCF Value: $1,326,692,211,453
- _Note_: signals differ (neutral vs bearish) but conf delta = 30 ≤ 30 — close call either way

### `valuation` / `AVGO` — PASS

- **Paid**: signal='neutral' confidence=50
- **Free**: signal='bearish' confidence=80
  - reasoning: [dcf_valuation] DCF Value: $260,483,744,723
- _Note_: signals differ (neutral vs bearish) but conf delta = 30 ≤ 30 — close call either way

### `valuation` / `INTU` — PASS

- **Paid**: signal='neutral' confidence=50
- **Free**: signal='bearish' confidence=69
  - reasoning: [dcf_valuation] DCF Value: $118,082,219,686
- _Note_: signals differ (neutral vs bearish) but conf delta = 19 ≤ 30 — close call either way

### `valuation` / `ZETA` — PASS

- **Paid**: signal='neutral' confidence=50
- **Free**: signal='neutral' confidence=50
  - reasoning: [dcf_valuation] DCF Value: $3,569,407,773
- _Note_: signals match (neutral), conf delta = 0

### `technicals` / `NVDA` — PASS

- **Paid**: signal='neutral' confidence=15
- **Free**: signal='neutral' confidence=15
- _Note_: signals match (neutral), conf delta = 0

### `technicals` / `MSFT` — SKIP

- **Paid**: signal='neutral' confidence=0
- **Free**: signal='neutral' confidence=0
- _Note_: paid returned no-data signal (likely no API key)

### `technicals` / `AVGO` — SKIP

- **Paid**: crashed (rc=1)
- **Free**: signal='neutral' confidence=16
- _Note_: paid backend crashed/no-data (rc=1)

### `technicals` / `INTU` — SKIP

- **Paid**: crashed (rc=1)
- **Free**: signal='bearish' confidence=38
- _Note_: paid backend crashed/no-data (rc=1)

### `technicals` / `ZETA` — SKIP

- **Paid**: crashed (rc=1)
- **Free**: signal='neutral' confidence=0
- _Note_: paid backend crashed/no-data (rc=1)
