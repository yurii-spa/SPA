#!/usr/bin/env python3
"""
MP-441: 30-Day Evidence Report Generator
Reads paper_evidence.json, tournament_ranking.json, golive_status.json
Outputs docs/evidence_report_30d.txt (plain text, stdlib only)

SCHEMA RECONCILIATION (Yield Capture WS2.2, 2026-06-28)
=======================================================
This generator was written against a STALE schema and band:
  * it read ``portfolio_apy`` / ``equity`` / per-day ``sharpe`` keys that
    paper_evidence.json no longer carries (the real keys are ``apy_pct`` /
    ``equity_value`` / ``day_return_pct``), so every metric silently fell
    through to the tournament fallback;
  * its go-live recommendation gated on a fabricated ~10–30% APY / Sharpe ≥ 0.8
    band that never matched the honest ~3.6% live track.

It is now reconciled to the CURRENT honest track:
  * metrics are computed from the REAL day keys, and STRICTLY over EVIDENCED
    days (dated >= the evidenced anchor, not reconstructed / warmup / seed /
    explicitly ``evidenced: false``) — never the raw days list. A pre-anchor or
    backfill day can no longer inflate the average APY / drawdown / return.
  * the go-live band reflects the real regime: a deterministic honest APY floor
    (above the ~3.4% RWA cash floor) and a realistic Sharpe gate, NOT the stale
    10–30% / 0.8 band.
  * go-live readiness reads the CURRENT golive_status.json fields
    (``passed`` / ``total`` / ``real_track_days`` / ``evidenced_anchor``).
"""

import json
import os
import sys
import tempfile
from datetime import date, datetime

# --------------------------------------------------------------------------- #
# Honest go-live band (reconciled to the live ~3.6% track, not the stale
# 10–30% / Sharpe-0.8 band). The APY floor is the RWA cash floor: an evidenced
# book that does not at least clear cash is not fundable. The Sharpe gate is a
# modest, realistic minimum for a low-vol stablecoin-yield book. Drawdown gate
# mirrors the kill-switch band.
# --------------------------------------------------------------------------- #
HONEST_MIN_APY_PCT = 3.4      # >= the ~3.4% tokenized-T-bill RWA floor
HONEST_MAX_APY_PCT = 30.0     # RiskPolicy APY ceiling (a higher reading is suspect)
HONEST_MIN_SHARPE = 0.5       # realistic minimum for a low-vol yield book
HONEST_MAX_DD_PCT = -5.0      # kill-switch drawdown band

# Evidenced-track anchor: the honest post-reset start. A day dated before this,
# or explicitly marked non-evidenced, does NOT count toward any real metric.
# Kept literal + stdlib-only; the canonical rule lives in
# spa_core.paper_trading.track_evidence (not imported here to keep this script
# dependency-free, but the predicate below mirrors it exactly).
EVIDENCED_ANCHOR = "2026-06-22"


def _day_date(d: dict):
    """ISO date string (YYYY-MM-DD) of a day record, or None."""
    if not isinstance(d, dict):
        return None
    raw = d.get("date") or d.get("timestamp") or d.get("ts")
    if not isinstance(raw, str) or len(raw) < 10:
        return None
    return raw[:10]


def _is_evidenced_day(d: dict, anchor: str = EVIDENCED_ANCHOR) -> bool:
    """Mirror of track_evidence.is_evidenced_bar (stdlib-only, no fs access).

    Evidenced iff: dated >= anchor; not warmup / seed / reconstructed; not
    explicitly ``evidenced: false``; and ``source`` not in the non-evidenced
    taxonomy. A day with no honesty label is treated as evidenced (legacy/
    synthetic), matching the canonical predicate's backward-compat rule.
    """
    if not isinstance(d, dict):
        return False
    dd = _day_date(d)
    if dd is None or dd < anchor:
        return False
    if d.get("is_warmup") is True or d.get("is_seed") is True:
        return False
    if d.get("reconstructed") is True:
        return False
    if d.get("evidenced") is False:
        return False
    if d.get("source") in ("backfill", "reconstructed", "warmup"):
        return False
    return True


def _evidenced_days(evidence: dict) -> list:
    """The clean evidenced day series (honest track), in input order."""
    days = evidence.get("days", []) if isinstance(evidence, dict) else []
    if not isinstance(days, list):
        return []
    return [d for d in days if _is_evidenced_day(d)]


def _day_apy(d: dict):
    """Per-day APY % from the CURRENT schema (apy_pct), falling back to legacy
    keys. Returns a float or None."""
    for k in ("apy_pct", "portfolio_apy", "apy_today_pct"):
        v = d.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return float(v)
    return None


def _day_equity(d: dict):
    """Per-day equity from the CURRENT schema (equity_value), falling back to
    legacy keys. Returns a float or None."""
    for k in ("equity_value", "equity", "close_equity", "current_equity"):
        v = d.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return float(v)
    return None


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
    Average APY computed STRICTLY over the EVIDENCED days (current ``apy_pct``
    schema). A pre-anchor / non-evidenced day can NOT contribute. Falls back to
    the tournament winner's realized APY only when there is no evidenced day.
    """
    apys = [a for a in (_day_apy(d) for d in _evidenced_days(evidence)) if a is not None]
    if apys:
        return sum(apys) / len(apys)

    # Fallback: tournament winner's realized APY (only when no evidenced day yet).
    strategies = tournament.get("strategies", [])
    if strategies:
        winner_apy = strategies[0].get("apy_realized")
        if winner_apy is not None:
            return float(winner_apy)
    return None


def _compute_max_drawdown(evidence: dict) -> float | None:
    """
    Max drawdown (%) over the EVIDENCED equity series (current ``equity_value``
    schema). Returns a non-positive number (e.g. -1.23) or None. A non-evidenced
    or inflated day outside the honest track can NOT widen or hide the drawdown.
    """
    equities = [e for e in (_day_equity(d) for d in _evidenced_days(evidence)) if e is not None]
    if len(equities) < 2:
        return None

    peak = equities[0]
    max_dd = 0.0
    for eq in equities:
        if eq > peak:
            peak = eq
        if peak > 0:
            dd = (eq - peak) / peak * 100.0
            if dd < max_dd:
                max_dd = dd
    return max_dd


# A realized Sharpe is only TRUSTED once the evidenced track is deep enough that
# the ratio is not a degenerate artifact. This mirrors
# forward_analytics.MIN_POINTS_FOR_DSR (20 equity points → 19 daily returns): the
# day-30 target depth. Below it the evidence report shows N/A (thin track), NEVER
# a degenerate ~118 / ~4.5e8 Sharpe on a near-constant accrual series.
_SHARPE_MIN_POINTS = 20
# A locked-volatility (fixed-rate accrual) book has only float-noise dispersion;
# its annualized "Sharpe" blows up. Above this magnitude the ratio is the
# documented degenerate artifact, not a real risk-adjusted score → report N/A.
_SHARPE_DEGENERATE_ABS = 20.0


def _compute_sharpe(evidence: dict, tournament: dict) -> float | None:
    """
    Realized annualized Sharpe from the EVIDENCED equity series (daily-return
    based, deterministic, stdlib-only). HONEST about depth and the documented
    degenerate-Sharpe hazard:

      * fewer than ``_SHARPE_MIN_POINTS`` evidenced equity points → None (a Sharpe
        on a handful of days is a degenerate artifact — this is the expected
        reading until ~day 20, BY DESIGN, never a fabricated number);
      * zero-dispersion (locked-vol) series → None;
      * an implausibly large magnitude (a near-zero-dispersion fixed-rate accrual
        whose ratio blows up) → None — never publish the degenerate ~118 Sharpe.

    Does NOT fall back to a (stale-band) tournament Sharpe: a thin evidenced track
    honestly has no trustworthy realized Sharpe yet. Returns None until the track
    is deep enough, which the report renders as N/A.
    """
    equities = [e for e in (_day_equity(d) for d in _evidenced_days(evidence)) if e is not None]
    if len(equities) < _SHARPE_MIN_POINTS:
        return None  # honest: not enough evidenced depth for a trustworthy ratio

    rets = []
    for i in range(1, len(equities)):
        prev = equities[i - 1]
        rets.append((equities[i] / prev - 1.0) if prev > 0 else 0.0)
    n = len(rets)
    if n < 2:
        return None
    mean = sum(rets) / n
    var = sum((r - mean) ** 2 for r in rets) / (n - 1)
    std = var ** 0.5
    if std <= 0:
        return None  # zero-dispersion / locked-vol → no honest ratio
    sharpe = (mean / std) * (365.0 ** 0.5)
    if abs(sharpe) >= _SHARPE_DEGENERATE_ABS:
        # Degenerate locked-vol artifact (float-noise dispersion) → never publish.
        return None
    return sharpe


def _go_live_recommendation(evidence: dict, golive: dict, avg_apy, max_dd, sharpe) -> str:
    """
    APPROVED  – golive ready AND all key metrics within the HONEST band
    BLOCKED   – golive not ready (has blockers)
    PENDING   – golive ready but metrics insufficient or insufficient days

    Reconciled (WS2.2): the metric band reflects the live ~3.6% track (APY floor
    = the ~3.4% RWA cash floor, realistic Sharpe gate), NOT the stale 10–30% /
    0.8 band. Days completed = EVIDENCED days (or golive_status.real_track_days),
    never the raw days list. Readiness reads the current golive schema.
    """
    blockers = golive.get("blockers", [])
    ready = golive.get("ready", False)

    if blockers:
        return "BLOCKED"

    # Evidenced track depth — prefer the canonical golive count, else evidenced days.
    days_done = golive.get("real_track_days")
    if not isinstance(days_done, int):
        days_done = len(_evidenced_days(evidence))
    min_days = evidence.get("min_days_required", 30)

    apy_ok = avg_apy is not None and HONEST_MIN_APY_PCT <= avg_apy <= HONEST_MAX_APY_PCT
    dd_ok = max_dd is None or max_dd > HONEST_MAX_DD_PCT
    sharpe_ok = sharpe is not None and sharpe >= HONEST_MIN_SHARPE
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
    base_capital = evidence.get("base_capital", 100000.0)
    ev_days = _evidenced_days(evidence)
    # Days completed = EVIDENCED days (prefer the canonical golive count when present).
    days_done = golive.get("real_track_days")
    if not isinstance(days_done, int):
        days_done = len(ev_days)
    min_days = evidence.get("min_days_required", 30)

    # Honest start = the evidenced anchor (the post-reset real start), not the
    # legacy pre-anchor start_date that mixes in backfill.
    start_date = golive.get("evidenced_anchor") or EVIDENCED_ANCHOR
    if ev_days and _day_date(ev_days[-1]):
        end_date = _day_date(ev_days[-1])
    else:
        end_date = golive.get("target_date") or evidence.get("golive_target", "N/A")

    avg_apy = _compute_avg_apy(evidence, tournament)
    max_dd = _compute_max_drawdown(evidence)
    sharpe = _compute_sharpe(evidence, tournament)

    recommendation = _go_live_recommendation(evidence, golive, avg_apy, max_dd, sharpe)

    lines = [
        "SECTION 1: PAPER TRADING SUMMARY",
        "----------------------------------",
        f"Period: {start_date} → {end_date}  (evidenced track only)",
        f"Capital: ${base_capital:,.0f} USDC",
        f"Days completed: {days_done} / {min_days}  (evidenced)",
        "",
        "Performance Metrics (evidenced days only):",
        f"  Average APY:      {_fmt_metric(avg_apy, '.2f', 'N/A')}%  "
        f"(Honest band: {HONEST_MIN_APY_PCT:.1f}-{HONEST_MAX_APY_PCT:.0f}%, floor = RWA cash)",
        f"  Maximum Drawdown: {_fmt_metric(max_dd, '.2f', 'N/A')}%   (Limit: {HONEST_MAX_DD_PCT:.0f}%)",
        f"  Sharpe Ratio:     {_fmt_metric(sharpe, '.3f', 'N/A')}    (Minimum: {HONEST_MIN_SHARPE:.1f})",
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

    # Current schema carries explicit passed/total; legacy carries a checks map.
    passed = golive.get("passed")
    total = golive.get("total")
    if not isinstance(passed, int) or not isinstance(total, int):
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
