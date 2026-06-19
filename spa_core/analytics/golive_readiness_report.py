"""
spa_core/analytics/golive_readiness_report.py

Complete go-live readiness assessment.
Aggregates: gate status, source quality, evidence points, owner acceptance,
            infrastructure, capital.

Output: data/reports/golive_readiness_YYYY-MM-DD.json + .md

MP-1353 (v9.69) — stdlib only, atomic writes, read-only analysis.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional

from spa_core.base import BaseAnalytics


# ── Constants ──────────────────────────────────────────────────────────────────

SCHEMA_VERSION = "1.0"
EVIDENCE_TARGET = 30.0   # points needed for paper gate

READINESS_CATEGORIES = [
    "gate_status",        # 4-state gate (Backtest/Pre-Paper/Paper/Live)
    "data_quality",       # source pipeline % CLEAN
    "evidence_points",    # current accumulated evidence points
    "owner_acceptance",   # is acceptance doc signed?
    "infrastructure",     # gnosis safe, kill switch, CI
    "capital",            # actual capital ($100K ready?)
]


# ── CategoryScore ──────────────────────────────────────────────────────────────

class CategoryScore:
    """Score for a single readiness category."""

    def __init__(
        self,
        name: str,
        score: float,
        max_score: float,
        items_done: List[str],
        items_pending: List[str],
        notes: str = "",
    ) -> None:
        self.name = str(name)
        self.score = float(score)
        self.max_score = float(max_score)
        self.items_done = list(items_done)
        self.items_pending = list(items_pending)
        self.notes = str(notes)

    @property
    def pct(self) -> float:
        """Score as percentage of max (0.0–100.0)."""
        if self.max_score <= 0.0:
            return 0.0
        return self.score / self.max_score * 100.0

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "score": round(self.score, 2),
            "max_score": round(self.max_score, 2),
            "pct": round(self.pct, 1),
            "items_done": self.items_done,
            "items_pending": self.items_pending,
            "notes": self.notes,
        }


# ── GoLiveReadinessReport ──────────────────────────────────────────────────────

class GoLiveReadinessReport(BaseAnalytics):
    """
    Full go-live readiness assessment across 6 categories.

    Usage::

        report = GoLiveReadinessReport(base_dir=".")
        print(report.overall_status())   # READY / NOT_READY / BLOCKED
        print(report.total_score())      # 0.0–100.0
        print(report.blocking_items())   # list[str]
        path = report.save()             # writes JSON + MD to data/reports/
    """

    OUTPUT_PATH = "data/reports/golive_readiness.json"

    def __init__(self, base_dir: str = ".") -> None:
        super().__init__(base_dir)
        self.base_dir = Path(base_dir)
        self.data_dir = self.base_dir / "data"
        self.backtest_dir = self.data_dir / "backtest"
        self._categories_cache: Optional[List[CategoryScore]] = None

    def to_dict(self) -> dict:
        """Returns go-live readiness report as JSON-serializable dict."""
        cats = self._get_categories()
        return {
            "schema_version": SCHEMA_VERSION,
            "overall_status": self.overall_status(),
            "total_score": self.total_score(),
            "estimated_days_to_ready": self.estimated_days_to_ready(),
            "categories": [c.to_dict() for c in cats],
            "blocking_items": self.blocking_items(),
        }

    # ── helpers ────────────────────────────────────────────────────────────────

    def _read_json(self, path: Path) -> dict:
        """Read JSON defensively; return {} on any error."""
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            return {}

    # ── category assessments ───────────────────────────────────────────────────

    def assess_gate_status(self) -> CategoryScore:
        """Gate system: Backtest PASS=25pts, Pre-Paper PASS=25pts, Paper PASS=25pts, Live=25pts"""
        items_done: List[str] = []
        items_pending: List[str] = []
        score = 0.0
        max_score = 100.0

        # ── 1. Backtest Gate ──
        bg = self._read_json(self.backtest_dir / "pre_paper_backtest_gate.json")
        if bg.get("status") == "PASS":
            score += 25.0
            items_done.append("Backtest Gate: PASS (P0/P1A/P2 closed)")
        else:
            items_pending.append(
                f"Backtest Gate: {bg.get('status', 'UNKNOWN')} — run CPA backtest"
            )

        # ── 2. Pre-Paper Gate ──
        pg = self._read_json(self.backtest_dir / "paper_ready_gate.json")
        if pg.get("status") in ("READY", "PASS"):
            score += 25.0
            items_done.append("Pre-Paper Gate: READY")
        else:
            blockers = []
            hardening = pg.get("hardening_status", "")
            if hardening not in ("PASS", "READY", ""):
                blockers.append(f"hardening_status={hardening}")
            exp_uni = pg.get("expanded_universe_verification_status", "")
            if exp_uni == "STRICT_BLOCKED":
                blockers.append("expanded_universe STRICT_BLOCKED (P1B sources missing)")
            label = "; ".join(blockers) if blockers else pg.get("status", "NOT_READY")
            items_pending.append(f"Pre-Paper Gate: NOT_READY — {label}")

        # ── 3. Paper Trading Gate (track days) ──
        gs = self._read_json(self.data_dir / "golive_status.json")
        checks = gs.get("checks", {})
        if checks.get("min_track_days_30"):
            score += 25.0
            items_done.append("Paper Trading Gate: 30+ gap-free days complete")
        else:
            track_days = 0
            for b in gs.get("blockers", []):
                m = re.search(r"(\d+)/30 (?:real track|honest paper)", b)
                if m:
                    track_days = int(m.group(1))
                    break
            if track_days == 0:
                # check consecutive_ready_days
                track_days = gs.get("consecutive_ready_days", 1) or 1
            needed = max(0, 30 - track_days)
            items_pending.append(
                f"Paper Trading Gate: {track_days}/30 days ({needed} more needed)"
            )

        # ── 4. Live Gate ──
        owner_acc_path = self.data_dir / "backtest" / "owner_paper_acceptance.json"
        owner_acc = self._read_json(owner_acc_path)
        owner_signed = (owner_acc.get("accepted") is True)
        paper_pass = (score >= 75.0)

        if paper_pass and owner_signed:
            score += 25.0
            items_done.append("Live Gate: UNBLOCKED")
        else:
            pending_live = []
            if not paper_pass:
                pending_live.append("complete Pre-Paper + Paper gates")
            if not owner_signed:
                pending_live.append("owner acceptance not signed")
            items_pending.append("Live Gate: BLOCKED — " + "; ".join(pending_live))

        return CategoryScore(
            "gate_status", score, max_score, items_done, items_pending,
            notes=f"{score:.0f}/{max_score:.0f} pts",
        )

    def assess_data_quality(self) -> CategoryScore:
        """Source quality: % of sources with status clean_included."""
        sp = self._read_json(self.backtest_dir / "source_pipeline.json")
        sources: dict = sp.get("sources", {})

        items_done: List[str] = []
        items_pending: List[str] = []

        if not sources:
            return CategoryScore(
                "data_quality", 0.0, 100.0, [],
                ["source_pipeline.json not found or empty — run source promotion"],
                "0/0 CLEAN",
            )

        clean_states = {"clean_included"}
        clean = [k for k, v in sources.items() if v in clean_states]
        total = len(sources)
        pct = len(clean) / total * 100.0
        score = pct  # score equals clean%

        for name in sorted(clean):
            items_done.append(f"{name}: clean_included ✓")

        for name, state in sorted(sources.items()):
            if state not in clean_states:
                items_pending.append(f"{name}: {state} → promote to CLEAN")

        return CategoryScore(
            "data_quality", score, 100.0, items_done, items_pending,
            notes=f"{len(clean)}/{total} CLEAN ({pct:.0f}%) — target: 100%",
        )

    def assess_evidence_points(self) -> CategoryScore:
        """Evidence accumulation: current_pts / 30 pts target."""
        ev = self._read_json(self.data_dir / "paper" / "evidence_v2.json")
        items_done: List[str] = []
        items_pending: List[str] = []

        current = float(
            ev.get("total_evidence_points", ev.get("total_points", 0.0))
        )
        target = EVIDENCE_TARGET
        score = min(current / target * 100.0, 100.0) if target > 0 else 0.0

        if current >= target:
            items_done.append(
                f"Evidence: {current:.1f}/{target:.0f} pts — SUFFICIENT"
            )
        else:
            needed = target - current
            items_pending.append(
                f"Evidence: {current:.1f}/{target:.0f} pts — need {needed:.1f} more"
            )
            items_pending.append(
                "Each paper day adds 0.3–1.5 pts (extreme market=1.5, CLEAN+low drift=1.0)"
            )
            items_pending.append(
                f"Estimated days at CLEAN rate: ~{int(needed / 1.0) + 1} days"
            )

        return CategoryScore(
            "evidence_points", score, 100.0, items_done, items_pending,
            notes=f"{current:.1f}/{target:.0f} pts",
        )

    def assess_owner_acceptance(self) -> CategoryScore:
        """Is owner_acceptance.json present and signed?"""
        acc = self._read_json(
            self.data_dir / "backtest" / "owner_paper_acceptance.json"
        )
        gate = self._read_json(
            self.backtest_dir / "owner_paper_acceptance_gate.json"
        )
        items_done: List[str] = []
        items_pending: List[str] = []

        if acc.get("accepted") is True:
            score = 100.0
            owner = acc.get("owner", "unknown")
            signed_at = acc.get("accepted_at", "unknown")
            items_done.append(f"Owner acceptance signed by: {owner}")
            items_done.append(f"Signed at: {signed_at}")
        else:
            score = 0.0
            gate_status = gate.get("status", "NOT_SIGNED")
            items_pending.append(f"Owner acceptance: {gate_status}")
            for b in gate.get("blockers", []):
                items_pending.append(f"  — {b}")
            items_pending.append(
                "Fix: python3 -m spa_core.backtesting.owner_acceptance "
                "--generate-draft  → review draft → sign"
            )

        return CategoryScore(
            "owner_acceptance", score, 100.0, items_done, items_pending,
            notes="SIGNED" if score == 100.0 else "NOT_SIGNED",
        )

    def assess_infrastructure(self) -> CategoryScore:
        """Infrastructure: launchd daemons, kill switch, Gnosis Safe, CI."""
        gs = self._read_json(self.data_dir / "golive_status.json")
        checks = gs.get("checks", {})

        items_done: List[str] = []
        items_pending: List[str] = []

        # Each check: (golive_key, label, pts)
        INFRA_CHECKS = [
            ("autopush_installed",    "autopush launchd daemon",        15.0),
            ("http_server",           "HTTP dashboard (port 8765)",      10.0),
            ("cycle_runner_exists",   "cycle_runner.py present",         15.0),
            ("multi_strategy_runner", "multi_strategy_runner.py present", 10.0),
            ("safe_tx_builder",       "Gnosis Safe TX builder",          20.0),
            ("promotion_engine",      "promotion_engine.py present",     10.0),
            ("gap_monitor_ok",        "gap_monitor: no gaps",            10.0),
            ("adr022_exists",         "ADR-022 present",                 10.0),
        ]

        score = 0.0
        max_score = sum(pts for _, _, pts in INFRA_CHECKS)

        for key, label, pts in INFRA_CHECKS:
            if checks.get(key):
                score += pts
                items_done.append(f"{label}: ✓")
            else:
                items_pending.append(f"{label}: missing/failed")

        return CategoryScore(
            "infrastructure", score, max_score, items_done, items_pending,
            notes=f"{score:.0f}/{max_score:.0f} pts",
        )

    def assess_capital(self) -> CategoryScore:
        """Capital: virtual $100K USDC ready, equity curve populated, portfolio active."""
        pts_data = self._read_json(self.data_dir / "paper_trading_status.json")
        eq_data = self._read_json(self.data_dir / "equity_curve_daily.json")
        pos_data = self._read_json(self.data_dir / "current_positions.json")

        items_done: List[str] = []
        items_pending: List[str] = []
        score = 0.0
        max_score = 100.0

        # ── 1. Virtual capital check (50 pts) ──
        # Check multiple field names used across different schema versions
        capital = float(
            pts_data.get("virtual_capital",
                pts_data.get("total_capital",
                    pts_data.get("capital",
                        pts_data.get("current_equity", 0))))
        )
        # Fallback: current_positions.json capital_usd
        if capital == 0:
            capital = float(pos_data.get("capital_usd", 0))
        is_demo = pts_data.get("is_demo", pos_data.get("is_demo", True))

        if capital >= 100_000 and not is_demo:
            score += 50.0
            items_done.append(
                f"Virtual capital: ${capital:,.0f} USDC (is_demo=False) ✓"
            )
        elif capital >= 100_000:
            score += 25.0
            items_pending.append(
                f"Capital allocated (${capital:,.0f}) but is_demo={is_demo}"
            )
        elif capital > 0:
            score += 10.0
            items_pending.append(
                f"Insufficient capital: ${capital:,.0f} (need $100,000)"
            )
        else:
            items_pending.append("Virtual capital not initialised ($0)")

        # ── 2. Equity curve check (30 pts) ──
        # Support multiple storage schemas: list / {daily:[...]} / {entries:[...]} / {data:[...]}
        if isinstance(eq_data, list):
            curve = eq_data
        elif isinstance(eq_data, dict):
            curve = (
                eq_data.get("daily")
                or eq_data.get("entries")
                or eq_data.get("data")
                or []
            )
        else:
            curve = []
        # Also accept summary.num_days as supplementary count
        num_days_summary = (
            eq_data.get("summary", {}).get("num_days", 0)
            if isinstance(eq_data, dict) else 0
        )
        eff_days = max(len(curve) if isinstance(curve, list) else 0, num_days_summary)

        if eff_days >= 30:
            score += 30.0
            items_done.append(f"Equity curve: {eff_days} days recorded ✓")
        elif eff_days >= 7:
            score += 20.0
            items_done.append(f"Equity curve: {eff_days} day(s) recorded")
            items_pending.append(f"Need 30+ equity curve entries ({30 - eff_days} more)")
        elif eff_days >= 1:
            score += 15.0
            items_done.append(f"Equity curve: {eff_days} day(s) recorded")
            items_pending.append(f"Need 30+ equity curve entries ({30 - eff_days} more)")
        else:
            items_pending.append("Equity curve: no entries yet")

        # ── 3. Active portfolio check (10 pts) ──
        deployed = float(pos_data.get("deployed_usd", 0))
        cap_ref = float(pos_data.get("capital_usd", capital or 1.0))
        if cap_ref > 0 and deployed / cap_ref >= 0.5:
            score += 10.0
            items_done.append(
                f"Portfolio active: ${deployed:,.0f} deployed "
                f"({deployed / cap_ref * 100:.0f}% of capital) ✓"
            )
        elif deployed > 0:
            items_pending.append(
                f"Portfolio underdeployed: ${deployed:,.0f} ({deployed / cap_ref * 100:.0f}%)"
            )
        else:
            items_pending.append("Portfolio: no positions deployed")

        # ── 4. Base allocation credit (20 pts) ──
        items_pending.append(
            "For LIVE: $100K actual USDC must be deposited in Gnosis Safe"
        )
        score += 20.0  # paper virtual capital is pre-allocated (always given)

        score = min(score, max_score)

        return CategoryScore(
            "capital", score, max_score, items_done, items_pending,
            notes=f"${capital:,.0f} virtual, is_demo={is_demo}",
        )

    def assess_documentation(self) -> CategoryScore:
        """Documentation: key policy, runbook and reference docs present and non-empty."""
        docs_dir = self.base_dir / "docs"
        adr_dir = docs_dir / "adr"

        items_done: List[str] = []
        items_pending: List[str] = []

        # Required documents: (filename, label, pts)
        REQUIRED_DOCS = [
            ("RISK_MANAGEMENT_POLICY.md",  "Risk Management Policy",      10.0),
            ("DEPLOYMENT_RUNBOOK.md",       "Deployment Runbook",          10.0),
            ("DATA_SOURCES_REGISTRY.md",    "Data Sources Registry",       10.0),
            ("FAMILY_FUND_ONBOARDING.md",   "Family Fund Onboarding",      10.0),
            ("API_REFERENCE.md",            "API Reference",               10.0),
            ("SECURITY_CHECKLIST.md",       "Security Checklist",          10.0),
            ("DISASTER_RECOVERY.md",        "Disaster Recovery Procedure", 10.0),
            ("TOKEN_ROTATION_RUNBOOK.md",   "Token Rotation Runbook",      10.0),
        ]
        ADR_MIN = 3
        ADR_PTS = 20.0
        MIN_BYTES = 500

        score = 0.0
        max_score = sum(pts for _, _, pts in REQUIRED_DOCS) + ADR_PTS

        for filename, label, pts in REQUIRED_DOCS:
            path = docs_dir / filename
            try:
                size = path.stat().st_size
            except OSError:
                size = 0
            if size >= MIN_BYTES:
                score += pts
                items_done.append(f"{label}: ✓ ({size:,} bytes)")
            else:
                items_pending.append(
                    f"{label}: missing or too small — create docs/{filename}"
                )

        # ADR directory check
        try:
            adr_files = [f for f in adr_dir.iterdir() if f.suffix == ".md"]
        except OSError:
            adr_files = []

        if len(adr_files) >= ADR_MIN:
            score += ADR_PTS
            items_done.append(f"ADR directory: {len(adr_files)} ADRs present ✓")
        else:
            items_pending.append(
                f"ADR directory: need ≥{ADR_MIN} ADR files (found {len(adr_files)})"
            )

        return CategoryScore(
            "documentation", score, max_score, items_done, items_pending,
            notes=f"{score:.0f}/{max_score:.0f} pts",
        )

    # ── v10.41–42 NEW category assessors (max_score directly in pts) ──────────

    def assess_gates(self) -> CategoryScore:
        """Gates: Backtest/Pre-Paper/Paper progress. Max 20 pts.
        MP-1425 (v10.41)
        """
        items_done: List[str] = []
        items_pending: List[str] = []
        score = 0.0
        max_score = 20.0

        # Backtest gate: +8
        bg = self._read_json(self.backtest_dir / "pre_paper_backtest_gate.json")
        if bg.get("status") == "PASS":
            score += 8.0
            items_done.append("Backtest Gate: PASS ✓")
        else:
            items_pending.append(
                f"Backtest Gate: {bg.get('status', 'UNKNOWN')} — run CPA backtest"
            )

        # Pre-paper gate: +8
        pg = self._read_json(self.backtest_dir / "paper_ready_gate.json")
        if pg.get("status") in ("READY", "PASS"):
            score += 8.0
            items_done.append("Pre-Paper Gate: READY ✓")
        else:
            items_pending.append("Pre-Paper Gate: NOT_READY — resolve hardening + P1B sources")

        # Paper trading started (≥1 day): +2
        pe = self._read_json(self.data_dir / "paper_evidence.json")
        paper_days = len(pe.get("days", [])) if isinstance(pe, dict) else 0
        eq = self._read_json(self.data_dir / "equity_curve_daily.json")
        if isinstance(eq, list):
            eq_days = len(eq)
        elif isinstance(eq, dict):
            eq_days = len(
                eq.get("daily") or eq.get("entries") or eq.get("data") or []
            )
        else:
            eq_days = 0
        effective_days = max(paper_days, eq_days)

        if effective_days >= 1:
            score += 2.0
            items_done.append(f"Paper trading started: {effective_days} day(s) ✓")
        else:
            items_pending.append("Paper trading not started yet")

        # Paper ≥7 days: +2
        if effective_days >= 7:
            score += 2.0
            items_done.append(f"Paper 7+ days: {effective_days} ✓")
        else:
            items_pending.append(
                f"Paper track: {effective_days}/7 days "
                f"({max(0, 7 - effective_days)} more for +2 pts)"
            )

        return CategoryScore(
            "gates", score, max_score, items_done, items_pending,
            notes=f"{score:.0f}/{max_score:.0f} pts",
        )

    def assess_evidence(self) -> CategoryScore:
        """Evidence infrastructure + accumulated paper cycles. Max 25 pts.
        MP-1426 (v10.42)
          +5  evidence_auto_calculator.py exists
          +5  paper_evidence_history.json initialized
          +5  ≥5 completed cycles  (cumulative tiers)
          +5  ≥10 completed cycles
          +5  ≥20 completed cycles
        """
        items_done: List[str] = []
        items_pending: List[str] = []
        score = 0.0
        max_score = 25.0

        # Infrastructure: auto-calculator
        calc_path = (
            self.base_dir / "spa_core" / "analytics" / "evidence_auto_calculator.py"
        )
        calc_exists = calc_path.exists()
        if calc_exists:
            score += 5.0
            items_done.append("evidence_auto_calculator.py: present ✓")
        else:
            items_pending.append(
                "evidence_auto_calculator.py: missing — create MP-1409"
            )

        # Infrastructure: history file initialized
        history_path = self.data_dir / "paper_evidence_history.json"
        hist_data = self._read_json(history_path)
        history_initialized = bool(hist_data.get("schema_version"))
        if history_initialized:
            score += 5.0
            items_done.append("paper_evidence_history.json: initialized ✓")
        else:
            items_pending.append(
                "paper_evidence_history.json: not initialized "
                "(run: python3 -m spa_core.analytics.evidence_auto_calculator --run)"
            )

        # Completed cycles — read from paper_evidence.json (cycle_runner writes this)
        pe = self._read_json(self.data_dir / "paper_evidence.json")
        completed_days = (
            len(pe.get("days", [])) if isinstance(pe, dict) else 0
        )
        # Also take max from history
        history_days = hist_data.get("day_count", len(hist_data.get("days", [])))
        completed_days = max(completed_days, history_days)

        TIERS = [(5, "+5 pts at ≥5 cycles"), (10, "+5 pts at ≥10 cycles"), (20, "+5 pts at ≥20 cycles")]
        for threshold, label in TIERS:
            if completed_days >= threshold:
                score += 5.0
                items_done.append(f"Cycles ≥{threshold}: {completed_days} ✓")
            else:
                items_pending.append(
                    f"{label} — currently {completed_days}/{threshold}"
                )

        return CategoryScore(
            "evidence", score, max_score, items_done, items_pending,
            notes=f"{score:.0f}/{max_score:.0f} pts, {completed_days} completed days",
        )

    def assess_infrastructure_v2(self) -> CategoryScore:
        """Infrastructure health. Max 20 pts (10 checks × 2 pts).
        MP-1425 (v10.41)
        """
        gs = self._read_json(self.data_dir / "golive_status.json")
        checks = gs.get("checks", {})

        items_done: List[str] = []
        items_pending: List[str] = []

        INFRA_CHECKS = [
            ("autopush_installed",    "autopush launchd daemon",          2.0),
            ("http_server",           "HTTP dashboard (port 8765)",        2.0),
            ("cycle_runner_exists",   "cycle_runner.py present",           2.0),
            ("multi_strategy_runner", "multi_strategy_runner.py",          2.0),
            ("safe_tx_builder",       "Gnosis Safe TX builder",            2.0),
            ("promotion_engine",      "promotion_engine.py",               2.0),
            ("gap_monitor_ok",        "gap_monitor: no gaps",              2.0),
            ("adr022_exists",         "ADR-022 present",                   2.0),
            ("data_fresh_48h",        "data freshness < 48h",              2.0),
            ("telegram_alert_today",  "Telegram daily alert sent today",   2.0),
        ]

        score = 0.0
        max_score = sum(pts for _, _, pts in INFRA_CHECKS)  # 20.0

        for key, label, pts in INFRA_CHECKS:
            if checks.get(key):
                score += pts
                items_done.append(f"{label}: ✓")
            else:
                items_pending.append(f"{label}: missing/failed")

        return CategoryScore(
            "infrastructure", score, max_score, items_done, items_pending,
            notes=f"{score:.0f}/{max_score:.0f} pts",
        )

    def assess_financial(self) -> CategoryScore:
        """Financial readiness. Max 15 pts.
        MP-1425 (v10.41)
          +3  capital_config.json exists and has starting_capital
          +2  starting_capital >= $100K (from paper_trading_status)
          +2  risk_policy defined (spa_core/risk/policy.py)
          +2  fee_structure.py documented
          +2  KYC docs present (docs/legal/ONBOARDING_CHECKLIST.md)
          +2  equity_curve >= 7 days (performance reporting ready)
          +2  is_demo = False
        """
        items_done: List[str] = []
        items_pending: List[str] = []
        score = 0.0
        max_score = 15.0

        # capital_config.json: +3
        cap_cfg_path = self.data_dir / "capital_config.json"
        cap_cfg = self._read_json(cap_cfg_path)
        cfg_capital = (
            cap_cfg.get("capital", {}).get("starting_capital_usd", 0)
            if isinstance(cap_cfg.get("capital"), dict)
            else 0
        )
        if cfg_capital >= 100_000:
            score += 3.0
            items_done.append(
                f"capital_config.json: starting_capital=${cfg_capital:,.0f} ✓"
            )
        else:
            items_pending.append(
                "capital_config.json: missing or starting_capital < $100K "
                "— create data/capital_config.json"
            )

        # Starting capital ≥ $100K (live status): +2
        pts_data = self._read_json(self.data_dir / "paper_trading_status.json")
        pos_data = self._read_json(self.data_dir / "current_positions.json")
        capital = float(
            pts_data.get("virtual_capital",
                pts_data.get("total_capital",
                    pts_data.get("capital",
                        pts_data.get("current_equity", 0))))
        )
        if capital == 0:
            capital = float(pos_data.get("capital_usd", 0))
        if capital >= 100_000:
            score += 2.0
            items_done.append(f"Starting capital: ${capital:,.0f} USDC ✓")
        else:
            items_pending.append(
                f"Starting capital: ${capital:,.0f} (need $100,000)"
            )

        # Risk policy defined: +2
        risk_policy_path = self.base_dir / "spa_core" / "risk" / "policy.py"
        if risk_policy_path.exists() and risk_policy_path.stat().st_size > 100:
            score += 2.0
            items_done.append("Risk policy (spa_core/risk/policy.py): defined ✓")
        else:
            items_pending.append("Risk policy: missing — create spa_core/risk/policy.py")

        # fee_structure.py: +2
        fee_path = self.base_dir / "spa_core" / "analytics" / "fee_structure.py"
        if fee_path.exists() and fee_path.stat().st_size > 200:
            score += 2.0
            items_done.append("fee_structure.py: present ✓")
        else:
            items_pending.append(
                "fee_structure.py: missing — create spa_core/analytics/fee_structure.py"
            )

        # KYC docs: +2
        kyc_path = self.base_dir / "docs" / "legal" / "ONBOARDING_CHECKLIST.md"
        if kyc_path.exists() and kyc_path.stat().st_size >= 200:
            score += 2.0
            items_done.append("Family Fund KYC (ONBOARDING_CHECKLIST.md): present ✓")
        else:
            items_pending.append(
                "Family Fund KYC: missing — create docs/legal/ONBOARDING_CHECKLIST.md"
            )

        # Equity curve ≥7 days: +2
        eq_data = self._read_json(self.data_dir / "equity_curve_daily.json")
        if isinstance(eq_data, list):
            eq_days = len(eq_data)
        elif isinstance(eq_data, dict):
            eq_days = len(
                eq_data.get("daily") or eq_data.get("entries") or eq_data.get("data") or []
            )
            eq_days = max(eq_days, eq_data.get("summary", {}).get("num_days", 0))
        else:
            eq_days = 0
        if eq_days >= 7:
            score += 2.0
            items_done.append(f"Performance reporting: {eq_days} equity curve days ✓")
        else:
            items_pending.append(
                f"Performance reporting: {eq_days}/7 equity curve days "
                f"({max(0, 7 - eq_days)} more needed for +2 pts)"
            )

        # is_demo = False: +2
        is_demo = pts_data.get("is_demo", pos_data.get("is_demo", True))
        if not is_demo:
            score += 2.0
            items_done.append("Paper trading mode: is_demo=False ✓")
        else:
            items_pending.append(
                "Paper trading: is_demo=True — ensure cycle_runner runs with is_demo=False"
            )

        return CategoryScore(
            "financial", score, max_score, items_done, items_pending,
            notes=f"{score:.0f}/{max_score:.0f} pts",
        )

    def assess_data_sources(self) -> CategoryScore:
        """Data source quality. Max 10 pts.
        MP-1426 (v10.42)
          +2  spa_core/utils/defillama.py exists
          +2  spa_core/analytics/t1_data_verifier.py exists
          +2  source_pipeline.json has ≥5 CLEAN sources
          +2  promotion_engine.py present
          +2  CLEAN source % ≥ 50%
        """
        items_done: List[str] = []
        items_pending: List[str] = []
        score = 0.0
        max_score = 10.0

        # DeFiLlama utils client: +2
        defillama_utils = self.base_dir / "spa_core" / "utils" / "defillama.py"
        defillama_adapter = (
            self.base_dir / "spa_core" / "adapters" / "defillama_feed.py"
        )
        if defillama_utils.exists() or defillama_adapter.exists():
            score += 2.0
            items_done.append("DeFiLlama client (utils/defillama.py or adapters/defillama_feed.py): ✓")
        else:
            items_pending.append("DeFiLlama client: missing")

        # T1 data verifier: +2
        t1_verifier = self.base_dir / "spa_core" / "analytics" / "t1_data_verifier.py"
        if t1_verifier.exists():
            score += 2.0
            items_done.append("T1 data verifier (t1_data_verifier.py): ✓")
        else:
            items_pending.append("T1 data verifier: missing")

        # Source pipeline CLEAN count: +2 if ≥5 CLEAN sources
        sp = self._read_json(self.backtest_dir / "source_pipeline.json")
        sources: dict = sp.get("sources", {})
        clean_sources = [k for k, v in sources.items() if v == "clean_included"]
        if len(clean_sources) >= 5:
            score += 2.0
            items_done.append(
                f"Source pipeline: {len(clean_sources)}/{len(sources)} CLEAN sources ✓"
            )
        else:
            items_pending.append(
                f"Source pipeline: {len(clean_sources)}/{len(sources)} CLEAN "
                f"(need ≥5 for +2 pts)"
            )

        # Promotion engine: +2
        promo_root = self.base_dir / "promotion_engine.py"
        promo_spa = self.base_dir / "spa_core" / "analytics" / "strategy_promoter.py"
        if promo_root.exists() or promo_spa.exists():
            score += 2.0
            items_done.append("Promotion engine: present ✓")
        else:
            items_pending.append("Promotion engine: missing")

        # CLEAN % ≥ 50%: +2
        total = len(sources)
        clean_pct = len(clean_sources) / total * 100.0 if total > 0 else 0.0
        if clean_pct >= 50.0:
            score += 2.0
            items_done.append(f"CLEAN source %: {clean_pct:.0f}% ≥50% ✓")
        else:
            items_pending.append(
                f"CLEAN source %: {clean_pct:.0f}% < 50% "
                f"(promote more sources to clean_included)"
            )

        return CategoryScore(
            "data_sources", score, max_score, items_done, items_pending,
            notes=f"{score:.0f}/{max_score:.0f} pts, {len(clean_sources)}/{total} CLEAN",
        )

    def assess_documentation_v2(self) -> CategoryScore:
        """Documentation: key policy and runbook docs. Max 10 pts.
        MP-1425 (v10.41) — normalized from assess_documentation()
        """
        old = self.assess_documentation()
        # Normalize old (max=100) to new max=10
        new_score = round(old.score / old.max_score * 10.0, 2) if old.max_score > 0 else 0.0
        return CategoryScore(
            "documentation", new_score, 10.0,
            old.items_done, old.items_pending,
            notes=f"{new_score:.1f}/10.0 pts",
        )

    # ── aggregation ────────────────────────────────────────────────────────────

    def _get_categories(self) -> List[CategoryScore]:
        """Run all assessments (cached).
        v10.41+ uses 6-category system (max_total=100):
          gates(20) + evidence(25) + infrastructure(20) + financial(15)
          + data_sources(10) + documentation(10)
        """
        if self._categories_cache is None:
            self._categories_cache = [
                self.assess_gates(),
                self.assess_evidence(),
                self.assess_infrastructure_v2(),
                self.assess_financial(),
                self.assess_data_sources(),
                self.assess_documentation_v2(),
            ]
        return self._categories_cache

    def total_score(self) -> float:
        """Overall score 0.0–100.0 (weighted by max_score)."""
        cats = self._get_categories()
        total = sum(c.score for c in cats)
        max_total = sum(c.max_score for c in cats)
        if max_total <= 0.0:
            return 0.0
        return round(total / max_total * 100.0, 1)

    def overall_status(self) -> str:
        """READY / NOT_READY / BLOCKED"""
        cats = self._get_categories()

        # BLOCKED: hard structural blocker (expanded universe STRICT_BLOCKED)
        pg = self._read_json(self.backtest_dir / "paper_ready_gate.json")
        if pg.get("expanded_universe_verification_status") == "STRICT_BLOCKED":
            return "BLOCKED"

        # BLOCKED: no backtest gate pass (gate_status score < 25)
        gate_cat = next((c for c in cats if c.name == "gate_status"), None)
        if gate_cat is not None and gate_cat.score < 25.0:
            return "BLOCKED"

        score = self.total_score()
        if score >= 80.0:
            return "READY"
        return "NOT_READY"

    def blocking_items(self) -> List[str]:
        """Items that must be resolved before going live."""
        cats = self._get_categories()
        items: List[str] = []
        for cat in cats:
            items.extend(cat.items_pending)

        # Also include raw golive blockers not already covered
        gs = self._read_json(self.data_dir / "golive_status.json")
        for b in gs.get("blockers", []):
            if b not in items:
                items.append(b)

        return items

    def estimated_days_to_ready(self) -> int:
        """Estimate based on pending items (lower bound)."""
        gs = self._read_json(self.data_dir / "golive_status.json")

        # Days for paper track
        track_needed = 0
        for b in gs.get("blockers", []):
            m = re.search(r"(\d+) more needed", b)
            if m:
                track_needed = max(track_needed, int(m.group(1)))
        if track_needed == 0:
            # Infer: check consecutive ready days
            consecutive = gs.get("consecutive_ready_days", 0) or 0
            track_needed = max(0, 30 - consecutive)

        # Days for infrastructure fixes
        pg = self._read_json(self.backtest_dir / "paper_ready_gate.json")
        infra_days = 0
        if pg.get("hardening_status") not in ("PASS", "READY", ""):
            infra_days = max(infra_days, 7)
        if pg.get("expanded_universe_verification_status") == "STRICT_BLOCKED":
            infra_days = max(infra_days, 14)  # need pool IDs + data

        # Owner acceptance: 1 day (can be done in parallel)
        owner_acc = self._read_json(
            self.data_dir / "backtest" / "owner_paper_acceptance.json"
        )
        owner_days = 1 if owner_acc.get("accepted") is not True else 0

        total = max(track_needed, infra_days) + owner_days
        return max(total, 1)

    # ── output ─────────────────────────────────────────────────────────────────

    def to_markdown(self) -> str:
        """Full markdown report answering: 'When can we go live?'"""
        cats = self._get_categories()
        status = self.overall_status()
        score = self.total_score()
        est_days = self.estimated_days_to_ready()
        today = date.today().isoformat()

        lines = [
            "# Go-Live Readiness Report",
            "",
            f"**Generated:** {today}  ",
            f"**Overall Status:** `{status}`  ",
            f"**Total Score:** {score:.1f} / 100  ",
            f"**Estimated Days to Ready:** {est_days}  ",
            "",
            "---",
            "",
            "## Category Scores",
            "",
            "| Category | Score | Max | % | Status |",
            "|----------|------:|----:|--:|--------|",
        ]

        for c in cats:
            emoji = "✅" if c.pct >= 80 else ("⚠️" if c.pct >= 40 else "❌")
            lines.append(
                f"| {c.name} | {c.score:.0f} | {c.max_score:.0f}"
                f" | {c.pct:.0f}% | {emoji} |"
            )

        lines += ["", "---", "", "## Category Details", ""]

        for c in cats:
            lines += [f"### {c.name}", ""]
            if c.notes:
                lines += [f"_{c.notes}_", ""]
            if c.items_done:
                lines.append("**Done:**")
                for item in c.items_done:
                    lines.append(f"- {item}")
                lines.append("")
            if c.items_pending:
                lines.append("**Pending:**")
                for item in c.items_pending:
                    lines.append(f"- {item}")
                lines.append("")

        lines += [
            "---",
            "",
            "## Blocking Items",
            "",
        ]

        blocking = self.blocking_items()
        if blocking:
            for b in blocking:
                lines.append(f"- {b}")
        else:
            lines.append("_No blocking items — READY for go-live._")

        lines += [
            "",
            "---",
            "",
            "## Answer: When Can We Go Live?",
            "",
            f"**Status: {status}**",
            "",
            (
                f"Estimated minimum time to ready: **{est_days} days** "
                f"(from {today})"
            ),
            "",
            "### Key Steps Remaining",
            "",
            "1. **Pre-Paper Gate** — resolve hardening audit + expanded universe (P1B sources)",
            "2. **Paper Track** — accumulate 30 gap-free days of CLEAN evidence",
            "3. **Owner Acceptance** — sign the acceptance document",
            "4. **Source Quality** — promote all T1 adapters to CLEAN in source_pipeline.json",
            "5. **Live Capital** — deposit $100K USDC in Gnosis Safe before live trading",
            "",
            "---",
            "",
            f"_Generated by spa_core.analytics.golive_readiness_report v{SCHEMA_VERSION}_",
            "",
        ]

        return "\n".join(lines)

    def save(self) -> str:
        """Saves JSON + MD to data/reports/. Returns JSON file path."""
        reports_dir = self.data_dir / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)

        today = date.today().isoformat()
        cats = self._get_categories()

        report = {
            "schema_version": SCHEMA_VERSION,
            "generated_at": datetime.now().isoformat(),
            "date": today,
            "overall_status": self.overall_status(),
            "total_score": self.total_score(),
            "estimated_days_to_ready": self.estimated_days_to_ready(),
            "categories": [c.to_dict() for c in cats],
            "blocking_items": self.blocking_items(),
        }

        json_path = reports_dir / f"golive_readiness_{today}.json"
        self._atomic_write_json(json_path, report)

        md_path = reports_dir / f"golive_readiness_{today}.md"
        self._atomic_write_text(md_path, self.to_markdown())

        return str(json_path)

    # ── atomic write helpers ───────────────────────────────────────────────────

    @staticmethod
    def _atomic_write_json(path: Path, data: dict) -> None:
        from spa_core.utils.atomic import atomic_save
        atomic_save(data, str(path))

    @staticmethod
    def _atomic_write_text(path: Path, text: str) -> None:
        fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(text)
            os.replace(tmp, path)
        except Exception:
            try:
                os.unlink(tmp)
            except Exception:
                pass
            raise


# ── CLI ────────────────────────────────────────────────────────────────────────

def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Go-Live Readiness Report — spa_core MP-1353"
    )
    parser.add_argument(
        "--check", action="store_true",
        help="Print report to stdout without saving (default)",
    )
    parser.add_argument(
        "--run", action="store_true",
        help="Compute report and save to data/reports/",
    )
    parser.add_argument(
        "--base-dir", default=".",
        help="Repo base directory (default: .)",
    )
    args = parser.parse_args()

    report = GoLiveReadinessReport(base_dir=args.base_dir)

    print(report.to_markdown())
    print(f"\nOverall status : {report.overall_status()}")
    print(f"Total score    : {report.total_score():.1f}/100")
    print(f"Days to ready  : {report.estimated_days_to_ready()}")

    if args.run:
        path = report.save()
        print(f"\nSaved → {path}")


if __name__ == "__main__":
    main()
