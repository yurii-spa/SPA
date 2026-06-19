"""
spa_core/analytics/cpa_health_dashboard.py

CLI health dashboard for the entire CPA pipeline.

Usage:
  python3 -m spa_core.analytics.cpa_health_dashboard
  python3 -m spa_core.analytics.cpa_health_dashboard --json
  python3 -m spa_core.analytics.cpa_health_dashboard --check-only  # exit code 0/1

Output (terminal):
  ╔══════════════════════════════════════════════════════╗
  ║         SPA CPA SYSTEM HEALTH DASHBOARD             ║
  ║               2026-06-19 09:00:00                   ║
  ╚══════════════════════════════════════════════════════╝

  GATE STATUS
  ──────────────────────────────
  ✅  Backtest Gate        PASS
  ✅  Pre-Paper Gate       PASS
  ⏳  Paper Trading        NOT_READY  (0 / 30 pts)
  🔒  Live Deployment      BLOCKED

  MODULES (24 total)
  ──────────────────────────────
  ✅  BacktestGate         OK
  ✅  PITEngine            OK
  ⚠️   GMXResearch          NO_DATA
  ...

  DATA SOURCES (12 tracked)
  ──────────────────────────────
  CLEAN:        2 / 12  (17%)
  IN_PROGRESS:  2 / 12
  NOT_STARTED:  8 / 12

  RESEARCH STRATEGIES
  ──────────────────────────────
  RS-001 Anti-Crisis       18.2% APY target  RESEARCH_ONLY
  RS-002 Cashflow LP       29.2% gross       RESEARCH_ONLY (SUSPENDED bearish)

  OVERALL: ⚠️  NOT_READY — Paper trading required

MP-1351 (v9.67)
stdlib only. Read-only advisory. LLM FORBIDDEN.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# ── Repo-root resolution ──────────────────────────────────────────────────────

_HERE = Path(__file__).resolve()
_REPO_ROOT = _HERE.parent.parent.parent   # spa_core/analytics/.. -> spa_core/.. -> repo
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# ── CPA module registry (24 entries) ─────────────────────────────────────────

_CPA_MODULES: list[dict] = [
    {"name": "BacktestGate",            "module": "spa_core.backtesting.gate"},
    {"name": "PITEngine",               "module": "spa_core.backtesting.pit_engine"},
    {"name": "BacktestEngine",          "module": "spa_core.backtesting.engine"},
    {"name": "SourcePipeline",          "module": "spa_core.backtesting.source_pipeline"},
    {"name": "PointInTimeWhitelist",    "module": "spa_core.backtesting.point_in_time_whitelist"},
    {"name": "PrePaperChecklist",       "module": "spa_core.backtesting.pre_paper_checklist"},
    {"name": "OwnerAcceptance",         "module": "spa_core.backtesting.owner_acceptance"},
    {"name": "SourcePromotionEngine",   "module": "spa_core.backtesting.source_promotion_engine"},
    {"name": "ResearchTournament",      "module": "spa_core.backtesting.research_tournament"},
    {"name": "ResearchScenarioMatrix",  "module": "spa_core.backtesting.research_scenario_matrix"},
    {"name": "DataLoader",              "module": "spa_core.backtesting.data_loader"},
    {"name": "PITVsNaive",              "module": "spa_core.backtesting.pit_vs_naive_comparison"},
    {"name": "CPADailyCycle",           "module": "spa_core.backtesting.cpa_daily_cycle"},
    {"name": "RunFullBacktest",         "module": "spa_core.backtesting.run_full_backtest"},
    {"name": "MultiStratBacktest",      "module": "spa_core.backtesting.multi_strategy_backtest"},
    {"name": "PaperPeriodSimulator",    "module": "spa_core.backtesting.paper_period_simulator"},
    {"name": "ScenarioRunner",          "module": "spa_core.backtesting.scenario_runner"},
    {"name": "Replay",                  "module": "spa_core.backtesting.replay"},
    {"name": "CycleRunnerCPAHook",      "module": "spa_core.backtesting.cycle_runner_cpa_hook"},
    {"name": "RunPITBacktest",          "module": "spa_core.backtesting.run_pit_backtest"},
    {"name": "PaperEvidenceV2",         "module": "spa_core.analytics.paper_evidence_tracker_v2"},
    {"name": "GMXResearch",             "module": "spa_core.adapters.gmx_research"},
    {"name": "RS001_AntiCrisis",        "module": "spa_core.strategies.s20_anticrisis_research"},
    {"name": "RS002_CashflowLP",        "module": "spa_core.strategies.s21_cashflow_research"},
]

# ── Source state groupings ────────────────────────────────────────────────────

_STATE_CLEAN       = {"clean_included"}
_STATE_IN_PROGRESS = {"pending", "manual_proxy", "review"}
_STATE_NOT_STARTED = {"source_needed", "research_only"}

# ── Research strategy constants ───────────────────────────────────────────────

_STRATEGIES = [
    {
        "id":          "RS-001",
        "name":        "Anti-Crisis",
        "apy_label":   "18.2% APY target",
        "status":      "RESEARCH_ONLY",
        "note":        "",
    },
    {
        "id":          "RS-002",
        "name":        "Cashflow LP",
        "apy_label":   "29.2% gross",
        "status":      "RESEARCH_ONLY",
        "note":        "SUSPENDED bearish",
    },
]

# ── Gate status emoji helpers ─────────────────────────────────────────────────

def _gate_icon(status: str) -> str:
    if status in ("PASS", "READY"):
        return "✅"
    if status in ("NOT_READY",):
        return "⏳"
    if status in ("BLOCKED", "FAIL"):
        return "🔒"
    return "❓"


def _module_icon(status: str) -> str:
    return "✅" if status == "OK" else "⚠️ "


# ══════════════════════════════════════════════════════════════════════════════
# CPAHealthDashboard
# ══════════════════════════════════════════════════════════════════════════════

class CPAHealthDashboard:
    """
    CLI health dashboard for the entire CPA pipeline.

    Args:
        base_dir: Root of the SPA repo. Defaults to current working directory.
    """

    def __init__(self, base_dir: str = ".") -> None:
        self._base = Path(base_dir).resolve()
        self._backtest_dir = self._base / "data" / "backtest"
        self._paper_dir    = self._base / "data" / "paper"

    # ── Gate status ───────────────────────────────────────────────────────────

    def check_gate(self) -> dict:
        """
        Returns 4-state gate status by reading BacktestGate.

        Returns::

            {
                "backtest":  "PASS" | "FAIL" | "UNKNOWN",
                "pre_paper": "PASS" | "FAIL" | "UNKNOWN",
                "paper":     "READY" | "NOT_READY" | "UNKNOWN",
                "live":      "READY" | "BLOCKED",
                "paper_pts": float,   # current evidence points
                "blockers":  [str, ...],
            }
        """
        try:
            from spa_core.backtesting.gate import BacktestGate  # type: ignore
            gate = BacktestGate(backtest_dir=str(self._backtest_dir))
            four = gate.four_state_status()
        except Exception:
            four = {
                "backtest":  "UNKNOWN",
                "pre_paper": "UNKNOWN",
                "paper":     "UNKNOWN",
                "live":      "BLOCKED",
                "blockers":  ["BacktestGate not available"],
            }

        # Pull paper evidence points from evidence_v2.json if present
        paper_pts = self._read_paper_pts()

        return {
            "backtest":  four.get("backtest",  "UNKNOWN"),
            "pre_paper": four.get("pre_paper", "UNKNOWN"),
            "paper":     four.get("paper",     "UNKNOWN"),
            "live":      four.get("live",      "BLOCKED"),
            "paper_pts": paper_pts,
            "blockers":  four.get("blockers",  []),
        }

    def _read_paper_pts(self) -> float:
        """Read accumulated evidence points from data/paper/evidence_v2.json."""
        try:
            path = self._paper_dir / "evidence_v2.json"
            with open(path) as fh:
                data = json.load(fh)
            return float(data.get("total_points", 0.0))
        except Exception:
            return 0.0

    # ── Module import check ───────────────────────────────────────────────────

    def check_modules(self) -> list:
        """
        Checks all CPA modules are importable.

        Returns list of dicts::

            [{"name": str, "module": str, "status": "OK" | "NO_DATA"}]
        """
        results = []
        for entry in _CPA_MODULES:
            try:
                importlib.import_module(entry["module"])
                status = "OK"
            except Exception:
                status = "NO_DATA"
            results.append({
                "name":   entry["name"],
                "module": entry["module"],
                "status": status,
            })
        return results

    # ── Data sources ──────────────────────────────────────────────────────────

    def check_data_sources(self) -> dict:
        """
        Source acquisition summary from data/backtest/source_pipeline.json.

        Returns::

            {
                "total":        int,
                "CLEAN":        int,
                "IN_PROGRESS":  int,
                "NOT_STARTED":  int,
                "clean_pct":    float,   # 0-1
                "sources":      {id: state, ...}
            }
        """
        sources = self._load_sources()
        total = len(sources)
        clean       = sum(1 for s in sources.values() if s in _STATE_CLEAN)
        in_progress = sum(1 for s in sources.values() if s in _STATE_IN_PROGRESS)
        not_started = sum(1 for s in sources.values() if s in _STATE_NOT_STARTED)
        clean_pct   = clean / total if total > 0 else 0.0

        return {
            "total":       total,
            "CLEAN":       clean,
            "IN_PROGRESS": in_progress,
            "NOT_STARTED": not_started,
            "clean_pct":   round(clean_pct, 4),
            "sources":     dict(sources),
        }

    def _load_sources(self) -> dict:
        """Load sources from source_pipeline.json or return DEFAULT_SOURCES."""
        path = self._backtest_dir / "source_pipeline.json"
        try:
            with open(path) as fh:
                data = json.load(fh)
            src = data.get("sources", {})
            if isinstance(src, dict) and src:
                return src
        except Exception:
            pass
        # Fall back to DEFAULT_SOURCES from source_pipeline module
        try:
            from spa_core.backtesting.source_pipeline import DEFAULT_SOURCES  # type: ignore
            return dict(DEFAULT_SOURCES)
        except Exception:
            return {}

    # ── Research strategies ───────────────────────────────────────────────────

    def check_strategies(self) -> list:
        """
        Returns RS-001 / RS-002 status list.

        Each element::

            {
                "id":        "RS-001",
                "name":      "Anti-Crisis",
                "apy_label": "18.2% APY target",
                "status":    "RESEARCH_ONLY",
                "note":      "",
            }
        """
        results = []
        for strat in _STRATEGIES:
            results.append(dict(strat))
        return results

    # ── Overall status ────────────────────────────────────────────────────────

    def overall_status(self) -> str:
        """
        Returns HEALTHY / NOT_READY / BLOCKED based on gate and paper status.

        Logic:
          BLOCKED   → live gate = BLOCKED or backtest gate = FAIL
          HEALTHY   → all gates PASS/READY and paper_pts >= 30
          NOT_READY → otherwise
        """
        gate = self.check_gate()

        if gate["live"] == "BLOCKED":
            # Check if it's just the paper gate holding us back
            if (gate["backtest"] in ("PASS", "UNKNOWN") and
                    gate["pre_paper"] in ("PASS", "UNKNOWN") and
                    gate["paper"] == "NOT_READY"):
                return "NOT_READY"
            # backtest or pre_paper failing → truly blocked
            if gate["backtest"] == "FAIL" or gate["pre_paper"] == "FAIL":
                return "BLOCKED"
            return "NOT_READY"

        if gate["paper"] == "READY" and gate["live"] == "READY":
            return "HEALTHY"

        return "NOT_READY"

    # ── Terminal renderer ─────────────────────────────────────────────────────

    def render_terminal(self) -> str:
        """Full terminal output as a string."""
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        gate    = self.check_gate()
        modules = self.check_modules()
        sources = self.check_data_sources()
        strats  = self.check_strategies()
        overall = self.overall_status()

        W = 54  # box width (inner)

        def box_line(text: str) -> str:
            return f"║  {text:<{W - 2}}║"

        lines: list[str] = []

        # Header box
        lines.append("╔" + "═" * W + "╗")
        title = "SPA CPA SYSTEM HEALTH DASHBOARD"
        lines.append("║" + title.center(W) + "║")
        lines.append("║" + now.center(W) + "║")
        lines.append("╚" + "═" * W + "╝")
        lines.append("")

        # Gate status
        lines.append("  GATE STATUS")
        lines.append("  " + "─" * 32)
        paper_pts = gate["paper_pts"]
        lines.append(
            f"  {_gate_icon(gate['backtest']):<3} Backtest Gate     "
            f"    {gate['backtest']}"
        )
        lines.append(
            f"  {_gate_icon(gate['pre_paper']):<3} Pre-Paper Gate    "
            f"    {gate['pre_paper']}"
        )
        lines.append(
            f"  {_gate_icon(gate['paper']):<3} Paper Trading     "
            f"    {gate['paper']}  ({paper_pts:.0f} / 30 pts)"
        )
        lines.append(
            f"  {_gate_icon(gate['live']):<3} Live Deployment   "
            f"    {gate['live']}"
        )
        lines.append("")

        # Modules
        ok_count    = sum(1 for m in modules if m["status"] == "OK")
        total_mods  = len(modules)
        lines.append(f"  MODULES ({total_mods} total)")
        lines.append("  " + "─" * 32)
        for m in modules:
            icon = _module_icon(m["status"])
            lines.append(f"  {icon}  {m['name']:<24} {m['status']}")
        lines.append(f"  → {ok_count}/{total_mods} modules OK")
        lines.append("")

        # Data sources
        total   = sources["total"]
        clean   = sources["CLEAN"]
        inprog  = sources["IN_PROGRESS"]
        nostart = sources["NOT_STARTED"]
        clean_p = int(sources["clean_pct"] * 100)
        lines.append(f"  DATA SOURCES ({total} tracked)")
        lines.append("  " + "─" * 32)
        lines.append(f"  CLEAN:        {clean:>2} / {total}  ({clean_p}%)")
        lines.append(f"  IN_PROGRESS:  {inprog:>2} / {total}")
        lines.append(f"  NOT_STARTED:  {nostart:>2} / {total}")
        lines.append("")

        # Research strategies
        lines.append("  RESEARCH STRATEGIES")
        lines.append("  " + "─" * 32)
        for s in strats:
            note = f"  ({s['note']})" if s["note"] else ""
            lines.append(
                f"  {s['id']} {s['name']:<14} {s['apy_label']:<18} "
                f"{s['status']}{note}"
            )
        lines.append("")

        # Overall
        icon = "✅" if overall == "HEALTHY" else ("🔒" if overall == "BLOCKED" else "⚠️ ")
        if overall == "HEALTHY":
            msg = "All systems GO"
        elif overall == "NOT_READY":
            msg = "Paper trading required"
        else:
            msg = "Critical gates failing"
        lines.append(f"  OVERALL: {icon} {overall} — {msg}")

        return "\n".join(lines)

    # ── JSON serialisable dict ────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """All sections as a JSON-serializable dict."""
        return {
            "timestamp":   datetime.now(timezone.utc).isoformat(),
            "gate":        self.check_gate(),
            "modules":     self.check_modules(),
            "data_sources": self.check_data_sources(),
            "strategies":  self.check_strategies(),
            "overall":     self.overall_status(),
        }


# ── CLI entry point ───────────────────────────────────────────────────────────

def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="SPA CPA System Health Dashboard"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON instead of terminal formatting",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        dest="check_only",
        help="Exit 0 if HEALTHY, 1 otherwise (no output)",
    )
    parser.add_argument(
        "--base-dir",
        default=".",
        dest="base_dir",
        help="Repo root directory (default: .)",
    )
    args = parser.parse_args(argv)

    dashboard = CPAHealthDashboard(base_dir=args.base_dir)

    if args.check_only:
        return 0 if dashboard.overall_status() == "HEALTHY" else 1

    if args.json:
        print(json.dumps(dashboard.to_dict(), indent=2))
        return 0

    print(dashboard.render_terminal())
    overall = dashboard.overall_status()
    return 0 if overall == "HEALTHY" else 1


if __name__ == "__main__":
    sys.exit(_main())
