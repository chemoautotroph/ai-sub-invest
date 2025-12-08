#!/usr/bin/env python3
"""Mohnish Pabrai style analysis - Dhandho framework."""
import sys
import json

sys.path.insert(0, '.')

from src.tools.api import get_financial_metrics, get_market_cap, search_line_items


def analyze_downside_protection(metrics: list, line_items: list, market_cap: float) -> dict:
    """Assess downside protection - key Dhandho principle."""
    if not metrics:
        return {"score": 0, "max_score": 5, "details": "Insufficient data"}

    score = 0
    details = []
    latest = metrics[0]

    # Balance sheet strength
    if latest.current_ratio and latest.current_ratio > 2.0:
        score += 1
        details.append("Strong liquidity provides downside protection")

    if latest.debt_to_equity and latest.debt_to_equity < 0.3:
        score += 2
        details.append("Low debt - minimal bankruptcy risk")
    elif latest.debt_to_equity and latest.debt_to_equity < 0.5:
        score += 1
        details.append("Moderate debt levels")

    # Asset backing
    if line_items:
        latest_li = line_items[0]
        if hasattr(latest_li, 'total_assets') and hasattr(latest_li, 'total_liabilities'):
            if latest_li.total_assets and latest_li.total_liabilities and market_cap:
                net_assets = latest_li.total_assets - latest_li.total_liabilities
                if net_assets > market_cap * 0.5:
                    score += 1
                    details.append("Significant asset backing relative to market cap")

    # Profitability floor
    if latest.net_margin and latest.net_margin > 0.10:
        score += 1
        details.append("Healthy margins provide earnings cushion")

    return {"score": min(score, 5), "max_score": 5, "details": "; ".join(details) if details else "Limited data"}


def analyze_upside_potential(metrics: list, market_cap: float) -> dict:
    """Assess upside potential for asymmetric payoff."""
    if not metrics:
        return {"score": 0, "max_score": 5, "details": "Insufficient data"}

    score = 0
    details = []
    latest = metrics[0]

    # Valuation relative to growth
    if latest.price_to_earnings_ratio and latest.earnings_growth:
        peg = latest.price_to_earnings_ratio / (latest.earnings_growth * 100) if latest.earnings_growth > 0 else None
        if peg and peg < 0.8:
            score += 2
            details.append(f"Low PEG ({peg:.2f}) suggests significant upside")
        elif peg and peg < 1.2:
            score += 1
            details.append(f"Reasonable PEG ({peg:.2f})")

    # Growth trajectory
    if latest.earnings_growth and latest.earnings_growth > 0.15:
        score += 2
        details.append(f"Strong growth ({latest.earnings_growth:.1%}) provides upside catalyst")
    elif latest.earnings_growth and latest.earnings_growth > 0.08:
        score += 1
        details.append(f"Moderate growth ({latest.earnings_growth:.1%})")

    # Return on capital (value creation)
    if latest.return_on_equity and latest.return_on_equity > 0.20:
        score += 1
        details.append("High ROE indicates value creation potential")

    return {"score": min(score, 5), "max_score": 5, "details": "; ".join(details) if details else "Limited data"}


def analyze_business_simplicity(metrics: list) -> dict:
    """Pabrai prefers simple, understandable businesses."""
    if not metrics:
        return {"score": 0, "max_score": 3, "details": "Insufficient data"}

    score = 0
    details = []
    latest = metrics[0]

    # Stable margins suggest predictable business
    if len(metrics) >= 3:
        margins = [m.operating_margin for m in metrics if m.operating_margin is not None]
        if len(margins) >= 3:
            avg = sum(margins) / len(margins)
            variance = sum((m - avg) ** 2 for m in margins) / len(margins)
            if variance < 0.005:
                score += 2
                details.append("Very stable margins - predictable business model")
            elif variance < 0.01:
                score += 1
                details.append("Reasonably stable margins")

    # Consistent returns
    roes = [m.return_on_equity for m in metrics if m.return_on_equity is not None]
    if len(roes) >= 3:
        if all(r > 0.10 for r in roes):
            score += 1
            details.append("Consistent profitability - easy to understand")

    return {"score": min(score, 3), "max_score": 3, "details": "; ".join(details) if details else "Limited data"}


def analyze_owner_operators(line_items: list) -> dict:
    """Check for owner-operator characteristics."""
    if not line_items:
        return {"score": 0, "max_score": 2, "details": "Insufficient data"}

    score = 0
    details = []

    latest = line_items[0]

    # Buybacks indicate owner mindset
    if hasattr(latest, 'issuance_or_purchase_of_equity_shares'):
        if latest.issuance_or_purchase_of_equity_shares and latest.issuance_or_purchase_of_equity_shares < 0:
            score += 1
            details.append("Share buybacks suggest owner-operator mindset")

    # Dividends (returning capital)
    if hasattr(latest, 'dividends_and_other_cash_distributions'):
        if latest.dividends_and_other_cash_distributions and latest.dividends_and_other_cash_distributions < 0:
            score += 1
            details.append("Dividend payments - shareholder friendly")

    return {"score": score, "max_score": 2, "details": "; ".join(details) if details else "Limited insider data"}


def generate_signal(analysis_data: dict) -> dict:
    """Generate Dhandho signal - asymmetric risk/reward focus."""
    downside = analysis_data["downside"]["score"]
    upside = analysis_data["upside"]["score"]
    simplicity = analysis_data["simplicity"]["score"]
    owners = analysis_data["owners"]["score"]

    total = downside + upside + simplicity + owners
    max_total = 15

    # Dhandho requires BOTH low downside AND high upside
    asymmetry_check = downside >= 3 and upside >= 3

    score_pct = total / max_total

    if score_pct >= 0.65 and asymmetry_check:
        signal = "bullish"
        confidence = min(85, int(score_pct * 100))
    elif score_pct <= 0.35 or (downside < 2):
        signal = "bearish"
        confidence = min(75, int((1 - score_pct) * 100))
    else:
        signal = "neutral"
        confidence = 50

    return {"signal": signal, "confidence": confidence, "score": total, "max_score": max_total}


LINE_ITEMS = [
    "total_assets",
    "total_liabilities",
    "outstanding_shares",
    "issuance_or_purchase_of_equity_shares",
    "dividends_and_other_cash_distributions",
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

    downside = analyze_downside_protection(metrics, line_items, market_cap)
    upside = analyze_upside_potential(metrics, market_cap)
    simplicity = analyze_business_simplicity(metrics)
    owners = analyze_owner_operators(line_items)

    analysis_data = {
        "downside": downside,
        "upside": upside,
        "simplicity": simplicity,
        "owners": owners,
    }

    signal_data = generate_signal(analysis_data)

    result = {
        "ticker": ticker,
        "signal": signal_data["signal"],
        "confidence": signal_data["confidence"],
        "score": signal_data["score"],
        "max_score": signal_data["max_score"],
        "downside_protection": downside,
        "upside_potential": upside,
        "business_simplicity": simplicity,
        "owner_operators": owners,
        "market_cap": market_cap,
    }

    print(json.dumps(result, indent=2, default=str))
