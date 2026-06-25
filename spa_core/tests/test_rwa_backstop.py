"""
spa_core/tests/test_rwa_backstop.py — SPA-RRB (RWA Repo Backstop) de-risk: LiqNAV + Safety Board.

Pure synthetic, no network (a FakeFetcher injects /pools payloads). Verifies the deterministic
contracts the de-risk relies on:
  - a thin / redemption-only asset has LiqNAV < marketing NAV (the thesis: NOT cash-like)
  - a deep-DEX, transferable asset → LiqNAV ≈ NAV
  - fail-CLOSED to LiqNAV 0 on no data (no DEX + no documented redemption)
  - slippage / LiqNAV is MONOTONIC decreasing in liquidation size
  - the Safety Board has the right structure and writes atomically
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import os

from spa_core.strategy_lab.rwa_backstop.collateral_registry import CollateralAsset
from spa_core.strategy_lab.rwa_backstop.liquidation_nav import (
    LiquidationNAVEngine,
    SIZES_USD,
)
from spa_core.strategy_lab.rwa_backstop import safety_board as sb


# ── fixtures ──────────────────────────────────────────────────────────────────────────────────
def _pools_payload(pools):
    return {"status": "success", "data": pools}


def _dex_pool(symbol, tvl, project="uniswap-v3"):
    return {"project": project, "chain": "Ethereum", "symbol": symbol, "tvlUsd": tvl}


class _FakeFetcher:
    """url -> json. Returns the configured /pools payload regardless of URL."""
    def __init__(self, payload):
        self._payload = payload
        self.calls = 0

    def __call__(self, url):
        self.calls += 1
        return self._payload


# Asset templates --------------------------------------------------------------------------------
def _transferable(symbol="USDY", contract="0xabc", delay=2.0, fee=0.0, documented=True):
    return CollateralAsset(
        symbol=symbol, issuer="Test Issuer", chain="ethereum", asset_class="tokenized_tbill",
        token_contract=contract, transfer_restricted=False,
        redemption_delay_days=delay, redemption_fee_bps=fee, min_redemption_usd=0.0,
        redemption_documented=documented,
    )


def _permissioned(symbol="BUIDL", delay=1.0, documented=True):
    return CollateralAsset(
        symbol=symbol, issuer="Test Issuer", chain="ethereum", asset_class="tokenized_mmf",
        token_contract="0xdef", transfer_restricted=True,
        redemption_delay_days=delay, redemption_fee_bps=0.0, min_redemption_usd=250_000.0,
        redemption_documented=documented,
    )


def _no_exit(symbol="STAC"):
    """Permissioned AND no documented redemption → no executable exit at all."""
    return CollateralAsset(
        symbol=symbol, issuer="Test Issuer", chain="ethereum", asset_class="tokenized_mmf",
        token_contract=None, transfer_restricted=True,
        redemption_delay_days=2.0, redemption_fee_bps=0.0, min_redemption_usd=100_000.0,
        redemption_documented=False,
    )


# ── 1. thin / redemption-only asset → LiqNAV < marketing NAV ────────────────────────────────────
def test_redemption_only_liqnav_below_marketing_nav():
    """A permissioned token (no DEX exit) priced off its DOCUMENTED redemption leg must come in
    BELOW the $1.00 marketing NAV — confirming it is NOT cash-like on an executable exit."""
    asset = _permissioned("BUIDL", delay=1.0, documented=True)
    eng = LiquidationNAVEngine(fetcher=_FakeFetcher(_pools_payload([])))
    res = eng.measure_asset(asset, pools=[])
    for size in SIZES_USD:
        liq = res.liq_nav_frac(size)
        assert liq < asset.marketing_nav_usd, f"{size}: LiqNAV {liq} not below NAV"
        assert liq > 0.0  # documented redemption → some value, just not cash-like
    # on-chain leg does not exist for a restricted token
    assert res.on_chain_dex_tvl_usd == 0.0
    assert res.sized[SIZES_USD[0]].binding_leg == "redemption"


def test_thin_dex_asset_liqnav_below_nav_at_size():
    """A transferable token with a SHALLOW DEX pool: fine at $100k, materially below NAV at $10M."""
    asset = _transferable("USDY", contract="0xabc")
    pools = [_dex_pool("USDY-USDC", tvl=2_000_000.0)]  # shallow: $1M one-sided depth
    eng = LiquidationNAVEngine(fetcher=_FakeFetcher(_pools_payload(pools)))
    res = eng.measure_asset(asset, pools=pools)
    big = res.liq_nav_frac(10_000_000.0)
    assert big < asset.marketing_nav_usd
    # the thin DEX is the binding (worse) leg at $10M, not redemption
    assert res.sized[10_000_000.0].binding_leg == "dex"


# ── 2. deep-DEX transferable asset → LiqNAV ≈ NAV ───────────────────────────────────────────────
def test_deep_dex_liqnav_approx_nav():
    """A transferable token with very deep DEX liquidity should realise ≈ marketing NAV at the
    $100k size (small impact)."""
    asset = _transferable("USDY", contract="0xabc")
    pools = [_dex_pool("USDY-USDC", tvl=2_000_000_000.0)]  # $1B → ~$1B one-sided depth
    eng = LiquidationNAVEngine(fetcher=_FakeFetcher(_pools_payload(pools)))
    res = eng.measure_asset(asset, pools=pools)
    liq_small = res.liq_nav_frac(100_000.0)
    assert liq_small > 0.995, f"deep DEX should be ~NAV, got {liq_small}"
    assert abs(liq_small - asset.marketing_nav_usd) < 0.01


# ── 3. fail-CLOSED: no executable exit → LiqNAV 0 ───────────────────────────────────────────────
def test_fail_closed_no_data_liqnav_zero():
    """No public DEX exit AND no documented redemption → LiqNAV fail-closed to 0 (never cash-like)."""
    asset = _no_exit("STAC")
    eng = LiquidationNAVEngine(fetcher=_FakeFetcher(_pools_payload([])))
    res = eng.measure_asset(asset, pools=[])
    for size in SIZES_USD:
        assert res.liq_nav_frac(size) == 0.0
        assert res.sized[size].binding_leg == "none"
    assert any("fail-closed" in g.lower() for g in res.data_gaps)


def test_fail_closed_on_fetch_failure_zero_dex():
    """If the pools fetch raises, on-chain depth is 0 everywhere (never fabricated)."""
    class _Boom:
        def __call__(self, url):
            raise RuntimeError("network down")

    asset = _transferable("USDY", contract="0xabc")
    eng = LiquidationNAVEngine(fetcher=_Boom())
    results = eng.measure_universe([asset])
    res = results[0]
    assert res.on_chain_dex_tvl_usd == 0.0
    assert res.n_dex_pools == 0


# ── 4. slippage / LiqNAV monotonic in size ──────────────────────────────────────────────────────
def test_slippage_monotonic_in_size():
    """On-chain realised fraction (and the resulting LiqNAV) is non-increasing as size grows."""
    asset = _transferable("USDY", contract="0xabc")
    pools = [_dex_pool("USDY-USDC", tvl=50_000_000.0)]
    eng = LiquidationNAVEngine(fetcher=_FakeFetcher(_pools_payload(pools)))
    res = eng.measure_asset(asset, pools=pools)
    fracs = [res.sized[s].on_chain_value_frac for s in sorted(SIZES_USD)]
    for a, b in zip(fracs, fracs[1:]):
        assert b <= a, f"slippage not monotonic: {fracs}"
    liqs = [res.liq_nav_frac(s) for s in sorted(SIZES_USD)]
    for a, b in zip(liqs, liqs[1:]):
        assert b <= a, f"LiqNAV not monotonic in size: {liqs}"


# ── 5. Safety Board structure + atomic write ────────────────────────────────────────────────────
def test_safety_board_structure_and_atomic(tmp_path):
    out = tmp_path / "rwa_safety_board.json"
    assets = [
        _transferable("DEEP", contract="0xabc"),      # deep DEX → LIQUID
        _permissioned("BUIDL", documented=True),       # restricted but redeemable → REDEMPTION_ONLY
        _no_exit("STAC"),                              # nothing → UNSAFE
    ]
    deep_pools = [_dex_pool("DEEP-USDC", tvl=5_000_000_000.0)]
    report = sb.build_report(
        write=True, fetcher=_FakeFetcher(_pools_payload(deep_pools)),
        out_path=out, assets=assets,
    )

    # top-level structure
    for key in ("generated_at", "verdict_counts", "assets", "thesis_confirmed",
                "n_not_cash_like", "data_caveats", "universe_summary"):
        assert key in report
    assert report["llm_forbidden"] is True
    assert report["research_only"] is True

    by_sym = {a["symbol"]: a for a in report["assets"]}
    assert by_sym["DEEP"]["verdict"] == sb.LIQUID
    assert by_sym["BUIDL"]["verdict"] == sb.REDEMPTION_ONLY
    assert by_sym["STAC"]["verdict"] == sb.UNSAFE

    # per-asset row structure
    row = by_sym["BUIDL"]
    for key in ("liq_nav_usd_1m", "marketing_vs_liq_gap_pct_1m", "on_chain_dex_liquidity_usd",
                "exit_capacity_72h_usd", "binding_leg_1m", "redemption_delay_days"):
        assert key in row
    # the thesis number: restricted asset has a positive marketing-vs-liq gap
    assert row["marketing_vs_liq_gap_pct_1m"] > 0.0
    # permissioned → zero on-chain exit capacity
    assert row["exit_capacity_72h_usd"] == 0.0

    # file written atomically + valid JSON, no leftover temp files
    assert out.exists()
    with open(out) as f:
        on_disk = json.load(f)
    assert on_disk["verdict_counts"] == report["verdict_counts"]
    leftovers = [p for p in os.listdir(tmp_path) if p.startswith(".") and p.endswith(".tmp")]
    assert not leftovers


def test_determinism_same_input_same_output():
    """Two runs over the same injected payload produce identical boards (modulo timestamps)."""
    assets = [_permissioned("BUIDL"), _transferable("USDY", contract="0xabc")]
    pools = [_dex_pool("USDY-USDC", tvl=10_000_000.0)]
    f = _FakeFetcher(_pools_payload(pools))
    r1 = sb.build_report(write=False, fetcher=f, assets=assets)
    r2 = sb.build_report(write=False, fetcher=f, assets=assets)
    for a, b in zip(r1["assets"], r2["assets"]):
        a2 = {k: v for k, v in a.items()}
        b2 = {k: v for k, v in b.items()}
        assert a2 == b2


def test_real_registry_loads_and_classifies():
    """The shipped registry runs end-to-end offline (empty pools → fail-closed on-chain) and every
    asset gets a valid verdict. With no DEX data, transferable+documented assets fall to
    REDEMPTION_ONLY (no on-chain exit measurable), restricted ones too, undocumented → UNSAFE."""
    report = sb.build_report(write=False, fetcher=_FakeFetcher(_pools_payload([])))
    assert report["n_assets"] >= 8
    valid = {sb.LIQUID, sb.THIN, sb.REDEMPTION_ONLY, sb.UNSAFE}
    for a in report["assets"]:
        assert a["verdict"] in valid
    # offline (no DEX feed) → nothing can be LIQUID; thesis must read as confirmed
    assert report["verdict_counts"][sb.LIQUID] == 0
    assert report["thesis_confirmed"] is True
