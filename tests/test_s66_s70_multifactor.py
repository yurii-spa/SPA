"""
tests/test_s66_s70_multifactor.py — S66–S70 multi-factor strategies (42 tests)

Covers the five session-synthesis strategies:
  S66 Real Data Optimal       — static optimizer book + weekly drift check
  S67 Anti-Bear               — inverse of S31's regime signal
  S68 Temporal Diversification — four horizon-laddered sleeves
  S69 Governance-Informed     — proposal-tilted equal weight + fallback
  S70 Session Best            — hand-curated low-vol book

Each strategy: identity, weight math, caps/policy compliance, expected APY,
allocation scaling, and registry registration.
"""
import unittest

from spa_core.strategies.s66_real_data_optimal import (
    S66RealDataOptimal, TARGET_WEIGHTS as S66_TARGET, DRIFT_THRESHOLD)
from spa_core.strategies.s67_anti_bear import (
    S67AntiBear, ANTI_BULL_WEIGHTS, ANTI_BEAR_WEIGHTS, CASH_KEY as S67_CASH, _invert)
from spa_core.strategies.s68_temporal_diversification import (
    S68TemporalDiversification, SUB_WEIGHT, T1_VENUES, T2_TOTAL_CAP as S68_T2CAP,
    PER_PROTOCOL_CAP as S68_CAP, PROTOCOL_TIERS as S68_TIERS, CASH_KEY as S68_CASH)
from spa_core.strategies.s69_governance_informed import (
    S69GovernanceInformed, PROTOCOLS as S69_PROTOCOLS, PROTOCOL_TIERS as S69_TIERS,
    CASH_KEY as S69_CASH)
from spa_core.strategies.s70_session_best import (
    S70SessionBest, TARGET_WEIGHTS as S70_TARGET, PROTOCOL_TIERS as S70_TIERS,
    CASH_KEY as S70_CASH)
from spa_core.strategies.strategy_registry import REGISTRY


def _wsum(weights):
    return round(sum(weights.values()), 6)


# ─────────────────────────── S66 Real Data Optimal ───────────────────────────

class TestS66RealDataOptimal(unittest.TestCase):
    def setUp(self):
        self.s = S66RealDataOptimal()

    def test_id(self):
        self.assertEqual(self.s.simulate(100_000.0)["strategy_id"], "S66")

    def test_target_weights_match_optimizer(self):
        self.assertEqual(S66_TARGET, {"aave_v3": 0.30, "sky_susds": 0.30,
                                      "compound_v3": 0.20, "morpho_blue": 0.20})

    def test_weights_sum_to_one(self):
        self.assertAlmostEqual(_wsum(self.s.compute_weights()), 1.0, places=6)

    def test_expected_apy_about_4_48(self):
        self.assertAlmostEqual(self.s.get_expected_apy(), 4.48, places=1)

    def test_no_rebalance_at_target(self):
        self.assertFalse(self.s.needs_rebalance(dict(S66_TARGET)))

    def test_rebalance_when_drift_exceeds_threshold(self):
        drifted = {"aave_v3": 0.40, "sky_susds": 0.25, "compound_v3": 0.20, "morpho_blue": 0.15}
        self.assertTrue(self.s.needs_rebalance(drifted))  # aave drift 0.10 > 0.05

    def test_no_rebalance_within_band(self):
        within = {"aave_v3": 0.33, "sky_susds": 0.28, "compound_v3": 0.21, "morpho_blue": 0.18}
        self.assertFalse(self.s.needs_rebalance(within))  # max drift 0.03 ≤ 0.05

    def test_drift_threshold_is_5pp(self):
        self.assertEqual(DRIFT_THRESHOLD, 0.05)

    def test_allocation_scales_with_capital(self):
        alloc = self.s.get_allocation(100_000.0)
        self.assertAlmostEqual(alloc["aave_v3"], 30_000.0, places=2)

    def test_zero_capital_empty_allocation(self):
        self.assertEqual(self.s.get_allocation(0.0), {})

    def test_t2_within_cap(self):
        rs = self.s.get_risk_summary()
        self.assertLessEqual(rs["t2_weight_pct"], 50.0)


# ──────────────────────────────── S67 Anti-Bear ──────────────────────────────

class TestS67AntiBear(unittest.TestCase):
    def setUp(self):
        self.s = S67AntiBear()

    def test_id(self):
        self.assertEqual(self.s.simulate(100_000.0)["strategy_id"], "S67")

    def test_invert_helper(self):
        self.assertEqual(_invert("bear"), "bull")
        self.assertEqual(_invert("bull"), "bear")

    def test_bull_posture_is_50pct_t2(self):
        w = self.s.compute_weights(regime="bull")
        t2 = sum(v for k, v in w.items()
                 if k in ("morpho_blue", "yearn_v3", "fluid"))
        self.assertAlmostEqual(t2, 0.50, places=6)

    def test_bear_posture_all_t1(self):
        w = self.s.compute_weights(regime="bear")
        t2 = sum(v for k, v in w.items() if k in ("morpho_blue", "yearn_v3", "fluid"))
        self.assertAlmostEqual(t2, 0.0, places=6)

    def test_both_books_sum_to_one(self):
        self.assertAlmostEqual(_wsum(ANTI_BULL_WEIGHTS), 1.0, places=6)
        self.assertAlmostEqual(_wsum(ANTI_BEAR_WEIGHTS), 1.0, places=6)

    def test_inverts_underlying_bear_to_bull(self):
        # aave_utilization < 0.50 trips S31 bear → S60 posture = bull
        signals = {"aave_utilization": 0.30}
        self.assertEqual(self.s.underlying_regime(signals), "bear")
        self.assertEqual(self.s.detect_regime(signals), "bull")

    def test_inverts_underlying_bull_to_bear(self):
        # no bear signals → S31 bull → S60 posture = bear
        self.assertEqual(self.s.underlying_regime(None), "bull")
        self.assertEqual(self.s.detect_regime(None), "bear")

    def test_bull_apy_exceeds_bear_apy(self):
        bull = self.s.get_expected_apy(regime="bull")
        bear = self.s.get_expected_apy(regime="bear")
        self.assertGreater(bull, bear)

    def test_cash_buffer_present(self):
        self.assertAlmostEqual(ANTI_BULL_WEIGHTS[S67_CASH], 0.05, places=6)
        self.assertAlmostEqual(ANTI_BEAR_WEIGHTS[S67_CASH], 0.05, places=6)

    def test_simulate_reports_underlying_and_posture(self):
        sim = self.s.simulate(100_000.0, regime="bull")
        self.assertEqual(sim["anti_bear_posture"], "bull")
        self.assertEqual(sim["underlying_regime"], "bear")


# ────────────────────────── S68 Temporal Diversification ─────────────────────

class TestS68Temporal(unittest.TestCase):
    def setUp(self):
        self.s = S68TemporalDiversification()

    def test_id(self):
        self.assertEqual(self.s.simulate(100_000.0)["strategy_id"], "S68")

    def test_four_sleeves(self):
        subs = self.s.sub_allocations()
        self.assertEqual(len(subs), 4)

    def test_each_sleeve_sums_to_quarter(self):
        for name, sleeve in self.s.sub_allocations().items():
            self.assertAlmostEqual(sum(sleeve.values()), SUB_WEIGHT, places=6, msg=name)

    def test_sub_a_is_sky_lock(self):
        self.assertEqual(self.s.sub_allocations()["sub_a_lock30"], {"sky_susds": 0.25})

    def test_sub_b_is_t1_equal_weight(self):
        sub_b = self.s.sub_allocations()["sub_b_t1_7d"]
        self.assertEqual(set(sub_b), set(T1_VENUES))
        vals = list(sub_b.values())
        self.assertTrue(all(abs(v - vals[0]) < 1e-9 for v in vals))

    def test_sub_c_picks_best_current_apy(self):
        cur = {"aave_v3": 9.9, "compound_v3": 3.0, "sky_susds": 4.2,
               "morpho_blue": 6.0, "yearn_v3": 5.0, "fluid": 6.0}
        sub_c = self.s.sub_allocations(cur)["sub_c_spot_1d"]
        self.assertEqual(list(sub_c.keys()), ["aave_v3"])

    def test_per_protocol_cap_enforced(self):
        w = self.s.compute_weights()
        for p, v in w.items():
            if p == S68_CASH:
                continue
            cap = S68_CAP[S68_TIERS[p]]
            self.assertLessEqual(v, cap + 1e-9, msg=p)

    def test_t2_total_cap_enforced(self):
        w = self.s.compute_weights()
        t2 = sum(v for p, v in w.items() if S68_TIERS.get(p) == "T2")
        self.assertLessEqual(t2, S68_T2CAP + 1e-9)

    def test_weights_sum_to_one(self):
        self.assertAlmostEqual(_wsum(self.s.compute_weights()), 1.0, places=5)

    def test_expected_apy_near_4_5(self):
        self.assertTrue(4.0 <= self.s.get_expected_apy() <= 5.2)


# ─────────────────────────── S69 Governance-Informed ─────────────────────────

class TestS69Governance(unittest.TestCase):
    def setUp(self):
        self.s = S69GovernanceInformed()

    def test_id(self):
        self.assertEqual(self.s.simulate(100_000.0, proposals=[])["strategy_id"], "S69")

    def test_empty_proposals_equal_weight_fallback(self):
        w = self.s.compute_weights(proposals=[])
        for p in S69_PROTOCOLS:
            self.assertAlmostEqual(w[p], 0.20, places=6)

    def test_fallback_flag_set_when_no_signal(self):
        sim = self.s.simulate(100_000.0, proposals=[])
        self.assertTrue(sim["used_fallback"])

    def test_classify_increase(self):
        self.assertEqual(self.s._classify(
            {"title": "Add incentives and raise borrow cap", "category": "parameter_change"}), 1)

    def test_classify_decrease(self):
        self.assertEqual(self.s._classify(
            {"title": "Emergency pause of USDC market", "category": "emergency"}), -1)

    def test_classify_neutral_when_both(self):
        self.assertEqual(self.s._classify(
            {"title": "Increase fee then pause rewards", "category": ""}), 0)

    def test_signal_maps_slug_and_direction(self):
        props = [{"protocol": "aave", "title": "incentive boost", "state": "active"},
                 {"protocol": "compound", "title": "emergency freeze", "state": "active"}]
        sig = self.s.governance_signal(props)
        self.assertEqual(sig.get("aave_v3"), 1)
        self.assertEqual(sig.get("compound_v3"), -1)

    def test_tilt_overweights_positive_underweights_negative(self):
        props = [{"protocol": "aave", "title": "incentive boost", "state": "active"},
                 {"protocol": "compound", "title": "emergency freeze", "state": "active"}]
        w = self.s.compute_weights(props)
        self.assertGreater(w["aave_v3"], w["compound_v3"])

    def test_inactive_proposal_ignored(self):
        props = [{"protocol": "aave", "title": "incentive boost", "state": "closed"}]
        self.assertEqual(self.s.governance_signal(props), {})

    def test_caps_enforced_under_tilt(self):
        props = [{"protocol": "morpho", "title": "incentive boost", "state": "active"}]
        w = self.s.compute_weights(props)
        self.assertLessEqual(w.get("morpho_blue", 0.0), 0.20 + 1e-9)

    def test_weights_sum_to_one(self):
        self.assertAlmostEqual(_wsum(self.s.compute_weights(proposals=[])), 1.0, places=6)


# ──────────────────────────────── S70 Session Best ───────────────────────────

class TestS70SessionBest(unittest.TestCase):
    def setUp(self):
        self.s = S70SessionBest()

    def test_id(self):
        self.assertEqual(self.s.simulate(100_000.0)["strategy_id"], "S70")

    def test_curated_weights(self):
        self.assertEqual(S70_TARGET, {"sky_susds": 0.30, "morpho_blue": 0.20,
                                      "aave_v3": 0.20, "compound_v3": 0.15,
                                      "fluid": 0.10, "cash": 0.05})

    def test_expected_apy_about_4_55(self):
        self.assertAlmostEqual(self.s.get_expected_apy(), 4.55, places=1)

    def test_policy_check_all_pass(self):
        pc = self.s.policy_check()
        self.assertTrue(pc["t2_cap_ok"])
        self.assertTrue(pc["per_protocol_ok"])
        self.assertTrue(pc["cash_buffer_ok"])
        self.assertTrue(pc["sums_to_one"])

    def test_t2_total_is_30pct(self):
        w = self.s.compute_weights()
        t2 = sum(v for p, v in w.items() if S70_TIERS.get(p) == "T2")
        self.assertAlmostEqual(t2, 0.30, places=6)

    def test_cash_buffer_5pct(self):
        self.assertAlmostEqual(self.s.compute_weights()[S70_CASH], 0.05, places=6)

    def test_weights_sum_to_one(self):
        self.assertAlmostEqual(_wsum(self.s.compute_weights()), 1.0, places=6)

    def test_zero_capital_empty_allocation(self):
        self.assertEqual(self.s.get_allocation(0.0), {})


# ─────────────────────────────── Registry wiring ─────────────────────────────

class TestRegistration(unittest.TestCase):
    def test_all_five_registered(self):
        for sid in ("S66", "S67", "S68", "S69", "S70"):
            self.assertIsNotNone(REGISTRY.get(sid), msg=sid)

    def test_handler_classes(self):
        expected = {
            "S66": "S66RealDataOptimal",
            "S67": "S67AntiBear",
            "S68": "S68TemporalDiversification",
            "S69": "S69GovernanceInformed",
            "S70": "S70SessionBest",
        }
        for sid, cls in expected.items():
            self.assertEqual(REGISTRY.get(sid).handler_class, cls, msg=sid)

    def test_valid_tiers(self):
        for sid in ("S66", "S67", "S68", "S69", "S70"):
            self.assertIn(REGISTRY.get(sid).risk_tier, ("T1", "T2", "T3"), msg=sid)


if __name__ == "__main__":
    unittest.main(verbosity=2)
