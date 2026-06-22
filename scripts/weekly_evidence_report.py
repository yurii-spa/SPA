#!/usr/bin/env python3
"""
Weekly Paper Trading Evidence Report — ADR-002
Generates: data/weekly_evidence/YYYY-WNN.md

Usage:
    python3 scripts/weekly_evidence_report.py               # current week
    python3 scripts/weekly_evidence_report.py --week 2026-W24
    python3 scripts/weekly_evidence_report.py --dry-run     # print, don't save
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
import tempfile
from datetime import date

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

PAPER_START = date(2026, 6, 10)        # Day 0 of real paper trading
PAPER_WINDOW_DAYS = 30                  # Evidence window
GOLIVE_DATE = date(2026, 8, 1)         # ADR-002

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _repo_root() -> pathlib.Path:
    return _REPO_ROOT


def _load_json(path: str | pathlib.Path) -> dict | list:
    """Load JSON file; return empty dict on any error."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def get_week_label(d: date | None = None) -> str:
    """Return 'YYYY-WNN' ISO week label for the given date (default: today)."""
    if d is None:
        d = date.today()
    iso = d.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def _week_date_range(week_label: str) -> tuple[date, date]:
    """Return (monday, sunday) for a 'YYYY-WNN' week label."""
    year_str, week_str = week_label.split("-W")
    year = int(year_str)
    week = int(week_str)
    # ISO weeks start on Monday
    monday = date.fromisocalendar(year, week, 1)
    sunday = date.fromisocalendar(year, week, 7)
    return monday, sunday


def _paper_day(for_date: date) -> int:
    """Return 1-based paper trading day index (0 before start)."""
    delta = (for_date - PAPER_START).days + 1
    return max(0, delta)


def _fmt_usd(v: float) -> str:
    if v >= 0:
        return f"+${v:,.2f}"
    return f"-${abs(v):,.2f}"


def _fmt_pct(v: float, decimals: int = 2) -> str:
    sign = "+" if v >= 0 else ""
    return f"{sign}{v:.{decimals}f}%"


def _annualise(weekly_return_pct: float) -> float:
    """Rough annualised return from a weekly return %."""
    # (1 + r_weekly)^52 - 1
    r = weekly_return_pct / 100.0
    return ((1 + r) ** 52 - 1) * 100.0


# --------------------------------------------------------------------------- #
# Data loading
# --------------------------------------------------------------------------- #

def load_equity_history(data_dir: str | pathlib.Path) -> list[dict]:
    """
    Load equity history.
    Tries equity_curve_daily.json first (canonical), then equity_history.json.
    Returns a list of dicts with at least: date (str), equity (float).
    """
    data_dir = pathlib.Path(data_dir)

    # Preferred source: equity_curve_daily.json → .daily[]
    ecd = _load_json(data_dir / "equity_curve_daily.json")
    if isinstance(ecd, dict) and ecd.get("daily"):
        rows = []
        for entry in ecd["daily"]:
            rows.append({
                "date": entry.get("date", ""),
                "equity": float(entry.get("close_equity", entry.get("equity", 0))),
                "daily_return_pct": float(entry.get("daily_return_pct", 0)),
                "apy_today": float(entry.get("apy_today", 0)),
                "daily_yield_usd": float(entry.get("daily_yield_usd", 0)),
            })
        return rows

    # Fallback: equity_history.json
    eh = _load_json(data_dir / "equity_history.json")
    if isinstance(eh, list):
        rows = []
        for entry in eh:
            rows.append({
                "date": entry.get("date", ""),
                "equity": float(entry.get("equity", 0)),
                "daily_return_pct": 0.0,
                "apy_today": float(entry.get("apy_pct", 0)),
                "daily_yield_usd": float(entry.get("day_pnl", 0)),
            })
        return rows

    return []


def load_pnl_history(data_dir: str | pathlib.Path) -> list[dict]:
    """Load pnl_history.json; return list of dicts."""
    data = _load_json(pathlib.Path(data_dir) / "pnl_history.json")
    if isinstance(data, list):
        return data
    return []


def load_tournament(data_dir: str | pathlib.Path) -> dict:
    """Load tournament_ranking.json."""
    data = _load_json(pathlib.Path(data_dir) / "tournament_ranking.json")
    if isinstance(data, dict):
        return data
    return {}


def load_milestone_log(data_dir: str | pathlib.Path) -> dict:
    """Load apy_milestone_log.json."""
    data = _load_json(pathlib.Path(data_dir) / "apy_milestone_log.json")
    if isinstance(data, dict):
        return data
    return {}


def load_market_regime(data_dir: str | pathlib.Path) -> dict:
    """Load market_regime.json."""
    data = _load_json(pathlib.Path(data_dir) / "market_regime.json")
    if isinstance(data, dict):
        return data
    return {}


def load_risk_blocks(data_dir: str | pathlib.Path) -> list:
    """Load risk_policy_blocks.json."""
    data = _load_json(pathlib.Path(data_dir) / "risk_policy_blocks.json")
    if isinstance(data, list):
        return data
    return []


def load_golive_status(data_dir: str | pathlib.Path) -> dict:
    """Load golive_status.json."""
    data = _load_json(pathlib.Path(data_dir) / "golive_status.json")
    if isinstance(data, dict):
        return data
    return {}


def load_current_positions(data_dir: str | pathlib.Path) -> dict:
    """Load current_positions.json."""
    data = _load_json(pathlib.Path(data_dir) / "current_positions.json")
    if isinstance(data, dict):
        return data
    return {}


def load_adapter_status(data_dir: str | pathlib.Path) -> dict:
    """Load adapter_status.json (execution-domain, read-only here)."""
    data = _load_json(pathlib.Path(data_dir) / "adapter_status.json")
    if isinstance(data, dict):
        return data
    return {}


# --------------------------------------------------------------------------- #
# Report sections
# --------------------------------------------------------------------------- #

def _section_header(week_label: str) -> str:
    monday, sunday = _week_date_range(week_label)
    today = date.today()
    paper_day = _paper_day(today)
    lines = [
        f"# SPA Weekly Evidence Report — {week_label}",
        "",
        f"**Period:** {monday.isoformat()} → {sunday.isoformat()}  ",
        f"**Generated:** {today.isoformat()}  ",
        f"**Day of paper trading:** {paper_day}/{PAPER_WINDOW_DAYS}  ",
        f"**Go-live target:** {GOLIVE_DATE.isoformat()}  ",
        "",
    ]
    return "\n".join(lines)


def _section_portfolio(
    week_label: str,
    equity_history: list[dict],
    pnl_history: list[dict],
) -> str:
    """Portfolio Performance section."""
    monday, sunday = _week_date_range(week_label)

    # Filter equity rows that fall inside [monday, sunday]
    week_rows = [
        r for r in equity_history
        if r.get("date") and monday.isoformat() <= r["date"] <= sunday.isoformat()
    ]

    # Determine start / end equity
    if week_rows:
        start_equity = week_rows[0]["equity"]
        end_equity = week_rows[-1]["equity"]
    elif equity_history:
        # use last known equity for both (no data yet this week)
        end_equity = equity_history[-1]["equity"]
        start_equity = equity_history[0]["equity"] if len(equity_history) > 1 else end_equity
    else:
        start_equity = 100_000.0
        end_equity = 100_000.0

    weekly_pnl = end_equity - start_equity
    weekly_return_pct = ((end_equity / start_equity) - 1) * 100.0 if start_equity else 0.0
    ann_return_pct = _annualise(weekly_return_pct) if weekly_return_pct != 0 else 0.0

    # Max drawdown within the week
    max_dd = 0.0
    if week_rows:
        peak = week_rows[0]["equity"]
        for r in week_rows:
            eq = r["equity"]
            if eq > peak:
                peak = eq
            dd = (eq - peak) / peak * 100.0 if peak else 0.0
            if dd < max_dd:
                max_dd = dd

    # Average daily yield
    total_yield = sum(r.get("daily_yield_usd", 0) for r in week_rows)
    avg_apy = (
        sum(r.get("apy_today", 0) for r in week_rows) / len(week_rows)
        if week_rows else 0.0
    )

    lines = [
        "## Portfolio Performance",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Start Equity | ${start_equity:,.2f} |",
        f"| End Equity | ${end_equity:,.2f} |",
        f"| Weekly PnL | {_fmt_usd(weekly_pnl)} |",
        f"| Weekly Return | {_fmt_pct(weekly_return_pct)} |",
        f"| Annualized Return | ~{ann_return_pct:.1f}% |",
        f"| Max Drawdown (week) | {_fmt_pct(max_dd)} |",
        f"| Avg Daily Yield | ${total_yield / max(len(week_rows), 1):,.2f} |",
        f"| Avg Portfolio APY | {avg_apy:.2f}% |",
        "",
    ]
    return "\n".join(lines)


def _section_tournament(tournament_data: dict) -> str:
    """Strategy Tournament section (Top 5)."""
    strategies = tournament_data.get("strategies", [])
    winner = tournament_data.get("winner", "—")

    lines = [
        "## Strategy Tournament (Top 5)",
        "",
        "| Rank | Strategy | APY | Sharpe | Status |",
        "|------|----------|-----|--------|--------|",
    ]

    status_icons = {
        "leading": "🏆 Leading",
        "active": "✅ Active",
        "new": "🆕 New",
        "research": "🔬 Research",
        "advisory": "📋 Advisory",
    }

    for s in strategies[:5]:
        rank = s.get("rank", "—")
        name = s.get("name", s.get("id", "—"))
        apy = s.get("apy_realized")
        sharpe = s.get("sharpe")
        status_raw = s.get("status", "—")
        status = status_icons.get(status_raw, status_raw)

        apy_str = f"{apy:.3f}%" if apy is not None else "—"
        sharpe_str = f"{sharpe:.2f}" if sharpe is not None else "—"
        lines.append(f"| {rank} | {name} | {apy_str} | {sharpe_str} | {status} |")

    lines.append("")
    if winner and winner != "—":
        lines.append(f"**Current tournament leader:** {winner}")
        lines.append("")

    return "\n".join(lines)


def _section_milestones(milestone_log: dict) -> str:
    """APY Milestones section."""
    reached = milestone_log.get("milestones_reached", [])

    # Known milestone targets
    all_milestones = [
        {"level": 1, "name": "Baseline beat", "target_pct": 5.0},
        {"level": 2, "name": "Target entry",  "target_pct": 7.0},
        {"level": 3, "name": "Target mid",    "target_pct": 10.0},
        {"level": 4, "name": "Target high",   "target_pct": 15.0},
        {"level": 5, "name": "Stretch goal",  "target_pct": 20.0},
    ]

    reached_map = {m["level"]: m.get("first_reached_date", "—") for m in reached}

    lines = ["## Milestones Reached", ""]
    for m in all_milestones:
        lvl = m["level"]
        if lvl in reached_map:
            lines.append(
                f"- ✅ L{lvl} ({m['target_pct']}% APY) — {m['name']} — "
                f"reached {reached_map[lvl]}"
            )
        else:
            lines.append(
                f"- ⏳ L{lvl} ({m['target_pct']}% APY) — {m['name']} — "
                f"not reached"
            )

    lines.append("")
    return "\n".join(lines)


def _section_risk(market_regime: dict, risk_blocks: list, golive_status: dict) -> str:
    """Risk Assessment section."""
    regime = market_regime.get("regime", "UNKNOWN")
    recommendation = market_regime.get("recommendation", "—").upper()

    # Risk gate result
    week_blocks = risk_blocks  # could be filtered by date; show count
    gate_result = "PASS ✅" if len(week_blocks) == 0 else f"⚠️ {len(week_blocks)} BLOCK(S)"

    # GoLive checks
    golive_ready = golive_status.get("ready", False)
    checks = golive_status.get("checks", {})
    blockers = golive_status.get("blockers", [])
    checks_pass = sum(1 for v in checks.values() if v)
    checks_total = len(checks) if checks else 0

    lines = [
        "## Risk Assessment",
        "",
        "| Check | Result |",
        "|-------|--------|",
        f"| Risk Gate | {gate_result} |",
        f"| Market Regime | {regime} |",
        f"| Regime Recommendation | {recommendation} |",
        f"| Kill-switch | {'INACTIVE ✅' if len(week_blocks) == 0 else '⚠️ ACTIVE'} |",
        f"| GoLive Checker | {'READY ✅' if golive_ready else '❌ NOT READY'} "
        f"({checks_pass}/{checks_total} pass) |",
        "",
    ]

    if blockers:
        lines.append("**GoLive Blockers:**")
        for b in blockers:
            lines.append(f"- ❌ {b}")
        lines.append("")

    if week_blocks:
        lines.append("**Recent Risk Blocks:**")
        for block in week_blocks[-5:]:
            ts = block.get("timestamp", "—")
            reason = block.get("reason", "—")
            lines.append(f"- `{ts}` — {reason}")
        lines.append("")

    return "\n".join(lines)


def _section_adapters(adapter_status: dict, current_positions: dict) -> str:
    """Adapter Status section."""
    adapters = adapter_status.get("adapters", {})
    positions = current_positions.get("positions", {})
    capital = current_positions.get("capital_usd", 100_000.0)

    # Build adapter rows from adapter_status keys that have apy_pct
    adapter_rows = []
    for key, val in adapter_status.items():
        if isinstance(val, dict) and "apy_pct" in val:
            pos_usd = positions.get(key, 0)
            alloc_pct = (pos_usd / capital * 100) if capital else 0
            adapter_rows.append({
                "name": key,
                "apy": val.get("apy_pct"),
                "status": val.get("status", "—"),
                "position_usd": pos_usd,
                "alloc_pct": alloc_pct,
            })

    # Also include positions that may not be in adapter_status
    for key, pos_usd in positions.items():
        if not any(r["name"] == key for r in adapter_rows):
            adapter_rows.append({
                "name": key,
                "apy": None,
                "status": "active",
                "position_usd": pos_usd,
                "alloc_pct": (pos_usd / capital * 100) if capital else 0,
            })

    lines = [
        "## Adapter Status",
        "",
        "| Protocol | APY | Allocation | Position (USD) | Status |",
        "|----------|-----|-----------|----------------|--------|",
    ]

    for r in sorted(adapter_rows, key=lambda x: x["position_usd"], reverse=True):
        apy_str = f"{r['apy']:.2f}%" if r["apy"] is not None else "—"
        pos_str = f"${r['position_usd']:,.2f}" if r["position_usd"] else "$0.00"
        alloc_str = f"{r['alloc_pct']:.1f}%"
        status = r["status"] or "—"
        lines.append(
            f"| {r['name']} | {apy_str} | {alloc_str} | {pos_str} | {status} |"
        )

    if not adapter_rows:
        lines.append("| — | — | — | — | No data available |")

    lines.append("")
    return "\n".join(lines)


def _section_owner_actions(golive_status: dict, market_regime: dict) -> str:
    """Owner Actions Required section."""
    blockers = golive_status.get("blockers", [])
    regime = market_regime.get("regime", "UNKNOWN")

    lines = ["## Owner Actions Required", ""]

    action_count = 0

    if blockers:
        for b in blockers:
            action_count += 1
            lines.append(f"- 🔴 **USER ACTION:** {b}")

    # Regime-specific advice
    if regime == "VOLATILE":
        action_count += 1
        lines.append(
            "- ⚠️ **REVIEW:** Market regime is VOLATILE — review position sizes before next cycle."
        )
    elif regime == "BEAR":
        action_count += 1
        lines.append(
            "- ⚠️ **REVIEW:** Bear regime detected — consider reducing T2/T3 exposure."
        )

    if action_count == 0:
        lines.append("- ✅ No owner actions required this week.")

    lines.append("")
    lines.append("---")
    lines.append("_Generated by `scripts/weekly_evidence_report.py` · ADR-002 compliance_")
    lines.append("")

    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Main report assembler
# --------------------------------------------------------------------------- #

def generate_report(
    week_label: str,
    equity_history: list,
    pnl_history: list,
    tournament_data: dict,
    milestone_log: dict,
    market_regime: dict | None = None,
    risk_blocks: list | None = None,
    golive_status: dict | None = None,
    current_positions: dict | None = None,
    adapter_status: dict | None = None,
) -> str:
    """
    Generate a markdown evidence report for the given week.

    Parameters
    ----------
    week_label       : 'YYYY-WNN'
    equity_history   : list of daily equity dicts (date, equity, …)
    pnl_history      : list of PnL dicts
    tournament_data  : dict from tournament_ranking.json
    milestone_log    : dict from apy_milestone_log.json
    market_regime    : dict from market_regime.json (optional)
    risk_blocks      : list from risk_policy_blocks.json (optional)
    golive_status    : dict from golive_status.json (optional)
    current_positions: dict from current_positions.json (optional)
    adapter_status   : dict from adapter_status.json (optional)
    """
    if market_regime is None:
        market_regime = {}
    if risk_blocks is None:
        risk_blocks = []
    if golive_status is None:
        golive_status = {}
    if current_positions is None:
        current_positions = {}
    if adapter_status is None:
        adapter_status = {}

    sections = [
        _section_header(week_label),
        _section_portfolio(week_label, equity_history, pnl_history),
        _section_tournament(tournament_data),
        _section_milestones(milestone_log),
        _section_risk(market_regime, risk_blocks, golive_status),
        _section_adapters(adapter_status, current_positions),
        _section_owner_actions(golive_status, market_regime),
    ]
    return "\n".join(sections)


# --------------------------------------------------------------------------- #
# Save (atomic)
# --------------------------------------------------------------------------- #

def save_report(content: str, week_label: str, data_dir: str | pathlib.Path = "data") -> str:
    """
    Atomically write report to data/weekly_evidence/YYYY-WNN.md.
    Creates the directory if needed.
    Returns the absolute path of the saved file.
    """
    out_dir = pathlib.Path(data_dir) / "weekly_evidence"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{week_label}.md"

    # Atomic write: mkstemp in same directory → os.replace
    fd, tmp_path = tempfile.mkstemp(dir=out_dir, prefix=".tmp_", suffix=".md")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.replace(tmp_path, out_path)
    except Exception:
        # Clean up temp file on error
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    return str(out_path.resolve())


# --------------------------------------------------------------------------- #
# CLI entry point
# --------------------------------------------------------------------------- #

def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate weekly paper trading evidence report (ADR-002)"
    )
    parser.add_argument(
        "--week",
        default=None,
        help="ISO week label, e.g. 2026-W24 (default: current week)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print report to stdout without saving",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help="Path to data/ directory (default: <repo_root>/data)",
    )
    args = parser.parse_args(argv)

    data_dir = pathlib.Path(args.data_dir) if args.data_dir else _repo_root() / "data"
    week_label = args.week or get_week_label()

    # Load all data sources (graceful fallback built into each loader)
    equity_history = load_equity_history(data_dir)
    pnl_history = load_pnl_history(data_dir)
    tournament_data = load_tournament(data_dir)
    milestone_log = load_milestone_log(data_dir)
    market_regime = load_market_regime(data_dir)
    risk_blocks = load_risk_blocks(data_dir)
    golive_status = load_golive_status(data_dir)
    current_positions = load_current_positions(data_dir)
    adapter_status = load_adapter_status(data_dir)

    content = generate_report(
        week_label=week_label,
        equity_history=equity_history,
        pnl_history=pnl_history,
        tournament_data=tournament_data,
        milestone_log=milestone_log,
        market_regime=market_regime,
        risk_blocks=risk_blocks,
        golive_status=golive_status,
        current_positions=current_positions,
        adapter_status=adapter_status,
    )

    if args.dry_run:
        print(content)
        return 0

    out_path = save_report(content, week_label, data_dir)
    print(f"✅ Report saved: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
