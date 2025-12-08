#!/usr/bin/env python3
"""Aswath Damodaran style valuation analysis."""
import sys
import json

sys.path.insert(0, '.')

from src.tools.api import get_financial_metrics, get_market_cap, search_line_items


def calculate_cost_of_capital(metrics: list) -> dict:
    """Estimate cost of capital (WACC proxy)."""
    # Simplified: use risk-free + equity risk premium + beta adjustment
    risk_free = 0.04  # ~4% treasury
    market_premium = 0.05  # ~5% equity risk premium

    if not metrics:
        return {"wacc": 0.10, "details": "Using default 10% WACC"}

    latest = metrics[0]

    # Adjust for leverage
    debt_to_equity = latest.debt_to_equity if latest.debt_to_equity else 0
    leverage_adjustment = min(debt_to_equity * 0.02, 0.03)  # Cap at 3%

    # Estimate beta from volatility proxy (simplified)
    beta = 1.0  # Default market beta
    if latest.price_to_earnings_ratio:
        if latest.price_to_earnings_ratio > 30:
            beta = 1.3  # High growth = higher beta
        elif latest.price_to_earnings_ratio < 10:
            beta = 0.8  # Value stocks = lower beta

    cost_of_equity = risk_free + (beta * market_premium)
    wacc = cost_of_equity + leverage_adjustment

    return {
        "wacc": wacc,
        "cost_of_equity": cost_of_equity,
        "beta": beta,
        "details": f"WACC: {wacc:.1%} (CoE: {cost_of_equity:.1%}, Beta: {beta:.1f})"
    }


def dcf_valuation(line_items: list, metrics: list, wacc: float) -> dict:
    """Perform DCF valuation using FCFF."""
    if not line_items or len(line_items) < 2:
        return {"intrinsic_value": None, "details": "Insufficient data for DCF"}

    latest = line_items[0]
    fcf = latest.free_cash_flow if hasattr(latest, 'free_cash_flow') and latest.free_cash_flow else None

    if not fcf:
        # Estimate from net income
        if latest.net_income and hasattr(latest, 'capital_expenditure'):
            depreciation = latest.depreciation_and_amortization if hasattr(latest, 'depreciation_and_amortization') else 0
            capex = abs(latest.capital_expenditure) if latest.capital_expenditure else 0
            fcf = latest.net_income + (depreciation or 0) - capex

    if not fcf or fcf <= 0:
        return {"intrinsic_value": None, "details": "Cannot calculate DCF - negative or missing FCF"}

    # Estimate growth rate
    growth_rate = 0.05  # Default 5%
    if metrics and len(metrics) >= 2:
        earnings_growth = metrics[0].earnings_growth
        if earnings_growth:
            growth_rate = min(max(earnings_growth * 0.7, 0.02), 0.12)  # Cap between 2-12%

    terminal_growth = 0.025  # Long-term GDP growth
    projection_years = 10

    # Calculate present value of cash flows
    pv_fcf = 0
    projected_fcf = fcf
    for year in range(1, projection_years + 1):
        if year <= 5:
            projected_fcf *= (1 + growth_rate)
        else:
            # Fade to terminal growth
            fade_growth = growth_rate - ((growth_rate - terminal_growth) * (year - 5) / 5)
            projected_fcf *= (1 + fade_growth)
        pv_fcf += projected_fcf / ((1 + wacc) ** year)

    # Terminal value
    terminal_fcf = projected_fcf * (1 + terminal_growth)
    terminal_value = terminal_fcf / (wacc - terminal_growth)
    pv_terminal = terminal_value / ((1 + wacc) ** projection_years)

    intrinsic_value = pv_fcf + pv_terminal

    return {
        "intrinsic_value": intrinsic_value,
        "current_fcf": fcf,
        "growth_rate": growth_rate,
        "terminal_growth": terminal_growth,
        "pv_fcf": pv_fcf,
        "pv_terminal": pv_terminal,
        "details": f"DCF Value: ${intrinsic_value:,.0f} (FCF: ${fcf:,.0f}, Growth: {growth_rate:.1%})"
    }


def relative_valuation(metrics: list, market_cap: float) -> dict:
    """Perform relative valuation analysis."""
    if not metrics:
        return {"score": 0, "max_score": 5, "details": "Insufficient data"}

    score = 0
    details = []
    latest = metrics[0]

    # P/E analysis
    if latest.price_to_earnings_ratio:
        pe = latest.price_to_earnings_ratio
        if pe < 12:
            score += 2
            details.append(f"Low P/E ({pe:.1f}) - potentially undervalued")
        elif pe < 20:
            score += 1
            details.append(f"Moderate P/E ({pe:.1f})")
        elif pe > 35:
            details.append(f"High P/E ({pe:.1f}) - requires high growth to justify")

    # EV/EBITDA proxy (using P/E and leverage)
    if latest.price_to_book_ratio:
        pb = latest.price_to_book_ratio
        if pb < 1.5:
            score += 1
            details.append(f"Low P/B ({pb:.1f}) - trading near book value")
        elif pb > 5:
            details.append(f"High P/B ({pb:.1f}) - premium valuation")

    # Price to Sales
    if latest.price_to_sales_ratio:
        ps = latest.price_to_sales_ratio
        if ps < 1.5:
            score += 1
            details.append(f"Low P/S ({ps:.1f})")
        elif ps > 5:
            details.append(f"High P/S ({ps:.1f})")

    # FCF yield
    if latest.free_cash_flow_yield:
        fcf_yield = latest.free_cash_flow_yield
        if fcf_yield > 0.08:
            score += 1
            details.append(f"High FCF yield ({fcf_yield:.1%})")

    return {"score": min(score, 5), "max_score": 5, "details": "; ".join(details) if details else "Limited data"}


def assess_story_consistency(metrics: list) -> dict:
    """Damodaran's story check - do the numbers tell a consistent story?"""
    if not metrics or len(metrics) < 3:
        return {"score": 0, "max_score": 5, "details": "Insufficient data"}

    score = 0
    details = []

    # Growth story consistency
    rev_growth = [m.revenue_growth for m in metrics if m.revenue_growth is not None]
    earn_growth = [m.earnings_growth for m in metrics if m.earnings_growth is not None]

    if len(rev_growth) >= 2 and len(earn_growth) >= 2:
        # Revenue and earnings should move together
        rev_trend = rev_growth[0] > rev_growth[-1]
        earn_trend = earn_growth[0] > earn_growth[-1] if len(earn_growth) > 1 else True
        if rev_trend == earn_trend:
            score += 2
            details.append("Revenue and earnings growth tell consistent story")

    # Margin story
    margins = [m.operating_margin for m in metrics if m.operating_margin is not None]
    if len(margins) >= 3:
        if all(m > 0.10 for m in margins):
            score += 2
            details.append("Consistent margin story - sustainable profitability")

    # Capital allocation story
    roes = [m.return_on_equity for m in metrics if m.return_on_equity is not None]
    if len(roes) >= 3:
        avg_roe = sum(roes) / len(roes)
        if avg_roe > 0.12:
            score += 1
            details.append("ROE supports value creation narrative")

    return {"score": min(score, 5), "max_score": 5, "details": "; ".join(details) if details else "Limited data"}


def generate_signal(analysis_data: dict, market_cap: float) -> dict:
    """Generate Damodaran-style signal."""
    dcf = analysis_data["dcf"]
    relative = analysis_data["relative"]["score"]
    story = analysis_data["story"]["score"]

    # Primary signal from DCF
    dcf_signal = "neutral"
    if dcf.get("intrinsic_value") and market_cap:
        gap = (dcf["intrinsic_value"] - market_cap) / market_cap
        if gap > 0.25:
            dcf_signal = "bullish"
        elif gap < -0.25:
            dcf_signal = "bearish"

    # Combine with relative and story
    total_score = relative + story + (5 if dcf_signal == "bullish" else 0 if dcf_signal == "bearish" else 2)
    max_score = 15

    score_pct = total_score / max_score

    if score_pct >= 0.65 and dcf_signal in ["bullish", "neutral"]:
        signal = "bullish"
        confidence = min(85, int(score_pct * 100))
    elif score_pct <= 0.35 or dcf_signal == "bearish":
        signal = "bearish"
        confidence = min(80, int((1 - score_pct) * 100))
    else:
        signal = "neutral"
        confidence = 50

    return {"signal": signal, "confidence": confidence, "score": total_score, "max_score": max_score}


LINE_ITEMS = [
    "free_cash_flow",
    "net_income",
    "capital_expenditure",
    "depreciation_and_amortization",
    "outstanding_shares",
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

    cost = calculate_cost_of_capital(metrics)
    dcf = dcf_valuation(line_items, metrics, cost["wacc"])
    relative = relative_valuation(metrics, market_cap)
    story = assess_story_consistency(metrics)

    analysis_data = {
        "cost_of_capital": cost,
        "dcf": dcf,
        "relative": relative,
        "story": story,
    }

    signal_data = generate_signal(analysis_data, market_cap)

    # Calculate valuation gap
    valuation_gap = None
    if dcf.get("intrinsic_value") and market_cap:
        valuation_gap = (dcf["intrinsic_value"] - market_cap) / market_cap

    result = {
        "ticker": ticker,
        "signal": signal_data["signal"],
        "confidence": signal_data["confidence"],
        "score": signal_data["score"],
        "max_score": signal_data["max_score"],
        "cost_of_capital": cost,
        "dcf_valuation": dcf,
        "relative_valuation": relative,
        "story_consistency": story,
        "market_cap": market_cap,
        "valuation_gap": valuation_gap,
    }

    print(json.dumps(result, indent=2, default=str))
