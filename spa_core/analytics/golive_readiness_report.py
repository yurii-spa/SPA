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

class GoLiveReadinessReport:
    """
    Full go-live readiness assessment across 6 categories.

    Usage::

        report = GoLiveReadinessReport(base_dir=".")
        print(report.overall_status())   # READY / NOT_READY / BLOCKED
        print(report.total_score())      # 0.0–100.0
        print(report.blocking_items())   # list[str]
        path = report.save()             # writes JSON + MD to data/reports/
    """

    def __init__(self, base_dir: str = ".") -> None:
        self.base_dir = Path(base_dir)
        self.data_dir = self.base_dir / "data"
        self.backtest_dir = self.data_dir / "backtest"
        self._categories_cache: Optional[List[CategoryScore]] = None

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
        """Capital: virtual $100K USDC ready, equity curve populated."""
        pts_data = self._read_json(self.data_dir / "paper_trading_status.json")
        eq_data = self._read_json(self.data_dir / "equity_curve_daily.json")

        items_done: List[str] = []
        items_pending: List[str] = []
        score = 0.0
        max_score = 100.0

        # Virtual capital check
        capital = float(
            pts_data.get("virtual_capital",
                pts_data.get("total_capital",
                    pts_data.get("capital", 0)))
        )
        is_demo = pts_data.get("is_demo", True)

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

        # Equity curve check
        if isinstance(eq_data, list):
            curve = eq_data
        elif isinstance(eq_data, dict):
            curve = eq_data.get("entries", eq_data.get("data", []))
        else:
            curve = []

        if len(curve) >= 30:
            score += 30.0
            items_done.append(f"Equity curve: {len(curve)} days recorded ✓")
        elif len(curve) >= 1:
            score += 15.0
            items_done.append(f"Equity curve: {len(curve)} day(s) recorded")
            items_pending.append(f"Need 30+ equity curve entries ({30 - len(curve)} more)")
        else:
            items_pending.append("Equity curve: no entries yet")

        # Live capital note (for go-live, not paper)
        items_pending.append(
            "For LIVE: $100K actual USDC must be deposited in Gnosis Safe"
        )
        score += 20.0  # paper virtual capital is pre-allocated

        score = min(score, max_score)

        return CategoryScore(
            "capital", score, max_score, items_done, items_pending,
            notes=f"${capital:,.0f} virtual, is_demo={is_demo}",
        )

    # ── aggregation ────────────────────────────────────────────────────────────

    def _get_categories(self) -> List[CategoryScore]:
        """Run all assessments (cached)."""
        if self._categories_cache is None:
            self._categories_cache = [
                self.assess_gate_status(),
                self.assess_data_quality(),
                self.assess_evidence_points(),
                self.assess_owner_acceptance(),
                self.assess_infrastructure(),
                self.assess_capital(),
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
        fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
            os.replace(tmp, path)
        except Exception:
            try:
                os.unlink(tmp)
            except Exception:
                pass
            raise

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
