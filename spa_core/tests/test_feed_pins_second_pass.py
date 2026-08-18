"""Second-pass feed wiring (agent-blocked-protocols-need-live-feeds, 2026-08-05).

The first wiring pass (ADR-064) left six of the eleven capital-blocked
protocols unobserved. This pass re-measured each against the live /pools feed
and split them honestly:

* ``sdai`` / ``scrvusd`` / ``extra_finance_base`` — the first pass MISSED the
  real pool (post-rebrand project names: sDAI lives under "sky-lending", the
  Curve Savings vault under "crvusd"; XLend under "extra-finance-xlend"). Each
  is now pinned by UUID, verified against the pool's ``underlyingTokens``.
* ``frax`` / ``stusd`` / ``wusdm`` — no honest pool exists in the feed. They
  MUST remain unobserved: wiring a near-miss (the SFRAX pool, an LP pair, an
  alien USDM token) would rank capital by another asset's number, which is the
  exact fabrication class the evidence gate exists to stop.

Both directions are pinned here. FakeFeed only — no test touches the network
(DeFiLlama gzip fails offline; rule .claude/rules/adapters.md).
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from spa_core.adapters.scrvusd_adapter import ScrvusdAdapter
from spa_core.adapters.sdai_adapter import SdaiAdapter
from spa_core.adapters.status_reader import read_live_tvl_usd, tvl_floor_verdict
from spa_core.monitoring import adapter_status_generator as gen

_FETCH = "spa_core.monitoring.adapter_status_generator._fetch_defillama"

# Порог RiskPolicy. Держится здесь одним литералом только для читаемости теста;
# сам вердикт получает его параметром, чтобы файл не завёл СВОЮ копию политики.
_FLOOR_USD = 5_000_000.0

# The three pools as the live feed reported them on 2026-08-05 (shape verbatim,
# numbers rounded). The UUIDs are the pinned identities; a test built on other
# ids could pass while the pins point at nothing.
_SDAI_POOL = {
    "pool": "c8a24fee-ec00-4f38-86c0-9f6daebc4225",
    "project": "sky-lending", "chain": "Ethereum", "symbol": "SDAI",
    "tvlUsd": 210_027_967.0, "apy": 1.25,
}
_SCRVUSD_POOL = {
    "pool": "5fd328af-4203-471b-bd16-1705c726d926",
    "project": "crvusd", "chain": "Ethereum", "symbol": "SCRVUSD",
    "tvlUsd": 18_682_400.0, "apy": 1.10226,
}
_XLEND_POOL = {
    "pool": "bc6b7193-da3c-43e3-8c7b-4c9508eec893",
    "project": "extra-finance-xlend", "chain": "Base", "symbol": "USDC",
    "tvlUsd": 344_947.0, "apy": 1.51308,
}

# Near-miss pools that the UNWIRED keys must NOT resolve to. Each one is a real
# record from the same scan — the exact temptation the first pass refused.
_SFRAX_POOL = {  # ``frax`` must not inherit sfrax's pool (hidden concentration)
    "pool": "55de30c3-bf9f-4d4e-9e0b-536a8ef5ab35",
    "project": "frax", "chain": "Ethereum", "symbol": "SFRAX",
    "tvlUsd": 65_149_746.0, "apy": 1.24973,
}
_SCRVUSD_LP_POOL = {  # the LP pair the first pass rightly refused for scrvusd
    "pool": "5c4940c7-c193-440d-b95e-9148d017e12c",
    "project": "curve-dex", "chain": "Ethereum", "symbol": "REUSD-SCRVUSD",
    "tvlUsd": 7_748_795.0, "apy": 3.56671,
}
_ALIEN_USDM_POOL = {  # a different USDM (Cardano lending), not Mountain wUSDM
    "pool": "ce3021c9-af52-46b0-a61a-3e92acdfd79b",
    "project": "liqwid", "chain": "Cardano", "symbol": "USDM",
    "tvlUsd": 647_362.0, "apy": 9.09415,
}

_ALL_POOLS = [
    _SDAI_POOL, _SCRVUSD_POOL, _XLEND_POOL,
    _SFRAX_POOL, _SCRVUSD_LP_POOL, _ALIEN_USDM_POOL,
]

_REGISTRY = {
    "adapters": {
        key: {"protocol": key, "tier": 2, "fallback_apy": 0.05,
              "chain": "ethereum", "per_protocol_cap": 0.2, "status": "active"}
        for key in ("sdai", "scrvusd", "extra_finance_base",
                    "frax", "stusd", "wusdm", "sfrax")
    }
}


class _GenBase(unittest.TestCase):
    """generate() against a temp registry/output — no network, no repo data/."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.data_dir = Path(self._tmp.name)
        self.registry = self.data_dir / "adapter_registry.json"
        self.output = self.data_dir / "adapter_status.json"
        self.registry.write_text(json.dumps(_REGISTRY), encoding="utf-8")

    def _generate(self, pools):
        with patch(_FETCH, return_value=pools):
            return gen.generate(registry_path=self.registry, output_path=self.output)


class TestNewPinsResolveLive(_GenBase):
    """Each newly pinned key yields a live, pinned, auditable observation."""

    _EXPECT = {
        "sdai":               (_SDAI_POOL, 1.25),
        "scrvusd":            (_SCRVUSD_POOL, 1.10226),
        "extra_finance_base": (_XLEND_POOL, 1.51308),
    }

    def test_pins_registered(self):
        for key, (pool, _) in self._EXPECT.items():
            with self.subTest(key=key):
                self.assertEqual(gen._POOL_ID_LOOKUP.get(key), pool["pool"])

    def test_live_apy_and_pinned_tvl(self):
        doc = self._generate(_ALL_POOLS)
        for key, (pool, apy) in self._EXPECT.items():
            with self.subTest(key=key):
                row = doc["adapters"][key]
                self.assertAlmostEqual(row["live_apy"], round(apy, 4))
                self.assertTrue(row["live_apy_fresh"])
                # Pinned match ⇒ the TVL is an observation, with the pool UUID
                # recorded so an auditor can re-fetch and reproduce it.
                self.assertEqual(row["pool_match"], "pinned")
                self.assertEqual(row["tvl_source"], "live")
                self.assertEqual(row["tvl_usd"], pool["tvlUsd"])
                self.assertEqual(row["tvl_pool_id"], pool["pool"])

    def test_xlend_observed_tvl_is_below_the_floor(self):
        """The point of pinning a tiny pool: the honest number FAILS the gate.

        The adapter's own constant claims $15M ("> $5M — RiskPolicy floor ok");
        the observation says $0.34M. If this assertion ever starts failing
        upward, the pool grew — re-verify before trusting the pin.
        """
        doc = self._generate(_ALL_POOLS)
        self.assertLess(doc["adapters"]["extra_finance_base"]["tvl_usd"], 5_000_000)

    def test_pool_absent_from_feed_yields_none_not_a_mock(self):
        """Pin present, pool gone from the feed → None. Never a substitute."""
        doc = self._generate([_SFRAX_POOL])  # feed answers, but without our pools
        for key in self._EXPECT:
            with self.subTest(key=key):
                row = doc["adapters"][key]
                self.assertIsNone(row["live_apy"])
                self.assertEqual(row["tvl_source"], "static")
                self.assertIsNone(row["tvl_pool_id"])


class TestUnwiredStayUnwired(_GenBase):
    """frax / stusd / wusdm: no honest pool ⇒ no observation, even with bait."""

    _UNWIRED = ("frax", "stusd", "wusdm")

    def test_no_pin_and_no_hint(self):
        for key in self._UNWIRED:
            with self.subTest(key=key):
                self.assertNotIn(key, gen._POOL_ID_LOOKUP)
                self.assertNotIn(key, gen._DEFILLAMA_HINTS)

    def test_near_miss_pools_are_not_picked_up(self):
        """The feed contains every temptation; the unwired keys take none.

        ``frax`` must not read the SFRAX vault, ``wusdm`` must not read the
        Cardano USDM, nobody reads the REUSD-SCRVUSD LP. A regression here means
        capital would be ranked by another asset's yield.
        """
        doc = self._generate(_ALL_POOLS)
        for key in self._UNWIRED:
            with self.subTest(key=key):
                row = doc["adapters"][key]
                self.assertIsNone(row["live_apy"])
                self.assertEqual(row["tvl_source"], "static")

    def test_lp_pool_is_nobodys_evidence(self):
        """No key in the whole document claims the REUSD-SCRVUSD LP pool."""
        doc = self._generate(_ALL_POOLS)
        for key, row in doc["adapters"].items():
            self.assertNotEqual(
                row.get("tvl_pool_id"), _SCRVUSD_LP_POOL["pool"],
                f"{key} pinned to the LP pair the wiring explicitly refused")


class TestFloorVerdictRestsOnTheObservation(_GenBase):
    """Порог $5M судится ЖИВЫМ числом — и только им (ADR-053).

    Замер 2026-08-18. Файл выше уже доказывал, что пин даёт ``tvl_source="live"``,
    а незакреплённый ключ остаётся ``static``. На нужный вопрос — «чем в итоге
    судится гейт» — он не отвечал: между полем ``tvl_source`` и вердиктом стоит
    ``tvl_floor_verdict``, и его поведение для этой шестёрки не было закреплено
    НИГДЕ. Для четырёх аавовских пинов вне Ethereum такой контроль есть
    (``test_feed_pins_aave_non_ethereum.py``), для второго прохода — не было.

    Разница не косметическая: литералы незакреплённых ключей — ``frax`` $100M,
    ``stusd`` $200M, ``wusdm`` $400M — все ВЫШЕ порога. Если вердикт когда-нибудь
    начнёт читать ``tvl_usd`` без оглядки на ``tvl_source``, эти трое молча
    «пройдут» гейт, которого никто не измерял, и ни один из существующих тестов
    этого не увидит.

    Обе стороны закреплены намеренно: только «живое проходит» пропустило бы
    производителя, который штампует pass всем подряд; только «незакреплённое не
    проходит» — того, кто отказывает всем.
    """

    def _write_status(self):
        doc = self._generate(_ALL_POOLS)
        gen.write(doc, self.output)

    def test_live_observation_clears_the_floor_by_its_own_number(self):
        """sdai $210.0M и scrvusd $18.68M проходят — потому что НАБЛЮДЕНЫ."""
        self._write_status()
        for key, observed in (("sdai", _SDAI_POOL["tvlUsd"]),
                              ("scrvusd", _SCRVUSD_POOL["tvlUsd"])):
            with self.subTest(key=key):
                self.assertEqual(read_live_tvl_usd(key, data_dir=self.data_dir), observed)
                self.assertIs(
                    tvl_floor_verdict(key, data_dir=self.data_dir, floor_usd=_FLOOR_USD),
                    True)

    def test_observed_below_the_floor_is_a_refusal_not_a_pass(self):
        """extra_finance_base: константа адаптера $15M, наблюдение $0.34M.

        Отрицательный исход — это и есть измерение (ADR-076). Гейт обязан
        вернуть ровно False, а не None: пул наблюдён, он просто мал.
        """
        self._write_status()
        self.assertIs(
            tvl_floor_verdict("extra_finance_base", data_dir=self.data_dir,
                              floor_usd=_FLOOR_USD),
            False)

    def test_unwired_key_is_UNMEASURED_though_its_literal_is_huge(self):
        """frax/stusd/wusdm: вердикт None, хотя литерал втрое-восьмикратно выше порога.

        Это и есть «never stamp live on a constant», доведённое до вердикта:
        ``None`` означает «не измеряли», и аллокатор по ADR-053 замораживает
        такой пул, а не финансирует его.
        """
        self._write_status()
        for key in ("frax", "stusd", "wusdm"):
            with self.subTest(key=key):
                self.assertIsNone(read_live_tvl_usd(key, data_dir=self.data_dir))
                self.assertIsNone(
                    tvl_floor_verdict(key, data_dir=self.data_dir, floor_usd=_FLOOR_USD),
                    f"{key}: литерал не имеет права выносить вердикт по порогу")

    def test_feed_down_leaves_every_verdict_unmeasured(self):
        """Фид не ответил — ни один ключ не «проходит» и ни один не «падает».

        Сетевой сбой не смеет выглядеть ни разрешением, ни отказом.
        """
        doc = self._generate(None)
        gen.write(doc, self.output)
        for key in _REGISTRY["adapters"]:
            with self.subTest(key=key):
                self.assertIsNone(
                    tvl_floor_verdict(key, data_dir=self.data_dir, floor_usd=_FLOOR_USD))


class TestAdapterEndToEnd(_GenBase):
    """generator → adapter_status.json → adapter: the number arrives intact."""

    def test_sdai_and_scrvusd_read_the_observation(self):
        doc = self._generate(_ALL_POOLS)
        gen.write(doc, self.output)
        self.assertAlmostEqual(
            SdaiAdapter(data_dir=self.data_dir).get_apy(), 1.25)
        self.assertAlmostEqual(
            ScrvusdAdapter(data_dir=self.data_dir).get_apy(), 1.1023, places=4)

    def test_without_observation_adapters_return_none(self):
        doc = self._generate(None)  # feed unreachable this run, no prior file
        gen.write(doc, self.output)
        self.assertIsNone(SdaiAdapter(data_dir=self.data_dir).get_apy())
        self.assertIsNone(ScrvusdAdapter(data_dir=self.data_dir).get_apy())


if __name__ == "__main__":
    unittest.main()
