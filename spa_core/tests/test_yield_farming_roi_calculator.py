"""
Tests for MP-869: YieldFarmingROICalculator
Run: python3 -m unittest spa_core.tests.test_yield_farming_roi_calculator -v

≥ 65 tests covering:
- _reward_token_impact() all 4 cases + boundaries
- _roi_label() all 5 cases + boundaries
- _build_recommendation() all 5 cases
- _analyze_farm() field values and math
- analyze() full pipeline: empty, single, multi-farm
- Edge cases: principal=0, holding_days=0
- Portfolio summary math
- Log file ring-buffer behaviour
- best_farm / worst_farm selection
- profitable_farms list
"""
from __future__ import annotations

import json
import sys
import time
import unittest
from pathlib import Path

# Ensure project root on sys.path
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import tempfile
from spa_core.analytics.yield_farming_roi_calculator import (
    MAX_ENTRIES,
    _analyze_farm,
    _append_log,
    _build_recommendation,
    _reward_token_impact,
    _roi_label,
    analyze,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _farm(**overrides) -> dict:
    """Return a baseline farm dict with optional overrides."""
    base = {
        "protocol": "TestProtocol",
        "principal_usd": 10_000.0,
        "entry_cost_usd": 50.0,
        "exit_cost_usd": 50.0,
        "holding_days": 30,
        "base_apy_pct": 10.0,
        "reward_token_apy_pct": 5.0,
        "reward_token_price_change_pct": 0.0,
        "principal_price_change_pct": 0.0,
        "impermanent_loss_pct": 0.0,
    }
    base.update(overrides)
    return base


def _tmp_log(td: str) -> Path:
    return Path(td) / "test_roi_log.json"


# ===========================================================================
# _reward_token_impact
# ===========================================================================

class TestRewardTokenImpact(unittest.TestCase):

    def test_exactly_20_is_boosted(self):
        self.assertEqual(_reward_token_impact(20.0), "BOOSTED")

    def test_above_20_is_boosted(self):
        self.assertEqual(_reward_token_impact(100.0), "BOOSTED")

    def test_just_below_20_is_neutral(self):
        self.assertEqual(_reward_token_impact(19.9), "NEUTRAL")

    def test_zero_is_neutral(self):
        self.assertEqual(_reward_token_impact(0.0), "NEUTRAL")

    def test_exactly_minus10_is_neutral(self):
        self.assertEqual(_reward_token_impact(-10.0), "NEUTRAL")

    def test_just_below_minus10_is_diluted(self):
        self.assertEqual(_reward_token_impact(-10.1), "DILUTED")

    def test_minus_30_is_diluted(self):
        self.assertEqual(_reward_token_impact(-30.0), "DILUTED")

    def test_exactly_minus50_is_diluted(self):
        self.assertEqual(_reward_token_impact(-50.0), "DILUTED")

    def test_just_below_minus50_is_destroyed(self):
        self.assertEqual(_reward_token_impact(-50.1), "DESTROYED")

    def test_minus100_is_destroyed(self):
        self.assertEqual(_reward_token_impact(-100.0), "DESTROYED")

    def test_large_positive_is_boosted(self):
        self.assertEqual(_reward_token_impact(999.0), "BOOSTED")


# ===========================================================================
# _roi_label
# ===========================================================================

class TestROILabel(unittest.TestCase):

    def test_exactly_30_is_exceptional(self):
        self.assertEqual(_roi_label(30.0), "EXCEPTIONAL")

    def test_above_30_is_exceptional(self):
        self.assertEqual(_roi_label(100.0), "EXCEPTIONAL")

    def test_exactly_15_is_strong(self):
        self.assertEqual(_roi_label(15.0), "STRONG")

    def test_just_below_30_is_strong(self):
        self.assertEqual(_roi_label(29.9), "STRONG")

    def test_exactly_0_is_positive(self):
        self.assertEqual(_roi_label(0.0), "POSITIVE")

    def test_just_below_15_is_positive(self):
        self.assertEqual(_roi_label(14.9), "POSITIVE")

    def test_positive_low_is_positive(self):
        self.assertEqual(_roi_label(1.0), "POSITIVE")

    def test_exactly_minus5_is_marginal(self):
        self.assertEqual(_roi_label(-5.0), "MARGINAL")

    def test_just_below_zero_is_marginal(self):
        self.assertEqual(_roi_label(-0.1), "MARGINAL")

    def test_just_below_minus5_is_loss(self):
        self.assertEqual(_roi_label(-5.1), "LOSS")

    def test_large_negative_is_loss(self):
        self.assertEqual(_roi_label(-100.0), "LOSS")


# ===========================================================================
# _build_recommendation
# ===========================================================================

class TestBuildRecommendation(unittest.TestCase):

    def _rec(self, label, annualized=20.0, holding_days=30, rt_impact="NEUTRAL",
             costs=100.0, il_pct=0.0, net_profit=500.0, protocol="Proto"):
        return _build_recommendation(
            label, protocol, annualized, holding_days,
            rt_impact, costs, il_pct, net_profit
        )

    def test_exceptional_contains_annualized(self):
        rec = self._rec("EXCEPTIONAL", annualized=35.5, holding_days=45)
        self.assertIn("35.5%", rec)
        self.assertIn("45d", rec)

    def test_exceptional_says_outstanding(self):
        rec = self._rec("EXCEPTIONAL")
        self.assertIn("Outstanding", rec)

    def test_strong_contains_protocol(self):
        rec = self._rec("STRONG", protocol="Aave")
        self.assertIn("Aave", rec)

    def test_strong_contains_impact_lower(self):
        rec = self._rec("STRONG", rt_impact="BOOSTED")
        self.assertIn("boosted", rec)

    def test_positive_message(self):
        rec = self._rec("POSITIVE")
        self.assertIn("Profitable", rec)

    def test_marginal_contains_costs(self):
        rec = self._rec("MARGINAL", costs=250.0, il_pct=3.5)
        self.assertIn("250", rec)
        self.assertIn("3.5%", rec)

    def test_loss_contains_abs_profit(self):
        rec = self._rec("LOSS", net_profit=-1234.0)
        self.assertIn("1234", rec)
        self.assertIn("Exit", rec)

    def test_loss_positive_net_uses_abs(self):
        # Edge: net_profit passed as positive but label is LOSS shouldn't happen in practice
        rec = self._rec("LOSS", net_profit=500.0)
        self.assertIn("500", rec)


# ===========================================================================
# _analyze_farm: math validation
# ===========================================================================

class TestAnalyzeFarmMath(unittest.TestCase):

    def _run(self, **kwargs):
        return _analyze_farm(_farm(**kwargs), risk_free_rate_pct=5.0)

    def test_base_yield_formula(self):
        res = self._run(principal_usd=10000.0, base_apy_pct=10.0, holding_days=365)
        self.assertAlmostEqual(res["base_yield_usd"], 1000.0, places=4)

    def test_base_yield_partial_year(self):
        res = self._run(principal_usd=10000.0, base_apy_pct=10.0, holding_days=73)
        expected = 10000.0 * 0.10 * 73.0 / 365.0
        self.assertAlmostEqual(res["base_yield_usd"], expected, places=4)

    def test_reward_yield_no_price_change(self):
        res = self._run(principal_usd=10000.0, reward_token_apy_pct=20.0,
                        holding_days=365, reward_token_price_change_pct=0.0)
        self.assertAlmostEqual(res["reward_yield_usd"], 2000.0, places=4)

    def test_reward_yield_boosted(self):
        # 10% reward APY, price up 100% → doubled reward value
        res = self._run(principal_usd=10000.0, reward_token_apy_pct=10.0,
                        holding_days=365, reward_token_price_change_pct=100.0)
        expected = 1000.0 * (1.0 + 1.0)
        self.assertAlmostEqual(res["reward_yield_usd"], expected, places=4)

    def test_reward_yield_destroyed(self):
        # Price drops 100% → reward worth 0
        res = self._run(principal_usd=10000.0, reward_token_apy_pct=20.0,
                        holding_days=365, reward_token_price_change_pct=-100.0)
        self.assertAlmostEqual(res["reward_yield_usd"], 0.0, places=4)

    def test_il_loss_usd_formula(self):
        res = self._run(principal_usd=10000.0, impermanent_loss_pct=5.0)
        self.assertAlmostEqual(res["il_loss_usd"], 500.0, places=4)

    def test_principal_gain_positive(self):
        res = self._run(principal_usd=10000.0, principal_price_change_pct=20.0)
        self.assertAlmostEqual(res["principal_gain_usd"], 2000.0, places=4)

    def test_principal_gain_negative(self):
        res = self._run(principal_usd=10000.0, principal_price_change_pct=-10.0)
        self.assertAlmostEqual(res["principal_gain_usd"], -1000.0, places=4)

    def test_total_costs_sum(self):
        res = self._run(entry_cost_usd=100.0, exit_cost_usd=75.0)
        self.assertAlmostEqual(res["total_costs_usd"], 175.0, places=4)

    def test_net_profit_formula(self):
        res = self._run(
            principal_usd=10000.0, base_apy_pct=10.0, holding_days=365,
            reward_token_apy_pct=0.0, reward_token_price_change_pct=0.0,
            principal_price_change_pct=0.0, impermanent_loss_pct=0.0,
            entry_cost_usd=0.0, exit_cost_usd=0.0,
        )
        self.assertAlmostEqual(res["net_profit_usd"], 1000.0, places=4)

    def test_total_return_pct(self):
        res = self._run(
            principal_usd=10000.0, base_apy_pct=0.0, holding_days=365,
            reward_token_apy_pct=0.0, reward_token_price_change_pct=0.0,
            principal_price_change_pct=10.0, impermanent_loss_pct=0.0,
            entry_cost_usd=0.0, exit_cost_usd=0.0,
        )
        self.assertAlmostEqual(res["total_return_pct"], 10.0, places=4)

    def test_annualized_return_pct(self):
        # 5% total return over 73 days → 5/73 * 365 = ~25%
        res = self._run(
            principal_usd=10000.0, base_apy_pct=0.0, holding_days=73,
            reward_token_apy_pct=0.0, reward_token_price_change_pct=0.0,
            principal_price_change_pct=5.0, impermanent_loss_pct=0.0,
            entry_cost_usd=0.0, exit_cost_usd=0.0,
        )
        expected_total = 5.0
        expected_ann = expected_total / 73.0 * 365.0
        self.assertAlmostEqual(res["annualized_return_pct"], expected_ann, places=4)

    def test_excess_return_formula(self):
        # annualized = 25%, rfr = 5%*73/365 ≈ 1.0%
        res = self._run(
            principal_usd=10000.0, base_apy_pct=0.0, holding_days=73,
            reward_token_apy_pct=0.0, reward_token_price_change_pct=0.0,
            principal_price_change_pct=5.0, impermanent_loss_pct=0.0,
            entry_cost_usd=0.0, exit_cost_usd=0.0,
        )
        ann = res["annualized_return_pct"]
        expected_excess = ann - 5.0 * 73.0 / 365.0
        self.assertAlmostEqual(res["excess_return_pct"], expected_excess, places=4)

    def test_protocol_name_preserved(self):
        res = self._run(protocol="Compound")
        self.assertEqual(res["protocol"], "Compound")

    def test_principal_preserved(self):
        res = self._run(principal_usd=99999.0)
        self.assertAlmostEqual(res["principal_usd"], 99999.0, places=2)


# ===========================================================================
# _analyze_farm: edge cases
# ===========================================================================

class TestAnalyzeFarmEdgeCases(unittest.TestCase):

    def test_principal_zero_yields_zero_base(self):
        res = _analyze_farm(_farm(principal_usd=0.0, holding_days=30), 5.0)
        self.assertAlmostEqual(res["base_yield_usd"], 0.0)

    def test_principal_zero_yields_zero_reward(self):
        res = _analyze_farm(_farm(principal_usd=0.0, holding_days=30), 5.0)
        self.assertAlmostEqual(res["reward_yield_usd"], 0.0)

    def test_principal_zero_total_return_zero(self):
        res = _analyze_farm(_farm(principal_usd=0.0, holding_days=30), 5.0)
        self.assertAlmostEqual(res["total_return_pct"], 0.0)

    def test_holding_days_zero_base_zero(self):
        res = _analyze_farm(_farm(holding_days=0), 5.0)
        self.assertAlmostEqual(res["base_yield_usd"], 0.0)

    def test_holding_days_zero_reward_zero(self):
        res = _analyze_farm(_farm(holding_days=0), 5.0)
        self.assertAlmostEqual(res["reward_yield_usd"], 0.0)

    def test_holding_days_zero_annualized_zero(self):
        res = _analyze_farm(_farm(holding_days=0), 5.0)
        self.assertAlmostEqual(res["annualized_return_pct"], 0.0)

    def test_holding_days_zero_excess_zero(self):
        res = _analyze_farm(_farm(holding_days=0), 5.0)
        self.assertAlmostEqual(res["excess_return_pct"], 0.0)

    def test_all_labels_present(self):
        res = _analyze_farm(_farm(), 5.0)
        self.assertIn("roi_label", res)
        self.assertIn("reward_token_impact", res)
        self.assertIn("recommendation", res)


# ===========================================================================
# _analyze_farm: ROI label paths
# ===========================================================================

class TestROILabelPaths(unittest.TestCase):

    def test_exceptional_path(self):
        # Very high principal gain → exceptional annualized return
        res = _analyze_farm(_farm(
            principal_usd=10000.0, holding_days=30,
            principal_price_change_pct=10.0,
            base_apy_pct=0.0, reward_token_apy_pct=0.0,
            entry_cost_usd=0.0, exit_cost_usd=0.0,
            impermanent_loss_pct=0.0, reward_token_price_change_pct=0.0,
        ), 5.0)
        # 10% over 30 days → 10/30*365 ≈ 121.7% annualized → EXCEPTIONAL
        self.assertEqual(res["roi_label"], "EXCEPTIONAL")

    def test_strong_path(self):
        # ~5% total return over 30 days → ~60.8% annualized
        # Let's do 1.5% total → ~18.25% annualized → STRONG
        res = _analyze_farm(_farm(
            principal_usd=10000.0, holding_days=365,
            base_apy_pct=20.0, reward_token_apy_pct=0.0,
            principal_price_change_pct=0.0,
            reward_token_price_change_pct=0.0,
            entry_cost_usd=0.0, exit_cost_usd=0.0,
            impermanent_loss_pct=0.0,
        ), 5.0)
        self.assertEqual(res["roi_label"], "STRONG")

    def test_positive_path(self):
        # small gain → POSITIVE
        res = _analyze_farm(_farm(
            principal_usd=10000.0, holding_days=365,
            base_apy_pct=5.0, reward_token_apy_pct=0.0,
            principal_price_change_pct=0.0,
            reward_token_price_change_pct=0.0,
            entry_cost_usd=0.0, exit_cost_usd=0.0,
            impermanent_loss_pct=0.0,
        ), 5.0)
        self.assertEqual(res["roi_label"], "POSITIVE")

    def test_marginal_path(self):
        # Small loss → MARGINAL
        res = _analyze_farm(_farm(
            principal_usd=10000.0, holding_days=365,
            base_apy_pct=0.0, reward_token_apy_pct=0.0,
            principal_price_change_pct=-2.0,  # -2% annualized
            reward_token_price_change_pct=0.0,
            entry_cost_usd=0.0, exit_cost_usd=0.0,
            impermanent_loss_pct=0.0,
        ), 5.0)
        self.assertEqual(res["roi_label"], "MARGINAL")

    def test_loss_path(self):
        # Large loss → LOSS
        res = _analyze_farm(_farm(
            principal_usd=10000.0, holding_days=365,
            base_apy_pct=0.0, reward_token_apy_pct=0.0,
            principal_price_change_pct=-20.0,
            reward_token_price_change_pct=0.0,
            entry_cost_usd=0.0, exit_cost_usd=0.0,
            impermanent_loss_pct=0.0,
        ), 5.0)
        self.assertEqual(res["roi_label"], "LOSS")


# ===========================================================================
# analyze(): full pipeline
# ===========================================================================

class TestAnalyzeEmpty(unittest.TestCase):

    def test_empty_farms_none_best(self):
        res = analyze([])
        self.assertIsNone(res["best_farm"])

    def test_empty_farms_none_worst(self):
        res = analyze([])
        self.assertIsNone(res["worst_farm"])

    def test_empty_farms_empty_profitable(self):
        res = analyze([])
        self.assertEqual(res["profitable_farms"], [])

    def test_empty_farms_empty_list(self):
        res = analyze([])
        self.assertEqual(res["farms"], [])

    def test_empty_portfolio_zeros(self):
        res = analyze([])
        ps = res["portfolio_summary"]
        self.assertAlmostEqual(ps["total_principal_usd"], 0.0)
        self.assertAlmostEqual(ps["total_net_profit_usd"], 0.0)
        self.assertAlmostEqual(ps["weighted_avg_annualized_pct"], 0.0)
        self.assertAlmostEqual(ps["total_costs_usd"], 0.0)

    def test_empty_farms_has_timestamp(self):
        t0 = time.time()
        res = analyze([])
        self.assertGreaterEqual(res["timestamp"], t0)


class TestAnalyzeSingleFarm(unittest.TestCase):

    def test_single_farm_best_equals_worst(self):
        res = analyze([_farm(protocol="Alpha")])
        self.assertEqual(res["best_farm"], "Alpha")
        self.assertEqual(res["worst_farm"], "Alpha")

    def test_single_farm_list_length(self):
        res = analyze([_farm()])
        self.assertEqual(len(res["farms"]), 1)

    def test_single_profitable_farm_in_list(self):
        farm = _farm(
            protocol="Winner",
            base_apy_pct=50.0, holding_days=365,
            entry_cost_usd=0.0, exit_cost_usd=0.0,
            principal_price_change_pct=0.0, reward_token_apy_pct=0.0,
            reward_token_price_change_pct=0.0, impermanent_loss_pct=0.0,
        )
        res = analyze([farm])
        self.assertIn("Winner", res["profitable_farms"])

    def test_single_losing_farm_not_in_profitable(self):
        farm = _farm(
            protocol="Loser",
            base_apy_pct=0.0, holding_days=365,
            entry_cost_usd=1000.0, exit_cost_usd=0.0,
            principal_price_change_pct=-10.0, reward_token_apy_pct=0.0,
            reward_token_price_change_pct=0.0, impermanent_loss_pct=0.0,
        )
        res = analyze([farm])
        self.assertNotIn("Loser", res["profitable_farms"])

    def test_portfolio_summary_total_principal(self):
        res = analyze([_farm(principal_usd=50000.0)])
        self.assertAlmostEqual(
            res["portfolio_summary"]["total_principal_usd"], 50000.0, places=2
        )

    def test_portfolio_summary_total_costs(self):
        res = analyze([_farm(entry_cost_usd=100.0, exit_cost_usd=200.0)])
        self.assertAlmostEqual(
            res["portfolio_summary"]["total_costs_usd"], 300.0, places=2
        )

    def test_config_default_rfr(self):
        res = analyze([_farm()])
        # Just check it completes without error
        self.assertIn("excess_return_pct", res["farms"][0])

    def test_config_custom_rfr(self):
        res_default = analyze([_farm(holding_days=365, principal_usd=10000.0,
                                      base_apy_pct=10.0, reward_token_apy_pct=0.0,
                                      entry_cost_usd=0.0, exit_cost_usd=0.0,
                                      principal_price_change_pct=0.0,
                                      reward_token_price_change_pct=0.0,
                                      impermanent_loss_pct=0.0)])
        res_custom = analyze([_farm(holding_days=365, principal_usd=10000.0,
                                     base_apy_pct=10.0, reward_token_apy_pct=0.0,
                                     entry_cost_usd=0.0, exit_cost_usd=0.0,
                                     principal_price_change_pct=0.0,
                                     reward_token_price_change_pct=0.0,
                                     impermanent_loss_pct=0.0)],
                              config={"risk_free_rate_pct": 2.0})
        # Higher rfr → lower excess return
        self.assertGreater(
            res_custom["farms"][0]["excess_return_pct"],
            res_default["farms"][0]["excess_return_pct"],
        )


class TestAnalyzeMultiFarm(unittest.TestCase):

    def setUp(self):
        self.farms = [
            _farm(protocol="Alpha", principal_usd=20000.0,
                  base_apy_pct=40.0, holding_days=365,
                  entry_cost_usd=0.0, exit_cost_usd=0.0,
                  reward_token_apy_pct=0.0, reward_token_price_change_pct=0.0,
                  principal_price_change_pct=0.0, impermanent_loss_pct=0.0),
            _farm(protocol="Beta", principal_usd=10000.0,
                  base_apy_pct=5.0, holding_days=365,
                  entry_cost_usd=0.0, exit_cost_usd=0.0,
                  reward_token_apy_pct=0.0, reward_token_price_change_pct=0.0,
                  principal_price_change_pct=0.0, impermanent_loss_pct=0.0),
            _farm(protocol="Gamma", principal_usd=10000.0,
                  base_apy_pct=0.0, holding_days=365,
                  entry_cost_usd=0.0, exit_cost_usd=0.0,
                  reward_token_apy_pct=0.0, reward_token_price_change_pct=0.0,
                  principal_price_change_pct=-15.0, impermanent_loss_pct=0.0),
        ]
        self.res = analyze(self.farms)

    def test_best_farm_is_alpha(self):
        self.assertEqual(self.res["best_farm"], "Alpha")

    def test_worst_farm_is_gamma(self):
        self.assertEqual(self.res["worst_farm"], "Gamma")

    def test_profitable_farms_count(self):
        # Alpha (+40%) and Beta (+5%) profitable; Gamma (-15%) not
        self.assertIn("Alpha", self.res["profitable_farms"])
        self.assertIn("Beta", self.res["profitable_farms"])
        self.assertNotIn("Gamma", self.res["profitable_farms"])

    def test_portfolio_total_principal(self):
        self.assertAlmostEqual(
            self.res["portfolio_summary"]["total_principal_usd"], 40000.0, places=2
        )

    def test_portfolio_total_net_profit(self):
        # Alpha: 20000*0.40=8000, Beta: 10000*0.05=500, Gamma: 10000*(-0.15)=-1500
        expected = 8000.0 + 500.0 - 1500.0
        self.assertAlmostEqual(
            self.res["portfolio_summary"]["total_net_profit_usd"], expected, places=2
        )

    def test_weighted_avg_formula(self):
        # weighted = (40*20000 + 5*10000 + (-15)*10000) / 40000
        expected_wav = (40.0 * 20000.0 + 5.0 * 10000.0 + (-15.0) * 10000.0) / 40000.0
        self.assertAlmostEqual(
            self.res["portfolio_summary"]["weighted_avg_annualized_pct"],
            expected_wav, places=4,
        )

    def test_farms_list_length(self):
        self.assertEqual(len(self.res["farms"]), 3)

    def test_result_has_timestamp(self):
        self.assertIn("timestamp", self.res)


# ===========================================================================
# _append_log: ring buffer behaviour
# ===========================================================================

class TestAppendLog(unittest.TestCase):

    def test_creates_file_if_missing(self):
        with tempfile.TemporaryDirectory() as td:
            lf = _tmp_log(td)
            _append_log({"x": 1}, lf)
            self.assertTrue(lf.exists())

    def test_valid_json_after_write(self):
        with tempfile.TemporaryDirectory() as td:
            lf = _tmp_log(td)
            _append_log({"v": 42}, lf)
            with open(lf) as fh:
                data = json.load(fh)
            self.assertIsInstance(data, list)

    def test_single_entry_written(self):
        with tempfile.TemporaryDirectory() as td:
            lf = _tmp_log(td)
            _append_log({"v": 1}, lf)
            with open(lf) as fh:
                data = json.load(fh)
            self.assertEqual(len(data), 1)
            self.assertEqual(data[0]["v"], 1)

    def test_multiple_entries_accumulate(self):
        with tempfile.TemporaryDirectory() as td:
            lf = _tmp_log(td)
            for i in range(5):
                _append_log({"i": i}, lf)
            with open(lf) as fh:
                data = json.load(fh)
            self.assertEqual(len(data), 5)

    def test_ring_buffer_cap_at_100(self):
        with tempfile.TemporaryDirectory() as td:
            lf = _tmp_log(td)
            for i in range(MAX_ENTRIES + 10):
                _append_log({"i": i}, lf)
            with open(lf) as fh:
                data = json.load(fh)
            self.assertEqual(len(data), MAX_ENTRIES)

    def test_ring_buffer_keeps_latest(self):
        with tempfile.TemporaryDirectory() as td:
            lf = _tmp_log(td)
            for i in range(MAX_ENTRIES + 5):
                _append_log({"i": i}, lf)
            with open(lf) as fh:
                data = json.load(fh)
            self.assertEqual(data[-1]["i"], MAX_ENTRIES + 4)

    def test_atomic_no_tmp_file_remains(self):
        with tempfile.TemporaryDirectory() as td:
            lf = _tmp_log(td)
            _append_log({"v": 1}, lf)
            tmp = Path(str(lf) + ".tmp")
            self.assertFalse(tmp.exists())


# ===========================================================================
# Reward token impact classification via analyze()
# ===========================================================================

class TestRewardTokenImpactViaAnalyze(unittest.TestCase):

    def _impact(self, price_change):
        f = _farm(reward_token_price_change_pct=price_change)
        res = analyze([f])
        return res["farms"][0]["reward_token_impact"]

    def test_boosted_via_analyze(self):
        self.assertEqual(self._impact(50.0), "BOOSTED")

    def test_neutral_via_analyze(self):
        self.assertEqual(self._impact(0.0), "NEUTRAL")

    def test_diluted_via_analyze(self):
        self.assertEqual(self._impact(-30.0), "DILUTED")

    def test_destroyed_via_analyze(self):
        self.assertEqual(self._impact(-80.0), "DESTROYED")


if __name__ == "__main__":
    unittest.main()
