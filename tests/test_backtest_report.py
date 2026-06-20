"""
tests/test_backtest_report.py

MP-1498 (v11.14) — 20 unit tests for BacktestReport.

Covers:
  1. Instantiation & defaults                           (3 tests)
  2. generate(): structure & required keys              (5 tests)
  3. _build_recommendation(): signal logic              (4 tests)
  4. to_markdown(): output correctness                  (4 tests)
  5. File output (JSON + Markdown)                      (4 tests)

Compatible with stdlib unittest and pytest.
"""

import os
import sys
import json
import tempfile
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from spa_core.reporting.backtest_report import BacktestReport


# ── helpers ───────────────────────────────────────────────────────────────────

def _report(strategy_id="S0", base_dir=None) -> BacktestReport:
    return BacktestReport(strategy_id=strategy_id, base_dir=base_dir or tempfile.mkdtemp())


def _write_json(tmpdir: str, rel_path: str, data: dict) -> None:
    full = os.path.join(tmpdir, rel_path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w") as f:
        json.dump(data, f)


class TestInstantiation(unittest.TestCase):
    """TC-BR-01..03: __init__ sets correct defaults."""

    def test_01_strategy_id_stored(self):
        r = _report("S5")
        self.assertEqual(r.strategy_id, "S5")

    def test_02_output_path_contains_strategy_id(self):
        r = _report("S5")
        self.assertIn("S5", r.OUTPUT_PATH)

    def test_03_report_initially_empty(self):
        r = _report()
        self.assertEqual(r._report, {})


class TestGenerate(unittest.TestCase):
    """TC-BR-04..08: generate() structure."""

    def setUp(self):
        self.r = _report()
        self.result = self.r.generate()

    def test_04_returns_dict(self):
        self.assertIsInstance(self.result, dict)

    def test_05_has_strategy_key(self):
        self.assertEqual(self.result["strategy"], "S0")

    def test_06_has_generated_at(self):
        self.assertIn("generated_at", self.result)
        self.assertTrue(self.result["generated_at"].endswith("Z"))

    def test_07_has_all_section_keys(self):
        for key in ("summary", "walk_forward", "monte_carlo",
                    "backtest_paper_correlation", "gate_status", "recommendation"):
            self.assertIn(key, self.result)

    def test_08_summary_has_required_fields(self):
        summary = self.result["summary"]
        for key in ("annualized_return", "volatility", "sharpe_ratio",
                    "max_drawdown", "calmar_ratio"):
            self.assertIn(key, summary)


class TestRecommendation(unittest.TestCase):
    """TC-BR-09..12: _build_recommendation() signal logic."""

    def _inject(self, wf_verdict="", mc_verdict="", corr_passes=False):
        r = _report()
        r._report = {
            "strategy": "S0",
            "generated_at": "2026-06-20T00:00:00Z",
            "summary": {"annualized_return": 0.0, "volatility": 0.0,
                        "sharpe_ratio": 0.0, "max_drawdown": 0.0, "calmar_ratio": 0.0},
            "walk_forward": {"verdict": wf_verdict},
            "monte_carlo": {"verdict": mc_verdict},
            "backtest_paper_correlation": {"passes_threshold": corr_passes},
            "gate_status": {},
        }
        return r._build_recommendation()

    def test_09_three_signals_proceed_to_live(self):
        rec = self._inject("STRONG", "ROBUST", True)
        self.assertEqual(rec["action"], "PROCEED_TO_LIVE")
        self.assertEqual(rec["positive_signals"], 3)

    def test_10_two_signals_proceed_to_paper(self):
        rec = self._inject("MODERATE", "ROBUST", False)
        self.assertEqual(rec["action"], "PROCEED_TO_PAPER")

    def test_11_one_signal_revise_strategy(self):
        rec = self._inject("WEAK", "RISKY", True)
        self.assertEqual(rec["action"], "REVISE_STRATEGY")

    def test_12_zero_signals_revise_strategy(self):
        rec = self._inject("NEGATIVE_OOS", "RISKY", False)
        self.assertEqual(rec["action"], "REVISE_STRATEGY")
        self.assertEqual(rec["positive_signals"], 0)


class TestToMarkdown(unittest.TestCase):
    """TC-BR-13..16: to_markdown() output."""

    def setUp(self):
        self.r = _report()
        self.r.generate()
        self.md = self.r.to_markdown()

    def test_13_returns_string(self):
        self.assertIsInstance(self.md, str)

    def test_14_contains_strategy_id(self):
        self.assertIn("S0", self.md)

    def test_15_contains_recommendation_section(self):
        self.assertIn("Recommendation", self.md)

    def test_16_contains_walk_forward_section(self):
        self.assertIn("Walk-Forward", self.md)


class TestFileOutput(unittest.TestCase):
    """TC-BR-17..20: JSON and Markdown file output."""

    def test_17_save_writes_json_file(self):
        tmpdir = tempfile.mkdtemp()
        r = _report("S1", base_dir=tmpdir)
        r.generate()
        r.save()
        out = os.path.join(tmpdir, r.OUTPUT_PATH)
        self.assertTrue(os.path.exists(out))
        with open(out) as f:
            data = json.load(f)
        self.assertEqual(data["strategy"], "S1")

    def test_18_save_markdown_writes_md_file(self):
        tmpdir = tempfile.mkdtemp()
        r = _report("S2", base_dir=tmpdir)
        r.generate()
        r.save_markdown()
        md_path = os.path.join(tmpdir, r.OUTPUT_PATH.replace(".json", ".md"))
        self.assertTrue(os.path.exists(md_path))

    def test_19_loads_walk_forward_data_when_file_exists(self):
        tmpdir = tempfile.mkdtemp()
        _write_json(tmpdir, "data/walk_forward_S3.json", {
            "strategy": "S3", "n_windows": 4,
            "is_sharpe_avg": 1.5, "oos_sharpe_avg": 1.1,
            "degradation_ratio": 0.73, "verdict": "STRONG",
        })
        r = _report("S3", base_dir=tmpdir)
        result = r.generate()
        self.assertEqual(result["walk_forward"]["verdict"], "STRONG")

    def test_20_loads_monte_carlo_data_when_file_exists(self):
        tmpdir = tempfile.mkdtemp()
        _write_json(tmpdir, "data/monte_carlo_S4.json", {
            "results": {
                "S4": {
                    "strategy": "S4", "simulations": 1000,
                    "p50": 1.12, "prob_profitable": 0.82,
                    "prob_drawdown_20pct": 0.04, "verdict": "ROBUST",
                }
            }
        })
        r = _report("S4", base_dir=tmpdir)
        result = r.generate()
        self.assertEqual(result["monte_carlo"]["verdict"], "ROBUST")


if __name__ == "__main__":
    unittest.main()
