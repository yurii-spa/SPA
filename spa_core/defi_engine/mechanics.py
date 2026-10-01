"""spa_core/defi_engine/mechanics.py — the second risk axis: WHAT a position does (ADR-532, P1-1).

The gap audit (ADR-530 §D) found ONE risk dimension: the protocol tier stood in for the mechanic,
so an Aave supply and an Aave loop would share Aave's T1 cap, and the only mechanic attribute in
the books (`is_delta_neutral: True` on every sleeve leg) was a stamp, not a computation.

This module is the home of the mechanic dimension:

* ``MECHANICS`` — the vocabulary (the audit's list plus ``savings_rate``, ``rwa_tbill`` and
  ``vault_aggregator``, which the books' universe actually contains), each with an advisory risk
  score, an advisory concentration cap (share of one book), who pays the yield, and what data the
  mechanic needs to be supervised;
* ``POSITION_MECHANIC`` — one row per registry key: mechanic + underlying asset;
* ``price_delta_neutral(key)`` — the COMPUTED neutrality: a position is price-delta-neutral for a
  USD book only if its mechanic is non-directional AND its underlying is a USD stablecoin.
  Unknown key ⇒ ``None`` (not measured), never ``True``.

**Advisory, by construction.** RiskPolicy v1.0 is frozen for the paper period (invariant #1), so
the mechanic caps here gate nothing: they are computed every run and published as findings.
Turning any of them into a gate is a RiskPolicy change ⇒ its own ADR. The numbers are INITIAL
design parameters, not measurements — they are labelled so in every artifact.

LLM_FORBIDDEN, stdlib only.
"""
# LLM_FORBIDDEN
from __future__ import annotations

from typing import Optional

#: Assets a USD book can hold without price exposure (a depeg is a separate risk — peg sensor).
USD_STABLES = frozenset({"USDC", "USDT", "DAI", "USDS", "FRAX", "CRVUSD", "USDM", "USDA",
                         "USD0", "USDE", "PYUSD", "GHO"})

#: mechanic → advisory parameters. ``risk`` ∈ [0,1], higher = riskier; ``cap`` = advisory max
#: share of ONE book; ``directional`` = carries price delta by construction; ``data_needs`` =
#: what a supervisor must observe for this mechanic to be supervised at all.
MECHANICS: dict[str, dict] = {
    "supply": {
        "risk": 0.20, "cap": 1.00, "directional": False,
        "who_pays": "borrowers' interest on an over-collateralised lending market",
        "data_needs": ["apy", "tvl", "utilization", "oracle"],
    },
    "savings_rate": {
        "risk": 0.20, "cap": 1.00, "directional": False,
        "who_pays": "the stablecoin issuer's savings rate (protocol revenue passed through)",
        "data_needs": ["apy", "peg", "governance_delay"],
    },
    "vault_aggregator": {
        "risk": 0.35, "cap": 0.50, "directional": False,
        "who_pays": "the vault's underlying strategies (lending), net of the vault fee",
        "data_needs": ["apy", "tvl", "underlying_strategies"],
    },
    "rwa_tbill": {
        "risk": 0.40, "cap": 0.40, "directional": False,
        "who_pays": "short-dated T-bill yield passed through by the issuer",
        "data_needs": ["apy", "peg", "redemption_terms", "issuer_attestation"],
    },
    "rwa_credit": {
        "risk": 0.50, "cap": 0.25, "directional": False,
        "who_pays": "institutional borrowers' interest on under-collateralised private credit",
        "data_needs": ["apy", "tvl", "redemption_queue", "loan_book_defaults"],
    },
    "pt_fixed": {
        "risk": 0.50, "cap": 0.30, "directional": False,
        "who_pays": "a fixed rate locked at purchase (the PT discount to par at maturity)",
        "data_needs": ["implied_apy", "maturity", "amm_depth", "underlying_peg"],
    },
    "lp_stable": {
        "risk": 0.45, "cap": 0.30, "directional": False,
        "who_pays": "swap fees between pegged assets, plus emissions",
        "data_needs": ["fees", "emissions", "pool_composition", "peg"],
    },
    "staked_synthetic": {
        "risk": 0.60, "cap": 0.25, "directional": False,
        "who_pays": "perpetual-futures funding paid by longs, plus staking rewards",
        "data_needs": ["apy", "funding_rate", "peg", "cooldown"],
    },
    "delta_neutral": {
        "risk": 0.60, "cap": 0.25, "directional": False,
        "who_pays": "funding / basis captured by a hedged pair",
        "data_needs": ["funding_rate", "hedge_ratio", "venue_risk"],
    },
    "basis": {
        "risk": 0.65, "cap": 0.20, "directional": False,
        "who_pays": "the spot-futures basis",
        "data_needs": ["basis", "funding_rate", "venue_risk"],
    },
    "lp_volatile": {
        "risk": 0.75, "cap": 0.10, "directional": True,
        "who_pays": "swap fees and emissions, against impermanent loss",
        "data_needs": ["fees", "emissions", "price", "impermanent_loss"],
    },
    "clmm": {
        "risk": 0.80, "cap": 0.10, "directional": True,
        "who_pays": "concentrated-range swap fees, against impermanent loss and range exit",
        "data_needs": ["fees", "price", "range", "impermanent_loss"],
    },
    "loop": {
        "risk": 0.85, "cap": 0.10, "directional": True,
        "who_pays": "the spread between supply and borrow rate, levered",
        "data_needs": ["health_factor", "borrow_rate", "oracle", "liquidation_threshold"],
    },
    "yt": {
        "risk": 0.90, "cap": 0.05, "directional": True,
        "who_pays": "the variable yield above the implied rate (yield tokens decay to zero)",
        "data_needs": ["implied_apy", "underlying_apy", "maturity"],
    },
}

#: A share within 0.1 pp of a cap is AT the cap: a sleeve sizes each leg at exactly the cap of its
#: equity, and the stored legs can exceed equity by that day's charged cost until the next re-size
#: (ADR-531). Without the tolerance every capped leg would be reported as a breach of 0.01 pp.
CAP_TOLERANCE = 0.001

#: Parameter provenance, printed with every published cap: these are NOT measured.
PARAMETER_STATUS = ("initial advisory design parameters (ADR-532); not measured and not a gate — "
                    "calibrating them is ADR-041-style curation work, binding them is a RiskPolicy ADR")

#: registry key → (mechanic, underlying asset). Every ``ADAPTER_REGISTRY`` key has a row
#: (test: ``test_defi_engine_mechanics.py``), plus the owner's T1 alias ``sky_susds``.
POSITION_MECHANIC: dict[str, tuple[str, str]] = {
    # over-collateralised lending supply
    "aave_v3": ("supply", "USDC"),
    "compound_v3": ("supply", "USDC"),
    "aave_arbitrum": ("supply", "USDC"),
    "aave_v3_optimism": ("supply", "USDC"),
    "aave_v3_polygon": ("supply", "USDC"),
    "aave_v3_base": ("supply", "USDC"),
    "morpho_blue": ("supply", "USDC"),
    "morpho_blue_base": ("supply", "USDC"),
    "morpho_steakhouse": ("supply", "USDC"),       # curated vault over Morpho Blue markets
    "euler_v2": ("supply", "USDC"),
    "fluid_fusdc": ("supply", "USDC"),
    "fluid_usdc": ("supply", "USDC"),
    "fluid_arbitrum": ("supply", "USDC"),
    "moonwell_base": ("supply", "USDC"),
    "silo_arbitrum": ("supply", "USDC"),
    "dolomite_arbitrum": ("supply", "USDC"),
    "extra_finance_base": ("supply", "USDC"),      # the LENDING side of a levered-farming protocol
    "frax": ("supply", "FRAX"),                    # FraxLend
    "tbtc_lending": ("supply", "TBTC"),            # BTC — directional for a USD book
    "cbbtc_lending": ("supply", "CBBTC"),          # BTC — directional for a USD book
    # issuer savings rates
    "spark_susds": ("savings_rate", "USDS"),
    "sky_susds": ("savings_rate", "USDS"),
    "sdai": ("savings_rate", "DAI"),
    "sfrax": ("savings_rate", "FRAX"),
    "scrvusd": ("savings_rate", "CRVUSD"),
    # vault aggregators
    "yearn_v3": ("vault_aggregator", "USDC"),
    # real-world assets
    "maple": ("rwa_credit", "USDC"),
    "wusdm": ("rwa_tbill", "USDM"),
    "stusd": ("rwa_tbill", "USDA"),
    "usual_usd0pp": ("rwa_tbill", "USD0"),
    # synthetic dollars (sUSDe: one pool under two keys)
    "susde": ("staked_synthetic", "USDE"),
    "ethena_susde": ("staked_synthetic", "USDE"),
    # fixed rate
    "pendle": ("pt_fixed", "USDC"),
    "pendle_pt_susde": ("pt_fixed", "USDE"),
    "pendle_pt_usdc": ("pt_fixed", "USDC"),
    # stable-pair liquidity
    "aerodrome_base": ("lp_stable", "USDC"),
    "velodrome_optimism": ("lp_stable", "USDC"),
}


def mechanic_of(key: object) -> Optional[str]:
    row = POSITION_MECHANIC.get(str(key or "").strip().lower())
    return row[0] if row else None


def underlying_of(key: object) -> Optional[str]:
    row = POSITION_MECHANIC.get(str(key or "").strip().lower())
    return row[1] if row else None


def price_delta_neutral(key: object) -> Optional[bool]:
    """Computed neutrality for a USD book. ``None`` = unknown key (NOT measured, never True)."""
    mech, asset = mechanic_of(key), underlying_of(key)
    if mech is None or asset is None:
        return None
    return (not MECHANICS[mech]["directional"]) and asset in USD_STABLES


def mechanic_params(mech: Optional[str]) -> Optional[dict]:
    return MECHANICS.get(mech) if mech else None


def position_risk(key: object) -> dict:
    """Risk of one position = f(protocol, mechanic): both axes and which one binds.

    The protocol axis is the canonical protocol risk score (``risk.protocol_risk_map``); the
    mechanic axis is the advisory score above. The composite is the MAX of the two — the worse
    axis decides, so neither can hide the other. Either axis missing ⇒ composite ``None``.
    """
    from spa_core.risk.protocol_risk_map import PROTOCOL_RISK_SCORES

    k = str(key or "").strip().lower()
    proto = PROTOCOL_RISK_SCORES.get(k, {}).get("risk_score")
    mech = mechanic_of(k)
    mrisk = MECHANICS[mech]["risk"] if mech else None
    if not isinstance(proto, (int, float)) or mrisk is None:
        return {"protocol_score": proto, "mechanic": mech, "mechanic_score": mrisk,
                "composite": None, "binding_axis": None}
    composite = max(float(proto), float(mrisk))
    binding = "protocol" if float(proto) >= float(mrisk) else "mechanic"
    return {"protocol_score": float(proto), "mechanic": mech, "mechanic_score": float(mrisk),
            "composite": round(composite, 4), "binding_axis": binding}


def mechanic_exposure(positions: list[dict], nav_usd: Optional[float]) -> dict:
    """Share of ONE book per mechanic vs the advisory cap. ``nav_usd`` is the book's share base
    (``exit_model.exposure_base``: NAV when cash is measured, else deployed notional).

    ``positions``: [{"protocol", "notional_usd"}]. Unknown mechanic ⇒ its own bucket
    ``"unknown"`` that always reports a finding — an unclassified position cannot pass silently.
    """
    out: dict[str, dict] = {}
    if not isinstance(nav_usd, (int, float)) or nav_usd <= 0:
        return {"measured": False, "reason": "book NAV not measured", "by_mechanic": {}, "findings": []}
    for p in positions:
        mech = mechanic_of(p.get("protocol")) or "unknown"
        row = out.setdefault(mech, {"usd": 0.0, "protocols": []})
        row["usd"] += float(p.get("notional_usd") or 0.0)
        row["protocols"].append(p.get("protocol"))
    findings = []
    for mech, row in sorted(out.items()):
        share = row["usd"] / float(nav_usd)
        row["share"] = round(share, 6)
        row["usd"] = round(row["usd"], 2)
        cap = MECHANICS.get(mech, {}).get("cap")
        row["advisory_cap"] = cap
        if cap is None:
            findings.append({"mechanic": mech, "share": row["share"],
                             "finding": "position with an unclassified mechanic"})
        elif share > cap + CAP_TOLERANCE:
            findings.append({"mechanic": mech, "share": row["share"], "advisory_cap": cap,
                             "finding": "above the advisory mechanic cap"})
    return {"measured": True, "by_mechanic": out, "findings": findings,
            "parameter_status": PARAMETER_STATUS}
