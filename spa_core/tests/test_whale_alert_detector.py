"""
Tests for MP-695: WhaleAlertDetector
≥60 tests covering all spec requirements.
Uses unittest only (no pytest).
"""

import json
import os
import time
import unittest
import tempfile
from pathlib import Path

from spa_core.analytics.whale_alert_detector import (
    Transaction,
    WhaleAlert,
    THRESHOLDS,
    detect,
    detect_batch,
    filter_critical,
    load_history,
    save_results,
    _alert_tier,
    _suspicion_score,
    _flags,
    _risk_level,
    _action,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BASE_TS = 1_700_000_000.0


def _tx(
    amount_usd=1_000_000.0,
    tx_type="DEPOSIT",
    wallet_age_days=30,
    is_contract=False,
    protocol="Aave",
    tx_id="tx_001",
):
    return Transaction(
        tx_id=tx_id,
        protocol=protocol,
        tx_type=tx_type,
        amount_usd=amount_usd,
        timestamp=BASE_TS,
        wallet_age_days=wallet_age_days,
        is_contract=is_contract,
    )


# ---------------------------------------------------------------------------
# 1. _alert_tier
# ---------------------------------------------------------------------------

class TestAlertTier(unittest.TestCase):

    def test_mega_whale_exact_boundary(self):
        self.assertEqual(_alert_tier(10_000_000), "MEGA_WHALE")

    def test_mega_whale_above_boundary(self):
        self.assertEqual(_alert_tier(50_000_000), "MEGA_WHALE")

    def test_whale_exactly_1m(self):
        self.assertEqual(_alert_tier(1_000_000), "WHALE")

    def test_whale_between_1m_and_10m(self):
        self.assertEqual(_alert_tier(5_000_000), "WHALE")

    def test_large_exactly_100k(self):
        self.assertEqual(_alert_tier(100_000), "LARGE")

    def test_large_between_100k_and_1m(self):
        self.assertEqual(_alert_tier(500_000), "LARGE")

    def test_medium_exactly_10k(self):
        self.assertEqual(_alert_tier(10_000), "MEDIUM")

    def test_medium_between_10k_and_100k(self):
        self.assertEqual(_alert_tier(50_000), "MEDIUM")

    def test_below_threshold(self):
        self.assertEqual(_alert_tier(9_999), "BELOW_THRESHOLD")

    def test_zero_is_below_threshold(self):
        self.assertEqual(_alert_tier(0), "BELOW_THRESHOLD")

    def test_just_below_mega_whale(self):
        self.assertEqual(_alert_tier(9_999_999), "WHALE")


# ---------------------------------------------------------------------------
# 2. _suspicion_score
# ---------------------------------------------------------------------------

class TestSuspicionScore(unittest.TestCase):

    def test_base_score_old_wallet_no_flags(self):
        tx = _tx(amount_usd=500, wallet_age_days=30, is_contract=False, tx_type="DEPOSIT")
        self.assertAlmostEqual(_suspicion_score(tx), 0.1)

    def test_new_wallet_adds_0_3(self):
        tx = _tx(amount_usd=500, wallet_age_days=6, is_contract=False, tx_type="DEPOSIT")
        self.assertAlmostEqual(_suspicion_score(tx), 0.4)

    def test_liquidate_adds_0_2(self):
        tx = _tx(amount_usd=500, wallet_age_days=30, is_contract=False, tx_type="LIQUIDATE")
        self.assertAlmostEqual(_suspicion_score(tx), 0.3)

    def test_contract_adds_0_2(self):
        tx = _tx(amount_usd=500, wallet_age_days=30, is_contract=True, tx_type="DEPOSIT")
        self.assertAlmostEqual(_suspicion_score(tx), 0.3)

    def test_mega_whale_size_adds_0_2(self):
        tx = _tx(amount_usd=10_000_000, wallet_age_days=30, is_contract=False, tx_type="DEPOSIT")
        self.assertAlmostEqual(_suspicion_score(tx), 0.3)

    def test_all_flags_capped_at_1(self):
        # base=0.1 + new_wallet=0.3 + liquidate=0.2 + contract=0.2 + mega=0.2 = 1.0
        tx = _tx(amount_usd=10_000_000, wallet_age_days=0, is_contract=True, tx_type="LIQUIDATE")
        self.assertAlmostEqual(_suspicion_score(tx), 1.0)

    def test_new_wallet_and_liquidate(self):
        tx = _tx(amount_usd=500, wallet_age_days=3, is_contract=False, tx_type="LIQUIDATE")
        self.assertAlmostEqual(_suspicion_score(tx), 0.6)

    def test_new_wallet_and_contract(self):
        tx = _tx(amount_usd=500, wallet_age_days=1, is_contract=True, tx_type="DEPOSIT")
        self.assertAlmostEqual(_suspicion_score(tx), 0.6)

    def test_wallet_age_exactly_7_not_new(self):
        # wallet_age_days == 7 is NOT < 7 → no bonus
        tx = _tx(amount_usd=500, wallet_age_days=7, is_contract=False, tx_type="DEPOSIT")
        self.assertAlmostEqual(_suspicion_score(tx), 0.1)

    def test_score_never_below_zero(self):
        tx = _tx(amount_usd=0, wallet_age_days=100, is_contract=False, tx_type="DEPOSIT")
        self.assertGreaterEqual(_suspicion_score(tx), 0.0)


# ---------------------------------------------------------------------------
# 3. _flags
# ---------------------------------------------------------------------------

class TestFlags(unittest.TestCase):

    def test_new_wallet_flag(self):
        tx = _tx(wallet_age_days=3)
        f = _flags(tx)
        self.assertTrue(any("🆕" in x for x in f))

    def test_no_new_wallet_flag_old_wallet(self):
        tx = _tx(wallet_age_days=30)
        f = _flags(tx)
        self.assertFalse(any("🆕" in x for x in f))

    def test_liquidation_flag(self):
        tx = _tx(tx_type="LIQUIDATE")
        f = _flags(tx)
        self.assertTrue(any("⚡" in x for x in f))

    def test_no_liquidation_flag_deposit(self):
        tx = _tx(tx_type="DEPOSIT")
        f = _flags(tx)
        self.assertFalse(any("⚡" in x for x in f))

    def test_contract_flag(self):
        tx = _tx(is_contract=True)
        f = _flags(tx)
        self.assertTrue(any("🤖" in x for x in f))

    def test_no_contract_flag_eoa(self):
        tx = _tx(is_contract=False)
        f = _flags(tx)
        self.assertFalse(any("🤖" in x for x in f))

    def test_mega_whale_flag(self):
        tx = _tx(amount_usd=10_000_000)
        f = _flags(tx)
        self.assertTrue(any("🐋" in x for x in f))

    def test_no_mega_whale_flag_small(self):
        tx = _tx(amount_usd=500)
        f = _flags(tx)
        self.assertFalse(any("🐋" in x for x in f))

    def test_large_withdrawal_flag_whale_withdraw(self):
        tx = _tx(amount_usd=1_000_000, tx_type="WITHDRAW")
        f = _flags(tx)
        self.assertTrue(any("🚨" in x for x in f))

    def test_no_large_withdrawal_flag_whale_deposit(self):
        tx = _tx(amount_usd=1_000_000, tx_type="DEPOSIT")
        f = _flags(tx)
        self.assertFalse(any("🚨" in x for x in f))

    def test_no_large_withdrawal_flag_small_withdraw(self):
        # Below WHALE threshold
        tx = _tx(amount_usd=500_000, tx_type="WITHDRAW")
        f = _flags(tx)
        self.assertFalse(any("🚨" in x for x in f))

    def test_empty_flags_clean_tx(self):
        tx = _tx(amount_usd=500, wallet_age_days=30, is_contract=False, tx_type="DEPOSIT")
        f = _flags(tx)
        self.assertEqual(f, [])


# ---------------------------------------------------------------------------
# 4. _risk_level
# ---------------------------------------------------------------------------

class TestRiskLevel(unittest.TestCase):

    def test_critical_mega_whale_high_suspicion(self):
        self.assertEqual(_risk_level("MEGA_WHALE", 0.6), "CRITICAL")

    def test_not_critical_mega_whale_low_suspicion(self):
        # suspicion 0.5 is NOT > 0.5 → not CRITICAL
        result = _risk_level("MEGA_WHALE", 0.5)
        self.assertNotEqual(result, "CRITICAL")

    def test_high_mega_whale_low_suspicion(self):
        # tier is MEGA_WHALE but suspicion ≤ 0.5 → HIGH (because tier in list)
        self.assertEqual(_risk_level("MEGA_WHALE", 0.3), "HIGH")

    def test_high_whale_tier(self):
        self.assertEqual(_risk_level("WHALE", 0.2), "HIGH")

    def test_high_suspicion_above_0_6(self):
        self.assertEqual(_risk_level("LARGE", 0.7), "HIGH")

    def test_medium_large_tier(self):
        self.assertEqual(_risk_level("LARGE", 0.1), "MEDIUM")

    def test_medium_suspicion_above_0_3(self):
        self.assertEqual(_risk_level("MEDIUM", 0.4), "MEDIUM")

    def test_low_medium_tier(self):
        self.assertEqual(_risk_level("MEDIUM", 0.1), "LOW")

    def test_info_below_threshold(self):
        self.assertEqual(_risk_level("BELOW_THRESHOLD", 0.1), "INFO")


# ---------------------------------------------------------------------------
# 5. _action
# ---------------------------------------------------------------------------

class TestAction(unittest.TestCase):

    def test_critical_returns_alert(self):
        self.assertEqual(_action("CRITICAL"), "ALERT")

    def test_high_returns_alert(self):
        self.assertEqual(_action("HIGH"), "ALERT")

    def test_medium_returns_investigate(self):
        self.assertEqual(_action("MEDIUM"), "INVESTIGATE")

    def test_low_returns_monitor(self):
        self.assertEqual(_action("LOW"), "MONITOR")

    def test_info_returns_monitor(self):
        self.assertEqual(_action("INFO"), "MONITOR")


# ---------------------------------------------------------------------------
# 6. detect()
# ---------------------------------------------------------------------------

class TestDetect(unittest.TestCase):

    def test_mega_whale_new_wallet_contract_critical_alert(self):
        tx = _tx(amount_usd=10_000_000, wallet_age_days=0, is_contract=True, tx_type="LIQUIDATE")
        alert = detect(tx)
        self.assertIsNotNone(alert)
        self.assertEqual(alert.alert_tier, "MEGA_WHALE")
        self.assertEqual(alert.risk_level, "CRITICAL")
        self.assertEqual(alert.action, "ALERT")

    def test_small_old_wallet_returns_none(self):
        # amount < 10k → BELOW_THRESHOLD; suspicion = 0.1 < 0.3 → None
        tx = _tx(amount_usd=500, wallet_age_days=30, is_contract=False, tx_type="DEPOSIT")
        self.assertIsNone(detect(tx))

    def test_whale_deposit_old_wallet_returns_high(self):
        tx = _tx(amount_usd=2_000_000, wallet_age_days=30, is_contract=False, tx_type="DEPOSIT")
        alert = detect(tx)
        self.assertIsNotNone(alert)
        self.assertEqual(alert.risk_level, "HIGH")

    def test_below_threshold_new_wallet_returns_alert_due_to_suspicion(self):
        # Below 10k but wallet_age_days=0 → suspicion = 0.1+0.3=0.4 ≥ 0.3 → not None
        tx = _tx(amount_usd=5_000, wallet_age_days=0, is_contract=False, tx_type="DEPOSIT")
        alert = detect(tx)
        self.assertIsNotNone(alert)

    def test_detect_returns_correct_tx_id(self):
        tx = _tx(amount_usd=1_000_000, tx_id="txABC")
        alert = detect(tx)
        self.assertEqual(alert.tx_id, "txABC")

    def test_detect_returns_correct_protocol(self):
        tx = _tx(amount_usd=1_000_000, protocol="Compound")
        alert = detect(tx)
        self.assertEqual(alert.protocol, "Compound")

    def test_detect_returns_correct_amount(self):
        tx = _tx(amount_usd=5_000_000)
        alert = detect(tx)
        self.assertAlmostEqual(alert.amount_usd, 5_000_000)

    def test_detect_large_tier_medium_risk(self):
        tx = _tx(amount_usd=200_000, wallet_age_days=30, is_contract=False, tx_type="DEPOSIT")
        alert = detect(tx)
        self.assertIsNotNone(alert)
        self.assertEqual(alert.alert_tier, "LARGE")
        self.assertEqual(alert.risk_level, "MEDIUM")

    def test_detect_medium_tier_low_risk(self):
        tx = _tx(amount_usd=50_000, wallet_age_days=30, is_contract=False, tx_type="DEPOSIT")
        alert = detect(tx)
        self.assertIsNotNone(alert)
        self.assertEqual(alert.alert_tier, "MEDIUM")
        self.assertEqual(alert.risk_level, "LOW")


# ---------------------------------------------------------------------------
# 7. detect_batch()
# ---------------------------------------------------------------------------

class TestDetectBatch(unittest.TestCase):

    def test_detect_batch_filters_none(self):
        txs = [
            _tx(amount_usd=500, wallet_age_days=30, tx_id="small"),   # → None
            _tx(amount_usd=1_000_000, wallet_age_days=30, tx_id="whale"),  # → alert
        ]
        alerts = detect_batch(txs)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].tx_id, "whale")

    def test_detect_batch_all_none_returns_empty(self):
        txs = [_tx(amount_usd=100, wallet_age_days=30, tx_id=f"t{i}") for i in range(5)]
        self.assertEqual(detect_batch(txs), [])

    def test_detect_batch_all_alerts_returned(self):
        txs = [_tx(amount_usd=1_000_000, tx_id=f"t{i}") for i in range(3)]
        alerts = detect_batch(txs)
        self.assertEqual(len(alerts), 3)

    def test_detect_batch_empty_list(self):
        self.assertEqual(detect_batch([]), [])

    def test_detect_batch_preserves_order(self):
        txs = [
            _tx(amount_usd=1_000_000, tx_id="first"),
            _tx(amount_usd=2_000_000, tx_id="second"),
        ]
        alerts = detect_batch(txs)
        self.assertEqual(alerts[0].tx_id, "first")
        self.assertEqual(alerts[1].tx_id, "second")


# ---------------------------------------------------------------------------
# 8. filter_critical()
# ---------------------------------------------------------------------------

class TestFilterCritical(unittest.TestCase):

    def _make_alert(self, risk_level, tx_id="tx"):
        return WhaleAlert(
            tx_id=tx_id,
            protocol="Aave",
            tx_type="DEPOSIT",
            amount_usd=10_000_000,
            alert_tier="MEGA_WHALE",
            suspicion_score=0.8,
            flags=[],
            risk_level=risk_level,
            action="ALERT",
        )

    def test_filter_critical_returns_only_critical(self):
        alerts = [
            self._make_alert("CRITICAL", "c1"),
            self._make_alert("HIGH", "h1"),
            self._make_alert("CRITICAL", "c2"),
            self._make_alert("MEDIUM", "m1"),
        ]
        critical = filter_critical(alerts)
        self.assertEqual(len(critical), 2)
        self.assertTrue(all(a.risk_level == "CRITICAL" for a in critical))

    def test_filter_critical_empty_input(self):
        self.assertEqual(filter_critical([]), [])

    def test_filter_critical_no_critical_alerts(self):
        alerts = [self._make_alert("HIGH"), self._make_alert("MEDIUM")]
        self.assertEqual(filter_critical(alerts), [])

    def test_filter_critical_all_critical(self):
        alerts = [self._make_alert("CRITICAL", f"c{i}") for i in range(3)]
        self.assertEqual(len(filter_critical(alerts)), 3)


# ---------------------------------------------------------------------------
# 9. save_results / load_history
# ---------------------------------------------------------------------------

class TestPersistence(unittest.TestCase):

    def _simple_alert(self, tx_id="tx_001"):
        tx = _tx(amount_usd=1_000_000, tx_id=tx_id)
        return detect(tx)

    def test_load_history_returns_empty_when_missing(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "nonexistent.json"
            self.assertEqual(load_history(path), [])

    def test_save_creates_file(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "whale_log.json"
            save_results([self._simple_alert()], data_file=path)
            self.assertTrue(path.exists())

    def test_save_and_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "whale_log.json"
            save_results([self._simple_alert()], data_file=path)
            records = load_history(path)
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["tx_id"], "tx_001")

    def test_save_appends_to_existing(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "whale_log.json"
            save_results([self._simple_alert("a1")], data_file=path)
            save_results([self._simple_alert("a2")], data_file=path)
            records = load_history(path)
            self.assertEqual(len(records), 2)

    def test_ring_buffer_max_entries_200(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "whale_log.json"
            max_e = 5
            for i in range(8):
                save_results([self._simple_alert(f"t{i}")], data_file=path, max_entries=max_e)
            records = load_history(path)
            self.assertEqual(len(records), max_e)

    def test_ring_buffer_keeps_latest_entries(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "whale_log.json"
            max_e = 3
            for i in range(6):
                save_results([self._simple_alert(f"t{i}")], data_file=path, max_entries=max_e)
            records = load_history(path)
            tx_ids = [r["tx_id"] for r in records]
            self.assertIn("t5", tx_ids)
            self.assertNotIn("t0", tx_ids)

    def test_atomic_write_no_tmp_left(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "whale_log.json"
            save_results([self._simple_alert()], data_file=path)
            self.assertFalse(path.with_suffix(".tmp").exists())

    def test_load_history_invalid_json_returns_empty(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "whale_log.json"
            path.write_text("INVALID")
            self.assertEqual(load_history(path), [])

    def test_save_multiple_alerts_in_one_call(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "whale_log.json"
            alerts = [self._simple_alert("x1"), self._simple_alert("x2")]
            save_results(alerts, data_file=path)
            records = load_history(path)
            self.assertEqual(len(records), 2)


if __name__ == "__main__":
    unittest.main()
