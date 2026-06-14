"""
Tests for MP-1014 DeFiProtocolAdminKeyControlRiskAnalyzer.
Run: python3 -m unittest spa_core.tests.test_defi_protocol_admin_key_control_risk_analyzer -v
"""

import json
import os
import sys
import tempfile
import unittest

_REPO = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from spa_core.analytics.defi_protocol_admin_key_control_risk_analyzer import (
    DeFiProtocolAdminKeyControlRiskAnalyzer,
    _validate_protocol,
    _multisig_strength_score,
    _timelock_score,
    _control_surface_score,
    _admin_control_risk_score,
    _classify,
    _grade,
    _compute_flags,
    _analyze_one,
    _atomic_write,
    _init_log,
    _append_log,
    _iso_now,
    analyze,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_protocol(name="Proto", multisig_threshold=4, multisig_signers=7,
                   timelock_hours=48.0, upgradeable=False, pausable=False,
                   has_guardian=False, admin_controlled_tvl_pct=10.0,
                   signer_independence_pct=80.0, audited=True):
    return {
        "name": name,
        "multisig_threshold": multisig_threshold,
        "multisig_signers": multisig_signers,
        "timelock_hours": timelock_hours,
        "upgradeable": upgradeable,
        "pausable": pausable,
        "has_guardian": has_guardian,
        "admin_controlled_tvl_pct": admin_controlled_tvl_pct,
        "signer_independence_pct": signer_independence_pct,
        "audited": audited,
    }


def _decentralized_protocol():
    return _make_protocol(
        name="Decentralized", multisig_threshold=5, multisig_signers=9,
        timelock_hours=72.0, upgradeable=False, pausable=False,
        has_guardian=False, admin_controlled_tvl_pct=5.0,
        signer_independence_pct=90.0,
    )


def _critical_protocol():
    return _make_protocol(
        name="Critical", multisig_threshold=1, multisig_signers=1,
        timelock_hours=0.0, upgradeable=True, pausable=True,
        has_guardian=True, admin_controlled_tvl_pct=100.0,
        signer_independence_pct=0.0, audited=False,
    )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class TestValidation(unittest.TestCase):
    def test_valid_passes(self):
        _validate_protocol(_make_protocol(), 0)

    def test_missing_field_raises(self):
        p = _make_protocol()
        del p["timelock_hours"]
        with self.assertRaises(ValueError):
            _validate_protocol(p, 0)

    def test_threshold_gt_signers_raises(self):
        with self.assertRaises(ValueError):
            _validate_protocol(_make_protocol(multisig_threshold=5, multisig_signers=3), 0)

    def test_zero_signers_raises(self):
        with self.assertRaises(ValueError):
            _validate_protocol(_make_protocol(multisig_threshold=0, multisig_signers=0), 0)

    def test_negative_timelock_raises(self):
        with self.assertRaises(ValueError):
            _validate_protocol(_make_protocol(timelock_hours=-1), 0)

    def test_non_int_multisig_raises(self):
        with self.assertRaises(ValueError):
            _validate_protocol(_make_protocol(multisig_threshold=2.5), 0)

    def test_empty_list_raises(self):
        with self.assertRaises(ValueError):
            DeFiProtocolAdminKeyControlRiskAnalyzer().analyze([])

    def test_non_list_raises(self):
        with self.assertRaises(ValueError):
            DeFiProtocolAdminKeyControlRiskAnalyzer().analyze("nope")


# ---------------------------------------------------------------------------
# Multisig strength
# ---------------------------------------------------------------------------

class TestMultisigStrength(unittest.TestCase):
    def test_single_key_is_zero(self):
        self.assertEqual(_multisig_strength_score(1, 1, 100.0), 0.0)

    def test_strong_multisig_high(self):
        s = _multisig_strength_score(5, 9, 90.0)
        self.assertGreater(s, 80.0)

    def test_independence_reduces_score(self):
        high = _multisig_strength_score(4, 7, 100.0)
        low = _multisig_strength_score(4, 7, 0.0)
        self.assertGreater(high, low)

    def test_zero_independence_not_negative(self):
        self.assertGreaterEqual(_multisig_strength_score(4, 7, 0.0), 0.0)

    def test_more_signers_better(self):
        small = _multisig_strength_score(2, 3, 80.0)
        big = _multisig_strength_score(2, 9, 80.0)
        self.assertGreater(big, small)

    def test_bounded_100(self):
        self.assertLessEqual(_multisig_strength_score(9, 9, 100.0), 100.0)

    def test_independence_above_100_clamped(self):
        a = _multisig_strength_score(4, 7, 150.0)
        b = _multisig_strength_score(4, 7, 100.0)
        self.assertEqual(a, b)


# ---------------------------------------------------------------------------
# Timelock
# ---------------------------------------------------------------------------

class TestTimelock(unittest.TestCase):
    def test_zero_timelock_zero(self):
        self.assertEqual(_timelock_score(0.0), 0.0)

    def test_24h_moderate(self):
        self.assertAlmostEqual(_timelock_score(24.0), 60.0, places=1)

    def test_48h_strong(self):
        self.assertAlmostEqual(_timelock_score(48.0), 90.0, places=1)

    def test_week_near_max(self):
        self.assertGreaterEqual(_timelock_score(168.0), 99.0)

    def test_monotonic(self):
        vals = [_timelock_score(h) for h in [0, 6, 12, 24, 48, 96, 168]]
        self.assertEqual(vals, sorted(vals))

    def test_bounded_100(self):
        self.assertLessEqual(_timelock_score(10000.0), 100.0)

    def test_negative_clamped(self):
        self.assertEqual(_timelock_score(-5.0), 0.0)


# ---------------------------------------------------------------------------
# Control surface
# ---------------------------------------------------------------------------

class TestControlSurface(unittest.TestCase):
    def test_no_powers_low_tvl(self):
        self.assertLess(_control_surface_score(False, False, False, 0.0), 1.0)

    def test_all_powers_full_tvl_high(self):
        self.assertGreaterEqual(
            _control_surface_score(True, True, True, 100.0), 99.0
        )

    def test_upgradeable_adds_most(self):
        up = _control_surface_score(True, False, False, 0.0)
        pause = _control_surface_score(False, True, False, 0.0)
        self.assertGreater(up, pause)

    def test_tvl_monotonic(self):
        a = _control_surface_score(False, False, False, 20.0)
        b = _control_surface_score(False, False, False, 80.0)
        self.assertGreater(b, a)

    def test_bounded_100(self):
        self.assertLessEqual(
            _control_surface_score(True, True, True, 100.0), 100.0
        )


# ---------------------------------------------------------------------------
# Composite risk / classify / grade
# ---------------------------------------------------------------------------

class TestRiskScore(unittest.TestCase):
    def test_strong_protocol_low_risk(self):
        risk = _admin_control_risk_score(90.0, 90.0, 5.0)
        self.assertLess(risk, 25.0)

    def test_weak_protocol_high_risk(self):
        risk = _admin_control_risk_score(0.0, 0.0, 100.0)
        self.assertGreater(risk, 90.0)

    def test_bounded(self):
        self.assertLessEqual(_admin_control_risk_score(0, 0, 100), 100.0)
        self.assertGreaterEqual(_admin_control_risk_score(100, 100, 0), 0.0)

    def test_classify_thresholds(self):
        self.assertEqual(_classify(85.0), "CRITICAL_CENTRALIZATION")
        self.assertEqual(_classify(65.0), "HIGHLY_CENTRALIZED")
        self.assertEqual(_classify(45.0), "SEMI_CENTRALIZED")
        self.assertEqual(_classify(25.0), "MOSTLY_DECENTRALIZED")
        self.assertEqual(_classify(5.0), "FULLY_DECENTRALIZED")

    def test_grade_scale(self):
        self.assertEqual(_grade(10.0), "A")
        self.assertEqual(_grade(30.0), "B")
        self.assertEqual(_grade(50.0), "C")
        self.assertEqual(_grade(70.0), "D")
        self.assertEqual(_grade(90.0), "F")


# ---------------------------------------------------------------------------
# Flags
# ---------------------------------------------------------------------------

class TestFlags(unittest.TestCase):
    def test_critical_flags(self):
        p = _critical_protocol()
        flags = _compute_flags(p, 0.0, 0.0)
        for expected in ("INSTANT_ADMIN_ACTIONS", "SINGLE_KEY_CONTROL",
                         "UPGRADEABLE_NO_TIMELOCK", "PAUSABLE_FUNDS",
                         "SINGLE_GUARDIAN", "LOW_SIGNER_INDEPENDENCE",
                         "ADMIN_CONTROLS_MAJORITY_TVL", "UNAUDITED"):
            self.assertIn(expected, flags)

    def test_decentralized_flags(self):
        p = _decentralized_protocol()
        flags = _compute_flags(p, 95.0, 95.0)
        self.assertIn("STRONG_TIMELOCK", flags)
        self.assertIn("WELL_DISTRIBUTED_MULTISIG", flags)
        self.assertNotIn("INSTANT_ADMIN_ACTIONS", flags)
        self.assertNotIn("SINGLE_KEY_CONTROL", flags)

    def test_audited_default_no_unaudited(self):
        p = _make_protocol()  # audited=True
        self.assertNotIn("UNAUDITED", _compute_flags(p, 50.0, 50.0))


# ---------------------------------------------------------------------------
# analyze_one + full analyze
# ---------------------------------------------------------------------------

class TestAnalyzeOne(unittest.TestCase):
    def test_keys_present(self):
        r = _analyze_one(_make_protocol())
        for k in ("name", "multisig", "multisig_strength_score", "timelock_score",
                  "control_surface_score", "admin_control_risk_score",
                  "decentralization_grade", "classification", "flags"):
            self.assertIn(k, r)

    def test_multisig_string(self):
        r = _analyze_one(_make_protocol(multisig_threshold=3, multisig_signers=5))
        self.assertEqual(r["multisig"], "3-of-5")

    def test_critical_is_critical(self):
        r = _analyze_one(_critical_protocol())
        self.assertEqual(r["classification"], "CRITICAL_CENTRALIZATION")
        self.assertEqual(r["decentralization_grade"], "F")

    def test_decentralized_is_low_risk(self):
        r = _analyze_one(_decentralized_protocol())
        self.assertLess(r["admin_control_risk_score"], 30.0)
        self.assertIn(r["classification"],
                      ("FULLY_DECENTRALIZED", "MOSTLY_DECENTRALIZED"))


class TestAnalyze(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.log = os.path.join(self.tmp, "admin_log.json")

    def test_aggregates(self):
        out = analyze([_decentralized_protocol(), _critical_protocol()])
        self.assertEqual(out["safest_protocol"], "Decentralized")
        self.assertEqual(out["riskiest_protocol"], "Critical")
        self.assertEqual(out["critical_count"], 1)
        self.assertGreaterEqual(out["decentralized_count"], 1)
        self.assertIn("analyzed_at", out)

    def test_avg_in_range(self):
        out = analyze([_make_protocol(), _make_protocol(name="P2")])
        self.assertGreaterEqual(out["avg_admin_control_risk"], 0.0)
        self.assertLessEqual(out["avg_admin_control_risk"], 100.0)

    def test_single_protocol(self):
        out = analyze([_make_protocol()])
        self.assertEqual(len(out["protocols"]), 1)
        self.assertEqual(out["safest_protocol"], out["riskiest_protocol"])


# ---------------------------------------------------------------------------
# Log helpers
# ---------------------------------------------------------------------------

class TestLog(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.log = os.path.join(self.tmp, "sub", "log.json")

    def test_atomic_write_read(self):
        _atomic_write(self.log, [{"a": 1}])
        self.assertEqual(_init_log(self.log), [{"a": 1}])

    def test_init_missing_returns_empty(self):
        self.assertEqual(_init_log(os.path.join(self.tmp, "nope.json")), [])

    def test_init_corrupt_returns_empty(self):
        path = os.path.join(self.tmp, "bad.json")
        with open(path, "w") as f:
            f.write("{not json")
        self.assertEqual(_init_log(path), [])

    def test_append_caps_at_100(self):
        for i in range(130):
            _append_log({"analyzed_at": _iso_now(), "protocols": [{}]}, log_path=self.log)
        with open(self.log) as f:
            self.assertEqual(len(json.load(f)), 100)

    def test_append_snapshot_shape(self):
        _append_log(
            {"analyzed_at": "T", "protocols": [{}, {}],
             "avg_admin_control_risk": 50.0, "critical_count": 1,
             "decentralized_count": 0, "safest_protocol": "A",
             "riskiest_protocol": "B"},
            log_path=self.log,
        )
        snap = _init_log(self.log)[-1]
        self.assertEqual(snap["protocol_count"], 2)
        self.assertEqual(snap["safest_protocol"], "A")

    def test_iso_now_format(self):
        s = _iso_now()
        self.assertRegex(s, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


if __name__ == "__main__":
    unittest.main()
