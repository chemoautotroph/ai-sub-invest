"""Pure financial-ratio computations.

No IO, no logging, no Pydantic — just arithmetic with consistent edge-case
semantics. Functions are imported by ``aggregator.py`` (Phase 1.6) when it
synthesises ``FinancialMetrics`` from raw SEC concepts.

Universal edge-case rules
-------------------------
1. **Zero denominator → ``None``** (not ``inf``, not ``nan``). Caller treats
   ``None`` as "metric undefined for this period" — same convention as
   the ``FinancialMetrics`` Pydantic model uses for missing fields.
2. **Negative inputs propagate** — never ``abs()``. A loss-making firm
   has negative ROE; a firm with negative book equity has negative D/E.
   Persona scripts depend on the sign carrying information.
3. **NaN propagates** through arithmetic naturally; we don't intercept it.
   ``float('nan') == 0`` is ``False`` so a NaN denominator skips the
   "zero check" and divides through to ``nan``.
4. **No silent zeros**: never substitute ``0`` for missing inputs; the
   shape of "missing" is ``None`` or ``NaN`` and stays that way.

Sign convention reminder (Phase 0 决策 #4)
-----------------------------------------
``LineItem.capital_expenditure`` is **negative** (SEC reports outflows as
positive; ``sec_edgar.lineitem_value_for_concept`` flips the sign so persona
code mirrors the financialdatasets convention). FCF here is therefore
``operating_cash_flow + capex`` — a PLUS, not minus. ``test_fcf_invariant_capex_already_negative``
in ``tests/unit/test_computed.py`` pins that.
"""
from __future__ import annotations


def _safe_divide(numerator: float, denominator: float) -> float | None:
    """Divide, returning ``None`` when ``denominator`` is exactly zero.

    NaN denominator falls through to division (yielding NaN) — not a
    zero-protection case. Only true zero (and ``-0.0``) trigger ``None``.
    """
    if denominator == 0:
        return None
    return numerator / denominator


def roe(net_income: float, stockholders_equity: float) -> float | None:
    """Return on Equity = ``net_income / stockholders_equity``.

    Negative ``net_income`` (loss-making firm) yields negative ROE.
    """
    return _safe_divide(net_income, stockholders_equity)


def roic(nopat: float, invested_capital: float) -> float | None:
    """Return on Invested Capital = ``nopat / invested_capital``.

    NOPAT (Net Operating Profit After Tax = ``EBIT × (1 - tax_rate)``) is
    the **caller's** responsibility to compute — this function does not
    accept EBIT or tax_rate. Keeping NOPAT as the input avoids ambiguity
    over what tax rate to use (effective vs. statutory vs. cash) and lets
    the caller share that decision across multiple ratios if needed.
    """
    return _safe_divide(nopat, invested_capital)


def fcf(operating_cash_flow: float, capex: float) -> float:
    """Free Cash Flow = ``operating_cash_flow + capex``.

    **Crucial sign convention** (Phase 0 决策 #4):
        ``capex`` is expected to be NEGATIVE — that is the
        ``LineItem.capital_expenditure`` shape after ``sec_edgar``'s sign flip.
        FCF therefore uses ``+`` (the algebraic sum), NOT ``ocf - capex``.
        Pass a positive capex by mistake and you'll be off by 2× capex on
        every company.
    """
    return operating_cash_flow + capex


def fcf_margin(fcf: float, revenue: float) -> float | None:
    """FCF margin = ``fcf / revenue``."""
    return _safe_divide(fcf, revenue)


def debt_to_equity(total_debt: float, stockholders_equity: float) -> float | None:
    """D/E = ``total_debt / stockholders_equity``.

    Negative ``stockholders_equity`` (distressed firm with accumulated
    deficit or aggressive buybacks) yields a negative D/E. We propagate;
    the caller decides how to display "debt over negative equity."
    """
    return _safe_divide(total_debt, stockholders_equity)


def current_ratio(current_assets: float, current_liabilities: float) -> float | None:
    """Current ratio = ``current_assets / current_liabilities``."""
    return _safe_divide(current_assets, current_liabilities)


def gross_margin(gross_profit: float, revenue: float) -> float | None:
    """Gross margin = ``gross_profit / revenue``."""
    return _safe_divide(gross_profit, revenue)


def operating_margin(operating_income: float, revenue: float) -> float | None:
    """Operating margin = ``operating_income / revenue``."""
    return _safe_divide(operating_income, revenue)
