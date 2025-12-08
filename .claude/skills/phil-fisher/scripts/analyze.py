#!/usr/bin/env python3
"""Phil Fisher style stock analysis - Growth and Quality focus."""
import sys
import json

sys.path.insert(0, '.')

from src.tools.api import get_financial_metrics, get_market_cap, search_line_items


def analyze_growth_potential(metrics: list) -> dict:
    """Assess market potential and growth trajectory."""
    if not metrics or len(metrics) < 3:
        return {"score": 0, "max_score": 5, "details": "Insufficient data"}

    score = 0
    details = []

    # Revenue growth trend
    revenues = [m.revenue_growth for m in metrics if m.revenue_growth is not None]
    if len(revenues) >= 3:
        avg_growth = sum(revenues) / len(revenues)
        if avg_growth > 0.15:
            score += 2
            details.append(f"Strong revenue growth ({avg_growth:.1%} avg) - market potential exists")
        elif avg_growth > 0.08:
            score += 1
            details.append(f"Moderate revenue growth ({avg_growth:.1%} avg)")
        else:
            details.append(f"Low revenue growth ({avg_growth:.1%} avg)")

    # Growth consistency
    if len(revenues) >= 3:
        positive_periods = sum(1 for r in revenues if r > 0)
        if positive_periods == len(revenues):
            score += 2
            details.append("Consistent positive growth - Fisher likes this")
        elif positive_periods >= len(revenues) * 0.7:
            score += 1
            details.append("Generally positive growth trend")

    # Acceleration check
    if len(revenues) >= 4:
        recent = sum(revenues[:2]) / 2
        older = sum(revenues[-2:]) / 2
        if recent > older:
            score += 1
            details.append("Growth is accelerating - positive sign")

    return {"score": min(score, 5), "max_score": 5, "details": "; ".join(details) if details else "Limited data"}


def analyze_profit_margins(metrics: list) -> dict:
    """Fisher's emphasis on profit margin quality and improvement."""
    if not metrics or len(metrics) < 3:
        return {"score": 0, "max_score": 5, "details": "Insufficient data"}

    score = 0
    details = []

    # Operating margin level
    margins = [m.operating_margin for m in metrics if m.operating_margin is not None]
    if len(margins) >= 2:
        avg_margin = sum(margins) / len(margins)
        if avg_margin > 0.20:
            score += 2
            details.append(f"Excellent operating margins ({avg_margin:.1%}) - worthwhile profits")
        elif avg_margin > 0.12:
            score += 1
            details.append(f"Good operating margins ({avg_margin:.1%})")

    # Margin improvement trend
    if len(margins) >= 3:
        if margins[0] > margins[-1]:
            score += 2
            details.append("Improving margins - management doing something right")
        elif margins[0] >= margins[-1] * 0.95:
            score += 1
            details.append("Stable margins maintained")
        else:
            details.append("Declining margins - potential concern")

    # Gross margin stability
    gross_margins = [m.gross_margin for m in metrics if m.gross_margin is not None]
    if len(gross_margins) >= 2:
        variance = sum((m - sum(gross_margins)/len(gross_margins))**2 for m in gross_margins) / len(gross_margins)
        if variance < 0.01:
            score += 1
            details.append("Very stable gross margins - strong competitive position")

    return {"score": min(score, 5), "max_score": 5, "details": "; ".join(details) if details else "Limited data"}


def analyze_management_quality(line_items: list, metrics: list) -> dict:
    """Fisher's management quality assessment (15-point checklist elements)."""
    if not metrics:
        return {"score": 0, "max_score": 5, "details": "Insufficient data"}

    score = 0
    details = []

    # Long-term orientation (consistent R&D, capex investment)
    if line_items and len(line_items) >= 2:
        latest = line_items[0]
        if hasattr(latest, 'capital_expenditure') and latest.capital_expenditure:
            score += 1
            details.append("Investing in capital expenditure - long-term focus")

    # Dilution check (Fisher hates dilution)
    if line_items and len(line_items) >= 3:
        shares = [item.outstanding_shares for item in line_items if hasattr(item, 'outstanding_shares') and item.outstanding_shares]
        if len(shares) >= 2:
            if shares[0] <= shares[-1]:
                score += 2
                details.append("No share dilution - shareholder-friendly management")
            elif shares[0] < shares[-1] * 1.05:
                score += 1
                details.append("Minimal dilution")
            else:
                details.append("Significant dilution - concern for existing shareholders")

    # Consistent returns (management execution)
    if metrics and len(metrics) >= 3:
        roes = [m.return_on_equity for m in metrics if m.return_on_equity is not None]
        if len(roes) >= 3:
            if all(r > 0.12 for r in roes):
                score += 2
                details.append("Consistently high ROE - good management execution")
            elif sum(1 for r in roes if r > 0.10) >= len(roes) * 0.7:
                score += 1
                details.append("Generally solid returns")

    return {"score": min(score, 5), "max_score": 5, "details": "; ".join(details) if details else "Limited data"}


def analyze_competitive_position(metrics: list) -> dict:
    """Assess sustainable competitive advantages."""
    if not metrics or len(metrics) < 3:
        return {"score": 0, "max_score": 5, "details": "Insufficient data"}

    score = 0
    details = []

    # Market position (inferred from margin stability)
    margins = [m.gross_margin for m in metrics if m.gross_margin is not None]
    if len(margins) >= 3:
        avg = sum(margins) / len(margins)
        if avg > 0.45 and all(m > 0.40 for m in margins):
            score += 3
            details.append("Consistently high gross margins indicate strong competitive position")
        elif avg > 0.35:
            score += 1
            details.append("Decent gross margins")

    # Asset efficiency
    latest = metrics[0]
    if latest.asset_turnover and latest.asset_turnover > 0.8:
        score += 1
        details.append("Efficient asset utilization")

    # Returns sustainability
    roics = [m.return_on_invested_capital for m in metrics if m.return_on_invested_capital is not None]
    if len(roics) >= 3:
        if all(r > 0.15 for r in roics):
            score += 1
            details.append("Sustained high ROIC - durable advantage")

    return {"score": min(score, 5), "max_score": 5, "details": "; ".join(details) if details else "Limited data"}


def generate_signal(analysis_data: dict) -> dict:
    """Generate Fisher-style signal."""
    total_score = (
        analysis_data["growth"]["score"] +
        analysis_data["margins"]["score"] +
        analysis_data["management"]["score"] +
        analysis_data["competitive"]["score"]
    )
    max_score = 20

    score_pct = total_score / max_score if max_score > 0 else 0

    if score_pct >= 0.7:
        signal = "bullish"
        confidence = min(85, int(score_pct * 100))
    elif score_pct <= 0.35:
        signal = "bearish"
        confidence = min(75, int((1 - score_pct) * 100))
    else:
        signal = "neutral"
        confidence = 50

    return {"signal": signal, "confidence": confidence, "score": total_score, "max_score": max_score}


LINE_ITEMS = [
    "capital_expenditure",
    "outstanding_shares",
    "net_income",
    "revenue",
]


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: analyze.py TICKER END_DATE")
        print("Example: analyze.py AAPL 2024-12-01")
        sys.exit(1)

    ticker = sys.argv[1]
    end_date = sys.argv[2]

    metrics = get_financial_metrics(ticker, end_date, "ttm", 10)
    market_cap = get_market_cap(ticker, end_date)
    line_items = search_line_items(ticker, LINE_ITEMS, end_date, "ttm", 10)

    growth = analyze_growth_potential(metrics)
    margins = analyze_profit_margins(metrics)
    management = analyze_management_quality(line_items, metrics)
    competitive = analyze_competitive_position(metrics)

    analysis_data = {
        "growth": growth,
        "margins": margins,
        "management": management,
        "competitive": competitive,
    }

    signal_data = generate_signal(analysis_data)

    result = {
        "ticker": ticker,
        "signal": signal_data["signal"],
        "confidence": signal_data["confidence"],
        "score": signal_data["score"],
        "max_score": signal_data["max_score"],
        "growth_potential": growth,
        "profit_margins": margins,
        "management_quality": management,
        "competitive_position": competitive,
        "market_cap": market_cap,
    }

    print(json.dumps(result, indent=2, default=str))
