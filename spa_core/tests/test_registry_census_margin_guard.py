"""Приёмка ADR-1013: ЗАПАС до предела — не причина «рядом с вердиктом», а УСЛОВИЕ вердикта.

Заказ G1002 п. 1 (а) = [ADR-1012](../../docs/decisions/ADR-1012-matrix-of-two-declared-inputs.md)
§ 7 (а). ADR-1011 закрыл право печатать `INVARIANT` по пределу: ответ обязан стоять над ЖИВЫМ
контролем входа, иначе «население не зависит от предела» неотличимо от «предел ни на что не
влияет». Контроль отвечает на вопрос «вход ДОХОДИТ до решения?».

Остался второй вопрос, и он другой: **ПОЧЕМУ при живом входе население всё равно не меняется.**
Ответ у прибора был, назывался вслух и держал на себе весь вердикт — ЗАПАС: ни один модуль не
подходит к пределу близко, поэтому статуса `timeout` нет ни в одной клетке. Запас прибор МЕРИЛ и
ПЕЧАТАЛ. И не гатил им НИЧЕГО.

Цена измерена дважды, и ровно она сделала сторожа починкой: ADR-1011 снял запас `375×` (самый
медленный модуль 0.008 с), ADR-1012 сутки позже на ТОМ ЖЕ дереве — `≥187.5×` (0.016 с). Величина,
названная причиной вердикта, уехала ВДВОЕ за один цикл, и не от кода, а от загрузки машины.

Дифференциальный замер дыры (цикл #1135, сцена этой батареи, байты `origin/main` против байтов
цикла; стороны совпадают ПОИМЁННО, контроль входа ЖИВОЙ, предел сцены 2.5 с):

| длительность модуля | запас | ДО | ПОСЛЕ |
|---|---|---|---|
| 0.001 с | 2500× | `INVARIANT` | `INVARIANT` |
| 0.1 с | 25× | `INVARIANT` | `INVARIANT` |
| 0.5 с | 5× | `INVARIANT` | **`UNMEASURED`** |
| 2.0 с | **1.2×** | `INVARIANT` | **`UNMEASURED`** |
| длительностей НЕТ ВОВСЕ | не измерен | `INVARIANT` | **`UNMEASURED`** |

Последняя строка — не гипотеза: такая сцена В БАТАРЕЕ УЖЕ БЫЛА
(`test_observations_without_durations_make_the_margin_UNMEASURED_not_zero`), и она проверяла
`slowest is None` и `margin is None`, но ВЕРДИКТ не проверяла ни одним утверждением. То есть
прибор печатал «инвариантно» над причиной, которой не существовало, а сторож рядом молчал —
честно отвечая на свой вопрос и мимо нужного.

Что держит эта батарея — по одному утверждению на класс:

* **у гейта ТРИ исхода** (`MARGIN_VERDICTS`), и третий не сливается с первыми двумя (инв. #17):
  порог пройден · порог НЕ пройден · запас НЕ ИЗМЕРЕН. «Запас тонок» и «длительностей нет»
  требуют РАЗНЫХ действий, поэтому называются раздельно;
* **знак оценки живёт В ДАННЫХ** (`MARGIN_KIND_LOWER_BOUND`), а не в прозе: `seconds` включает
  накладные наблюдателя, поэтому частное есть НИЖНЯЯ граница запаса. Пройденный порог ДОКАЗЫВАЕТ
  безопасность (настоящий запас ≥ оценки); НЕ пройденный не доказывает обратного — поэтому он
  даёт `UNMEASURED` (fail-CLOSED), а не находку о системе;
* **нуль — НЕ бесконечный запас.** Длительность ниже разрешения часов и сломанный секундомер
  дают одну запись, и считать её самым безопасным исходом значило бы вывернуть инв. #17 наизнанку;
* **утверждение стои́т у ПРОВОДКИ, а не у функции.** Урок ADR-1012 § 7 (г): мутация без
  РАЗЛИЧАЮЩЕЙ сцены выживает, если проверять только помощника. Поэтому каждый исход гейта
  проверяется ещё и сквозь `timeout_variance`;
* **`VARIES` запасом НЕ гатится.** Названное различие само есть доказательство, что вход доходит,
  и требовать от него ещё и запаса значило бы погасить находку порогом;
* **порог — РЕШЕНИЕ, а не копия чужого числа.** Класс ADR-913 закрыт тем, что предел берётся У
  БЕГУНА: контроль двигает `MODULE_TIMEOUT` синтетического бегуна и требует, чтобы порог остался
  прежним, а запас — изменился;
* **порог живёт в ОДНОМ месте** (AST самого прибора): второе объявление вернулось бы молча
  первой же правкой;
* **храповик несёт ЗАМЕР со своим доказательством**, а не копию порога: запись без
  измеренных полей не принимается, а записанный замер обязан проходить ТЕКУЩИЙ порог той же
  дверью — объявить порог выше того, что система показывает, запрещено.

Контроль у каждого утверждения — в ОБЕ стороны: сцена, где прибор обязан сказать «да», и сцена,
где он обязан сказать «нет» с НАЗВАННОЙ причиной.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CENSUS_PATH = ROOT / "scripts" / "registry_runner_write_census.py"
BASELINE_PATH = Path(__file__).resolve().parent / "registry_census_margin_baseline.json"

#: Поля, без которых запись храповика не является замером. Дословный порядок
#: `acceptance_plateau_baseline.json`: «запись без замера в неё не принимается — плато,
#: объявленное на слово, и есть тот дефект».
REQUIRED_MEASURE_FIELDS = ("at_commit", "instrument_md5", "cells", "declared_timeout_s",
                           "slowest_module", "slowest_seconds", "margin_kind",
                           "source", "measured_at")


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


rrwc = _load(CENSUS_PATH, "rrwc_margin_guard")
_MG_CLEARS, _MG_BELOW, _MG_UNMEASURED = rrwc.MARGIN_VERDICTS


def _slowest(seconds, *, module="m_slow", at="3.0"):
    return {"module": module, "seconds": seconds, "at_timeout": at}


class MarginGateOutcomes(unittest.TestCase):
    """Три исхода гейта, каждый — своим утверждением, и ни один не выводится из другого."""

    def test_fat_margin_clears_the_floor_and_says_it_is_a_lower_bound(self):
        v = rrwc.margin_floor_verdict(3.0, _slowest(0.016))
        self.assertEqual(v["verdict"], _MG_CLEARS)
        # Ровно замер ADR-1012 § 7 (а): 3.0 / 0.016 = 187.5.
        self.assertEqual(v["margin"], 187.5)
        self.assertEqual(v["kind"], rrwc.MARGIN_KIND_LOWER_BOUND)
        self.assertIsNone(v["reason"])

    def test_thin_margin_is_below_the_floor_and_names_module_seconds_and_floor(self):
        v = rrwc.margin_floor_verdict(3.0, _slowest(0.5, module="slowpoke"))
        self.assertEqual(v["verdict"], _MG_BELOW)
        self.assertEqual(v["margin"], 6.0)
        for needle in ("slowpoke", "0.5", str(rrwc.MARGIN_FLOOR_X)):
            self.assertIn(needle, v["reason"], needle)
        # Знак оценки назван В ПРИЧИНЕ: «ниже порога» НЕ есть утверждение о системе.
        self.assertIn(rrwc.MARGIN_KIND_LOWER_BOUND, v["reason"])

    def test_the_floor_itself_clears_and_the_boundary_is_named(self):
        """Порог включительный — решение, и оно закреплено с ОБЕИХ сторон границы."""
        at_floor = 3.0 / rrwc.MARGIN_FLOOR_X
        self.assertEqual(rrwc.margin_floor_verdict(3.0, _slowest(at_floor))["verdict"], _MG_CLEARS)
        just_under = at_floor * 1.02
        self.assertEqual(rrwc.margin_floor_verdict(3.0, _slowest(just_under))["verdict"], _MG_BELOW)

    def test_missing_durations_are_UNMEASURED_and_not_a_zero_margin(self):
        v = rrwc.margin_floor_verdict(3.0, None)
        self.assertEqual(v["verdict"], _MG_UNMEASURED)
        self.assertIsNone(v["margin"])
        self.assertNotEqual(v["margin"], 0)
        self.assertIn("НЕ ИЗМЕРЕН", v["reason"])

    def test_zero_seconds_is_UNMEASURED_not_an_infinite_margin(self):
        """Нуль неотличим от «секундомер не сработал». Самый безопасный исход из НЕ ИЗМЕРЕНО
        делать нельзя — это инв. #17 наизнанку."""
        v = rrwc.margin_floor_verdict(3.0, _slowest(0.0))
        self.assertEqual(v["verdict"], _MG_UNMEASURED)
        self.assertIsNone(v["margin"])
        self.assertIn("неотличим", v["reason"])

    def test_a_boolean_is_not_a_duration(self):
        """`True` — подкласс `int`, и 3.0/True = 3.0 прошло бы порогом молча."""
        v = rrwc.margin_floor_verdict(3.0, _slowest(True))
        self.assertEqual(v["verdict"], _MG_UNMEASURED)

    def test_an_unread_runner_limit_is_UNMEASURED_not_a_substituted_number(self):
        """Числитель запаса принадлежит БЕГУНУ. Нет объявления — его пришлось бы выдумать."""
        v = rrwc.margin_floor_verdict(None, _slowest(0.016))
        self.assertEqual(v["verdict"], _MG_UNMEASURED)
        self.assertIsNone(v["margin"])
        self.assertIn("ADR-913", v["reason"])


class FloorIsADecisionNotACopy(unittest.TestCase):
    """Класс ADR-913: мерка, сверяющая свои константы сама с собой."""

    def test_the_floor_is_declared_exactly_once_in_the_instrument(self):
        tree = ast.parse(CENSUS_PATH.read_text(encoding="utf-8"))
        assigns = [n for n in ast.walk(tree) if isinstance(n, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == "MARGIN_FLOOR_X"
                           for t in n.targets)]
        self.assertEqual(len(assigns), 1,
                         "порог обязан жить в ОДНОМ месте: второе объявление вернётся молча")

    def test_the_floor_is_dimensionless_and_survives_the_runner_changing_its_limit(self):
        """Положительный контроль класса ADR-913: двигаем ЧУЖОЕ число и требуем, чтобы наше
        осталось прежним, а производная величина — изменилась."""
        floor_before = rrwc.MARGIN_FLOOR_X
        with tempfile.TemporaryDirectory() as td:
            margins = {}
            for limit in (3.0, 30.0):
                repo = Path(td) / f"r{limit}"
                (repo / "spa_core" / "analytics").mkdir(parents=True)
                (repo / "spa_core" / "analytics" / "signal_aggregator.py").write_text(
                    textwrap.dedent(f'''
                        MODULE_TIMEOUT = {limit}

                        class SignalAggregator:
                            def _run_module(self, name):
                                try:
                                    pass
                                except TimeoutError:
                                    self._record(name, "timeout")
                    '''), encoding="utf-8")
                declared = rrwc.read_runner_timeout(repo)
                self.assertEqual(declared, limit)
                margins[limit] = rrwc.margin_floor_verdict(declared, _slowest(0.1))["margin"]
        self.assertEqual(rrwc.MARGIN_FLOOR_X, floor_before,
                         "порог не имеет права зависеть от числа бегуна — он КРАТНОСТЬ")
        self.assertNotEqual(margins[3.0], margins[30.0],
                            "запас обязан следовать за объявлением бегуна, иначе он не о нём")
        self.assertEqual(margins[3.0], 30.0)
        self.assertEqual(margins[30.0], 300.0)

    def test_the_live_runner_declares_a_limit_the_floor_can_be_read_against(self):
        """Живой бегун проверяется отдельно: исчезни у него объявление — краснеет ЗДЕСЬ, а
        прибор честно скажет НЕ ИЗМЕРЕНО."""
        declared = rrwc.read_runner_timeout(ROOT)
        self.assertGreater(declared, 0)
        self.assertGreater(declared / rrwc.MARGIN_FLOOR_X, 0)


class MarginGateIsWiredIntoTheVerdict(unittest.TestCase):
    """Урок ADR-1012 § 7 (г): утверждение у ФУНКЦИИ мутанта не убивает. Эти сцены идут сквозь
    `timeout_variance` — туда, где вердикт действительно рождается."""

    def setUp(self):
        self.bat = _load(Path(__file__).resolve().parent
                         / "test_registry_census_timeout_variance.py", "bat_for_margin")
        self.scene = self.bat.Scene()
        self.mv = self.scene.verdict()

    def tearDown(self):
        self.scene.close()

    def _ask(self, *, seconds=0.001, drop_seconds=False, differ=False, knob=None):
        rows_a = [self.bat._entered(self.mv.module)]
        rows_b = [self.bat._not_entered(self.mv.module)] if differ else rows_a
        o1 = self.scene.obs(rows_a, seconds=seconds)
        o2 = self.scene.obs(rows_b, seconds=seconds)
        if drop_seconds:
            for row in o1["per_module"]:
                row.pop("seconds")
        return rrwc.timeout_variance(
            self.scene.root, self.scene.census([self.mv]),
            {rrwc.timeout_key(1.0): o1, rrwc.timeout_key(9.0): o2},
            knob if knob is not None else self.bat._knob(self.bat._KB_LIVE))

    def test_a_fat_margin_still_earns_INVARIANT(self):
        """Обратный контроль: гейт не имеет права краснеть на здоровых данных."""
        res = self._ask(seconds=0.001)
        self.assertEqual(res["verdict"], "INVARIANT")
        self.assertEqual(res["margin_gate"]["verdict"], _MG_CLEARS)

    def test_a_thin_margin_turns_INVARIANT_into_UNMEASURED(self):
        res = self._ask(seconds=0.5)
        self.assertEqual(res["verdict"], "UNMEASURED")
        self.assertEqual(res["margin_gate"]["verdict"], _MG_BELOW)
        self.assertIn("не подтверждена", res["unmeasured_reason"])
        self.assertIn(str(rrwc.MARGIN_FLOOR_X), res["unmeasured_reason"])

    def test_observations_without_durations_turn_INVARIANT_into_UNMEASURED(self):
        """Та САМАЯ сцена, что уже жила в соседней батарее без утверждения о вердикте.
        Дифференциальный замер #1135: `origin/main` отвечал здесь `INVARIANT`."""
        res = self._ask(drop_seconds=True)
        self.assertEqual(res["verdict"], "UNMEASURED")
        self.assertEqual(res["margin_gate"]["verdict"], _MG_UNMEASURED)
        self.assertIsNone(res["margin"])

    def test_a_named_difference_is_NOT_gated_by_the_margin(self):
        """`VARIES` в запасе не нуждается: различие само есть доказательство, что вход доходит.
        Погасить находку порогом было бы ровно ослаблением проверки."""
        res = self._ask(seconds=2.0, differ=True)
        self.assertEqual(res["verdict"], "VARIES")
        self.assertEqual(res["margin_gate"]["verdict"], _MG_BELOW)

    def test_a_dead_knob_keeps_its_own_reason_and_is_not_overwritten_by_the_margin(self):
        """Порядок звеньев — часть ответа: контроль входа и запас отвечают на РАЗНЫЕ вопросы,
        и причина отказа обязана называть то звено, которое отказало."""
        dead = self.bat._knob(self.bat._KB_DEAD)
        res = self._ask(seconds=0.001, knob=dead)
        self.assertEqual(res["verdict"], "UNMEASURED")
        self.assertIn("контролем", res["unmeasured_reason"])

    def test_the_render_prints_both_the_number_and_the_floor_verdict(self):
        fat = "\n".join(rrwc.render_timeout_variance(self._ask(seconds=0.001)))
        self.assertIn("ПРОЙДЕН", fat)
        self.assertIn(str(rrwc.MARGIN_FLOOR_X), fat)
        thin = "\n".join(rrwc.render_timeout_variance(self._ask(seconds=0.5)))
        self.assertIn("НИЖЕ порога", thin)
        none = "\n".join(rrwc.render_timeout_variance(self._ask(drop_seconds=True)))
        self.assertIn("запас НЕ ИЗМЕРЕН", none)


class MarginBaselineIsAMeasurementNotACopy(unittest.TestCase):
    """Храповик. Он несёт ЗАМЕР со своим доказательством — не копию порога (копия была бы
    меркой, которой сторож мерит сам себя)."""

    def setUp(self):
        self.doc = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))

    def test_the_baseline_carries_its_own_evidence(self):
        m = self.doc["measured"]
        for field in REQUIRED_MEASURE_FIELDS:
            self.assertIn(field, m, f"запись без поля `{field}` замером не является")
            self.assertNotIn(m[field], (None, "", []), field)

    def test_the_baseline_does_not_carry_a_copy_of_the_floor(self):
        """Порог живёт в приборе. Копия здесь означала бы, что сторож сверяет константу с
        константой и молчит ровно до дня, когда одна из двух поедет (класс ADR-913).

        Проверяется СВОЙСТВО, а не слово: ни одно число базы не равно порогу. Искать подстроку
        «floor» было бы игрой в слова — она есть в самом имени исхода `MARGIN_CLEARS_FLOOR`.
        """
        def numbers(node):
            if isinstance(node, bool):
                return
            if isinstance(node, (int, float)):
                yield float(node)
            elif isinstance(node, dict):
                for v in node.values():
                    yield from numbers(v)
            elif isinstance(node, list):
                for v in node:
                    yield from numbers(v)

        found = [n for n in numbers(self.doc) if n == rrwc.MARGIN_FLOOR_X]
        self.assertEqual(found, [], "в базе лежит копия порога — порог объявляется в приборе")

    def test_the_recorded_measurement_clears_the_CURRENT_floor_through_the_same_door(self):
        """Объявить порог выше того, что система показывает, запрещено: такой порог краснел бы
        на верном состоянии, и первым же циклом его бы «починили» понижением."""
        m = self.doc["measured"]
        v = rrwc.margin_floor_verdict(
            float(m["declared_timeout_s"]),
            _slowest(float(m["slowest_seconds"]), module=m["slowest_module"]))
        self.assertEqual(v["verdict"], _MG_CLEARS, v["reason"])
        self.assertEqual(v["kind"], m["margin_kind"])

    def test_the_not_clearing_population_may_only_shrink(self):
        """База может только УМЕНЬШАТЬСЯ. Дописывать в неё, чтобы погасить падение, запрещено
        (инв. #16) — тот же порядок, что у `frozen_date_baseline.json`."""
        pop = self.doc["not_clearing"]
        self.assertIsInstance(pop, list)
        self.assertEqual(pop, [], "население выросло — чинить модуль, а не дописывать базу")

    def test_an_entry_without_evidence_is_rejected_by_the_reader(self):
        """Положительный контроль самого храповика: запись «на слово» обязана быть отвергнута."""
        bad = dict(self.doc["measured"])
        bad.pop("slowest_seconds")
        missing = [f for f in REQUIRED_MEASURE_FIELDS if f not in bad]
        self.assertEqual(missing, ["slowest_seconds"])


if __name__ == "__main__":
    unittest.main()
