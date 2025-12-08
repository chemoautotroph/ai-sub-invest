#!/usr/bin/env python3
"""Bill Ackman style analysis - Activist Value Investing."""
import sys
import json

sys.path.insert(0, '.')

from src.tools.api import get_financial_metrics, get_market_cap, search_line_items


def analyze_business_quality(metrics: list) -> dict:
    """Ackman loves simple, predictable businesses."""
    if not metrics or len(metrics) < 3:
        return {"score": 0, "max_score": 5, "details": "Insufficient data"}

    score = 0
    details = []

    # Predictable margins
    margins = [m.operating_margin for m in metrics if m.operating_margin is not None]
    if len(margins) >= 3:
        avg = sum(margins) / len(margins)
        variance = sum((m - avg) ** 2 for m in margins) / len(margins)
        if variance < 0.005 and avg > 0.15:
            score += 3
            details.append(f"Very predictable high margins ({avg:.1%}) - Ackman loves this")
        elif variance < 0.01:
            score += 1
            details.append("Reasonably stable margins")

    # Strong returns
    roes = [m.return_on_equity for m in metrics if m.return_on_equity is not None]
    if len(roes) >= 2:
        avg_roe = sum(roes) / len(roes)
        if avg_roe > 0.20:
            score += 2
            details.append(f"Excellent ROE ({avg_roe:.1%}) - quality business")

    return {"score": min(score, 5), "max_score": 5, "details": "; ".join(details) if details else "Limited data"}


def analyze_value_opportunity(metrics: list, market_cap: float) -> dict:
    """Assess undervaluation and activist opportunity."""
    if not metrics:
        return {"score": 0, "max_score": 5, "details": "Insufficient data"}

    score = 0
    details = []
    latest = metrics[0]

    # Valuation discount
    if latest.price_to_earnings_ratio:
        pe = latest.price_to_earnings_ratio
        if pe < 12:
            score += 2
            details.append(f"Low P/E ({pe:.1f}) - potential value opportunity")
        elif pe < 18:
            score += 1
            details.append(f"Reasonable P/E ({pe:.1f})")

    # FCF yield
    if latest.free_cash_flow_per_share and latest.earnings_per_share:
        fcf_to_eps = latest.free_cash_flow_per_share / latest.earnings_per_share
        if fcf_to_eps > 1.0:
            score += 1
            details.append("Strong FCF conversion - cash generating")

    # Margin improvement potential
    if len(metrics) >= 3:
        margins = [m.operating_margin for m in metrics if m.operating_margin is not None]
        if len(margins) >= 2:
            if margins[0] < max(margins):
                score += 2
                potential = max(margins) - margins[0]
                details.append(f"Margin improvement potential ({potential:.1%}) - activist opportunity")

    return {"score": min(score, 5), "max_score": 5, "details": "; ".join(details) if details else "Limited data"}


def analyze_capital_allocation(line_items: list, metrics: list) -> dict:
    """Assess capital allocation - key activist focus."""
    if not line_items and not metrics:
        return {"score": 0, "max_score": 3, "details": "Insufficient data"}

    score = 0
    details = []

    # Share buybacks (shareholder return)
    if line_items:
        latest = line_items[0]
        if hasattr(latest, 'issuance_or_purchase_of_equity_shares'):
            if latest.issuance_or_purchase_of_equity_shares and latest.issuance_or_purchase_of_equity_shares < 0:
                score += 1
                details.append("Repurchasing shares - returning capital")

    # Dividend
    if line_items:
        latest = line_items[0]
        if hasattr(latest, 'dividends_and_other_cash_distributions'):
            if latest.dividends_and_other_cash_distributions and latest.dividends_and_other_cash_distributions < 0:
                score += 1
                details.append("Paying dividends")

    # ROE trend (efficient capital use)
    if metrics and len(metrics) >= 2:
        roes = [m.return_on_equity for m in metrics if m.return_on_equity is not None]
        if len(roes) >= 2:
            if roes[0] > roes[-1]:
                score += 1
                details.append("Improving ROE - better capital allocation")

    return {"score": min(score, 3), "max_score": 3, "details": "; ".join(details) if details else "Limited data"}


def analyze_downside_protection(metrics: list) -> dict:
    """Ackman wants limited downside risk."""
    if not metrics:
        return {"score": 0, "max_score": 2, "details": "Insufficient data"}

    score = 0
    details = []
    latest = metrics[0]

    # Balance sheet strength
    if latest.debt_to_equity and latest.debt_to_equity < 0.5:
        score += 1
        details.append("Conservative leverage - limited downside")

    if latest.current_ratio and latest.current_ratio > 1.5:
        score += 1
        details.append("Strong liquidity position")

    return {"score": score, "max_score": 2, "details": "; ".join(details) if details else "Limited data"}


def generate_signal(analysis_data: dict) -> dict:
    """Generate Ackman-style signal."""
    quality = analysis_data["quality"]["score"]
    value = analysis_data["value"]["score"]
    capital = analysis_data["capital"]["score"]
    downside = analysis_data["downside"]["score"]

    total = quality + value + capital + downside
    max_total = 15

    score_pct = total / max_total

    # Ackman wants quality AND value AND downside protection
    has_quality = quality >= 3
    has_value = value >= 3
    has_protection = downside >= 1

    if score_pct >= 0.60 and has_quality and has_value:
        signal = "bullish"
        confidence = min(85, int(score_pct * 100))
    elif score_pct <= 0.35 or (not has_quality and not has_value):
        signal = "bearish"
        confidence = min(75, int((1 - score_pct) * 100))
    else:
        signal = "neutral"
        confidence = 50

    return {"signal": signal, "confidence": confidence, "score": total, "max_score": max_total}


LINE_ITEMS = [
    "issuance_or_purchase_of_equity_shares",
    "dividends_and_other_cash_distributions",
    "net_income",
]


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: analyze.py TICKER END_DATE")
        print("Example: analyze.py CMG 2024-12-01")
        sys.exit(1)

    ticker = sys.argv[1]
    end_date = sys.argv[2]

    metrics = get_financial_metrics(ticker, end_date, "ttm", 10)
    market_cap = get_market_cap(ticker, end_date)
    line_items = search_line_items(ticker, LINE_ITEMS, end_date, "ttm", 10)

    quality = analyze_business_quality(metrics)
    value = analyze_value_opportunity(metrics, market_cap)
    capital = analyze_capital_allocation(line_items, metrics)
    downside = analyze_downside_protection(metrics)

    analysis_data = {
        "quality": quality,
        "value": value,
        "capital": capital,
        "downside": downside,
    }

    signal_data = generate_signal(analysis_data)

    result = {
        "ticker": ticker,
        "signal": signal_data["signal"],
        "confidence": signal_data["confidence"],
        "score": signal_data["score"],
        "max_score": signal_data["max_score"],
        "business_quality": quality,
        "value_opportunity": value,
        "capital_allocation": capital,
        "downside_protection": downside,
        "market_cap": market_cap,
    }

    print(json.dumps(result, indent=2, default=str))
