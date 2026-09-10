"""Приёмка прибора «чем закрываема дыра переписи» (заказ #544, ADR-302).

# FROZEN-DATE-OK: injected-clock — литерал `FIXED_NOW` уходит аргументом `now=`
# в `measure`/`run`; отметки фикстур закреплены тем же литералом, обе стороны
# сравнения неподвижны, и вердикт набора не зависит от календаря хоста.

Главный контроль набора — ОТРИЦАТЕЛЬНЫЙ: покрытие «материал есть» обязано
схлопываться в ноль, когда ряд пуст. Без него «40 из 41» было бы утверждением,
истинным по построению, — ровно тот класс украшений, который поймал на себе
цикл #544.
"""
from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.monitoring import journal_backfill_material as jbm

FIXED_NOW = datetime(2026, 9, 10, 4, 0, 0, tzinfo=timezone.utc)

D1, D2, D3 = "2026-08-12", "2026-08-13", "2026-08-14"


def _pair(protocol: str, forward_date: str, cls: str = jbm.CLASS_ABSENT) -> dict:
    return {"decision_date": "2026-08-11", "forward_date": forward_date,
            "protocol": protocol, "class": cls}


def _causes(pairs, *, status: str = "CRITICAL", parity_passed: bool = True) -> dict:
    return {"status": status, "attribution": list(pairs),
            "parity_control": {"passed": parity_passed}}


def _series(mapping: dict) -> dict:
    return {"series": {k: [[d, 1.0] for d in v] for k, v in mapping.items()}}


def _data_dir(td, *, series: dict, adapters: dict | None = None) -> Path:
    data = Path(td) / "data"
    data.mkdir(exist_ok=True)
    (data / jbm.SERIES_FILENAME).write_text(json.dumps(series), encoding="utf-8")
    if adapters is not None:
        (data / jbm.ADAPTER_STATUS_FILENAME).write_text(
            json.dumps({"adapters": adapters}), encoding="utf-8")
    return data


class MaterialClassification(unittest.TestCase):
    """Исход по паре читается из ряда и ни из чего больше."""

    def test_point_on_that_day_for_that_leg_is_material(self):
        with TemporaryDirectory() as td:
            data = _data_dir(td, series=_series({"aave_v3": [D1, D2]}))
            doc = jbm.measure(data, now=FIXED_NOW,
                              causes=_causes([_pair("aave_v3", D1)]))
        self.assertEqual(doc["material"][jbm.MATERIAL_PRESENT], 1)
        self.assertEqual(doc["protocols_without_material"], [])

    def test_protocol_in_series_but_day_missing_is_not_material(self):
        """Положительный контроль на пропуск дня: покрытие обязано ПАДАТЬ.

        Конвенция самого накопителя — «пропуск дня остаётся пропуском, никогда
        не интерполируем». Прибор, засчитавший такой день как материал, врал бы
        в сторону дешёвой починки.
        """
        with TemporaryDirectory() as td:
            data = _data_dir(td, series=_series({"aave_v3": [D2, D3]}))
            doc = jbm.measure(data, now=FIXED_NOW,
                              causes=_causes([_pair("aave_v3", D1)]))
        self.assertEqual(doc["material"][jbm.MATERIAL_ABSENT_DAY], 1)
        self.assertEqual(doc["material"][jbm.MATERIAL_PRESENT], 0)
        self.assertEqual(doc["protocols_without_material"], ["aave_v3"])

    def test_protocol_absent_from_the_series_is_its_own_outcome(self):
        with TemporaryDirectory() as td:
            data = _data_dir(td, series=_series({"aave_v3": [D1]}))
            doc = jbm.measure(data, now=FIXED_NOW,
                              causes=_causes([_pair("pendle", D1)]))
        self.assertEqual(doc["material"][jbm.MATERIAL_NO_SERIES], 1)
        self.assertEqual(doc["protocols_without_material"], ["pendle"])

    def test_empty_series_collapses_coverage_to_zero(self):
        """ОТРИЦАТЕЛЬНЫЙ контроль всего замера.

        Если «материал есть» не умеет становиться нулём при пустом ряде, то
        число покрытия — свойство прибора, а не данных, и опираться на него
        владелец не вправе.
        """
        pairs = [_pair("aave_v3", D1), _pair("compound_v3", D2)]
        with TemporaryDirectory() as td:
            data = _data_dir(td, series={"series": {}})
            doc = jbm.measure(data, now=FIXED_NOW, causes=_causes(pairs))
        self.assertEqual(doc["material"][jbm.MATERIAL_PRESENT], 0)
        self.assertEqual(doc["material"][jbm.MATERIAL_NO_SERIES], 2)

    def test_only_transcription_cut_pairs_are_asked_about(self):
        """Пара перебоя эвиденса материалом ряда не закрывается по смыслу.

        Она БЫЛА в книгах дня; отсутствовал живой провенанс. Спрашивать о ней
        «есть ли точка в ряду» значило бы предложить заменить отказ эвиденса
        значением из файла, который провенанса не несёт вовсе.
        """
        pairs = [_pair("aave_v3", D1),
                 _pair("pendle", D1, cls="in_books_source_not_live")]
        with TemporaryDirectory() as td:
            data = _data_dir(td, series=_series({"aave_v3": [D1], "pendle": [D1]}))
            doc = jbm.measure(data, now=FIXED_NOW, causes=_causes(pairs))
        self.assertEqual(doc["pairs_cut_by_transcription"], 1)
        self.assertEqual(len(doc["per_pair"]), 1)

    def test_per_pair_names_day_and_leg(self):
        """Заказ требовал ПОИМЁННО — доля без перечня ответом не является."""
        with TemporaryDirectory() as td:
            data = _data_dir(td, series=_series({"aave_v3": [D1]}))
            doc = jbm.measure(data, now=FIXED_NOW,
                              causes=_causes([_pair("aave_v3", D1)]))
        row = doc["per_pair"][0]
        self.assertEqual(row["forward_date"], D1)
        self.assertEqual(row["protocol"], "aave_v3")
        self.assertEqual(row["decision_date"], "2026-08-11")


class ThirdOutcome(unittest.TestCase):
    """«Не измерено» обязано быть отличимо от измеренного нуля."""

    def test_unreadable_series_is_unmeasured_not_zero_material(self):
        with TemporaryDirectory() as td:
            data = Path(td) / "data"
            data.mkdir()
            (data / jbm.SERIES_FILENAME).write_text("{не json", encoding="utf-8")
            doc = jbm.measure(data, now=FIXED_NOW,
                              causes=_causes([_pair("aave_v3", D1)]))
        self.assertEqual(doc["status"], jbm.STATUS_UNMEASURED)
        self.assertNotIn("material", doc)
        self.assertTrue(any("НЕ ИЗМЕРЕНО" in f for f in doc["findings"]))

    def test_series_of_the_wrong_shape_is_unmeasured(self):
        with TemporaryDirectory() as td:
            data = Path(td) / "data"
            data.mkdir()
            (data / jbm.SERIES_FILENAME).write_text(
                json.dumps({"series": ["не словарь"]}), encoding="utf-8")
            doc = jbm.measure(data, now=FIXED_NOW,
                              causes=_causes([_pair("aave_v3", D1)]))
        self.assertEqual(doc["status"], jbm.STATUS_UNMEASURED)

    def test_upstream_unmeasured_propagates(self):
        with TemporaryDirectory() as td:
            data = _data_dir(td, series=_series({"aave_v3": [D1]}))
            doc = jbm.measure(data, now=FIXED_NOW,
                              causes=_causes([], status=jbm.STATUS_UNMEASURED))
        self.assertEqual(doc["status"], jbm.STATUS_UNMEASURED)
        self.assertNotIn("material", doc)

    def test_upstream_parity_failure_blocks_the_count(self):
        """Паритет ADR-302 не прошёл ⇒ население пар брать неоткуда.

        Считать по нему всё равно значило бы построить своё число на чужом
        неподтверждённом.
        """
        with TemporaryDirectory() as td:
            data = _data_dir(td, series=_series({"aave_v3": [D1]}))
            doc = jbm.measure(data, now=FIXED_NOW,
                              causes=_causes([_pair("aave_v3", D1)],
                                             parity_passed=False))
        self.assertEqual(doc["status"], jbm.STATUS_UNMEASURED)
        self.assertNotIn("material", doc)

    def test_no_cut_pairs_is_ok_and_not_confused_with_no_material(self):
        with TemporaryDirectory() as td:
            data = _data_dir(td, series=_series({"aave_v3": [D1]}), adapters={})
            doc = jbm.measure(data, now=FIXED_NOW, causes=_causes([]))
        self.assertEqual(doc["status"], jbm.STATUS_OK)
        self.assertEqual(doc["pairs_cut_by_transcription"], 0)

    def test_missing_adapter_status_does_not_fabricate_zero_exposure(self):
        with TemporaryDirectory() as td:
            data = _data_dir(td, series=_series({"aave_v3": [D1]}))
            doc = jbm.measure(data, now=FIXED_NOW,
                              causes=_causes([_pair("aave_v3", D1)]))
        self.assertTrue(any("НЕ ИЗМЕРЕНО" in f for f in doc["findings"]),
                        "нечитаемый снимок дороги обязан сказать о себе вслух")

    def test_malformed_series_rows_leave_the_protocol_present(self):
        """«Протокола нет в ряду» и «строки протокола нечитаемы» — разные ответы."""
        by = jbm.series_dates({"aave_v3": ["мусор", 17, None]})
        self.assertIn("aave_v3", by)
        self.assertEqual(by["aave_v3"], set())


class ProvenanceExposure(unittest.TestCase):
    """Проба материала измеряется ОТДЕЛЬНО от его наличия."""

    def test_adapter_without_live_apy_but_with_finite_apy_is_exposure(self):
        exp = jbm.provenance_exposure(
            {"pendle": {"apy": 8.0}}, {"pendle": {D1}})
        self.assertEqual(exp["without_live_apy_but_finite_apy"], 1)
        self.assertEqual(exp["of_those_present_in_series"], ["pendle"])

    def test_adapter_with_live_apy_is_not_exposure(self):
        exp = jbm.provenance_exposure(
            {"aave_v3": {"live_apy": 3.6, "apy": 3.6}}, {"aave_v3": {D1}})
        self.assertEqual(exp["without_live_apy_but_finite_apy"], 0)
        self.assertEqual(exp["with_live_apy"], 1)

    def test_exposed_adapter_outside_the_series_is_counted_but_not_listed(self):
        exp = jbm.provenance_exposure({"pendle": {"apy": 8.0}}, {"aave_v3": {D1}})
        self.assertEqual(exp["without_live_apy_but_finite_apy"], 1)
        self.assertEqual(exp["of_those_present_in_series"], [])

    def test_non_finite_apy_is_neither_live_nor_exposure(self):
        exp = jbm.provenance_exposure({"x": {"apy": None}, "y": {"apy": True}}, {})
        self.assertEqual(exp["adapters_seen"], 0)

    def test_exposure_drives_the_critical_verdict(self):
        """CRITICAL приходит от ЗАМЕРА, а не от факта запуска прибора."""
        with TemporaryDirectory() as td:
            data = _data_dir(td, series=_series({"aave_v3": [D1]}),
                             adapters={"aave_v3": {"live_apy": 3.6}})
            clean = jbm.measure(data, now=FIXED_NOW,
                                causes=_causes([_pair("aave_v3", D1)]))
        with TemporaryDirectory() as td:
            data = _data_dir(td, series=_series({"aave_v3": [D1], "pendle": [D1]}),
                             adapters={"aave_v3": {"live_apy": 3.6},
                                       "pendle": {"apy": 8.0}})
            dirty = jbm.measure(data, now=FIXED_NOW,
                                causes=_causes([_pair("aave_v3", D1)]))
        self.assertEqual(clean["status"], jbm.STATUS_OK)
        self.assertEqual(dirty["status"], jbm.STATUS_CRITICAL)

    def test_the_report_says_out_loud_what_it_does_not_prove(self):
        with TemporaryDirectory() as td:
            data = _data_dir(td, series=_series({"aave_v3": [D1]}), adapters={})
            doc = jbm.measure(data, now=FIXED_NOW,
                              causes=_causes([_pair("aave_v3", D1)]))
        self.assertIn("провенанса", doc["what_it_does_not_prove"])


class ClockIsAnInput(unittest.TestCase):
    def test_generated_at_comes_from_the_injected_clock(self):
        with TemporaryDirectory() as td:
            data = _data_dir(td, series=_series({"aave_v3": [D1]}), adapters={})
            doc = jbm.measure(data, now=FIXED_NOW,
                              causes=_causes([_pair("aave_v3", D1)]))
        self.assertEqual(doc["generated_at"], FIXED_NOW.isoformat())


class RunShape(unittest.TestCase):
    def test_run_returns_the_shape_the_bridge_expects(self):
        with TemporaryDirectory() as td:
            _data_dir(td, series=_series({"aave_v3": [D1], "pendle": [D1]}),
                      adapters={"pendle": {"apy": 8.0}})
            doc = jbm.run(root=td, now=FIXED_NOW, write=False,
                          causes=_causes([_pair("aave_v3", D1)]))
        self.assertIn("overall", doc)
        for key in ("critical", "warn", "info", "unchecked"):
            self.assertIn(key, doc["counts"])
        self.assertEqual(doc["counts"]["critical"], 1)

    def test_unmeasured_is_counted_apart_from_zero(self):
        with TemporaryDirectory() as td:
            data = Path(td) / "data"
            data.mkdir()
            (data / jbm.SERIES_FILENAME).write_text("{", encoding="utf-8")
            doc = jbm.run(root=td, now=FIXED_NOW, write=False,
                          causes=_causes([_pair("aave_v3", D1)]))
        self.assertEqual(doc["overall"], jbm.STATUS_UNMEASURED)
        self.assertGreaterEqual(doc["counts"]["unchecked"], 1)

    def test_run_writes_the_artifact(self):
        with TemporaryDirectory() as td:
            _data_dir(td, series=_series({"aave_v3": [D1]}), adapters={})
            jbm.run(root=td, now=FIXED_NOW,
                    causes=_causes([_pair("aave_v3", D1)]))
            written = json.loads(
                (Path(td) / "data" / jbm.OUTPUT_FILENAME).read_text(encoding="utf-8"))
        self.assertEqual(written["generated_at"], FIXED_NOW.isoformat())

    def test_report_lines_name_the_coverage(self):
        with TemporaryDirectory() as td:
            data = _data_dir(td, series=_series({"aave_v3": [D1]}), adapters={})
            doc = jbm.measure(data, now=FIXED_NOW,
                              causes=_causes([_pair("aave_v3", D1)]))
        text = "\n".join(jbm.format_report(doc))
        self.assertIn("заказ #544", text)
        self.assertIn(jbm.MATERIAL_PRESENT, text)


class RealUpstreamIsCalled(unittest.TestCase):
    """Своей копии правила отнесения пары к классу у прибора нет.

    Мутация «считать классом всё подряд» иначе не краснела бы: подставной
    `causes` в остальных тестах закрывает арифметику, но не проводку к
    настоящему ADR-302.

    Подменять ОДИН `sys.modules` тут недостаточно, и это не педантизм: как только
    настоящий модуль импортирован кем угодно раньше (например соседним тест-файлом
    в том же прогоне), он становится АТРИБУТОМ пакета, и `from … import …` берёт
    атрибут, а не запись в `sys.modules`. Тест, подменивший только запись, зеленел
    бы в одиночку и краснел в наборе — вердикт решал бы ПОРЯДОК СБОРА, а не
    поведение. Подменяются обе двери.
    """

    @staticmethod
    def _swap(fake):
        """Ставит подмену в обе двери и возвращает восстановитель."""
        import sys
        from spa_core import monitoring as pkg

        name = "spa_core.monitoring.unevidenced_leg_causes"
        prev_mod = sys.modules.get(name)
        had_attr = hasattr(pkg, "unevidenced_leg_causes")
        prev_attr = getattr(pkg, "unevidenced_leg_causes", None)
        sys.modules[name] = fake
        setattr(pkg, "unevidenced_leg_causes", fake)

        def restore():
            if prev_mod is not None:
                sys.modules[name] = prev_mod
            else:  # pragma: no cover
                sys.modules.pop(name, None)
            if had_attr:
                setattr(pkg, "unevidenced_leg_causes", prev_attr)
            else:  # pragma: no cover
                delattr(pkg, "unevidenced_leg_causes")

        return restore

    def test_without_injection_the_real_producer_is_used(self):
        import types

        calls: list = []
        fake = types.ModuleType("spa_core.monitoring.unevidenced_leg_causes")

        def _measure(data_dir, **kwargs):
            calls.append(kwargs)
            return _causes([_pair("aave_v3", D1)])

        fake.measure = _measure
        restore = self._swap(fake)
        try:
            with TemporaryDirectory() as td:
                data = _data_dir(td, series=_series({"aave_v3": [D1]}), adapters={})
                doc = jbm.measure(data, now=FIXED_NOW)
        finally:
            restore()
        self.assertEqual(len(calls), 1, "настоящий производитель причин не вызван")
        self.assertEqual(doc["material"][jbm.MATERIAL_PRESENT], 1)

    def test_a_broken_upstream_is_unmeasured_not_zero(self):
        import types

        fake = types.ModuleType("spa_core.monitoring.unevidenced_leg_causes")

        def _measure(data_dir, **kwargs):
            raise RuntimeError("журнал не прочитан")

        fake.measure = _measure
        restore = self._swap(fake)
        try:
            with TemporaryDirectory() as td:
                data = _data_dir(td, series=_series({"aave_v3": [D1]}), adapters={})
                doc = jbm.measure(data, now=FIXED_NOW)
        finally:
            restore()
        self.assertEqual(doc["status"], jbm.STATUS_UNMEASURED)


class Wiring(unittest.TestCase):
    """Прибор без читателя — не прибор. Каждая точка проверяется ОТДЕЛЬНО."""

    ROOT = Path(__file__).resolve().parents[2]
    ARTIFACT = f"data/{jbm.OUTPUT_FILENAME}"

    def test_the_bridge_declares_the_artifact_among_its_products(self):
        from spa_core.monitoring import findings_bridge as fb
        self.assertIn(self.ARTIFACT, fb.PRODUCES)

    def test_the_bridge_maps_the_artifact_to_its_producing_module(self):
        from spa_core.monitoring import findings_bridge as fb
        entry = fb.CENSUS_PRODUCT.get("journal_backfill_material")
        self.assertIsNotNone(entry, "производителя нет в карте моста")
        self.assertEqual(entry["artifact"], self.ARTIFACT)
        self.assertEqual(entry["module"],
                         "spa_core/monitoring/journal_backfill_material.py")

    def test_the_bridge_names_it_in_the_census_stage(self):
        from spa_core.monitoring import findings_bridge as fb
        self.assertIn("journal_backfill_material", fb.CENSUS_STAGE)

    def test_the_office_step_knows_the_schema_and_the_producer(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "_cor_probe_jbm", self.ROOT / "scripts/consume_office_reports.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.assertIn(jbm.OUTPUT_FILENAME, mod._READ_SCHEMA)
        for key in ("material", "per_pair", "series_provenance_exposure"):
            self.assertIn(key, mod._READ_SCHEMA[jbm.OUTPUT_FILENAME],
                          "ответ ПОИМЁННО обязан быть в схеме чтения")
        self.assertEqual(mod._PRODUCER.get(jbm.OUTPUT_FILENAME),
                         "spa_core/monitoring/journal_backfill_material.py")

    def test_the_office_step_actually_renders_the_artifact(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "_cor_probe_jbm2", self.ROOT / "scripts/consume_office_reports.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        with TemporaryDirectory() as td:
            data = _data_dir(td, series=_series({"aave_v3": [D1]}), adapters={})
            doc = jbm.run(root=td, now=FIXED_NOW, write=False,
                          causes=_causes([_pair("aave_v3", D1)]))
            lines = mod._summarize_json(
                str(data / jbm.OUTPUT_FILENAME), doc, now=FIXED_NOW)
        text = "\n".join(lines)
        self.assertIn("заказ #544", text,
                      "шаг 0-офис не отрисовал прибор — строки чужие или пустые")

    def test_the_artifact_home_is_both_manifest_entries(self):
        doc = json.loads((self.ROOT / "architecture/manifest.json").read_text(
            encoding="utf-8"))
        art = [a for a in doc["artifacts"] if a.get("path") == self.ARTIFACT]
        self.assertEqual(len(art), 1, "нет записи в реестре artifacts[]")
        self.assertEqual(art[0]["producer"], "com.spa.decision_loop")

        agent = next(a for a in doc["agents"]
                     if a.get("label") == "com.spa.decision_loop")
        produced = [p for p in agent["produces"] if p.get("artifact") == self.ARTIFACT]
        self.assertEqual(len(produced), 1, "нет записи в produces[] паспорта агента")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
