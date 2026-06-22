"""
Tests for MP-667: OraclePriceMonitor
Run: python3 -m unittest spa_core.tests.test_oracle_price_monitor -v
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.analytics.oracle_price_monitor import (
    OracleFeed,
    OracleHealth,
    OraclePriceMonitor,
    MAX_ENTRIES,
)

# Reference "now" for deterministic testing
NOW = 1_700_000_000.0


def _feed(
    feed_id="feed_eth",
    protocol="Chainlink",
    asset="ETH/USD",
    reported_price=2000.0,
    reference_price=2000.0,
    age=0.0,        # seconds old
    heartbeat=3600,
):
    return OracleFeed(
        feed_id=feed_id,
        protocol=protocol,
        asset=asset,
        reported_price=reported_price,
        reference_price=reference_price,
        last_update_ts=NOW - age,
        current_ts=NOW,
        heartbeat_seconds=heartbeat,
    )


def _monitor(tmp_dir=None):
    if tmp_dir:
        return OraclePriceMonitor(data_file=Path(tmp_dir) / "oracle_log.json")
    return OraclePriceMonitor()


# ---------------------------------------------------------------------------
# 1. _age
# ---------------------------------------------------------------------------
class TestAge(unittest.TestCase):
    def setUp(self):
        self.m = OraclePriceMonitor()

    def test_age_zero_when_just_updated(self):
        f = _feed(age=0)
        self.assertAlmostEqual(self.m._age(f), 0.0)

    def test_age_3600_when_one_hour_old(self):
        f = _feed(age=3600)
        self.assertAlmostEqual(self.m._age(f), 3600.0)

    def test_age_86400_when_one_day_old(self):
        f = _feed(age=86400)
        self.assertAlmostEqual(self.m._age(f), 86400.0)

    def test_age_precise_seconds(self):
        f = _feed(age=1234.56)
        self.assertAlmostEqual(self.m._age(f), 1234.56, places=2)


# ---------------------------------------------------------------------------
# 2. _staleness
# ---------------------------------------------------------------------------
class TestStaleness(unittest.TestCase):
    def setUp(self):
        self.m = OraclePriceMonitor()

    def test_zero_age_is_fresh(self):
        self.assertEqual(self.m._staleness(0), "FRESH")

    def test_just_under_3600_is_fresh(self):
        self.assertEqual(self.m._staleness(3599.9), "FRESH")

    def test_exactly_3600_is_aging(self):
        self.assertEqual(self.m._staleness(3600), "AGING")

    def test_5000_is_aging(self):
        self.assertEqual(self.m._staleness(5000), "AGING")

    def test_just_under_14400_is_aging(self):
        self.assertEqual(self.m._staleness(14399.9), "AGING")

    def test_exactly_14400_is_stale(self):
        self.assertEqual(self.m._staleness(14400), "STALE")

    def test_50000_is_stale(self):
        self.assertEqual(self.m._staleness(50000), "STALE")

    def test_just_under_86400_is_stale(self):
        self.assertEqual(self.m._staleness(86399.9), "STALE")

    def test_exactly_86400_is_expired(self):
        self.assertEqual(self.m._staleness(86400), "EXPIRED")

    def test_100000_is_expired(self):
        self.assertEqual(self.m._staleness(100000), "EXPIRED")

    def test_one_week_is_expired(self):
        self.assertEqual(self.m._staleness(86400 * 7), "EXPIRED")


# ---------------------------------------------------------------------------
# 3. _deviation_pct
# ---------------------------------------------------------------------------
class TestDeviationPct(unittest.TestCase):
    def setUp(self):
        self.m = OraclePriceMonitor()

    def test_reference_zero_returns_zero(self):
        self.assertEqual(self.m._deviation_pct(2000.0, 0.0), 0.0)

    def test_negative_reference_returns_zero(self):
        self.assertEqual(self.m._deviation_pct(2000.0, -1.0), 0.0)

    def test_perfect_match_zero(self):
        self.assertEqual(self.m._deviation_pct(2000.0, 2000.0), 0.0)

    def test_one_percent_high(self):
        result = self.m._deviation_pct(2020.0, 2000.0)
        self.assertAlmostEqual(result, 1.0, places=4)

    def test_one_percent_low(self):
        result = self.m._deviation_pct(1980.0, 2000.0)
        self.assertAlmostEqual(result, 1.0, places=4)

    def test_five_percent_deviation(self):
        result = self.m._deviation_pct(2100.0, 2000.0)
        self.assertAlmostEqual(result, 5.0, places=4)

    def test_returns_float(self):
        self.assertIsInstance(self.m._deviation_pct(1.0, 1.0), float)

    def test_symmetry_above_below(self):
        self.assertAlmostEqual(
            self.m._deviation_pct(2020.0, 2000.0),
            self.m._deviation_pct(1980.0, 2000.0),
            places=4,
        )


# ---------------------------------------------------------------------------
# 4. _deviation_status
# ---------------------------------------------------------------------------
class TestDeviationStatus(unittest.TestCase):
    def setUp(self):
        self.m = OraclePriceMonitor()

    def test_zero_is_normal(self):
        self.assertEqual(self.m._deviation_status(0.0), "NORMAL")

    def test_below_05pct_is_normal(self):
        self.assertEqual(self.m._deviation_status(0.4), "NORMAL")

    def test_exactly_05pct_is_suspicious(self):
        self.assertEqual(self.m._deviation_status(0.5), "SUSPICIOUS")

    def test_1pct_is_suspicious(self):
        self.assertEqual(self.m._deviation_status(1.0), "SUSPICIOUS")

    def test_just_under_2pct_is_suspicious(self):
        self.assertEqual(self.m._deviation_status(1.99), "SUSPICIOUS")

    def test_exactly_2pct_is_alert(self):
        self.assertEqual(self.m._deviation_status(2.0), "ALERT")

    def test_3pct_is_alert(self):
        self.assertEqual(self.m._deviation_status(3.0), "ALERT")

    def test_just_under_5pct_is_alert(self):
        self.assertEqual(self.m._deviation_status(4.99), "ALERT")

    def test_exactly_5pct_is_manipulation(self):
        self.assertEqual(self.m._deviation_status(5.0), "MANIPULATION")

    def test_10pct_is_manipulation(self):
        self.assertEqual(self.m._deviation_status(10.0), "MANIPULATION")

    def test_large_deviation_is_manipulation(self):
        self.assertEqual(self.m._deviation_status(99.0), "MANIPULATION")


# ---------------------------------------------------------------------------
# 5. _heartbeat_missed
# ---------------------------------------------------------------------------
class TestHeartbeatMissed(unittest.TestCase):
    def setUp(self):
        self.m = OraclePriceMonitor()

    def test_age_within_heartbeat_not_missed(self):
        self.assertFalse(self.m._heartbeat_missed(3600, 3600))

    def test_age_double_heartbeat_missed(self):
        self.assertTrue(self.m._heartbeat_missed(7201, 3600))

    def test_age_exactly_double_heartbeat_not_missed(self):
        # age > 2*heartbeat (strict >)
        self.assertFalse(self.m._heartbeat_missed(7200, 3600))

    def test_zero_age_not_missed(self):
        self.assertFalse(self.m._heartbeat_missed(0, 3600))

    def test_large_age_missed(self):
        self.assertTrue(self.m._heartbeat_missed(100000, 3600))


# ---------------------------------------------------------------------------
# 6. _overall_status
# ---------------------------------------------------------------------------
class TestOverallStatus(unittest.TestCase):
    def setUp(self):
        self.m = OraclePriceMonitor()

    def test_expired_gives_failed(self):
        self.assertEqual(self.m._overall_status("EXPIRED", "NORMAL"), "FAILED")

    def test_manipulation_gives_failed(self):
        self.assertEqual(self.m._overall_status("FRESH", "MANIPULATION"), "FAILED")

    def test_expired_plus_manipulation_gives_failed(self):
        self.assertEqual(self.m._overall_status("EXPIRED", "MANIPULATION"), "FAILED")

    def test_stale_gives_degraded(self):
        self.assertEqual(self.m._overall_status("STALE", "NORMAL"), "DEGRADED")

    def test_aging_gives_degraded(self):
        self.assertEqual(self.m._overall_status("AGING", "NORMAL"), "DEGRADED")

    def test_suspicious_gives_degraded(self):
        self.assertEqual(self.m._overall_status("FRESH", "SUSPICIOUS"), "DEGRADED")

    def test_alert_gives_degraded(self):
        self.assertEqual(self.m._overall_status("FRESH", "ALERT"), "DEGRADED")

    def test_fresh_normal_gives_healthy(self):
        self.assertEqual(self.m._overall_status("FRESH", "NORMAL"), "HEALTHY")

    def test_stale_alert_gives_degraded_not_failed(self):
        # Neither EXPIRED nor MANIPULATION → DEGRADED
        self.assertEqual(self.m._overall_status("STALE", "ALERT"), "DEGRADED")


# ---------------------------------------------------------------------------
# 7. _advisory
# ---------------------------------------------------------------------------
class TestAdvisory(unittest.TestCase):
    def setUp(self):
        self.m = OraclePriceMonitor()

    def test_failed_returns_nonempty(self):
        msg = self.m._advisory("FAILED", "EXPIRED", "MANIPULATION")
        self.assertTrue(len(msg) > 0)

    def test_failed_contains_failed(self):
        msg = self.m._advisory("FAILED", "EXPIRED", "NORMAL")
        self.assertIn("FAILED", msg)

    def test_degraded_returns_nonempty(self):
        msg = self.m._advisory("DEGRADED", "AGING", "SUSPICIOUS")
        self.assertTrue(len(msg) > 0)

    def test_degraded_contains_degraded(self):
        msg = self.m._advisory("DEGRADED", "STALE", "ALERT")
        self.assertIn("DEGRADED", msg)

    def test_healthy_returns_nonempty(self):
        msg = self.m._advisory("HEALTHY", "FRESH", "NORMAL")
        self.assertTrue(len(msg) > 0)

    def test_healthy_contains_healthy(self):
        msg = self.m._advisory("HEALTHY", "FRESH", "NORMAL")
        self.assertIn("healthy", msg.lower())


# ---------------------------------------------------------------------------
# 8. assess — integration
# ---------------------------------------------------------------------------
class TestAssess(unittest.TestCase):
    def setUp(self):
        self.m = OraclePriceMonitor()

    def test_fresh_normal_oracle_healthy(self):
        f = _feed(age=100, reported_price=2000.0, reference_price=2000.0)
        h = self.m.assess(f)
        self.assertEqual(h.overall_status, "HEALTHY")
        self.assertEqual(h.staleness_status, "FRESH")
        self.assertEqual(h.deviation_status, "NORMAL")

    def test_two_hour_old_feed_is_aging(self):
        f = _feed(age=2 * 3600)  # 7200s < 14400s AGING limit
        h = self.m.assess(f)
        self.assertEqual(h.staleness_status, "AGING")

    def test_over_24h_old_is_expired_and_failed(self):
        f = _feed(age=86401)
        h = self.m.assess(f)
        self.assertEqual(h.staleness_status, "EXPIRED")
        self.assertEqual(h.overall_status, "FAILED")

    def test_3pct_deviation_is_alert_and_degraded(self):
        f = _feed(reported_price=2060.0, reference_price=2000.0, age=100)
        h = self.m.assess(f)
        self.assertEqual(h.deviation_status, "ALERT")
        self.assertEqual(h.overall_status, "DEGRADED")

    def test_6pct_deviation_is_manipulation_and_failed(self):
        f = _feed(reported_price=2120.0, reference_price=2000.0, age=100)
        h = self.m.assess(f)
        self.assertEqual(h.deviation_status, "MANIPULATION")
        self.assertEqual(h.overall_status, "FAILED")

    def test_heartbeat_missed_when_age_double(self):
        f = _feed(age=7201, heartbeat=3600)
        h = self.m.assess(f)
        self.assertTrue(h.heartbeat_missed)

    def test_heartbeat_not_missed_within_double(self):
        f = _feed(age=3600, heartbeat=3600)
        h = self.m.assess(f)
        self.assertFalse(h.heartbeat_missed)

    def test_age_seconds_stored(self):
        f = _feed(age=1800)
        h = self.m.assess(f)
        self.assertAlmostEqual(h.age_seconds, 1800.0, places=1)

    def test_feed_id_preserved(self):
        f = _feed(feed_id="my_feed")
        h = self.m.assess(f)
        self.assertEqual(h.feed_id, "my_feed")

    def test_asset_preserved(self):
        f = _feed(asset="BTC/USD")
        h = self.m.assess(f)
        self.assertEqual(h.asset, "BTC/USD")

    def test_reported_price_rounded(self):
        f = _feed(reported_price=2000.1234567)
        h = self.m.assess(f)
        self.assertEqual(h.reported_price, round(2000.1234567, 6))

    def test_advisory_nonempty(self):
        f = _feed()
        h = self.m.assess(f)
        self.assertTrue(len(h.advisory) > 0)

    def test_assess_returns_oracle_health(self):
        f = _feed()
        h = self.m.assess(f)
        self.assertIsInstance(h, OracleHealth)

    def test_deviation_pct_stored(self):
        f = _feed(reported_price=2020.0, reference_price=2000.0, age=100)
        h = self.m.assess(f)
        self.assertAlmostEqual(h.price_deviation_pct, 1.0, places=4)

    def test_stale_data_is_degraded(self):
        f = _feed(age=30000)  # ~8h → STALE
        h = self.m.assess(f)
        self.assertEqual(h.staleness_status, "STALE")
        self.assertEqual(h.overall_status, "DEGRADED")

    def test_reference_price_rounded(self):
        f = _feed(reference_price=2000.9876543)
        h = self.m.assess(f)
        self.assertEqual(h.reference_price, round(2000.9876543, 6))


# ---------------------------------------------------------------------------
# 9. assess_batch
# ---------------------------------------------------------------------------
class TestAssessBatch(unittest.TestCase):
    def setUp(self):
        self.m = OraclePriceMonitor()

    def test_empty_returns_empty(self):
        self.assertEqual(self.m.assess_batch([]), [])

    def test_length_matches_input(self):
        feeds = [_feed(feed_id=f"f{i}") for i in range(4)]
        results = self.m.assess_batch(feeds)
        self.assertEqual(len(results), 4)

    def test_preserves_order(self):
        feeds = [_feed(feed_id=f"f{i}") for i in range(3)]
        results = self.m.assess_batch(feeds)
        self.assertEqual([r.feed_id for r in results], ["f0", "f1", "f2"])

    def test_single_item_batch(self):
        results = self.m.assess_batch([_feed()])
        self.assertEqual(len(results), 1)


# ---------------------------------------------------------------------------
# 10. failed_oracles
# ---------------------------------------------------------------------------
class TestFailedOracles(unittest.TestCase):
    def setUp(self):
        self.m = OraclePriceMonitor()

    def test_filters_failed_only(self):
        feeds = [
            _feed(feed_id="ok", age=100),
            _feed(feed_id="expired", age=90000),
            _feed(feed_id="manip", reported_price=2200.0, reference_price=2000.0, age=100),
        ]
        results = self.m.assess_batch(feeds)
        failed = self.m.failed_oracles(results)
        failed_ids = {r.feed_id for r in failed}
        self.assertIn("expired", failed_ids)
        self.assertIn("manip", failed_ids)
        self.assertNotIn("ok", failed_ids)

    def test_empty_input_returns_empty(self):
        self.assertEqual(self.m.failed_oracles([]), [])

    def test_all_healthy_returns_empty(self):
        results = self.m.assess_batch([_feed(feed_id=f"f{i}") for i in range(3)])
        self.assertEqual(self.m.failed_oracles(results), [])

    def test_all_failed_returns_all(self):
        feeds = [_feed(feed_id=f"f{i}", age=90000) for i in range(3)]
        results = self.m.assess_batch(feeds)
        failed = self.m.failed_oracles(results)
        self.assertEqual(len(failed), 3)


# ---------------------------------------------------------------------------
# 11. save_results + load_history
# ---------------------------------------------------------------------------
class TestPersistence(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.m = OraclePriceMonitor(data_file=Path(self.tmp) / "oracle_log.json")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_load_history_missing_file_returns_empty(self):
        self.assertEqual(self.m.load_history(), [])

    def test_save_creates_file(self):
        h = self.m.assess(_feed())
        self.m.save_results([h])
        self.assertTrue(self.m.data_file.exists())

    def test_save_and_reload(self):
        h = self.m.assess(_feed(feed_id="feed_eth"))
        self.m.save_results([h])
        history = self.m.load_history()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["feed_id"], "feed_eth")

    def test_atomic_write_no_tmp_left(self):
        h = self.m.assess(_feed())
        self.m.save_results([h])
        tmp_path = self.m.data_file.with_suffix(".tmp")
        self.assertFalse(tmp_path.exists())

    def test_ring_buffer_100(self):
        h = self.m.assess(_feed())
        for _ in range(11):
            self.m.save_results([h] * 10)
        history = self.m.load_history()
        self.assertEqual(len(history), MAX_ENTRIES)

    def test_history_entry_has_required_keys(self):
        h = self.m.assess(_feed())
        self.m.save_results([h])
        entry = self.m.load_history()[0]
        for key in ("timestamp", "feed_id", "age_seconds", "staleness_status",
                    "deviation_status", "overall_status"):
            self.assertIn(key, entry)

    def test_save_empty_list(self):
        self.m.save_results([])
        self.assertEqual(self.m.load_history(), [])

    def test_accumulates_across_calls(self):
        h1 = self.m.assess(_feed(feed_id="a"))
        h2 = self.m.assess(_feed(feed_id="b"))
        self.m.save_results([h1])
        self.m.save_results([h2])
        history = self.m.load_history()
        self.assertEqual(len(history), 2)

    def test_corrupted_file_returns_empty_list(self):
        self.m.data_file.parent.mkdir(parents=True, exist_ok=True)
        self.m.data_file.write_text("NOT VALID JSON {{{")
        result = self.m.load_history()
        self.assertEqual(result, [])

    def test_save_multiple_items(self):
        feeds = [_feed(feed_id=f"f{i}") for i in range(5)]
        results = self.m.assess_batch(feeds)
        self.m.save_results(results)
        history = self.m.load_history()
        self.assertEqual(len(history), 5)

    def test_history_is_list(self):
        h = self.m.assess(_feed())
        self.m.save_results([h])
        self.assertIsInstance(self.m.load_history(), list)


if __name__ == "__main__":
    unittest.main()
