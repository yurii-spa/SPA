"""Приёмка прибора «сколько дней журнала поднимет закрытие G1» (заказ #541, ADR-299).

Каждый тест — положительный контроль на конкретное свойство прибора, а не
украшение: набор писался так, чтобы мутация по координате в
`spa_core/monitoring/g1_verdict_recoverability.py` краснила хотя бы один тест.

Три свойства закрыты отдельно и намеренно, потому что именно на них прибор такого
рода обычно врёт молча:

1. **единица ответа — ДНИ, а не ключи** (прямое требование заказа);
2. **ноль сопровождается доказанной СПОСОБНОСТЬЮ** дать не-ноль, иначе он вакуум;
3. **выдаётся право быть оценённым, а не доходность** — сентинел не смеет внести
   в `benefit` ни цента, и `hit_rate` после расширения не считается вовсе
   (ловушка заказа).

FROZEN-DATE-OK: injected-clock — единственные часы прибора приходят параметром
`now=` в `measure`/`run` (константа `FIXED_NOW` ниже), и ни одно утверждение
набора не зависит от календаря. Даты в фикстурах (`2026-08-01` и соседи) — ИМЕНА
строк журнала: по ним `load_history` сортирует и разрешает повтор дня, свойством
свежести они не являются.
"""
# LLM_FORBIDDEN
# FROZEN-DATE-OK: injected-clock — единственные часы прибора приходят
# параметром: FIXED_NOW (и второй литерал в test_clock_is_an_input) передаются в
# measure(..., now=) и run(..., now=), поэтому ни одно утверждение набора не
# зависит от календаря. Даты в фикстурах (`2026-08-01` и соседи) — ИМЕНА строк
# журнала: по ним load_history сортирует и разрешает повтор дня, свежестью они
# не являются.
from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import scripts.measure_pin_placement_effect as pin_producer
from spa_core.monitoring import g1_verdict_recoverability as g1r
from spa_core.paper_trading import shadow_trigger_eval as ste

#: Часы прибора — вход, а не окружение (правило `.claude/rules/deployment.md`).
FIXED_NOW = datetime(2026, 9, 10, 12, 0, 0, tzinfo=timezone.utc)

#: Имя ноги, которую фикстуры двигают и НЕ оценивают. Одно на весь набор, чтобы
#: сценарий «нога внутри набора» и «нога вне набора» отличались ровно набором.
BLOCKED_LEG = "spark_susds"

#: Вторая двигаемая и НЕоценённая нога. Нужна ровно для одной сцены: покрытие
#: набором ЧАСТИ ног. При одной ноге «подмножество» и «пересечение» дают один и
#: тот же ответ, и ослабление условия проходит незамеченным (мутация #543).
BLOCKED_LEG_2 = "sfrax"


def _day(date: str, *, verdict: str = "HOLD", apys: dict | None = None,
         current: dict | None = None, target: dict | None = None,
         cost: float = 50.0, turnover: float = 20_000.0) -> dict:
    """Одна строка журнала решений в форме настоящего писателя."""
    return {
        "cycle_date": date,
        "verdict": verdict,
        "schema": "shadow-hist-v2",
        "capital_usd": 100_000.0,
        "cost_usd": cost,
        "turnover_usd": turnover,
        "current_positions": current if current is not None else {"aave_v3": 20_000.0},
        "target_positions": target if target is not None else {BLOCKED_LEG: 20_000.0},
        "apy_evidenced_pct": apys if apys is not None else {},
    }


def _write(data_dir: Path, rows: list[dict]) -> None:
    (data_dir / "allocation_rationale_history.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def _orchestrator(data_dir: Path, protocols: list[str]) -> None:
    (data_dir / "adapter_orchestrator_status.json").write_text(
        json.dumps({"adapters": [{"protocol": p} for p in protocols]}),
        encoding="utf-8")


def _grants(*, not_polled: list[str] | None = None,
            no_adapter: list[str] | None = None,
            unmeasured: str | None = None):
    """Подмена КАНОНИЧЕСКОГО производителя набора (ADR-236).

    Патчится имя в `scripts.measure_pin_placement_effect` — то самое, которое
    прибор обязан звать. Заведи он себе вторую копию списка, патч перестал бы
    действовать и сценарные тесты покраснели бы: это и есть проверка проводки.
    """
    if unmeasured:
        return mock.patch.object(pin_producer, "pins_invisible_to_the_gate",
                                 return_value={"unmeasured": unmeasured,
                                               "checked": 0, "invisible": []})
    not_polled = not_polled or []
    no_adapter = no_adapter or []
    return mock.patch.object(
        pin_producer, "pins_invisible_to_the_gate",
        return_value={"unmeasured": None, "checked": len(not_polled) + len(no_adapter),
                      "polled": 3, "invisible": sorted(not_polled + no_adapter),
                      "not_polled": not_polled, "no_adapter": no_adapter})


def _window_blocked(days: int = 10) -> list[dict]:
    """Окно, где двигаемая нога `BLOCKED_LEG` НЕ оценена ни в один forward-день.

    `aave_v3` оценён всегда — значит день выпадает из вердикта ровно из-за одной
    названной ноги, и сценарий отличается от соседнего только НАБОРОМ.
    """
    apys = {"aave_v3": 4.0}
    return [_day(f"2026-08-{d:02d}", apys=dict(apys)) for d in range(1, days + 1)]


def _window_priceable(days: int = 10) -> list[dict]:
    """То же окно, но ставка у обеих ног есть — дни получают вердикт сами."""
    apys = {"aave_v3": 4.0, BLOCKED_LEG: 6.0}
    return [_day(f"2026-08-{d:02d}", apys=dict(apys)) for d in range(1, days + 1)]


class AnswerIsInDays(unittest.TestCase):
    """Заказ требует ДНИ. Ключи печатаются как вход возмущения, не как ответ."""

    def test_grant_lifting_the_blocking_leg_lifts_days(self):
        with TemporaryDirectory() as td:
            d = Path(td)
            _write(d, _window_blocked())
            _orchestrator(d, ["aave_v3"])
            with _grants(not_polled=[BLOCKED_LEG]):
                doc = g1r.measure(d, now=FIXED_NOW)
        self.assertNotEqual(doc["status"], g1r.STATUS_UNMEASURED, doc["findings"])
        sc = doc["scenarios"]["g1_wiring"]
        self.assertEqual(sc["grant_key_count"], 1)
        self.assertGreater(sc["days_recovered"], 0)
        self.assertEqual(sc["days_recovered"],
                         doc["population"]["recoverable_in_principle"])

    def test_key_count_and_day_count_are_reported_separately(self):
        """Ключей много, дней ноль — ровно то, что заказ велел не путать."""
        with TemporaryDirectory() as td:
            d = Path(td)
            _write(d, _window_blocked())
            _orchestrator(d, ["aave_v3"])
            with _grants(not_polled=["sdai", "scrvusd", "sfrax", "susde"]):
                doc = g1r.measure(d, now=FIXED_NOW)
        sc = doc["scenarios"]["g1_wiring"]
        self.assertEqual(sc["grant_key_count"], 4)
        self.assertEqual(sc["days_recovered"], 0)
        answer = [x for x in doc["findings"] if x.startswith("[ОТВЕТ]")]
        self.assertTrue(answer, doc["findings"])
        self.assertIn("ДНИ", answer[0])

    def test_ceiling_scenario_is_wider_than_the_wiring_scenario(self):
        with TemporaryDirectory() as td:
            d = Path(td)
            _write(d, _window_blocked())
            _orchestrator(d, ["aave_v3"])
            with _grants(not_polled=["sdai"], no_adapter=[BLOCKED_LEG]):
                doc = g1r.measure(d, now=FIXED_NOW)
        self.assertEqual(doc["scenarios"]["g1_wiring"]["days_recovered"], 0)
        self.assertGreater(doc["scenarios"]["g1_max"]["days_recovered"], 0)


class ParityControl(unittest.TestCase):
    """Пустой набор ⇒ реплей = настоящий `_evaluate_verdict` бит в бит."""

    def test_parity_passes_on_healthy_data(self):
        with TemporaryDirectory() as td:
            d = Path(td)
            _write(d, _window_priceable())
            _orchestrator(d, ["aave_v3", BLOCKED_LEG])
            with _grants(not_polled=["sdai"]):
                doc = g1r.measure(d, now=FIXED_NOW)
        self.assertTrue(doc["parity_control"]["passed"])
        self.assertEqual(doc["parity_control"]["days_compared"], doc["journal_rows"])

    def test_a_lying_copier_makes_the_instrument_REFUSE(self):
        """Положительный контроль: испорти копирование — прибор обязан отказать."""
        real_grant_pricing = g1r.grant_pricing   # взять ДО патча, иначе рекурсия

        def corrupt(forward, grant):
            out = real_grant_pricing(forward, grant)
            for rec in out:            # тихая порча, какую дал бы неверный copy
                rec["apy_evidenced_pct"] = {}
            return out

        with TemporaryDirectory() as td:
            d = Path(td)
            _write(d, _window_priceable())
            _orchestrator(d, ["aave_v3", BLOCKED_LEG])
            with _grants(not_polled=["sdai"]), \
                    mock.patch.object(g1r, "grant_pricing", corrupt):
                doc = g1r.measure(d, now=FIXED_NOW)
        self.assertEqual(doc["status"], g1r.STATUS_UNMEASURED)
        self.assertFalse(doc["parity_control"]["passed"])
        self.assertTrue(any(x.startswith("[НЕ ИЗМЕРЕНО]") for x in doc["findings"]))
        self.assertNotIn("scenarios", doc)

    def test_perturbation_never_mutates_the_baseline_records(self):
        rows = _window_blocked(4)
        before = json.dumps(rows, sort_keys=True)
        g1r.grant_pricing(rows, {BLOCKED_LEG, "sdai"})
        self.assertEqual(json.dumps(rows, sort_keys=True), before)


class CapabilityControl(unittest.TestCase):
    """Ноль без доказанной способности дать не-ноль — вакуум, а не ответ."""

    def test_capability_fires_and_is_measured_from_the_journal(self):
        with TemporaryDirectory() as td:
            d = Path(td)
            _write(d, _window_blocked())
            _orchestrator(d, ["aave_v3"])
            with _grants(not_polled=["sdai"]):
                doc = g1r.measure(d, now=FIXED_NOW)
        cap = doc["capability_control"]
        self.assertTrue(cap["required"])
        self.assertTrue(cap["passed"])
        self.assertIn(BLOCKED_LEG, cap["grant"])       # ИЗМЕРЕН, не выписан
        self.assertNotIn("sdai", cap["grant"])
        self.assertGreater(cap["days_recovered"], 0)

    def test_capability_failure_REFUSES_instead_of_reporting_zero(self):
        with TemporaryDirectory() as td:
            d = Path(td)
            _write(d, _window_blocked())
            _orchestrator(d, ["aave_v3"])
            with _grants(not_polled=["sdai"]), \
                    mock.patch.object(g1r, "_structural_recovers",
                                      return_value=False):
                doc = g1r.measure(d, now=FIXED_NOW)
        self.assertEqual(doc["status"], g1r.STATUS_UNMEASURED)
        self.assertNotIn("scenarios", doc)
        self.assertTrue(any("способност" in x for x in doc["findings"]))

    def test_capability_is_not_required_when_nothing_is_recoverable(self):
        """Все UNCHECKED — от конца окна: требовать контроль не с чего."""
        rows = [_day("2026-08-01", apys={"aave_v3": 4.0, BLOCKED_LEG: 5.0}),
                _day("2026-08-02", apys={"aave_v3": 4.0, BLOCKED_LEG: 5.0})]
        with TemporaryDirectory() as td:
            d = Path(td)
            _write(d, rows)
            _orchestrator(d, ["aave_v3", BLOCKED_LEG])
            with _grants(not_polled=["sdai"]):
                doc = g1r.measure(d, now=FIXED_NOW)
        self.assertFalse(doc["capability_control"]["required"])
        self.assertTrue(doc["capability_control"]["passed"])
        self.assertEqual(doc["population"]["recoverable_in_principle"], 0)
        self.assertNotEqual(doc["status"], g1r.STATUS_UNMEASURED)


class TwoDerivationsMustAgree(unittest.TestCase):
    def test_cross_check_passes_on_healthy_data(self):
        with TemporaryDirectory() as td:
            d = Path(td)
            _write(d, _window_blocked())
            _orchestrator(d, ["aave_v3"])
            with _grants(not_polled=[BLOCKED_LEG]):
                doc = g1r.measure(d, now=FIXED_NOW)
        self.assertTrue(doc["derivation_cross_check"]["passed"])

    def test_disagreement_REFUSES(self):
        """Структурный вывод врёт «поднято» — реплей это опровергает."""
        with TemporaryDirectory() as td:
            d = Path(td)
            _write(d, _window_blocked())
            _orchestrator(d, ["aave_v3"])
            real = g1r._structural_recovers
            calls = {"n": 0}

            def lying(deltas, forward, horizon, grant):
                calls["n"] += 1
                # первый вызов — контроль способности, его не трогаем
                return True if calls["n"] > len(forward) else real(
                    deltas, forward, horizon, grant)

            with _grants(not_polled=["sdai"]), \
                    mock.patch.object(g1r, "_structural_recovers", lying):
                doc = g1r.measure(d, now=FIXED_NOW)
        self.assertEqual(doc["status"], g1r.STATUS_UNMEASURED)
        self.assertFalse(doc["derivation_cross_check"]["passed"])


class StructuralDerivationIsExact(unittest.TestCase):
    """Положительные контроли на ДВЕ мутации, ПЕРЕЖИВШИЕ первую редакцию тестов.

    Батарея цикла #543 (16 мутаций по координатам) оставила в живых ровно эти
    две, и обе жили в `_structural_recovers`. Обе выжили по одной причине: у
    КАЖДОГО дня прежних фикстур блокирующая нога РОВНО ОДНА, а окно однородно —
    при таком населении «подмножество» и «пересечение» неотличимы, а срез
    горизонта нечего отрезать. Усилены ТЕСТЫ, а не ослаблена батарея
    (порядок ADR-295): ниже сцены, где ответ решает исход.
    """

    def test_partial_leg_coverage_does_NOT_recover_a_day(self):
        """`missing <= grant`, а не `missing & grant`.

        День двигает ДВЕ неоценённые ноги, набор покрывает ОДНУ. Выдача одной
        ноги вердикта не даёт: вторая по-прежнему без ставки. Ослабь условие до
        пересечения — структурный вывод скажет «поднято», реплей настоящего
        оценщика скажет «UNCHECKED», и прибор ОТКАЖЕТ по сверке двух выводов.
        """
        rows = [_day(f"2026-08-{d:02d}", apys={"aave_v3": 4.0},
                     target={BLOCKED_LEG: 10_000.0, BLOCKED_LEG_2: 10_000.0})
                for d in range(1, 11)]
        with TemporaryDirectory() as td:
            d = Path(td)
            _write(d, rows)
            _orchestrator(d, ["aave_v3"])
            with _grants(not_polled=[BLOCKED_LEG]):     # покрыта ОДНА из двух
                doc = g1r.measure(d, now=FIXED_NOW)

        # прямое утверждение о самой функции: пересечение НЕ есть подмножество
        deltas = ste._deltas(rows[0])
        self.assertFalse(
            g1r._structural_recovers(deltas, rows[1:], 7, {BLOCKED_LEG}),
            "частичное покрытие ног объявлено восстановлением дня")
        self.assertTrue(
            g1r._structural_recovers(deltas, rows[1:], 7,
                                     {BLOCKED_LEG, BLOCKED_LEG_2}),
            "полное покрытие ног обязано поднимать день — иначе контроль пуст")

        # и то же самое у ПОТРЕБИТЕЛЯ: сверка двух выводов не разошлась
        self.assertNotEqual(doc["status"], g1r.STATUS_UNMEASURED, doc["findings"])
        self.assertTrue(doc["derivation_cross_check"]["passed"],
                        doc["derivation_cross_check"])
        self.assertEqual(doc["scenarios"]["g1_wiring"]["days_recovered"], 0)

    def test_a_rate_arriving_BEYOND_the_horizon_does_not_recover_the_day(self):
        """Срез `[:horizon]` — часть вывода, а не украшение.

        Ставка блокирующей ноги появляется в forward-дне, до которого горизонт
        решения НЕ достаёт. `_evaluate_verdict` его не видит по построению;
        увидь его структурный вывод — два вывода разойдутся, и ответ станет
        недействительным.
        """
        rows = [_day(f"2026-08-{d:02d}", apys={"aave_v3": 4.0})
                for d in range(1, 9)]
        rows.append(_day("2026-08-09",
                         apys={"aave_v3": 4.0, BLOCKED_LEG: 6.0}))
        with TemporaryDirectory() as td:
            d = Path(td)
            _write(d, rows)
            _orchestrator(d, ["aave_v3"])
            with _grants(not_polled=["sdai"]):   # блокирующей ноги в наборе НЕТ
                doc = g1r.measure(d, now=FIXED_NOW)

        # 2026-08-01: внутри горизонта ставки нет, за горизонтом — есть
        deltas = ste._deltas(rows[0])
        self.assertFalse(
            g1r._structural_recovers(deltas, rows[1:], 7, {"sdai"}),
            "структурный вывод заглянул ЗА горизонт решения")
        self.assertTrue(
            g1r._structural_recovers(deltas, rows[1:], 8, {"sdai"}),
            "при горизонте, ДОСТАЮЩЕМ до ставки, день обязан подниматься — "
            "иначе контроль выше пуст по построению")

        self.assertIn("2026-08-01", doc["population"]["unchecked_days"])
        self.assertNotEqual(doc["status"], g1r.STATUS_UNMEASURED, doc["findings"])
        self.assertTrue(doc["derivation_cross_check"]["passed"],
                        doc["derivation_cross_check"])
        self.assertEqual(doc["scenarios"]["g1_wiring"]["days_recovered"], 0)


class GrantSetIsMeasuredNotInvented(unittest.TestCase):
    def test_unmeasured_producer_REFUSES_with_a_named_reason(self):
        with TemporaryDirectory() as td:
            d = Path(td)
            _write(d, _window_blocked())
            _orchestrator(d, ["aave_v3"])
            with _grants(unmeasured="снимок оркестратора не прочитан"):
                doc = g1r.measure(d, now=FIXED_NOW)
        self.assertEqual(doc["status"], g1r.STATUS_UNMEASURED)
        self.assertIn("unmeasured", doc["grant_sets"])
        self.assertNotIn("scenarios", doc)
        self.assertTrue(any("РАЗНЫЕ факты" in x for x in doc["findings"]))

    def test_the_module_holds_no_second_copy_of_the_G1_list(self):
        """Вторая копия набора разошлась бы с канонической молча."""
        src = Path(g1r.__file__).read_text(encoding="utf-8")
        body = src.split('"""', 2)[-1]          # без модульной docstring
        for key in ("aave_arbitrum", "aave_v3_polygon", "moonwell_base",
                    "extra_finance_base", "fluid_fusdc", "ondo_usdy"):
            self.assertNotIn(key, body,
                             f"имя {key} выписано в код — набор обязан приходить "
                             f"от pins_invisible_to_the_gate")

    def test_real_producer_is_reachable_and_used(self):
        """Проводка по ФОРМЕ вызова: без патча зовётся каноническое имя."""
        with TemporaryDirectory() as td:
            d = Path(td)
            _orchestrator(d, ["aave_v3", "compound_v3"])
            with mock.patch.object(pin_producer, "pins_invisible_to_the_gate",
                                   wraps=pin_producer.pins_invisible_to_the_gate
                                   ) as spy:
                res = g1r.measure_grant_sets(d)
        spy.assert_called_once()
        self.assertIsNone(res["unmeasured"], res)
        self.assertIn("wiring", res)


class SentinelGrantsPriceabilityNotYield(unittest.TestCase):
    def test_sentinel_is_zero_so_benefit_cannot_be_fabricated(self):
        self.assertEqual(g1r._PRICING_SENTINEL_PCT, 0.0)
        rec = _day("2026-08-01")
        fw = g1r.grant_pricing(
            [_day("2026-08-02", apys={"aave_v3": 4.0})], {BLOCKED_LEG})
        out = ste._evaluate_verdict(rec, fw, 7)
        self.assertNotEqual(out["outcome"], "UNCHECKED")
        # Единственная оценённая нога сверх `aave_v3` — сентинел, и её вклад
        # обязан быть нулевым: выдано право быть оценённым, не доходность.
        deltas = ste._deltas(rec)
        expected = deltas["aave_v3"] * 4.0 / 100.0 / 365.0
        self.assertAlmostEqual(out["benefit_usd_over_checked_days"],
                               round(expected, 2), places=2)

    def test_grant_does_not_overwrite_an_already_evidenced_rate(self):
        fw = g1r.grant_pricing(
            [_day("2026-08-02", apys={BLOCKED_LEG: 7.5})], {BLOCKED_LEG})
        self.assertEqual(fw[0]["apy_evidenced_pct"][BLOCKED_LEG], 7.5)

    def test_the_instrument_never_reports_a_post_widening_hit_rate(self):
        """Ловушка заказа: расширенный `hit_rate` не сравним с 1.0 напрямую."""
        with TemporaryDirectory() as td:
            d = Path(td)
            _write(d, _window_blocked())
            _orchestrator(d, ["aave_v3"])
            with _grants(not_polled=[BLOCKED_LEG]):
                doc = g1r.measure(d, now=FIXED_NOW)
        blob = json.dumps(doc, ensure_ascii=False)
        self.assertNotIn('"hit_rate"', blob)
        self.assertIn("does_not_report", doc)
        for line in doc.get("findings") or []:
            self.assertNotIn("hit_rate после расширения =", line)


class PopulationIsSplitByCause(unittest.TestCase):
    def test_end_of_window_day_is_not_charged_to_G1(self):
        with TemporaryDirectory() as td:
            d = Path(td)
            _write(d, _window_priceable(3))
            _orchestrator(d, ["aave_v3", BLOCKED_LEG])
            with _grants(not_polled=["sdai"]):
                doc = g1r.measure(d, now=FIXED_NOW)
        pop = doc["population"]
        self.assertEqual(pop["beyond_any_grant"], 1)
        self.assertEqual(pop["beyond_any_grant_days"], ["2026-08-03"])
        self.assertIn("no_forward_data", pop["beyond_reasons"])

    def test_unparsed_verdict_day_is_beyond_grant_not_recoverable(self):
        """День оценён, но вердикт не разобран — выдача ставок его не лечит."""
        rows = _window_priceable(4)
        rows[0]["verdict"] = "MAYBE"
        with TemporaryDirectory() as td:
            d = Path(td)
            _write(d, rows)
            _orchestrator(d, ["aave_v3", BLOCKED_LEG])
            with _grants(not_polled=["sdai"]):
                doc = g1r.measure(d, now=FIXED_NOW)
        self.assertEqual(doc["status"], doc["status"])  # не UNMEASURED от разлада
        self.assertNotEqual(doc["status"], g1r.STATUS_UNMEASURED, doc["findings"])
        self.assertIn("2026-08-01", doc["population"]["beyond_any_grant_days"])
        self.assertNotIn("2026-08-01",
                         doc["scenarios"]["g1_wiring"].get("scanned_days", []))


class BlockingLegAttribution(unittest.TestCase):
    def test_a_polled_leg_is_named_intermittent_not_G1(self):
        """Главная находка: оркестратор СПРАШИВАЕТ ногу, а ставки всё равно нет."""
        with TemporaryDirectory() as td:
            d = Path(td)
            _write(d, _window_blocked())
            _orchestrator(d, ["aave_v3", BLOCKED_LEG])   # нога ОПРАШИВАЕТСЯ
            with _grants(not_polled=["sdai"]):
                doc = g1r.measure(d, now=FIXED_NOW)
        legs = {a["protocol"]: a for a in doc["blocking_legs"]}
        self.assertEqual(legs[BLOCKED_LEG]["class"], "polled_but_unevidenced")
        self.assertEqual(doc["status"], g1r.STATUS_CRITICAL)
        self.assertTrue(any("ПЕРЕБОЯМИ ЭВИДЕНСА" in x for x in doc["findings"]))

    def test_a_not_polled_leg_is_named_G1(self):
        with TemporaryDirectory() as td:
            d = Path(td)
            _write(d, _window_blocked())
            _orchestrator(d, ["aave_v3"])
            with _grants(not_polled=[BLOCKED_LEG]):
                doc = g1r.measure(d, now=FIXED_NOW)
        legs = {a["protocol"]: a for a in doc["blocking_legs"]}
        self.assertEqual(legs[BLOCKED_LEG]["class"], "g1_not_polled")

    def test_unreadable_orchestrator_snapshot_leaves_the_class_UNMEASURED(self):
        with TemporaryDirectory() as td:
            d = Path(td)
            _write(d, _window_blocked())
            # снимка нет вовсе — класс ноги назвать нечем
            with _grants(not_polled=["sdai"]):
                doc = g1r.measure(d, now=FIXED_NOW)
        legs = {a["protocol"]: a for a in doc["blocking_legs"]}
        self.assertEqual(legs[BLOCKED_LEG]["class"], "UNMEASURED")
        self.assertTrue(any(x.startswith("[НЕ ИЗМЕРЕНО]") for x in doc["findings"]))


class RefusalsAndShape(unittest.TestCase):
    def test_empty_journal_REFUSES(self):
        with TemporaryDirectory() as td:
            d = Path(td)
            _orchestrator(d, ["aave_v3"])
            doc = g1r.measure(d, now=FIXED_NOW)
        self.assertEqual(doc["status"], g1r.STATUS_UNMEASURED)
        self.assertEqual(doc["journal_rows"], 0)

    def test_clock_is_an_input(self):
        other = datetime(2027, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        with TemporaryDirectory() as td:
            d = Path(td)
            _orchestrator(d, ["aave_v3"])
            self.assertEqual(g1r.measure(d, now=other)["generated_at"],
                             other.isoformat())

    def test_run_counts_unmeasured_separately_from_zeros(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "data").mkdir()
            _orchestrator(root / "data", ["aave_v3"])
            doc = g1r.run(root=str(root), now=FIXED_NOW, write=True)
            written = json.loads((root / "data" / g1r.OUTPUT_FILENAME)
                                 .read_text(encoding="utf-8"))
        self.assertEqual(doc["overall"], g1r.STATUS_UNMEASURED)
        self.assertGreaterEqual(doc["counts"]["unchecked"], 1)
        self.assertEqual(written["version"], g1r.VERSION)

    def test_report_lines_lead_with_days_and_carry_the_controls(self):
        with TemporaryDirectory() as td:
            d = Path(td)
            _write(d, _window_blocked())
            _orchestrator(d, ["aave_v3"])
            with _grants(not_polled=["sdai"]):
                doc = g1r.measure(d, now=FIXED_NOW)
        lines = g1r.format_report(doc)
        self.assertTrue(lines[0].startswith("   поднимет ли G1 дни журнала"))
        joined = "\n".join(lines)
        self.assertIn("ДНЕЙ поднято", joined)
        self.assertIn("контроль способности", joined)
        self.assertIn("сверка двух выводов", joined)
        self.assertIn("ADVISORY", joined)


class WiringAtBirth(unittest.TestCase):
    """Прибор без потребителя — украшение (правило «проводка при рождении»)."""

    def test_bridge_census_knows_the_artifact(self):
        from spa_core.monitoring import findings_bridge as fb
        self.assertIn(f"data/{g1r.OUTPUT_FILENAME}", fb.PRODUCES)
        stem = g1r.OUTPUT_FILENAME[:-len(".json")]
        self.assertIn(stem, fb.CENSUS_STAGE)
        self.assertEqual(fb.CENSUS_PRODUCT[stem]["module"],
                         "spa_core/monitoring/g1_verdict_recoverability.py")

    def test_office_step_reads_and_renders_the_artifact(self):
        import scripts.consume_office_reports as office
        self.assertIn(g1r.OUTPUT_FILENAME, office._READ_SCHEMA)
        self.assertEqual(office._PRODUCER[g1r.OUTPUT_FILENAME],
                         "spa_core/monitoring/g1_verdict_recoverability.py")
        src = Path(office.__file__).read_text(encoding="utf-8")
        self.assertIn("g1_verdict_recoverability import", src)

    def test_manifest_carries_both_entries(self):
        root = Path(__file__).resolve().parents[2]
        man = json.loads((root / "architecture" / "manifest.json")
                         .read_text(encoding="utf-8"))
        path = f"data/{g1r.OUTPUT_FILENAME}"
        arts = [a for a in man.get("artifacts", []) if a.get("path") == path]
        self.assertEqual(len(arts), 1, "нет записи в artifacts[]")
        producer = arts[0]["producer"]
        agents = [a for a in man.get("agents", []) if a.get("label") == producer]
        self.assertEqual(len(agents), 1, f"паспорт {producer} не найден")
        produced = [p.get("artifact") for p in agents[0].get("produces", [])]
        self.assertIn(path, produced, "нет записи в produces[] паспорта агента")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
