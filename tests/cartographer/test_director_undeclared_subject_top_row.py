"""N3 (ADR-580 §C8 REVIEW_2, 2026-10-05) — верхняя строка показывает count
карточек владельца с необъявленной темой, а не только свёрнутый список.

До этой правки `render_studio` уже СЧИТАЛ `unclear` (карточки класса
`CLASS_UNKNOWN` — тема не объявлена во frontmatter), но показывал число ТОЛЬКО
внутри `<details>` «предмет не определён» — узнать его можно было лишь после
клика. На живом трекере (замер ревьюера 2026-10-05) все 12 ждущих карточек
сегодня именно такие: верхняя строка без этого числа читалась бы как «ничего
не ждёт», хотя ждут все двенадцать.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "cartographer"))

import director_shell as DS   # noqa: E402
import owner_decisions as od  # noqa: E402

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)


def _write(tracker: Path, name: str, extra_fm: str = "") -> None:
    tracker.mkdir(parents=True, exist_ok=True)
    text = (f"---\ntitle: {name}\nstatus: needs-owner\ncreated: 2026-09-01\n"
            f"{extra_fm}---\n\nВопрос владельцу.\n")
    (tracker / f"own-{name}.md").write_text(text, encoding="utf-8")


def _top_row(html: str) -> str:
    """Всё до первого свёрнутого `<details>` — то, что владелец видит без клика."""
    return html.split('<details', 1)[0]


class TestTopRowCarriesTheUndeclaredCount(unittest.TestCase):

    def _decisions(self, *, n_undeclared: int, n_declared_money: int = 0):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            tracker = root / "nimbalyst-local" / "tracker"
            for i in range(n_undeclared):
                _write(tracker, f"undeclared-{i}")
            for i in range(n_declared_money):
                _write(tracker, f"money-{i}", "subject: '1'\n")
            return od.build_owner_decisions(production_root=root, now=NOW)

    def test_fixture_with_three_undeclared_cards_shows_3_in_the_top_row(self):
        decisions = self._decisions(n_undeclared=3)
        self.assertEqual(decisions['by_class'][od.CLASS_UNKNOWN], 3)
        html = DS.render_studio(health={}, decisions=decisions, bridge={})
        top = _top_row(html)
        self.assertIn('тема не объявлена', top,
                      "верхняя строка не несёт подпись про необъявленную тему")
        self.assertIn('>3<', top,
                      "число 3 (необъявленная тема) не найдено в ВЕРХНЕЙ строке")

    def test_a_declared_money_card_does_not_count_as_undeclared(self):
        """Карточка с объявленным `subject:` не должна раздувать счётчик
        «тема не объявлена» — иначе число ничего не называет."""
        decisions = self._decisions(n_undeclared=2, n_declared_money=1)
        self.assertEqual(decisions['by_class'][od.CLASS_UNKNOWN], 2)
        html = DS.render_studio(health={}, decisions=decisions, bridge={})
        top = _top_row(html)
        self.assertIn('>2<', top)

    def test_zero_undeclared_is_a_measured_zero_not_a_missing_caption(self):
        """Инв. #17: ноль карточек без темы — ЧИСЛО 0 в строке, не отсутствие
        подписи (отсутствие подписи неотличимо от «не измерено»)."""
        decisions = self._decisions(n_undeclared=0, n_declared_money=1)
        self.assertEqual(decisions['by_class'][od.CLASS_UNKNOWN], 0)
        html = DS.render_studio(health={}, decisions=decisions, bridge={})
        top = _top_row(html)
        self.assertIn('тема не объявлена', top)
        self.assertIn('>0<', top)


if __name__ == "__main__":
    unittest.main()
