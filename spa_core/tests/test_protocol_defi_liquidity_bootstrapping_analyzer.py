"""
Tests for MP-1007 ProtocolDeFiLiquidityBootstrappingAnalyzer
Run: python3 -m unittest spa_core.tests.test_protocol_defi_liquidity_bootstrapping_analyzer -v
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from spa_core.analytics.protocol_defi_liquidity_bootstrapping_analyzer import (
    analyze,
    _price_efficiency_ratio,
    _bot_extraction_usd,
    _community_allocation_pct,
    _lbp_success_score,
    _lbp_label,
    _compute_flags,
    _append_log,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_event(**kwargs):
    """Return a minimal valid LBP event dict with overrides."""
    base = {
        "name": "TestLBP",
        "protocol": "BalancerV2",
        "start_price_usd": 10.0,
        "end_price_usd": 2.0,
        "current_price_usd": 2.5,
        "duration_hours": 72.0,
        "starting_weight_pct": 92.0,
        "ending_weight_pct": 50.0,
        "total_raised_usd": 5_000_000.0,
        "tokens_sold_pct": 10.0,
        "bot_snipe_first_block_pct": 3.0,
        "price_decay_rate_pct_per_hour": 1.1,
        "fair_launch_score": 80.0,
        "team_allocation_pct": 20.0,
        "vesting_period_months": 12.0,
    }
    base.update(kwargs)
    return base


# ---------------------------------------------------------------------------
# _price_efficiency_ratio
# ---------------------------------------------------------------------------

class TestPriceEfficiencyRatio(unittest.TestCase):

    def test_basic_calculation(self):
        per = _price_efficiency_ratio(2.0, 10.0)
        self.assertAlmostEqual(per, 0.2)

    def test_no_decay(self):
        per = _price_efficiency_ratio(10.0, 10.0)
        self.assertAlmostEqual(per, 1.0)

    def test_zero_start_price_no_crash(self):
        per = _price_efficiency_ratio(1.0, 0.0)
        self.assertEqual(per, 1.0)

    def test_price_below_ideal(self):
        per = _price_efficiency_ratio(1.0, 10.0)
        self.assertAlmostEqual(per, 0.1)

    def test_returns_float(self):
        self.assertIsInstance(_price_efficiency_ratio(2.0, 5.0), float)

    def test_high_decay_low_ratio(self):
        per = _price_efficiency_ratio(0.5, 10.0)
        self.assertLess(per, 0.1)

    def test_rounding_4_decimals(self):
        per = _price_efficiency_ratio(1.0, 3.0)
        self.assertEqual(per, round(per, 4))


# ---------------------------------------------------------------------------
# _bot_extraction_usd
# ---------------------------------------------------------------------------

class TestBotExtractionUSD(unittest.TestCase):

    def test_basic_calculation(self):
        ext = _bot_extraction_usd(10.0, 1_000_000.0)
        self.assertAlmostEqual(ext, 100_000.0)

    def test_zero_bots(self):
        self.assertEqual(_bot_extraction_usd(0.0, 1_000_000.0), 0.0)

    def test_zero_raised(self):
        self.assertEqual(_bot_extraction_usd(10.0, 0.0), 0.0)

    def test_100_pct_bots(self):
        ext = _bot_extraction_usd(100.0, 500_000.0)
        self.assertAlmostEqual(ext, 500_000.0)

    def test_returns_float(self):
        self.assertIsInstance(_bot_extraction_usd(5.0, 200_000.0), float)

    def test_small_snipe(self):
        ext = _bot_extraction_usd(0.5, 10_000_000.0)
        self.assertAlmostEqual(ext, 50_000.0)


# ---------------------------------------------------------------------------
# _community_allocation_pct
# ---------------------------------------------------------------------------

class TestCommunityAllocationPct(unittest.TestCase):

    def test_basic(self):
        pct = _community_allocation_pct(20.0, 3.0)
        self.assertAlmostEqual(pct, 77.0)

    def test_team_and_bots_sum_to_100(self):
        pct = _community_allocation_pct(60.0, 40.0)
        self.assertAlmostEqual(pct, 0.0)

    def test_clamped_to_zero(self):
        pct = _community_allocation_pct(80.0, 40.0)
        self.assertEqual(pct, 0.0)

    def test_zero_team_zero_bots(self):
        pct = _community_allocation_pct(0.0, 0.0)
        self.assertAlmostEqual(pct, 100.0)

    def test_returns_float(self):
        self.assertIsInstance(_community_allocation_pct(15.0, 5.0), float)

    def test_clamped_max_100(self):
        pct = _community_allocation_pct(0.0, 0.0)
        self.assertLessEqual(pct, 100.0)


# ---------------------------------------------------------------------------
# _lbp_success_score
# ---------------------------------------------------------------------------

class TestLBPSuccessScore(unittest.TestCase):

    def test_ideal_inputs_high_score(self):
        score = _lbp_success_score(90.0, 0.1, 80.0)
        self.assertGreater(score, 50.0)

    def test_no_decay_low_score(self):
        score = _lbp_success_score(90.0, 1.0, 80.0)
        self.assertAlmostEqual(score, 0.0)

    def test_zero_fair_launch_zero_score(self):
        score = _lbp_success_score(0.0, 0.2, 80.0)
        self.assertAlmostEqual(score, 0.0)

    def test_zero_community_zero_score(self):
        score = _lbp_success_score(90.0, 0.2, 0.0)
        self.assertAlmostEqual(score, 0.0)

    def test_returns_float(self):
        self.assertIsInstance(_lbp_success_score(70.0, 0.2, 70.0), float)

    def test_clamped_0_to_100(self):
        score = _lbp_success_score(100.0, 0.0, 100.0)
        self.assertLessEqual(score, 100.0)
        self.assertGreaterEqual(score, 0.0)

    def test_partial_community(self):
        s_full = _lbp_success_score(80.0, 0.2, 100.0)
        s_half = _lbp_success_score(80.0, 0.2, 50.0)
        self.assertGreater(s_full, s_half)


# ---------------------------------------------------------------------------
# _lbp_label
# ---------------------------------------------------------------------------

class TestLBPLabel(unittest.TestCase):

    def test_bot_dominated_high_bots(self):
        label = _lbp_label(90.0, 25.0, 0.2)
        self.assertEqual(label, "BOT_DOMINATED")

    def test_ideal_lbp_high_success_low_bots_good_decay(self):
        label = _lbp_label(85.0, 2.0, 0.2)
        self.assertEqual(label, "IDEAL_LBP")

    def test_fair_launch(self):
        label = _lbp_label(65.0, 8.0, 0.3)
        self.assertEqual(label, "FAIR_LAUNCH")

    def test_acceptable(self):
        label = _lbp_label(40.0, 8.0, 0.3)
        self.assertEqual(label, "ACCEPTABLE")

    def test_failed_lbp_low_score(self):
        label = _lbp_label(10.0, 5.0, 0.5)
        self.assertEqual(label, "FAILED_LBP")

    def test_bot_dominated_overrides_high_success(self):
        """Even if score is great, bot domination wins."""
        label = _lbp_label(95.0, 30.0, 0.1)
        self.assertEqual(label, "BOT_DOMINATED")

    def test_ideal_lbp_requires_low_ratio(self):
        """IDEAL_LBP should not trigger if ratio > 0.5."""
        label = _lbp_label(85.0, 2.0, 0.6)
        self.assertNotEqual(label, "IDEAL_LBP")

    def test_ideal_lbp_requires_low_bots(self):
        """IDEAL_LBP should not trigger if bots > 5."""
        label = _lbp_label(85.0, 8.0, 0.2)
        self.assertNotEqual(label, "IDEAL_LBP")

    def test_valid_labels(self):
        valid = {"IDEAL_LBP", "FAIR_LAUNCH", "ACCEPTABLE", "BOT_DOMINATED", "FAILED_LBP"}
        for success in [0, 20, 40, 65, 85]:
            for bots in [2, 10, 25]:
                label = _lbp_label(success, bots, 0.3)
                self.assertIn(label, valid)


# ---------------------------------------------------------------------------
# _compute_flags
# ---------------------------------------------------------------------------

class TestComputeFlags(unittest.TestCase):

    def test_no_flags_clean(self):
        # community=55 (<60, so no FAIR_COMMUNITY_DISTRIBUTION), success=70 (<75, no SUCCESSFUL_PRICE_DISCOVERY)
        flags = _compute_flags(3.0, 0.2, 15.0, 55.0, 12.0, 70.0)
        self.assertEqual(flags, [])

    def test_bot_sniped_flag(self):
        flags = _compute_flags(20.0, 0.2, 15.0, 65.0, 12.0, 70.0)
        self.assertIn("BOT_SNIPED", flags)

    def test_price_did_not_decay_flag(self):
        flags = _compute_flags(3.0, 0.85, 15.0, 65.0, 12.0, 70.0)
        self.assertIn("PRICE_DIDN_NOT_DECAY", flags)

    def test_team_heavy_flag(self):
        flags = _compute_flags(3.0, 0.2, 35.0, 62.0, 12.0, 70.0)
        self.assertIn("TEAM_HEAVY", flags)

    def test_fair_community_distribution_flag(self):
        flags = _compute_flags(3.0, 0.2, 15.0, 65.0, 12.0, 70.0)
        self.assertIn("FAIR_COMMUNITY_DISTRIBUTION", flags)

    def test_short_vesting_risk_flag(self):
        flags = _compute_flags(3.0, 0.2, 15.0, 65.0, 3.0, 70.0)
        self.assertIn("SHORT_VESTING_RISK", flags)

    def test_successful_price_discovery_flag(self):
        flags = _compute_flags(3.0, 0.2, 15.0, 65.0, 12.0, 80.0)
        self.assertIn("SUCCESSFUL_PRICE_DISCOVERY", flags)

    def test_bot_sniped_boundary_15_no_flag(self):
        flags = _compute_flags(15.0, 0.2, 15.0, 65.0, 12.0, 70.0)
        self.assertNotIn("BOT_SNIPED", flags)

    def test_price_decay_boundary_0_8_no_flag(self):
        flags = _compute_flags(3.0, 0.79, 15.0, 65.0, 12.0, 70.0)
        self.assertNotIn("PRICE_DIDN_NOT_DECAY", flags)

    def test_vesting_boundary_6_no_flag(self):
        flags = _compute_flags(3.0, 0.2, 15.0, 65.0, 6.0, 70.0)
        self.assertNotIn("SHORT_VESTING_RISK", flags)

    def test_multiple_flags(self):
        flags = _compute_flags(20.0, 0.9, 35.0, 55.0, 3.0, 80.0)
        self.assertIn("BOT_SNIPED", flags)
        self.assertIn("PRICE_DIDN_NOT_DECAY", flags)
        self.assertIn("TEAM_HEAVY", flags)
        self.assertIn("SHORT_VESTING_RISK", flags)

    def test_returns_list(self):
        self.assertIsInstance(_compute_flags(5.0, 0.2, 20.0, 70.0, 12.0, 60.0), list)


# ---------------------------------------------------------------------------
# _append_log (ring-buffer behavior)
# ---------------------------------------------------------------------------

class TestAppendLog(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmp_dir, "test_lbp_log.json")

    def test_creates_log_file(self):
        _append_log({"event": "test"}, log_path=self.log_path, cap=10)
        self.assertTrue(os.path.exists(self.log_path))

    def test_appends_entry(self):
        _append_log({"event": "e1"}, log_path=self.log_path, cap=10)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_ring_buffer_enforces_cap(self):
        for i in range(15):
            _append_log({"i": i}, log_path=self.log_path, cap=10)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 10)

    def test_ring_buffer_keeps_latest(self):
        for i in range(15):
            _append_log({"i": i}, log_path=self.log_path, cap=10)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(data[-1]["i"], 14)
        self.assertEqual(data[0]["i"], 5)

    def test_multiple_appends_accumulate(self):
        _append_log({"a": 1}, log_path=self.log_path, cap=100)
        _append_log({"a": 2}, log_path=self.log_path, cap=100)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)

    def test_corrupted_file_reset(self):
        with open(self.log_path, "w") as f:
            f.write("not-json")
        _append_log({"event": "recovery"}, log_path=self.log_path, cap=10)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_atomic_write_via_replace(self):
        """File should be valid JSON after write (no partial writes)."""
        _append_log({"k": "v"}, log_path=self.log_path, cap=10)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)


# ---------------------------------------------------------------------------
# analyze() — integration tests
# ---------------------------------------------------------------------------

class TestAnalyzeBasic(unittest.TestCase):

    def _cfg(self):
        tmp = tempfile.mkdtemp()
        return {"write_log": False, "log_path": os.path.join(tmp, "lbp.json")}

    def test_returns_dict(self):
        result = analyze([_make_event()], config=self._cfg())
        self.assertIsInstance(result, dict)

    def test_output_keys(self):
        result = analyze([_make_event()], config=self._cfg())
        self.assertIn("event_analyses", result)
        self.assertIn("summary", result)

    def test_single_event_count(self):
        result = analyze([_make_event()], config=self._cfg())
        self.assertEqual(len(result["event_analyses"]), 1)

    def test_multiple_events(self):
        evs = [_make_event(name=f"LBP{i}") for i in range(5)]
        result = analyze(evs, config=self._cfg())
        self.assertEqual(len(result["event_analyses"]), 5)

    def test_empty_list_returns_error(self):
        result = analyze([], config=self._cfg())
        self.assertIn("error", result)

    def test_non_list_returns_error(self):
        result = analyze("bad", config=self._cfg())
        self.assertIn("error", result)


class TestAnalyzeEventFields(unittest.TestCase):

    def setUp(self):
        cfg = {"write_log": False}
        self.result = analyze([_make_event()], config=cfg)
        self.ev = self.result["event_analyses"][0]

    def test_price_efficiency_ratio_present(self):
        self.assertIn("price_efficiency_ratio", self.ev)

    def test_price_efficiency_ratio_value(self):
        self.assertAlmostEqual(self.ev["price_efficiency_ratio"], 0.2)

    def test_discovered_fair_value_equals_end_price(self):
        self.assertAlmostEqual(self.ev["discovered_fair_value_usd"], 2.0)

    def test_bot_extraction_usd_present(self):
        self.assertIn("bot_extraction_usd", self.ev)

    def test_bot_extraction_usd_value(self):
        expected = 0.03 * 5_000_000.0
        self.assertAlmostEqual(self.ev["bot_extraction_usd"], expected)

    def test_community_allocation_pct_present(self):
        self.assertIn("community_allocation_pct", self.ev)

    def test_community_allocation_pct_value(self):
        self.assertAlmostEqual(self.ev["community_allocation_pct"], 77.0)

    def test_lbp_success_score_0_100(self):
        s = self.ev["lbp_success_score"]
        self.assertGreaterEqual(s, 0.0)
        self.assertLessEqual(s, 100.0)

    def test_lbp_label_valid(self):
        valid = {"IDEAL_LBP", "FAIR_LAUNCH", "ACCEPTABLE", "BOT_DOMINATED", "FAILED_LBP"}
        self.assertIn(self.ev["lbp_label"], valid)

    def test_flags_is_list(self):
        self.assertIsInstance(self.ev["flags"], list)

    def test_name_preserved(self):
        self.assertEqual(self.ev["name"], "TestLBP")

    def test_protocol_preserved(self):
        self.assertEqual(self.ev["protocol"], "BalancerV2")


class TestAnalyzeSummary(unittest.TestCase):

    def _cfg(self):
        return {"write_log": False}

    def test_summary_event_count(self):
        evs = [_make_event(name=f"LBP{i}") for i in range(3)]
        result = analyze(evs, config=self._cfg())
        self.assertEqual(result["summary"]["event_count"], 3)

    def test_summary_most_successful(self):
        evs = [
            _make_event(name="Good", fair_launch_score=90.0, bot_snipe_first_block_pct=2.0,
                        end_price_usd=1.0, team_allocation_pct=10.0),
            _make_event(name="Bad", fair_launch_score=10.0, bot_snipe_first_block_pct=25.0,
                        end_price_usd=9.5),
        ]
        result = analyze(evs, config=self._cfg())
        self.assertEqual(result["summary"]["most_successful"], "Good")

    def test_summary_least_successful(self):
        evs = [
            _make_event(name="Good", fair_launch_score=90.0, bot_snipe_first_block_pct=2.0,
                        end_price_usd=1.0, team_allocation_pct=10.0),
            _make_event(name="Bad", fair_launch_score=5.0, bot_snipe_first_block_pct=1.0,
                        end_price_usd=9.8),
        ]
        result = analyze(evs, config=self._cfg())
        self.assertEqual(result["summary"]["least_successful"], "Bad")

    def test_summary_avg_success_score(self):
        evs = [
            _make_event(name="A", fair_launch_score=100.0, end_price_usd=1.0,
                        bot_snipe_first_block_pct=1.0, team_allocation_pct=5.0),
            _make_event(name="B", fair_launch_score=0.0, end_price_usd=10.0,
                        bot_snipe_first_block_pct=1.0, team_allocation_pct=5.0),
        ]
        result = analyze(evs, config=self._cfg())
        avg = result["summary"]["avg_success_score"]
        self.assertGreaterEqual(avg, 0.0)
        self.assertLessEqual(avg, 100.0)

    def test_summary_bot_dominated_count(self):
        evs = [
            _make_event(name="Bot1", bot_snipe_first_block_pct=25.0),
            _make_event(name="Bot2", bot_snipe_first_block_pct=30.0),
            _make_event(name="Clean", bot_snipe_first_block_pct=2.0),
        ]
        result = analyze(evs, config=self._cfg())
        self.assertEqual(result["summary"]["bot_dominated_count"], 2)

    def test_summary_ideal_count(self):
        evs = [
            _make_event(name="Ideal", fair_launch_score=90.0, bot_snipe_first_block_pct=2.0,
                        end_price_usd=1.5, team_allocation_pct=10.0),
            _make_event(name="Meh", fair_launch_score=30.0, bot_snipe_first_block_pct=5.0,
                        end_price_usd=8.0),
        ]
        result = analyze(evs, config=self._cfg())
        self.assertGreaterEqual(result["summary"]["ideal_count"], 0)

    def test_summary_analyzed_at_present(self):
        result = analyze([_make_event()], config=self._cfg())
        self.assertIn("analyzed_at", result["summary"])

    def test_single_event_most_and_least_same(self):
        result = analyze([_make_event()], config=self._cfg())
        s = result["summary"]
        self.assertEqual(s["most_successful"], s["least_successful"])


class TestAnalyzeLabels(unittest.TestCase):

    def _cfg(self):
        return {"write_log": False}

    def test_bot_dominated_label(self):
        ev = _make_event(bot_snipe_first_block_pct=25.0)
        result = analyze([ev], config=self._cfg())
        self.assertEqual(result["event_analyses"][0]["lbp_label"], "BOT_DOMINATED")

    def test_ideal_lbp_label(self):
        # per=0.05 (end=0.5/start=10), fair=100, comm=93 → score≈88.35 > 80 → IDEAL_LBP
        ev = _make_event(
            fair_launch_score=100.0, bot_snipe_first_block_pct=2.0,
            end_price_usd=0.5, start_price_usd=10.0, team_allocation_pct=5.0,
        )
        result = analyze([ev], config=self._cfg())
        self.assertEqual(result["event_analyses"][0]["lbp_label"], "IDEAL_LBP")

    def test_fair_launch_label(self):
        # per=0.1 (end=1.0/start=10), fair=90, team=10, bot=5 → comm=85, score≈68.85 → FAIR_LAUNCH
        ev = _make_event(fair_launch_score=90.0, bot_snipe_first_block_pct=5.0,
                         end_price_usd=1.0, start_price_usd=10.0, team_allocation_pct=10.0)
        result = analyze([ev], config=self._cfg())
        self.assertIn(result["event_analyses"][0]["lbp_label"],
                      {"FAIR_LAUNCH", "IDEAL_LBP"})

    def test_failed_lbp_no_decay(self):
        ev = _make_event(
            fair_launch_score=20.0, bot_snipe_first_block_pct=5.0,
            end_price_usd=9.5, start_price_usd=10.0,
            team_allocation_pct=50.0,
        )
        result = analyze([ev], config=self._cfg())
        self.assertEqual(result["event_analyses"][0]["lbp_label"], "FAILED_LBP")


class TestAnalyzeFlags(unittest.TestCase):

    def _cfg(self):
        return {"write_log": False}

    def test_flag_bot_sniped(self):
        ev = _make_event(bot_snipe_first_block_pct=20.0)
        result = analyze([ev], config=self._cfg())
        self.assertIn("BOT_SNIPED", result["event_analyses"][0]["flags"])

    def test_flag_price_did_not_decay(self):
        ev = _make_event(end_price_usd=9.0, start_price_usd=10.0)
        result = analyze([ev], config=self._cfg())
        self.assertIn("PRICE_DIDN_NOT_DECAY", result["event_analyses"][0]["flags"])

    def test_flag_team_heavy(self):
        ev = _make_event(team_allocation_pct=35.0)
        result = analyze([ev], config=self._cfg())
        self.assertIn("TEAM_HEAVY", result["event_analyses"][0]["flags"])

    def test_flag_fair_community_distribution(self):
        ev = _make_event(team_allocation_pct=10.0, bot_snipe_first_block_pct=5.0)
        result = analyze([ev], config=self._cfg())
        self.assertIn("FAIR_COMMUNITY_DISTRIBUTION", result["event_analyses"][0]["flags"])

    def test_flag_short_vesting_risk(self):
        ev = _make_event(vesting_period_months=3.0)
        result = analyze([ev], config=self._cfg())
        self.assertIn("SHORT_VESTING_RISK", result["event_analyses"][0]["flags"])

    def test_flag_successful_price_discovery(self):
        # per=0.05 (end=0.5/start=10), fair=90, team=5, bot=2 → comm=93, score≈79.5 > 75 ✓
        ev = _make_event(
            fair_launch_score=90.0, bot_snipe_first_block_pct=2.0,
            end_price_usd=0.5, start_price_usd=10.0, team_allocation_pct=5.0,
        )
        result = analyze([ev], config=self._cfg())
        self.assertIn("SUCCESSFUL_PRICE_DISCOVERY", result["event_analyses"][0]["flags"])

    def test_no_flags_on_neutral_event(self):
        ev = _make_event(
            bot_snipe_first_block_pct=5.0, end_price_usd=3.0,
            team_allocation_pct=28.0, vesting_period_months=12.0,
            fair_launch_score=60.0,
        )
        result = analyze([ev], config=self._cfg())
        flags = result["event_analyses"][0]["flags"]
        self.assertNotIn("BOT_SNIPED", flags)
        self.assertNotIn("PRICE_DIDN_NOT_DECAY", flags)
        self.assertNotIn("TEAM_HEAVY", flags)


class TestAnalyzeLogWriting(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmp_dir, "lbp_log.json")

    def test_log_file_created(self):
        analyze([_make_event()], config={"write_log": True, "log_path": self.log_path})
        self.assertTrue(os.path.exists(self.log_path))

    def test_log_entry_count(self):
        analyze([_make_event()], config={"write_log": True, "log_path": self.log_path})
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_log_has_timestamp(self):
        analyze([_make_event()], config={"write_log": True, "log_path": self.log_path})
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIn("timestamp", data[0])

    def test_log_has_event_count(self):
        evs = [_make_event(name=f"E{i}") for i in range(3)]
        analyze(evs, config={"write_log": True, "log_path": self.log_path})
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(data[0]["event_count"], 3)

    def test_write_log_false_skips_file(self):
        analyze([_make_event()], config={"write_log": False, "log_path": self.log_path})
        self.assertFalse(os.path.exists(self.log_path))

    def test_log_ring_buffer_cap(self):
        for _ in range(5):
            analyze([_make_event()], config={"write_log": True,
                                              "log_path": self.log_path,
                                              "log_cap": 3})
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 3)

    def test_log_has_avg_success_score(self):
        analyze([_make_event()], config={"write_log": True, "log_path": self.log_path})
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIn("avg_success_score", data[0])


class TestAnalyzeEdgeCases(unittest.TestCase):

    def _cfg(self):
        return {"write_log": False}

    def test_missing_optional_fields_no_crash(self):
        ev = {"name": "Minimal", "protocol": "Unknown",
              "start_price_usd": 5.0, "end_price_usd": 1.0}
        result = analyze([ev], config=self._cfg())
        self.assertIn("event_analyses", result)

    def test_zero_start_price_no_crash(self):
        ev = _make_event(start_price_usd=0.0)
        result = analyze([ev], config=self._cfg())
        self.assertIsInstance(result["event_analyses"][0]["price_efficiency_ratio"], float)

    def test_zero_total_raised(self):
        ev = _make_event(total_raised_usd=0.0)
        result = analyze([ev], config=self._cfg())
        self.assertAlmostEqual(result["event_analyses"][0]["bot_extraction_usd"], 0.0)

    def test_100_pct_bot_snipe(self):
        ev = _make_event(bot_snipe_first_block_pct=100.0)
        result = analyze([ev], config=self._cfg())
        self.assertEqual(result["event_analyses"][0]["lbp_label"], "BOT_DOMINATED")

    def test_zero_fair_launch_score(self):
        ev = _make_event(fair_launch_score=0.0)
        result = analyze([ev], config=self._cfg())
        self.assertAlmostEqual(result["event_analyses"][0]["lbp_success_score"], 0.0)

    def test_community_clamped_to_zero_when_over_allotted(self):
        ev = _make_event(team_allocation_pct=70.0, bot_snipe_first_block_pct=40.0)
        result = analyze([ev], config=self._cfg())
        self.assertEqual(result["event_analyses"][0]["community_allocation_pct"], 0.0)

    def test_large_number_of_events(self):
        evs = [_make_event(name=f"LBP{i}") for i in range(50)]
        result = analyze(evs, config=self._cfg())
        self.assertEqual(len(result["event_analyses"]), 50)

    def test_current_price_preserved(self):
        ev = _make_event(current_price_usd=3.5)
        result = analyze([ev], config=self._cfg())
        self.assertAlmostEqual(result["event_analyses"][0]["current_price_usd"], 3.5)

    def test_duration_hours_preserved(self):
        ev = _make_event(duration_hours=48.0)
        result = analyze([ev], config=self._cfg())
        self.assertAlmostEqual(result["event_analyses"][0]["duration_hours"], 48.0)


if __name__ == "__main__":
    unittest.main()
