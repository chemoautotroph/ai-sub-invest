#!/usr/bin/env python3
"""Michael Burry style analysis - Contrarian Deep Value."""
import sys
import json

sys.path.insert(0, '.')

from src.tools.api import get_financial_metrics, get_market_cap, search_line_items, get_insider_trades


def analyze_asset_value(metrics: list, line_items: list, market_cap: float) -> dict:
    """Deep value asset analysis - Burry's specialty."""
    if not metrics or not market_cap:
        return {"score": 0, "max_score": 5, "details": "Insufficient data"}

    score = 0
    details = []
    latest = metrics[0]

    # Price to Book value
    if latest.price_to_book_ratio:
        pb = latest.price_to_book_ratio
        if pb < 0.8:
            score += 3
            details.append(f"Deep discount to book ({pb:.2f}x) - Burry territory")
        elif pb < 1.0:
            score += 2
            details.append(f"Below book value ({pb:.2f}x)")
        elif pb < 1.5:
            score += 1
            details.append(f"Near book value ({pb:.2f}x)")

    # Net-Net check (classic Burry)
    if line_items:
        latest_li = line_items[0]
        if hasattr(latest_li, 'current_assets') and hasattr(latest_li, 'total_liabilities'):
            if latest_li.current_assets and latest_li.total_liabilities:
                ncav = latest_li.current_assets - latest_li.total_liabilities
                if ncav > 0 and ncav > market_cap * 0.67:
                    score += 2
                    details.append(f"Net-Net situation! NCAV ${ncav:,.0f} > 2/3 Market Cap")

    return {"score": min(score, 5), "max_score": 5, "details": "; ".join(details) if details else "No deep value signals"}


def analyze_contrarian_signals(metrics: list) -> dict:
    """Look for contrarian opportunities - beaten down stocks."""
    if not metrics or len(metrics) < 2:
        return {"score": 0, "max_score": 3, "details": "Insufficient data"}

    score = 0
    details = []
    latest = metrics[0]

    # Low valuation multiples (market pessimism)
    if latest.price_to_earnings_ratio and latest.price_to_earnings_ratio < 8:
        score += 2
        details.append(f"Very low P/E ({latest.price_to_earnings_ratio:.1f}) - market pessimistic")
    elif latest.price_to_earnings_ratio and latest.price_to_earnings_ratio < 12:
        score += 1
        details.append(f"Low P/E ({latest.price_to_earnings_ratio:.1f})")

    # Price to sales discount
    if latest.price_to_sales_ratio and latest.price_to_sales_ratio < 0.5:
        score += 1
        details.append(f"Very low P/S ({latest.price_to_sales_ratio:.2f}) - deep discount")

    return {"score": min(score, 3), "max_score": 3, "details": "; ".join(details) if details else "No contrarian signals"}


def analyze_insider_activity(ticker: str, end_date: str) -> dict:
    """Check insider buying - Burry watches this closely."""
    try:
        # Phase 0 audit found this bug; was passing limit to start_date param
        trades = get_insider_trades(ticker, end_date, limit=20)
    except:
        return {"score": 0, "max_score": 3, "details": "Could not fetch insider data"}

    if not trades:
        return {"score": 0, "max_score": 3, "details": "No recent insider trades"}

    buy_count = 0
    sell_count = 0
    net_value = 0

    for trade in trades:
        if hasattr(trade, 'transaction_type'):
            if 'buy' in str(trade.transaction_type).lower() or 'purchase' in str(trade.transaction_type).lower():
                buy_count += 1
                if hasattr(trade, 'value') and trade.value:
                    net_value += trade.value
            elif 'sell' in str(trade.transaction_type).lower() or 'sale' in str(trade.transaction_type).lower():
                sell_count += 1
                if hasattr(trade, 'value') and trade.value:
                    net_value -= trade.value

    score = 0
    details = []

    if buy_count > sell_count * 2:
        score += 3
        details.append(f"Strong insider buying ({buy_count} buys vs {sell_count} sells)")
    elif buy_count > sell_count:
        score += 2
        details.append(f"Net insider buying ({buy_count} buys vs {sell_count} sells)")
    elif buy_count > 0:
        score += 1
        details.append(f"Some insider buying activity")
    else:
        details.append("No significant insider buying")

    return {"score": score, "max_score": 3, "details": "; ".join(details), "buy_count": buy_count, "sell_count": sell_count}


def analyze_financial_health(metrics: list) -> dict:
    """Even contrarian plays need financial stability."""
    if not metrics:
        return {"score": 0, "max_score": 4, "details": "Insufficient data"}

    score = 0
    details = []
    latest = metrics[0]

    # Positive earnings (not value traps)
    if latest.earnings_per_share and latest.earnings_per_share > 0:
        score += 1
        details.append("Profitable - not a value trap")

    # Debt manageable
    if latest.debt_to_equity and latest.debt_to_equity < 1.0:
        score += 1
        details.append("Manageable debt levels")

    # Positive cash flow
    if latest.free_cash_flow_per_share and latest.free_cash_flow_per_share > 0:
        score += 2
        details.append("Generating free cash flow")

    return {"score": score, "max_score": 4, "details": "; ".join(details) if details else "Financial concerns"}


def generate_signal(analysis_data: dict) -> dict:
    """Generate Burry-style contrarian signal."""
    asset = analysis_data["asset"]["score"]
    contrarian = analysis_data["contrarian"]["score"]
    insider = analysis_data["insider"]["score"]
    health = analysis_data["health"]["score"]

    total = asset + contrarian + insider + health
    max_total = 15

    score_pct = total / max_total

    # Burry wants deep value AND financial stability
    has_value = asset >= 3 or contrarian >= 2
    has_health = health >= 2
    has_insider = insider >= 2

    if score_pct >= 0.60 and has_value and has_health:
        signal = "bullish"
        confidence = min(80, int(score_pct * 100))
        if has_insider:
            confidence = min(90, confidence + 10)
    elif score_pct <= 0.35 or health <= 1:
        signal = "bearish"
        confidence = min(75, int((1 - score_pct) * 100))
    else:
        signal = "neutral"
        confidence = 50

    return {"signal": signal, "confidence": confidence, "score": total, "max_score": max_total}


LINE_ITEMS = [
    "current_assets",
    "total_liabilities",
    "total_assets",
    "shareholders_equity",
]


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: analyze.py TICKER END_DATE")
        print("Example: analyze.py GME 2024-12-01")
        sys.exit(1)

    ticker = sys.argv[1]
    end_date = sys.argv[2]

    metrics = get_financial_metrics(ticker, end_date, "ttm", 10)
    market_cap = get_market_cap(ticker, end_date)
    line_items = search_line_items(ticker, LINE_ITEMS, end_date, "ttm", 10)

    asset = analyze_asset_value(metrics, line_items, market_cap)
    contrarian = analyze_contrarian_signals(metrics)
    insider = analyze_insider_activity(ticker, end_date)
    health = analyze_financial_health(metrics)

    analysis_data = {
        "asset": asset,
        "contrarian": contrarian,
        "insider": insider,
        "health": health,
    }

    signal_data = generate_signal(analysis_data)

    result = {
        "ticker": ticker,
        "signal": signal_data["signal"],
        "confidence": signal_data["confidence"],
        "score": signal_data["score"],
        "max_score": signal_data["max_score"],
        "asset_value": asset,
        "contrarian_signals": contrarian,
        "insider_activity": insider,
        "financial_health": health,
        "market_cap": market_cap,
    }

    print(json.dumps(result, indent=2, default=str))
