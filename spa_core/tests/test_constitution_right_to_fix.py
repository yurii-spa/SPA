"""Право чинить спрашивается у ДВУХ поверхностей решения (заказ G54 п. 1).

Заказ G54 п. 1 (хвост [ADR-431](../../docs/decisions/ADR-431-a-zero-that-was-the-shape-of-the-question.md))
назвал асимметрию: третья ось `rule_second_copy_census` спрашивала право чинить
у двух поверхностей решения (пороги `spa_core/risk/policy.py` и витрина порогов
сайта `landing/src/lib/constitution.json`), а две соседние — у одной. Заказ
велел ЗАМЕРИТЬ сдвиг, и замер вышел ненулевым: на оси «исполнитель ×
исполнитель» 14 пар из 67 сравнимых публиковались как «возражать некому», хотя
их величина объявлена витриной — род «решение», меняется только ADR-ом.

Каждый тест ниже — обратная сторона одного правила: сцена, где форма починки
обязана смениться, и соседняя, где она обязана остаться прежней. Ноль на первой
оси проверяется ОТДЕЛЬНО и с обеих сторон: сцена доказывает, что прибор на этой
оси заговорил бы, а живое дерево — что сегодня ему нечего сказать.
"""
from __future__ import annotations

import datetime as dt
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import spa_core.monitoring.rule_second_copy_census as rsc

# FROZEN-DATE-OK: injected-clock — дата подаётся в `measure(..., now=)`
# аргументом; свежести у переписи нет вовсе, `generated_at` в вердикте не
# участвует, и ни одна сцена не спрашивает часы машины.
_NOW = dt.datetime(2000, 1, 1, tzinfo=dt.timezone.utc)

#: Порог RiskPolicy сцены. Значение выбрано так, чтобы не совпасть ни с одной
#: величиной сцен, кроме той единственной, что мерит старшинство порога над
#: витриной: иначе сцена мерила бы не свой предмет.
_POLICY = "MAX_DRAWDOWN = 0.07\n"

#: Число, объявленное ТОЛЬКО витриной порогов. На нём и проверяется сдвиг.
_SHELF_ONLY = "424242.0"


def _tree(base: Path, *, shelf: str | None = '{"start_capital_usd": 424242.0}',
          **files: str) -> Path:
    """Дерево сцены: оба обязательных каталога, пороги и — опционально — витрина.

    ``shelf=None`` означает дерево БЕЗ витрины: это не порча сцены, а её
    предмет — третий исход права чинить (инв. #17). Пороги RiskPolicy при этом
    на месте: без них прибор отвечает `UNMEASURED` всей переписью, и сцена
    мерила бы отказ вместо правила.
    """
    (base / "spa_core" / "tests").mkdir(parents=True)
    (base / "scripts").mkdir(parents=True)
    (base / "spa_core" / "risk").mkdir(parents=True, exist_ok=True)
    (base / "spa_core" / "risk" / "policy.py").write_text(_POLICY, encoding="utf-8")
    if shelf is not None:
        (base / "landing" / "src" / "lib").mkdir(parents=True, exist_ok=True)
        (base / "landing" / "src" / "lib" / "constitution.json").write_text(
            shelf, encoding="utf-8")
    (base / "spa_core" / "tests" / "test_nothing.py").write_text(
        "OTHER = 1\n_read = (OTHER,)\n", encoding="utf-8")
    for rel, text in files.items():
        path = base / rel.replace("__", "/")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return base


def _guard(name: str, value: str) -> str:
    """Сторож, который своё правило ЧИТАЕТ.

    Не читающий сторож снимается с учёта отдельным основанием
    (`guard_constant_unused`), и сцена про право чинить мерила бы тогда чужое
    правило.
    """
    return f"{name} = {value}\n\n\ndef test_it():\n    assert {name} == {value}\n"


def _findings(doc: dict) -> list:
    return [r for r in doc["rows"] if r["verdict"] in rsc._FINDING_CLASSES]


def _pairs(doc: dict) -> list:
    return [r for r in doc["peer_rows"]
            if r["verdict"] == rsc.CLASS_PEER_TWO_COPIES]


class TheRuleOfRightToFixIsOneFunction(unittest.TestCase):
    """Правило права чинить — одно на три оси, и ветви его упорядочены."""

    def test_a_threshold_of_risk_policy_is_the_owners_subject(self):
        remedy, evidence, extra = rsc.right_to_fix(
            "0.05", thresholds={"0.05": ["min_cash_pct"]}, constitution={},
            constitution_unread=None)
        self.assertEqual(remedy, rsc.REMEDY_OWNER)
        self.assertEqual(extra["owner_threshold_names"], ["min_cash_pct"])
        self.assertIn("ADR-285", evidence)

    def test_a_number_declared_only_by_the_shelf_is_the_owners_subject_too(self):
        remedy, evidence, extra = rsc.right_to_fix(
            "100000.0", thresholds={}, constitution={"100000.0": ["start_capital_usd"]},
            constitution_unread=None)
        self.assertEqual(remedy, rsc.REMEDY_CONSTITUTION)
        self.assertEqual(extra["constitution_fields"], ["start_capital_usd"])
        self.assertIn("start_capital_usd", evidence)
        self.assertIn(rsc.CONSTITUTION_FILE, evidence)

    def test_the_threshold_wins_but_the_shelf_is_not_swallowed(self):
        """Обе поверхности сразу: форма — владельца, но вторая НАЗВАНА.

        Умолчать о витрине значило бы выдать одну поверхность за полный ответ
        ровно тем способом, против которого заказ и написан.
        """
        remedy, evidence, extra = rsc.right_to_fix(
            "40.0", thresholds={"40.0": ["max_per_protocol_t1_pct"]},
            constitution={"40.0": ["max_per_protocol_t1_pct"]},
            constitution_unread=None)
        self.assertEqual(remedy, rsc.REMEDY_OWNER)
        self.assertEqual(extra["also_constitution_fields"],
                         ["max_per_protocol_t1_pct"])
        self.assertIn("поверхностей решения ДВЕ", evidence)

    def test_every_colliding_shelf_field_is_named(self):
        _remedy, evidence, extra = rsc.right_to_fix(
            "50.0", thresholds={},
            constitution={"50.0": ["chain_caps.l2_total_pct", "max_t2_total_pct"]},
            constitution_unread=None)
        self.assertEqual(len(extra["constitution_fields"]), 2)
        for field in ("chain_caps.l2_total_pct", "max_t2_total_pct"):
            self.assertIn(f"`{field}`", evidence)

    def test_an_unread_shelf_is_a_third_outcome_not_permission(self):
        remedy, evidence, _extra = rsc.right_to_fix(
            "1.0", thresholds={}, constitution={},
            constitution_unread="витрина порогов не прочитана (причина)")
        self.assertEqual(remedy, rsc.REMEDY_RIGHT_UNMEASURED)
        self.assertIn("не прочитана", evidence)

    def test_an_unread_shelf_cannot_take_away_a_right_already_established(self):
        """Величина равна порогу ⇒ право чинить УЖЕ у владельца.

        Обратная сторона предыдущего теста, и она не симметрична намеренно:
        вторая поверхность способна добавить причину, но не отнять ту, что
        уже названа первой.
        """
        remedy, _evidence, extra = rsc.right_to_fix(
            "0.07", thresholds={"0.07": ["max_drawdown_stop"]}, constitution={},
            constitution_unread="витрина порогов не прочитана (причина)")
        self.assertEqual(remedy, rsc.REMEDY_OWNER)
        self.assertIn("не прочитана", extra["constitution_unread"])

    def test_a_probe_field_survives_the_move_to_the_owner(self):
        """Поле зонда — про ВРЕД, и правом чинить не отменяется.

        Зонд отвечает на вопрос «поймают ли расхождение», право чинить — на
        вопрос «кто вправе править». Потерять первый ответ при переходе ко
        второй форме значило бы погасить наблюдение решением о полномочиях
        (ADR-419 разбирает обратную ошибку — чтение зонда как ответа о
        предмете).
        """
        row = {"verdict": rsc.CLASS_TWO_COPIES, "guard": "tests/test_g.py",
               "executor": "spa_core/e.py", "name": "N", "value": "424242.0"}
        got = rsc.classify_remedy(
            row, guard_text="", executor_text="", thresholds={},
            constitution={"424242.0": ["start_capital_usd"]},
            constitution_unread=None,
            probe={"verdict": rsc.PROBE_DRIFT_SILENT, "evidence": "снос врозь"})
        self.assertEqual(got["remedy"], rsc.REMEDY_CONSTITUTION)
        self.assertEqual(got["drift"], rsc.PROBE_DRIFT_SILENT)
        self.assertEqual(got["drift_evidence"], "снос врозь")

    def test_a_value_on_neither_surface_leaves_the_question_to_the_method(self):
        self.assertEqual(
            rsc.right_to_fix("42", thresholds={}, constitution={},
                             constitution_unread=None),
            (None, None, {}))


class OnlyNumbersCanBeAskedOfTheShelf(unittest.TestCase):
    """Знаменатель сдвига сужен по ПОСТРОЕНИЮ, и сужение это названо числом."""

    def test_a_number_is_comparable(self):
        for value in ("42", "5000000.0", "0.05", "-1"):
            self.assertTrue(rsc.is_numeric_value(value), value)

    def test_a_string_value_is_not(self):
        for value in ("'main'", "'2026-06-12'", "frozenset({'a'})", None):
            self.assertFalse(rsc.is_numeric_value(value), value)


class TheShiftIsVisibleOnTheFirstAxis(unittest.TestCase):
    """Положительный контроль к НУЛЮ живого дерева: прибор здесь заговорил бы."""

    _SCENE = {
        "spa_core__e.py": f"RULE = {_SHELF_ONLY}\n",
        "spa_core__tests__test_g.py": _guard("RULE", _SHELF_ONLY),
    }

    def test_a_shelf_value_moves_the_pair_to_the_owner(self):
        with TemporaryDirectory() as tmp:
            doc = rsc.measure(_tree(Path(tmp), **self._SCENE), now=_NOW)
        rows = _findings(doc)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["remedy"], rsc.REMEDY_CONSTITUTION)
        self.assertEqual(rows[0]["constitution_fields"], ["start_capital_usd"])

    def test_the_form_it_had_before_the_shelf_is_recorded_not_guessed(self):
        with TemporaryDirectory() as tmp:
            doc = rsc.measure(_tree(Path(tmp), **self._SCENE), now=_NOW)
        self.assertEqual(_findings(doc)[0]["remedy_without_shelf"],
                         rsc.REMEDY_UNPROVEN)
        shift = doc["constitution_shift"]["first_axis"]
        self.assertEqual(shift["verdict"], rsc.SHIFT_MEASURED)
        self.assertEqual(shift["moved"], 1)
        self.assertEqual(shift["transitions"],
                         {f"{rsc.REMEDY_UNPROVEN} → {rsc.REMEDY_CONSTITUTION}": 1})

    def test_a_value_on_no_surface_keeps_its_old_form(self):
        """Соседняя сцена: то же дерево, величина витрине неизвестна."""
        scene = {"spa_core__e.py": "RULE = 999.5\n",
                 "spa_core__tests__test_g.py": _guard("RULE", "999.5")}
        with TemporaryDirectory() as tmp:
            doc = rsc.measure(_tree(Path(tmp), **scene), now=_NOW)
        row = _findings(doc)[0]
        self.assertEqual(row["remedy"], rsc.REMEDY_UNPROVEN)
        self.assertNotIn("remedy_without_shelf", row)
        self.assertEqual(doc["constitution_shift"]["first_axis"]["verdict"],
                         rsc.SHIFT_NONE_MEASURED)


class TheShiftIsVisibleOnThePeerAxis(unittest.TestCase):
    """Та же сцена на оси «исполнитель × исполнитель» — ради неё и заказ."""

    _SCENE = {
        "spa_core__a.py": f"RULE = {_SHELF_ONLY}\n",
        "spa_core__b.py": f"RULE = {_SHELF_ONLY}\n",
    }

    def test_a_shelf_value_moves_the_pair_to_the_owner(self):
        with TemporaryDirectory() as tmp:
            doc = rsc.measure(_tree(Path(tmp), **self._SCENE), now=_NOW)
        row = _pairs(doc)[0]
        self.assertEqual(row["remedy"], rsc.REMEDY_CONSTITUTION)
        self.assertEqual(row["remedy_without_shelf"], rsc.REMEDY_UNPROVEN)
        self.assertEqual(doc["peer_remedy_counts"][rsc.REMEDY_CONSTITUTION], 1)
        self.assertEqual(doc["peer_remedy_counts"][rsc.REMEDY_UNPROVEN], 0)

    def test_a_threshold_pair_keeps_its_owner_form_and_records_no_shift(self):
        """Сдвиг приписывается ВИТРИНЕ, а не всякой форме владельца.

        Первая редакция этого прибора записала бы `remedy_without_shelf` и
        паре, равной порогу RiskPolicy, — то есть приписала бы витрине работу,
        сделанную до заказа. Ошибка найдена этим тестом.
        """
        scene = {"spa_core__a.py": "RULE = 0.07\n",
                 "spa_core__b.py": "RULE = 0.07\n"}
        with TemporaryDirectory() as tmp:
            doc = rsc.measure(_tree(Path(tmp), **scene), now=_NOW)
        row = _pairs(doc)[0]
        self.assertEqual(row["remedy"], rsc.REMEDY_OWNER)
        self.assertNotIn("remedy_without_shelf", row)
        self.assertEqual(doc["constitution_shift"]["peer_axis"]["moved"], 0)


class AnAbsentShelfIsNotPermission(unittest.TestCase):
    """Дерево без витрины: «не измерено» на ОБЕИХ осях, а не «чинить можно»."""

    _SCENE = {
        "spa_core__a.py": f"RULE = {_SHELF_ONLY}\n",
        "spa_core__b.py": f"RULE = {_SHELF_ONLY}\n",
        "spa_core__e.py": f"OTHER_RULE = {_SHELF_ONLY}\n",
        "spa_core__tests__test_g.py": _guard("OTHER_RULE", _SHELF_ONLY),
    }

    def test_both_axes_say_unmeasured(self):
        with TemporaryDirectory() as tmp:
            doc = rsc.measure(_tree(Path(tmp), shelf=None, **self._SCENE), now=_NOW)
        self.assertIsNotNone(doc["constitution_unread"])
        self.assertEqual(_findings(doc)[0]["remedy"], rsc.REMEDY_RIGHT_UNMEASURED)
        self.assertEqual(_pairs(doc)[0]["remedy"], rsc.REMEDY_RIGHT_UNMEASURED)

    def test_the_shift_itself_is_unmeasured_not_zero(self):
        with TemporaryDirectory() as tmp:
            doc = rsc.measure(_tree(Path(tmp), shelf=None, **self._SCENE), now=_NOW)
        # Без `subTest` намеренно: падение подтеста оставляет ВНЕШНИЙ вердикт
        # «passed» в перечне `-rA`, и тест, снятый целиком, читался бы глазами
        # как прошедший — тот же класс «не измерено, выданное за ответ».
        self.assertEqual(
            {k: doc["constitution_shift"][k]["verdict"]
             for k in ("first_axis", "peer_axis")},
            {"first_axis": rsc.SHIFT_UNMEASURED,
             "peer_axis": rsc.SHIFT_UNMEASURED})

    def test_a_broken_shelf_is_the_same_outcome_as_an_absent_one(self):
        with TemporaryDirectory() as tmp:
            doc = rsc.measure(_tree(Path(tmp), shelf="{не json", **self._SCENE),
                              now=_NOW)
        self.assertIsNotNone(doc["constitution_unread"])
        self.assertEqual(_pairs(doc)[0]["remedy"], rsc.REMEDY_RIGHT_UNMEASURED)


class ZeroMustBeAnAnswerAndNotTheShapeOfTheQuestion(unittest.TestCase):
    """Ноль от пустого знаменателя — свой вердикт, а не «сдвига нет» (ADR-431)."""

    def test_a_string_valued_pair_is_silent_by_construction(self):
        scene = {"spa_core__a.py": "RULE = 'main'\n",
                 "spa_core__b.py": "RULE = 'main'\n"}
        with TemporaryDirectory() as tmp:
            doc = rsc.measure(_tree(Path(tmp), **scene), now=_NOW)
        shift = doc["constitution_shift"]["peer_axis"]
        self.assertEqual(shift["verdict"], rsc.SHIFT_NOTHING_COMPARABLE)
        self.assertEqual(shift["silent_by_construction"], 1)
        self.assertEqual(shift["comparable"], 0)
        self.assertIn("ПО ПОСТРОЕНИЮ", shift["reason"])

    def test_a_number_valued_pair_makes_the_zero_measured(self):
        scene = {"spa_core__a.py": "RULE = 999.5\n",
                 "spa_core__b.py": "RULE = 999.5\n"}
        with TemporaryDirectory() as tmp:
            doc = rsc.measure(_tree(Path(tmp), **scene), now=_NOW)
        shift = doc["constitution_shift"]["peer_axis"]
        self.assertEqual(shift["verdict"], rsc.SHIFT_NONE_MEASURED)
        self.assertEqual(shift["comparable"], 1)
        self.assertEqual(shift["moved"], 0)

    def test_the_population_of_the_shift_adds_up(self):
        scene = {"spa_core__a.py": f"RULE = {_SHELF_ONLY}\nSTR = 'main'\nTH = 0.07\n",
                 "spa_core__b.py": f"RULE = {_SHELF_ONLY}\nSTR = 'main'\nTH = 0.07\n"}
        with TemporaryDirectory() as tmp:
            doc = rsc.measure(_tree(Path(tmp), **scene), now=_NOW)
        shift = doc["constitution_shift"]["peer_axis"]
        self.assertEqual(shift["population"], 3)
        self.assertEqual(
            shift["population"],
            shift["owner_by_threshold"] + shift["comparable"]
            + shift["silent_by_construction"])
        self.assertLessEqual(shift["moved"], shift["comparable"])


class AllThreeAxesAskTheSameTwoSurfaces(unittest.TestCase):
    """Асимметрия, названная заказом, обязана быть закрыта во ВСЕХ трёх местах."""

    def test_one_scene_answers_the_same_on_every_axis(self):
        scene = {
            "spa_core__a.py": f"RULE = {_SHELF_ONLY}\n",
            "spa_core__b.py": f"RULE = {_SHELF_ONLY}\n",
            "spa_core__tests__test_three.py": _guard("RULE", _SHELF_ONLY),
        }
        with TemporaryDirectory() as tmp:
            doc = rsc.measure(_tree(Path(tmp), **scene), now=_NOW)
        triple = [r for r in doc["triple_rows"]
                  if r["verdict"] == rsc.CLASS_TRIPLE]
        self.assertEqual(len(triple), 1, "сцена обязана дать ровно три копии")
        self.assertEqual(triple[0]["remedy"], rsc.REMEDY_CONSTITUTION)
        self.assertEqual(_pairs(doc)[0]["remedy"], rsc.REMEDY_CONSTITUTION)
        # Первая ось этой пары не видит по построению (исполнителей двое) —
        # и именно поэтому её ответ проверяется отдельной сценой выше, а не
        # выводится из этой.
        self.assertEqual(doc["counts"][rsc.CLASS_TWO_COPIES], 0)


class TheReportNamesTheNumbers(unittest.TestCase):
    """Читателю шага 0-офис достаётся число, а не имя файла."""

    def test_the_shift_line_carries_the_verdict_and_the_denominator(self):
        scene = {"spa_core__a.py": f"RULE = {_SHELF_ONLY}\n",
                 "spa_core__b.py": f"RULE = {_SHELF_ONLY}\n"}
        with TemporaryDirectory() as tmp:
            doc = rsc.measure(_tree(Path(tmp), **scene), now=_NOW)
        lines = rsc.report(doc)
        shift_lines = [l for l in lines if l.startswith("[ВТОРАЯ ПОВЕРХНОСТЬ")]
        self.assertEqual(len(shift_lines), 2, "обе соседние оси обязаны звучать")
        peer_line = [l for l in shift_lines if "исполнитель × исполнитель" in l][0]
        self.assertIn(rsc.SHIFT_MEASURED, peer_line)
        self.assertIn("сравнимых", peer_line)
        self.assertTrue(any(l.startswith("[СДВИГ]") for l in lines))
        self.assertTrue(any("RULE = " in l for l in lines
                            if l.startswith("[СДВИГ · имена]")))

    def test_an_unread_shelf_says_so_in_the_report(self):
        scene = {"spa_core__a.py": f"RULE = {_SHELF_ONLY}\n",
                 "spa_core__b.py": f"RULE = {_SHELF_ONLY}\n"}
        with TemporaryDirectory() as tmp:
            doc = rsc.measure(_tree(Path(tmp), shelf=None, **scene), now=_NOW)
        lines = rsc.report(doc)
        self.assertTrue(any(rsc.SHIFT_UNMEASURED in l for l in lines))


class LiveControlOnTheRealTree(unittest.TestCase):
    """Сцены мерят правило; живое дерево мерит, что правило не холостое."""

    @classmethod
    def setUpClass(cls):
        cls.doc = rsc.measure(Path(rsc._ROOT), now=_NOW)

    def test_the_shelf_is_readable_here_so_nothing_is_unmeasured(self):
        self.assertIsNone(self.doc["constitution_unread"])
        self.assertEqual(
            self.doc["remedy_counts"][rsc.REMEDY_RIGHT_UNMEASURED], 0)
        self.assertEqual(
            self.doc["peer_remedy_counts"][rsc.REMEDY_RIGHT_UNMEASURED], 0)

    def test_the_peer_axis_really_shifted(self):
        """Тот самый замер заказа: число ненулевое, и оно названо строками."""
        shift = self.doc["constitution_shift"]["peer_axis"]
        self.assertEqual(shift["verdict"], rsc.SHIFT_MEASURED)
        self.assertGreater(shift["moved"], 0)
        moved = [r for r in _pairs(self.doc) if r.get("remedy_without_shelf")]
        self.assertEqual(len(moved), shift["moved"])
        for row in moved:
            self.assertEqual(row["remedy"], rsc.REMEDY_CONSTITUTION)
            self.assertTrue(row["constitution_fields"])

    def test_the_first_axis_shift_rests_on_a_named_pair(self):
        """Сдвиг первой оси — ЗАМЕР, и каждая сдвинутая пара названа строкой.

        **Намеренная правка цикла #651, инв. #16.** Прежняя редакция пинила
        здесь `NO_SHIFT_MEASURED`, и ноль был верен ровно до тех пор, пока
        сверка величины шла ТЕКСТОМ: `MIN_ADAPTERS = 10` не совпадало с
        `kill_switch.hard_kill_pct = 10.0`, хотя это одно число. С
        каноническим ключом (:func:`rsc.value_key`) пара нашлась, и ноль
        здесь стал бы уже неправдой.

        Проверяется ТО ЖЕ, что и прежде — что вердикт опирается на непустой
        знаменатель и не берётся из воздуха, — плюс то, чего прежняя
        редакция проверить не могла: каждая сдвинутая пара обязана иметь
        строку с прежней формой. Ветка `NO_SHIFT_MEASURED` контроля не
        теряет: она проверяется сценами выше (обе стороны).
        """
        shift = self.doc["constitution_shift"]["first_axis"]
        self.assertEqual(shift["verdict"], rsc.SHIFT_MEASURED)
        self.assertGreater(shift["comparable"], 0,
                           "вердикт при пустом знаменателе был бы не ответом")
        moved = [r for r in _findings(self.doc) if r.get("remedy_without_shelf")]
        self.assertEqual(len(moved), shift["moved"])
        self.assertGreater(shift["moved"], 0)
        for row in moved:
            self.assertEqual(row["remedy"], rsc.REMEDY_CONSTITUTION)
            self.assertTrue(row["constitution_fields"])

    def test_every_form_of_every_pair_is_a_declared_class(self):
        for row in _pairs(self.doc):
            self.assertIn(row["remedy"], rsc._PEER_REMEDY_CLASSES)
        for row in _findings(self.doc):
            self.assertIn(row["remedy"], rsc._REMEDY_CLASSES)


if __name__ == "__main__":
    unittest.main()
