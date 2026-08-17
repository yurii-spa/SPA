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


class TestTheVerdictItself(unittest.TestCase):
    """Прогоняем НАСТОЯЩИЙ сторож, а не копию его логики.

    Замер 2026-08-16 на коде после правки 10.08: разделение доехало только до
    `reasons`, а ВЕРДИКТ (`status`, иконка и код возврата — то, что человек
    реально читает) по-прежнему считал общее число. 303 расхождения, все до
    единого по построению нормальные, давали `WARNING` и `exit 1` — каждый день
    и навсегда: `data/` — живой трек, правило доставки §4 запрещает его возить,
    поэтому счётчик физически не может стать нулём.

    Классы выше проверяли СТРОКИ исходника и СВОЮ копию отбора (`_split`), а не
    `check_deployment_drift`, — поэтому были зелёными всё это время, пока
    заголовок оставался жёлтым на верном состоянии.
    """

    NOISE = (["data/f%d.json" % i for i in range(166)]
             + ["nimbalyst-local/tracker/c%d.md" % i for i in range(117)]
             + ["docs/d%d.md" % i for i in range(20)])

    def _run(self, files, root):
        for p in files:
            (root / p).parent.mkdir(parents=True, exist_ok=True)
            (root / p).write_text("on-disk", encoding="utf-8")

        def runner(args, cwd, stdin=None):
            if args[0] == "rev-parse" and args[1] == "HEAD":
                return True, "a" * 40
            if args[:2] == ["rev-parse", "--abbrev-ref"]:
                return True, "main"
            if args[0] == "rev-parse":
                return True, "b" * 40
            if args[0] == "rev-list":
                return True, "0\t0"
            if args[0] == "ls-tree":
                return True, "\n".join("100644 blob %040d\t%s" % (i, p)
                                       for i, p in enumerate(files))
            if args[0] == "hash-object":   # every file differs from the delivered blob
                return True, "\n".join("c" * 40 for _ in stdin.strip().splitlines())
            return False, "unexpected {}".format(args)

        return m.check_deployment_drift(repo_root=root, fetch=False, git_runner=runner,
                                        plist_reader=lambda d: [])

    def test_drift_that_is_entirely_by_design_reads_green(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as td:
            rep = self._run(list(self.NOISE), Path(td))
        self.assertEqual(len(rep.other_files), 303)
        self.assertEqual(rep.status, m.OK, "303 нормальных расхождения — не тревога")
        self.assertEqual(rep.by_design_files, 303)
        self.assertEqual(rep.synced_other_files, [])
        # норма всё ещё НАЗВАНА — сигнал не потерян, он просто не в вердикте
        self.assertTrue(any("Reference only" in r for r in rep.reasons))

    def test_one_synced_file_among_the_noise_turns_the_verdict(self):
        """Ноль обязан значить ноль, а единица — требовать внимания."""
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as td:
            rep = self._run(list(self.NOISE) + ["spa_core/monitoring/x.py"], Path(td))
        self.assertEqual(rep.status, m.WARNING)
        self.assertEqual(rep.synced_other_files, ["spa_core/monitoring/x.py"])
        self.assertEqual(rep.by_design_files, 303)
        # и он НАЗВАН, а не утоплен в счётчике
        self.assertTrue(any("spa_core/monitoring/x.py" in r for r in rep.reasons))

    def test_money_path_still_outranks_everything(self):
        """Правка заголовка не имеет права смягчить главный класс."""
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as td:
            rep = self._run(list(self.NOISE) + ["spa_core/risk/policy.py"], Path(td))
        self.assertEqual(rep.status, m.CRITICAL)
        self.assertEqual(rep.money_path_files, ["spa_core/risk/policy.py"])

    def test_synced_prefixes_are_a_single_named_constant(self):
        """Один список на модуль: две копии разошлись бы молча."""
        self.assertEqual(m.SYNCED_PREFIXES,
                         ("spa_core/", "scripts/", "tests/", "architecture/"))


if __name__ == "__main__":
    unittest.main()
