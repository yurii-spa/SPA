"""ADR-238 — сторож тождества обязан ЧИТАТЬ подпись, которую кладёт ADR-233.

Каждая проверка здесь — положительный контроль на ИЗМЕРЕННОЕ состояние
2026-09-06, а не на воображаемое:

* снимок оркестратора (`data/adapter_orchestrator_status.json`) несёт `pool_id`
  на всех путях с ADR-233 (05.09), а `_observations` жёстко клала туда `None`
  с оговоркой «пул-UUID оттуда не приходит никогда» — то есть род `declared`
  был слеп ко ВСЕМ одиннадцати опрашиваемым ключам;
* род `observed` их не спасает: он требует совпадения TVL до 1e-6 и APY до
  0.001 пп, а два производителя опрашивают фид в разные моменты;
* три опрашиваемых ключа ходят в DeFiLlama своим запросом и выбрасывали UUID
  выбранной строки (замер: fluid-lending/Ethereum/USDC — ЧЕТЫРЕ пула с одной
  ставкой 4.45 пп и TVL от $12k до $149M);
* `pendle` личность имеет, но в ДРУГОМ пространстве имён — и поле остаётся
  пустым сознательно.

Время и личность процесса здесь не участвуют: сверка идёт по значениям.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import unittest

from spa_core.adapters._pool_identity import selected_pool_id
from spa_core.monitoring import pool_identity_collision as guard


# UUID замерены на живом фиде DeFiLlama 2026-09-06 — это не выдуманные строки.
FLUID_USDC_POOL = "4438dabc-7f0c-430b-8136-2722711ae663"   # fluid-lending/Ethereum/USDC $149.1M
MORPHO_ETH_POOL = "931ea9be-5f4d-428e-beaf-205fc5b4e2b5"   # morpho-blue/Ethereum/STEAKUSDC
MORPHO_BASE_POOL = "ba68527f-8ec2-4c55-827a-8f4673ae047c"  # morpho-blue/Base/STEAKUSDC $427.7M
AAVE_BASE_POOL = "7e0661bf-8cf3-45e6-9424-31916d4c7b84"    # aave-v3/Base/USDC $18.5M


def _orch_row(protocol, tvl, apy, pool_id=None):
    row = {"protocol": protocol, "status": "ok", "live_data": True,
           "tvl_source": "live", "tvl_usd": tvl, "apy_pct": apy}
    if pool_id is not None:
        row["pool_id"] = pool_id
    return row


class ObservationsReadTheOrchestratorSignature(unittest.TestCase):
    """Подпись из снимка оркестратора доходит до сверки."""

    def test_pool_id_from_orchestrator_row_is_kept(self):
        obs, unchecked = guard._observations(
            {"adapters": [_orch_row("morpho_blue", 94419311.0, 4.0956, MORPHO_ETH_POOL)]}, {})
        self.assertEqual(obs["morpho_blue"]["pool_id"], MORPHO_ETH_POOL)
        self.assertEqual(obs["morpho_blue"]["source"], "orchestrator")
        self.assertEqual(unchecked, [])

    def test_missing_pool_id_stays_unmeasured_not_invented(self):
        obs, _ = guard._observations(
            {"adapters": [_orch_row("morpho_blue", 94419311.0, 4.0956)]}, {})
        self.assertIsNone(obs["morpho_blue"]["pool_id"])

    def test_blank_pool_id_is_unmeasured(self):
        for blank in ("", "   ", 42, None):
            with self.subTest(blank=blank):
                obs, _ = guard._observations(
                    {"adapters": [_orch_row("morpho_blue", 1.0, 1.0, blank)]}, {})
                self.assertIsNone(obs["morpho_blue"]["pool_id"])


class DeclaredRodSeesWhatObservedRodMisses(unittest.TestCase):
    """АВАРИЯ, которую воспроизводит этот файл.

    Два ключа стоят в ОДНОМ пуле, но их числа сняты в разные секунды — пул
    сдвинулся между двумя запросами. Роду `observed` этого достаточно, чтобы
    промолчать (допуск 1e-6 по TVL). До ADR-238 сторож не говорил НИЧЕГО:
    подпись была, и её выбрасывали. После — находка есть, и она `declared`.
    """

    def _pair_apart_in_time(self):
        # TVL расходится на 0.9 % — далеко за 1e-6, — а пул ОДИН и тот же.
        return {"adapters": [
            _orch_row("fluid_usdc", 150402432.0, 4.16, FLUID_USDC_POOL),
            _orch_row("fluid_fusdc", 149057132.0, 4.45, FLUID_USDC_POOL),
        ]}

    def test_observed_rod_is_blind_to_this_pair(self):
        obs, _ = guard._observations(self._pair_apart_in_time(), {})
        self.assertEqual(guard._observed_groups(obs), [],
                         "род `observed` не должен видеть пару, снятую в разные такты")

    def test_declared_rod_finds_it_once_the_signature_is_read(self):
        obs, _ = guard._observations(self._pair_apart_in_time(), {})
        pairs, named_by = guard._declared_pairs(obs, {}, {})
        self.assertEqual(pairs, {FLUID_USDC_POOL: ["fluid_fusdc", "fluid_usdc"]})
        self.assertEqual(named_by[FLUID_USDC_POOL]["fluid_usdc"],
                         guard.NAMED_BY_OBSERVATION)

    def test_positive_control_the_old_behaviour_would_be_silent(self):
        """Контроль на украшение: обнули подпись — и находка исчезает.

        Ровно это и делала прежняя строка ``"pool_id": None``.
        """
        obs, _ = guard._observations(self._pair_apart_in_time(), {})
        for row in obs.values():
            row["pool_id"] = None
        pairs, _ = guard._declared_pairs(obs, {}, {})
        self.assertEqual(pairs, {}, "с выброшенной подписью сторож обязан молчать — "
                                    "именно этим дефект и был незаметен")

    def test_same_tick_pair_is_found_by_both_rods(self):
        """Контроль на ложное срабатывание в обратную сторону: одинаковые числа
        по-прежнему находит и `observed`."""
        obs, _ = guard._observations({"adapters": [
            _orch_row("fluid_usdc", 149057132.0, 4.45, FLUID_USDC_POOL),
            _orch_row("fluid_fusdc", 149057132.0, 4.45, FLUID_USDC_POOL),
        ]}, {})
        self.assertEqual(guard._observed_groups(obs),
                         [["fluid_fusdc", "fluid_usdc"]])
        pairs, _ = guard._declared_pairs(obs, {}, {})
        self.assertIn(FLUID_USDC_POOL, pairs)

    def test_different_pools_are_not_a_collision(self):
        """Контроль на ложное срабатывание: разные пулы — не находка."""
        obs, _ = guard._observations({"adapters": [
            _orch_row("morpho_blue", 94419311.0, 4.0956, MORPHO_ETH_POOL),
            _orch_row("morpho_blue_base", 427734956.0, 4.7368, MORPHO_BASE_POOL),
        ]}, {})
        pairs, _ = guard._declared_pairs(obs, {}, {})
        self.assertEqual(pairs, {})


class SignaturesInDisputeAreNotMeasured(unittest.TestCase):
    """Два артефакта называют РАЗНЫЕ пулы за одним ключом — это `aave_v3`
    (ADR-233). Выбрать сторону сторож не вправе."""

    def _dispute(self):
        return guard._observations(
            {"adapters": [_orch_row("aave_v3", 58396614.0, 5.2651, "umbrella-uuid")]},
            {"adapters": {"aave_v3": {"tvl_source": "live", "tvl_usd": 1500000.0,
                                      "live_apy": 2.5804,
                                      "tvl_pool_id": "prime-instance-uuid"}}})

    def test_disputed_key_loses_its_signature(self):
        obs, _ = self._dispute()
        self.assertIsNone(obs["aave_v3"]["pool_id"])

    def test_dispute_is_said_out_loud(self):
        _, unchecked = self._dispute()
        self.assertEqual(len(unchecked), 1)
        self.assertIn("aave_v3", unchecked[0])
        self.assertIn("НЕ ИЗМЕРЕНА", unchecked[0])

    def test_agreeing_artifacts_are_not_a_dispute(self):
        obs, unchecked = guard._observations(
            {"adapters": [_orch_row("fluid_usdc", 1.0, 1.0, FLUID_USDC_POOL)]},
            {"adapters": {"fluid_usdc": {"tvl_source": "live", "tvl_usd": 1.0,
                                         "live_apy": 1.0,
                                         "tvl_pool_id": FLUID_USDC_POOL}}})
        self.assertEqual(obs["fluid_usdc"]["pool_id"], FLUID_USDC_POOL)
        self.assertEqual(unchecked, [])

    def test_adapter_status_still_completes_a_silent_orchestrator(self):
        obs, unchecked = guard._observations(
            {"adapters": [_orch_row("fluid_usdc", 1.0, 1.0)]},
            {"adapters": {"fluid_usdc": {"tvl_source": "live", "tvl_usd": 1.0,
                                         "live_apy": 1.0,
                                         "tvl_pool_id": FLUID_USDC_POOL}}})
        self.assertEqual(obs["fluid_usdc"]["pool_id"], FLUID_USDC_POOL)
        self.assertEqual(unchecked, [])


class SelectedPoolIdHelper(unittest.TestCase):
    def test_uuid_of_the_chosen_row(self):
        self.assertEqual(selected_pool_id({"pool": FLUID_USDC_POOL, "tvlUsd": 1.0}),
                         FLUID_USDC_POOL)

    def test_third_outcome_for_anything_unusable(self):
        for bad in (None, {}, {"pool": ""}, {"pool": "  "}, {"pool": 7}, [], "x"):
            with self.subTest(bad=bad):
                self.assertIsNone(selected_pool_id(bad))


class PolledAdaptersDeclareTheirPool(unittest.TestCase):
    """Три ключа, ходящие в DeFiLlama СВОИМ запросом, называют выбранный пул."""

    def test_aave_v3_base_names_the_selected_pool(self):
        from spa_core.adapters.aave_v3_base_adapter import AaveV3BaseAdapter
        a = AaveV3BaseAdapter()
        a._fetch_live_pool = lambda: {"pool": AAVE_BASE_POOL, "tvlUsd": 18500468.0,
                                      "apy": 3.71928}
        self.assertEqual(a.get_yield_info().pool_id, AAVE_BASE_POOL)

    def test_morpho_blue_base_names_the_selected_pool(self):
        from spa_core.adapters.morpho_blue_base_adapter import MorphoBlueBaseAdapter
        a = MorphoBlueBaseAdapter()
        a._fetch_live_pool = lambda: {"pool": MORPHO_BASE_POOL, "tvlUsd": 427667492.0,
                                      "apy": 4.23356}
        self.assertEqual(a.get_yield_info().pool_id, MORPHO_BASE_POOL)

    def test_refused_fetch_leaves_identity_unmeasured(self):
        from spa_core.adapters.aave_v3_base_adapter import AaveV3BaseAdapter
        a = AaveV3BaseAdapter()
        a._fetch_live_pool = lambda: None
        self.assertIsNone(a.get_yield_info().pool_id)

    def test_fluid_names_the_pool_when_defillama_ranked_the_row(self):
        from spa_core.adapters.fluid_usdc_adapter import FluidUSDCAdapter
        a = FluidUSDCAdapter()
        a._fetch_primary = lambda: {"apy": None, "utilization": None}
        a._fetch_defillama = lambda: {"apy": 0.0445, "tvl": 149057132.0,
                                      "pool_id": FLUID_USDC_POOL}
        info = a.get_yield_info()
        self.assertEqual(info.pool_id, FLUID_USDC_POOL)
        self.assertEqual(info.tvl_source, "live")

    def test_fluid_refuses_to_sign_a_rate_it_read_elsewhere(self):
        """Ставку дал собственный API Fluid, а пул — DeFiLlama: подписать
        чужое наблюдение нельзя, личность НЕ ИЗМЕРЕНА."""
        from spa_core.adapters.fluid_usdc_adapter import FluidUSDCAdapter
        a = FluidUSDCAdapter()
        a._fetch_primary = lambda: {"apy": 0.058, "utilization": 0.9}
        a._fetch_defillama = lambda: {"apy": 0.0445, "tvl": 149057132.0,
                                      "pool_id": FLUID_USDC_POOL}
        rec = a.fetch()
        self.assertEqual(rec["source"], "fluid_api")
        self.assertIsNone(rec["pool_id"])
        self.assertIsNone(a.get_yield_info().pool_id)


class PendleKeepsItsNamespaceApart(unittest.TestCase):
    """Личность есть, но не того рода — поле пустое СОЗНАТЕЛЬНО."""

    def test_pendle_does_not_put_a_market_address_into_a_uuid_field(self):
        from spa_core.adapters import pendle_adapter as pa
        from spa_core.adapters.pendle_pt import PendleMarketData
        market = PendleMarketData(
            market_address="0x" + "ab" * 20,
            name="PT-sUSDe-25DEC2026", underlying_asset="sUSDe",
            pt_apy=14.0414, underlying_apy=9.0,
            maturity_date="2026-12-25", days_to_maturity=110,
            tvl_usd=30_000_000.0, is_expired=False,
            liquidity_usd=30_000_000.0, implied_apy=14.0414,
        )
        a = pa.PendleAdapter()
        a._fetch_eligible = lambda: [market]
        info = a.get_yield_info()
        self.assertEqual(info.protocol, "pendle")
        self.assertIsNone(
            info.pool_id,
            "адрес рынка Pendle — ДРУГОЕ пространство имён, чем UUID DeFiLlama; "
            "положив его в это поле, сторож сравнил бы несравнимое")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
