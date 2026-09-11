"""ADR-335: один пул — один ключ у всех писателей денежного пути.

Урок отменённой ADR-331: каноническим может быть ТОЛЬКО ключ, под которым пул видит
денежный путь (оркестратор → гейт RiskPolicy и провенанс CIO). Тогда каноническим
взяли ключ таблицы пинов, оркестратор его не опрашивал — и гейт ослеп на $20 000.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.orchestrator.adapter_orchestrator import POLLED_ADAPTERS
from spa_core.paper_trading.pool_alias_gate import CANONICAL_KEYS

POLLED = {k for k, _t, _c in POLLED_ADAPTERS}


class TheMoneyPathPollsTheCanonicalKey(unittest.TestCase):
    def test_every_canonical_key_is_polled_by_the_orchestrator(self):
        """СТОРОЖ УРОКА ADR-331: канонический ключ, которого денежный путь не видит, слепит гейт."""
        for alias, canon in CANONICAL_KEYS.items():
            self.assertIn(canon, POLLED, f"{alias}→{canon}: канонический ключ не опрашивается")

    def test_no_alias_is_polled_as_a_second_name(self):
        for alias in CANONICAL_KEYS:
            self.assertNotIn(alias, POLLED, f"{alias} опрашивается вторым именем пула")

    def test_the_fluid_pool_is_polled_once(self):
        self.assertIn("fluid_fusdc", POLLED)
        self.assertNotIn("fluid_usdc", POLLED)


class FluidFUSDCReportsWhatWasObserved(unittest.TestCase):
    """До ADR-335 адаптер отдавал литерал TVL $2 млрд при импортированном и неиспользуемом
    `read_live_tvl_usd` — из-за этого пул и опрашивали другим классом под другим ключом."""

    def _adapter(self, block):
        from spa_core.adapters.fluid_fusdc_adapter import FluidFUSDCAdapter
        td = TemporaryDirectory(); self.addCleanup(td.cleanup)
        d = Path(td.name)
        (d / "adapter_status.json").write_text(
            json.dumps({"adapters": {"fluid_fusdc": block}}), encoding="utf-8")
        a = FluidFUSDCAdapter(); a._data_dir = d
        return a

    def test_live_tvl_and_pool_are_reported_when_observed(self):
        a = self._adapter({"live_apy": 4.33, "live_apy_fresh": True, "apy": 4.33,
                           "tvl_usd": 157962829.0, "tvl_source": "live",
                           "tvl_pool_id": "4438dabc-7f0c-430b-8136-2722711ae663"})
        yi = a.get_yield_info()
        self.assertEqual(yi.tvl_source, "live")
        self.assertAlmostEqual(yi.tvl_usd, 157962829.0)
        self.assertEqual(yi.pool_id, "4438dabc-7f0c-430b-8136-2722711ae663")

    def test_a_static_tvl_is_never_stamped_live(self):
        """ADR-053: литерал живым не штампуется — гейт его не засчитывает."""
        a = self._adapter({"live_apy": 4.33, "live_apy_fresh": True,
                           "tvl_usd": 100000000.0, "tvl_source": "static"})
        yi = a.get_yield_info()
        self.assertIsNone(yi.tvl_source)
        self.assertIsNone(yi.pool_id)

    def test_one_pool_carries_one_risk_score(self):
        from spa_core.adapters.fluid_fusdc_adapter import FluidFUSDCAdapter
        from spa_core.adapters.fluid_usdc_adapter import FluidUSDCAdapter
        self.assertEqual(FluidFUSDCAdapter.RISK_SCORE, FluidUSDCAdapter.RISK_SCORE)


if __name__ == "__main__":
    unittest.main()
