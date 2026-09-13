"""Сторож прибора «мощность знаменателя hit_rate под рычагом» (заказ #591/G8).

Каждый тест — либо положительный контроль (воспроизводит поломку, которая делает
ответ недействительным, и обязан покраснеть), либо закрепление границы утверждения.

Даты в фикстурах — ПРЕДМЕТ, а не якорь свежести: см. пометку под докстрингом.
"""
# FROZEN-DATE-OK: dates-are-the-subject — `cycle_date` есть ЛИЧНОСТЬ дня журнала:
# по ней идут сортировка и выбор форвардного окна, и заменить её относительной
# отметкой значило бы стереть предмет. Понятия свежести у прибора нет ВОВСЕ — ни
# окна, ни TTL, ни сравнения с настенными часами; собственная отметка
# `generated_at` приходит параметром `now=` (см. NOW ниже). Сдвиг календаря на
# вердикт этих тестов повлиять не может ни через одну дверь.
from __future__ import annotations

import copy
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Dict, List, Optional

from spa_core.monitoring import g1_verdict_recoverability as _g1
from spa_core.monitoring import hit_rate_denominator_recovery as hr
from spa_core.monitoring import unobserved_leg_remedy_class as _remedy
from spa_core.paper_trading import shadow_trigger_eval as _ste

NOW = datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)


def _day(date: str, *, current: Dict[str, float], target: Dict[str, float],
         verdict: str = "HOLD", evidenced: Optional[Dict[str, float]] = None,
         unevidenced=None, turnover: Optional[float] = None,
         cost: float = 1.0) -> dict:
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
    if unevidenced is not None:
        rec["apy_unevidenced"] = unevidenced
    return rec


def _write(data_dir: Path, rows: List[dict]) -> None:
    path = data_dir / _ste.HISTORY_FILENAME
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


class _Case(unittest.TestCase):
    """Общий стенд: журнал, у которого один день заведомо без вердикта."""

    #: Журнал стенда устроен так, чтобы ОБА исхода были непусты: один день ЛЕЖИТ в
    #: знаменателе (иначе монотонности нечего терять и контроль был бы украшением),
    #: другой отвергнут ровно одной ногой, которой нет НИ НА ОДНОМ форвардном дне.
    def _journal(self) -> List[dict]:
        return [
            # отвергнут: `comp` не оценён ни на одном форвардном дне
            _day("2026-01-01", current={"aave": 40000.0}, target={"comp": 40000.0},
                 evidenced={}),
            # в знаменателе: обе двигаемые ноги оценены на форвардных днях
            _day("2026-01-02", current={"aave": 40000.0},
                 target={"aave": 20000.0, "maple": 20000.0},
                 evidenced={"aave": 3.0}),
            _day("2026-01-03", current={"aave": 20000.0, "maple": 20000.0},
                 target={"aave": 20000.0, "maple": 20000.0},
                 evidenced={"aave": 3.0, "maple": 5.0}, turnover=0.0),
            _day("2026-01-04", current={"aave": 20000.0, "maple": 20000.0},
                 target={"aave": 20000.0, "maple": 20000.0},
                 evidenced={"aave": 3.0, "maple": 5.0}, turnover=0.0),
        ]

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.data_dir = Path(self._tmp.name)
        _write(self.data_dir, self._journal())
        self.addCleanup(self._tmp.cleanup)

    def measure(self, **kwargs) -> dict:
        return hr.measure(self.data_dir, now=NOW, **kwargs)


class TestCanonicalParity(_Case):
    """ПАРИТЕТ-1: знаменатель отбирается каноническим правилом, не вторым своим."""

    def test_baseline_equals_canonical_scored_days(self):
        doc = self.measure()
        par = doc["canonical_parity"]
        self.assertTrue(par["passed"], par)
        canon = _ste.scored_days(self.data_dir)
        self.assertEqual(par["canonical_size"], len(canon))
        self.assertEqual(len(canon), 1, "стенд обязан иметь непустой знаменатель")
        self.assertEqual(par["own_size"], len(canon))

    def test_canonical_refusal_is_a_third_outcome_not_an_empty_denominator(self):
        """Положительный контроль: канон не измерен ⇒ UNMEASURED, а не «0 дней»."""
        original = _ste.scored_days
        try:
            _ste.scored_days = lambda *a, **k: None  # noqa: E731
            doc = self.measure()
        finally:
            _ste.scored_days = original
        self.assertEqual(doc["status"], hr.STATUS_UNMEASURED)
        self.assertIn("канонический знаменатель", doc["unmeasured_reason"])
        self.assertNotIn("answer", doc)

    def test_disagreement_with_canonical_refuses_loudly(self):
        """Положительный контроль: разойдись отбор с каноном — числа недействительны."""
        original = _ste.scored_days
        try:
            _ste.scored_days = lambda *a, **k: {"2026-01-01", "2026-01-02"}  # noqa: E731
            doc = self.measure()
        finally:
            _ste.scored_days = original
        self.assertEqual(doc["status"], hr.STATUS_UNMEASURED)
        self.assertIn("разошёлся с каноническим", doc["unmeasured_reason"])


class TestCopyParity(_Case):
    """ПАРИТЕТ-2: при пустом наборе реплей = настоящий судья бит в бит."""

    def test_empty_grant_reproduces_the_judge(self):
        doc = self.measure()
        self.assertTrue(doc["copy_parity"]["passed"], doc["copy_parity"])
        self.assertEqual(doc["copy_parity"]["days_compared"], 4)

    def test_lying_copy_is_caught(self):
        """Положительный контроль: возмущение, портящее запись, обязано покраснеть."""
        original = hr.perturb

        def _liar(records, **kwargs):
            out = original(records, **kwargs)
            for rec in out.values():
                rec["verdict"] = "ACT"  # копия перестала быть копией
            return out

        try:
            hr.perturb = _liar
            doc = self.measure()
        finally:
            hr.perturb = original
        self.assertEqual(doc["status"], hr.STATUS_UNMEASURED)
        self.assertIn("паритета копирования", doc["unmeasured_reason"])

    def test_perturbation_does_not_mutate_the_input(self):
        """Глубина копии — предпосылка паритета, а не деталь реализации."""
        records = {str(r["cycle_date"]): r for r in self._journal()}
        before = copy.deepcopy(records)
        hr.perturb(records, polled={"aave", "comp"}, twins={},
                   grant_polled=True, respect_writer=True, grant_twin=False)
        self.assertEqual(records, before)


class TestAnswerShape(_Case):
    """Ответ — о РАЗМЕРЕ знаменателя, и рычаги измеряются, а не объявляются."""

    def test_writer_universe_returns_the_day_when_the_leg_is_polled(self):
        original = _remedy._polled_keys
        try:
            _remedy._polled_keys = lambda: {"aave", "comp"}  # noqa: E731
            doc = self.measure()
        finally:
            _remedy._polled_keys = original
        self.assertEqual(doc["status"] in (hr.STATUS_OK, hr.STATUS_WARNING), True, doc)
        base = doc["population"]["denominator_today"]
        writer = doc["scenarios"][hr.SC_WRITER]
        self.assertEqual(writer["delta_days"], 1)
        self.assertEqual(writer["denominator"], base + 1)
        self.assertEqual(writer["days_added"], ["2026-01-01"])

    def test_unpolled_leg_leaves_the_day_with_the_owner(self):
        """Нога вне опрашиваемого набора ⇒ наш код дня не возвращает."""
        original = _remedy._polled_keys
        try:
            _remedy._polled_keys = lambda: {"aave"}  # noqa: E731 — comp не опрашивается
            doc = self.measure()
        finally:
            _remedy._polled_keys = original
        self.assertEqual(doc["scenarios"][hr.SC_WRITER]["delta_days"], 0)
        self.assertEqual(doc["scenarios"][hr.SC_OUR_CODE]["recoverable_not_lifted"],
                         ["2026-01-01"])
        self.assertTrue(any(x.startswith("[ЦЕНА]") for x in doc["findings"]))

    def test_ceiling_is_an_upper_bound_on_every_lever(self):
        original = _remedy._polled_keys
        try:
            _remedy._polled_keys = lambda: set()  # noqa: E731
            doc = self.measure()
        finally:
            _remedy._polled_keys = original
        ceiling = doc["scenarios"][hr.SC_CEILING]["denominator"]
        for name, sc in doc["scenarios"].items():
            self.assertLessEqual(sc["denominator"], ceiling, name)
        self.assertEqual(ceiling, doc["population"]["denominator_today"] + 1)

    def test_share_of_ceiling_is_computed_not_constant(self):
        doc = self.measure()
        answer = doc["answer"]
        expected = round(100.0 * answer["denominator_today"]
                         / answer["denominator_ceiling"], 2)
        self.assertEqual(answer["share_of_ceiling_measured_today_pct"], expected)


class TestAdr300Boundary(_Case):
    """ADR-300: вердикт под сентинелом не печатается — ни значением, ни исходом."""

    def test_hit_rate_after_is_never_a_number(self):
        doc = self.measure()
        self.assertIsNone(doc["answer"]["hit_rate_after"])
        self.assertIn("ADR-300", doc["answer"]["hit_rate_after_note"])

    def test_no_outcome_of_a_lifted_day_leaks_into_the_artifact(self):
        original = _remedy._polled_keys
        try:
            _remedy._polled_keys = lambda: {"aave", "comp"}  # noqa: E731
            doc = self.measure()
        finally:
            _remedy._polled_keys = original
        blob = json.dumps(doc, ensure_ascii=False)
        for forbidden in ('"outcome"', '"net_usd"', '"benefit_usd_over_checked_days"',
                          '"hit_rate":'):
            self.assertNotIn(forbidden, blob,
                             f"исход под сентинелом утёк в артефакт: {forbidden}")

    def test_report_says_out_loud_what_it_refuses_to_report(self):
        lines = hr.format_report(self.measure())
        self.assertTrue(any("НЕ ДОКЛАДЫВАЕТ" in x for x in lines), lines)


class TestControls(_Case):
    """Контроли обязаны СРАБАТЫВАТЬ на настоящей поломке, а не украшать отчёт."""

    def test_monotonicity_violation_refuses(self):
        """Положительный контроль: день, выпавший из знаменателя, — не «минус день»."""
        original = hr.perturb

        def _destroyer(records, **kwargs):
            out = original(records, **kwargs)
            if kwargs.get("grant_polled"):
                # день ИЗ ЗНАМЕНАТЕЛЯ теряет цель ⇒ UNCHECKED; отвергнутый день при
                # этом по-прежнему поднимается, то есть падает именно монотонность,
                # а не контроль способности следом за ней
                out["2026-01-02"]["target_positions"] = {}
            return out

        try:
            hr.perturb = _destroyer
            doc = self.measure()
        finally:
            hr.perturb = original
        self.assertEqual(doc["status"], hr.STATUS_UNMEASURED)
        self.assertIn("онотонность", doc["unmeasured_reason"])

    def test_capability_control_is_required_only_when_something_is_recoverable(self):
        rows = [r for r in self._journal() if r["cycle_date"] != "2026-01-01"]
        _write(self.data_dir, rows)
        doc = self.measure()
        self.assertEqual(doc["population"]["recoverable_in_principle"], 0)
        self.assertFalse(doc["capability_control"]["required"])
        self.assertTrue(doc["capability_control"]["passed"])

    def test_capability_failure_refuses_instead_of_reporting_zero(self):
        """Положительный контроль: потолок не поднял ничего ⇒ ноль есть вакуум."""
        original = hr.perturb
        try:
            # Возмущение, которое ничего не выдаёт: потолок обязан остаться пустым.
            hr.perturb = lambda records, **kw: {k: copy.deepcopy(v)
                                                for k, v in records.items()}
            doc = self.measure()
        finally:
            hr.perturb = original
        self.assertEqual(doc["status"], hr.STATUS_UNMEASURED)
        self.assertIn("способности", doc["unmeasured_reason"])

    def test_derivation_disagreement_refuses(self):
        """Положительный контроль: два вывода разошлись ⇒ ответ недействителен."""
        original = hr._structural_member
        try:
            hr._structural_member = lambda *a, **k: True  # noqa: E731
            doc = self.measure()
        finally:
            hr._structural_member = original
        self.assertEqual(doc["status"], hr.STATUS_UNMEASURED)
        self.assertIn("два вывода", doc["unmeasured_reason"])

    def test_two_derivations_agree_on_the_real_journal_shape(self):
        original = _remedy._polled_keys
        try:
            _remedy._polled_keys = lambda: {"aave", "comp"}  # noqa: E731
            doc = self.measure()
        finally:
            _remedy._polled_keys = original
        self.assertTrue(doc["derivation_cross_check"]["passed"],
                        doc["derivation_cross_check"])


class TestThirdOutcome(_Case):
    """Отсутствие наблюдения — отдельное значение, а не ноль и не успех (инв. #17)."""

    def test_unreadable_polled_set_is_unmeasured_not_empty(self):
        original = _remedy._polled_keys
        try:
            _remedy._polled_keys = lambda: None  # noqa: E731
            doc = self.measure()
        finally:
            _remedy._polled_keys = original
        self.assertEqual(doc["status"], hr.STATUS_UNMEASURED)
        self.assertEqual(doc["unmeasured_reason"], hr.NO_POLLED)
        self.assertNotIn("scenarios", doc)

    def test_day_without_a_blocking_leg_list_refuses_instead_of_lowering_the_ceiling(self):
        """Сфабрикованная сцена: в живой истории судья список несёт всегда.

        Без неё ветка была бы украшением, никогда не видевшим поломки: подставленный
        пустой список унёс бы ноги дня из ПОТОЛКА, и день молча стал бы «не поднимает
        никакой рычаг» — ошибка адресата починки, напечатанная как ответ.
        """
        original = _ste._evaluate_verdict

        def _stripped(rec, forward, horizon):
            row = original(rec, forward, horizon)
            if row.get("unchecked_reason") == "no_evidenced_apy_for_moved_legs":
                row.pop("unpriced_protocols", None)
            return row

        try:
            _ste._evaluate_verdict = _stripped
            doc = self.measure()
        finally:
            _ste._evaluate_verdict = original
        self.assertEqual(doc["status"], hr.STATUS_UNMEASURED)
        self.assertIn("списка", doc["unmeasured_reason"])
        self.assertIn("2026-01-01", doc["unmeasured_reason"])
        self.assertNotIn("scenarios", doc)

    def test_empty_journal_is_unmeasured_not_a_zero_denominator(self):
        _write(self.data_dir, [])
        doc = self.measure()
        self.assertEqual(doc["status"], hr.STATUS_UNMEASURED)
        self.assertEqual(doc["unmeasured_reason"], hr.NO_JOURNAL)

    def test_unmeasured_is_counted_apart_from_zeros(self):
        # Корень с ЖИВЫМ журналом: иначе отказ пришёл бы от пустого журнала, и тест
        # проверял бы не тот путь, что назван в его имени.
        root = self.data_dir / "root"
        (root / "data").mkdir(parents=True)
        _write(root / "data", self._journal())
        original = _remedy._polled_keys
        try:
            _remedy._polled_keys = lambda: None  # noqa: E731
            doc = hr.run(root=str(root), now=NOW, write=False)
        finally:
            _remedy._polled_keys = original
        self.assertEqual(doc["unmeasured_reason"], hr.NO_POLLED)
        self.assertGreaterEqual(doc["counts"]["unchecked"], 1)
        self.assertEqual(doc["counts"]["critical"], 0)
        self.assertEqual(doc["counts"]["info"], 0)


class TestWriterVerdictReading(_Case):
    """Две читки рычага писателя, и расхождение — величина, а не отказ."""

    def test_respecting_reading_does_not_override_the_writers_own_verdict(self):
        rows = self._journal()
        # На КАЖДОМ форвардном дне писатель сам объявил отвергающую ногу неэвиденсной.
        for row in rows[1:]:
            row["apy_unevidenced"] = ["comp"]
        _write(self.data_dir, rows)
        original = _remedy._polled_keys
        try:
            _remedy._polled_keys = lambda: {"aave", "comp"}  # noqa: E731
            doc = self.measure()
        finally:
            _remedy._polled_keys = original
        self.assertEqual(doc["scenarios"][hr.SC_WRITER]["delta_days"], 0)
        self.assertEqual(doc["scenarios"][hr.SC_WRITER_OVERRIDING]["delta_days"], 1)
        self.assertEqual(doc["writer_verdict_sensitivity"]["difference_days"], 1)
        self.assertTrue(any(x.startswith("[ЧУВСТВИТЕЛЬНОСТЬ]") for x in doc["findings"]))

    def test_zero_sensitivity_is_stated_out_loud(self):
        """Измерено и равно нулю обязано отличаться от «не измерено» (инв. #17)."""
        original = _remedy._polled_keys
        try:
            _remedy._polled_keys = lambda: {"aave", "comp"}  # noqa: E731
            doc = self.measure()
        finally:
            _remedy._polled_keys = original
        self.assertEqual(doc["writer_verdict_sensitivity"]["difference_days"], 0)
        self.assertTrue(any(x.startswith("[ОПОРА]") for x in doc["findings"]))

    def test_unevidenced_field_is_parsed_in_every_shape_it_has(self):
        self.assertEqual(hr.writer_unevidenced_keys({"apy_unevidenced": ["a", "b"]}),
                         {"a", "b"})
        self.assertEqual(hr.writer_unevidenced_keys({"apy_unevidenced": {"a": 1.0}}),
                         {"a"})
        self.assertEqual(
            hr.writer_unevidenced_keys({"apy_unevidenced": [{"protocol": "a"}]}), {"a"})
        # Неизвестная форма даёт ПУСТО ⇒ читка respecting ведёт себя как overriding,
        # и расхождение читок становится ВИДНЫМ, вместо того чтобы быть замятым.
        self.assertEqual(hr.writer_unevidenced_keys({"apy_unevidenced": 7}), set())
        self.assertEqual(hr.writer_unevidenced_keys({}), set())


class TestLeversAreNotAdditive(_Case):
    """Свойство измеряется, а не объявляется константой."""

    def test_additivity_flag_is_computed_from_the_three_measurements(self):
        original = _remedy._polled_keys
        try:
            _remedy._polled_keys = lambda: {"aave", "comp"}  # noqa: E731
            doc = self.measure()
        finally:
            _remedy._polled_keys = original
        block = doc["levers_are_not_additive"]
        self.assertEqual(
            block["additive"],
            block["writer_universe_alone"] + block["key_mismatch_alone"]
                == block["both"])

    def test_a_lever_that_lifts_no_leg_alone_is_worth_zero_days(self):
        """Рычаг, поднимающий ЧАСТЬ ног дня, в одиночку не возвращает дня вовсе."""
        original = _remedy._polled_keys
        try:
            _remedy._polled_keys = lambda: {"aave"}  # noqa: E731
            doc = self.measure()
        finally:
            _remedy._polled_keys = original
        self.assertEqual(doc["scenarios"][hr.SC_WRITER]["delta_days"], 0)
        self.assertEqual(doc["scenarios"][hr.SC_CEILING]["delta_days"], 1)


class TestGrantProvenance(_Case):
    """Что именно кладётся в запись — сентинел или НАБЛЮДЁННАЯ ставка близнеца."""

    def test_polled_grant_writes_the_neighbours_sentinel_not_a_local_copy(self):
        """Сентинел берётся ПО ССЫЛКЕ на модуль соседа, а не копией числа."""
        records = {str(r["cycle_date"]): r for r in self._journal()}
        out = hr.perturb(records, polled={"comp"}, twins={},
                         grant_polled=True, respect_writer=True, grant_twin=False)
        self.assertEqual(out["2026-01-03"]["apy_evidenced_pct"]["comp"],
                         _g1._PRICING_SENTINEL_PCT)
        original = _g1._PRICING_SENTINEL_PCT
        try:
            _g1._PRICING_SENTINEL_PCT = -1.0
            out = hr.perturb(records, polled={"comp"}, twins={},
                             grant_polled=True, respect_writer=True, grant_twin=False)
        finally:
            _g1._PRICING_SENTINEL_PCT = original
        self.assertEqual(out["2026-01-03"]["apy_evidenced_pct"]["comp"], -1.0,
                         "сентинел скопирован в свой литерал — подмена правила пройдёт молча")

    def test_granted_leg_contributes_exactly_nothing_to_the_benefit(self):
        """Выдаётся ПРАВО быть оценённым, а не доходность: вклад ноги ровно ноль."""
        deltas = {"comp": 40000.0}
        gain, missing = _ste._day_gain_usd(
            deltas, {"comp": _g1._PRICING_SENTINEL_PCT})
        self.assertEqual(missing, [])
        self.assertEqual(gain, 0.0)

    def test_twin_grant_uses_the_observed_rate_not_the_sentinel(self):
        records = {str(r["cycle_date"]): r for r in self._journal()}
        records["2026-01-03"]["apy_evidenced_pct"]["comp_new"] = 9.25
        out = hr.perturb(records, polled=set(), twins={"comp": ["comp_new"]},
                         grant_polled=False, respect_writer=True, grant_twin=True)
        self.assertEqual(out["2026-01-03"]["apy_evidenced_pct"]["comp"], 9.25,
                         "ставка близнеца НАБЛЮДЕНА — подменять её сентинелом значит "
                         "стереть единственный доказанный класс")

    def test_key_mismatch_alone_returns_the_day_when_the_twin_is_live(self):
        rows = self._journal()
        for row in rows[1:]:
            row["apy_evidenced_pct"]["comp_new"] = 9.25
        _write(self.data_dir, rows)
        original_polled = _remedy._polled_keys
        original_twins = _remedy._twin_keys
        try:
            _remedy._polled_keys = lambda: set()  # noqa: E731 — рычаг писателя выключен
            _remedy._twin_keys = lambda *a, **k: {"measured": True,
                                                  "pairs": {"comp": ["comp_new"]}}
            doc = self.measure()
        finally:
            _remedy._polled_keys = original_polled
            _remedy._twin_keys = original_twins
        self.assertEqual(doc["scenarios"][hr.SC_KEY_MISMATCH]["delta_days"], 1)
        self.assertEqual(doc["scenarios"][hr.SC_KEY_MISMATCH]["days_added"],
                         ["2026-01-01"])

    def test_unmeasured_twins_do_not_abort_the_answer(self):
        """Близнецы не измерены — это отсутствие рычага, а не отказ всего замера."""
        original = _remedy._twin_keys
        try:
            _remedy._twin_keys = lambda *a, **k: {"measured": False, "pairs": {},
                                                  "reason": "журнал ходов пуст"}
            doc = self.measure()
        finally:
            _remedy._twin_keys = original
        self.assertIn(doc["status"], (hr.STATUS_OK, hr.STATUS_WARNING, hr.STATUS_CRITICAL))
        self.assertFalse(doc["twin_keys"]["measured"])
        self.assertEqual(doc["twin_keys"]["reason"], "журнал ходов пуст")
        self.assertEqual(doc["scenarios"][hr.SC_KEY_MISMATCH]["delta_days"], 0)


class TestNeighbourCheck(_Case):
    """Сверка с G7 — ОДНОСТОРОННЯЯ, и её отказ не выдаётся за согласие."""

    def test_neighbour_refusal_is_not_reported_as_agreement(self):
        original = _remedy.measure
        try:
            _remedy.measure = lambda *a, **k: {"status": "UNMEASURED", "per_day": []}
            doc = self.measure()
        finally:
            _remedy.measure = original
        nb = doc["neighbour_check"]
        self.assertFalse(nb["compared"])
        self.assertNotIn("passed", nb)
        self.assertIn("НЕ", nb["reason"])

    def test_violation_of_the_one_directional_rule_is_named(self):
        """Сосед отдал день владельцу, а наш код его поднял ⇒ это улика."""
        original_polled = _remedy._polled_keys
        original_measure = _remedy.measure
        try:
            _remedy._polled_keys = lambda: {"aave", "comp"}  # noqa: E731
            _remedy.measure = lambda *a, **k: {
                "status": "CRITICAL",
                "per_day": [{"cycle_date": "2026-01-01",
                             "remedies_required": [_remedy.REMEDY_NEEDS_POLLING]}],
            }
            doc = self.measure()
        finally:
            _remedy._polled_keys = original_polled
            _remedy.measure = original_measure
        nb = doc["neighbour_check"]
        self.assertTrue(nb["compared"])
        self.assertFalse(nb["passed"])
        self.assertEqual(nb["violations"], ["2026-01-01"])

    def test_neighbour_exception_is_a_third_outcome(self):
        original = _remedy.measure

        def _boom(*a, **k):
            raise RuntimeError("сосед упал")

        try:
            _remedy.measure = _boom
            doc = self.measure()
        finally:
            _remedy.measure = original
        self.assertFalse(doc["neighbour_check"]["compared"])
        self.assertIn("сосед G7 отказал", doc["neighbour_check"]["reason"])


class TestDenominatorRule(_Case):
    """Правило отбора — одно, и оно то же, что у автора знаменателя."""

    def test_trivial_day_is_excluded_even_though_it_has_an_outcome(self):
        row = {"trivial": True, "outcome": "hit"}
        self.assertFalse(hr.in_denominator(row))

    def test_unchecked_day_is_excluded(self):
        self.assertFalse(hr.in_denominator({"trivial": False, "outcome": "UNCHECKED"}))

    def test_scored_day_is_included(self):
        self.assertTrue(hr.in_denominator({"trivial": False, "outcome": "miss"}))

    def test_rule_matches_the_authors_own_selection_on_the_real_shape(self):
        doc = self.measure()
        canon = _ste.scored_days(self.data_dir)
        self.assertEqual(set(doc["population"]["denominator_days_today"]), canon)


class TestSurvivorClosures(_Case):
    """Сцены, которых в живом журнале нет — и без них четыре претензии были бы
    истинны ПО ПОСТРОЕНИЮ населения, а не закреплены (батарея мутаций #591)."""

    def test_outcome_outside_the_canonical_pair_is_excluded(self):
        """`in (hit, miss)` и `!= UNCHECKED` совпадают на СЕГОДНЯШНЕМ домене судьи.

        Совпадают — значит претензия «правило то же, что у автора знаменателя» сегодня
        держится на населении, а не на коде. Домен судьи расширится (новый исход) — и
        разойдутся молча; сцена фабрикует ровно этот день.
        """
        self.assertFalse(hr.in_denominator({"trivial": False, "outcome": "pending"}))
        self.assertFalse(hr.in_denominator({"trivial": False, "outcome": None}))

    def test_perturbation_shares_no_nested_object_with_the_input(self):
        """Неглубокая копия сегодня безвредна — потому что карта ставок заменяется
        целиком. Претензия докстринга («копия глубокая») закрепляется ТОЖДЕСТВОМ
        объектов, иначе она держится на порядке строк в теле функции."""
        records = {str(r["cycle_date"]): r for r in self._journal()}
        out = hr.perturb(records, polled={"comp"}, twins={},
                         grant_polled=True, respect_writer=True, grant_twin=False)
        for date, clone in out.items():
            src = records[date]
            self.assertIsNot(clone, src)
            for key, value in clone.items():
                if isinstance(value, (dict, list)):
                    self.assertIsNot(value, src.get(key),
                                     f"{date}.{key} — общий объект с входом")

    def test_grant_never_overwrites_an_already_observed_rate(self):
        """Выдача заполняет ПРОБЕЛ. Затирая наблюдённое, она стёрла бы и ставку
        близнеца (выданную ПЕРЕД ней), то есть уничтожила бы единственный
        доказанный рычаг — на мощности знаменателя это не видно вовсе."""
        records = {str(r["cycle_date"]): r for r in self._journal()}
        records["2026-01-03"]["apy_evidenced_pct"]["aave"] = 3.0
        out = hr.perturb(records, polled={"aave", "comp"},
                         twins={"comp": ["aave"]},
                         grant_polled=True, respect_writer=True, grant_twin=True)
        apy = out["2026-01-03"]["apy_evidenced_pct"]
        self.assertEqual(apy["aave"], 3.0, "наблюдённая ставка затёрта сентинелом")
        self.assertEqual(apy["comp"], 3.0, "ставка близнеца затёрта сентинелом")

    def test_day_with_an_unparsed_verdict_never_enters_the_denominator(self):
        """Сфабрикованный вердикт: в живом журнале только ACT/HOLD.

        Без сцены структурный вывод мог бы забыть про разобранность вердикта и
        разойтись с судьёй молча — а расхождение двух выводов и есть то, чем
        прибор доказывает, что мерит настоящую поверхность решения.
        """
        rows = self._journal()
        rows[0]["verdict"] = "REVIEW"
        _write(self.data_dir, rows)
        original = _remedy._polled_keys
        try:
            _remedy._polled_keys = lambda: {"aave", "comp"}  # noqa: E731
            doc = self.measure()
        finally:
            _remedy._polled_keys = original
        self.assertNotIn("2026-01-01", doc["population"]["denominator_days_today"])
        for name, sc in doc["scenarios"].items():
            self.assertNotIn("2026-01-01", sc["days_added"], name)
        self.assertTrue(doc["derivation_cross_check"]["passed"],
                        doc["derivation_cross_check"])


class TestHorizonBinds(_Case):
    """Горизонт судьи обязан связывать и ВТОРОЙ вывод.

    Стенд основного класса короче горизонта (4 дня против 7), поэтому на нём срез
    не связывает НИКОГДА — и претензия «оба вывода смотрят одно окно» держалась бы
    на длине фикстуры, а не на коде. Здесь журнал ДЛИННЕЕ горизонта, и нога,
    оценённая только ЗА окном, обязана остаться невидимой для обоих выводов.
    """

    def _journal(self):
        rows = [_day("2026-02-01", current={"aave": 40000.0}, target={"comp": 40000.0},
                     evidenced={"aave": 3.0})]
        # семь форвардных дней внутри окна: `comp` не оценён ни на одном
        for i in range(2, 9):
            rows.append(_day(f"2026-02-{i:02d}",
                             current={"comp": 40000.0}, target={"comp": 40000.0},
                             evidenced={"aave": 3.0}, turnover=0.0))
        # девятый день — ЗА горизонтом, и там `comp` живой
        rows.append(_day("2026-02-09", current={"comp": 40000.0},
                         target={"comp": 40000.0},
                         evidenced={"aave": 3.0, "comp": 4.0}, turnover=0.0))
        return rows

    def test_a_leg_priced_only_beyond_the_horizon_returns_no_day(self):
        original = _remedy._polled_keys
        try:
            _remedy._polled_keys = lambda: set()  # noqa: E731 — рычагов не выдаём
            doc = self.measure()
        finally:
            _remedy._polled_keys = original
        self.assertEqual(doc["population"]["recoverable_in_principle"], 1)
        self.assertNotIn("2026-02-01", doc["population"]["denominator_days_today"])
        self.assertTrue(doc["derivation_cross_check"]["passed"],
                        doc["derivation_cross_check"])
        self.assertTrue(doc["canonical_parity"]["passed"], doc["canonical_parity"])

    def test_the_grant_returns_that_day_only_inside_the_window(self):
        original = _remedy._polled_keys
        try:
            _remedy._polled_keys = lambda: {"comp"}  # noqa: E731
            doc = self.measure()
        finally:
            _remedy._polled_keys = original
        self.assertEqual(doc["scenarios"][hr.SC_WRITER]["days_added"], ["2026-02-01"])
        self.assertTrue(doc["derivation_cross_check"]["passed"])


class TestArtifact(_Case):
    """Артефакт — то, что читает шаг 0-офис; форма его закреплена."""

    def test_run_writes_the_artifact_and_carries_the_boundaries(self):
        # Корень строится ВНУТРИ временного каталога стенда: `self.data_dir.parent`
        # есть системный /tmp, и тест писал бы за пределы своей песочницы.
        root = self.data_dir / "root"
        (root / "data").mkdir(parents=True)
        _write(root / "data", self._journal())
        doc = hr.run(root=str(root), now=NOW)
        written = json.loads(
            (root / "data" / hr.OUTPUT_FILENAME).read_text(encoding="utf-8"))
        self.assertEqual(written["version"], hr.VERSION)
        self.assertEqual(written["overall"], doc["status"])
        self.assertTrue(written["what_it_does_not_prove"])
        self.assertIn("ADVISORY", written["advisory"])

    def test_report_lines_lead_with_the_unit_of_the_answer(self):
        lines = hr.format_report(self.measure())
        self.assertTrue(lines[0].startswith("   знаменатель hit_rate"), lines[0])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
