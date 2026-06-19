"""
spa_core/analytics/weekly_paper_report_v2.py

Enhanced weekly paper report incorporating CPA methodology.
Adds:
  - Gate status section (4-state) from spa_core.backtesting.gate
  - Research exclusions reminder (RS-001, RS-002)
  - Drift vs backtest section
  - Research strategy shadow performance (S20/S21)
  - Source quality indicator from source_pipeline.json

Output: JSON + Markdown report

Scope: STRICTLY READ-ONLY / advisory. Pure stdlib only.
LLM FORBIDDEN in this module.
Atomic writes via tmp + os.replace.

Date: 2026-06-19 (MP-1312, Sprint v9.28)
"""
from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _load_json(path: str) -> Optional[Dict]:
    """Load JSON defensively; return None on any error."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def _compute_apy(nav: float, initial: float, days: int) -> Optional[float]:
    """Annualise return from NAV, initial capital, and elapsed days.

    Returns APY as a percentage, or None if insufficient data.
    """
    if days <= 0 or initial <= 0:
        return None
    gross_return = (nav - initial) / initial
    # Annualise: (1 + r)^(365/days) - 1
    try:
        apy = ((1.0 + gross_return) ** (365.0 / days) - 1.0) * 100.0
    except (ZeroDivisionError, ValueError, OverflowError):
        return None
    return round(apy, 4)


# ─── WeeklyPaperReportV2 ─────────────────────────────────────────────────────

class WeeklyPaperReportV2:
    """Enhanced weekly paper report with CPA gate section.

    Reads from:
      - data/backtest/*.json  (gate files via BacktestGate)
      - data/research/rs001_shadow.json, rs002_shadow.json  (shadow perf)
      - data/backtest/source_pipeline.json  (source quality)

    All file reads are defensive — missing files yield graceful empty sections.
    Never writes to any operational state file. Output only to its own report path.
    """

    RESEARCH_STRATEGIES = {
        "RS001": {
            "name": "RS-001 Anti-Crisis (S20)",
            "slots": [
                "gmx_btc_exposure", "gmx_eth_exposure", "btc_stable_pool",
                "eth_aggressive_pool", "gold_proxy", "stablecoin_t1",
            ],
            "target_apy": 18.2,
            "reason": "5 of 6 slots have no clean point-in-time DeFiLlama series",
        },
        "RS002": {
            "name": "RS-002 Cashflow (S21)",
            "slots": [
                "btc_usd_conc_liq", "rwa_conc_liq",
                "trader_losses_vault", "stablecoin_deposit",
            ],
            "target_apy_gross": 29.24,
            "target_apy_net_range": [12.0, 18.0],
            "reason": "IL not modeled historically; venue/product identity unspecified",
        },
    }

    def __init__(
        self,
        initial_capital: float = 100_000.0,
        backtest_dir: str = "data/backtest",
    ) -> None:
        self._initial_capital = initial_capital
        self._backtest_dir = backtest_dir

    # ── Internal ──────────────────────────────────────────────────────────────

    def _load_backtest(self, filename: str) -> Optional[Dict]:
        return _load_json(os.path.join(self._backtest_dir, filename))

    # ── Sections ──────────────────────────────────────────────────────────────

    def gate_section(self) -> Dict:
        """4-state gate status.

        Returns a dict with keys: backtest, pre_paper, paper, live.
        Reads gate files defensively (missing → UNKNOWN).
        """

        def _status_from(data: Optional[Dict], key: str = "status") -> str:
            if data is None:
                return "UNKNOWN"
            return str(data.get(key, "UNKNOWN"))

        pre_paper_data = self._load_backtest("pre_paper_backtest_gate.json")
        paper_data = self._load_backtest("paper_ready_gate.json")
        owner_data = self._load_backtest("owner_paper_acceptance_gate.json")

        pre_paper_status = _status_from(pre_paper_data)
        paper_status = _status_from(paper_data)

        # Owner / live status
        owner_accepted = bool(
            (owner_data or {}).get("accepted", False)
            or (owner_data or {}).get("status") == "ACCEPTED"
        )

        # Derive backtest status from pre_paper_data strict_backtest_scope
        backtest_scope = (pre_paper_data or {}).get("strict_backtest_scope", {})
        backtest_status = backtest_scope.get("backtest_gate_status", "UNKNOWN")
        if not backtest_status:
            backtest_status = pre_paper_status  # fallback

        # Live requires paper=READY + owner accepted
        if paper_status == "READY" and owner_accepted:
            live_status = "READY"
        else:
            live_status = "NOT_READY"

        blockers: List[str] = []
        if pre_paper_status not in ("PASS", "READY"):
            blockers.append(f"Pre-paper gate: {pre_paper_status}")
        if paper_status not in ("READY", "PASS"):
            blockers.append(f"Paper-ready gate: {paper_status}")
        if not owner_accepted:
            blockers.append("Owner paper acceptance not signed")

        return {
            "section": "gate_status",
            "backtest": backtest_status,
            "pre_paper": pre_paper_status,
            "paper": paper_status,
            "live": live_status,
            "owner_accepted": owner_accepted,
            "blockers": blockers,
        }

    def research_exclusions_section(self) -> Dict:
        """Lists research-only strategies and why they're excluded from strict evidence."""
        strategies = []
        for code, info in self.RESEARCH_STRATEGIES.items():
            entry: Dict[str, Any] = {
                "code": code,
                "name": info["name"],
                "excluded_from_strict_evidence": True,
                "reason": info["reason"],
                "slots": info["slots"],
            }
            if "target_apy" in info:
                entry["target_apy"] = info["target_apy"]
            if "target_apy_gross" in info:
                entry["target_apy_gross"] = info["target_apy_gross"]
                entry["target_apy_net_range"] = info["target_apy_net_range"]
            strategies.append(entry)

        return {
            "section": "research_exclusions",
            "count": len(strategies),
            "strategies": strategies,
            "note": (
                "Research strategies are advisory only. "
                "No backtest, no paper capital, no live capital until strict evidence accepted."
            ),
        }

    def paper_performance_section(
        self,
        paper_nav: float,
        days: int,
        weekly_snapshots: Optional[List[Dict]] = None,
    ) -> Dict:
        """Paper trading performance: NAV, APY, vs backtest.

        Args:
            paper_nav: Current paper portfolio NAV (USD).
            days: Days elapsed since paper trading start.
            weekly_snapshots: Optional list of {"date": ..., "nav": ...} dicts.
        """
        initial = self._initial_capital
        pnl = paper_nav - initial
        pnl_pct = round((pnl / initial) * 100.0, 4) if initial > 0 else None
        apy = _compute_apy(paper_nav, initial, days)

        # Load backtest NAV benchmark from gate file (if available)
        pre_paper_data = self._load_backtest("pre_paper_backtest_gate.json")
        backtest_apy = None
        if pre_paper_data:
            # Try various possible keys where backtest APY might live
            scope = pre_paper_data.get("strict_backtest_scope", {})
            backtest_apy = (
                pre_paper_data.get("backtest_apy")
                or pre_paper_data.get("blended_apy")
                or scope.get("blended_apy")
                or scope.get("backtest_apy")
            )
            if backtest_apy is not None:
                backtest_apy = float(backtest_apy)

        drift: Optional[float] = None
        if apy is not None and backtest_apy is not None:
            drift = round(apy - backtest_apy, 4)

        return {
            "section": "paper_performance",
            "initial_capital": initial,
            "current_nav": round(paper_nav, 4),
            "pnl_usd": round(pnl, 4),
            "pnl_pct": pnl_pct,
            "days_elapsed": days,
            "annualised_return_pct": apy,
            "backtest_apy_pct": backtest_apy,
            "drift_vs_backtest_pct": drift,
            "weekly_snapshots": weekly_snapshots or [],
        }

    def research_shadow_section(self) -> Dict:
        """Reads data/research/rs001_shadow.json and rs002_shadow.json.

        Shows shadow performance of RS-001 and RS-002.
        Gracefully empty when files are missing.
        """
        shadows: Dict[str, Any] = {}
        base = "data/research"

        for code, filename in (("RS001", "rs001_shadow.json"), ("RS002", "rs002_shadow.json")):
            path = os.path.join(base, filename)
            data = _load_json(path)
            if data is not None:
                shadows[code] = {
                    "available": True,
                    "data": data,
                }
            else:
                shadows[code] = {
                    "available": False,
                    "note": f"Shadow file not yet generated ({filename}). "
                            "Run shadow tracker to populate.",
                }

        any_available = any(v["available"] for v in shadows.values())

        return {
            "section": "research_shadow",
            "available": any_available,
            "note": (
                "Shadow performance is simulated/research-only. "
                "Not included in strict evidence."
            ),
            "strategies": shadows,
        }

    def source_quality_section(self) -> Dict:
        """Source pipeline status from source_pipeline.json.

        Summarises clean/pending/research/missing counts.
        Works gracefully when source_pipeline.json doesn't exist.
        """
        pipeline_path = os.path.join(self._backtest_dir, "source_pipeline.json")
        data = _load_json(pipeline_path)

        if data is None:
            return {
                "section": "source_quality",
                "available": False,
                "note": "source_pipeline.json not found. Run source pipeline to generate.",
            }

        sources: Dict[str, str] = data.get("sources", {})
        counts: Dict[str, int] = {}
        for state in sources.values():
            counts[state] = counts.get(state, 0) + 1

        total = len(sources)
        clean = counts.get("clean_included", 0)
        source_needed = counts.get("source_needed", 0)
        research_only = counts.get("research_only", 0)
        pending = counts.get("pending", 0)
        review = counts.get("review", 0)
        manual_proxy = counts.get("manual_proxy", 0)

        coverage_pct = round((clean / total) * 100.0, 1) if total > 0 else 0.0

        return {
            "section": "source_quality",
            "available": True,
            "last_updated": data.get("last_updated"),
            "total_sources": total,
            "clean_included": clean,
            "pending": pending,
            "review": review,
            "manual_proxy": manual_proxy,
            "research_only": research_only,
            "source_needed": source_needed,
            "strict_coverage_pct": coverage_pct,
            "counts_by_state": counts,
            "verdict": (
                "good" if coverage_pct >= 70
                else "partial" if coverage_pct >= 30
                else "insufficient"
            ),
        }

    def generate_full_report(
        self,
        paper_nav: Optional[float] = None,
        days_elapsed: int = 9,
    ) -> Dict:
        """Generates complete weekly report JSON.

        Args:
            paper_nav: Current paper NAV. If None, uses initial_capital (flat).
            days_elapsed: Days since paper trading start.
        """
        if paper_nav is None:
            paper_nav = self._initial_capital

        report = {
            "report_type": "weekly_paper_report_v2",
            "sprint": "v9.28",
            "mp": "MP-1312",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "gate_section": self.gate_section(),
            "research_exclusions_section": self.research_exclusions_section(),
            "paper_performance_section": self.paper_performance_section(
                paper_nav=paper_nav,
                days=days_elapsed,
                weekly_snapshots=[],
            ),
            "research_shadow_section": self.research_shadow_section(),
            "source_quality_section": self.source_quality_section(),
        }
        return report

    def to_markdown(self, report: Dict) -> str:
        """Converts report dict to readable markdown."""
        lines: List[str] = []

        lines.append("# SPA Weekly Paper Report v2")
        lines.append("")

        # Header meta
        lines.append(
            f"**Generated:** {report.get('generated_at', 'N/A')}  "
        )
        lines.append(f"**Sprint:** {report.get('sprint', 'N/A')}  ")
        lines.append(f"**MP:** {report.get('mp', 'N/A')}")
        lines.append("")

        # Gate section
        gate = report.get("gate_section", {})
        lines.append("## Gate Status")
        lines.append("")
        for key in ("backtest", "pre_paper", "paper", "live"):
            val = gate.get(key, "N/A")
            lines.append(f"- **{key.replace('_', ' ').title()}:** {val}")
        blockers = gate.get("blockers", [])
        if blockers:
            lines.append("")
            lines.append("**Blockers:**")
            for b in blockers:
                lines.append(f"  - {b}")
        lines.append("")

        # Research exclusions
        excl = report.get("research_exclusions_section", {})
        lines.append("## Research Exclusions")
        lines.append("")
        lines.append(excl.get("note", ""))
        lines.append("")
        for strat in excl.get("strategies", []):
            lines.append(f"### {strat.get('name', strat.get('code', '?'))}")
            lines.append(f"- **Code:** {strat.get('code', 'N/A')}")
            lines.append(f"- **Reason:** {strat.get('reason', 'N/A')}")
            lines.append(f"- **Excluded from strict evidence:** {strat.get('excluded_from_strict_evidence', True)}")
            lines.append("")

        # Paper performance
        perf = report.get("paper_performance_section", {})
        lines.append("## Paper Performance")
        lines.append("")
        lines.append(f"- **Initial Capital:** ${perf.get('initial_capital', 0):,.2f}")
        lines.append(f"- **Current NAV:** ${perf.get('current_nav', 0):,.2f}")
        lines.append(f"- **P&L:** ${perf.get('pnl_usd', 0):,.2f} ({perf.get('pnl_pct', 0):.2f}%)")
        lines.append(f"- **Days Elapsed:** {perf.get('days_elapsed', 0)}")
        apy = perf.get("annualised_return_pct")
        lines.append(f"- **Annualised APY:** {f'{apy:.2f}%' if apy is not None else 'N/A'}")
        drift = perf.get("drift_vs_backtest_pct")
        lines.append(f"- **Drift vs Backtest:** {f'{drift:+.2f}%' if drift is not None else 'N/A'}")
        lines.append("")

        # Research shadow
        shadow = report.get("research_shadow_section", {})
        lines.append("## Research Strategy Shadow Performance")
        lines.append("")
        lines.append(shadow.get("note", ""))
        lines.append("")
        for code, info in shadow.get("strategies", {}).items():
            avail = info.get("available", False)
            lines.append(
                f"- **{code}:** {'Shadow data available' if avail else info.get('note', 'N/A')}"
            )
        lines.append("")

        # Source quality
        src = report.get("source_quality_section", {})
        lines.append("## Source Quality")
        lines.append("")
        if src.get("available"):
            lines.append(f"- **Total Sources:** {src.get('total_sources', 0)}")
            lines.append(f"- **Clean Included:** {src.get('clean_included', 0)}")
            lines.append(f"- **Strict Coverage:** {src.get('strict_coverage_pct', 0):.1f}%")
            lines.append(f"- **Verdict:** {src.get('verdict', 'N/A')}")
        else:
            lines.append(src.get("note", "Source pipeline not available."))
        lines.append("")

        return "\n".join(lines)

    def save(
        self,
        report: Dict,
        path: str = "data/paper/weekly_report_v2.json",
    ) -> None:
        """Atomic save using tmp + os.replace.

        Creates parent directory if it doesn't exist.
        """
        out_path = Path(path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        from spa_core.utils.atomic import atomic_save
        atomic_save(report, str(out_path))


# ─── CLI ──────────────────────────────────────────────────────────────────────

def _main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Weekly Paper Report v2 — MP-1312 (Sprint v9.28)"
    )
    parser.add_argument("--run", action="store_true", help="Save report to disk")
    parser.add_argument("--check", action="store_true", help="Print only (default)")
    parser.add_argument("--nav", type=float, default=None, help="Current NAV (USD)")
    parser.add_argument("--days", type=int, default=9, help="Days elapsed")
    parser.add_argument(
        "--output", default="data/paper/weekly_report_v2.json",
        help="Output path"
    )
    args = parser.parse_args()

    reporter = WeeklyPaperReportV2()
    report = reporter.generate_full_report(paper_nav=args.nav, days_elapsed=args.days)
    md = reporter.to_markdown(report)

    print(md)

    if args.run:
        reporter.save(report, args.output)
        print(f"\nReport saved → {args.output}")
    else:
        print("(dry-run — use --run to save)")


if __name__ == "__main__":
    _main()
