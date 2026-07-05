"""spa_core/adapters/tier_map.py — SINGLE canonical protocol→tier resolver.

Why this exists (registry hygiene): the risk-tier of a protocol was classified by
hand-maintained dicts DUPLICATED across ~a dozen modules (export_data, tuner/*,
reporting/*, strategies/s41/s74/s76, monitoring/analytics …), each with its own
``unknown → "T2"`` default. Two failure modes followed:

  1. A protocol fed under a DeFiLlama slug (``aave-v3-arbitrum``, ``pendle-pt``,
     ``morpho-blue-steakhouse``) or a variant key (``aave_v3_wsteth``) did not match
     the canonical ``ADAPTER_REGISTRY`` key, so its tier silently DEFAULTED to T2 —
     a *guess* that then drove concentration caps / audits on the money path.
  2. Fixes to one map never propagated to the others.

This module is the ONE place tier truth lives. It derives tiers from
``ADAPTER_REGISTRY`` first, then an EXPLICIT alias table, and otherwise returns
``None`` (an *explicit* UNKNOWN — never a silent T2). It is deterministic, stdlib-only,
imports nothing from ``execution/``, and changes no allocation behaviour on its own —
callers opt in by using :func:`tier_of`. New adapters should be added to
``ADAPTER_REGISTRY``; new external slugs/aliases go in ``_ALIASES`` below.
"""
# LLM_FORBIDDEN
from __future__ import annotations

VALID_TIERS = ("T1", "T2", "T3")

# Explicit aliases: names that appear in live feeds / allocations / strategies but are
# NOT canonical ADAPTER_REGISTRY keys. Each maps to a (canonical_name, tier). Tiers are
# taken from the code that already classifies them (strategies s41/s74/s76, tuner
# portfolio_rebalancer, CLAUDE.md tier table) — NOT guessed. Keep this the only guess-free
# home for slug/variant → tier so consumers stop re-deriving it.
_ALIASES: dict[str, tuple[str, str]] = {
    # DeFiLlama slugs (hyphenated) → canonical registry key + tier
    "aave-v3-arbitrum": ("aave_arbitrum", "T1"),
    "aave-v3-optimism": ("aave_v3_optimism", "T1"),
    "aave-v3-base": ("aave_v3_base", "T2"),
    "aave-v3-polygon": ("aave_v3_polygon", "T1"),
    "morpho-blue-steakhouse": ("morpho_steakhouse", "T1"),
    "pendle-pt": ("pendle_pt_susde", "T2"),
    # variant / sub-market keys not separately registered
    "morpho_steakhouse": ("morpho_steakhouse", "T1"),   # Morpho Steakhouse USDC vault (T1)
    "aave_v3_wsteth": ("aave_v3_wsteth", "T2"),          # wstETH collateral market → ETH-exposed, T2
    "aerodrome_usdc_lp": ("aerodrome_usdc_lp", "T2"),    # tight-range USDC/USDT LP on Base (s76)
    "aerodrome_base": ("aerodrome_base", "T2"),
    "ondo_usdy": ("ondo_usdy", "T2"),                    # T-bill-backed stablecoin (s74)
    "pendle_yt_susde": ("pendle_yt_susde", "T3"),        # YT leg = the risky/advisory half (T3)
}


def _norm(name: str) -> str:
    """Normalise a protocol identifier for lookup (case/whitespace/slug style)."""
    return str(name).strip().lower()


def _registry_tiers() -> dict[str, str]:
    """name → tier from ADAPTER_REGISTRY (canonical), lower-cased. Lazy to avoid import cost."""
    out: dict[str, str] = {}
    try:
        from spa_core.adapters import ADAPTER_REGISTRY
    except Exception:  # noqa: BLE001 — registry unavailable (e.g. partial test env)
        return out
    for entry in ADAPTER_REGISTRY:
        try:
            name, tier = entry[0], entry[1]
        except Exception:  # noqa: BLE001 — malformed row
            continue
        if isinstance(tier, str) and tier.upper() in VALID_TIERS:
            out[_norm(name)] = tier.upper()
    return out


def tier_of(name: str) -> str | None:
    """Canonical tier ("T1"/"T2"/"T3") for a protocol, or None if genuinely unknown.

    Resolution order: ADAPTER_REGISTRY → explicit alias table → both hyphen/underscore
    spellings → None. Returns None (NOT "T2") for unknowns so callers must handle the
    gap visibly instead of silently mis-capping an unclassified protocol.
    """
    if not name:
        return None
    key = _norm(name)
    reg = _registry_tiers()
    if key in reg:
        return reg[key]
    if key in _ALIASES:
        return _ALIASES[key][1]
    # try swapping hyphens/underscores (DeFiLlama slug ↔ registry key)
    for alt in (key.replace("-", "_"), key.replace("_", "-")):
        if alt in reg:
            return reg[alt]
        if alt in _ALIASES:
            return _ALIASES[alt][1]
    return None


def canonical_name(name: str) -> str:
    """Map a slug/variant to its canonical registry key (or the normalised input if none)."""
    key = _norm(name)
    if key in _ALIASES:
        return _ALIASES[key][0]
    for alt in (key.replace("-", "_"), key.replace("_", "-")):
        if alt in _ALIASES:
            return _ALIASES[alt][0]
    return key


def unknown_protocols(names) -> list[str]:
    """Subset of ``names`` this resolver cannot classify — the honest 'not-in-order' list."""
    return sorted({n for n in names if tier_of(n) is None})
