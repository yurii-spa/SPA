"""
spa_core/dfb — DFB ("DeFi Board"): the RISK-FIRST, PROVABLE pool explorer.

> *DeBank shows you the yield; DFB shows you the RISK behind the yield — per pool, with its
> A/B/C/D class, its exit-liquidity-by-size, and a deterministic would-the-desk-refuse-it verdict,
> each row carrying a reproducible proof hash. Don't trust us — check us.*

THE NON-NEGOTIABLE «NO-FORK» RULE
---------------------------------
DFB defines **NO risk math of its own**. It IMPORTS and composes the SPA engine:
  • `spa_core.strategy_lab.rates_desk.rate_policy.evaluate_entry`  — the refusal-first gate
  • `spa_core.strategy_lab.rates_desk.fair_value_engine.FairValueEngine` — baseline − 5 haircuts
  • `spa_core.strategy_lab.rates_desk.depth_at_size.compute_market_depth_row` — exit-by-size
  • `spa_core.strategy_lab.rates_desk.exit_nav.compute_ticket_row` — per-ticket exit schedule
  • `spa_core.strategy_lab.rates_desk.contracts` — the dataclasses + the A/B/C/D taxonomy inputs
  • `spa_core.risk.policy.RiskPolicy` — the deterministic spine (composed under, never copied)
  • `spa_core.strategy_lab.rates_desk.proof_chain` — the tamper-evident hash-chain pattern
So the desk's verdict and DFB's verdict on the SAME pool are always byte-identical. A pool-shaped
entrypoint that the engine lacked was ADDED IN PLACE to the engine (with engine tests), never copied
here — `test_dfb_no_fork.py` AST-asserts DFB composes engine calls and defines no risk/refusal/exit
math of its own.

CONSTRAINTS (inherited verbatim from CLAUDE.md)
-----------------------------------------------
stdlib-only · deterministic (`as_of` = the DATA date, never the wall clock) · fail-CLOSED (missing /
stale data → `flagged`, never a fabricated number or grade) · atomic writes · NO LLM in the risk path
· NEVER imports `spa_core.execution` · READ-ONLY + advisory (never touches the go-live track / capital;
writes confined to `data/dfb/`).

THE SHARED CONTRACT
-------------------
This module defines the per-pool risk-overlay object (`PoolOverlay`) + the pool-identity model
(`Pool`). Lane 1 PRODUCES it (`risk_overlay.py` → `data/dfb/pools.json` + `data/dfb/pool/<id>.json`);
Lanes 2 (API) + 3 (frontend) CONSUME it. The exact on-disk schema is documented on `PoolOverlay`.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import enum
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional

# ── DFB risk class — the A/B/C/D taxonomy (presentation of the engine verdict; NOT new risk math) ──
class RiskClass(str, enum.Enum):
    """The DFB per-pool risk letter. This is a deterministic PRESENTATION mapping of the SPA engine's
    OWN outputs (the refusal verdict + the fair-value decomposition + the tier) — DFB invents no new
    score. The mapping itself lives in `risk_overlay.classify` (composed from engine outputs only).

      A  alpha          — the desk would ENTER (refusal SAFE) AND structurally clean (low structural
                          haircut): real risk-adjusted carry above the RWA floor.
      B  beta_floor     — the desk would ENTER but the yield is essentially the honest baseline /
                          floor (little harvestable edge over fair value): own-the-floor, not alpha.
      C  risk_comp      — the desk REFUSES on an economics / size / liquidity ground (the quoted
                          yield is mostly risk compensation, OR the position cannot be exited at size).
      D  incentive      — the desk REFUSES on a STRUCTURAL TOXICITY veto (tail_veto on the size-
                          INDEPENDENT structural haircut, peg/depeg/oracle/stable/funding) — the
                          worst class; the yield is incentive / tail-comp, refused AT ANY SIZE.
      UNKNOWN           — fail-CLOSED: data too thin / stale to grade (NEVER silently graded safe).
    """
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    UNKNOWN = "UNKNOWN"


# ── pool identity (WS-1.1) ────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Pool:
    """One followed market in the DFB universe — pure IDENTITY + the raw feed snapshot, NO judgment.

    `pool_id` is a STABLE, DETERMINISTIC slug derived from (protocol, chain, asset) — reproducible
    across runs (so history files and detail URLs are stable). Every numeric field is present or
    explicitly `None` (NEVER fabricated / 0-coerced — fail-CLOSED, MEMORY: adapters mix percent vs
    decimal so APY is normalized to a DECIMAL fraction before it lands here, e.g. 0.085 == 8.5%)."""
    pool_id: str                      # stable slug: "<protocol>__<chain>__<asset>" (sanitized)
    protocol: str
    chain: str
    asset: str                        # the symbol / underlying ("USDC", "susde", "ezeth", ...)
    tier: str                         # SPA tier tag: "T1" | "T2" | "T3"
    source: str                       # provenance: "adapter_registry" | "rates_desk_market"
    apy_total: Optional[float] = None    # decimal fraction (0.085 == 8.5%) or None (no live data)
    apy_base: Optional[float] = None     # base APY (real: fees/lending/staking) decimal or None
    apy_reward: Optional[float] = None   # reward/incentive APY (mercenary emissions) decimal or None
    tvl_usd: Optional[float] = None
    il_risk: Optional[str] = None        # DeFiLlama-style "yes"/"no"/None
    exposure: Optional[str] = None       # "single" | "multi" | None
    underlying_kind: Optional[str] = None  # the rates-desk UnderlyingKind value, if resolvable
    market_id: Optional[str] = None      # the rates-desk market_id for engine depth/exit (if any)
    exit_liquidity_usd: Optional[float] = None  # §9 one-tick exit capacity carried from the surface
    as_of: Optional[str] = None          # the DATA date (ISO), never the wall clock

    def to_dict(self) -> dict:
        return asdict(self)


# ── exit-liquidity row (presentation of depth_at_size.compute_market_depth_row outputs) ─────────────
@dataclass(frozen=True)
class ExitLiquidityRow:
    """One ticket on the exit-liquidity-by-size schedule (@ $1M / $5M / $10M). A flattened view of the
    engine's `depth_at_size.compute_market_depth_row` per-ticket output — DFB computes NONE of these
    numbers. `absorbable_usd` / `dex_exit_frac` are `None` + `flagged=True` on a fail-CLOSED hole."""
    ticket_usd: int
    absorbable_usd: Optional[float]
    dex_exit_frac: Optional[float]
    flagged: bool


# ── refusal verdict (presentation of rate_policy.evaluate_entry output) ─────────────────────────────
@dataclass(frozen=True)
class RefusalVerdict:
    """The desk's would-I-enter verdict for this pool, straight from `rate_policy.evaluate_entry`.

      verdict   "SAFE"   = approved (the desk would enter)
                "REFUSE" = refused (the gate vetoed it)
                "UNKNOWN"= fail-CLOSED (could not evaluate on thin/malformed data)
      reason    the engine's KillReason value (e.g. "tail_veto", "economics", "none")
      tail_veto True iff the refusal is the size-INDEPENDENT STRUCTURAL toxicity veto — i.e. it cannot
                be sized around (the worst, class-D refusal)."""
    verdict: str
    reason: str
    tail_veto: bool


# ── the shared-contract per-pool overlay object (WS-1.2 — THE highest-value seam) ───────────────────
@dataclass(frozen=True)
class PoolOverlay:
    """The risk-first verdict object — the single thing the whole DFB product is downstream of.

    EXACT data/dfb/pools.json (list element) AND data/dfb/pool/<pool_id>.json schema for Lanes 2+3:

    {
      "pool_id": str, "protocol": str, "chain": str, "asset": str, "tier": "T1"|"T2"|"T3",
      "apy": {"total": float|null, "base": float|null, "reward": float|null},   # DECIMAL fractions
      "tvl_usd": float|null,
      "risk_class": "A"|"B"|"C"|"D"|"UNKNOWN",                                  # the A/B/C/D letter
      "risk_class_label": str,                                                  # human label
      "structural_haircut": float|null,                                         # rate_policy / fair-value
      "total_haircut": float|null,
      "exit_liquidity": [ {"ticket_usd": int, "absorbable_usd": float|null,
                           "dex_exit_frac": float|null, "flagged": bool}, ... ], # @ $1M/$5M/$10M
      "refusal": {"verdict": "SAFE"|"REFUSE"|"UNKNOWN", "reason": str, "tail_veto": bool},
      "as_of": str|null,                  # the DATA date, NEVER the wall clock
      "data_source": str,                 # "live" | "fallback" | "none" (provenance)
      "feed_coverage": str,               # "full" | "partial" | "none" (how complete the inputs were)
      "flagged": bool,                    # any fail-CLOSED hole in this row
      "flag_reason": str|null,
      "engine_proof_hash": str,           # the SPA engine's OWN GateResult.proof_hash() (byte-identical
                                          #   to what the desk computes for the same market)
      "prev_hash": str,                   # per-row proof-chain link (genesis "0"*64)
      "row_hash": str                     # sha256 over the canonical row (inputs+outputs+prev_hash)
    }
    """
    pool_id: str
    protocol: str
    chain: str
    asset: str
    tier: str
    apy: Dict[str, Optional[float]]                  # {"total","base","reward"} decimal fractions
    tvl_usd: Optional[float]
    risk_class: RiskClass
    risk_class_label: str
    structural_haircut: Optional[float]
    total_haircut: Optional[float]
    exit_liquidity: List[ExitLiquidityRow]
    refusal: RefusalVerdict
    as_of: Optional[str]
    data_source: str
    feed_coverage: str
    flagged: bool
    flag_reason: Optional[str]
    engine_proof_hash: str
    prev_hash: str
    row_hash: str = ""

    def to_dict(self) -> dict:
        """The canonical JSON dict (the shared contract above). `risk_class` → its letter value;
        nested dataclasses → plain dicts. Deterministic key set."""
        return {
            "pool_id": self.pool_id,
            "protocol": self.protocol,
            "chain": self.chain,
            "asset": self.asset,
            "tier": self.tier,
            "apy": {
                "total": self.apy.get("total"),
                "base": self.apy.get("base"),
                "reward": self.apy.get("reward"),
            },
            "tvl_usd": self.tvl_usd,
            "risk_class": self.risk_class.value,
            "risk_class_label": self.risk_class_label,
            "structural_haircut": self.structural_haircut,
            "total_haircut": self.total_haircut,
            "exit_liquidity": [
                {
                    "ticket_usd": r.ticket_usd,
                    "absorbable_usd": r.absorbable_usd,
                    "dex_exit_frac": r.dex_exit_frac,
                    "flagged": r.flagged,
                }
                for r in self.exit_liquidity
            ],
            "refusal": {
                "verdict": self.refusal.verdict,
                "reason": self.refusal.reason,
                "tail_veto": self.refusal.tail_veto,
            },
            "as_of": self.as_of,
            "data_source": self.data_source,
            "feed_coverage": self.feed_coverage,
            "flagged": self.flagged,
            "flag_reason": self.flag_reason,
            "engine_proof_hash": self.engine_proof_hash,
            "prev_hash": self.prev_hash,
            "row_hash": self.row_hash,
        }


# Human labels for the A/B/C/D letters (presentation only).
RISK_CLASS_LABELS: Dict[RiskClass, str] = {
    RiskClass.A: "alpha — desk would enter, structurally clean",
    RiskClass.B: "beta-floor — desk would enter, ~baseline yield (own-the-floor)",
    RiskClass.C: "risk-comp — desk refuses (yield is mostly risk compensation / unexitable at size)",
    RiskClass.D: "incentive — desk REFUSES on structural toxicity (tail-veto, at ANY size)",
    RiskClass.UNKNOWN: "unknown — data too thin/stale to grade (fail-closed)",
}

__all__ = [
    "RiskClass",
    "RISK_CLASS_LABELS",
    "Pool",
    "ExitLiquidityRow",
    "RefusalVerdict",
    "PoolOverlay",
]
