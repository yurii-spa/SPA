#!/usr/bin/env python3
"""Контроль пробы приёмки `tier_b_protocol_path_survives_a_disabled_log` (ADR-948).

# LLM_FORBIDDEN

**Чего требует правило приёмки** (`.claude/rules/acceptance.md`, п. 3): новая проба
регистрируется ТОЛЬКО с тестом, где она зелёная на ЦЕЛОМ контуре и красная на
КАЖДОМ порванном звене — с названным звеном, — и где она НЕ проходит ПОДСТРОКОЙ.

**Порванные звенья здесь настоящие, а не выдуманные:**

* дверь ``default_file`` вернули к телу ДО ADR-948 (дословная авария 02.11) ⇒
  проба обязана покраснеть и НАЗВАТЬ модули;
* каталог Tier-B не читается ⇒ ``unmeasured`` с названной причиной;
* признака не несёт ни один модуль ⇒ ``unmeasured``, и «модулей ноль» за «чисто»
  не выдаётся;
* предмет до своей двери не доехал ⇒ ``unmeasured`` (частичное покрытие — не
  «выполнено»).

**Почему подстрокой проба не проходит.** Наличие строки ``"log_path": None`` в
исходнике делает модуль ПРЕДМЕТОМ, а вердикт даёт настоящий вызов — это
проверяется сценой, где признак есть, а дверь сломана.
"""

from __future__ import annotations

import importlib
import os
import unittest
from pathlib import Path

from spa_core.monitoring import card_acceptance as ca

PROBE = "tier_b_protocol_path_survives_a_disabled_log"


def _pre_adr948_default_file(path, default):
    """Тело ``default_file`` ДО ADR-948: начинается с ``os.fspath(path)``.

    Это и есть авария: ``os.fspath(None)`` поднимает
    ``TypeError: expected str, bytes or os.PathLike object, not NoneType``.
    """
    if os.fspath(path) != os.fspath(default):
        return path
    return path


def _subjects() -> list[str]:
    folder = Path(ca.REPO_ROOT) / "spa_core" / "analytics"
    return sorted(
        path.stem for path in folder.glob("*.py")
        if ca._DISABLED_LOG_FORM in path.read_text(errors="replace")
    )


class TheProbeIsGreenOnTheWholeCircuit(unittest.TestCase):

    def test_the_live_circuit_is_satisfied_and_names_how_many_it_called(self):
        verdict, detail = ca.PROBES[PROBE](None)
        self.assertEqual(ca.SATISFIED, verdict, detail)
        self.assertIn("падений НЕТ", detail)

    def test_the_subject_is_not_empty_so_the_green_is_not_vacuous(self):
        """Зелёный над ПУСТЫМ предметом ничего не доказывает — предмет назван."""
        self.assertGreater(len(_subjects()), 0)


class TheProbeIsRedOnEachBrokenLink(unittest.TestCase):

    def test_reverting_the_door_turns_the_probe_RED_and_names_the_modules(self):
        """Звено: сама дверь ``default_file``. Модули связывают её при ИМПОРТЕ
        (``from … import default_file as _default_file``), поэтому подмена идёт у
        каждого предмета — иначе контроль судил бы о двери, которую модули уже
        не спрашивают."""
        subjects = _subjects()
        self.assertGreater(len(subjects), 0)
        patched: list[tuple[object, object]] = []
        for stem in subjects:
            module = importlib.import_module(f"spa_core.analytics.{stem}")
            if hasattr(module, "_default_file"):
                patched.append((module, module._default_file))
                module._default_file = _pre_adr948_default_file
        self.assertGreater(len(patched), 0, "ни у одного предмета нет двери _default_file")
        try:
            verdict, detail = ca.PROBES[PROBE](None)
        finally:
            for module, original in patched:
                module._default_file = original
        self.assertEqual(ca.NOT_SATISFIED, verdict, detail)
        self.assertIn("падают на отключённом логе", detail)
        # Вердикт обязан НАЗВАТЬ хотя бы один модуль поимённо: «что-то сломано»
        # находкой не является.
        self.assertTrue(any(stem in detail for stem in subjects), detail)

    def test_the_probe_recovers_after_the_control(self):
        """Контроль обязан быть ОБРАТИМЫМ: иначе красный предыдущей пробы
        остался бы свойством прогона, а не двери."""
        verdict, detail = ca.PROBES[PROBE](None)
        self.assertEqual(ca.SATISFIED, verdict, detail)

    def test_an_unreadable_folder_is_UNMEASURED_with_a_named_reason(self):
        original = ca.REPO_ROOT
        ca.REPO_ROOT = "/nonexistent-root-for-the-control"
        try:
            verdict, detail = ca.PROBES[PROBE](None)
        finally:
            ca.REPO_ROOT = original
        self.assertEqual(ca.UNMEASURED, verdict, detail)
        self.assertIn("предмет НЕ ИЗМЕРЕН", detail)

    def test_no_subject_at_all_is_UNMEASURED_not_clean(self):
        """«Модулей ноль» за «чисто» не выдаётся (инв. #17)."""
        import tempfile
        original = ca.REPO_ROOT
        with tempfile.TemporaryDirectory() as box:
            (Path(box) / "spa_core" / "analytics").mkdir(parents=True)
            ca.REPO_ROOT = box
            try:
                verdict, detail = ca.PROBES[PROBE](None)
            finally:
                ca.REPO_ROOT = original
        self.assertEqual(ca.UNMEASURED, verdict, detail)
        self.assertIn("ни одного модуля с признаком", detail)

    def test_a_subject_that_never_reaches_its_door_is_UNMEASURED(self):
        """ПОДСТРОКОЙ проба не проходит и в обратную сторону: файл несёт признак,
        но импортироваться не может ⇒ про него не известно НИЧЕГО, и частичное
        покрытие объявляется `unmeasured`, а не «выполнено»."""
        import tempfile
        original = ca.REPO_ROOT
        with tempfile.TemporaryDirectory() as box:
            folder = Path(box) / "spa_core" / "analytics"
            folder.mkdir(parents=True)
            (folder / "nosuchmodule_for_the_control.py").write_text(
                'CFG = {"log_path": None}\n')
            ca.REPO_ROOT = box
            try:
                verdict, detail = ca.PROBES[PROBE](None)
            finally:
                ca.REPO_ROOT = original
        self.assertEqual(ca.UNMEASURED, verdict, detail)
        self.assertIn("до своей двери НЕ доехали", detail)


class TheProbeIsRegisteredAndMeasuresAnOutcome(unittest.TestCase):

    def test_the_probe_is_in_the_registry(self):
        self.assertIn(PROBE, ca.PROBES)

    def test_every_verdict_is_a_declared_member(self):
        verdict, _detail = ca.PROBES[PROBE](None)
        self.assertIn(verdict, (ca.SATISFIED, ca.NOT_SATISFIED, ca.UNMEASURED))

    def test_the_probe_does_not_write_into_the_live_data_dir(self):
        """Проба зовётся КАЖДЫЙ цикл шагом 0-офис: `SPA_DATA_DIR` на время вызова
        уводится в песочницу и ВОЗВРАЩАЕТСЯ — иначе измерение меняло бы живое
        состояние, а следующий читатель получил бы чужой каталог."""
        before = os.environ.get("SPA_DATA_DIR")
        ca.PROBES[PROBE](None)
        self.assertEqual(before, os.environ.get("SPA_DATA_DIR"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
