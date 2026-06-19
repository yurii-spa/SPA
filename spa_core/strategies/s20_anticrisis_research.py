"""
spa_core/strategies/s20_anticrisis_research.py — RS-001 Anti-Crisis (RESEARCH ONLY)

Research Strategy RS-001: Anti-Crisis Balanced
===============================================
Target APY: 18.2%
Status: RESEARCH-ONLY — NOT in strict evidence mode
Capital: any (normalized to weights)

IMPORTANT: This strategy uses placeholder APYs for components without
point-in-time historical data (GMX, BTC pool, Gold).
Do NOT use for real capital until strict evidence is accepted.

Allocation:
  gmx_btc_exposure    20%  15% APY (placeholder — no DeFiLlama point-in-time series)
  gmx_eth_exposure    10%  15% APY (placeholder — no DeFiLlama point-in-time series)
  btc_stable_pool     35%  25% APY (placeholder — venue unspecified)
  eth_aggressive_pool  5%  45% APY (placeholder — pool unspecified)
  gold_proxy          15%  15% APY (placeholder — PAXG or synthetic, identity unconfirmed)
  stablecoin_t1       15%   3% APY (uses aave_v3/compound_v3 live data when available)

Research exclusion reasons (per CPA methodology):
  - gmx_btc_exposure:   no clean point-in-time historical APY series
  - gmx_eth_exposure:   no clean point-in-time historical APY series
  - btc_stable_pool:    venue not specified, no historical source
  - eth_aggressive_pool: pool not specified
  - gold_proxy:         product identity unconfirmed, APY unclear

Architecture:
  - RESEARCH_ONLY = True → hard-coded, never override
  - STRICT_MODE = False → always runs in research mode
  - In strict mode simulation: only stablecoin_t1 slice is eligible (15%)
  - Weighted APY calculation uses live adapter data for T1 stablecoins
    and placeholder constants for research components
  - stdlib only, no external dependencies
  - LLM FORBIDDEN in this module

Date: 2026-06-19 (MP-1302, Sprint v9.18)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Optional

# ─── Module-level constants ────────────────────────────────────────────────────

RESEARCH_ONLY: bool = True   # Hard-coded flag — never override
STRATEGY_ID:   str  = "S20"
STRATEGY_NAME: str  = "RS-001 Anti-Crisis (Research)"
TARGET_APY:    float = 18.2

# Research weights with placeholder APYs and evidence status
RESEARCH_WEIGHTS: Dict[str, dict] = {
    "gmx_btc_exposure": {
        "weight":          0.20,
        "placeholder_apy": 15.0,
        "status":          "source_needed",
        "note":            "No DeFiLlama point-in-time historical APY series for GMX BTC",
    },
    "gmx_eth_exposure": {
        "weight":          0.10,
        "placeholder_apy": 15.0,
        "status":          "source_needed",
        "note":            "No DeFiLlama point-in-time historical APY series for GMX ETH",
    },
    "btc_stable_pool": {
        "weight":          0.35,
        "placeholder_apy": 25.0,
        "status":          "source_needed",
        "note":            "Venue not specified; no historical source available",
    },
    "eth_aggressive_pool": {
        "weight":          0.05,
        "placeholder_apy": 45.0,
        "status":          "source_needed",
        "note":            "Pool not specified; no historical source available",
    },
    "gold_proxy": {
        "weight":          0.15,
        "placeholder_apy": 15.0,
        "status":          "source_needed",
        "note":            "Product identity unconfirmed (PAXG or synthetic); APY unclear",
    },
    "stablecoin_t1": {
        "weight":          0.15,
        "placeholder_apy": 3.0,
        "status":          "live_proxy",
        "note":            "Uses aave_v3/compound_v3 live data when available",
    },
}

# Sources excluded from strict/evidence-based mode (CPA methodology)
RESEARCH_EXCLUSION_REASONS: Dict[str, str] = {
    "gmx_btc_exposure":    "no clean point-in-time historical APY series",
    "gmx_eth_exposure":    "no clean point-in-time historical APY series",
    "btc_stable_pool":     "venue not specified, no historical source",
    "eth_aggressive_pool": "pool not specified",
    "gold_proxy":          "product identity unconfirmed, APY unclear",
}

# Stablecoin T1 live adapter keys (tried in order)
_STABLECOIN_T1_ADAPTERS = ("aave_v3", "compound_v3")

# Target APY range (for registry metadata)
TARGET_APY_MIN: float = 12.0
TARGET_APY_MAX: float = 25.0

# Max drawdown threshold
MAX_DRAWDOWN_PCT: float = 5.0


# ─── AntiCrisisResearchStrategy ───────────────────────────────────────────────

class AntiCrisisResearchStrategy:
    """RS-001 Anti-Crisis Research Strategy (S20).

    RESEARCH ONLY — uses placeholder APYs for components without
    clean historical data. Do NOT deploy with real capital until all
    sources pass strict evidence review.

    Public API:
        allocate(capital, live_apy)         → {slot: usd_amount}
        blended_apy(live_apy)               → float (weighted APY %)
        strict_eligible_fraction()          → float (0.15 — only stablecoin_t1)
        research_exclusion_report()         → dict of excluded sources + reasons
        risk_warning()                      → str warning about research status
        to_dict()                           → full snapshot dict for dashboard
    """

    STRATEGY_ID    = STRATEGY_ID
    STRATEGY_NAME  = STRATEGY_NAME
    TARGET_APY     = TARGET_APY
    RESEARCH_ONLY  = RESEARCH_ONLY

    def __init__(self) -> None:
        """Initialise RS-001. Load live T1 stablecoin adapter (optional)."""
        self._live_apy_cache: Optional[float] = None
        self._adapters_loaded: list = []
        self._load_stablecoin_adapters()

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _load_stablecoin_adapters(self) -> None:
        """Try to load T1 stablecoin adapters for live APY. Fail silently."""
        for key in _STABLECOIN_T1_ADAPTERS:
            try:
                if key == "aave_v3":
                    from spa_core.adapters.aave_v3 import AaveV3Adapter  # type: ignore
                    self._adapters_loaded.append(("aave_v3", AaveV3Adapter()))
                elif key == "compound_v3":
                    from spa_core.adapters.compound_v3 import CompoundV3Adapter  # type: ignore
                    self._adapters_loaded.append(("compound_v3", CompoundV3Adapter()))
            except Exception:  # noqa: BLE001
                pass

    def _get_live_stablecoin_apy(self) -> Optional[float]:
        """Fetch live stablecoin APY from first available T1 adapter."""
        for name, adapter in self._adapters_loaded:
            try:
                apy = adapter.get_apy()  # type: ignore[attr-defined]
                if isinstance(apy, (int, float)) and not isinstance(apy, bool) and apy > 0:
                    return float(apy)
            except Exception:  # noqa: BLE001
                continue
        return None

    def _resolve_slot_apy(self, slot: str, live_apy: Optional[dict]) -> float:
        """Resolve APY for a slot.

        For stablecoin_t1: prefer live_apy dict, then live adapter, then placeholder.
        For research slots: use live_apy dict override if provided, else placeholder.

        Args:
            slot:     One of the RESEARCH_WEIGHTS keys.
            live_apy: Optional dict of {slot: apy_pct} overrides.

        Returns:
            APY percentage (float).
        """
        meta = RESEARCH_WEIGHTS.get(slot, {})
        placeholder = meta.get("placeholder_apy", 0.0)

        # Allow override via live_apy dict
        if live_apy and slot in live_apy:
            val = live_apy[slot]
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                return float(val)

        # For stablecoin_t1: try live adapter
        if slot == "stablecoin_t1":
            live = self._get_live_stablecoin_apy()
            if live is not None and live > 0:
                return live

        return placeholder

    # ── Public API ─────────────────────────────────────────────────────────────

    def allocate(self, capital: float, live_apy: Optional[dict] = None) -> dict:
        """Compute allocation across RS-001 slots.

        Applies RESEARCH_WEIGHTS to capital. Negative capital produces
        zero-valued allocations (no short positions).

        Args:
            capital:  Total capital in USD (or normalised units).
            live_apy: Optional {slot: apy_pct} dict for T1 stablecoin live data.

        Returns:
            dict with keys per RESEARCH_WEIGHTS slot:
                {
                    slot: {
                        "weight": float,
                        "amount": float,         # capital * weight (0.0 if capital <= 0)
                        "apy":    float,         # resolved APY %
                        "status": str,           # "source_needed" | "live_proxy"
                    },
                    ...
                    "_meta": {
                        "strategy_id": str,
                        "research_only": bool,
                        "total_capital": float,
                        "total_weight": float,
                        "timestamp": str,
                    }
                }
        """
        safe_capital = max(0.0, capital)
        result: dict = {}
        total_weight = sum(v["weight"] for v in RESEARCH_WEIGHTS.values())

        for slot, meta in RESEARCH_WEIGHTS.items():
            weight = meta["weight"]
            amount = safe_capital * weight
            apy    = self._resolve_slot_apy(slot, live_apy)
            result[slot] = {
                "weight": weight,
                "amount": amount,
                "apy":    apy,
                "status": meta["status"],
            }

        result["_meta"] = {
            "strategy_id":   STRATEGY_ID,
            "research_only": RESEARCH_ONLY,
            "total_capital": capital,
            "total_weight":  round(total_weight, 10),
            "timestamp":     datetime.now(timezone.utc).isoformat(),
        }
        return result

    def blended_apy(self, live_apy: Optional[dict] = None) -> float:
        """Compute portfolio-weighted blended APY (%).

        Uses placeholder APYs for research slots and (optionally) live data
        for stablecoin_t1. With all-placeholder inputs the result equals
        TARGET_APY (18.2%).

        Args:
            live_apy: Optional {slot: apy_pct} overrides.

        Returns:
            Blended APY in percent (float, ≥ 0.0).
        """
        total = 0.0
        for slot, meta in RESEARCH_WEIGHTS.items():
            weight = meta["weight"]
            apy    = self._resolve_slot_apy(slot, live_apy)
            total += weight * apy
        return round(total, 6)

    def strict_eligible_fraction(self) -> float:
        """Return the fraction of the portfolio eligible in strict evidence mode.

        Only stablecoin_t1 (15%) has a confirmed live data source. All other
        slots are excluded pending evidence review.

        Returns:
            0.15 (float) — the weight of stablecoin_t1.
        """
        return RESEARCH_WEIGHTS["stablecoin_t1"]["weight"]

    def research_exclusion_report(self) -> dict:
        """Return a structured report of sources excluded from strict mode.

        Returns:
            {
                "excluded_count": int,
                "eligible_count": int,
                "methodology": str,
                "excluded": {
                    slot: {
                        "reason": str,
                        "weight": float,
                        "placeholder_apy": float,
                    },
                    ...
                },
                "eligible": {
                    slot: {
                        "reason": str,
                        "weight": float,
                    },
                    ...
                }
            }
        """
        excluded: dict = {}
        eligible: dict = {}

        for slot, meta in RESEARCH_WEIGHTS.items():
            if slot in RESEARCH_EXCLUSION_REASONS:
                excluded[slot] = {
                    "reason":          RESEARCH_EXCLUSION_REASONS[slot],
                    "weight":          meta["weight"],
                    "placeholder_apy": meta["placeholder_apy"],
                }
            else:
                eligible[slot] = {
                    "reason": "live T1 adapter data available",
                    "weight": meta["weight"],
                }

        return {
            "excluded_count": len(excluded),
            "eligible_count": len(eligible),
            "methodology":    "CPA point-in-time evidence methodology",
            "excluded":       excluded,
            "eligible":       eligible,
        }

    def risk_warning(self) -> str:
        """Return a human-readable risk warning string for this research strategy.

        Returns:
            Non-empty warning string describing research limitations.
        """
        return (
            "RS-001 Anti-Crisis is RESEARCH ONLY. "
            "85% of the portfolio (GMX BTC/ETH, BTC stable pool, ETH aggressive pool, "
            "gold proxy) uses placeholder APYs with no verified point-in-time historical "
            "data. Do NOT allocate real or virtual capital via this strategy until all "
            "components pass strict CPA evidence review. Target APY of 18.2% is "
            "hypothetical and unverified."
        )

    def to_dict(self) -> dict:
        """Full strategy snapshot for dashboard and reports."""
        now_iso = datetime.now(timezone.utc).isoformat()
        blended = self.blended_apy()
        exclusion = self.research_exclusion_report()

        return {
            "strategy_id":              STRATEGY_ID,
            "strategy_name":            STRATEGY_NAME,
            "research_only":            RESEARCH_ONLY,
            "target_apy":               TARGET_APY,
            "blended_apy_placeholder":  blended,
            "strict_eligible_fraction": self.strict_eligible_fraction(),
            "weights":                  {k: v["weight"] for k, v in RESEARCH_WEIGHTS.items()},
            "exclusion_report":         exclusion,
            "risk_warning":             self.risk_warning(),
            "adapters_loaded":          [name for name, _ in self._adapters_loaded],
            "timestamp":                now_iso,
        }


# ─── Auto-registration ────────────────────────────────────────────────────────

def _register() -> None:
    """Register S20 in the global REGISTRY. Failure does not block import."""
    try:
        from spa_core.strategies.strategy_registry import REGISTRY, StrategyMeta  # type: ignore
        REGISTRY.register(StrategyMeta(
            id=STRATEGY_ID,
            name=STRATEGY_NAME,
            type="lending",
            risk_tier="T3",
            target_apy_min=TARGET_APY_MIN,
            target_apy_max=TARGET_APY_MAX,
            max_drawdown_pct=MAX_DRAWDOWN_PCT,
            description=(
                "RS-001 Anti-Crisis Research Strategy: 20% GMX BTC (15% APY placeholder), "
                "10% GMX ETH (15% APY placeholder), 35% BTC stable pool (25% APY placeholder), "
                "5% ETH aggressive pool (45% APY placeholder), 15% gold proxy (15% APY placeholder), "
                "15% stablecoin T1 (live data). Target APY 18.2%. RESEARCH ONLY."
            ),
            module="spa_core.strategies.s20_anticrisis_research",
            handler_class="AntiCrisisResearchStrategy",
            tags=["research", "anti_crisis", "gmx", "btc", "eth", "gold", "stablecoin",
                  "placeholder", "t3_spec", "s20", "rs001"],
        ))
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning(
            "AntiCrisisResearchStrategy auto-registration failed: %s", exc
        )


_register()
