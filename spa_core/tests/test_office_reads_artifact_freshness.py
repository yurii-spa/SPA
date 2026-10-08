"""Заказ владельца G105 п. 1 (хвост ADR-526), решение ADR-642.

ПЕРВЫЙ из пяти непрочитанных производителей находок, названных ADR-526 поимённо:
`data/artifact_freshness.json`. Сторож, чей единственный предмет — «что обязано
оставаться свежим», сам доезжал до оркестратора МОЛЧА: его находка уходила тревогой
в Телеграм и больше никуда, а шаг 0-офис этот артефакт не читал.

Каждый тест — либо положительный контроль РЕАЛЬНОЙ формы (замер 07.10: 4 протухших
из 14, старшему 2481 ч), либо контроль в обратную сторону с поимённо порванным
звеном. Литеральных дат нет: часы приходят входом `now=`, отметки сцены вычислены
от якоря.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import pathlib
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]
ARTIFACT = "data/artifact_freshness.json"
PRODUCER_AGENT = "com.spa.artifact_freshness"

# Якорь сцены.
# FROZEN-DATE-OK: injected-clock — ветка выжимки принимает часы входом
# `_summarize_json(..., now=NOW)`, все отметки документов сцены вычислены от этого
# якоря, стенных часов в батарее нет ни одних. Якорь намеренно уведён от стенных
# часов на месяцы: совпадение с сегодняшним днём делало бы батарею зелёной и тогда,
# когда ветка часы НЕ принимает.
NOW = dt.datetime(2026, 3, 15, 12, 0, tzinfo=dt.timezone.utc)


def _office():
    spec = importlib.util.spec_from_file_location(
        "_office_probe_af", REPO / "scripts" / "consume_office_reports.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _report(**over):
    """Документ в форме, ИЗМЕРЕННОЙ у производителя (`summarize()`), не выдуманной."""
    doc = {
        "llm_forbidden": True,
        "deterministic": True,
        "advisory": True,
        "n_artifacts": 14,
        "any_stale": True,
        "n_stale": 1,
        "n_unchecked": 0,
        "stale": [{"name": "rates_desk_rate_surface", "producer": "rates_desk",
                   "status": "STALE", "age_hours": 2481.39, "max_age_hours": 30.0,
                   "public": False, "budget_source": "literal"}],
        "artifacts": [],
        "generated_at": (NOW - dt.timedelta(hours=11.7)).isoformat(),
    }
    doc.update(over)
    return doc


def _lines(doc):
    return _office()._summarize_json(ARTIFACT, doc, now=NOW, root=str(REPO))


class TheOfficeActuallyReadsTheFreshnessRegistry(unittest.TestCase):
    """Объявить артефакт и не уметь его разобрать = `ПРОЧИТАН ВХОЛОСТУЮ`."""

    def test_the_branch_exists_so_the_read_is_not_hollow(self):
        o = _office()
        lines = _lines(_report())
        self.assertFalse(any(ln.startswith(o._HOLLOW_MARK) for ln in lines), lines)

    def test_the_stale_artifact_is_named_not_merely_counted(self):
        """Число без перечня не говорит, ЧТО именно протухло."""
        lines = _lines(_report())
        self.assertTrue(any("rates_desk_rate_surface" in ln for ln in lines), lines)
        self.assertTrue(any("2481" in ln for ln in lines), lines)

    def test_the_count_carries_its_denominator(self):
        """«1 протухло» без `n_artifacts` читается как «1 на весь флот»."""
        lines = _lines(_report())
        self.assertTrue(any("1 из 14" in ln for ln in lines), lines)

    def test_a_clean_registry_reads_as_all_fresh(self):
        lines = _lines(_report(any_stale=False, n_stale=0, stale=[]))
        self.assertTrue(any("все свежи" in ln for ln in lines), lines)
        self.assertFalse(any("ПРОТУХШИЕ ЕСТЬ" in ln for ln in lines), lines)

    def test_an_empty_list_and_a_false_flag_are_PRESENT_not_missing(self):
        """Здоровый реестр не имеет права краснеть «СХЕМА РАЗОШЛАСЬ».

        `stale: []` и `any_stale: false` объявлены в `_READ_SCHEMA`, и у ветки,
        судящей по ИСТИННОСТИ, они читались бы как отсутствующие поля — то есть
        каждый спокойный день печатал бы ложное расхождение схемы, и читатель
        научился бы игнорировать строку, которая однажды скажет правду.
        """
        o = _office()
        doc = _report(any_stale=False, n_stale=0, n_unchecked=0, stale=[])
        self.assertEqual(o._schema_drift("artifact_freshness.json", doc,
                                         root=str(REPO)), [])


class MeasuredZeroIsNotTheSameAsNotMeasured(unittest.TestCase):
    """Инв. #17 на этой ветке: три исхода производителя обязаны быть различимы."""

    def test_unchecked_is_printed_even_when_nothing_is_stale(self):
        """Реестр, который НИЧЕГО не смог измерить, не есть «всё свежо».

        Положительный контроль ровно того класса, ради которого `n_unchecked`
        объявлен в `_READ_SCHEMA`: при `n_stale=0` и `n_unchecked=9` ветка,
        печатающая одно «все свежи», выдала бы слепоту за здоровье.
        """
        lines = _lines(_report(any_stale=False, n_stale=0, n_unchecked=9, stale=[]))
        self.assertTrue(any("без отметки времени: 9" in ln for ln in lines), lines)

    def test_a_missing_counter_reads_as_unmeasured_not_zero(self):
        doc = _report()
        doc.pop("n_unchecked")
        o = _office()
        lines = _lines(doc)
        self.assertTrue(any(f"без отметки времени: {o._UNMEASURED}" in ln
                            for ln in lines), lines)

    def test_a_missing_artifact_has_no_age_and_says_so(self):
        """`MISSING` приходит без `age_hours` — подставить ноль значило бы соврать."""
        o = _office()
        lines = _lines(_report(stale=[
            {"name": "dfb_pools", "producer": "dfb_capture", "status": "MISSING",
             "age_hours": None, "max_age_hours": 30.0, "public": False,
             "budget_source": "manifest_slo"}]))
        self.assertTrue(any("dfb_pools" in ln and o._UNMEASURED in ln
                            for ln in lines), lines)

    def test_the_heaviest_outcome_is_printed_first(self):
        """`MISSING` вперёд `STALE`: сортировка по возрасту задвинула бы его в хвост."""
        lines = _lines(_report(n_stale=2, stale=[
            {"name": "very_old", "producer": "p", "status": "STALE",
             "age_hours": 9999.0, "max_age_hours": 30.0, "public": False,
             "budget_source": "literal"},
            {"name": "gone", "producer": "p", "status": "MISSING",
             "age_hours": None, "max_age_hours": 30.0, "public": False,
             "budget_source": "literal"}]))
        named = [ln for ln in lines if "very_old" in ln or "gone" in ln]
        self.assertIn("gone", named[0], named)

    def test_truncation_is_announced_not_silent(self):
        """Умолчание об усечении превращает перечень в «вот и всё»."""
        many = [{"name": f"a{i}", "producer": "p", "status": "STALE",
                 "age_hours": float(100 + i), "max_age_hours": 30.0,
                 "public": False, "budget_source": "literal"} for i in range(11)]
        lines = _lines(_report(n_stale=11, stale=many))
        self.assertTrue(any("ещё 3 протухших не напечатано" in ln for ln in lines),
                        lines)


class TheDeclaredSchemaIsMeasuredAtTheProducer(unittest.TestCase):
    """Ветка, написанная не по замеру производителя, печатает несуществующее поле."""

    def test_every_declared_key_exists_in_the_producer_source(self):
        o = _office()
        src = REPO / o._PRODUCER["artifact_freshness.json"]
        self.assertTrue(src.exists(), src)
        keys = o._source_keys(str(src))
        self.assertIsNotNone(keys, "исходник производителя не разобран")
        for key in o._READ_SCHEMA["artifact_freshness.json"]:
            self.assertIn(key, keys, f"{key} объявлен, а производитель его не пишет")

    def test_the_producer_is_declared_so_drift_is_measurable_not_unmeasured(self):
        """Без строки в `_PRODUCER` расхождение схемы было бы «НЕ ИЗМЕРЕНО»."""
        o = _office()
        doc = _report()
        doc.pop("n_stale")
        lines = o._schema_drift("artifact_freshness.json", doc, root=str(REPO))
        self.assertTrue(lines, "пропущенное поле обязано быть названо вслух")
        self.assertFalse(any(o._UNMEASURED in ln for ln in lines), lines)

    def test_the_torn_link_reads_as_unmeasured_loudly(self):
        """Обратная сторона: производитель не объявлен ⇒ громкое «НЕ ИЗМЕРЕНО»."""
        o = _office()
        doc = _report()
        doc.pop("n_stale")
        saved = o._PRODUCER.pop("artifact_freshness.json")
        try:
            lines = o._schema_drift("artifact_freshness.json", doc, root=str(REPO))
        finally:
            o._PRODUCER["artifact_freshness.json"] = saved
        self.assertTrue(any(o._UNMEASURED in ln for ln in lines), lines)


class TheClosureIsPinnedToTheRealTree(unittest.TestCase):
    """Сторож самого закрытия: снять его молча теперь нельзя."""

    def _manifest(self):
        return json.loads((REPO / "architecture" / "manifest.json")
                          .read_text(encoding="utf-8"))

    def test_the_registry_is_declared_as_read_by_the_cycle(self):
        from spa_core.monitoring import finding_reader_census as frc
        art = [a for a in self._manifest()["artifacts"] if a["path"] == ARTIFACT]
        self.assertEqual(len(art), 1, "строка реестра в artifacts[] должна быть одна")
        self.assertEqual(art[0]["status"], "active")
        self.assertIn(frc.CYCLE_CONSUMER, art[0]["consumers"])

    def test_the_declared_slo_does_not_disagree_with_the_producer(self):
        """Два объявления об одном файле — второй дом порога (урок ADR-513)."""
        man = self._manifest()
        art = next(a for a in man["artifacts"] if a["path"] == ARTIFACT)
        produced = next(p for ag in man["agents"] if ag["label"] == PRODUCER_AGENT
                        for p in ag["produces"] if p["artifact"] == ARTIFACT)
        self.assertEqual(art["slo_hours"], produced["slo_hours"])

    def test_the_writer_leg_is_asked_before_the_reader_leg(self):
        """Порядок ног ADR-526: объявление законно только при ЖИВОМ писателе.

        Проверяется не живость хоста (о ней судить тест не вправе), а то, что
        производитель объявлен активным и с тактом — то есть что объявление не
        посажено на `intent=designed`, как ADR-475 верно отказался делать.
        """
        agent = next(a for a in self._manifest()["agents"]
                     if a["label"] == PRODUCER_AGENT)
        self.assertEqual(agent["intent"], "active")
        self.assertTrue(agent.get("schedule"), "у писателя обязан быть такт")


if __name__ == "__main__":
    unittest.main()
