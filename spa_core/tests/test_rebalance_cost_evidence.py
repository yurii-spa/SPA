"""Сторож §49 ТЗ CIO «Costs»: газ/комиссии/проскальзывание в РЕШЕНИИ о перекладке.

Каждый тест — положительный контроль: он воспроизводит дефект, ради которого
сторож написан, и краснеет, если дефект вернуть.

Литеральных дат в файле нет намеренно, хотя модуль О СВЕЖЕСТИ судит (возраст
чтения против SLO производителя). Часы — ВХОД (`run(..., now=)`), а отметки в
фикстурах строятся ОТНОСИТЕЛЬНО этих часов от эпохи: обе стороны закреплены, и
сдвиг календаря не может уронить ни один тест (`.claude/rules/deployment.md`,
«Время в тестах»).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import tempfile
import unittest

from spa_core.monitoring import rebalance_cost_evidence as R
from spa_core.allocator.rebalance_economics import evaluate, TriggerParams

_NOW = dt.datetime.fromtimestamp(0, dt.timezone.utc)


def _ts(hours_ago: float) -> str:
    """Отметка ОТНОСИТЕЛЬНО инъектированных часов — литеральных дат в файле нет."""
    return (_NOW - dt.timedelta(hours=hours_ago)).isoformat().replace("+00:00", "Z")


def _gas_doc(*, eth_gwei=0.06, base_gwei=0.006, eth_usd=2500.0,
             eth_source="live", spot_source="live", age_hours=0.5):
    return {
        "eth_usd": {"source": spot_source, "usd": eth_usd},
        "gas_limit_per_leg": R.GAS_LIMIT_PER_LEG,
        "history": {
            "ethereum": [{"ts": _ts(age_hours), "source": eth_source,
                          "gwei": eth_gwei, "sources_ok": 4}],
            "base": [{"ts": _ts(age_hours), "source": "live",
                      "gwei": base_gwei, "sources_ok": 2}],
        },
    }


#: Ноги ЖИВОГО вердикта 06.09 (`data/allocation_rationale.json`, 06:00:09Z).
#: Фикстура — не выдумка: пять ног на ethereum по $12.00 и одна на base по $0.15
#: дают ровно те $60.15 газа, из-за которых сторож и написан. Положительный
#: контроль обязан воспроизводить НАСТОЯЩУЮ аварию, иначе он украшение.
_LIVE_LEGS = [
    {"protocol": "aave_v3", "delta_usd": 28_157.89, "direction": "increase"},
    {"protocol": "compound_v3", "delta_usd": -2_105.26, "direction": "decrease"},
    {"protocol": "fluid_usdc", "delta_usd": -20_000.0, "direction": "decrease"},
    {"protocol": "maple", "delta_usd": -20_000.0, "direction": "decrease"},
    {"protocol": "morpho_blue_base", "delta_usd": -5_000.0, "direction": "decrease"},
    {"protocol": "pendle", "delta_usd": 18_947.37, "direction": "increase"},
]


def _rationale(*, legs=None, turnover=47_105.26, payback=23.11, gate=True):
    legs = legs if legs is not None else [dict(l) for l in _LIVE_LEGS]
    return {
        "generated_at": _ts(1.0),
        "capital_usd": 100_000.0,
        "decision_shadow": {
            "decision": "HOLD",
            "legs": legs,
            "turnover_usd": turnover,
            "payback_days": payback,
            "gates": {"has_legs": True, "payback_within_horizon": gate,
                      "gain_above_band": True},
        },
    }


#: Сети и TVL — тоже с живого снимка 06.09 (реестр + снимок оркестратора).
_LIVE_CHAINS = {"aave_v3": "ethereum", "compound_v3": "ethereum",
                "fluid_usdc": "ethereum", "maple": "ethereum",
                "morpho_blue_base": "base", "pendle": "ethereum"}
_LIVE_TVL = {"aave_v3": 58_548_694.0, "compound_v3": 34_659_970.0,
             "fluid_usdc": 148_902_380.0, "maple": 2_725_025_302.0,
             "morpho_blue_base": 427_666_197.0, "pendle": 21_372_031.0}


def _registry():
    return {"adapters": {k: {"chain": v} for k, v in _LIVE_CHAINS.items()}}


def _orch(tvl_source="live"):
    return {"adapters": [{"protocol": k, "tvl_usd": v, "tvl_source": tvl_source}
                         for k, v in _LIVE_TVL.items()]}


def _manifest(slo=1.5):
    return {"artifacts": [{"path": R.GAS_ARTIFACT_REL, "slo_hours": slo}]}


class _Tree:
    """Дерево-песочница: каждый вход модуля — отдельный файл, подменяемый поимённо.

    Мутация по КООРДИНАТЕ (какой файл/поле), а не по тексту: тест обязан краснеть
    от смены проводки, а не от переименования.
    """

    def __init__(self, tmp: str, **files):
        self.root = tmp
        self.data = os.path.join(tmp, "data")
        os.makedirs(self.data, exist_ok=True)
        os.makedirs(os.path.join(tmp, "architecture"), exist_ok=True)
        self.files = {
            "data/allocation_rationale.json": _rationale(),
            "data/adapter_registry.json": _registry(),
            "data/adapter_orchestrator_status.json": _orch(),
            "data/gas_price_history.json": _gas_doc(),
            "architecture/manifest.json": _manifest(),
        }
        self.files.update({k: v for k, v in files.items() if v is not None})
        self.dropped = {k for k, v in files.items() if v is None}

    def read(self, path: str):
        rel = os.path.relpath(path, self.root).replace(os.sep, "/")
        if rel in self.dropped:
            raise FileNotFoundError(path)
        if rel in self.files:
            return self.files[rel]
        raise FileNotFoundError(path)

    def run(self):
        return R.run(root=self.root, write=False, data_dir=self.data,
                     now=_NOW, reader=self.read)


def _tree(**files):
    tmp = tempfile.mkdtemp(prefix="spa_cost_ev_")
    return _Tree(tmp, **files)


class TestCostEntersOnlyThePaybackGate(unittest.TestCase):
    """Положительный контроль на УТВЕРЖДЕНИЕ модуля, а не на его пересказ.

    Модуль печатает как факт: «стоимость входит в вердикт ТОЛЬКО через
    `payback_within_horizon`; `gain_above_band` сравнивает ВАЛОВУЮ выгоду».
    Здесь это меряется на настоящем `evaluate()`: сделает кто-нибудь полосу
    выгоды функцией стоимости — тест покраснеет, и находка сторожа станет ложью
    ДО того, как её кто-то прочитает.
    """

    def _verdict(self, *, chain: str):
        return evaluate(
            current_positions={"a": 50_000.0, "b": 50_000.0},
            target_positions={"a": 20_000.0, "b": 80_000.0},
            apy_pct={"a": 2.0, "b": 8.0},
            evidenced={"a", "b"},
            chains={"a": chain, "b": chain},
            capital_usd=100_000.0,
            params=TriggerParams(),
        )

    def test_cost_moves_only_the_payback_gate(self):
        cheap = self._verdict(chain="base")        # $0.15 за ногу
        dear = self._verdict(chain="ethereum")     # $12.00 за ногу
        self.assertGreater(dear.cost_usd, cheap.cost_usd,
                           "смена сети обязана менять заряженную стоимость")
        # Стоимость выросла — ВАЛОВАЯ выгода не дрогнула.
        self.assertEqual(cheap.gain_pp, dear.gain_pp)
        self.assertEqual(cheap.gates["gain_above_band"], dear.gates["gain_above_band"])
        # …и срок окупаемости вырос.
        self.assertGreater(dear.payback_days, cheap.payback_days)

    def test_gain_band_compares_gross_gain_not_net(self):
        """Полоса выгоды сравнивается с ВАЛОВОЙ выгодой — стоимость из неё не вычтена."""
        v = self._verdict(chain="ethereum")
        self.assertAlmostEqual(v.gain_pp, v.apy_opt_pp - v.apy_now_pp, places=6)
        self.assertGreater(v.cost_pp, 0.0)
        # Если бы выгода была чистой, она была бы меньше валовой ровно на cost_pp.
        self.assertNotAlmostEqual(v.gain_pp,
                                  v.apy_opt_pp - v.apy_now_pp - v.cost_pp, places=6)


class TestDecompositionIsCheckedAgainstTheRealFormula(unittest.TestCase):
    def test_components_sum_to_move_cost_usd(self):
        legs = [{"protocol": "aave_v3", "delta_usd": 10_000.0},
                {"protocol": "morpho_blue_base", "delta_usd": -10_000.0}]
        c = R.charged_components(legs, 10_000.0,
                                 {"aave_v3": "ethereum", "morpho_blue_base": "base"})
        self.assertTrue(c["consistent"])
        self.assertAlmostEqual(c["total_usd"], c["canonical_total_usd"], places=9)

    def test_drift_from_the_real_formula_is_UNCHECKED_not_a_number(self):
        """Разошлось разложение с `_move_cost_usd` ⇒ третий исход, а не тихий отчёт."""
        original = R._move_cost_usd
        try:
            R._move_cost_usd = lambda legs, turnover, chains: 999_999.0
            rep = _tree().run()
        finally:
            R._move_cost_usd = original
        self.assertEqual(rep["overall"], "UNCHECKED")
        self.assertTrue(any("разложение стоимости разошлось" in u
                            for u in rep["unchecked"]))
        self.assertIsNone(rep["substitution"],
                          "на разошедшемся разложении подстановку считать нельзя")

    def test_bridge_is_charged_only_when_more_than_one_chain_is_touched(self):
        one = R.charged_components([{"protocol": "aave_v3", "delta_usd": 10_000.0}],
                                   10_000.0, {"aave_v3": "ethereum"})
        two = R.charged_components(
            [{"protocol": "aave_v3", "delta_usd": 10_000.0},
             {"protocol": "morpho_blue_base", "delta_usd": -10_000.0}],
            10_000.0, {"aave_v3": "ethereum", "morpho_blue_base": "base"})
        self.assertEqual(one["bridge_usd"], 0.0)
        self.assertGreater(two["bridge_usd"], 0.0)

    def test_chain_provenance_names_the_default(self):
        """Сеть, которой нет в реестре, помечается ДЕФОЛТОМ, а не выдаётся за реестр."""
        c = R.charged_components([{"protocol": "неизвестный", "delta_usd": 1_000.0}],
                                 1_000.0, {})
        self.assertEqual(c["gas_by_leg"][0]["chain_provenance"], "default:blended")


class TestObservationIsNeverInvented(unittest.TestCase):
    """«Не измерено» — третий исход с причиной, а не ноль и не пропуск."""

    def test_spot_not_live_measures_NOTHING(self):
        rep = _tree(**{"data/gas_price_history.json":
                       _gas_doc(spot_source="unchecked")}).run()
        self.assertEqual(rep["overall"], "UNCHECKED")
        self.assertFalse(rep["observed_gas"]["measured"])
        self.assertIn("ETH/USD", rep["observed_gas"]["reason"])
        self.assertIsNone(rep["substitution"])

    def test_chain_without_a_live_reading_is_UNCHECKED_not_zero(self):
        rep = _tree(**{"data/gas_price_history.json":
                       _gas_doc(eth_source="unchecked")}).run()
        self.assertEqual(rep["overall"], "UNCHECKED")
        self.assertIsNone(rep["substitution"],
                          "частичное покрытие сетей не даёт подставлять газ")
        self.assertTrue(any("ethereum" in u for u in rep["unchecked"]))

    def test_the_last_LIVE_reading_is_taken_not_the_last_row(self):
        """Отказ источников (`unchecked`) чтением НЕ считается — иначе вернулся бы
        ровно тот fallback-литерал, которого избегает ADR-183."""
        doc = _gas_doc()
        doc["history"]["ethereum"] = [
            {"ts": _ts(3.0), "source": "live", "gwei": 0.06, "sources_ok": 4},
            {"ts": _ts(0.5), "source": "unchecked", "note": "источники молчат"},
        ]
        obs = R.observed_gas_usd_per_leg(doc, now=_NOW)
        self.assertTrue(obs["chains"]["ethereum"]["measured"])
        self.assertEqual(obs["chains"]["ethereum"]["gwei"], 0.06)
        self.assertEqual(obs["chains"]["ethereum"]["age_hours"], 3.0)

    def test_missing_gas_artifact_is_UNCHECKED(self):
        rep = _tree(**{"data/gas_price_history.json": None}).run()
        self.assertEqual(rep["overall"], "UNCHECKED")

    def test_missing_verdict_is_UNCHECKED(self):
        rep = _tree(**{"data/allocation_rationale.json": None}).run()
        self.assertEqual(rep["overall"], "UNCHECKED")
        self.assertIsNone(rep["charged"])

    def test_unchecked_outranks_critical(self):
        """Третий исход ВЫШЕ CRITICAL — иначе он тонет в находках."""
        rep = _tree(**{"data/gas_price_history.json":
                       _gas_doc(spot_source="unchecked")}).run()
        self.assertEqual(rep["overall"], "UNCHECKED")
        self.assertGreater(rep["counts"]["unchecked"], 0)


class TestUnitOfTheObservationIsTheUnitOfTheCharge(unittest.TestCase):
    def test_usd_per_leg_uses_the_producers_own_multiplier(self):
        obs = R.observed_gas_usd_per_leg(_gas_doc(eth_gwei=0.06, eth_usd=2500.0),
                                         now=_NOW)
        expected = 0.06 * 1e-9 * R.GAS_LIMIT_PER_LEG * 2500.0
        self.assertAlmostEqual(obs["chains"]["ethereum"]["usd_per_leg"], expected,
                               places=12)

    def test_gas_limit_comes_from_the_producer_not_from_a_local_literal(self):
        """Множитель читается из дома производителя — своей копии здесь нет."""
        from spa_core.monitoring import gas_price_agent
        self.assertIs(R.GAS_LIMIT_PER_LEG, gas_price_agent.GAS_LIMIT_PER_LEG)

    def test_gas_limit_is_read_from_the_SOURCE_not_matched_by_value(self):
        """Подменяем ИСТОЧНИК, а не сверяем значение.

        Литерал, СОВПАДАЮЩИЙ с домом, проверку по значению проходит молча —
        ровно этот класс дважды промолчал в цикле #502. Здесь дом подменён:
        зашитая копия множителя за ним не пойдёт и тест покраснеет.
        """
        original = R.GAS_LIMIT_PER_LEG
        try:
            R.GAS_LIMIT_PER_LEG = original * 3
            obs = R.observed_gas_usd_per_leg(_gas_doc(eth_gwei=0.06, eth_usd=2500.0),
                                             now=_NOW)
        finally:
            R.GAS_LIMIT_PER_LEG = original
        self.assertAlmostEqual(obs["chains"]["ethereum"]["usd_per_leg"],
                               0.06 * 1e-9 * original * 3 * 2500.0, places=12)


class TestTheFindingIsPrincipledNotTuned(unittest.TestCase):
    """CRITICAL ставится по ПРИНЦИПУ: ошибка стоимости больше зазора гейта."""

    def test_error_bigger_than_the_margin_is_CRITICAL(self):
        rep = _tree().run()
        self.assertEqual(rep["overall"], "CRITICAL")
        kinds = {f["kind"] for f in rep["findings"]}
        self.assertIn("cost_error_exceeds_the_deciding_margin", kinds)
        s = rep["substitution"]
        self.assertLess(s["cost_ratio_observed_over_charged"], 1.0)
        self.assertIsNotNone(s["false_refusal_band_days"])

    def test_error_smaller_than_the_margin_is_only_WARN(self):
        """Газ, почти совпавший с литералом, критикой быть не должен."""
        # Подбираем gwei так, чтобы наблюдённый газ был близок к заряженному.
        near = R.GAS_USD_PER_POSITION_CHANGE["ethereum"] / (
            1e-9 * R.GAS_LIMIT_PER_LEG * 2500.0)
        rep = _tree(**{"data/gas_price_history.json":
                       _gas_doc(eth_gwei=near, base_gwei=near, eth_usd=2500.0)}).run()
        kinds = {f["kind"] for f in rep["findings"]}
        self.assertIn("cost_error_within_the_deciding_margin", kinds)
        self.assertNotIn("cost_error_exceeds_the_deciding_margin", kinds)

    def test_a_flipped_gate_is_reported_as_such(self):
        """Подстановка переворачивает гейт ⇒ это названо отдельной находкой."""
        # Гейт сейчас отказывает на длинном payback; на наблюдённом газе — пройдёт.
        rep = _tree(**{"data/allocation_rationale.json":
                       _rationale(payback=45.0, gate=False)}).run()
        s = rep["substitution"]
        self.assertTrue(s["verdict_would_flip"])
        self.assertFalse(s["payback_gate_now"])
        self.assertTrue(s["payback_gate_on_observed_gas"])
        kinds = {f["kind"] for f in rep["findings"]}
        self.assertIn("observed_gas_flips_the_gate", kinds)

    def test_the_horizon_is_read_from_its_home_not_from_a_local_literal(self):
        """`max_payback_days` берётся у демпфера; своего числа модуль не назначает."""
        rep = _tree().run()
        self.assertEqual(rep["substitution"]["max_payback_days"],
                         TriggerParams.for_mode().max_payback_days)
        self.assertIn("TriggerParams.for_mode()", rep["provenance"]["params"])

    def test_the_horizon_follows_its_SOURCE_not_a_matching_literal(self):
        """Подменяем ДОМ порога: зашитая копия «30.0» за ним не пойдёт.

        Сверка по значению здесь бесполезна — в бумажной колонке
        `max_payback_days` и есть 30.0, поэтому литерал совпал бы с политикой и
        молчал (класс, дважды промолчавший в цикле #502).
        """
        original = R.TriggerParams
        try:
            R.TriggerParams = type(
                "_Loud", (), {"for_mode": staticmethod(
                    lambda: TriggerParams(max_payback_days=99.0))})
            rep = _tree().run()
        finally:
            R.TriggerParams = original
        self.assertEqual(rep["substitution"]["max_payback_days"], 99.0)
        self.assertIn("99.0", rep["provenance"]["params"])

    def test_the_finding_threshold_MOVES_with_the_gate_margin(self):
        """Порог находки — ЗАЗОР ГЕЙТА, а не подобранное число.

        Один и тот же перекос стоимости при РАЗНЫХ зазорах обязан давать разные
        вердикты: у короткого payback зазор велик (ошибка внутри него ⇒ WARN),
        у длинного зазор мал (та же ошибка его превосходит ⇒ CRITICAL).
        Константа в этом месте на такую пару не отреагирует.
        """
        def kinds(payback):
            rep = _tree(**{"data/allocation_rationale.json":
                           _rationale(payback=payback)}).run()
            return {f["kind"] for f in rep["findings"]}

        wide = kinds(4.0)     # зазор ×7.5 — ошибка ×0.51 внутри него
        narrow = kinds(23.11)  # зазор ×1.298 — та же ошибка его превосходит
        self.assertIn("cost_error_within_the_deciding_margin", wide)
        self.assertNotIn("cost_error_exceeds_the_deciding_margin", wide)
        self.assertIn("cost_error_exceeds_the_deciding_margin", narrow)

    def test_module_declares_no_cost_literal_of_its_own(self):
        """Все три компоненты — из `cost_model`, а не из копии в этом файле."""
        from spa_core.backtesting.tier1 import cost_model
        self.assertIs(R.SLIPPAGE_BPS_STABLE, cost_model.SLIPPAGE_BPS_STABLE)
        self.assertIs(R.BRIDGE_BPS, cost_model.BRIDGE_BPS)
        self.assertIs(R.GAS_USD_PER_POSITION_CHANGE,
                      cost_model.GAS_USD_PER_POSITION_CHANGE)


class TestSlippageCheckIsAnAssumptionAndSaysSo(unittest.TestCase):
    def test_modelled_slippage_never_rises_above_WARN(self):
        """Модель над наблюдённым TVL — ДОПУЩЕНИЕ: коэффициент k такой же литерал.

        Поднять её до CRITICAL значило бы выдать модель за измерение — ровно та
        подмена, ради которой сторож написан.
        """
        # Тонкие пулы (все шесть — чуть выше TVL-floor) ⇒ модельный слиппедж
        # кратно выше плоских 8 bps.
        thin = {"adapters": [{"protocol": k, "tvl_usd": 6_000_000.0,
                              "tvl_source": "live"} for k in _LIVE_TVL]}
        rep = _tree(**{"data/adapter_orchestrator_status.json": thin}).run()
        slip = [f for f in rep["findings"]
                if f["kind"] == "modelled_slippage_above_the_flat_charge"]
        self.assertEqual(len(slip), 1)
        self.assertEqual(slip[0]["severity"], "WARN")
        self.assertIn("ДОПУЩЕНИЕ", slip[0]["message"])

    def test_literal_tvl_is_not_a_denominator(self):
        """Порядок ADR-053: литеральный TVL знаменателем не является."""
        rep = _tree(**{"data/adapter_orchestrator_status.json":
                       _orch(tvl_source="static")}).run()
        self.assertEqual(rep["overall"], "UNCHECKED")
        self.assertTrue(any("TVL там не наблюдён" in u for u in rep["unchecked"]))
        for row in rep["slippage_check"]["per_leg"]:
            self.assertFalse(row["measured"])

    def test_slippage_model_is_reused_not_reimplemented(self):
        from spa_core.paper_trading import liquidity_depth_analyzer as L
        self.assertIs(R._compute_slippage_bps, L._compute_slippage_bps)


class TestFreshnessIsJudgedByTheProducersOwnSLO(unittest.TestCase):
    def test_stale_observation_is_named(self):
        rep = _tree(**{"data/gas_price_history.json": _gas_doc(age_hours=48.0)}).run()
        kinds = {f["kind"] for f in rep["findings"]}
        self.assertIn("observed_gas_is_stale", kinds)

    def test_slo_comes_from_the_manifest(self):
        slo, prov = R.gas_slo_hours(
            "/root", lambda p: _manifest(slo=1.5))
        self.assertEqual(slo, 1.5)
        self.assertIn("slo_hours", prov)

    def test_no_manifest_entry_means_freshness_is_NOT_judged_not_invented(self):
        """Нет дома у порога ⇒ свежесть не судится; выдуманного числа здесь нет."""
        slo, prov = R.gas_slo_hours("/root", lambda p: {"artifacts": []})
        self.assertIsNone(slo)
        self.assertIn("нет записи", prov)
        rep = _tree(**{"architecture/manifest.json": {"artifacts": []},
                       "data/gas_price_history.json": _gas_doc(age_hours=48.0)}).run()
        kinds = {f["kind"] for f in rep["findings"]}
        self.assertNotIn("observed_gas_is_stale", kinds)

    def test_clock_is_an_input(self):
        """Часы инъектируются: тот же снимок при разных `now` даёт разный возраст."""
        doc = _gas_doc(age_hours=1.0)
        a = R.observed_gas_usd_per_leg(doc, now=_NOW)
        b = R.observed_gas_usd_per_leg(doc, now=_NOW + dt.timedelta(hours=10))
        self.assertEqual(a["chains"]["ethereum"]["age_hours"], 1.0)
        self.assertEqual(b["chains"]["ethereum"]["age_hours"], 11.0)

    def test_run_ITSELF_uses_the_injected_clock_not_the_wall(self):
        """Инъекция обязана доходить до `run`, а не только до пробы.

        «Половина инъекции» — та же бомба, что её отсутствие
        (`.claude/rules/deployment.md`, замер #453): часы приняты параметром, а
        внутри всё равно спрошена живая машина. На настенных часах отметка
        отчёта не совпала бы с инъектированной, а свежий снимок стал бы
        протухшим на десятилетия.
        """
        rep = _tree().run()
        self.assertEqual(rep["generated_at"], _NOW.isoformat())
        kinds = {f["kind"] for f in rep["findings"]}
        self.assertNotIn("observed_gas_is_stale", kinds,
                         "чтение сделано 0.5 ч назад ОТ ИНЪЕКТИРОВАННЫХ часов")
        # Те же байты, часы сдвинуты вперёд ⇒ то же чтение обязано протухнуть.
        late = _tree()
        rep_late = R.run(root=late.root, write=False, data_dir=late.data,
                         now=_NOW + dt.timedelta(hours=48), reader=late.read)
        self.assertIn("observed_gas_is_stale",
                      {f["kind"] for f in rep_late["findings"]})


class TestWiring(unittest.TestCase):
    """Проводка: у артефакта должен быть ДОМ (две записи манифеста) и ПОТРЕБИТЕЛЬ.

    Удаление ЛЮБОЙ из двух записей манифеста не красило ни один существующий
    сторож (замер цикла #502) — поэтому обе проверяются здесь поимённо.
    """

    @staticmethod
    def _repo() -> str:
        return R.REPO_ROOT

    def test_artifact_has_a_top_level_manifest_entry(self):
        with open(os.path.join(self._repo(), "architecture", "manifest.json"),
                  encoding="utf-8") as fh:
            manifest = json.load(fh)
        entry = [a for a in manifest["artifacts"] if a.get("path") == R.REPORT_REL]
        self.assertEqual(len(entry), 1, f"нет записи artifacts[{R.REPORT_REL}]")
        self.assertEqual(entry[0]["producer"], "com.spa.decision_loop")
        self.assertIn("orchestrator_protocol", entry[0]["consumers"])

    def test_artifact_is_in_the_producers_passport(self):
        with open(os.path.join(self._repo(), "architecture", "manifest.json"),
                  encoding="utf-8") as fh:
            manifest = json.load(fh)
        agent = [a for a in manifest["agents"]
                 if a.get("label") == "com.spa.decision_loop"]
        self.assertEqual(len(agent), 1)
        produced = {p["artifact"] for p in agent[0]["produces"]}
        self.assertIn(R.REPORT_REL, produced,
                      "артефакт не объявлен в produces паспорта производителя")

    def test_producer_declares_the_artifact(self):
        from spa_core.monitoring import findings_bridge
        self.assertIn(R.REPORT_REL, findings_bridge.PRODUCES)

    def test_the_producer_actually_CALLS_the_module(self):
        """Объявить производство мало — проводка проверяется ФОРМОЙ ВЫЗОВА.

        `PRODUCES` это обещание; без строки вызова артефакт не появится вовсе, а
        обещание останется зелёным.
        """
        path = os.path.join(os.path.dirname(
            os.path.abspath(__import__("spa_core.monitoring.findings_bridge",
                                       fromlist=["x"]).__file__)),
            "findings_bridge.py")
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn("from spa_core.monitoring import rebalance_cost_evidence", src)
        self.assertIn("rebalance_cost_evidence.run(", src,
                      "мост объявляет артефакт, но не зовёт его производителя")

    def test_the_consumer_branch_exists_by_name(self):
        """Потребитель — шаг 0-офис. Без именной ветки отчёт никто не прочитает.

        Проверяется именно ВЕТКА, а не упоминание имени: имя есть и в таблице
        полей `_SPEC`, поэтому поиск по имени зеленел бы и на снятой ветке —
        отчёт читался бы, но не печатался ни одной строкой.
        """
        path = os.path.join(self._repo(), "scripts", "consume_office_reports.py")
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn('"rebalance_cost_evidence.json": (', src,
                      "отчёта нет в таблице полей шага 0-офис")
        self.assertIn('elif name == "rebalance_cost_evidence.json":', src,
                      "у отчёта нет ПЕЧАТАЮЩЕЙ ветки в шаге 0-офис")


#: Манифест, объявляющий срок годности ТОЛЬКО в паспорте производителя —
#: ровно так, как его объявляет НАСТОЯЩИЙ `architecture/manifest.json`
#: (замер 29.09: `data/gas_price_history.json` живёт в
#: `agents[com.spa.gas_price_agent].produces`, а среди `artifacts[]` его нет).
def _manifest_passport_only(slo=1.5, artifact=None, label="com.spa.gas_price_agent"):
    return {"artifacts": [],
            "agents": [{"label": label,
                        "produces": [{"artifact": artifact or R.GAS_ARTIFACT_REL,
                                      "slo_hours": slo}]}]}


def _manifest_both_homes(gas_slo=1.5, verdict_slo=26.0):
    """Оба дома сразу — газ в верхнем реестре, вердикт в паспорте производителя."""
    return {"artifacts": [{"path": R.GAS_ARTIFACT_REL, "slo_hours": gas_slo}],
            "agents": [{"label": "com.spa.daily_cycle",
                        "produces": [{"artifact": R.VERDICT_ARTIFACT_REL,
                                      "slo_hours": verdict_slo}]}]}


class TestTheHomeOfTheThresholdIsAskedInBOTHPLACES(unittest.TestCase):
    """Авария #730: дом порога искали в ОДНОМ из двух мест, где он живёт.

    `gas_slo_hours` перебирал только верхнеуровневые `artifacts[]` и на
    ненайденное честно отвечал «в манифесте нет записи». Ответ был верен по
    букве и ложен по существу: этот манифест объявляет сроки годности ТАКЖЕ в
    паспорте производителя, и у `data/gas_price_history.json` объявление живёт
    ИМЕННО там — 1,5 ч. Свежесть наблюдения газа не судилась НИ РАЗУ.

    Сторож этого не ловил потому, что фикстура клала SLO в тот дом, куда
    смотрел код: тест отвечал на свой вопрос, а не на нужный.
    """

    def test_the_producers_passport_is_a_home_too(self):
        slo, prov = R.gas_slo_hours("/root", lambda p: _manifest_passport_only())
        self.assertEqual(slo, 1.5)
        self.assertIn("com.spa.gas_price_agent", prov,
                      "провенанс обязан НАЗВАТЬ производителя, а не «где-то в агентах»")

    def test_the_REAL_manifest_declares_the_gas_SLO_and_it_IS_found(self):
        """Тот самый контроль, которого не было: вопрос задан ЖИВОЙ конституции.

        Фикстура доказывает, что разбор умеет прочитать объявление. А вот
        умеет ли он прочитать объявление ЭТОГО репозитория — вопрос другой, и
        до #730 его не задавал никто. Верни поиск в один дом — тест покраснеет
        на настоящем манифесте, а не на выдуманном.
        """
        slo, prov = R.gas_slo_hours(R.REPO_ROOT, R._read_json)
        self.assertIsNotNone(
            slo, f"срок годности наблюдения газа объявлен в живом манифесте, но "
                 f"разбор его не нашёл: {prov}")

    def test_freshness_becomes_judged_when_the_home_is_only_in_the_passport(self):
        """Сквозной контроль аварии: протухшее чтение обязано быть НАЗВАНО."""
        rep = _tree(**{"architecture/manifest.json": _manifest_passport_only(),
                       "data/gas_price_history.json": _gas_doc(age_hours=48.0)}).run()
        kinds = {f["kind"] for f in rep["findings"]}
        self.assertIn("observed_gas_is_stale", kinds)

    def test_two_homes_disagreeing_is_a_THIRD_OUTCOME_not_a_choice(self):
        """Два разных числа — срок годности не объявлен, а ОСПОРЕН."""
        manifest = {"artifacts": [{"path": R.GAS_ARTIFACT_REL, "slo_hours": 1.5}],
                    "agents": [{"label": "com.spa.gas_price_agent",
                                "produces": [{"artifact": R.GAS_ARTIFACT_REL,
                                              "slo_hours": 12.0}]}]}
        slo, prov = R.gas_slo_hours("/root", lambda p: manifest)
        self.assertIsNone(slo, "выбрать одно из двух спорящих чисел молча нельзя")
        self.assertIn("оспорен", prov)
        # И свежесть тогда НЕ судится: спор конституции не есть порог.
        rep = _tree(**{"architecture/manifest.json": manifest,
                       "data/gas_price_history.json": _gas_doc(age_hours=48.0)}).run()
        self.assertNotIn("observed_gas_is_stale",
                         {f["kind"] for f in rep["findings"]})

    def test_two_homes_agreeing_is_one_answer(self):
        manifest = {"artifacts": [{"path": R.GAS_ARTIFACT_REL, "slo_hours": 1.5}],
                    "agents": [{"label": "com.spa.gas_price_agent",
                                "produces": [{"artifact": R.GAS_ARTIFACT_REL,
                                              "slo_hours": 1.5}]}]}
        slo, _ = R.gas_slo_hours("/root", lambda p: manifest)
        self.assertEqual(slo, 1.5)

    def test_no_home_anywhere_still_means_NOT_judged(self):
        slo, prov = R.gas_slo_hours("/root", lambda p: {"artifacts": [], "agents": []})
        self.assertIsNone(slo)
        self.assertIn("artifacts[]", prov)
        self.assertIn("agents[].produces[]", prov,
                      "причина обязана назвать ОБА дома, иначе читатель снова "
                      "решит, что спрошено было всё")

    def test_a_malformed_manifest_is_NOT_an_empty_home(self):
        """«Этот дом пуст» и «этот дом не разобран» чинятся разным (инв. #17).

        Ключ не того типа — поломка конституции, и она обязана дойти до
        читателя причиной, а не превратиться в тихий пустой перебор: иначе
        испорченный манифест читался бы как «объявления просто нет».
        """
        slo, prov = R.gas_slo_hours(
            "/root", lambda p: {"artifacts": [], "agents": {"не": "список"}})
        self.assertIsNone(slo)
        self.assertIn("манифест не прочитан", prov)
        self.assertIn("`agents`", prov)

    def test_the_lookup_is_ONE_and_gas_only_names_its_artifact(self):
        """Второй копии разбора манифеста нет: `gas_slo_hours` — обёртка."""
        a = R.gas_slo_hours("/root", lambda p: _manifest_passport_only())
        b = R.declared_slo_hours("/root", lambda p: _manifest_passport_only(),
                                 R.GAS_ARTIFACT_REL)
        self.assertEqual(a, b)


class TestTheCriterionVerdictIsNotTheSeverityLadder(unittest.TestCase):
    """Вердикт критерия §49 `Costs` читает находки ПО ОСИ, а не поле `overall`.

    `overall` ставит третий исход ВЫШЕ `CRITICAL` намеренно
    (`test_unchecked_outranks_critical`): для здоровья артефакта это верно.
    Для вердикта критерия тот же порядок прятал бы ИЗМЕРЕННОЕ красное за «не
    измерено» — инвариант #17 наизнанку.
    """

    def test_a_found_divergence_survives_an_unchecked(self):
        """Главный контроль цикла: неполнота рядом не отменяет находку.

        Снимок оркестратора убран ⇒ `unchecked` не пуст ⇒ `overall` = UNCHECKED.
        Но расхождение стоимости НАЙДЕНО, и вердикт критерия обязан остаться
        красным: утверждение существования от чужой неполноты не зависит.
        """
        rep = _tree(**{"data/gas_price_history.json":
                       _gas_doc(spot_source="unchecked")}).run()
        self.assertEqual(rep["overall"], "UNCHECKED")
        self.assertEqual(rep["criterion"]["status"], R.CRITERION_UNMEASURED,
                         "без наблюдения газа сравнивать нечем — это третий исход")

        # А теперь то же самое, но наблюдение ЕСТЬ и расхождение НАЙДЕНО:
        # слиппедж не моделируется на части оборота (TVL одной ноги не
        # наблюдён) ⇒ `unchecked` не пуст ⇒ `overall` = UNCHECKED. Сравнение
        # газа при этом состоялось, и находка о нём НАЙДЕНА.
        partial = {"adapters": [a for a in _orch()["adapters"]
                                if a["protocol"] != "pendle"]}
        rep = _tree(**{"data/adapter_orchestrator_status.json": partial}).run()
        self.assertTrue(rep["unchecked"], "фикстура не воспроизвела неполноту")
        self.assertEqual(rep["overall"], "UNCHECKED")
        self.assertIn("cost_error_exceeds_the_deciding_margin",
                      rep["criterion"]["found"])
        self.assertEqual(rep["criterion"]["status"], R.CRITERION_NOT_SATISFIED,
                         "находка существования спрятана за «не измерено» — "
                         "инвариант #17 наизнанку")

    def test_unchecked_without_a_finding_IS_the_third_outcome(self):
        rep = _tree(**{"data/allocation_rationale.json": None}).run()
        self.assertEqual(rep["criterion"]["status"], R.CRITERION_UNMEASURED)
        self.assertEqual(rep["criterion"]["found"], [])

    def test_an_unknown_finding_kind_is_a_THIRD_OUTCOME_not_a_silent_class(self):
        block = R._criterion_block(
            [{"severity": "WARN", "kind": "kind_invented_tomorrow"}], [], None,
            verdict_freshness={"slo_hours": 1.0, "age_hours": 0.0})
        self.assertEqual(block["status"], R.CRITERION_UNMEASURED)
        self.assertIn("kind_invented_tomorrow", block["reason"])

    def test_every_kind_the_module_can_emit_has_an_axis(self):
        """Храповик: вид находки, рождённый кодом, обязан быть объявлен осью.

        Иначе новый вид молча уводил бы вердикт критерия в третий исход — то
        есть выключал бы меру, не тронув ни строчки в ней.
        """
        with open(R.__file__, encoding="utf-8") as fh:
            src = fh.read()
        emitted = set(re.findall(r'"kind":\s*"([a-z_]+)"', src))
        self.assertTrue(emitted, "виды находок не найдены — замер НЕ СОСТОЯЛСЯ")
        self.assertEqual(emitted - set(R.FINDING_AXIS), set())

    def test_an_assumption_does_not_redden_the_criterion(self):
        """Модель над наблюдённым TVL — ДОПУЩЕНИЕ, и вердикта оно не двигает."""
        block = R._criterion_block(
            [{"severity": "WARN", "kind": "modelled_slippage_above_the_flat_charge"}],
            [], None, verdict_freshness={"slo_hours": 26.0, "age_hours": 1.0})
        self.assertEqual(block["status"], R.CRITERION_SATISFIED)
        self.assertEqual(block["assumption"],
                         ["modelled_slippage_above_the_flat_charge"])

    def _green(self, **files):
        base = {"data/gas_price_history.json": _gas_doc(eth_gwei=19.2),
                "architecture/manifest.json": _manifest_both_homes()}
        base.update(files)
        return _tree(**base).run()

    def test_a_clean_and_fresh_tree_is_SATISFIED(self):
        rep = self._green()
        self.assertEqual(rep["criterion"]["found"], [])
        self.assertEqual(rep["unchecked"], [])
        self.assertEqual(rep["criterion"]["status"], R.CRITERION_SATISFIED,
                         rep["criterion"]["reason"])

    def test_the_green_path_asks_the_age_of_the_RECORDED_verdict(self):
        """«Расхождений нет» про вердикт трёхнедельной давности — тишина дерева."""
        old = _rationale()
        old["generated_at"] = _ts(24.0 * 21)
        rep = self._green(**{"data/allocation_rationale.json": old})
        self.assertEqual(rep["criterion"]["status"], R.CRITERION_UNMEASURED)
        self.assertIn("протух", rep["criterion"]["reason"])

    def test_the_green_path_refuses_when_the_verdicts_SLO_has_no_home(self):
        rep = self._green(**{"architecture/manifest.json": _manifest(slo=1.5)})
        self.assertEqual(rep["criterion"]["status"], R.CRITERION_UNMEASURED)
        self.assertIn("дом срока годности", rep["criterion"]["reason"])

    def test_an_unparsable_verdict_stamp_is_NOT_treated_as_fresh(self):
        broken = _rationale()
        broken["generated_at"] = "не-дата"
        rep = self._green(**{"data/allocation_rationale.json": broken})
        self.assertEqual(rep["criterion"]["status"], R.CRITERION_UNMEASURED)
        self.assertIn("НЕ ИЗМЕРЕН", rep["criterion"]["reason"])

    def test_the_unjudged_ratio_is_named_when_the_gate_margin_is_absent(self):
        """Тихий день: отношение ИЗМЕРЕНО, но зазора гейта нет — и это сказано.

        Порога «во сколько раз уже много» вне зазора гейта владелец не
        объявлял; назначить его здесь значило бы завести порог вне его дома.
        Поэтому число печатается, а вердикта из него не выходит.
        """
        quiet = _rationale(payback=None)
        rep = _tree(**{"data/allocation_rationale.json": quiet}).run()
        unjudged = rep["criterion"]["unjudged"]
        self.assertIsNotNone(unjudged, "измеренное отношение не названо вовсе")
        self.assertIsNotNone(unjudged["gas_ratio_charged_over_observed"])
        self.assertEqual(rep["criterion"]["found"], [],
                         "без зазора гейта находки нет — и выдумывать её нельзя")

    def test_the_declaration_names_THIS_criterion_by_anchor(self):
        self.assertTrue(R.CRITERION.startswith("§49 Costs"),
                        "проба сверяет объявление по ЯКОРЮ, а не подстрокой")


if __name__ == "__main__":                                    # pragma: no cover
    unittest.main()
