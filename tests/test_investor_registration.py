"""
tests/test_investor_registration.py

MP-1365 — 40 unit tests for spa_core/family_fund/investor_registration.py

Run:
    python3 -m unittest tests.test_investor_registration -v
    python3 -m unittest tests/test_investor_registration.py -v
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from spa_core.family_fund.investor_registration import (
    InvestorRecord,
    InvestorRegistry,
    MIN_INVESTMENT_USD,
    LOCK_UP_DAYS,
    INVESTOR_STATUSES,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_registry(tmp_dir: str) -> InvestorRegistry:
    path = os.path.join(tmp_dir, "investor_registry.json")
    reg = InvestorRegistry(registry_path=path)
    reg.load()
    return reg


def _register_one(reg: InvestorRegistry, email: str = "alice@example.com",
                  name: str = "Alice", amount: float = 50_000.0) -> InvestorRecord:
    return reg.register(name=name, email=email, amount_usd=amount)


# ---------------------------------------------------------------------------
# Test classes
# ---------------------------------------------------------------------------

class TestConstants(unittest.TestCase):
    """Tests for module-level constants."""

    def test_min_investment_is_10k(self):
        self.assertEqual(MIN_INVESTMENT_USD, 10_000.0)

    def test_lockup_days_is_90(self):
        self.assertEqual(LOCK_UP_DAYS, 90)

    def test_investor_statuses_contain_pending(self):
        self.assertIn("PENDING", INVESTOR_STATUSES)

    def test_investor_statuses_contain_approved(self):
        self.assertIn("APPROVED", INVESTOR_STATUSES)

    def test_investor_statuses_contain_rejected(self):
        self.assertIn("REJECTED", INVESTOR_STATUSES)

    def test_investor_statuses_contain_suspended(self):
        self.assertIn("SUSPENDED", INVESTOR_STATUSES)


class TestRegisterBasic(unittest.TestCase):
    """Tests for register() core behaviour."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.reg = _make_registry(self.tmp)

    def test_register_returns_investor_record(self):
        rec = _register_one(self.reg)
        self.assertIsInstance(rec, InvestorRecord)

    def test_register_status_is_pending(self):
        rec = _register_one(self.reg)
        self.assertEqual(rec.status, "PENDING")

    def test_register_stores_name(self):
        rec = _register_one(self.reg, name="Bob")
        self.assertEqual(rec.name, "Bob")

    def test_register_stores_email(self):
        rec = _register_one(self.reg, email="bob@example.com")
        self.assertEqual(rec.email, "bob@example.com")

    def test_register_stores_amount(self):
        rec = _register_one(self.reg, amount=25_000.0)
        self.assertAlmostEqual(rec.requested_amount_usd, 25_000.0)

    def test_register_sets_created_at(self):
        rec = _register_one(self.reg)
        self.assertIsNotNone(rec.created_at)
        self.assertGreater(len(rec.created_at), 0)

    def test_register_approved_at_is_none(self):
        rec = _register_one(self.reg)
        self.assertIsNone(rec.approved_at)

    def test_register_rejected_reason_is_none(self):
        rec = _register_one(self.reg)
        self.assertIsNone(rec.rejected_reason)

    def test_register_kyc_notes_empty(self):
        rec = _register_one(self.reg)
        self.assertEqual(rec.kyc_notes, "")

    def test_register_investor_id_not_empty(self):
        rec = _register_one(self.reg)
        self.assertTrue(len(rec.investor_id) > 0)


class TestRegisterValidation(unittest.TestCase):
    """Tests for register() validation errors."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.reg = _make_registry(self.tmp)

    def test_register_raises_if_amount_below_minimum(self):
        with self.assertRaises(ValueError):
            self.reg.register("X", "x@x.com", 9_999.0)

    def test_register_raises_if_amount_zero(self):
        with self.assertRaises(ValueError):
            self.reg.register("X", "x@x.com", 0.0)

    def test_register_raises_if_amount_negative(self):
        with self.assertRaises(ValueError):
            self.reg.register("X", "x@x.com", -500.0)

    def test_register_raises_if_amount_exactly_below_minimum(self):
        with self.assertRaises(ValueError):
            self.reg.register("X", "x@x.com", MIN_INVESTMENT_USD - 0.01)

    def test_register_ok_at_minimum(self):
        rec = self.reg.register("X", "x@x.com", MIN_INVESTMENT_USD)
        self.assertEqual(rec.status, "PENDING")

    def test_register_raises_duplicate_email(self):
        _register_one(self.reg, email="dup@example.com")
        with self.assertRaises(ValueError):
            self.reg.register("Other", "dup@example.com", 20_000.0)

    def test_register_raises_duplicate_email_case_insensitive(self):
        _register_one(self.reg, email="Alice@Example.com")
        with self.assertRaises(ValueError):
            self.reg.register("Other", "alice@example.com", 20_000.0)

    def test_unique_ids_for_different_emails(self):
        r1 = _register_one(self.reg, email="a@x.com")
        r2 = _register_one(self.reg, email="b@x.com")
        self.assertNotEqual(r1.investor_id, r2.investor_id)


class TestApprove(unittest.TestCase):
    """Tests for approve()."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.reg = _make_registry(self.tmp)
        self.rec = _register_one(self.reg)

    def test_approve_sets_status_approved(self):
        updated = self.reg.approve(self.rec.investor_id)
        self.assertEqual(updated.status, "APPROVED")

    def test_approve_sets_approved_at(self):
        updated = self.reg.approve(self.rec.investor_id)
        self.assertIsNotNone(updated.approved_at)

    def test_approve_stores_kyc_notes(self):
        updated = self.reg.approve(self.rec.investor_id, kyc_notes="ID verified")
        self.assertEqual(updated.kyc_notes, "ID verified")

    def test_approve_raises_if_not_pending(self):
        self.reg.approve(self.rec.investor_id)
        with self.assertRaises(ValueError):
            self.reg.approve(self.rec.investor_id)

    def test_approve_raises_if_investor_not_found(self):
        with self.assertRaises(KeyError):
            self.reg.approve("nonexistent-id")


class TestReject(unittest.TestCase):
    """Tests for reject()."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.reg = _make_registry(self.tmp)
        self.rec = _register_one(self.reg)

    def test_reject_sets_status_rejected(self):
        updated = self.reg.reject(self.rec.investor_id, reason="Incomplete docs")
        self.assertEqual(updated.status, "REJECTED")

    def test_reject_stores_reason(self):
        updated = self.reg.reject(self.rec.investor_id, reason="Fraud risk")
        self.assertEqual(updated.rejected_reason, "Fraud risk")

    def test_reject_raises_if_not_pending(self):
        self.reg.reject(self.rec.investor_id, reason="r1")
        with self.assertRaises(ValueError):
            self.reg.reject(self.rec.investor_id, reason="r2")

    def test_reject_raises_if_investor_not_found(self):
        with self.assertRaises(KeyError):
            self.reg.reject("bad-id", reason="n/a")


class TestSuspend(unittest.TestCase):
    """Tests for suspend()."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.reg = _make_registry(self.tmp)
        rec = _register_one(self.reg)
        self.reg.approve(rec.investor_id)
        self.investor_id = rec.investor_id

    def test_suspend_sets_status_suspended(self):
        updated = self.reg.suspend(self.investor_id, reason="AML flag")
        self.assertEqual(updated.status, "SUSPENDED")

    def test_suspend_stores_reason(self):
        updated = self.reg.suspend(self.investor_id, reason="Compliance issue")
        self.assertEqual(updated.suspended_reason, "Compliance issue")

    def test_suspend_raises_if_not_approved(self):
        tmp2 = tempfile.mkdtemp()
        reg2 = _make_registry(tmp2)
        rec2 = _register_one(reg2, email="pending@x.com")
        with self.assertRaises(ValueError):
            reg2.suspend(rec2.investor_id, reason="x")

    def test_suspend_raises_if_investor_not_found(self):
        with self.assertRaises(KeyError):
            self.reg.suspend("ghost", reason="x")


class TestListAndQuery(unittest.TestCase):
    """Tests for list_by_status(), get(), total_committed_usd()."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.reg = _make_registry(self.tmp)
        # Alice: APPROVED
        r1 = _register_one(self.reg, email="alice@x.com", amount=30_000.0)
        self.reg.approve(r1.investor_id)
        self.alice_id = r1.investor_id
        # Bob: PENDING
        r2 = _register_one(self.reg, email="bob@x.com", amount=20_000.0)
        self.bob_id = r2.investor_id
        # Carol: REJECTED
        r3 = _register_one(self.reg, email="carol@x.com", amount=15_000.0)
        self.reg.reject(r3.investor_id, reason="docs")
        self.carol_id = r3.investor_id

    def test_list_by_status_pending_returns_only_pending(self):
        pending = self.reg.list_by_status("PENDING")
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].investor_id, self.bob_id)

    def test_list_by_status_approved_returns_only_approved(self):
        approved = self.reg.list_by_status("APPROVED")
        self.assertEqual(len(approved), 1)
        self.assertEqual(approved[0].investor_id, self.alice_id)

    def test_list_by_status_rejected_returns_only_rejected(self):
        rejected = self.reg.list_by_status("REJECTED")
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0].investor_id, self.carol_id)

    def test_list_by_status_empty_for_suspended(self):
        self.assertEqual(self.reg.list_by_status("SUSPENDED"), [])

    def test_get_returns_record(self):
        rec = self.reg.get(self.alice_id)
        self.assertIsNotNone(rec)
        self.assertEqual(rec.investor_id, self.alice_id)

    def test_get_returns_none_for_unknown(self):
        self.assertIsNone(self.reg.get("does-not-exist"))

    def test_total_committed_sums_approved_only(self):
        total = self.reg.total_committed_usd()
        self.assertAlmostEqual(total, 30_000.0)

    def test_total_committed_zero_when_no_approved(self):
        tmp = tempfile.mkdtemp()
        reg = _make_registry(tmp)
        rec = _register_one(reg, email="z@x.com")
        self.assertAlmostEqual(reg.total_committed_usd(), 0.0)


class TestSave(unittest.TestCase):
    """Tests for atomic save() and load() round-trip."""

    def test_save_creates_file(self):
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "investor_registry.json")
        reg = InvestorRegistry(registry_path=path)
        reg.load()
        _register_one(reg)
        reg.save()
        self.assertTrue(os.path.exists(path))

    def test_save_and_reload_preserves_data(self):
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "investor_registry.json")
        reg = InvestorRegistry(registry_path=path)
        reg.load()
        rec = reg.register("Saved", "saved@x.com", 12_000.0)
        reg.approve(rec.investor_id)
        reg.save()

        reg2 = InvestorRegistry(registry_path=path)
        reg2.load()
        loaded = reg2.get(rec.investor_id)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.status, "APPROVED")
        self.assertEqual(loaded.name, "Saved")

    def test_load_from_missing_file_gives_empty(self):
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "missing.json")
        reg = InvestorRegistry(registry_path=path)
        reg.load()
        self.assertEqual(reg.list_by_status("PENDING"), [])

    def test_save_creates_parent_dirs(self):
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "nested", "dir", "registry.json")
        reg = InvestorRegistry(registry_path=path)
        reg.load()
        _register_one(reg)
        reg.save()
        self.assertTrue(os.path.exists(path))


if __name__ == "__main__":
    unittest.main(verbosity=2)
