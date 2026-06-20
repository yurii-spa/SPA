"""
Protocol Risk Map — per-adapter risk scoring for the full ADAPTER_REGISTRY.

Companion to ``scoring_engine.py``. Where ``scoring_engine`` computes a rich
15-subscore **safety** grade (higher = safer) for a small whitelist of canonical
protocol *slugs*, this module supplies a single, flat **risk_score** per
*adapter registry key* (the ``protocol_key`` in
``spa_core.adapters.ADAPTER_REGISTRY``):

    risk_score ∈ [0, 1], higher = riskier.

Every adapter in the registry MUST have an explicit entry here. The completeness
test (``tests/test_risk_scoring_completeness.py``) cross-checks this map against
the live registry so a newly-added adapter cannot silently ship without a score.

Tier ↔ risk_score bands (enforced by the test):

    T1  risk_score  < 0.25     (blue-chip lending anchors)
    T2  0.25 ≤ risk_score ≤ 0.60
    T3  risk_score  > 0.60     (speculative / isolated / depeg-exposed)

Design constraints (match the rest of the risk layer)
-----------------------------------------------------
* **Stdlib only** — ``json``, ``datetime``, ``pathlib``.
* **Deterministic / offline** — a static table, no network, no clock-dependent
  values. Re-running ``--run`` produces a byte-identical ``data/protocol_risk_map.json``
  (sorted keys) except for ``generated_at``.
* **Self-contained** — does NOT import the adapter package (which instantiates
  Base/L2 adapters at import time). The registry cross-check lives in the test.
* **Read-only consumer** — writes ``data/protocol_risk_map.json`` only; never
  touches allocator / execution / risk-policy state.

CLI
---
::

    python -m spa_core.risk.protocol_risk_map            # print summary (no write)
    python -m spa_core.risk.protocol_risk_map --run      # atomic write to data/
    python -m spa_core.risk.protocol_risk_map --run --output <path>
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from spa_core.utils.atomic import atomic_save

MAP_VERSION = "1.0"

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_OUTPUT_PATH = _REPO_ROOT / "data" / "protocol_risk_map.json"

# Tier bands — single source of truth shared with the completeness test.
# (low_inclusive, high_inclusive); None = open-ended on that side.
TIER_BANDS: dict[str, tuple[Optional[float], Optional[float]]] = {
    "T1": (0.0, 0.249),     # strictly < 0.25
    "T2": (0.25, 0.60),     # inclusive both ends
    "T3": (0.601, 1.0),     # strictly > 0.60
}

# Neutral fallback used by get_risk_score() when an (unexpected) registry key is
# missing from PROTOCOL_RISK_SCORES — keeps runtime resilient. The completeness
# test still fails on any missing key, so this is a safety net, not a substitute
# for an explicit entry. Values sit mid-band for each tier.
TIER_DEFAULT_RISK: dict[str, float] = {
    "T1": 0.20,
    "T2": 0.45,
    "T3": 0.70,
}

# ─── Canonical per-adapter risk scores ────────────────────────────────────────
# Keyed by ADAPTER_REGISTRY protocol_key. Each entry: tier + risk_score + note.
# Scores set tonight (v1.266) extend coverage to all 32 registry adapters,
# including the 9 new MP-1227 / MP-1250 / multichain protocols.

PROTOCOL_RISK_SCORES: dict[str, dict[str, Any]] = {
    # ── T1 — blue-chip lending anchors (risk_score < 0.25) ───────────────────
    "aave_v3":          {"tier": "T1", "risk_score": 0.10, "note": "Aave V3 Ethereum — deepest, most-audited lending market"},
    "compound_v3":      {"tier": "T1", "risk_score": 0.12, "note": "Compound V3 Comet USDC — blue-chip, single-asset Comet"},
    "spark_susds":      {"tier": "T1", "risk_score": 0.15, "note": "Spark sUSDS — Sky/Maker-backed, DSR-style yield"},
    "aave_arbitrum":    {"tier": "T1", "risk_score": 0.16, "note": "Aave V3 Arbitrum — same code, L2 maturity discount"},
    "aave_v3_optimism": {"tier": "T1", "risk_score": 0.16, "note": "Aave V3 Optimism — same code, L2 maturity discount"},
    "aave_v3_polygon":  {"tier": "T1", "risk_score": 0.18, "note": "Aave V3 Polygon — USDC.e bridge-asset note adds margin"},

    # ── T2 — established but higher-risk (0.25 ≤ risk_score ≤ 0.60) ───────────
    "sdai":             {"tier": "T2", "risk_score": 0.26, "note": "Maker sDAI — DSR yield, very safe but ERC-4626 wrapper risk"},
    "aave_v3_base":     {"tier": "T2", "risk_score": 0.28, "note": "Aave V3 Base — Aave code, Base L2 + bridge risk"},
    "sfrax":            {"tier": "T2", "risk_score": 0.30, "note": "Frax sFRAX — Frax savings, peg-gated"},
    "morpho_blue":      {"tier": "T2", "risk_score": 0.30, "note": "Morpho Blue — isolated lending markets, curator risk"},
    "yearn_v3":         {"tier": "T2", "risk_score": 0.32, "note": "Yearn V3 — ERC-4626 strategy vaults, strategy migration risk"},
    "scrvusd":          {"tier": "T2", "risk_score": 0.32, "note": "Curve scrvUSD — savings crvUSD, soft-peg gate"},
    "fluid_fusdc":      {"tier": "T2", "risk_score": 0.35, "note": "Fluid fUSDC — ERC-4626 vault, GSM gate"},
    "fluid_usdc":       {"tier": "T2", "risk_score": 0.35, "note": "Fluid USDC lending — relatively new, medium TVL"},
    "wusdm":            {"tier": "T2", "risk_score": 0.35, "note": "Mountain wUSDM — T-bill RWA backing, off-chain custody risk"},
    "stusd":            {"tier": "T2", "risk_score": 0.35, "note": "Angle stUSD — hard-peg gate, RWA-backed yield"},
    "frax":             {"tier": "T2", "risk_score": 0.35, "note": "FraxLend USDC — utilisation-based yield, peg gate"},
    "pendle_pt_susde":  {"tier": "T2", "risk_score": 0.35, "note": "Pendle PT sUSDe — fixed-rate PT, safer than YT"},
    "pendle_pt_usdc":   {"tier": "T2", "risk_score": 0.35, "note": "Pendle PT USDC — fixed-rate PT, safer than YT"},
    "morpho_blue_base": {"tier": "T2", "risk_score": 0.38, "note": "Morpho Blue Base — Morpho code on Base L2"},
    "euler_v2":         {"tier": "T2", "risk_score": 0.38, "note": "Euler V2 — re-audited rebuild after 2023 exploit"},
    "pendle":           {"tier": "T2", "risk_score": 0.40, "note": "Pendle — basis/yield-tokenisation, maturity & liquidity risk"},
    "ethena_susde":     {"tier": "T2", "risk_score": 0.40, "note": "Ethena sUSDe — delta-neutral, depeg & funding risk"},
    "silo_arbitrum":    {"tier": "T2", "risk_score": 0.40, "note": "Silo Arbitrum — cross-chain + isolated lending, low TVL"},
    "dolomite_arbitrum":{"tier": "T2", "risk_score": 0.40, "note": "Dolomite Arbitrum — cross-chain lending, low TVL"},
    "maple":            {"tier": "T2", "risk_score": 0.45, "note": "Maple — private credit / undercollateralised RWA"},
    "usual_usd0pp":     {"tier": "T2", "risk_score": 0.45, "note": "Usual USD0++ — newer RWA-backed protocol"},
    "moonwell_base":    {"tier": "T2", "risk_score": 0.45, "note": "Moonwell Base — smaller Base lending market"},
    "velodrome_optimism":{"tier": "T2", "risk_score": 0.45, "note": "Velodrome Optimism — cross-chain AMM LP + VELO emissions"},
    "aerodrome_base":   {"tier": "T2", "risk_score": 0.45, "note": "Aerodrome Base — AMM stable LP + AERO emissions"},

    # ── T3 — speculative / isolated / depeg-exposed (risk_score > 0.60) ───────
    "susde":            {"tier": "T3", "risk_score": 0.65, "note": "Ethena sUSDe (T3 adapter) — depeg + 7d unstake cooldown"},
    "extra_finance_base":{"tier": "T3", "risk_score": 0.68, "note": "Extra Finance XLend Base — isolated lending, small/new"},
}


def get_risk_score(protocol_key: str, tier: Optional[str] = None) -> float:
    """Return the risk_score for a registry protocol_key.

    Falls back to the tier mid-band default if the key is not explicitly mapped
    (keeps runtime resilient; the completeness test still enforces explicit
    coverage of every registry key). If neither key nor a recognised tier is
    given, returns the neutral T2 default 0.45.
    """
    entry = PROTOCOL_RISK_SCORES.get(protocol_key)
    if entry is not None:
        return float(entry["risk_score"])
    if tier and tier in TIER_DEFAULT_RISK:
        return TIER_DEFAULT_RISK[tier]
    return TIER_DEFAULT_RISK["T2"]


def tier_band(tier: str) -> tuple[Optional[float], Optional[float]]:
    """Return the (low_inclusive, high_inclusive) risk_score band for a tier."""
    return TIER_BANDS.get(tier, (None, None))


def build_map() -> dict[str, Any]:
    """Build the canonical snapshot dict (no I/O)."""
    by_tier: dict[str, int] = {"T1": 0, "T2": 0, "T3": 0}
    protocols: dict[str, Any] = {}
    for key in sorted(PROTOCOL_RISK_SCORES):
        entry = PROTOCOL_RISK_SCORES[key]
        protocols[key] = {
            "tier":       entry["tier"],
            "risk_score": entry["risk_score"],
            "note":       entry["note"],
        }
        by_tier[entry["tier"]] = by_tier.get(entry["tier"], 0) + 1
    return {
        "generated_at":   datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "map_version":    MAP_VERSION,
        "tier_bands":     {k: list(v) for k, v in TIER_BANDS.items()},
        "count":          len(protocols),
        "count_by_tier":  by_tier,
        "protocols":      protocols,
    }


def export(output_file: Path | str = DEFAULT_OUTPUT_PATH, dry_run: bool = False) -> dict[str, Any]:
    """Build the map and (optionally) atomically write the JSON snapshot."""
    snapshot = build_map()
    if dry_run:
        return snapshot
    out = Path(output_file)
    out.parent.mkdir(parents=True, exist_ok=True)
    atomic_save(snapshot, str(out))
    return snapshot


def _cli(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Protocol Risk Map — per-adapter risk_score for ADAPTER_REGISTRY",
    )
    parser.add_argument("--run", action="store_true",
                        help="Atomically write data/protocol_risk_map.json (default: print only).")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH,
                        help=f"Output path (default: {DEFAULT_OUTPUT_PATH})")
    args = parser.parse_args(argv)

    snapshot = export(output_file=args.output, dry_run=not args.run)
    by_tier = snapshot["count_by_tier"]
    print(
        f"protocol_risk_map v{snapshot['map_version']}: "
        f"{snapshot['count']} protocols "
        f"(T1={by_tier.get('T1', 0)} T2={by_tier.get('T2', 0)} T3={by_tier.get('T3', 0)})"
    )
    if args.run:
        print(f"wrote {args.output}")
    else:
        print("dry-run (use --run to write)")
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
