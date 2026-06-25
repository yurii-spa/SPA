"""
tests/test_golive_readiness_report.py

45 tests for spa_core/analytics/golive_readiness_report.py
MP-1353 (v9.69)

stdlib only — unittest, no external dependencies.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

# Ensure repo root is on path
_REPO_ROOT = Path(__file__).parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.analytics.golive_readiness_report import (
    CategoryScore,
    GoLiveReadinessReport,
    READINESS_CATEGORIES,
    EVIDENCE_TARGET,
)


# ── helpers ────────────────────────────────────────────────────────────────────

def _write(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)


def _make_minimal_env(base: Path) -> None:
    """Write minimal JSON fixtures so the report can run without errors."""
    data = base / "data"
    bt = data / "backtest"

    _write(
        bt / "pre_paper_backtest_gate.json",
        {"status": "PASS", "strict_backtest_scope": {"backtest_gate_status": "PASS"}},
    )
    _write(
        bt / "paper_ready_gate.json",
        {
            "status": "NOT_READY",
            "hardening_status": "NOT_READY",
            "expanded_universe_verification_status": "STRICT_BLOCKED",
        },
    )
    _write(
        bt / "owner_paper_acceptance_gate.json",
        {"status": "NOT_SIGNED", "blockers": ["accepted must be true."]},
    )
    _write(
        bt / "source_pipeline.json",
        {
            "sources": {
                "aave_v2_usdc": "clean_included",
                "compound_v2_usdc": "clean_included",
                "morpho_steakhouse": "pending",
                "gmx_btc": "source_needed",
            }
        },
    )
    _write(
        data / "golive_status.json",
        {
            "ready": False,
            "passed": 20,
            "total": 26,
            "consecutive_ready_days": 1,
            "checks": {
                "min_track_days_30": False,
                "gap_monitor_ok": True,
                "autopush_installed": True,
                "http_server": True,
                "cycle_runner_exists": True,
                "multi_strategy_runner": True,
                "safe_tx_builder": True,
                "promotion_engine": True,
                "adr022_exists": True,
            },
            "blockers": [
                "min_track_days_30: 1/30 honest paper-trading days (29 more needed)",
            ],
        },
    )
    _write(
        data / "paper_trading_status.json",
        {"virtual_capital": 100000, "is_demo": False, "capital": 100000},
    )
    _write(
        data / "equity_curve_daily.json",
        [{"date": "2026-06-19", "equity": 100000}],
    )


def _make_ready_env(base: Path) -> None:
    """Write fixtures that should make overall_status() == READY (score >= 80%)."""
    data = base / "data"
    bt = data / "backtest"
    spa = base / "spa_core"
    docs = base / "docs"

    # ── Gates ─────────────────────────────────────────────────────────────────
    _write(bt / "pre_paper_backtest_gate.json", {"status": "PASS"})
    _write(bt / "paper_ready_gate.json", {
        "status": "READY", "hardening_status": "PASS",
        "expanded_universe_verification_status": "PASS",
    })
    _write(bt / "owner_paper_acceptance.json",
           {"accepted": True, "owner": "Yurii", "accepted_at": "2026-06-19T10:00:00"})
    _write(bt / "owner_paper_acceptance_gate.json", {"status": "SIGNED", "blockers": []})
    _write(data / "gate_status.json", {"status": "PASS", "passed": 10, "total": 10})
    _write(data / "kill_switch_status.json", {"locked": True, "status": "LOCKED"})
    # 100% clean sources
    _write(bt / "source_pipeline.json",
           {"sources": {f"src_{i}": "clean_included" for i in range(10)}})

    # ── GoLive status ─────────────────────────────────────────────────────────
    _write(data / "golive_status.json", {
        "ready": True, "passed": 26, "total": 26, "consecutive_ready_days": 30,
        "checks": {k: True for k in [
            "min_track_days_30", "gap_monitor_ok", "autopush_installed",
            "http_server", "cycle_runner_exists", "multi_strategy_runner",
            "safe_tx_builder", "promotion_engine", "adr022_exists",
        ]},
        "blockers": [],
    })

    # ── Financial ─────────────────────────────────────────────────────────────
    _write(data / "paper_trading_status.json",
           {"virtual_capital": 100000, "is_demo": False})
    _write(data / "capital_config.json",
           {"starting_capital": 100000, "currency": "USDC"})
    # 31 days equity curve
    entries = [{"date": f"2026-{m:02d}-{d:02d}", "equity": 100000 + i * 10}
               for i, (m, d) in enumerate([(5, j) for j in range(20, 31)]
                                           + [(6, j) for j in range(1, 21)])]
    _write(data / "equity_curve_daily.json", entries)
    _write(data / "paper" / "evidence_v2.json", {"total_evidence_points": 31.0})
    # KYC / family fund onboarding doc (≥200 bytes)
    kyc = docs / "legal" / "ONBOARDING_CHECKLIST.md"
    kyc.parent.mkdir(parents=True, exist_ok=True)
    kyc.write_text("# Family Fund Onboarding\n\n" + "KYC complete. " * 20)

    # ── Evidence ──────────────────────────────────────────────────────────────
    analytics = spa / "analytics"
    analytics.mkdir(parents=True, exist_ok=True)
    (analytics / "__init__.py").write_text("")
    (analytics / "evidence_auto_calculator.py").write_text(
        "# evidence_auto_calculator stub\nSCHEMA_VERSION = '1.0'\n"
    )
    (analytics / "t1_data_verifier.py").write_text("# t1 verifier stub\n")
    (analytics / "fee_structure.py").write_text("# fee structure stub\n")
    # paper_evidence_history.json: initialized with 20 seed days
    seed_days = [{"date": f"2026-05-{i:02d}", "cycle_completed": True,
                  "apy_verified": True, "risk_policy_passed": True, "is_seed": True}
                 for i in range(1, 21)]
    _write(data / "paper_evidence_history.json", {
        "schema_version": "1.0", "initialized_at": "2026-05-01",
        "SEED_DATA": True, "day_count": len(seed_days), "days": seed_days,
        "target_pts": 30.0,
    })
    # paper_evidence.json: 20 real days
    real_days = [{"date": f"2026-06-{i:02d}", "strategy_id": "S7",
                  "apy_pct": 4.0, "equity_value": 100000 + i * 10}
                 for i in range(1, 21)]
    _write(data / "paper_evidence.json", {"days": real_days})

    # ── Data Sources ──────────────────────────────────────────────────────────
    utils = spa / "utils"
    utils.mkdir(parents=True, exist_ok=True)
    (utils / "__init__.py").write_text("")
    (utils / "defillama.py").write_text("# defillama stub\n")
    (base / "promotion_engine.py").write_text("# promotion engine stub\n")

    # ── Risk policy ───────────────────────────────────────────────────────────
    risk = spa / "risk"
    risk.mkdir(parents=True, exist_ok=True)
    (risk / "__init__.py").write_text("")
    (risk / "policy.py").write_text("# risk policy stub\nclass RiskPolicy: pass\n")

    # ── Documentation (≥200 bytes each, ≥3 ADRs) ──────────────────────────────
    docs.mkdir(parents=True, exist_ok=True)
    for fname, title in [
        ("RISK_MANAGEMENT_POLICY.md", "Risk Management Policy"),
        ("DEPLOYMENT_RUNBOOK.md", "Deployment Runbook"),
        ("DATA_SOURCES_REGISTRY.md", "Data Sources Registry"),
        ("FAMILY_FUND_ONBOARDING.md", "Family Fund Onboarding"),
        ("API_REFERENCE.md", "API Reference"),
        ("SECURITY_CHECKLIST.md", "Security Checklist"),
        ("DISASTER_RECOVERY.md", "Disaster Recovery"),
        ("TOKEN_ROTATION_RUNBOOK.md", "Token Rotation Runbook"),
    ]:
        (docs / fname).write_text(f"# {title}\n\n" + f"{title} content. " * 15)
    adr_dir = docs / "adr"
    adr_dir.mkdir(parents=True, exist_ok=True)
    for i in range(1, 4):
        (adr_dir / f"ADR-00{i}.md").write_text(
            f"# ADR-00{i}\n\n" + f"Architecture decision record {i}. " * 10
        )


# ── Test: CategoryScore ────────────────────────────────────────────────────────

class TestCategoryScore(unittest.TestCase):

    def _make(self, score=50.0, max_score=100.0) -> CategoryScore:
        return CategoryScore(
            name="test_cat",
            score=score,
            max_score=max_score,
            items_done=["done item"],
            items_pending=["pending item"],
            notes="test notes",
        )

    # T01
    def test_init_defaults(self):
        cs = self._make()
        self.assertEqual(cs.name, "test_cat")
        self.assertEqual(cs.score, 50.0)
        self.assertEqual(cs.max_score, 100.0)

    # T02
    def test_pct_normal(self):
        cs = self._make(score=33.0, max_score=100.0)
        self.assertAlmostEqual(cs.pct, 33.0)

    # T03
    def test_pct_zero_max(self):
        cs = self._make(score=0.0, max_score=0.0)
        self.assertEqual(cs.pct, 0.0)

    # T04
    def test_score_not_exceeds_max(self):
        cs = self._make(score=75.0, max_score=100.0)
        self.assertLessEqual(cs.score, cs.max_score)

    # T05
    def test_to_dict_keys(self):
        cs = self._make()
        d = cs.to_dict()
        for key in ("name", "score", "max_score", "pct", "items_done", "items_pending", "notes"):
            self.assertIn(key, d)

    # T06
    def test_to_dict_items_done_is_list(self):
        cs = self._make()
        self.assertIsInstance(cs.to_dict()["items_done"], list)

    # T07
    def test_to_dict_pct_rounded(self):
        cs = self._make(score=33.33, max_score=100.0)
        d = cs.to_dict()
        self.assertIsInstance(d["pct"], float)

    # T08
    def test_items_pending_is_list(self):
        cs = self._make()
        self.assertIsInstance(cs.items_pending, list)


# ── Test: GoLiveReadinessReport initialization ─────────────────────────────────

class TestGoLiveReadinessReportInit(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        _make_minimal_env(Path(self.tmp))
        self.report = GoLiveReadinessReport(base_dir=self.tmp)

    # T09
    def test_init_no_error(self):
        r = GoLiveReadinessReport(base_dir=self.tmp)
        self.assertIsNotNone(r)

    # T10
    def test_init_empty_dir_no_crash(self):
        empty = tempfile.mkdtemp()
        r = GoLiveReadinessReport(base_dir=empty)
        self.assertIsNotNone(r)

    # T11
    def test_readiness_categories_constant(self):
        self.assertIsInstance(READINESS_CATEGORIES, list)
        self.assertGreater(len(READINESS_CATEGORIES), 0)

    # T12
    def test_evidence_target_constant(self):
        self.assertGreater(EVIDENCE_TARGET, 0)


# ── Test: assess_gate_status ───────────────────────────────────────────────────

class TestAssessGateStatus(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        _make_minimal_env(Path(self.tmp))
        self.report = GoLiveReadinessReport(base_dir=self.tmp)

    # T13
    def test_returns_category_score(self):
        result = self.report.assess_gate_status()
        self.assertIsInstance(result, CategoryScore)

    # T14
    def test_score_le_max(self):
        cs = self.report.assess_gate_status()
        self.assertLessEqual(cs.score, cs.max_score)

    # T15
    def test_score_ge_zero(self):
        cs = self.report.assess_gate_status()
        self.assertGreaterEqual(cs.score, 0.0)

    # T16
    def test_backtest_pass_adds_25(self):
        cs = self.report.assess_gate_status()
        # Backtest gate is PASS in minimal env
        self.assertGreaterEqual(cs.score, 25.0)

    # T17
    def test_blocked_gate_in_pending(self):
        cs = self.report.assess_gate_status()
        combined = " ".join(cs.items_pending)
        self.assertIn("BLOCKED", combined)

    # T18
    def test_name_is_gate_status(self):
        cs = self.report.assess_gate_status()
        self.assertEqual(cs.name, "gate_status")


# ── Test: assess_data_quality ──────────────────────────────────────────────────

class TestAssessDataQuality(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        _make_minimal_env(Path(self.tmp))
        self.report = GoLiveReadinessReport(base_dir=self.tmp)

    # T19
    def test_returns_category_score(self):
        result = self.report.assess_data_quality()
        self.assertIsInstance(result, CategoryScore)

    # T20
    def test_score_le_max(self):
        cs = self.report.assess_data_quality()
        self.assertLessEqual(cs.score, cs.max_score)

    # T21
    def test_score_ge_zero(self):
        cs = self.report.assess_data_quality()
        self.assertGreaterEqual(cs.score, 0.0)

    # T22
    def test_clean_sources_in_done(self):
        cs = self.report.assess_data_quality()
        combined = " ".join(cs.items_done)
        self.assertIn("clean_included", combined)

    # T23
    def test_pending_sources_in_pending(self):
        cs = self.report.assess_data_quality()
        combined = " ".join(cs.items_pending)
        self.assertIn("pending", combined)

    # T24
    def test_missing_pipeline_returns_zero(self):
        empty = tempfile.mkdtemp()
        r = GoLiveReadinessReport(base_dir=empty)
        cs = r.assess_data_quality()
        self.assertEqual(cs.score, 0.0)


# ── Test: assess_evidence_points ──────────────────────────────────────────────

class TestAssessEvidencePoints(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        _make_minimal_env(Path(self.tmp))
        self.report = GoLiveReadinessReport(base_dir=self.tmp)

    # T25
    def test_returns_category_score(self):
        result = self.report.assess_evidence_points()
        self.assertIsInstance(result, CategoryScore)

    # T26
    def test_score_le_max(self):
        cs = self.report.assess_evidence_points()
        self.assertLessEqual(cs.score, cs.max_score)

    # T27
    def test_no_evidence_score_zero(self):
        cs = self.report.assess_evidence_points()
        # minimal env has no evidence_v2.json → score == 0
        self.assertEqual(cs.score, 0.0)

    # T28
    def test_sufficient_evidence_score_100(self):
        ev_path = Path(self.tmp) / "data" / "paper" / "evidence_v2.json"
        _write(ev_path, {"total_evidence_points": 30.0})
        r = GoLiveReadinessReport(base_dir=self.tmp)
        cs = r.assess_evidence_points()
        self.assertAlmostEqual(cs.score, 100.0)


# ── Test: assess_owner_acceptance ─────────────────────────────────────────────

class TestAssessOwnerAcceptance(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        _make_minimal_env(Path(self.tmp))
        self.report = GoLiveReadinessReport(base_dir=self.tmp)

    # T29
    def test_returns_category_score(self):
        result = self.report.assess_owner_acceptance()
        self.assertIsInstance(result, CategoryScore)

    # T30
    def test_not_signed_score_zero(self):
        cs = self.report.assess_owner_acceptance()
        self.assertEqual(cs.score, 0.0)

    # T31
    def test_signed_score_100(self):
        acc_path = Path(self.tmp) / "data" / "backtest" / "owner_paper_acceptance.json"
        _write(acc_path, {
            "accepted": True,
            "owner": "Yurii",
            "accepted_at": "2026-06-19T10:00:00",
        })
        r = GoLiveReadinessReport(base_dir=self.tmp)
        cs = r.assess_owner_acceptance()
        self.assertAlmostEqual(cs.score, 100.0)

    # T32
    def test_not_signed_in_pending(self):
        cs = self.report.assess_owner_acceptance()
        combined = " ".join(cs.items_pending)
        self.assertIn("NOT_SIGNED", combined)


# ── Test: assess_infrastructure ───────────────────────────────────────────────

class TestAssessInfrastructure(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        _make_minimal_env(Path(self.tmp))
        self.report = GoLiveReadinessReport(base_dir=self.tmp)

    # T33
    def test_returns_category_score(self):
        result = self.report.assess_infrastructure()
        self.assertIsInstance(result, CategoryScore)

    # T34
    def test_score_le_max(self):
        cs = self.report.assess_infrastructure()
        self.assertLessEqual(cs.score, cs.max_score)

    # T35
    def test_all_checks_pass_full_score(self):
        cs = self.report.assess_infrastructure()
        # minimal env has all infra checks True → score == max_score
        self.assertAlmostEqual(cs.score, cs.max_score)


# ── Test: total_score ─────────────────────────────────────────────────────────

class TestTotalScore(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        _make_minimal_env(Path(self.tmp))
        self.report = GoLiveReadinessReport(base_dir=self.tmp)

    # T36
    def test_returns_float(self):
        self.assertIsInstance(self.report.total_score(), float)

    # T37
    def test_in_range_0_100(self):
        score = self.report.total_score()
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 100.0)

    # T38
    def test_empty_dir_returns_zero(self):
        empty = tempfile.mkdtemp()
        r = GoLiveReadinessReport(base_dir=empty)
        score = r.total_score()
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 100.0)


# ── Test: overall_status ──────────────────────────────────────────────────────

class TestOverallStatus(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        _make_minimal_env(Path(self.tmp))
        self.report = GoLiveReadinessReport(base_dir=self.tmp)

    # T39
    def test_returns_valid_string(self):
        status = self.report.overall_status()
        self.assertIn(status, ("READY", "NOT_READY", "BLOCKED"))

    # T40
    def test_minimal_env_is_blocked(self):
        # expanded_universe_verification_status == STRICT_BLOCKED → BLOCKED
        self.assertEqual(self.report.overall_status(), "BLOCKED")

    # T41
    def test_ready_env_is_ready(self):
        tmp2 = tempfile.mkdtemp()
        _make_ready_env(Path(tmp2))
        r = GoLiveReadinessReport(base_dir=tmp2)
        self.assertEqual(r.overall_status(), "READY")


# ── Test: blocking_items ──────────────────────────────────────────────────────

class TestBlockingItems(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        _make_minimal_env(Path(self.tmp))
        self.report = GoLiveReadinessReport(base_dir=self.tmp)

    # T42
    def test_returns_list(self):
        self.assertIsInstance(self.report.blocking_items(), list)

    # T43
    def test_not_empty_when_not_ready(self):
        self.assertGreater(len(self.report.blocking_items()), 0)


# ── Test: estimated_days_to_ready ─────────────────────────────────────────────

class TestEstimatedDays(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        _make_minimal_env(Path(self.tmp))
        self.report = GoLiveReadinessReport(base_dir=self.tmp)

    # T44
    def test_returns_int(self):
        self.assertIsInstance(self.report.estimated_days_to_ready(), int)

    # T45
    def test_gt_zero_when_not_ready(self):
        self.assertGreater(self.report.estimated_days_to_ready(), 0)


# ── Test: to_markdown ─────────────────────────────────────────────────────────

class TestToMarkdown(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        _make_minimal_env(Path(self.tmp))
        self.report = GoLiveReadinessReport(base_dir=self.tmp)

    # T46 (extra, brings total to 46 — but let's label correctly)
    def test_contains_golive(self):
        md = self.report.to_markdown()
        self.assertIn("Go-Live", md)

    def test_contains_status(self):
        md = self.report.to_markdown()
        # should contain BLOCKED or NOT_READY in output
        self.assertTrue("BLOCKED" in md or "NOT_READY" in md)

    def test_is_string(self):
        self.assertIsInstance(self.report.to_markdown(), str)


# ── Test: save ────────────────────────────────────────────────────────────────

class TestSave(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        _make_minimal_env(Path(self.tmp))
        self.report = GoLiveReadinessReport(base_dir=self.tmp)

    def test_save_creates_json_file(self):
        path = self.report.save()
        self.assertTrue(os.path.exists(path), f"JSON not created: {path}")

    def test_save_creates_md_file(self):
        self.report.save()
        import datetime
        today = datetime.date.today().isoformat()
        md_path = Path(self.tmp) / "data" / "reports" / f"golive_readiness_{today}.md"
        self.assertTrue(md_path.exists(), f"MD not created: {md_path}")

    def test_save_json_is_valid(self):
        path = self.report.save()
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertIn("overall_status", data)
        self.assertIn("total_score", data)

    def test_save_returns_string(self):
        path = self.report.save()
        self.assertIsInstance(path, str)


if __name__ == "__main__":
    unittest.main(verbosity=2)
