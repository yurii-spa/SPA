"""Батарея прибора «верность реестра источников, спрошенная у живой страницы».

Заказ **G103 п. 1** приказа владельца «Portfolio CIO», решение — ADR-594.

## Чем эта батарея обязана быть

Правило `.claude/rules/acceptance.md` п. 3: проба меряет ИСХОД и у неё есть
контроль в обе стороны — зелёный на целом контуре и КРАСНЫЙ на каждом порванном
звене, с названным звеном. Поэтому каждый тест ниже воспроизводит ОДНУ поломку,
и ни один не проверяет «модуль импортируется».

## Что в сцене закреплено, а что инъектировано

Часы подаются входом (`now=`), отметка операнда считается ОТ НИХ — литеральных
дат в файле нет вовсе, и календарь на вердикт не влияет (правило
`.claude/rules/deployment.md`, раздел о времени). Реестр и запись кустодиана —
тоже ВХОДЫ: в одноразовом дереве ни отчёта, ни живой страницы нет по
построению, и предпосылка, добытая у окружения, и есть та бомба, против которой
правило написано.

**Счёты исходов в сцене РАЗНЫЕ намеренно** (урок цикла #786): равные числа двух
исходов делают подмену ИМЕНИ ключа невидимой — тест остался бы зелёным на
приборе, который перепутал «опровергнут» с «заглушкой».
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import unittest
from pathlib import Path

from spa_core.monitoring import declared_source_live_parity as M

REPO = Path(__file__).resolve().parents[2]
CUSTODIAN = REPO / "scripts" / "site_freshness_monitor.py"

#: Часы сцены. Литеральной даты нет: берётся «сейчас», и все отметки считаются
#: ОТ НЕГО, поэтому ни один тест не может протухнуть от смены календаря.
NOW = dt.datetime.now(dt.timezone.utc)


def _custodian():
    spec = importlib.util.spec_from_file_location("_sfm_under_test", CUSTODIAN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _stamp(hours_ago: float) -> str:
    return (NOW - dt.timedelta(hours=hours_ago)).isoformat()


#: Реестр сцены. Разложен так, чтобы КАЖДЫЙ исход по label был населён ровно
#: одним label и ни один счёт не совпадал с другим:
#:   `silent` — один опровергнут, один подтверждён ⇒ МОЛЧА;
#:   `loud`   — единственный источник опровергнут ⇒ ГРОМКО;
#:   `clean`  — подтверждён, опровержений нет;
#:   `dark`   — страница не скачана ⇒ о label сказать нечего.
SCENE_REGISTRY = {
    "silent": (("home", "live-one", r'id="live-one"[^>]*>\s*(\d+)', "живой"),
               ("home", "dead-one", r'id="dead-one"[^>]*>\s*(\d+)', "мёртвый")),
    "loud": (("home", "dead-two", r'id="dead-two"[^>]*>\s*(\d+)', "мёртвый"),),
    "clean": (("track", "live-two", r'id="live-two"[^>]*>\s*(\d+)', "живой"),),
    "dark": (("ghost", "live-three", r'id="live-three"[^>]*>\s*(\d+)', "живой"),),
}

SCENE_PAGES = {
    "home": '<span id="live-one">41</span><span id="x">dead-one</span>',
    "track": '<span id="live-two">7</span><span id="ph">&mdash;</span>',
}


def _scene_record(hours_ago: float = 1.0, pages=None, registry=None) -> dict:
    """Запись кустодиана, снятая ЕГО ЖЕ функцией, а не нашей копией правила.

    Вторая копия правила «как читается источник» разошлась бы с кустодианом
    молча, и батарея судила бы прибор по выдуманному операнду.
    """
    sfm = _custodian()
    probes = sfm.probe_declared_sources(pages if pages is not None else SCENE_PAGES,
                                        sources=registry or SCENE_REGISTRY)
    return {"ts": _stamp(hours_ago), "declared_source_probes": probes}


def _measure(**kw) -> dict:
    kw.setdefault("record", _scene_record())
    kw.setdefault("registry", SCENE_REGISTRY)
    return M.measure(REPO, now=NOW, **kw)


class TheAnswerOfTheOrder(unittest.TestCase):
    """Сколько объявленных источников страница подтверждает/опровергает."""

    def test_every_declared_source_gets_exactly_one_outcome(self):
        doc = _measure()
        declared = sum(len(v) for v in SCENE_REGISTRY.values())
        self.assertEqual(doc["population"], declared)
        self.assertEqual(sum(doc["outcomes"].values()), declared,
                         "сумма исходов не равна населению — источник потерян "
                         "или сосчитан дважды")

    def test_the_counts_are_the_measured_ones_and_they_differ(self):
        doc = _measure()
        self.assertEqual(doc["outcomes"][M.CONFIRMED], 2)
        self.assertEqual(doc["outcomes"][M.REFUTED], 2)
        self.assertEqual(doc["outcomes"][M.UNMEASURED_PAGE], 1)
        self.assertEqual(doc["outcomes"][M.UNMEASURED_PLACEHOLDER], 0)

    def test_a_refuted_source_with_a_live_sibling_is_silent(self):
        """Вред заказа дословно: сосед отвечает, кустодиан зелёный."""
        doc = _measure()
        self.assertEqual(doc["labels"]["silent"], M.LABEL_SILENT)
        self.assertEqual(doc["refuted_silently"], 1)

    def test_a_label_whose_every_source_is_refuted_is_LOUD_not_silent(self):
        """Громкий и молчаливый вред НЕ складываются: лекарство разное.

        У громкого кустодиан краснеет сам (`COMPARISON_NOT_MEASURED`), у
        молчаливого не краснеет никто. Слить их в одно число значило бы
        объявить найденным то, что и так видно.
        """
        doc = _measure()
        self.assertEqual(doc["labels"]["loud"], M.LABEL_LOUD)
        self.assertEqual(doc["refuted_loudly"], 1)
        self.assertEqual(doc["refuted"],
                         doc["refuted_silently"] + doc["refuted_loudly"])

    def test_a_label_with_no_refutation_is_clean_and_an_unfetched_one_is_not(self):
        doc = _measure()
        self.assertEqual(doc["labels"]["clean"], M.LABEL_CLEAN)
        self.assertEqual(doc["labels"]["dark"], M.LABEL_UNMEASURED,
                         "«страницу не скачали» объявлено чистым — это "
                         "третий исход, выданный за отсутствие находок")

    def test_label_outcomes_sum_to_the_number_of_labels(self):
        doc = _measure()
        self.assertEqual(sum(doc["label_outcomes"].values()),
                         len(SCENE_REGISTRY))


class ADuplicateIdIsItsOwnObservation(unittest.TestCase):
    """Дубль id НЕ опровержение и НЕ подтверждение — своё число."""

    def test_two_elements_with_one_id_are_counted_apart(self):
        pages = dict(SCENE_PAGES)
        pages["home"] = ('<span id="live-one">41</span>'
                         '<span id="live-one">99</span>'
                         '<span id="x">dead-one</span>')
        doc = _measure(record=_scene_record(pages=pages))
        self.assertEqual(doc["ambiguous_duplicate_ids"], 1)
        self.assertEqual(doc["outcomes"][M.REFUTED], 2,
                         "дубль попал в опровергнутые — это выдуманная находка")

    def test_a_single_id_is_not_reported_as_ambiguous(self):
        self.assertEqual(_measure()["ambiguous_duplicate_ids"], 0)


class TheRecordAndTheRegistryCanAGE(unittest.TestCase):
    """Расхождение реестра и записи имеет ДВА направления, и они разные."""

    def test_a_declared_source_missing_from_the_record_is_not_confirmed(self):
        registry = dict(SCENE_REGISTRY)
        registry["fresh"] = (("home", "brand-new",
                              r'id="brand-new"[^>]*>\s*(\d+)', "новый"),)
        doc = M.measure(REPO, now=NOW, registry=registry,
                        record=_scene_record())
        self.assertEqual(doc["outcomes"][M.UNMEASURED_NOT_RECORDED], 1)
        self.assertEqual(doc["labels"]["fresh"], M.LABEL_UNMEASURED)

    def test_a_recorded_source_the_registry_dropped_is_a_separate_number(self):
        record = _scene_record(registry=dict(
            SCENE_REGISTRY,
            gone=(("home", "retired", r'id="retired"[^>]*>\s*(\d+)', "снят"),)))
        doc = _measure(record=record)
        self.assertEqual(doc[M.RECORD_ORPHANS], 1)
        self.assertEqual(doc["population"],
                         sum(len(v) for v in SCENE_REGISTRY.values()),
                         "сирота записи попала в население реестра — это два "
                         "разных утверждения")


class TheTranslationIsByWholeWordNotBySubstring(unittest.TestCase):
    """Род исхода читается по СЛОВУ целиком (ADR-333), не подстрокой."""

    def test_an_unknown_leg_is_the_third_outcome_not_a_guess(self):
        record = _scene_record()
        for row in record["declared_source_probes"]:
            if row["elem_id"] == "dead-one":
                row["leg"] = "unmeasured:id_absent_in_a_new_sense"
        doc = _measure(record=record)
        self.assertEqual(doc["outcomes"][M.UNMEASURED_LEG_UNKNOWN], 1)
        self.assertEqual(doc["outcomes"][M.REFUTED], 1,
                         "незнакомый исход угадан подстрокой «id_absent» — "
                         "новый исход кустодиана стал бы знакомым молча")

    def test_every_leg_the_custodian_can_write_is_translated(self):
        """Перевод обязан покрывать ВСЕ исходы кустодиана.

        Иначе исправный сосед даёт прибору «не измерено» на целом контуре —
        а такой отказ читается как находка.
        """
        sfm = _custodian()
        for leg in (sfm.SOURCE_LEG_MEASURED, sfm.SOURCE_LEG_ID_ABSENT,
                    sfm.SOURCE_LEG_PLACEHOLDER, sfm.SOURCE_LEG_PAGE_ABSENT):
            self.assertIn(leg, M._LEG_TO_OUTCOME, leg)


class TheThirdOutcomeIsNamedAtEveryDoor(unittest.TestCase):
    """«Не измерено» обязано быть ИСХОДОМ с причиной, а не нулём и не падением."""

    def test_no_report_is_a_refusal_not_zero_findings(self):
        out = M.run(Path("/nonexistent-tree-c788"), write=False, now=NOW,
                    registry=SCENE_REGISTRY)
        self.assertFalse(out["measured"])
        self.assertEqual(out["doc"]["gap"], M.GAP_NO_OPERAND)

    def test_a_report_without_the_field_is_a_refusal_with_its_own_reason(self):
        with self.assertRaises(M.NotMeasured) as ctx:
            _measure(record={"ts": _stamp(1.0)})
        self.assertEqual(ctx.exception.gap, M.GAP_NO_FIELD)

    def test_a_report_without_a_timestamp_is_a_refusal(self):
        """Возраст — ПОЛЕ ответа, поэтому без отметки ответа нет."""
        rec = _scene_record()
        rec.pop("ts")
        with self.assertRaises(M.NotMeasured) as ctx:
            _measure(record=rec)
        self.assertEqual(ctx.exception.gap, M.GAP_NO_STAMP)

    def test_an_unparsable_timestamp_is_the_same_refusal(self):
        rec = _scene_record()
        rec["ts"] = "вчера"
        with self.assertRaises(M.NotMeasured) as ctx:
            _measure(record=rec)
        self.assertEqual(ctx.exception.gap, M.GAP_NO_STAMP)

    def test_a_report_older_than_the_bound_is_a_refusal(self):
        with self.assertRaises(M.NotMeasured) as ctx:
            _measure(record=_scene_record(hours_ago=M.OPERAND_MAX_AGE_H + 1))
        self.assertEqual(ctx.exception.gap, M.GAP_STALE)

    def test_a_report_inside_the_bound_answers_and_prints_its_age(self):
        doc = _measure(record=_scene_record(hours_ago=M.OPERAND_MAX_AGE_H - 1))
        self.assertEqual(doc["status"], "MEASURED")
        self.assertAlmostEqual(doc["operand_age_hours"],
                              M.OPERAND_MAX_AGE_H - 1, places=1)

    def test_an_unreadable_registry_is_a_refusal_not_an_invented_table(self):
        with self.assertRaises(M.NotMeasured) as ctx:
            M.load_registry(Path("/nonexistent-tree-c788"))
        self.assertEqual(ctx.exception.gap, M.GAP_NO_REGISTRY)

    def test_an_empty_registry_is_a_refusal_not_a_clean_sheet(self):
        with self.assertRaises(M.NotMeasured) as ctx:
            _measure(registry={})
        self.assertEqual(ctx.exception.gap, M.GAP_NO_REGISTRY)

    def test_a_record_of_the_wrong_kind_is_a_refusal_not_a_crash(self):
        """ВТОРОЙ вход — тот же урок, что у реестра.

        Род записи проверяет дверь чтения; запись, поданная ВХОДОМ, её не
        проходит, и не-словарь валил бы разбор `AttributeError` — «упало»
        вместо названного отказа.
        """
        with self.assertRaises(M.NotMeasured) as ctx:
            _measure(record=["не словарь"])
        self.assertEqual(ctx.exception.gap, M.GAP_OPERAND_UNREADABLE)

    def test_a_registry_entry_of_another_shape_is_a_refusal_not_a_crash(self):
        """Форма записи реестра — предпосылка, а не данность.

        Запись иной арности валила бы разбор исключением, а «упало» читается
        как дефект прибора, не как «реестр изменил форму».
        """
        with self.assertRaises(M.NotMeasured) as ctx:
            _measure(registry={"odd": (("home", "x"),)})
        self.assertEqual(ctx.exception.gap, M.GAP_NO_REGISTRY)

    def test_a_probe_row_without_a_full_address_leaves_the_source_unrecorded(self):
        """Почти совпавшая проба объявлением не считается.

        Без всех трёх частей адреса пробу нельзя сопоставить объявлению;
        взять «похожую» значило бы судить объявление по чужому наблюдению.
        """
        record = _scene_record()
        for row in record["declared_source_probes"]:
            if row["elem_id"] == "live-one":
                row.pop("label")
        doc = _measure(record=record)
        self.assertEqual(doc["outcomes"][M.UNMEASURED_NOT_RECORDED], 1)
        self.assertEqual(doc["outcomes"][M.CONFIRMED], 1,
                         "безадресная проба зачтена подтверждением")

    def test_the_cli_returns_nonzero_when_nothing_is_measured(self):
        self.assertEqual(M.main(["--root", "/nonexistent-tree-c788",
                                 "--no-write"]), 2)


class TheRegistryIsTheCUSTODIANS(unittest.TestCase):
    """Второй копии таблицы у прибора нет — иначе он судит не тот реестр."""

    def test_the_default_registry_is_read_from_the_custodian(self):
        table = M.load_registry(REPO)
        self.assertEqual(table, _custodian().SITE_NUMBER_SOURCES)

    def test_the_module_carries_no_second_copy_of_the_table(self):
        src = (REPO / M.PRODUCER).read_text(encoding="utf-8")
        body = src.split('"""', 2)[2] if src.count('"""') >= 2 else src
        self.assertNotIn(f"{M.REGISTRY_NAME} = ", body,
                         "в приборе появилась своя копия реестра — две копии "
                         "одного правила расходятся молча (ADR-220)")


class TheReportPrintsTheAnswerAndItsLimits(unittest.TestCase):
    def test_the_report_names_every_refuted_source_by_page_and_id(self):
        lines = "\n".join(M.report(_measure()))
        self.assertIn("home#dead-one", lines)
        self.assertIn("home#dead-two", lines)

    def test_the_report_states_what_it_does_not_prove(self):
        doc = _measure()
        self.assertTrue(doc["what_it_does_not_prove"])
        self.assertIn("НЕ ДОКЛАДЫВАЕТ", "\n".join(M.report(doc)))

    def test_an_unmeasured_report_says_so_and_names_the_reason(self):
        out = M.run(Path("/nonexistent-tree-c788"), write=False, now=NOW,
                    registry=SCENE_REGISTRY)
        lines = M.report(out["doc"])
        self.assertTrue(lines[0].startswith("НЕ ИЗМЕРЕНО"))
        self.assertIn(M.GAP_NO_OPERAND, lines[0])

    def test_the_office_rendering_truncates_the_SHOW_and_says_so(self):
        doc = _measure()
        short = M.format_report(doc, max_rows=1)
        self.assertTrue(any("обрезка ПОКАЗА" in line for line in short))
        self.assertEqual(doc["population"],
                         sum(len(v) for v in SCENE_REGISTRY.values()),
                         "население изменилось от обрезки показа")

    def test_the_artifact_is_json_serialisable(self):
        json.dumps(_measure(), ensure_ascii=False)

    def test_the_instrument_declares_itself_advisory(self):
        self.assertIs(_measure()["applied"], False)


class TheCustodianRecordsEverySource(unittest.TestCase):
    """Половина лекарства живёт у кустодиана: без записи судить нечего."""

    def test_the_probe_does_not_stop_at_the_first_hit(self):
        sfm = _custodian()
        probes = sfm.probe_declared_sources(SCENE_PAGES,
                                            sources=SCENE_REGISTRY)
        self.assertEqual(len(probes),
                         sum(len(v) for v in SCENE_REGISTRY.values()))
        legs = {p["elem_id"]: p["leg"] for p in probes}
        self.assertEqual(legs["live-one"], sfm.SOURCE_LEG_MEASURED)
        self.assertEqual(legs["dead-one"], sfm.SOURCE_LEG_ID_ABSENT,
                         "мёртвый сосед живого источника в записи не назван — "
                         "ровно то молчание, ради которого заказ написан")

    def test_locate_site_number_still_answers_about_the_OPERAND_only(self):
        """Контроль в обратную сторону: вердикт кустодиана НЕ изменён.

        `locate_site_number` обязан по-прежнему останавливаться на первом
        годном источнике — иначе правка сдвинула бы живой гейт, а не добавила
        наблюдение.
        """
        sfm = _custodian()
        hits, _probes = sfm.locate_site_number("silent", SCENE_PAGES,
                                               sources=SCENE_REGISTRY)
        self.assertEqual([h[1] for h in hits], ["live-one"])

    def test_the_id_count_is_asked_apart_from_presence(self):
        sfm = _custodian()
        probes = sfm.probe_declared_sources(
            {"home": '<span id="live-one">1</span><span id="live-one">2</span>'},
            sources={"silent": SCENE_REGISTRY["silent"]})
        counts = {p["elem_id"]: p["id_occurrences"] for p in probes}
        self.assertEqual(counts["live-one"], 2)
        self.assertEqual(counts["dead-one"], 0)

    def test_an_unfetched_page_is_its_own_leg(self):
        sfm = _custodian()
        probes = sfm.probe_declared_sources(
            {}, sources={"dark": SCENE_REGISTRY["dark"]})
        self.assertEqual(probes[0]["leg"], sfm.SOURCE_LEG_PAGE_ABSENT)

    def test_the_report_of_the_custodian_carries_the_field(self):
        """Поле обязано быть В ОТЧЁТЕ, а не только в функции.

        Функция без записи в отчёт — это наблюдение, которого никто не
        увидит: прибор получил бы `GAP_NO_FIELD` на исправном кустодиане.
        """
        src = CUSTODIAN.read_text(encoding="utf-8")
        self.assertIn(f'"{M.OPERAND_FIELD}": probe_declared_sources(', src)


if __name__ == "__main__":   # pragma: no cover
    unittest.main()
