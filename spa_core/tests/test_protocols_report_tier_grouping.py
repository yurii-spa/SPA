"""Группировка отчёта владельцу `/protocols` по тирам — батарея ADR-713.

Предмет — карточка `inbox-yarlyki-tirov-v-otchete-protocols-nazyva` и заказ
**G712 п. 3** приказа `inbox-task-portfolio-cio-dynamic-capital-alloc`.

**Замер живого `data/adapter_status.json` 2026-10-13** (34 записи): поле `tier`
несёт ЦЕЛОЕ `1` у 6 записей, `2` у 23, `3` у 4 и строку `"T1"` ровно у одной
(теневой легаси-блок `sky_susds`). Группировка брала ярлык как есть
(`str(запись["tier"])`), поэтому 33 записи из 34 печатались владельцу
заголовками `*1*`, `*2*`, `*3*` — без названия тира и ВНЕ канонического порядка
(порядок таких разделов был порядком обхода словаря). Тир T1 при этом выходил
ДВУМЯ разделами сразу: каноническим `*T1 — Anchor Protocols*` с одной записью и
`*1*` с остальными шестью.

Второй дефект того же места — ТИШЕ первого: отсутствие поля `tier` подставлялось
строкой `"T2"` (`adapter.get("tier", "T2")`), то есть запись без объявленного
тира читалась владельцу как протокол второго тира. Это ровно инвариант #17:
отсутствие наблюдения обязано быть представлено ОТДЕЛЬНЫМ значением.

**Каждый тест здесь — обратная сторона с НАЗВАННЫМ звеном**, а не проверка
формата (`.claude/rules/deployment.md`, «Проверка сторожа сторожей»).
Положительный контроль
:meth:`LiveFormsOfTheArtifact.test_integer_labels_are_the_2026_10_13_outage`
воспроизводит аварию дословно — артефакт с целыми ярлыками — и обязан краснеть
на дереве до правки (замерено: проба на копии читателя с `origin/main`
sha 60962dcb1e26 давала `not_satisfied`, 33 записи из 34 вне канона).
"""
# FROZEN-DATE-OK: injected-clock — обе стороны сравнения возраста закреплены:
# якорь `_ANCHOR` подставляется в `generated_at` артефакта (`_doc`) И передаётся
# пробе аргументом `now=` (`_probe`), поэтому ни один вердикт здесь не зависит
# ни от календаря машины, ни от длительности прогона.
from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.monitoring import card_acceptance as ca
from spa_core import telegram_protocols_reporter as reporter

PROBE_NAME = "owner_protocols_report_groups_by_canonical_tier"

#: Якорь времени. Литерал здесь — ПРЕДМЕТ сравнения, а не стенные часы.
_ANCHOR = datetime(2026, 10, 13, 12, 0, 0, tzinfo=timezone.utc)


def _record(name: str, tier: object, apy: float = 4.0, **extra: object) -> dict:
    """Запись раздела в той форме, какую пишет `adapter_orchestrator`."""
    row: dict = {"display_name": name, "apy": apy, "live_apy": apy,
                 "live_apy_fresh": True}
    if tier is not _NO_TIER:
        row["tier"] = tier
    row.update(dict(extra))
    return row


#: «Поля `tier` нет вовсе» — отдельный вход фикстуры, а не пустая строка.
_NO_TIER = object()


def _doc(section: object, *, age_hours: float = 1.0, **top: object) -> dict:
    """Артефакт с ОБЪЯВЛЕННЫМ возрастом (разница от `_ANCHOR`)."""
    made = _ANCHOR - timedelta(hours=age_hours)
    doc: dict = {
        "generated_at": made.isoformat(),
        "schema_version": "3",
        "adapters": section,
    }
    doc.update(top)
    return doc


def _probe(doc: dict, *, now: datetime | None = None) -> tuple[str, str]:
    """Прогнать пробу ЧЕРЕЗ РЕЕСТР на одноразовом каталоге данных."""
    with TemporaryDirectory() as tmp:
        (Path(tmp) / "adapter_status.json").write_text(
            json.dumps(doc), encoding="utf-8"
        )
        return ca.PROBES[PROBE_NAME](None, data_dir=tmp, now=now or _ANCHOR)


def _headings(doc: dict) -> list[str]:
    """Заголовки разделов отчёта — строка целиком в звёздочках, кроме `System`."""
    out: list[str] = []
    for line in reporter.format_protocols_message(doc).splitlines():
        s = line.strip()
        if len(s) > 2 and s.startswith("*") and s.endswith("*") and s != "*System*":
            out.append(s[1:-1])
    return out


def _shown(doc: dict) -> int:
    """Сколько строк протоколов НАСТОЯЩИЙ отчёт печатает владельцу."""
    return sum(
        1
        for line in reporter.format_protocols_message(doc).splitlines()
        if line.startswith("•")
    )


# ──────────────────────── звено 1: таблица форм ПРОИЗВОДИТСЯ ────────────────


class TierFormsAreDerivedFromTheCanon(unittest.TestCase):
    """Звено 1 — таблица форм производится из `_TIER_ORDER`, а не объявляется.

    Сломано ⇒ второй литеральный перечень тиров, который разойдётся с первым
    молча (класс ADR-710/ADR-712: два объявления одного контракта).
    """

    def test_every_canonical_tier_is_its_own_form(self):
        """ЗВЕНО: канонический ярлык читается сам собой."""
        for tier in reporter._TIER_ORDER:
            self.assertEqual(reporter.canonical_tier(tier), tier)

    def test_numeric_tiers_also_claim_the_bare_digit(self):
        """ЗВЕНО: `T<цифра>` встречается в артефакте голой цифрой (замер 13.10)."""
        self.assertEqual(reporter.canonical_tier(1), "T1")
        self.assertEqual(reporter.canonical_tier(2), "T2")
        self.assertEqual(reporter.canonical_tier(3), "T3")
        self.assertEqual(reporter.canonical_tier("2"), "T2")

    def test_conditional_tiers_do_not_claim_a_digit(self):
        """ЗВЕНО: цифра НЕ выдумывается там, где канон её не несёт.

        `T1-conditional` голой единицей не записан нигде, и притязать на неё он
        не вправе: единица уже принадлежит `T1`, а два притязания на одну форму
        решались бы порядком литерала.
        """
        forms = reporter._build_tier_forms(["T1-conditional"])
        self.assertEqual(forms, {"T1-CONDITIONAL": "T1-conditional"})

    def test_a_new_tier_in_the_order_gets_forms_without_a_second_edit(self):
        """ЗВЕНО: производство, а не перечисление — новый тир приходит сам."""
        self.assertEqual(
            reporter._build_tier_forms(["T7"]), {"T7": "T7", "7": "T7"}
        )

    def test_colliding_forms_are_refused_loudly(self):
        """ЗВЕНО (обратная сторона): столкновение форм — ОТКАЗ, не победитель.

        Молчаливый победитель решал бы, под каким заголовком владелец читает
        протокол, порядком строк в литерале.
        """
        with self.assertRaises(ValueError) as caught:
            reporter._build_tier_forms(["T1", "1"])
        self.assertIn("притязает на два", str(caught.exception))

    def test_the_live_table_has_no_collisions(self):
        """ЗВЕНО: сам канон дерева собирается (значит, столкновений в нём нет)."""
        table = reporter._build_tier_forms(reporter._TIER_ORDER)
        self.assertEqual(set(table.values()), set(reporter._TIER_ORDER))


# ──────────────── звено 2: форма, которую канон НЕ читает ───────────────────


class UnknownFormsAreRefusedNotGuessed(unittest.TestCase):
    """Звено 2 — непрочитанная форма даёт ``None``, а не догадку.

    Сломано ⇒ тихая подстановка: ровно то, чем жил дефект (`"T2"` по умолчанию).
    """

    def test_unknown_string_is_none(self):
        """ЗВЕНО: `T4-CUSTOM` канон не знает."""
        self.assertIsNone(reporter.canonical_tier("T4-CUSTOM"))

    def test_absent_value_is_none(self):
        """ЗВЕНО: `None` — не тир."""
        self.assertIsNone(reporter.canonical_tier(None))

    def test_boolean_is_not_tier_one(self):
        """ЗВЕНО: `True` в Python есть целое 1 — и тиром быть не вправе."""
        self.assertIsNone(reporter.canonical_tier(True))

    def test_float_is_not_accepted_without_a_measurement(self):
        """ЗВЕНО: `2.0` никто в артефакте не мерил — форма не принимается."""
        self.assertIsNone(reporter.canonical_tier(2.0))

    def test_list_is_not_a_tier(self):
        """ЗВЕНО: составное значение — не ярлык."""
        self.assertIsNone(reporter.canonical_tier(["T1"]))

    def test_case_and_space_do_not_change_the_answer(self):
        """ЗВЕНО: регистр и пробелы — не предмет (`" t2 "` = T2)."""
        self.assertEqual(reporter.canonical_tier(" t2 "), "T2")
        self.assertEqual(reporter.canonical_tier("t1-CONDITIONAL"), "T1-conditional")


# ──────────────────────── звено 3: перепись группировки ─────────────────────


class CensusGroupsAndCounts(unittest.TestCase):
    """Звено 3 — перепись: порядок из канона, третий исход назван числом."""

    def test_sections_follow_the_canonical_order_not_insertion_order(self):
        """ЗВЕНО: порядок разделов приходит из `_TIER_ORDER`.

        Записи поданы в ОБРАТНОМ порядке (T3, T2, T1): если порядок разделов
        брался бы у обхода словаря, тест покраснел бы.
        """
        doc = _doc({
            "c": _record("C", 3),
            "b": _record("B", 2),
            "a": _record("A", 1),
        })
        census = reporter.tier_grouping_census(doc)
        self.assertEqual([t for t, _ in census["sections"]], ["T1", "T2", "T3"])

    def test_conditional_tiers_keep_their_canonical_place_not_alphabet(self):
        """ЗВЕНО: порядок — КАНОН, а не алфавит.

        В `_TIER_ORDER` условный T2 стои́т ПЕРЕД обычным T2, а T3-SPEC — перед
        T3. Сортировка по алфавиту дала бы обратное, и на тройке T1/T2/T3 это
        было бы неотличимо: выбор «канон или алфавит» видно только здесь.
        """
        doc = _doc({
            "a": _record("A", "T3"),
            "b": _record("B", "T3-SPEC"),
            "c": _record("C", "T2"),
            "d": _record("D", "T2-conditional"),
        })
        census = reporter.tier_grouping_census(doc)
        self.assertEqual(
            [t for t, _ in census["sections"]],
            ["T2-conditional", "T2", "T3-SPEC", "T3"],
        )

    def test_record_without_a_tier_is_not_silently_tier_two(self):
        """ЗВЕНО (обратная сторона, инв. #17): отсутствие ≠ T2.

        Прежний код подставлял `"T2"` по умолчанию, и запись без объявленного
        тира читалась владельцу как протокол второго тира.
        """
        doc = _doc({"x": _record("X", _NO_TIER)})
        census = reporter.tier_grouping_census(doc)
        self.assertEqual(census["sections"], [])
        self.assertEqual(census["undeclared_count"], 1)
        self.assertEqual(census["forms_outside_canon"], ["поля `tier` нет"])

    def test_unknown_form_lands_outside_the_canon_with_its_form_named(self):
        """ЗВЕНО: форма, которую канон не читает, названа, а не спрятана."""
        doc = _doc({"x": _record("X", "T4-CUSTOM")})
        census = reporter.tier_grouping_census(doc)
        self.assertEqual(census["undeclared_count"], 1)
        self.assertEqual(census["forms_outside_canon"], ["'T4-CUSTOM'"])

    def test_measured_zero_is_a_number(self):
        """ЗВЕНО: ноль вне канона есть ИЗМЕРЕННЫЙ ноль при непустом населении."""
        doc = _doc({"a": _record("A", 1), "b": _record("B", 2)})
        census = reporter.tier_grouping_census(doc)
        self.assertEqual(census["undeclared_count"], 0)
        self.assertEqual(census["records"], 2)

    def test_empty_artifact_is_zero_records_not_zero_outside(self):
        """ЗВЕНО: пустой артефакт — это НЕ «измерено и равно нулю»."""
        census = reporter.tier_grouping_census(_doc({}))
        self.assertEqual(census["records"], 0)
        self.assertEqual(census["undeclared_count"], 0)

    def test_no_record_is_lost_by_grouping(self):
        """ЗВЕНО: сумма разделов и остатка равна населению читателя."""
        doc = _doc({
            "a": _record("A", 1),
            "b": _record("B", "T4-CUSTOM"),
            "c": _record("C", _NO_TIER),
            "d": _record("D", 3),
        })
        census = reporter.tier_grouping_census(doc)
        grouped = sum(len(r) for _t, r in census["sections"])
        self.assertEqual(grouped + census["undeclared_count"], census["records"])
        self.assertEqual(census["records"], len(reporter._get_all_adapters(doc)))


# ──────────────── звено 4: что владелец ЧИТАЕТ (исход у двери) ──────────────


class LiveFormsOfTheArtifact(unittest.TestCase):
    """Звено 4 — исход у двери владельца на ЖИВЫХ формах артефакта."""

    def test_integer_labels_are_the_2026_10_13_outage(self):
        """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: авария 13.10 дословно.

        Шесть записей с целым `1`, 23 с `2`, 4 с `3` и одна со строкой `"T1"` —
        ровно живой артефакт того дня. До правки владелец читал `*1*`, `*2*`,
        `*3*`, а тир T1 выходил ДВУМЯ разделами.
        """
        section = {}
        for i in range(6):
            section[f"one{i}"] = _record(f"One{i}", 1)
        for i in range(23):
            section[f"two{i}"] = _record(f"Two{i}", 2)
        for i in range(4):
            section[f"three{i}"] = _record(f"Three{i}", 3)
        section["sky_susds"] = _record("Sky/sUSDS", "T1")
        doc = _doc(section)

        heads = _headings(doc)
        self.assertEqual(heads, [
            reporter._TIER_LABEL["T1"],
            reporter._TIER_LABEL["T2"],
            reporter._TIER_LABEL["T3"],
        ])
        self.assertNotIn("1", heads)
        self.assertEqual(_shown(doc), 34)

    def test_one_tier_is_one_section(self):
        """ЗВЕНО: смешанные формы ОДНОГО тира не дают двух разделов.

        Замер 13.10: `"T1"` и `1` соседствовали в одном артефакте, и владелец
        читал T1 дважды.
        """
        doc = _doc({"a": _record("A", "T1"), "b": _record("B", 1)})
        self.assertEqual(_headings(doc), [reporter._TIER_LABEL["T1"]])

    def test_outside_canon_is_one_named_section_carrying_the_count(self):
        """ЗВЕНО: остаток — ОДИН названный раздел с числом и формами."""
        doc = _doc({
            "a": _record("A", 1),
            "x": _record("X", "T4-CUSTOM"),
            "y": _record("Y", _NO_TIER),
        })
        heads = _headings(doc)
        self.assertEqual(len(heads), 2)
        self.assertEqual(heads[0], reporter._TIER_LABEL["T1"])
        self.assertIn("2", heads[1])
        self.assertIn("T4-CUSTOM", heads[1])
        self.assertEqual(_shown(doc), 3)

    def test_the_old_raw_heading_is_gone(self):
        """ЗВЕНО (обратная сторона): ярлык-сырьё заголовком больше не бывает."""
        doc = _doc({"a": _record("A", 2)})
        self.assertNotIn("2", _headings(doc))

    def test_system_line_always_carries_the_measured_zero(self):
        """ЗВЕНО: число вне канона печатается ВСЕГДА, включая ноль."""
        clean = reporter.format_protocols_message(_doc({"a": _record("A", 1)}))
        self.assertIn("Тиры вне канона: 0", clean)
        dirty = reporter.format_protocols_message(
            _doc({"x": _record("X", "T4-CUSTOM")})
        )
        self.assertIn("Тиры вне канона: 1", dirty)

    def test_unknown_tier_record_still_reaches_the_owner(self):
        """ЗВЕНО: непрочитанный ярлык не прячет ЗАПИСЬ — только называет форму."""
        doc = _doc({"x": _record("Strange Proto", "T4-CUSTOM")})
        self.assertIn("Strange Proto", reporter.format_protocols_message(doc))


# ───────────────────────── звено 5: проба приёмки ───────────────────────────


class ProbeIsRedOnEachBrokenLink(unittest.TestCase):
    """Звено 5 — проба меряет исход и краснеет на КАЖДОМ порванном звене."""

    def test_probe_is_green_on_canonical_grouping(self):
        """ЗВЕНО: живые формы (целые) после правки дают `satisfied`."""
        doc = _doc({"a": _record("A", 1), "b": _record("B", 2), "c": _record("C", 3)})
        verdict, detail = _probe(doc)
        self.assertEqual(verdict, ca.SATISFIED, detail)

    def test_probe_is_red_when_a_form_is_outside_the_canon(self):
        """ЗВЕНО: запись под неканоническим заголовком ⇒ `not_satisfied`."""
        doc = _doc({"a": _record("A", 1), "x": _record("X", "T4-CUSTOM")})
        verdict, detail = _probe(doc)
        self.assertEqual(verdict, ca.NOT_SATISFIED, detail)
        self.assertIn("вне канона", detail)

    def test_probe_is_red_when_a_record_has_no_tier_at_all(self):
        """ЗВЕНО: тихая подстановка T2 больше не проходит мимо пробы."""
        doc = _doc({"a": _record("A", 1), "y": _record("Y", _NO_TIER)})
        self.assertEqual(_probe(doc)[0], ca.NOT_SATISFIED)

    def test_probe_does_not_pass_by_substring(self):
        """ЗВЕНО (ADR-333): имя протокола, совпавшее с ярлыком, вердикт не красит.

        Запись названа ровно как канонический заголовок T2 и при этом стои́т вне
        канона. Проба, искавшая бы текст, позеленела бы; эта считает ЧИСЛА.
        """
        doc = _doc({"x": _record(reporter._TIER_LABEL["T2"], "T4-CUSTOM")})
        self.assertEqual(_probe(doc)[0], ca.NOT_SATISFIED)

    def test_probe_is_unmeasured_when_the_artifact_is_absent(self):
        """ЗВЕНО: третий исход — артефакта нет."""
        with TemporaryDirectory() as tmp:
            verdict, detail = ca.PROBES[PROBE_NAME](None, data_dir=tmp, now=_ANCHOR)
        self.assertEqual(verdict, ca.UNMEASURED, detail)

    def test_probe_is_unmeasured_when_the_artifact_is_stale(self):
        """ЗВЕНО: третий исход — замороженный канон, а не наблюдение."""
        doc = _doc({"a": _record("A", 1)}, age_hours=ca.ADAPTER_STATUS_MAX_AGE_H + 1)
        verdict, detail = _probe(doc)
        self.assertEqual(verdict, ca.UNMEASURED, detail)
        self.assertIn("протух", detail)

    def test_probe_is_unmeasured_when_there_are_no_records(self):
        """ЗВЕНО: ноль вне канона из ПУСТОГО артефакта не считается замером."""
        verdict, detail = _probe(_doc({}))
        self.assertEqual(verdict, ca.UNMEASURED, detail)
        self.assertIn("НЕ ИЗМЕРЕН", detail)

    def test_probe_is_unmeasured_when_population_is_broken(self):
        """ЗВЕНО: население — одной копией, у соседней пробы.

        Член раздела, не являющийся записью, роняет население; группировку
        записей, не доехавших до владельца, судить нечем ⇒ третий исход, а не
        зелёный ноль по остатку.
        """
        doc = _doc({"a": _record("A", 1), "broken": "это не запись"})
        verdict, detail = _probe(doc)
        self.assertEqual(verdict, ca.UNMEASURED, detail)
        self.assertIn("население", detail)

    def test_probe_is_red_when_the_order_of_canonical_sections_is_wrong(self):
        """ЗВЕНО: порядок разделов. Сломано ⇒ канон объявлен и не действует.

        Порядок приходит из переписи, поэтому сломать его данными нельзя — и
        именно поэтому звено проверяется ПОДМЕНОЙ выдачи читателя: иначе ветка
        вердикта про порядок не исполнялась бы ни одним тестом, то есть была бы
        написана и не позвана.
        """
        doc = _doc({"a": _record("A", 1), "b": _record("B", 2)})
        upside_down = "\n".join([
            "📊 *SPA Protocol Status* — now",
            "",
            f"*{reporter._TIER_LABEL['T2']}*",
            "• *B* — 4.0%",
            "",
            f"*{reporter._TIER_LABEL['T1']}*",
            "• *A* — 4.0%",
            "",
            "*System*",
            "Capital: $100,000 | Total adapters: 2 | Тиры вне канона: 0",
        ])
        with mock.patch.object(
            reporter, "format_protocols_message", return_value=upside_down
        ):
            verdict, detail = _probe(doc)
        self.assertEqual(verdict, ca.NOT_SATISFIED, detail)
        self.assertIn("порядок", detail)

    def test_probe_is_registered_under_its_name(self):
        """ЗВЕНО: проба, потерявшая регистрацию, не измеряет ничего."""
        self.assertIn(PROBE_NAME, ca.PROBES)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
