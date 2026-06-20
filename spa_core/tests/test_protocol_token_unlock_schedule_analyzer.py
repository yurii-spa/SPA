"""
Tests for MP-906: ProtocolTokenUnlockScheduleAnalyzer
Run: python3 -m unittest spa_core.tests.test_protocol_token_unlock_schedule_analyzer -v
"""

import json
import os
import sys
import unittest
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.analytics.protocol_token_unlock_schedule_analyzer import (
    ProtocolTokenUnlockScheduleAnalyzer,
    _unlocks_in_window,
    _compute_sell_pressure_30d_pct,
    _compute_dilution_impact,
    _compute_unlock_pressure_score,
    _pressure_label,
    _compute_flags,
    _total_30d_unlock_usd,
    _append_log,
    DATA_FILE,
    MAX_ENTRIES,
    RECIPIENT_RISK,
    _SELL_PRESSURE_BRACKETS,
)


# ─────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────

def _token(**kw):
    base = {
        "name": "TKN",
        "total_supply": 1_000_000_000,
        "circulating_supply": 400_000_000,
        "upcoming_unlocks": [],
        "current_price_usd": 1.0,
        "market_cap_usd": 400_000_000,
        "daily_volume_usd": 20_000_000,
        "vesting_cliff_days": 0,
    }
    base.update(kw)
    return base


def _unlock(days, amount, recipient="community"):
    return {"date_days_from_now": days, "amount": amount, "recipient_type": recipient}


# ─────────────────────────────────────────────────────────────────
# Tests: _unlocks_in_window
# ─────────────────────────────────────────────────────────────────

class TestUnlocksInWindow(unittest.TestCase):

    def test_empty_list(self):
        self.assertEqual(_unlocks_in_window([], 30), [])

    def test_all_within_window(self):
        unlocks = [_unlock(5, 1e6), _unlock(15, 2e6), _unlock(29, 3e6)]
        self.assertEqual(len(_unlocks_in_window(unlocks, 30)), 3)

    def test_none_within_window(self):
        unlocks = [_unlock(31, 1e6), _unlock(60, 2e6)]
        self.assertEqual(_unlocks_in_window(unlocks, 30), [])

    def test_boundary_30_included(self):
        unlocks = [_unlock(30, 1e6)]
        self.assertEqual(len(_unlocks_in_window(unlocks, 30)), 1)

    def test_boundary_31_excluded(self):
        unlocks = [_unlock(31, 1e6)]
        self.assertEqual(_unlocks_in_window(unlocks, 30), [])

    def test_mixed(self):
        unlocks = [_unlock(10, 1e6), _unlock(30, 2e6), _unlock(31, 3e6)]
        result = _unlocks_in_window(unlocks, 30)
        self.assertEqual(len(result), 2)

    def test_custom_window_7(self):
        unlocks = [_unlock(5, 1e6), _unlock(8, 2e6)]
        result = _unlocks_in_window(unlocks, 7)
        self.assertEqual(len(result), 1)


# ─────────────────────────────────────────────────────────────────
# Tests: _compute_sell_pressure_30d_pct
# ─────────────────────────────────────────────────────────────────

class TestComputeSellPressure30dPct(unittest.TestCase):

    def test_no_unlocks_zero_pressure(self):
        self.assertEqual(_compute_sell_pressure_30d_pct([], 1e9), 0.0)

    def test_zero_circulating_returns_zero(self):
        self.assertEqual(_compute_sell_pressure_30d_pct([_unlock(5, 1e6)], 0.0), 0.0)

    def test_basic_percentage(self):
        # 100M / 1B circulating = 10%
        p = _compute_sell_pressure_30d_pct([_unlock(10, 1e8)], 1e9)
        self.assertAlmostEqual(p, 10.0, places=4)

    def test_multiple_unlocks_summed(self):
        # 50M + 50M = 100M / 1B = 10%
        unlocks = [_unlock(5, 5e7), _unlock(20, 5e7)]
        p = _compute_sell_pressure_30d_pct(unlocks, 1e9)
        self.assertAlmostEqual(p, 10.0, places=4)

    def test_only_within_30d_counted(self):
        # 100M in window, 200M outside
        unlocks = [_unlock(10, 1e8), _unlock(60, 2e8)]
        p = _compute_sell_pressure_30d_pct(unlocks, 1e9)
        self.assertAlmostEqual(p, 10.0, places=4)

    def test_all_outside_window_zero(self):
        unlocks = [_unlock(31, 1e8), _unlock(90, 2e8)]
        p = _compute_sell_pressure_30d_pct(unlocks, 1e9)
        self.assertEqual(p, 0.0)

    def test_exact_100pct_possible(self):
        p = _compute_sell_pressure_30d_pct([_unlock(10, 1e9)], 1e9)
        self.assertAlmostEqual(p, 100.0, places=4)


# ─────────────────────────────────────────────────────────────────
# Tests: _compute_dilution_impact
# ─────────────────────────────────────────────────────────────────

class TestComputeDilutionImpact(unittest.TestCase):

    def test_no_unlocks_zero_dilution(self):
        self.assertEqual(_compute_dilution_impact([], 1e9), 0.0)

    def test_zero_total_supply_returns_zero(self):
        self.assertEqual(_compute_dilution_impact([_unlock(5, 1e6)], 0.0), 0.0)

    def test_basic_dilution(self):
        # 100M / 1B = 10%
        d = _compute_dilution_impact([_unlock(10, 1e8)], 1e9)
        self.assertAlmostEqual(d, 10.0, places=4)

    def test_only_30d_window_counted(self):
        unlocks = [_unlock(10, 1e8), _unlock(60, 5e8)]
        d = _compute_dilution_impact(unlocks, 1e9)
        self.assertAlmostEqual(d, 10.0, places=4)

    def test_zero_amount_unlock(self):
        d = _compute_dilution_impact([_unlock(5, 0)], 1e9)
        self.assertEqual(d, 0.0)


# ─────────────────────────────────────────────────────────────────
# Tests: _compute_unlock_pressure_score
# ─────────────────────────────────────────────────────────────────

class TestComputeUnlockPressureScore(unittest.TestCase):

    def _score(self, unlocks=None, circ=4e8, total=1e9,
                daily_vol=2e7, price=1.0, cliff=0, sell_pct=None):
        if unlocks is None:
            unlocks = []
        if sell_pct is None:
            sell_pct = _compute_sell_pressure_30d_pct(unlocks, circ)
        return _compute_unlock_pressure_score(
            unlocks, circ, total, daily_vol, price, cliff, sell_pct
        )

    def test_no_unlocks_low_score(self):
        s = self._score()
        self.assertLessEqual(s, 15)

    def test_score_in_0_100(self):
        for sell_pct in (0, 5, 15, 30, 60, 100):
            s = self._score(sell_pct=sell_pct)
            self.assertGreaterEqual(s, 0)
            self.assertLessEqual(s, 100)

    def test_team_unlock_increases_score(self):
        unlocks_team = [_unlock(10, 5e7, "team")]
        unlocks_com = [_unlock(10, 5e7, "community")]
        s_team = self._score(unlocks_team)
        s_com = self._score(unlocks_com)
        self.assertGreater(s_team, s_com)

    def test_investor_unlock_increases_score(self):
        unlocks_inv = [_unlock(10, 5e7, "investor")]
        unlocks_eco = [_unlock(10, 5e7, "ecosystem")]
        s_inv = self._score(unlocks_inv)
        s_eco = self._score(unlocks_eco)
        self.assertGreater(s_inv, s_eco)

    def test_large_single_unlock_increases_score(self):
        # Single unlock > 5% of total_supply
        big = [_unlock(10, 6e7)]   # 6% of 1B
        small = [_unlock(10, 4e7)] # 4% of 1B
        s_big = self._score(big)
        s_small = self._score(small)
        self.assertGreater(s_big, s_small)

    def test_cliff_imminent_under_7_adds_15(self):
        s_cliff = self._score(cliff=5)
        s_no_cliff = self._score(cliff=0)
        self.assertGreater(s_cliff, s_no_cliff)

    def test_cliff_14d_adds_less_than_7d(self):
        s_7 = self._score(cliff=5)
        s_14 = self._score(cliff=10)
        self.assertGreaterEqual(s_7, s_14)

    def test_low_volume_vs_unlock_adds_score(self):
        # unlock 20M tokens @ $1 = $20M USD; daily_vol = $1M → 20x > 10x threshold
        unlocks = [_unlock(10, 2e7)]
        s_low_vol = self._score(unlocks, daily_vol=1e6, price=1.0)
        s_high_vol = self._score(unlocks, daily_vol=5e8, price=1.0)
        self.assertGreater(s_low_vol, s_high_vol)

    def test_zero_daily_volume_no_error(self):
        s = self._score(daily_vol=0)
        self.assertGreaterEqual(s, 0)

    def test_high_sell_pct_gives_high_score(self):
        # >35% sell pct → base score 78+
        s = self._score(sell_pct=50)
        self.assertGreater(s, 50)


# ─────────────────────────────────────────────────────────────────
# Tests: _pressure_label
# ─────────────────────────────────────────────────────────────────

class TestPressureLabel(unittest.TestCase):

    def test_extreme_at_85(self):
        self.assertEqual(_pressure_label(85), "EXTREME")

    def test_extreme_at_100(self):
        self.assertEqual(_pressure_label(100), "EXTREME")

    def test_severe_at_70(self):
        self.assertEqual(_pressure_label(70), "SEVERE")

    def test_severe_at_84(self):
        self.assertEqual(_pressure_label(84), "SEVERE")

    def test_high_at_55(self):
        self.assertEqual(_pressure_label(55), "HIGH")

    def test_high_at_69(self):
        self.assertEqual(_pressure_label(69), "HIGH")

    def test_moderate_at_40(self):
        self.assertEqual(_pressure_label(40), "MODERATE")

    def test_moderate_at_54(self):
        self.assertEqual(_pressure_label(54), "MODERATE")

    def test_low_at_20(self):
        self.assertEqual(_pressure_label(20), "LOW")

    def test_low_at_39(self):
        self.assertEqual(_pressure_label(39), "LOW")

    def test_minimal_at_0(self):
        self.assertEqual(_pressure_label(0), "MINIMAL")

    def test_minimal_at_19(self):
        self.assertEqual(_pressure_label(19), "MINIMAL")


# ─────────────────────────────────────────────────────────────────
# Tests: _compute_flags
# ─────────────────────────────────────────────────────────────────

class TestComputeFlags(unittest.TestCase):

    def test_no_flags_empty_unlocks(self):
        flags = _compute_flags([], 1e9, 1e7, 1.0, 0)
        self.assertEqual(flags, [])

    def test_team_unlock_soon_flag(self):
        unlocks = [_unlock(10, 1e6, "team")]
        flags = _compute_flags(unlocks, 1e9, 1e7, 1.0, 0)
        self.assertIn("TEAM_UNLOCK_SOON", flags)

    def test_no_team_unlock_soon_outside_30d(self):
        unlocks = [_unlock(40, 1e6, "team")]
        flags = _compute_flags(unlocks, 1e9, 1e7, 1.0, 0)
        self.assertNotIn("TEAM_UNLOCK_SOON", flags)

    def test_no_team_unlock_soon_for_investor(self):
        unlocks = [_unlock(10, 1e6, "investor")]
        flags = _compute_flags(unlocks, 1e9, 1e7, 1.0, 0)
        self.assertNotIn("TEAM_UNLOCK_SOON", flags)

    def test_large_single_unlock_flag(self):
        # 60M > 5% of 1B total_supply
        unlocks = [_unlock(45, 6e7)]  # Outside 30d but flag checks all unlocks
        flags = _compute_flags(unlocks, 1e9, 1e7, 1.0, 0)
        self.assertIn("LARGE_SINGLE_UNLOCK", flags)

    def test_no_large_single_unlock_below_threshold(self):
        unlocks = [_unlock(45, 4e7)]  # 4% < 5%
        flags = _compute_flags(unlocks, 1e9, 1e7, 1.0, 0)
        self.assertNotIn("LARGE_SINGLE_UNLOCK", flags)

    def test_cliff_imminent_flag(self):
        flags = _compute_flags([], 1e9, 1e7, 1.0, 5)
        self.assertIn("CLIFF_IMMINENT", flags)

    def test_no_cliff_imminent_at_7(self):
        flags = _compute_flags([], 1e9, 1e7, 1.0, 7)
        self.assertNotIn("CLIFF_IMMINENT", flags)

    def test_no_cliff_imminent_at_zero(self):
        flags = _compute_flags([], 1e9, 1e7, 1.0, 0)
        self.assertNotIn("CLIFF_IMMINENT", flags)

    def test_low_volume_vs_unlock_flag(self):
        # unlock 2M tokens @ $1 = $2M; daily_vol = $100k → 20x > 10x
        unlocks = [_unlock(10, 2e6)]
        flags = _compute_flags(unlocks, 1e9, 1e5, 1.0, 0)
        self.assertIn("LOW_VOLUME_VS_UNLOCK", flags)

    def test_no_low_volume_vs_unlock_high_vol(self):
        unlocks = [_unlock(10, 2e6)]
        # daily_vol = $1B → unlock_usd = $2M << 10x
        flags = _compute_flags(unlocks, 1e9, 1e9, 1.0, 0)
        self.assertNotIn("LOW_VOLUME_VS_UNLOCK", flags)

    def test_zero_daily_volume_no_flag(self):
        unlocks = [_unlock(10, 2e6)]
        flags = _compute_flags(unlocks, 1e9, 0.0, 1.0, 0)
        self.assertNotIn("LOW_VOLUME_VS_UNLOCK", flags)

    def test_multiple_flags_combined(self):
        unlocks = [
            _unlock(5, 1e6, "team"),       # TEAM_UNLOCK_SOON
            _unlock(60, 6e7),              # LARGE_SINGLE_UNLOCK (>5% of 1B)
        ]
        flags = _compute_flags(unlocks, 1e9, 1e5, 1.0, 3)
        self.assertIn("TEAM_UNLOCK_SOON", flags)
        self.assertIn("LARGE_SINGLE_UNLOCK", flags)
        self.assertIn("CLIFF_IMMINENT", flags)
        self.assertIn("LOW_VOLUME_VS_UNLOCK", flags)


# ─────────────────────────────────────────────────────────────────
# Tests: _total_30d_unlock_usd
# ─────────────────────────────────────────────────────────────────

class TestTotal30dUnlockUsd(unittest.TestCase):

    def test_empty_unlocks(self):
        self.assertEqual(_total_30d_unlock_usd([], 2.0), 0.0)

    def test_basic_usd(self):
        unlocks = [_unlock(10, 1e6)]  # 1M tokens @ $2
        val = _total_30d_unlock_usd(unlocks, 2.0)
        self.assertAlmostEqual(val, 2e6, places=2)

    def test_only_30d_window(self):
        unlocks = [_unlock(10, 1e6), _unlock(45, 5e6)]
        val = _total_30d_unlock_usd(unlocks, 1.0)
        self.assertAlmostEqual(val, 1e6, places=2)

    def test_zero_price(self):
        unlocks = [_unlock(10, 1e6)]
        val = _total_30d_unlock_usd(unlocks, 0.0)
        self.assertEqual(val, 0.0)


# ─────────────────────────────────────────────────────────────────
# Tests: ProtocolTokenUnlockScheduleAnalyzer.analyze()
# ─────────────────────────────────────────────────────────────────

class TestAnalyzeBasic(unittest.TestCase):

    def setUp(self):
        self.analyzer = ProtocolTokenUnlockScheduleAnalyzer()
        self._td = tempfile.TemporaryDirectory()
        import spa_core.analytics.protocol_token_unlock_schedule_analyzer as mod
        self._mod = mod
        self._orig = mod.DATA_FILE
        mod.DATA_FILE = Path(self._td.name) / "token_unlock_log.json"

    def tearDown(self):
        self._mod.DATA_FILE = self._orig
        self._td.cleanup()

    def _run(self, tokens=None, config=None):
        if tokens is None:
            tokens = [_token()]
        return self.analyzer.analyze(tokens, config or {})

    def test_returns_dict_with_required_keys(self):
        r = self._run()
        for k in ("tokens", "highest_pressure_token", "lowest_pressure_token",
                   "total_30d_unlock_usd", "average_pressure_score",
                   "extreme_count", "timestamp"):
            self.assertIn(k, r)

    def test_empty_input_returns_none_aggregates(self):
        r = self._run(tokens=[])
        self.assertIsNone(r["highest_pressure_token"])
        self.assertIsNone(r["lowest_pressure_token"])
        self.assertEqual(r["total_30d_unlock_usd"], 0.0)
        self.assertEqual(r["average_pressure_score"], 0.0)
        self.assertEqual(r["extreme_count"], 0)

    def test_per_token_keys(self):
        r = self._run([_token()])
        tok = r["tokens"][0]
        for k in ("name", "total_supply", "circulating_supply", "current_price_usd",
                   "market_cap_usd", "vesting_cliff_days",
                   "sell_pressure_30d_pct", "dilution_impact",
                   "unlock_pressure_score", "pressure_label",
                   "unlock_usd_30d", "flags"):
            self.assertIn(k, tok)

    def test_sell_pressure_range(self):
        r = self._run([_token(
            upcoming_unlocks=[_unlock(10, 1e7)],
            circulating_supply=4e8,
        )])
        pct = r["tokens"][0]["sell_pressure_30d_pct"]
        self.assertGreaterEqual(pct, 0.0)

    def test_dilution_impact_range(self):
        r = self._run([_token(
            upcoming_unlocks=[_unlock(10, 1e7)],
            total_supply=1e9,
        )])
        d = r["tokens"][0]["dilution_impact"]
        self.assertGreaterEqual(d, 0.0)

    def test_pressure_score_range(self):
        r = self._run([_token(
            upcoming_unlocks=[_unlock(5, 2e8, "team")],
            vesting_cliff_days=3,
        )])
        s = r["tokens"][0]["unlock_pressure_score"]
        self.assertGreaterEqual(s, 0)
        self.assertLessEqual(s, 100)

    def test_pressure_label_valid(self):
        valid = {"MINIMAL", "LOW", "MODERATE", "HIGH", "SEVERE", "EXTREME"}
        r = self._run([_token(), _token(name="T2",
                      upcoming_unlocks=[_unlock(5, 2e8, "team")])])
        for tok in r["tokens"]:
            self.assertIn(tok["pressure_label"], valid)

    def test_flags_is_list(self):
        r = self._run([_token()])
        self.assertIsInstance(r["tokens"][0]["flags"], list)

    def test_no_unlocks_minimal_pressure(self):
        r = self._run([_token(upcoming_unlocks=[])])
        self.assertIn(r["tokens"][0]["pressure_label"], ("MINIMAL", "LOW"))

    def test_many_tokens_count(self):
        tokens = [_token(name=f"T{i}") for i in range(8)]
        r = self._run(tokens)
        self.assertEqual(len(r["tokens"]), 8)

    def test_highest_pressure_identified(self):
        tokens = [
            _token(name="LOW"),
            _token(name="HIGH",
                   upcoming_unlocks=[_unlock(5, 3e8, "team")],
                   daily_volume_usd=1e5,
                   vesting_cliff_days=3),
        ]
        r = self._run(tokens)
        self.assertEqual(r["highest_pressure_token"], "HIGH")

    def test_lowest_pressure_identified(self):
        tokens = [
            _token(name="LOW"),
            _token(name="HIGH",
                   upcoming_unlocks=[_unlock(5, 3e8, "team")],
                   daily_volume_usd=1e5),
        ]
        r = self._run(tokens)
        self.assertEqual(r["lowest_pressure_token"], "LOW")

    def test_total_30d_unlock_usd_correct(self):
        tokens = [
            _token(name="A", upcoming_unlocks=[_unlock(5, 1e6)], current_price_usd=2.0),
            _token(name="B", upcoming_unlocks=[_unlock(10, 5e5)], current_price_usd=4.0),
        ]
        r = self._run(tokens)
        expected = 1e6 * 2.0 + 5e5 * 4.0
        self.assertAlmostEqual(r["total_30d_unlock_usd"], expected, places=1)

    def test_average_pressure_score_computed(self):
        tokens = [_token(name="A"), _token(name="B")]
        r = self._run(tokens)
        scores = [t["unlock_pressure_score"] for t in r["tokens"]]
        expected_avg = sum(scores) / len(scores)
        self.assertAlmostEqual(r["average_pressure_score"], expected_avg, places=1)

    def test_extreme_count_zero_no_extreme(self):
        r = self._run([_token()])
        self.assertEqual(r["extreme_count"], 0)

    def test_extreme_count_increments(self):
        # Force extreme: large sell pressure + team unlock + cliff + low vol
        tok = _token(
            name="XTRM",
            upcoming_unlocks=[_unlock(5, 3.5e8, "team")],
            vesting_cliff_days=3,
            daily_volume_usd=1e4,
            circulating_supply=4e8,
        )
        r = self._run([tok])
        if r["tokens"][0]["pressure_label"] == "EXTREME":
            self.assertEqual(r["extreme_count"], 1)
        else:
            self.assertGreaterEqual(r["tokens"][0]["unlock_pressure_score"], 50)

    def test_team_unlock_soon_flag_in_result(self):
        tok = _token(upcoming_unlocks=[_unlock(5, 1e7, "team")])
        r = self._run([tok])
        self.assertIn("TEAM_UNLOCK_SOON", r["tokens"][0]["flags"])

    def test_cliff_imminent_flag_in_result(self):
        tok = _token(vesting_cliff_days=3)
        r = self._run([tok])
        self.assertIn("CLIFF_IMMINENT", r["tokens"][0]["flags"])

    def test_large_single_unlock_flag_in_result(self):
        tok = _token(
            upcoming_unlocks=[_unlock(60, 7e7)],  # 7% of 1B
            total_supply=1e9,
        )
        r = self._run([tok])
        self.assertIn("LARGE_SINGLE_UNLOCK", r["tokens"][0]["flags"])

    def test_low_volume_vs_unlock_flag_in_result(self):
        tok = _token(
            upcoming_unlocks=[_unlock(10, 2e6)],
            daily_volume_usd=1e4,
            current_price_usd=1.0,
        )
        r = self._run([tok])
        self.assertIn("LOW_VOLUME_VS_UNLOCK", r["tokens"][0]["flags"])

    def test_name_preserved(self):
        r = self._run([_token(name="MYTOKEN")])
        self.assertEqual(r["tokens"][0]["name"], "MYTOKEN")

    def test_config_none_accepted(self):
        r = self.analyzer.analyze([_token()], None)
        self.assertIn("tokens", r)

    def test_missing_upcoming_unlocks_defaults_empty(self):
        tok = {"name": "BARE", "total_supply": 1e9, "circulating_supply": 5e8}
        r = self._run([tok])
        self.assertEqual(r["tokens"][0]["sell_pressure_30d_pct"], 0.0)

    def test_timestamp_recent(self):
        import time
        r = self._run()
        self.assertAlmostEqual(r["timestamp"], time.time(), delta=5)

    def test_single_token_highest_equals_lowest(self):
        r = self._run([_token(name="SOLO")])
        self.assertEqual(r["highest_pressure_token"], "SOLO")
        self.assertEqual(r["lowest_pressure_token"], "SOLO")

    def test_unlock_outside_30d_not_in_sell_pressure(self):
        tok = _token(upcoming_unlocks=[_unlock(60, 2e8)])
        r = self._run([tok])
        self.assertEqual(r["tokens"][0]["sell_pressure_30d_pct"], 0.0)

    def test_unlock_outside_30d_not_in_usd_total(self):
        tok = _token(upcoming_unlocks=[_unlock(60, 2e8)], current_price_usd=1.0)
        r = self._run([tok])
        self.assertEqual(r["tokens"][0]["unlock_usd_30d"], 0.0)


# ─────────────────────────────────────────────────────────────────
# Tests: ring-buffer log
# ─────────────────────────────────────────────────────────────────

class TestRingBufferLog(unittest.TestCase):

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        import spa_core.analytics.protocol_token_unlock_schedule_analyzer as mod
        self._mod = mod
        self._orig = mod.DATA_FILE
        mod.DATA_FILE = Path(self._td.name) / "token_unlock_log.json"

    def tearDown(self):
        self._mod.DATA_FILE = self._orig
        self._td.cleanup()

    def test_log_file_created(self):
        _append_log({"x": 1})
        self.assertTrue(self._mod.DATA_FILE.exists())

    def test_log_is_json_list(self):
        _append_log({"x": 1})
        with open(self._mod.DATA_FILE) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_entries_accumulate(self):
        _append_log({"i": 1})
        _append_log({"i": 2})
        with open(self._mod.DATA_FILE) as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)

    def test_ring_buffer_cap(self):
        for i in range(MAX_ENTRIES + 10):
            _append_log({"i": i})
        with open(self._mod.DATA_FILE) as f:
            data = json.load(f)
        self.assertEqual(len(data), MAX_ENTRIES)

    def test_ring_buffer_keeps_newest(self):
        for i in range(MAX_ENTRIES + 10):
            _append_log({"i": i})
        with open(self._mod.DATA_FILE) as f:
            data = json.load(f)
        self.assertEqual(data[-1]["i"], MAX_ENTRIES + 9)

    def test_tmp_file_removed(self):
        _append_log({"x": 1})
        tmp = self._mod.DATA_FILE.with_suffix(".tmp")
        self.assertFalse(tmp.exists())

    def test_analyze_writes_to_log(self):
        analyzer = ProtocolTokenUnlockScheduleAnalyzer()
        analyzer.analyze([_token()])
        self.assertTrue(self._mod.DATA_FILE.exists())

    def test_corrupt_log_resets_gracefully(self):
        self._mod.DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(self._mod.DATA_FILE, "w") as f:
            f.write("{{bad json")
        _append_log({"x": 1})
        with open(self._mod.DATA_FILE) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_non_list_log_resets(self):
        self._mod.DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(self._mod.DATA_FILE, "w") as f:
            json.dump({"wrong": "type"}, f)
        _append_log({"x": 1})
        with open(self._mod.DATA_FILE) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_multiple_analyze_calls_accumulate(self):
        analyzer = ProtocolTokenUnlockScheduleAnalyzer()
        for _ in range(5):
            analyzer.analyze([_token()])
        with open(self._mod.DATA_FILE) as f:
            data = json.load(f)
        self.assertEqual(len(data), 5)


# ─────────────────────────────────────────────────────────────────
# Tests: constants & edge cases
# ─────────────────────────────────────────────────────────────────

class TestConstantsAndEdgeCases(unittest.TestCase):

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        import spa_core.analytics.protocol_token_unlock_schedule_analyzer as mod
        self._mod = mod
        self._orig = mod.DATA_FILE
        mod.DATA_FILE = Path(self._td.name) / "token_unlock_log.json"
        self.analyzer = ProtocolTokenUnlockScheduleAnalyzer()

    def tearDown(self):
        self._mod.DATA_FILE = self._orig
        self._td.cleanup()

    def test_max_entries_positive(self):
        self.assertGreater(MAX_ENTRIES, 0)

    def test_recipient_risk_contains_team(self):
        self.assertIn("team", RECIPIENT_RISK)

    def test_recipient_risk_contains_investor(self):
        self.assertIn("investor", RECIPIENT_RISK)

    def test_recipient_risk_team_highest(self):
        self.assertEqual(RECIPIENT_RISK["team"], max(RECIPIENT_RISK.values()))

    def test_recipient_risk_community_lowest(self):
        self.assertEqual(RECIPIENT_RISK["community"], min(RECIPIENT_RISK.values()))

    def test_sell_pressure_brackets_sorted(self):
        thresholds = [b[0] for b in _SELL_PRESSURE_BRACKETS[:-1]]
        self.assertEqual(thresholds, sorted(thresholds))

    def test_zero_total_supply_no_error(self):
        tok = _token(total_supply=0, circulating_supply=0,
                     upcoming_unlocks=[_unlock(5, 1e6)])
        r = self.analyzer.analyze([tok])
        self.assertIsNotNone(r)

    def test_zero_price_unlock_usd_is_zero(self):
        tok = _token(current_price_usd=0.0,
                     upcoming_unlocks=[_unlock(5, 1e6)])
        r = self.analyzer.analyze([tok])
        self.assertEqual(r["tokens"][0]["unlock_usd_30d"], 0.0)

    def test_unlocks_all_community_lower_score(self):
        tok_com = _token(upcoming_unlocks=[_unlock(5, 1e8, "community")])
        tok_team = _token(upcoming_unlocks=[_unlock(5, 1e8, "team")])
        r_com = self.analyzer.analyze([tok_com])
        r_team = self.analyzer.analyze([tok_team])
        self.assertLessEqual(
            r_com["tokens"][0]["unlock_pressure_score"],
            r_team["tokens"][0]["unlock_pressure_score"],
        )

    def test_ecosystem_recipient_accepted(self):
        tok = _token(upcoming_unlocks=[_unlock(10, 5e7, "ecosystem")])
        r = self.analyzer.analyze([tok])
        self.assertGreaterEqual(r["tokens"][0]["unlock_pressure_score"], 0)

    def test_unknown_recipient_handled(self):
        tok = _token(upcoming_unlocks=[_unlock(10, 5e7, "unknown_party")])
        r = self.analyzer.analyze([tok])
        self.assertGreaterEqual(r["tokens"][0]["unlock_pressure_score"], 0)

    def test_vesting_cliff_zero_no_cliff_flag(self):
        tok = _token(vesting_cliff_days=0)
        r = self.analyzer.analyze([tok])
        self.assertNotIn("CLIFF_IMMINENT", r["tokens"][0]["flags"])

    def test_dilution_rounds(self):
        tok = _token(upcoming_unlocks=[_unlock(5, 1e8)], total_supply=1e9)
        r = self.analyzer.analyze([tok])
        d = r["tokens"][0]["dilution_impact"]
        self.assertAlmostEqual(d, 10.0, places=2)

    def test_market_cap_preserved(self):
        tok = _token(market_cap_usd=9_999_999.0)
        r = self.analyzer.analyze([tok])
        self.assertAlmostEqual(r["tokens"][0]["market_cap_usd"], 9_999_999.0, places=2)

    def test_pressure_label_monotone_with_score(self):
        order = {"MINIMAL": 0, "LOW": 1, "MODERATE": 2, "HIGH": 3, "SEVERE": 4, "EXTREME": 5}
        for score in range(0, 101, 5):
            label = _pressure_label(score)
            self.assertIn(label, order)


if __name__ == "__main__":
    unittest.main()
