"""Контроль прибора «цена НЕИЗМЕРЕННОГО критерия §49» (заказ G93 п. 1, ADR-506).

Каждый тест — положительный контроль на КОНКРЕТНЫЙ способ соврать, а не проверка
того, что функция «что-то возвращает». Разделительная линия всей батареи одна:
**пять исходов чинятся разным**, поэтому склейка любых двух из них есть дефект,
а не огрубление.

Часы здесь — ВХОД, а не окружение: см. пометку под docstring.
"""
# FROZEN-DATE-OK: injected-clock — якорь NOW передаётся каждому замеру аргументом
# `now=`, а отметки артефактов выводятся из него же (`NOW - timedelta(...)`);
# обе стороны закреплены, стенные часы здесь не спрашиваются ни разу.
# LLM_FORBIDDEN
from __future__ import annotations

import datetime as dt
import json
import os
import unittest

from spa_core.monitoring.s49_criterion_price import (
    CANONICAL_FORM,
    DECISION,
    MANIFEST_REL,
    PRODUCER,
    TRANSCRIPTION,
    UNMEASURED,
    WORDING,
    Unmeasured,
    measure,
    parse_bindings,
    price_of,
    read_manifest,
)

#: Якорь времени батареи. Значение произвольно и намеренно не «сегодня»: тест,
#: зависящий от календаря, краснеет от того, что сдвинулся день.
NOW = dt.datetime(2026, 9, 29, 12, 0, tzinfo=dt.timezone.utc)


def _artifact(entry_path: str, *, notes: str | None = None, slo=None,
              status: str = "active") -> dict:
    entry = {"path": entry_path, "producer": "com.spa.someone",
             "consumers": ["orchestrator_protocol"], "status": status}
    if notes is not None:
        entry["notes"] = notes
    if slo is not None:
        entry["slo_hours"] = slo
    return entry


def _manifest(*entries: dict) -> dict:
    return {"schema_version": 1, "artifacts": list(entries)}


class ParseBindings(unittest.TestCase):
    """Разбор привязки «критерий → артефакт» из прозы конституции."""

    def test_canonical_backtick_form_binds(self):
        parsed = parse_bindings(_manifest(_artifact(
            "data/a.json", notes="Критерий §49 `Economics` приказа владельца")))
        self.assertEqual(["data/a.json"],
                         [e["path"] for e in parsed["bindings"]["Economics"]])
        self.assertEqual(CANONICAL_FORM, parsed["bindings"]["Economics"][0]["form"])
        self.assertEqual([], parsed["unparsed"])

    def test_paren_form_binds_the_criterion_and_not_the_order_name(self):
        """«§49 ТЗ «Portfolio CIO» (Costs: …)» — критерий Costs, а НЕ Portfolio CIO.

        Промах здесь был бы двойным одним движением: привязка ушла бы в сироту
        под именем приказа, а критерий `Costs` остался бы без меры.

        Защищает от него НЕ порядок форм, а ЯКОРЬ (`match`, не `search`): каждая
        формулировка обязана начаться сразу после `§49`. Перестановка форм
        местами вердикта не меняет — это проверено мутацией и названо вслух, а
        не предположено (см. `FormsAreAnchored` ниже).
        """
        parsed = parse_bindings(_manifest(_artifact(
            "data/c.json",
            notes="§49 ТЗ «Portfolio CIO» (Costs: gas, fees, slippage accounted)")))
        self.assertIn("Costs", parsed["bindings"])
        self.assertNotIn("Portfolio CIO", parsed["bindings"])
        self.assertEqual("paren", parsed["bindings"]["Costs"][0]["form"])

    def test_quoted_form_binds(self):
        parsed = parse_bindings(_manifest(_artifact(
            "data/m.json", notes="§49 «Marginal return» ТЗ «Portfolio CIO»")))
        self.assertIn("Marginal return", parsed["bindings"])
        self.assertEqual("quoted", parsed["bindings"]["Marginal return"][0]["form"])

    def test_an_unrecognised_wording_lands_in_unparsed_with_its_address(self):
        """Непонятая формулировка НЕ пропускается молча — иначе привязка исчезает.

        Разбор, умеющий пропустить непонятное, врал бы тихо: население привязок
        стало бы короче, и ни один сторож этого не сказал бы.
        """
        parsed = parse_bindings(_manifest(_artifact(
            "data/x.json", notes="см. §49 приказа, критерий про издержки")))
        self.assertEqual({}, parsed["bindings"])
        self.assertEqual(1, len(parsed["unparsed"]))
        self.assertEqual("data/x.json", parsed["unparsed"][0]["path"])
        self.assertIn("§49", parsed["unparsed"][0]["snippet"])

    def test_notes_without_the_section_mark_are_not_scanned_at_all(self):
        parsed = parse_bindings(_manifest(_artifact(
            "data/y.json", notes="обычная заметка про `Economics` без ссылки")))
        self.assertEqual({}, parsed["bindings"])
        self.assertEqual([], parsed["unparsed"])

    def test_several_mentions_in_one_note_are_all_read(self):
        parsed = parse_bindings(_manifest(_artifact(
            "data/z.json",
            notes="§49 `Economics` и заодно §49 `Persistence` — обе меры тут")))
        self.assertEqual({"Economics", "Persistence"}, set(parsed["bindings"]))

    def test_missing_artifacts_list_is_unmeasured_not_zero_bindings(self):
        with self.assertRaises(Unmeasured) as caught:
            parse_bindings({"schema_version": 1})
        self.assertIn("artifacts", str(caught.exception))

    def test_a_non_dict_member_stops_the_parse_loudly(self):
        with self.assertRaises(Unmeasured):
            parse_bindings({"artifacts": [_artifact("data/a.json"), "мусор"]})

    def test_an_artifact_without_path_stops_the_parse_loudly(self):
        with self.assertRaises(Unmeasured) as caught:
            parse_bindings({"artifacts": [{"notes": "§49 `Economics`"}]})
        self.assertIn("path", str(caught.exception))


class FormsAreAnchored(unittest.TestCase):
    """Форма обязана начинаться СРАЗУ после `§49` — иначе привязкой станет фон.

    Это та самая претензия, которую первая редакция батареи приписала ПОРЯДКУ
    форм. Мутация «переставить формы местами» выжила и была права: формы
    взаимоисключительны по первому значащему символу (`ТЗ`, обратная кавычка,
    ёлочка), поэтому порядок им безразличен. Работает якорь, и стеречь надо его.
    """

    def test_a_backtick_far_from_the_mark_is_not_a_binding(self):
        """`Economics` в ТЕКСТЕ заметки — упоминание, а не объявление меры.

        Замени якорный `match` на `search`, и прибор объявил бы мерой критерия
        первый попавшийся термин в кавычках — привязка появилась бы из фона.
        """
        parsed = parse_bindings(_manifest(_artifact(
            "data/f.json",
            notes="§49 — подробности в ADR, см. `Economics` в тексте ниже")))
        self.assertEqual({}, parsed["bindings"])
        self.assertEqual(1, len(parsed["unparsed"]))

    def test_each_declared_wording_is_matched_by_exactly_one_form(self):
        """Взаимоисключительность — свойство ИЗМЕРЕННОЕ, а не обещанное."""
        samples = {
            "backtick": "§49 `Economics` приказа",
            "paren": "§49 ТЗ «Portfolio CIO» (Costs: издержки)",
            "quoted": "§49 «Marginal return» ТЗ «Portfolio CIO»",
        }
        for expected, note in samples.items():
            parsed = parse_bindings(_manifest(_artifact("data/s.json", notes=note)))
            forms = [e["form"] for entries in parsed["bindings"].values()
                     for e in entries]
            self.assertEqual([expected], forms, msg=note)


class ReadManifest(unittest.TestCase):
    def setUp(self):
        self.tree = self.enterContext(__import__("tempfile").TemporaryDirectory())
        os.makedirs(os.path.join(self.tree, os.path.dirname(MANIFEST_REL)))

    def _write(self, text: str):
        with open(os.path.join(self.tree, MANIFEST_REL), "w", encoding="utf-8") as fh:
            fh.write(text)

    def test_absent_manifest_is_unmeasured(self):
        with self.assertRaises(Unmeasured) as caught:
            read_manifest(self.tree)
        self.assertIn("НЕ СКАЗАНО НИЧЕГО", str(caught.exception))

    def test_broken_json_is_unmeasured_not_empty(self):
        self._write("{не json")
        with self.assertRaises(Unmeasured):
            read_manifest(self.tree)

    def test_a_list_at_top_level_is_unmeasured(self):
        self._write("[]")
        with self.assertRaises(Unmeasured):
            read_manifest(self.tree)

    def test_a_well_formed_manifest_is_read(self):
        self._write(json.dumps(_manifest(_artifact("data/a.json"))))
        self.assertIn("artifacts", read_manifest(self.tree))


class PriceOfOne(unittest.TestCase):
    """Цена одного критерия: пять исходов, и ни один не поглощает другой."""

    def setUp(self):
        self.data = self.enterContext(__import__("tempfile").TemporaryDirectory())

    def _put(self, name: str, *, age_hours: float | None = 1.0,
             stamp_field: str = "generated_at", raw: str | None = None):
        path = os.path.join(self.data, name)
        if raw is not None:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(raw)
            return path
        doc: dict = {"overall": "OK"}
        if age_hours is not None:
            doc[stamp_field] = (NOW - dt.timedelta(hours=age_hours)).isoformat()
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(doc, fh)
        return path

    def _parsed(self, notes: str, *, slo=12, path: str = "data/a.json"):
        return parse_bindings(_manifest(_artifact(path, notes=notes, slo=slo)))

    def test_live_artifact_in_canonical_form_costs_one_field(self):
        self._put("a.json", age_hours=1.0)
        row = price_of("Economics", self._parsed("§49 `Economics`"),
                       data_dir=self.data, now=NOW)
        self.assertEqual(TRANSCRIPTION, row["price"])
        self.assertEqual("data/a.json", row["artifact"])
        self.assertAlmostEqual(1.0, row["age_hours"], places=6)

    def test_live_artifact_in_another_wording_is_a_separate_price(self):
        """WORDING ≠ TRANSCRIPTION: у читателя две формулировки одного утверждения.

        Слить их значило бы спрятать находку — конституция говорит одно и то же
        двумя способами, и любой разбирающий обязан угадывать, какой из них канон.
        """
        self._put("a.json", age_hours=1.0)
        row = price_of("Costs", self._parsed('§49 ТЗ «Portfolio CIO» (Costs: …)'),
                       data_dir=self.data, now=NOW)
        self.assertEqual(WORDING, row["price"])
        self.assertEqual("paren", row["form"])
        self.assertIn(CANONICAL_FORM, row["detail"])

    def test_absent_artifact_is_the_producers_price_not_the_fields(self):
        row = price_of("Economics", self._parsed("§49 `Economics`"),
                       data_dir=self.data, now=NOW)
        self.assertEqual(PRODUCER, row["price"])
        self.assertIsNone(row["age_hours"])

    def test_stale_artifact_is_the_producers_price(self):
        self._put("a.json", age_hours=13.0)
        row = price_of("Economics", self._parsed("§49 `Economics`", slo=12),
                       data_dir=self.data, now=NOW)
        self.assertEqual(PRODUCER, row["price"])
        self.assertIn("протух", row["detail"])

    def test_liveness_dominates_wording(self):
        """Артефакт, которого нет, не дешевеет оттого, что о нём красиво написано."""
        row = price_of("Costs", self._parsed('§49 ТЗ «Portfolio CIO» (Costs: …)'),
                       data_dir=self.data, now=NOW)
        self.assertEqual(PRODUCER, row["price"])

    def test_age_exactly_at_the_limit_is_still_alive(self):
        self._put("a.json", age_hours=12.0)
        row = price_of("Economics", self._parsed("§49 `Economics`", slo=12),
                       data_dir=self.data, now=NOW)
        self.assertEqual(TRANSCRIPTION, row["price"])

    def test_a_hair_past_the_limit_is_stale(self):
        self._put("a.json", age_hours=12.001)
        row = price_of("Economics", self._parsed("§49 `Economics`", slo=12),
                       data_dir=self.data, now=NOW)
        self.assertEqual(PRODUCER, row["price"])

    def test_the_clock_is_an_input_and_the_same_fixture_flips_with_it(self):
        """Доказательство, что часы ИНЪЕКТИРОВАНЫ, а не подсмотрены у машины.

        Одна и та же отметка на диске даёт `TRANSCRIPTION` при одном `now` и
        `PRODUCER` при другом. Уронивший проброс код краснеет на ЛЮБОМ хосте.
        """
        self._put("a.json", age_hours=1.0)
        parsed = self._parsed("§49 `Economics`", slo=12)
        self.assertEqual(TRANSCRIPTION,
                         price_of("Economics", parsed, data_dir=self.data,
                                  now=NOW)["price"])
        self.assertEqual(PRODUCER,
                         price_of("Economics", parsed, data_dir=self.data,
                                  now=NOW + dt.timedelta(hours=24))["price"])

    def test_missing_slo_is_unmeasured_not_alive(self):
        """`slo_hours` нет ⇒ сравнивать НЕ С ЧЕМ. Назвать это «жив» = fail-OPEN."""
        self._put("a.json", age_hours=1.0)
        row = price_of("Economics", self._parsed("§49 `Economics`", slo=None),
                       data_dir=self.data, now=NOW)
        self.assertEqual(UNMEASURED, row["price"])
        self.assertIsNotNone(row["age_hours"])

    def test_artifact_without_a_timestamp_is_unmeasured_not_stale(self):
        self._put("a.json", age_hours=None)
        row = price_of("Economics", self._parsed("§49 `Economics`"),
                       data_dir=self.data, now=NOW)
        self.assertEqual(UNMEASURED, row["price"])
        self.assertIn("украшение", row["detail"])

    def test_artifact_with_a_foreign_timestamp_field_is_unmeasured(self):
        self._put("a.json", age_hours=1.0, stamp_field="checked_at")
        self.assertEqual(UNMEASURED,
                         price_of("Economics", self._parsed("§49 `Economics`"),
                                  data_dir=self.data, now=NOW)["price"])

    def test_unreadable_artifact_is_unmeasured_not_absent(self):
        self._put("a.json", raw="{сломано")
        row = price_of("Economics", self._parsed("§49 `Economics`"),
                       data_dir=self.data, now=NOW)
        self.assertEqual(UNMEASURED, row["price"])

    def test_unnamed_data_dir_is_unmeasured_not_producer(self):
        """«Не спрашивали» ≠ «артефакта нет». Иначе молчат ВСЕ производители разом."""
        row = price_of("Economics", self._parsed("§49 `Economics`"),
                       data_dir=None, now=NOW)
        self.assertEqual(UNMEASURED, row["price"])
        self.assertIn("НЕ СПРОШЕНО", row["detail"])

    def test_a_missing_data_dir_is_unmeasured_not_producer(self):
        row = price_of("Economics", self._parsed("§49 `Economics`"),
                       data_dir=os.path.join(self.data, "нет-такого"), now=NOW)
        self.assertEqual(UNMEASURED, row["price"])
        self.assertIn("не у того дерева", row["detail"])

    def test_no_binding_at_all_is_a_decision_not_a_missing_field(self):
        row = price_of("Auditability", self._parsed("§49 `Economics`"),
                       data_dir=self.data, now=NOW)
        self.assertEqual(DECISION, row["price"])
        self.assertIsNone(row["artifact"])

    def test_an_unparsed_mention_blocks_the_decision_verdict(self):
        """«Привязки нет» и «спросили не той формой» здесь НЕРАЗЛИЧИМЫ — и это сказано.

        Объявить `DECISION` при неразобранном упоминании значило бы выдать
        «наблюдателя нет» за измеренный факт, тогда как измерена была лишь
        неудача разбора.
        """
        parsed = parse_bindings(_manifest(
            _artifact("data/x.json", notes="см. §49 про аудит", slo=12)))
        row = price_of("Auditability", parsed, data_dir=self.data, now=NOW)
        self.assertEqual(UNMEASURED, row["price"])
        self.assertIn("НЕРАЗЛИЧИМЫ", row["detail"])

    def test_two_artifacts_on_one_criterion_collide_loudly(self):
        parsed = parse_bindings(_manifest(
            _artifact("data/a.json", notes="§49 `Economics`", slo=12),
            _artifact("data/b.json", notes="§49 `Economics`", slo=12)))
        row = price_of("Economics", parsed, data_dir=self.data, now=NOW)
        self.assertEqual(UNMEASURED, row["price"])
        self.assertIn("data/a.json", row["detail"])
        self.assertIn("data/b.json", row["detail"])

    def test_every_row_carries_the_same_keys_whatever_the_outcome(self):
        """Читатель — машина: исчезнувший ключ читается как `None`, а не как отказ."""
        self._put("a.json", age_hours=1.0)
        parsed = self._parsed("§49 `Economics`")
        keys = None
        for criterion in ("Economics", "Auditability"):
            row = price_of(criterion, parsed, data_dir=self.data, now=NOW)
            if keys is None:
                keys = set(row)
            self.assertEqual(keys, set(row), msg=f"строка {criterion} другой формы")


class MeasureMany(unittest.TestCase):
    def setUp(self):
        self.tree = self.enterContext(__import__("tempfile").TemporaryDirectory())
        self.data = os.path.join(self.tree, "data")
        os.makedirs(self.data)
        os.makedirs(os.path.join(self.tree, os.path.dirname(MANIFEST_REL)))

    def _manifest_file(self, *entries: dict):
        with open(os.path.join(self.tree, MANIFEST_REL), "w", encoding="utf-8") as fh:
            json.dump(_manifest(*entries), fh)

    def _put(self, name: str, age_hours: float = 1.0):
        with open(os.path.join(self.data, name), "w", encoding="utf-8") as fh:
            json.dump({"generated_at":
                       (NOW - dt.timedelta(hours=age_hours)).isoformat()}, fh)

    def test_population_is_the_callers_not_the_modules(self):
        """«Десять» нигде не зашито: спросили про двоих — ответ про двоих."""
        self._manifest_file(_artifact("data/a.json", notes="§49 `Economics`", slo=12))
        report = measure(["Economics", "Auditability"], repo_root=self.tree,
                         data_dir=self.data, now=NOW)
        self.assertEqual(2, len(report["rows"]))

    def test_orphan_binding_is_judged_against_the_full_population(self):
        """Сирота меряется ПОЛНЫМ населением §49, а не подмножеством без мерки.

        Иначе привязка критерия, у которого мерка УЖЕ есть, попала бы в находку,
        а настоящая сирота потерялась бы среди ложных.
        """
        self._manifest_file(
            _artifact("data/a.json", notes="§49 `Economics`", slo=12),
            _artifact("data/b.json", notes="§49 `Risk`", slo=12),
            _artifact("data/c.json", notes="§49 `Forecast accuracy`", slo=12))
        report = measure(["Economics"], repo_root=self.tree, data_dir=self.data,
                         population=["Economics", "Risk"], now=NOW)
        self.assertEqual({"Forecast accuracy": ["data/c.json"]},
                         report["orphan_bindings"])

    def test_without_a_population_the_priced_subset_is_used_and_it_is_wider(self):
        self._manifest_file(
            _artifact("data/a.json", notes="§49 `Economics`", slo=12),
            _artifact("data/b.json", notes="§49 `Risk`", slo=12))
        report = measure(["Economics"], repo_root=self.tree, data_dir=self.data,
                         now=NOW)
        self.assertIn("Risk", report["orphan_bindings"])

    def test_counts_add_up_to_the_population(self):
        self._manifest_file(
            _artifact("data/a.json", notes="§49 `Economics`", slo=12),
            _artifact("data/b.json", notes="§49 `Risk`", slo=12))
        self._put("a.json")
        report = measure(["Economics", "Risk", "Auditability"], repo_root=self.tree,
                         data_dir=self.data, now=NOW)
        self.assertEqual(3, sum(report["counts"].values()))
        self.assertEqual({TRANSCRIPTION: 1, PRODUCER: 1, DECISION: 1},
                         report["counts"])

    def test_unreadable_manifest_raises_rather_than_reporting_zero_prices(self):
        with self.assertRaises(Unmeasured):
            measure(["Economics"], repo_root=self.tree, data_dir=self.data, now=NOW)

    def test_unparsed_mentions_travel_to_the_report(self):
        self._manifest_file(_artifact("data/x.json", notes="§49 без формы", slo=12))
        report = measure(["Economics"], repo_root=self.tree, data_dir=self.data,
                         now=NOW)
        self.assertEqual(1, len(report["unparsed_mentions"]))
        self.assertEqual("data/x.json", report["unparsed_mentions"][0]["path"])


if __name__ == "__main__":
    unittest.main()
