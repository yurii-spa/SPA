"""
tests/test_gates_assessment.py

MP-1441 (v10.57) — 30 тестов для assess_gates() + Gate infrastructure

Test groups:
  1.  gate_status.json structure (tests 1–5)
  2.  pre_launch_validation.json structure (tests 6–10)
  3.  assess_gates() category structure (tests 11–15)
  4.  assess_gates() scoring with full env (tests 16–22)
  5.  Individual gate criteria isolation (tests 23–27)
  6.  generate_report() + regression guard (tests 28–30)

Total: 30 tests
stdlib unittest + pytest compatible
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.analytics.golive_readiness_report import (
    CategoryScore,
    GoLiveReadinessReport,
)


# ── helpers ────────────────────────────────────────────────────────────────────

def _write(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)


def _make_base_env(base: Path) -> None:
    """Minimal env so GoLiveReadinessReport runs without errors."""
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
    _write(bt / "source_pipeline.json", {"sources": {}})
    _write(data / "golive_status.json", {
        "checks": {k: True for k in [
            "equity_curve_real", "trades_real", "status_real", "no_demo_data",
            "data_fresh_48h", "cycle_runner_exists", "multi_strategy_runner",
            "promotion_engine", "safe_tx_builder", "http_server", "adr022_exists",
            "gap_monitor_ok", "autopush_installed", "apy_above_floor",
            "drawdown_below_kill_kill", "risk_policy_snapshot",
        ]},
    })
    _write(data / "paper_trading_status.json", {
        "is_demo": False,
        "current_equity": 100_000.0,
    })
    _write(data / "current_positions.json", {"capital_usd": 100_000.0, "deployed_usd": 75_000.0})
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
    _write(data / "paper_evidence_history.json", {"schema_version": "1.0", "day_count": 2})
    _write(data / "capital_config.json", {
        "capital": {"starting_capital_usd": 100_000}
    })
    # kill switch: triggered=false = LOCKED
    _write(data / "kill_switch_status.json", {"triggered": False, "reason": "all clear"})
    # gate_status.json
    _write(data / "gate_status.json", {
        "schema_version": "1.0",
        "backtest_gate": "PASS",
        "kill_switch_status": "LOCKED",
    })
    # pre_launch_validation.json: 32/40 = 80%
    _write(data / "pre_launch_validation.json", {
        "schema_version": "1.0",
        "pass_count": 32,
        "passed_count": 32,
        "total_count": 40,
        "pass_pct": 80.0,
        "launch_ready": False,
    })
    # analytics modules
    analytics = base / "spa_core" / "analytics"
    analytics.mkdir(parents=True, exist_ok=True)
    (analytics / "evidence_auto_calculator.py").write_text(
        "# evidence_auto_calculator\n", encoding="utf-8"
    )
    (analytics / "t1_data_verifier.py").write_text("# t1\n", encoding="utf-8")
    (analytics / "fee_structure.py").write_text("# fee_structure\n" * 20, encoding="utf-8")
    # adapters
    adapters = base / "spa_core" / "adapters"
    adapters.mkdir(parents=True, exist_ok=True)
    (adapters / "defillama_feed.py").write_text("# feed\n", encoding="utf-8")
    # risk policy
    risk_dir = base / "spa_core" / "risk"
    risk_dir.mkdir(parents=True, exist_ok=True)
    (risk_dir / "policy.py").write_text("# policy\n" * 10, encoding="utf-8")
    # docs
    for fname in [
        "RISK_MANAGEMENT_POLICY.md", "DEPLOYMENT_RUNBOOK.md",
        "DATA_SOURCES_REGISTRY.md", "FAMILY_FUND_ONBOARDING.md",
        "API_REFERENCE.md", "SECURITY_CHECKLIST.md",
        "DISASTER_RECOVERY.md", "TOKEN_ROTATION_RUNBOOK.md",
    ]:
        (docs / fname).write_text("# doc\n" * 60, encoding="utf-8")
    (adr / "ADR-001.md").write_text("# adr\n" * 60, encoding="utf-8")
    (adr / "ADR-002.md").write_text("# adr\n" * 60, encoding="utf-8")
    (adr / "ADR-003.md").write_text("# adr\n" * 60, encoding="utf-8")
    # legal
    legal = docs / "legal"
    legal.mkdir(parents=True, exist_ok=True)
    (legal / "ONBOARDING_CHECKLIST.md").write_text("# checklist\n" * 15, encoding="utf-8")


# ══════════════════════════════════════════════════════════════════════════════
# GROUP 1 — gate_status.json structure (tests 1–5)
# ══════════════════════════════════════════════════════════════════════════════

# WS4 hermeticity: these classes assert against the LIVE committed gate
# artifacts. On a clean checkout with an empty data/ they are absent → skip the
# class (live-presence/consistency guard, not a hermetic unit test).
@unittest.skipUnless(
    (_REPO_ROOT / "data" / "gate_status.json").exists(),
    "live data/gate_status.json absent (clean checkout)",
)
class TestGateStatusJson(unittest.TestCase):

    def setUp(self):
        self.gate_status_path = _REPO_ROOT / "data" / "gate_status.json"

    def test_01_gate_status_file_exists(self):
        """gate_status.json must exist in data/."""
        self.assertTrue(
            self.gate_status_path.exists(),
            "data/gate_status.json not found — run MP-1441 setup",
        )

    def test_02_gate_status_is_valid_json(self):
        """gate_status.json must be parseable JSON."""
        with open(self.gate_status_path, encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertIsInstance(data, dict)

    def test_03_gate_status_has_schema_version(self):
        """gate_status.json must have schema_version field."""
        with open(self.gate_status_path, encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertIn("schema_version", data)
        self.assertEqual(data["schema_version"], "1.0")

    def test_04_gate_status_backtest_gate_pass(self):
        """gate_status.json: backtest_gate must be PASS."""
        with open(self.gate_status_path, encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual(data.get("backtest_gate"), "PASS")

    def test_05_gate_status_kill_switch_locked(self):
        """gate_status.json: kill_switch_status must be LOCKED."""
        with open(self.gate_status_path, encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual(data.get("kill_switch_status"), "LOCKED")


# ══════════════════════════════════════════════════════════════════════════════
# GROUP 2 — pre_launch_validation.json structure (tests 6–10)
# ══════════════════════════════════════════════════════════════════════════════

@unittest.skipUnless(
    (_REPO_ROOT / "data" / "pre_launch_validation.json").exists(),
    "live data/pre_launch_validation.json absent (clean checkout)",
)
class TestPreLaunchValidationJson(unittest.TestCase):

    def setUp(self):
        self.plv_path = _REPO_ROOT / "data" / "pre_launch_validation.json"

    def test_06_plv_file_exists(self):
        """data/pre_launch_validation.json must exist."""
        self.assertTrue(
            self.plv_path.exists(),
            "data/pre_launch_validation.json missing — run pre_launch_validation",
        )

    def test_07_plv_is_valid_json(self):
        """pre_launch_validation.json must be valid JSON."""
        with open(self.plv_path, encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertIsInstance(data, dict)

    def test_08_plv_has_pass_count(self):
        """pre_launch_validation.json must have pass_count or passed_count."""
        with open(self.plv_path, encoding="utf-8") as fh:
            data = json.load(fh)
        has_count = "pass_count" in data or "passed_count" in data
        self.assertTrue(has_count, "Missing pass_count / passed_count field")

    def test_09_plv_pass_rate_above_80(self):
        """pre_launch_validation.json must have ≥ 80% pass rate."""
        with open(self.plv_path, encoding="utf-8") as fh:
            data = json.load(fh)
        pass_count = data.get("pass_count", data.get("passed_count", 0))
        total_count = data.get("total_count", 1)
        pct = pass_count / total_count * 100.0 if total_count > 0 else 0.0
        self.assertGreaterEqual(
            pct, 80.0,
            f"Pre-launch validation pass rate {pct:.1f}% < 80%",
        )

    def test_10_plv_has_total_count(self):
        """pre_launch_validation.json must have total_count."""
        with open(self.plv_path, encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertIn("total_count", data)
        self.assertGreater(data["total_count"], 0)


# ══════════════════════════════════════════════════════════════════════════════
# GROUP 3 — assess_gates() category structure (tests 11–15)
# ══════════════════════════════════════════════════════════════════════════════

class TestAssessGatesStructure(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        _make_base_env(Path(self.tmp))
        self.r = GoLiveReadinessReport(base_dir=self.tmp)
        self.gates = self.r.assess_gates()

    def test_11_assess_gates_returns_category_score(self):
        """assess_gates() must return a CategoryScore instance."""
        self.assertIsInstance(self.gates, CategoryScore)

    def test_12_assess_gates_name_is_gates(self):
        """CategoryScore.name must be 'gates'."""
        self.assertEqual(self.gates.name, "gates")

    def test_13_assess_gates_max_score_is_20(self):
        """Max score must be exactly 20.0."""
        self.assertEqual(self.gates.max_score, 20.0)

    def test_14_assess_gates_score_within_range(self):
        """Score must be in [0.0, 20.0]."""
        self.assertGreaterEqual(self.gates.score, 0.0)
        self.assertLessEqual(self.gates.score, 20.0)

    def test_15_assess_gates_has_items_lists(self):
        """items_done and items_pending must be lists."""
        self.assertIsInstance(self.gates.items_done, list)
        self.assertIsInstance(self.gates.items_pending, list)


# ══════════════════════════════════════════════════════════════════════════════
# GROUP 4 — assess_gates() scoring with full env (tests 16–22)
# ══════════════════════════════════════════════════════════════════════════════

class TestAssessGatesScoring(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        _make_base_env(Path(self.tmp))
        self.r = GoLiveReadinessReport(base_dir=self.tmp)

    def test_16_backtest_pass_gives_6_pts(self):
        """Backtest Gate PASS → +6 pts."""
        g = self.r.assess_gates()
        # With PASS backtest and full env we should have >= 6 pts
        self.assertGreaterEqual(g.score, 6.0)

    def test_17_paper_started_gives_3_pts_minimum(self):
        """Paper trading started (≥1 day) must contribute +3 pts."""
        g = self.r.assess_gates()
        done_text = " ".join(g.items_done)
        self.assertIn("Paper trading started", done_text)

    def test_18_evidence_infra_initialized_gives_3_pts(self):
        """Evidence infrastructure initialized → +3 pts."""
        g = self.r.assess_gates()
        done_text = " ".join(g.items_done)
        self.assertIn("Evidence infrastructure initialized", done_text)

    def test_19_kill_switch_locked_gives_2_pts(self):
        """Kill-switch LOCKED → +2 pts credited."""
        g = self.r.assess_gates()
        done_text = " ".join(g.items_done)
        self.assertIn("Kill-switch", done_text)
        self.assertIn("LOCKED", done_text)

    def test_20_pre_launch_validation_80pct_gives_2_pts(self):
        """Pre-launch validation ≥80% → +2 pts."""
        g = self.r.assess_gates()
        done_text = " ".join(g.items_done)
        self.assertIn("Pre-launch validation", done_text)

    def test_21_gate_status_json_present_gives_2_pts(self):
        """gate_status.json present → +2 pts."""
        g = self.r.assess_gates()
        done_text = " ".join(g.items_done)
        self.assertIn("gate_status.json", done_text)

    def test_22_full_env_score_at_least_16(self):
        """Full env (all achievable criteria) must score ≥ 16/20."""
        g = self.r.assess_gates()
        self.assertGreaterEqual(
            g.score, 16.0,
            f"Gates score {g.score}/20 < 16 — criteria not met:\n" +
            "\n".join(g.items_pending),
        )


# ══════════════════════════════════════════════════════════════════════════════
# GROUP 5 — Individual gate criteria isolation (tests 23–27)
# ══════════════════════════════════════════════════════════════════════════════

class TestAssessGatesIsolation(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        _make_base_env(Path(self.tmp))

    def test_23_missing_backtest_gate_reduces_score(self):
        """Missing / FAIL backtest gate lowers score by 6 pts."""
        _write(
            Path(self.tmp) / "data" / "backtest" / "pre_paper_backtest_gate.json",
            {"status": "FAIL"},
        )
        r = GoLiveReadinessReport(base_dir=self.tmp)
        g = r.assess_gates()
        self.assertLessEqual(g.score, 14.0, "Backtest FAIL should cost 6 pts")

    def test_24_paper_trading_not_started_pending_message(self):
        """No paper days → pending message about paper not started."""
        _write(
            Path(self.tmp) / "data" / "paper_evidence.json",
            {"schema_version": "1.0", "days": []},
        )
        _write(
            Path(self.tmp) / "data" / "equity_curve_daily.json",
            {"summary": {"num_days": 0}, "daily": []},
        )
        r = GoLiveReadinessReport(base_dir=self.tmp)
        g = r.assess_gates()
        pending_text = " ".join(g.items_pending)
        self.assertIn("not started", pending_text.lower())

    def test_25_missing_gate_status_json_shows_pending(self):
        """Missing gate_status.json → pending message."""
        gate_path = Path(self.tmp) / "data" / "gate_status.json"
        if gate_path.exists():
            gate_path.unlink()
        r = GoLiveReadinessReport(base_dir=self.tmp)
        g = r.assess_gates()
        pending_text = " ".join(g.items_pending)
        self.assertIn("gate_status.json", pending_text)

    def test_26_kill_switch_triggered_shows_pending(self):
        """Kill-switch triggered=True (and no gate_status.json) → pending message."""
        _write(
            Path(self.tmp) / "data" / "kill_switch_status.json",
            {"triggered": True, "reason": "drawdown exceeded"},
        )
        # Remove gate_status kill_switch_status
        _write(
            Path(self.tmp) / "data" / "gate_status.json",
            {"schema_version": "1.0"},  # no kill_switch_status key
        )
        r = GoLiveReadinessReport(base_dir=self.tmp)
        g = r.assess_gates()
        pending_text = " ".join(g.items_pending)
        self.assertIn("Kill-switch", pending_text)

    def test_27_pre_paper_gate_pass_adds_2_pts(self):
        """Pre-Paper Gate PASS → additional +2 pts."""
        base_r = GoLiveReadinessReport(base_dir=self.tmp)
        base_score = base_r.assess_gates().score

        _write(
            Path(self.tmp) / "data" / "backtest" / "paper_ready_gate.json",
            {"status": "READY"},
        )
        new_r = GoLiveReadinessReport(base_dir=self.tmp)
        new_score = new_r.assess_gates().score
        self.assertAlmostEqual(new_score, base_score + 2.0, places=1)


# ══════════════════════════════════════════════════════════════════════════════
# GROUP 6 — generate_report() + regression guard (tests 28–30)
# ══════════════════════════════════════════════════════════════════════════════

class TestGenerateReportAndRegression(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        _make_base_env(Path(self.tmp))
        self.r = GoLiveReadinessReport(base_dir=self.tmp)

    def test_28_generate_report_returns_dict(self):
        """generate_report() must return a dict."""
        report = self.r.generate_report()
        self.assertIsInstance(report, dict)

    def test_29_generate_report_has_required_keys(self):
        """generate_report() dict must contain total_score, overall_status, categories."""
        report = self.r.generate_report()
        for key in ("total_score", "overall_status", "categories", "blocking_items"):
            self.assertIn(key, report, f"Missing key: {key}")

    @unittest.skipUnless(
        (_REPO_ROOT / "data" / "gate_status.json").exists(),
        "live data/gate_status.json absent (clean checkout)",
    )
    def test_30_production_gates_score_gte_16(self):
        """Live repo gates score must be ≥ 16/20 (regression guard)."""
        live_r = GoLiveReadinessReport(base_dir=str(_REPO_ROOT))
        g = live_r.assess_gates()
        self.assertGreaterEqual(
            g.score, 16.0,
            f"Production gates score regressed to {g.score}/20 "
            f"(need ≥ 16)\nPending: {g.items_pending}",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
