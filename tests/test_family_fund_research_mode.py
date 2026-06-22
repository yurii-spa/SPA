"""
tests/test_family_fund_research_mode.py — 30 tests for ResearchModeAPI (MP-1335 v9.51)

Coverage:
  T01–T07   handle_research_status() — structure
  T08–T15   rs001_projection() — keys, types, values
  T16–T21   rs002_projection() — keys, types, values
  T22–T26   gate_summary() — structure and invariants
  T27–T30   disclaimer() — non-empty, correct type, fallback
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

from spa_core.family_fund.research_mode import ResearchModeAPI


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_api(tmp_dir: str = None) -> ResearchModeAPI:
    """Return a ResearchModeAPI instance pointing at a temp directory."""
    if tmp_dir is None:
        tmp_dir = tempfile.mkdtemp()
    return ResearchModeAPI(base_dir=tmp_dir)


# ══════════════════════════════════════════════════════════════════════════════
# T01–T07  handle_research_status()
# ══════════════════════════════════════════════════════════════════════════════

class TestHandleResearchStatus(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.api = _make_api(self.tmp)

    def test_T01_returns_dict(self):
        """handle_research_status() returns a dict."""
        result = self.api.handle_research_status()
        self.assertIsInstance(result, dict)

    def test_T02_contains_rs001_key(self):
        """handle_research_status() contains 'rs001' key."""
        result = self.api.handle_research_status()
        self.assertIn("rs001", result)

    def test_T03_contains_rs002_key(self):
        """handle_research_status() contains 'rs002' key."""
        result = self.api.handle_research_status()
        self.assertIn("rs002", result)

    def test_T04_contains_gate_key(self):
        """handle_research_status() contains 'gate' key."""
        result = self.api.handle_research_status()
        self.assertIn("gate", result)

    def test_T05_all_three_top_level_keys_present(self):
        """All three top-level keys are present simultaneously."""
        result = self.api.handle_research_status()
        self.assertSetEqual(set(result.keys()), {"rs001", "rs002", "gate"})

    def test_T06_rs001_value_is_dict(self):
        """rs001 value inside handle_research_status() is a dict."""
        result = self.api.handle_research_status()
        self.assertIsInstance(result["rs001"], dict)

    def test_T07_rs002_value_is_dict(self):
        """rs002 value inside handle_research_status() is a dict."""
        result = self.api.handle_research_status()
        self.assertIsInstance(result["rs002"], dict)


# ══════════════════════════════════════════════════════════════════════════════
# T08–T15  rs001_projection()
# ══════════════════════════════════════════════════════════════════════════════

class TestRS001Projection(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.api = _make_api(self.tmp)

    def test_T08_returns_dict(self):
        """rs001_projection() returns a dict."""
        result = self.api.rs001_projection()
        self.assertIsInstance(result, dict)

    def test_T09_status_is_research_only(self):
        """rs001_projection() status == 'RESEARCH_ONLY'."""
        result = self.api.rs001_projection()
        self.assertEqual(result["status"], "RESEARCH_ONLY")

    def test_T10_has_blended_apy_projection_key(self):
        """rs001_projection() has 'blended_apy_projection' key."""
        result = self.api.rs001_projection()
        self.assertIn("blended_apy_projection", result)

    def test_T11_blended_apy_projection_is_float(self):
        """blended_apy_projection is a float (or int)."""
        result = self.api.rs001_projection()
        self.assertIsInstance(result["blended_apy_projection"], (int, float))

    def test_T12_blended_apy_projection_positive(self):
        """blended_apy_projection > 0."""
        result = self.api.rs001_projection()
        self.assertGreater(result["blended_apy_projection"], 0)

    def test_T13_has_disclaimer_key(self):
        """rs001_projection() has 'disclaimer' key."""
        result = self.api.rs001_projection()
        self.assertIn("disclaimer", result)

    def test_T14_has_target_apy_key(self):
        """rs001_projection() has 'target_apy' key."""
        result = self.api.rs001_projection()
        self.assertIn("target_apy", result)

    def test_T15_has_strict_eligible_fraction_key(self):
        """rs001_projection() has 'strict_eligible_fraction' key."""
        result = self.api.rs001_projection()
        self.assertIn("strict_eligible_fraction", result)

    def test_T15b_blended_apy_from_file_if_available(self):
        """blended_apy_projection reads from rs001_apy_breakdown.json when present."""
        research_dir = Path(self.tmp) / "data" / "research"
        research_dir.mkdir(parents=True, exist_ok=True)
        breakdown = {"blended_apy": 42.0}
        (research_dir / "rs001_apy_breakdown.json").write_text(
            json.dumps(breakdown), encoding="utf-8"
        )
        result = self.api.rs001_projection()
        self.assertAlmostEqual(result["blended_apy_projection"], 42.0, places=3)


# ══════════════════════════════════════════════════════════════════════════════
# T16–T21  rs002_projection()
# ══════════════════════════════════════════════════════════════════════════════

class TestRS002Projection(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.api = _make_api(self.tmp)

    def test_T16_returns_dict(self):
        """rs002_projection() returns a dict."""
        result = self.api.rs002_projection()
        self.assertIsInstance(result, dict)

    def test_T17_status_is_research_only(self):
        """rs002_projection() status == 'RESEARCH_ONLY'."""
        result = self.api.rs002_projection()
        self.assertEqual(result["status"], "RESEARCH_ONLY")

    def test_T18_has_net_apy_range(self):
        """rs002_projection() has 'net_apy_range' key."""
        result = self.api.rs002_projection()
        self.assertIn("net_apy_range", result)

    def test_T19_net_apy_range_is_list_of_two(self):
        """net_apy_range is a list with exactly 2 elements."""
        result = self.api.rs002_projection()
        r = result["net_apy_range"]
        self.assertIsInstance(r, list)
        self.assertEqual(len(r), 2)

    def test_T20_il_risk_is_high(self):
        """rs002_projection() il_risk == 'HIGH'."""
        result = self.api.rs002_projection()
        self.assertEqual(result["il_risk"], "HIGH")

    def test_T21_has_disclaimer(self):
        """rs002_projection() has non-empty 'disclaimer'."""
        result = self.api.rs002_projection()
        self.assertIn("disclaimer", result)
        self.assertTrue(len(result["disclaimer"]) > 0)


# ══════════════════════════════════════════════════════════════════════════════
# T22–T26  gate_summary()
# ══════════════════════════════════════════════════════════════════════════════

class TestGateSummary(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.api = _make_api(self.tmp)

    def test_T22_returns_dict(self):
        """gate_summary() returns a dict."""
        result = self.api.gate_summary()
        self.assertIsInstance(result, dict)

    def test_T23_paper_ready_is_false(self):
        """gate_summary() paper_ready == False (owner unsigned)."""
        result = self.api.gate_summary()
        self.assertFalse(result["paper_ready"])

    def test_T24_has_blockers_list(self):
        """gate_summary() has 'blockers' key that is a list."""
        result = self.api.gate_summary()
        self.assertIn("blockers", result)
        self.assertIsInstance(result["blockers"], list)

    def test_T25_blockers_non_empty(self):
        """blockers list is always non-empty (owner blocker guaranteed)."""
        result = self.api.gate_summary()
        self.assertGreater(len(result["blockers"]), 0)

    def test_T26_estimated_paper_start_is_none(self):
        """estimated_paper_start is None in research phase."""
        result = self.api.gate_summary()
        self.assertIsNone(result["estimated_paper_start"])

    def test_T26b_gate_reads_golive_blockers(self):
        """gate_summary() incorporates blockers from golive_status.json."""
        data_dir = Path(self.tmp) / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        golive = {
            "ready": False,
            "blockers": ["gap_monitor: 1/30 days", "adapter_missing"],
        }
        (data_dir / "golive_status.json").write_text(
            json.dumps(golive), encoding="utf-8"
        )
        result = _make_api(self.tmp).gate_summary()
        # Should contain at least the owner blocker + some system blockers
        self.assertGreater(len(result["blockers"]), 1)


# ══════════════════════════════════════════════════════════════════════════════
# T27–T30  disclaimer()
# ══════════════════════════════════════════════════════════════════════════════

class TestDisclaimer(unittest.TestCase):

    def setUp(self):
        self.api = _make_api()

    def test_T27_rs001_disclaimer_not_empty(self):
        """disclaimer('rs001') returns non-empty string."""
        d = self.api.disclaimer("rs001")
        self.assertIsInstance(d, str)
        self.assertGreater(len(d), 0)

    def test_T28_rs002_disclaimer_not_empty(self):
        """disclaimer('rs002') returns non-empty string."""
        d = self.api.disclaimer("rs002")
        self.assertIsInstance(d, str)
        self.assertGreater(len(d), 0)

    def test_T29_unknown_strategy_has_fallback(self):
        """disclaimer() with unknown id returns non-empty fallback string."""
        d = self.api.disclaimer("rs_unknown_xyz")
        self.assertIsInstance(d, str)
        self.assertGreater(len(d), 0)

    def test_T30_disclaimer_is_string_type(self):
        """disclaimer() always returns str for various inputs."""
        for sid in ["rs001", "rs002", "rs003", "", "x"]:
            with self.subTest(strategy_id=sid):
                d = self.api.disclaimer(sid)
                self.assertIsInstance(d, str)


if __name__ == "__main__":
    unittest.main(verbosity=2)
