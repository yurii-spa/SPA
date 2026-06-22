# spa_core/tests/test_lp_position_tracker.py
# MP-660 — Tests for LPPositionTracker (pure stdlib, unittest only)

import json
import tempfile
import time
import unittest
from pathlib import Path

from spa_core.analytics.lp_position_tracker import (
    LPEntry,
    LPPositionTracker,
    LPSummary,
)


def _make_entry(
    position_id="pos-1",
    pool_id="pool-A",
    protocol="Uniswap V3",
    token_pair="ETH/USDC",
    entry_timestamp=None,
    entry_capital_usd=10000.0,
    current_capital_usd=10500.0,
    fees_accumulated_usd=150.0,
    last_updated=None,
    days_active=7.0,
    status="ACTIVE",
) -> LPEntry:
    now = time.time()
    return LPEntry(
        position_id=position_id,
        pool_id=pool_id,
        protocol=protocol,
        token_pair=token_pair,
        entry_timestamp=entry_timestamp if entry_timestamp is not None else now - days_active * 86400,
        entry_capital_usd=entry_capital_usd,
        current_capital_usd=current_capital_usd,
        fees_accumulated_usd=fees_accumulated_usd,
        last_updated=last_updated if last_updated is not None else now,
        days_active=days_active,
        status=status,
    )


class TestFeeYield(unittest.TestCase):
    """Tests for _fee_yield helper."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.tracker = LPPositionTracker(data_file=Path(self.tmpdir) / "lp.json")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_fee_yield_zero_capital(self):
        entry = _make_entry(entry_capital_usd=0.0, fees_accumulated_usd=100.0)
        self.assertEqual(self.tracker._fee_yield(entry), 0.0)

    def test_fee_yield_basic(self):
        entry = _make_entry(entry_capital_usd=10000.0, fees_accumulated_usd=500.0)
        self.assertAlmostEqual(self.tracker._fee_yield(entry), 0.05, places=6)

    def test_fee_yield_zero_fees(self):
        entry = _make_entry(entry_capital_usd=10000.0, fees_accumulated_usd=0.0)
        self.assertEqual(self.tracker._fee_yield(entry), 0.0)

    def test_fee_yield_ratio(self):
        entry = _make_entry(entry_capital_usd=2000.0, fees_accumulated_usd=100.0)
        self.assertAlmostEqual(self.tracker._fee_yield(entry), 0.05, places=6)

    def test_fee_yield_negative_capital(self):
        # Negative capital treated as <= 0 → return 0.0
        entry = _make_entry(entry_capital_usd=-500.0, fees_accumulated_usd=50.0)
        # _fee_yield checks <=0 so -500 → 0.0
        self.assertEqual(self.tracker._fee_yield(entry), 0.0)


class TestAddPosition(unittest.TestCase):
    """Tests for add_position()."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.data_file = Path(self.tmpdir) / "data" / "lp.json"
        self.tracker = LPPositionTracker(data_file=self.data_file)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_add_creates_file(self):
        entry = _make_entry(position_id="new-1")
        self.tracker.add_position(entry)
        self.assertTrue(self.data_file.exists())

    def test_add_single_position(self):
        entry = _make_entry(position_id="p1")
        self.tracker.add_position(entry)
        positions = self.tracker.load_positions()
        self.assertEqual(len(positions), 1)
        self.assertEqual(positions[0]["position_id"], "p1")

    def test_add_idempotent_same_id(self):
        entry = _make_entry(position_id="dup", fees_accumulated_usd=100.0)
        self.tracker.add_position(entry)
        entry2 = _make_entry(position_id="dup", fees_accumulated_usd=200.0)
        self.tracker.add_position(entry2)
        positions = self.tracker.load_positions()
        self.assertEqual(len(positions), 1)

    def test_add_updates_existing(self):
        entry = _make_entry(position_id="upd", fees_accumulated_usd=100.0)
        self.tracker.add_position(entry)
        entry2 = _make_entry(position_id="upd", fees_accumulated_usd=250.0)
        self.tracker.add_position(entry2)
        positions = self.tracker.load_positions()
        self.assertAlmostEqual(positions[0]["fees_accumulated_usd"], 250.0, places=2)

    def test_add_multiple_positions(self):
        for i in range(5):
            self.tracker.add_position(_make_entry(position_id=f"pos-{i}"))
        positions = self.tracker.load_positions()
        self.assertEqual(len(positions), 5)

    def test_add_ring_buffer_50(self):
        """More than 50 positions → keeps last 50."""
        for i in range(55):
            self.tracker.add_position(_make_entry(position_id=f"pos-{i}"))
        positions = self.tracker.load_positions()
        self.assertEqual(len(positions), 50)

    def test_add_preserves_fields(self):
        entry = _make_entry(
            position_id="fields",
            pool_id="pool-X",
            protocol="Curve",
            token_pair="USDC/DAI",
            status="ACTIVE",
        )
        self.tracker.add_position(entry)
        positions = self.tracker.load_positions()
        p = positions[0]
        self.assertEqual(p["pool_id"], "pool-X")
        self.assertEqual(p["protocol"], "Curve")
        self.assertEqual(p["token_pair"], "USDC/DAI")
        self.assertEqual(p["status"], "ACTIVE")

    def test_add_rounds_capital(self):
        entry = _make_entry(entry_capital_usd=1234.5678, current_capital_usd=5432.109)
        self.tracker.add_position(entry)
        positions = self.tracker.load_positions()
        self.assertAlmostEqual(positions[0]["entry_capital_usd"], 1234.57, places=1)

    def test_add_atomic_no_tmp(self):
        entry = _make_entry(position_id="atomic")
        self.tracker.add_position(entry)
        tmp = self.data_file.with_suffix(".tmp")
        self.assertFalse(tmp.exists())


class TestClosePosition(unittest.TestCase):
    """Tests for close_position()."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.data_file = Path(self.tmpdir) / "lp.json"
        self.tracker = LPPositionTracker(data_file=self.data_file)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_close_unknown_id_returns_false(self):
        result = self.tracker.close_position("nonexistent")
        self.assertFalse(result)

    def test_close_known_id_returns_true(self):
        entry = _make_entry(position_id="to-close")
        self.tracker.add_position(entry)
        result = self.tracker.close_position("to-close")
        self.assertTrue(result)

    def test_close_sets_status_closed(self):
        entry = _make_entry(position_id="close-me", status="ACTIVE")
        self.tracker.add_position(entry)
        self.tracker.close_position("close-me")
        positions = self.tracker.load_positions()
        p = next(x for x in positions if x["position_id"] == "close-me")
        self.assertEqual(p["status"], "CLOSED")

    def test_close_updates_last_updated(self):
        before = time.time()
        entry = _make_entry(position_id="ts-check", last_updated=before - 1000)
        self.tracker.add_position(entry)
        self.tracker.close_position("ts-check")
        positions = self.tracker.load_positions()
        p = next(x for x in positions if x["position_id"] == "ts-check")
        self.assertGreaterEqual(p["last_updated"], before)

    def test_close_only_affects_target(self):
        self.tracker.add_position(_make_entry(position_id="a", status="ACTIVE"))
        self.tracker.add_position(_make_entry(position_id="b", status="ACTIVE"))
        self.tracker.close_position("a")
        positions = self.tracker.load_positions()
        b = next(x for x in positions if x["position_id"] == "b")
        self.assertEqual(b["status"], "ACTIVE")

    def test_close_empty_tracker_returns_false(self):
        self.assertFalse(self.tracker.close_position("anything"))

    def test_close_persists(self):
        entry = _make_entry(position_id="persist-close")
        self.tracker.add_position(entry)
        self.tracker.close_position("persist-close")
        # Re-load via new tracker instance
        tracker2 = LPPositionTracker(data_file=self.data_file)
        positions = tracker2.load_positions()
        p = next(x for x in positions if x["position_id"] == "persist-close")
        self.assertEqual(p["status"], "CLOSED")


class TestGetSummary(unittest.TestCase):
    """Tests for get_summary()."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.tracker = LPPositionTracker(data_file=Path(self.tmpdir) / "lp.json")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _p(self, pid, status="ACTIVE", capital=10000.0, fees=100.0, days=5.0):
        return {
            "position_id": pid,
            "pool_id": "pool",
            "protocol": "Uniswap",
            "token_pair": "ETH/USDC",
            "entry_timestamp": time.time() - days * 86400,
            "entry_capital_usd": capital,
            "current_capital_usd": capital,
            "fees_accumulated_usd": fees,
            "last_updated": time.time(),
            "days_active": days,
            "status": status,
        }

    def test_summary_empty_list(self):
        s = self.tracker.get_summary([])
        self.assertEqual(s.total_positions, 0)
        self.assertEqual(s.active_positions, 0)
        self.assertEqual(s.closed_positions, 0)
        self.assertAlmostEqual(s.total_capital_deployed_usd, 0.0, places=2)
        self.assertAlmostEqual(s.total_fees_earned_usd, 0.0, places=4)
        self.assertAlmostEqual(s.avg_position_age_days, 0.0, places=2)
        self.assertIsNone(s.best_performer_id)
        self.assertIsNone(s.worst_performer_id)
        self.assertAlmostEqual(s.overall_fee_yield_pct, 0.0, places=6)

    def test_summary_total_positions(self):
        positions = [self._p("a"), self._p("b"), self._p("c", status="CLOSED")]
        s = self.tracker.get_summary(positions)
        self.assertEqual(s.total_positions, 3)

    def test_summary_active_count(self):
        positions = [self._p("a"), self._p("b"), self._p("c", status="CLOSED")]
        s = self.tracker.get_summary(positions)
        self.assertEqual(s.active_positions, 2)

    def test_summary_closed_count(self):
        positions = [self._p("a"), self._p("b", status="CLOSED"), self._p("c", status="CLOSED")]
        s = self.tracker.get_summary(positions)
        self.assertEqual(s.closed_positions, 2)

    def test_summary_total_capital_active_only(self):
        positions = [
            self._p("a", capital=5000.0),
            self._p("b", capital=8000.0),
            self._p("c", status="CLOSED", capital=3000.0),
        ]
        s = self.tracker.get_summary(positions)
        self.assertAlmostEqual(s.total_capital_deployed_usd, 13000.0, places=1)

    def test_summary_total_fees_active_only(self):
        positions = [
            self._p("a", fees=200.0),
            self._p("b", fees=300.0),
            self._p("c", status="CLOSED", fees=1000.0),
        ]
        s = self.tracker.get_summary(positions)
        self.assertAlmostEqual(s.total_fees_earned_usd, 500.0, places=3)

    def test_summary_avg_age_active_only(self):
        positions = [
            self._p("a", days=10.0),
            self._p("b", days=20.0),
            self._p("c", status="CLOSED", days=100.0),
        ]
        s = self.tracker.get_summary(positions)
        self.assertAlmostEqual(s.avg_position_age_days, 15.0, places=2)

    def test_summary_best_performer(self):
        # b has highest fee_yield (200/5000 = 4%) vs a (100/10000 = 1%)
        positions = [
            self._p("a", capital=10000.0, fees=100.0),
            self._p("b", capital=5000.0, fees=200.0),
        ]
        s = self.tracker.get_summary(positions)
        self.assertEqual(s.best_performer_id, "b")

    def test_summary_worst_performer(self):
        positions = [
            self._p("a", capital=10000.0, fees=100.0),   # 1%
            self._p("b", capital=5000.0, fees=200.0),    # 4%
        ]
        s = self.tracker.get_summary(positions)
        self.assertEqual(s.worst_performer_id, "a")

    def test_summary_overall_fee_yield(self):
        positions = [
            self._p("a", capital=10000.0, fees=500.0),
            self._p("b", capital=10000.0, fees=500.0),
        ]
        s = self.tracker.get_summary(positions)
        # total_fees=1000, total_cap=20000 → 5%
        self.assertAlmostEqual(s.overall_fee_yield_pct, 0.05, places=5)

    def test_summary_overall_yield_zero_capital(self):
        positions = [self._p("a", capital=0.0, fees=100.0)]
        s = self.tracker.get_summary(positions)
        self.assertAlmostEqual(s.overall_fee_yield_pct, 0.0, places=5)

    def test_summary_single_position(self):
        positions = [self._p("only", capital=10000.0, fees=100.0, days=30.0)]
        s = self.tracker.get_summary(positions)
        self.assertEqual(s.total_positions, 1)
        self.assertEqual(s.active_positions, 1)
        self.assertEqual(s.best_performer_id, "only")
        self.assertEqual(s.worst_performer_id, "only")

    def test_summary_returns_lpsummary(self):
        s = self.tracker.get_summary([])
        self.assertIsInstance(s, LPSummary)

    def test_summary_closed_not_in_best_worst(self):
        positions = [
            self._p("a", capital=10000.0, fees=100.0),
            self._p("b", status="CLOSED", capital=1000.0, fees=9999.0),
        ]
        s = self.tracker.get_summary(positions)
        # Only active: "a"
        self.assertEqual(s.best_performer_id, "a")
        self.assertEqual(s.worst_performer_id, "a")

    def test_summary_all_closed_no_best_worst(self):
        positions = [
            self._p("a", status="CLOSED"),
            self._p("b", status="CLOSED"),
        ]
        s = self.tracker.get_summary(positions)
        self.assertIsNone(s.best_performer_id)
        self.assertIsNone(s.worst_performer_id)
        self.assertAlmostEqual(s.total_capital_deployed_usd, 0.0, places=2)


class TestLoadPositions(unittest.TestCase):
    """Tests for load_positions() / _load_positions()."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.data_file = Path(self.tmpdir) / "lp.json"
        self.tracker = LPPositionTracker(data_file=self.data_file)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_load_missing_file_returns_empty(self):
        result = self.tracker.load_positions()
        self.assertEqual(result, [])

    def test_load_corrupted_json_returns_empty(self):
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        self.data_file.write_text("{{not-valid-json")
        result = self.tracker.load_positions()
        self.assertEqual(result, [])

    def test_load_returns_list(self):
        entry = _make_entry(position_id="loadme")
        self.tracker.add_position(entry)
        result = self.tracker.load_positions()
        self.assertIsInstance(result, list)

    def test_persistence_add_then_load(self):
        entry = _make_entry(position_id="persist", protocol="Curve", token_pair="USDT/DAI")
        self.tracker.add_position(entry)
        # Load with a fresh tracker instance
        tracker2 = LPPositionTracker(data_file=self.data_file)
        positions = tracker2.load_positions()
        self.assertEqual(len(positions), 1)
        self.assertEqual(positions[0]["position_id"], "persist")
        self.assertEqual(positions[0]["protocol"], "Curve")
        self.assertEqual(positions[0]["token_pair"], "USDT/DAI")

    def test_load_valid_json_array(self):
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        self.data_file.write_text(json.dumps([{"position_id": "manual", "status": "ACTIVE"}]))
        result = self.tracker.load_positions()
        self.assertEqual(result[0]["position_id"], "manual")

    def test_load_multiple_persisted(self):
        for i in range(3):
            self.tracker.add_position(_make_entry(position_id=f"m{i}"))
        positions = self.tracker.load_positions()
        self.assertEqual(len(positions), 3)


class TestAddPositionExtended(unittest.TestCase):
    """Additional add_position edge-case tests."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.data_file = Path(self.tmpdir) / "lp.json"
        self.tracker = LPPositionTracker(data_file=self.data_file)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_add_status_closed(self):
        entry = _make_entry(position_id="c1", status="CLOSED")
        self.tracker.add_position(entry)
        positions = self.tracker.load_positions()
        self.assertEqual(positions[0]["status"], "CLOSED")

    def test_add_days_active_rounded(self):
        entry = _make_entry(position_id="days", days_active=7.123456789)
        self.tracker.add_position(entry)
        positions = self.tracker.load_positions()
        self.assertAlmostEqual(positions[0]["days_active"], round(7.123456789, 2), places=2)

    def test_add_fees_rounded_to_4_places(self):
        entry = _make_entry(position_id="fees", fees_accumulated_usd=12.123456789)
        self.tracker.add_position(entry)
        positions = self.tracker.load_positions()
        self.assertAlmostEqual(positions[0]["fees_accumulated_usd"], round(12.123456789, 4), places=4)

    def test_add_current_capital_rounded(self):
        entry = _make_entry(position_id="ccap", current_capital_usd=9876.54321)
        self.tracker.add_position(entry)
        positions = self.tracker.load_positions()
        self.assertAlmostEqual(positions[0]["current_capital_usd"], round(9876.54321, 2), places=1)

    def test_add_position_id_in_dict(self):
        entry = _make_entry(position_id="id-check")
        self.tracker.add_position(entry)
        positions = self.tracker.load_positions()
        self.assertIn("position_id", positions[0])

    def test_add_overwrites_older_on_ring_buffer(self):
        """Last 50 of 55 must not contain first 5."""
        for i in range(55):
            self.tracker.add_position(_make_entry(position_id=f"pos-{i}"))
        positions = self.tracker.load_positions()
        ids = [p["position_id"] for p in positions]
        for i in range(5):
            self.assertNotIn(f"pos-{i}", ids)

    def test_add_last_updated_stored(self):
        entry = _make_entry(position_id="lu")
        self.tracker.add_position(entry)
        positions = self.tracker.load_positions()
        self.assertIn("last_updated", positions[0])


class TestGetSummaryExtended(unittest.TestCase):
    """Extended get_summary edge cases."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.tracker = LPPositionTracker(data_file=Path(self.tmpdir) / "lp.json")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _p(self, pid, status="ACTIVE", capital=10000.0, fees=100.0, days=5.0):
        return {
            "position_id": pid,
            "pool_id": "pool",
            "protocol": "Uniswap",
            "token_pair": "ETH/USDC",
            "entry_timestamp": time.time() - days * 86400,
            "entry_capital_usd": capital,
            "current_capital_usd": capital,
            "fees_accumulated_usd": fees,
            "last_updated": time.time(),
            "days_active": days,
            "status": status,
        }

    def test_summary_avg_age_single(self):
        positions = [self._p("a", days=14.0)]
        s = self.tracker.get_summary(positions)
        self.assertAlmostEqual(s.avg_position_age_days, 14.0, places=2)

    def test_summary_avg_age_three(self):
        positions = [
            self._p("a", days=6.0),
            self._p("b", days=12.0),
            self._p("c", days=18.0),
        ]
        s = self.tracker.get_summary(positions)
        self.assertAlmostEqual(s.avg_position_age_days, 12.0, places=2)

    def test_summary_closed_not_counted_in_avg_age(self):
        positions = [
            self._p("a", days=10.0),
            self._p("b", status="CLOSED", days=1000.0),
        ]
        s = self.tracker.get_summary(positions)
        self.assertAlmostEqual(s.avg_position_age_days, 10.0, places=2)

    def test_summary_capital_rounds_to_2(self):
        positions = [self._p("a", capital=1234.5678)]
        s = self.tracker.get_summary(positions)
        self.assertEqual(s.total_capital_deployed_usd, round(1234.5678, 2))

    def test_summary_fees_rounds_to_4(self):
        positions = [self._p("a", fees=12.34567)]
        s = self.tracker.get_summary(positions)
        self.assertEqual(s.total_fees_earned_usd, round(12.34567, 4))

    def test_summary_three_positions_best_worst(self):
        # a: 50/5000=1%, b: 200/10000=2%, c: 30/20000=0.15%
        positions = [
            self._p("a", capital=5000.0, fees=50.0),
            self._p("b", capital=10000.0, fees=200.0),
            self._p("c", capital=20000.0, fees=30.0),
        ]
        s = self.tracker.get_summary(positions)
        self.assertEqual(s.best_performer_id, "b")
        self.assertEqual(s.worst_performer_id, "c")

    def test_summary_overall_yield_single_position(self):
        positions = [self._p("a", capital=10000.0, fees=250.0)]
        s = self.tracker.get_summary(positions)
        self.assertAlmostEqual(s.overall_fee_yield_pct, 0.025, places=5)

    def test_summary_all_active(self):
        positions = [self._p(f"p{i}") for i in range(3)]
        s = self.tracker.get_summary(positions)
        self.assertEqual(s.active_positions, 3)
        self.assertEqual(s.closed_positions, 0)

    def test_summary_mixed_active_closed_counts(self):
        positions = [
            self._p("a"),
            self._p("b", status="CLOSED"),
            self._p("c", status="CLOSED"),
            self._p("d"),
        ]
        s = self.tracker.get_summary(positions)
        self.assertEqual(s.total_positions, 4)
        self.assertEqual(s.active_positions, 2)
        self.assertEqual(s.closed_positions, 2)

    def test_summary_yield_pct_rounds_to_6(self):
        positions = [self._p("a", capital=3000.0, fees=100.0)]
        s = self.tracker.get_summary(positions)
        self.assertEqual(s.overall_fee_yield_pct, round(100.0 / 3000.0, 6))

    def test_summary_fields_present(self):
        s = self.tracker.get_summary([])
        self.assertTrue(hasattr(s, "total_positions"))
        self.assertTrue(hasattr(s, "active_positions"))
        self.assertTrue(hasattr(s, "closed_positions"))
        self.assertTrue(hasattr(s, "total_capital_deployed_usd"))
        self.assertTrue(hasattr(s, "total_fees_earned_usd"))
        self.assertTrue(hasattr(s, "avg_position_age_days"))
        self.assertTrue(hasattr(s, "best_performer_id"))
        self.assertTrue(hasattr(s, "worst_performer_id"))
        self.assertTrue(hasattr(s, "overall_fee_yield_pct"))


if __name__ == "__main__":
    unittest.main()
