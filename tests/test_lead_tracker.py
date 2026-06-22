"""
tests/test_lead_tracker.py

35 unit tests for spa_core.family_fund.lead_tracker.LeadTracker.

Coverage:
  - Lead dataclass construction and validation
  - add_lead() creates NEW leads
  - add_lead() deduplicates by email (no duplicates)
  - update_status() transitions through pipeline
  - list_by_status() filters correctly
  - total_pipeline_usd() sums NEW + QUALIFIED only
  - summary() returns counts for all statuses + pipeline_usd
  - save() / load() round-trip (atomic file write)
  - send_telegram_notification() mocked → returns bool
  - lead_id is unique per distinct email
  - edge cases: empty tracker, invalid status, missing lead_id, etc.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest.mock import patch

from spa_core.family_fund.lead_tracker import (
    Lead,
    LeadTracker,
    LEAD_STATUSES,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tracker(tmp_dir: str, **kwargs) -> LeadTracker:
    """Create a LeadTracker backed by a temp file."""
    path = os.path.join(tmp_dir, "leads.json")
    return LeadTracker(leads_path=path, telegram_token="tok", telegram_chat_id="123", **kwargs)


def _add_alice(tracker: LeadTracker) -> Lead:
    return tracker.add_lead(
        name="Alice Ivanova",
        email="alice@example.com",
        amount_usd=25_000,
        message="Interested in Core strategy",
    )


def _add_bob(tracker: LeadTracker) -> Lead:
    return tracker.add_lead(
        name="Bob Smith",
        email="bob@example.com",
        amount_usd=15_000,
        message="",
    )


# ---------------------------------------------------------------------------
# Test: Lead dataclass
# ---------------------------------------------------------------------------

class TestLeadDataclass(unittest.TestCase):

    def test_lead_defaults_status_new(self):
        """Lead default status is NEW."""
        lead = Lead(
            lead_id="abc",
            name="Alice",
            email="a@b.com",
            telegram_handle=None,
            interested_amount_usd=10_000,
            message="hello",
        )
        self.assertEqual(lead.status, "NEW")

    def test_lead_created_at_auto_populated(self):
        """created_at is set automatically if not provided."""
        lead = Lead(
            lead_id="abc",
            name="Alice",
            email="a@b.com",
            telegram_handle=None,
            interested_amount_usd=10_000,
            message="",
        )
        self.assertTrue(len(lead.created_at) > 0)

    def test_lead_invalid_status_raises(self):
        """Lead raises ValueError for invalid status."""
        with self.assertRaises(ValueError):
            Lead(
                lead_id="abc",
                name="Alice",
                email="a@b.com",
                telegram_handle=None,
                interested_amount_usd=10_000,
                message="",
                status="BOGUS",
            )

    def test_lead_all_statuses_valid(self):
        """All LEAD_STATUSES can be set on a Lead."""
        for status in LEAD_STATUSES:
            lead = Lead(
                lead_id="x",
                name="Test",
                email="t@t.com",
                telegram_handle=None,
                interested_amount_usd=0,
                message="",
                status=status,
            )
            self.assertEqual(lead.status, status)


# ---------------------------------------------------------------------------
# Test: add_lead
# ---------------------------------------------------------------------------

class TestAddLead(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.tracker = _make_tracker(self.tmp)
        self.tracker.load()

    def test_add_lead_returns_lead(self):
        """add_lead() returns a Lead instance."""
        lead = _add_alice(self.tracker)
        self.assertIsInstance(lead, Lead)

    def test_add_lead_status_is_new(self):
        """add_lead() creates lead with status NEW."""
        lead = _add_alice(self.tracker)
        self.assertEqual(lead.status, "NEW")

    def test_add_lead_name_stored(self):
        """add_lead() stores name correctly."""
        lead = _add_alice(self.tracker)
        self.assertEqual(lead.name, "Alice Ivanova")

    def test_add_lead_email_lowercase(self):
        """add_lead() normalises email to lowercase."""
        lead = self.tracker.add_lead("Test", "TEST@EXAMPLE.COM", 10_000)
        self.assertEqual(lead.email, "test@example.com")

    def test_add_lead_amount_stored(self):
        """add_lead() stores interested_amount_usd."""
        lead = _add_alice(self.tracker)
        self.assertAlmostEqual(lead.interested_amount_usd, 25_000.0)

    def test_add_lead_assigns_unique_id(self):
        """add_lead() assigns a non-empty lead_id."""
        lead = _add_alice(self.tracker)
        self.assertTrue(len(lead.lead_id) > 0)

    def test_add_lead_two_different_emails_unique_ids(self):
        """Two different emails produce two leads with different IDs."""
        a = _add_alice(self.tracker)
        b = _add_bob(self.tracker)
        self.assertNotEqual(a.lead_id, b.lead_id)

    def test_add_lead_duplicate_email_no_duplicate(self):
        """add_lead() with same email returns existing lead, no duplicate."""
        a1 = _add_alice(self.tracker)
        a2 = _add_alice(self.tracker)
        self.assertEqual(a1.lead_id, a2.lead_id)
        self.assertEqual(len(self.tracker.all_leads()), 1)

    def test_add_lead_duplicate_email_case_insensitive(self):
        """Duplicate check is case-insensitive for email."""
        a1 = self.tracker.add_lead("Alice", "Alice@Example.COM", 25_000)
        a2 = self.tracker.add_lead("Alice", "alice@example.com", 25_000)
        self.assertEqual(a1.lead_id, a2.lead_id)

    def test_add_lead_telegram_handle_optional(self):
        """add_lead() works without telegram_handle."""
        lead = self.tracker.add_lead("Test", "t@t.com", 10_000)
        self.assertIsNone(lead.telegram_handle)

    def test_add_lead_with_telegram_handle(self):
        """add_lead() stores telegram_handle when provided."""
        lead = self.tracker.add_lead("Test", "t@t.com", 10_000, telegram_handle="@testuser")
        self.assertEqual(lead.telegram_handle, "@testuser")

    def test_add_lead_sends_telegram_notification(self):
        """add_lead() calls send_telegram_notification once."""
        with patch.object(self.tracker, "send_telegram_notification", return_value=True) as mock_tg:
            _add_alice(self.tracker)
        mock_tg.assert_called_once()

    def test_add_lead_duplicate_does_not_send_notification(self):
        """Duplicate email add_lead does not call send_telegram_notification again."""
        _add_alice(self.tracker)
        with patch.object(self.tracker, "send_telegram_notification", return_value=True) as mock_tg:
            _add_alice(self.tracker)
        mock_tg.assert_not_called()


# ---------------------------------------------------------------------------
# Test: update_status
# ---------------------------------------------------------------------------

class TestUpdateStatus(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.tracker = _make_tracker(self.tmp)
        self.tracker.load()

    def test_update_status_new_to_contacted(self):
        """update_status() can move lead NEW → CONTACTED."""
        lead = _add_alice(self.tracker)
        updated = self.tracker.update_status(lead.lead_id, "CONTACTED")
        self.assertEqual(updated.status, "CONTACTED")

    def test_update_status_to_qualified(self):
        """update_status() can move lead → QUALIFIED."""
        lead = _add_alice(self.tracker)
        self.tracker.update_status(lead.lead_id, "CONTACTED")
        updated = self.tracker.update_status(lead.lead_id, "QUALIFIED")
        self.assertEqual(updated.status, "QUALIFIED")

    def test_update_status_to_investor(self):
        """update_status() can move lead → INVESTOR."""
        lead = _add_alice(self.tracker)
        updated = self.tracker.update_status(lead.lead_id, "INVESTOR")
        self.assertEqual(updated.status, "INVESTOR")

    def test_update_status_to_rejected(self):
        """update_status() can move lead → REJECTED."""
        lead = _add_alice(self.tracker)
        updated = self.tracker.update_status(lead.lead_id, "REJECTED")
        self.assertEqual(updated.status, "REJECTED")

    def test_update_status_stores_notes(self):
        """update_status() appends notes to lead."""
        lead = _add_alice(self.tracker)
        updated = self.tracker.update_status(lead.lead_id, "CONTACTED", notes="Called on June 20")
        self.assertIn("Called on June 20", updated.notes)

    def test_update_status_appends_to_existing_notes(self):
        """Subsequent update_status() appends new notes."""
        lead = _add_alice(self.tracker)
        self.tracker.update_status(lead.lead_id, "CONTACTED", notes="First call")
        updated = self.tracker.update_status(lead.lead_id, "QUALIFIED", notes="Sent KYC")
        self.assertIn("First call", updated.notes)
        self.assertIn("Sent KYC", updated.notes)

    def test_update_status_invalid_raises(self):
        """update_status() raises ValueError for invalid status."""
        lead = _add_alice(self.tracker)
        with self.assertRaises(ValueError):
            self.tracker.update_status(lead.lead_id, "FLYING")

    def test_update_status_unknown_id_raises(self):
        """update_status() raises KeyError for unknown lead_id."""
        with self.assertRaises(KeyError):
            self.tracker.update_status("nonexistent-id", "CONTACTED")


# ---------------------------------------------------------------------------
# Test: list_by_status
# ---------------------------------------------------------------------------

class TestListByStatus(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.tracker = _make_tracker(self.tmp)
        self.tracker.load()

    def test_list_by_status_filters_new(self):
        """list_by_status('NEW') returns only NEW leads."""
        _add_alice(self.tracker)
        b = _add_bob(self.tracker)
        self.tracker.update_status(b.lead_id, "CONTACTED")
        result = self.tracker.list_by_status("NEW")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].email, "alice@example.com")

    def test_list_by_status_empty_if_none(self):
        """list_by_status returns empty list when no leads match."""
        _add_alice(self.tracker)
        result = self.tracker.list_by_status("INVESTOR")
        self.assertEqual(result, [])

    def test_list_by_status_invalid_raises(self):
        """list_by_status() raises ValueError for invalid status."""
        with self.assertRaises(ValueError):
            self.tracker.list_by_status("BOGUS")

    def test_list_by_status_returns_all_matching(self):
        """list_by_status returns all leads with that status."""
        _add_alice(self.tracker)
        _add_bob(self.tracker)
        result = self.tracker.list_by_status("NEW")
        self.assertEqual(len(result), 2)


# ---------------------------------------------------------------------------
# Test: total_pipeline_usd
# ---------------------------------------------------------------------------

class TestTotalPipelineUsd(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.tracker = _make_tracker(self.tmp)
        self.tracker.load()

    def test_total_pipeline_empty(self):
        """total_pipeline_usd() returns 0.0 for empty tracker."""
        self.assertAlmostEqual(self.tracker.total_pipeline_usd(), 0.0)

    def test_total_pipeline_includes_new(self):
        """total_pipeline_usd() includes NEW leads."""
        _add_alice(self.tracker)  # 25_000, NEW
        self.assertAlmostEqual(self.tracker.total_pipeline_usd(), 25_000.0)

    def test_total_pipeline_includes_qualified(self):
        """total_pipeline_usd() includes QUALIFIED leads."""
        lead = _add_alice(self.tracker)  # 25_000
        self.tracker.update_status(lead.lead_id, "QUALIFIED")
        self.assertAlmostEqual(self.tracker.total_pipeline_usd(), 25_000.0)

    def test_total_pipeline_excludes_investor(self):
        """total_pipeline_usd() excludes INVESTOR leads."""
        lead = _add_alice(self.tracker)  # 25_000
        self.tracker.update_status(lead.lead_id, "INVESTOR")
        self.assertAlmostEqual(self.tracker.total_pipeline_usd(), 0.0)

    def test_total_pipeline_excludes_rejected(self):
        """total_pipeline_usd() excludes REJECTED leads."""
        lead = _add_alice(self.tracker)
        self.tracker.update_status(lead.lead_id, "REJECTED")
        self.assertAlmostEqual(self.tracker.total_pipeline_usd(), 0.0)

    def test_total_pipeline_sums_new_and_qualified(self):
        """total_pipeline_usd() sums NEW + QUALIFIED correctly."""
        a = _add_alice(self.tracker)   # 25_000 NEW
        b = _add_bob(self.tracker)     # 15_000 NEW
        self.tracker.update_status(b.lead_id, "QUALIFIED")
        # both should count: 25_000 + 15_000
        self.assertAlmostEqual(self.tracker.total_pipeline_usd(), 40_000.0)


# ---------------------------------------------------------------------------
# Test: summary
# ---------------------------------------------------------------------------

class TestSummary(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.tracker = _make_tracker(self.tmp)
        self.tracker.load()

    def test_summary_has_counts_key(self):
        """summary() contains 'counts' key."""
        s = self.tracker.summary()
        self.assertIn("counts", s)

    def test_summary_counts_all_statuses(self):
        """summary()['counts'] has a key for every LEAD_STATUS."""
        s = self.tracker.summary()
        for status in LEAD_STATUSES:
            self.assertIn(status, s["counts"])

    def test_summary_has_pipeline_usd(self):
        """summary() contains 'pipeline_usd' key."""
        s = self.tracker.summary()
        self.assertIn("pipeline_usd", s)

    def test_summary_has_total_leads(self):
        """summary() contains 'total_leads' key."""
        s = self.tracker.summary()
        self.assertIn("total_leads", s)

    def test_summary_correct_counts(self):
        """summary()['counts'] reflects actual lead statuses."""
        _add_alice(self.tracker)   # NEW
        b = _add_bob(self.tracker)  # NEW → CONTACTED
        self.tracker.update_status(b.lead_id, "CONTACTED")
        s = self.tracker.summary()
        self.assertEqual(s["counts"]["NEW"], 1)
        self.assertEqual(s["counts"]["CONTACTED"], 1)
        self.assertEqual(s["counts"]["QUALIFIED"], 0)

    def test_summary_pipeline_usd_correct(self):
        """summary()['pipeline_usd'] matches total_pipeline_usd()."""
        _add_alice(self.tracker)
        s = self.tracker.summary()
        self.assertAlmostEqual(s["pipeline_usd"], self.tracker.total_pipeline_usd())


# ---------------------------------------------------------------------------
# Test: save / load (atomic persistence)
# ---------------------------------------------------------------------------

class TestSaveLoad(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_save_creates_file(self):
        """save() creates the leads JSON file."""
        tracker = _make_tracker(self.tmp)
        tracker.load()
        _add_alice(tracker)
        # File was created by add_lead (which calls save internally)
        self.assertTrue(os.path.exists(tracker.leads_path))

    def test_save_file_is_valid_json(self):
        """File saved by save() is valid JSON."""
        tracker = _make_tracker(self.tmp)
        tracker.load()
        _add_alice(tracker)
        with open(tracker.leads_path, "r") as fh:
            data = json.load(fh)
        self.assertIn("leads", data)

    def test_load_restores_leads(self):
        """load() restores leads saved to disk."""
        tracker1 = _make_tracker(self.tmp)
        tracker1.load()
        lead = _add_alice(tracker1)

        tracker2 = LeadTracker(leads_path=tracker1.leads_path, telegram_token="tok", telegram_chat_id="123")
        tracker2.load()
        restored = tracker2.get_lead(lead.lead_id)
        self.assertEqual(restored.email, "alice@example.com")

    def test_load_empty_when_no_file(self):
        """load() is safe when file does not exist."""
        tracker = _make_tracker(self.tmp)
        tracker.load()
        self.assertEqual(len(tracker.all_leads()), 0)


# ---------------------------------------------------------------------------
# Test: send_telegram_notification (mocked)
# ---------------------------------------------------------------------------

class TestSendTelegramNotification(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.tracker = _make_tracker(self.tmp)
        self.tracker.load()

    def test_send_telegram_returns_true_on_success(self):
        """send_telegram_notification() returns True when HTTP call succeeds."""
        lead = Lead(
            lead_id="test-id",
            name="Test",
            email="t@t.com",
            telegram_handle=None,
            interested_amount_usd=10_000,
            message="Hi",
        )
        with patch.object(self.tracker, "_post_telegram", return_value=None):
            result = self.tracker.send_telegram_notification(lead)
        self.assertTrue(result)

    def test_send_telegram_returns_false_on_error(self):
        """send_telegram_notification() returns False when HTTP call fails."""
        lead = Lead(
            lead_id="test-id",
            name="Test",
            email="t@t.com",
            telegram_handle=None,
            interested_amount_usd=10_000,
            message="Hi",
        )
        with patch.object(self.tracker, "_post_telegram", side_effect=Exception("network error")):
            result = self.tracker.send_telegram_notification(lead)
        self.assertFalse(result)

    def test_send_telegram_never_raises(self):
        """send_telegram_notification() never raises — always returns bool."""
        lead = Lead(
            lead_id="test-id",
            name="Test",
            email="t@t.com",
            telegram_handle=None,
            interested_amount_usd=10_000,
            message="Hi",
        )
        with patch.object(self.tracker, "_resolve_telegram_credentials", side_effect=RuntimeError("no keychain")):
            result = self.tracker.send_telegram_notification(lead)
        self.assertIsInstance(result, bool)


if __name__ == "__main__":
    unittest.main(verbosity=2)
