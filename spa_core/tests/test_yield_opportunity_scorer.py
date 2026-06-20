"""
Tests for MP-876: YieldOpportunityScorer
Run: python3 -m unittest spa_core.tests.test_yield_opportunity_scorer -v
"""

import json
import os
import time
import unittest
import tempfile

from spa_core.analytics.yield_opportunity_scorer import (
    _DEFAULT_WEIGHTS,
    _opportunity_grade,
    _parse_config,
    _score_opportunity,
    analyze,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _opp(**kwargs):
    """Build a minimal opportunity dict with safe defaults."""
    defaults = {
        "name": "TestOpp",
        "protocol": "TestProto",
        "net_apy_pct": 5.0,
        "risk_score": 50,
        "liquidity_score": 50,
        "sustainability_score": 50,
        "battle_test_score": 50,
        "tvl_usd": 1_000_000.0,
        "min_capital_usd": 1.0,
        "chain": "ethereum",
    }
    defaults.update(kwargs)
    return defaults


_DEFAULT_W = dict(_DEFAULT_WEIGHTS)


# ============================================================
# 1. _opportunity_grade
# ============================================================

class TestOpportunityGrade(unittest.TestCase):

    def test_a_plus_85(self):
        self.assertEqual(_opportunity_grade(85), "A+")

    def test_a_plus_100(self):
        self.assertEqual(_opportunity_grade(100), "A+")

    def test_a_75(self):
        self.assertEqual(_opportunity_grade(75), "A")

    def test_a_84(self):
        self.assertEqual(_opportunity_grade(84), "A")

    def test_b_plus_65(self):
        self.assertEqual(_opportunity_grade(65), "B+")

    def test_b_plus_74(self):
        self.assertEqual(_opportunity_grade(74), "B+")

    def test_b_55(self):
        self.assertEqual(_opportunity_grade(55), "B")

    def test_b_64(self):
        self.assertEqual(_opportunity_grade(64), "B")

    def test_c_40(self):
        self.assertEqual(_opportunity_grade(40), "C")

    def test_c_54(self):
        self.assertEqual(_opportunity_grade(54), "C")

    def test_d_39(self):
        self.assertEqual(_opportunity_grade(39), "D")

    def test_d_0(self):
        self.assertEqual(_opportunity_grade(0), "D")


# ============================================================
# 2. _parse_config
# ============================================================

class TestParseConfig(unittest.TestCase):

    def test_none_returns_defaults(self):
        w, min_apy, min_tvl = _parse_config(None)
        self.assertAlmostEqual(w["yield"], 0.30)
        self.assertAlmostEqual(w["safety"], 0.30)
        self.assertAlmostEqual(w["liquidity"], 0.20)
        self.assertAlmostEqual(w["sustainability"], 0.15)
        self.assertAlmostEqual(w["battle_test"], 0.05)
        self.assertEqual(min_apy, 0.0)
        self.assertEqual(min_tvl, 0.0)

    def test_empty_dict_returns_defaults(self):
        w, min_apy, min_tvl = _parse_config({})
        self.assertAlmostEqual(w["yield"], 0.30)
        self.assertEqual(min_apy, 0.0)
        self.assertEqual(min_tvl, 0.0)

    def test_custom_min_apy(self):
        _, min_apy, _ = _parse_config({"min_apy_pct": 5.0})
        self.assertEqual(min_apy, 5.0)

    def test_custom_min_tvl(self):
        _, _, min_tvl = _parse_config({"min_tvl_usd": 1_000_000.0})
        self.assertEqual(min_tvl, 1_000_000.0)

    def test_custom_weights(self):
        w, _, _ = _parse_config({"weights": {"yield": 0.50, "safety": 0.50}})
        self.assertAlmostEqual(w["yield"], 0.50)
        self.assertAlmostEqual(w["safety"], 0.50)
        # Unspecified remain at defaults
        self.assertAlmostEqual(w["liquidity"], 0.20)


# ============================================================
# 3. _score_opportunity — component calculations
# ============================================================

class TestScoreOpportunity(unittest.TestCase):

    def test_perfect_score(self):
        opp = _opp(net_apy_pct=50.0, risk_score=0, liquidity_score=100,
                   sustainability_score=100, battle_test_score=100)
        composite, comps = _score_opportunity(opp, _DEFAULT_W)
        # yield_raw=100, yield_comp=30, safety=30, liq=20, sus=15, bt=5 → 100
        self.assertEqual(composite, 100)

    def test_zero_score(self):
        opp = _opp(net_apy_pct=0.0, risk_score=100, liquidity_score=0,
                   sustainability_score=0, battle_test_score=0)
        composite, _ = _score_opportunity(opp, _DEFAULT_W)
        self.assertEqual(composite, 0)

    def test_negative_apy_treated_as_zero(self):
        opp = _opp(net_apy_pct=-5.0, risk_score=0, liquidity_score=100,
                   sustainability_score=100, battle_test_score=100)
        composite, comps = _score_opportunity(opp, _DEFAULT_W)
        # yield=0, safety=30, liq=20, sus=15, bt=5 → 70
        self.assertEqual(comps["yield_component"], 0.0)
        self.assertEqual(composite, 70)

    def test_apy_capped_at_50_pct(self):
        opp1 = _opp(net_apy_pct=50.0, risk_score=100, liquidity_score=0,
                    sustainability_score=0, battle_test_score=0)
        opp2 = _opp(net_apy_pct=200.0, risk_score=100, liquidity_score=0,
                    sustainability_score=0, battle_test_score=0)
        c1, comps1 = _score_opportunity(opp1, _DEFAULT_W)
        c2, comps2 = _score_opportunity(opp2, _DEFAULT_W)
        self.assertEqual(comps1["yield_component"], comps2["yield_component"])

    def test_yield_component_formula(self):
        opp = _opp(net_apy_pct=10.0)
        _, comps = _score_opportunity(opp, _DEFAULT_W)
        # yield_raw = min(100, 10*2) = 20; yield_comp = 20 * 0.30 = 6.0
        self.assertAlmostEqual(comps["yield_component"], 6.0)

    def test_safety_component_formula(self):
        opp = _opp(risk_score=40)
        _, comps = _score_opportunity(opp, _DEFAULT_W)
        # safety = (100 - 40) * 0.30 = 18.0
        self.assertAlmostEqual(comps["safety_component"], 18.0)

    def test_liquidity_component_formula(self):
        opp = _opp(liquidity_score=80)
        _, comps = _score_opportunity(opp, _DEFAULT_W)
        # liq = 80 * 0.20 = 16.0
        self.assertAlmostEqual(comps["liquidity_component"], 16.0)

    def test_sustainability_component_formula(self):
        opp = _opp(sustainability_score=60)
        _, comps = _score_opportunity(opp, _DEFAULT_W)
        # sus = 60 * 0.15 = 9.0
        self.assertAlmostEqual(comps["sustainability_component"], 9.0)

    def test_battle_test_component_formula(self):
        opp = _opp(battle_test_score=100)
        _, comps = _score_opportunity(opp, _DEFAULT_W)
        # bt = 100 * 0.05 = 5.0
        self.assertAlmostEqual(comps["battle_test_component"], 5.0)

    def test_composite_capped_at_100(self):
        opp = _opp(net_apy_pct=1000.0, risk_score=0, liquidity_score=100,
                   sustainability_score=100, battle_test_score=100)
        composite, _ = _score_opportunity(opp, _DEFAULT_W)
        self.assertLessEqual(composite, 100)

    def test_custom_weights_yield_heavy(self):
        weights = {"yield": 0.70, "safety": 0.10, "liquidity": 0.10,
                   "sustainability": 0.05, "battle_test": 0.05}
        opp = _opp(net_apy_pct=25.0, risk_score=0, liquidity_score=0,
                   sustainability_score=0, battle_test_score=0)
        _, comps = _score_opportunity(opp, weights)
        # yield_raw = min(100,50) = 50; yield_comp = 50*0.70 = 35
        self.assertAlmostEqual(comps["yield_component"], 35.0)

    def test_int_cast_truncates(self):
        # Make sure int() truncates toward zero, not rounds
        opp = _opp(net_apy_pct=1.0)  # yield_raw=2.0; yield_comp=0.6
        composite, _ = _score_opportunity(opp, _DEFAULT_W)
        self.assertIsInstance(composite, int)


# ============================================================
# 4. analyze() — empty/trivial
# ============================================================

class TestAnalyzeEmpty(unittest.TestCase):

    def setUp(self):
        self.tmp_log = tempfile.mktemp(suffix=".json")

    def tearDown(self):
        for f in [self.tmp_log, self.tmp_log + ".tmp"]:
            try:
                os.remove(f)
            except FileNotFoundError:
                pass

    def test_empty_list(self):
        result = analyze([], log_path=self.tmp_log)
        self.assertEqual(result["opportunities"], [])
        self.assertIsNone(result["top_opportunity"])
        self.assertEqual(result["top_opportunities_by_chain"], {})
        self.assertEqual(result["filtered_count"], 0)
        self.assertEqual(result["ranking_summary"], [])
        self.assertEqual(result["average_composite_score"], 0.0)

    def test_empty_timestamp(self):
        result = analyze([], log_path=self.tmp_log)
        self.assertIn("timestamp", result)
        self.assertIsInstance(result["timestamp"], float)


# ============================================================
# 5. analyze() — single opportunity
# ============================================================

class TestAnalyzeSingle(unittest.TestCase):

    def setUp(self):
        self.tmp_log = tempfile.mktemp(suffix=".json")

    def tearDown(self):
        for f in [self.tmp_log, self.tmp_log + ".tmp"]:
            try:
                os.remove(f)
            except FileNotFoundError:
                pass

    def test_single_rank_1(self):
        result = analyze([_opp(name="Solo")], log_path=self.tmp_log)
        self.assertEqual(result["opportunities"][0]["rank"], 1)

    def test_single_top_opportunity(self):
        result = analyze([_opp(name="Solo")], log_path=self.tmp_log)
        self.assertEqual(result["top_opportunity"], "Solo")

    def test_single_top_by_chain(self):
        result = analyze([_opp(name="Solo", chain="arbitrum")], log_path=self.tmp_log)
        self.assertIn("arbitrum", result["top_opportunities_by_chain"])
        self.assertEqual(result["top_opportunities_by_chain"]["arbitrum"], "Solo")

    def test_single_not_filtered(self):
        result = analyze([_opp(name="Solo")], log_path=self.tmp_log)
        self.assertFalse(result["opportunities"][0]["filtered_out"])
        self.assertEqual(result["filtered_count"], 0)

    def test_single_grade_present(self):
        result = analyze([_opp(name="Solo")], log_path=self.tmp_log)
        opp = result["opportunities"][0]
        self.assertIn(opp["opportunity_grade"], ["A+", "A", "B+", "B", "C", "D"])

    def test_single_average_equals_composite(self):
        result = analyze([_opp(name="Solo")], log_path=self.tmp_log)
        opp = result["opportunities"][0]
        self.assertAlmostEqual(
            result["average_composite_score"], float(opp["composite_score"])
        )

    def test_single_ranking_summary_has_1(self):
        result = analyze([_opp(name="Solo")], log_path=self.tmp_log)
        self.assertEqual(len(result["ranking_summary"]), 1)
        self.assertEqual(result["ranking_summary"][0]["name"], "Solo")


# ============================================================
# 6. analyze() — filtering
# ============================================================

class TestAnalyzeFiltering(unittest.TestCase):

    def setUp(self):
        self.tmp_log = tempfile.mktemp(suffix=".json")

    def tearDown(self):
        for f in [self.tmp_log, self.tmp_log + ".tmp"]:
            try:
                os.remove(f)
            except FileNotFoundError:
                pass

    def test_filtered_by_min_apy(self):
        opps = [
            _opp(name="Low", net_apy_pct=1.0),
            _opp(name="High", net_apy_pct=10.0),
        ]
        result = analyze(opps, config={"min_apy_pct": 5.0}, log_path=self.tmp_log)
        by_name = {o["name"]: o for o in result["opportunities"]}
        self.assertTrue(by_name["Low"]["filtered_out"])
        self.assertFalse(by_name["High"]["filtered_out"])
        self.assertEqual(result["filtered_count"], 1)

    def test_filtered_by_min_tvl(self):
        opps = [
            _opp(name="Small", tvl_usd=500_000),
            _opp(name="Big", tvl_usd=10_000_000),
        ]
        result = analyze(opps, config={"min_tvl_usd": 1_000_000}, log_path=self.tmp_log)
        by_name = {o["name"]: o for o in result["opportunities"]}
        self.assertTrue(by_name["Small"]["filtered_out"])
        self.assertFalse(by_name["Big"]["filtered_out"])
        self.assertEqual(result["filtered_count"], 1)

    def test_all_filtered_returns_none_top(self):
        opps = [_opp(name="X", net_apy_pct=0.5)]
        result = analyze(opps, config={"min_apy_pct": 5.0}, log_path=self.tmp_log)
        self.assertIsNone(result["top_opportunity"])
        self.assertEqual(result["filtered_count"], 1)
        self.assertEqual(result["average_composite_score"], 0.0)

    def test_filtered_rank_zero(self):
        opps = [_opp(name="X", net_apy_pct=0.5)]
        result = analyze(opps, config={"min_apy_pct": 5.0}, log_path=self.tmp_log)
        self.assertEqual(result["opportunities"][0]["rank"], 0)

    def test_all_filtered_empty_ranking_summary(self):
        opps = [_opp(name="X", net_apy_pct=0.5)]
        result = analyze(opps, config={"min_apy_pct": 5.0}, log_path=self.tmp_log)
        self.assertEqual(result["ranking_summary"], [])

    def test_all_filtered_empty_chain_map(self):
        opps = [_opp(name="X", net_apy_pct=0.5)]
        result = analyze(opps, config={"min_apy_pct": 5.0}, log_path=self.tmp_log)
        self.assertEqual(result["top_opportunities_by_chain"], {})

    def test_partial_filter_average_excludes_filtered(self):
        opps = [
            _opp(name="Low", net_apy_pct=0.5, risk_score=0,
                 liquidity_score=100, sustainability_score=100, battle_test_score=100),
            _opp(name="High", net_apy_pct=10.0, risk_score=50,
                 liquidity_score=50, sustainability_score=50, battle_test_score=50),
        ]
        result = analyze(opps, config={"min_apy_pct": 5.0}, log_path=self.tmp_log)
        # Only "High" is non-filtered
        high_score = next(o["composite_score"] for o in result["opportunities"] if o["name"] == "High")
        self.assertAlmostEqual(result["average_composite_score"], float(high_score))


# ============================================================
# 7. analyze() — ranking
# ============================================================

class TestAnalyzeRanking(unittest.TestCase):

    def setUp(self):
        self.tmp_log = tempfile.mktemp(suffix=".json")
        self.opps = [
            _opp(name="Best", net_apy_pct=40.0, risk_score=10,
                 liquidity_score=95, sustainability_score=90, battle_test_score=90),
            _opp(name="Middle", net_apy_pct=10.0, risk_score=50,
                 liquidity_score=60, sustainability_score=60, battle_test_score=60),
            _opp(name="Worst", net_apy_pct=2.0, risk_score=80,
                 liquidity_score=30, sustainability_score=30, battle_test_score=30),
        ]

    def tearDown(self):
        for f in [self.tmp_log, self.tmp_log + ".tmp"]:
            try:
                os.remove(f)
            except FileNotFoundError:
                pass

    def test_top_opportunity_is_best(self):
        result = analyze(self.opps, log_path=self.tmp_log)
        self.assertEqual(result["top_opportunity"], "Best")

    def test_rank_1_is_best(self):
        result = analyze(self.opps, log_path=self.tmp_log)
        by_name = {o["name"]: o for o in result["opportunities"]}
        self.assertEqual(by_name["Best"]["rank"], 1)

    def test_rank_3_is_worst(self):
        result = analyze(self.opps, log_path=self.tmp_log)
        by_name = {o["name"]: o for o in result["opportunities"]}
        self.assertEqual(by_name["Worst"]["rank"], 3)

    def test_all_ranked_non_filtered(self):
        result = analyze(self.opps, log_path=self.tmp_log)
        ranks = sorted(o["rank"] for o in result["opportunities"])
        self.assertEqual(ranks, [1, 2, 3])

    def test_ranking_summary_length(self):
        result = analyze(self.opps, log_path=self.tmp_log)
        self.assertEqual(len(result["ranking_summary"]), 3)

    def test_ranking_summary_first_is_best(self):
        result = analyze(self.opps, log_path=self.tmp_log)
        self.assertEqual(result["ranking_summary"][0]["name"], "Best")

    def test_ranking_summary_max_5(self):
        many = [_opp(name=f"O{i}", net_apy_pct=float(i)) for i in range(10)]
        result = analyze(many, log_path=self.tmp_log)
        self.assertLessEqual(len(result["ranking_summary"]), 5)

    def test_ranking_summary_fields(self):
        result = analyze(self.opps, log_path=self.tmp_log)
        for entry in result["ranking_summary"]:
            for field in ["rank", "name", "composite_score", "net_apy_pct", "grade"]:
                self.assertIn(field, entry)

    def test_average_composite(self):
        result = analyze(self.opps, log_path=self.tmp_log)
        scores = [o["composite_score"] for o in result["opportunities"]]
        expected_avg = sum(scores) / len(scores)
        self.assertAlmostEqual(result["average_composite_score"], expected_avg, places=5)


# ============================================================
# 8. analyze() — multi-chain
# ============================================================

class TestAnalyzeMultiChain(unittest.TestCase):

    def setUp(self):
        self.tmp_log = tempfile.mktemp(suffix=".json")
        self.opps = [
            _opp(name="EthBest", chain="ethereum", net_apy_pct=30.0, risk_score=10,
                 liquidity_score=95, sustainability_score=90, battle_test_score=90),
            _opp(name="EthSecond", chain="ethereum", net_apy_pct=5.0, risk_score=50,
                 liquidity_score=50, sustainability_score=50, battle_test_score=50),
            _opp(name="ArbOnly", chain="arbitrum", net_apy_pct=15.0, risk_score=30,
                 liquidity_score=80, sustainability_score=80, battle_test_score=80),
        ]

    def tearDown(self):
        for f in [self.tmp_log, self.tmp_log + ".tmp"]:
            try:
                os.remove(f)
            except FileNotFoundError:
                pass

    def test_top_by_chain_keys(self):
        result = analyze(self.opps, log_path=self.tmp_log)
        self.assertIn("ethereum", result["top_opportunities_by_chain"])
        self.assertIn("arbitrum", result["top_opportunities_by_chain"])

    def test_top_by_chain_eth_is_best_eth(self):
        result = analyze(self.opps, log_path=self.tmp_log)
        self.assertEqual(result["top_opportunities_by_chain"]["ethereum"], "EthBest")

    def test_top_by_chain_arb(self):
        result = analyze(self.opps, log_path=self.tmp_log)
        self.assertEqual(result["top_opportunities_by_chain"]["arbitrum"], "ArbOnly")

    def test_no_chain_for_filtered(self):
        opps = [
            _opp(name="A", chain="polygon", net_apy_pct=0.1),
        ]
        result = analyze(opps, config={"min_apy_pct": 5.0}, log_path=self.tmp_log)
        self.assertNotIn("polygon", result["top_opportunities_by_chain"])


# ============================================================
# 9. Log ring-buffer
# ============================================================

class TestLogRingBuffer(unittest.TestCase):

    def setUp(self):
        self.tmp_log = tempfile.mktemp(suffix=".json")

    def tearDown(self):
        for f in [self.tmp_log, self.tmp_log + ".tmp"]:
            try:
                os.remove(f)
            except FileNotFoundError:
                pass

    def test_log_created(self):
        analyze([_opp(name="A")], log_path=self.tmp_log)
        self.assertTrue(os.path.exists(self.tmp_log))

    def test_log_valid_json(self):
        analyze([_opp(name="A")], log_path=self.tmp_log)
        with open(self.tmp_log) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_appends(self):
        analyze([_opp(name="A")], log_path=self.tmp_log)
        analyze([_opp(name="B")], log_path=self.tmp_log)
        with open(self.tmp_log) as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)

    def test_log_ring_cap(self):
        for i in range(110):
            analyze([_opp(name=f"O{i}")], log_path=self.tmp_log)
        with open(self.tmp_log) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), 100)

    def test_log_entry_fields(self):
        analyze([_opp(name="A")], log_path=self.tmp_log)
        with open(self.tmp_log) as f:
            data = json.load(f)
        entry = data[0]
        self.assertIn("timestamp", entry)
        self.assertIn("opportunity_count", entry)
        self.assertIn("filtered_count", entry)
        self.assertIn("top_opportunity", entry)
        self.assertIn("average_composite_score", entry)

    def test_log_empty_result(self):
        analyze([], log_path=self.tmp_log)
        with open(self.tmp_log) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["opportunity_count"], 0)


# ============================================================
# 10. Edge cases & integration
# ============================================================

class TestEdgeCases(unittest.TestCase):

    def setUp(self):
        self.tmp_log = tempfile.mktemp(suffix=".json")

    def tearDown(self):
        for f in [self.tmp_log, self.tmp_log + ".tmp"]:
            try:
                os.remove(f)
            except FileNotFoundError:
                pass

    def test_config_none_works(self):
        result = analyze([_opp(name="A")], config=None, log_path=self.tmp_log)
        self.assertEqual(len(result["opportunities"]), 1)

    def test_config_empty_dict_works(self):
        result = analyze([_opp(name="A")], config={}, log_path=self.tmp_log)
        self.assertEqual(len(result["opportunities"]), 1)

    def test_apy_25_pct_yield_raw(self):
        opp = _opp(net_apy_pct=25.0, risk_score=0, liquidity_score=0,
                   sustainability_score=0, battle_test_score=0)
        _, comps = _score_opportunity(opp, _DEFAULT_W)
        # yield_raw = min(100, 25*2) = 50; yield_comp = 50*0.30 = 15
        self.assertAlmostEqual(comps["yield_component"], 15.0)

    def test_50_pct_apy_max_yield(self):
        opp = _opp(net_apy_pct=50.0, risk_score=100, liquidity_score=0,
                   sustainability_score=0, battle_test_score=0)
        _, comps = _score_opportunity(opp, _DEFAULT_W)
        # yield_raw = 100; yield_comp = 30
        self.assertAlmostEqual(comps["yield_component"], 30.0)

    def test_100_pct_apy_same_as_50(self):
        opp50 = _opp(net_apy_pct=50.0)
        opp100 = _opp(net_apy_pct=100.0)
        _, c50 = _score_opportunity(opp50, _DEFAULT_W)
        _, c100 = _score_opportunity(opp100, _DEFAULT_W)
        self.assertEqual(c50["yield_component"], c100["yield_component"])

    def test_a_plus_grade_threshold(self):
        # Need composite >= 85
        opp = _opp(net_apy_pct=50.0, risk_score=0, liquidity_score=100,
                   sustainability_score=100, battle_test_score=100)
        result = analyze([opp], log_path=self.tmp_log)
        self.assertEqual(result["opportunities"][0]["opportunity_grade"], "A+")

    def test_d_grade_low_everything(self):
        opp = _opp(net_apy_pct=0.5, risk_score=90, liquidity_score=5,
                   sustainability_score=5, battle_test_score=5)
        result = analyze([opp], log_path=self.tmp_log)
        grade = result["opportunities"][0]["opportunity_grade"]
        self.assertIn(grade, ["C", "D"])

    def test_all_output_fields_present(self):
        result = analyze([_opp(name="A")], log_path=self.tmp_log)
        opp = result["opportunities"][0]
        for field in ["name", "protocol", "chain", "net_apy_pct",
                      "composite_score", "opportunity_grade",
                      "yield_component", "safety_component",
                      "liquidity_component", "sustainability_component",
                      "battle_test_component", "rank", "filtered_out"]:
            self.assertIn(field, opp, f"Missing field: {field}")

    def test_composite_score_is_int(self):
        result = analyze([_opp(name="A")], log_path=self.tmp_log)
        opp = result["opportunities"][0]
        self.assertIsInstance(opp["composite_score"], int)

    def test_filtered_out_false_default(self):
        result = analyze([_opp(name="A")], log_path=self.tmp_log)
        self.assertFalse(result["opportunities"][0]["filtered_out"])

    def test_multiple_same_composite_all_ranked(self):
        # Same scores → both should be ranked, no zeros
        opps = [
            _opp(name="A", net_apy_pct=10.0, risk_score=50,
                 liquidity_score=50, sustainability_score=50, battle_test_score=50),
            _opp(name="B", net_apy_pct=10.0, risk_score=50,
                 liquidity_score=50, sustainability_score=50, battle_test_score=50),
        ]
        result = analyze(opps, log_path=self.tmp_log)
        ranks = [o["rank"] for o in result["opportunities"]]
        self.assertNotIn(0, ranks)

    def test_high_and_low_apy_grading(self):
        opps = [
            _opp(name="HighAPY", net_apy_pct=45.0, risk_score=5,
                 liquidity_score=95, sustainability_score=90, battle_test_score=90),
            _opp(name="LowAPY", net_apy_pct=1.0, risk_score=95,
                 liquidity_score=5, sustainability_score=5, battle_test_score=5),
        ]
        result = analyze(opps, log_path=self.tmp_log)
        by_name = {o["name"]: o for o in result["opportunities"]}
        self.assertGreater(by_name["HighAPY"]["composite_score"],
                           by_name["LowAPY"]["composite_score"])

    def test_ranking_summary_sorted_by_score(self):
        opps = [
            _opp(name=f"O{i}", net_apy_pct=float(i * 5)) for i in range(6)
        ]
        result = analyze(opps, log_path=self.tmp_log)
        scores_in_summary = [e["composite_score"] for e in result["ranking_summary"]]
        self.assertEqual(scores_in_summary, sorted(scores_in_summary, reverse=True))

    def test_zero_tvl_not_filtered_by_default(self):
        result = analyze([_opp(name="A", tvl_usd=0)], log_path=self.tmp_log)
        self.assertFalse(result["opportunities"][0]["filtered_out"])

    def test_zero_apy_not_filtered_by_default(self):
        result = analyze([_opp(name="A", net_apy_pct=0)], log_path=self.tmp_log)
        self.assertFalse(result["opportunities"][0]["filtered_out"])


if __name__ == "__main__":
    unittest.main()
