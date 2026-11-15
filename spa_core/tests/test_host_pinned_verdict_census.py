"""Приёмка переписи «вердикт закреплён за ХОЗЯИНОМ» + контроль переписанного утверждения.

Карточка `inbox-proverka-slepoty-predela-zakrepila-otvet`. Предмет — не «есть ли модуль», а
ИСХОД: перепись обязана быть ЗЕЛЕНА на целом контуре и КРАСНА на каждом порванном звене, с
названным звеном, и НЕ проходить подстрокой (ADR-333, `.claude/rules/acceptance.md` п. 3).

Что держит эта батарея:

* **положительный контроль — настоящая авария в её настоящем месте.** Редакция
  `test_observer_margin_control.py` ДО починки (`git show origin/main:…`) обязана получить
  `PINNED`. Перепись, никогда не видевшая настоящей поломки, — украшение;
* **синтетическая сцена предметом НЕ является:** сфабрикованные строки (`observe_door=`)
  решают исход сами, и `_BZ_BLIND` в них закреплён за ДАННЫМИ, а не за машиной. Замер цикла
  #1143: условие поверхности, заданное ФАЙЛУ вместо ОБЛАСТИ, давало 8 ложных `PINNED`;
* **область, не гонящая гонку, в поверхность не попадает** — это не «чисто», а «вопрос не
  задан», и выдумывать ей вердикт запрещено;
* **подстрокой перепись не проходит:** имя двери в комментарии или в строковом литерале
  поверхностью не является;
* **три исхода различимы** (инв. #17): измерено · предмет НЕ пуст · НЕ ИЗМЕРЕНО с НАЗВАННОЙ
  причиной. Отсутствие каталога тестов — третий исход, а не пустой класс;
* **храповик:** предмет обязан быть ПОДМНОЖЕСТВОМ базы, и база может только уменьшаться;
* **переписанное утверждение проверено в ОБЕ стороны:** на хозяине, где предел КУСАЕТ, тест
  ЗЕЛЁН (третий исход назван, а не скипнут); при РАСХОЖДЕНИИ двух дверей — КРАСЕН.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CENSUS_PATH = ROOT / "scripts" / "host_pinned_verdict_census.py"
BASELINE = Path(__file__).resolve().parent / "host_pinned_verdict_baseline.json"
SUBJECT_REL = "spa_core/tests/test_observer_margin_control.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


hpvc = _load(CENSUS_PATH, "hpvc_under_test")
omc = _load(ROOT / SUBJECT_REL, "omc_under_test")


class ThePositiveControlReplaysTheRealFailure(unittest.TestCase):
    """Нулевая проба: авария 15.11 на байтах, которые её и несли."""

    @classmethod
    def setUpClass(cls):
        shown = subprocess.run(["git", "show", f"origin/main:{SUBJECT_REL}"],
                               cwd=str(ROOT), capture_output=True, text=True)
        cls.pre = shown.stdout if shown.returncode == 0 else None
        cls.why = f"git вернул код {shown.returncode}: {shown.stderr.strip()[:200]}"

    def test_the_pre_fix_assertion_is_named_PINNED(self):
        if self.pre is None:
            # Предпосылка не обеспечена — падать ГРОМКО, а не скипать (урок #465).
            self.fail(f"предпосылка НЕ ОБЕСПЕЧЕНА, восстановить аварию нечем: {self.why}")
        claims = hpvc.measure_source(self.pre, label="PRE")
        pinned = [c for c in claims if c.verdict == hpvc.PINNED]
        if "_HOST_TO_SCENE" in self.pre:
            self.fail("на origin/main уже лежит починенная редакция — нулевая проба "
                      "изображала бы аварию, которой нет; предмет перемерить")
        self.assertTrue(pinned, f"перепись НЕ видит аварии, ради которой написана: {claims}")
        self.assertTrue(any(c.constant == "_BZ_BLIND" for c in pinned), pinned)

    def test_the_fixed_assertion_is_named_HOST_ASKED(self):
        claims = hpvc.measure_source((ROOT / SUBJECT_REL).read_text(encoding="utf-8"),
                                     label="POST")
        self.assertTrue(claims, "починенная редакция выпала из ПОВЕРХНОСТИ — перепись "
                                "перестала смотреть на предмет вовсе")
        self.assertEqual([c.verdict for c in claims], [hpvc.HOST_ASKED] * len(claims), claims)


class TheSurfaceConditionIsAskedOfTheScopeNotTheFile(unittest.TestCase):
    """Замер #1143: условие, заданное ФАЙЛУ, дало 8 ложных `PINNED`."""

    def test_a_synthetic_scope_is_SYNTHETIC_not_PINNED(self):
        src = ("def t(self):\n"
               "    ctl = observer_margin_control(self.root, observe_door=plan())\n"
               "    self.assertEqual(ctl['busy_limit']['verdict'], _BZ_BLIND)\n")
        claims = hpvc.measure_source(src, label="synthetic")
        self.assertEqual([c.verdict for c in claims], [hpvc.SYNTHETIC], claims)

    def test_a_scope_that_does_not_drive_the_race_is_NOT_in_the_surface(self):
        """РАЗЛИЧАЮЩАЯ сцена: две области, обе утверждают, гонку гонит ОДНА.

        Область `delegated` достаёт сцену через `self.ctl` — дверь гонки в ней не названа, и
        вопрос ей не задан. Это и есть граница, объявленная прибором вслух: будь условие
        поверхности задано ФАЙЛУ, в население попали бы обе.
        """
        src = ("def drives(self):\n"
               "    ctl = observer_margin_control(self.root)\n"
               "    self.assertEqual(ctl['busy_limit']['verdict'], _BZ_BLIND)\n"
               "\n"
               "def delegated(self):\n"
               "    self.assertEqual(self.ctl['busy_limit']['verdict'], _BZ_BLIND)\n")
        claims = hpvc.measure_source(src, label="delegating")
        self.assertEqual([c.scope for c in claims], ["drives"], claims)
        self.assertEqual([c.verdict for c in claims], [hpvc.PINNED], claims)

    def test_a_real_race_scope_without_the_host_question_is_PINNED(self):
        src = ("def t(self):\n"
               "    ctl = observer_margine = observer_margin_control(self.root)\n"
               "    self.assertEqual(ctl['busy_limit']['verdict'], _BZ_BLIND)\n")
        claims = hpvc.measure_source(src, label="pinned")
        self.assertEqual([c.verdict for c in claims], [hpvc.PINNED], claims)

    def test_the_SAME_scope_WITH_the_host_question_is_HOST_ASKED(self):
        """Различающая сцена: меняется ОДНА строка — зов двери хозяина."""
        src = ("def t(self):\n"
               "    host = host_busy_limit(work_s=0.05, limit_s=0.005, repeats=10)\n"
               "    ctl = observer_margin_control(self.root)\n"
               "    self.assertEqual(ctl['busy_limit']['verdict'], _BZ_BLIND)\n")
        claims = hpvc.measure_source(src, label="asked")
        self.assertEqual([c.verdict for c in claims], [hpvc.HOST_ASKED], claims)

    def test_the_census_does_NOT_pass_by_substring(self):
        """ADR-333: имя двери в комментарии и в строке поверхностью не является."""
        src = ("def t(self):\n"
               "    # observer_margin_control тут только упомянут\n"
               "    note = 'observer_margin_control'\n"
               "    self.assertEqual(note, _BZ_BLIND)\n")
        self.assertEqual(hpvc.measure_source(src, label="substring"), [])

    def test_the_vocabulary_itself_is_not_an_expectation(self):
        """Кортеж значений — СЛОВАРЬ, а не ожидание: закреплять за хозяином нечего."""
        src = ("def t(self):\n"
               "    ctl = observer_margin_control(self.root)\n"
               "    self.assertIn(ctl['v'], BUSY_LIMIT_VERDICTS)\n")
        self.assertEqual(hpvc.measure_source(src, label="vocab"), [])


class TheThirdOutcomeIsNamedNotSilent(unittest.TestCase):
    def test_a_missing_tests_dir_is_UNMEASURED_not_an_empty_class(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(hpvc.NotMeasured):
                hpvc.measure(Path(d))

    def test_an_empty_tests_dir_is_UNMEASURED_not_an_empty_class(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "spa_core" / "tests").mkdir(parents=True)
            with self.assertRaises(hpvc.NotMeasured):
                hpvc.measure(Path(d))

    def test_an_unparsable_file_is_named_not_subtracted(self):
        with tempfile.TemporaryDirectory() as d:
            tests = Path(d) / "spa_core" / "tests"
            tests.mkdir(parents=True)
            (tests / "test_broken.py").write_text("def t(:\n", encoding="utf-8")
            census = hpvc.measure(Path(d))
            self.assertEqual(len(census.unmeasured), 1, census.unmeasured)
            self.assertIn("test_broken.py", census.unmeasured[0][0])


class TheRatchetHoldsTheClass(unittest.TestCase):
    def test_the_subject_is_a_subset_of_the_declared_baseline(self):
        base = json.loads(BASELINE.read_text(encoding="utf-8"))
        declared = {tuple(x) if isinstance(x, list) else x for x in base["subject"]}
        census = hpvc.measure(ROOT)
        self.assertEqual(census.unmeasured, [], census.unmeasured)
        found = {f"{c.file}:{c.scope}:{c.constant}" for c in census.subject}
        new = sorted(found - declared)
        self.assertEqual(new, [], f"НОВЫЕ утверждения закрепили ответ одной машины: {new}. "
                                  f"Дописывать их в базу ЗАПРЕЩЕНО — чинить утверждение")

    def test_the_surface_is_not_empty(self):
        """Пустая поверхность = перепись смотрит не туда, и её «предмет пуст» ничего не значит."""
        census = hpvc.measure(ROOT)
        self.assertIn(SUBJECT_REL, census.surface, census.surface)


class TheRewrittenClaimWorksOnEitherHost(unittest.TestCase):
    """Контроль ПЕРЕПИСАННОГО утверждения в обе стороны — без настоящей второй машины.

    Гонку за GIL подменить нельзя, поэтому проверяется ЛОГИКА ветвления: ответы двух дверей
    подставляются значениями, и спрашивается ИСХОД теста. Это контроль проводки, и он честно
    не утверждает ничего о планировщике.
    """

    @staticmethod
    def _scene(host_verdict, scene_verdict, ok_n, *, total=10, over_x=10.0):
        case = omc.TheLiveRunnerIsAskedTheSameQuestion
        probe = type("Probe", (case,), {})
        probe.setUpClass = classmethod(lambda cls: None)
        probe.tearDownClass = classmethod(lambda cls: None)
        probe.host = {"verdict": host_verdict, "ok_n": ok_n, "n": total, "over_x": over_x,
                      "reason": "подставлено контролем"}
        probe.ctl = {"busy_limit": {"verdict": scene_verdict, "ok_n": ok_n,
                                    "timeout_n": total - ok_n, "total_n": total,
                                    "over_x": over_x}}
        probe.reason = None
        probe.BUSY_REPEATS = total
        return probe

    def _run(self, probe, name):
        suite = unittest.TestLoader().loadTestsFromNames([name], probe)
        result = unittest.TestResult()
        suite.run(result)
        return result

    def test_a_BITING_host_leaves_the_claim_GREEN_with_the_third_outcome_named(self):
        probe = self._scene(omc._H_BITES, omc._BZ_BITES, 0)
        for name in ("test_the_host_question_is_asked_BEFORE_the_scene_and_its_answer_is_NAMED",
                     "test_the_scene_AGREES_with_the_host_about_the_busy_limit",
                     "test_the_REAL_runner_is_blind_to_a_busy_module_WHERE_THE_SUBJECT_EXISTS"):
            r = self._run(probe, name)
            self.assertEqual((len(r.failures), len(r.errors)), (0, 0),
                             f"{name}: {r.failures or r.errors}")
            self.assertEqual(len(r.skipped), 0, f"{name} СКИПНУЛ — «не измерено» стало "
                                                f"неотличимо от «прошло» (урок #465)")

    def test_a_BLIND_host_still_CHECKS_the_blindness(self):
        probe = self._scene(omc._H_BLIND, omc._BZ_BLIND, 9)
        r = self._run(probe,
                      "test_the_REAL_runner_is_blind_to_a_busy_module_WHERE_THE_SUBJECT_EXISTS")
        self.assertEqual((len(r.failures), len(r.errors), len(r.skipped)), (0, 0, 0),
                         r.failures or r.errors)

    def test_a_BLIND_host_whose_scene_INVENTED_bites_is_RED(self):
        """Спор двух наблюдений ГАСИТ вердикт (ADR-1017 § 26в), а не выбирает удобное."""
        probe = self._scene(omc._H_BLIND, omc._BZ_BITES, 0)
        r = self._run(probe, "test_the_scene_AGREES_with_the_host_about_the_busy_limit")
        self.assertEqual(len(r.failures), 1, "расхождение дверей прошло МОЛЧА")
        self.assertIn("разошлись", r.failures[0][1])

    def test_a_BITING_host_whose_scene_INVENTED_blindness_is_RED(self):
        probe = self._scene(omc._H_BITES, omc._BZ_BLIND, 4)
        r = self._run(probe, "test_the_scene_AGREES_with_the_host_about_the_busy_limit")
        self.assertEqual(len(r.failures), 1, "выдуманная слепота прошла МОЛЧА")

    def test_an_UNMEASURED_host_FAILS_loudly_and_does_not_skip(self):
        probe = self._scene(omc._H_UNMEASURED, omc._BZ_BLIND, 9)
        r = self._run(probe,
                      "test_the_host_question_is_asked_BEFORE_the_scene_and_its_answer_is_NAMED")
        self.assertEqual(len(r.failures), 1, "НЕ ИЗМЕРЕНО прошло молча")
        self.assertEqual(len(r.skipped), 0)
        self.assertIn("НЕ ИЗМЕРЕН", r.failures[0][1])

    def test_an_INCOMPLETE_scene_series_is_RED_not_a_proportion_of_the_remainder(self):
        probe = self._scene(omc._H_BLIND, omc._BZ_BLIND, 2, total=3)
        probe.BUSY_REPEATS = 10
        r = self._run(probe, "test_the_scene_AGREES_with_the_host_about_the_busy_limit")
        self.assertEqual(len(r.failures), 1, "обрезанный ряд прошёл как полный")


class TheHostDoorNamesItsThirdOutcome(unittest.TestCase):
    """Сама дверь хозяина: пустой ряд НЕ есть `BITES`."""

    @classmethod
    def setUpClass(cls):
        cls.bcp = _load(ROOT / "scripts" / "bounded_countdown_probe.py", "bcp_under_test")

    def test_zero_repeats_is_UNMEASURED_not_BITES(self):
        d = self.bcp.host_busy_limit(repeats=0)
        self.assertEqual(d["verdict"], "HOST_LIMIT_UNMEASURED", d)
        self.assertIn("ответом о хозяине не является", d["reason"])

    def test_a_series_of_timeouts_is_BITES_with_the_count_named(self):
        d = self.bcp.host_busy_limit(work_s=0.01, limit_s=5.0, repeats=2,
                                     runner=self._always_timeout)
        self.assertEqual(d["verdict"], "HOST_LIMIT_BITES", d)
        self.assertEqual((d["ok_n"], d["n"]), (0, 2), d)

    def test_an_ERROR_row_is_UNMEASURED_not_a_proportion(self):
        d = self.bcp.host_busy_limit(work_s=0.01, limit_s=5.0, repeats=2,
                                     runner=self._always_error)
        self.assertEqual(d["verdict"], "HOST_LIMIT_UNMEASURED", d)
        self.assertIsNone(d["ok_n"], d)
        self.assertIn("НЕПОЛОН или испорчен", d["reason"])

    def test_an_OK_row_is_BLIND_with_the_proportion_named(self):
        d = self.bcp.host_busy_limit(work_s=0.01, limit_s=5.0, repeats=2,
                                     runner=self._always_ok)
        self.assertEqual(d["verdict"], "HOST_LIMIT_BLIND", d)
        self.assertEqual((d["ok_n"], d["n"]), (2, 2), d)

    @staticmethod
    def _always_timeout(fn, limit, label):
        raise _load(ROOT / "scripts" / "bounded_countdown_probe.py",
                    "bcp_under_test")._sa.FuturesTimeout(label)

    @staticmethod
    def _always_error(fn, limit, label):
        raise ValueError(label)

    @staticmethod
    def _always_ok(fn, limit, label):
        return fn()


if __name__ == "__main__":
    unittest.main(verbosity=2)
