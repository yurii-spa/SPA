"""
tests/test_kyc_manager.py — 25 unit tests for spa_core.family_fund.kyc_manager (MP-1480)
"""
import sys
import json
import unittest
import tempfile
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from spa_core.family_fund.kyc_manager import (
    KYCManager,
    KYCRecord,
    KYCStatus,
    KYC_EXPIRY_DAYS,
)


# ---------------------------------------------------------------------------
# 1. TestKYCStatus (3 tests)
# ---------------------------------------------------------------------------
class TestKYCStatus(unittest.TestCase):
    def test_enum_values_exist(self):
        """All four status variants are defined."""
        self.assertIn("PENDING", KYCStatus.__members__)
        self.assertIn("APPROVED", KYCStatus.__members__)
        self.assertIn("REJECTED", KYCStatus.__members__)
        self.assertIn("EXPIRED", KYCStatus.__members__)

    def test_enum_string_values(self):
        """Enum values match their string names."""
        self.assertEqual(KYCStatus.PENDING.value, "PENDING")
        self.assertEqual(KYCStatus.APPROVED.value, "APPROVED")
        self.assertEqual(KYCStatus.REJECTED.value, "REJECTED")
        self.assertEqual(KYCStatus.EXPIRED.value, "EXPIRED")

    def test_enum_is_str(self):
        """KYCStatus inherits str — can be used as a JSON-serializable string."""
        self.assertIsInstance(KYCStatus.PENDING, str)
        self.assertEqual(KYCStatus.PENDING, "PENDING")


# ---------------------------------------------------------------------------
# 2. TestKYCRecord (4 tests)
# ---------------------------------------------------------------------------
class TestKYCRecord(unittest.TestCase):
    def _sample(self) -> KYCRecord:
        return KYCRecord(
            investor_id="inv-001",
            status=KYCStatus.APPROVED,
            documents=["passport.pdf", "utility_bill.pdf"],
            submitted_at="2026-01-01T00:00:00+00:00",
            approved_at="2026-01-02T00:00:00+00:00",
            rejected_at=None,
            expires_at="2027-01-02T00:00:00+00:00",
            rejection_reason=None,
        )

    def test_to_dict_round_trip(self):
        """to_dict produces a plain dict with correct keys."""
        rec = self._sample()
        d = rec.to_dict()
        self.assertEqual(d["investor_id"], "inv-001")
        self.assertEqual(d["status"], "APPROVED")
        self.assertEqual(d["documents"], ["passport.pdf", "utility_bill.pdf"])
        self.assertIsNone(d["rejected_at"])

    def test_from_dict_round_trip(self):
        """from_dict(to_dict(rec)) reproduces the original record."""
        rec = self._sample()
        rec2 = KYCRecord.from_dict(rec.to_dict())
        self.assertEqual(rec2.investor_id, rec.investor_id)
        self.assertEqual(rec2.status, rec.status)
        self.assertEqual(rec2.documents, rec.documents)
        self.assertEqual(rec2.approved_at, rec.approved_at)
        self.assertEqual(rec2.expires_at, rec.expires_at)

    def test_default_fields(self):
        """A minimal KYCRecord has PENDING status and empty documents."""
        rec = KYCRecord(investor_id="inv-002")
        self.assertEqual(rec.status, KYCStatus.PENDING)
        self.assertEqual(rec.documents, [])
        self.assertIsNone(rec.submitted_at)
        self.assertIsNone(rec.approved_at)
        self.assertIsNone(rec.expires_at)
        self.assertIsNone(rec.rejection_reason)

    def test_from_dict_missing_optional_fields(self):
        """from_dict handles a minimal dict with only investor_id."""
        rec = KYCRecord.from_dict({"investor_id": "inv-003"})
        self.assertEqual(rec.investor_id, "inv-003")
        self.assertEqual(rec.status, KYCStatus.PENDING)
        self.assertEqual(rec.documents, [])
        self.assertIsNone(rec.submitted_at)
        self.assertIsNone(rec.rejection_reason)


# ---------------------------------------------------------------------------
# 3. TestKYCManagerInit (2 tests)
# ---------------------------------------------------------------------------
class TestKYCManagerInit(unittest.TestCase):
    def test_init_without_existing_file(self):
        """Manager initializes cleanly when data file does not exist."""
        with tempfile.TemporaryDirectory() as tmp:
            mgr = KYCManager(data_file="kyc.json", base_dir=tmp)
            self.assertEqual(mgr.list_records(), [])

    def test_init_with_existing_file(self):
        """Manager loads records from an existing file on init."""
        with tempfile.TemporaryDirectory() as tmp:
            # Pre-populate a file
            path = os.path.join(tmp, "kyc.json")
            data = {
                "records": [
                    {"investor_id": "inv-pre", "status": "PENDING", "documents": []}
                ],
                "updated_at": "2026-01-01T00:00:00+00:00",
            }
            with open(path, "w") as fh:
                json.dump(data, fh)
            mgr = KYCManager(data_file=path)
            recs = mgr.list_records()
            self.assertEqual(len(recs), 1)
            self.assertEqual(recs[0].investor_id, "inv-pre")


# ---------------------------------------------------------------------------
# 4. TestSubmit (3 tests)
# ---------------------------------------------------------------------------
class TestSubmit(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.mgr = KYCManager(data_file="kyc.json", base_dir=self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_submit_creates_pending_record(self):
        """submit() creates a record with PENDING status."""
        rec = self.mgr.submit("inv-A", ["doc1.pdf"])
        self.assertEqual(rec.investor_id, "inv-A")
        self.assertEqual(rec.status, KYCStatus.PENDING)
        self.assertEqual(rec.documents, ["doc1.pdf"])

    def test_submit_sets_submitted_at(self):
        """submit() populates submitted_at with a non-null timestamp."""
        rec = self.mgr.submit("inv-B", [])
        self.assertIsNotNone(rec.submitted_at)
        # Must be parseable as datetime
        dt = datetime.fromisoformat(rec.submitted_at)
        self.assertIsNotNone(dt)

    def test_submit_allows_resubmission(self):
        """Re-submitting overwrites the existing record with a fresh PENDING."""
        self.mgr.submit("inv-C", ["old.pdf"])
        self.mgr.approve("inv-C")
        # Now re-submit — should revert to PENDING
        rec = self.mgr.submit("inv-C", ["new.pdf"])
        self.assertEqual(rec.status, KYCStatus.PENDING)
        self.assertEqual(rec.documents, ["new.pdf"])
        self.assertIsNone(rec.approved_at)


# ---------------------------------------------------------------------------
# 5. TestApprove (4 tests)
# ---------------------------------------------------------------------------
class TestApprove(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.mgr = KYCManager(data_file="kyc.json", base_dir=self._tmp.name)
        self.mgr.submit("inv-D", ["id.pdf"])

    def tearDown(self):
        self._tmp.cleanup()

    def test_approve_sets_approved_status(self):
        """approve() changes status to APPROVED."""
        rec = self.mgr.approve("inv-D")
        self.assertEqual(rec.status, KYCStatus.APPROVED)

    def test_approve_sets_approved_at(self):
        """approve() populates approved_at."""
        rec = self.mgr.approve("inv-D")
        self.assertIsNotNone(rec.approved_at)
        datetime.fromisoformat(rec.approved_at)  # must parse

    def test_approve_sets_expires_at_365d(self):
        """approve() sets expires_at to approved_at + 365 days."""
        rec = self.mgr.approve("inv-D")
        approved_dt = datetime.fromisoformat(rec.approved_at)
        expires_dt = datetime.fromisoformat(rec.expires_at)
        delta = expires_dt - approved_dt
        # Allow ±1 second tolerance for clock skew in test execution
        self.assertAlmostEqual(delta.total_seconds(), KYC_EXPIRY_DAYS * 86400, delta=1)

    def test_approve_raises_keyerror_unknown(self):
        """approve() raises KeyError for an unknown investor_id."""
        with self.assertRaises(KeyError):
            self.mgr.approve("nonexistent-investor")


# ---------------------------------------------------------------------------
# 6. TestReject (3 tests)
# ---------------------------------------------------------------------------
class TestReject(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.mgr = KYCManager(data_file="kyc.json", base_dir=self._tmp.name)
        self.mgr.submit("inv-E", ["doc.pdf"])

    def tearDown(self):
        self._tmp.cleanup()

    def test_reject_sets_rejected_status(self):
        """reject() changes status to REJECTED."""
        rec = self.mgr.reject("inv-E", "incomplete documents")
        self.assertEqual(rec.status, KYCStatus.REJECTED)

    def test_reject_stores_rejection_reason(self):
        """reject() persists the rejection_reason."""
        rec = self.mgr.reject("inv-E", "AML flag")
        self.assertEqual(rec.rejection_reason, "AML flag")

    def test_reject_raises_keyerror_unknown(self):
        """reject() raises KeyError for an unknown investor_id."""
        with self.assertRaises(KeyError):
            self.mgr.reject("ghost-investor", "n/a")


# ---------------------------------------------------------------------------
# 7. TestIsCleared (4 tests)
# ---------------------------------------------------------------------------
class TestIsCleared(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.mgr = KYCManager(data_file="kyc.json", base_dir=self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_is_cleared_true_for_approved(self):
        """is_cleared() returns True for an unexpired APPROVED record."""
        self.mgr.submit("inv-ok", ["doc.pdf"])
        self.mgr.approve("inv-ok")
        self.assertTrue(self.mgr.is_cleared("inv-ok"))

    def test_is_cleared_false_for_pending(self):
        """is_cleared() returns False for a PENDING record."""
        self.mgr.submit("inv-pend", ["doc.pdf"])
        self.assertFalse(self.mgr.is_cleared("inv-pend"))

    def test_is_cleared_false_for_rejected(self):
        """is_cleared() returns False for a REJECTED record."""
        self.mgr.submit("inv-rej", ["doc.pdf"])
        self.mgr.reject("inv-rej", "fraud")
        self.assertFalse(self.mgr.is_cleared("inv-rej"))

    def test_is_cleared_false_for_no_record(self):
        """is_cleared() returns False when investor has no record at all."""
        self.assertFalse(self.mgr.is_cleared("nobody"))


# ---------------------------------------------------------------------------
# 8. TestExpiry (2 tests)
# ---------------------------------------------------------------------------
class TestExpiry(unittest.TestCase):
    def _make_mgr_with_expired_record(self) -> tuple:
        """Helper: returns (tmp_dir_ctx, mgr) with an already-expired record."""
        tmp = tempfile.TemporaryDirectory()
        mgr = KYCManager(data_file="kyc.json", base_dir=tmp.name)
        mgr.submit("inv-exp", ["doc.pdf"])
        mgr.approve("inv-exp")
        # Manually backdate expires_at to the past
        rec = mgr.get_record("inv-exp")
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        rec.expires_at = past
        mgr._save()
        return tmp, mgr

    def test_refresh_expiry_auto_expires(self):
        """_refresh_expiry changes status to EXPIRED when expires_at is past."""
        tmp, mgr = self._make_mgr_with_expired_record()
        try:
            mgr._refresh_expiry("inv-exp")
            rec = mgr.get_record("inv-exp")
            self.assertEqual(rec.status, KYCStatus.EXPIRED)
        finally:
            tmp.cleanup()

    def test_is_cleared_false_after_expiry(self):
        """is_cleared() returns False once an APPROVED record has expired."""
        tmp, mgr = self._make_mgr_with_expired_record()
        try:
            self.assertFalse(mgr.is_cleared("inv-exp"))
        finally:
            tmp.cleanup()


# ---------------------------------------------------------------------------
# 9. TestPersistence (2 tests)
# ---------------------------------------------------------------------------
class TestPersistence(unittest.TestCase):
    def test_saves_to_file(self):
        """After submit+approve, the JSON file on disk contains the record."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "kyc.json")
            mgr = KYCManager(data_file=path)
            mgr.submit("inv-persist", ["proof.pdf"])
            mgr.approve("inv-persist")
            self.assertTrue(os.path.exists(path))
            with open(path, "r") as fh:
                data = json.load(fh)
            records = data.get("records", [])
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["investor_id"], "inv-persist")
            self.assertEqual(records[0]["status"], "APPROVED")

    def test_loads_from_file_across_instances(self):
        """A second KYCManager instance reads records saved by the first."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "kyc.json")
            mgr1 = KYCManager(data_file=path)
            mgr1.submit("inv-load", ["id.pdf"])
            mgr1.approve("inv-load")

            mgr2 = KYCManager(data_file=path)
            rec = mgr2.get_record("inv-load")
            self.assertIsNotNone(rec)
            self.assertEqual(rec.status, KYCStatus.APPROVED)
            self.assertIsNotNone(rec.expires_at)


if __name__ == "__main__":
    unittest.main()
