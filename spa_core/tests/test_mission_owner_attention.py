"""The home attention line «Вопрос ждёт вас N дн.» names only questions that wait for the OWNER.

Defect reproduced on the live Director OS bundle (P1 recovery audit): the three attention lines were two
owner-ACCEPTED loop findings (36 d — the owner had already said yes, agents execute them) and one
card without a declared ADR-285 subject, while the three real questions (two MONEY, one
IRREVERSIBLE) never reached the home screen. ``owner_attention_items`` now selects
NEEDS_OWNER + declared subject, ordered subject → oldest first.

Dates are relative to the real clock (no literal dates — frozen-date ratchet).
"""
import unittest
from datetime import datetime, timedelta, timezone

from spa_core.studio_os.mission_control import owner_attention_items


def _scene(now):
    def ago(n):
        return (now - timedelta(days=n)).isoformat()

    pending = [
        {"id": "own-accepted-old", "title": "accepted loop finding", "state": "ACCEPTED", "created_at": ago(36)},
        {"id": "own-undeclared-old", "title": "no subject", "state": "NEEDS_OWNER", "created_at": ago(29)},
        {"id": "own-answered", "title": "answered in telegram", "state": "ANSWERED", "created_at": ago(25)},
        {"id": "own-money-19", "title": "cash 5%", "state": "NEEDS_OWNER", "created_at": ago(19)},
        {"id": "own-money-17", "title": "base cap", "state": "NEEDS_OWNER", "created_at": ago(17)},
        {"id": "own-irreversible-20", "title": "disk", "state": "NEEDS_OWNER", "created_at": ago(20)},
        {"id": "own-public-12", "title": "site number", "state": "NEEDS_OWNER", "created_at": ago(12)},
        {"id": "own-money-young", "title": "fresh money", "state": "NEEDS_OWNER", "created_at": ago(2)},
    ]
    subjects = {"own-accepted-old": "money", "own-undeclared-old": None, "own-answered": "money",
                "own-money-19": "money", "own-money-17": "money", "own-irreversible-20": "irreversible",
                "own-public-12": "public_numbers_naming_legal", "own-money-young": "money"}
    cards = {f"{k}.md": {"fm": ({"subject": v} if v else {})} for k, v in subjects.items()}
    return {"pending": pending}, cards


class OwnerAttentionItems(unittest.TestCase):
    def setUp(self):
        self.now = datetime.now(timezone.utc)
        self.decisions, self.cards = _scene(self.now)

    def titles(self):
        return [i["title"] for i in owner_attention_items(self.decisions, self.cards, self.now)]

    def test_only_declared_waiting_questions_subject_then_age(self):
        self.assertEqual(self.titles(), ["cash 5%", "base cap", "site number", "disk"])

    def test_accepted_card_is_not_a_question_waiting_for_the_owner(self):
        self.assertNotIn("accepted loop finding", self.titles())
        # control: the same card, still NEEDS_OWNER, would be named first (oldest money)
        self.decisions["pending"][0]["state"] = "NEEDS_OWNER"
        self.assertEqual(self.titles()[0], "accepted loop finding")

    def test_undeclared_and_answered_are_excluded(self):
        t = self.titles()
        self.assertNotIn("no subject", t)
        self.assertNotIn("answered in telegram", t)
        # control: declaring the subject brings the card in
        self.cards["own-undeclared-old.md"]["fm"] = {"subject": "irreversible"}
        self.assertIn("no subject", self.titles())

    def test_younger_than_threshold_excluded(self):
        self.assertNotIn("fresh money", self.titles())
        self.assertIn("fresh money", [i["title"] for i in
                                      owner_attention_items(self.decisions, self.cards, self.now, min_days=0)])

    def test_days_are_reported(self):
        items = owner_attention_items(self.decisions, self.cards, self.now)
        self.assertEqual([i["days"] for i in items], [19, 17, 12, 20])

    def test_not_measured_queue_yields_no_lines(self):
        self.assertEqual(owner_attention_items({"_meta": {"state": "NOT_MEASURED"}}, self.cards, self.now), [])
        self.assertEqual(owner_attention_items(self.decisions, None, self.now), [])


if __name__ == "__main__":
    unittest.main()
