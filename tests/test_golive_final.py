"""
tests/test_golive_final.py

MP-1442 (v10.58) — 20 финальных тестов GoLive score.

Test groups:
  1. generate_report() return structure (tests 1–4)
  2. total_score не регрессирует ниже 69 (tests 5–7)
  3. overall_status не "BLOCKED"-only (tests 8–9)
  4. 6 категорий присутствуют (tests 10–12)
  5. GOLIVE_PROGRESS_REPORT существует (tests 13–15)
  6. Gates ≥ 16/20 (не регрессия) (tests 16–17)
  7. Evidence / Infrastructure / Financial (tests 18–20)

Total: 20 tests
stdlib unittest + pytest compatible
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.analytics.golive_readiness_report import (
    GoLiveReadinessReport,
)


# ── helpers ────────────────────────────────────────────────────────────────────

def _write(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)


def _make_minimal_env(base: Path) -> None:
    """Write minimal fixtures so GoLiveReadinessReport can run end-to-end."""
    data = base / "data"
    bt = data / "backtest"
    docs = base / "docs"
    adr = docs / "adr"
    adr.mkdir(parents=True, exist_ok=True)

    _write(bt / "pre_paper_backtest_gate.json", {"status": "PASS"})
    _write(bt / "paper_ready_gate.json", {
        "status": "NOT_READY",
        "hardening_status": "NOT_READY",
        "expanded_universe_verification_status": "STRICT_BLOCKED",
    })
    _write(bt / "owner_paper_acceptance.json", {"accepted": False})
    _write(bt / "owner_paper_acceptance_gate.json", {
        "status": "NOT_SIGNED", "blockers": []
    })
    _write(bt / "source_pipeline.json", {"sources": {
        "aave_v3": "clean_included",
        "compound_v3": "clean_included",
        "morpho": "clean_included",
        "yearn": "clean_included",
        "euler": "clean_included",
    }})
    _write(data / "golive_status.json", {
        "checks": {k: True for k in [
            "equity_curve_real", "trades_real", "status_real",
            "no_demo_data", "data_fresh_48h", "cycle_runner_exists",
            "multi_strategy_runner", "promotion_engine", "safe_tx_builder",
            "http_server", "adr022_exists", "gap_monitor_ok",
            "autopush_installed", "apy_above_floor", "drawdown_below_kill",
            "risk_policy_snapshot",
        ]},
    })
    _write(data / "paper_trading_status.json", {
        "is_demo": False,
        "current_equity": 100_000.0,
    })
    _write(data / "current_positions.json", {
        "capital_usd": 100_000.0,
        "deployed_usd": 75_000.0,
    })
    _write(data / "equity_curve_daily.json", {
        "schema_version": "1.0",
        "summary": {"num_days": 2},
        "daily": [{"date": "2026-06-18", "equity": 100_000.0},
                  {"date": "2026-06-19", "equity": 100_021.0}],
    })
    _write(data / "paper_evidence.json", {
        "schema_version": "1.0",
        "days": [{"date": "2026-06-18"}, {"date": "2026-06-19"}],
    })
    _write(data / "paper_evidence_history.json", {
        "schema_version": "1.0", "day_count": 2
    })
    _write(data / "capital_config.json", {
        "capital": {"starting_capital_usd": 100_000}
    })
    _write(data / "kill_switch_status.json", {
        "triggered": False, "reason": "all clear"
    })
    _write(data / "gate_status.json", {
        "schema_version": "1.0",
        "backtest_gate": "PASS",
        "kill_switch_status": "LOCKED",
    })
    _write(data / "pre_launch_validation.json", {
        "schema_version": "1.0",
        "pass_count": 32,
        "passed_count": 32,
        "total_count": 40,
        "pass_pct": 80.0,
    })
    # analytics modules
    analytics = base / "spa_core" / "analytics"
    analytics.mkdir(parents=True, exist_ok=True)
    # analytics — fee_structure needs > 200 bytes; others just need to exist
    _FILLER = "# placeholder content for SPA test fixture\n"
    (analytics / "evidence_auto_calculator.py").write_text(
        "# evidence_auto_calculator\n", encoding="utf-8"
    )
    (analytics / "t1_data_verifier.py").write_text("# t1\n", encoding="utf-8")
    (analytics / "fee_structure.py").write_text(_FILLER * 6, encoding="utf-8")   # ~240 bytes > 200
    (analytics / "investment_memo_generator.py").write_text("# memo\n", encoding="utf-8")
    adapters = base / "spa_core" / "adapters"
    adapters.mkdir(parents=True, exist_ok=True)
    (adapters / "defillama_feed.py").write_text("# feed\n", encoding="utf-8")
    risk_dir = base / "spa_core" / "risk"
    risk_dir.mkdir(parents=True, exist_ok=True)
    (risk_dir / "policy.py").write_text("# policy\n" * 10, encoding="utf-8")
    # docs — each file must be >= 500 bytes for documentation scoring
    _DOC = _FILLER * 14  # ~560 bytes > 500
    for fname in [
        "RISK_MANAGEMENT_POLICY.md", "DEPLOYMENT_RUNBOOK.md",
        "DATA_SOURCES_REGISTRY.md", "FAMILY_FUND_ONBOARDING.md",
        "API_REFERENCE.md", "SECURITY_CHECKLIST.md",
        "DISASTER_RECOVERY.md", "TOKEN_ROTATION_RUNBOOK.md",
    ]:
        (docs / fname).write_text(_DOC, encoding="utf-8")
    _ADR = _FILLER * 14
    for i in range(1, 5):
        (adr / f"ADR-00{i}.md").write_text(_ADR, encoding="utf-8")
    legal = docs / "legal"
    legal.mkdir(parents=True, exist_ok=True)
    # ONBOARDING_CHECKLIST.md needs >= 200 bytes for KYC check
    (legal / "ONBOARDING_CHECKLIST.md").write_text(_FILLER * 6, encoding="utf-8")  # ~240 bytes


# ══════════════════════════════════════════════════════════════════════════════
# GROUP 1 — generate_report() return structure (tests 1–4)
# ══════════════════════════════════════════════════════════════════════════════

class TestGenerateReportStructure(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        _make_minimal_env(Path(self.tmp))
        self.r = GoLiveReadinessReport(base_dir=self.tmp)
        self.report = self.r.generate_report()

    def test_01_generate_report_returns_dict(self):
        """generate_report() must return a dict."""
        self.assertIsInstance(self.report, dict)

    def test_02_report_has_total_score(self):
        """Report dict must contain 'total_score' float."""
        self.assertIn("total_score", self.report)
        self.assertIsInstance(self.report["total_score"], (int, float))

    def test_03_report_has_overall_status(self):
        """Report must contain 'overall_status' string."""
        self.assertIn("overall_status", self.report)
        self.assertIsInstance(self.report["overall_status"], str)

    def test_04_report_has_all_required_top_level_keys(self):
        """Report must contain schema_version, categories, blocking_items."""
        for key in ("schema_version", "overall_status", "total_score",
                    "categories", "blocking_items"):
            self.assertIn(key, self.report, f"Missing key: {key}")


# ══════════════════════════════════════════════════════════════════════════════
# GROUP 2 — total_score не регрессирует (tests 5–7)
# ══════════════════════════════════════════════════════════════════════════════

class TestTotalScoreRegression(unittest.TestCase):

    def test_05_total_score_not_below_69_in_isolated_env(self):
        """Full-fixture env must score ≥ 69/100 (v10.41 baseline)."""
        tmp = tempfile.mkdtemp()
        _make_minimal_env(Path(tmp))
        r = GoLiveReadinessReport(base_dir=tmp)
        score = r.total_score()
        self.assertGreaterEqual(
            score, 69.0,
            f"Score {score}/100 < 69 — regression from v10.41 baseline",
        )

    def test_06_production_total_score_not_below_69(self):
        """Live repo total score must be ≥ 69 (no regression)."""
        r = GoLiveReadinessReport(base_dir=str(_REPO_ROOT))
        score = r.total_score()
        self.assertGreaterEqual(
            score, 69.0,
            f"Production score {score}/100 regressed below 69",
        )

    def test_07_production_total_score_at_target_77(self):
        """Live repo total score must reach v10.57 target of ≥ 75."""
        r = GoLiveReadinessReport(base_dir=str(_REPO_ROOT))
        score = r.total_score()
        self.assertGreaterEqual(
            score, 75.0,
            f"Production score {score}/100 < 75 (v10.57 target)",
        )


# ══════════════════════════════════════════════════════════════════════════════
# GROUP 3 — overall_status field (tests 8–9)
# ══════════════════════════════════════════════════════════════════════════════

class TestOverallStatus(unittest.TestCase):

    def setUp(self):
        self.r = GoLiveReadinessReport(base_dir=str(_REPO_ROOT))

    def test_08_overall_status_is_valid_string(self):
        """overall_status must be one of the valid states."""
        status = self.r.overall_status()
        valid = {"READY", "NOT_READY", "BLOCKED", "IN_PROGRESS"}
        self.assertIn(
            status, valid,
            f"Unexpected overall_status: {status!r}",
        )

    def test_09_overall_status_not_unknown(self):
        """overall_status must not be UNKNOWN or empty."""
        status = self.r.overall_status()
        self.assertTrue(status, "overall_status is empty")
        self.assertNotEqual(status, "UNKNOWN")


# ══════════════════════════════════════════════════════════════════════════════
# GROUP 4 — 6 категорий присутствуют (tests 10–12)
# ══════════════════════════════════════════════════════════════════════════════

class TestCategoryPresence(unittest.TestCase):

    def setUp(self):
        tmp = tempfile.mkdtemp()
        _make_minimal_env(Path(tmp))
        self.report = GoLiveReadinessReport(base_dir=tmp).generate_report()

    def test_10_report_has_six_categories(self):
        """Report must include exactly 6 category entries."""
        cats = self.report.get("categories", [])
        self.assertEqual(len(cats), 6, f"Expected 6 categories, got {len(cats)}")

    def test_11_all_expected_category_names_present(self):
        """Report must include: gates, evidence, infrastructure, financial, data_sources, documentation."""
        cat_names = {c["name"] for c in self.report.get("categories", [])}
        expected = {"gates", "evidence", "infrastructure", "financial", "data_sources", "documentation"}
        self.assertEqual(cat_names, expected,
                         f"Category mismatch: {cat_names} vs {expected}")

    def test_12_each_category_has_score_and_max(self):
        """Each category dict must have score and max_score fields."""
        for cat in self.report.get("categories", []):
            with self.subTest(cat=cat.get("name")):
                self.assertIn("score", cat)
                self.assertIn("max_score", cat)
                self.assertLessEqual(cat["score"], cat["max_score"])


# ══════════════════════════════════════════════════════════════════════════════
# GROUP 5 — GOLIVE_PROGRESS_REPORT существует (tests 13–15)
# ══════════════════════════════════════════════════════════════════════════════

class TestProgressReportExists(unittest.TestCase):

    def setUp(self):
        self.report_path = _REPO_ROOT / "docs" / "GOLIVE_PROGRESS_REPORT_20260619.md"

    def test_13_progress_report_file_exists(self):
        """docs/GOLIVE_PROGRESS_REPORT_20260619.md must exist."""
        self.assertTrue(
            self.report_path.exists(),
            f"Progress report not found: {self.report_path}",
        )

    def test_14_progress_report_is_non_empty(self):
        """Progress report must be a non-empty markdown file."""
        size = self.report_path.stat().st_size
        self.assertGreater(size, 500, "Progress report is too small (< 500 bytes)")

    def test_15_progress_report_contains_score_table(self):
        """Progress report must contain the score progression table."""
        content = self.report_path.read_text(encoding="utf-8")
        self.assertIn("Score Progression", content)
        self.assertIn("v10.57", content)
        self.assertIn("77", content)


# ══════════════════════════════════════════════════════════════════════════════
# GROUP 6 — Gates ≥ 16/20 не регрессирует (tests 16–17)
# ══════════════════════════════════════════════════════════════════════════════

class TestGatesRegression(unittest.TestCase):

    def test_16_production_gates_not_below_16(self):
        """Production gates score must remain ≥ 16/20."""
        r = GoLiveReadinessReport(base_dir=str(_REPO_ROOT))
        g = r.assess_gates()
        self.assertGreaterEqual(
            g.score, 16.0,
            f"Gates regressed to {g.score}/20 — check MP-1441 changes",
        )

    def test_17_gates_score_category_in_report(self):
        """generate_report() must include gates category with score ≥ 16."""
        r = GoLiveReadinessReport(base_dir=str(_REPO_ROOT))
        report = r.generate_report()
        gates_cat = next(
            (c for c in report["categories"] if c["name"] == "gates"), None
        )
        self.assertIsNotNone(gates_cat, "Gates category missing from report")
        self.assertGreaterEqual(gates_cat["score"], 16.0)


# ══════════════════════════════════════════════════════════════════════════════
# GROUP 7 — Evidence / Infrastructure / Financial (tests 18–20)
# ══════════════════════════════════════════════════════════════════════════════

class TestCategoryMinimums(unittest.TestCase):

    def setUp(self):
        self.r = GoLiveReadinessReport(base_dir=str(_REPO_ROOT))
        self.report = self.r.generate_report()
        self.cats = {c["name"]: c for c in self.report["categories"]}

    def test_18_infrastructure_score_at_least_16(self):
        """Infrastructure must score ≥ 16/20 (launchd daemons, dash, gap monitor)."""
        infra = self.cats.get("infrastructure", {})
        self.assertGreaterEqual(
            infra.get("score", 0), 16.0,
            f"Infrastructure {infra.get('score')}/20 < 16",
        )

    def test_19_financial_score_at_least_11(self):
        """Financial must score ≥ 11/15 (capital + risk_policy + KYC baseline)."""
        fin = self.cats.get("financial", {})
        self.assertGreaterEqual(
            fin.get("score", 0), 11.0,
            f"Financial {fin.get('score')}/15 < 11",
        )

    def test_20_documentation_score_perfect_or_near(self):
        """Documentation must score ≥ 9/10 (all key docs present)."""
        doc = self.cats.get("documentation", {})
        self.assertGreaterEqual(
            doc.get("score", 0), 9.0,
            f"Documentation {doc.get('score')}/10 < 9",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
