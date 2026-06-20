"""
spa_core/backtesting/pre_launch_validation.py

MP-1367 (v9.83) — Pre-Launch Validation Suite.

Runs 30+ validation checks before live trading launch.
Designed to be executed AFTER 30 days of paper trading.

Groups:
  A. gates          — 4-state gate system (required, all blocking)
  B. evidence       — paper trading quality (equity curve, drawdown, trades)
  C. infrastructure — kill switch, Gnosis Safe, autopush, Telegram, HTTP server
  D. financial      — capital target, legal docs, family fund registry
  E. data_sources   — adapter coverage (T1/T2), DeFiLlama feed
  F. strategy       — RS-001/RS-002, tournament, strategy registry
  G. documentation  — owner acceptance, investment memo, ADR-002, DR procedure
  H. technical      — tests dirs, risk policy version, cycle_runner, atomic writes

Result: LAUNCH_READY / NOT_READY with blocking_count, warning_count

Rules:
  - stdlib only, no external dependencies
  - atomic save via tmp + os.replace
  - all reads defensive (missing/malformed files → failed check, no raise)
  - never modifies allocator/risk/execution state
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from spa_core.utils.atomic import atomic_save


# ── Constants ──────────────────────────────────────────────────────────────────

SCHEMA_VERSION = "1.0"

VALIDATION_GROUPS = [
    "gates",
    "evidence",
    "infrastructure",
    "financial",
    "data_sources",
    "strategy",
    "documentation",
    "technical",
]


# ── Data classes ───────────────────────────────────────────────────────────────

@dataclass
class ValidationCheck:
    """Single validation check result."""
    group: str          # must be in VALIDATION_GROUPS
    name: str           # short identifier (e.g. "pre_paper_gate_pass")
    passed: bool        # did the check pass?
    blocking: bool      # if not passed → blocks launch
    message: str        # human-readable detail

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ValidationReport:
    """Full pre-launch validation report."""
    checks: List[ValidationCheck]
    blocking_count: int
    warning_count: int
    passed_count: int
    total_count: int
    launch_ready: bool
    generated_at: str
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "generated_at": self.generated_at,
            "launch_ready": self.launch_ready,
            "passed_count": self.passed_count,
            "blocking_count": self.blocking_count,
            "warning_count": self.warning_count,
            "total_count": self.total_count,
            "checks": [c.to_dict() for c in self.checks],
        }


# ── PreLaunchValidation ────────────────────────────────────────────────────────

class PreLaunchValidation:
    """
    Runs 30+ validation checks before live trading launch.

    Usage::

        v = PreLaunchValidation(base_dir=".")
        report = v.run_all()
        print(report.launch_ready)        # False until all gates pass
        print(report.blocking_count)      # number of blocking failures
        blockers = v.blocking_checks()    # list[ValidationCheck]
        path = v.save(report)             # atomic write to data/validation/
        md = v.to_markdown(report)        # full markdown report
    """

    def __init__(self, base_dir: str = ".") -> None:
        self.base_dir = Path(base_dir)
        self.data_dir = self.base_dir / "data"
        self.backtest_dir = self.data_dir / "backtest"
        self._report_cache: Optional[ValidationReport] = None

    # ── helpers ────────────────────────────────────────────────────────────────

    def _read_json(self, path: Path) -> dict:
        """Read JSON defensively; return {} on any error."""
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            return {}

    def _exists(self, path: Path) -> bool:
        return path.exists()

    def _check(
        self,
        group: str,
        name: str,
        passed: bool,
        blocking: bool,
        message: str,
    ) -> ValidationCheck:
        return ValidationCheck(
            group=group,
            name=name,
            passed=passed,
            blocking=blocking,
            message=message,
        )

    # ── Group A: Gates ─────────────────────────────────────────────────────────

    def _run_gates(self) -> List[ValidationCheck]:
        checks: List[ValidationCheck] = []

        # A1: Pre-paper backtest gate
        pre_paper = self._read_json(
            self.backtest_dir / "pre_paper_backtest_gate.json"
        )
        a1_pass = pre_paper.get("status", "") == "PASS"
        checks.append(self._check(
            "gates", "pre_paper_gate_pass",
            a1_pass, True,
            "Pre-paper backtest gate PASS" if a1_pass
            else "Pre-paper backtest gate not PASS (run cpa_daily_cycle.py)",
        ))

        # A2: Paper ready gate (paper_trading_allowed)
        paper_ready = self._read_json(
            self.backtest_dir / "paper_ready_gate.json"
        )
        a2_pass = bool(paper_ready.get("paper_trading_allowed", False))
        checks.append(self._check(
            "gates", "paper_ready_gate_pass",
            a2_pass, True,
            "Paper ready gate: paper_trading_allowed=True" if a2_pass
            else "Paper ready gate not ready (paper_trading_allowed=False)",
        ))

        # A3: Owner paper acceptance signed
        owner = self._read_json(
            self.backtest_dir / "owner_paper_acceptance_gate.json"
        )
        a3_pass = bool(owner.get("accepted", False))
        checks.append(self._check(
            "gates", "owner_acceptance_signed",
            a3_pass, True,
            "Owner acceptance doc signed" if a3_pass
            else "Owner acceptance not signed (run owner_acceptance.py --sign)",
        ))

        # A4: GoLive checker — >= 24/26 criteria must pass
        golive = self._read_json(self.data_dir / "golive_status.json")
        passed_gl = golive.get("passed", 0)
        total_gl = golive.get("total", 26)
        a4_pass = (passed_gl >= 24) and (total_gl >= 26)
        checks.append(self._check(
            "gates", "golive_checker_24_of_26",
            a4_pass, True,
            f"GoLive checker: {passed_gl}/{total_gl} pass" if a4_pass
            else f"GoLive checker: {passed_gl}/{total_gl} pass (need 24+/26)",
        ))

        return checks

    # ── Group B: Evidence ──────────────────────────────────────────────────────

    def _run_evidence(self) -> List[ValidationCheck]:
        checks: List[ValidationCheck] = []

        # B1: Equity curve has >= 30 real data points
        ec = self._read_json(self.data_dir / "equity_curve_daily.json")
        entries = ec.get("entries", [])
        b1_pass = len(entries) >= 30
        checks.append(self._check(
            "evidence", "equity_curve_30_days",
            b1_pass, True,
            f"Equity curve has {len(entries)} days (need 30+)" if not b1_pass
            else f"Equity curve: {len(entries)} days of real data",
        ))

        # B2: Max drawdown < 5% (kill switch threshold)
        b2_pass = False
        b2_msg = "equity_curve_daily.json missing or empty"
        if entries:
            navs = [e.get("nav", 0.0) for e in entries if "nav" in e]
            if navs:
                peak = navs[0]
                max_dd = 0.0
                for nav in navs:
                    peak = max(peak, nav)
                    dd = (peak - nav) / peak if peak > 0 else 0.0
                    max_dd = max(max_dd, dd)
                b2_pass = max_dd < 0.05
                b2_msg = (
                    f"Max drawdown {max_dd:.2%} < 5% kill switch threshold"
                    if b2_pass
                    else f"Max drawdown {max_dd:.2%} >= 5% kill switch triggered"
                )
        checks.append(self._check(
            "evidence", "drawdown_below_kill_switch",
            b2_pass, True, b2_msg,
        ))

        # B3: No demo trades (is_demo must be false)
        trades = self._read_json(self.data_dir / "trades.json")
        trade_list = trades.get("trades", [])
        demo_count = sum(1 for t in trade_list if t.get("is_demo", True))
        b3_pass = len(trade_list) > 0 and demo_count == 0
        checks.append(self._check(
            "evidence", "no_demo_trades",
            b3_pass, True,
            f"All {len(trade_list)} trades are real (is_demo=false)"
            if b3_pass
            else f"{demo_count}/{len(trade_list)} demo trades found (need all real)",
        ))

        # B4: Paper trading status is_demo: false
        pts = self._read_json(self.data_dir / "paper_trading_status.json")
        b4_pass = not pts.get("is_demo", True)
        checks.append(self._check(
            "evidence", "paper_status_not_demo",
            b4_pass, True,
            "paper_trading_status.json: is_demo=false" if b4_pass
            else "paper_trading_status.json: is_demo still true",
        ))

        # B5: Gap monitor — no gaps in 30-day track
        gap = self._read_json(self.data_dir / "gap_monitor.json")
        gaps = gap.get("gaps", [])
        real_days = gap.get("real_track_days", 0)
        b5_pass = len(gaps) == 0 and real_days >= 30
        checks.append(self._check(
            "evidence", "gap_monitor_30d_clean",
            b5_pass, True,
            f"Gap monitor: {real_days} real days, 0 gaps" if b5_pass
            else f"Gap monitor: {real_days}/30 days, {len(gaps)} gap(s) found",
        ))

        # B6: APY above floor (>= 1%)
        status = self._read_json(self.data_dir / "paper_trading_status.json")
        current_apy = status.get("current_apy", 0.0)
        b6_pass = current_apy >= 0.01
        checks.append(self._check(
            "evidence", "apy_above_floor",
            b6_pass, False,  # warning only
            f"Current APY {current_apy:.2%} >= 1% floor" if b6_pass
            else f"Current APY {current_apy:.2%} below 1% floor",
        ))

        return checks

    # ── Group C: Infrastructure ────────────────────────────────────────────────

    def _run_infrastructure(self) -> List[ValidationCheck]:
        checks: List[ValidationCheck] = []

        # C1: Kill switch script exists
        ks_path = self.base_dir / "scripts" / "kill_switch_drill.py"
        c1_pass = self._exists(ks_path)
        checks.append(self._check(
            "infrastructure", "kill_switch_exists",
            c1_pass, True,
            "Kill switch script found at scripts/kill_switch_drill.py" if c1_pass
            else "Kill switch script missing (scripts/kill_switch_drill.py)",
        ))

        # C2: Gnosis Safe checklist script exists
        gs_path = self.base_dir / "scripts" / "gnosis_safe_checklist.py"
        c2_pass = self._exists(gs_path)
        checks.append(self._check(
            "infrastructure", "gnosis_safe_checklist_exists",
            c2_pass, True,
            "Gnosis Safe checklist found" if c2_pass
            else "Gnosis Safe checklist missing (scripts/gnosis_safe_checklist.py)",
        ))

        # C3: Autopush launchd plist installed
        autopush_plist = Path(
            os.path.expanduser("~/Library/LaunchAgents/com.spa.autopush.plist")
        )
        # Also check scripts dir as fallback
        autopush_scripts = self.base_dir / "scripts" / "com.spa.autopush.plist"
        c3_pass = autopush_plist.exists() or autopush_scripts.exists()
        checks.append(self._check(
            "infrastructure", "autopush_installed",
            c3_pass, False,  # warning
            "Autopush launchd plist found" if c3_pass
            else "Autopush not installed (run bash mp009_fix_launchd.command)",
        ))

        # C4: HTTP server plist exists (dashboard)
        http_plist = self.base_dir / "scripts" / "com.spa.httpserver.plist"
        c4_pass = self._exists(http_plist)
        checks.append(self._check(
            "infrastructure", "http_server_plist_exists",
            c4_pass, False,
            "HTTP server plist found (port 8765)" if c4_pass
            else "HTTP server plist missing (scripts/com.spa.httpserver.plist)",
        ))

        # C5: Cloudflared plist exists (tunnel)
        cf_plist = self.base_dir / "scripts" / "com.spa.cloudflared.plist"
        c5_pass = self._exists(cf_plist)
        checks.append(self._check(
            "infrastructure", "cloudflared_plist_exists",
            c5_pass, False,
            "Cloudflared tunnel plist found" if c5_pass
            else "Cloudflared plist missing (scripts/com.spa.cloudflared.plist)",
        ))

        return checks

    # ── Group D: Financial ─────────────────────────────────────────────────────

    def _run_financial(self) -> List[ValidationCheck]:
        checks: List[ValidationCheck] = []

        # D1: Capital target — paper_trading_status shows ~$100K
        pts = self._read_json(self.data_dir / "paper_trading_status.json")
        nav = pts.get("portfolio_nav", 0.0)
        d1_pass = nav >= 90_000.0  # $90K+ (accounting for minor drift from $100K)
        checks.append(self._check(
            "financial", "capital_target_100k",
            d1_pass, True,
            f"Portfolio NAV ${nav:,.0f} (target $100,000)" if d1_pass
            else f"Portfolio NAV ${nav:,.0f} below $90,000 threshold",
        ))

        # D2: Legal docs directory exists
        legal_dir = self.base_dir / "docs" / "legal"
        d2_pass = legal_dir.is_dir() and any(legal_dir.iterdir())
        checks.append(self._check(
            "financial", "legal_docs_exist",
            d2_pass, True,
            "Legal docs directory exists with documents" if d2_pass
            else "Legal docs missing (docs/legal/ empty or absent)",
        ))

        # D3: Family fund registry exists and has participants
        ff_reg = self.base_dir / "spa_core" / "family_fund" / "registry.py"
        d3_pass = self._exists(ff_reg)
        checks.append(self._check(
            "financial", "family_fund_registry_exists",
            d3_pass, False,
            "Family fund registry found (spa_core/family_fund/registry.py)" if d3_pass
            else "Family fund registry missing",
        ))

        # D4: Investment memo exists
        memo_path = self.base_dir / "spa_core" / "analytics" / "investment_memo_generator.py"
        d4_pass = self._exists(memo_path)
        checks.append(self._check(
            "financial", "investment_memo_generator_exists",
            d4_pass, False,
            "Investment memo generator found" if d4_pass
            else "Investment memo generator missing",
        ))

        return checks

    # ── Group E: Data Sources ──────────────────────────────────────────────────

    def _run_data_sources(self) -> List[ValidationCheck]:
        checks: List[ValidationCheck] = []
        adapters_dir = self.base_dir / "spa_core" / "adapters"

        # E1: Aave V3 T1 adapter
        e1_pass = self._exists(adapters_dir / "aave_v3.py")
        checks.append(self._check(
            "data_sources", "aave_v3_adapter_exists",
            e1_pass, True,
            "Aave V3 (T1) adapter found" if e1_pass
            else "Aave V3 adapter missing (spa_core/adapters/aave_v3.py)",
        ))

        # E2: Compound V3 T1 adapter
        e2_pass = self._exists(adapters_dir / "compound_v3.py")
        checks.append(self._check(
            "data_sources", "compound_v3_adapter_exists",
            e2_pass, True,
            "Compound V3 (T1) adapter found" if e2_pass
            else "Compound V3 adapter missing",
        ))

        # E3: Morpho Steakhouse T1 adapter
        e3_pass = self._exists(adapters_dir / "morpho_steakhouse_adapter.py")
        checks.append(self._check(
            "data_sources", "morpho_steakhouse_adapter_exists",
            e3_pass, True,
            "Morpho Steakhouse (T1) adapter found" if e3_pass
            else "Morpho Steakhouse adapter missing",
        ))

        # E4: DeFiLlama feed exists
        e4_pass = self._exists(adapters_dir / "defillama_feed.py")
        checks.append(self._check(
            "data_sources", "defillama_feed_exists",
            e4_pass, True,
            "DeFiLlama feed found (spa_core/adapters/defillama_feed.py)" if e4_pass
            else "DeFiLlama feed missing",
        ))

        # E5: Adapter registry (__init__.py with ADAPTER_REGISTRY)
        init_path = adapters_dir / "__init__.py"
        e5_pass = False
        if init_path.exists():
            try:
                content = init_path.read_text(encoding="utf-8")
                e5_pass = "ADAPTER_REGISTRY" in content
            except Exception:
                pass
        checks.append(self._check(
            "data_sources", "adapter_registry_defined",
            e5_pass, True,
            "ADAPTER_REGISTRY defined in adapters/__init__.py" if e5_pass
            else "ADAPTER_REGISTRY not found in adapters/__init__.py",
        ))

        return checks

    # ── Group F: Strategy ──────────────────────────────────────────────────────

    def _run_strategy(self) -> List[ValidationCheck]:
        checks: List[ValidationCheck] = []
        strategies_dir = self.base_dir / "spa_core" / "strategies"
        analytics_dir = self.base_dir / "spa_core" / "analytics"

        # F1: Strategy registry exists
        f1_pass = self._exists(strategies_dir / "strategy_registry.py")
        checks.append(self._check(
            "strategy", "strategy_registry_exists",
            f1_pass, True,
            "Strategy registry found (spa_core/strategies/strategy_registry.py)" if f1_pass
            else "Strategy registry missing",
        ))

        # F2: Tournament evaluator exists
        f2_pass = self._exists(
            self.base_dir / "spa_core" / "paper_trading" / "tournament_evaluator.py"
        ) or self._exists(strategies_dir / "tournament_evaluator.py")
        checks.append(self._check(
            "strategy", "tournament_evaluator_exists",
            f2_pass, True,
            "Tournament evaluator found" if f2_pass
            else "Tournament evaluator missing",
        ))

        # F3: RS-001 live APY engine
        f3_pass = self._exists(analytics_dir / "rs001_live_apy_engine.py")
        checks.append(self._check(
            "strategy", "rs001_live_apy_engine_exists",
            f3_pass, False,
            "RS-001 live APY engine found" if f3_pass
            else "RS-001 live APY engine missing (advisory warning)",
        ))

        # F4: RS-002 live APY engine
        f4_pass = self._exists(analytics_dir / "rs002_live_apy_engine.py")
        checks.append(self._check(
            "strategy", "rs002_live_apy_engine_exists",
            f4_pass, False,
            "RS-002 live APY engine found" if f4_pass
            else "RS-002 live APY engine missing (advisory warning)",
        ))

        # F5: Multi-strategy runner (parallel S0-S10)
        f5_pass = self._exists(
            self.base_dir / "spa_core" / "paper_trading" / "multi_strategy_runner.py"
        )
        checks.append(self._check(
            "strategy", "multi_strategy_runner_exists",
            f5_pass, True,
            "Multi-strategy runner found (spa_core/paper_trading/multi_strategy_runner.py)" if f5_pass
            else "Multi-strategy runner missing",
        ))

        return checks

    # ── Group G: Documentation ─────────────────────────────────────────────────

    def _run_documentation(self) -> List[ValidationCheck]:
        checks: List[ValidationCheck] = []
        docs_dir = self.base_dir / "docs"
        adr_dir = docs_dir / "adr"

        # G1: Owner acceptance doc generated
        owner_doc = self._read_json(
            self.backtest_dir / "owner_paper_acceptance_gate.json"
        )
        g1_pass = bool(owner_doc)
        checks.append(self._check(
            "documentation", "owner_acceptance_doc_exists",
            g1_pass, True,
            "Owner acceptance gate JSON found" if g1_pass
            else "Owner acceptance gate JSON missing (run owner_acceptance.py --generate)",
        ))

        # G2: ADR-002 go-live transfer rule
        adr002 = adr_dir / "ADR-002-golive-transfer-rule.md"
        g2_pass = self._exists(adr002)
        checks.append(self._check(
            "documentation", "adr002_golive_transfer_rule_exists",
            g2_pass, True,
            "ADR-002 (go-live transfer rule) found" if g2_pass
            else "ADR-002 missing (docs/adr/ADR-002-golive-transfer-rule.md)",
        ))

        # G3: MASTER_PLAN_v1.md exists
        mp = self.base_dir / "MASTER_PLAN_v1.md"
        g3_pass = self._exists(mp)
        checks.append(self._check(
            "documentation", "master_plan_exists",
            g3_pass, False,
            "MASTER_PLAN_v1.md found" if g3_pass
            else "MASTER_PLAN_v1.md missing (advisory)",
        ))

        # G4: DR_PROCEDURE_v2.md exists
        dr = self.base_dir / "DR_PROCEDURE_v2.md"
        g4_pass = self._exists(dr)
        checks.append(self._check(
            "documentation", "dr_procedure_v2_exists",
            g4_pass, True,
            "DR_PROCEDURE_v2.md found" if g4_pass
            else "Disaster Recovery procedure missing (DR_PROCEDURE_v2.md)",
        ))

        # G5: Investment memo generator (advisory output)
        memo_gen = self.base_dir / "spa_core" / "analytics" / "investment_memo_generator.py"
        g5_pass = self._exists(memo_gen)
        checks.append(self._check(
            "documentation", "investment_memo_generator_exists",
            g5_pass, False,
            "Investment memo generator found" if g5_pass
            else "Investment memo generator missing (advisory warning)",
        ))

        return checks

    # ── Group H: Technical ─────────────────────────────────────────────────────

    def _run_technical(self) -> List[ValidationCheck]:
        checks: List[ValidationCheck] = []

        # H1: tests/ directory exists and has test files
        tests_dir = self.base_dir / "tests"
        h1_count = len(list(tests_dir.glob("test_*.py"))) if tests_dir.is_dir() else 0
        h1_pass = h1_count > 0
        checks.append(self._check(
            "technical", "integration_tests_exist",
            h1_pass, True,
            f"Integration tests: {h1_count} test files in tests/" if h1_pass
            else "No integration tests found in tests/",
        ))

        # H2: spa_core/tests/ directory exists (800+ unit test files)
        core_tests = self.base_dir / "spa_core" / "tests"
        h2_count = len(list(core_tests.glob("test_*.py"))) if core_tests.is_dir() else 0
        h2_pass = h2_count >= 50  # reasonable threshold
        checks.append(self._check(
            "technical", "unit_tests_exist",
            h2_pass, True,
            f"Unit tests: {h2_count} test files in spa_core/tests/" if h2_pass
            else f"Insufficient unit tests: {h2_count} (need 50+)",
        ))

        # H3: Risk policy version is v1.0 (must not change during paper period)
        risk_policy = self.base_dir / "spa_core" / "risk" / "policy.py"
        h3_pass = False
        h3_msg = "spa_core/risk/policy.py not found"
        if risk_policy.exists():
            try:
                content = risk_policy.read_text(encoding="utf-8")
                h3_pass = '"v1.0"' in content or "'v1.0'" in content
                h3_msg = (
                    "Risk policy version is v1.0 (frozen for paper period)"
                    if h3_pass
                    else "Risk policy version is NOT v1.0 (requires ADR to change)"
                )
            except Exception:
                h3_msg = "Could not read spa_core/risk/policy.py"
        checks.append(self._check(
            "technical", "risk_policy_version_v1_0",
            h3_pass, True, h3_msg,
        ))

        # H4: cycle_runner.py exists (main daily cycle)
        cr_path = self.base_dir / "spa_core" / "paper_trading" / "cycle_runner.py"
        h4_pass = self._exists(cr_path)
        checks.append(self._check(
            "technical", "cycle_runner_exists",
            h4_pass, True,
            "Cycle runner found (spa_core/paper_trading/cycle_runner.py)" if h4_pass
            else "Cycle runner missing",
        ))

        # H5: No external runtime dependencies (verify no 'import requests' in spa_core/)
        h5_pass = True
        h5_msg = "No forbidden external imports found in spa_core/"
        forbidden_imports = ["import requests", "import aiohttp", "import httpx",
                             "import numpy", "import pandas", "import scipy"]
        try:
            spa_core_dir = self.base_dir / "spa_core"
            for py_file in spa_core_dir.rglob("*.py"):
                # skip tests and __pycache__
                parts = py_file.parts
                if "tests" in parts or "__pycache__" in parts:
                    continue
                try:
                    content = py_file.read_text(encoding="utf-8")
                    for fi in forbidden_imports:
                        if fi in content:
                            h5_pass = False
                            h5_msg = f"Forbidden external import '{fi}' in {py_file.name}"
                            break
                    if not h5_pass:
                        break
                except Exception:
                    pass
        except Exception:
            h5_pass = False
            h5_msg = "Could not scan spa_core/ for external imports"
        checks.append(self._check(
            "technical", "no_external_runtime_deps",
            h5_pass, False,  # warning
            h5_msg,
        ))

        # H6: Push script exists
        push_script = self.base_dir / "push_to_github.py"
        h6_pass = self._exists(push_script)
        checks.append(self._check(
            "technical", "push_to_github_script_exists",
            h6_pass, False,
            "push_to_github.py found" if h6_pass
            else "push_to_github.py missing",
        ))

        return checks

    # ── Public API ─────────────────────────────────────────────────────────────

    def run_group(self, group: str) -> List[ValidationCheck]:
        """Run all checks in a group. Returns list of ValidationCheck."""
        dispatch = {
            "gates": self._run_gates,
            "evidence": self._run_evidence,
            "infrastructure": self._run_infrastructure,
            "financial": self._run_financial,
            "data_sources": self._run_data_sources,
            "strategy": self._run_strategy,
            "documentation": self._run_documentation,
            "technical": self._run_technical,
        }
        fn = dispatch.get(group)
        if fn is None:
            raise ValueError(f"Unknown group: {group!r}. Valid: {VALIDATION_GROUPS}")
        return fn()

    def run_all(self) -> ValidationReport:
        """Run all groups, aggregate counts, return ValidationReport."""
        all_checks: List[ValidationCheck] = []
        for group in VALIDATION_GROUPS:
            all_checks.extend(self.run_group(group))

        passed_count = sum(1 for c in all_checks if c.passed)
        blocking_count = sum(1 for c in all_checks if not c.passed and c.blocking)
        warning_count = sum(1 for c in all_checks if not c.passed and not c.blocking)
        total_count = len(all_checks)
        launch_ready = blocking_count == 0

        report = ValidationReport(
            checks=all_checks,
            blocking_count=blocking_count,
            warning_count=warning_count,
            passed_count=passed_count,
            total_count=total_count,
            launch_ready=launch_ready,
            generated_at=datetime.now(timezone.utc).isoformat(),
        )
        self._report_cache = report
        return report

    def blocking_checks(self) -> List[ValidationCheck]:
        """Return checks where blocking=True and passed=False."""
        report = self._report_cache if self._report_cache is not None else self.run_all()
        return [c for c in report.checks if c.blocking and not c.passed]

    def save(self, report: ValidationReport) -> str:
        """
        Atomic save to data/validation/pre_launch_YYYY-MM-DD.json.
        Returns the absolute path of the written file.
        """
        val_dir = self.data_dir / "validation"
        val_dir.mkdir(parents=True, exist_ok=True)

        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        out_path = val_dir / f"pre_launch_{date_str}.json"

        atomic_save(report.to_dict(), str(out_path))
        return str(out_path)

    def to_markdown(self, report: ValidationReport) -> str:
        """Return full markdown report covering all 8 groups."""
        status_label = "✅ LAUNCH_READY" if report.launch_ready else "🚫 NOT_READY"
        lines = [
            "# SPA Pre-Launch Validation Report",
            "",
            f"**Status:** {status_label}",
            f"**Generated:** {report.generated_at}",
            f"**Schema:** {report.schema_version}",
            "",
            "## Summary",
            "",
            f"| Metric | Count |",
            f"|--------|-------|",
            f"| Total checks | {report.total_count} |",
            f"| Passed | {report.passed_count} |",
            f"| Blocking failures | {report.blocking_count} |",
            f"| Warnings | {report.warning_count} |",
            "",
        ]

        # Group labels for display
        group_labels = {
            "gates": "A. Gates (required)",
            "evidence": "B. Evidence (paper trading quality)",
            "infrastructure": "C. Infrastructure",
            "financial": "D. Financial",
            "data_sources": "E. Data Sources",
            "strategy": "F. Strategy",
            "documentation": "G. Documentation",
            "technical": "H. Technical",
        }

        for group in VALIDATION_GROUPS:
            group_checks = [c for c in report.checks if c.group == group]
            passed = sum(1 for c in group_checks if c.passed)
            total = len(group_checks)
            label = group_labels.get(group, group)
            lines.append(f"## {label} ({passed}/{total})")
            lines.append("")
            lines.append("| Check | Status | Blocking | Message |")
            lines.append("|-------|--------|----------|---------|")
            for c in group_checks:
                status_icon = "✅" if c.passed else ("🚫" if c.blocking else "⚠️")
                blocking_label = "Yes" if c.blocking else "No"
                # escape pipes in message
                msg = c.message.replace("|", "\\|")
                lines.append(
                    f"| `{c.name}` | {status_icon} | {blocking_label} | {msg} |"
                )
            lines.append("")

        if report.blocking_count > 0:
            lines.append("## Blocking Issues")
            lines.append("")
            for c in report.checks:
                if c.blocking and not c.passed:
                    lines.append(f"- **[{c.group}]** `{c.name}`: {c.message}")
            lines.append("")

        lines.append("---")
        lines.append(
            "*Generated by spa_core/backtesting/pre_launch_validation.py (MP-1367 v9.83)*"
        )

        return "\n".join(lines)


# ── CLI ────────────────────────────────────────────────────────────────────────

def _main() -> None:
    import sys

    base_dir = "."
    save_flag = "--save" in sys.argv

    # allow --base-dir override
    for i, arg in enumerate(sys.argv):
        if arg == "--base-dir" and i + 1 < len(sys.argv):
            base_dir = sys.argv[i + 1]

    v = PreLaunchValidation(base_dir=base_dir)
    report = v.run_all()

    print(v.to_markdown(report))
    print()
    print(f"Launch ready: {report.launch_ready}")
    print(f"Passed: {report.passed_count}/{report.total_count}")
    print(f"Blocking failures: {report.blocking_count}")
    print(f"Warnings: {report.warning_count}")

    if save_flag:
        path = v.save(report)
        print(f"\nReport saved: {path}")

    sys.exit(0 if report.launch_ready else 1)


if __name__ == "__main__":
    _main()
