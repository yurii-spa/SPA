"""Приёмка пробы `persistence_and_anti_churn_gates_are_implemented` (ADR-1133).

Проба переносит вердикт прибора §22 (`spa_core/analytics/anti_churn_census.py`) в
критерий §50 приказа CIO «Реализованы persistence и anti-churn gates.». Батарея
сторожит ПРОВОДКУ переноса, а не сегодняшнее состояние §22: привяжи сцену к
«сегодня три величины ABSENT» — и батарея покраснеет в тот день, когда владелец
заведёт порог, то есть ровно от УСПЕХА. Поэтому каждая сцена подменяет прибор в
`sys.modules` (модуль ПАКЕТНЫЙ, подмена доходит) и спрашивает: что проба сделала с
ЕГО ответом.

Контроль в обе стороны у каждого звена, и порванное звено НАЗВАНО в имени теста
(`.claude/rules/acceptance.md` п. 3). Проверки подстрокой здесь нет: «в пояснении
есть слово ABSENT» ответило бы одинаково и на верный перенос, и на пробу, которая
просто перепечатывает текст прибора.

Отдельно — ОДИН тест на НАСТОЯЩЕМ приборе: без него вся батарея говорила бы только
о заглушках, то есть была бы зелена по построению (урок #1217).

# LLM_FORBIDDEN
"""
from __future__ import annotations

import sys
import types
import unittest
from unittest import mock

from spa_core.monitoring import card_acceptance as ca

PROBE = "persistence_and_anti_churn_gates_are_implemented"

#: Шкала прибора §22 — ВВЕЗЕНА у него же. Перепечатать её литералами здесь значило бы
#: завести ВТОРУЮ копию шкалы: переименуй прибор свой `ABSENT` — и батарея осталась бы
#: зелёной, проверяя мёртвое слово.
from spa_core.analytics import anti_churn_census as REAL  # noqa: E402

BINDING, LITERAL, INERT = REAL.BINDING, REAL.LITERAL, REAL.DECLARED_INERT
ABSENT, UNMEAS = REAL.ABSENT, REAL.UNMEASURED


def _report(params=None, *, section=ca.ANTI_CHURN_SECTION, tally=None,
            reach=None, vocab=(), control=True, control_why=""):
    """Отчёт прибора нужной формы. Форма взята у настоящего отчёта, не выдумана."""
    params = list(params if params is not None else
                  [{"param": n, "outcome": BINDING, "detail": ""}
                   for n in REAL.OWNER_PARAMS])
    if tally is None:
        tally = {o: sum(1 for p in params if p["outcome"] == o)
                 for o in (BINDING, LITERAL, INERT, ABSENT, UNMEAS)}
    if reach is None:
        reach = {"tact": {"kind": "unreachable_by_construction"},
                 "economics": {"two_step": {"kind": "refused", "decision": "HOLD"},
                               "three_step": {"kind": "refused", "decision": "HOLD"}},
                 "damper": {"kind": "refused_by_anti_churn"}}
    return {"section": section, "params": params, "tally": tally,
            "reachability": reach, "vocab_errors": list(vocab),
            "control": {"passed": control, "reason": control_why},
            "params_declared": REAL.OWNER_PARAMS_DECLARED,
            "surfaces": list(REAL.SURFACES_22),
            "scale_imported_from": "stub"}


def _door(*, report=None, code=None, census=None, verdict_code=None,
          drop=()):  # noqa: C901 — одна заглушка на все сцены, развилок немного
    """Прибор-заглушка. `drop` снимает названную дверь — это и есть порванное звено."""
    mod = types.ModuleType(ca.ANTI_CHURN_CENSUS_MODULE)
    for name in ("BINDING", "LITERAL", "DECLARED_INERT", "ABSENT", "UNMEASURED",
                 "OWNER_PARAMS", "OWNER_PARAMS_DECLARED", "SURFACES_22"):
        setattr(mod, name, getattr(REAL, name))
    if "census" not in drop:
        mod.census = census or (lambda root=None: report if report is not None
                                else _report())
    if "verdict_code" not in drop:
        mod.verdict_code = verdict_code or (lambda rep: code)
    return mod


class _Scene(unittest.TestCase):
    """Подменяет прибор в `sys.modules` и возвращает вердикт пробы."""

    def ask(self, module):
        with mock.patch.dict(sys.modules,
                             {ca.ANTI_CHURN_CENSUS_MODULE: module}):
            return ca.run_probe(PROBE)


class TheDeclarationLandsOnTheOwnersCriterion(unittest.TestCase):
    """Объявление, указывающее мимо населения §50, читается «мерка есть» и мерит НИЧЕГО."""

    def test_probe_is_registered_and_its_spec_validates(self):
        self.assertIn(PROBE, ca.PROBES)
        self.assertIsNone(ca.validate_spec(PROBE))

    def test_the_declared_criterion_is_in_the_s50_population_of_the_card(self):
        import os
        sys.path.insert(0, os.path.join(ca.REPO_ROOT, "scripts"))
        try:
            import cio_dod_rollup as R
        finally:
            sys.path.pop(0)
        population = R.read_population(ca.REPO_ROOT)["criteria"]
        declared = ca.probes_by_s50_criterion()
        mine = [c for c, probes in declared.items() if PROBE in probes]
        self.assertEqual(len(mine), 1, f"объявление ровно одно, нашлось {mine}")
        self.assertIn(mine[0], population,
                      "объявление указывает МИМО населения §50 — сирота, а не мерка")

    def test_the_criterion_is_not_claimed_by_a_second_probe(self):
        declared = ca.probes_by_s50_criterion()
        mine = [c for c, probes in declared.items() if PROBE in probes][0]
        self.assertEqual(declared[mine], [PROBE],
                         "два объявления на один критерий = столкновение, "
                         "и выбрать из них одно молча нельзя")

    def test_the_probe_declares_no_tree_input(self):
        # Объявить `repo_root` значило бы собрать вердикт из ДВУХ деревьев: такт из
        # названного, девять величин и обе двери — из дерева процесса.
        self.assertEqual(ca.probe_tree_inputs(PROBE), ())


class TheVerdictIsTheDoorsCode(_Scene):
    def test_code_zero_becomes_satisfied(self):
        v, d = self.ask(_door(code=0))
        self.assertEqual(v, ca.SATISFIED)
        self.assertTrue(d.strip())

    def test_code_one_becomes_not_satisfied(self):
        v, _ = self.ask(_door(code=1))
        self.assertEqual(v, ca.NOT_SATISFIED)

    def test_code_two_becomes_unmeasured_not_a_finding(self):
        v, _ = self.ask(_door(code=2, report=_report(control=False,
                                                     control_why="сцена не собралась")))
        self.assertEqual(v, ca.UNMEASURED)

    def test_an_unknown_code_is_unmeasured_and_names_the_code(self):
        v, d = self.ask(_door(code=7))
        self.assertEqual(v, ca.UNMEASURED)
        self.assertIn("7", d)

    def test_the_verdict_is_not_read_off_the_report_text(self):
        # Отчёт «грязный» (три величины ABSENT), а код двери — 0. Проба, читающая
        # ТЕКСТ, сказала бы «не выполнен»; проба, читающая КОД, скажет «выполнен».
        dirty = _report(params=[{"param": n,
                                 "outcome": ABSENT if i < 3 else BINDING,
                                 "detail": ""}
                                for i, n in enumerate(REAL.OWNER_PARAMS)])
        v, _ = self.ask(_door(code=0, report=dirty))
        self.assertEqual(v, ca.SATISFIED,
                         "вердикт обязан идти от verdict_code, а не от текста отчёта")

    def test_a_clean_report_with_code_one_is_still_a_finding(self):
        # Обратная половина той же сцены: текст чистый, код — 1.
        v, _ = self.ask(_door(code=1, report=_report()))
        self.assertEqual(v, ca.NOT_SATISFIED,
                         "чистый текст не отменяет находку, объявленную дверью")


class TheFindingNamesItsKind(_Scene):
    """`not_satisfied` без породы — это «что-то не так», а не находка."""

    def test_absent_values_are_named_one_by_one(self):
        params = [{"param": n,
                   "outcome": ABSENT if n in ("cooldown", "decision expiry") else BINDING,
                   "detail": ""} for n in REAL.OWNER_PARAMS]
        v, d = self.ask(_door(code=1, report=_report(params=params)))
        self.assertEqual(v, ca.NOT_SATISFIED)
        self.assertIn("cooldown", d)
        self.assertIn("decision expiry", d)

    def test_a_hardcoded_threshold_is_named_as_hardcoded_not_as_absent(self):
        params = [{"param": n,
                   "outcome": LITERAL if n == "minimum confidence" else BINDING,
                   "detail": ""} for n in REAL.OWNER_PARAMS]
        v, d = self.ask(_door(code=1, report=_report(params=params)))
        self.assertEqual(v, ca.NOT_SATISFIED)
        self.assertIn("minimum confidence", d)
        self.assertIn("зашит", d)

    def test_an_inert_policy_field_is_named_as_inert(self):
        params = [{"param": n,
                   "outcome": INERT if n == "minimum net gain" else BINDING,
                   "detail": ""} for n in REAL.OWNER_PARAMS]
        v, d = self.ask(_door(code=1, report=_report(params=params)))
        self.assertEqual(v, ca.NOT_SATISFIED)
        self.assertIn("ничего не двигает", d)

    def test_a_permitted_swing_is_named_even_when_all_nine_values_bind(self):
        # Ровно сегодняшняя форма находки прибора на `main`: девять величин могут
        # связывать, а книга всё равно возвращается туда, откуда ушла.
        reach = {"tact": {"kind": "unreachable_by_construction"},
                 "economics": {"two_step": {"kind": "permitted", "decision": "ACT"},
                               "three_step": {"kind": "refused", "decision": "HOLD"}},
                 "damper": {"kind": "refused_by_anti_churn"}}
        v, d = self.ask(_door(code=1, report=_report(reach=reach)))
        self.assertEqual(v, ca.NOT_SATISFIED)
        self.assertIn("качел", d)
        self.assertIn("two_step", d)
        self.assertNotIn("three_step", d,
                         "отказанный шаг качелей находкой не является")


class TheThirdOutcomeNamesItsReason(_Scene):
    """«Не измерено» без причины неотличимо от «измерено и чисто»."""

    def test_a_failed_positive_control_of_the_door_is_named(self):
        v, d = self.ask(_door(code=2, report=_report(
            control=False, control_why="здоровая сцена не воспроизвелась")))
        self.assertEqual(v, ca.UNMEASURED)
        self.assertIn("здоровая сцена не воспроизвелась", d)

    def test_an_unmeasured_value_is_named_by_name(self):
        params = [{"param": n,
                   "outcome": UNMEAS if n == "minimum persistence" else BINDING,
                   "detail": ""} for n in REAL.OWNER_PARAMS]
        v, d = self.ask(_door(code=2, report=_report(params=params)))
        self.assertEqual(v, ca.UNMEASURED)
        self.assertIn("minimum persistence", d)

    def test_an_unmeasured_swing_leg_is_named_by_leg(self):
        reach = {"tact": {"kind": "unreachable_by_construction"},
                 "economics": {"kind": UNMEAS, "why": "дверь цены не собралась"},
                 "damper": {"kind": "refused_by_anti_churn"}}
        v, d = self.ask(_door(code=2, report=_report(reach=reach)))
        self.assertEqual(v, ca.UNMEASURED)
        self.assertIn("economics", d)
        self.assertIn("дверь цены не собралась", d)

    def test_a_vocabulary_drift_of_the_owners_words_is_named(self):
        v, d = self.ask(_door(code=2, report=_report(vocab=["minimum persistance"])))
        self.assertEqual(v, ca.UNMEASURED)
        self.assertIn("minimum persistance", d)


class TheBrokenDoorIsUnmeasuredNotAFinding(_Scene):
    """Сломанный прибор не есть находка о системе — и тем более не разрешение закрыть."""

    def test_a_missing_prober_is_unmeasured(self):
        def boom(name):
            raise ModuleNotFoundError(f"No module named {name!r}")
        with mock.patch("importlib.import_module", side_effect=boom):
            v, d = ca.run_probe(PROBE)
        self.assertEqual(v, ca.UNMEASURED)
        self.assertIn("не ввозится", d)

    def test_a_prober_without_the_census_door_is_named_as_doorless_not_as_crashed(self):
        # РАЗЛИЧАЮЩАЯ половина сцены (мутация M05 выжила без неё): со снятой
        # проверкой наличия дверей отсутствующая `census` всё равно даёт
        # «не измерено» — но ПО ИСКЛЮЧЕНИЮ, и в тексте `AttributeError` слово
        # «census» тоже есть. «Не измерено» мало: сцена требует НАЗВАННУЮ причину.
        v, d = self.ask(_door(code=0, drop=("census",)))
        self.assertEqual(v, ca.UNMEASURED)
        self.assertIn("не несёт двери", d)
        self.assertIn("census", d)
        self.assertNotIn("упал", d,
                         "наличие двери обязана проверить проба, а не исключение")

    def test_a_prober_without_the_verdict_door_is_named_as_doorless_not_as_crashed(self):
        v, d = self.ask(_door(drop=("verdict_code",)))
        self.assertEqual(v, ca.UNMEASURED)
        self.assertIn("не несёт двери", d)
        self.assertIn("verdict_code", d)
        self.assertNotIn("упал", d)

    def test_a_raising_census_is_unmeasured(self):
        def boom(root=None):
            raise RuntimeError("сцена качелей не построилась")
        v, d = self.ask(_door(code=0, census=boom))
        self.assertEqual(v, ca.UNMEASURED)
        self.assertIn("сцена качелей не построилась", d)

    def test_a_raising_verdict_door_is_unmeasured(self):
        def boom(rep):
            raise ValueError("шкала разъехалась")
        v, d = self.ask(_door(verdict_code=boom))
        self.assertEqual(v, ca.UNMEASURED)
        self.assertIn("шкала разъехалась", d)

    def test_a_report_that_is_not_a_mapping_is_unmeasured_with_its_own_reason(self):
        # Падение на `report.get` дало бы «не измерено» ТОЖЕ, поэтому слова «list»
        # мало: сцена требует НАЗВАННУЮ причину, иначе она зелена при снятой проверке.
        v, d = self.ask(_door(code=0, census=lambda root=None: ["не отчёт"]))
        self.assertEqual(v, ca.UNMEASURED)
        self.assertIn("а не отчёт", d)
        self.assertNotIn("проба упала", d,
                         "форму отчёта обязана проверить проба, а не исключение")


class TheProberIsAskedWhatItClaimsToMeasure(_Scene):
    """Имя модуля предмета не называет: прибор под чужой секцией = «не измерено»."""

    def test_a_prober_about_another_section_cannot_measure_this_criterion(self):
        v, d = self.ask(_door(code=0, report=_report(
            section="§41 Auto-execution limits")))
        self.assertEqual(v, ca.UNMEASURED,
                         "чужой предмет обязан дать третий исход, а не вердикт")
        self.assertIn("§41", d)

    def test_a_prober_that_declares_no_section_cannot_measure_it_either(self):
        rep = _report()
        rep.pop("section")
        v, _ = self.ask(_door(code=0, report=rep))
        self.assertEqual(v, ca.UNMEASURED)

    def test_the_section_the_probe_demands_is_the_one_the_real_prober_declares(self):
        # Сторож самой сверки: разойдись константа пробы с объявлением прибора —
        # проба отвечала бы «не измерено» на ЦЕЛОМ контуре, то есть тихо умерла бы.
        self.assertEqual(ca.ANTI_CHURN_SECTION, REAL.census()["section"])


class TheRealProberIsActuallyWired(unittest.TestCase):
    """Без этого теста батарея говорила бы только о заглушках (урок #1217)."""

    def test_the_probe_carries_the_real_prober_verdict_and_both_agree(self):
        report = REAL.census()
        code = REAL.verdict_code(report)
        verdict, detail = ca.run_probe(PROBE)
        expected = {0: ca.SATISFIED, 1: ca.NOT_SATISFIED, 2: ca.UNMEASURED}[code]
        self.assertEqual(verdict, expected,
                         f"прибор отдал код {code}, проба сказала {verdict!r}")
        self.assertTrue(detail.strip(), "вердикт без пояснения перемерить нечем")
        # Пояснение несёт ЧИСЛО владельца, а не только слова.
        self.assertIn(str(REAL.OWNER_PARAMS_DECLARED), detail)

    def test_the_real_prober_writes_nothing_while_the_probe_runs(self):
        # Прибор объявлен читающим; проба зовёт его на КАЖДОМ прогоне сводки, и
        # запись здесь была бы записью в живое состояние из читающего шага. Имён
        # мало: файл может быть ПЕРЕПИСАН без смены имени, поэтому снимок несёт
        # размер и отметку времени.
        import os
        data = os.path.join(ca.REPO_ROOT, "data")

        def snapshot():
            if not os.path.isdir(data):
                return None
            out = {}
            for name in sorted(os.listdir(data)):
                try:
                    st = os.stat(os.path.join(data, name))
                except OSError:
                    out[name] = "НЕ ИЗМЕРЕНО"
                    continue
                out[name] = (st.st_size, st.st_mtime_ns)
            return out

        before = snapshot()
        ca.run_probe(PROBE)
        self.assertEqual(before, snapshot())



class TheDoorsWindowDoesNotLeakIntoTheSummary(_Scene):
    """Звено сторожится дверью, которая ПЕЧАТАЕТ — иначе сцена зелена по построению.

    Замер 28.11: настоящий прибор §22 печатает в `stdout` **0** символов и в
    `stderr` **1411** (голос RiskPolicy из его сцен). Значит сцена на НАСТОЯЩЕЙ
    двери сказала бы «не течёт» и при СНЯТОМ глушителе — ровно так и выжила
    мутация M20 прогона 1. Поэтому дверь сцены говорит в `stdout` нарочно:
    глушитель есть страховка от печати, и проверять его надо на печати.
    """

    def test_a_door_that_prints_does_not_reach_stdout_through_the_probe(self):
        import contextlib
        import io

        def loud(root=None):
            print("окно прибора: девять величин, качели, полоса выигрыша")
            return _report()

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            verdict, _ = self.ask(_door(code=1, census=loud))
        self.assertEqual(verdict, ca.NOT_SATISFIED, "вердикт обязан дойти")
        self.assertEqual(out.getvalue(), "",
                         "печать прибора протекла в столбцы сводки §50")

    def test_the_probe_does_not_swallow_the_risk_engines_voice_on_stderr(self):
        # Обратная половина: глушить stderr значило бы спрятать настоящий отказ
        # RiskPolicy ради опрятного вывода. Сцена требует, чтобы он ПРОШЁЛ.
        import contextlib
        import io
        import sys

        def loud(root=None):
            sys.stderr.write("Risk check REJECTED: new_position(aave_v3)\n")
            return _report()

        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.ask(_door(code=1, census=loud))
        self.assertIn("Risk check REJECTED", err.getvalue())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
