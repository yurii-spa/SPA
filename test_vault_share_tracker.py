"""
Tests for MP-775: VaultShareTracker
=====================================
70 tests — unittest only, temporary directories for log isolation.
"""

import json
import os
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(_HERE))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from spa_core.analytics.vault_share_tracker import (
    VaultShareTracker,
    _atomic_write,
    _load_log,
    compute_dilution_risk,
    compute_nav_per_share,
    compute_price_change_pct,
    compute_vault_apy_from_share_price,
    detect_dilution_events,
    DILUTION_DROP_THRESHOLD_PCT,
    DILUTION_RISK_HIGH,
    DILUTION_RISK_LOW,
    DILUTION_RISK_MEDIUM,
    LOG_MAX_ENTRIES,
)


# ---------------------------------------------------------------------------
# TestComputePriceChangePct  (10 tests)
# ---------------------------------------------------------------------------

class TestComputePriceChangePct(unittest.TestCase):

    def test_empty_list_returns_none(self):
        self.assertIsNone(compute_price_change_pct([], 7))

    def test_single_element_returns_none(self):
        self.assertIsNone(compute_price_change_pct([1.0], 7))

    def test_two_elements_7d(self):
        # Only 2 elements → uses all available window
        result = compute_price_change_pct([1.0, 1.1], 7)
        self.assertAlmostEqual(result, 10.0, places=4)

    def test_exact_7d_window(self):
        # 8 prices → uses last 8 (index -8 to -1 = 7 days)
        prices = [1.0] * 7 + [1.0, 1.07]  # last 7-day change = 7%
        result = compute_price_change_pct(prices, 7)
        self.assertAlmostEqual(result, 7.0, places=4)

    def test_insufficient_history_uses_full_range(self):
        # Only 4 prices for a 7-day query → uses all 4
        prices = [1.0, 1.01, 1.02, 1.05]
        result = compute_price_change_pct(prices, 7)
        self.assertAlmostEqual(result, 5.0, places=4)

    def test_positive_change(self):
        prices = [1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.1]
        result = compute_price_change_pct(prices, 7)
        self.assertGreater(result, 0)

    def test_negative_change(self):
        prices = [1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 0.9]
        result = compute_price_change_pct(prices, 7)
        self.assertLess(result, 0)

    def test_zero_start_returns_none(self):
        self.assertIsNone(compute_price_change_pct([0.0, 1.0], 7))

    def test_30d_window(self):
        prices = [1.0] * 30 + [1.2]  # 31 prices → 30-day change = 20%
        result = compute_price_change_pct(prices, 30)
        self.assertAlmostEqual(result, 20.0, places=4)

    def test_result_is_float(self):
        result = compute_price_change_pct([1.0, 1.1], 7)
        self.assertIsInstance(result, float)


# ---------------------------------------------------------------------------
# TestDetectDilutionEvents  (12 tests)
# ---------------------------------------------------------------------------

class TestDetectDilutionEvents(unittest.TestCase):

    def _event(self, ts="2026-06-01T00:00:00+00:00", minted=1000, usd=1000):
        return {"timestamp": ts, "shares_minted": minted, "usd_value": usd}

    def test_no_deposit_events_returns_empty(self):
        self.assertEqual(detect_dilution_events([1.0, 0.99], []), [])

    def test_empty_history_returns_empty(self):
        self.assertEqual(detect_dilution_events([], [self._event()]), [])

    def test_single_price_returns_empty(self):
        self.assertEqual(detect_dilution_events([1.0], [self._event()]), [])

    def test_small_drop_not_dilution(self):
        # 1% drop, threshold is >2%
        events = detect_dilution_events([1.0, 0.99], [self._event()])
        self.assertEqual(events, [])

    def test_below_threshold_not_dilution(self):
        # 1.8% drop (0.982): clearly below 2% threshold → NOT dilution
        # Note: 1.0-0.98 gives 2.000...018% in float (strictly > 2), so use 0.982
        events = detect_dilution_events([1.0, 0.982], [self._event()])
        self.assertEqual(events, [])

    def test_above_threshold_is_dilution(self):
        # >2% drop: IS dilution
        events = detect_dilution_events([1.0, 0.979], [self._event()])
        self.assertEqual(len(events), 1)

    def test_price_increase_not_dilution(self):
        events = detect_dilution_events([1.0, 1.05], [self._event()])
        self.assertEqual(events, [])

    def test_dilution_event_has_required_fields(self):
        events = detect_dilution_events([1.0, 0.97], [self._event()])
        self.assertEqual(len(events), 1)
        required = ["timestamp", "shares_minted", "usd_value",
                    "price_before", "price_after", "drop_pct"]
        for field in required:
            self.assertIn(field, events[0], msg=f"Missing: {field}")

    def test_drop_pct_computed_correctly(self):
        # 1.0 → 0.97: drop = 3%
        events = detect_dilution_events([1.0, 0.97], [self._event()])
        self.assertAlmostEqual(events[0]["drop_pct"], 3.0, places=4)

    def test_price_before_and_after_in_event(self):
        events = detect_dilution_events([1.0, 0.97], [self._event()])
        self.assertAlmostEqual(events[0]["price_before"], 1.0)
        self.assertAlmostEqual(events[0]["price_after"], 0.97)

    def test_zero_price_before_skipped(self):
        events = detect_dilution_events([0.0, 0.97], [self._event()])
        self.assertEqual(events, [])

    def test_multiple_deposit_events_multiple_dilutions(self):
        prices = [1.0, 0.97, 0.94]
        events_in = [self._event("t1"), self._event("t2")]
        dilutions = detect_dilution_events(prices, events_in)
        self.assertGreaterEqual(len(dilutions), 1)


# ---------------------------------------------------------------------------
# TestComputeDilutionRisk  (6 tests)
# ---------------------------------------------------------------------------

class TestComputeDilutionRisk(unittest.TestCase):

    def test_zero_is_low(self):
        self.assertEqual(compute_dilution_risk(0), DILUTION_RISK_LOW)

    def test_one_is_medium(self):
        self.assertEqual(compute_dilution_risk(1), DILUTION_RISK_MEDIUM)

    def test_two_is_medium(self):
        self.assertEqual(compute_dilution_risk(2), DILUTION_RISK_MEDIUM)

    def test_three_is_high(self):
        self.assertEqual(compute_dilution_risk(3), DILUTION_RISK_HIGH)

    def test_ten_is_high(self):
        self.assertEqual(compute_dilution_risk(10), DILUTION_RISK_HIGH)

    def test_constants_are_strings(self):
        self.assertEqual(DILUTION_RISK_LOW, "LOW")
        self.assertEqual(DILUTION_RISK_MEDIUM, "MEDIUM")
        self.assertEqual(DILUTION_RISK_HIGH, "HIGH")


# ---------------------------------------------------------------------------
# TestComputeNavPerShare  (8 tests)
# ---------------------------------------------------------------------------

class TestComputeNavPerShare(unittest.TestCase):

    def test_zero_shares_returns_none(self):
        self.assertIsNone(compute_nav_per_share(1_000_000.0, 0))

    def test_basic_nav(self):
        nav = compute_nav_per_share(1_000.0, 1_000.0)
        self.assertAlmostEqual(nav, 1.0, places=6)

    def test_more_assets_than_shares(self):
        nav = compute_nav_per_share(2_000.0, 1_000.0)
        self.assertAlmostEqual(nav, 2.0, places=6)

    def test_more_shares_than_assets(self):
        nav = compute_nav_per_share(1_000.0, 2_000.0)
        self.assertAlmostEqual(nav, 0.5, places=6)

    def test_large_values(self):
        nav = compute_nav_per_share(5_000_000.0, 4_975_000.0)
        self.assertGreater(nav, 1.0)

    def test_result_is_float(self):
        nav = compute_nav_per_share(1000.0, 900.0)
        self.assertIsInstance(nav, float)

    def test_precision_8_decimal_places(self):
        nav = compute_nav_per_share(1.0, 3.0)
        # 1/3 rounded to 8 places
        self.assertAlmostEqual(nav, 0.33333333, places=7)

    def test_equal_assets_and_shares_nav_one(self):
        nav = compute_nav_per_share(999_999.0, 999_999.0)
        self.assertAlmostEqual(nav, 1.0, places=6)


# ---------------------------------------------------------------------------
# TestComputeVaultApyFromSharePrice  (10 tests)
# ---------------------------------------------------------------------------

class TestComputeVaultApyFromSharePrice(unittest.TestCase):

    def test_empty_returns_none(self):
        self.assertIsNone(compute_vault_apy_from_share_price([]))

    def test_single_element_returns_none(self):
        self.assertIsNone(compute_vault_apy_from_share_price([1.0]))

    def test_flat_price_returns_zero(self):
        result = compute_vault_apy_from_share_price([1.0, 1.0])
        self.assertAlmostEqual(result, 0.0, places=6)

    def test_positive_growth_positive_apy(self):
        prices = [1.0] + [1.001] * 365
        result = compute_vault_apy_from_share_price(prices)
        self.assertGreater(result, 0)

    def test_negative_growth_negative_apy(self):
        prices = [1.0, 0.5]  # crashed 50%
        result = compute_vault_apy_from_share_price(prices)
        self.assertLess(result, 0)

    def test_zero_start_returns_none(self):
        self.assertIsNone(compute_vault_apy_from_share_price([0.0, 1.0]))

    def test_negative_ratio_returns_none(self):
        self.assertIsNone(compute_vault_apy_from_share_price([1.0, -0.5]))

    def test_result_is_float(self):
        result = compute_vault_apy_from_share_price([1.0, 1.1])
        self.assertIsInstance(result, float)

    def test_result_is_rounded_to_6_places(self):
        result = compute_vault_apy_from_share_price([1.0, 1.0001, 1.0002])
        # Just check it doesn't have more than 6 decimal places
        decimal_places = len(str(result).split(".")[-1]) if "." in str(result) else 0
        self.assertLessEqual(decimal_places, 6)

    def test_annualised_correctly(self):
        # 100-day history: price goes from 1.0 to 1.05
        prices = [1.0 + 0.05 * i / 99 for i in range(100)]
        result = compute_vault_apy_from_share_price(prices)
        # Annualised should be approximately 5% * (365/99) ≈ 18.4% but due to compounding
        # Just verify it's positive and larger than 5%
        self.assertGreater(result, 5.0)


# ---------------------------------------------------------------------------
# TestVaultShareTrackerTrack  (12 tests)
# ---------------------------------------------------------------------------

class TestVaultShareTrackerTrack(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.log = os.path.join(self.tmpdir.name, "vault_log.json")
        self.tracker = VaultShareTracker(log_path=self.log)

    def tearDown(self):
        self.tmpdir.cleanup()

    def _vault(self, vid="yearn-usdc", history=None, events=None,
               total_assets=None, total_shares=None):
        d = {"vault_id": vid, "share_price_history": history or [1.0, 1.01, 1.02]}
        d["deposit_events"] = events or []
        if total_assets is not None:
            d["total_assets"] = total_assets
        if total_shares is not None:
            d["total_shares"] = total_shares
        return d

    def test_track_returns_dict(self):
        result = self.tracker.track(self._vault())
        self.assertIsInstance(result, dict)

    def test_vault_id_in_result(self):
        result = self.tracker.track(self._vault("my-vault"))
        self.assertEqual(result["vault_id"], "my-vault")

    def test_7d_change_computed(self):
        result = self.tracker.track(self._vault(history=[1.0, 1.07]))
        self.assertAlmostEqual(result["share_price_change_7d_pct"], 7.0, places=4)

    def test_30d_change_computed(self):
        prices = [1.0] * 30 + [1.2]
        result = self.tracker.track(self._vault(history=prices))
        self.assertAlmostEqual(result["share_price_change_30d_pct"], 20.0, places=4)

    def test_dilution_events_in_result(self):
        result = self.tracker.track(self._vault())
        self.assertIn("dilution_events", result)
        self.assertIsInstance(result["dilution_events"], list)

    def test_dilution_risk_in_result(self):
        result = self.tracker.track(self._vault())
        self.assertIn("dilution_risk", result)
        self.assertIn(result["dilution_risk"], ["LOW", "MEDIUM", "HIGH"])

    def test_nav_per_share_when_provided(self):
        result = self.tracker.track(self._vault(total_assets=10000.0, total_shares=9800.0))
        self.assertIsNotNone(result["nav_per_share"])
        self.assertAlmostEqual(result["nav_per_share"], 10000 / 9800, places=5)

    def test_nav_none_when_not_provided(self):
        result = self.tracker.track(self._vault())
        self.assertIsNone(result["nav_per_share"])

    def test_apy_computed(self):
        result = self.tracker.track(self._vault(history=[1.0, 1.001, 1.002]))
        self.assertIsNotNone(result["vault_apy_from_share_price"])

    def test_history_length_in_result(self):
        result = self.tracker.track(self._vault(history=[1.0, 1.01, 1.02]))
        self.assertEqual(result["history_length"], 3)

    def test_log_file_created(self):
        self.tracker.track(self._vault())
        self.assertTrue(os.path.exists(self.log))

    def test_log_ring_buffer_cap_100(self):
        for i in range(105):
            self.tracker.track(self._vault(vid=f"vault-{i}"))
        with open(self.log) as fh:
            log = json.load(fh)
        self.assertLessEqual(len(log), LOG_MAX_ENTRIES)


# ---------------------------------------------------------------------------
# TestGetDilutionEvents  (6 tests)
# ---------------------------------------------------------------------------

class TestGetDilutionEvents(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.tracker = VaultShareTracker(
            log_path=os.path.join(self.tmpdir.name, "log.json")
        )

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_empty_before_track(self):
        self.assertEqual(self.tracker.get_dilution_events(), [])

    def test_no_dilutions_returns_empty(self):
        self.tracker.track({
            "vault_id": "v1",
            "share_price_history": [1.0, 1.01],
            "deposit_events": [],
        })
        self.assertEqual(self.tracker.get_dilution_events(), [])

    def test_dilution_detected_returns_events(self):
        self.tracker.track({
            "vault_id": "v1",
            "share_price_history": [1.0, 0.97],
            "deposit_events": [{"timestamp": "t", "shares_minted": 1000, "usd_value": 1000}],
        })
        events = self.tracker.get_dilution_events()
        self.assertEqual(len(events), 1)

    def test_returns_from_latest_track(self):
        # Track vault A (dilution), then vault B (no dilution) — result from B
        self.tracker.track({
            "vault_id": "A",
            "share_price_history": [1.0, 0.97],
            "deposit_events": [{"timestamp": "t", "shares_minted": 1000, "usd_value": 1000}],
        })
        self.tracker.track({
            "vault_id": "B",
            "share_price_history": [1.0, 1.01],
            "deposit_events": [],
        })
        self.assertEqual(self.tracker.get_dilution_events(), [])

    def test_dilution_event_structure(self):
        self.tracker.track({
            "vault_id": "v1",
            "share_price_history": [1.0, 0.97],
            "deposit_events": [{"timestamp": "2026-06-01", "shares_minted": 500, "usd_value": 500}],
        })
        events = self.tracker.get_dilution_events()
        self.assertIn("drop_pct", events[0])
        self.assertIn("price_before", events[0])
        self.assertIn("price_after", events[0])

    def test_returns_list(self):
        self.tracker.track({
            "vault_id": "v1",
            "share_price_history": [1.0, 1.01],
            "deposit_events": [],
        })
        self.assertIsInstance(self.tracker.get_dilution_events(), list)


# ---------------------------------------------------------------------------
# TestGetVaultApy  (6 tests)
# ---------------------------------------------------------------------------

class TestGetVaultApy(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.tracker = VaultShareTracker(
            log_path=os.path.join(self.tmpdir.name, "log.json")
        )

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_none_before_track(self):
        self.assertIsNone(self.tracker.get_vault_apy())

    def test_apy_after_growing_vault(self):
        self.tracker.track({
            "vault_id": "v1",
            "share_price_history": [1.0, 1.001, 1.002, 1.003],
            "deposit_events": [],
        })
        apy = self.tracker.get_vault_apy()
        self.assertIsNotNone(apy)
        self.assertGreater(apy, 0)

    def test_flat_price_returns_zero_apy(self):
        self.tracker.track({
            "vault_id": "v1",
            "share_price_history": [1.0, 1.0, 1.0],
            "deposit_events": [],
        })
        self.assertAlmostEqual(self.tracker.get_vault_apy(), 0.0, places=4)

    def test_shrinking_vault_negative_apy(self):
        self.tracker.track({
            "vault_id": "v1",
            "share_price_history": [1.0, 0.5],
            "deposit_events": [],
        })
        self.assertLess(self.tracker.get_vault_apy(), 0)

    def test_returns_float_or_none(self):
        self.tracker.track({
            "vault_id": "v1",
            "share_price_history": [1.0, 1.1],
            "deposit_events": [],
        })
        apy = self.tracker.get_vault_apy()
        self.assertIsNotNone(apy)
        self.assertIsInstance(apy, float)

    def test_apy_from_latest_track_only(self):
        self.tracker.track({
            "vault_id": "A",
            "share_price_history": [1.0, 2.0],
            "deposit_events": [],
        })
        self.tracker.track({
            "vault_id": "B",
            "share_price_history": [1.0, 1.0],
            "deposit_events": [],
        })
        self.assertAlmostEqual(self.tracker.get_vault_apy(), 0.0, places=4)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main()
