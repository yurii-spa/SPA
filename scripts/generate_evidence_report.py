#!/usr/bin/env python3
"""
MP-441: 30-Day Evidence Report Generator
Reads paper_evidence.json, tournament_ranking.json, golive_status.json
Outputs docs/evidence_report_30d.txt (plain text, stdlib only)
"""

import json
import os
import sys
import tempfile
from datetime import date, datetime


# --------------------------------------------------------------------------- #
# Paths (relative to repo root by default, overridable for tests)
# --------------------------------------------------------------------------- #

def _repo_root():
    """Return the repository root directory (parent of scripts/)."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_json(path: str) -> dict:
    """Load a JSON file; return empty dict on missing / parse error."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


# --------------------------------------------------------------------------- #
# Derived metrics helpers
# --------------------------------------------------------------------------- #

def _compute_avg_apy(evidence: dict, tournament: dict) -> float | None:
    """
    Attempt to compute average APY from paper_evidence days;
    fall back to the tournament winner's realized APY if no days recorded yet.
    """
    days = evidence.get("days", [])
    if days:
        apys = [d.get("portfolio_apy") for d in days if d.get("portfolio_apy") is not None]
        if apys:
            return sum(apys) / len(apys)

    # Fallback: use tournament winner's realized APY
    strategies = tournament.get("strategies", [])
    if strategies:
        winner_apy = strategies[0].get("apy_realized")
        if winner_apy is not None:
            return float(winner_apy)
    return None


def _compute_max_drawdown(evidence: dict) -> float | None:
    """
    Max drawdown (%) from equity_curve in paper_evidence days.
    Returns a negative number (e.g. -1.23) or None.
    """
    days = evidence.get("days", [])
    equities = [d.get("equity") for d in days if d.get("equity") is not None]
    if len(equities) < 2:
        return None

    peak = equities[0]
    max_dd = 0.0
    for eq in equities:
        if eq > peak:
            peak = eq
        dd = (eq - peak) / peak * 100.0
        if dd < max_dd:
            max_dd = dd
    return max_dd


def _compute_sharpe(evidence: dict, tournament: dict) -> float | None:
    """
    Sharpe from paper_evidence; fall back to tournament winner's Sharpe.
    """
    days = evidence.get("days", [])
    if days:
        sharpes = [d.get("sharpe") for d in days if d.get("sharpe") is not None]
        if sharpes:
            return sharpes[-1]  # most recent

    strategies = tournament.get("strategies", [])
    if strategies:
        s = strategies[0].get("sharpe")
        if s is not None:
            return float(s)
    return None


def _go_live_recommendation(evidence: dict, golive: dict, avg_apy, max_dd, sharpe) -> str:
    """
    APPROVED  – golive ready AND all key metrics within bounds
    BLOCKED   – golive not ready (has blockers)
    PENDING   – golive ready but metrics insufficient or insufficient days
    """
    blockers = golive.get("blockers", [])
    ready = golive.get("ready", False)

    if blockers:
        return "BLOCKED"

    days_list = evidence.get("days", [])
    days_done = len(days_list)
    min_days = evidence.get("min_days_required", 30)

    apy_ok = avg_apy is not None and 10.0 <= avg_apy <= 30.0
    dd_ok = max_dd is None or max_dd > -5.0
    sharpe_ok = sharpe is not None and sharpe >= 0.8
    track_ok = days_done >= min_days

    if ready and apy_ok and dd_ok and sharpe_ok and track_ok:
        return "APPROVED"
    return "PENDING"


# --------------------------------------------------------------------------- #
# Section builders
# --------------------------------------------------------------------------- #

def _fmt_metric(value, fmt_spec, na="N/A"):
    if value is None:
        return na
    return format(value, fmt_spec)


def _section1(evidence: dict, tournament: dict, golive: dict, prepared_date: str) -> str:
    start_date = evidence.get("start_date", "N/A")
    base_capital = evidence.get("base_capital", 100000.0)
    days_list = evidence.get("days", [])
    days_done = len(days_list)
    min_days = evidence.get("min_days_required", 30)

    # End date: last day entry or golive_target
    if days_list and days_list[-1].get("date"):
        end_date = days_list[-1]["date"]
    else:
        end_date = evidence.get("golive_target", "N/A")

    avg_apy = _compute_avg_apy(evidence, tournament)
    max_dd = _compute_max_drawdown(evidence)
    sharpe = _compute_sharpe(evidence, tournament)

    recommendation = _go_live_recommendation(evidence, golive, avg_apy, max_dd, sharpe)

    lines = [
        "SECTION 1: PAPER TRADING SUMMARY",
        "----------------------------------",
        f"Period: {start_date} → {end_date}",
        f"Capital: ${base_capital:,.0f} USDC",
        f"Days completed: {days_done} / {min_days}",
        "",
        "Performance Metrics:",
        f"  Average APY:      {_fmt_metric(avg_apy, '.2f', 'N/A')}%  (Target: 10-15%)",
        f"  Maximum Drawdown: {_fmt_metric(max_dd, '.2f', 'N/A')}%   (Limit: -5%)",
        f"  Sharpe Ratio:     {_fmt_metric(sharpe, '.3f', 'N/A')}    (Minimum: 0.8)",
        "",
        f"Go-Live Recommendation: {recommendation}",
    ]
    return "\n".join(lines)


def _section2(tournament: dict) -> str:
    strategies = tournament.get("strategies", [])
    top5 = [s for s in strategies if s.get("rank") is not None][:5]

    lines = [
        "SECTION 2: STRATEGY TOURNAMENT (Top 5)",
        "---------------------------------------",
    ]

    if not top5:
        lines.append("  No strategy data available yet.")
        return "\n".join(lines)

    header = f"{'Rank':<5} {'Strategy':<28} {'APY Target':>10} {'Days':>6} {'Status':<14}"
    lines.append(header)
    lines.append("-" * len(header))

    for s in top5:
        rank = s.get("rank", "?")
        name = (s.get("name") or "")[:27]
        apy_target = s.get("apy_target")
        days_run = s.get("days_running", 0)
        status = (s.get("status") or "unknown")[:13]
        apy_str = f"{apy_target:.1f}%" if apy_target is not None else "N/A"
        lines.append(f"{rank:<5} {name:<28} {apy_str:>10} {days_run:>6} {status:<14}")

    winner = tournament.get("winner")
    if winner:
        lines.append("")
        lines.append(f"Tournament winner: {winner}")

    return "\n".join(lines)


def _section3(golive: dict) -> str:
    ready = golive.get("ready", False)
    checks = golive.get("checks", {})
    blockers = golive.get("blockers", [])

    passed = sum(1 for v in checks.values() if v)
    total = len(checks)

    lines = [
        "SECTION 3: GO-LIVE CHECKLIST",
        "------------------------------",
        f"Status: {'READY' if ready else 'NOT READY'}",
        f"Checks passed: {passed}/{total}",
    ]

    # Individual checks
    if checks:
        lines.append("")
        lines.append("Checks:")
        for name, val in checks.items():
            mark = "✓" if val else "✗"
            lines.append(f"  [{mark}] {name}")

    lines.append("")
    if blockers:
        lines.append("Blockers:")
        for b in blockers:
            lines.append(f"  - {b}")
    else:
        lines.append("Blockers: None")

    ts = golive.get("timestamp", "")
    if ts:
        lines.append(f"Last checked: {ts[:19].replace('T', ' ')} UTC")

    return "\n".join(lines)


def _section4() -> str:
    lines = [
        "SECTION 4: OWNER DECISION",
        "---------------------------",
        "[ ] Approve go-live with $100K USDC",
        "[ ] Request additional 30 days paper trading",
        "[ ] Decline — specify reason: ___________",
        "",
        "Signature: ___________________  Date: ___________",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Main generator
# --------------------------------------------------------------------------- #

def generate_report(
    evidence_path: str | None = None,
    tournament_path: str | None = None,
    golive_path: str | None = None,
) -> str:
    """
    Build and return the full evidence report as a string.
    Paths default to the standard data/ locations relative to repo root.
    """
    root = _repo_root()

    evidence_path = evidence_path or os.path.join(root, "data", "paper_evidence.json")
    tournament_path = tournament_path or os.path.join(root, "data", "tournament_ranking.json")
    golive_path = golive_path or os.path.join(root, "data", "golive_status.json")

    evidence = load_json(evidence_path)
    tournament = load_json(tournament_path)
    golive = load_json(golive_path)

    prepared_date = date.today().isoformat()

    sep = "=" * 60

    sections = [
        sep,
        "SPA FAMILY FUND — 30-DAY EVIDENCE REPORT",
        "Договір простого товариства | Prepared: " + prepared_date,
        sep,
        "",
        _section1(evidence, tournament, golive, prepared_date),
        "",
        _section2(tournament),
        "",
        _section3(golive),
        "",
        _section4(),
        "",
        sep,
        "CONFIDENTIAL — ДОГОВІР ПРОСТОГО ТОВАРИСТВА",
        sep,
    ]

    return "\n".join(sections) + "\n"


def write_report(report: str, output_path: str | None = None) -> str:
    """
    Atomically write the report to output_path.
    Returns the final path.
    """
    root = _repo_root()
    output_path = output_path or os.path.join(root, "docs", "evidence_report_30d.txt")

    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # Atomic write: tmp + os.replace
    dir_ = os.path.dirname(output_path)
    fd, tmp_path = tempfile.mkstemp(dir=dir_, prefix=".evidence_report_tmp_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(report)
        os.replace(tmp_path, output_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    return output_path


# --------------------------------------------------------------------------- #
# CLI entry point
# --------------------------------------------------------------------------- #

def main():
    report = generate_report()
    output_path = write_report(report)
    print(f"[MP-441] Evidence report written → {output_path}")
    # Print first 20 lines preview
    lines = report.splitlines()
    print("\n--- Preview (first 20 lines) ---")
    for line in lines[:20]:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
