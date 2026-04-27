"""Unit tests for src/data_sources/computed.py.

每个公式函数 4 个 case:
  - 正常输入(用 NVDA FY2026 真实数字硬编码,数值来源注释清楚)
  - 分母 0 → None
  - 负值输入 → 负值返回(亏损公司 / 负资产组),不要 abs
  - NaN propagate(返回 NaN,不 silent 0)

8 × 4 = 32 + fcf 符号约定专测 1 + NVDA fixture 三个 invariant 总览测 3 = 36。
"""
from __future__ import annotations

import datetime as dt
import math
from pathlib import Path
from typing import Any

import pytest

from src.data_sources.computed import (
    current_ratio,
    debt_to_equity,
    fcf,
    fcf_margin,
    gross_margin,
    operating_margin,
    roe,
    roic,
)
from src.data_sources.sec_edgar import _datapoints_for_concept, _parse_companyfacts


# ---------------------------------------------------------------------------
# NVDA FY2026 (year ending 2026-01-25) raw values.
# Pulled from tests/unit/fixtures/sec/NVDA_companyfacts.json on 2026-04-26.
# Hardcoded so the basic-case tests don't depend on fixture-refresh schedule;
# the dynamic invariant block below DOES read the fixture so any future fixture
# regeneration with different numbers gets exercised there.
# ---------------------------------------------------------------------------

NVDA_REVENUE = 215_938_000_000.0
NVDA_NET_INCOME = 120_067_000_000.0
NVDA_STOCKHOLDERS_EQUITY = 157_293_000_000.0
NVDA_OPERATING_INCOME = 130_387_000_000.0
NVDA_GROSS_PROFIT = 153_463_000_000.0
NVDA_OCF = 102_718_000_000.0
NVDA_CAPEX_RAW_POSITIVE = 6_042_000_000.0    # SEC reports outflow as positive
NVDA_CAPEX_LINEITEM = -NVDA_CAPEX_RAW_POSITIVE  # after Phase 0 sign convention
NVDA_ASSETS_CURRENT = 125_605_000_000.0
NVDA_LIABILITIES_CURRENT = 32_163_000_000.0
NVDA_LONG_TERM_DEBT = 8_468_000_000.0


NVDA_FACTS_PATH = Path(__file__).parent / "fixtures" / "sec" / "NVDA_companyfacts.json"


@pytest.fixture(scope="module")
def nvda_facts() -> Any:
    return _parse_companyfacts(NVDA_FACTS_PATH.read_bytes())


# ===========================================================================
# roe(net_income, stockholders_equity)
# ===========================================================================


def test_roe_normal_input() -> None:
    """NVDA FY2026: NI 120,067M / SE 157,293M ≈ 76.33%."""
    result = roe(net_income=NVDA_NET_INCOME, stockholders_equity=NVDA_STOCKHOLDERS_EQUITY)
    assert result == pytest.approx(0.7633, rel=1e-4)


def test_roe_zero_denominator_returns_none() -> None:
    assert roe(20.0, 0.0) is None
    assert roe(20.0, -0.0) is None  # signed zero is still zero


def test_roe_negative_net_income_returns_negative() -> None:
    """Loss-making firm has negative ROE — never abs()'d."""
    assert roe(net_income=-50.0, stockholders_equity=100.0) == -0.5


def test_roe_nan_propagates() -> None:
    assert math.isnan(roe(math.nan, 100.0))  # numerator NaN
    assert math.isnan(roe(100.0, math.nan))  # denominator NaN


# ===========================================================================
# roic(nopat, invested_capital)
# ===========================================================================


def test_roic_normal_input() -> None:
    """NOPAT 20 / IC 100 = 0.20. NOPAT computation (EBIT × (1 - tax_rate)) is
    explicitly the caller's responsibility — see computed.roic docstring."""
    assert roic(nopat=20.0, invested_capital=100.0) == 0.2


def test_roic_zero_denominator_returns_none() -> None:
    assert roic(20.0, 0.0) is None


def test_roic_negative_nopat_returns_negative() -> None:
    """Operating loss → negative ROIC."""
    assert roic(nopat=-30.0, invested_capital=100.0) == -0.3


def test_roic_nan_propagates() -> None:
    assert math.isnan(roic(math.nan, 100.0))
    assert math.isnan(roic(100.0, math.nan))


# ===========================================================================
# fcf(operating_cash_flow, capex)  — see Phase 0 决策 #4 sign convention
# ===========================================================================


def test_fcf_normal_input() -> None:
    """NVDA FY2026: OCF 102,718M + capex -6,042M = 96,676M."""
    result = fcf(operating_cash_flow=NVDA_OCF, capex=NVDA_CAPEX_LINEITEM)
    assert result == pytest.approx(NVDA_OCF + NVDA_CAPEX_LINEITEM)
    assert result == pytest.approx(96_676_000_000.0)


def test_fcf_invariant_capex_already_negative() -> None:
    """Pin Phase 0 决策 #4: free-backend LineItem.capital_expenditure is
    NEGATIVE (mirroring financialdatasets convention). FCF is therefore
    OCF + capex (PLUS, not minus) — flip the operator and you'll be off
    by 2x capex on every company.

    Concrete pin: capex=-100, ocf=500 → fcf=400 (NOT 600).
    """
    assert fcf(operating_cash_flow=500.0, capex=-100.0) == 400.0
    # And the symmetric reminder — with positive capex we'd OVERshoot,
    # which is exactly the bug shape we're guarding against:
    wrong = 500.0 + 100.0  # what you'd get if you forgot the convention
    assert fcf(operating_cash_flow=500.0, capex=-100.0) != wrong


def test_fcf_both_zero_returns_zero() -> None:
    """FCF has no denominator so the 'div by zero' edge isn't applicable;
    the equivalent degenerate input is "both zero" → arithmetic 0.0.
    No special path, no None, no NaN — just plain addition.
    """
    assert fcf(operating_cash_flow=0.0, capex=0.0) == 0.0


def test_fcf_negative_ocf_propagates() -> None:
    """Loss-making firm with capex still spending: deeply negative FCF."""
    assert fcf(operating_cash_flow=-200.0, capex=-50.0) == -250.0


def test_fcf_nan_propagates() -> None:
    assert math.isnan(fcf(math.nan, -50.0))
    assert math.isnan(fcf(500.0, math.nan))


# ===========================================================================
# fcf_margin(fcf, revenue)
# ===========================================================================


def test_fcf_margin_normal_input() -> None:
    """NVDA FY2026: FCF 96,676M / Rev 215,938M ≈ 44.77%."""
    result = fcf_margin(fcf=NVDA_OCF + NVDA_CAPEX_LINEITEM, revenue=NVDA_REVENUE)
    assert result == pytest.approx(0.4477, rel=1e-3)


def test_fcf_margin_zero_revenue_returns_none() -> None:
    assert fcf_margin(50.0, 0.0) is None


def test_fcf_margin_negative_fcf_returns_negative() -> None:
    """Cash-burning firm has negative FCF margin."""
    assert fcf_margin(fcf=-100.0, revenue=1000.0) == -0.1


def test_fcf_margin_nan_propagates() -> None:
    assert math.isnan(fcf_margin(math.nan, 1000.0))
    assert math.isnan(fcf_margin(100.0, math.nan))


# ===========================================================================
# debt_to_equity(total_debt, stockholders_equity)
# ===========================================================================


def test_debt_to_equity_normal_input() -> None:
    """NVDA FY2026: long-term debt 8,468M / SE 157,293M ≈ 0.0538."""
    result = debt_to_equity(
        total_debt=NVDA_LONG_TERM_DEBT, stockholders_equity=NVDA_STOCKHOLDERS_EQUITY
    )
    assert result == pytest.approx(0.05384, rel=1e-3)


def test_debt_to_equity_zero_denominator_returns_none() -> None:
    assert debt_to_equity(100.0, 0.0) is None


def test_debt_to_equity_negative_equity_returns_negative() -> None:
    """Distressed firms can have negative book equity (large buybacks /
    accumulated deficit). Function propagates the sign — the caller is
    expected to interpret 'negative D/E' correctly (debt is real but
    equity has gone underwater)."""
    assert debt_to_equity(total_debt=100.0, stockholders_equity=-50.0) == -2.0


def test_debt_to_equity_nan_propagates() -> None:
    assert math.isnan(debt_to_equity(math.nan, 100.0))
    assert math.isnan(debt_to_equity(100.0, math.nan))


# ===========================================================================
# current_ratio(current_assets, current_liabilities)
# ===========================================================================


def test_current_ratio_normal_input() -> None:
    """NVDA FY2026: AssetsCurrent 125,605M / LiabilitiesCurrent 32,163M ≈ 3.905."""
    result = current_ratio(NVDA_ASSETS_CURRENT, NVDA_LIABILITIES_CURRENT)
    assert result == pytest.approx(3.905, rel=1e-3)


def test_current_ratio_zero_denominator_returns_none() -> None:
    assert current_ratio(100.0, 0.0) is None


def test_current_ratio_negative_assets_propagates() -> None:
    """Truly weird, but: propagate sign rather than silently zero out."""
    assert current_ratio(current_assets=-10.0, current_liabilities=5.0) == -2.0


def test_current_ratio_nan_propagates() -> None:
    assert math.isnan(current_ratio(math.nan, 100.0))
    assert math.isnan(current_ratio(100.0, math.nan))


# ===========================================================================
# gross_margin(gross_profit, revenue)
# ===========================================================================


def test_gross_margin_normal_input() -> None:
    """NVDA FY2026: GP 153,463M / Rev 215,938M ≈ 71.07%."""
    result = gross_margin(NVDA_GROSS_PROFIT, NVDA_REVENUE)
    assert result == pytest.approx(0.7107, rel=1e-3)


def test_gross_margin_zero_revenue_returns_none() -> None:
    assert gross_margin(100.0, 0.0) is None


def test_gross_margin_negative_gross_profit_returns_negative() -> None:
    """Companies selling below cost — negative GP, propagate."""
    assert gross_margin(gross_profit=-50.0, revenue=1000.0) == -0.05


def test_gross_margin_nan_propagates() -> None:
    assert math.isnan(gross_margin(math.nan, 1000.0))
    assert math.isnan(gross_margin(100.0, math.nan))


# ===========================================================================
# operating_margin(operating_income, revenue)
# ===========================================================================


def test_operating_margin_normal_input() -> None:
    """NVDA FY2026: OpInc 130,387M / Rev 215,938M ≈ 60.38%."""
    result = operating_margin(NVDA_OPERATING_INCOME, NVDA_REVENUE)
    assert result == pytest.approx(0.6038, rel=1e-3)


def test_operating_margin_zero_revenue_returns_none() -> None:
    assert operating_margin(100.0, 0.0) is None


def test_operating_margin_negative_operating_income_returns_negative() -> None:
    """Loss-making at the operating line — propagate negative margin."""
    assert operating_margin(operating_income=-200.0, revenue=1000.0) == -0.2


def test_operating_margin_nan_propagates() -> None:
    assert math.isnan(operating_margin(math.nan, 1000.0))
    assert math.isnan(operating_margin(100.0, math.nan))


# ===========================================================================
# Real-company sanity invariants — NVDA fixture
#
# Stretch goal per Phase 1.5 spec. These tests use the SEC fixture directly
# so any fixture refresh exercises the parser + computed pipeline together.
# Thresholds are intentionally generous (no risk of false negatives from
# year-to-year variance), tight enough to immediately catch sign flips or
# orders-of-magnitude bugs.
# ===========================================================================


def _latest_full_year_value(facts: Any, concept: str) -> float | None:
    """Pick the most recent FY-coverage row's val for a flow concept."""
    series = _datapoints_for_concept(facts, concept, "USD")
    candidates = [
        dp for dp in series
        if dp.fp == "FY" and dp.start is not None and (dp.end - dp.start).days > 350
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda dp: dp.end).val


def _latest_instant_value(facts: Any, concept: str) -> float | None:
    """Pick the most recent FY-end snapshot for a balance-sheet (instant) concept."""
    raw_units = facts.raw["facts"]["us-gaap"].get(concept, {}).get("units", {}).get("USD", [])
    annual = [r for r in raw_units if r.get("form") == "10-K" and r.get("fp") == "FY"]
    if not annual:
        return None
    return float(max(annual, key=lambda r: r["end"])["val"])


def test_real_nvda_roe_above_30pct(nvda_facts: Any) -> None:
    """NVDA's recent ROE is ~75-80%. > 30% is loose enough to survive
    fixture refresh swings; tight enough to catch a negative-sign bug."""
    ni = _latest_full_year_value(nvda_facts, "NetIncomeLoss")
    se = _latest_instant_value(nvda_facts, "StockholdersEquity")
    assert ni is not None and se is not None
    result = roe(ni, se)
    assert result is not None and result > 0.30, (
        f"NVDA ROE = {result!r} (NI={ni}, SE={se}); expected > 0.30. "
        "Likely cause: sign flip in NetIncomeLoss extraction or SE pulled from "
        "wrong fiscal period."
    )


def test_real_nvda_operating_margin_above_30pct(nvda_facts: Any) -> None:
    op = _latest_full_year_value(nvda_facts, "OperatingIncomeLoss")
    rev = _latest_full_year_value(nvda_facts, "Revenues")
    assert op is not None and rev is not None
    result = operating_margin(op, rev)
    assert result is not None and result > 0.30, (
        f"NVDA operating margin = {result!r} (OpInc={op}, Rev={rev}); expected > 0.30."
    )


def test_real_nvda_fcf_margin_above_25pct(nvda_facts: Any) -> None:
    """End-to-end check that ties together: concept extraction (sec_edgar) +
    sign convention + fcf computation + fcf_margin computation. A bug
    anywhere in that chain shows up here as a wildly-off margin.
    """
    ocf = _latest_full_year_value(nvda_facts, "NetCashProvidedByUsedInOperatingActivities")
    capex_raw = _latest_full_year_value(nvda_facts, "PaymentsToAcquireProductiveAssets")
    rev = _latest_full_year_value(nvda_facts, "Revenues")
    assert ocf is not None and capex_raw is not None and rev is not None
    # Apply Phase 0 决策 #4 sign convention manually (mirrors what aggregator will do)
    capex_signed = -capex_raw  # SEC positive → LineItem negative
    free_cash = fcf(operating_cash_flow=ocf, capex=capex_signed)
    assert free_cash is not None
    margin = fcf_margin(free_cash, rev)
    assert margin is not None and margin > 0.25, (
        f"NVDA FCF margin = {margin!r} (OCF={ocf}, capex_raw={capex_raw}, "
        f"capex_signed={capex_signed}, FCF={free_cash}, Rev={rev}). "
        "Expected > 0.25. Most likely culprit: capex sign inverted."
    )
