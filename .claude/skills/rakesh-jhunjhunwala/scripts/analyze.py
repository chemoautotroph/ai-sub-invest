#!/usr/bin/env python3
"""Rakesh Jhunjhunwala style analysis - Growth with Macro awareness."""
import sys
import json

sys.path.insert(0, '.')

from src.tools.api import get_financial_metrics, get_market_cap, search_line_items


def analyze_growth_trajectory(metrics: list) -> dict:
    """Jhunjhunwala loves sustainable growth stories."""
    if not metrics or len(metrics) < 3:
        return {"score": 0, "max_score": 5, "details": "Insufficient data"}

    score = 0
    details = []

    # Revenue growth consistency
    rev_growth = [m.revenue_growth for m in metrics if m.revenue_growth is not None]
    if len(rev_growth) >= 3:
        avg_growth = sum(rev_growth) / len(rev_growth)
        if avg_growth > 0.20:
            score += 2
            details.append(f"Strong revenue growth ({avg_growth:.1%} avg)")
        elif avg_growth > 0.12:
            score += 1
            details.append(f"Good revenue growth ({avg_growth:.1%} avg)")

        # Consistency check
        if all(r > 0.08 for r in rev_growth):
            score += 1
            details.append("Consistent growth - compounding story")

    # Earnings growth
    earn_growth = [m.earnings_growth for m in metrics if m.earnings_growth is not None]
    if len(earn_growth) >= 2:
        if earn_growth[0] > 0.15:
            score += 2
            details.append(f"Strong earnings growth ({earn_growth[0]:.1%})")

    return {"score": min(score, 5), "max_score": 5, "details": "; ".join(details) if details else "Limited growth data"}


def analyze_quality_metrics(metrics: list) -> dict:
    """Quality of earnings and returns."""
    if not metrics:
        return {"score": 0, "max_score": 4, "details": "Insufficient data"}

    score = 0
    details = []
    latest = metrics[0]

    # ROE quality
    roes = [m.return_on_equity for m in metrics if m.return_on_equity is not None]
    if len(roes) >= 2:
        avg_roe = sum(roes) / len(roes)
        if avg_roe > 0.18:
            score += 2
            details.append(f"Excellent ROE ({avg_roe:.1%}) - quality compounder")
        elif avg_roe > 0.12:
            score += 1
            details.append(f"Good ROE ({avg_roe:.1%})")

    # Margin quality
    if latest.operating_margin and latest.operating_margin > 0.15:
        score += 1
        details.append("Strong operating margins")

    # Cash conversion
    if latest.free_cash_flow_per_share and latest.earnings_per_share:
        if latest.free_cash_flow_per_share > latest.earnings_per_share * 0.8:
            score += 1
            details.append("Good cash conversion")

    return {"score": min(score, 4), "max_score": 4, "details": "; ".join(details) if details else "Limited quality data"}


def analyze_valuation(metrics: list) -> dict:
    """Jhunjhunwala wants growth at reasonable price."""
    if not metrics:
        return {"score": 0, "max_score": 4, "details": "Insufficient data"}

    score = 0
    details = []
    latest = metrics[0]

    # PEG ratio
    if latest.price_to_earnings_ratio and latest.earnings_growth and latest.earnings_growth > 0:
        peg = latest.price_to_earnings_ratio / (latest.earnings_growth * 100)
        if peg < 1.0:
            score += 3
            details.append(f"Excellent PEG ({peg:.2f}) - growth at value")
        elif peg < 1.5:
            score += 2
            details.append(f"Reasonable PEG ({peg:.2f})")
        elif peg < 2.0:
            score += 1
            details.append(f"Fair PEG ({peg:.2f})")
        else:
            details.append(f"High PEG ({peg:.2f}) - expensive")

    # P/E reasonableness
    if latest.price_to_earnings_ratio:
        pe = latest.price_to_earnings_ratio
        if pe < 20:
            score += 1
            details.append(f"Moderate P/E ({pe:.1f})")
        elif pe > 40:
            details.append(f"Very high P/E ({pe:.1f}) - needs high growth")

    return {"score": min(score, 4), "max_score": 4, "details": "; ".join(details) if details else "Valuation unclear"}


def analyze_financial_stability(metrics: list) -> dict:
    """Balance sheet strength for long-term holding."""
    if not metrics:
        return {"score": 0, "max_score": 2, "details": "Insufficient data"}

    score = 0
    details = []
    latest = metrics[0]

    # Debt levels
    if latest.debt_to_equity and latest.debt_to_equity < 0.5:
        score += 1
        details.append("Low leverage - stable compounder")

    # Liquidity
    if latest.current_ratio and latest.current_ratio > 1.5:
        score += 1
        details.append("Strong liquidity")

    return {"score": score, "max_score": 2, "details": "; ".join(details) if details else "Review financials"}


def generate_signal(analysis_data: dict) -> dict:
    """Generate Jhunjhunwala-style growth signal."""
    growth = analysis_data["growth"]["score"]
    quality = analysis_data["quality"]["score"]
    valuation = analysis_data["valuation"]["score"]
    stability = analysis_data["stability"]["score"]

    total = growth + quality + valuation + stability
    max_total = 15

    score_pct = total / max_total

    # Jhunjhunwala wants growth AND reasonable valuation
    has_growth = growth >= 3
    has_valuation = valuation >= 2
    has_quality = quality >= 2

    if score_pct >= 0.60 and has_growth and has_valuation:
        signal = "bullish"
        confidence = min(85, int(score_pct * 100))
    elif score_pct <= 0.35 or (not has_growth):
        signal = "bearish"
        confidence = min(75, int((1 - score_pct) * 100))
    else:
        signal = "neutral"
        confidence = 50

    return {"signal": signal, "confidence": confidence, "score": total, "max_score": max_total}


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: analyze.py TICKER END_DATE")
        print("Example: analyze.py TITAN 2024-12-01")
        sys.exit(1)

    ticker = sys.argv[1]
    end_date = sys.argv[2]

    metrics = get_financial_metrics(ticker, end_date, "ttm", 10)
    market_cap = get_market_cap(ticker, end_date)

    growth = analyze_growth_trajectory(metrics)
    quality = analyze_quality_metrics(metrics)
    valuation = analyze_valuation(metrics)
    stability = analyze_financial_stability(metrics)

    analysis_data = {
        "growth": growth,
        "quality": quality,
        "valuation": valuation,
        "stability": stability,
    }

    signal_data = generate_signal(analysis_data)

    result = {
        "ticker": ticker,
        "signal": signal_data["signal"],
        "confidence": signal_data["confidence"],
        "score": signal_data["score"],
        "max_score": signal_data["max_score"],
        "growth_trajectory": growth,
        "quality_metrics": quality,
        "valuation": valuation,
        "financial_stability": stability,
        "market_cap": market_cap,
    }

    print(json.dumps(result, indent=2, default=str))
