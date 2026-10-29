"""ADR-859 — ЖАДНЫЙ СПРЕД есть НИЖНЯЯ ГРАНИЦА, а не оптимум.

Каждый тест — положительный контроль на один из шести дефектов, против которых
прибор написан:

1. **«жадный спред не оптимален» осталось РАССУЖДЕНИЕМ.** ADR-855 назвал это
   прямо и честно оставил без замера. Сцена ``BEATEN_*`` — настоящая запись
   истории, на которой дверь книги ПУСКАЕТ жадную книгу, и всё равно есть
   допустимая книга ДЕШЕВЛЕ: 17.87 дн. против 20.40. Причина названа в тесте
   и измерима — жадное правило берёт ногу с лучшей ставкой, не спрашивая, что
   она на ДРУГОЙ сети, и платит за мост.
2. **отказанная книга, прочитанная как «дорогой вариант».** Книга, которой
   дверь отказала, не хуже и не лучше — её НЕТ. Сцена ``REFUSED_CHEAPER_*``
   ровно такова: окупаемость жадной книги 14.83 дн. (лучшая из трёх!), а дверь
   её отказывает, и поиск даёт 23.20. Сложить эти числа в одно сравнение
   значило бы смешать рода (ADR-580 C2), поэтому перепись считает ось «против
   жадного» ТОЛЬКО там, где дверь жадную книгу пускает. Контроль в обе стороны.
3. **нижняя граница, названная оптимумом.** Доминирование жадного — инвариант
   ПОСТРОЕНИЯ (полное подмножество при потолке и есть книга жадного), и он
   проверяется; а вот «это оптимум» НЕ утверждается нигде, и притязание прибора
   (``claim``) обязано стоять в самой переписи.
4. **молча урезанный перебор, выданный за полный.** Ног больше потолка перебора
   ⇒ ``search_truncated`` с НАЗВАННЫМ числом подмножеств, а не тихо усечённый
   ответ (инв. #17).
5. **край отрезка, найденный на глаз.** Деление отрезка обязано давать КРАЙ:
   допустимо в нём и недопустимо чуть дальше. На сцене ``REFUSED_CHEAPER_*``
   край ставит ЖИВОЙ потолок концентрации на сеть (90 % ethereum) — ограничение,
   которого не знали ни жадное правило, ни контрпример ADR-850 про группу T2.
6. **прибор без читателя.** Проводка проверяется НАСТОЯЩИМ ``evaluate_window``
   и НАСТОЯЩИМ шагом 0-офис, а не подстрокой в исходнике: собранный руками
   словарь мерил бы свой словарь (урок ADR-835/#944/#945).

Сцены 1–2 и обе сцены исходов взяты из ЖИВОЙ истории предложений (замер 29.10)
и вписаны литералами: прибор обязан отвечать одинаково на любой машине, а
чтение живого ``data/`` сделало бы тест зависимым от хоста.

# FROZEN-DATE-OK: injected-clock — якорь ``_NOW`` передаётся
# ``evaluate_window(..., now=_NOW)``, и все отметки сцены производны от него же.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.allocator.rebalance_economics import TriggerParams
from spa_core.paper_trading.trim_optimum import (
    CENSUS_MEASURED,
    CENSUS_MEASURED_ZERO,
    CENSUS_UNMEASURED,
    OPT_MEASURED,
    OPT_NO_SUBJECT,
    OPT_NONE_ADMISSIBLE,
    OPT_SEARCH_TRUNCATED,
    OPT_STANDING_INADMISSIBLE,
    OPT_TIER_UNKNOWN,
    OPT_UNMEASURED,
    _approved,
    _fill,
    _largest_admissible_turnover,
    compare_trim_optimum,
    format_trim_optimum,
    score_book,
    search_admissible_optimum,
    trim_optimum_census,
    trim_optimum_outcome,
)

_NOW = datetime(2026, 10, 29, 11, 3, tzinfo=timezone.utc)

CAPITAL = 100_000.0
PARAMS = TriggerParams.for_mode("paper")

# ── сцена 1: дверь ПУСКАЕТ жадную книгу, и всё равно есть дешевле ─────────────
# Предложение разворачивает кэш (ход в плюс), поэтому сторона продажи пуста.
# Жадное правило сортирует покупки по ставке и берёт `morpho_blue_base` (4.42)
# ПЕРЕД `aave_v3` (3.27) — а `morpho_blue_base` живёт на сети `base`, то есть
# вторая нога добавляет и газ, и МОСТ. Поиск берёт одну ногу на одной сети:
# выигрыш меньше, цена меньше сильнее, окупаемость лучше.
BEATEN_CURRENT = {"compound_v3": 37_894.74, "fluid_usdc": 9_473.68,
                  "maple": 18_947.37}
BEATEN_TARGET = {"aave_v3": 22_105.26, "compound_v3": 37_894.74,
                 "fluid_usdc": 9_473.68, "maple": 18_947.37,
                 "morpho_blue_base": 6_578.95}
BEATEN_APY = {"aave_v3": 3.2679, "compound_v3": 4.6852, "fluid_usdc": 4.7,
              "maple": 4.9719, "morpho_blue_base": 4.4246}
BEATEN_TIERS = {"aave_v3": "T1", "compound_v3": "T1", "fluid_usdc": "T2",
                "maple": "T2", "morpho_blue_base": "T2"}
BEATEN_CHAINS = {"aave_v3": "ethereum", "compound_v3": "ethereum",
                 "fluid_usdc": "ethereum", "maple": "ethereum",
                 "morpho_blue_base": "base"}

# ── сцена 2: у ОТКАЗАННОЙ книги окупаемость ЛУЧШЕ всех ───────────────────────
REFUSED_CURRENT = {"aave_v3": 5_000.0, "compound_v3": 40_000.0,
                   "fluid_usdc": 20_000.0, "maple": 20_000.0,
                   "morpho_blue_base": 10_000.0}
REFUSED_TARGET = {"compound_v3": 40_000.0, "fluid_usdc": 20_000.0,
                  "maple": 10_000.0, "pendle": 20_000.0}
REFUSED_APY = {"aave_v3": 3.3871, "compound_v3": 4.0868, "fluid_usdc": 5.53,
               "maple": 5.083, "morpho_blue_base": 4.2604, "pendle": 13.9121}
REFUSED_TIERS = {"aave_v3": "T1", "compound_v3": "T1", "fluid_usdc": "T2",
                 "maple": "T2", "morpho_blue_base": "T2", "pendle": "T2"}
REFUSED_CHAINS = dict({k: "ethereum" for k in REFUSED_TIERS},
                      morpho_blue_base="base")

# ── сцена 3: допустимой книги НЕТ ни при каком подмножестве ──────────────────
NONE_CURRENT = {"aave_v3": 40_000.0, "maple": 20_000.0,
                "morpho_steakhouse": 10_000.0, "pendle": 20_000.0}
NONE_TARGET = {"aave_v3": 5_000.0, "maple": 20_000.0, "morpho_blue": 10_000.0,
               "morpho_steakhouse": 40_000.0, "pendle": 20_000.0}
NONE_APY = {"aave_v3": 3.3024, "maple": 4.8268, "morpho_blue": 4.397,
            "morpho_steakhouse": 4.397, "pendle": 13.9899}
NONE_TIERS = {"aave_v3": "T1", "maple": "T2", "morpho_blue": "T2",
              "morpho_steakhouse": "T2", "pendle": "T2"}
NONE_CHAINS = {k: "ethereum" for k in NONE_TIERS}

# ── сцена 4: день УЖЕ стоял вне политики ─────────────────────────────────────
STANDING_CURRENT = {"aave_v3": 5_000.0, "maple": 20_000.0,
                    "morpho_steakhouse": 40_000.0, "pendle": 20_000.0}
STANDING_TARGET = {"aave_v3": 40_000.0, "maple": 20_000.0,
                   "morpho_steakhouse": 5_000.0, "pendle": 20_000.0}
STANDING_APY = {"aave_v3": 4.9913, "maple": 4.961, "morpho_steakhouse": 3.4961,
                "pendle": 15.0957}
STANDING_TIERS = {"aave_v3": "T1", "maple": "T2", "morpho_steakhouse": "T2",
                  "pendle": "T2"}
STANDING_CHAINS = {k: "ethereum" for k in STANDING_TIERS}


def _one(current, target, apy, tiers, chains, capital=CAPITAL, params=PARAMS):
    return compare_trim_optimum(current, target, apy, capital_usd=capital,
                                params=params, tiers=tiers, chains=chains)


def _beaten():
    return _one(BEATEN_CURRENT, BEATEN_TARGET, BEATEN_APY,
                BEATEN_TIERS, BEATEN_CHAINS)


def _refused():
    return _one(REFUSED_CURRENT, REFUSED_TARGET, REFUSED_APY,
                REFUSED_TIERS, REFUSED_CHAINS)


def _record(label, current, target, apy):
    return {"cycle_date": label, "capital_usd": CAPITAL,
            "current_positions": dict(current),
            "target_positions": dict(target),
            "apy_evidenced_pct": dict(apy)}


class TheGreedySpreadIsDominatedByConstruction(unittest.TestCase):
    """Дефект 1 и 3: рассуждение становится замером, но НЕ становится оптимумом."""

    def test_an_admissible_greedy_book_is_still_beaten(self):
        one = _beaten()
        self.assertEqual(one["kind"], OPT_MEASURED)
        # Дверь жадную книгу ПУСКАЕТ — значит сравнение внутри одного рода.
        self.assertTrue(one["approved"]["greedy"])
        self.assertLess(one["payback"]["search"], one["payback"]["greedy"])
        self.assertAlmostEqual(one["payback"]["greedy"], 20.40, places=2)
        self.assertAlmostEqual(one["payback"]["search"], 17.87, places=2)

    def test_the_reason_is_the_leg_the_greedy_rule_cannot_refuse(self):
        """ПОЧЕМУ жадный проигрывает — измеримо, а не на словах.

        Жадное правило обязано взять ногу с лучшей СТАВКОЙ. Здесь это
        ``morpho_blue_base`` на сети ``base``, то есть вторая сеть в ходе и
        мост в цене. Поиск берёт ОДНУ ногу на ОДНОЙ сети.
        """
        one = _beaten()
        best = one["search"]["best"]
        self.assertEqual(best["subset_buy"], ("aave_v3",))
        self.assertEqual(best["subset_sell"], ())
        self.assertEqual(best["legs"], 1)
        # Жадная книга платит и за газ второй ноги, и за мост между сетями.
        greedy_legs = one["legs"]["greedy"]
        self.assertGreater(greedy_legs, best["legs"])
        # Выигрыш у жадного БОЛЬШЕ — проигрывает он именно ценой, и это
        # отличает находку от «поиск нашёл более жирный ход».
        from spa_core.paper_trading.trim_shape import shapes_of_proposal
        shapes = shapes_of_proposal(BEATEN_CURRENT, BEATEN_TARGET, BEATEN_APY,
                                    capital_usd=CAPITAL, params=PARAMS)
        greedy = score_book(shapes["current"], shapes["book_subset"], BEATEN_APY,
                            capital_usd=CAPITAL,
                            min_leg_frac=float(shapes["min_leg_frac"]),
                            chains=BEATEN_CHAINS)
        assert greedy is not None
        self.assertGreater(greedy["gain_pp"], best["gain_pp"])
        self.assertGreater(greedy["cost_usd"], best["cost_usd"])

    def test_the_search_is_never_worse_than_an_admissible_greedy(self):
        """Инвариант ПОСТРОЕНИЯ, проверенный на каждой сцене, где он применим."""
        scenes = {
            "BEATEN": (BEATEN_CURRENT, BEATEN_TARGET, BEATEN_APY,
                       BEATEN_TIERS, BEATEN_CHAINS),
            "REFUSED_CHEAPER": (REFUSED_CURRENT, REFUSED_TARGET, REFUSED_APY,
                                REFUSED_TIERS, REFUSED_CHAINS),
            "NONE_ADMISSIBLE": (NONE_CURRENT, NONE_TARGET, NONE_APY,
                                NONE_TIERS, NONE_CHAINS),
        }
        for name, args in scenes.items():
            with self.subTest(scene=name):
                one = _one(*args)
                approved = (one.get("approved") or {}).get("greedy")
                greedy = (one.get("payback") or {}).get("greedy")
                search = (one.get("payback") or {}).get("search")
                if not approved or greedy is None or search is None:
                    # Инвариант про ДОПУСТИМОГО жадного; остальное — не он.
                    continue
                self.assertLessEqual(search, greedy + 1e-6)

    def test_the_census_says_out_loud_that_this_is_a_lower_bound(self):
        """Дефект 3: притязание обязано стоять В САМОЙ переписи, не только в коде."""
        census = trim_optimum_census(
            [_record("день-1", BEATEN_CURRENT, BEATEN_TARGET, BEATEN_APY)],
            params=PARAMS, tiers=BEATEN_TIERS, tiers_measured=True,
            chains=BEATEN_CHAINS, chains_measured=True)
        self.assertEqual(census["kind"], CENSUS_MEASURED)
        self.assertIn("НИЖНЯЯ ГРАНИЦА", census["claim"])
        self.assertIn("НЕ оптимум", census["claim"])
        self.assertIn("НИЖНЯЯ ГРАНИЦА", census["last"]["search"]["claim"])

    def test_the_dominance_counter_of_the_census_is_zero_on_the_scenes(self):
        census = trim_optimum_census(
            [_record("день-1", BEATEN_CURRENT, BEATEN_TARGET, BEATEN_APY)],
            params=PARAMS, tiers=BEATEN_TIERS, tiers_measured=True,
            chains=BEATEN_CHAINS, chains_measured=True)
        self.assertEqual(census["vs_greedy"]["search_worse"], 0)
        self.assertEqual(census["vs_greedy"]["search_strictly_better"], 1)


class ARefusedBookIsNotACheaperVariant(unittest.TestCase):
    """Дефект 2: смешать «пустят» и «отказали» — смешать рода (ADR-580 C2)."""

    def test_the_refused_greedy_book_really_has_the_best_number(self):
        # Без этого утверждения тест ниже проверял бы пустое место.
        one = _refused()
        self.assertEqual(one["kind"], OPT_MEASURED)
        self.assertFalse(one["approved"]["greedy"])
        self.assertAlmostEqual(one["payback"]["greedy"], 14.83, places=2)
        self.assertAlmostEqual(one["payback"]["search"], 23.20, places=2)
        self.assertLess(one["payback"]["greedy"], one["payback"]["search"])

    def test_the_base_of_comparison_skips_the_refused_book(self):
        one = _refused()
        # Лучшая ДОПУСТИМАЯ прежняя форма — интерполяция, не жадный.
        self.assertAlmostEqual(one["payback"]["best_known_admissible"],
                               one["payback"]["interpolated"], places=6)
        self.assertNotAlmostEqual(one["payback"]["best_known_admissible"],
                                  one["payback"]["greedy"], places=2)

    def test_the_census_excludes_it_from_the_greedy_axis(self):
        census = trim_optimum_census(
            [_record("день-1", REFUSED_CURRENT, REFUSED_TARGET, REFUSED_APY)],
            params=PARAMS, tiers=REFUSED_TIERS, tiers_measured=True,
            chains=REFUSED_CHAINS, chains_measured=True)
        self.assertEqual(census["kind"], CENSUS_MEASURED)
        # Ось «против жадного» ПУСТА — книги, с которой сравнивать, нет.
        self.assertEqual(census["vs_greedy"]["comparable"], 0)
        self.assertEqual(census["vs_greedy"]["search_worse"], 0)
        # А главная ось — есть: допустимая прежняя форма существует.
        self.assertEqual(census["vs_best_known_admissible"]["comparable"], 1)

    def test_the_other_direction_an_admissible_greedy_IS_counted(self):
        """Обратный контроль: исключение по ДОПУСТИМОСТИ, а не «всегда пусто»."""
        census = trim_optimum_census(
            [_record("день-1", BEATEN_CURRENT, BEATEN_TARGET, BEATEN_APY)],
            params=PARAMS, tiers=BEATEN_TIERS, tiers_measured=True,
            chains=BEATEN_CHAINS, chains_measured=True)
        self.assertEqual(census["vs_greedy"]["comparable"], 1)

    def test_a_naive_axis_would_have_called_the_search_worse(self):
        """Цена правила, названная числом: наивное сравнение дало бы «хуже»."""
        one = _refused()
        naive_worse = one["payback"]["search"] > one["payback"]["greedy"]
        self.assertTrue(naive_worse, "сцена обязана быть той, на которой "
                                     "наивное сравнение ошибается")
        census = trim_optimum_census(
            [_record("день-1", REFUSED_CURRENT, REFUSED_TARGET, REFUSED_APY)],
            params=PARAMS, tiers=REFUSED_TIERS, tiers_measured=True,
            chains=REFUSED_CHAINS, chains_measured=True)
        self.assertEqual(census["vs_greedy"]["search_worse"], 0)


class EveryOutcomeIsAValue(unittest.TestCase):
    """Дефект 4 и инв. #17: каждый исход назван, ни один не притворяется соседом."""

    def test_no_admissible_book_is_its_own_outcome_not_a_measured_zero(self):
        one = _one(NONE_CURRENT, NONE_TARGET, NONE_APY, NONE_TIERS, NONE_CHAINS)
        self.assertEqual(one["kind"], OPT_NONE_ADMISSIBLE)
        self.assertIn("перебраны все подмножества", one["why"])
        # Перебор БЫЛ, и его размер назван — это отличает «искали и не нашли»
        # от «не искали».
        self.assertGreater(one["search"]["subsets_tried"], 0)
        self.assertEqual(one["search"]["admissible_books_found"], 0)

    def test_a_standing_book_outside_the_policy_stops_the_record(self):
        one = _one(STANDING_CURRENT, STANDING_TARGET, STANDING_APY,
                   STANDING_TIERS, STANDING_CHAINS)
        self.assertEqual(one["kind"], OPT_STANDING_INADMISSIBLE)
        self.assertIn("наследства", one["why"])

    def test_a_proposal_within_the_size_cap_has_no_subject(self):
        small = dict(REFUSED_CURRENT)
        small["maple"] = REFUSED_CURRENT["maple"] - 1_000.0
        small["aave_v3"] = REFUSED_CURRENT["aave_v3"] + 1_000.0
        one = _one(REFUSED_CURRENT, small, REFUSED_APY,
                   REFUSED_TIERS, REFUSED_CHAINS)
        self.assertEqual(one["kind"], OPT_NO_SUBJECT)

    def test_an_unknown_tier_is_its_own_outcome_never_T2(self):
        one = _one(REFUSED_CURRENT, REFUSED_TARGET, REFUSED_APY,
                   {k: v for k, v in REFUSED_TIERS.items() if k != "pendle"},
                   REFUSED_CHAINS)
        self.assertEqual(one["kind"], OPT_TIER_UNKNOWN)
        self.assertIn("ADR-359", one["why"] + " ")

    def test_capital_not_recorded_is_unmeasured_with_a_named_reason(self):
        one = _one(REFUSED_CURRENT, REFUSED_TARGET, REFUSED_APY,
                   REFUSED_TIERS, REFUSED_CHAINS, capital=0.0)
        self.assertEqual(one["kind"], OPT_UNMEASURED)
        self.assertIn("капитал", one["why"])

    def test_too_many_legs_is_named_not_silently_truncated(self):
        from spa_core.paper_trading.trim_shape import shapes_of_proposal
        shapes = shapes_of_proposal(REFUSED_CURRENT, REFUSED_TARGET, REFUSED_APY,
                                    capital_usd=CAPITAL, params=PARAMS)
        found = search_admissible_optimum(
            shapes["current"], shapes["proposal"], REFUSED_APY,
            admissible_usd=float(shapes["admissible_usd"]),
            net_cash_usd=float(shapes["net_cash_usd"]),
            capital_usd=CAPITAL,
            min_leg_frac=float(shapes["min_leg_frac"]),
            tiers=REFUSED_TIERS, chains=REFUSED_CHAINS, max_subsets=2)
        self.assertEqual(found["kind"], OPT_SEARCH_TRUNCATED)
        # ЧИСЛО названо — иначе «не полон» нечем поверить.
        self.assertEqual(found["subsets_total"], 16)
        self.assertIn("НЕ полон", found["why"])

    def test_the_real_leg_counts_stay_under_the_declared_ceiling(self):
        """Обратный контроль к усечению: на живых сценах предел НЕ достигается."""
        from spa_core.paper_trading.trim_optimum import MAX_SUBSETS_PER_RECORD
        for name, one in (("BEATEN", _beaten()), ("REFUSED", _refused())):
            with self.subTest(scene=name):
                self.assertNotEqual(one["kind"], OPT_SEARCH_TRUNCATED)
                self.assertLess(one["search"]["subsets_tried"],
                                MAX_SUBSETS_PER_RECORD)


class TheBisectionFindsTheEdgeOfTheAdmissibleInterval(unittest.TestCase):
    """Дефект 5: край отрезка — измеряемое свойство, а не «примерно столько»."""

    SUBSET_BUY = [["pendle", 20_000.0]]
    SUBSET_SELL = [["morpho_blue_base", 10_000.0]]
    CEILING = 15_000.0
    NET = -3_000.0

    def _edge(self):
        return _largest_admissible_turnover(
            REFUSED_CURRENT, self.SUBSET_BUY, self.SUBSET_SELL,
            ceiling=self.CEILING, net=self.NET, apy_pct=REFUSED_APY,
            capital_usd=CAPITAL, tiers=REFUSED_TIERS, chains=REFUSED_CHAINS)

    def _ok_at(self, size):
        book = _fill(REFUSED_CURRENT, self.SUBSET_BUY, self.SUBSET_SELL,
                     size, self.NET)
        assert book is not None
        return _approved(book, REFUSED_APY, CAPITAL,
                         tiers=REFUSED_TIERS, chains=REFUSED_CHAINS)

    def test_the_edge_is_interior_so_the_test_has_a_subject(self):
        edge = self._edge()
        self.assertIsNotNone(edge)
        assert edge is not None
        self.assertLess(edge, self.CEILING - 1.0)

    def test_it_is_admissible_in_the_edge_and_just_inside_it(self):
        edge = self._edge()
        assert edge is not None
        for mult in (1.0, 0.999, 0.5):
            with self.subTest(multiplier=mult):
                self.assertTrue(self._ok_at(edge * mult))

    def test_it_is_inadmissible_just_beyond_the_edge(self):
        edge = self._edge()
        assert edge is not None
        for mult in (1.001, 1.2, 2.0):
            with self.subTest(multiplier=mult):
                self.assertFalse(self._ok_at(edge * mult))

    def test_the_edge_is_set_by_a_LIVE_policy_limit_and_it_is_named(self):
        """Край обязан ставить настоящий потолок, а не ошибка счёта.

        Здесь это концентрация на СЕТЬ — ограничение, которого не знают ни
        жадное правило, ни контрпример ADR-850 (там потолок на ГРУППУ T2).
        """
        from spa_core.paper_trading.trim_admissibility import book_verdict
        edge = self._edge()
        assert edge is not None
        book = _fill(REFUSED_CURRENT, self.SUBSET_BUY, self.SUBSET_SELL,
                     edge * 1.01, self.NET)
        verdict, _unknown = book_verdict(book or {}, REFUSED_APY, CAPITAL,
                                         tiers=REFUSED_TIERS,
                                         chains=REFUSED_CHAINS)
        assert verdict is not None
        self.assertFalse(verdict["approved"])
        self.assertTrue(any("Chain concentration" in v
                            for v in verdict["violations"]),
                        verdict["violations"])

    def test_the_limit_really_comes_from_the_policy_object(self):
        """Контроль двери: сузили живой потолок — край обязан сдвинуться."""
        from unittest import mock

        from spa_core.risk import policy as pol
        original = pol.RiskPolicy
        wide = self._edge()
        assert wide is not None

        def narrower(config=None):
            built = original(config)
            built.config.max_single_chain_allocation = 0.85
            return built

        with mock.patch.object(pol, "RiskPolicy", narrower):
            narrow = self._edge()
        self.assertNotEqual(narrow, wide)


class TheDoorIsOneForEveryReader(unittest.TestCase):
    """Исход читается ОДНОЙ дверью — урок ADR-851."""

    def test_a_missing_block_is_unmeasured_not_a_zero(self):
        kind, why = trim_optimum_outcome(None)
        self.assertEqual(kind, CENSUS_UNMEASURED)
        self.assertIn("ADR-851", why)

    def test_an_unknown_kind_does_not_pass_for_measured(self):
        kind, why = trim_optimum_outcome({"kind": "совсем новое"})
        self.assertEqual(kind, CENSUS_UNMEASURED)
        self.assertIn("совсем новое", why)

    def test_a_registry_that_was_not_read_is_unmeasured_not_a_zero(self):
        census = trim_optimum_census(
            [_record("день-1", BEATEN_CURRENT, BEATEN_TARGET, BEATEN_APY)],
            params=PARAMS, tiers={}, tiers_measured=False,
            chains=BEATEN_CHAINS, chains_measured=True)
        self.assertEqual(census["kind"], CENSUS_UNMEASURED)
        self.assertIn("ADR-359", census["why"])

    def test_a_history_with_nothing_trimmable_is_a_measured_zero(self):
        small = dict(REFUSED_CURRENT)
        small["maple"] = REFUSED_CURRENT["maple"] - 1_000.0
        small["aave_v3"] = REFUSED_CURRENT["aave_v3"] + 1_000.0
        census = trim_optimum_census(
            [_record("день-1", REFUSED_CURRENT, small, REFUSED_APY)],
            params=PARAMS, tiers=REFUSED_TIERS, tiers_measured=True,
            chains=REFUSED_CHAINS, chains_measured=True)
        self.assertEqual(census["kind"], CENSUS_MEASURED_ZERO)
        self.assertEqual(census["outcomes"].get(OPT_NO_SUBJECT), 1)

    def test_an_empty_history_is_unmeasured_not_a_measured_zero(self):
        census = trim_optimum_census([], params=PARAMS, tiers=BEATEN_TIERS,
                                     tiers_measured=True, chains=BEATEN_CHAINS,
                                     chains_measured=True)
        self.assertEqual(census["kind"], CENSUS_UNMEASURED)

    def test_history_that_is_not_a_list_is_unmeasured_with_a_reason(self):
        census = trim_optimum_census({"not": "a list"},  # type: ignore[arg-type]
                                     params=PARAMS, tiers=BEATEN_TIERS,
                                     tiers_measured=True, chains=BEATEN_CHAINS,
                                     chains_measured=True)
        self.assertEqual(census["kind"], CENSUS_UNMEASURED)
        self.assertIn("список", census["why"])

    def test_the_printer_of_an_unmeasured_census_prints_no_numbers(self):
        lines = format_trim_optimum(None)
        self.assertEqual(len(lines), 2)
        self.assertNotIn("ПРОТИВ", "\n".join(lines))

    def test_the_printer_of_a_measured_census_prints_both_axes(self):
        census = trim_optimum_census(
            [_record("день-1", BEATEN_CURRENT, BEATEN_TARGET, BEATEN_APY)],
            params=PARAMS, tiers=BEATEN_TIERS, tiers_measured=True,
            chains=BEATEN_CHAINS, chains_measured=True)
        text = "\n".join(format_trim_optimum(census))
        self.assertIn("ПРОТИВ ЖАДНОГО", text)
        self.assertIn("ПРОТИВ лучшей ДОПУСТИМОЙ прежней формы", text)
        self.assertIn("НИЖНЯЯ ГРАНИЦА", text)
        self.assertIn("ADVISORY", text)

    def test_the_horizon_counters_come_from_the_params_door(self):
        from dataclasses import replace
        rows = [_record("день-1", BEATEN_CURRENT, BEATEN_TARGET, BEATEN_APY)]
        wide = trim_optimum_census(
            rows, params=replace(PARAMS, max_payback_days=10_000.0),
            tiers=BEATEN_TIERS, tiers_measured=True,
            chains=BEATEN_CHAINS, chains_measured=True)
        self.assertEqual(wide["horizon_days"], 10_000.0)
        self.assertEqual(wide["vs_best_known_admissible"]["within_horizon_search"],
                         wide["vs_best_known_admissible"]["comparable"])
        narrow = trim_optimum_census(
            rows, params=replace(PARAMS, max_payback_days=1.0),
            tiers=BEATEN_TIERS, tiers_measured=True,
            chains=BEATEN_CHAINS, chains_measured=True)
        self.assertEqual(
            narrow["vs_best_known_admissible"]["within_horizon_search"], 0)


class TheCensusIsWiredIntoTheArtifactNotJustWritten(unittest.TestCase):
    """Дефект 6: прибор без читателя — сирота (ADR-843)."""

    def _scene(self, tmp: Path) -> None:
        rows = []
        for day in range(6):
            stamp = _NOW - timedelta(days=5 - day)
            rows.append({
                "cycle_date": stamp.date().isoformat(),
                "generated_at": stamp.isoformat(),
                "decision_id": f"scene-{day}",
                "capital_usd": CAPITAL,
                "verdict": "HOLD",
                "turnover_usd": 60_000.0,
                "gain_pp": 1.1,
                "current_positions": dict(BEATEN_CURRENT),
                "target_positions": dict(BEATEN_TARGET),
                "apy_evidenced_pct": dict(BEATEN_APY),
            })
        (tmp / "allocation_rationale_history.jsonl").write_text(
            "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
        (tmp / "adapter_registry.json").write_text(json.dumps({
            "adapters": {k: {"tier": t, "chain": BEATEN_CHAINS[k]}
                         for k, t in BEATEN_TIERS.items()}}), encoding="utf-8")

    def test_evaluate_window_carries_the_block_and_format_summary_prints_it(self):
        from spa_core.paper_trading.shadow_trigger_eval import (
            evaluate_window, format_summary)
        with TemporaryDirectory() as raw:
            tmp = Path(raw)
            self._scene(tmp)
            doc = evaluate_window(tmp, write=False, now=_NOW)
        self.assertIn("trim_optimum_census", doc)
        kind, why = trim_optimum_outcome(doc["trim_optimum_census"])
        self.assertEqual(kind, CENSUS_MEASURED, why)
        self.assertEqual(doc["trim_optimum_census"]["population"], 6)
        self.assertIn("приз ограниченного поиска", format_summary(doc))

    def test_the_office_step_declares_the_block_in_its_read_schema(self):
        """Необъявленное чтение молча становится `None` — класс ADR-855."""
        import importlib
        office = importlib.import_module("scripts.consume_office_reports")
        declared = office._READ_SCHEMA["shadow_trigger_evaluation.json"]
        self.assertIn("trim_optimum_census", declared)

    def test_the_office_step_prints_the_block_through_the_same_printer(self):
        # Не подстрока в исходнике, а НАСТОЯЩИЙ вызов выжимки шага 0-офис.
        import importlib
        office = importlib.import_module("scripts.consume_office_reports")
        census = trim_optimum_census(
            [_record("день-1", BEATEN_CURRENT, BEATEN_TARGET, BEATEN_APY)],
            params=PARAMS, tiers=BEATEN_TIERS, tiers_measured=True,
            chains=BEATEN_CHAINS, chains_measured=True)
        doc = {"status": "NOT_READY", "ready_to_arm": False,
               "observation_days": 1, "generated_at": _NOW.isoformat(),
               "trim_optimum_census": census}
        text = "\n".join(
            office._summarize_json("shadow_trigger_evaluation.json", doc))
        self.assertIn("приз ограниченного поиска", text)
        self.assertIn("ПРОТИВ ЖАДНОГО", text)

    def test_an_artifact_without_the_block_is_named_not_silently_zero(self):
        """Отрицательный контроль: запись СТАРШЕ прибора звучит, а не молчит."""
        import importlib
        office = importlib.import_module("scripts.consume_office_reports")
        text = "\n".join(office._summarize_json(
            "shadow_trigger_evaluation.json",
            {"status": "NOT_READY", "ready_to_arm": False,
             "observation_days": 1, "generated_at": _NOW.isoformat()}))
        self.assertIn("приз ограниченного поиска", text)
        self.assertIn(CENSUS_UNMEASURED, text)

    def test_the_block_changes_no_verdict_of_the_day(self):
        # ADVISORY объявлено — значит обязано быть ПРОВЕРЕНО: подменённая
        # перепись не имеет права двигать ни один другой ключ ответа.
        from unittest import mock

        from spa_core.paper_trading import shadow_trigger_eval as ste
        with TemporaryDirectory() as raw:
            tmp = Path(raw)
            self._scene(tmp)
            real = ste.evaluate_window(tmp, write=False, now=_NOW)
            with mock.patch(
                    "spa_core.paper_trading.trim_optimum.trim_optimum_census",
                    return_value={"kind": "подменено"}):
                patched = ste.evaluate_window(tmp, write=False, now=_NOW)
        self.assertNotEqual(real["trim_optimum_census"],
                            patched["trim_optimum_census"])
        self.assertEqual(
            json.dumps(dict(real, trim_optimum_census=None),
                       sort_keys=True, default=str),
            json.dumps(dict(patched, trim_optimum_census=None),
                       sort_keys=True, default=str))
        self.assertIn(real["status"], {"READY", "NOT_READY"})
        self.assertFalse(real["ready_to_arm"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
