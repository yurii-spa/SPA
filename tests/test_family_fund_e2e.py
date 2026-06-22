"""
tests/test_family_fund_e2e.py

MP-1395 — Family Fund E2E Test Suite (40 tests)

End-to-end scenarios covering the full investor lifecycle via
InvestorRegistry from spa_core/family_fund/investor_registration.py.

Pure stdlib. No external dependencies. No network/disk side-effects
(each test gets an isolated tempdir that is cleaned up in tearDown).
"""
from __future__ import annotations

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

from spa_core.family_fund.investor_registration import (
    InvestorRecord,
    InvestorRegistry,
    MIN_INVESTMENT_USD,
)


# ---------------------------------------------------------------------------
# Shared setUp / tearDown mixin
# ---------------------------------------------------------------------------

class _RegistryTestCase(unittest.TestCase):
    """Base class providing a fresh isolated InvestorRegistry per test."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self._registry_path = os.path.join(self.tmpdir, "registry.json")
        self.registry = InvestorRegistry(registry_path=self._registry_path)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)


# ===========================================================================
# 1. TestInvestorLifecycleE2E  (8 tests)
# ===========================================================================

class TestInvestorLifecycleE2E(_RegistryTestCase):
    """Full happy-path lifecycle: register → KYC approve → query."""

    # ---- registration ----

    def test_register_returns_pending_record(self) -> None:
        rec = self.registry.register("Alice", "alice@test.com", 50_000)
        self.assertIsInstance(rec, InvestorRecord)
        self.assertEqual(rec.status, "PENDING")

    def test_register_stores_name_email_amount(self) -> None:
        rec = self.registry.register("Bob", "bob@test.com", 25_000)
        self.assertEqual(rec.name, "Bob")
        self.assertEqual(rec.email, "bob@test.com")
        self.assertAlmostEqual(rec.requested_amount_usd, 25_000.0)

    def test_register_sets_created_at(self) -> None:
        rec = self.registry.register("Carol", "carol@test.com", 10_000)
        self.assertIsInstance(rec.created_at, str)
        self.assertTrue(len(rec.created_at) > 0)

    def test_register_generates_investor_id(self) -> None:
        rec = self.registry.register("Dave", "dave@test.com", 15_000)
        self.assertIsInstance(rec.investor_id, str)
        self.assertTrue(len(rec.investor_id) > 0)

    # ---- KYC approval ----

    def test_approve_returns_approved_record(self) -> None:
        rec = self.registry.register("Eve", "eve@test.com", 20_000)
        approved = self.registry.approve(rec.investor_id)
        self.assertEqual(approved.status, "APPROVED")

    def test_approve_sets_approved_at(self) -> None:
        rec = self.registry.register("Frank", "frank@test.com", 30_000)
        approved = self.registry.approve(rec.investor_id)
        self.assertIsNotNone(approved.approved_at)
        self.assertIsInstance(approved.approved_at, str)
        self.assertGreater(len(approved.approved_at), 0)

    def test_approve_accepts_kyc_notes(self) -> None:
        rec = self.registry.register("Grace", "grace@test.com", 100_000)
        notes = "Passport verified, AML clear"
        approved = self.registry.approve(rec.investor_id, kyc_notes=notes)
        self.assertEqual(approved.kyc_notes, notes)

    def test_get_by_id_returns_approved_record(self) -> None:
        rec = self.registry.register("Hank", "hank@test.com", 50_000)
        self.registry.approve(rec.investor_id)
        fetched = self.registry.get(rec.investor_id)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.status, "APPROVED")


# ===========================================================================
# 2. TestMultipleInvestorsConcurrentFlow  (6 tests)
# ===========================================================================

class TestMultipleInvestorsConcurrentFlow(_RegistryTestCase):
    """Three investors registered simultaneously; batch KYC; allocations correct."""

    def _register_three(self) -> tuple:
        a = self.registry.register("Investor-A", "a@test.com", 30_000)
        b = self.registry.register("Investor-B", "b@test.com", 50_000)
        c = self.registry.register("Investor-C", "c@test.com", 20_000)
        return a, b, c

    def test_three_investors_have_distinct_ids(self) -> None:
        a, b, c = self._register_three()
        ids = {a.investor_id, b.investor_id, c.investor_id}
        self.assertEqual(len(ids), 3)

    def test_all_three_initially_pending(self) -> None:
        a, b, c = self._register_three()
        for rec in (a, b, c):
            self.assertEqual(rec.status, "PENDING")

    def test_batch_approve_all_three(self) -> None:
        a, b, c = self._register_three()
        for rec in (a, b, c):
            self.registry.approve(rec.investor_id)
        approved_list = self.registry.list_by_status("APPROVED")
        self.assertEqual(len(approved_list), 3)

    def test_total_committed_sums_all_approved(self) -> None:
        a, b, c = self._register_three()
        for rec in (a, b, c):
            self.registry.approve(rec.investor_id)
        total = self.registry.total_committed_usd()
        self.assertAlmostEqual(total, 100_000.0)

    def test_list_pending_after_partial_approval(self) -> None:
        a, b, c = self._register_three()
        self.registry.approve(a.investor_id)
        pending = self.registry.list_by_status("PENDING")
        self.assertEqual(len(pending), 2)
        pending_ids = {r.investor_id for r in pending}
        self.assertIn(b.investor_id, pending_ids)
        self.assertIn(c.investor_id, pending_ids)

    def test_list_approved_after_batch_approval(self) -> None:
        a, b, c = self._register_three()
        self.registry.approve(a.investor_id)
        self.registry.approve(b.investor_id)
        approved = self.registry.list_by_status("APPROVED")
        approved_ids = {r.investor_id for r in approved}
        self.assertIn(a.investor_id, approved_ids)
        self.assertIn(b.investor_id, approved_ids)
        self.assertNotIn(c.investor_id, approved_ids)


# ===========================================================================
# 3. TestRejectionFlow  (7 tests)
# ===========================================================================

class TestRejectionFlow(_RegistryTestCase):
    """Register → KYC reject → re-register on different email → new attempt."""

    def test_register_then_reject_sets_rejected_status(self) -> None:
        rec = self.registry.register("Ivan", "ivan@test.com", 10_000)
        rejected = self.registry.reject(rec.investor_id, "Failed AML check")
        self.assertEqual(rejected.status, "REJECTED")

    def test_reject_stores_reason(self) -> None:
        rec = self.registry.register("Jules", "jules@test.com", 15_000)
        reason = "Incomplete documentation"
        rejected = self.registry.reject(rec.investor_id, reason)
        self.assertEqual(rejected.rejected_reason, reason)

    def test_rejected_not_in_approved_list(self) -> None:
        rec = self.registry.register("Kim", "kim@test.com", 20_000)
        self.registry.reject(rec.investor_id, "Sanctions hit")
        approved = self.registry.list_by_status("APPROVED")
        approved_ids = {r.investor_id for r in approved}
        self.assertNotIn(rec.investor_id, approved_ids)

    def test_rejected_appears_in_rejected_list(self) -> None:
        rec = self.registry.register("Leo", "leo@test.com", 25_000)
        self.registry.reject(rec.investor_id, "PEP match")
        rejected_list = self.registry.list_by_status("REJECTED")
        self.assertEqual(len(rejected_list), 1)
        self.assertEqual(rejected_list[0].investor_id, rec.investor_id)

    def test_reregister_different_email_allowed(self) -> None:
        rec = self.registry.register("Mike", "mike@test.com", 30_000)
        self.registry.reject(rec.investor_id, "Invalid docs")
        # New registration with different email must succeed
        new_rec = self.registry.register("Mike", "mike2@test.com", 30_000)
        self.assertEqual(new_rec.status, "PENDING")

    def test_reregister_same_email_blocked_after_reject(self) -> None:
        rec = self.registry.register("Nina", "nina@test.com", 10_000)
        self.registry.reject(rec.investor_id, "AML block")
        with self.assertRaises(ValueError):
            self.registry.register("Nina", "nina@test.com", 10_000)

    def test_cannot_approve_rejected_investor(self) -> None:
        rec = self.registry.register("Omar", "omar@test.com", 50_000)
        self.registry.reject(rec.investor_id, "Source of funds unclear")
        with self.assertRaises(ValueError):
            self.registry.approve(rec.investor_id)


# ===========================================================================
# 4. TestSuspensionFlow  (7 tests)
# ===========================================================================

class TestSuspensionFlow(_RegistryTestCase):
    """Approved investor violates terms → suspend → data retained."""

    def _register_and_approve(self, name: str, email: str, amount: float) -> InvestorRecord:
        rec = self.registry.register(name, email, amount)
        return self.registry.approve(rec.investor_id)

    def test_approve_then_suspend(self) -> None:
        rec = self._register_and_approve("Pam", "pam@test.com", 40_000)
        suspended = self.registry.suspend(rec.investor_id, "Terms violation")
        self.assertEqual(suspended.status, "SUSPENDED")

    def test_suspend_stores_reason(self) -> None:
        rec = self._register_and_approve("Quinn", "quinn@test.com", 20_000)
        reason = "Suspicious activity"
        suspended = self.registry.suspend(rec.investor_id, reason)
        self.assertEqual(suspended.suspended_reason, reason)

    def test_suspended_not_in_approved_list(self) -> None:
        rec = self._register_and_approve("Rosa", "rosa@test.com", 30_000)
        self.registry.suspend(rec.investor_id, "T&C breach")
        approved = self.registry.list_by_status("APPROVED")
        approved_ids = {r.investor_id for r in approved}
        self.assertNotIn(rec.investor_id, approved_ids)

    def test_suspended_in_suspended_list(self) -> None:
        rec = self._register_and_approve("Sam", "sam@test.com", 50_000)
        self.registry.suspend(rec.investor_id, "Fraud suspicion")
        suspended_list = self.registry.list_by_status("SUSPENDED")
        self.assertEqual(len(suspended_list), 1)
        self.assertEqual(suspended_list[0].investor_id, rec.investor_id)

    def test_suspended_not_counted_in_total_committed(self) -> None:
        rec_ok = self._register_and_approve("Tara", "tara@test.com", 60_000)
        rec_susp = self._register_and_approve("Uma", "uma@test.com", 40_000)
        self.registry.suspend(rec_susp.investor_id, "Compliance issue")
        total = self.registry.total_committed_usd()
        self.assertAlmostEqual(total, 60_000.0)

    def test_cannot_suspend_pending_investor(self) -> None:
        rec = self.registry.register("Vera", "vera@test.com", 10_000)
        with self.assertRaises(ValueError):
            self.registry.suspend(rec.investor_id, "Should fail")

    def test_cannot_approve_suspended_investor(self) -> None:
        rec = self._register_and_approve("Will", "will@test.com", 15_000)
        self.registry.suspend(rec.investor_id, "Suspended for review")
        with self.assertRaises(ValueError):
            self.registry.approve(rec.investor_id)


# ===========================================================================
# 5. TestMinimumInvestmentGate  (6 tests)
# ===========================================================================

class TestMinimumInvestmentGate(_RegistryTestCase):
    """Investment amount validation: minimum $10K."""

    def test_exact_minimum_allowed(self) -> None:
        rec = self.registry.register("Xena", "xena@test.com", MIN_INVESTMENT_USD)
        self.assertEqual(rec.status, "PENDING")
        self.assertAlmostEqual(rec.requested_amount_usd, MIN_INVESTMENT_USD)

    def test_five_thousand_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.registry.register("Yolanda", "yolanda@test.com", 5_000)

    def test_zero_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.registry.register("Zack", "zack@test.com", 0)

    def test_just_below_minimum_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.registry.register("Ana", "ana@test.com", MIN_INVESTMENT_USD - 0.01)

    def test_error_message_mentions_minimum(self) -> None:
        try:
            self.registry.register("Ben", "ben@test.com", 1_000)
        except ValueError as exc:
            # Error message formats the amount with locale commas, e.g. "$10,000"
            msg = str(exc)
            self.assertTrue(
                "10,000" in msg or "10000" in msg,
                f"Expected minimum amount in error message, got: {msg!r}",
            )
        else:
            self.fail("ValueError not raised for amount below minimum")

    def test_above_minimum_always_succeeds(self) -> None:
        for amount in (10_001, 25_000, 100_000, 999_999):
            email = f"investor_{amount}@test.com"
            rec = self.registry.register(f"Inv-{amount}", email, amount)
            self.assertEqual(rec.status, "PENDING")


# ===========================================================================
# 6. TestFamilyFundCapacity  (6 tests)
# ===========================================================================

class TestFamilyFundCapacity(_RegistryTestCase):
    """Beyond 10 investors → controlled behavior, no crash."""

    def _bulk_register(self, n: int, prefix: str = "cap") -> list:
        """Register n investors; returns list of InvestorRecord."""
        records = []
        for i in range(n):
            rec = self.registry.register(
                name=f"Investor-{prefix}-{i}",
                email=f"{prefix}_{i}@test.com",
                amount_usd=10_000 + i * 1_000,
            )
            records.append(rec)
        return records

    def test_ten_investors_register_successfully(self) -> None:
        records = self._bulk_register(10)
        self.assertEqual(len(records), 10)
        for rec in records:
            self.assertEqual(rec.status, "PENDING")

    def test_eleventh_investor_no_crash(self) -> None:
        self._bulk_register(10)
        # 11th investor must not raise (no hard cap in registry)
        rec = self.registry.register("Extra-11", "extra_11@test.com", 10_000)
        self.assertIsInstance(rec, InvestorRecord)
        self.assertEqual(rec.status, "PENDING")

    def test_twenty_investors_all_registered(self) -> None:
        records = self._bulk_register(20)
        pending = self.registry.list_by_status("PENDING")
        self.assertEqual(len(pending), 20)

    def test_capacity_all_ids_unique(self) -> None:
        records = self._bulk_register(15)
        ids = [r.investor_id for r in records]
        self.assertEqual(len(ids), len(set(ids)))

    def test_capacity_all_pending_status(self) -> None:
        records = self._bulk_register(12)
        statuses = {r.status for r in records}
        self.assertEqual(statuses, {"PENDING"})

    def test_capacity_total_committed_after_all_approved(self) -> None:
        records = self._bulk_register(5, prefix="total")
        for rec in records:
            self.registry.approve(rec.investor_id)
        expected = sum(10_000 + i * 1_000 for i in range(5))
        total = self.registry.total_committed_usd()
        self.assertAlmostEqual(total, float(expected))


# ===========================================================================
# Entry point
# ===========================================================================

if __name__ == "__main__":
    unittest.main(verbosity=2)
