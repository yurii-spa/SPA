# -*- coding: utf-8 -*-
"""Контроль пробы `queue_reader_names_record_memory_loss` (цикл #860, ADR-716).

`.claude/rules/acceptance.md` п. 3: новая проба регистрируется ТОЛЬКО с тестом, где она
зелена на целом контуре и КРАСНА НА КАЖДОМ ПОРВАННОМ ЗВЕНЕ — с названным звеном, — и где
она не проходит подстрокой (ADR-333).

Контур пробы — ЧИТАТЕЛЬ ОЧЕРЕДИ (`scripts/orchestrator_queue.py`, шаг 1 протокола): он
обязан доносить до читающего вердикт оси памяти, который прибор расхождения мерит с #859.
Звенья, каждое ломается по одному и на ОДНОРАЗОВОЙ копии читателя:

1. читателя нет вовсе ⇒ третий исход («НЕ ИЗМЕРЕНО» с причиной);
2. читатель не несёт ось памяти — ровно состояние `origin/main` до #860 ⇒ `not_satisfied`;
3. вердикт есть, а ЧИСЛА пропавших записей нет (вторая мерка из прозы) ⇒ `not_satisfied`;
4. вердикт есть, а пропавшие записи НЕ названы поимённо ⇒ `not_satisfied`;
5. вердикт есть в JSON, но человек у терминала его не видит (нет раздела stderr);
6. читатель объявляет потерю ЧЕМУ УГОДНО, включая чистую переписку тела (fail-LOUD);
7. читатель падает на вызове ⇒ предпосылка НЕ ОБЕСПЕЧЕНА, третий исход;
8. читатель ПЕЧАТАЕТ нужные слова и не несёт полей — проба не проходит подстрокой.

Звенья ломаются **хирургией по тексту** текущего читателя, а не версией из истории git:
в CI клон глубины 1, и «версия до правки» там недостижима — тест, зависящий от истории,
отвечал бы «предпосылка не обеспечена» вместо измерения (урок ADR-479).

Живое дерево не трогается: каждое звено живёт в `tempfile.mkdtemp()`. Литеральных дат и
литеральных pid здесь нет.
"""
import os
import re
import shutil
import tempfile
import unittest
from pathlib import Path

from spa_core.monitoring import card_acceptance as ca

PROBE = "queue_reader_names_record_memory_loss"
_ROOT = Path(__file__).resolve().parents[2]
_READER_REL = os.path.join("scripts", "orchestrator_queue.py")


def run(root: str):
    return ca.PROBES[PROBE](None, repo_root=root)


class Scene:
    """Одноразовая копия контура: ЧИТАТЕЛЬ + прибор рядом, живое дерево не тронуто.

    `spa_core` в сцену не копируется НАМЕРЕННО: читатель ввозит его из того дерева,
    где идёт прогон, и предмет измерения — код самого читателя. Пустой `.git` внутри
    делает сцену НЕ-репозиторием детерминированно на любом хосте.
    """

    def __init__(self, with_reader: bool = True):
        self.dir = tempfile.mkdtemp(prefix="probe_queue_mem_")
        os.mkdir(os.path.join(self.dir, "scripts"))
        os.mkdir(os.path.join(self.dir, ".git"))
        shutil.copy2(_ROOT / "scripts" / "check_tracker_drift.py",
                     os.path.join(self.dir, "scripts", "check_tracker_drift.py"))
        if with_reader:
            shutil.copy2(_ROOT / _READER_REL, self.reader)

    @property
    def reader(self) -> str:
        return os.path.join(self.dir, _READER_REL)

    def surgery(self, pattern: str, repl: str, *, count: int = 0, expect: int = 1):
        """Поломать ОДНО звено заменой в тексте читателя; число замен проверяется.

        Проверка числа обязательна: хирургия, не нашедшая своего места, дала бы ЦЕЛЫЙ
        контур под именем порванного звена — тест зеленел бы, ничего не сломав.
        """
        with open(self.reader, encoding="utf-8") as fh:
            text = fh.read()
        hits = len(re.findall(pattern, text))
        assert hits == expect, f"хирургия {pattern!r}: найдено {hits}, ожидалось {expect}"
        with open(self.reader, "w", encoding="utf-8") as fh:
            fh.write(re.sub(pattern, repl, text, count=count))

    def close(self):
        shutil.rmtree(self.dir, ignore_errors=True)


class ProbeMeasuresTheReader(unittest.TestCase):

    def setUp(self):
        self.scenes: list[Scene] = []

    def tearDown(self):
        for s in self.scenes:
            s.close()

    def scene(self, **kw) -> Scene:
        s = Scene(**kw)
        self.scenes.append(s)
        return s

    # ── целый контур ────────────────────────────────────────────────────────

    def test_whole_contour_is_satisfied(self):
        verdict, why = run(self.scene().dir)
        self.assertEqual(ca.SATISFIED, verdict, why)
        self.assertIn("tree_poorer", why)

    def test_live_tree_is_satisfied(self):
        """То же самое на НАСТОЯЩЕМ дереве прогона — проба мерит не только сцену."""
        verdict, why = run(str(_ROOT))
        self.assertEqual(ca.SATISFIED, verdict, why)

    # ── звено 1: читателя нет вовсе ⇒ третий исход ──────────────────────────

    def test_missing_reader_is_the_third_outcome(self):
        verdict, why = run(self.scene(with_reader=False).dir)
        self.assertEqual(ca.UNMEASURED, verdict, why)
        self.assertIn("orchestrator_queue.py", why)

    # ── звено 2: у читателя НЕТ оси памяти (состояние origin/main до #860) ──

    def test_reader_without_the_memory_axis_is_not_satisfied(self):
        s = self.scene()
        s.surgery(r"verdicts\[f\.card_id\]\.update\(_memory_verdict\(f, drift\)\)",
                  "pass", expect=1)
        verdict, why = run(s.dir)
        self.assertEqual(ca.NOT_SATISFIED, verdict, why)
        self.assertIn("НЕТ оси памяти", why)

    # ── звено 3: вердикт есть, ЧИСЛА нет ────────────────────────────────────

    def test_reader_without_the_number_is_not_satisfied(self):
        s = self.scene()
        s.surgery(r'"origin_memory_missing_tree": f\.memory_missing_tree,',
                  '"origin_memory_missing_tree": 0,', expect=1)
        verdict, why = run(s.dir)
        self.assertEqual(ca.NOT_SATISFIED, verdict, why)
        self.assertIn("ЧИСЛО", why)

    # ── звено 4: потеря названа, записи — нет ───────────────────────────────

    def test_reader_that_hides_the_record_numbers_is_not_satisfied(self):
        s = self.scene()
        s.surgery(r'"origin_memory_detail": f\.memory_detail,',
                  '"origin_memory_detail": "копии расходятся",', expect=1)
        verdict, why = run(s.dir)
        self.assertEqual(ca.NOT_SATISFIED, verdict, why)
        self.assertIn("поимённо", why)

    # ── звено 5: JSON знает, человек у терминала — нет ──────────────────────

    def test_reader_silent_in_stderr_is_not_satisfied(self):
        s = self.scene()
        s.surgery(r'🔴 ПАМЯТЬ КОПИЙ РАЗОШЛАСЬ', 'память копий (тихо)', expect=1)
        verdict, why = run(s.dir)
        self.assertEqual(ca.NOT_SATISFIED, verdict, why)
        self.assertIn("человек у терминала", why)

    # ── звено 6: читатель кричит на ЧТО УГОДНО (fail-LOUD) ─────────────────

    def test_reader_that_cries_on_any_difference_is_not_satisfied(self):
        """Обратная сторона: сторож, говорящий «нет» всему, бесполезен как молчащий."""
        s = self.scene()
        s.surgery(r"if f\.memory in drift\.MEMORY_FINDINGS:", "if f.memory:", expect=1)
        verdict, why = run(s.dir)
        self.assertEqual(ca.NOT_SATISFIED, verdict, why)
        self.assertIn("МОЛЧАТЬ", why)

    def test_reader_that_calls_any_difference_a_loss_is_not_satisfied(self):
        """Та же сторона, но ложь в самом ВЕРДИКТЕ, а не только в примечании."""
        s = self.scene()
        s.surgery(r'"origin_memory": f\.memory,',
                  '"origin_memory": drift.MEMORY_TREE_POORER,', expect=1)
        verdict, why = run(s.dir)
        self.assertEqual(ca.NOT_SATISFIED, verdict, why)
        self.assertIn("ЧИСТОЙ ПЕРЕПИСКЕ", why)

    # ── звено 7: читатель падает ⇒ предпосылка НЕ ОБЕСПЕЧЕНА ────────────────

    def test_reader_that_blows_up_is_the_third_outcome(self):
        s = self.scene()
        s.surgery(r"def cmd_list\(args\) -> int:\n",
                  "def cmd_list(args) -> int:\n    raise RuntimeError('читатель сломан')\n",
                  expect=1)
        verdict, why = run(s.dir)
        self.assertEqual(ca.UNMEASURED, verdict, why)
        self.assertIn("предпосылка пробы НЕ ОБЕСПЕЧЕНА", why)

    # ── звено 8: подстрокой проба НЕ проходит (ADR-333) ─────────────────────

    def test_probe_does_not_pass_on_the_words_alone(self):
        """Читатель, ПЕЧАТАЮЩИЙ нужные слова и не несущий полей, пробу не удовлетворяет.

        Это не теория: самый дешёвый способ «закрыть» такую карточку — дописать фразу в
        stderr. Проба требует ПОЛЯ вердикта и ЧИСЛО, а слова — лишь довесок.
        """
        s = self.scene()
        s.surgery(r"verdicts\[f\.card_id\]\.update\(_memory_verdict\(f, drift\)\)",
                  "pass", expect=1)
        s.surgery(r"    def _ids\(kind\):\n",
                  "    print('🔴 ПАМЯТЬ КОПИЙ РАЗОШЛАСЬ: inbox-order — записи #717, #718 "
                  "пропали', file=sys.stderr)\n\n    def _ids(kind):\n", expect=1)
        verdict, why = run(s.dir)
        self.assertEqual(ca.NOT_SATISFIED, verdict, why)
        self.assertIn("НЕТ оси памяти", why)


if __name__ == "__main__":
    unittest.main()
