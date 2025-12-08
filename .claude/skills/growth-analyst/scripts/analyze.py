#!/usr/bin/env python3
"""Growth analysis focusing on revenue, earnings, and margin trends."""
import sys
import json

sys.path.insert(0, '.')

from src.tools.api import get_financial_metrics


def analyze_revenue_growth(metrics: list) -> dict:
    """Analyze revenue growth trajectory."""
    if not metrics or len(metrics) < 2:
        return {"score": 0, "max_score": 5, "details": "Insufficient data"}

    score = 0
    details = []

    rev_growth = [m.revenue_growth for m in metrics if m.revenue_growth is not None]

    if not rev_growth:
        return {"score": 0, "max_score": 5, "details": "No revenue growth data"}

    latest = rev_growth[0]

    # Growth rate scoring
    if latest > 0.30:
        score += 3
        details.append(f"Exceptional revenue growth: {latest:.1%}")
    elif latest > 0.15:
        score += 2
        details.append(f"Strong revenue growth: {latest:.1%}")
    elif latest > 0.08:
        score += 1
        details.append(f"Moderate revenue growth: {latest:.1%}")
    elif latest < 0:
        details.append(f"Revenue decline: {latest:.1%}")

    # Acceleration check
    if len(rev_growth) >= 2:
        if rev_growth[0] > rev_growth[1]:
            score += 1
            details.append("Revenue growth accelerating")
        elif rev_growth[0] < rev_growth[1] * 0.8:
            details.append("Revenue growth decelerating")

    # Consistency
    if len(rev_growth) >= 3 and all(r > 0 for r in rev_growth[:3]):
        score += 1
        details.append("Consistent positive growth")

    return {"score": min(score, 5), "max_score": 5, "latest_growth": latest, "details": "; ".join(details)}


def analyze_earnings_growth(metrics: list) -> dict:
    """Analyze earnings growth trajectory."""
    if not metrics or len(metrics) < 2:
        return {"score": 0, "max_score": 5, "details": "Insufficient data"}

    score = 0
    details = []

    earn_growth = [m.earnings_growth for m in metrics if m.earnings_growth is not None]

    if not earn_growth:
        return {"score": 0, "max_score": 5, "details": "No earnings growth data"}

    latest = earn_growth[0]

    # Growth rate scoring
    if latest > 0.25:
        score += 3
        details.append(f"Exceptional earnings growth: {latest:.1%}")
    elif latest > 0.12:
        score += 2
        details.append(f"Strong earnings growth: {latest:.1%}")
    elif latest > 0.05:
        score += 1
        details.append(f"Moderate earnings growth: {latest:.1%}")
    elif latest < 0:
        details.append(f"Earnings decline: {latest:.1%}")

    # Earnings vs revenue (operating leverage)
    if metrics[0].revenue_growth and latest > metrics[0].revenue_growth:
        score += 1
        details.append("Positive operating leverage (earnings growing faster than revenue)")

    # Consistency
    if len(earn_growth) >= 2 and earn_growth[0] > earn_growth[1] > 0:
        score += 1
        details.append("Accelerating earnings growth")

    return {"score": min(score, 5), "max_score": 5, "latest_growth": latest, "details": "; ".join(details)}


def analyze_margin_trends(metrics: list) -> dict:
    """Analyze margin expansion/contraction."""
    if not metrics or len(metrics) < 2:
        return {"score": 0, "max_score": 5, "details": "Insufficient data"}

    score = 0
    details = []

    # Gross margin trend
    gross_margins = [m.gross_margin for m in metrics if m.gross_margin is not None]
    if len(gross_margins) >= 2:
        if gross_margins[0] > gross_margins[-1]:
            score += 1
            delta = gross_margins[0] - gross_margins[-1]
            details.append(f"Gross margin expanding (+{delta:.1%})")
        elif gross_margins[0] < gross_margins[-1] * 0.95:
            details.append("Gross margin contracting")

    # Operating margin trend
    op_margins = [m.operating_margin for m in metrics if m.operating_margin is not None]
    if len(op_margins) >= 2:
        if op_margins[0] > op_margins[-1]:
            score += 2
            delta = op_margins[0] - op_margins[-1]
            details.append(f"Operating margin expanding (+{delta:.1%})")
        elif op_margins[0] < op_margins[-1] * 0.9:
            details.append("Operating margin contracting")

    # Absolute margin quality
    if op_margins and op_margins[0] > 0.20:
        score += 1
        details.append(f"High operating margin: {op_margins[0]:.1%}")

    # Net margin improvement
    net_margins = [m.net_margin for m in metrics if m.net_margin is not None]
    if len(net_margins) >= 2 and net_margins[0] > net_margins[-1]:
        score += 1
        details.append("Net margin improving")

    return {"score": min(score, 5), "max_score": 5, "details": "; ".join(details) if details else "No margin data"}


def analyze_growth_sustainability(metrics: list) -> dict:
    """Analyze if growth is sustainable."""
    if not metrics:
        return {"score": 0, "max_score": 5, "details": "Insufficient data"}

    score = 0
    details = []
    latest = metrics[0]

    # ROIC/ROE (reinvestment returns)
    if latest.return_on_equity and latest.return_on_equity > 0.18:
        score += 2
        details.append(f"High ROE ({latest.return_on_equity:.1%}) supports sustainable growth")
    elif latest.return_on_equity and latest.return_on_equity > 0.12:
        score += 1
        details.append(f"Decent ROE ({latest.return_on_equity:.1%})")

    # Balance sheet support
    if latest.debt_to_equity and latest.debt_to_equity < 0.5:
        score += 1
        details.append("Low debt supports growth investment")

    # FCF positive (self-funding growth)
    if latest.free_cash_flow_per_share and latest.free_cash_flow_per_share > 0:
        score += 1
        details.append("Positive FCF - growth is self-funding")

    # Consistent returns
    if len(metrics) >= 3:
        roes = [m.return_on_equity for m in metrics if m.return_on_equity is not None]
        if len(roes) >= 3 and all(r > 0.12 for r in roes):
            score += 1
            details.append("Consistent high returns")

    return {"score": min(score, 5), "max_score": 5, "details": "; ".join(details) if details else "Limited data"}


def generate_signal(analysis: dict) -> dict:
    """Generate overall growth signal."""
    revenue = analysis["revenue"]["score"]
    earnings = analysis["earnings"]["score"]
    margins = analysis["margins"]["score"]
    sustainability = analysis["sustainability"]["score"]

    total = revenue + earnings + margins + sustainability
    max_total = 20

    score_pct = total / max_total

    if score_pct >= 0.65:
        signal = "bullish"
        confidence = min(85, int(score_pct * 100))
    elif score_pct <= 0.35:
        signal = "bearish"
        confidence = min(75, int((1 - score_pct) * 100))
    else:
        signal = "neutral"
        confidence = 50

    return {"signal": signal, "confidence": confidence, "score": total, "max_score": max_total}


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: analyze.py TICKER END_DATE")
        print("Example: analyze.py NVDA 2024-12-01")
        sys.exit(1)

    ticker = sys.argv[1]
    end_date = sys.argv[2]

    metrics = get_financial_metrics(ticker, end_date, "ttm", 10)

    revenue = analyze_revenue_growth(metrics)
    earnings = analyze_earnings_growth(metrics)
    margins = analyze_margin_trends(metrics)
    sustainability = analyze_growth_sustainability(metrics)

    analysis = {
        "revenue": revenue,
        "earnings": earnings,
        "margins": margins,
        "sustainability": sustainability,
    }

    overall = generate_signal(analysis)

    result = {
        "ticker": ticker,
        "signal": overall["signal"],
        "confidence": overall["confidence"],
        "score": overall["score"],
        "max_score": overall["max_score"],
        "revenue_growth": revenue,
        "earnings_growth": earnings,
        "margin_trends": margins,
        "growth_sustainability": sustainability,
    }

    print(json.dumps(result, indent=2, default=str))
