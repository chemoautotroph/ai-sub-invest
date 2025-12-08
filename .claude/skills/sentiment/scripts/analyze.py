#!/usr/bin/env python3
"""Market sentiment analysis."""
import sys
import json

sys.path.insert(0, '.')

from src.tools.api import get_financial_metrics, get_insider_trades


def analyze_insider_sentiment(ticker: str, end_date: str) -> dict:
    """Analyze insider trading activity."""
    try:
        trades = get_insider_trades(ticker, end_date, 30)
    except:
        return {"signal": "neutral", "score": 0, "max_score": 5, "details": "Could not fetch insider data"}

    if not trades:
        return {"signal": "neutral", "score": 0, "max_score": 5, "details": "No recent insider trades"}

    buy_count = 0
    sell_count = 0
    buy_value = 0
    sell_value = 0

    for trade in trades:
        trans_type = str(getattr(trade, 'transaction_type', '')).lower()
        value = getattr(trade, 'value', 0) or 0

        if 'buy' in trans_type or 'purchase' in trans_type:
            buy_count += 1
            buy_value += abs(value)
        elif 'sell' in trans_type or 'sale' in trans_type:
            sell_count += 1
            sell_value += abs(value)

    score = 0
    details = []

    # Net activity
    if buy_count > sell_count * 2:
        score = 5
        signal = "bullish"
        details.append(f"Strong insider buying: {buy_count} buys vs {sell_count} sells")
    elif buy_count > sell_count:
        score = 3
        signal = "bullish"
        details.append(f"Net insider buying: {buy_count} buys vs {sell_count} sells")
    elif sell_count > buy_count * 2:
        score = 0
        signal = "bearish"
        details.append(f"Heavy insider selling: {sell_count} sells vs {buy_count} buys")
    elif sell_count > buy_count:
        score = 1
        signal = "bearish"
        details.append(f"Net insider selling: {sell_count} sells vs {buy_count} buys")
    else:
        score = 2
        signal = "neutral"
        details.append("Balanced insider activity")

    return {
        "signal": signal,
        "score": score,
        "max_score": 5,
        "buy_count": buy_count,
        "sell_count": sell_count,
        "details": "; ".join(details)
    }


def analyze_valuation_sentiment(metrics: list) -> dict:
    """Analyze sentiment from valuation levels."""
    if not metrics:
        return {"signal": "neutral", "score": 0, "max_score": 5, "details": "No metrics"}

    latest = metrics[0]
    score = 0
    details = []

    # Low valuation = bullish sentiment opportunity
    if latest.price_to_earnings_ratio:
        pe = latest.price_to_earnings_ratio
        if pe < 12:
            score += 2
            details.append(f"Low P/E ({pe:.1f}) - pessimism priced in")
        elif pe < 20:
            score += 1
            details.append(f"Moderate P/E ({pe:.1f})")
        elif pe > 35:
            score -= 1
            details.append(f"High P/E ({pe:.1f}) - high expectations")

    # Quality metrics affecting sentiment
    if latest.return_on_equity and latest.return_on_equity > 0.15:
        score += 1
        details.append("High ROE supports positive sentiment")

    if latest.debt_to_equity and latest.debt_to_equity < 0.5:
        score += 1
        details.append("Low debt reduces negative sentiment risk")

    if latest.free_cash_flow_per_share and latest.free_cash_flow_per_share > 0:
        score += 1
        details.append("Positive FCF supports sentiment")

    score = max(0, min(score, 5))

    if score >= 4:
        signal = "bullish"
    elif score <= 1:
        signal = "bearish"
    else:
        signal = "neutral"

    return {
        "signal": signal,
        "score": score,
        "max_score": 5,
        "details": "; ".join(details) if details else "N/A"
    }


def generate_signal(analysis: dict) -> dict:
    """Generate overall sentiment signal."""
    insider = analysis["insider"]
    valuation = analysis["valuation"]

    total_score = insider["score"] + valuation["score"]
    max_score = 10

    # Weight insider sentiment more heavily
    insider_weight = 0.6
    valuation_weight = 0.4

    weighted_score = (insider["score"] / 5 * insider_weight + valuation["score"] / 5 * valuation_weight)

    if weighted_score >= 0.6:
        signal = "bullish"
    elif weighted_score <= 0.3:
        signal = "bearish"
    else:
        signal = "neutral"

    confidence = round(weighted_score * 100)

    return {
        "signal": signal,
        "confidence": confidence,
        "score": total_score,
        "max_score": max_score
    }


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: analyze.py TICKER END_DATE")
        print("Example: analyze.py AAPL 2024-12-01")
        sys.exit(1)

    ticker = sys.argv[1]
    end_date = sys.argv[2]

    metrics = get_financial_metrics(ticker, end_date, "ttm", 5)

    insider = analyze_insider_sentiment(ticker, end_date)
    valuation = analyze_valuation_sentiment(metrics)

    analysis = {
        "insider": insider,
        "valuation": valuation,
    }

    overall = generate_signal(analysis)

    result = {
        "ticker": ticker,
        "signal": overall["signal"],
        "confidence": overall["confidence"],
        "score": overall["score"],
        "max_score": overall["max_score"],
        "insider_sentiment": insider,
        "valuation_sentiment": valuation,
    }

    print(json.dumps(result, indent=2, default=str))
