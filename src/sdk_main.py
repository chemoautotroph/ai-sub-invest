#!/usr/bin/env python3
"""ConsensusAI - Multi-analyst investment analysis using Claude Agent SDK + Skills.

This module provides programmatic access to ConsensusAI's investment analysis system
using Claude Agent SDK with auto-discovered skills from .claude/skills/.

Usage:
    # Single ticker analysis
    python src/sdk_main.py AAPL 2025-12-06

    # Multiple tickers
    python src/sdk_main.py AAPL,MSFT,GOOGL 2025-12-06

    # With custom portfolio
    python src/sdk_main.py AAPL 2025-12-06 --cash 50000

    # Specific analysts only
    python src/sdk_main.py AAPL 2025-12-06 --analysts warren-buffett,ben-graham
"""
import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# Load environment variables
load_dotenv()


def get_project_root() -> Path:
    """Get the project root directory."""
    return Path(__file__).parent.parent


def build_analysis_prompt(
    tickers: list[str],
    end_date: str,
    portfolio: dict,
    analysts: Optional[list[str]] = None,
    start_date: Optional[str] = None,
) -> str:
    """Build the analysis prompt for Claude.

    Args:
        tickers: List of stock tickers to analyze
        end_date: Analysis end date (YYYY-MM-DD)
        portfolio: Portfolio state with cash and positions
        analysts: Optional list of specific analyst skills to use
        start_date: Optional start date for historical data

    Returns:
        Formatted prompt string for Claude
    """
    tickers_str = ", ".join(tickers)
    portfolio_str = json.dumps(portfolio, indent=2)

    # Default analysts if not specified
    if analysts is None:
        analysts = [
            "warren-buffett",
            "ben-graham",
            "peter-lynch",
            "fundamentals",
            "technicals",
            "valuation",
        ]

    analysts_str = ", ".join(analysts)

    # Calculate start date if not provided (6 months before end_date)
    if start_date is None:
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        start_dt = end_dt.replace(month=end_dt.month - 6) if end_dt.month > 6 else end_dt.replace(year=end_dt.year - 1, month=end_dt.month + 6)
        start_date = start_dt.strftime("%Y-%m-%d")

    prompt = f"""Analyze the following stocks and provide trading recommendations.

## Tickers to Analyze
{tickers_str}

## Analysis Date
End Date: {end_date}
Start Date: {start_date} (for historical data)

## Current Portfolio
```json
{portfolio_str}
```

## Analysis Instructions

For each ticker, perform the following analysis:

### Step 1: Run Analyst Skills
Use these analyst skills to analyze each ticker: {analysts_str}

For each analyst skill:
1. Run the skill's analysis script with the ticker and end_date
2. Collect the signal (bullish/bearish/neutral), confidence, and reasoning

### Step 2: Risk Analysis
Use the risk-manager skill to calculate:
- Volatility metrics for each ticker
- Position limits based on portfolio value
- Maximum recommended position sizes

### Step 3: Portfolio Decision
Use the portfolio-manager skill to:
- Aggregate all analyst signals
- Weight by confidence
- Generate final trading recommendations

### Step 4: Output Format
Provide the final output as JSON:
```json
{{
  "analysis_date": "{end_date}",
  "tickers": {{
    "TICKER": {{
      "analyst_signals": {{
        "analyst_name": {{"signal": "...", "confidence": N, "reasoning": "..."}}
      }},
      "aggregated": {{
        "consensus_signal": "...",
        "confidence": N,
        "bullish_count": N,
        "bearish_count": N
      }},
      "risk_metrics": {{
        "volatility": N,
        "position_limit": N,
        "risk_level": "..."
      }},
      "recommendation": {{
        "action": "buy|sell|hold",
        "quantity": N,
        "reasoning": "..."
      }}
    }}
  }},
  "portfolio_summary": {{
    "total_value": N,
    "cash_after_trades": N,
    "positions": {{}}
  }}
}}
```

Begin the analysis now.
"""
    return prompt


async def run_hedge_fund_sdk(
    tickers: list[str],
    end_date: str,
    portfolio: dict,
    analysts: Optional[list[str]] = None,
    start_date: Optional[str] = None,
    verbose: bool = False,
) -> dict:
    """Run hedge fund analysis using Claude Agent SDK.

    Args:
        tickers: List of stock tickers to analyze
        end_date: Analysis end date (YYYY-MM-DD)
        portfolio: Portfolio state with cash and positions
        analysts: Optional list of specific analyst skills to use
        start_date: Optional start date for historical data
        verbose: Whether to print intermediate output

    Returns:
        Analysis results dictionary
    """
    try:
        from claude_agent_sdk import query, ClaudeAgentOptions
    except ImportError:
        print("Error: claude-agent-sdk not installed.")
        print("Install with: pip install claude-agent-sdk")
        sys.exit(1)

    project_root = get_project_root()

    options = ClaudeAgentOptions(
        cwd=str(project_root),
        allowed_tools=["Skill", "Read", "Bash"],
        max_turns=50,  # Allow enough turns for multi-analyst analysis
    )

    prompt = build_analysis_prompt(
        tickers=tickers,
        end_date=end_date,
        portfolio=portfolio,
        analysts=analysts,
        start_date=start_date,
    )

    if verbose:
        print(f"Analyzing {len(tickers)} ticker(s): {', '.join(tickers)}")
        print(f"As of: {end_date}")
        print("-" * 50)

    result_text = []

    async for message in query(prompt=prompt, options=options):
        if hasattr(message, 'content'):
            content = message.content
            if isinstance(content, list):
                for block in content:
                    if hasattr(block, 'text'):
                        result_text.append(block.text)
                        if verbose:
                            print(block.text)
            elif isinstance(content, str):
                result_text.append(content)
                if verbose:
                    print(content)

    # Try to extract JSON from the result
    full_result = "\n".join(result_text)

    # Look for JSON block in the output
    try:
        # Find JSON between ```json and ```
        if "```json" in full_result:
            start = full_result.find("```json") + 7
            end = full_result.find("```", start)
            json_str = full_result[start:end].strip()
            return json.loads(json_str)
        # Try parsing the whole result as JSON
        return json.loads(full_result)
    except json.JSONDecodeError:
        # Return raw text if JSON parsing fails
        return {"raw_output": full_result}


def run_hedge_fund_sync(
    tickers: list[str],
    end_date: str,
    portfolio: dict,
    analysts: Optional[list[str]] = None,
    start_date: Optional[str] = None,
    verbose: bool = False,
) -> dict:
    """Synchronous wrapper for run_hedge_fund_sdk.

    Args:
        tickers: List of stock tickers to analyze
        end_date: Analysis end date (YYYY-MM-DD)
        portfolio: Portfolio state with cash and positions
        analysts: Optional list of specific analyst skills to use
        start_date: Optional start date for historical data
        verbose: Whether to print intermediate output

    Returns:
        Analysis results dictionary
    """
    return asyncio.run(
        run_hedge_fund_sdk(
            tickers=tickers,
            end_date=end_date,
            portfolio=portfolio,
            analysts=analysts,
            start_date=start_date,
            verbose=verbose,
        )
    )


def create_default_portfolio(cash: float, tickers: list[str]) -> dict:
    """Create a default portfolio structure.

    Args:
        cash: Initial cash amount
        tickers: List of tickers to initialize positions for

    Returns:
        Portfolio dictionary
    """
    return {
        "cash": cash,
        "margin_requirement": 0.0,
        "margin_used": 0.0,
        "positions": {
            ticker: {
                "long": 0,
                "short": 0,
                "long_cost_basis": 0.0,
                "short_cost_basis": 0.0,
            }
            for ticker in tickers
        },
        "realized_gains": {
            ticker: {"long": 0.0, "short": 0.0}
            for ticker in tickers
        },
    }


def main():
    """CLI entry point for ConsensusAI analysis."""
    parser = argparse.ArgumentParser(
        description="ConsensusAI - Multi-analyst investment analysis using Claude Agent SDK + Skills",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python src/sdk_main.py AAPL 2025-12-06
  python src/sdk_main.py AAPL,MSFT,GOOGL 2025-12-06 --cash 50000
  python src/sdk_main.py NVDA 2025-12-06 --analysts warren-buffett,cathie-wood
        """,
    )

    parser.add_argument(
        "tickers",
        type=str,
        help="Comma-separated list of stock tickers (e.g., AAPL,MSFT,GOOGL)",
    )
    parser.add_argument(
        "end_date",
        type=str,
        help="Analysis end date in YYYY-MM-DD format",
    )
    parser.add_argument(
        "--start-date",
        type=str,
        default=None,
        help="Analysis start date in YYYY-MM-DD format (default: 6 months before end_date)",
    )
    parser.add_argument(
        "--cash",
        type=float,
        default=100000.0,
        help="Initial cash amount (default: 100000)",
    )
    parser.add_argument(
        "--analysts",
        type=str,
        default=None,
        help="Comma-separated list of analyst skills to use (default: all core analysts)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Print intermediate analysis output",
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default=None,
        help="Output file path for JSON results (default: stdout)",
    )

    args = parser.parse_args()

    # Parse tickers
    tickers = [t.strip().upper() for t in args.tickers.split(",")]

    # Parse analysts if specified
    analysts = None
    if args.analysts:
        analysts = [a.strip() for a in args.analysts.split(",")]

    # Create portfolio
    portfolio = create_default_portfolio(args.cash, tickers)

    # Run analysis
    try:
        result = run_hedge_fund_sync(
            tickers=tickers,
            end_date=args.end_date,
            portfolio=portfolio,
            analysts=analysts,
            start_date=args.start_date,
            verbose=args.verbose,
        )

        # Output results
        output_json = json.dumps(result, indent=2, default=str)

        if args.output:
            with open(args.output, "w") as f:
                f.write(output_json)
            print(f"Results written to {args.output}")
        else:
            print(output_json)

    except KeyboardInterrupt:
        print("\nAnalysis interrupted by user.")
        sys.exit(1)
    except Exception as e:
        print(f"Error during analysis: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
