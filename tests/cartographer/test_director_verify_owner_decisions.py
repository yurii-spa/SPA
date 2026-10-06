"""`director_verify.verify_owner_decisions` — многостатусная ловушка (C5, ADR-580).

До правки ``verify_owner_decisions`` считал `status: needs-owner` по НАИВНОМУ
`re.search` над первыми 2000 символами ЦЕЛОГО файла — не отличая frontmatter от тела.
Карточка, чьё тело ЦИТИРУЕТ или ПРИВОДИТ ПРИМЕРОМ `status: needs-owner` (а настоящий
статус во frontmatter уже другой — `ingested`/`owner-done`), засчитывалась как ждущая,
хотя ответ владелец уже дал. Это один из источников расхождения «11/12/6/4» между
поверхностями очереди владельца (A5_owner_control.md).

Каждый тест — положительный контроль: воспроизводит форму, на которой наивный разбор
ошибался, и называет верное звено.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "cartographer"))

import director_verify as dv  # noqa: E402


def _write(tracker: Path, name: str, text: str) -> None:
    tracker.mkdir(parents=True, exist_ok=True)
    (tracker / f"{name}.md").write_text(text, encoding="utf-8")


class TestOwnerDecisionsFrontmatterOnly(unittest.TestCase):

    def test_a_status_line_in_the_body_is_not_counted(self, tmp_path=None):
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            tracker = root / "nimbalyst-local" / "tracker"
            # Настоящий статус — ingested (владелец уже ответил); тело ЦИТИРУЕТ пример
            # с другим статусом, как у живой карточки `inbox-ochered-*` (три строки `status:`).
            _write(tracker, "owner-decision-already-answered",
                   "---\nstatus: ingested\n---\n\n"
                   "## Что от тебя нужно\n\n"
                   "Пример формата карточки:\n```\nstatus: needs-owner\n```\n")
            result = dv.verify_owner_decisions(str(root))
        self.assertEqual(result["owner_decisions_waiting"], 0,
                         "карточка отвечена (ingested) — наивный разбор "
                         "засчитал бы её как needs-owner из-за цитаты в теле")

    def test_a_real_needs_owner_card_is_still_counted(self):
        """Обратный контроль: настоящий ждущий вопрос не теряется границей по frontmatter."""
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            tracker = root / "nimbalyst-local" / "tracker"
            _write(tracker, "owner-decision-live-question",
                   "---\nstatus: needs-owner\n---\n\nВопрос владельцу.\n")
            result = dv.verify_owner_decisions(str(root))
        self.assertEqual(result["owner_decisions_waiting"], 1)

    def test_text_before_frontmatter_opens_is_not_a_status(self):
        """Файл без frontmatter (прочая заметка в каталоге) — упоминание `status:` в прозе
        не выдаёт себя за замер."""
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            tracker = root / "nimbalyst-local" / "tracker"
            _write(tracker, "own-note", "просто заметка, status: needs-owner где-то в тексте\n")
            result = dv.verify_owner_decisions(str(root))
        self.assertEqual(result["owner_decisions_waiting"], 0)


if __name__ == "__main__":
    unittest.main()
