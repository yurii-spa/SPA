"""
tests/test_withdrawal_engine.py

MP-1396 — Withdrawal Engine Test Suite (35 tests)

Covers:
  - WithdrawalRequest dataclass fields and defaults
  - WithdrawalEngine.request_withdrawal() — creation & validation
  - approve() / reject() / complete() state transitions
  - get_pending() filtering
  - investor_total_withdrawn() aggregation
  - save() / load() round-trip (atomic persistence)

Pure stdlib. No external dependencies. Each test uses an isolated tmpdir.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

# ---------------------------------------------------------------------------
# Ensure project root on sys.path
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from spa_core.family_fund.withdrawal_engine import (
    WithdrawalEngine,
    WithdrawalRequest,
    WithdrawalStatus,
)


# ---------------------------------------------------------------------------
# Shared setUp / tearDown
# ---------------------------------------------------------------------------

class _EngineTestCase(unittest.TestCase):
    """Base class providing a fresh WithdrawalEngine per test."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.engine = WithdrawalEngine(base_dir=self.tmpdir)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)


# ===========================================================================
# 1. TestWithdrawalRequestDataclass  (5 tests)
# ===========================================================================

class TestWithdrawalRequestDataclass(unittest.TestCase):
    """WithdrawalRequest dataclass fields and default values."""

    def _make(self, **kwargs) -> WithdrawalRequest:
        defaults = dict(request_id="r1", investor_id="inv-001", amount_usd=5_000.0)
        defaults.update(kwargs)
        return WithdrawalRequest(**defaults)

    def test_dataclass_has_request_id(self) -> None:
        req = self._make(request_id="req-123")
        self.assertEqual(req.request_id, "req-123")

    def test_dataclass_has_investor_id(self) -> None:
        req = self._make(investor_id="inv-999")
        self.assertEqual(req.investor_id, "inv-999")

    def test_dataclass_has_amount_usd(self) -> None:
        req = self._make(amount_usd=12_345.67)
        self.assertAlmostEqual(req.amount_usd, 12_345.67)

    def test_default_status_is_requested(self) -> None:
        req = self._make()
        self.assertEqual(req.status, WithdrawalStatus.REQUESTED)

    def test_default_completed_at_is_none(self) -> None:
        req = self._make()
        self.assertIsNone(req.completed_at)


# ===========================================================================
# 2. TestRequestWithdrawal  (8 tests)
# ===========================================================================

class TestRequestWithdrawal(_EngineTestCase):
    """WithdrawalEngine.request_withdrawal() — creation and validation."""

    def test_request_creates_withdrawal_object(self) -> None:
        req = self.engine.request_withdrawal("inv-001", 2_000)
        self.assertIsInstance(req, WithdrawalRequest)

    def test_request_status_is_requested(self) -> None:
        req = self.engine.request_withdrawal("inv-001", 3_000)
        self.assertEqual(req.status, WithdrawalStatus.REQUESTED)

    def test_request_stores_investor_id(self) -> None:
        req = self.engine.request_withdrawal("inv-abc", 1_500)
        self.assertEqual(req.investor_id, "inv-abc")

    def test_request_stores_amount(self) -> None:
        req = self.engine.request_withdrawal("inv-001", 7_777.77)
        self.assertAlmostEqual(req.amount_usd, 7_777.77, places=2)

    def test_request_sets_requested_at_timestamp(self) -> None:
        req = self.engine.request_withdrawal("inv-001", 1_000)
        self.assertIsInstance(req.requested_at, str)
        self.assertGreater(len(req.requested_at), 0)

    def test_request_below_minimum_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            self.engine.request_withdrawal("inv-001", 999.99)

    def test_request_exact_minimum_succeeds(self) -> None:
        req = self.engine.request_withdrawal("inv-001", WithdrawalEngine.MIN_WITHDRAWAL)
        self.assertEqual(req.status, WithdrawalStatus.REQUESTED)

    def test_multiple_requests_generate_unique_ids(self) -> None:
        r1 = self.engine.request_withdrawal("inv-001", 1_000)
        r2 = self.engine.request_withdrawal("inv-001", 2_000)
        r3 = self.engine.request_withdrawal("inv-001", 3_000)
        ids = {r1.request_id, r2.request_id, r3.request_id}
        self.assertEqual(len(ids), 3)


# ===========================================================================
# 3. TestApproveWithdrawal  (5 tests)
# ===========================================================================

class TestApproveWithdrawal(_EngineTestCase):
    """approve() state machine transitions."""

    def test_approve_changes_status_to_approved(self) -> None:
        req = self.engine.request_withdrawal("inv-001", 5_000)
        approved = self.engine.approve(req.request_id)
        self.assertEqual(approved.status, WithdrawalStatus.APPROVED)

    def test_approve_stores_processing_notes(self) -> None:
        req = self.engine.request_withdrawal("inv-002", 2_000)
        note = "Fund liquidity confirmed"
        approved = self.engine.approve(req.request_id, notes=note)
        self.assertEqual(approved.processing_notes, note)

    def test_approve_nonexistent_request_raises_key_error(self) -> None:
        with self.assertRaises(KeyError):
            self.engine.approve("does-not-exist")

    def test_approve_already_completed_raises_value_error(self) -> None:
        req = self.engine.request_withdrawal("inv-003", 1_000)
        self.engine.approve(req.request_id)
        self.engine.complete(req.request_id)
        with self.assertRaises(ValueError):
            self.engine.approve(req.request_id)

    def test_approve_rejected_request_raises_value_error(self) -> None:
        req = self.engine.request_withdrawal("inv-004", 1_000)
        self.engine.reject(req.request_id, "Insufficient balance")
        with self.assertRaises(ValueError):
            self.engine.approve(req.request_id)


# ===========================================================================
# 4. TestRejectWithdrawal  (5 tests)
# ===========================================================================

class TestRejectWithdrawal(_EngineTestCase):
    """reject() state machine transitions."""

    def test_reject_changes_status_to_rejected(self) -> None:
        req = self.engine.request_withdrawal("inv-001", 1_500)
        rejected = self.engine.reject(req.request_id, "AML hold")
        self.assertEqual(rejected.status, WithdrawalStatus.REJECTED)

    def test_reject_stores_reason(self) -> None:
        req = self.engine.request_withdrawal("inv-002", 2_000)
        reason = "Lock-up period not expired"
        rejected = self.engine.reject(req.request_id, reason)
        self.assertEqual(rejected.rejection_reason, reason)

    def test_reject_nonexistent_request_raises_key_error(self) -> None:
        with self.assertRaises(KeyError):
            self.engine.reject("ghost-id", "reason")

    def test_reject_completed_request_raises_value_error(self) -> None:
        req = self.engine.request_withdrawal("inv-003", 1_000)
        self.engine.approve(req.request_id)
        self.engine.complete(req.request_id)
        with self.assertRaises(ValueError):
            self.engine.reject(req.request_id, "Too late")

    def test_reject_already_rejected_raises_value_error(self) -> None:
        req = self.engine.request_withdrawal("inv-004", 1_000)
        self.engine.reject(req.request_id, "First rejection")
        with self.assertRaises(ValueError):
            self.engine.reject(req.request_id, "Second rejection")


# ===========================================================================
# 5. TestCompleteWithdrawal  (5 tests)
# ===========================================================================

class TestCompleteWithdrawal(_EngineTestCase):
    """complete() state machine transitions."""

    def test_complete_changes_status_to_completed(self) -> None:
        req = self.engine.request_withdrawal("inv-001", 3_000)
        self.engine.approve(req.request_id)
        completed = self.engine.complete(req.request_id)
        self.assertEqual(completed.status, WithdrawalStatus.COMPLETED)

    def test_complete_sets_completed_at_timestamp(self) -> None:
        req = self.engine.request_withdrawal("inv-002", 4_000)
        self.engine.approve(req.request_id)
        completed = self.engine.complete(req.request_id)
        self.assertIsNotNone(completed.completed_at)
        self.assertIsInstance(completed.completed_at, str)
        self.assertGreater(len(completed.completed_at), 0)

    def test_complete_nonexistent_request_raises_key_error(self) -> None:
        with self.assertRaises(KeyError):
            self.engine.complete("no-such-id")

    def test_double_complete_raises_value_error(self) -> None:
        req = self.engine.request_withdrawal("inv-003", 5_000)
        self.engine.approve(req.request_id)
        self.engine.complete(req.request_id)
        with self.assertRaises(ValueError):
            self.engine.complete(req.request_id)

    def test_complete_non_approved_raises_value_error(self) -> None:
        req = self.engine.request_withdrawal("inv-004", 1_000)
        # Status is REQUESTED (not yet approved) — complete must fail
        with self.assertRaises(ValueError):
            self.engine.complete(req.request_id)


# ===========================================================================
# 6. TestGetPending  (4 tests)
# ===========================================================================

class TestGetPending(_EngineTestCase):
    """get_pending() returns only REQUESTED and PENDING_REVIEW requests."""

    def test_get_pending_includes_requested(self) -> None:
        req = self.engine.request_withdrawal("inv-001", 1_000)
        pending = self.engine.get_pending()
        self.assertIn(req, pending)

    def test_get_pending_includes_pending_review_status(self) -> None:
        req = self.engine.request_withdrawal("inv-002", 2_000)
        req.status = WithdrawalStatus.PENDING_REVIEW  # direct state injection
        pending = self.engine.get_pending()
        self.assertIn(req, pending)

    def test_get_pending_excludes_completed(self) -> None:
        req = self.engine.request_withdrawal("inv-003", 3_000)
        self.engine.approve(req.request_id)
        self.engine.complete(req.request_id)
        pending = self.engine.get_pending()
        self.assertNotIn(req, pending)

    def test_get_pending_excludes_rejected(self) -> None:
        req = self.engine.request_withdrawal("inv-004", 1_000)
        self.engine.reject(req.request_id, "Compliance block")
        pending = self.engine.get_pending()
        self.assertNotIn(req, pending)


# ===========================================================================
# 7. TestInvestorTotalWithdrawnAndPersistence  (3 tests)
# ===========================================================================

class TestInvestorTotalWithdrawnAndPersistence(_EngineTestCase):
    """investor_total_withdrawn() and save/load round-trip."""

    def test_total_withdrawn_sums_completed_only(self) -> None:
        r1 = self.engine.request_withdrawal("inv-001", 5_000)
        r2 = self.engine.request_withdrawal("inv-001", 3_000)
        # Approve and complete r1; leave r2 as REQUESTED
        self.engine.approve(r1.request_id)
        self.engine.complete(r1.request_id)
        total = self.engine.investor_total_withdrawn("inv-001")
        self.assertAlmostEqual(total, 5_000.0)

    def test_total_withdrawn_excludes_non_completed(self) -> None:
        r1 = self.engine.request_withdrawal("inv-002", 10_000)
        self.engine.reject(r1.request_id, "Insufficient liquidity")
        total = self.engine.investor_total_withdrawn("inv-002")
        self.assertAlmostEqual(total, 0.0)

    def test_save_and_load_round_trip(self) -> None:
        r1 = self.engine.request_withdrawal("inv-001", 8_000)
        self.engine.approve(r1.request_id)
        self.engine.complete(r1.request_id)
        r2 = self.engine.request_withdrawal("inv-002", 4_500)
        self.engine.reject(r2.request_id, "Lock-up")

        self.engine.save()

        # Fresh engine loading from same base_dir
        engine2 = WithdrawalEngine(base_dir=self.tmpdir)
        engine2.load()

        req_loaded = engine2._requests.get(r1.request_id)
        self.assertIsNotNone(req_loaded)
        self.assertEqual(req_loaded.status, WithdrawalStatus.COMPLETED)
        self.assertAlmostEqual(req_loaded.amount_usd, 8_000.0)

        req2_loaded = engine2._requests.get(r2.request_id)
        self.assertIsNotNone(req2_loaded)
        self.assertEqual(req2_loaded.status, WithdrawalStatus.REJECTED)
        self.assertEqual(req2_loaded.rejection_reason, "Lock-up")


# ===========================================================================
# Entry point
# ===========================================================================

if __name__ == "__main__":
    unittest.main(verbosity=2)
