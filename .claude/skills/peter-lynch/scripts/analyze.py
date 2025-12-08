#!/usr/bin/env python3
"""Peter Lynch style stock analysis - GARP methodology."""
import sys
import json

sys.path.insert(0, '.')

from src.tools.api import get_financial_metrics, get_market_cap, search_line_items


def calculate_peg_ratio(metrics: list) -> dict:
    """Calculate PEG ratio - Lynch's key metric."""
    if not metrics:
        return {"peg": None, "score": 0, "max_score": 5, "details": "Insufficient data"}

    latest = metrics[0]
    pe_ratio = latest.price_to_earnings_ratio
    earnings_growth = latest.earnings_growth

    if not pe_ratio or not earnings_growth or earnings_growth <= 0:
        return {"peg": None, "score": 0, "max_score": 5, "details": "Cannot calculate PEG - missing P/E or growth data"}

    peg = pe_ratio / (earnings_growth * 100)  # Growth as percentage

    score = 0
    if peg < 0.5:
        score = 5
        details = f"Excellent PEG of {peg:.2f} - significantly undervalued for growth"
    elif peg < 1.0:
        score = 4
        details = f"Good PEG of {peg:.2f} - undervalued relative to growth"
    elif peg < 1.5:
        score = 3
        details = f"Fair PEG of {peg:.2f} - reasonably valued"
    elif peg < 2.0:
        score = 1
        details = f"High PEG of {peg:.2f} - getting expensive"
    else:
        score = 0
        details = f"Very high PEG of {peg:.2f} - overvalued for growth rate"

    return {"peg": peg, "score": score, "max_score": 5, "pe_ratio": pe_ratio,
            "earnings_growth": earnings_growth, "details": details}


def classify_stock_category(metrics: list) -> dict:
    """Classify stock into Lynch's categories."""
    if not metrics:
        return {"category": "unknown", "details": "Insufficient data"}

    latest = metrics[0]
    earnings_growth = latest.earnings_growth

    if not earnings_growth:
        # Try to calculate from historical data
        if len(metrics) >= 2 and metrics[0].earnings_per_share and metrics[-1].earnings_per_share:
            years = len(metrics) - 1
            if metrics[-1].earnings_per_share > 0:
                earnings_growth = ((metrics[0].earnings_per_share / metrics[-1].earnings_per_share) ** (1/years)) - 1

    if not earnings_growth:
        return {"category": "unknown", "details": "Cannot determine growth rate"}

    growth_pct = earnings_growth * 100

    if growth_pct < 5:
        category = "slow_grower"
        details = f"Slow Grower ({growth_pct:.1f}% growth) - focus on dividend yield"
    elif growth_pct < 15:
        category = "stalwart"
        details = f"Stalwart ({growth_pct:.1f}% growth) - steady performer, good for stability"
    elif growth_pct < 50:
        category = "fast_grower"
        details = f"Fast Grower ({growth_pct:.1f}% growth) - Lynch's favorite category"
    else:
        category = "fast_grower"
        details = f"Aggressive Fast Grower ({growth_pct:.1f}% growth) - high potential but verify sustainability"

    return {"category": category, "growth_rate": growth_pct, "details": details}


def analyze_growth_sustainability(metrics: list) -> dict:
    """Analyze if growth is sustainable."""
    if not metrics or len(metrics) < 3:
        return {"score": 0, "max_score": 5, "details": "Insufficient data for growth analysis"}

    score = 0
    details = []

    # Revenue growth consistency
    revenues = [m.revenue_growth for m in metrics if m.revenue_growth is not None]
    if len(revenues) >= 3:
        positive_growth = sum(1 for r in revenues if r > 0)
        if positive_growth == len(revenues):
            score += 2
            details.append("Consistent revenue growth across all periods")
        elif positive_growth >= len(revenues) * 0.7:
            score += 1
            details.append("Generally positive revenue growth")

    # Earnings growth consistency
    eps_values = [m.earnings_per_share for m in metrics if m.earnings_per_share is not None]
    if len(eps_values) >= 3:
        growth_periods = sum(1 for i in range(len(eps_values)-1) if eps_values[i] > eps_values[i+1])
        if growth_periods >= len(eps_values) - 2:
            score += 2
            details.append("Consistent earnings growth")
        elif growth_periods >= (len(eps_values) - 1) * 0.6:
            score += 1
            details.append("Generally growing earnings")

    # Margin expansion
    margins = [m.net_margin for m in metrics if m.net_margin is not None]
    if len(margins) >= 2:
        if margins[0] > margins[-1]:
            score += 1
            details.append("Expanding profit margins - positive sign")

    return {"score": score, "max_score": 5, "details": "; ".join(details) if details else "Limited growth data"}


def analyze_financial_health(metrics: list, line_items: list) -> dict:
    """Lynch's financial health checks."""
    if not metrics:
        return {"score": 0, "max_score": 5, "details": "No data"}

    score = 0
    details = []
    latest = metrics[0]

    # Debt check (Lynch prefers < 35% debt-to-assets)
    if latest.debt_to_equity is not None:
        if latest.debt_to_equity < 0.35:
            score += 2
            details.append(f"Low debt ({latest.debt_to_equity:.1%}) - Lynch approved")
        elif latest.debt_to_equity < 0.5:
            score += 1
            details.append(f"Moderate debt ({latest.debt_to_equity:.1%})")
        else:
            details.append(f"High debt ({latest.debt_to_equity:.1%}) - concern")

    # Current ratio
    if latest.current_ratio is not None:
        if latest.current_ratio > 2.0:
            score += 1
            details.append("Strong liquidity position")
        elif latest.current_ratio > 1.5:
            score += 0.5
            details.append("Adequate liquidity")

    # Free cash flow positive
    if latest.free_cash_flow_per_share and latest.free_cash_flow_per_share > 0:
        score += 1
        details.append("Positive free cash flow")

    # Insider ownership (if we had that data)
    # Lynch loves when insiders own shares

    return {"score": int(score), "max_score": 5, "details": "; ".join(details) if details else "Limited financial data"}


def generate_signal(analysis_data: dict) -> dict:
    """Generate Lynch-style signal."""
    peg_score = analysis_data["peg"]["score"]
    growth_score = analysis_data["growth"]["score"]
    health_score = analysis_data["health"]["score"]

    total_score = peg_score + growth_score + health_score
    max_score = 15

    category = analysis_data["category"]["category"]

    # Lynch loves fast growers with low PEG
    bonus = 0
    if category == "fast_grower" and analysis_data["peg"]["peg"] and analysis_data["peg"]["peg"] < 1.0:
        bonus = 2  # Bonus for Lynch's ideal scenario

    final_score = total_score + bonus
    score_pct = final_score / (max_score + 2) if max_score > 0 else 0

    if score_pct >= 0.7:
        signal = "bullish"
        confidence = min(90, int(score_pct * 100))
    elif score_pct <= 0.35:
        signal = "bearish"
        confidence = min(75, int((1 - score_pct) * 100))
    else:
        signal = "neutral"
        confidence = 50 + int(abs(score_pct - 0.5) * 30)

    return {"signal": signal, "confidence": confidence, "score": total_score, "max_score": max_score}


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: analyze.py TICKER END_DATE")
        print("Example: analyze.py AAPL 2024-12-01")
        sys.exit(1)

    ticker = sys.argv[1]
    end_date = sys.argv[2]

    metrics = get_financial_metrics(ticker, end_date, "ttm", 10)
    market_cap = get_market_cap(ticker, end_date)

    peg = calculate_peg_ratio(metrics)
    category = classify_stock_category(metrics)
    growth = analyze_growth_sustainability(metrics)
    health = analyze_financial_health(metrics, [])

    analysis_data = {
        "peg": peg,
        "category": category,
        "growth": growth,
        "health": health,
    }

    signal_data = generate_signal(analysis_data)

    result = {
        "ticker": ticker,
        "signal": signal_data["signal"],
        "confidence": signal_data["confidence"],
        "score": signal_data["score"],
        "max_score": signal_data["max_score"],
        "peg_analysis": peg,
        "stock_category": category,
        "growth_sustainability": growth,
        "financial_health": health,
        "market_cap": market_cap,
    }

    print(json.dumps(result, indent=2, default=str))
