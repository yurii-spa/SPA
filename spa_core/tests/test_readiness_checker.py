"""
SPA-V387 — Tests for the Go-Live Readiness Checker.

Read-only analytics surface; every test builds an isolated temp SPA directory
with mock data files so nothing in the real repo is touched. Uses stdlib
unittest (run with ``python3 -m unittest spa_core.tests.test_readiness_checker``).
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.golive.criteria import CRITERIA, Criterion, get_criterion
from spa_core.golive.readiness_checker import ReadinessChecker
from spa_core.golive.readiness_report import ReadinessReport


# A fixed "today" giving 40 days of paper trading (start 2026-06-10 per readiness_checker.py).
TODAY_OK = date(2026, 7, 20)  # 40 days after 2026-06-10
# A fixed "today" giving only 10 days (blocker C001 would fail).
TODAY_SHORT = date(2026, 6, 20)  # 10 days after 2026-06-10


def _good_data() -> dict:
    """Mock data files that should make every criterion PASS."""
    return {
        "risk_metrics.json": {
            "metrics": {
                "win_rate_pct": 55.0,
                "max_drawdown_pct": -2.0,
                "sharpe_ratio": 1.4,
                "num_return_days": 25,
            }
        },
        "drawdown_analysis.json": {
            "summary": {
                "max_drawdown_pct": -2.0,
                "current_drawdown_pct": -1.0,
            }
        },
        "equity_curve_daily.json": {"summary": {"num_days": 25}},
        "adapter_orchestrator_status.json": {
            "adapters": [
                {"protocol": "a", "apy_pct": 8.0},
                {"protocol": "b", "apy_pct": 7.0},
                {"protocol": "c", "apy_pct": 9.0},
            ],
            "overall_health": {"grade": "A"},
        },
        "orchestrator_runs.json": {"runs": [{"run_ts": "2026-06-29T00:00:00+00:00"}]},
        "return_distribution.json": {
            "distribution": {"percentiles": {"p5": -0.87}}
        },
    }


def _root_files() -> dict:
    """Project-root files / KANBAN that should make infra criteria PASS."""
    return {
        "push_to_github.py": "# stub\n",
        "auto_push.py": "# stub\n",
        "KANBAN.json": {"sprint_completed": "v3.85"},
    }


class _Harness(unittest.TestCase):
    """Base class: builds a temp SPA dir and a checker against it."""

    def _build(self, data: dict | None = None, root: dict | None = None,
               today: date = TODAY_OK) -> ReadinessChecker:
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(self._rm, tmp)
        (tmp / "data").mkdir()

        data = _good_data() if data is None else data
        for name, payload in data.items():
            (tmp / "data" / name).write_text(json.dumps(payload), encoding="utf-8")

        root = _root_files() if root is None else root
        for name, payload in root.items():
            content = payload if isinstance(payload, str) else json.dumps(payload)
            (tmp / name).write_text(content, encoding="utf-8")

        return ReadinessChecker(spa_dir=tmp, today=today)

    @staticmethod
    def _rm(path: Path) -> None:
        import shutil
        shutil.rmtree(path, ignore_errors=True)

    @staticmethod
    def _status(result: dict, cid: str) -> str:
        for c in result["criteria"]:
            if c["id"] == cid:
                return c["status"]
        raise AssertionError(f"criterion {cid} not in result")


class TestReadinessChecker(_Harness):

    def test_all_criteria_pass(self):
        result = self._build().check_all()
        self.assertEqual(result["verdict"], "READY")
        self.assertEqual(result["num_failed"], 0)
        self.assertEqual(result["blockers"], [])

    def test_blocker_fail(self):
        # Short paper-trading window → C001 (blocker) FAIL → NOT_READY.
        result = self._build(today=TODAY_SHORT).check_all()
        self.assertEqual(self._status(result, "C001"), "FAIL")
        self.assertEqual(result["verdict"], "NOT_READY")
        self.assertTrue(any(b["id"] == "C001" for b in result["blockers"]))

    def test_no_risk_metrics_file(self):
        data = _good_data()
        del data["risk_metrics.json"]
        del data["equity_curve_daily.json"]  # remove fallback for trading days too
        result = self._build(data=data).check_all()
        # Win rate / sharpe / trading days lose their source → SKIP.
        self.assertEqual(self._status(result, "C002"), "SKIP")
        self.assertEqual(self._status(result, "C004"), "SKIP")
        self.assertEqual(self._status(result, "C005"), "SKIP")

    def test_win_rate_below_threshold(self):
        data = _good_data()
        data["risk_metrics.json"]["metrics"]["win_rate_pct"] = 30.0
        result = self._build(data=data).check_all()
        self.assertEqual(self._status(result, "C002"), "FAIL")
        self.assertEqual(result["verdict"], "NOT_READY")  # C002 is a blocker

    def test_drawdown_exceeds_limit(self):
        data = _good_data()
        data["risk_metrics.json"]["metrics"]["max_drawdown_pct"] = -8.5
        result = self._build(data=data).check_all()
        self.assertEqual(self._status(result, "C003"), "FAIL")

    def test_sharpe_exists_regardless_of_sign(self):
        data = _good_data()
        data["risk_metrics.json"]["metrics"]["sharpe_ratio"] = -5.38
        result = self._build(data=data).check_all()
        # Negative Sharpe must NOT be a FAIL or SKIP — it is a WARN.
        self.assertEqual(self._status(result, "C004"), "WARN")
        self.assertIn("C004", [w["id"] for w in result["warnings"]])

    def test_score_calculation(self):
        result = self._build().check_all()
        # All-pass mock → score must be 1.0.
        self.assertAlmostEqual(result["score"], 1.0, places=4)

    def test_verdict_conditional(self):
        # Keep blockers passing but degrade enough non-blockers to land in 0.5–0.75.
        data = _good_data()
        data["risk_metrics.json"]["metrics"]["sharpe_ratio"] = -1.0  # WARN (medium)
        data["risk_metrics.json"]["metrics"]["num_return_days"] = 5
        data["equity_curve_daily.json"]["summary"]["num_days"] = 5   # C005 FAIL (high)
        data["adapter_orchestrator_status.json"]["adapters"] = [
            {"protocol": "a", "apy_pct": 8.0},
            {"protocol": "b", "apy_pct": 0.0},
        ]                                                            # C006 FAIL (high)
        del data["return_distribution.json"]                         # C009 SKIP (high)
        del data["orchestrator_runs.json"]                           # C007 SKIP (medium)
        root = _root_files()
        root["KANBAN.json"] = {"sprint_completed": "v3.10"}          # C013 FAIL (medium)
        result = self._build(data=data, root=root).check_all()
        self.assertEqual(result["blockers"], [])
        self.assertGreaterEqual(result["score"], 0.50)
        self.assertLess(result["score"], 0.75)
        self.assertEqual(result["verdict"], "CONDITIONAL")

    def test_infrastructure_checks(self):
        root = _root_files()
        del root["auto_push.py"]
        result = self._build(root=root).check_all()
        self.assertEqual(self._status(result, "C011"), "PASS")
        self.assertEqual(self._status(result, "C012"), "FAIL")

    def test_adapter_checks_no_file(self):
        data = _good_data()
        del data["adapter_orchestrator_status.json"]
        del data["orchestrator_runs.json"]
        result = self._build(data=data).check_all()
        self.assertEqual(self._status(result, "C006"), "SKIP")
        self.assertEqual(self._status(result, "C007"), "SKIP")
        self.assertEqual(self._status(result, "C008"), "SKIP")

    def test_adapter_apy_below_minimum(self):
        data = _good_data()
        data["adapter_orchestrator_status.json"]["adapters"] = [
            {"protocol": "a", "apy_pct": 8.0},
            {"protocol": "b", "apy_pct": 0.0},
        ]
        result = self._build(data=data).check_all()
        self.assertEqual(self._status(result, "C006"), "FAIL")

    def test_health_grade_f_blocks(self):
        data = _good_data()
        data["adapter_orchestrator_status.json"]["overall_health"]["grade"] = "F"
        result = self._build(data=data).check_all()
        self.assertEqual(self._status(result, "C008"), "FAIL")
        self.assertEqual(result["verdict"], "NOT_READY")

    def test_current_drawdown_exceeds_limit(self):
        data = _good_data()
        data["drawdown_analysis.json"]["summary"]["current_drawdown_pct"] = -15.0
        result = self._build(data=data).check_all()
        self.assertEqual(self._status(result, "C010"), "FAIL")

    def test_report_formats_correctly(self):
        result = self._build().check_all()
        text = ReadinessReport(result).render()
        self.assertIn("SPA GO-LIVE READINESS REPORT", text)
        self.assertIn("Verdict:", text)
        self.assertIn("READY", text)
        self.assertIn("Days to go-live:", text)

    def test_json_output_written(self):
        result = self._build().check_all()
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(self._rm, tmp)
        out = tmp / "golive_readiness.json"
        ReadinessReport(result).save_json(out)
        self.assertTrue(out.exists())
        reloaded = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(reloaded["verdict"], result["verdict"])
        self.assertIn("criteria", reloaded)

    def test_sprint_completed_check(self):
        root = _root_files()
        root["KANBAN.json"] = {"sprint_completed": "v3.79"}
        result = self._build(root=root).check_all()
        self.assertEqual(self._status(result, "C013"), "FAIL")

        root["KANBAN.json"] = {"sprint_completed": "v3.86"}
        result = self._build(root=root).check_all()
        self.assertEqual(self._status(result, "C013"), "PASS")

    def test_days_to_golive_calculation(self):
        result = self._build(today=date(2026, 6, 9)).check_all()
        # 2026-07-15 − 2026-06-09 = 36 days.
        self.assertEqual(result["days_to_golive"], 36)

    def test_var95_skip_when_missing(self):
        data = _good_data()
        del data["return_distribution.json"]
        result = self._build(data=data).check_all()
        self.assertEqual(self._status(result, "C009"), "SKIP")

    def test_never_raises_on_garbage(self):
        # Corrupt every data file with non-JSON; check_all must still return.
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(self._rm, tmp)
        (tmp / "data").mkdir()
        for name in _good_data():
            (tmp / "data" / name).write_text("{not json", encoding="utf-8")
        (tmp / "KANBAN.json").write_text("{nope", encoding="utf-8")
        result = ReadinessChecker(spa_dir=tmp, today=TODAY_OK).check_all()
        self.assertIn(result["verdict"], {"READY", "CONDITIONAL", "NOT_READY"})


class TestCriteriaCatalogue(unittest.TestCase):

    def test_catalogue_ids_unique(self):
        ids = [c.id for c in CRITERIA]
        self.assertEqual(len(ids), len(set(ids)))

    def test_get_criterion(self):
        c = get_criterion("C001")
        self.assertIsInstance(c, Criterion)
        self.assertEqual(c.category, "paper_trading")

    def test_all_weights_valid(self):
        valid = {"blocker", "high", "medium", "low"}
        for c in CRITERIA:
            self.assertIn(c.weight, valid)


if __name__ == "__main__":
    unittest.main(verbosity=2)
