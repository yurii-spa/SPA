"""ADR-861 — КРАЙ ОТРЕЗКА размеров: оптимум внутри подмножества или нет.

Каждый тест — положительный контроль на один из восьми дефектов, против
которых прибор написан:

1. **ПРИЧИНА 2 нижней границы ADR-859 осталась РАССУЖДЕНИЕМ.** ADR-859 взял
   НАИБОЛЬШИЙ допустимый размер хода и честно сказал: «монотонность
   окупаемости по размеру не доказана». Сцена ``WIN_*`` — настоящая запись
   истории 21.10, на которой размер НИЖЕ края даёт окупаемость ЛУЧШЕ: 169.22
   дн. против 170.82.
2. **приз, прочитанный как ЭКОНОМИКА, когда он создан ПЫЛЬНЫМ ПОРОГОМ.** Это
   главный тест файла. На всех восьми живых улучшениях книга скана несёт
   дельту $499.99 при пороге $500: ``_legs`` выбрасывает её и из газа, и из
   оборота, а ``_book_apy_pp`` её выигрыш считает — дверь цены отдаёт сумму
   БЕСПЛАТНО. Механизм проверяется У САМОЙ ДВЕРИ, а не на словах прибора.
3. **ось ПЛАТО, посчитанная по ЗАПРОШЕННОМУ размеру.** Первая редакция оси
   считала именно так и дала 36 записей из 87. Запрошенный размер выше суммы
   комнат ног даёт ТУ ЖЕ книгу, поэтому 36 было числом про потолок, а не про
   плато; по ФАКТИЧЕСКОМУ обороту книги ось равна НУЛЮ. Сцена ``PLATEAU_*`` —
   живая запись 29.10, воспроизводящая ровно эту ловушку: размеры $15 000 и
   $10 000, оборот у обеих $10 000.
4. **нижняя граница, названная оптимумом.** Край входит в кандидатов ВСЕГДА,
   поэтому скан не может ответить хуже ADR-859 — инвариант построения. А вот
   ПРИЧИНА 1 (раскладка фиксирована спредом) не закрыта, и притязание прибора
   обязано говорить это вслух.
5. **молча урезанный перебор.** Кандидатов больше потолка ⇒ названный исход с
   числом, а не тихо обрезанный список (инв. #17).
6. **«не измерено», выданное за ноль.** Блока нет в артефакте ⇒ исход
   ``unmeasured`` с причиной; населения нет ⇒ ``measured_zero``. Разные.
7. **структура, проверенная только рассуждением.** Вывод «минимум лежит на
   конце участка» проверяется ГУСТОЙ СЕТКОЙ: сетка обязана НЕ побить перебор
   концов.
8. **прибор без читателя.** Проводка проверяется НАСТОЯЩИМ ``evaluate_window``
   и НАСТОЯЩИМ шагом 0-офис, а не подстрокой в исходнике (урок #944/#945).

Сцены взяты из ЖИВОЙ истории предложений (замер 29.10) и вписаны литералами:
прибор обязан отвечать одинаково на любой машине, а чтение живого ``data/``
сделало бы тест зависимым от хоста.

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
from spa_core.paper_trading.trim_size_edge import (
    CENSUS_MEASURED,
    CENSUS_MEASURED_ZERO,
    CENSUS_UNMEASURED,
    MAX_CANDIDATES_PER_SUBSET,
    PROBE_DELTA_USD,
    SZ_MEASURED,
    SZ_NO_SUBJECT,
    SZ_SEARCH_TRUNCATED,
    SZ_STANDING_INADMISSIBLE,
    SZ_TIER_UNKNOWN,
    candidate_sizes,
    compare_trim_size_edge,
    dust_deltas,
    format_trim_size_edge,
    trim_size_edge_census,
    trim_size_edge_outcome,
)

_NOW = datetime(2026, 10, 29, 16, 40, tzinfo=timezone.utc)

#: Метка «ключа в сцене НЕТ» — отличима от значения `None`,
#: которое само является записанным наблюдением (инв. #17).
_DROP = object()

CAPITAL = 100_000.0
PARAMS = TriggerParams.for_mode("paper")

# ── сцена 1: размер НИЖЕ края лучше края (живая запись 2026-10-21) ───────────
# Край отрезка просит $15 000; бюджет перетекает за комнату `morpho_blue_base`
# ($10 000) в `aave_v3` и рождает ТРЕТЬЮ ногу. На $10 499.99 та же нога
# получает $499.99 — ниже порога $500, то есть становится ПЫЛЬЮ: дверь цены её
# не считает ни ногой, ни оборотом, а выигрыш в книге остаётся.
WIN_CURRENT = {"aave_v3": 5_000.0, "compound_v3": 40_000.0,
               "fluid_fusdc": 20_000.0, "maple": 20_000.0,
               "morpho_blue_base": 10_000.0}
WIN_TARGET = {"aave_v3": 40_000.0, "aave_v3_base": 10_000.0,
              "compound_v3": 5_000.0, "fluid_fusdc": 20_000.0,
              "morpho_blue_base": 20_000.0}
WIN_APY = {"aave_v3": 5.5724, "aave_v3_base": 5.4391, "compound_v3": 5.31,
           "fluid_fusdc": 5.45, "maple": 5.1904, "morpho_blue_base": 5.7278}
WIN_TIERS = {"aave_v3": "T1", "aave_v3_base": "T1", "compound_v3": "T1",
             "fluid_fusdc": "T2", "maple": "T2", "morpho_blue_base": "T2"}
WIN_CHAINS = {"aave_v3": "ethereum", "aave_v3_base": "base",
              "compound_v3": "ethereum", "fluid_fusdc": "ethereum",
              "maple": "ethereum", "morpho_blue_base": "base"}

# ── сцена 2: край ОПТИМАЛЕН, приза нет (сцена ADR-859, живая 29.10) ──────────
EDGE_CURRENT = {"compound_v3": 37_894.74, "fluid_usdc": 9_473.68,
                "maple": 18_947.37}
EDGE_TARGET = {"aave_v3": 22_105.26, "compound_v3": 37_894.74,
               "fluid_usdc": 9_473.68, "maple": 18_947.37,
               "morpho_blue_base": 6_578.95}
EDGE_APY = {"aave_v3": 3.2679, "compound_v3": 4.6852, "fluid_usdc": 4.7,
            "maple": 4.9719, "morpho_blue_base": 4.4246}
EDGE_TIERS = {"aave_v3": "T1", "compound_v3": "T1", "fluid_usdc": "T2",
              "maple": "T2", "morpho_blue_base": "T2"}
EDGE_CHAINS = {"aave_v3": "ethereum", "compound_v3": "ethereum",
               "fluid_usdc": "ethereum", "maple": "ethereum",
               "morpho_blue_base": "base"}

# ── сцена 3: ловушка оси ПЛАТО (живая запись 2026-10-29) ─────────────────────
# Размеры РАЗНЫЕ ($15 000 против $10 000), окупаемость ОДНА (80.16 дн.), а
# оборот у обеих книг ОДИН ($10 000): размер выше суммы комнат ног даёт ту же
# книгу. Ось, посчитанная по размеру, объявила бы здесь плато; по обороту — нет.
PLATEAU_CURRENT = {"aave_v3": 5_000.0, "compound_v3": 40_000.0,
                   "fluid_fusdc": 20_000.0, "maple": 20_000.0,
                   "morpho_blue_base": 10_000.0}
PLATEAU_TARGET = {"aave_v3": 5_000.0, "aave_v3_base": 10_000.0,
                  "compound_v3": 40_000.0, "fluid_fusdc": 20_000.0,
                  "morpho_blue_base": 20_000.0}
PLATEAU_APY = {"aave_v3": 4.1754, "aave_v3_base": 5.4321,
               "compound_v3": 4.3455, "fluid_fusdc": 6.27, "maple": 5.1011,
               "morpho_blue_base": 6.2463}
PLATEAU_TIERS = {"aave_v3": "T1", "aave_v3_base": "T2", "compound_v3": "T1",
                 "fluid_fusdc": "T2", "maple": "T2", "morpho_blue_base": "T2"}
PLATEAU_CHAINS = dict(WIN_CHAINS)

# ── сцена 4: день УЖЕ стоял вне политики ─────────────────────────────────────
STANDING_CURRENT = {"aave_v3": 5_000.0, "maple": 20_000.0,
                    "morpho_steakhouse": 40_000.0, "pendle": 20_000.0}
STANDING_TARGET = {"aave_v3": 40_000.0, "maple": 20_000.0,
                   "morpho_steakhouse": 5_000.0, "pendle": 20_000.0}
STANDING_APY = {"aave_v3": 4.9913, "maple": 4.961,
                "morpho_steakhouse": 3.4961, "pendle": 15.0957}
STANDING_TIERS = {"aave_v3": "T1", "maple": "T2", "morpho_steakhouse": "T2",
                  "pendle": "T2"}
STANDING_CHAINS = {k: "ethereum" for k in STANDING_TIERS}


def _one(current, target, apy, tiers, chains, grid_points=0):
    return compare_trim_size_edge(current, target, apy, capital_usd=CAPITAL,
                                  params=PARAMS, tiers=tiers, chains=chains,
                                  grid_points=grid_points)


def _win(grid_points=0):
    return _one(WIN_CURRENT, WIN_TARGET, WIN_APY, WIN_TIERS, WIN_CHAINS,
                grid_points=grid_points)


def _record(label, current, target, apy):
    return {"cycle_date": label, "capital_usd": CAPITAL,
            "current_positions": dict(current),
            "target_positions": dict(target),
            "apy_evidenced_pct": dict(apy)}


class TheEdgeIsTheOptimumOnceTheDustBandIsClosed(unittest.TestCase):
    """ПРИЧИНА 2 измерена до конца — и ответ оказался «улучшений нет».

    ⚠️ НАМЕРЕННОЕ ИЗМЕНЕНИЕ ТЕСТА (инв. #16, ADR-864; запись в
    `docs/journal/2026-W44.md`). Здесь стоял класс
    ``TheEdgeIsNotAlwaysTheOptimumInsideASubset`` с утверждением «размер ниже
    края БЬЁТ край на живой записи» (окупаемость 169.22 против 170.82). Это
    утверждение было ВЕРНЫМ замером НЕИСПРАВНОЙ двери и неверным утверждением
    о монотонности: приз создавался пыльной полосой — ``_legs`` выбрасывала
    подпороговую дельту из газа и оборота, а ставку книги считали ПО ОБЪЯВЛЕННОЙ
    цели, где эти деньги уже переложены. Перебор размеров сам сползал к
    ``min_leg_usd − $0.01``.

    ADR-864 заставил обе половины двери судить ОДНУ книгу: книга с
    неисполнимой ногой больше не считается (``trim_optimum.score_book`` → None).
    На ТОЙ ЖЕ записи приз исчез — ``scanned == edge_only``, — и это первый
    честный ответ про монотонность. Тест не ослаблен: он утверждает РОВНО то же
    про ту же сцену, только теперь его предмет — исход исправленной двери.
    Контроль обратной стороны (дверь снова отдаёт полосу бесплатно ⇒ приз
    возвращается) живёт в ``TheSourceAxisIsWiredToTheDustReading`` ниже.
    """

    def test_the_edge_is_not_beaten_on_the_live_record(self):
        one = _win()
        self.assertEqual(one["kind"], SZ_MEASURED)
        self.assertAlmostEqual(one["payback"]["edge_only"], 170.82, places=2)
        self.assertAlmostEqual(one["payback"]["scanned"], 170.82, places=2)
        self.assertEqual(one["payback"]["scanned"], one["payback"]["edge_only"],
                         "приз вернулся — дверь снова судит две книги")

    def test_the_scan_is_never_worse_than_the_edge_on_any_scene(self):
        """Инвариант ПОСТРОЕНИЯ: край входит в кандидатов на каждом подмножестве."""
        scenes = {
            "WIN": (WIN_CURRENT, WIN_TARGET, WIN_APY, WIN_TIERS, WIN_CHAINS),
            "EDGE": (EDGE_CURRENT, EDGE_TARGET, EDGE_APY, EDGE_TIERS,
                     EDGE_CHAINS),
            "PLATEAU": (PLATEAU_CURRENT, PLATEAU_TARGET, PLATEAU_APY,
                        PLATEAU_TIERS, PLATEAU_CHAINS),
        }
        for name, scene in scenes.items():
            with self.subTest(scene=name):
                one = _one(*scene)
                self.assertEqual(one["kind"], SZ_MEASURED)
                self.assertLessEqual(one["payback"]["scanned"],
                                     one["payback"]["edge_only"] + 1e-9)

    def test_a_scene_where_the_edge_is_optimal_yields_no_prize(self):
        """Контроль в ДРУГУЮ сторону: приз не берётся из воздуха."""
        one = _one(EDGE_CURRENT, EDGE_TARGET, EDGE_APY, EDGE_TIERS,
                   EDGE_CHAINS)
        self.assertEqual(one["kind"], SZ_MEASURED)
        self.assertAlmostEqual(one["payback"]["edge_only"], 17.87, places=2)
        self.assertAlmostEqual(one["payback"]["scanned"], 17.87, places=2)
        self.assertEqual(one["prize_dust_deltas"], {})


class ThePrizeIsTheDustBandNotEconomics(unittest.TestCase):
    """ЧЕМ создан приз, спрашивается ОТДЕЛЬНО — и после ADR-864 приза нет.

    ⚠️ НАМЕРЕННОЕ ИЗМЕНЕНИЕ ТЕСТОВ класса (инв. #16, ADR-864; запись в
    `docs/journal/2026-W44.md`). Три теста утверждали числа НЕИСПРАВНОЙ двери
    (победившая книга несёт дельту $499.99 · строго лучших 1 · пыльных 1).
    Все три перемеряны на ТЕХ ЖЕ сценах: дверь больше не считает книгу с
    неисполнимой ногой, поэтому победителя нет, и разложение приза стало
    ``0 = 0 + 0``. Ось при этом СОХРАНЕНА и по-прежнему обязана сходиться —
    она и есть то, что отличает «приза нет» от «приза не искали».
    """

    def test_the_winning_book_no_longer_carries_a_sub_dust_delta(self):
        one = _win()
        self.assertEqual(one["min_leg_usd"], 500.0)
        self.assertEqual(one["prize_dust_deltas"], {},
                         "книга с неисполнимой ногой снова побеждает")

    def test_the_cost_door_itself_charges_nothing_for_a_sub_dust_delta(self):
        """Механизм — У ДВЕРИ, а не на словах прибора.

        Это и есть причина, по которой приз ПРИЧИНЫ 2 не экономический: газа
        нет, оборота нет, а выигрыш в книге есть.
        """
        from spa_core.allocator.rebalance_economics import (_legs,
                                                            _move_cost_usd)
        from spa_core.paper_trading.trim_shape import _book_apy_pp

        current = {"aave_v3": 5_000.0, "compound_v3": 40_000.0}
        # Ровно на цент НИЖЕ порога $500 (min_leg_frac 0.005 × $100 000).
        book = {"aave_v3": 5_499.99, "compound_v3": 39_500.01}
        apy = {"aave_v3": 5.5724, "compound_v3": 5.31}
        chains = {"aave_v3": "ethereum", "compound_v3": "ethereum"}
        legs, turnover = _legs(current, book, CAPITAL, 0.005)
        self.assertEqual(legs, [], "подпороговая нога попала в ноги")
        self.assertEqual(turnover, 0.0, "подпороговая нога попала в оборот")
        self.assertEqual(_move_cost_usd(legs, turnover, chains), 0.0)
        # А выигрыш — есть, и он положителен: дверь отдала его БЕСПЛАТНО.
        gain = (_book_apy_pp(book, apy, CAPITAL)
                - _book_apy_pp(current, apy, CAPITAL))
        self.assertGreater(gain, 0.0)

    def test_the_census_names_the_source_of_every_prize(self):
        census = trim_size_edge_census(
            [_record("день-1", WIN_CURRENT, WIN_TARGET, WIN_APY)],
            params=PARAMS, tiers=WIN_TIERS, tiers_measured=True,
            chains=WIN_CHAINS, chains_measured=True,
            grid_control_records=0)
        src = census["prize_source"]
        self.assertEqual(src["strictly_better"], 0)
        self.assertEqual(src["from_dust_band"], 0)
        self.assertEqual(src["economic"], 0,
                         "экономический приз объявлен там, где его нет")
        # Части сходятся с целым и при нуле: это ЗАМЕР нуля, а не пустота.
        self.assertEqual(src["from_dust_band"] + src["economic"],
                         src["strictly_better"])
        self.assertIn("ПЫЛЬНЫМ ПОРОГОМ", src["note"])
        self.assertIn("ИСТОЧНИК приза", "\n".join(
            format_trim_size_edge(census)))

    def test_the_source_axis_is_wired_to_the_dust_reading_not_to_the_count(self):
        """Дыра, вскрытая мутацией #978: ось источника без фильтра.

        На живом населении все улучшения ПЫЛЬНЫЕ, поэтому «фильтр снят» и
        «фильтр работает» дают одно число — населения, различающего их, в
        истории нет вовсе. Различает ДВЕРЬ: подменим чтение полосы пустым
        ответом, и то же улучшение обязано стать ЭКОНОМИЧЕСКИМ.

        ⚠️ ADR-864 добавил ВТОРУЮ подмену, и без неё тест перестал мерить свой
        предмет: после починки победителя на этой сцене нет вовсе (книга с
        неисполнимой ногой не считается), поэтому «ось без фильтра» и «ось с
        фильтром» снова дали бы одно число — ноль. Подменяются обе двери, то
        есть сцена ВОЗВРАЩАЕТСЯ к поведению до ADR-864, и ось обязана назвать
        тот же приз ЭКОНОМИЧЕСКИМ. Это и есть обратный контроль самой починки.
        """
        from unittest import mock
        from spa_core.allocator import rebalance_economics as _re
        with mock.patch("spa_core.paper_trading.trim_size_edge.dust_deltas",
                        return_value={}), \
             mock.patch.object(_re, "unexecuted_legs", return_value={}):
            census = trim_size_edge_census(
                [_record("день-1", WIN_CURRENT, WIN_TARGET, WIN_APY)],
                params=PARAMS, tiers=WIN_TIERS, tiers_measured=True,
                chains=WIN_CHAINS, chains_measured=True,
                grid_control_records=0)
        src = census["prize_source"]
        self.assertEqual(src["strictly_better"], 1)
        self.assertEqual(src["from_dust_band"], 0)
        self.assertEqual(src["economic"], 1)

    def test_dust_deltas_reads_the_band_and_not_the_whole_move(self):
        band = dust_deltas({"a": 1_000.0, "b": 1_000.0},
                           {"a": 1_400.0, "b": 2_000.0}, 500.0)
        self.assertEqual(band, {"a": 400.0})     # 400 ≤ 500 — пыль
        self.assertNotIn("b", band)              # 1000 > 500 — настоящая нога
        # Точно на пороге дельта ещё ПЫЛЬ: дверь `_legs` отсекает нестрого.
        self.assertEqual(dust_deltas({"a": 0.0}, {"a": 500.0}, 500.0),
                         {"a": 500.0})
        # Нулевая дельта — не пыль, а отсутствие хода.
        self.assertEqual(dust_deltas({"a": 500.0}, {"a": 500.0}, 500.0), {})


class TheCandidateDoorRefusesAnUnknownTier(unittest.TestCase):
    """Дыра, вскрытая мутацией #978: `is not True` против `is False`.

    На пути переписи неизвестный тир отсекается раньше (``compare_*`` судит
    стоящую книгу, ``_largest_admissible_turnover`` спрашивает ``is True``),
    поэтому населения у этой двери в истории нет. Но ``scan_subset`` —
    САМОСТОЯТЕЛЬНАЯ функция, и её контракт обязан держаться сам: сомнение
    трактуется в пользу ОТКАЗА (ADR-359), а не в пользу хода.
    """

    def test_a_book_with_an_unknown_tier_yields_no_candidate(self):
        from spa_core.paper_trading.trim_size_edge import scan_subset
        tiers_without = {k: v for k, v in WIN_TIERS.items()
                         if k != "aave_v3_base"}
        scan = scan_subset(WIN_CURRENT,
                           [["aave_v3_base", 10_000.0]],
                           [["maple", 20_000.0]],
                           edge=10_000.0, net_cash_usd=0.0,
                           apy_pct=WIN_APY, capital_usd=CAPITAL,
                           min_leg_frac=0.005, tiers=tiers_without,
                           chains=WIN_CHAINS)
        self.assertEqual(scan["kind"], SZ_MEASURED)
        self.assertIsNone(scan["best"],
                          "книга с неизвестным тиром прошла как допустимая")
        # Контроль в ДРУГУЮ сторону: с полным реестром кандидат находится.
        scan_ok = scan_subset(WIN_CURRENT,
                              [["aave_v3_base", 10_000.0]],
                              [["maple", 20_000.0]],
                              edge=10_000.0, net_cash_usd=0.0,
                              apy_pct=WIN_APY, capital_usd=CAPITAL,
                              min_leg_frac=0.005, tiers=WIN_TIERS,
                              chains=WIN_CHAINS)
        self.assertIsNotNone(scan_ok["best"])


class ThePlateauAxisIsMeasuredOnTurnoverNotOnRequestedSize(unittest.TestCase):
    """Дефект 3: воспроизведение СВОЕЙ ЖЕ ошибки замера (36 против 0)."""

    def test_the_same_book_at_two_requested_sizes_is_not_a_plateau(self):
        one = _one(PLATEAU_CURRENT, PLATEAU_TARGET, PLATEAU_APY,
                   PLATEAU_TIERS, PLATEAU_CHAINS)
        self.assertEqual(one["kind"], SZ_MEASURED)
        # Размеры РАЗНЫЕ…
        self.assertNotAlmostEqual(one["size_usd"]["edge_only"],
                                  one["size_usd"]["scanned"], places=2)
        # …окупаемость ОДНА…
        self.assertAlmostEqual(one["payback"]["edge_only"],
                               one["payback"]["scanned"], places=2)
        # …а оборот книги РАЗЛИЧАЕТСЯ не более чем на квант книги (цент):
        # книга та же, и «меньший размер» был числом про потолок.
        self.assertGreater(abs(one["size_usd"]["edge_only"]
                               - one["size_usd"]["scanned"]), 1_000.0)
        self.assertLessEqual(abs(one["turnover_usd"]["edge_only"]
                                 - one["turnover_usd"]["scanned"]),
                             PROBE_DELTA_USD + 1e-9)

    def test_the_census_counts_no_plateau_on_that_record(self):
        census = trim_size_edge_census(
            [_record("день-1", PLATEAU_CURRENT, PLATEAU_TARGET, PLATEAU_APY)],
            params=PARAMS, tiers=PLATEAU_TIERS, tiers_measured=True,
            chains=PLATEAU_CHAINS, chains_measured=True,
            grid_control_records=0)
        self.assertEqual(census["plateau_same_payback_smaller_size"], 0)
        self.assertIsNone(census["plateau_median_size_cut_usd"])
        printed = "\n".join(format_trim_size_edge(census))
        # «Нет числа» обязано звучать ЗАМЕРОМ НУЛЯ, а не пустотой.
        self.assertIn("ЗАМЕР нуля", printed)


class EveryCandidateListIsHonest(unittest.TestCase):
    """Дефекты 4–5: край в кандидатах всегда; усечение НАЗВАНО."""

    def test_the_edge_is_always_a_candidate(self):
        inc = [["a", 10_000.0], ["b", 10_000.0]]
        dec = [["c", 20_000.0]]
        sizes, why = candidate_sizes(inc, dec, edge=15_000.0,
                                     net_cash_usd=0.0, min_leg_usd=500.0)
        self.assertIsNotNone(sizes)
        self.assertIn(15_000.0, sizes)
        self.assertTrue(all(0.0 < s <= 15_000.0 + 1e-9 for s in sizes))
        self.assertIn("кандидатов", why)

    def test_both_sides_of_every_breakpoint_are_probed(self):
        """Порог принадлежит НИЖНЕМУ участку — значит нужны оба соседа."""
        sizes, _why = candidate_sizes([["a", 10_000.0]], [["c", 20_000.0]],
                                      edge=10_000.0, net_cash_usd=0.0,
                                      min_leg_usd=500.0)
        assert sizes is not None
        self.assertIn(round(500.0 - PROBE_DELTA_USD, 2), sizes)
        self.assertIn(round(500.0 + PROBE_DELTA_USD, 2), sizes)
        # И оба конца участка «нога наполнилась» — тоже оба.
        self.assertIn(round(10_000.0 - PROBE_DELTA_USD, 2), sizes)
        self.assertIn(10_000.0, sizes)

    def test_the_edge_stays_a_candidate_even_when_the_rooms_saturate_earlier(self):
        """Дыра, вскрытая мутацией #978: `ceiling` ≠ `edge`, и подмена молчит.

        Выше суммы комнат ног книга не меняется, поэтому ОТВЕТ (окупаемость)
        от подмены «край → насыщение» не страдает, а вот ОБЪЯВЛЕННЫЙ размер и
        притязание «край входит в кандидатов ВСЕГДА» — страдают. Сцена ровно
        такая: комнаты покупки $5 000, край отрезка $15 000.
        """
        sizes, _why = candidate_sizes([["a", 5_000.0]], [["c", 20_000.0]],
                                      edge=15_000.0, net_cash_usd=0.0,
                                      min_leg_usd=500.0)
        assert sizes is not None
        self.assertIn(15_000.0, sizes)
        self.assertIn(5_000.0, sizes)   # и само насыщение — тоже кандидат

    def test_too_many_candidates_is_a_named_outcome_not_a_cut_list(self):
        inc = [[f"p{i}", 100.0] for i in range(MAX_CANDIDATES_PER_SUBSET)]
        sizes, why = candidate_sizes(inc, [["c", 1e9]],
                                     edge=1e9, net_cash_usd=0.0,
                                     min_leg_usd=1.0)
        self.assertIsNone(sizes)
        self.assertIn("потолке", why)
        self.assertIn(str(MAX_CANDIDATES_PER_SUBSET), why)

    def test_the_claim_still_names_reason_one_as_open(self):
        one = _win()
        self.assertIn("ПРИЧИНА 1", one["claim"])
        self.assertIn("money-path", one["claim"])


class EveryOutcomeIsAValue(unittest.TestCase):
    """Дефект 6: «не измерено» ≠ ноль ≠ отказ (инв. #17)."""

    def test_a_proposal_inside_the_ceiling_has_no_subject(self):
        one = _one({"aave_v3": 50_000.0}, {"aave_v3": 50_100.0},
                   {"aave_v3": 4.0}, {"aave_v3": "T1"},
                   {"aave_v3": "ethereum"})
        self.assertEqual(one["kind"], SZ_NO_SUBJECT)
        self.assertTrue(one["why"])

    def test_a_day_already_outside_policy_is_its_own_outcome(self):
        one = _one(STANDING_CURRENT, STANDING_TARGET, STANDING_APY,
                   STANDING_TIERS, STANDING_CHAINS)
        self.assertEqual(one["kind"], SZ_STANDING_INADMISSIBLE)

    def test_an_unknown_tier_is_a_refusal_not_a_substituted_tier(self):
        one = _one(WIN_CURRENT, WIN_TARGET, WIN_APY, {}, WIN_CHAINS)
        self.assertEqual(one["kind"], SZ_TIER_UNKNOWN)
        self.assertIn("ADR-359", one["why"])

    def test_a_history_that_is_not_a_list_is_unmeasured(self):
        census = trim_size_edge_census("не список", params=PARAMS,
                                       tiers=WIN_TIERS, tiers_measured=True,
                                       chains=WIN_CHAINS, chains_measured=True)
        self.assertEqual(census["kind"], CENSUS_UNMEASURED)

    def test_an_unread_registry_is_unmeasured_not_an_empty_answer(self):
        census = trim_size_edge_census(
            [_record("день-1", WIN_CURRENT, WIN_TARGET, WIN_APY)],
            params=PARAMS, tiers={}, tiers_measured=False,
            chains=WIN_CHAINS, chains_measured=True)
        self.assertEqual(census["kind"], CENSUS_UNMEASURED)
        self.assertIn("ADR-359", census["why"])

    def test_no_comparable_proposal_is_a_measured_zero(self):
        census = trim_size_edge_census(
            [_record("день-1", {"aave_v3": 50_000.0}, {"aave_v3": 50_100.0},
                     {"aave_v3": 4.0})],
            params=PARAMS, tiers={"aave_v3": "T1"}, tiers_measured=True,
            chains={"aave_v3": "ethereum"}, chains_measured=True)
        self.assertEqual(census["kind"], CENSUS_MEASURED_ZERO)
        kind, why = trim_size_edge_outcome(census)
        self.assertEqual(kind, CENSUS_MEASURED_ZERO)
        self.assertTrue(why)

    def test_a_missing_block_is_unmeasured_with_a_reason(self):
        for empty in (None, {}, {"kind": "чего-то новенького"}):
            with self.subTest(block=empty):
                kind, why = trim_size_edge_outcome(empty)
                self.assertEqual(kind, CENSUS_UNMEASURED)
                self.assertTrue(why)


class TheStructuralClaimIsCheckedByADenseGrid(unittest.TestCase):
    """Дефект 7: «минимум на конце участка» проверяется ЗАМЕРОМ."""

    def test_the_grid_never_beats_the_breakpoint_enumeration(self):
        for name, scene in (("WIN", (WIN_CURRENT, WIN_TARGET, WIN_APY,
                                     WIN_TIERS, WIN_CHAINS)),
                            ("EDGE", (EDGE_CURRENT, EDGE_TARGET, EDGE_APY,
                                      EDGE_TIERS, EDGE_CHAINS))):
            with self.subTest(scene=name):
                one = _one(*scene, grid_points=64)
                self.assertEqual(one["kind"], SZ_MEASURED)
                self.assertEqual(one["grid_beats_breakpoints"], 0)
                self.assertEqual(one["grid_points"], 64)

    def test_the_census_publishes_the_control_and_its_sample_size(self):
        census = trim_size_edge_census(
            [_record("день-1", WIN_CURRENT, WIN_TARGET, WIN_APY)],
            params=PARAMS, tiers=WIN_TIERS, tiers_measured=True,
            chains=WIN_CHAINS, chains_measured=True,
            grid_control_records=1, grid_points=32)
        ctl = census["grid_control"]
        self.assertEqual(ctl["records_checked"], 1)
        self.assertEqual(ctl["points_per_subset"], 32)
        self.assertEqual(ctl["grid_beats_breakpoints"], 0)
        self.assertIn("КОНТРОЛЬ структуры", "\n".join(
            format_trim_size_edge(census)))


class TheCensusIsWiredIntoTheArtifactNotJustWritten(unittest.TestCase):
    """Дефект 8: прибор без читателя — сирота (ADR-843)."""

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
                "current_positions": dict(WIN_CURRENT),
                "target_positions": dict(WIN_TARGET),
                "apy_evidenced_pct": dict(WIN_APY),
            })
        (tmp / "allocation_rationale_history.jsonl").write_text(
            "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
        (tmp / "adapter_registry.json").write_text(json.dumps({
            "adapters": {k: {"tier": t, "chain": WIN_CHAINS[k]}
                         for k, t in WIN_TIERS.items()}}), encoding="utf-8")

    def test_evaluate_window_carries_the_block_and_format_summary_prints_it(self):
        from spa_core.paper_trading.shadow_trigger_eval import (evaluate_window,
                                                                format_summary)
        with TemporaryDirectory() as raw:
            tmp = Path(raw)
            self._scene(tmp)
            doc = evaluate_window(tmp, write=False, now=_NOW)
        self.assertIn("trim_size_edge_census", doc)
        kind, why = trim_size_edge_outcome(doc["trim_size_edge_census"])
        self.assertEqual(kind, CENSUS_MEASURED, why)
        self.assertEqual(doc["trim_size_edge_census"]["population"], 6)
        self.assertIn("цена ПРИЧИНЫ 2", format_summary(doc))

    def test_the_office_step_declares_the_block_in_its_read_schema(self):
        """Необъявленное чтение молча становится `None` — класс ADR-855."""
        import importlib
        office = importlib.import_module("scripts.consume_office_reports")
        declared = office._READ_SCHEMA["shadow_trigger_evaluation.json"]
        self.assertIn("trim_size_edge_census", declared)

    def test_the_office_step_prints_the_block_through_the_same_printer(self):
        # Не подстрока в исходнике, а НАСТОЯЩИЙ вызов выжимки шага 0-офис.
        import importlib
        office = importlib.import_module("scripts.consume_office_reports")
        census = trim_size_edge_census(
            [_record("день-1", WIN_CURRENT, WIN_TARGET, WIN_APY)],
            params=PARAMS, tiers=WIN_TIERS, tiers_measured=True,
            chains=WIN_CHAINS, chains_measured=True, grid_control_records=0)
        doc = {"status": "NOT_READY", "ready_to_arm": False,
               "observation_days": 1, "generated_at": _NOW.isoformat(),
               "trim_size_edge_census": census}
        text = "\n".join(
            office._summarize_json("shadow_trigger_evaluation.json", doc))
        self.assertIn("цена ПРИЧИНЫ 2", text)
        self.assertIn("ИСТОЧНИК приза", text)

    def test_an_artifact_without_the_block_is_named_not_silently_zero(self):
        """Отрицательный контроль: запись СТАРШЕ прибора звучит, а не молчит."""
        import importlib
        office = importlib.import_module("scripts.consume_office_reports")
        text = "\n".join(office._summarize_json(
            "shadow_trigger_evaluation.json",
            {"status": "NOT_READY", "ready_to_arm": False,
             "observation_days": 1, "generated_at": _NOW.isoformat()}))
        self.assertIn("цена ПРИЧИНЫ 2", text)
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
                    "spa_core.paper_trading.trim_size_edge."
                    "trim_size_edge_census",
                    return_value={"kind": "подменено"}):
                patched = ste.evaluate_window(tmp, write=False, now=_NOW)
        self.assertNotEqual(real["trim_size_edge_census"],
                            patched["trim_size_edge_census"])
        self.assertEqual(
            json.dumps(dict(real, trim_size_edge_census=None),
                       sort_keys=True, default=str),
            json.dumps(dict(patched, trim_size_edge_census=None),
                       sort_keys=True, default=str))
        self.assertIn(real["status"], {"READY", "NOT_READY"})
        self.assertFalse(real["ready_to_arm"])


class TheAcceptanceProbeHasAControlInBothDirections(unittest.TestCase):
    """Правило приёмки, п. 3: зелена на ЦЕЛОМ контуре, красна на КАЖДОМ рваном.

    Проба меряет ИСХОД (артефакт несёт разложенный приз), а не структуру, и
    НЕ проходит подстрокой — последний тест класса ровно об этом.
    """

    def _census(self):
        return trim_size_edge_census(
            [_record("2026-10-21", WIN_CURRENT, WIN_TARGET, WIN_APY)],
            params=PARAMS, tiers=WIN_TIERS, tiers_measured=True,
            chains=WIN_CHAINS, chains_measured=True, grid_control_records=0)

    def _artifact(self, tmp: Path, **over) -> None:
        doc = {"status": "NOT_READY", "ready_to_arm": False,
               "observation_days": 1,
               "generated_at": (_NOW - timedelta(hours=1)).isoformat(),
               "trim_size_edge_census": self._census()}
        doc.update(over)
        for key in [k for k, v in over.items() if v is _DROP]:
            doc.pop(key, None)
        (tmp / "shadow_trigger_evaluation.json").write_text(
            json.dumps(doc, default=str), encoding="utf-8")

    def _ask(self, tmp: Path):
        from spa_core.monitoring.card_acceptance import PROBES
        fn = PROBES["size_edge_prize_source_is_named"]
        return fn(None, now=_NOW, data_dir=str(tmp))

    def test_the_whole_circuit_is_satisfied(self):
        from spa_core.monitoring.card_acceptance import SATISFIED
        with TemporaryDirectory() as raw:
            tmp = Path(raw)
            self._artifact(tmp)
            verdict, why = self._ask(tmp)
        self.assertEqual(verdict, SATISFIED, why)
        self.assertIn("пыльный порог", why)

    def test_a_missing_artifact_is_unmeasured_not_a_refusal(self):
        from spa_core.monitoring.card_acceptance import UNMEASURED
        with TemporaryDirectory() as raw:
            verdict, why = self._ask(Path(raw))
        self.assertEqual(verdict, UNMEASURED)
        self.assertIn("не прочитан", why)

    def test_a_stale_artifact_is_unmeasured_with_its_age(self):
        from spa_core.monitoring.card_acceptance import UNMEASURED
        with TemporaryDirectory() as raw:
            tmp = Path(raw)
            self._artifact(tmp, generated_at=(_NOW - timedelta(hours=99)
                                              ).isoformat())
            verdict, why = self._ask(tmp)
        self.assertEqual(verdict, UNMEASURED)
        self.assertIn("протух", why)

    def test_an_artifact_older_than_the_instrument_is_unmeasured(self):
        from spa_core.monitoring.card_acceptance import UNMEASURED
        with TemporaryDirectory() as raw:
            tmp = Path(raw)
            self._artifact(tmp, trim_size_edge_census=_DROP)
            verdict, why = self._ask(tmp)
        self.assertEqual(verdict, UNMEASURED)
        self.assertIn(CENSUS_UNMEASURED, why)

    def test_a_measured_block_without_the_source_axis_is_refused(self):
        from spa_core.monitoring.card_acceptance import NOT_SATISFIED
        census = dict(self._census())
        census.pop("prize_source")
        with TemporaryDirectory() as raw:
            tmp = Path(raw)
            self._artifact(tmp, trim_size_edge_census=census)
            verdict, why = self._ask(tmp)
        self.assertEqual(verdict, NOT_SATISFIED)
        self.assertIn("ИСТОЧНИКА", why)

    def test_parts_that_do_not_add_up_to_the_whole_are_refused(self):
        from spa_core.monitoring.card_acceptance import NOT_SATISFIED
        # Сцена строится так, чтобы части НЕ СХОДИЛИСЬ: целое объявлено
        # единицей, части — нулями. До ADR-864 то же состояние получалось
        # обнулением частей (целое тогда было 1 само); теперь целое ноль, и
        # обнуление частей дало бы СХОДЯЩУЮСЯ сцену, то есть контроль молча
        # перестал бы рвать звено. Предмет контроля не менялся.
        census = dict(self._census())
        census["prize_source"] = dict(census["prize_source"],
                                      strictly_better=1,
                                      from_dust_band=0, economic=0)
        with TemporaryDirectory() as raw:
            tmp = Path(raw)
            self._artifact(tmp, trim_size_edge_census=census)
            verdict, why = self._ask(tmp)
        self.assertEqual(verdict, NOT_SATISFIED)
        self.assertIn("не сходятся", why)

    def test_the_probe_does_not_pass_on_a_substring(self):
        """ADR-333: проба обязана мерить ИСХОД, а не присутствие слов."""
        from spa_core.monitoring.card_acceptance import (NOT_SATISFIED,
                                                         SATISFIED, UNMEASURED)
        prose = ("prize_source: strictly_better 8, from_dust_band 8, "
                 "economic 0 — ИСТОЧНИК приза назван, kind=measured")
        with TemporaryDirectory() as raw:
            tmp = Path(raw)
            self._artifact(tmp, trim_size_edge_census=prose)
            verdict, why = self._ask(tmp)
        self.assertNotEqual(verdict, SATISFIED, why)
        self.assertIn(verdict, {UNMEASURED, NOT_SATISFIED})

    def test_an_argument_is_refused_because_the_criterion_is_whole(self):
        from spa_core.monitoring.card_acceptance import PROBES, UNMEASURED
        verdict, why = PROBES["size_edge_prize_source_is_named"]("что-нибудь")
        self.assertEqual(verdict, UNMEASURED)
        self.assertIn("не принимает аргумента", why)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
