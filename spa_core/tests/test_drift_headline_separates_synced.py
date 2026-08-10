"""Дрейф разделён по синхронизируемости — иначе сигнал приучает себя не читать.

Замер 2026-08-10: сторож выдавал заголовком «303 файла разошлись». Разбор:

* `data/` — 166 (живой трек, синхронизация его НЕ ВОЗИТ по правилу §4);
* `nimbalyst-local/` — 117 (очередь карточек, живёт на машине);
* `docs/` + `archive/` — 78;
* всё остальное — **9**, и кода среди них нет вовсе.

То есть 294 из 303 — норма, прямо предписанная правилом доставки. Число росло каждый
день и пять витков подряд докладывалось владельцу как накапливающийся риск, ни разу
не разобранное.

Сторож при этом НЕ ВРАЛ: он честно считал расхождения и честно добавлял «ни одного
money-path файла». Дефект в том, ЧТО вынесено в заголовок: сигнал, состоящий из нормы,
воспитывает привычку его пропускать. Усталость от тревоги опаснее молчания — молчащий
сторож хотя бы не создаёт уверенности, что за областью следят.
"""
from __future__ import annotations

import inspect
import unittest

from spa_core.monitoring import deployment_drift_monitor as m


class TestHeadlineSeparation(unittest.TestCase):

    def setUp(self):
        self.src = inspect.getsource(m)

    def test_synced_dirs_are_reported_separately(self):
        """Значимая часть обязана иметь СВОЮ строку."""
        self.assertIn("in SYNCED dirs differ", self.src)

    def test_by_design_drift_is_marked_as_expected(self):
        """Норма обязана быть названа нормой, а не смешана со значимым."""
        self.assertIn("outside synced dirs", self.src)
        self.assertIn("Reference only", self.src)

    def test_the_synced_list_matches_the_delivery_rule(self):
        """Список обязан совпадать с тем, что реально возит синхронизация.

        Разойдётся — и часть кода снова утонет в «норме». Источник правды —
        `CODE_PATHS` в `scripts/code_sync_from_origin.sh`.
        """
        for d in ("spa_core/", "scripts/", "tests/", "architecture/"):
            self.assertIn(f'"{d}"', self.src, f"{d} обязан считаться синхронизируемым")

    def test_the_money_path_line_is_untouched(self):
        """Главная строка сторожа не должна пострадать от правки заголовка."""
        self.assertIn("money-path file(s) differ", self.src)
        self.assertIn("the risk logic running in", self.src)


class TestClassificationLogic(unittest.TestCase):
    """Проверка самой логики отбора, а не только наличия строк."""

    def _split(self, files: list) -> tuple:
        synced = ("spa_core/", "scripts/", "tests/", "architecture/")
        code = [f for f in files if str(f).startswith(synced)]
        return code, len(files) - len(code)

    def test_live_track_files_are_by_design(self):
        code, by_design = self._split(["data/equity_curve_daily.json",
                                       "nimbalyst-local/tracker/x.md"])
        self.assertEqual(code, [])
        self.assertEqual(by_design, 2)

    def test_code_files_are_significant(self):
        code, by_design = self._split(["spa_core/risk/policy.py", "scripts/x.sh"])
        self.assertEqual(len(code), 2)
        self.assertEqual(by_design, 0)

    def test_a_mixed_set_is_split_not_summed(self):
        """Сердце правки: 1 значимый среди 100 нормальных обязан быть виден."""
        files = ["data/f%d.json" % i for i in range(100)] + ["spa_core/risk/policy.py"]
        code, by_design = self._split(files)
        self.assertEqual(code, ["spa_core/risk/policy.py"])
        self.assertEqual(by_design, 100)


if __name__ == "__main__":
    unittest.main()
