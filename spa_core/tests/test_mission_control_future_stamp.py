"""Отметка наблюдения ВПЕРЁД судящих часов — третий исход, а не «свежо» (ADR-1078, инв. #17).

Предмет. `mission_control._meta()` понижает состояние до `STALE`, когда возраст
наблюдения БОЛЬШЕ порога: `age > stale_after_min`. На ОТРИЦАТЕЛЬНОМ возрасте это
сравнение ложно ВСЕГДА, то есть наблюдение, помеченное вперёд относительно часов,
читается как свежее — и чем грубее расхождение, тем надёжнее оно выглядит свежим.
Замер цикла #1223: `state=HEALTHY · colour=neutral-ok · age_min=-89119.5 ·
stale_after_min=1560`, то есть 61,9 суток «в будущем» при пороге 26 часов.

Население ИЗМЕРЕНО до правки (цикл #1231, живое прод-`data/`): из 24 секций
объявленной формы отрицательный возраст несли **4** в одной сборке из четырёх
наблюдённых (`studio`, `studio.board`, `decisions`, `release_feed` — все −0.4 мин,
отметка зеркала прочитана ПОСЛЕ фиксации `now`) и **0** в трёх остальных. Класс
живой и перемежающийся; прибор — `scripts/future_dated_observation_census.py`.

Отсюда форма правки: допуск. Все наблюдённые отрицательные возрасты лежат внутри
`FUTURE_SKEW_MINUTES`, поэтому понижать их значило бы красить окно чтения сборки —
та же ошибка в другую сторону, и ровно её ADR-612/ADR-763 уже закрыли для
`readiness_scopes`/`company_truth`. Поэтому ниже проверяются ОБА направления: и
что далёкое будущее больше не читается как свежесть, и что близкое будущее
по-прежнему свежесть.

Время здесь — ВХОД, а не окружение (`.claude/rules/deployment.md` § «Время в
тестах»): `now` и отметка задаются обе, стенных часов в файле нет ни одной.
"""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from spa_core.studio_os import mission_control as mc
from spa_core.studio_os import readiness_scopes as rs

# FROZEN-DATE-OK: injected-clock — NOW ниже есть якорь СЦЕНЫ, и обе стороны
# сравнения происходят от него: отметка наблюдения считается как `NOW - delta`,
# а судящий момент передаётся `_meta(..., now=NOW)` аргументом. Стенных часов в
# файле нет ни одной двери, поэтому календарь сдвинуть вердикт не способен —
# ровно приём №1 из `.claude/rules/deployment.md` § «Время в тестах».
NOW = datetime(2026, 11, 24, 12, 0, 0, tzinfo=timezone.utc)
CONTRACT = 90.0


def meta(delta_min: float, *, state: str = "HEALTHY",
         contract: float | None = CONTRACT) -> dict:
    """Конверт для отметки, стоящей на `delta_min` минут ПОЗАДИ `NOW`.

    Отрицательный `delta_min` ставит отметку ВПЕРЁД часов — ровно предмет файла.
    """
    return mc._meta(state, ["сцена"], NOW - timedelta(minutes=delta_min), NOW, contract)


class TheToleranceHasOneHome(unittest.TestCase):
    """Число допуска не назначается заново: панель и области читают ОДНО значение."""

    def test_the_panel_reuses_the_scopes_constant(self):
        self.assertIs(mc.FUTURE_SKEW_MINUTES, rs.FUTURE_SKEW_MINUTES)

    def test_the_tolerance_is_a_positive_number_of_minutes(self):
        self.assertIsInstance(mc.FUTURE_SKEW_MINUTES, (int, float))
        self.assertGreater(mc.FUTURE_SKEW_MINUTES, 0)


class ThreeOutcomesAreDistinguishable(unittest.TestCase):
    """Свежо · протухло · отметка впереди часов — три РАЗНЫХ значения (инв. #17)."""

    def test_a_stamp_behind_the_clock_within_the_contract_is_left_alone(self):
        got = meta(5)
        self.assertEqual(got["state"], "HEALTHY")
        self.assertEqual(got["age_min"], 5.0)

    def test_a_stamp_behind_the_clock_past_the_contract_is_stale(self):
        got = meta(CONTRACT + 5)
        self.assertEqual(got["state"], "STALE")
        self.assertIn("contract", got["reason"])

    def test_a_stamp_far_ahead_of_the_clock_is_not_measured(self):
        got = meta(-(mc.FUTURE_SKEW_MINUTES + 5))
        self.assertEqual(got["state"], "NOT_MEASURED",
                         "порог на отрицательном возрасте не срабатывает никогда — "
                         "состояние обязано стать третьим, а не остаться свежим")
        self.assertEqual(got["colour"], "unknown")

    def test_the_third_outcome_names_its_reason(self):
        # «Не измерено» без причины неотличимо от «протухло»: читатель панели
        # видит серую плашку и не узнаёт, что дело в часах, а не в давности.
        got = meta(-(mc.FUTURE_SKEW_MINUTES + 5))
        self.assertTrue(got["reason"])
        self.assertIn("AHEAD", got["reason"])

    def test_the_three_outcomes_are_three_different_values(self):
        states = {meta(5)["state"], meta(CONTRACT + 5)["state"],
                  meta(-(mc.FUTURE_SKEW_MINUTES + 5))["state"]}
        self.assertEqual(len(states), 3, f"исходы слиплись: {sorted(states)}")


class TheBuildReadWindowIsNotPainted(unittest.TestCase):
    """Обратная половина контроля: близкое будущее — по-прежнему свежесть.

    `now` фиксируется в начале сборки, а источники читаются секундами позже;
    отметка зеркала так и обогнала часы на 0.4 мин у 4 секций из 24 на живом
    прод-дереве. Понизить их значило бы заменить одну неправду другой.
    """

    def test_a_stamp_just_ahead_of_the_clock_stays_fresh(self):
        got = meta(-0.4)
        self.assertEqual(got["state"], "HEALTHY")
        self.assertEqual(got["age_min"], -0.4, "возраст остаётся КАК ИЗМЕРЕН, "
                                               "зажимать его в ноль значило бы спрятать расхождение")

    def test_the_whole_tolerance_window_stays_fresh(self):
        for ahead in (0.1, mc.FUTURE_SKEW_MINUTES / 2, mc.FUTURE_SKEW_MINUTES):
            with self.subTest(ahead=ahead):
                self.assertEqual(meta(-ahead)["state"], "HEALTHY")

    def test_the_boundary_is_exclusive_on_the_tolerance(self):
        # Ровно допуск — ещё свежесть; на волосок дальше — уже третий исход.
        self.assertEqual(meta(-mc.FUTURE_SKEW_MINUTES)["state"], "HEALTHY")
        self.assertEqual(meta(-(mc.FUTURE_SKEW_MINUTES + 0.1))["state"], "NOT_MEASURED")


class TheThirdOutcomeDoesNotOverrideWhatIsAlreadyWorse(unittest.TestCase):
    """`CRITICAL` и `NOT_MEASURED` правка не трогает — иначе авария стала бы незнанием."""

    def test_a_critical_section_stays_critical_even_with_a_future_stamp(self):
        got = meta(-(mc.FUTURE_SKEW_MINUTES + 500), state="CRITICAL")
        self.assertEqual(got["state"], "CRITICAL")

    def test_an_unmeasured_section_stays_unmeasured(self):
        got = meta(-(mc.FUTURE_SKEW_MINUTES + 500), state="NOT_MEASURED")
        self.assertEqual(got["state"], "NOT_MEASURED")


class TheQuestionIsAskedWithoutAFreshnessContract(unittest.TestCase):
    """Отметка из будущего — аномалия сама по себе, а не нарушение срока.

    Секция без порога свежести (`stale_after_min=None`) до правки была
    НЕМА: единственный понижающий путь шёл через порог, которого у неё нет,
    поэтому любая отметка, включая отметку на 62 суток вперёд, читалась как
    свежая. Цена этой ветки на живом дереве ИЗМЕРЕНА и равна нулю: среди 24
    секций ни одна беспороговая не стои́т впереди часов дальше допуска.
    """

    def test_a_future_stamp_without_a_contract_is_not_measured(self):
        got = meta(-(mc.FUTURE_SKEW_MINUTES + 5), contract=None)
        self.assertEqual(got["state"], "NOT_MEASURED")

    def test_an_old_stamp_without_a_contract_is_still_left_alone(self):
        # Обратная половина: без порога «давно» по-прежнему НЕ повод понижать —
        # правка добавляет исход, а не выдумывает контракт.
        got = meta(10_000, contract=None)
        self.assertEqual(got["state"], "HEALTHY")


class TheCensusAnswersAboutTheNamedTree(unittest.TestCase):
    """Прибор населения: дерево — ВХОД, и три исхода у него различимы."""

    def setUp(self):
        import importlib.util
        import sys
        path = (mc.REPO / "scripts" / "future_dated_observation_census.py")
        self.assertTrue(path.exists(), f"прибора нет по пути {path}")
        spec = importlib.util.spec_from_file_location("_fdo_census_test", path)
        self.mod = importlib.util.module_from_spec(spec)
        sys.modules["_fdo_census_test"] = self.mod
        try:
            spec.loader.exec_module(self.mod)
        finally:
            sys.modules.pop("_fdo_census_test", None)

    def test_the_tolerance_is_read_from_the_same_home(self):
        self.assertEqual(self.mod.FUTURE_SKEW_MINUTES, rs.FUTURE_SKEW_MINUTES)

    def test_a_stamp_behind_the_clock_is_not_a_finding(self):
        self.assertEqual(self.mod.classify(5.0, 10.0), self.mod.BEHIND)

    def test_a_stamp_just_ahead_is_measured_and_named_but_not_a_finding(self):
        # Род печатается именно затем, чтобы «такого нет» отличалось от «не смотрели».
        self.assertEqual(self.mod.classify(-0.4, 10.0), self.mod.AHEAD_WITHIN)

    def test_a_stamp_far_ahead_is_the_finding(self):
        self.assertEqual(self.mod.classify(-10.1, 10.0), self.mod.AHEAD_BEYOND)

    def test_a_missing_stamp_is_its_own_kind_not_a_zero_age(self):
        self.assertEqual(self.mod.classify(None, 10.0), self.mod.NO_STAMP)

    def test_the_four_kinds_are_four_different_values(self):
        kinds = {self.mod.classify(v, 10.0) for v in (5.0, -0.4, -10.1, None)}
        self.assertEqual(len(kinds), 4, f"рода слиплись: {sorted(kinds)}")

    def test_an_empty_model_is_unmeasured_not_clean(self):
        # Ноль секций НЕ выдаётся за «чисто»: перепись, не нашедшей поверхности,
        # положено отвечать о СВОЕЙ немочи (инв. #17).
        self.assertEqual(self.mod.sections({"a": {"b": 1}}), [])

    def test_sections_are_found_by_the_declared_shape(self):
        model = {"one": {"_meta": {"state": "HEALTHY", "age_min": -0.4}},
                 "two": {"_meta": {"state": "HEALTHY"}},          # без возраста — вне населения
                 "three": [{"_meta": {"state": "STALE", "age_min": 99.0}}]}
        found = {row["path"]: row["age_min"] for row in self.mod.sections(model)}
        self.assertEqual(found, {"one": -0.4, "three[0]": 99.0})


class TheProbeMeasuresTheOutcome(unittest.TestCase):
    """Проба приёмки карточки зелена на целом контуре и красна на каждом порванном звене."""

    def setUp(self):
        from spa_core.monitoring import card_acceptance as ca
        self.ca = ca
        self.probe = ca.PROBES["meta_distinguishes_a_stamp_from_the_future"]

    def test_the_probe_is_registered(self):
        self.assertIn("meta_distinguishes_a_stamp_from_the_future", self.ca.PROBES)

    def test_the_probe_is_satisfied_on_the_whole_contour(self):
        verdict, detail = self.probe()
        self.assertEqual(verdict, self.ca.SATISFIED, detail)

    def test_a_missing_module_is_unmeasured_with_a_named_reason(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            verdict, detail = self.probe(repo_root=tmp)
            self.assertEqual(verdict, self.ca.UNMEASURED, detail)
            self.assertIn("модуля нет", detail)

    def _tree_with(self, module_text: str):
        """Одноразовое дерево: названный текст модуля + прибор населения на месте."""
        import pathlib as _pl
        import shutil
        import tempfile
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        dst = _pl.Path(tmp)
        (dst / "spa_core" / "studio_os").mkdir(parents=True)
        (dst / "scripts").mkdir(parents=True)
        (dst / "spa_core" / "studio_os" / "mission_control.py").write_text(module_text, encoding="utf-8")
        shutil.copy(mc.REPO / "scripts" / "future_dated_observation_census.py",
                    dst / "scripts" / "future_dated_observation_census.py")
        return dst

    def _module_text(self) -> str:
        return (mc.REPO / "spa_core" / "studio_os" / "mission_control.py").read_text(encoding="utf-8")

    #: Якорь ветки будущего. Если он перестанет находиться — три контроля ниже
    #: падают ГРОМКО, а не зеленеют на дереве, которого не поняли.
    FUTURE_BRANCH = "and age is not None and -age > FUTURE_SKEW_MINUTES"
    REASON_LINE = 'reason = (f"observation stamped {-age} min AHEAD of the judging clock "'

    def test_the_probe_is_red_when_the_future_branch_is_torn_out(self):
        """Порванное звено — КРАСНО, а не «не измерено» и не «выполнено».

        Без этого контроля проба была бы украшением: она зеленела бы и на
        дереве, где третьего исхода нет вовсе (`.claude/rules/acceptance.md`, п. 3).
        """
        text = self._module_text()
        torn = text.replace(self.FUTURE_BRANCH, "and age is not None and False")
        self.assertNotEqual(torn, text, "якорь ветки будущего не найден — мерка смотрит не туда")
        verdict, detail = self.probe(repo_root=str(self._tree_with(torn)))
        self.assertEqual(verdict, self.ca.NOT_SATISFIED, detail)
        self.assertIn("не срабатывает никогда", detail)

    def test_the_probe_is_red_when_the_tolerance_window_is_painted(self):
        """Обратное порванное звено: правка, красящая окно чтения сборки, тоже КРАСНА."""
        text = self._module_text()
        painted = text.replace(self.FUTURE_BRANCH, "and age is not None and age < 0")
        self.assertNotEqual(painted, text, "якорь ветки будущего не найден — мерка смотрит не туда")
        verdict, detail = self.probe(repo_root=str(self._tree_with(painted)))
        self.assertEqual(verdict, self.ca.NOT_SATISFIED, detail)
        self.assertIn("окно чтения сборки покрашено", detail)

    def test_the_probe_is_red_when_the_third_outcome_has_no_reason(self):
        """«Не измерено» без причины неотличимо от «протухло» — тоже порванное звено."""
        text = self._module_text()
        self.assertIn(self.REASON_LINE, text, "якорь причины не найден — мерка смотрит не туда")
        head, _, tail = text.partition(self.REASON_LINE)
        # срезаем ОБЕ строки f-выражения причины и ставим молчание
        tail = tail.split("\n", 2)[2]
        verdict, detail = self.probe(repo_root=str(self._tree_with(head + "reason = None\n" + tail)))
        self.assertEqual(verdict, self.ca.NOT_SATISFIED, detail)
        self.assertIn("ПРИЧИНА не названа", detail)

    def test_a_module_without_the_tolerance_is_unmeasured_not_satisfied(self):
        """Дыра покрытия, найденная мутацией M16 цикла #1231 — записана, а не замазана.

        Ни одна сцена не подавала пробе модуль БЕЗ объявленного допуска, поэтому
        снятие этой проверки набор упавших имён не меняло: проба выдала бы
        «НЕ ИЗМЕРЕНО» за ответ. Базовый замер карточки был ровно этим исходом,
        то есть ветка живая и достижимая, а не теоретическая.
        """
        text = self._module_text()
        line = "from spa_core.studio_os.readiness_scopes import FUTURE_SKEW_MINUTES"
        self.assertIn(line, text, "якорь ввоза допуска не найден — мерка смотрит не туда")
        without = text.replace(line, "# допуск снят сценой")
        verdict, detail = self.probe(repo_root=str(self._tree_with(without)))
        self.assertEqual(verdict, self.ca.UNMEASURED, detail)
        self.assertIn("FUTURE_SKEW_MINUTES", detail)

    def test_a_missing_census_is_unmeasured_not_satisfied(self):
        # Порядок карточки — «сперва население, потом правка»; проба, зелёная без
        # прибора населения, зачла бы правку, цена которой не измерена.
        import shutil
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = mc.REPO
            dst = __import__("pathlib").Path(tmp)
            (dst / "spa_core" / "studio_os").mkdir(parents=True)
            shutil.copy(root / "spa_core" / "studio_os" / "mission_control.py",
                        dst / "spa_core" / "studio_os" / "mission_control.py")
            verdict, detail = self.probe(repo_root=str(dst))
            self.assertEqual(verdict, self.ca.UNMEASURED, detail)
            self.assertIn("переписи населения нет", detail)


if __name__ == "__main__":
    unittest.main()
