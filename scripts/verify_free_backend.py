"""Phase 3 verification matrix runner.

Runs every (persona, ticker) cell twice — once with USE_FREE_BACKEND=0 and
once with =1 — captures the persona script's JSON output, classifies each
case, and writes ``docs/verification_report.md``.

Classification (spec § Phase 3):
  - PASS    — both backends ran, signal+confidence valid, signals match
              OR confidence delta ≤ 30
  - PARTIAL — free ran successfully but disagrees with paid (signal differs
              AND confidence delta > 30) — typically free's conservative
              bias from unfilled FinancialMetrics fields
  - FAIL    — free crashed / produced invalid signal / non-numeric confidence
              (genuine bug in the free backend integration)
  - SKIP    — paid degraded (crash, no API key, no-data signal) and we have
              no comparison baseline — only counted if free ran cleanly

Delivery threshold: PASS ≥ 28 / 35 (80%), FAIL ≤ 3.

Usage:
    SEC_EDGAR_USER_AGENT="Your Name your-email@example.com" \\
        uv run python scripts/verify_free_backend.py

Re-run when adapter logic changes; the cache makes subsequent runs much
faster (first cold pass ~10-20 min, subsequent passes ~3-5 min).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent.parent
PYTHON_BIN = REPO_ROOT / ".venv" / "bin" / "python"
SKILLS_DIR = REPO_ROOT / ".claude" / "skills"
REPORT_PATH = REPO_ROOT / "docs" / "verification_report.md"

PERSONAS: list[str] = [
    "warren-buffett",
    "ben-graham",
    "charlie-munger",
    "stanley-druckenmiller",
    "fundamentals",
    "valuation",
    "technicals",
]
# technicals takes a date *range* (TICKER START_DATE END_DATE); the rest take
# only TICKER END_DATE. CLI-shape difference, not a free-backend issue.
PERSONAS_NEED_START_DATE: frozenset[str] = frozenset({"technicals"})
TICKERS: list[str] = ["NVDA", "MSFT", "AVGO", "INTU", "ZETA"]
END_DATE = "2026-04-26"
# 90-day window for technicals — enough for SMA(50) + RSI smoothing without
# pulling years of price history we don't need.
TECHNICALS_START_DATE = "2026-01-26"
SUBPROCESS_TIMEOUT_SEC = 300

ALLOWED_SIGNALS: frozenset[str] = frozenset({"bullish", "bearish", "neutral"})
CONF_DELTA_TOLERANCE = 30


@dataclass
class CellResult:
    persona: str
    ticker: str
    paid: dict[str, Any] | None = None
    free: dict[str, Any] | None = None
    paid_returncode: int = 0
    free_returncode: int = 0
    paid_stderr_tail: str = ""
    free_stderr_tail: str = ""
    classification: str = "?"
    notes: list[str] = field(default_factory=list)

    @property
    def free_signal(self) -> str | None:
        return self.free.get("signal") if self.free else None

    @property
    def free_conf(self) -> float | None:
        return self.free.get("confidence") if self.free else None

    @property
    def paid_signal(self) -> str | None:
        return self.paid.get("signal") if self.paid else None

    @property
    def paid_conf(self) -> float | None:
        return self.paid.get("confidence") if self.paid else None


def run_persona(persona: str, ticker: str, end_date: str, *, free: bool) -> tuple[
    dict[str, Any] | None, int, str
]:
    """Returns (parsed JSON or None, returncode, stderr tail)."""
    script = SKILLS_DIR / persona / "scripts" / "analyze.py"
    if persona in PERSONAS_NEED_START_DATE:
        cli_args = [ticker, TECHNICALS_START_DATE, end_date]
    else:
        cli_args = [ticker, end_date]
    env = os.environ.copy()
    env["USE_FREE_BACKEND"] = "1" if free else "0"
    try:
        proc = subprocess.run(
            [str(PYTHON_BIN), str(script), *cli_args],
            cwd=str(REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT_SEC,
        )
    except subprocess.TimeoutExpired as e:
        return None, -1, f"TIMEOUT after {SUBPROCESS_TIMEOUT_SEC}s: {e}"

    if proc.returncode != 0:
        return None, proc.returncode, proc.stderr[-1500:]
    try:
        return json.loads(proc.stdout), 0, proc.stderr[-500:]
    except json.JSONDecodeError as e:
        return None, proc.returncode, f"JSON parse failed: {e}\nSTDOUT[:500]={proc.stdout[:500]!r}"


def classify(cell: CellResult) -> tuple[str, list[str]]:
    """Returns (classification, notes). Mutates nothing."""
    notes: list[str] = []

    # 1. Free is the SUT — if it broke, FAIL.
    if cell.free is None:
        notes.append(f"free backend crashed (rc={cell.free_returncode})")
        return "FAIL", notes
    if cell.free_signal not in ALLOWED_SIGNALS:
        notes.append(f"free signal invalid: {cell.free_signal!r}")
        return "FAIL", notes
    if not isinstance(cell.free_conf, (int, float)):
        notes.append(f"free confidence non-numeric: {cell.free_conf!r}")
        return "FAIL", notes
    if not (0 <= cell.free_conf <= 100):
        notes.append(f"free confidence out of [0,100]: {cell.free_conf}")
        return "FAIL", notes

    # 2. Paid issues → SKIP (no A/B comparison possible)
    if cell.paid is None:
        notes.append(f"paid backend crashed/no-data (rc={cell.paid_returncode})")
        return "SKIP", notes
    if (
        cell.paid_signal == "neutral"
        and cell.paid_conf == 0
    ):
        notes.append("paid returned no-data signal (likely no API key)")
        return "SKIP", notes
    if cell.paid_signal not in ALLOWED_SIGNALS or not isinstance(cell.paid_conf, (int, float)):
        notes.append(f"paid output malformed: signal={cell.paid_signal!r} conf={cell.paid_conf!r}")
        return "SKIP", notes

    # 3. Both backends ran. Compare.
    delta = abs(cell.paid_conf - cell.free_conf)
    same_signal = cell.paid_signal == cell.free_signal

    if same_signal and delta <= CONF_DELTA_TOLERANCE:
        notes.append(f"signals match ({cell.free_signal}), conf delta = {delta:.0f}")
        return "PASS", notes
    if same_signal:
        notes.append(
            f"signals match ({cell.free_signal}) but conf delta = {delta:.0f} "
            f"(> {CONF_DELTA_TOLERANCE} tolerance — free may be conservative)"
        )
        return "PARTIAL", notes
    if delta <= CONF_DELTA_TOLERANCE:
        notes.append(
            f"signals differ ({cell.paid_signal} vs {cell.free_signal}) but conf delta "
            f"= {delta:.0f} ≤ {CONF_DELTA_TOLERANCE} — close call either way"
        )
        return "PASS", notes
    notes.append(
        f"signals differ ({cell.paid_signal} vs {cell.free_signal}) AND conf delta "
        f"= {delta:.0f} > {CONF_DELTA_TOLERANCE}"
    )
    return "PARTIAL", notes


def reasoning_summary(payload: dict[str, Any] | None) -> str:
    """Best-effort one-line reasoning extract from persona output JSON."""
    if not payload:
        return ""
    # Different personas put reasoning under different keys; take the first
    # short-ish string we can find from a known set.
    for key in ("details", "reasoning", "summary"):
        if key in payload and isinstance(payload[key], str):
            return payload[key][:200]
    # Some personas have nested {fundamentals: {details: "..."}}
    for k, v in payload.items():
        if isinstance(v, dict):
            for inner in ("details", "reasoning"):
                if inner in v and isinstance(v[inner], str):
                    return f"[{k}] {v[inner]}"[:200]
    return ""


# ---------------------------------------------------------------------------
# Report writer
# ---------------------------------------------------------------------------


def write_report(results: list[CellResult]) -> None:
    counts = {"PASS": 0, "PARTIAL": 0, "FAIL": 0, "SKIP": 0}
    for r in results:
        counts[r.classification] += 1

    lines: list[str] = []
    lines.append("# Free Backend Verification Report")
    lines.append("")
    lines.append(f"**Run date**: {dt.date.today().isoformat()}")
    lines.append(f"**Matrix**: {len(TICKERS)} tickers × {len(PERSONAS)} personas = {len(results)} cases")
    lines.append(f"**End date used**: {END_DATE}")
    lines.append(f"**Confidence delta tolerance**: ≤ {CONF_DELTA_TOLERANCE} pts")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- **PASS**: {counts['PASS']} / {len(results)}")
    lines.append(f"- **PARTIAL**: {counts['PARTIAL']}")
    lines.append(f"- **FAIL**: {counts['FAIL']}")
    lines.append(f"- **SKIP** (paid degraded): {counts['SKIP']}")
    lines.append("")

    comparable = counts["PASS"] + counts["PARTIAL"] + counts["FAIL"]
    pass_rate = (counts["PASS"] / comparable * 100) if comparable else 0.0
    abs_ok = counts["PASS"] >= 28 and counts["FAIL"] <= 3
    rate_ok = pass_rate >= 80.0 and counts["FAIL"] <= 3
    lines.append("**Delivery thresholds**:")
    lines.append("")
    lines.append(
        f"- *Absolute* (PASS ≥ 28 / 35, FAIL ≤ 3): "
        f"{'**MET**' if abs_ok else '**NOT MET**'}"
    )
    lines.append(
        f"- *Rate-based, SKIPs excluded from denominator* "
        f"(PASS / (PASS+PARTIAL+FAIL) ≥ 80%, FAIL ≤ 3): "
        f"{counts['PASS']} / {comparable} = {pass_rate:.0f}% — "
        f"{'**MET**' if rate_ok else '**NOT MET**'}"
    )
    lines.append("")
    lines.append(
        "Spec § Phase 3 says \"SKIP 不计入 PASS/FAIL 分母\" so the rate-based view "
        "is the operational delivery gate. Absolute count is reported for transparency."
    )
    lines.append("")

    # Matrix table
    lines.append("## Result Matrix")
    lines.append("")
    header = "| Persona | " + " | ".join(TICKERS) + " |"
    sep = "|---|" + "|".join([":---:"] * len(TICKERS)) + "|"
    lines.append(header)
    lines.append(sep)
    by_pt = {(r.persona, r.ticker): r for r in results}
    for persona in PERSONAS:
        row = [f"`{persona}`"]
        for ticker in TICKERS:
            cell = by_pt[(persona, ticker)]
            row.append(cell.classification)
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")

    # Per-cell detail
    lines.append("## Per-cell Detail")
    lines.append("")
    for r in results:
        lines.append(f"### `{r.persona}` / `{r.ticker}` — {r.classification}")
        lines.append("")
        if r.paid is not None:
            lines.append(f"- **Paid**: signal={r.paid_signal!r} confidence={r.paid_conf}")
        else:
            lines.append(f"- **Paid**: crashed (rc={r.paid_returncode})")
            if r.paid_stderr_tail.strip():
                lines.append(f"  - stderr tail: `{r.paid_stderr_tail.strip().splitlines()[-1][:160]}`")
        if r.free is not None:
            lines.append(f"- **Free**: signal={r.free_signal!r} confidence={r.free_conf}")
            free_summary = reasoning_summary(r.free)
            if free_summary:
                lines.append(f"  - reasoning: {free_summary}")
        else:
            lines.append(f"- **Free**: crashed (rc={r.free_returncode})")
            if r.free_stderr_tail.strip():
                lines.append(f"  - stderr tail: `{r.free_stderr_tail.strip().splitlines()[-1][:160]}`")
        for n in r.notes:
            lines.append(f"- _Note_: {n}")
        lines.append("")

    REPORT_PATH.write_text("\n".join(lines))
    print(f"\nReport written to {REPORT_PATH}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    if not os.environ.get("SEC_EDGAR_USER_AGENT", "").strip():
        print(
            "ERROR: SEC_EDGAR_USER_AGENT env var is required for free backend.\n"
            "  export SEC_EDGAR_USER_AGENT='Your Name your-email@example.com'",
            file=sys.stderr,
        )
        return 2

    n_total = len(PERSONAS) * len(TICKERS)
    print(f"Phase 3 verification: {n_total} cells × 2 backends = {n_total * 2} subprocess calls")
    print(f"Tickers: {TICKERS}")
    print(f"Personas: {PERSONAS}")
    print()

    results: list[CellResult] = []
    i = 0
    for persona in PERSONAS:
        for ticker in TICKERS:
            i += 1
            cell = CellResult(persona=persona, ticker=ticker)
            print(f"[{i}/{n_total}] {persona} / {ticker} ... ", end="", flush=True)

            cell.paid, cell.paid_returncode, cell.paid_stderr_tail = run_persona(
                persona, ticker, END_DATE, free=False,
            )
            cell.free, cell.free_returncode, cell.free_stderr_tail = run_persona(
                persona, ticker, END_DATE, free=True,
            )
            cell.classification, cell.notes = classify(cell)
            results.append(cell)
            print(cell.classification)

    write_report(results)

    # Stdout summary
    counts = {"PASS": 0, "PARTIAL": 0, "FAIL": 0, "SKIP": 0}
    for r in results:
        counts[r.classification] += 1
    print()
    print(f"PASS={counts['PASS']}  PARTIAL={counts['PARTIAL']}  "
          f"FAIL={counts['FAIL']}  SKIP={counts['SKIP']}")
    comparable = counts["PASS"] + counts["PARTIAL"] + counts["FAIL"]
    rate = (counts["PASS"] / comparable * 100) if comparable else 0.0
    print(f"Rate (SKIPs excluded): {counts['PASS']}/{comparable} = {rate:.0f}%")
    abs_ok = counts["PASS"] >= 28 and counts["FAIL"] <= 3
    rate_ok = rate >= 80.0 and counts["FAIL"] <= 3
    print(f"Absolute threshold (≥28 PASS, ≤3 FAIL): {'MET' if abs_ok else 'NOT MET'}")
    print(f"Rate threshold (≥80%, ≤3 FAIL): {'MET' if rate_ok else 'NOT MET'}")
    return 0 if rate_ok else 1


if __name__ == "__main__":
    sys.exit(main())
