#!/usr/bin/env python3
"""Charlie Munger style stock analysis - Quality and Mental Models."""
import sys
import json

sys.path.insert(0, '.')

from src.tools.api import get_financial_metrics, get_market_cap, search_line_items


def analyze_business_quality(metrics: list) -> dict:
    """Assess business quality using Munger's criteria."""
    if not metrics or len(metrics) < 3:
        return {"score": 0, "max_score": 10, "details": "Insufficient data"}

    score = 0
    details = []

    # ROIC consistency (Munger's favorite)
    roics = [m.return_on_invested_capital for m in metrics if m.return_on_invested_capital is not None]
    roes = [m.return_on_equity for m in metrics if m.return_on_equity is not None]

    returns = roics if len(roics) >= 3 else roes

    if len(returns) >= 3:
        avg_return = sum(returns) / len(returns)
        high_returns = sum(1 for r in returns if r > 0.15)

        if avg_return > 0.20 and high_returns >= len(returns) * 0.8:
            score += 4
            details.append(f"Excellent returns on capital (avg: {avg_return:.1%}) - Munger loves this")
        elif avg_return > 0.15:
            score += 2
            details.append(f"Good returns on capital (avg: {avg_return:.1%})")
        else:
            details.append(f"Mediocre returns on capital (avg: {avg_return:.1%})")

    # Margin stability (predictable business)
    margins = [m.operating_margin for m in metrics if m.operating_margin is not None]
    if len(margins) >= 3:
        avg_margin = sum(margins) / len(margins)
        variance = sum((m - avg_margin) ** 2 for m in margins) / len(margins)
        stability = 1 - (variance ** 0.5) / avg_margin if avg_margin > 0 else 0

        if stability > 0.8 and avg_margin > 0.20:
            score += 3
            details.append(f"Highly predictable margins ({avg_margin:.1%} avg) - quality business")
        elif stability > 0.6:
            score += 1
            details.append(f"Reasonably stable margins")

    # Low debt (Munger prefers conservative balance sheets)
    latest = metrics[0]
    if latest.debt_to_equity is not None:
        if latest.debt_to_equity < 0.3:
            score += 2
            details.append("Conservative debt levels - Munger approved")
        elif latest.debt_to_equity < 0.5:
            score += 1
            details.append("Moderate debt levels")
        else:
            details.append("High debt - potential concern")

    # Strong cash generation
    if latest.free_cash_flow_per_share and latest.earnings_per_share:
        fcf_to_earnings = latest.free_cash_flow_per_share / latest.earnings_per_share
        if fcf_to_earnings > 1.0:
            score += 1
            details.append("Strong free cash flow conversion")

    return {"score": score, "max_score": 10, "details": "; ".join(details)}


def analyze_management_quality(line_items: list, metrics: list) -> dict:
    """Assess management using Munger's criteria."""
    if not line_items:
        return {"score": 0, "max_score": 5, "details": "Insufficient data"}

    score = 0
    details = []

    latest = line_items[0]

    # Share buybacks (returning capital to shareholders)
    if hasattr(latest, "issuance_or_purchase_of_equity_shares"):
        if latest.issuance_or_purchase_of_equity_shares and latest.issuance_or_purchase_of_equity_shares < 0:
            score += 2
            details.append("Repurchasing shares - shareholder-aligned management")
        elif latest.issuance_or_purchase_of_equity_shares and latest.issuance_or_purchase_of_equity_shares > 0:
            details.append("Issuing shares - watch for dilution")

    # Dividend consistency
    if hasattr(latest, "dividends_and_other_cash_distributions"):
        if latest.dividends_and_other_cash_distributions and latest.dividends_and_other_cash_distributions < 0:
            score += 1
            details.append("Paying dividends consistently")

    # Capital allocation (ROE trend)
    if metrics and len(metrics) >= 3:
        roes = [m.return_on_equity for m in metrics if m.return_on_equity is not None]
        if len(roes) >= 3:
            recent_roe = sum(roes[:2]) / 2 if len(roes) >= 2 else roes[0]
            older_roe = sum(roes[-2:]) / 2 if len(roes) >= 2 else roes[-1]
            if recent_roe >= older_roe:
                score += 2
                details.append("Improving or stable ROE - good capital allocation")

    return {"score": score, "max_score": 5, "details": "; ".join(details)}


def analyze_moat_strength(metrics: list) -> dict:
    """Analyze competitive moat using Munger's framework."""
    if not metrics or len(metrics) < 5:
        return {"score": 0, "max_score": 5, "details": "Insufficient data for moat analysis"}

    score = 0
    details = []

    # Consistent high margins indicate pricing power
    margins = [m.gross_margin for m in metrics if m.gross_margin is not None]
    if len(margins) >= 5:
        avg_margin = sum(margins) / len(margins)
        if avg_margin > 0.5:
            score += 2
            details.append(f"Exceptional gross margins ({avg_margin:.1%}) suggest strong moat")
        elif avg_margin > 0.35:
            score += 1
            details.append(f"Good gross margins ({avg_margin:.1%})")

    # ROE consistency (durable advantage)
    roes = [m.return_on_equity for m in metrics if m.return_on_equity is not None]
    if len(roes) >= 5:
        high_roe_count = sum(1 for r in roes if r > 0.15)
        if high_roe_count >= len(roes) * 0.9:
            score += 3
            details.append("Consistently high ROE indicates durable competitive advantage")
        elif high_roe_count >= len(roes) * 0.7:
            score += 1
            details.append("Generally good ROE")

    return {"score": score, "max_score": 5, "details": "; ".join(details)}


def apply_inversion_checklist(metrics: list, line_items: list) -> dict:
    """Munger's inversion: What could go wrong?"""
    red_flags = []
    concerns = 0

    if metrics:
        latest = metrics[0]

        # High debt
        if latest.debt_to_equity and latest.debt_to_equity > 1.0:
            red_flags.append("High leverage - bankruptcy risk in downturns")
            concerns += 2

        # Declining margins
        if len(metrics) >= 3:
            margins = [m.operating_margin for m in metrics if m.operating_margin is not None]
            if len(margins) >= 3 and margins[0] < margins[-1] * 0.8:
                red_flags.append("Declining operating margins - competitive pressure")
                concerns += 1

        # Negative FCF
        if latest.free_cash_flow_per_share and latest.free_cash_flow_per_share < 0:
            red_flags.append("Negative free cash flow - cash burn concern")
            concerns += 1

    if line_items:
        latest = line_items[0]
        # Significant dilution
        if hasattr(latest, "outstanding_shares") and len(line_items) >= 2:
            older = line_items[-1]
            if hasattr(older, "outstanding_shares") and older.outstanding_shares:
                if latest.outstanding_shares and latest.outstanding_shares > older.outstanding_shares * 1.1:
                    red_flags.append("Significant share dilution")
                    concerns += 1

    return {
        "concerns": concerns,
        "red_flags": red_flags if red_flags else ["No major red flags identified"],
        "passed": concerns < 2
    }


def generate_signal(analysis_data: dict) -> dict:
    """Generate Munger-style signal."""
    total_score = (
        analysis_data["quality"]["score"] +
        analysis_data["management"]["score"] +
        analysis_data["moat"]["score"]
    )

    max_score = (
        analysis_data["quality"]["max_score"] +
        analysis_data["management"]["max_score"] +
        analysis_data["moat"]["max_score"]
    )

    # Reduce score if inversion found concerns
    if not analysis_data["inversion"]["passed"]:
        total_score = int(total_score * 0.7)

    score_pct = total_score / max_score if max_score > 0 else 0

    if score_pct >= 0.7 and analysis_data["inversion"]["passed"]:
        signal = "bullish"
        confidence = min(85, int(score_pct * 100))
    elif score_pct <= 0.35 or analysis_data["inversion"]["concerns"] >= 3:
        signal = "bearish"
        confidence = min(80, int((1 - score_pct) * 100))
    else:
        signal = "neutral"
        confidence = 50

    return {"signal": signal, "confidence": confidence, "score": total_score, "max_score": max_score}


LINE_ITEMS = [
    "net_income",
    "outstanding_shares",
    "shareholders_equity",
    "dividends_and_other_cash_distributions",
    "issuance_or_purchase_of_equity_shares",
    "free_cash_flow",
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

    quality = analyze_business_quality(metrics)
    management = analyze_management_quality(line_items, metrics)
    moat = analyze_moat_strength(metrics)
    inversion = apply_inversion_checklist(metrics, line_items)

    analysis_data = {
        "quality": quality,
        "management": management,
        "moat": moat,
        "inversion": inversion,
    }

    signal_data = generate_signal(analysis_data)

    result = {
        "ticker": ticker,
        "signal": signal_data["signal"],
        "confidence": signal_data["confidence"],
        "score": signal_data["score"],
        "max_score": signal_data["max_score"],
        "business_quality": quality,
        "management_quality": management,
        "moat_analysis": moat,
        "inversion_checklist": inversion,
        "market_cap": market_cap,
    }

    print(json.dumps(result, indent=2, default=str))
