"""Сторож прибора «цена операции, которой не было» (ADR-390, заказ #609/G22).

Каждый тест здесь — контроль В ОБЕ СТОРОНЫ: он обязан не только зеленеть на
целом контуре, но и краснеть на НАЗВАННОМ порванном звене. Проверка, никогда не
видевшая настоящей поломки, — украшение (`.claude/rules/deployment.md`).

Время и личность процесса здесь не при чём: прибор не судит о свежести и не
спрашивает ОС о номерах. Литеральных дат в фикстурах нет вовсе — даты journal
суть КЛЮЧИ строк, а не отметки свежести, и сдвиг календаря их не трогает.
"""
# FROZEN-DATE-OK: даты в фикстурах — ключи строк журнала (`cycle_date`), а не
# отметки свежести: ни одна проверка прибора не сравнивает их с часами.
from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from spa_core.monitoring import swap_existence_price as sep


def _legs(*pairs):
    return [{"protocol": p, "delta_usd": d,
             "direction": "increase" if d > 0 else "decrease"} for p, d in pairs]


#: Карта активов для фикстур. Строится ЯВНО, а не берётся у живого реестра:
#: тест про арифметику границ не должен краснеть от того, что кто-то завёл
#: новый адаптер.
def _assets(**kw):
    return {k: ({"asset": v, "state": "resolved", "routes": {"fixture": v}}
                if v else {"asset": None, "state": "unknown", "routes": {}})
            for k, v in kw.items()}


class AssetMapTest(unittest.TestCase):
    """Актив ноги берётся тождеством кода, а не видом имени."""

    def test_resolves_the_money_path_key_through_class_identity(self):
        amap, ctx = sep.asset_map()
        self.assertTrue(ctx["measured"])
        # `aave_v3` (ключ денежного пути) и `aave_usdc` (ключ метаданных) —
        # РАЗНЫЕ имена одного класса. Сведение по виду имени дало бы промах.
        self.assertEqual(amap["aave_v3"]["state"], "resolved")
        self.assertEqual(amap["aave_v3"]["asset"], "USDC")
        self.assertIn("metadata_by_class", amap["aave_v3"]["routes"])
        self.assertEqual(amap["aave_v3"]["metadata_twins"], ["aave_usdc"])

    def test_the_two_routes_are_complementary_and_that_is_measured(self):
        """«Дорог две» — замер, а не украшение: вторая добывает то, что первая нет."""
        amap, ctx = sep.asset_map()
        only_attr = ctx["resolved_by_class_attribute_only"]
        self.assertTrue(
            only_attr,
            "вторая дорога не добыла НИ ОДНОГО ключа — тогда она не дорога")
        # `fluid_usdc` первой дорогой не берётся: в метаданных под этим именем
        # объявлен ДРУГОЙ модуль, и тождество классов честно отказывает.
        self.assertIn("fluid_usdc", only_attr)
        self.assertEqual(amap["fluid_usdc"]["asset"], "USDC")
        self.assertNotIn("metadata_by_class", amap["fluid_usdc"]["routes"])

    def test_pendle_is_not_the_portfolio_asset(self):
        """Весь ответ (а) держится на том, что PT-USDC ≠ USDC."""
        amap, _ = sep.asset_map()
        self.assertEqual(amap["pendle"]["asset"], "PT-USDC")
        self.assertNotEqual(amap["pendle"]["asset"], amap["aave_v3"]["asset"])

    def test_an_unregistered_key_stays_unknown_and_is_never_guessed(self):
        amap, ctx = sep.asset_map()
        self.assertEqual(amap["morpho_blue_base"]["state"], "unknown")
        self.assertIsNone(amap["morpho_blue_base"]["asset"])
        self.assertGreater(ctx["unknown"], 0)


class SwapShareTest(unittest.TestCase):
    """Границы доли свопа: арифметика и три исхода."""

    A = _assets(aave="USDC", comp="USDC", pendle="PT-USDC",
                fluid="USDC", dark=None)

    def test_same_asset_move_needs_no_swap_and_the_answer_is_exact(self):
        out = sep.swap_share(_legs(("aave", 35000.0), ("comp", -35000.0)),
                             35000.0, self.A, "USDC")
        self.assertTrue(out["measured"])
        self.assertEqual(out["swap_usd_min"], 0.0)
        self.assertEqual(out["swap_usd_max"], 0.0)
        self.assertTrue(out["exact"])
        self.assertTrue(out["all_assets_known"])

    def test_a_real_conversion_is_charged_in_full(self):
        out = sep.swap_share(_legs(("pendle", 20000.0), ("comp", -20000.0)),
                             20000.0, self.A, "USDC")
        self.assertEqual(out["swap_usd_min"], 20000.0)
        self.assertEqual(out["swap_usd_max"], 20000.0)
        self.assertTrue(out["exact"])

    def test_a_mixed_day_splits_and_the_bounds_still_coincide(self):
        """Своп = ровно нога смены актива, когда все активы известны."""
        out = sep.swap_share(
            _legs(("aave", 35000.0), ("pendle", 20000.0), ("comp", -55000.0)),
            55000.0, self.A, "USDC")
        self.assertEqual(out["swap_usd_min"], 20000.0)
        self.assertEqual(out["swap_usd_max"], 20000.0)
        self.assertTrue(out["exact"])

    def test_an_unknown_leg_WIDENS_the_bounds_instead_of_being_guessed(self):
        """Порванное звено: тот же день, но актив одной ноги не объявлен."""
        legs = _legs(("aave", 35000.0), ("pendle", 20000.0), ("comp", -35000.0),
                     ("dark", -20000.0))
        known = sep.swap_share(
            legs, 55000.0,
            _assets(aave="USDC", comp="USDC", pendle="PT-USDC", dark="USDC"),
            "USDC")
        unknown = sep.swap_share(legs, 55000.0, self.A, "USDC")
        self.assertTrue(known["exact"])
        self.assertFalse(unknown["exact"],
                         "неизвестная нога обязана РАЗДВИНУТЬ границы, а не "
                         "подставить актив")
        self.assertLessEqual(unknown["swap_usd_min"], known["swap_usd_min"])
        self.assertGreaterEqual(unknown["swap_usd_max"], known["swap_usd_max"])
        self.assertFalse(unknown["all_assets_known"])
        self.assertEqual(unknown["unknown_keys"], ["dark"])
        self.assertIsNotNone(unknown["relaxation"])

    def test_the_true_answer_lies_inside_the_bounds(self):
        """Границы обязаны СОДЕРЖАТЬ ответ, иначе они не границы."""
        # Форма дня 2026-09-03 живого журнала: отток 60к, приток 55к, разница
        # в кэш; одна нога с необъявленным активом.
        legs = _legs(("aave", 35000.0), ("pendle", 20000.0), ("comp", -40000.0),
                     ("dark", -10000.0), ("fluid", -10000.0))
        unknown = sep.swap_share(legs, 60000.0, self.A, "USDC")
        self.assertTrue(unknown["measured"], unknown.get("reason"))
        for guess in ("USDC", "PT-USDC"):
            truth = sep.swap_share(
                legs, 60000.0,
                _assets(aave="USDC", comp="USDC", pendle="PT-USDC",
                        fluid="USDC", dark=guess),
                "USDC")
            self.assertGreaterEqual(truth["swap_usd_min"], unknown["swap_usd_min"] - 0.01)
            self.assertLessEqual(truth["swap_usd_max"], unknown["swap_usd_max"] + 0.01)

    def test_the_imbalance_is_closed_by_cash_with_its_declared_asset(self):
        """Отток больше притока ⇒ разница ушла в кэш, и своп там не нужен."""
        out = sep.swap_share(_legs(("comp", -35000.0), ("aave", 20000.0)),
                             35000.0, self.A, "USDC")
        self.assertEqual(out["swap_usd_min"], 0.0)
        self.assertEqual(out["assets_in"]["USDC"], 35000.0)

    def test_cash_in_a_foreign_asset_makes_the_same_day_a_swap(self):
        """Порванное звено: кэш объявлен НЕ тем активом — ответ обязан измениться."""
        legs = _legs(("comp", -35000.0), ("aave", 20000.0))
        usdc = sep.swap_share(legs, 35000.0, self.A, "USDC")
        other = sep.swap_share(legs, 35000.0, self.A, "PT-USDC")
        self.assertEqual(usdc["swap_usd_min"], 0.0)
        self.assertEqual(other["swap_usd_min"], 15000.0)

    def test_cash_asset_absent_refuses_the_day(self):
        out = sep.swap_share(_legs(("aave", 1.0), ("comp", -1.0)), 1.0,
                             self.A, None)
        self.assertFalse(out["measured"])
        self.assertEqual(out["reason"], "cash_asset_unknown")

    def test_legs_disagreeing_with_turnover_is_a_third_outcome(self):
        """Два производителя хода спорят ⇒ знаменатель брать нельзя."""
        out = sep.swap_share(_legs(("aave", 100.0), ("comp", -100.0)),
                             999.0, self.A, "USDC")
        self.assertFalse(out["measured"])
        self.assertTrue(str(out["reason"]).startswith("flow_disagrees_with_turnover"))

    def test_an_unreadable_delta_refuses_instead_of_counting_zero(self):
        out = sep.swap_share([{"protocol": "aave", "delta_usd": "нет"}],
                             1.0, self.A, "USDC")
        self.assertFalse(out["measured"])
        self.assertEqual(out["reason"], "leg_delta_unreadable:aave")


class CashAssetTest(unittest.TestCase):
    def test_reads_the_declared_owner_not_a_hardcoded_dollar(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "capital_config.json").write_text(
                json.dumps({"capital": {"currency": "EURC"}}), encoding="utf-8")
            value, source = sep.cash_asset(Path(td))
        self.assertEqual(value, "EURC")
        self.assertIn("capital_config.json", source)

    def test_missing_file_is_named_not_defaulted(self):
        with tempfile.TemporaryDirectory() as td:
            value, source = sep.cash_asset(Path(td))
        self.assertIsNone(value)
        self.assertIn("НЕ ПРОЧИТАН", source)

    def test_empty_currency_is_named_not_defaulted(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "capital_config.json").write_text(
                json.dumps({"capital": {}}), encoding="utf-8")
            value, source = sep.cash_asset(Path(td))
        self.assertIsNone(value)
        self.assertIn("НЕ ОБЪЯВЛЕН", source)


class ReliefMutationTest(unittest.TestCase):
    """Записанный ноль судья прочтёт как ОТСУТСТВИЕ — и прибор его не пишет."""

    def test_a_relief_that_would_zero_the_price_is_refused_and_named(self):
        refused: set = set()
        mutate = sep._charge_swap_only({"d1": 100.0}, refused)
        rec = {"cycle_date": "d1", "cost_usd": 100.0, "turnover_usd": 1000.0}
        mutate(rec)
        self.assertEqual(rec["cost_usd"], 100.0, "цена обязана остаться записанной")
        self.assertEqual(refused, {"d1"})

    def test_a_normal_relief_is_applied(self):
        refused: set = set()
        sep._charge_swap_only({"d1": 28.0}, refused)(
            rec := {"cycle_date": "d1", "cost_usd": 52.0})
        self.assertAlmostEqual(rec["cost_usd"], 24.0)
        self.assertEqual(refused, set())

    def test_a_day_outside_the_map_is_not_touched(self):
        rec = {"cycle_date": "other", "cost_usd": 52.0}
        sep._charge_swap_only({"d1": 28.0}, set())(rec)
        self.assertEqual(rec["cost_usd"], 52.0)

    def test_flat_cost_skips_rows_without_a_move(self):
        idle = {"cycle_date": "d", "cost_usd": 0.0, "turnover_usd": 0.0}
        sep._flat_cost(0.01)(idle)
        self.assertEqual(idle["cost_usd"], 0.0,
                         "строке без хода цену придумывать нельзя")


class ProvenanceTest(unittest.TestCase):
    """Археология на обрезанной истории — НЕ ИЗМЕРЕНО, и без даты."""

    def _repo(self, td: str, *, with_line: str) -> Path:
        repo = Path(td)
        subprocess.run(("git", "init", "-q", str(repo)), check=True)
        subprocess.run(("git", "-C", str(repo), "config", "user.email", "t@t"),
                       check=True)
        subprocess.run(("git", "-C", str(repo), "config", "user.name", "t"),
                       check=True)
        for rel, _name in sep._CONSTANTS:
            f = repo / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(with_line, encoding="utf-8")
        subprocess.run(("git", "-C", str(repo), "add", "-A"), check=True)
        subprocess.run(("git", "-C", str(repo), "commit", "-q", "-m", "seed"),
                       check=True)
        return repo

    def test_a_bare_literal_reports_no_citation(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self._repo(td, with_line="SLIPPAGE_BPS_STABLE = 8.0  # swap\n"
                                            "ASSUMED_COST_BPS_OF_TURNOVER = 15.0\n")
            out = sep.provenance(repo)
        self.assertTrue(out["measured"])
        self.assertTrue(out["history_complete"])
        self.assertEqual(sorted(out["constants_without_any_citation"]),
                         ["ASSUMED_COST_BPS_OF_TURNOVER", "SLIPPAGE_BPS_STABLE"])
        for entry in out["constants"]:
            self.assertTrue(entry["history_measured"])
            self.assertIsNotNone(entry["first_commit"])

    def test_a_cited_literal_is_NOT_reported_as_naked(self):
        """Порванное звено наоборот: сторож обязан замолкать, когда ссылка есть."""
        with tempfile.TemporaryDirectory() as td:
            repo = self._repo(
                td,
                with_line=("SLIPPAGE_BPS_STABLE = 8.0  # см. ADR-042\n"
                           "ASSUMED_COST_BPS_OF_TURNOVER = 15.0  # https://x/y\n"))
            out = sep.provenance(repo)
        self.assertEqual(out["constants_without_any_citation"], [])

    def test_a_shallow_repo_refuses_the_date_instead_of_printing_a_wrong_one(self):
        """Ровно та авария: прод-дерево называет НЕ ТУ дату рождения константы."""
        with tempfile.TemporaryDirectory() as td:
            full = self._repo(str(Path(td) / "full"),
                              with_line="SLIPPAGE_BPS_STABLE = 8.0\n"
                                        "ASSUMED_COST_BPS_OF_TURNOVER = 15.0\n")
            for extra in range(2):
                (full / "x.txt").write_text(str(extra), encoding="utf-8")
                subprocess.run(("git", "-C", str(full), "add", "-A"), check=True)
                subprocess.run(("git", "-C", str(full), "commit", "-q", "-m",
                                f"c{extra}"), check=True)
            shallow = Path(td) / "shallow"
            subprocess.run(("git", "clone", "-q", "--depth", "1",
                            f"file://{full}", str(shallow)), check=True)
            out = sep.provenance(shallow)
        self.assertTrue(out["measured"])
        self.assertFalse(out["history_complete"])
        for entry in out["constants"]:
            self.assertFalse(entry["history_measured"])
            self.assertIsNone(entry["first_commit_date"],
                              "на обрезке дату печатать НЕЛЬЗЯ")
            self.assertIn("ОБРЕЗАНА", entry["history_reason"])
        # Вопрос к ДЕРЕВУ на обрезке всё равно измерим — иначе обрезка глушила бы
        # и то, на что история не влияет.
        self.assertEqual(sorted(out["constants_without_any_citation"]),
                         ["ASSUMED_COST_BPS_OF_TURNOVER", "SLIPPAGE_BPS_STABLE"])

    def test_a_missing_git_is_a_third_outcome_not_a_clean_pass(self):
        with tempfile.TemporaryDirectory() as td:
            out = sep.provenance(Path(td))
        self.assertFalse(out["measured"])
        self.assertIn("git не отвечает", out["reason"])

    def test_an_absent_file_is_named_not_counted_as_cited(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            subprocess.run(("git", "init", "-q", str(repo)), check=True)
            subprocess.run(("git", "-C", str(repo), "config", "user.email", "t@t"),
                           check=True)
            subprocess.run(("git", "-C", str(repo), "config", "user.name", "t"),
                           check=True)
            (repo / "seed").write_text("x", encoding="utf-8")
            subprocess.run(("git", "-C", str(repo), "add", "-A"), check=True)
            subprocess.run(("git", "-C", str(repo), "commit", "-q", "-m", "s"),
                           check=True)
            out = sep.provenance(repo)
        for entry in out["constants"]:
            self.assertFalse(entry["measured"])
            self.assertIn("не прочитан", entry["reason"])
        self.assertEqual(out["constants_without_any_citation"], [])


class HeadlineNumbersTest(unittest.TestCase):
    """Числа заголовка ЗАКРЕПЛЕНЫ: подмена любого обязана краснеть.

    Урок цикла #607: батарея мутаций нашла шесть заголовочных чисел соседа
    незакреплёнными — сторож проверял только, что строка непуста.
    """

    EX = {
        "days_total": 4, "days_measured": 2, "days_all_assets_known": 1,
        "per_day": [], "unmeasured_reasons": {}, "blocking_keys": {},
        "assets_seen": ["USDC"],
        "totals_all_measured_days": {
            "days": 2, "flow_usd": 100000.0, "swap_usd_min": 20000.0,
            "swap_usd_max": 30000.0, "swap_share_min": 0.2, "swap_share_max": 0.3,
            "no_swap_share_min": 0.7, "no_swap_share_max": 0.8,
            "bounds_coincide": False},
        "totals_strict_days": {
            "days": 1, "flow_usd": 50000.0, "swap_usd_min": 5000.0,
            "swap_usd_max": 5000.0, "swap_share_min": 0.1, "swap_share_max": 0.1,
            "no_swap_share_min": 0.9, "no_swap_share_max": 0.9,
            "bounds_coincide": True},
    }
    CF = {"measured": True, "wiring_alive": True, "act_days_returned_min": 2,
          "act_days_returned_max": 5}
    PROV = {"measured": True, "constants_without_any_citation": ["X"]}

    def test_every_headline_number_comes_from_the_measurement(self):
        head = sep._headline(self.EX, self.PROV, self.CF)
        for needle in ("$100,000.00", "20.00 %", "30.00 %", "1 дн", "10.00 %",
                       "2…5", "2 дн"):
            self.assertIn(needle, head, f"числа {needle} нет в заголовке")

    def test_moving_the_share_moves_the_headline(self):
        other = json.loads(json.dumps(self.EX))
        other["totals_all_measured_days"]["swap_share_min"] = 0.42
        self.assertNotEqual(sep._headline(self.EX, self.PROV, self.CF),
                            sep._headline(other, self.PROV, self.CF))

    def test_moving_the_returned_act_days_moves_the_headline(self):
        self.assertNotEqual(
            sep._headline(self.EX, self.PROV, self.CF),
            sep._headline(self.EX, self.PROV, dict(self.CF,
                                                   act_days_returned_max=9)))

    def test_no_population_says_so_instead_of_printing_a_share(self):
        head = sep._headline({"totals_all_measured_days": None}, self.PROV, self.CF)
        self.assertIn("НЕ ИЗМЕРЕНО", head)
        self.assertNotIn("%", head)


class FindingsTest(unittest.TestCase):
    """Каждая находка обязана иметь состояние, в котором её НЕТ."""

    EX_CLEAN = {
        "days_total": 1, "days_measured": 1, "days_all_assets_known": 1,
        "per_day": [], "unmeasured_reasons": {}, "blocking_keys": {},
        "assets_seen": ["USDC"], "totals_strict_days": None,
        "totals_all_measured_days": {
            "days": 1, "flow_usd": 100.0, "swap_usd_min": 100.0,
            "swap_usd_max": 100.0, "swap_share_min": 1.0, "swap_share_max": 1.0,
            "no_swap_share_min": 0.0, "no_swap_share_max": 0.0,
            "bounds_coincide": True}}
    CF_OFF = {"measured": False}
    ZERO_OK = {"measured": True, "collides": False}

    def _codes(self, ex, prov, cf, zero):
        return {f["code"] for f in sep._findings(ex, prov, cf, zero)}

    def test_a_pure_swap_day_raises_no_phantom_slippage_finding(self):
        codes = self._codes(self.EX_CLEAN, {"measured": False},
                            self.CF_OFF, self.ZERO_OK)
        self.assertNotIn("slippage_charged_where_no_swap_occurs", codes)

    def test_a_same_asset_day_does_raise_it(self):
        ex = json.loads(json.dumps(self.EX_CLEAN))
        ex["totals_all_measured_days"].update(
            {"no_swap_share_min": 0.6, "no_swap_share_max": 0.8})
        codes = self._codes(ex, {"measured": False}, self.CF_OFF, self.ZERO_OK)
        self.assertIn("slippage_charged_where_no_swap_occurs", codes)

    def test_a_colliding_judge_is_reported_and_a_sound_one_is_not(self):
        collide = {"measured": True, "collides": True,
                   "best_net_usd_zero": -1.0, "best_net_usd_one_cent": 1.0}
        self.assertIn("zero_price_is_read_as_absent_price",
                      self._codes(self.EX_CLEAN, {"measured": False},
                                  self.CF_OFF, collide))
        self.assertNotIn("zero_price_is_read_as_absent_price",
                         self._codes(self.EX_CLEAN, {"measured": False},
                                     self.CF_OFF, self.ZERO_OK))

    def test_a_refused_counterfactual_is_reported_as_such(self):
        refused = {"measured": False, "wiring_alive": False, "reason": "контроль"}
        self.assertIn("counterfactual_refused",
                      self._codes(self.EX_CLEAN, {"measured": False},
                                  refused, self.ZERO_OK))

    def test_returned_act_days_and_zero_returned_are_different_findings(self):
        none_back = {"measured": True, "wiring_alive": True,
                     "act_days_returned_min": 0, "act_days_returned_max": 0,
                     "relief_usd_max": 10.0}
        some_back = {"measured": True, "wiring_alive": True,
                     "act_days_returned_min": 1, "act_days_returned_max": 3,
                     "relief_usd_max": 10.0}
        self.assertIn("relief_changes_no_act_day",
                      self._codes(self.EX_CLEAN, {"measured": False},
                                  none_back, self.ZERO_OK))
        self.assertIn("act_days_returned_by_removing_phantom_slippage",
                      self._codes(self.EX_CLEAN, {"measured": False},
                                  some_back, self.ZERO_OK))


class ReadOnlyTest(unittest.TestCase):
    """Прибор только ЧИТАЕТ: живой каталог не меняется ни одним байтом."""

    def test_measure_does_not_touch_the_data_directory(self):
        """Предпосылка СТРОИТСЯ, а не ищется: скип здесь снял бы проверку молча.

        Живого журнала в одноразовом дереве нет по построению (`data/` не
        синхронизируется), и ветка `skipTest` делала бы сторожа функцией того,
        где его запустили.
        """
        with tempfile.TemporaryDirectory() as td:
            data = Path(td)
            (data / "capital_config.json").write_text(
                json.dumps({"capital": {"currency": "USDC"}}), encoding="utf-8")
            (data / "allocation_rationale_history.jsonl").write_text(
                "\n".join(json.dumps(r) for r in (
                    {"cycle_date": "2026-09-05", "turnover_usd": 55000.0,
                     "cost_usd": 92.0, "legs": _legs(("aave_v3", 35000.0),
                                                     ("pendle", 20000.0),
                                                     ("compound_v3", -55000.0)),
                     "apy_evidenced_pct": {"aave_v3": 5.0, "pendle": 9.0,
                                           "compound_v3": 4.0}},
                )) + "\n", encoding="utf-8")
            before = {p.name: (p.stat().st_mtime_ns, p.read_bytes())
                      for p in data.iterdir() if p.is_file()}
            sep.measure(data, now=datetime(2020, 1, 1, tzinfo=timezone.utc),
                        with_counterfactual=False)
            after = {p.name: (p.stat().st_mtime_ns, p.read_bytes())
                     for p in data.iterdir() if p.is_file()}
        self.assertEqual(before, after, "каталог данных изменился ЗАМЕРОМ")


class UnmeasuredShapeTest(unittest.TestCase):
    def test_third_outcome_carries_every_key_the_reader_expects(self):
        doc = sep._unmeasured(datetime(2020, 1, 1, tzinfo=timezone.utc), "почему")
        self.assertEqual(doc["status"], sep.STATUS_UNMEASURED)
        for key in ("existence", "provenance", "counterfactual", "zero_is_absent",
                    "findings", "what_it_does_not_prove", "headline", "version"):
            self.assertIn(key, doc)
        self.assertIn("почему", doc["headline"])

    def test_an_empty_journal_is_unmeasured_not_a_clean_zero(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "allocation_rationale_history.jsonl").write_text(
                "", encoding="utf-8")
            doc = sep.measure(Path(td), with_counterfactual=False)
        self.assertEqual(doc["status"], sep.STATUS_UNMEASURED)
        self.assertNotIn("%", doc["headline"])


class ConstantOwnershipTest(unittest.TestCase):
    """Значения констант берутся ИМПОРТОМ: своей копии литерала здесь нет."""

    def test_the_slippage_value_comes_from_its_owner(self):
        from spa_core.backtesting.tier1 import cost_model
        self.assertEqual(sep._slippage_bps(),
                         float(cost_model.SLIPPAGE_BPS_STABLE))

    def test_moving_the_owners_value_moves_the_instrument(self):
        """Порванное звено: подмена у владельца обязана дойти до прибора."""
        from spa_core.backtesting.tier1 import cost_model
        real = cost_model.SLIPPAGE_BPS_STABLE
        cost_model.SLIPPAGE_BPS_STABLE = 4321.0
        try:
            self.assertEqual(sep._slippage_bps(), 4321.0)
        finally:
            cost_model.SLIPPAGE_BPS_STABLE = real

    def test_the_module_carries_no_copy_of_the_numbers(self):
        src = Path(sep.__file__).read_text(encoding="utf-8")
        body = "\n".join(l for l in src.splitlines()
                         if not l.lstrip().startswith("#"))
        self.assertNotIn("= 8.0", body)
        self.assertNotIn("= 15.0", body)


if __name__ == "__main__":
    unittest.main()
