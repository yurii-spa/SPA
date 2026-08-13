"""Правило «запись в реестре R&D = проводка» — и его границы.

Карточка `inbox-hrapovik-nepodklyuchennyh-skriptov-ne-ot` (цикл #192 оставил храповик
КРАСНЫМ осознанно): у сторожа не было способа отличить два вида скриптов без
вызывающего — «доставлен и мёртв» (ради чего он заведён) и «исследовательский замер,
который запускают руками» (26 штук, 25 внесены в базу задним числом). Пока различия
нет, каждый новый R&D-замер упирается в выбор: соврать базе или держать CI красным.

**Почему правило узкое.** Карточка рекомендовала считать проводкой любое упоминание
в `docs/`. Замер 13.08 это отверг: имя хотя бы одного из 88 скриптов без вызывающего
встречается где-нибудь в `docs/` у 62 из них, а у пяти единственное упоминание — в
`docs/journal/`, то есть в летописи, которая называет поимённо всё доставленное.
Правило «любой docs/» сняло бы с учёта две трети подопечных — это не различение
классов, а отключение сторожа. Засчитывается ТОЛЬКО реестр R&D-идей.

Каждая проверка ниже — на синтетическом дереве (корень — вход функции, а не окружение),
поэтому у каждой есть честная мутация: убери правило — проверка покраснеет поимённо.
"""
from __future__ import annotations

import pathlib
import tempfile
import unittest

from spa_core.tests import _unwired
from spa_core.tests._unwired import (
    entrypoint_scripts,
    registry_recorded_scripts,
    scripts_without_caller,
    unwired_scripts,
)


def _fake_repo(tmp: pathlib.Path) -> pathlib.Path:
    """Крошечный репозиторий со всеми четырьмя случаями сразу."""
    (tmp / "scripts").mkdir(parents=True)
    (tmp / "launchd").mkdir()
    (tmp / "docs" / "journal").mkdir(parents=True)

    body = 'if __name__ == "__main__":\n    pass\n'
    for name in ("alone.py", "wired.py", "journal_only.py", "measured.py"):
        (tmp / "scripts" / name).write_text(body, encoding="utf-8")

    # НАСТОЯЩАЯ проводка: обёртка зовёт wired.py
    (tmp / "scripts" / "run_it.sh").write_text(
        '#!/bin/bash\npython3 scripts/wired.py --once\n', encoding="utf-8")
    # летопись называет journal_only.py поимённо — и это НЕ проводка
    (tmp / "docs" / "journal" / "2026-W33.md").write_text(
        "цикл #999 доставил scripts/journal_only.py, 4 теста\n", encoding="utf-8")
    # реестр R&D: продукт measured.py — запись в нём
    (tmp / "docs" / "DYNAMIC_LEVERAGE_GUARDIAN.md").write_text(
        "### Идея #99 — проверено scripts/measured.py: Calmar 0.81 против 0.79\n",
        encoding="utf-8")
    return tmp


class TestTheRuleOnASyntheticRepo(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = _fake_repo(pathlib.Path(self._tmp.name))
        self.addCleanup(self._tmp.cleanup)

    def test_the_raw_measurement_forgives_nothing(self):
        """`scripts_without_caller` отвечает на свой вопрос — «его кто-то ЗОВЁТ?».

        Реестр здесь не прощает: у measured.py вызывающего нет, и сырое измерение
        обязано это сказать. Иначе различить два вида будет нечем.
        """
        self.assertEqual(
            scripts_without_caller(self.root),
            ["alone", "journal_only", "measured"])

    def test_a_registry_record_counts_as_wiring(self):
        """measured.py уходит из-под храповика — его продукт доставлен в реестр."""
        self.assertNotIn("measured", unwired_scripts(self.root))
        self.assertEqual(registry_recorded_scripts(self.root), {"measured"})

    def test_a_mention_in_the_journal_does_NOT_count(self):
        """Летопись называет всё доставленное — доказательством она не является."""
        self.assertIn("journal_only", unwired_scripts(self.root))

    def test_a_script_nobody_calls_and_nobody_measured_stays_watched(self):
        """Тот самый класс, ради которого храповик заведён."""
        self.assertIn("alone", unwired_scripts(self.root))

    def test_a_real_caller_is_still_seen(self):
        """Положительный контроль детектора: настоящий вызов из обёртки виден."""
        self.assertNotIn("wired", scripts_without_caller(self.root))
        self.assertNotIn("wired", unwired_scripts(self.root))

    def test_mutation_without_the_registry_the_measured_script_reddens(self):
        """Мутация: нет реестра — measured.py снова объявлен мёртвым.

        Это и есть доказательство, что зелёный храповик держится ИМЕННО правилом,
        а не тем, что скрипт где-то случайно упомянут.
        """
        (self.root / "docs" / "DYNAMIC_LEVERAGE_GUARDIAN.md").unlink()
        self.assertIn("measured", unwired_scripts(self.root))


class TestTheRuleOnTheRealRepo(unittest.TestCase):
    """То же самое, но на настоящем дереве — синтетика не заменяет факта."""

    def test_edge_exposure_depth_is_excused_by_its_registry_record(self):
        """Скрипт из #192: вызывающего нет и не будет, замер в реестре есть."""
        self.assertIn("edge_exposure_depth", scripts_without_caller(),
                      "у R&D-замера вызывающего быть не должно — измерение изменилось")
        self.assertIn("edge_exposure_depth", registry_recorded_scripts())
        self.assertNotIn("edge_exposure_depth", unwired_scripts())

    def test_the_carve_out_did_not_swallow_the_watch(self):
        """Правило обязано СУЖАТЬ класс, а не отменять сторожа.

        Порог — не украшение: 13.08 без вычета подопечных было 88, с вычетом 54.
        Если однажды вычет заберёт почти всех, значит правило расширили до «любого
        упоминания в docs/» — ровно то, что замер отверг.
        """
        raw, watched = set(scripts_without_caller()), set(unwired_scripts())
        self.assertTrue(watched, "храповик остался без единого подопечного")
        self.assertLess(len(raw - watched), len(raw) / 2, (
            f"вычет забрал {len(raw - watched)} из {len(raw)} — это уже не класс "
            "«ручной R&D», а отключение сторожа"))

    def test_only_the_registry_is_admissible_evidence(self):
        """Ни один файл `docs/` кроме реестра не участвует в решении.

        Проверка структурная: путь-исключение ровно один и он — реестр R&D.
        Расширение до каталога `docs/` обязано быть решением, а не правкой строки.
        """
        self.assertEqual(_unwired._RND_REGISTRY,
                         pathlib.Path("docs") / "DYNAMIC_LEVERAGE_GUARDIAN.md")
        self.assertTrue((_unwired._ROOT / _unwired._RND_REGISTRY).exists(),
                        "реестр R&D исчез — правило судит по несуществующему файлу")

    def test_entrypoints_are_still_found(self):
        """Общий предохранитель: пустой список входов сделал бы всё выше зелёным."""
        self.assertGreater(len(entrypoint_scripts()), 100)


if __name__ == "__main__":
    unittest.main()
