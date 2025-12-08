#!/usr/bin/env python3
"""Benjamin Graham style stock analysis."""
import sys
import json
import math

sys.path.insert(0, '.')

from src.tools.api import get_financial_metrics, get_market_cap, search_line_items


def analyze_earnings_stability(metrics: list, financial_line_items: list) -> dict:
    """Graham wants at least several years of consistently positive earnings."""
    score = 0
    details = []

    if not metrics or not financial_line_items:
        return {"score": score, "max_score": 4, "details": "Insufficient data for earnings stability analysis"}

    eps_vals = [item.earnings_per_share for item in financial_line_items if item.earnings_per_share is not None]

    if len(eps_vals) < 2:
        return {"score": score, "max_score": 4, "details": "Not enough multi-year EPS data"}

    # Consistently positive EPS
    positive_eps_years = sum(1 for e in eps_vals if e > 0)
    total_eps_years = len(eps_vals)

    if positive_eps_years == total_eps_years:
        score += 3
        details.append("EPS was positive in all available periods")
    elif positive_eps_years >= (total_eps_years * 0.8):
        score += 2
        details.append("EPS was positive in most periods")
    else:
        details.append("EPS was negative in multiple periods")

    # EPS growth
    if eps_vals[0] > eps_vals[-1]:
        score += 1
        details.append("EPS grew from earliest to latest period")
    else:
        details.append("EPS did not grow from earliest to latest period")

    return {"score": score, "max_score": 4, "details": "; ".join(details)}


def analyze_financial_strength(financial_line_items: list) -> dict:
    """Graham checks liquidity, debt levels, and dividend record."""
    score = 0
    details = []

    if not financial_line_items:
        return {"score": score, "max_score": 5, "details": "No data for financial strength analysis"}

    latest = financial_line_items[0]
    total_assets = latest.total_assets or 0
    total_liabilities = latest.total_liabilities or 0
    current_assets = latest.current_assets or 0
    current_liabilities = latest.current_liabilities or 0

    # Current ratio
    if current_liabilities > 0:
        current_ratio = current_assets / current_liabilities
        if current_ratio >= 2.0:
            score += 2
            details.append(f"Current ratio = {current_ratio:.2f} (>=2.0: solid)")
        elif current_ratio >= 1.5:
            score += 1
            details.append(f"Current ratio = {current_ratio:.2f} (moderately strong)")
        else:
            details.append(f"Current ratio = {current_ratio:.2f} (<1.5: weaker liquidity)")
    else:
        details.append("Cannot compute current ratio")

    # Debt vs Assets
    if total_assets > 0:
        debt_ratio = total_liabilities / total_assets
        if debt_ratio < 0.5:
            score += 2
            details.append(f"Debt ratio = {debt_ratio:.2f}, under 0.50 (conservative)")
        elif debt_ratio < 0.8:
            score += 1
            details.append(f"Debt ratio = {debt_ratio:.2f}, somewhat high")
        else:
            details.append(f"Debt ratio = {debt_ratio:.2f}, quite high by Graham standards")

    # Dividend track record
    div_periods = [item.dividends_and_other_cash_distributions for item in financial_line_items
                   if item.dividends_and_other_cash_distributions is not None]
    if div_periods:
        div_paid_years = sum(1 for d in div_periods if d < 0)
        if div_paid_years >= (len(div_periods) // 2 + 1):
            score += 1
            details.append("Company paid dividends in the majority of reported years")
        elif div_paid_years > 0:
            details.append("Company has some dividend payments")
        else:
            details.append("Company did not pay dividends")

    return {"score": score, "max_score": 5, "details": "; ".join(details)}


def analyze_valuation_graham(financial_line_items: list, market_cap: float) -> dict:
    """Core Graham valuation: Net-Net and Graham Number."""
    if not financial_line_items or not market_cap or market_cap <= 0:
        return {"score": 0, "max_score": 7, "details": "Insufficient data to perform valuation",
                "graham_number": None, "ncav": None, "margin_of_safety": None}

    latest = financial_line_items[0]
    current_assets = latest.current_assets or 0
    total_liabilities = latest.total_liabilities or 0
    book_value_ps = latest.book_value_per_share or 0
    eps = latest.earnings_per_share or 0
    shares_outstanding = latest.outstanding_shares or 0

    details = []
    score = 0

    # Net-Net Check
    ncav = current_assets - total_liabilities
    ncav_per_share = None
    price_per_share = market_cap / shares_outstanding if shares_outstanding > 0 else 0

    if ncav > 0 and shares_outstanding > 0:
        ncav_per_share = ncav / shares_outstanding
        details.append(f"Net Current Asset Value = ${ncav:,.0f}")
        details.append(f"NCAV Per Share = ${ncav_per_share:.2f}")
        details.append(f"Price Per Share = ${price_per_share:.2f}")

        if ncav > market_cap:
            score += 4
            details.append("Net-Net: NCAV > Market Cap (classic Graham deep value)")
        elif ncav_per_share >= (price_per_share * 0.67):
            score += 2
            details.append("NCAV Per Share >= 2/3 of Price Per Share (moderate net-net discount)")

    # Graham Number
    graham_number = None
    if eps > 0 and book_value_ps > 0:
        graham_number = math.sqrt(22.5 * eps * book_value_ps)
        details.append(f"Graham Number = ${graham_number:.2f}")

    # Margin of Safety relative to Graham Number
    margin_of_safety = None
    if graham_number and price_per_share > 0:
        margin_of_safety = (graham_number - price_per_share) / price_per_share
        details.append(f"Margin of Safety (Graham Number) = {margin_of_safety:.1%}")

        if margin_of_safety > 0.5:
            score += 3
            details.append("Price is well below Graham Number (>=50% margin)")
        elif margin_of_safety > 0.2:
            score += 1
            details.append("Some margin of safety relative to Graham Number")
        else:
            details.append("Price close to or above Graham Number, low margin of safety")

    return {
        "score": score,
        "max_score": 7,
        "details": "; ".join(details),
        "graham_number": graham_number,
        "ncav": ncav,
        "ncav_per_share": ncav_per_share,
        "margin_of_safety": margin_of_safety
    }


def generate_signal(analysis_data: dict) -> dict:
    """Generate investment signal based on Graham analysis."""
    total_score = (
        analysis_data["earnings"]["score"] +
        analysis_data["strength"]["score"] +
        analysis_data["valuation"]["score"]
    )

    max_score = (
        analysis_data["earnings"]["max_score"] +
        analysis_data["strength"]["max_score"] +
        analysis_data["valuation"]["max_score"]
    )

    score_pct = total_score / max_score if max_score > 0 else 0

    if score_pct >= 0.7:
        signal = "bullish"
        confidence = min(90, int(score_pct * 100))
    elif score_pct <= 0.3:
        signal = "bearish"
        confidence = min(80, int((1 - score_pct) * 100))
    else:
        signal = "neutral"
        confidence = 50 + int(abs(score_pct - 0.5) * 40)

    return {
        "signal": signal,
        "confidence": confidence,
        "score": total_score,
        "max_score": max_score
    }


LINE_ITEMS = [
    "earnings_per_share",
    "revenue",
    "net_income",
    "book_value_per_share",
    "total_assets",
    "total_liabilities",
    "current_assets",
    "current_liabilities",
    "dividends_and_other_cash_distributions",
    "outstanding_shares",
]


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: analyze.py TICKER END_DATE")
        print("Example: analyze.py AAPL 2024-12-01")
        sys.exit(1)

    ticker = sys.argv[1]
    end_date = sys.argv[2]

    # Fetch data
    metrics = get_financial_metrics(ticker, end_date, "annual", 10)
    market_cap = get_market_cap(ticker, end_date)
    line_items = search_line_items(ticker, LINE_ITEMS, end_date, "annual", 10)

    # Run analyses
    earnings = analyze_earnings_stability(metrics, line_items)
    strength = analyze_financial_strength(line_items)
    valuation = analyze_valuation_graham(line_items, market_cap)

    analysis_data = {
        "earnings": earnings,
        "strength": strength,
        "valuation": valuation,
    }

    signal_data = generate_signal(analysis_data)

    result = {
        "ticker": ticker,
        "signal": signal_data["signal"],
        "confidence": signal_data["confidence"],
        "score": signal_data["score"],
        "max_score": signal_data["max_score"],
        "earnings_stability": earnings,
        "financial_strength": strength,
        "valuation": valuation,
        "market_cap": market_cap,
        "graham_number": valuation.get("graham_number"),
        "ncav": valuation.get("ncav"),
        "margin_of_safety": valuation.get("margin_of_safety"),
    }

    print(json.dumps(result, indent=2, default=str))
