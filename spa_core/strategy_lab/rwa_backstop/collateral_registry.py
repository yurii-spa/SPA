"""
spa_core/strategy_lab/rwa_backstop/collateral_registry.py — tokenized-RWA collateral universe.

A deterministic, hand-curated registry of tokenized-RWA collateral CANDIDATES we would consider
underwriting in an RWA repo backstop. For each asset we record what is publicly documented:
  - symbol / issuer / chain / token contract (where a public mainnet contract is known);
  - redemption rules as CONFIG CONSTANTS: documented settlement delay (days), redemption fee
    (bps), and a minimum redemption size (USD) where the issuer publishes one;
  - transfer_restricted: True for permissioned/whitelist-gated tokens (BUIDL, USYC, OUSG, VBILL,
    BENJI, STAC…) that CANNOT freely trade on a public DEX — the single most important field for
    the thesis, because a transfer-restricted token has ~0 executable on-chain exit.

IMPORTANT — these redemption figures are DOCUMENTED config constants, not live-measured. The
honest position (see docs/RWA_BACKSTOP_DERISK.md §8): the redemption leg is *relationship-gated*
— actual settlement is governed by a subscription agreement we do not have read-only. We encode
the issuer's PUBLISHED terms as a transparent assumption and clearly label it as such. The
on-chain DEX leg is the part we can MEASURE live; the redemption leg is documented-only.

Marketing NAV is ~$1.00 per share for every fund here (that is the whole point of the thesis —
the marketing number is uniform, the executable exit is not). Stored as marketing_nav_usd.

stdlib only, deterministic, LLM-forbidden. No network here — pure config.
"""
# LLM_FORBIDDEN
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# Standard marketing NAV per share for a tokenized money-market / T-bill fund.
MARKETING_NAV_USD = 1.00


@dataclass(frozen=True)
class CollateralAsset:
    """One tokenized-RWA collateral candidate. All fields are PUBLICLY DOCUMENTED config, not
    live-measured (except that liquidation_nav.py later measures the on-chain DEX leg)."""

    symbol: str
    issuer: str
    chain: str
    asset_class: str                       # "tokenized_tbill" | "tokenized_mmf" | "tokenized_credit"
    token_contract: Optional[str]          # public mainnet/chain contract, or None if not public
    transfer_restricted: bool              # permissioned / whitelist-gated → ~0 on-chain exit
    redemption_delay_days: float           # documented settlement delay (T+n) for redemption
    redemption_fee_bps: float              # documented redemption fee in basis points
    min_redemption_usd: float              # documented minimum redemption ticket (0 if none)
    redemption_documented: bool            # True = terms are published; False = unknown (fail-closed)
    marketing_nav_usd: float = MARKETING_NAV_USD
    notes: str = ""

    # DeFiLlama coins price id (chain:contract) for the live price probe, or None.
    @property
    def coin_id(self) -> Optional[str]:
        if not self.token_contract:
            return None
        return f"{self.chain}:{self.token_contract}"


# ── The registry ────────────────────────────────────────────────────────────────────────────
# Conservative, documented terms. Where a number is genuinely not public we set
# redemption_documented=False so the LiqNAV engine fails CLOSED on that leg (treats it as
# unredeemable rather than assuming cash-like).
#
# Contracts: Ethereum mainnet unless the chain field says otherwise. Permissioned funds
# (BUIDL/USYC/OUSG/VBILL/BENJI/STAC) are transfer_restricted=True — their tokens cannot move to
# an arbitrary DEX-router/AMM address, so an on-chain forced-sale exit is structurally impossible.
_REGISTRY: Tuple[CollateralAsset, ...] = (
    CollateralAsset(
        symbol="BUIDL", issuer="BlackRock / Securitize", chain="ethereum",
        asset_class="tokenized_mmf",
        token_contract="0x7712c34205737192402172409a8F7ccef8aA2AEc",
        transfer_restricted=True,
        redemption_delay_days=1.0, redemption_fee_bps=0.0, min_redemption_usd=250_000.0,
        redemption_documented=True,
        notes="Permissioned MMF (Securitize whitelist). Redemption to USDC via Circle smart "
              "contract or T+0/T+1 wire. No public DEX market — whitelist-gated transfer.",
    ),
    CollateralAsset(
        symbol="sBUIDL", issuer="Securitize (wrapped BUIDL)", chain="ethereum",
        asset_class="tokenized_mmf",
        token_contract=None,  # wrapper; no canonical public DEX-traded contract for exit
        transfer_restricted=True,
        redemption_delay_days=1.0, redemption_fee_bps=0.0, min_redemption_usd=250_000.0,
        redemption_documented=True,
        notes="Wrapped/composable BUIDL. Still whitelist-gated upstream; exit inherits BUIDL.",
    ),
    CollateralAsset(
        symbol="USYC", issuer="Circle / Hashnote", chain="ethereum",
        asset_class="tokenized_mmf",
        token_contract="0x136471a34f6ef19fE571EFFC1CA711fdb8E49f2b",
        transfer_restricted=True,
        redemption_delay_days=1.0, redemption_fee_bps=0.0, min_redemption_usd=100_000.0,
        redemption_documented=True,
        notes="Permissioned yield-coin (KYC). Near-instant mint/redeem inside the whitelist; no "
              "free public AMM market for an arbitrary liquidator.",
    ),
    CollateralAsset(
        symbol="OUSG", issuer="Ondo Finance", chain="ethereum",
        asset_class="tokenized_tbill",
        token_contract="0x1B19C19393e2d034D8Ff31ff34c81252FcBbee92",
        transfer_restricted=True,
        redemption_delay_days=0.0, redemption_fee_bps=0.0, min_redemption_usd=100_000.0,
        redemption_documented=True,
        notes="Permissioned (KYC) tokenized T-bills. Instant redeem to USDC inside whitelist "
              "(BUIDL-backed). No open DEX exit for a non-whitelisted holder.",
    ),
    CollateralAsset(
        symbol="USDY", issuer="Ondo Finance", chain="ethereum",
        asset_class="tokenized_tbill",
        token_contract="0x96F6eF951840721AdBF46Ac996b59E0235CB985C",
        transfer_restricted=False,  # USDY is the PERMISSIONLESS, transferable Ondo token
        redemption_delay_days=2.0, redemption_fee_bps=0.0, min_redemption_usd=0.0,
        redemption_documented=True,
        notes="Transferable yield-bearing note (non-US holders). Has on-chain liquidity on "
              "several chains; redemption T+n. The closest thing to DEX-exitable in this set.",
    ),
    CollateralAsset(
        symbol="USDM", issuer="Mountain Protocol", chain="ethereum",
        asset_class="tokenized_tbill",
        token_contract="0x59D9356E565Ab3A36dD77763Fc0d87fEaf85508C",
        transfer_restricted=False,  # permissionless rebasing stablecoin backed by T-bills
        redemption_delay_days=1.0, redemption_fee_bps=0.0, min_redemption_usd=0.0,
        redemption_documented=True,
        notes="Permissionless rebasing USD backed by short T-bills. Some on-chain liquidity; "
              "redemption via issuer with KYC for mint/redeem (secondary transfer is free).",
    ),
    CollateralAsset(
        symbol="VBILL", issuer="VanEck / Securitize", chain="ethereum",
        asset_class="tokenized_tbill",
        token_contract=None,  # permissioned; no public DEX contract for liquidator exit
        transfer_restricted=True,
        redemption_delay_days=1.0, redemption_fee_bps=0.0, min_redemption_usd=100_000.0,
        redemption_documented=True,
        notes="Permissioned tokenized T-bill fund. Whitelist transfer only; no on-chain DEX exit.",
    ),
    CollateralAsset(
        symbol="STAC", issuer="Arca / institutional", chain="ethereum",
        asset_class="tokenized_mmf",
        token_contract=None,
        transfer_restricted=True,
        redemption_delay_days=2.0, redemption_fee_bps=0.0, min_redemption_usd=100_000.0,
        redemption_documented=False,  # terms not consistently public → fail-closed redemption leg
        notes="Permissioned tokenized treasury fund. Redemption terms not consistently public → "
              "fail-CLOSED (redemption leg treated as unredeemable until documented).",
    ),
    CollateralAsset(
        symbol="cUSDO", issuer="OpenEden", chain="ethereum",
        asset_class="tokenized_tbill",
        # cUSDO is a GENUINE ERC-4626 wrapper of USDO (OpenEden tokenized T-bills) that exposes
        # convertToAssets()/totalAssets() read-only on mainnet — so onchain_nav.py reads its REAL
        # intrinsic NAV/share via keyless eth_call (≈ $1.05, accrued T-bill yield since inception).
        # The wrapper itself is freely transferable (the 4626  compounding share); mint/redeem of the
        # underlying USDO is KYC-gated, hence redemption documented but relationship-gated downstream.
        token_contract="0xaD55aebc9b8c03FC43cd9f62260391c13c23e7c0",
        transfer_restricted=False,
        redemption_delay_days=1.0, redemption_fee_bps=0.0, min_redemption_usd=100_000.0,
        redemption_documented=True,
        notes="OpenEden cUSDO — REAL ERC-4626 wrapper of USDO tokenized T-bills. Exposes "
              "convertToAssets()/totalAssets() on-chain → intrinsic NAV is keyless-eth_call READABLE "
              "(nav_source=onchain_4626). Underlying USDO mint/redeem is KYC-gated.",
    ),
    CollateralAsset(
        symbol="wUSDM", issuer="Mountain Protocol", chain="ethereum",
        asset_class="tokenized_tbill",
        # wUSDM is the GENUINE ERC-4626 wrapper of USDM (Mountain rebasing T-bill stablecoin). It
        # exposes convertToAssets()/totalAssets() read-only on mainnet, so onchain_nav.py reads its
        # REAL intrinsic NAV/share via keyless eth_call (≈ $1.08, accrued since inception). The
        # wrapper is permissionless/transferable; mint/redeem of USDM is KYC-gated downstream.
        token_contract="0x57F5E098CaD7A3D1Eed53991D4d66C45C9AF7812",
        transfer_restricted=False,
        redemption_delay_days=1.0, redemption_fee_bps=0.0, min_redemption_usd=0.0,
        redemption_documented=True,
        notes="Mountain wUSDM — REAL ERC-4626 wrapper of USDM T-bill-backed USD. Exposes "
              "convertToAssets()/totalAssets() on-chain → intrinsic NAV is keyless-eth_call READABLE "
              "(nav_source=onchain_4626). Underlying USDM mint/redeem is KYC-gated.",
    ),
    CollateralAsset(
        symbol="BENJI", issuer="Franklin Templeton", chain="ethereum",
        asset_class="tokenized_mmf",
        token_contract=None,  # BENJI (FOBXX) lives on a permissioned registry, not a public ERC-20 DEX
        transfer_restricted=True,
        redemption_delay_days=1.0, redemption_fee_bps=0.0, min_redemption_usd=0.0,
        redemption_documented=True,
        notes="Franklin OnChain US Gov MMF. Transfer-agent registry, not a public DEX token. "
              "Redeem via Franklin/Benji app inside the whitelist. No on-chain liquidator exit.",
    ),
)


def registry() -> List[CollateralAsset]:
    """The full collateral universe (stable, deterministic order)."""
    return list(_REGISTRY)


def by_symbol() -> Dict[str, CollateralAsset]:
    """{SYMBOL(upper): asset}. Symbols are unique in the registry."""
    return {a.symbol.upper(): a for a in _REGISTRY}


def get(symbol: str) -> Optional[CollateralAsset]:
    return by_symbol().get((symbol or "").upper())


def coin_ids() -> Dict[str, str]:
    """{SYMBOL: chain:contract} for every asset with a public contract (DEX price probe set)."""
    return {a.symbol.upper(): a.coin_id for a in _REGISTRY if a.coin_id}


# Diagnostic counts (used by the report header / tests).
def universe_summary() -> Dict[str, int]:
    total = len(_REGISTRY)
    restricted = sum(1 for a in _REGISTRY if a.transfer_restricted)
    with_contract = sum(1 for a in _REGISTRY if a.token_contract)
    documented_redemption = sum(1 for a in _REGISTRY if a.redemption_documented)
    return {
        "total": total,
        "transfer_restricted": restricted,
        "transferable": total - restricted,
        "with_public_contract": with_contract,
        "redemption_documented": documented_redemption,
    }
