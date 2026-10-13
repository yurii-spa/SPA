"""Население отчёта владельцу `/protocols` — батарея ADR-710.

Предмет — заказ **G709 п. 1** приказа `inbox-task-portfolio-cio-dynamic-capital-alloc`
и карточка `inbox-otchet-vladeltsu-protocols-pokazyvaet-2`: отчёт владельцу показывал
**2 записи из 36**, потому что `_get_all_adapters` обходил `data["adapters"]` КАК
СПИСОК, а живой `data/adapter_status.json` несёт этот раздел СЛОВАРЁМ. Обход словаря
отдаёт КЛЮЧИ (строки), `isinstance(ключ, dict)` ложен — и 34 современные записи
отбрасывались МОЛЧА.

**Каждый тест здесь — обратная сторона с НАЗВАННЫМ звеном**, а не проверка формата:
батарея, не видевшая настоящей поломки, — украшение (`.claude/rules/deployment.md`,
«Проверка сторожа сторожей»). Положительный контроль
:meth:`ProbeIsRedOnEachBrokenLink.test_list_only_traversal_is_the_2026_10_12_outage`
воспроизводит аварию дословно — возвращает читателю обход только списком — и ОБЯЗАН
краснеть.

Признак класса замороженных дат стоит СТРОКОЙ-КОММЕНТАРИЕМ ниже, а не здесь:
храповик читает именно комментарий, и пометка внутри докстринга была бы запиской
без читателя — ровно тот дефект, который сторож и ловит.
"""
# FROZEN-DATE-OK: injected-clock — обе стороны сравнения возраста закреплены:
# якорь `_ANCHOR` подставляется в `generated_at` артефакта (`_doc`) И передаётся
# пробе аргументом `now=` (`_probe`), поэтому ни один вердикт здесь не зависит
# ни от календаря машины, ни от длительности прогона.
from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.monitoring import card_acceptance as ca
from spa_core import telegram_protocols_reporter as reporter

PROBE_NAME = "owner_protocols_report_carries_every_record"

#: Якорь времени. Литерал здесь — ПРЕДМЕТ сравнения, а не стенные часы: он же
#: уезжает в `generated_at` и он же передаётся пробе как `now`.
_ANCHOR = datetime(2026, 10, 13, 12, 0, 0, tzinfo=timezone.utc)


def _record(name: str, apy: float, *, live: bool = True, **extra: object) -> dict:
    """Современная запись раздела — такая, какую пишет `adapter_orchestrator`.

    Ни `protocol_key`, ни `adapter_id`, ни `name`: замер живого артефакта
    2026-10-13 — ни одна из 34 записей раздела их не несёт, поэтому личность
    записи приходит ТОЛЬКО из ключа раздела.
    """
    row: dict = {"display_name": name, "apy": apy, "tier": 1}
    if live:
        row["live_apy"] = apy
        row["live_apy_fresh"] = True
    extra_row: dict = dict(extra)
    row.update(extra_row)
    return row


def _doc(section: object, *, age_hours: float = 1.0, **top: object) -> dict:
    """Артефакт с ОБЪЯВЛЕННЫМ возрастом (разница от `_ANCHOR`, а не от сегодня)."""
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


def _shown(doc: dict) -> int:
    """Сколько строк протоколов НАСТОЯЩИЙ отчёт печатает владельцу."""
    return sum(
        1
        for line in reporter.format_protocols_message(doc).splitlines()
        if line.startswith("•")
    )


class ReaderAcceptsBothShapes(unittest.TestCase):
    """Звено 1 — форма раздела. Сломано ⇒ владелец читает 2 строки из 36."""

    def test_dict_section_reaches_the_owner(self):
        """ЗВЕНО: раздел-СЛОВАРЬ (форма живого артефакта)."""
        doc = _doc({f"p{i}": _record(f"P{i}", 4.0 + i) for i in range(34)})
        self.assertEqual(len(reporter._get_all_adapters(doc)), 34)
        self.assertEqual(_shown(doc), 34)

    def test_list_section_reaches_the_owner(self):
        """ЗВЕНО: раздел-СПИСОК (форма тестов и части legacy-читателей)."""
        doc = _doc([_record(f"P{i}", 4.0 + i, protocol_key=f"p{i}") for i in range(7)])
        self.assertEqual(len(reporter._get_all_adapters(doc)), 7)
        self.assertEqual(_shown(doc), 7)

    def test_both_shapes_give_the_same_population(self):
        """ЗВЕНО: форма артефакта НЕ есть вопрос отчёта — население одно."""
        rows = {f"p{i}": _record(f"P{i}", 4.0 + i) for i in range(5)}
        as_dict = _doc(rows)
        as_list = _doc([dict(v, protocol_key=k) for k, v in rows.items()])
        self.assertEqual(_shown(as_dict), _shown(as_list))


class DroppedMembersStayDistinguishable(unittest.TestCase):
    """Звено 2 — третий исход у НАСЕЛЕНИЯ (инв. #17)."""

    def test_measured_zero_is_a_number_not_none(self):
        """ЗВЕНО: ноль есть ИЗМЕРЕННЫЙ ноль, а не отсутствие вопроса."""
        doc = _doc({"p0": _record("P0", 4.0)})
        self.assertEqual(reporter.unparsed_adapter_entries(doc), 0)

    def test_absent_section_is_unmeasured_not_zero(self):
        """ЗВЕНО: раздела нет ⇒ None. Ноль здесь был бы утверждением."""
        doc = _doc(None)
        doc.pop("adapters")
        self.assertIsNone(reporter.unparsed_adapter_entries(doc))

    def test_section_of_a_wrong_shape_entirely_is_unmeasured(self):
        """ЗВЕНО: раздел не словарь и не список ⇒ НЕ ИЗМЕРЕНО, не ноль."""
        self.assertIsNone(reporter.unparsed_adapter_entries(_doc("не раздел")))
        self.assertIsNone(reporter.unparsed_adapter_entries(_doc(17)))

    def test_non_record_member_is_counted_and_named(self):
        """ЗВЕНО: член, который не запись, уронен ЧИСЛОМ и назван владельцу."""
        doc = _doc({"p0": _record("P0", 4.0), "p1": "строка вместо записи"})
        self.assertEqual(reporter.unparsed_adapter_entries(doc), 1)
        message = reporter.format_protocols_message(doc)
        self.assertIn("НЕ РАЗОБРАНО", message)

    def test_the_named_reason_no_longer_claims_the_fixed_cause(self):
        """ЗВЕНО: прежняя причина «раздел пришёл словарём» стала НЕПРАВДОЙ.

        Пережившая правку проза врёт владельцу тише, чем молчание: читатель
        принимает обе формы, и уронить запись теперь может только то, что она
        не запись.
        """
        doc = _doc({"p0": _record("P0", 4.0), "p1": 42})
        message = reporter.format_protocols_message(doc)
        self.assertIn("НЕ РАЗОБРАНО", message)
        self.assertNotIn("читатель ждёт список", message)

    def test_silent_day_prints_no_dropped_line(self):
        """ЗВЕНО: ронять нечего ⇒ строки нет вовсе, а не «уронено 0»."""
        doc = _doc({"p0": _record("P0", 4.0)})
        self.assertNotIn("НЕ РАЗОБРАНО", reporter.format_protocols_message(doc))

    def test_one_copy_of_the_shape_rule(self):
        """ЗВЕНО: оба читателя формы — ОДНА функция.

        До ADR-710 их было два, и они читали форму по-разному: именно поэтому
        сторож исправно считал «уронено 34», пока отчёт ронял всё.
        """
        doc = _doc({"p0": _record("P0", 4.0), "p1": "не запись"})
        records, dropped = reporter._adapter_section_records(doc)
        self.assertEqual(len(records), len(reporter._get_all_adapters(doc)))
        self.assertEqual(dropped, reporter.unparsed_adapter_entries(doc))


class LegacyShadowIsMergedWithItsModernTwin(unittest.TestCase):
    """Звено 3 — личность записи. Сломано ⇒ владелец читает протокол ДВАЖДЫ."""

    def test_separator_only_alias_is_the_same_protocol(self):
        """ЗВЕНО: ключ раздела `pendle_pt` против тени `protocol_key: pendle-pt`.

        Замер живого артефакта 2026-10-13: ровно эта пара давала владельцу две
        строки про Pendle — современную и тень со ставкой-эхом 8.0.
        """
        doc = _doc(
            {"pendle_pt": _record("Pendle PT", 8.0, live=False, fallback_apy=8.0)},
            pendle_pt={"apy": 8.0, "tier": "T2", "protocol_key": "pendle-pt"},
        )
        self.assertEqual(_shown(doc), 1)

    def test_modern_record_wins_over_its_shadow(self):
        """ЗВЕНО: из двух близнецов остаётся СОВРЕМЕННЫЙ (он несёт род)."""
        doc = _doc(
            {"aave_arbitrum": _record("Aave V3 Arbitrum", 3.13)},
            aave_arbitrum={"apy": 9.99, "tier": "T1"},
        )
        rows = reporter._get_all_adapters(doc)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].get("display_name"), "Aave V3 Arbitrum")
        self.assertEqual(rows[0].get("live_apy"), 3.13)

    def test_legacy_blob_without_a_twin_keeps_its_row(self):
        """ЗВЕНО: дедупликация не имеет права ПРЯТАТЬ строку.

        Цена односторонности названа в `_dedup_identity`: ошибка идёт в сторону
        слияния, поэтому «легаси без близнеца» обязан остаться виден.
        """
        doc = _doc(
            {"p0": _record("P0", 4.0)},
            lone_legacy={"apy": 5.5, "tier": "T2"},
        )
        self.assertEqual(_shown(doc), 2)

    def test_dedup_identity_does_not_touch_the_displayed_name(self):
        """ЗВЕНО: нечувствительность — только у ЛИЧНОСТИ, не у отображения."""
        doc = _doc({"pendle_pt": _record("Pendle-PT REST", 8.0)})
        self.assertIn("Pendle-PT REST", reporter.format_protocols_message(doc))

    def test_two_genuinely_different_protocols_are_not_merged(self):
        """ЗВЕНО: разные протоколы остаются двумя строками."""
        doc = _doc({"aave_v3": _record("Aave V3", 4.3), "spark": _record("Spark", 3.8)})
        self.assertEqual(_shown(doc), 2)


class ProbeIsRedOnEachBrokenLink(unittest.TestCase):
    """Звено 4 — сама проба. Зелёная на целом контуре, красная на каждом рве."""

    def test_green_on_a_whole_contour(self):
        doc = _doc({f"p{i}": _record(f"P{i}", 4.0 + i) for i in range(34)})
        verdict, detail = _probe(doc)
        self.assertEqual(verdict, ca.SATISFIED, detail)
        self.assertIn("ждём 34", detail)
        self.assertIn("печатает 34", detail)

    def test_list_only_traversal_is_the_2026_10_12_outage(self):
        """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: авария дословно — обход только списком.

        Читателю возвращается поведение до ADR-710. Проба ОБЯЗАНА краснеть;
        зелёный здесь означал бы, что она ничего не меряет.
        """
        original = reporter._adapter_section_records

        def list_only(data: dict):
            section = data.get("adapters") if isinstance(data, dict) else None
            if isinstance(section, list):
                return [(None, v) for v in section if isinstance(v, dict)], 0
            return [], None

        reporter._adapter_section_records = list_only
        try:
            doc = _doc({f"p{i}": _record(f"P{i}", 4.0 + i) for i in range(34)})
            self.assertEqual(_shown(doc), 0)
            verdict, detail = _probe(doc)
        finally:
            reporter._adapter_section_records = original
        self.assertEqual(verdict, ca.NOT_SATISFIED, detail)
        self.assertIn("теряет 34", detail)

    def test_denominator_is_not_taken_from_the_measured_reader(self):
        """ЗВЕНО: знаменатель независим.

        Знаменатель, взятый у читателя, равен числителю по построению — такая
        проба зелена и на полностью сломанном читателе. Здесь читатель отдаёт
        пустой отчёт, и проба обязана это увидеть.
        """
        original = reporter.format_protocols_message
        reporter.format_protocols_message = lambda data: "📊 пусто\n*System*\nCapital: $0"
        try:
            verdict, detail = _probe(_doc({"p0": _record("P0", 4.0)}))
        finally:
            reporter.format_protocols_message = original
        self.assertEqual(verdict, ca.NOT_SATISFIED, detail)
        self.assertIn("теряет 1", detail)

    def test_extra_rows_are_red_too(self):
        """ЗВЕНО: двусторонность — лишняя строка тоже дефект населения."""
        original = reporter.format_protocols_message
        reporter.format_protocols_message = lambda data: "• *лишний*\n• *и ещё*"
        try:
            verdict, detail = _probe(_doc({"p0": _record("P0", 4.0)}))
        finally:
            reporter.format_protocols_message = original
        self.assertEqual(verdict, ca.NOT_SATISFIED, detail)
        self.assertIn("лишние 1", detail)

    def test_denominator_counts_a_legacy_blob_without_a_twin(self):
        """ЗВЕНО: легаси-блок без близнеца ВХОДИТ в знаменатель.

        Найдено МУТАЦИЕЙ собственной батареи: `expected = len(section_records)`
        (без слагаемого легаси) выживал, потому что ни один тест пробы легаси-блока
        не содержал вовсе. Проба, чей знаменатель не видит легаси, объявила бы
        лишней ту строку, которую отчёт обязан печатать.
        """
        doc = _doc({"p0": _record("P0", 4.0)}, lone_legacy={"apy": 5.5, "tier": "T2"})
        verdict, detail = _probe(doc)
        self.assertEqual(verdict, ca.SATISFIED, detail)
        self.assertIn("ждём 2", detail)
        self.assertIn("легаси без близнеца 1", detail)

    def test_denominator_excludes_a_legacy_shadow_that_has_a_twin(self):
        """ЗВЕНО: тень, у которой есть современный близнец, НЕ удваивает знаменатель.

        Найдено МУТАЦИЕЙ: `if ident not in section_ids` → `if True` выживал.
        Знаменатель, считающий тень отдельно, требовал бы от отчёта печатать
        протокол ДВАЖДЫ — тот самый дефект, который `_dedup_identity` и закрыл.
        """
        doc = _doc(
            {"pendle_pt": _record("Pendle PT", 8.0, live=False, fallback_apy=8.0)},
            pendle_pt={"apy": 8.0, "tier": "T2", "protocol_key": "pendle-pt"},
        )
        verdict, detail = _probe(doc)
        self.assertEqual(verdict, ca.SATISFIED, detail)
        self.assertIn("ждём 1", detail)
        self.assertIn("легаси без близнеца 0", detail)

    def test_dropped_member_is_red(self):
        """ЗВЕНО: уронённый член — отказ, а не зелёный «ну почти всё»."""
        doc = _doc({"p0": _record("P0", 4.0), "p1": "не запись"})
        verdict, detail = _probe(doc)
        self.assertEqual(verdict, ca.NOT_SATISFIED, detail)
        self.assertIn("не являющиеся записями", detail)

    def test_reader_that_raises_is_unmeasured_not_satisfied(self):
        """ЗВЕНО: читатель упал ⇒ ТРЕТИЙ исход, не вердикт о предмете."""
        original = reporter.format_protocols_message

        def boom(data):
            raise RuntimeError("дверь закрыта")

        reporter.format_protocols_message = boom
        try:
            verdict, detail = _probe(_doc({"p0": _record("P0", 4.0)}))
        finally:
            reporter.format_protocols_message = original
        self.assertEqual(verdict, ca.UNMEASURED, detail)
        self.assertIn("RuntimeError", detail)


class ProbeThirdOutcomes(unittest.TestCase):
    """Звено 5 — «не измерено» НИКОГДА не выдаётся за «чисто» (инв. #17)."""

    def test_stale_artifact_is_unmeasured(self):
        """ЗВЕНО: возраст — часть вопроса; замороженный канон не наблюдение."""
        doc = _doc({f"p{i}": _record(f"P{i}", 4.0) for i in range(34)}, age_hours=500.0)
        verdict, detail = _probe(doc)
        self.assertEqual(verdict, ca.UNMEASURED, detail)
        self.assertIn("протух", detail)

    def test_time_is_an_input_not_the_wall_clock(self):
        """ЗВЕНО: один и тот же артефакт, два `now` ⇒ два вердикта."""
        doc = _doc({"p0": _record("P0", 4.0)}, age_hours=1.0)
        fresh, _ = _probe(doc, now=_ANCHOR)
        stale, _ = _probe(doc, now=_ANCHOR + timedelta(hours=200))
        self.assertEqual(fresh, ca.SATISFIED)
        self.assertEqual(stale, ca.UNMEASURED)

    def test_missing_artifact_is_unmeasured(self):
        with TemporaryDirectory() as tmp:
            verdict, detail = ca.PROBES[PROBE_NAME](None, data_dir=tmp, now=_ANCHOR)
        self.assertEqual(verdict, ca.UNMEASURED, detail)
        self.assertIn("нет в этом дереве", detail)

    def test_unparseable_artifact_is_unmeasured(self):
        with TemporaryDirectory() as tmp:
            (Path(tmp) / "adapter_status.json").write_text("{не json", encoding="utf-8")
            verdict, detail = ca.PROBES[PROBE_NAME](None, data_dir=tmp, now=_ANCHOR)
        self.assertEqual(verdict, ca.UNMEASURED, detail)
        self.assertIn("не разобран", detail)

    def test_artifact_without_generated_at_is_unmeasured(self):
        doc = _doc({"p0": _record("P0", 4.0)})
        doc.pop("generated_at")
        verdict, detail = _probe(doc)
        self.assertEqual(verdict, ca.UNMEASURED, detail)
        self.assertIn("возраст не измерен", detail)

    def test_section_of_a_wrong_shape_entirely_is_unmeasured(self):
        verdict, detail = _probe(_doc("не раздел"))
        self.assertEqual(verdict, ca.UNMEASURED, detail)
        self.assertIn("не той формы вовсе", detail)


class ProbeDoesNotPassBySubstring(unittest.TestCase):
    """Звено 6 — вердикт считается ЧИСЛАМИ (ADR-333)."""

    def test_prose_inside_a_protocol_name_changes_nothing(self):
        """ЗВЕНО: текст отчёта вердикта не назначает.

        Имя протокола несёт дословно ту прозу, которой проба могла бы
        соблазниться, — вердикт обязан остаться прежним.
        """
        doc = _doc(
            {
                "p0": _record("НЕ РАЗОБРАНО записей раздела `adapters`: 34", 4.0),
                "p1": _record("satisfied", 5.0),
            }
        )
        verdict, detail = _probe(doc)
        self.assertEqual(verdict, ca.SATISFIED, detail)
        self.assertIn("ждём 2", detail)

    def test_probe_is_registered_by_name(self):
        """ЗВЕНО: проба, потерявшая регистрацию, не меряет ничего."""
        self.assertIn(PROBE_NAME, ca.PROBES)


if __name__ == "__main__":
    unittest.main()
