"""`cartographer.owner_decisions.from_tracker` — тема по ОБЩЕЙ функции (C5, ADR-580).

До правки `from_tracker` угадывал тему словами заголовка (`SUBJECT_HINTS`), и это
расходилось с Mission Control на тех же карточках (A5_owner_control.md: «Закрыть три
PR» получала разные темы на двух экранах, потому что у каждой поверхности был СВОЙ
словарь примет). Теперь обе поверхности читают ОДНУ функцию
(`spa_core.owner_queue.subject`), которая смотрит только на объявленное поле
`subject:` frontmatter.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "cartographer"))

import owner_decisions as od  # noqa: E402

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)


def _write(tracker: Path, name: str, extra_fm: str, body: str = "") -> None:
    tracker.mkdir(parents=True, exist_ok=True)
    text = (f"---\ntitle: {name}\nstatus: needs-owner\ncreated: 2026-10-01\n{extra_fm}---\n\n{body}\n")
    (tracker / f"own-{name}.md").write_text(text, encoding="utf-8")


class TestSharedSubjectReplacesKeywordGuessing(unittest.TestCase):

    def test_a_card_mentioning_a_money_word_without_declaring_subject_is_UNDECLARED(self):
        """Регрессия A5_owner_control.md: «Закрыть три PR» содержит слово «ключ», и
        прежнее угадывание называло это «1 · real money». Без объявленного `subject:`
        тема теперь UNDECLARED, а не угаданный предмет.

        # CHANGED (integration review F2, 2026-10-05 — journal 2026-W40): assertion was
        # `item["subject"] == "NONE"`. That value made `classify_item` treat EVERY real
        # `needs-owner` card (none declares `subject:` today) as `CLASS_SYSTEM` — "work
        # for the agent", hidden from "ждёт вашего решения" (measured on the prod
        # tracker: OWNER_DECISION_REQUIRED 2 -> 0). `subject.py` now returns the
        # distinct code `UNDECLARED` for this exact case (not-declared is not the same
        # as "no subject matched"), and `classify_item` routes it to `CLASS_UNKNOWN`
        # (visible to the owner, not re-routed to agents). This tightens the test to
        # the fixed, intended behaviour; it does not relax any check.
        """
        with tempfile.TemporaryDirectory() as d:
            tracker = Path(d) / "nimbalyst-local" / "tracker"
            _write(tracker, "zakryt-tri-PR", "", body="PAT не хватает прав (ключ)")
            result = od.from_tracker(tracker, now=NOW)
        item = result["items"][0]
        self.assertEqual(item["subject"], "UNDECLARED")
        self.assertEqual(item["subject_basis"], "NOT_DECLARED")
        self.assertEqual(od.classify_item(item)[0], od.CLASS_UNKNOWN)

    def test_a_card_with_declared_subject_is_read_verbatim(self):
        with tempfile.TemporaryDirectory() as d:
            tracker = Path(d) / "nimbalyst-local" / "tracker"
            _write(tracker, "real-money-card", "subject: money\n", body="выдать ключ подписанту")
            result = od.from_tracker(tracker, now=NOW)
        item = result["items"][0]
        self.assertEqual(item["subject"], "1")
        self.assertEqual(item["subject_basis"], "DECLARED")


class TestImportFailureFailsVisibleNotHeuristic(unittest.TestCase):
    """F15 (integration review, 2026-10-05): before this fix, `ImportError` on
    `spa_core.owner_queue.subject` silently fell back to the OLD keyword heuristic
    (`_subject_of`) — Director's subject depended on `sys.path`, two behaviours
    under one name, with nothing in the result saying which one ran."""

    def test_import_failure_refuses_not_measured_instead_of_guessing(self):
        with tempfile.TemporaryDirectory() as d:
            tracker = Path(d) / "nimbalyst-local" / "tracker"
            # Money-word card WITHOUT a declared subject — if the old heuristic ran,
            # it would call this "1 · real money" (the exact A5_owner_control.md
            # regression). The fix must refuse instead of guessing.
            _write(tracker, "zakryt-tri-PR", "", body="PAT не хватает прав (ключ)")
            import importlib
            import spa_core.owner_queue as _pkg
            real_subject_mod = importlib.import_module("spa_core.owner_queue.subject")
            try:
                # `pkg.subject` is cached as an ATTRIBUTE on the already-imported
                # parent package — `from pkg import name` resolves via that
                # attribute and ignores a `None` left in sys.modules alone. Both
                # must go to reproduce "the import genuinely does not work"
                # without touching the real package on disk.
                delattr(_pkg, "subject")
                sys.modules["spa_core.owner_queue.subject"] = None
                result = od.from_tracker(tracker, now=NOW)
            finally:
                sys.modules["spa_core.owner_queue.subject"] = real_subject_mod
                _pkg.subject = real_subject_mod
        self.assertEqual(result["state"], "NOT_MEASURED")
        self.assertIn("F15", result["reason"])
        self.assertNotIn("items", result)


if __name__ == "__main__":
    unittest.main()
