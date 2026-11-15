"""Приёмка ADR-1014: у МАТРИЦЫ запас — тоже УСЛОВИЕ вердикта, и мерится он у СРЕЗА.

Заказ G1003 п. 1 (а) = [ADR-1013](../../docs/decisions/ADR-1013-margin-is-a-condition-not-a-reason.md)
§ 7 (а). ADR-1013 сделал запас условием вердикта у ОДИНОЧНОГО входа и САМ НАЗВАЛ границу: матрица
двух входов запасом не гатилась вовсе. В матричном зове `timeout_variance` возвращает ранний
`UNMEASURED` (`_MATRIX_ABSENT_REASON`), то есть гейт ADR-1013 живёт только в зове `--timeouts` без
`--protocols`, а ответ ADR-1012 по оси `timeout_within_protocol` печатал «инвариантно» без
условия на запас — над причиной, которой в наблюдении могло не существовать вовсе.

**Запас мерится у СРЕЗА, и это несущая половина решения.** «Инвариантно по пределу ПРИ `aave_v3`»
объясняется запасом ТЕХ клеток, по которым этот срез и сравнивался. Запас, снятый по всей
матрице, осудил бы вместе с тонким срезом и все остальные — утверждение встало бы у оси целиком
и, как сказано в заказе дословно, «не сработало бы никогда». Поэтому у сцены есть РАЗЛИЧАЮЩАЯ
клетка: ОДНА медленная клетка обязана осудить РОВНО один срез на каждой оси и не тронуть
соседний (урок ADR-1012 § 7г: мутация без различающей сцены выживает).

Что держит эта батарея — по одному утверждению на класс:

* **гейт стои́т у СРЕЗА**: одна медленная клетка — один осуждённый срез на ось, остальные
  INVARIANT. Гейт у оси целиком и гейт нигде обе эти сцены красят;
* **`VARIES` запасом НЕ гатится** — порядок звеньев тот же, что у одиночного замера: названное
  различие само есть доказательство, что вход доходит, и гасить находку порогом было бы
  ослаблением проверки;
* **гейт НЕ ОТНИМАЕТ у оси доказательство живости.** Сводка стороны вправе уйти в `UNMEASURED`
  из-за ДРУГОГО, тонкого среза; спроси ось сводку — и она потеряла бы различие, которое у неё
  есть, а причина отказа назвала бы НЕ ТО звено («живость не доказана» вместо «запас тонок»).
  Это найдено сценой, а не рассуждением;
* **названная находка не исчезает из сводки оси** вместе с ушедшей в `UNMEASURED` сводкой стороны;
* **три исхода различимы** (инв. #17) и причины НАЗВАНЫ раздельно: запас прошёл · запас тонок
  (искать подорожавший модуль) · длительностей нет вовсе (чинить наблюдателя);
* **адрес замера несёт свой РОД** (`MARGIN_AT_KINDS`): у одиночного входа это ПРЕДЕЛ, у матрицы —
  КЛЕТКА. До ADR-1014 адрес звался `at_timeout` безусловно, и матрица печатала бы «наблюдение при
  пределе `p_one@1.0` с» — число с подделанным родом;
* **дверь ОДНА** и у ключа клетки среза, и у запаса: разойдись они, запас мерился бы по одному
  набору клеток, а вердикт выносился по другому, и расхождение было бы молчаливым.

Контроль у каждого утверждения — в ОБЕ стороны: сцена, где прибор обязан сказать «да», и сцена,
где он обязан сказать «нет» с НАЗВАННОЙ причиной.
"""
from __future__ import annotations

import ast
import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CENSUS_PATH = ROOT / "scripts" / "registry_runner_write_census.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


rrwc = _load(CENSUS_PATH, "rrwc_matrix_margin")
bat = _load(Path(__file__).resolve().parent / "test_registry_census_matrix_variance.py",
            "bat_for_matrix_margin")

_MG_CLEARS, _MG_BELOW, _MG_UNMEASURED = rrwc.MARGIN_VERDICTS
_T_IN_P, _P_IN_T = rrwc.MATRIX_AXES
_INVARIANT, _VARIES, _UNMEASURED = "INVARIANT", "VARIES", "UNMEASURED"
#: Длительности сцены. Предел сцены 2.5 с (`bat.SCENE_TIMEOUT`), порог `MARGIN_FLOOR_X` = 10×:
#: 0.001 с даёт 2500× (порог пройден), 0.5 с — 5× (НИЖЕ порога). Обе величины — следствие
#: объявленного порога, а не литералы «на глаз».
_FAT, _THIN = 0.001, 0.5
_SIDE = "runner_status"


class _Matrix(unittest.TestCase):
    """Общая сцена: полный квадрат 2×2, цена и статусы задаются ПОКЛЕТОЧНО."""

    def setUp(self):
        self.s = bat.Scene()

    def tearDown(self):
        self.s.close()

    def _same(self, p, t):
        return [(m, "ok") for m in self.s.modules]

    def _timeout_moves_in_first_protocol(self, p, t):
        """Статус зависит от ПРЕДЕЛА и только у `p_one` — различие ровно в одном срезе оси
        `timeout_within_protocol`."""
        if p != bat._PROTOCOLS[0]:
            return self._same(p, t)
        return [(self.s.modules[0], "ok" if t == bat._T_LOW else "dormant")] + \
               [(m, "ok") for m in self.s.modules[1:]]

    def _ask(self, seconds_of, rows_of=None, knob=bat._KB_LIVE):
        rows_of = rows_of or self._same
        by_cell = {rrwc.cell_key(p, t): self.s.obs(rows_of(p, t), seconds=seconds_of(p, t))
                   for p in bat._PROTOCOLS for t in (bat._T_LOW, bat._T_HIGH)}
        return self.s.ask(by_cell, bat._knob(knob) if knob is not None else None)

    def _slice(self, mx, axis, fixed, side=_SIDE):
        return mx["sides"][side][axis]["slices"][fixed]


# ───────────── гейт стои́т у СРЕЗА, а не у оси ─────────────

class TheGateStandsAtTheSlice(_Matrix):

    def test_a_fat_margin_in_every_cell_still_earns_INVARIANT(self):
        """Обратный контроль: гейт не вправе краснеть на здоровых данных."""
        mx = self._ask(lambda p, t: _FAT)
        self.assertEqual(mx["axes"][_T_IN_P]["verdict"], _INVARIANT)
        self.assertEqual(mx["sides"][_SIDE][_T_IN_P]["verdict"], _INVARIANT)
        for fixed in bat._PROTOCOLS:
            gate = self._slice(mx, _T_IN_P, fixed)["margin_gate"]
            self.assertEqual(gate["verdict"], _MG_CLEARS, fixed)
            self.assertEqual(gate["margin"], 2500.0, fixed)

    def test_ONE_slow_cell_condemns_exactly_one_slice_per_axis_and_spares_the_rest(self):
        """РАЗЛИЧАЮЩАЯ сцена заказа. Медленна РОВНО клетка (`p_one`, 1.0 с).

        Гейт у ОСИ целиком осудил бы все четыре среза, гейт нигде — ни одного; только гейт у
        СРЕЗА осуждает по одному срезу на ось и называет его ИМЕНЕМ.
        """
        slow = (bat._PROTOCOLS[0], bat._T_LOW)
        mx = self._ask(lambda p, t: _THIN if (p, t) == slow else _FAT)
        # ось «предел внутри протокола»: срезы — протоколы.
        self.assertEqual(mx["sides"][_SIDE][_T_IN_P]["slices_unmeasured"], [bat._PROTOCOLS[0]])
        thin = self._slice(mx, _T_IN_P, bat._PROTOCOLS[0])
        self.assertEqual(thin["verdict"], _UNMEASURED)
        self.assertEqual(thin["margin_gate"]["verdict"], _MG_BELOW)
        self.assertEqual(thin["margin_gate"]["margin"], 5.0)
        spared = self._slice(mx, _T_IN_P, bat._PROTOCOLS[1])
        self.assertEqual(spared["verdict"], _INVARIANT)
        self.assertEqual(spared["margin_gate"]["verdict"], _MG_CLEARS)
        # ось «протокол внутри предела»: срезы — пределы, и осуждён РОВНО тот, где медленно.
        self.assertEqual(mx["sides"][_SIDE][_P_IN_T]["slices_unmeasured"],
                         [rrwc.timeout_key(bat._T_LOW)])
        self.assertEqual(self._slice(mx, _P_IN_T, rrwc.timeout_key(bat._T_HIGH))["verdict"],
                         _INVARIANT)

    def test_the_condemned_slice_is_NAMED_in_the_axis_reason_and_the_spared_one_is_not(self):
        slow = (bat._PROTOCOLS[0], bat._T_LOW)
        mx = self._ask(lambda p, t: _THIN if (p, t) == slow else _FAT)
        axis = mx["axes"][_T_IN_P]
        self.assertEqual(axis["verdict"], _UNMEASURED)
        self.assertIn(bat._PROTOCOLS[0], axis["unmeasured_reason"])
        self.assertNotIn(bat._PROTOCOLS[1], axis["unmeasured_reason"])
        self.assertIn(str(rrwc.MARGIN_FLOOR_X), axis["unmeasured_reason"])

    def test_the_gate_fires_even_when_LIVENESS_is_proven(self):
        """Несущее: запас и контроль входа отвечают на РАЗНЫЕ вопросы. Контроль жив, живость оси
        доказана им же — и вердикт всё равно `UNMEASURED`, потому что не подтверждена ПРИЧИНА,
        которой этот ответ объясняется."""
        mx = self._ask(lambda p, t: _THIN)
        axis = mx["axes"][_T_IN_P]
        self.assertEqual(axis["liveness"], rrwc.AXIS_LIVENESS[1])  # AXIS_LIVE_BY_KNOB
        self.assertEqual(axis["verdict"], _UNMEASURED)
        self.assertIn("не подтверждена", axis["unmeasured_reason"])

    def test_a_dead_knob_keeps_its_OWN_reason_and_is_not_overwritten_by_the_margin(self):
        """Порядок звеньев — часть ответа: при здоровом запасе отказать обязан контроль входа, и
        причина обязана называть ЕГО."""
        mx = self._ask(lambda p, t: _FAT, knob=bat._KB_DEAD)
        reason = mx["sides"][_SIDE][_T_IN_P]["unmeasured_reason"]
        self.assertIn("живость оси НЕ ДОКАЗАНА", reason)
        self.assertNotIn("запас", reason)


# ───────────── названное различие запасом НЕ гатится ─────────────

class ANamedDifferenceIsNotGated(_Matrix):

    def test_a_VARIES_slice_survives_a_thin_margin(self):
        mx = self._ask(lambda p, t: _THIN if p == bat._PROTOCOLS[0] else _FAT,
                       rows_of=self._timeout_moves_in_first_protocol)
        varying = self._slice(mx, _T_IN_P, bat._PROTOCOLS[0])
        self.assertEqual(varying["verdict"], _VARIES)
        # запас при этом ИЗМЕРЕН и назван — он просто ничего не гатит у различия.
        self.assertEqual(varying["margin_gate"]["verdict"], _MG_BELOW)
        self.assertEqual(mx["sides"][_SIDE][_T_IN_P]["slices_unmeasured"], [])
        self.assertEqual(mx["sides"][_SIDE][_T_IN_P]["verdict"], _VARIES)
        # А ОСЬ при этом `UNMEASURED`, и это НЕ гашение находки: тот же тонкий срез `p_one` у
        # сторон, которые в нём НЕ различаются, запаса не прошёл, а порядок исходов у оси
        # (ADR-1012) — fail-CLOSED. Причина обязана называть ДРУГУЮ сторону, не эту.
        axis = mx["axes"][_T_IN_P]
        self.assertEqual(axis["verdict"], _UNMEASURED)
        self.assertEqual(axis["sides"][_SIDE], _VARIES)
        self.assertNotIn(f"{_SIDE}:", axis["unmeasured_reason"])
        other = sorted(n for n, v in axis["sides"].items() if v == _UNMEASURED)
        self.assertTrue(other, axis["sides"])
        self.assertIn(other[0], axis["unmeasured_reason"])

    def test_the_gate_does_NOT_steal_the_axis_liveness_proof(self):
        """Сцена, нашедшая СЦЕПКУ. Срез `p_one` РАЗЛИЧАЕТСЯ, срез `p_two` тонок ⇒ сводка стороны
        уходит в `UNMEASURED`. Спроси ось сводку стороны (как спрашивал ADR-1012) — и живость
        стала бы `UNPROVEN`, то есть причина отказа назвала бы НЕ ТО звено.

        Контроль входа здесь НЕ ИЗМЕРЕН намеренно: живость обязана быть доказана РАЗЛИЧИЕМ.
        """
        mx = self._ask(lambda p, t: _FAT if p == bat._PROTOCOLS[0] else _THIN,
                       rows_of=self._timeout_moves_in_first_protocol,
                       knob=bat._KB_UNMEASURED)
        side = mx["sides"][_SIDE][_T_IN_P]
        self.assertEqual(side["verdict"], _UNMEASURED)
        self.assertEqual(side["slices_varying"], [bat._PROTOCOLS[0]])
        self.assertEqual(side["slices_unmeasured"], [bat._PROTOCOLS[1]])
        axis = mx["axes"][_T_IN_P]
        self.assertEqual(axis["liveness"], rrwc.AXIS_LIVENESS[0])  # AXIS_LIVE_BY_DIFFERENCE
        self.assertIn(_SIDE, axis["liveness_reason"])
        # и причина отказа называет ЗАПАС того среза, который его не прошёл, а не живость.
        self.assertIn(bat._PROTOCOLS[1], axis["unmeasured_reason"])
        self.assertIn(str(rrwc.MARGIN_FLOOR_X), axis["unmeasured_reason"])

    def test_the_named_finding_does_not_vanish_from_the_axis_summary(self):
        mx = self._ask(lambda p, t: _FAT if p == bat._PROTOCOLS[0] else _THIN,
                       rows_of=self._timeout_moves_in_first_protocol,
                       knob=bat._KB_UNMEASURED)
        self.assertEqual(mx["axes"][_T_IN_P]["sides_varying"].get(_SIDE),
                         [bat._PROTOCOLS[0]])


# ───────────── три исхода, и причины названы раздельно ─────────────

class ThreeOutcomesNamedSeparately(_Matrix):

    def test_cells_without_durations_are_UNMEASURED_and_not_a_zero_margin(self):
        mx = self._ask(lambda p, t: None)
        gate = self._slice(mx, _T_IN_P, bat._PROTOCOLS[0])["margin_gate"]
        self.assertEqual(gate["verdict"], _MG_UNMEASURED)
        self.assertIsNone(gate["margin"])
        self.assertIn("нет длительностей", gate["reason"])
        self.assertEqual(mx["axes"][_T_IN_P]["verdict"], _UNMEASURED)

    def test_thin_and_blind_are_DIFFERENT_reasons_not_one_line_about_the_margin(self):
        """«Запас тонок» и «длительностей нет» требуют РАЗНЫХ действий — искать подорожавший
        модуль против чинить наблюдателя, — поэтому называются раздельно."""
        thin = self._slice(self._ask(lambda p, t: _THIN), _T_IN_P, bat._PROTOCOLS[0])
        blind = self._slice(self._ask(lambda p, t: None), _T_IN_P, bat._PROTOCOLS[0])
        self.assertNotEqual(thin["margin_gate"]["verdict"], blind["margin_gate"]["verdict"])
        self.assertNotEqual(thin["unmeasured_reason"], blind["unmeasured_reason"])
        self.assertIn("НИЖЕ порога", thin["margin_gate"]["reason"])

    def test_a_zero_duration_is_UNMEASURED_not_an_infinite_margin(self):
        mx = self._ask(lambda p, t: 0.0)
        gate = self._slice(mx, _T_IN_P, bat._PROTOCOLS[0])["margin_gate"]
        self.assertEqual(gate["verdict"], _MG_UNMEASURED)
        self.assertEqual(mx["axes"][_T_IN_P]["verdict"], _UNMEASURED)


# ───────────── адрес замера несёт свой РОД ─────────────

class TheAddressCarriesItsKind(_Matrix):

    def test_the_matrix_measurement_is_addressed_by_CELL(self):
        mx = self._ask(lambda p, t: _FAT)
        slowest = self._slice(mx, _T_IN_P, bat._PROTOCOLS[0])["margin_gate"]["slowest"]
        self.assertEqual(slowest["at_kind"], rrwc.MARGIN_AT_KINDS[1])
        self.assertIn(rrwc.MATRIX_CELL_SEP, slowest["at"])
        self.assertIn("в клетке", rrwc._margin_at(slowest))

    def test_the_single_input_measurement_is_still_addressed_by_TIMEOUT(self):
        """Обратный контроль: род не «всегда клетка», он объявлен у ЗАМЕРА."""
        single = rrwc._slowest_observed_module(
            {rrwc.timeout_key(3.0): {"per_module": [{"module": "m", "seconds": 0.01}]}})
        self.assertEqual(single["at_kind"], rrwc.MARGIN_AT_KINDS[0])
        self.assertIn("при пределе", rrwc._margin_at(single))

    def test_an_undeclared_kind_is_a_THIRD_outcome_not_a_silent_substitution(self):
        said = rrwc._margin_at({"module": "m", "seconds": 1.0, "at": "?", "at_kind": "выдумка"})
        self.assertIn("НЕ ОБЪЯВЛЕН", said)
        with self.assertRaises(ValueError):
            rrwc._slowest_observed_module({"3.0": {"per_module": []}}, "выдумка")

    def test_no_measurement_at_all_says_so(self):
        self.assertIn("не измерен", rrwc._margin_at(None))


# ───────────── печать ─────────────

class TheRenderNamesTheWorstSlice(_Matrix):

    def _text(self, seconds_of, **kw):
        return "\n".join(rrwc.render_matrix_variance(self._ask(seconds_of, **kw)))

    def _margin_lines(self, seconds_of, **kw):
        """Утверждать надо о СТРОКЕ ЗАПАСА, а не о всей печати.

        Мутант M12 (#1136) «печатать лучший срез вместо худшего» ВЫЖИЛ у первой редакции этих
        сцен: нужные слова нашлись в строке `ОСЬ:` — там печатается причина отказа, и она тоже
        несёт «НИЖЕ порога». Подстрочный поиск по всему тексту отдаёт подтверждение ДАРОМ
        (урок G1003 п. 26д), поэтому предмет вырезается по своему заголовку.
        """
        lines = [l for l in self._text(seconds_of, **kw).splitlines() if "запас до предела" in l]
        self.assertTrue(lines, "строки запаса в печати нет вовсе")
        return lines

    def test_the_margin_line_names_the_WORST_slice_not_the_best(self):
        slow = (bat._PROTOCOLS[0], bat._T_LOW)
        lines = self._margin_lines(lambda p, t: _THIN if (p, t) == slow else _FAT)
        joined = "\n".join(lines)
        self.assertIn("НИЖЕ порога", joined)
        self.assertIn(f"`{bat._PROTOCOLS[0]}`", joined)
        # и сохранный срез НЕ выдаётся за ответ о запасе оси.
        self.assertNotIn(f"`{bat._PROTOCOLS[1]}`", joined)
        self.assertNotIn("ПРОЙДЕН", joined)
        self.assertIn(str(rrwc.MARGIN_FLOOR_X), joined)
        self.assertIn(rrwc.MARGIN_KIND_LOWER_BOUND, joined)

    def test_a_healthy_margin_is_printed_too_because_INVARIANT_needs_its_cause_named(self):
        joined = "\n".join(self._margin_lines(lambda p, t: _FAT))
        self.assertIn("ПРОЙДЕН", joined)
        self.assertIn("2500.0×", joined)

    def test_missing_durations_are_printed_as_NOT_MEASURED(self):
        joined = "\n".join(self._margin_lines(lambda p, t: None))
        self.assertIn("НЕ ИЗМЕРЕН", joined)
        self.assertNotIn("ПРОЙДЕН", joined)

    def test_the_footer_no_longer_claims_the_margin_guard_is_missing(self):
        """Хвост «НЕ ДОКЛАДЫВАЕТ» — утверждение, и оно обязано перестать быть ложным в тот же
        день, когда докладывать начали."""
        text = self._text(lambda p, t: _FAT)
        footer = [l for l in text.splitlines() if "НЕ ДОКЛАДЫВАЕТ" in l]
        self.assertEqual(len(footer), 1, text)
        self.assertNotIn("сторож ЗАПАСА", footer[0])


# ───────────── двери ─────────────

class OneDoorNotTwo(unittest.TestCase):
    """Своя формула или свой ключ рядом вернули бы класс «одно имя — один объект»: запас мерился
    бы по одному набору клеток, а вердикт выносился по другому."""

    def setUp(self):
        self.tree = ast.parse(CENSUS_PATH.read_text(encoding="utf-8"))
        self.funcs = {n.name: n for n in ast.walk(self.tree)
                      if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}

    def _calls(self, name):
        return {n.func.id for n in ast.walk(self.funcs[name])
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}

    def test_the_matrix_builds_cell_keys_ONLY_through_the_slice_door(self):
        """В теле `matrix_variance` разделителя клетки нет ВОВСЕ: ключ среза делает одна дверь,
        и её же зовёт замер запаса."""
        names = {n.id for n in ast.walk(self.funcs["matrix_variance"])
                 if isinstance(n, ast.Name)}
        self.assertNotIn("MATRIX_CELL_SEP", names)
        self.assertIn("_slice_cell_key", self._calls("matrix_variance"))
        self.assertIn("_slice_cell_key", self._calls("_slice_margin"))

    def test_the_margin_of_a_slice_comes_from_the_SAME_verdict_door(self):
        self.assertIn("margin_floor_verdict", self._calls("_slice_margin"))
        self.assertIn("_slowest_observed_module", self._calls("_slice_margin"))
        # и матрица не считает запас сама — только через дверь среза.
        self.assertNotIn("margin_floor_verdict", self._calls("matrix_variance"))
        self.assertIn("_slice_margin", self._calls("matrix_variance"))

    def test_the_floor_is_still_declared_exactly_once(self):
        src = CENSUS_PATH.read_text(encoding="utf-8")
        self.assertEqual(src.count("MARGIN_FLOOR_X = "), 1)


# ───────────── храповик замера матрицы ─────────────

#: Поля, без которых запись замером не является. Порядок ADR-1013 (`measured`) дословно: запись
#: без замера в неё не принимается — плато, объявленное на слово, и есть тот дефект.
_REQUIRED = ("at_commit", "instrument_md5", "cells", "declared_timeout_s", "slices",
             "margin_kind", "source", "measured_at")


class TheMatrixMeasurementIsAMeasurementNotACopy(unittest.TestCase):
    """Замер срезов живёт в том же храповике, что и замер одиночного входа, и по тем же правилам:
    своё доказательство · без копии порога · население только убывает."""

    def setUp(self):
        import json
        path = Path(__file__).resolve().parent / "registry_census_margin_baseline.json"
        self.base = json.loads(path.read_text(encoding="utf-8"))
        self.text = path.read_text(encoding="utf-8")
        self.m = self.base.get("measured_matrix")

    def test_the_matrix_measurement_exists_and_carries_its_own_evidence(self):
        self.assertIsNotNone(self.m, "замера матрицы в базе нет")
        for field in _REQUIRED:
            self.assertIn(field, self.m, field)
            self.assertTrue(self.m[field] not in (None, "", [], {}), field)

    def test_the_baseline_does_not_carry_a_copy_of_the_floor(self):
        """Копия порога означала бы, что сторож сверяет константу с константой и молчит ровно до
        дня, когда одна из двух поедет (класс ADR-913)."""
        self.assertNotIn("margin_floor", self.m)
        self.assertNotIn(f'"floor": {rrwc.MARGIN_FLOOR_X}', self.text)

    def test_every_recorded_slice_clears_the_CURRENT_floor_through_the_SAME_door(self):
        """Замер проверяется ТЕКУЩИМ порогом и той же дверью: объявить порог выше того, что
        система показывает, запрещено."""
        declared = self.m["declared_timeout_s"]
        for axis, slices in self.m["slices"].items():
            self.assertIn(axis, rrwc.MATRIX_AXES, axis)
            for fixed, rec in slices.items():
                gate = rrwc.margin_floor_verdict(
                    declared, {"module": rec["slowest_module"], "seconds": rec["slowest_seconds"],
                               "at": rec["at_cell"], "at_kind": rrwc.MARGIN_AT_KINDS[1]})
                self.assertEqual(gate["verdict"], rec["verdict"], f"{axis}/{fixed}")
                self.assertEqual(gate["margin"], rec["margin_at_least"], f"{axis}/{fixed}")

    def test_the_not_clearing_population_may_only_shrink(self):
        """Дописывать в население, чтобы погасить падение, ЗАПРЕЩЕНО (инв. #16) — тот же порядок,
        что у `frozen_date_baseline.json`."""
        self.assertLessEqual(len(self.m["not_clearing_slices"]), 0,
                             "население срезов без запаса выросло — это находка, а не база")

    def test_the_measurement_names_the_SIZE_of_its_own_population(self):
        """«Ни один срез не ниже порога» принадлежит замеру и его размеру, а не системе вообще."""
        self.assertIn("_что_НЕ_измерено", self.m)
        self.assertIn("4", str(self.m["cells"]))
        self.assertEqual(sum(len(s) for s in self.m["slices"].values()), 4)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
