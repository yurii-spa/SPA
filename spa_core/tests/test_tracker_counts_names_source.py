"""Подсчёт карточек обязан называть свой источник (ADR-152).

Авария 27.08. Владелец попросил замерить, движется ли бэклог. Замер сняли с ЛОКАЛЬНОГО
дерева: 525 карточек, 237 `done`. На origin в тот же момент — 719 и 379. Разница в 142
карточки не работа за день, а разрыв копий: `nimbalyst-local/` не синхронизируется с
origin никогда (пишется локально, merge затёр бы незапушенное).

Вечерний замер сняли уже с origin — и сравнить с утренним стало нельзя. Ответа на простой
вопрос «сдвинулся ли бэклог» не получилось вовсе; пришлось восстанавливать состояние из
истории git.

Ключевое: **ADR-152 про ровно эту слепоту был написан за несколько часов до, тем же
автором.** Значит правило, которое надо ПОМНИТЬ, не работает. Работает только проверка,
которая называет источник САМА — как приёмка, научившаяся говорить «измерено из worktree»
и после этого трижды поймавшая своего же автора.

Поэтому тесты ниже проверяют не подсчёт (он тривиален), а невозможность получить число
БЕЗ источника.
"""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from unittest import mock

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "tracker_counts.py"


def _mod():
    spec = importlib.util.spec_from_file_location("tracker_counts", str(_SCRIPT))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class TestSourceIsAlwaysNamed(unittest.TestCase):

    def setUp(self):
        self.m = _mod()

    def test_local_counts_warn_that_they_do_not_reflect_origin(self):
        """Сердце аварии: локальное число без предупреждения ввело владельца в заблуждение."""
        with mock.patch.object(self.m, "_git", return_value="1154"):
            note = self.m.source_note(local=True)
        self.assertIn("ЛОКАЛЬНОЕ", note)
        self.assertIn("НЕ отражают origin", note)
        self.assertIn("1154", note, "отставание обязано быть НАЗВАНО числом")

    def test_origin_counts_name_the_commit(self):
        """Источник-истина тоже обязан быть опознаваем — иначе два замера не сравнить."""
        with mock.patch.object(self.m, "_git", return_value="8a67f95a3"):
            note = self.m.source_note(local=False)
        self.assertIn("origin/main", note)
        self.assertIn("8a67f95a3", note)

    def test_unmeasurable_lag_is_UNCHECKED_not_silence(self):
        """«Git не ответил» ≠ «отставания нет» (инвариант #17)."""
        with mock.patch.object(self.m, "_git", return_value=""):
            note = self.m.source_note(local=True)
        self.assertIn("НЕ ИЗМЕРЕНО", note)

    def test_the_default_mode_is_origin_not_local(self):
        """Умолчание обязано быть истиной: ошибиться должно быть ТРУДНЕЕ, чем не ошибиться."""
        src = _SCRIPT.read_text(encoding="utf-8")
        self.assertIn('ap.add_argument("--local"', src,
                      "локальный режим обязан требовать ЯВНОГО флага")
        self.assertNotIn('ap.add_argument("--origin"', src,
                         "origin не может быть опциональным — это умолчание")


class TestCountingItself(unittest.TestCase):

    def setUp(self):
        self.m = _mod()

    def test_status_is_read_from_frontmatter(self):
        self.assertEqual(self.m._status_of("---\nstatus: backlog\n---\n"), "backlog")

    def test_a_card_without_status_is_named_not_dropped(self):
        """Молча выброшенная карточка исказила бы итог — она обязана попасть в свой класс."""
        self.assertEqual(self.m._status_of("# карточка без статуса"), "нет-статуса")


if __name__ == "__main__":
    unittest.main()
