"""Храповик: чтение отчёта шага 0-офис, за которым НЕ стоит объявление.

Заказ CIO #563: сколько блоков отчёта доходят до читателя, не будучи
объявленными в `_READ_SCHEMA`. Замер (цикл #564, `origin/main` 4e9c01c89):

| класс | население | что значит |
|---|---|---|
| A · у ветки НЕТ записи в схеме | **2** ветки, 15 верхних ключей | не стережётся ни одно чтение |
| B · верхний ключ читается, не объявлен | **12** в 5 ветках | пропади блок — ветка промолчит |
| C · вложенный путь читается, не объявлен | **169** | пропади поле — напечатается `None` |
| третий исход · чтение ушло в чужой модуль | **2** | что прочтут ТАМ, отсюда не видно |
| третий исход · ключ вычисляется | **3** | статике путь не даётся |

Население НЕ ноль ⇒ третий исход заказа («класс пуст») не наступил.

## Почему храповик стоит на A и B, а не на C

Схема — не украшение, а вход тревоги: `_summarize_json` печатает «СХЕМА
РАЗОШЛАСЬ» ровно по объявленным путям. Объявить недостающее = завести тревогу;
но объявить НЕОБЯЗАТЕЛЬНОЕ поле = изготовить ложную тревогу на здоровом файле.
Ровно это сказано в самом модуле про `house_view`: «производитель дневной, и до
его следующего такта живой файл поля не имеет — требование обязательности
выдало бы ложную находку „СХЕМА РАЗОШЛАСЬ“ на верном состоянии».

Поэтому граница класса проходит по УРОВНЮ, а не по важности:

* верхний блок (A и B) — структурная часть отчёта; производитель, переставший
  писать блок целиком, сломал форму, а не пропустил такт. Это стережём;
* вложенное поле (C) — сплошь и рядом необязательно. Его населением сегодня
  **169**, и число записано в базу как ЗАМЕР, а не как потолок: храповика на
  нём нет НАМЕРЕННО, иначе всякий новый прибор краснел бы на ровном месте и
  приучал дописывать базу — тот самый дефект, против которого храповики и
  заводят (ср. `frozen_date_baseline.json`).

Граница названа вслух и закреплена обратным контролем ниже: новое ВЛОЖЕННОЕ
чтение храповик молчит, новое ВЕРХНЕЕ — краснеет.

## База может только уменьшаться

Дописывать имя в базу, чтобы погасить падение, ЗАПРЕЩЕНО (тот же порядок, что
у `frozen_date_baseline.json`, `design_status_baseline.json` и соседнего
`office_schema_field_baseline.json`). Выход из класса один: объявить путь в
`_READ_SCHEMA` — и тогда опустить базу здесь.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from spa_core.tests import _office_read_sites as CENSUS

_BASELINE_PATH = Path(__file__).parent / "office_undeclared_read_baseline.json"
BASELINE = json.loads(_BASELINE_PATH.read_text(encoding="utf-8"))

#: Синтетический исходник: перепись обязана уметь и краснеть, и молчать, не
#: трогая живой файл отчёта. Контроль, не видевший поломки, — украшение.
_FAKE_HEAD = '''
_READ_SCHEMA = {}

def _num(container, key):
    return (container or {}).get(key)

def _summarize_json(path, data):
    name = path
    out = []
'''


def _fake(body: str) -> str:
    return _FAKE_HEAD + body


class OfficeReadDeclarationCensus(unittest.TestCase):
    """Перепись живого файла: населения классов и их движение."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.census = CENSUS.census()

    # ── храповик ───────────────────────────────────────────────────────────
    def test_no_new_branch_without_a_schema_entry(self) -> None:
        """Новая ветка обязана объявить, что читает, — иначе она вне тревоги."""
        new = sorted(set(self.census["no_entry"]) - set(BASELINE["no_entry"]))
        self.assertEqual(new, [], (
            f"у этих веток отчёта НЕТ записи в `_READ_SCHEMA`: {new}. Значит ни "
            "одно их чтение не стережёт строка «СХЕМА РАЗОШЛАСЬ»: пропади у "
            "производителя блок целиком — ветка напечатает `None`, и не "
            "покраснеет ничто. Выход из класса — объявить читаемые блоки в "
            "`_READ_SCHEMA`, а НЕ дописать имя в базу."))

    def test_no_new_undeclared_top_level_read(self) -> None:
        """Верхний блок читается — значит объявлен. Иначе тревоги по нему нет."""
        grew: dict[str, list[str]] = {}
        base = BASELINE["undeclared_top"]
        for name, keys in self.census["undeclared_top"].items():
            known = set(base.get(name, ()))
            new = sorted(set(keys) - known)
            if new:
                grew[name] = new
        self.assertEqual(grew, {}, (
            f"верхние блоки читаются отчётом, но не объявлены: {grew}. "
            "`_summarize_json` сверяет артефакт ровно по объявленным путям, и "
            "необъявленный блок молча становится `None` в строке, которую "
            "читает оркестратор. Объявить в `_READ_SCHEMA`; дописывать базу "
            "здесь, чтобы погасить падение, запрещено (инв. #16)."))

    def test_baseline_is_not_stale(self) -> None:
        """База — про ЭТОТ файл, а не про его прошлое.

        Имя, вышедшее из класса, обязано быть названо здесь: иначе база старела
        бы бесшумно и усыпляла так же надёжно, как её отсутствие.
        """
        gone_entry = sorted(set(BASELINE["no_entry"]) - set(self.census["no_entry"]))
        stale_top = {
            name: sorted(set(keys) - set(self.census["undeclared_top"].get(name, ())))
            for name, keys in BASELINE["undeclared_top"].items()
            if set(keys) - set(self.census["undeclared_top"].get(name, ()))
        }
        self.assertEqual((gone_entry, stale_top), ([], {}), (
            f"класс УМЕНЬШИЛСЯ — это хорошо, но база отстала: вышли из класса "
            f"{gone_entry} / {stale_top}. Опустите базу в "
            f"{_BASELINE_PATH.name}, иначе она перестанет мерить."))

    # ── перепись НЕ вакуумна: она видит тот самый блок, о котором заказ ──────
    def test_the_block_the_order_pointed_at_is_actually_found(self) -> None:
        """Блок `window` цикла #563 доходит до читателя вне всякой тревоги.

        Он печатается из `summary_line(channel_buttons)`, а у артефакта
        `owner_decision_pending.json` записи в схеме нет ВОВСЕ. Не найди этого
        перепись — она была бы украшением: заказ указал ровно сюда.
        """
        self.assertIn("owner_decision_pending.json", self.census["no_entry"])
        self.assertIn("channel_buttons",
                      self.census["no_entry"]["owner_decision_pending.json"])
        handed = {(h["callee"], h["path"]) for h in self.census["handed_off"]}
        self.assertIn(("summary_line", "channel_buttons"), handed)

    def test_third_outcome_is_kept_apart_from_the_population(self) -> None:
        """«Не измерено» не сворачивается ни в «объявлено», ни в «нет»."""
        self.assertTrue(self.census["handed_off"],
                        "третий исход пуст — значит он либо не мерится, либо "
                        "молча слит с населением")
        for row in self.census["handed_off"]:
            self.assertTrue(row["callee"] and row["path"],
                            f"третий исход без причины: {row}")
        for row in self.census["unresolvable"]:
            self.assertIn("<ключ вычисляется>", row["path"], row)

    def test_the_measurement_covers_the_whole_chain(self) -> None:
        """Разбор дошёл до всех веток, а не до первых нескольких.

        Молчаливая потеря хвоста цепочки дала бы «класс пуст» из ничего —
        зелёное от недомера неотличимо от зелёного от здоровья.
        """
        self.assertGreaterEqual(self.census["branches"], 53)
        self.assertGreaterEqual(self.census["schema_entries"], 51)
        self.assertGreater(self.census["population_nested"], 0)


class CensusPositiveControls(unittest.TestCase):
    """Контроли на синтетическом исходнике: перепись умеет и то, и другое."""

    def test_undeclared_top_level_read_is_reported(self) -> None:
        got = CENSUS.census_source(
            _fake('    if name == "x.json":\n'
                  '        out.append(data.get("brand_new_block"))\n'),
            {"x.json": ("other",)})
        self.assertEqual(got["undeclared_top"], {"x.json": ["brand_new_block"]})

    def test_declared_top_level_read_is_silent(self) -> None:
        got = CENSUS.census_source(
            _fake('    if name == "x.json":\n'
                  '        out.append(data.get("brand_new_block"))\n'),
            {"x.json": ("brand_new_block",)})
        self.assertEqual(got["undeclared_top"], {})

    def test_a_nested_declaration_covers_its_container(self) -> None:
        """Объявив `counts.total`, тревогу об отсутствии `counts` уже завели."""
        got = CENSUS.census_source(
            _fake('    if name == "x.json":\n'
                  '        c = data.get("counts") or {}\n'
                  '        out.append(_num(c, "total"))\n'),
            {"x.json": ("counts.total",)})
        self.assertEqual(got["undeclared_top"], {})
        self.assertEqual(got["undeclared_nested"], {})

    def test_nested_read_under_a_declared_container_is_NOT_ratcheted(self) -> None:
        """Граница с классом C: вложенное население считается, но не краснеет.

        Обратный контроль к храповику верхнего уровня. Судил бы храповик и это,
        база стала бы запретом на любое новое поле — и научила бы её дописывать.
        """
        got = CENSUS.census_source(
            _fake('    if name == "x.json":\n'
                  '        c = data.get("counts") or {}\n'
                  '        out.append(c.get("brand_new_leaf"))\n'),
            {"x.json": ("counts",)})
        self.assertEqual(got["undeclared_top"], {})
        self.assertEqual(got["undeclared_nested"], {"x.json": ["counts.brand_new_leaf"]})

    def test_branch_without_a_schema_entry_is_reported(self) -> None:
        got = CENSUS.census_source(
            _fake('    if name == "orphan.json":\n'
                  '        out.append(data.get("anything"))\n'),
            {})
        self.assertEqual(got["no_entry"], {"orphan.json": ["anything"]})

    def test_handoff_to_a_foreign_function_is_the_third_outcome(self) -> None:
        """Под-словарь ушёл наружу — это «не измерено», а не «объявлено»."""
        got = CENSUS.census_source(
            _fake('    if name == "x.json":\n'
                  '        ch = data.get("block")\n'
                  '        out.append(summary_line(ch))\n'),
            {"x.json": ("block",)})
        self.assertEqual(got["undeclared_top"], {})
        self.assertEqual([(h["callee"], h["path"]) for h in got["handed_off"]],
                         [("summary_line", "block")])

    def test_list_element_fields_are_not_counted(self) -> None:
        """Граница названа вслух: поля элемента списка схема не объявляет."""
        got = CENSUS.census_source(
            _fake('    if name == "x.json":\n'
                  '        for a in (data.get("analysts") or []):\n'
                  '            out.append(a.get("agent"))\n'),
            {"x.json": ("analysts",)})
        self.assertEqual(got["undeclared_top"], {})
        self.assertEqual(got["undeclared_nested"], {})

    def test_a_lost_binding_does_not_invent_a_path(self) -> None:
        """Имя, получившее неразбираемое значение, перестаёт быть путём."""
        got = CENSUS.census_source(
            _fake('    if name == "x.json":\n'
                  '        c = data.get("counts")\n'
                  '        c = make_something()\n'
                  '        out.append(c.get("total"))\n'),
            {"x.json": ("counts",)})
        self.assertEqual(got["undeclared_top"], {})
        self.assertEqual(got["undeclared_nested"], {})

    def test_a_missing_summarizer_refuses_loudly(self) -> None:
        """Разбирать нечего ⇒ громкий отказ, а не «класс пуст»."""
        with self.assertRaises(LookupError):
            CENSUS.census_source("def other(): pass\n", {})


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
