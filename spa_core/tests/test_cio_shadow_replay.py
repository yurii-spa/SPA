"""Сторож §38 ТЗ «Portfolio CIO» → «Historical replay».

Каждый тест здесь — ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ на замер 2026-09-06 по живой истории
ADR-060: проверка, никогда не видевшая настоящей поломки, — украшение
(`.claude/rules/deployment.md`). Воспроизводятся ровно те факты, ради которых
модуль написан:

1. рука ``cio_hold`` (не перекладывать вовсе) обошла живую книгу по ЧИСТОЙ
   доходности, при том что ВАЛОВЫЕ доходности рук почти совпали — разница
   создана платой за оборот, а не выбором ставок;
2. большинство перекладок живой книги не окупается за срок, которым система
   сама разрешает ход, и вывод переживает подстановку НАБЛЮДЁННОГО газа
   (ADR-243) — иначе он держался бы на литерале;
3. общих сверенных дней мало, и это сказано вслух: сравнивать руки на РАЗНЫХ
   популяциях — та же ошибка, что принимать групповой срез за приговор элементу.

Календаря в ФИКСТУРАХ нет намеренно: ярлыки дней здесь — ``day-00``…``day-NN``,
модуль сверяет записи по ПОРЯДКУ и ни одним сравнением не смотрит на дату
(``test_scoring_never_consults_the_calendar`` сдвигает те же ярлыки и требует
того же вердикта). Единственная литеральная дата файла — якорь ``_NOW``, и он
передаётся ВХОДОМ.

FROZEN-DATE-OK: injected-clock — единственная дверь модуля к часам это параметр
``now``; якорь ``_NOW`` ниже передаётся в ``R.run(..., now=_NOW)`` и он же попадает
в ``generated_at`` (закреплено ``test_run_uses_the_injected_clock_and_no_other_door``,
а мутация «часы взяты у машины» краснеет — замер #505).
"""

from __future__ import annotations

import contextlib
import datetime as dt
import importlib
import json
import os
import sys
import tempfile
import unittest

from spa_core.monitoring import cio_shadow_replay as R

# FROZEN-DATE-OK: injected-clock — якорь передаётся аргументом `now=` в каждый
# вызов `R.run`, обе стороны сверки закреплены, календарь на вердикт не влияет.
_NOW = dt.datetime(2030, 1, 1, 12, 0, 0, tzinfo=dt.timezone.utc)


def _day(i: int) -> str:
    """Ярлык дня. Сортируется как порядок — и не является датой."""
    return f"day-{i:02d}"


def _rec(i: int, *, cur: dict, tgt: dict | None = None, apy: dict | None = None,
         capital: float = 100_000.0, verdict: str = "HOLD",
         band: float = 0.5) -> dict:
    return {
        "cycle_date": _day(i),
        "verdict": verdict,
        "capital_usd": capital,
        "required_gain_pp": band,
        "current_positions": dict(cur),
        "target_positions": dict(tgt if tgt is not None else cur),
        "apy_evidenced_pct": dict(apy or {}),
    }


@contextlib.contextmanager
def _no_module(package: str, name: str):
    """Сделать `from package import name` невозможным — ОБЕ двери сразу.

    Одной записи в ``sys.modules`` мало: `from pkg import mod` находит уже
    импортированный модуль ещё и АТРИБУТОМ пакета, и саботаж, снявший только
    одну дверь, тихо проходит мимо — ветка третьего исхода осталась бы
    непроверенной (замер этого файла: тест зеленел на `WARN`).
    """
    full = f"{package}.{name}"
    pkg = importlib.import_module(package)
    had_attr = hasattr(pkg, name)
    saved_attr = getattr(pkg, name, None)
    saved_mod = sys.modules.get(full)
    if had_attr:
        delattr(pkg, name)
    sys.modules[full] = None  # type: ignore[assignment]
    try:
        yield
    finally:
        if saved_mod is None:
            sys.modules.pop(full, None)
        else:
            sys.modules[full] = saved_mod
        if had_attr:
            setattr(pkg, name, saved_attr)


def _gain(deltas, apy_map):
    """Та же семантика, что у производителя: непрайсенная нога ⇒ весь день None."""
    missing = sorted(p for p in deltas if apy_map.get(p) is None)
    if missing:
        return None, missing
    return sum(v * float(apy_map[p]) / 100.0 / 365.0 for p, v in deltas.items()), []


def _legs(current, target, capital_usd, min_leg_frac):
    min_leg = max(0.0, min_leg_frac) * capital_usd
    legs, inc, dec = [], 0.0, 0.0
    for p in sorted(set(current) | set(target)):
        d = float(target.get(p, 0.0)) - float(current.get(p, 0.0))
        if abs(d) <= min_leg + 1e-9:
            continue
        legs.append({"protocol": p, "delta_usd": round(d, 2),
                     "direction": "increase" if d > 0 else "decrease"})
        inc += d if d > 0 else 0.0
        dec += -d if d < 0 else 0.0
    return legs, max(inc, dec)


# ── Построение рук ────────────────────────────────────────────────────────────

class TestArms(unittest.TestCase):

    def test_hold_arm_stands_still_while_the_verdict_is_hold(self):
        """32 дня HOLD подряд — тень не совершает ни одной перекладки."""
        recs = [_rec(i, cur={"a": 50_000.0, "b": 50_000.0}) for i in range(4)]
        recs[2]["current_positions"] = {"a": 90_000.0, "b": 10_000.0}  # книга ушла
        arms = R.build_arms(recs)
        self.assertEqual(arms[R.ARM_CIO_HOLD][3], {"a": 50_000.0, "b": 50_000.0})
        self.assertEqual(arms[R.ARM_CURRENT][2], {"a": 90_000.0, "b": 10_000.0})

    def test_hold_arm_ADOPTS_the_target_on_an_ACT_day(self):
        """Заморозка ВЫВЕДЕНА из вердикта, а не вписана литералом.

        Положительный контроль ровно на это: появись в истории ``ACT`` — рука
        обязана взять цель того дня. Тест краснеет, если кто-нибудь заменит
        ветку на «всегда книга первого дня».
        """
        recs = [
            _rec(0, cur={"a": 100_000.0}),
            _rec(1, cur={"a": 100_000.0}, tgt={"b": 100_000.0}, verdict="ACT"),
            _rec(2, cur={"a": 100_000.0}),
        ]
        arms = R.build_arms(recs)
        self.assertEqual(arms[R.ARM_CIO_HOLD][0], {"a": 100_000.0})
        self.assertEqual(arms[R.ARM_CIO_HOLD][1], {"b": 100_000.0})
        self.assertEqual(arms[R.ARM_CIO_HOLD][2], {"b": 100_000.0})

    def test_zero_and_negative_positions_are_not_a_book(self):
        arms = R.build_arms([_rec(0, cur={"a": 0.0, "b": -5.0, "c": 10.0})])
        self.assertEqual(arms[R.ARM_CURRENT][0], {"c": 10.0})


# ── Отсутствие look-ahead ─────────────────────────────────────────────────────

class TestNoLookAhead(unittest.TestCase):

    def test_a_day_is_scored_with_TOMORROWS_rates(self):
        """Состав дня d зарабатывает ставки дня d+1, а не свои собственные.

        Положительный контроль: ставки завтрашнего дня в сто раз выше, и если
        сместить окно на свой день, число изменится на два порядка.
        """
        recs = [_rec(0, cur={"a": 36_500.0}, apy={"a": 1.0}),
                _rec(1, cur={"a": 36_500.0}, apy={"a": 100.0})]
        daily, unpriced = R.score_days(R.build_arms(recs)[R.ARM_CURRENT], recs,
                                       day_gain=_gain)
        self.assertEqual(len(daily), 1)
        self.assertAlmostEqual(daily[0], 36_500.0 * 100.0 / 100.0 / 365.0, places=6)
        self.assertEqual(unpriced, set())

    def test_an_unpriced_leg_makes_the_WHOLE_day_unchecked(self):
        recs = [_rec(0, cur={"a": 10_000.0, "b": 10_000.0}),
                _rec(1, cur={"a": 10_000.0}, apy={"a": 5.0})]
        daily, unpriced = R.score_days(R.build_arms(recs)[R.ARM_CURRENT], recs,
                                       day_gain=_gain)
        self.assertIsNone(daily[0])
        self.assertEqual(unpriced, {"b"})

    def test_the_last_day_has_no_tomorrow_and_is_not_invented(self):
        recs = [_rec(i, cur={"a": 10_000.0}, apy={"a": 5.0}) for i in range(3)]
        daily, _ = R.score_days(R.build_arms(recs)[R.ARM_CURRENT], recs,
                                day_gain=_gain)
        self.assertEqual(len(daily), 2)


# ── Стоимость хода ────────────────────────────────────────────────────────────

class TestMoveCosts(unittest.TestCase):

    def _moves(self, recs, arm=R.ARM_CURRENT, gas=lambda _c: 12.0,
               chains=None, min_leg_frac=0.005):
        return R.move_costs(R.build_arms(recs)[arm], recs, legs_of=_legs,
                            min_leg_frac=min_leg_frac,
                            chains=chains if chains is not None else {},
                            gas_of=gas, slippage_bps=8.0, bridge_bps=5.0)

    def test_a_standing_book_pays_nothing(self):
        recs = [_rec(i, cur={"a": 100_000.0}) for i in range(5)]
        self.assertEqual(self._moves(recs), [])

    def test_gas_is_per_leg_and_slippage_is_a_fraction_of_turnover(self):
        recs = [_rec(0, cur={"a": 100_000.0}),
                _rec(1, cur={"b": 100_000.0})]
        m = self._moves(recs)[0]
        self.assertEqual(m["turnover_usd"], 100_000.0)
        self.assertAlmostEqual(m["gas_usd"], 24.0)              # две ноги
        self.assertAlmostEqual(m["fees_usd"], 100_000.0 * 8.0 / 10_000.0)

    def test_bridge_is_charged_only_when_two_chains_are_touched(self):
        recs = [_rec(0, cur={"a": 100_000.0}), _rec(1, cur={"b": 100_000.0})]
        one = self._moves(recs, chains={"a": "ethereum", "b": "ethereum"})[0]
        two = self._moves(recs, chains={"a": "ethereum", "b": "base"})[0]
        self.assertAlmostEqual(one["fees_usd"], 80.0)
        self.assertAlmostEqual(two["fees_usd"], 80.0 + 50.0)

    def test_dust_legs_do_not_create_a_move(self):
        recs = [_rec(0, cur={"a": 100_000.0}),
                _rec(1, cur={"a": 99_900.0, "b": 100.0})]
        self.assertEqual(self._moves(recs), [])

    def test_observed_gas_column_uses_the_injected_gas_function(self):
        """Обе колонки — ОДНА арифметика с разной ценой ноги."""
        recs = [_rec(0, cur={"a": 100_000.0}), _rec(1, cur={"b": 100_000.0})]
        charged = self._moves(recs, gas=lambda _c: 12.0)[0]
        observed = self._moves(recs, gas=lambda _c: 0.04)[0]
        self.assertAlmostEqual(charged["gas_usd"], 24.0)
        self.assertAlmostEqual(observed["gas_usd"], 0.08)
        self.assertAlmostEqual(charged["fees_usd"], observed["fees_usd"])


# ── Метрики руки ──────────────────────────────────────────────────────────────

class TestArmMetrics(unittest.TestCase):

    def test_empty_common_population_is_UNCHECKED_not_zero(self):
        out = R.arm_metrics([], [], [], [], [], concentration_cap=0.4)
        self.assertEqual(out["verdict"], R._UNCHECKED)
        self.assertIn("сравнивать нечего", out["reason"])

    def test_concentration_denominator_is_CAPITAL_not_the_deployed_book(self):
        """Потолок RiskPolicy меряется от капитала — иначе он мерит не то.

        Книга $40k при капитале $100k (остальное кэш) — это 40 %, а не 100 %.
        Тест краснеет, если знаменателем взять сумму позиций.
        """
        recs = [_rec(0, cur={"a": 40_000.0}), _rec(1, cur={"a": 40_000.0})]
        books = [{"a": 40_000.0}, {"a": 40_000.0}]
        out = R.arm_metrics([1.0, 1.0], [], recs, books, [0], concentration_cap=0.5)
        self.assertAlmostEqual(out["max_concentration"], 0.4)
        self.assertEqual(out["risk_events"], 0)

    def test_risk_events_count_days_over_the_cap(self):
        recs = [_rec(i, cur={"a": 60_000.0}) for i in range(3)]
        books = [{"a": 60_000.0}] * 3
        out = R.arm_metrics([1.0, 1.0], [], recs, books, [0, 1],
                            concentration_cap=0.5)
        self.assertEqual(out["risk_events"], 2)
        self.assertAlmostEqual(out["max_concentration"], 0.6)

    def test_risk_events_are_NOT_ZERO_when_the_cap_is_unreadable(self):
        """Непрочитанный потолок — «не измерено», а не «нарушений нет»."""
        recs = [_rec(0, cur={"a": 60_000.0}), _rec(1, cur={"a": 60_000.0})]
        out = R.arm_metrics([1.0, 1.0], [], recs, [{"a": 60_000.0}] * 2, [0],
                            concentration_cap=None)
        self.assertIsNone(out["risk_events"])

    def test_net_is_gross_minus_cost_and_annualises_on_the_scored_days(self):
        recs = [_rec(i, cur={"a": 100_000.0}) for i in range(3)]
        moves = [{"day_index": 1, "cycle_date": _day(1), "legs": [],
                  "turnover_usd": 10_000.0, "gas_usd": 4.0, "fees_usd": 8.0,
                  "cost_usd": 12.0}]
        out = R.arm_metrics([10.0, 10.0], moves, recs, [{"a": 100_000.0}] * 3,
                            [0, 1], concentration_cap=0.4)
        self.assertAlmostEqual(out["gross_usd"], 20.0)
        self.assertAlmostEqual(out["cost_usd"], 12.0)
        self.assertAlmostEqual(out["realized_return_usd"], 8.0)
        self.assertAlmostEqual(out["net_apy_pct"], 8.0 / 100_000.0 * 365 / 2 * 100)

    def test_a_move_on_a_day_outside_the_common_set_is_not_charged(self):
        """Иначе рука платила бы за ход, доходность которого не сверялась."""
        recs = [_rec(i, cur={"a": 100_000.0}) for i in range(3)]
        moves = [{"day_index": 2, "cycle_date": _day(2), "legs": [],
                  "turnover_usd": 10_000.0, "gas_usd": 4.0, "fees_usd": 8.0,
                  "cost_usd": 12.0}]
        out = R.arm_metrics([10.0, 10.0], moves, recs, [{"a": 100_000.0}] * 3,
                            [0, 1], concentration_cap=0.4)
        self.assertAlmostEqual(out["cost_usd"], 0.0)
        self.assertEqual(out["moves"], 0)


# ── Ложные перекладки ─────────────────────────────────────────────────────────

class TestFalseRebalances(unittest.TestCase):

    def _move(self, i, protocol_in, protocol_out, usd, cost):
        return {"day_index": i, "cycle_date": _day(i),
                "legs": [{"protocol": protocol_in, "delta_usd": usd},
                         {"protocol": protocol_out, "delta_usd": -usd}],
                "turnover_usd": usd, "gas_usd": 0.0, "fees_usd": cost,
                "cost_usd": cost}

    def test_a_move_that_repays_inside_the_horizon_is_not_false(self):
        recs = [_rec(0, cur={}), _rec(1, cur={}),
                _rec(2, cur={}, apy={"good": 100.0, "bad": 0.0})]
        out = R.false_rebalances([self._move(1, "good", "bad", 36_500.0, 10.0)],
                                 recs, day_gain=_gain, horizon_days=7,
                                 max_payback_days=30.0)
        self.assertEqual(out["false"], 0)
        self.assertEqual(out["checked"], 1)

    def test_a_move_with_NEGATIVE_realised_gain_is_false(self):
        """Перекладка в худшую ставку не окупается никогда — окупаться нечему."""
        recs = [_rec(0, cur={}), _rec(1, cur={}),
                _rec(2, cur={}, apy={"good": 0.0, "bad": 100.0})]
        out = R.false_rebalances([self._move(1, "good", "bad", 36_500.0, 10.0)],
                                 recs, day_gain=_gain, horizon_days=7,
                                 max_payback_days=30.0)
        self.assertEqual(out["false"], 1)
        self.assertIsNone(out["worst"][0]["payback_days"])

    def test_a_move_that_repays_too_slowly_is_false(self):
        recs = [_rec(0, cur={}), _rec(1, cur={}),
                _rec(2, cur={}, apy={"good": 1.0, "bad": 0.0})]
        out = R.false_rebalances([self._move(1, "good", "bad", 36_500.0, 1_000.0)],
                                 recs, day_gain=_gain, horizon_days=7,
                                 max_payback_days=30.0)
        self.assertEqual(out["false"], 1)
        self.assertGreater(out["worst"][0]["payback_days"], 30.0)

    def test_no_forward_prices_is_UNCHECKED_and_never_counted_as_false(self):
        """Не сверено ≠ ложно. Иначе молчание фида становилось бы находкой."""
        recs = [_rec(0, cur={}), _rec(1, cur={}), _rec(2, cur={}, apy={})]
        out = R.false_rebalances([self._move(1, "good", "bad", 36_500.0, 10.0)],
                                 recs, day_gain=_gain, horizon_days=7,
                                 max_payback_days=30.0)
        self.assertEqual(out["unchecked"], 1)
        self.assertEqual(out["false"], 0)
        self.assertEqual(out["checked"], 0)

    def test_an_unreadable_horizon_is_UNCHECKED_not_a_verdict(self):
        out = R.false_rebalances([], [], day_gain=_gain, horizon_days=7,
                                 max_payback_days=None)
        self.assertEqual(out["verdict"], R._UNCHECKED)

    def test_the_horizon_is_the_THRESHOLD_and_the_verdict_follows_it(self):
        """Порог берётся у демпфера: сдвинь его — сдвинется и вердикт."""
        recs = [_rec(0, cur={}), _rec(1, cur={}),
                _rec(2, cur={}, apy={"good": 1.0, "bad": 0.0})]
        move = [self._move(1, "good", "bad", 36_500.0, 40.0)]
        tight = R.false_rebalances(move, recs, day_gain=_gain, horizon_days=7,
                                   max_payback_days=30.0)
        wide = R.false_rebalances(move, recs, day_gain=_gain, horizon_days=7,
                                  max_payback_days=60.0)
        self.assertEqual(tight["false"], 1)
        self.assertEqual(wide["false"], 0)


# ── Пропущенные возможности ───────────────────────────────────────────────────

class TestMissedOpportunities(unittest.TestCase):

    def _daily(self, cur, opt):
        return {R.ARM_CURRENT: cur, R.ARM_CIO_HOLD: cur, R.ARM_CIO_OPT: opt}

    def test_an_edge_smaller_than_its_own_cost_is_not_an_opportunity(self):
        recs = [_rec(0, cur={}, band=0.0), _rec(1, cur={}, band=0.0)]
        moves = [{"day_index": 0, "cost_usd": 100.0}]
        out = R.missed_opportunities(self._daily([5.0], [10.0]), moves, [0],
                                     band_pp_of=lambda _i: 0.0, records=recs)
        self.assertEqual(out["missed"], 0)

    def test_an_edge_above_cost_and_band_is_an_opportunity(self):
        recs = [_rec(0, cur={}), _rec(1, cur={})]
        moves = [{"day_index": 0, "cost_usd": 1.0}]
        out = R.missed_opportunities(self._daily([5.0], [500.0]), moves, [0],
                                     band_pp_of=lambda _i: 0.0, records=recs)
        self.assertEqual(out["missed"], 1)
        self.assertAlmostEqual(out["worst"][0]["edge_usd_per_day"], 495.0)

    def test_the_band_of_the_gate_raises_the_bar(self):
        """Полоса читается из САМОЙ записи — не назначается модулем."""
        recs = [_rec(0, cur={}, capital=100_000.0), _rec(1, cur={})]
        moves = [{"day_index": 0, "cost_usd": 0.0}]
        loose = R.missed_opportunities(self._daily([0.0], [1.0]), moves, [0],
                                       band_pp_of=lambda _i: 0.0, records=recs)
        strict = R.missed_opportunities(self._daily([0.0], [1.0]), moves, [0],
                                        band_pp_of=lambda _i: 5.0, records=recs)
        self.assertEqual(loose["missed"], 1)
        self.assertEqual(strict["missed"], 0)

    def test_empty_population_is_UNCHECKED(self):
        out = R.missed_opportunities(self._daily([], []), [], [],
                                     band_pp_of=lambda _i: 0.0, records=[])
        self.assertEqual(out["verdict"], R._UNCHECKED)


# ── Находки и их зависимость от ОБЕИХ колонок ─────────────────────────────────

def _column(net_current, net_hold, net_opt, *, gross_spread=0.2,
            false_n=0, checked=0, unchecked=0, missed=0):
    arms = {
        R.ARM_CURRENT: {"net_apy_pct": net_current, "gross_apy_pct": 5.0,
                        "cost_usd": 204.0, "gross_usd": 102.5},
        R.ARM_CIO_HOLD: {"net_apy_pct": net_hold,
                         "gross_apy_pct": 5.0 + gross_spread, "cost_usd": 0.0,
                         "gross_usd": 103.7},
        R.ARM_CIO_OPT: {"net_apy_pct": net_opt, "gross_apy_pct": 5.0,
                        "cost_usd": 200.0, "gross_usd": 106.7},
    }
    return {"arms": arms,
            "false_rebalances": {"checked": checked, "false": false_n,
                                 "unchecked": unchecked, "max_payback_days": 30.0,
                                 "worst": []},
            "missed_opportunities": {"checked": 7, "missed": missed, "worst": []}}


class TestFindings(unittest.TestCase):

    POP = {"common_scored_days": 12, "day_pairs": 31}

    def test_hold_beating_the_book_in_BOTH_columns_is_a_finding(self):
        cols = {"charged": _column(-5.3, 5.4, -4.9),
                "observed": _column(0.3, 5.4, 0.7)}
        codes = [f["code"] for f in R._findings(cols, R._compare(cols), self.POP)]
        self.assertIn("hold_beats_the_live_book", codes)

    def test_a_conclusion_that_dies_on_OBSERVED_gas_is_NOT_a_finding(self):
        """Положительный контроль на ADR-243: вывод на литерале не объявляется.

        Тест краснеет, если кто-нибудь начнёт судить по одной колонке.
        """
        cols = {"charged": _column(-5.3, 5.4, -4.9),
                "observed": _column(9.9, 5.4, 9.8)}
        codes = [f["code"] for f in R._findings(cols, R._compare(cols), self.POP)]
        self.assertNotIn("hold_beats_the_live_book", codes)

    def test_chasing_the_optimum_being_worse_is_reported(self):
        cols = {"charged": _column(-5.3, 5.4, -6.0),
                "observed": _column(0.3, 5.4, -0.2)}
        codes = [f["code"] for f in R._findings(cols, R._compare(cols), self.POP)]
        self.assertIn("chasing_the_optimum_is_worse", codes)

    def test_false_rebalances_report_BOTH_columns_in_one_line(self):
        cols = {"charged": _column(-5.3, 5.4, -4.9, false_n=12, checked=13,
                                   unchecked=4),
                "observed": _column(0.3, 5.4, 0.7, false_n=9, checked=13,
                                    unchecked=4)}
        msgs = {f["code"]: f["message"]
                for f in R._findings(cols, R._compare(cols), self.POP)}
        self.assertIn("false_rebalances_dominate", msgs)
        self.assertIn("12 из 13", msgs["false_rebalances_dominate"])
        self.assertIn("9 из 13", msgs["false_rebalances_dominate"])

    def test_a_thin_common_population_is_said_OUT_LOUD(self):
        cols = {"charged": _column(-5.3, 5.4, -4.9)}
        pop = {"common_scored_days": 7, "day_pairs": 31}
        codes = [f["code"] for f in R._findings(cols, R._compare(cols), pop)]
        self.assertIn("thin_common_population", codes)

    def test_an_unchecked_comparison_produces_no_findings_at_all(self):
        cols = {"charged": {"arms": {a: {} for a in R.ARMS},
                            "false_rebalances": {}, "missed_opportunities": {}}}
        self.assertEqual(R._findings(cols, R._compare(cols), self.POP), [])

    def test_compare_names_the_best_arm_by_NET_not_by_gross(self):
        cols = {"charged": _column(-5.3, 5.4, -4.9)}
        cmp_ = R._compare(cols)["charged"]
        self.assertEqual(cmp_["best_net_arm"], R.ARM_CIO_HOLD)
        self.assertAlmostEqual(cmp_["hold_minus_current_pp"], 10.7)


# ── Прогон целиком ────────────────────────────────────────────────────────────

class TestRun(unittest.TestCase):

    def _root(self, records, *, registry=True, gas_history=None):
        td = tempfile.mkdtemp()
        os.makedirs(os.path.join(td, "data"), exist_ok=True)
        with open(os.path.join(td, "data/allocation_rationale_history.jsonl"),
                  "w", encoding="utf-8") as fh:
            for rec in records:
                fh.write(json.dumps(rec) + "\n")
        if registry:
            with open(os.path.join(td, "data/adapter_registry.json"), "w",
                      encoding="utf-8") as fh:
                json.dump({"adapters": {"a": {"chain": "ethereum"},
                                        "b": {"chain": "ethereum"}}}, fh)
        if gas_history is not None:
            with open(os.path.join(td, "data/gas_price_history.json"), "w",
                      encoding="utf-8") as fh:
                json.dump(gas_history, fh)
        return td

    def test_empty_history_is_UNCHECKED_not_OK(self):
        doc = R.run(root=self._root([]), now=_NOW, write=False)
        self.assertEqual(doc["overall"], R._UNCHECKED)
        self.assertTrue(doc["unchecked"])

    def test_no_common_day_is_UNCHECKED_and_names_the_reason(self):
        """Ни одного дня, сверенного во всех руках, — вердикта нет."""
        recs = [_rec(0, cur={"a": 100_000.0}, tgt={"b": 100_000.0}),
                _rec(1, cur={"b": 100_000.0}, tgt={"b": 100_000.0}, apy={"b": 5.0})]
        doc = R.run(root=self._root(recs), now=_NOW, write=False)
        self.assertEqual(doc["overall"], R._UNCHECKED)
        self.assertTrue(any("интерполировать" in u for u in doc["unchecked"]))

    def test_the_live_shape_reproduces_the_measurement_of_2026_09_06(self):
        """Книга крутится и теряет; тень стои́т и выигрывает.

        Это ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ на замер: убери из отчёта учёт стоимости —
        и вердикт перестанет быть CRITICAL.
        """
        recs = []
        for i in range(6):
            churn = {"a": 100_000.0} if i % 2 else {"b": 100_000.0}
            recs.append(_rec(i, cur=churn, tgt=churn,
                             apy={"a": 5.0, "b": 5.0}))
        doc = R.run(root=self._root(recs), now=_NOW, write=False)
        self.assertEqual(doc["overall"], "CRITICAL")
        codes = [f["code"] for f in doc["findings"]]
        self.assertIn("hold_beats_the_live_book", codes)
        charged = doc["comparison"]["charged"]
        self.assertEqual(charged["best_net_arm"], R.ARM_CIO_HOLD)
        self.assertGreater(charged["hold_minus_current_pp"], 0.0)

    def test_gross_yields_agreeing_while_NET_diverges_is_the_whole_point(self):
        recs = []
        for i in range(6):
            churn = {"a": 100_000.0} if i % 2 else {"b": 100_000.0}
            recs.append(_rec(i, cur=churn, apy={"a": 5.0, "b": 5.0}))
        doc = R.run(root=self._root(recs), now=_NOW, write=False)
        charged = doc["comparison"]["charged"]
        self.assertAlmostEqual(charged["gross_spread_pp"], 0.0, places=6)
        self.assertGreater(charged["hold_minus_current_pp"], 0.0)

    def test_population_is_reported_NEXT_TO_the_verdict(self):
        recs = [_rec(i, cur={"a": 100_000.0}, apy={"a": 5.0}) for i in range(4)]
        doc = R.run(root=self._root(recs), now=_NOW, write=False)
        pop = doc["population"]
        self.assertEqual(pop["days_observed"], 4)
        self.assertEqual(pop["day_pairs"], 3)
        self.assertEqual(pop["verdicts"], {"HOLD": 4})
        self.assertIn("common_scored_days", pop)

    def test_run_uses_the_injected_clock_and_no_other_door(self):
        recs = [_rec(i, cur={"a": 100_000.0}, apy={"a": 5.0}) for i in range(3)]
        doc = R.run(root=self._root(recs), now=_NOW, write=False)
        self.assertEqual(doc["generated_at"], _NOW.isoformat())

    def test_scoring_never_consults_the_calendar(self):
        """Ярлыки дней сдвинуты на десять лет — вердикт обязан не измениться."""
        base = [_rec(i, cur={"a": 100_000.0}, apy={"a": 5.0}) for i in range(4)]
        shifted = []
        for i, rec in enumerate(base):
            copy = dict(rec)
            copy["cycle_date"] = f"zday-{i:02d}"
            shifted.append(copy)
        a = R.run(root=self._root(base), now=_NOW, write=False)
        b = R.run(root=self._root(shifted), now=_NOW, write=False)
        self.assertEqual(a["overall"], b["overall"])
        self.assertEqual(a["comparison"], b["comparison"])

    def test_the_same_input_gives_the_same_answer(self):
        recs = [_rec(i, cur={"a": 100_000.0}, apy={"a": 5.0}) for i in range(4)]
        root = self._root(recs)
        a = R.run(root=root, now=_NOW, write=False)
        b = R.run(root=root, now=_NOW, write=False)
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))

    def test_write_false_leaves_no_artifact(self):
        recs = [_rec(i, cur={"a": 100_000.0}, apy={"a": 5.0}) for i in range(3)]
        root = self._root(recs)
        R.run(root=root, now=_NOW, write=False)
        self.assertFalse(os.path.exists(os.path.join(root, R.REPORT_REL)))

    def test_write_true_puts_the_artifact_where_the_manifest_says(self):
        recs = [_rec(i, cur={"a": 100_000.0}, apy={"a": 5.0}) for i in range(3)]
        root = self._root(recs)
        R.run(root=root, now=_NOW, write=True)
        with open(os.path.join(root, R.REPORT_REL), encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["generated_at"], _NOW.isoformat())

    def test_a_missing_gain_formula_is_a_THIRD_OUTCOME_not_a_verdict(self):
        """Нечем прогнать ≠ разницы нет. Саботируем импорт производителя."""
        recs = [_rec(i, cur={"a": 100_000.0}, apy={"a": 5.0}) for i in range(3)]
        root = self._root(recs)
        with _no_module("spa_core.paper_trading", "shadow_trigger_eval"):
            doc = R.run(root=root, now=_NOW, write=False)
        self.assertEqual(doc["overall"], R._UNCHECKED)
        self.assertTrue(any("формулу выгоды" in u for u in doc["unchecked"]))

    def test_a_missing_cost_model_is_a_THIRD_OUTCOME(self):
        recs = [_rec(i, cur={"a": 100_000.0}, apy={"a": 5.0}) for i in range(3)]
        root = self._root(recs)
        with _no_module("spa_core.allocator", "rebalance_economics"):
            doc = R.run(root=root, now=_NOW, write=False)
        self.assertEqual(doc["overall"], R._UNCHECKED)
        self.assertTrue(any("стоимости" in u for u in doc["unchecked"]))

    def test_a_missing_registry_is_said_out_loud_not_silently_defaulted(self):
        recs = [_rec(i, cur={"a": 100_000.0}, apy={"a": 5.0}) for i in range(3)]
        doc = R.run(root=self._root(recs, registry=False), now=_NOW, write=False)
        self.assertTrue(any("карта сетей" in u for u in doc["unchecked"]))

    def test_the_observed_column_is_ABSENT_not_faked_when_gas_is_unmeasured(self):
        """Нет наблюдения — нет колонки. Молча подставить литерал нельзя."""
        recs = [_rec(i, cur={"a": 100_000.0}, apy={"a": 5.0}) for i in range(3)]
        doc = R.run(root=self._root(recs), now=_NOW, write=False)
        self.assertNotIn("observed", doc["columns"])
        self.assertTrue(any("наблюдённ" in u for u in doc["unchecked"]))


# ── Проводка: дом артефакта и его потребитель ─────────────────────────────────

class TestWiring(unittest.TestCase):
    """Артефакт без ДОМА и без ЧИТАТЕЛЯ — тот самый дефект, который меряет модуль."""

    ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    def _manifest(self):
        with open(os.path.join(self.ROOT, "architecture/manifest.json"),
                  encoding="utf-8") as fh:
            return json.load(fh)

    def test_the_artifact_has_an_entry_in_artifacts(self):
        paths = [a.get("path") for a in self._manifest().get("artifacts", [])]
        self.assertIn(R.REPORT_REL, paths)

    def test_the_artifact_has_a_PRODUCES_entry_on_its_producing_agent(self):
        """Паритет-тест краснеет только на ВТОРОЙ записи — она обязана быть."""
        man = self._manifest()
        art = next(a for a in man["artifacts"] if a.get("path") == R.REPORT_REL)
        producer = art["producer"]
        agent = next(a for a in man["agents"]
                     if a.get("label") == producer or a.get("name") == producer
                     or a.get("id") == producer)
        self.assertIn(R.REPORT_REL,
                      [p.get("artifact") for p in agent.get("produces", [])])

    def test_the_bridge_DECLARES_the_artifact_and_CALLS_the_module(self):
        from spa_core.monitoring import findings_bridge
        self.assertIn(R.REPORT_REL, findings_bridge.PRODUCES)
        with open(os.path.join(self.ROOT, "spa_core/monitoring/findings_bridge.py"),
                  encoding="utf-8") as fh:
            src = fh.read()
        # Проверяем ФОРМУ вызова, а не упоминание имени: имя есть и в PRODUCES.
        self.assertIn("cio_shadow_replay.run(", src)

    def test_the_office_step_has_a_NAMED_printing_branch(self):
        path = os.path.join(self.ROOT, "scripts/consume_office_reports.py")
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn('elif name == "cio_shadow_replay.json":', src)
        self.assertIn('"cio_shadow_replay.json": '
                      '"spa_core/monitoring/cio_shadow_replay.py"', src)


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
