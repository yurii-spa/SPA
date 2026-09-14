"""Сторож прибора «цена починки молчащей ноги в ДНЯХ знаменателя» (заказ #598/G12).

Каждый тест — либо положительный контроль (воспроизводит поломку, которая делает ответ
недействительным, и обязан покраснеть), либо закрепление границы утверждения.

Даты в фикстурах — ПРЕДМЕТ, а не якорь свежести: см. пометку под докстрингом.
"""
# FROZEN-DATE-OK: dates-are-the-subject — `cycle_date` есть ЛИЧНОСТЬ дня журнала: по ней
# идут сортировка и выбор форвардного окна, и заменить её относительной отметкой значило
# бы стереть предмет. Понятия свежести у прибора нет ВОВСЕ — ни окна, ни TTL, ни сравнения
# с настенными часами; собственная отметка `generated_at` приходит параметром `now=` (NOW
# ниже). Сдвиг календаря на вердикт этих тестов повлиять не может ни через одну дверь.
from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Dict, List, Optional

from spa_core.monitoring import hit_rate_denominator_recovery as _rec
from spa_core.monitoring import polled_never_observed_census as _census
from spa_core.monitoring import silent_leg_day_price as sp
from spa_core.monitoring import unobserved_leg_remedy_class as _remedy
from spa_core.paper_trading import shadow_trigger_eval as _ste

NOW = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)

#: Ключи стенда — НАСТОЯЩИЕ имена из `POLLED_ADAPTERS`. Выдуманные имена сделали бы сцену
#: недостижимой для честной переписи (она берёт население из кода), и тест про субъект
#: превратился бы в тест про подмену.
SILENT = "pendle"          # субъект: опрашивается, в ряду ни одной точки
SECOND = "morpho_blue"     # вторая нога: опрашивается и наблюдалась
OUTSIDER = "spark_susds"   # нога вне опрашиваемого набора — рычаг владельца
OTHER = "maple"


def _day(date: str, *, current: Dict[str, float], target: Dict[str, float],
         verdict: str = "HOLD", evidenced: Optional[Dict[str, float]] = None,
         turnover: Optional[float] = None, cost: float = 1.0) -> dict:
    rec = {
        "cycle_date": date,
        "book_id": "main",
        "verdict": verdict,
        "current_positions": dict(current),
        "target_positions": dict(target),
        "apy_evidenced_pct": dict(evidenced or {}),
        "cost_usd": cost,
        "capital_usd": 100000.0,
    }
    if turnover is not None:
        rec["turnover_usd"] = turnover
    return rec


def _write_journal(data_dir: Path, rows: List[dict]) -> None:
    with (data_dir / _ste.HISTORY_FILENAME).open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _write_census_inputs(data_dir: Path, *, silent: str, observed_keys: List[str]) -> None:
    """Настоящие входы переписи ADR-379: ряд, снимок производителя и книга.

    Молчащая нога предъявлена ПРОИЗВОДИТЕЛЕМ и отсутствует в ряду — ровно та форма, при
    которой перепись выносит `never_observed`. Ни один её вердикт здесь не подставляется.
    """
    series = {k: [["2026-09-01", 4.0], ["2026-09-02", 4.1]] for k in observed_keys}
    (data_dir / _census.SERIES_FILENAME).write_text(
        json.dumps({"series": series}), encoding="utf-8")
    (data_dir / _census.PRODUCER_FILENAME).write_text(
        json.dumps({"adapters": {k: {} for k in observed_keys + [silent]}}),
        encoding="utf-8")
    (data_dir / _census.BOOK_FILENAME).write_text(
        json.dumps({"positions": {SECOND: 40000.0}}), encoding="utf-8")


class _Case(unittest.TestCase):
    """Общий стенд: три исхода дня непусты одновременно.

    Журнал устроен так, чтобы у прибора было что терять в КАЖДУЮ сторону:
    один день лежит в знаменателе (иначе монотонности нечего ронять), один поднимается
    субъектом в одиночку, один держит вторая нога НАШЕГО кода, один — нога владельца.
    Стенд, в котором какой-то исход пуст, сделал бы соответствующий контроль украшением.
    """

    def _journal(self) -> List[dict]:
        return [
            # (A) поднимается СУБЪЕКТОМ в одиночку: единственная неоценённая нога — он
            _day("2026-01-01", current={OTHER: 40000.0}, target={SILENT: 40000.0}),
            # (B) держит ВТОРАЯ нога нашего кода: ни на одном форварде нет SECOND
            _day("2026-01-02", current={OTHER: 40000.0},
                 target={SILENT: 20000.0, SECOND: 20000.0}),
            # (C) держит нога ВЛАДЕЛЬЦА: OUTSIDER не опрашивается вовсе
            _day("2026-01-03", current={OTHER: 40000.0},
                 target={SILENT: 20000.0, OUTSIDER: 20000.0}),
            # (E) восстановим в принципе, но субъект его НЕ блокирует. Без такого дня
            # «блокирующие дни ЭТОЙ ноги» неотличимы от «все восстановимые дни», и
            # центральное утверждение прибора не спрашивает никто.
            _day("2026-01-04", current={OTHER: 40000.0}, target={SECOND: 40000.0}),
            # (D) в знаменателе: обе двигаемые ноги оценены на форвардном дне
            _day("2026-01-05", current={OTHER: 40000.0},
                 target={OTHER: 20000.0, "aave_v3": 20000.0},
                 evidenced={OTHER: 5.0}),
            _day("2026-01-06", current={OTHER: 20000.0, "aave_v3": 20000.0},
                 target={OTHER: 20000.0, "aave_v3": 20000.0},
                 evidenced={OTHER: 5.0, "aave_v3": 3.0}, turnover=0.0),
            _day("2026-01-07", current={OTHER: 20000.0, "aave_v3": 20000.0},
                 target={OTHER: 20000.0, "aave_v3": 20000.0},
                 evidenced={OTHER: 5.0, "aave_v3": 3.0}, turnover=0.0),
        ]

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.data_dir = Path(self._tmp.name)
        _write_journal(self.data_dir, self._journal())
        _write_census_inputs(self.data_dir, silent=SILENT,
                             observed_keys=[SECOND, OTHER, "aave_v3"])
        self.addCleanup(self._tmp.cleanup)

    def measure(self, **kwargs) -> dict:
        return sp.measure(self.data_dir, now=NOW, **kwargs)

    def leg(self, doc: dict, name: str = SILENT) -> dict:
        rows = [r for r in (doc.get("per_leg") or []) if r["leg"] == name]
        self.assertEqual(len(rows), 1, f"в ответе нет ноги {name}: {doc.get('per_leg')}")
        return rows[0]


class TestSubjectComesFromTheCensus(_Case):
    """Субъект берётся у канонического производителя, а не вписан литералом."""

    def test_subject_is_named_by_the_real_census_without_any_stub(self):
        """Центральное утверждение модуля, спрошенное БЕЗ подмены переписи.

        Контроль, истинный по построению, есть украшение: если бы каждая сцена
        подменяла перепись, никто ни разу не проверил бы, что имя приходит именно
        оттуда.
        """
        doc = self.measure()
        self.assertTrue(doc["subjects"]["measured"], doc["subjects"])
        self.assertEqual(doc["subjects"]["legs"], [SILENT])
        self.assertEqual([r["leg"] for r in doc["per_leg"]], [SILENT])

    def test_subject_follows_the_census_when_the_silent_leg_changes(self):
        """Положительный контроль имени: молчит ДРУГАЯ нога ⇒ субъект другой.

        Без этого теста имя `pendle` могло бы быть зашито в модуль, и сцена выше
        прошла бы всё равно.
        """
        _write_census_inputs(self.data_dir, silent=SECOND,
                             observed_keys=[SILENT, OTHER, "aave_v3"])
        doc = self.measure()
        self.assertEqual(doc["subjects"]["legs"], [SECOND])
        self.assertEqual([r["leg"] for r in doc["per_leg"]], [SECOND])

    def test_census_refusal_is_a_third_outcome_not_an_empty_subject_list(self):
        """Положительный контроль: перепись отказала ⇒ UNMEASURED, а не «молчащих нет»."""
        (self.data_dir / _census.SERIES_FILENAME).write_text("{}", encoding="utf-8")
        doc = self.measure()
        self.assertEqual(doc["status"], sp.STATUS_UNMEASURED)
        self.assertIn("перепись молчащих ног", doc["unmeasured_reason"])
        self.assertNotIn("answer", doc)

    def test_census_exception_is_a_third_outcome_too(self):
        """Отказ переписи ИСКЛЮЧЕНИЕМ обязан звучать так же, как её отказ вердиктом."""
        original = _census.measure
        try:
            def boom(*_a, **_k):
                raise RuntimeError("перепись упала")
            _census.measure = boom
            doc = self.measure()
        finally:
            _census.measure = original
        self.assertEqual(doc["status"], sp.STATUS_UNMEASURED)
        self.assertIn("RuntimeError", doc["unmeasured_reason"])

    def test_measured_zero_of_silent_legs_is_not_the_refusal(self):
        """Инв. #17: перепись прошла и молчащих не нашла ≠ перепись не читалась."""
        _write_census_inputs(self.data_dir, silent="",
                             observed_keys=[SILENT, SECOND, OTHER, "aave_v3"])
        doc = self.measure()
        self.assertEqual(doc["status"], sp.STATUS_OK)
        self.assertEqual(doc["per_leg"], [])
        self.assertNotIn("unmeasured_reason", doc)
        self.assertTrue(any("по ИЗМЕРЕНИЮ" in x for x in doc["findings"]), doc["findings"])


class TestThePriceInDays(_Case):
    """Ответ заказа: блокирует ≠ поднимает, и разница названа."""

    def test_blocking_days_are_the_legs_own_not_every_recoverable_day(self):
        """Положительный контроль населения: восстановимых 4, блокирует субъект 3.

        Стенд намеренно держит день, который восстановим и субъектом НЕ блокируется:
        сравняй эти два числа — и цена ноги вырастет на чужой день.
        """
        doc = self.measure()
        self.assertEqual(doc["population"]["recoverable_in_principle"], 4)
        self.assertEqual(self.leg(doc)["blocking_days"], 3)
        self.assertNotIn("2026-01-04", self.leg(doc)["blocking_day_list"])

    def test_blocking_days_exceed_lifted_days_and_both_are_reported(self):
        doc = self.measure()
        row = self.leg(doc)
        self.assertEqual(row["blocking_days"], 3, row)
        self.assertEqual(row["days_lifted_alone"], 1, row)
        self.assertEqual(row["days_lifted_alone_list"], ["2026-01-01"])
        self.assertEqual(row["days_held_by_second_leg"], 2, row)

    def test_denominator_moves_by_exactly_the_days_lifted_alone(self):
        doc = self.measure()
        row = self.leg(doc)
        self.assertEqual(row["denominator_leg_alone"] - row["denominator_today"],
                         row["days_lifted_alone"])

    def test_the_correction_line_is_printed_when_the_two_counts_differ(self):
        """Поправка соседу — ОТДЕЛЬНАЯ строка, а не оговорка в шапке модуля."""
        doc = self.measure()
        self.assertTrue(any(x.startswith("[ПОПРАВКА]") for x in doc["findings"]),
                        doc["findings"])

    def test_hit_rate_value_is_never_computed(self):
        """Граница ADR-300: критерий под сентинелом не печатается ни в каком виде."""
        doc = self.measure()
        self.assertIsNone(doc["answer"]["hit_rate_after"])
        blob = json.dumps(doc, ensure_ascii=False)
        self.assertNotIn("hit_rate_value", blob)


class TestHoldersAreNamedAndProven(_Case):
    """«Держит вторая нога» — замер с контролем достаточности, а не список."""

    def test_second_leg_of_our_code_is_named_with_its_cause(self):
        doc = self.measure()
        held = {h["cycle_date"]: h for h in self.leg(doc)["held_detail"]}
        ours = held["2026-01-02"]
        self.assertEqual(ours["held_by"], [SECOND])
        self.assertEqual(ours["causes"][SECOND], sp.CAUSE_POLLED_OBSERVED)
        self.assertEqual(ours["outcome"], sp.DAY_HELD_BY_OUR_CODE)
        self.assertEqual(ours["owner_legs"], [])

    def test_owner_leg_is_a_separate_outcome_from_our_code(self):
        """Инв. #17: «чиним мы» и «рычаг у владельца» не сливаются в один счёт."""
        doc = self.measure()
        row = self.leg(doc)
        held = {h["cycle_date"]: h for h in row["held_detail"]}
        owner = held["2026-01-03"]
        self.assertEqual(owner["held_by"], [OUTSIDER])
        self.assertEqual(owner["causes"][OUTSIDER], sp.CAUSE_NOT_POLLED)
        self.assertEqual(owner["outcome"], sp.DAY_HELD_BY_OWNER)
        self.assertEqual(owner["owner_legs"], [OUTSIDER])
        self.assertEqual(row["days_held_our_code"], 1)
        self.assertEqual(row["days_held_owner"], 1)

    def test_owner_held_day_makes_the_verdict_critical(self):
        doc = self.measure()
        self.assertEqual(doc["status"], sp.STATUS_CRITICAL)

    def test_sufficiency_control_is_verified_for_every_named_holder(self):
        """Назвал держащих — показал, что назвал верно, по КАЖДОМУ дню."""
        doc = self.measure()
        self.assertTrue(doc["sufficiency_control"]["passed"], doc["sufficiency_control"])
        for h in self.leg(doc)["held_detail"]:
            self.assertTrue(h["sufficiency_verified"], h)

    def test_sufficiency_control_reddens_when_the_named_set_does_not_lift(self):
        """Положительный контроль: назови не тех — прибор обязан ОТКАЗАТЬ.

        Порча идёт в `cheapest_holders`, то есть ровно в том месте, где набор
        держащих и рождается; порча соседней строки прошла бы мимо предмета.
        """
        original = sp.cheapest_holders
        try:
            sp.cheapest_holders = lambda rows: (
                (rows[0][0] if rows else None), ["nobody_holds_this"])
            doc = self.measure()
        finally:
            sp.cheapest_holders = original
        self.assertEqual(doc["status"], sp.STATUS_UNMEASURED)
        self.assertIn("контроль достаточности", doc["unmeasured_reason"])
        self.assertNotIn("answer", doc)

    def test_a_held_day_without_any_named_holder_is_unmeasured_not_lifted(self):
        """Положительный контроль: день не поднялся, держащих не нашлось ⇒ третий исход."""
        original = sp.cheapest_holders
        try:
            sp.cheapest_holders = lambda rows: (None, [])
            doc = self.measure()
        finally:
            sp.cheapest_holders = original
        self.assertEqual(doc["status"], sp.STATUS_UNMEASURED)
        self.assertIn("не разобрано", doc["unmeasured_reason"])


class TestCauseOfHolder(_Case):
    """Род починки второй ноги измерен, и порядок проверки — предмет."""

    def test_renamed_key_is_checked_before_not_polled(self):
        """Переименованный ключ НЕ отдаётся владельцу: это те же деньги под новым именем.

        Проверь порядок наоборот — и работа, лежащая у нас, уехала бы в очередь
        владельца (память `renamed-key-is-a-remedy-class`).
        """
        cause = sp.cause_of("fluid_usdc", polled={"fluid_fusdc"},
                            twins={"fluid_usdc": ["fluid_fusdc"]}, silent=set())
        self.assertEqual(cause, sp.CAUSE_RENAMED)
        self.assertNotIn(cause, sp.OWNER_CAUSES)

    def test_silent_in_series_is_checked_before_not_polled(self):
        cause = sp.cause_of("x", polled=set(), twins={}, silent={"x"})
        self.assertEqual(cause, sp.CAUSE_SILENT)
        self.assertNotIn(cause, sp.OWNER_CAUSES)

    def test_not_polled_is_the_only_owner_cause(self):
        self.assertEqual(sp.OWNER_CAUSES, frozenset({sp.CAUSE_NOT_POLLED}))
        self.assertEqual(sp.cause_of("x", polled=set(), twins={}, silent=set()),
                         sp.CAUSE_NOT_POLLED)

    def test_polled_and_observed_is_our_code(self):
        self.assertEqual(sp.cause_of("x", polled={"x"}, twins={}, silent=set()),
                         sp.CAUSE_POLLED_OBSERVED)

    def test_every_cause_in_order_is_reachable(self):
        """Род, который не возвращается ни при каком входе, — мёртвая ветка отчёта."""
        produced = {
            sp.cause_of("a", polled=set(), twins={"a": ["b"]}, silent=set()),
            sp.cause_of("a", polled=set(), twins={}, silent={"a"}),
            sp.cause_of("a", polled=set(), twins={}, silent=set()),
            sp.cause_of("a", polled={"a"}, twins={}, silent=set()),
        }
        self.assertEqual(produced, set(sp.CAUSE_ORDER))


class TestCheapestHolders(unittest.TestCase):
    """Минимум по мощности — не объединение и не пересечение."""

    def test_minimum_cardinality_forward_day_wins(self):
        rows = [("d1", ["a", "b"]), ("d2", ["c"]), ("d3", ["a", "b", "c"])]
        self.assertEqual(sp.cheapest_holders(rows), ("d2", ["c"]))

    def test_union_would_overstate_and_is_not_what_is_returned(self):
        rows = [("d1", ["a"]), ("d2", ["b"])]
        _date, missing = sp.cheapest_holders(rows)
        self.assertEqual(len(missing), 1)
        self.assertNotEqual(set(missing), {"a", "b"})

    def test_no_forward_days_yields_no_holders_and_no_date(self):
        self.assertEqual(sp.cheapest_holders([]), (None, []))


class TestHoldersByForwardDay(_Case):
    """Разбор форвардных дней отвечает про КОНКРЕТНЫЙ день, а не про журнал."""

    def test_unknown_date_is_none_not_an_empty_list(self):
        records = {r["cycle_date"]: r for r in self._journal()}
        self.assertIsNone(sp.holders_by_forward_day(records, "1999-01-01", 7))
        self.assertIsNotNone(sp.holders_by_forward_day(records, "2026-01-01", 7))

    def test_rows_are_limited_by_the_horizon(self):
        records = {r["cycle_date"]: r for r in self._journal()}
        rows = sp.holders_by_forward_day(records, "2026-01-01", 2)
        self.assertEqual([d for d, _ in rows], ["2026-01-02", "2026-01-03"])


class TestWriterLeverFloor(_Case):
    """Пол рычага писателя: сколько его дней стои́т на молчащей ноге."""

    def test_floor_excludes_the_silent_leg_and_the_gap_is_reported(self):
        doc = self.measure()
        row = self.leg(doc)
        self.assertEqual(row["writer_days_resting_on_leg"],
                         row["writer_lever_with_leg"] - row["writer_lever_floor_without_leg"])
        self.assertGreater(row["writer_days_resting_on_leg"], 0, row)
        self.assertTrue(any(x.startswith("[ПОЛ РЫЧАГА]") for x in doc["findings"]),
                        doc["findings"])

    def test_floor_is_measured_by_removing_the_leg_from_the_polled_set(self):
        """Пол обязан быть НЕ ВЫШЕ потолка: иначе изъятие ноги мерит не тот путь."""
        row = self.leg(self.measure())
        self.assertLessEqual(row["writer_lever_floor_without_leg"],
                             row["writer_lever_with_leg"])


class TestControls(_Case):
    """Контроли отказывают ГРОМКО, и каждый воспроизводит свою поломку."""

    def test_canonical_parity_refusal_is_a_third_outcome(self):
        original = _ste.scored_days
        try:
            _ste.scored_days = lambda *a, **k: None  # noqa: E731
            doc = self.measure()
        finally:
            _ste.scored_days = original
        self.assertEqual(doc["status"], sp.STATUS_UNMEASURED)
        self.assertIn("канонический знаменатель", doc["unmeasured_reason"])

    def test_canonical_disagreement_refuses(self):
        original = _ste.scored_days
        try:
            _ste.scored_days = lambda *a, **k: {"2026-01-01", "2026-01-02", "2026-01-03"}
            doc = self.measure()
        finally:
            _ste.scored_days = original
        self.assertEqual(doc["status"], sp.STATUS_UNMEASURED)
        self.assertIn("разошёлся", doc["unmeasured_reason"])

    def test_copy_parity_refusal_is_loud(self):
        """Положительный контроль: возмущение врёт при ПУСТОМ наборе ⇒ отказ."""
        original = _rec.perturb
        try:
            def liar(records, **kwargs):
                out = original(records, **kwargs)
                first = sorted(out)[0]
                out[first]["turnover_usd"] = 0.0
                return out
            _rec.perturb = liar
            doc = self.measure()
        finally:
            _rec.perturb = original
        self.assertEqual(doc["status"], sp.STATUS_UNMEASURED)
        self.assertIn("паритета копирования", doc["unmeasured_reason"])

    def test_monotonicity_refusal_is_loud(self):
        """Положительный контроль: выдача ставки ВЫБРОСИЛА день ⇒ мерим не тот путь."""
        original = _rec.perturb
        try:
            def shrinker(records, **kwargs):
                out = original(records, **kwargs)
                if kwargs.get("extra_keys"):
                    out["2026-01-05"]["turnover_usd"] = 0.0
                return out
            _rec.perturb = shrinker
            doc = self.measure()
        finally:
            _rec.perturb = original
        self.assertEqual(doc["status"], sp.STATUS_UNMEASURED)
        self.assertIn("онотонность", doc["unmeasured_reason"])

    def test_polled_refusal_is_a_third_outcome_not_an_empty_set(self):
        original = _remedy._polled_keys
        try:
            _remedy._polled_keys = lambda *a, **k: None  # noqa: E731
            doc = self.measure()
        finally:
            _remedy._polled_keys = original
        self.assertEqual(doc["status"], sp.STATUS_UNMEASURED)
        self.assertIn("POLLED_ADAPTERS", doc["unmeasured_reason"])

    def test_missing_blocking_leg_list_is_unmeasured_not_an_innocent_subject(self):
        """Положительный контроль: списка отвергающих ног нет ⇒ отказ.

        Подстановка пустого списка объявила бы субъекта НЕПРИЧАСТНЫМ к дню — то есть
        напечатала бы заниженную цену как измеренный ответ.
        """
        original = _rec._judge_all
        try:
            def stripped(records, horizon):
                rows = original(records, horizon)
                for row in rows.values():
                    row.pop("unpriced_protocols", None)
                return rows
            _rec._judge_all = stripped
            doc = self.measure()
        finally:
            _rec._judge_all = original
        self.assertEqual(doc["status"], sp.STATUS_UNMEASURED)
        self.assertIn("списка отвергающих ног", doc["unmeasured_reason"])

    def test_empty_journal_is_unmeasured_not_a_zero_price(self):
        _write_journal(self.data_dir, [])
        doc = self.measure()
        self.assertEqual(doc["status"], sp.STATUS_UNMEASURED)
        self.assertIn("журнал решений", doc["unmeasured_reason"])


class TestReportAndWiring(_Case):
    """Ответ обязан быть ПРОЧИТАН: отчёт, счётчики, форма ступени."""

    def test_report_names_the_leg_and_all_three_counts(self):
        lines = sp.format_report(self.measure())
        blob = "\n".join(lines)
        self.assertIn(SILENT, blob)
        self.assertIn("поднимает в одиночку", blob)
        self.assertIn("владельца", blob)
        self.assertIn("контроль достаточности", blob)

    def test_report_says_unmeasured_out_loud(self):
        (self.data_dir / _census.SERIES_FILENAME).write_text("{}", encoding="utf-8")
        blob = "\n".join(sp.format_report(self.measure()))
        self.assertIn("НЕ ИЗМЕРЕНО", blob)

    def test_run_writes_the_artifact_and_counts_unchecked_separately(self):
        doc = sp.run(root=str(self.data_dir.parent), now=NOW, write=False)
        self.assertIn("counts", doc)
        self.assertIn("unchecked", doc["counts"])
        self.assertEqual(doc["overall"], doc["status"])

    def test_unmeasured_is_counted_as_unchecked_not_as_clean(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "data").mkdir()
        doc = sp.run(root=str(root), now=NOW, write=False)
        self.assertEqual(doc["status"], sp.STATUS_UNMEASURED)
        # ОБА слагаемых названы поимённо: вердикт UNMEASURED даёт единицу САМ, и
        # строки findings дают свои. Проверка «>= 1» прикрывала бы потерю первого.
        from_findings = sum(1 for x in doc["findings"] if x.startswith("[НЕ ИЗМЕРЕНО]"))
        self.assertGreaterEqual(from_findings, 1)
        self.assertEqual(doc["counts"]["unchecked"], 1 + from_findings)
        self.assertEqual(doc["counts"]["critical"], 0)

    def test_boundaries_of_the_claim_travel_inside_the_artifact(self):
        doc = self.measure()
        self.assertTrue(doc["what_it_does_not_prove"])
        self.assertIn("ADVISORY", doc["advisory"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
