"""Приёмка переписи §13 (`spa_core/analytics/transaction_economics.py`, ADR-956).

КАЖДЫЙ тест здесь — положительный контроль: он воспроизводит состояние, при
котором перепись ОБЯЗАНА сменить ответ, и краснеет, если прибор перестал мерить
и начал утверждать. Проверка, никогда не видевшая настоящей поломки, —
украшение (`.claude/rules/deployment.md` § «Проверка сторожа сторожей»).

Главное, что здесь закреплено, — что прибор МЕРИТ, а не пересказывает. Все
девять ответов сняты дифференциально на двери цены, поэтому у каждого есть
ОБРАТНАЯ сцена: подменённая дверь, на которой ответ обязан стать другим. Если
бы прибор просто печатал объявленный `why`, обратные сцены не покраснели бы ни
одна — именно это и ловят тесты `*_flips_when_*`.

Время и живой трек: сцены не читают ни `data/equity_curve_daily.json`, ни
стенные часы — момент передаётся входом `now` (`.claude/rules/deployment.md`
§ «Время в тестах»), а книга сцены объявлена константами прибора.
"""
# FROZEN-DATE-OK: injected-clock — момент сцен передаётся входом `now=NOW`
# в `terms_state`/`measure`; literal ниже служит ЯКОРЕМ, от которого
# происходят отметки файлов сцены (`os.utime`), поэтому обе стороны сравнения
# свежести закреплены и календарь на вердикт не влияет.
from __future__ import annotations

import json
import os
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Dict, List

from spa_core.analytics import transaction_economics as te

NOW = datetime(2026, 11, 8, 12, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Сцена: ДВЕРЬ. Настоящая дверь берётся у живого модуля; подменённые двери ниже
# служат обратными сценами — на них ответ обязан смениться.
# ---------------------------------------------------------------------------

def real_door() -> Dict[str, Any]:
    door, why = te.load_cost_door()
    if door is None:  # pragma: no cover — предпосылка теста
        raise AssertionError(f"живая дверь цены не ввезена: {why}")
    return door


class _FakeCostModel:
    """Литерал цены, которым можно управлять. Форма — как у живого модуля."""

    def __init__(self, gas: Dict[str, float], slippage_bps: float = 8.0,
                 bridge_bps: float = 5.0) -> None:
        self.GAS_USD_PER_POSITION_CHANGE = dict(gas)
        self.SLIPPAGE_BPS_STABLE = slippage_bps
        self.BRIDGE_BPS = bridge_bps
        self.__name__ = "fake.cost_model"


def door_with(*, cost_fn, cost_model=None, legs_fn=None, evaluate_fn=None) -> Dict[str, Any]:
    base = real_door()
    return {"module": base["module"],
            "cost_model": cost_model or base["cost_model"],
            "move_cost": cost_fn,
            "legs": legs_fn or base["legs"],
            "evaluate": evaluate_fn or base["evaluate"]}


def kinds(door: Dict[str, Any]) -> Dict[str, str]:
    return {k: v["kind"] for k, v in te.probe_terms(door).items()}


# ---------------------------------------------------------------------------
# Сцена: ВХОД. Одноразовый каталог; живое `data/` не читается ни одним тестом.
# ---------------------------------------------------------------------------

def write_scene(dirpath: Path, *, gas_eth_usd: Any = None,
                chains: Any = None, gas_limit: Any = 250_000,
                adapters: Any = None, extra: Dict[str, Any] | None = None,
                age_h: float = 1.0) -> None:
    adapters = adapters if adapters is not None else {
        "aave_v3": {"display_name": "Aave V3", "chain": "ethereum"},
        "moonwell_base": {"display_name": "Moonwell", "chain": "base"},
    }
    (dirpath / "adapter_status.json").write_text(
        json.dumps({"adapters": adapters}), encoding="utf-8")
    gas_doc = {
        "generated_at": NOW.isoformat(),
        "gas_limit_per_leg": gas_limit,
        "eth_usd": gas_eth_usd if gas_eth_usd is not None
        else {"source": "live", "usd": 2000.0},
        "chains": chains if chains is not None else {
            "ethereum": {"source": "live", "gwei": 1.0, "sources_ok": 5},
            "base": {"source": "live", "gwei": 0.01, "sources_ok": 2},
        },
    }
    (dirpath / "gas_price_history.json").write_text(
        json.dumps(gas_doc), encoding="utf-8")
    for name, doc in (extra or {}).items():
        (dirpath / name).write_text(json.dumps(doc), encoding="utf-8")
    stamp = (NOW - timedelta(hours=age_h)).timestamp()
    for p in dirpath.iterdir():
        os.utime(p, (stamp, stamp))


class TransactionEconomicsCensusTest(unittest.TestCase):
    """Перепись на НАСТОЯЩЕЙ двери: девять ответов, и каждый измерен."""

    def test_the_declaration_holds_its_own_contract(self):
        # Урок ADR-943: сторож, мерящий себя своей же меркой, не мерит ничего.
        self.assertEqual(te.validate(), [])
        self.assertEqual(len(te.TERMS), 9)
        self.assertEqual(len(te.QUANTITIES), 4)
        self.assertNotIn(te.UNMEASURED, te.CHARGE_KINDS,
                         "«не измерено» не судится шкалой родов")
        for t in te.TERMS:
            self.assertIn(t["subject_kind"], te.SUBJECT_KINDS, t["term"])

    def test_nine_terms_of_the_owner_are_declared_verbatim(self):
        self.assertEqual(
            [t["owner_words"] for t in te.TERMS],
            ["withdraw gas", "deposit gas", "claim gas", "swap fee",
             "protocol fee", "slippage", "market impact", "bridge cost",
             "future exit cost"],
            "перечень и ПОРЯДОК — владельца; менять их значило бы отвечать на "
            "свой вопрос вместо заданного")

    def test_the_live_door_charges_two_terms_by_their_own_summand(self):
        k = kinds(real_door())
        self.assertEqual(k["slippage"], "charged_named")
        self.assertEqual(k["bridge_cost"], "charged_named")

    def test_withdraw_and_deposit_gas_are_charged_by_one_and_the_same_number(self):
        # Нога НЕСЁТ `direction`, и цена его игнорирует: два слагаемых
        # владельца заряжены одним литералом и дверью не различаются.
        k = kinds(real_door())
        self.assertEqual(k["withdraw_gas"], "charged_merged")
        self.assertEqual(k["deposit_gas"], "charged_merged")

    def test_claim_gas_is_expressible_and_not_charged(self):
        self.assertEqual(kinds(real_door())["claim_gas"], "not_charged")

    def test_market_impact_is_absent_because_cost_is_strictly_linear(self):
        self.assertEqual(kinds(real_door())["market_impact"], "not_charged")

    def test_three_terms_cannot_be_expressed_to_the_door_at_all(self):
        # ОТДЕЛЬНЫЙ исход, а не разновидность `not_charged`: чинится разным.
        k = kinds(real_door())
        for term in ("swap_fee", "protocol_fee", "future_exit_cost"):
            self.assertEqual(k[term], "no_input_door", term)


class ProbesActuallyMeasureTest(unittest.TestCase):
    """ОБРАТНЫЕ сцены. Прибор, который печатает объявленный `why`, краснеет."""

    def test_gas_verdict_flips_when_the_door_starts_reading_direction(self):
        base = real_door()

        def directional(legs: List[dict], turnover: float, chains: Dict[str, str]) -> float:
            # Вывод дороже ввода — ровно то, чего §13 и просит.
            extra = sum(3.0 for l in legs if float(l["delta_usd"]) < 0)
            return float(base["move_cost"](legs, turnover, chains)) + extra

        k = kinds(door_with(cost_fn=directional))
        self.assertEqual(k["withdraw_gas"], "charged_named",
                         "дверь стала читать направление — замер обязан это увидеть")
        self.assertEqual(k["deposit_gas"], "charged_named")

    def test_gas_verdict_flips_to_not_charged_when_gas_is_dropped(self):
        base = real_door()

        def slippage_only(legs: List[dict], turnover: float, chains: Dict[str, str]) -> float:
            return turnover * 0.0008

        k = kinds(door_with(cost_fn=slippage_only))
        self.assertEqual(k["withdraw_gas"], "not_charged")
        self.assertEqual(k["deposit_gas"], "not_charged")
        self.assertEqual(k["slippage"], "charged_named",
                         "проскальзывание в этой сцене осталось — ответ о нём не меняется")

    def test_claim_verdict_flips_when_a_zero_delta_move_produces_a_leg(self):
        base = real_door()

        def legs_for_claims(current, target, capital, min_leg_frac):
            legs, turnover = base["legs"](current, target, capital, min_leg_frac)
            if not legs:
                # Сцена, в которой сбор награды СТАЛ ногой.
                return ([{"protocol": p, "delta_usd": 0.0, "direction": "claim"}
                         for p in sorted(current)], turnover)
            return legs, turnover

        k = kinds(door_with(cost_fn=real_door()["move_cost"], legs_fn=legs_for_claims))
        self.assertEqual(k["claim_gas"], "charged_named",
                         "сбор стал стоить денег — замер обязан это увидеть")

    def test_market_impact_verdict_flips_when_cost_becomes_convex(self):
        base = real_door()

        def convex(legs: List[dict], turnover: float, chains: Dict[str, str]) -> float:
            return (float(base["move_cost"](legs, turnover, chains))
                    + 1e-7 * turnover * turnover)

        self.assertEqual(kinds(door_with(cost_fn=convex))["market_impact"],
                         "charged_named",
                         "зависимость стала выпуклой — выпуклый член обязан быть найден")

    def test_bridge_verdict_flips_to_not_charged_when_the_second_chain_is_free(self):
        def gas_only(legs: List[dict], turnover: float, chains: Dict[str, str]) -> float:
            return 12.0 * len(legs)

        self.assertEqual(kinds(door_with(cost_fn=gas_only))["bridge_cost"],
                         "not_charged")

    def test_bridge_is_unmeasured_when_no_two_chains_share_a_gas_literal(self):
        # Без пары с РАВНЫМ газом вопрос о мосте стал бы замером суммы двух
        # сдвигов. Третий исход, а не «мост не заряжен» (инв. #17).
        cm = _FakeCostModel({"ethereum": 12.0, "base": 0.15, "blended": 1.5})
        k = kinds(door_with(cost_fn=real_door()["move_cost"], cost_model=cm))
        self.assertEqual(k["bridge_cost"], te.UNMEASURED)

    def test_the_equal_gas_pair_is_measured_not_assumed(self):
        cm = _FakeCostModel({"alpha": 7.0, "beta": 7.0, "gamma": 1.0})
        self.assertEqual(te._equal_gas_pair(cm), ("alpha", "beta"))
        self.assertIsNone(te._equal_gas_pair(_FakeCostModel({"a": 1.0, "b": 2.0})))


class CostDoesNotEnterTheGainBandTest(unittest.TestCase):
    """Утверждение ADR-243, перемеренное ДИФФЕРЕНЦИАЛЬНО, а не прочитанное."""

    def test_raising_the_cost_moves_payback_and_leaves_the_gain_band_alone(self):
        rec = te.probe_quantities(real_door())[0]["cost_does_not_enter_band"]
        self.assertGreater(rec["cost_ratio"], 1.0, "сцена обязана подорожать")
        self.assertFalse(rec["gain_moved_with_cost"],
                         "выгода не является функцией цены")
        self.assertFalse(rec["band_moved_with_cost"],
                         "полоса выгоды от цены не сужается")
        self.assertGreater(rec["payback_days_dear"], rec["payback_days_cheap"],
                           "цена входит РОВНО в срок окупаемости")

    def test_the_reading_flips_when_the_band_starts_to_see_the_cost(self):
        base = real_door()

        def evaluate_net(**kw):
            d = base["evaluate"](**kw)
            # Сцена: полоса сравнивает выгоду ЗА ВЫЧЕТОМ цены.
            d.gain_pp = round(d.gain_pp - d.cost_pp, 6)
            d.gates = dict(d.gates,
                           gain_above_band=d.gain_pp >= d.required_gain_pp)
            return d

        rec = te.probe_quantities(door_with(
            cost_fn=base["move_cost"], evaluate_fn=evaluate_net,
        ))[0]["cost_does_not_enter_band"]
        self.assertTrue(rec["gain_moved_with_cost"],
                        "выгода стала функцией цены — замер обязан это увидеть")
        self.assertIn("перемерить", rec["reading"])

    def test_two_of_four_quantities_are_computed_and_two_are_not(self):
        qs = te.probe_quantities(real_door())[0]["quantities"]
        by = {q["quantity"]: q["state"] for q in qs}
        self.assertEqual(by["gross_incremental_yield"], "computed")
        self.assertEqual(by["break_even_time"], "computed")
        self.assertEqual(by["net_incremental_yield"], "not_computed")
        self.assertEqual(by["expected_incremental_profit"], "not_computed")

    def test_a_declared_field_that_vanished_is_unmeasured_not_absent(self):
        base = real_door()

        def evaluate_without_gain(**kw):
            d = base["evaluate"](**kw)
            del d.gain_pp
            return d

        qs = te.probe_quantities(door_with(
            cost_fn=base["move_cost"], evaluate_fn=evaluate_without_gain,
        ))[0]["quantities"]
        by = {q["quantity"]: q["state"] for q in qs}
        self.assertEqual(by["gross_incremental_yield"], te.UNMEASURED,
                         "исчезнувшее поле — НЕ ИЗМЕРЕНО, а не «не вычисляется»")


class ObservedGasReaderTest(unittest.TestCase):
    """Читатель наблюдения. Его первая редакция и была дефектом (см. ADR-956)."""

    def test_the_price_of_eth_is_read_from_the_declared_record_form(self):
        # ЭТО положительный контроль найденного дефекта: писатель несёт
        # `{"source": "live", "usd": …}`, а не число, и первая редакция
        # отвечала `unmeasured` о наблюдении, которое ЕСТЬ.
        with TemporaryDirectory() as td:
            d = Path(td)
            write_scene(d)
            rec = te.observed_gas_usd_per_leg(d)
            self.assertEqual(rec["state"], "observed", rec.get("detail"))
            # 1 gwei × 250 000 × $2000 = $0.50 за ногу
            self.assertAlmostEqual(
                rec["per_chain"]["ethereum"]["usd_per_leg"], 0.5, places=6)

    def test_a_bare_number_is_also_accepted(self):
        with TemporaryDirectory() as td:
            d = Path(td)
            write_scene(d, gas_eth_usd=2000.0)
            self.assertEqual(te.observed_gas_usd_per_leg(d)["state"], "observed")

    def test_a_sample_that_was_not_taken_live_is_not_an_observation(self):
        with TemporaryDirectory() as td:
            d = Path(td)
            write_scene(d, chains={"ethereum": {"source": "unchecked", "gwei": 1.0}})
            rec = te.observed_gas_usd_per_leg(d)
            self.assertEqual(rec["state"], "no_live_sample")
            self.assertEqual(rec["per_chain"]["ethereum"]["state"], "no_live_sample")

    def test_a_price_taken_not_live_is_refused_as_the_converter(self):
        with TemporaryDirectory() as td:
            d = Path(td)
            write_scene(d, gas_eth_usd={"source": "cached", "usd": 2000.0})
            rec = te.observed_gas_usd_per_leg(d)
            self.assertEqual(rec["state"], te.UNMEASURED)
            self.assertIn("eth_usd", rec["detail"])

    def test_a_missing_converter_is_unmeasured_not_zero(self):
        with TemporaryDirectory() as td:
            d = Path(td)
            write_scene(d, gas_limit=None)
            rec = te.observed_gas_usd_per_leg(d)
            self.assertEqual(rec["state"], te.UNMEASURED)
            self.assertIn("gas_limit_per_leg", rec["detail"])

    def test_an_absent_file_is_unmeasured_and_an_empty_one_is_empty(self):
        with TemporaryDirectory() as td:
            d = Path(td)
            self.assertEqual(te.observed_gas_usd_per_leg(d)["state"], te.UNMEASURED)
            write_scene(d, chains={})
            self.assertEqual(te.observed_gas_usd_per_leg(d)["state"], "empty")


class ChargedVersusObservedTest(unittest.TestCase):
    """Перемер ADR-243 у слагаемых §13: заряжено против наблюдённого."""

    def test_the_ratio_is_computed_only_where_both_numbers_exist(self):
        with TemporaryDirectory() as td:
            d = Path(td)
            write_scene(d)
            cm = _FakeCostModel({"ethereum": 12.0, "mainnet": 12.0, "blended": 1.5})
            door = door_with(cost_fn=real_door()["move_cost"], cost_model=cm)
            out = te.charged_vs_observed(door, te.observed_gas_usd_per_leg(d))
            self.assertEqual(out["state"], "compared")
            eth = [p for p in out["pairs"] if p["chain"] == "ethereum"][0]
            self.assertEqual(eth["charged_usd_per_leg"], 12.0)
            self.assertAlmostEqual(eth["observed_usd_per_leg"], 0.5, places=6)
            self.assertAlmostEqual(eth["ratio_charged_over_observed"], 24.0, places=2)
            # `base` наблюдена, но литерала у неё в ЭТОЙ сцене нет.
            base_pair = [p for p in out["pairs"] if p["chain"] == "base"][0]
            self.assertEqual(base_pair["state"], "not_in_literal")

    def test_without_an_observation_the_comparison_is_unmeasured_not_clean(self):
        with TemporaryDirectory() as td:
            d = Path(td)
            write_scene(d, chains={"ethereum": {"source": "unchecked", "gwei": 1.0}})
            out = te.charged_vs_observed(real_door(),
                                         te.observed_gas_usd_per_leg(d))
            self.assertEqual(out["state"], te.UNMEASURED)
            self.assertIn("сверять заряженное не с чем", out["detail"])


class LiteralSitesTest(unittest.TestCase):
    """ГДЕ печатается литерал. Значение читается у ЖИВОГО модуля, не у копии."""

    def test_the_value_follows_the_live_module(self):
        cm = _FakeCostModel({"ethereum": 99.0}, slippage_bps=123.0, bridge_bps=4.0)
        sites = {s["constant"]: s for s in
                 te.literal_sites(door_with(cost_fn=real_door()["move_cost"],
                                            cost_model=cm))}
        self.assertEqual(sites["SLIPPAGE_BPS_STABLE"]["value"], 123.0,
                         "прибор со СВОЕЙ копией числа отвечал бы о себе")
        self.assertEqual(sites["GAS_USD_PER_POSITION_CHANGE"]["value"],
                         {"ethereum": 99.0})
        self.assertEqual(sites["BRIDGE_BPS"]["value"], 4.0)

    def test_a_constant_that_vanished_is_unmeasured_not_absent(self):
        class Bare:
            __name__ = "bare"

        sites = {s["constant"]: s for s in
                 te.literal_sites(door_with(cost_fn=real_door()["move_cost"],
                                            cost_model=Bare()))}
        for name in ("GAS_USD_PER_POSITION_CHANGE", "SLIPPAGE_BPS_STABLE", "BRIDGE_BPS"):
            self.assertEqual(sites[name]["state"], te.UNMEASURED, name)


class SubjectKindTest(unittest.TestCase):
    """Род ПРЕДМЕТА. Спутать протокол с цепью — значит выдумать находку."""

    def test_gas_binds_by_chain_and_is_credited(self):
        with TemporaryDirectory() as td:
            d = Path(td)
            write_scene(d)
            terms = {t["term"]: t for t in
                     te.terms_state(d, json.loads(
                         (d / "adapter_status.json").read_text())["adapters"],
                         real_door(), now=NOW)}
            self.assertEqual(terms["withdraw_gas"]["subject_kind"], "chain")
            self.assertEqual(terms["withdraw_gas"]["observation"]["state"],
                             "credited")

    def test_binding_gas_by_protocol_would_have_invented_a_finding(self):
        # Это ДОКАЗАТЕЛЬСТВО, что род предмета нужен: тем же файлом, но
        # привязанным к ПРОТОКОЛАМ, живое наблюдение газа объявляется
        # выдуманным. Ровно так и ошиблась первая редакция прибора.
        with TemporaryDirectory() as td:
            d = Path(td)
            write_scene(d)
            protocols = te.opportunity_names(json.loads(
                (d / "adapter_status.json").read_text())["adapters"])
            wrong = te._source_state(
                d, "gas_price_history.json", protocols,
                "rebalance_economics._move_cost_usd (газ за ногу)", NOW)
            self.assertEqual(wrong["state"], "fixture_subject")
            right = te._source_state(
                d, "gas_price_history.json",
                te.our_chain_names(json.loads(
                    (d / "adapter_status.json").read_text())["adapters"],
                    real_door()),
                "rebalance_economics._move_cost_usd (газ за ногу)", NOW)
            self.assertEqual(right["state"], "credited")

    def test_chain_names_come_from_both_the_registry_and_the_literal(self):
        names = te.our_chain_names(
            {"x": {"chain": "zksync"}}, real_door())
        self.assertIn("zksync", names, "цепь реестра")
        self.assertIn("ethereum", names, "цепь заряженного литерала")

    def test_a_term_with_no_names_to_bind_is_unmeasured_not_fixture(self):
        with TemporaryDirectory() as td:
            d = Path(td)
            write_scene(d)
            terms = {t["term"]: t for t in
                     te.terms_state(d, {}, real_door(), now=NOW)}
            # Пустой реестр ⇒ имён ПРОТОКОЛОВ нет; у газа имена всё равно
            # есть (из литерала), поэтому слепым обязан стать именно
            # протокольный предмет, а не газ.
            self.assertEqual(terms["claim_gas"]["observation"]["state"],
                             te.UNMEASURED)
            self.assertEqual(terms["withdraw_gas"]["observation"]["state"],
                             "credited")

    def test_a_term_without_any_source_says_so_and_does_not_guess(self):
        with TemporaryDirectory() as td:
            d = Path(td)
            write_scene(d)
            terms = {t["term"]: t for t in
                     te.terms_state(d, {"a": {"chain": "base"}}, real_door(), now=NOW)}
            for term in ("market_impact", "future_exit_cost"):
                self.assertEqual(terms[term]["observation"]["state"], "no_source",
                                 term)

    def test_a_stale_observation_is_stale_and_not_credited(self):
        with TemporaryDirectory() as td:
            d = Path(td)
            write_scene(d, age_h=te.SOURCE_MAX_AGE_H + 10.0)
            terms = {t["term"]: t for t in
                     te.terms_state(d, {"a": {"chain": "ethereum"}},
                                    real_door(), now=NOW)}
            self.assertEqual(terms["withdraw_gas"]["observation"]["state"], "stale")


class MeasureEndToEndTest(unittest.TestCase):
    """Три исхода переписи различимы (инв. #17), и ни один не молчит."""

    def test_the_census_is_taken_and_names_its_findings(self):
        with TemporaryDirectory() as td:
            d = Path(td)
            write_scene(d)
            rep = te.measure(d, now=NOW)
            self.assertEqual(rep["status"], "WARN")
            self.assertEqual(rep["verdict"], "FINDINGS")
            c = rep["counts"]
            self.assertEqual(c["terms_declared"], 9)
            self.assertEqual(c["charged_named"], 2)
            self.assertEqual(c["charged_merged"], 2)
            self.assertEqual(c["not_charged"], 2)
            self.assertEqual(c["no_input_door"], 3)
            self.assertEqual(c["charge_unmeasured"], 0)
            self.assertEqual(c["quantities_computed"], 2)
            self.assertEqual(c["quantities_not_computed"], 2)
            self.assertTrue(rep["findings"])
            self.assertTrue(rep["is_advisory"], "слой обязан остаться advisory")

    def test_an_unreadable_registry_does_not_silence_the_charge_axis(self):
        # Род ЗАРЯДА есть свойство ДВЕРИ, не данных: вход не прочитан ⇒
        # слепота НАЗЫВАЕТСЯ, а перепись родов всё равно снимается.
        with TemporaryDirectory() as td:
            d = Path(td)
            rep = te.measure(d, now=NOW)
            self.assertTrue(rep["unmeasured"], "слепота обязана быть названа")
            self.assertEqual(rep["counts"]["terms_declared"], 9)
            self.assertEqual(rep["counts"]["charged_named"], 2)

    def test_a_missing_cost_door_is_unmeasured_and_never_a_clean_pass(self):
        import spa_core.allocator.rebalance_economics as re_mod
        saved = re_mod._move_cost_usd
        try:
            del re_mod._move_cost_usd
            with TemporaryDirectory() as td:
                d = Path(td)
                write_scene(d)
                rep = te.measure(d, now=NOW)
            self.assertEqual(rep["status"], "SKIPPED")
            self.assertEqual(rep["verdict"], "UNMEASURED")
            self.assertIn("_move_cost_usd", rep["reason"])
            self.assertNotIn("terms", rep,
                             "без двери перепись не выдаётся за снятую")
        finally:
            re_mod._move_cost_usd = saved

    def test_a_broken_declaration_refuses_before_measuring(self):
        saved = te.TERMS
        try:
            te.TERMS = saved[:3]
            rep = te.measure(Path("."), now=NOW)
            self.assertEqual(rep["verdict"], "UNMEASURED")
            self.assertIn("ДЕВЯТЬ", rep["reason"])
        finally:
            te.TERMS = saved

    def test_the_cli_returns_zero_while_something_is_charged(self):
        with TemporaryDirectory() as td:
            d = Path(td)
            write_scene(d)
            self.assertEqual(te.main(["--data-dir", str(d), "--json"]), 0)

    def test_the_cli_returns_two_when_the_door_is_gone(self):
        import spa_core.allocator.rebalance_economics as re_mod
        saved = re_mod.evaluate
        try:
            del re_mod.evaluate
            with TemporaryDirectory() as td:
                self.assertEqual(
                    te.main(["--data-dir", td, "--json"]), 2,
                    "НЕ ИЗМЕРЕНО обязано отличаться кодом от «ничего не заряжено»")
        finally:
            re_mod.evaluate = saved

    def test_the_report_is_json_serialisable(self):
        # Секция цикла печатается и уезжает в отчёт — непечатаемый отчёт
        # означал бы, что замера не видел никто.
        with TemporaryDirectory() as td:
            d = Path(td)
            write_scene(d)
            json.dumps(te.measure(d, now=NOW), ensure_ascii=False, default=str)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
