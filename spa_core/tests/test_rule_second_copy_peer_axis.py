"""Вторая ось переписи копий: копия между двумя ИСПОЛНИТЕЛЯМИ (заказ G52 п. 1).

Заказ G52 п. 1 (хвост [ADR-429](../../docs/decisions/ADR-429-a-door-that-counts-the-command-is-not-a-door.md))
приказал спросить `rule_second_copy_census` о паре, которую цикл #646 свёл к
ввозу, и ПРОВЕРИТЬ её же прибором, что копия теперь одна. Прибор ответил
молчанием — и молчание оказалось НЕ свидетельством: в сцене с восстановленной
второй копией его вердикт остаётся побуквенно тем же. Причина структурная:
сторожем у первой оси обязан быть собираемый pytest файл, а обе стороны той
пары — рабочий код. Ось заведена, чтобы у класса было ЧИСЛО (ADR-430).

Каждый тест ниже — обратная сторона одного правила оси: сцена, где число
ДОЛЖНО вырасти, и соседняя, где оно вырасти не должно.
"""
from __future__ import annotations

import datetime as dt
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import spa_core.monitoring.rule_second_copy_census as rsc

# FROZEN-DATE-OK: injected-clock — дата подаётся в `measure(..., now=)`
# аргументом; ни одна сцена не спрашивает часы машины, и свежести у переписи
# нет вовсе — `generated_at` в вердикте не участвует.
_NOW = dt.datetime(2000, 1, 1, tzinfo=dt.timezone.utc)

#: Порог сцены. 0.07 выбран так, чтобы НЕ совпасть со значениями сцен, кроме
#: той единственной, что мерит право владельца: иначе всякая пара уезжала бы
#: владельцем и сцена мерила бы не свой предмет.
_POLICY = "MAX_DRAWDOWN = 0.07\n"


def _tree(base: Path, *, shelf: str | None = '{"tvl_floor_usd": 1234567.0}',
          **files: str) -> Path:
    """Дерево из двух обязательных каталогов, порогов и названных модулей.

    Каталоги `spa_core/` и `scripts/` создаются ОБА: отсутствие любого из них —
    самостоятельный исход прибора (`UNMEASURED`), и смешивать его со сценой
    значило бы мерить отказ вместо предмета.
    """
    (base / "spa_core" / "tests").mkdir(parents=True)
    (base / "scripts").mkdir(parents=True)
    (base / "spa_core" / "risk").mkdir(parents=True, exist_ok=True)
    (base / "spa_core" / "risk" / "policy.py").write_text(_POLICY, encoding="utf-8")
    # Витрина порогов сайта — предпосылка сцены ровно так же, как пороги
    # RiskPolicy (заказ G54 п. 1): с этого заказа право чинить спрашивается у
    # ДВУХ поверхностей решения, и дерево без витрины отвечает
    # `right_to_fix_unmeasured` — честный третий исход, но НЕ предмет этой оси.
    # Значение по умолчанию выбрано так, чтобы не совпасть ни с одной сценой:
    # иначе сцена мерила бы витрину вместо своего правила.
    #
    # `shelf=None` ОБЯЗАН остаться выразимым, и это не удобство вызывающего.
    # Помощник общий (его импортирует `test_rule_third_copy_axis`), а там
    # живёт положительный контроль инв. #17: «витрины в дереве нет ⇒ право НЕ
    # ИЗМЕРЕНО». Витрина, положенная в КАЖДУЮ сцену безусловно, отняла бы у
    # того контроля саму его предпосылку — сцену «витрины нет» стало бы
    # невозможно построить, и сторож замолчал бы не потому, что стало не о чем
    # говорить.
    if shelf is not None:
        (base / "landing" / "src" / "lib").mkdir(parents=True, exist_ok=True)
        (base / "landing" / "src" / "lib" / "constitution.json").write_text(
            shelf, encoding="utf-8")
    # Сторож в дереве обязан быть: без единого `test_*.py` прибор отвечает
    # `UNMEASURED`, и это не предмет этой оси.
    (base / "spa_core" / "tests" / "test_nothing.py").write_text(
        "OTHER = 1\n_read = (OTHER,)\n", encoding="utf-8")
    for rel, text in files.items():
        path = base / rel.replace("__", "/")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return base


def _peer(doc: dict) -> dict:
    return doc["peer_counts"]


def _pairs(doc: dict) -> list:
    return [r for r in doc["peer_rows"]
            if r["verdict"] == rsc.CLASS_PEER_TWO_COPIES]


class ThePairThatMotivatedTheAxis(unittest.TestCase):
    """Почему ось вообще есть: молчание первой оси не было свидетельством."""

    _SCENE = {
        "spa_core__left.py": "SPLITTERS = frozenset({'splitlines', 'split'})\n",
        "spa_core__right.py": "SPLITTERS = frozenset({'splitlines', 'split'})\n",
    }

    def test_the_guard_axis_says_nothing_about_two_executors(self):
        """Положительный контроль НА МОЛЧАНИЕ: копия есть, первая ось нема.

        Это и есть замер, ради которого ось написана. Если однажды первая ось
        научится видеть такую пару, тест покраснеет — и правильно сделает:
        основание второй оси тогда придётся перемерить, а не унаследовать.
        """
        with TemporaryDirectory() as tmp:
            doc = rsc.measure(_tree(Path(tmp), **self._SCENE), now=_NOW)
        self.assertEqual(doc["counts"][rsc.CLASS_TWO_COPIES], 0)
        self.assertEqual(doc["counts"][rsc.CLASS_AMBIGUOUS], 0,
                         "пара не попадает даже в корзину неоднозначности")
        self.assertEqual(doc["status"], "CLEAN")

    def test_the_peer_axis_does_see_it(self):
        with TemporaryDirectory() as tmp:
            doc = rsc.measure(_tree(Path(tmp), **self._SCENE), now=_NOW)
        self.assertEqual(_peer(doc)[rsc.CLASS_PEER_TWO_COPIES], 1)
        row = _pairs(doc)[0]
        self.assertEqual(row["name"], "SPLITTERS")
        self.assertEqual((row["left"], row["right"]),
                         ("spa_core/left.py", "spa_core/right.py"))


class TheDoorTakesThePairOff(unittest.TestCase):
    """Достал соседа хоть одной дверью — копия одна, а не две."""

    def test_import_by_one_side_is_enough(self):
        with TemporaryDirectory() as tmp:
            doc = rsc.measure(_tree(
                Path(tmp),
                spa_core__left__="",
                **{"spa_core__left.py": "from spa_core.right import RULE as _r\nRULE = 10\n",
                   "spa_core__right.py": "RULE = 10\n"}), now=_NOW)
        self.assertEqual(_peer(doc)[rsc.CLASS_PEER_TWO_COPIES], 0)
        self.assertEqual(_peer(doc)[rsc.CLASS_PEER_DELEGATES], 1)

    def test_the_other_direction_counts_too(self):
        """Дверь ищется у ОБЕИХ сторон: ввоз односторонен, копия — нет."""
        with TemporaryDirectory() as tmp:
            doc = rsc.measure(_tree(
                Path(tmp),
                **{"spa_core__left.py": "RULE = 10\n",
                   "spa_core__right.py": "from spa_core.left import RULE as _r\nRULE = 10\n"}),
                now=_NOW)
        self.assertEqual(_peer(doc)[rsc.CLASS_PEER_DELEGATES], 1)

    def test_no_door_at_all_stays_a_pair(self):
        """Обратная сторона: без упоминания соседа пара остаётся парой."""
        with TemporaryDirectory() as tmp:
            doc = rsc.measure(_tree(
                Path(tmp),
                **{"spa_core__left.py": "RULE = 10\n",
                   "spa_core__right.py": "RULE = 10\n"}), now=_NOW)
        self.assertEqual(_peer(doc)[rsc.CLASS_PEER_TWO_COPIES], 1)


class AThirdDeclarerIsNotAFinding(unittest.TestCase):
    """Имя у трёх исполнителей — соглашение об именовании, а не правило."""

    def test_three_sides_go_to_their_own_bin(self):
        with TemporaryDirectory() as tmp:
            doc = rsc.measure(_tree(
                Path(tmp),
                **{"spa_core__a.py": "LOG_CAP = 1000\n",
                   "spa_core__b.py": "LOG_CAP = 1000\n",
                   "spa_core__c.py": "LOG_CAP = 1000\n"}), now=_NOW)
        self.assertEqual(_peer(doc)[rsc.CLASS_PEER_TWO_COPIES], 0)
        self.assertEqual(_peer(doc)[rsc.CLASS_PEER_MANY], 1,
                         "третий объявитель уводит имя в свою корзину, а не в ноль")

    def test_two_sides_of_the_same_name_do_stay(self):
        """Обратная сторона того же правила: ровно два — находка."""
        with TemporaryDirectory() as tmp:
            doc = rsc.measure(_tree(
                Path(tmp),
                **{"spa_core__a.py": "LOG_CAP = 1000\n",
                   "spa_core__b.py": "LOG_CAP = 1000\n"}), now=_NOW)
        self.assertEqual(_peer(doc)[rsc.CLASS_PEER_TWO_COPIES], 1)
        self.assertEqual(_peer(doc)[rsc.CLASS_PEER_MANY], 0)


class ValueIsComparedNotOnlyTheName(unittest.TestCase):
    """Равенство значения — условие НЕОБХОДИМОЕ, и его спрашивают."""

    def test_different_values_are_their_own_bin(self):
        with TemporaryDirectory() as tmp:
            doc = rsc.measure(_tree(
                Path(tmp),
                **{"spa_core__a.py": "RULE = 10\n",
                   "spa_core__b.py": "RULE = 11\n"}), now=_NOW)
        self.assertEqual(_peer(doc)[rsc.CLASS_PEER_TWO_COPIES], 0)
        self.assertEqual(_peer(doc)[rsc.CLASS_PEER_VALUE_DIFFERS], 1)

    def test_non_constant_value_is_not_difference(self):
        """«Сравнить было нечем» — третий исход, а не «различаются»."""
        with TemporaryDirectory() as tmp:
            doc = rsc.measure(_tree(
                Path(tmp),
                **{"spa_core__a.py": "RULE = 10\n",
                   "spa_core__b.py": "import os\nRULE = int(os.environ['X'])\n"}),
                now=_NOW)
        self.assertEqual(_peer(doc)[rsc.CLASS_PEER_VALUE_DIFFERS], 0)
        self.assertEqual(_peer(doc)[rsc.CLASS_PEER_NOT_CONSTANT], 1)


class APrivateNameIsInThisPopulation(unittest.TestCase):
    """Асимметрия с первой осью — решение, и оно проверяется в обе стороны."""

    _SCENE = {"spa_core__a.py": "_T1_CAP = 0.4\n",
              "spa_core__b.py": "_T1_CAP = 0.4\n"}

    def test_the_peer_axis_keeps_it(self):
        with TemporaryDirectory() as tmp:
            doc = rsc.measure(_tree(Path(tmp), **self._SCENE), now=_NOW)
        self.assertEqual(_peer(doc)[rsc.CLASS_PEER_TWO_COPIES], 1)
        self.assertTrue(_pairs(doc)[0]["private_name"])
        self.assertEqual(doc["peer_private_names"], 1)

    def test_the_guard_axis_still_drops_it(self):
        """Первая ось приватное имя по-прежнему не берёт — правило не тронуто."""
        with TemporaryDirectory() as tmp:
            base = _tree(Path(tmp), **self._SCENE)
            (base / "spa_core" / "tests" / "test_g.py").write_text(
                "_T1_CAP = 0.4\n_read = (_T1_CAP,)\n", encoding="utf-8")
            doc = rsc.measure(base, now=_NOW)
        self.assertEqual(doc["counts"][rsc.CLASS_TWO_COPIES], 0)


class RightToFixIsAskedFirst(unittest.TestCase):
    """Величина, равная порогу RiskPolicy, — предмет №1 границы ADR-285."""

    def test_a_threshold_value_goes_to_the_owner(self):
        with TemporaryDirectory() as tmp:
            doc = rsc.measure(_tree(
                Path(tmp),
                **{"spa_core__a.py": "CASH = 0.07\n",
                   "spa_core__b.py": "CASH = 0.07\n"}), now=_NOW)
        row = _pairs(doc)[0]
        self.assertEqual(row["remedy"], rsc.REMEDY_OWNER)
        self.assertIn("MAX_DRAWDOWN", row["remedy_evidence"])
        self.assertEqual(doc["peer_owner_subject"], 1)

    def test_a_value_beside_no_threshold_does_not(self):
        """Обратная сторона: сверка не приписывает владельцу что попало."""
        with TemporaryDirectory() as tmp:
            doc = rsc.measure(_tree(
                Path(tmp),
                **{"spa_core__a.py": "CASH = 0.071\n",
                   "spa_core__b.py": "CASH = 0.071\n"}), now=_NOW)
        self.assertEqual(_pairs(doc)[0]["remedy"], rsc.REMEDY_UNPROVEN)
        self.assertEqual(doc["peer_owner_subject"], 0)


class TheUnreadableSideIsAThirdOutcome(unittest.TestCase):
    """Исходник не перечитан ⇒ «дверь НЕ ИЗМЕРЕНА», а не «двери нет» (инв. #17)."""

    def test_missing_text_does_not_become_a_finding(self):
        rows, counts = rsc.peer_pairs(
            {"RULE": [("spa_core/a.py", "10"), ("spa_core/b.py", "10")]},
            source_of=lambda rel: None if rel.endswith("b.py") else "RULE = 10\n",
            imports_of=lambda rel: set(),
            thresholds={}, constitution={}, constitution_unread=None)
        self.assertEqual(counts[rsc.CLASS_PEER_TWO_COPIES], 0)
        self.assertEqual(counts[rsc.CLASS_PEER_UNMEASURED], 1)
        self.assertEqual(rows[0]["verdict"], rsc.CLASS_PEER_UNMEASURED)
        self.assertIn("не измерен", rows[0]["reason"])

    def test_both_texts_present_is_measured(self):
        _rows, counts = rsc.peer_pairs(
            {"RULE": [("spa_core/a.py", "10"), ("spa_core/b.py", "10")]},
            source_of=lambda rel: "RULE = 10\n",
            imports_of=lambda rel: set(),
            thresholds={}, constitution={}, constitution_unread=None)
        self.assertEqual(counts[rsc.CLASS_PEER_UNMEASURED], 0)
        self.assertEqual(counts[rsc.CLASS_PEER_TWO_COPIES], 1)


class TheAxisDoesNotTouchTheVerdictOfTheFirst(unittest.TestCase):
    """189 строк, влитые в находки, утопили бы девять пар первой оси."""

    def test_peer_pairs_alone_leave_the_status_clean(self):
        with TemporaryDirectory() as tmp:
            doc = rsc.measure(_tree(
                Path(tmp),
                **{"spa_core__a.py": "RULE = 10\n",
                   "spa_core__b.py": "RULE = 10\n"}), now=_NOW)
        self.assertEqual(_peer(doc)[rsc.CLASS_PEER_TWO_COPIES], 1)
        self.assertEqual(doc["status"], "CLEAN")

    def test_exit_code_stays_zero_on_peer_pairs_only(self):
        with TemporaryDirectory() as tmp:
            base = _tree(Path(tmp),
                         **{"spa_core__a.py": "RULE = 10\n",
                            "spa_core__b.py": "RULE = 10\n"})
            code = rsc.main(["--root", str(base), "--no-write"])
        self.assertEqual(code, 0)


class AccountingOverNamesIsIdentical(unittest.TestCase):
    """Учёт тождественен: имя с двумя и более объявителями попадает РОВНО в одну корзину."""

    def test_every_multiname_lands_in_exactly_one_bin(self):
        scene = {
            "spa_core__a.py": "SAME = 1\nDIFF = 1\nMANY = 1\nDOOR = 1\n",
            "spa_core__b.py": ("import os\nSAME = 1\nDIFF = 2\nMANY = 1\n"
                               "DOOR = 1\nNOCONST = os.getpid()\n"),
            "spa_core__c.py": "MANY = 1\nNOCONST = 5\n",
            "scripts__d.py": "DOOR = 1\n",
        }
        # DOOR объявлен тремя — уйдёт в MANY; сцена проверяет именно учёт.
        with TemporaryDirectory() as tmp:
            doc = rsc.measure(_tree(Path(tmp), **scene), now=_NOW)
        peer = _peer(doc)
        total = sum(peer[cls] for cls in (
            rsc.CLASS_PEER_TWO_COPIES, rsc.CLASS_PEER_DELEGATES,
            rsc.CLASS_PEER_VALUE_DIFFERS, rsc.CLASS_PEER_NOT_CONSTANT,
            rsc.CLASS_PEER_MANY, rsc.CLASS_PEER_UNMEASURED))
        self.assertEqual(total, 5, f"пять имён с ≥2 объявителями, корзины: {peer}")
        self.assertEqual(peer[rsc.CLASS_PEER_TWO_COPIES], 1)   # SAME
        self.assertEqual(peer[rsc.CLASS_PEER_VALUE_DIFFERS], 1)  # DIFF
        self.assertEqual(peer[rsc.CLASS_PEER_NOT_CONSTANT], 1)   # NOCONST
        self.assertEqual(peer[rsc.CLASS_PEER_MANY], 2)           # MANY, DOOR


class TheReportPrintsEveryNumberIncludingZero(unittest.TestCase):
    """Ноль ПЕЧАТАЕТСЯ, а не подразумевается (инв. #17)."""

    def _lines(self, **scene) -> list:
        with TemporaryDirectory() as tmp:
            doc = rsc.measure(_tree(Path(tmp), **scene), now=_NOW)
        return rsc.report(doc)

    def test_all_six_bins_are_named(self):
        lines = self._lines(**{"spa_core__a.py": "RULE = 10\n",
                               "spa_core__b.py": "RULE = 10\n"})
        head = next(l for l in lines if l.startswith("[ПАРА ИСПОЛНИТЕЛЕЙ]"))
        for word in ("копия между двумя исполнителями", "дверь открыта",
                     "значения разные", "сравнить нечем",
                     "имя у многих исполнителей", "дверь НЕ ИЗМЕРЕНА"):
            self.assertIn(word, head)
        self.assertIn("дверь открыта 0", head, "ноль печатается, а не умалчивается")

    def test_the_private_line_names_the_number_and_its_denominator(self):
        """Выживание мутации #24: строку про приватные имена не проверял никто.

        Батарея сняла `приватных {priv} из {two}` до `[ИМЯ] из ` — и все
        тесты остались зелёными. Число в документе есть, а у читателя его
        нет: ровно тот класс «измерено, но не доехало», против которого
        написана вся перепись.
        """
        lines = self._lines(**{"spa_core__a.py": "_T1_CAP = 0.4\n",
                               "spa_core__b.py": "_T1_CAP = 0.4\n"})
        line = next(l for l in lines if l.startswith("[ИМЯ]"))
        self.assertIn("приватных 1", line)
        self.assertIn("из 1", line, "знаменатель обязан стоять рядом с числом")

    def test_the_axis_says_why_it_exists(self):
        lines = self._lines(**{"spa_core__a.py": "RULE = 10\n",
                               "spa_core__b.py": "RULE = 10\n"})
        self.assertTrue(any("молчание первой оси" in l for l in lines))

    def test_an_absent_axis_is_named_not_shown_as_zero(self):
        doc = {"status": "CLEAN", "counts": {}, "rows": [],
               "renamed_copy_surface": []}
        lines = rsc.report(doc)
        self.assertTrue(any("[ПАРА ИСПОЛНИТЕЛЕЙ] НЕ ИЗМЕРЕНА" in l for l in lines))


class RowsAreDeterministic(unittest.TestCase):
    """Две подряд переписи одного дерева дают один и тот же перечень."""

    def test_two_runs_agree(self):
        scene = {"spa_core__b.py": "RULE = 10\nOTHER = 2\n",
                 "spa_core__a.py": "RULE = 10\nOTHER = 2\n"}
        with TemporaryDirectory() as tmp:
            base = _tree(Path(tmp), **scene)
            first = rsc.measure(base, now=_NOW)["peer_rows"]
            second = rsc.measure(base, now=_NOW)["peer_rows"]
        self.assertEqual(first, second)
        self.assertEqual([r["name"] for r in first], ["OTHER", "RULE"])


class LiveControlOnTheRealTree(unittest.TestCase):
    """Сцены проверяют правило; живое дерево проверяет, что оно не холостое."""

    def test_the_axis_is_not_empty_on_this_repository(self):
        doc = rsc.measure(Path(rsc._ROOT), now=_NOW)
        pairs = _pairs(doc)
        self.assertGreater(len(pairs), 0,
                           "перепись без единой пары на живом дереве была бы холостой")
        for row in pairs:
            self.assertNotEqual(row["left"], row["right"])
            self.assertIn(row["remedy"], (rsc.REMEDY_OWNER,
                                          rsc.REMEDY_CONSTITUTION,
                                          rsc.REMEDY_UNPROVEN))
        # Витрина порогов в этом дереве ЕСТЬ и читается, поэтому третий исход
        # права чинить обязан быть ПУСТ: непустой означал бы, что живое дерево
        # отвечает «не измерено» там, где измерить было чем (заказ G54 п. 1).
        self.assertEqual(doc["peer_remedy_counts"][rsc.REMEDY_RIGHT_UNMEASURED], 0)
        self.assertIsNone(doc["constitution_unread"])
        self.assertEqual(len(pairs), doc["peer_counts"][rsc.CLASS_PEER_TWO_COPIES])


if __name__ == "__main__":
    unittest.main()
