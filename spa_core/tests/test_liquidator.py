"""
spa_core/tests/test_liquidator.py — tests for the Cross-Domain / Balance-Sheet Liquidator de-risk.

Covers:
  - collateral classification (LRT / PT / LP / BTC / ETH / stable / exotic / unknown);
  - MarketMonitor parsing of injected /pools rows + filtering to target protocols;
  - OpportunityEstimator: penalty math, the EXIT GAP (illiquid collateral → high addressable,
    deep-DEX collateral → ~0 addressable / atomic-MEV handles it);
  - fail-CLOSED behaviour (bad data, no DEX depth, unknown symbol);
  - determinism (same inputs → identical numbers).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import pytest

from spa_core.strategy_lab.liquidator.market_monitor import (
    CollateralKind,
    MarketMonitor,
    classify_collateral,
    documented_penalty_bps,
)
from spa_core.strategy_lab.liquidator.opportunity_estimator import (
    ATOMIC_LIQUIDATION_FILL_FLOOR,
    OpportunityEstimator,
)


# ── fixtures: injected /pools payloads (no network) ────────────────────────────────────────────
def _pool(project, symbol, tvl, *, chain="Ethereum", exposure="single", apyBase=None,
          underlying=None):
    return {
        "project": project, "symbol": symbol, "tvlUsd": tvl, "chain": chain,
        "exposure": exposure, "apyBase": apyBase, "pool": f"{project}:{symbol}:{chain}",
        "underlyingTokens": underlying or [],
    }


def _dex_pool(project, symbol, tvl, chain="Ethereum"):
    return {"project": project, "symbol": symbol, "tvlUsd": tvl, "chain": chain}


def _payload(rows):
    return {"status": "success", "data": rows}


# A mixed universe: an LRT market (thin/illiquid), a vanilla USDC market (deep), plus DEX pools that
# give USDC deep on-chain depth but the LRT essentially none.
LENDING_ROWS = [
    _pool("morpho-blue", "WEETH", 50_000_000, exposure="single"),      # LRT collateral (long tail)
    _pool("morpho-blue", "USDC", 100_000_000, exposure="single", apyBase=4.2),  # vanilla stable
    _pool("euler-v2", "PT-USDE", 8_000_000, exposure="single"),        # Pendle PT (long tail)
    _pool("euler-v2", "WETH-USDC", 20_000_000, exposure="multi"),      # LP (long tail)
    _pool("aave-v3", "USDC", 500_000_000),                             # NOT a target protocol
]

DEX_ROWS = [
    _dex_pool("uniswap-v3", "USDC-WETH", 800_000_000),   # deep USDC DEX depth
    _dex_pool("curve-dex", "USDC-USDT", 400_000_000),    # more USDC depth
    # No qualifying DEX pool for WEETH / PT / the LP → those are fail-CLOSED illiquid.
]


# ══ classification ══════════════════════════════════════════════════════════════════════════════
def test_classify_lrt():
    assert classify_collateral("WEETH") is CollateralKind.LRT
    assert classify_collateral("ezETH-USDC") is CollateralKind.LRT  # riskiest leg wins
    assert classify_collateral("WEETH").is_long_tail


def test_classify_pt():
    assert classify_collateral("PT-USDE") is CollateralKind.PT
    assert classify_collateral("PT-weETH-26DEC2024") is CollateralKind.PT
    assert classify_collateral("PT-USDE").is_long_tail


def test_classify_lp_via_exposure():
    # a multi-exposure market is LP regardless of legs (must be unwound, not spot-sold)
    assert classify_collateral("WETH-USDC", exposure="multi") is CollateralKind.LP
    assert classify_collateral("WETH-USDC", exposure="multi").is_long_tail


def test_classify_vanilla_not_long_tail():
    assert classify_collateral("USDC") is CollateralKind.VANILLA_STABLE
    assert classify_collateral("WETH") is CollateralKind.VANILLA_ETH
    assert classify_collateral("WBTC") is CollateralKind.VANILLA_BTC
    for s in ("USDC", "WETH", "WBTC"):
        assert not classify_collateral(s).is_long_tail


def test_classify_exotic_and_unknown_failclosed():
    assert classify_collateral("KHYPE") is CollateralKind.EXOTIC
    assert classify_collateral("") is CollateralKind.UNKNOWN
    # an unrecognised single token fails CLOSED to UNKNOWN (treated long-tail/illiquid)
    assert classify_collateral("ZZZQQ").is_long_tail
    assert classify_collateral("").is_long_tail


def test_stablecoin_vault_not_exotic():
    # MetaMorpho curator vault shares (STEAKUSDC, GTUSDCP) come back as stablecoin=True single rows;
    # they must NOT masquerade as exotic long-tail collateral (the big honesty trap in /pools).
    assert classify_collateral("STEAKUSDC", "single", True) is CollateralKind.VANILLA_STABLE
    assert classify_collateral("GTUSDCP", "single", True) is CollateralKind.VANILLA_STABLE
    assert not classify_collateral("STEAKUSDC", "single", True).is_long_tail
    # but a stablecoin-flagged LRT/BTC row still classifies by its volatile leg
    assert classify_collateral("WEETH", "single", True) is CollateralKind.LRT


def test_documented_penalty_monotone_by_risk():
    # riskier kinds carry a larger documented incentive than vanilla
    assert documented_penalty_bps(CollateralKind.LRT) > documented_penalty_bps(CollateralKind.VANILLA_ETH)
    assert documented_penalty_bps(CollateralKind.LP) > documented_penalty_bps(CollateralKind.VANILLA_STABLE)
    assert documented_penalty_bps(CollateralKind.UNKNOWN) >= documented_penalty_bps(CollateralKind.EXOTIC)


# ══ market monitor ══════════════════════════════════════════════════════════════════════════════
def test_monitor_parses_and_filters_protocols():
    mon = MarketMonitor(fetcher=lambda url: _payload(LENDING_ROWS))
    markets = mon.build_markets()
    syms = {(m.protocol, m.symbol) for m in markets}
    # aave-v3 row is dropped; the four target rows are kept
    assert ("aave-v3", "USDC") not in syms
    assert len(markets) == 4
    weeth = next(m for m in markets if m.symbol == "WEETH")
    assert weeth.collateral_kind is CollateralKind.LRT
    assert weeth.is_long_tail
    assert weeth.liquidation_penalty_bps > 0
    # documented data gaps are always surfaced (LLTV/borrow/at-risk are RPC-gated)
    assert any("RPC" in g or "subgraph" in g for g in weeth.data_gaps)


def test_monitor_summary_long_tail_share():
    mon = MarketMonitor(fetcher=lambda url: _payload(LENDING_ROWS))
    markets = mon.build_markets()
    summ = mon.summary(markets)
    assert summ["n_markets"] == 4
    assert summ["n_long_tail"] == 3          # WEETH, PT-USDE, the LP
    assert 0.0 <= summ["long_tail_tvl_share"] <= 1.0


def test_monitor_failclosed_on_bad_payload():
    mon = MarketMonitor(fetcher=lambda url: {"status": "error"})
    with pytest.raises(Exception):
        mon.build_markets()
    mon2 = MarketMonitor(fetcher=lambda url: ["not", "a", "dict"])
    with pytest.raises(Exception):
        mon2.build_markets()


def test_monitor_skips_symbolless_row():
    rows = [_pool("morpho-blue", "", 1_000_000), _pool("morpho-blue", "WEETH", 2_000_000)]
    mon = MarketMonitor(fetcher=lambda url: _payload(rows))
    markets = mon.build_markets()
    assert len(markets) == 1 and markets[0].symbol == "WEETH"


# ══ opportunity estimator — the EXIT GAP ═══════════════════════════════════════════════════════
def test_illiquid_collateral_is_addressable():
    """LRT collateral with NO qualifying DEX depth → atomic-MEV can't → fully addressable."""
    mon = MarketMonitor(fetcher=lambda url: _payload(LENDING_ROWS))
    markets = mon.build_markets()
    est = OpportunityEstimator(dex_pools=DEX_ROWS)
    weeth = next(m for m in markets if m.symbol == "WEETH")
    opp = est.estimate_market(weeth, DEX_ROWS)
    assert opp.dex_depth_usd == 0.0          # no WEETH DEX pool in DEX_ROWS
    assert opp.illiquid_share == 1.0         # fail-CLOSED fully illiquid
    assert not opp.atomic_mev_handles_it
    assert opp.addressable_penalty_usd == opp.gross_penalty_usd_est > 0


def test_deep_dex_collateral_handled_by_mev():
    """Vanilla USDC collateral with deep DEX depth → atomic-MEV handles it → ~0 addressable."""
    mon = MarketMonitor(fetcher=lambda url: _payload(LENDING_ROWS))
    markets = mon.build_markets()
    est = OpportunityEstimator(dex_pools=DEX_ROWS)
    usdc = next(m for m in markets if m.symbol == "USDC")
    opp = est.estimate_market(usdc, DEX_ROWS)
    assert opp.dex_depth_usd > 0
    assert opp.atomic_fill_frac >= ATOMIC_LIQUIDATION_FILL_FLOOR
    assert opp.atomic_mev_handles_it
    assert opp.illiquid_share == 0.0
    assert opp.addressable_penalty_usd == 0.0


def test_penalty_math():
    mon = MarketMonitor(fetcher=lambda url: _payload(LENDING_ROWS))
    markets = mon.build_markets()
    est = OpportunityEstimator(dex_pools=DEX_ROWS)
    weeth = next(m for m in markets if m.symbol == "WEETH")
    opp = est.estimate_market(weeth, DEX_ROWS)
    # gross_penalty = borrowed * turnover * (penalty_bps/1e4); borrowed = tvl * borrow_share
    expected = (opp.annual_liquidated_usd_est * opp.liquidation_penalty_bps / 10_000.0)
    assert abs(opp.gross_penalty_usd_est - round(expected, 2)) < 1.0
    assert 0 < opp.borrowed_usd_est < opp.tvl_usd


def test_universe_aggregate_and_determinism():
    mon = MarketMonitor(fetcher=lambda url: _payload(LENDING_ROWS))
    markets = mon.build_markets()
    est1 = OpportunityEstimator(dex_pools=DEX_ROWS)
    est2 = OpportunityEstimator(dex_pools=DEX_ROWS)
    u1 = est1.estimate_universe(markets)
    u2 = est2.estimate_universe(markets)
    # deterministic
    assert u1.total_addressable_penalty_usd == u2.total_addressable_penalty_usd
    assert [m.symbol for m in u1.markets] == [m.symbol for m in u2.markets]
    # the long-tail markets carry the addressable opportunity; vanilla USDC contributes 0
    assert u1.long_tail_addressable_penalty_usd > 0
    assert u1.total_addressable_penalty_usd >= u1.long_tail_addressable_penalty_usd
    # markets sorted by addressable penalty descending; vanilla USDC at the bottom (0)
    assert u1.markets[-1].addressable_penalty_usd == 0.0
    assert u1.top20_addressable_penalty_usd <= u1.total_addressable_penalty_usd + 1.0


def test_estimator_failclosed_no_dex_pools():
    """Empty DEX universe → every collateral is illiquid → everything addressable (never assume
    liquid)."""
    mon = MarketMonitor(fetcher=lambda url: _payload(LENDING_ROWS))
    markets = mon.build_markets()
    est = OpportunityEstimator(dex_pools=[])
    u = est.estimate_universe(markets)
    for m in u.markets:
        assert m.illiquid_share == 1.0
        assert m.addressable_penalty_usd == m.gross_penalty_usd_est
