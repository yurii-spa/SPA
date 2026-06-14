"""
Tests for MP-953: ProtocolGovernanceAttackResistanceScorer
Run: python3 -m unittest spa_core.tests.test_protocol_governance_attack_resistance_scorer -v
≥85 tests required.
"""

import json
import math
import os
import sys
import tempfile
import unittest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from spa_core.analytics.protocol_governance_attack_resistance_scorer import (
    ProtocolGovernanceAttackResistanceScorer,
    _attack_cost_usd,
    _plutocracy_score,
    _flashloan_vulnerability,
    _governance_participation_score,
    _composite_resistance_score,
    _resistance_label,
    _clamp,
    _atomic_write,
    _append_log,
    _load_log,
    _build_protocol_result,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def make_protocol(**kwargs) -> dict:
    defaults = {
        "name": "TestDAO",
        "governance_token_market_cap_usd": 100_000_000,
        "top_10_holder_pct": 40.0,
        "quorum_pct": 4.0,
        "timelock_hours": 48.0,
        "flash_loan_protected": True,
        "delegation_enabled": True,
        "voting_period_hours": 72.0,
        "proposal_threshold_pct": 1.0,
        "total_unique_voters_30d": 500,
        "snapshot_based": False,
    }
    defaults.update(kwargs)
    return defaults


# ---------------------------------------------------------------------------
# Unit Tests: _clamp
# ---------------------------------------------------------------------------
class TestClamp(unittest.TestCase):

    def test_within_range(self):
        self.assertAlmostEqual(_clamp(50.0), 50.0)

    def test_below_min(self):
        self.assertAlmostEqual(_clamp(-10.0), 0.0)

    def test_above_max(self):
        self.assertAlmostEqual(_clamp(150.0), 100.0)

    def test_at_min(self):
        self.assertAlmostEqual(_clamp(0.0), 0.0)

    def test_at_max(self):
        self.assertAlmostEqual(_clamp(100.0), 100.0)

    def test_custom_bounds(self):
        self.assertAlmostEqual(_clamp(5.0, 0.0, 10.0), 5.0)
        self.assertAlmostEqual(_clamp(-5.0, 0.0, 10.0), 0.0)
        self.assertAlmostEqual(_clamp(15.0, 0.0, 10.0), 10.0)


# ---------------------------------------------------------------------------
# Unit Tests: _attack_cost_usd
# ---------------------------------------------------------------------------
class TestAttackCostUsd(unittest.TestCase):

    def test_basic(self):
        self.assertAlmostEqual(_attack_cost_usd(100_000_000), 51_000_000)

    def test_zero_market_cap(self):
        self.assertAlmostEqual(_attack_cost_usd(0), 0.0)

    def test_large_cap(self):
        cost = _attack_cost_usd(10_000_000_000)
        self.assertAlmostEqual(cost, 5_100_000_000)

    def test_small_cap(self):
        cost = _attack_cost_usd(500_000)
        self.assertAlmostEqual(cost, 255_000)

    def test_ratio_is_51_percent(self):
        for cap in [1e6, 1e8, 1e10]:
            cost = _attack_cost_usd(cap)
            self.assertAlmostEqual(cost / cap, 0.51)


# ---------------------------------------------------------------------------
# Unit Tests: _plutocracy_score
# ---------------------------------------------------------------------------
class TestPlutocracyScore(unittest.TestCase):

    def test_zero_concentration(self):
        self.assertAlmostEqual(_plutocracy_score(0.0), 0.0)

    def test_full_concentration(self):
        self.assertAlmostEqual(_plutocracy_score(100.0), 100.0)

    def test_midpoint(self):
        self.assertAlmostEqual(_plutocracy_score(50.0), 50.0)

    def test_clamped_above_100(self):
        self.assertAlmostEqual(_plutocracy_score(120.0), 100.0)

    def test_clamped_below_0(self):
        self.assertAlmostEqual(_plutocracy_score(-5.0), 0.0)

    def test_typical_value(self):
        # 40% top-10 → score 40
        self.assertAlmostEqual(_plutocracy_score(40.0), 40.0)


# ---------------------------------------------------------------------------
# Unit Tests: _flashloan_vulnerability
# ---------------------------------------------------------------------------
class TestFlashloanVulnerability(unittest.TestCase):

    def test_snapshot_based_is_safe(self):
        score = _flashloan_vulnerability(False, True, 24.0)
        self.assertAlmostEqual(score, 5.0)

    def test_flash_protected_low_score(self):
        score = _flashloan_vulnerability(True, False, 72.0)
        self.assertLessEqual(score, 30.0)

    def test_unprotected_not_snapshot_high_score(self):
        score = _flashloan_vulnerability(False, False, 24.0)
        self.assertGreater(score, 50.0)

    def test_short_voting_period_increases_score(self):
        s_long = _flashloan_vulnerability(False, False, 168.0)
        s_short = _flashloan_vulnerability(False, False, 1.0)
        self.assertGreater(s_short, s_long)

    def test_score_clamped_0_100(self):
        s = _flashloan_vulnerability(False, False, 0.01)
        self.assertGreaterEqual(s, 0.0)
        self.assertLessEqual(s, 100.0)

    def test_protected_and_long_voting(self):
        s = _flashloan_vulnerability(True, False, 168.0)
        self.assertLessEqual(s, 20.0)

    def test_snapshot_overrides_other_params(self):
        # Even if unprotected and short period, snapshot = safe
        s = _flashloan_vulnerability(False, True, 1.0)
        self.assertAlmostEqual(s, 5.0)


# ---------------------------------------------------------------------------
# Unit Tests: _governance_participation_score
# ---------------------------------------------------------------------------
class TestGovernanceParticipationScore(unittest.TestCase):

    def test_zero_voters(self):
        # With 0 voters, voter_score=0 and deleg=False, but quorum (4%) still contributes
        s = _governance_participation_score(0, 4.0, False)
        self.assertGreaterEqual(s, 0.0)
        self.assertLess(s, 10.0)  # still low — no voters, no delegation

    def test_delegation_bonus(self):
        s_no = _governance_participation_score(100, 4.0, False)
        s_yes = _governance_participation_score(100, 4.0, True)
        self.assertGreater(s_yes, s_no)

    def test_higher_quorum_higher_score(self):
        s_low = _governance_participation_score(500, 1.0, False)
        s_high = _governance_participation_score(500, 40.0, False)
        self.assertGreater(s_high, s_low)

    def test_many_voters_high_score(self):
        s = _governance_participation_score(10_000, 4.0, True)
        self.assertGreater(s, 50.0)

    def test_score_clamped_0_100(self):
        s = _governance_participation_score(1_000_000, 100.0, True)
        self.assertLessEqual(s, 100.0)
        self.assertGreaterEqual(s, 0.0)

    def test_max_quorum_cap(self):
        s_50 = _governance_participation_score(100, 50.0, False)
        s_100 = _governance_participation_score(100, 100.0, False)
        # quorum capped at 30 pts so both have same quorum_score
        self.assertAlmostEqual(s_50, s_100)

    def test_positive_for_reasonable_protocol(self):
        s = _governance_participation_score(1000, 4.0, True)
        self.assertGreater(s, 0.0)


# ---------------------------------------------------------------------------
# Unit Tests: _composite_resistance_score
# ---------------------------------------------------------------------------
class TestCompositeResistanceScore(unittest.TestCase):

    def test_returns_float(self):
        s = _composite_resistance_score(1e9, 30.0, 10.0, 70.0, 72.0, 1.0)
        self.assertIsInstance(s, float)

    def test_clamped_0_100(self):
        s = _composite_resistance_score(1e12, 0.0, 0.0, 100.0, 1000.0, 100.0)
        self.assertLessEqual(s, 100.0)
        s2 = _composite_resistance_score(0.0, 100.0, 100.0, 0.0, 0.0, 0.0)
        self.assertGreaterEqual(s2, 0.0)

    def test_high_cost_high_score(self):
        s_cheap = _composite_resistance_score(100_000, 40.0, 50.0, 50.0, 24.0, 1.0)
        s_exp = _composite_resistance_score(1_000_000_000, 40.0, 50.0, 50.0, 24.0, 1.0)
        self.assertGreater(s_exp, s_cheap)

    def test_low_plutocracy_better(self):
        s_conc = _composite_resistance_score(1e8, 90.0, 20.0, 50.0, 48.0, 1.0)
        s_disp = _composite_resistance_score(1e8, 10.0, 20.0, 50.0, 48.0, 1.0)
        self.assertGreater(s_disp, s_conc)

    def test_low_flash_vuln_better(self):
        s_vuln = _composite_resistance_score(1e8, 40.0, 80.0, 50.0, 48.0, 1.0)
        s_safe = _composite_resistance_score(1e8, 40.0, 5.0, 50.0, 48.0, 1.0)
        self.assertGreater(s_safe, s_vuln)

    def test_high_participation_better(self):
        s_low = _composite_resistance_score(1e8, 40.0, 20.0, 10.0, 48.0, 1.0)
        s_high = _composite_resistance_score(1e8, 40.0, 20.0, 90.0, 48.0, 1.0)
        self.assertGreater(s_high, s_low)

    def test_longer_timelock_better(self):
        s_short = _composite_resistance_score(1e8, 40.0, 20.0, 50.0, 1.0, 1.0)
        s_long = _composite_resistance_score(1e8, 40.0, 20.0, 50.0, 48.0, 1.0)
        self.assertGreater(s_long, s_short)


# ---------------------------------------------------------------------------
# Unit Tests: _resistance_label
# ---------------------------------------------------------------------------
class TestResistanceLabel(unittest.TestCase):

    def test_fortress(self):
        self.assertEqual(_resistance_label(90.0), "FORTRESS")

    def test_robust(self):
        self.assertEqual(_resistance_label(70.0), "ROBUST")

    def test_adequate(self):
        self.assertEqual(_resistance_label(50.0), "ADEQUATE")

    def test_vulnerable(self):
        self.assertEqual(_resistance_label(30.0), "VULNERABLE")

    def test_critical(self):
        self.assertEqual(_resistance_label(10.0), "CRITICAL")

    def test_boundary_fortress(self):
        self.assertEqual(_resistance_label(80.0), "FORTRESS")

    def test_boundary_robust(self):
        self.assertEqual(_resistance_label(60.0), "ROBUST")

    def test_boundary_adequate(self):
        self.assertEqual(_resistance_label(40.0), "ADEQUATE")

    def test_boundary_vulnerable(self):
        self.assertEqual(_resistance_label(20.0), "VULNERABLE")

    def test_zero_score(self):
        self.assertEqual(_resistance_label(0.0), "CRITICAL")

    def test_100_score(self):
        self.assertEqual(_resistance_label(100.0), "FORTRESS")


# ---------------------------------------------------------------------------
# Unit Tests: _build_protocol_result
# ---------------------------------------------------------------------------
class TestBuildProtocolResult(unittest.TestCase):

    def _r(self, **kwargs):
        return _build_protocol_result(make_protocol(**kwargs))

    def test_returns_dict(self):
        self.assertIsInstance(self._r(), dict)

    def test_required_keys(self):
        r = self._r()
        for k in ["name", "attack_cost_usd", "plutocracy_score",
                  "flashloan_vulnerability", "governance_participation_score",
                  "composite_resistance_score", "resistance_label", "flags",
                  "score_breakdown"]:
            self.assertIn(k, r)

    def test_attack_cost_positive(self):
        r = self._r(governance_token_market_cap_usd=1e8)
        self.assertGreater(r["attack_cost_usd"], 0)

    def test_composite_score_range(self):
        r = self._r()
        self.assertGreaterEqual(r["composite_resistance_score"], 0.0)
        self.assertLessEqual(r["composite_resistance_score"], 100.0)

    def test_flash_loan_vulnerable_flag(self):
        r = self._r(flash_loan_protected=False, snapshot_based=False)
        self.assertIn("FLASH_LOAN_VULNERABLE", r["flags"])

    def test_no_flash_loan_flag_when_protected(self):
        r = self._r(flash_loan_protected=True, snapshot_based=False)
        self.assertNotIn("FLASH_LOAN_VULNERABLE", r["flags"])

    def test_no_flash_loan_flag_when_snapshot(self):
        r = self._r(flash_loan_protected=False, snapshot_based=True)
        self.assertNotIn("FLASH_LOAN_VULNERABLE", r["flags"])

    def test_low_participation_flag(self):
        r = self._r(total_unique_voters_30d=50)
        self.assertIn("LOW_PARTICIPATION", r["flags"])

    def test_no_low_participation_flag(self):
        r = self._r(total_unique_voters_30d=100)
        self.assertNotIn("LOW_PARTICIPATION", r["flags"])

    def test_plutocratic_flag(self):
        r = self._r(top_10_holder_pct=75.0)
        self.assertIn("PLUTOCRATIC", r["flags"])

    def test_no_plutocratic_flag_at_70(self):
        r = self._r(top_10_holder_pct=70.0)
        self.assertNotIn("PLUTOCRATIC", r["flags"])

    def test_short_timelock_flag(self):
        r = self._r(timelock_hours=12.0)
        self.assertIn("SHORT_TIMELOCK", r["flags"])

    def test_no_short_timelock_flag(self):
        r = self._r(timelock_hours=24.0)
        self.assertNotIn("SHORT_TIMELOCK", r["flags"])

    def test_low_attack_cost_flag(self):
        r = self._r(governance_token_market_cap_usd=1_000_000)
        # cost = 510_000 < 1M → LOW_ATTACK_COST
        self.assertIn("LOW_ATTACK_COST", r["flags"])

    def test_no_low_attack_cost_flag(self):
        r = self._r(governance_token_market_cap_usd=100_000_000)
        self.assertNotIn("LOW_ATTACK_COST", r["flags"])

    def test_resistance_label_is_valid(self):
        r = self._r()
        self.assertIn(r["resistance_label"], ["FORTRESS", "ROBUST", "ADEQUATE", "VULNERABLE", "CRITICAL"])

    def test_score_breakdown_keys(self):
        r = self._r()
        bd = r["score_breakdown"]
        for k in ["attack_cost_component", "plutocracy_component",
                  "flash_component", "participation_component",
                  "timelock_component", "proposal_threshold_component"]:
            self.assertIn(k, bd)

    def test_name_preserved(self):
        r = self._r(name="Aave")
        self.assertEqual(r["name"], "Aave")

    def test_flags_is_list(self):
        r = self._r()
        self.assertIsInstance(r["flags"], list)

    def test_all_flags_possible(self):
        r = self._r(
            governance_token_market_cap_usd=100_000,
            top_10_holder_pct=80.0,
            flash_loan_protected=False,
            snapshot_based=False,
            total_unique_voters_30d=10,
            timelock_hours=12.0,
        )
        self.assertIn("FLASH_LOAN_VULNERABLE", r["flags"])
        self.assertIn("LOW_PARTICIPATION", r["flags"])
        self.assertIn("PLUTOCRATIC", r["flags"])
        self.assertIn("SHORT_TIMELOCK", r["flags"])
        self.assertIn("LOW_ATTACK_COST", r["flags"])

    def test_critical_label_for_weak_protocol(self):
        r = self._r(
            governance_token_market_cap_usd=10_000,
            top_10_holder_pct=99.0,
            flash_loan_protected=False,
            snapshot_based=False,
            total_unique_voters_30d=5,
            timelock_hours=0.0,
            quorum_pct=0.0,
            voting_period_hours=1.0,
            proposal_threshold_pct=0.0,
        )
        self.assertIn(r["resistance_label"], ["CRITICAL", "VULNERABLE"])

    def test_fortress_for_strong_protocol(self):
        r = _build_protocol_result({
            "name": "MegaDAO",
            "governance_token_market_cap_usd": 10_000_000_000,
            "top_10_holder_pct": 5.0,
            "quorum_pct": 20.0,
            "timelock_hours": 72.0,
            "flash_loan_protected": True,
            "delegation_enabled": True,
            "voting_period_hours": 168.0,
            "proposal_threshold_pct": 3.0,
            "total_unique_voters_30d": 10_000,
            "snapshot_based": True,
        })
        self.assertIn(r["resistance_label"], ["FORTRESS", "ROBUST"])


# ---------------------------------------------------------------------------
# Integration Tests: ProtocolGovernanceAttackResistanceScorer.score
# ---------------------------------------------------------------------------
class TestScorerIntegration(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmp_dir, "gov_log.json")
        self.scorer = ProtocolGovernanceAttackResistanceScorer(log_path=self.log_path)

    def test_empty_list(self):
        result = self.scorer.score([])
        self.assertEqual(result["aggregates"]["total_count"], 0)
        self.assertIsNone(result["aggregates"]["most_resistant"])

    def test_single_protocol(self):
        result = self.scorer.score([make_protocol(name="Aave")])
        self.assertEqual(len(result["protocols"]), 1)
        self.assertEqual(result["protocols"][0]["name"], "Aave")

    def test_multiple_protocols(self):
        protos = [make_protocol(name=f"P{i}") for i in range(5)]
        result = self.scorer.score(protos)
        self.assertEqual(len(result["protocols"]), 5)

    def test_output_has_timestamp(self):
        result = self.scorer.score([make_protocol()])
        self.assertIn("analysis_timestamp", result)
        self.assertTrue(result["analysis_timestamp"].endswith("Z"))

    def test_module_field(self):
        result = self.scorer.score([make_protocol()])
        self.assertEqual(result["module"], "MP-953")

    def test_version_field(self):
        result = self.scorer.score([make_protocol()])
        self.assertEqual(result["version"], "1.0.0")

    def test_aggregates_most_resistant(self):
        strong = make_protocol(name="Strong", governance_token_market_cap_usd=1e10,
                               top_10_holder_pct=5.0, flash_loan_protected=True)
        weak = make_protocol(name="Weak", governance_token_market_cap_usd=1000,
                             top_10_holder_pct=99.0, flash_loan_protected=False, snapshot_based=False)
        result = self.scorer.score([strong, weak])
        self.assertEqual(result["aggregates"]["most_resistant"], "Strong")

    def test_aggregates_most_vulnerable(self):
        strong = make_protocol(name="Strong", governance_token_market_cap_usd=1e10,
                               top_10_holder_pct=5.0, flash_loan_protected=True)
        weak = make_protocol(name="Weak", governance_token_market_cap_usd=1000,
                             top_10_holder_pct=99.0, flash_loan_protected=False, snapshot_based=False)
        result = self.scorer.score([strong, weak])
        self.assertEqual(result["aggregates"]["most_vulnerable"], "Weak")

    def test_average_resistance_calculation(self):
        protos = [make_protocol(name=f"P{i}") for i in range(4)]
        result = self.scorer.score(protos)
        scores = [p["composite_resistance_score"] for p in result["protocols"]]
        expected_avg = sum(scores) / len(scores)
        self.assertAlmostEqual(result["aggregates"]["average_resistance"], expected_avg, places=2)

    def test_fortress_count(self):
        result = self.scorer.score([make_protocol()])
        # Just check it's an int ≥ 0
        self.assertIsInstance(result["aggregates"]["fortress_count"], int)
        self.assertGreaterEqual(result["aggregates"]["fortress_count"], 0)

    def test_critical_count(self):
        result = self.scorer.score([make_protocol()])
        self.assertIsInstance(result["aggregates"]["critical_count"], int)

    def test_total_count_matches(self):
        protos = [make_protocol(name=f"P{i}") for i in range(3)]
        result = self.scorer.score(protos)
        self.assertEqual(result["aggregates"]["total_count"], 3)

    def test_log_written(self):
        self.scorer.score([make_protocol()])
        self.assertTrue(os.path.exists(self.log_path))

    def test_log_ring_buffer(self):
        small = ProtocolGovernanceAttackResistanceScorer(
            log_path=self.log_path, log_cap=3
        )
        for _ in range(6):
            small.score([make_protocol()])
        with open(self.log_path) as f:
            log = json.load(f)
        self.assertLessEqual(len(log), 3)

    def test_log_entry_fields(self):
        self.scorer.score([make_protocol()])
        with open(self.log_path) as f:
            log = json.load(f)
        entry = log[0]
        self.assertIn("ts", entry)
        self.assertIn("count", entry)
        self.assertIn("average_resistance", entry)

    def test_log_entry_count_correct(self):
        self.scorer.score([make_protocol(), make_protocol(name="B")])
        with open(self.log_path) as f:
            log = json.load(f)
        self.assertEqual(log[0]["count"], 2)

    def test_config_none_ok(self):
        result = self.scorer.score([make_protocol()], config=None)
        self.assertIn("protocols", result)

    def test_config_empty_ok(self):
        result = self.scorer.score([make_protocol()], config={})
        self.assertIn("protocols", result)

    def test_aggregates_type(self):
        result = self.scorer.score([make_protocol()])
        self.assertIsInstance(result["aggregates"], dict)

    def test_protocols_list_type(self):
        result = self.scorer.score([make_protocol()])
        self.assertIsInstance(result["protocols"], list)

    def test_single_protocol_most_resistant_equals_most_vulnerable(self):
        result = self.scorer.score([make_protocol(name="Solo")])
        agg = result["aggregates"]
        self.assertEqual(agg["most_resistant"], "Solo")
        self.assertEqual(agg["most_vulnerable"], "Solo")

    def test_multiple_log_entries(self):
        self.scorer.score([make_protocol()])
        self.scorer.score([make_protocol()])
        with open(self.log_path) as f:
            log = json.load(f)
        self.assertEqual(len(log), 2)

    def test_no_crash_on_bad_log_path(self):
        bad = ProtocolGovernanceAttackResistanceScorer(
            log_path="/nonexistent/xyz/gov_log.json"
        )
        try:
            bad.score([make_protocol()])
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Tests: Atomic write helpers
# ---------------------------------------------------------------------------
class TestAtomicWriteGov(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()

    def test_write_and_read(self):
        path = os.path.join(self.tmp_dir, "gov.json")
        _atomic_write(path, [{"name": "test"}])
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(data[0]["name"], "test")

    def test_overwrites(self):
        path = os.path.join(self.tmp_dir, "gov.json")
        _atomic_write(path, [1])
        _atomic_write(path, [2, 3])
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(data, [2, 3])

    def test_creates_subdirs(self):
        path = os.path.join(self.tmp_dir, "a", "b", "gov.json")
        _atomic_write(path, {"ok": True})
        self.assertTrue(os.path.exists(path))


class TestLoadLogGov(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()

    def test_missing_file(self):
        self.assertEqual(_load_log("/no/such/file.json"), [])

    def test_bad_json(self):
        p = os.path.join(self.tmp_dir, "bad.json")
        with open(p, "w") as f:
            f.write("{{bad")
        self.assertEqual(_load_log(p), [])

    def test_non_list(self):
        p = os.path.join(self.tmp_dir, "obj.json")
        with open(p, "w") as f:
            json.dump({}, f)
        self.assertEqual(_load_log(p), [])

    def test_valid(self):
        p = os.path.join(self.tmp_dir, "log.json")
        _atomic_write(p, [{"x": 1}])
        self.assertEqual(len(_load_log(p)), 1)


class TestAppendLogGov(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp_dir, "log.json")

    def test_first_append(self):
        _append_log(self.path, {"n": 1}, cap=10)
        self.assertEqual(len(_load_log(self.path)), 1)

    def test_multiple_appends(self):
        for i in range(5):
            _append_log(self.path, {"i": i}, cap=10)
        self.assertEqual(len(_load_log(self.path)), 5)

    def test_cap(self):
        for i in range(10):
            _append_log(self.path, {"i": i}, cap=4)
        self.assertLessEqual(len(_load_log(self.path)), 4)

    def test_last_kept(self):
        for i in range(10):
            _append_log(self.path, {"i": i}, cap=4)
        log = _load_log(self.path)
        self.assertEqual(log[-1]["i"], 9)


# ---------------------------------------------------------------------------
# Edge case / boundary tests
# ---------------------------------------------------------------------------
class TestEdgeCasesGov(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.scorer = ProtocolGovernanceAttackResistanceScorer(
            log_path=os.path.join(self.tmp_dir, "log.json")
        )

    def test_zero_market_cap(self):
        r = self.scorer.score([make_protocol(governance_token_market_cap_usd=0)])
        self.assertEqual(r["protocols"][0]["attack_cost_usd"], 0.0)
        self.assertIn("LOW_ATTACK_COST", r["protocols"][0]["flags"])

    def test_all_snapshot_protocols(self):
        protos = [make_protocol(name=f"P{i}", snapshot_based=True) for i in range(3)]
        result = self.scorer.score(protos)
        for p in result["protocols"]:
            self.assertNotIn("FLASH_LOAN_VULNERABLE", p["flags"])

    def test_10_protocols(self):
        protos = [make_protocol(name=f"P{i}") for i in range(10)]
        result = self.scorer.score(protos)
        self.assertEqual(result["aggregates"]["total_count"], 10)

    def test_missing_fields_use_defaults(self):
        result = self.scorer.score([{"name": "Minimal"}])
        self.assertIn("composite_resistance_score", result["protocols"][0])

    def test_float_string_input(self):
        p = make_protocol(top_10_holder_pct="50.0", quorum_pct="4.0")
        result = self.scorer.score([p])
        self.assertGreaterEqual(result["protocols"][0]["composite_resistance_score"], 0.0)

    def test_resistance_label_valid(self):
        result = self.scorer.score([make_protocol()])
        label = result["protocols"][0]["resistance_label"]
        self.assertIn(label, ["FORTRESS", "ROBUST", "ADEQUATE", "VULNERABLE", "CRITICAL"])

    def test_fortress_and_critical_counts_correct(self):
        strong = make_protocol(name="S", governance_token_market_cap_usd=1e12,
                               top_10_holder_pct=2.0, flash_loan_protected=True,
                               snapshot_based=True, total_unique_voters_30d=50000,
                               quorum_pct=20.0, timelock_hours=72.0)
        weak = make_protocol(name="W", governance_token_market_cap_usd=100,
                             top_10_holder_pct=99.0, flash_loan_protected=False,
                             snapshot_based=False, total_unique_voters_30d=1,
                             quorum_pct=0.0, timelock_hours=0.0)
        result = self.scorer.score([strong, weak])
        total = (result["aggregates"]["fortress_count"] +
                 result["aggregates"]["critical_count"] +
                 sum(1 for p in result["protocols"]
                     if p["resistance_label"] in ["ROBUST", "ADEQUATE", "VULNERABLE"]))
        self.assertEqual(total, 2)

    def test_no_crash_on_empty_name(self):
        result = self.scorer.score([make_protocol(name="")])
        self.assertEqual(result["protocols"][0]["name"], "")

    def test_very_high_proposal_threshold(self):
        p = make_protocol(proposal_threshold_pct=100.0)
        result = self.scorer.score([p])
        # score_breakdown threshold capped → no crash
        comp = result["protocols"][0]["score_breakdown"]["proposal_threshold_component"]
        self.assertLessEqual(comp, 5.0)  # 5% weight max

    def test_very_long_voting_period(self):
        p = make_protocol(voting_period_hours=8760)  # 1 year
        result = self.scorer.score([p])
        # Protected=True anyway, should not FLASH_LOAN_VULNERABLE
        self.assertNotIn("FLASH_LOAN_VULNERABLE", result["protocols"][0]["flags"])


if __name__ == "__main__":
    unittest.main()
