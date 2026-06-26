"""Tests for the canonical APY-unit contract (Architect P3-5).

Proves the latent 100x hazard is closed:
  * a percent-returning adapter and a decimal-returning adapter yield the SAME
    correct decimal via the canonical accessor ``get_yield_info().apy``;
  * the registry no longer 100x-deflates a percent-adapter;
  * a true sub-1% APY (btc_lending 0.5%) is NOT read as 50% by the shared
    normalizer;
  * the decimal sane-band assertion catches a deliberately-misconfigured
    5000% adapter (fail-closed → None).
"""
from __future__ import annotations

import unittest

from spa_core.adapters.base_adapter import BaseAdapter, YieldInfo
from spa_core.adapters.apy_contract import (
    APY_DECIMAL_SOFT_CAP,
    canonical_apy_decimal,
    canonical_apy_pct,
    validate_apy_decimal,
)


# ── Two adapters that report the SAME real yield (5.0%) via different raw units ──

class _PercentRawAdapter(BaseAdapter):
    """Raw get_apy() is PERCENT (5.0); get_yield_info().apy normalises to decimal."""

    PROTOCOL = "percent_raw"

    def get_apy(self):           # percent units (5.0 == 5%)
        return 5.0

    def get_yield_info(self):
        return YieldInfo(
            protocol=self.PROTOCOL, asset="USDC", apy=self.get_apy() / 100.0,
            tvl_usd=1e7, tier="T1", risk_score=0.2,
        )


class _DecimalRawAdapter(BaseAdapter):
    """Raw get_apy() is DECIMAL (0.05); get_yield_info().apy is the same decimal."""

    PROTOCOL = "decimal_raw"

    def get_apy(self):           # decimal units (0.05 == 5%)
        return 0.05

    def get_yield_info(self):
        return YieldInfo(
            protocol=self.PROTOCOL, asset="USDC", apy=self.get_apy(),
            tvl_usd=1e7, tier="T1", risk_score=0.2,
        )


class _Misconfigured5000Adapter(BaseAdapter):
    """Misconfigured: leaks a PERCENT value (50.0 == 5000%) into the decimal accessor."""

    PROTOCOL = "misconfigured_5000"

    def get_apy(self):
        return 50.0

    def get_yield_info(self):
        # BUG: should have divided by 100; 50.0 as a "decimal" == 5000%.
        return YieldInfo(
            protocol=self.PROTOCOL, asset="USDC", apy=50.0,
            tvl_usd=1e7, tier="T2", risk_score=0.5,
        )


class TestCanonicalAccessorParity(unittest.TestCase):
    def test_percent_and_decimal_adapters_agree_via_canonical(self):
        p = canonical_apy_decimal(_PercentRawAdapter())
        d = canonical_apy_decimal(_DecimalRawAdapter())
        self.assertAlmostEqual(p, 0.05, places=9)
        self.assertAlmostEqual(d, 0.05, places=9)
        self.assertAlmostEqual(p, d, places=9)

    def test_canonical_pct_converts_once(self):
        self.assertAlmostEqual(canonical_apy_pct(_PercentRawAdapter()), 5.0, places=9)
        self.assertAlmostEqual(canonical_apy_pct(_DecimalRawAdapter()), 5.0, places=9)


class TestSaneBandFailClosed(unittest.TestCase):
    def test_misconfigured_5000pct_rejected(self):
        # 50.0 as a decimal == 5000% > soft-cap 1.0 → fail-closed None.
        self.assertIsNone(canonical_apy_decimal(_Misconfigured5000Adapter()))
        self.assertIsNone(canonical_apy_pct(_Misconfigured5000Adapter()))

    def test_validate_band_edges(self):
        self.assertEqual(validate_apy_decimal(0.0, protocol="x"), 0.0)   # 0% legit
        self.assertAlmostEqual(validate_apy_decimal(0.05, protocol="x"), 0.05)
        self.assertEqual(
            validate_apy_decimal(APY_DECIMAL_SOFT_CAP, protocol="x"),
            APY_DECIMAL_SOFT_CAP,
        )  # exactly 100% accepted (soft-cap inclusive)
        self.assertIsNone(validate_apy_decimal(1.0001, protocol="x"))    # >100% rejected
        self.assertIsNone(validate_apy_decimal(-0.01, protocol="x"))     # negative
        self.assertIsNone(validate_apy_decimal(None, protocol="x"))
        self.assertIsNone(validate_apy_decimal(True, protocol="x"))      # bool guard
        self.assertIsNone(validate_apy_decimal(float("nan"), protocol="x"))
        self.assertIsNone(validate_apy_decimal(float("inf"), protocol="x"))

    def test_no_get_yield_info_fails_closed(self):
        class _NoCanonical:
            def get_apy(self):
                return 0.05

        self.assertIsNone(canonical_apy_decimal(_NoCanonical()))
        self.assertIsNone(canonical_apy_decimal(None))


class TestRegistryNo100xDeflation(unittest.TestCase):
    """The former unit-blind get_apy()*100 step is gone; a percent-adapter that
    exposes the canonical accessor is read correctly (not 100x-deflated)."""

    def test_percent_adapter_not_deflated_by_registry(self):
        from spa_core.adapters.adapter_registry import _extract_apy_pct

        # _PercentRawAdapter's get_yield_info().apy == 0.05 (decimal) → 5.0%.
        # Old step-3 would have done get_apy()(=5.0)*100 = 500% OR, for a
        # decimal-only adapter, 0.05*100=5 by luck. The hazard was a percent
        # value sub-1.0; here we confirm the canonical route gives the right 5.0%.
        self.assertAlmostEqual(_extract_apy_pct(_PercentRawAdapter()), 5.0, places=6)

    def test_decimal_adapter_via_registry(self):
        from spa_core.adapters.adapter_registry import _extract_apy_pct

        self.assertAlmostEqual(_extract_apy_pct(_DecimalRawAdapter()), 5.0, places=6)

    def test_registry_rejects_misconfigured_5000(self):
        from spa_core.adapters.adapter_registry import _extract_apy_pct

        # No get_apy_pct, no fetch — only the (out-of-band) canonical accessor.
        self.assertIsNone(_extract_apy_pct(_Misconfigured5000Adapter()))


class TestSharedNormalizerNoSub1Corruption(unittest.TestCase):
    """The shared normalizer must NOT 100x a true sub-1% APY (the v<1.0 trap)."""

    def test_income_common_normalizer_true_half_percent(self):
        from spa_core.strategies._income_common import canonical_adapter_apy_pct

        class _HalfPercentPercentRaw(BaseAdapter):
            # An adapter whose REAL yield is 0.5%. Old heuristic on a percent
            # raw of 0.5 would do 0.5<1.0 → ×100 = 50% (WRONG). Canonical:
            # get_yield_info().apy = 0.005 (decimal) → 0.5% (correct).
            PROTOCOL = "half_pct"

            def get_apy(self):
                return 0.5  # percent units, honest 0.5%

            def get_yield_info(self):
                return YieldInfo(
                    protocol=self.PROTOCOL, asset="USDC", apy=0.005,
                    tvl_usd=1e7, tier="T2", risk_score=0.4,
                )

        pct = canonical_adapter_apy_pct(_HalfPercentPercentRaw())
        self.assertAlmostEqual(pct, 0.5, places=6)   # NOT 50.0

    def test_btc_lending_half_percent_not_read_as_50(self):
        # btc_lending get_apy() is a DECIMAL (0.005 == 0.5%) and get_yield_info()
        # mirrors it. Canonical accessor must yield 0.5%, never 50%.
        from spa_core.strategies._income_common import canonical_adapter_apy_pct

        class _FakeBtcFeed:
            def get_pool(self, project, symbol, chain):
                # DeFiLlama serves apy as percent; 0.5 == 0.5%.
                return {"apy": 0.5, "tvlUsd": 1.2e8}

        from spa_core.adapters.btc_lending import TbtcLendingAdapter

        adapter = TbtcLendingAdapter(feed=_FakeBtcFeed())
        # raw decimal accessor: 0.5 / 100 == 0.005 == 0.5%
        self.assertAlmostEqual(adapter.get_apy(), 0.005, places=9)
        pct = canonical_adapter_apy_pct(adapter)
        self.assertAlmostEqual(pct, 0.5, places=6)   # NOT 50.0
        self.assertLess(pct, 1.0)


if __name__ == "__main__":   # pragma: no cover
    unittest.main()
