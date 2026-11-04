"""STUDIO-TRUTH-AND-OWNER-CONTROL-01 — чистые помощники ``company_truth`` (открытый вопрос, признак теста,
свежесть книги). Имя файла — по префиксу, который разрешает храповик ``test_company_truth_import_ratchet``.
"""
# FROZEN-DATE-OK: injected-clock — every judged moment is passed as `now=`; fixtures are relative to it
import unittest
from datetime import datetime, timedelta, timezone

from spa_core.studio_os import company_truth as ct
from spa_core.studio_os import owner_view as ov

NOW = datetime(2026, 11, 4, 10, 0, tzinfo=timezone.utc)


class OpenQuestions(unittest.TestCase):
    """F1/T04/F7/T05: снятый/заменённый/тестовый вопрос не открыт и не считается."""

    def test_closed_reasons(self):
        self.assertIsNotNone(ct.question_closed_reason("a", {}, {"a"}))                 # supersedes
        self.assertIn("Mac", ct.question_closed_reason("a", {"state": "ANSWERED"}, set()))
        self.assertIsNone(ct.question_closed_reason("a", {"state": "NEEDS_OWNER"}, set()))
        self.assertIsNone(ct.question_closed_reason("a", {}, set()))                     # возраст не причина

    def test_superseded_ids_read_from_the_replacing_card(self):
        cards = {"new.md": {"fm": {"supersedes": "old-card.md"}}, "old-card.md": {"fm": {}}}
        self.assertEqual(ct.superseded_ids(cards), {"old-card"})

    def test_fixture_markers_are_fields_not_title_guesses(self):
        self.assertIsNotNone(ct.test_or_fixture_reason({"submission_id": "demo-e2e-20261016153932"}))
        self.assertIsNotNone(ct.test_or_fixture_reason({"claimed_by": "arb-demo-1"}))
        self.assertIsNotNone(ct.test_or_fixture_reason({"fixture": "true"}))
        self.assertIsNone(ct.test_or_fixture_reason({"title": "купить зонт в пятницу"}))

    def test_triage_excludes_closed_and_counts_undeclared(self):
        cards = {"owner-decision-a.md": {"fm": {"type": "owner-decision", "status": "needs-owner", "title": "A"}},
                 "owner-decision-b.md": {"fm": {"type": "owner-decision", "status": "needs-owner", "title": "B",
                                                "supersedes": "owner-decision-a"}}}
        tri = ct.decisions_triage(cards, {}, NOW, {"pending": [{"id": "owner-decision-b", "state": "NEEDS_OWNER"}]})
        self.assertEqual(tri["counts"]["closed_elsewhere"], 1)
        self.assertEqual([r["id"] for r in tri["groups"]["closed_elsewhere"]], ["owner-decision-a"])
        q = ov.owner_questions({"decisions": tri}, None)
        self.assertEqual(q["count"], 0)                 # ADR-285: без темы — не вопрос владельцу
        self.assertEqual(q["subject_undeclared"], 1)     # но число видно рядом
        self.assertIn("без названной темы", q["summary"]["text"])


class BookFreshness(unittest.TestCase):
    def test_book_as_of_is_the_last_cycle_not_the_window_start(self):
        doc = {"last_cycle_at": (NOW - timedelta(hours=1)).isoformat()}
        old = {"last_cycle_at": (NOW - timedelta(hours=40)).isoformat()}
        self.assertLess(ct._age_min_iso(doc["last_cycle_at"], NOW), ct.BOOK_STALE_AFTER_MIN)
        self.assertGreater(ct._age_min_iso(old["last_cycle_at"], NOW), ct.BOOK_STALE_AFTER_MIN)
        self.assertEqual(ct._age_min_iso((NOW + timedelta(hours=1)).isoformat(), NOW), 0.0)
        self.assertIsNone(ct._age_min_iso(None, NOW))


if __name__ == "__main__":
    unittest.main()
