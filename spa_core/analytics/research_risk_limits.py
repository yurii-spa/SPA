"""
spa_core/analytics/research_risk_limits.py

Hard risk limits for research strategies RS-001 and RS-002.
These limits apply even in shadow/research mode.

RS-001 limits:
  - Max single-protocol weight: 35% (btc_stable_pool)
  - Max total crypto exposure: 50% (gmx_btc + gmx_eth + btc_stable + eth_aggressive)
  - Min stablecoin weight: 15% (stablecoin_t1)
  - RESEARCH_ONLY=True cannot be removed without new ADR

RS-002 limits:
  - Max concentrated LP weight: 70% (btc_usd + rwa)
  - Min stablecoin buffer: 15% (stablecoin_deposit)
  - IL risk classification must remain "AGGRESSIVE"
  - Bear market: SUSPEND flag activated automatically

Limit enforcement:
  If any limit is violated in proposed allocation → REJECT with specific violation

Conventions:
  - stdlib only, no external dependencies
  - Allocation values are fractions (0.0–1.0) unless otherwise noted
  - All fractions must sum to <= 1.0 (cash = residual)
  - LLM FORBIDDEN in this module
"""
from __future__ import annotations

from typing import Any, Dict, List


# ─── Exceptions ───────────────────────────────────────────────────────────────


class RiskLimitViolation(Exception):
    """Raised when auto-fix cannot resolve a hard risk limit violation."""
    pass


# ─── Slot definitions ─────────────────────────────────────────────────────────

# RS-001 slot IDs that count toward crypto exposure
RS001_CRYPTO_SLOTS = frozenset({
    "gmx_btc",
    "gmx_eth",
    "btc_stable_pool",
    "eth_aggressive",
})

# RS-001 stablecoin slot
RS001_STABLECOIN_SLOTS = frozenset({"stablecoin_t1"})

# RS-002 concentrated LP slots
RS002_CONC_LP_SLOTS = frozenset({"btc_usd", "rwa"})

# RS-002 stablecoin buffer slot
RS002_STABLECOIN_SLOTS = frozenset({"stablecoin_deposit"})

# Regime strings that trigger RS-002 suspension
BEAR_REGIMES = frozenset({"bear", "extreme_bear", "crash"})


# ─── ResearchRiskLimits ───────────────────────────────────────────────────────


class ResearchRiskLimits:
    """
    Validates and enforces hard risk limits for RS-001 and RS-002.

    All allocation dicts use slot_id → fraction (0.0–1.0) mapping.
    Fractions outside this range are treated as violations.
    """

    # ── RS-001 class-level limits ─────────────────────────────────────────────

    RS001_LIMITS: Dict[str, Any] = {
        "max_single_protocol": 0.35,   # No single slot > 35%
        "max_crypto_exposure": 0.50,   # gmx_btc + gmx_eth + btc_stable + eth_aggressive ≤ 50%
        "min_stablecoin": 0.15,        # stablecoin_t1 ≥ 15%
        "max_leverage": 0.0,           # No leverage in research mode
        "research_only": True,         # Cannot be removed without ADR
    }

    # ── RS-002 class-level limits ─────────────────────────────────────────────

    RS002_LIMITS: Dict[str, Any] = {
        "max_conc_lp_total": 0.70,     # btc_usd + rwa ≤ 70%
        "min_stablecoin_buffer": 0.15, # stablecoin_deposit ≥ 15%
        "max_leverage": 0.0,           # No leverage in research mode
        "bear_market_suspend": True,   # Auto-suspend in bear regime
        "il_risk_classification": "AGGRESSIVE",  # Must not be changed
    }

    # ── RS-001 validation ─────────────────────────────────────────────────────

    def check_rs001(
        self,
        allocation: Dict[str, float],
    ) -> Dict[str, Any]:
        """
        Validates RS-001 allocation against limits.

        Returns:
            {
              "valid": bool,
              "violations": [str],   # hard limit breaches
              "warnings": [str],     # soft advisory notes
            }

        allocation: {slot_id: fraction}  fractions in [0.0, 1.0]
        """
        violations: List[str] = []
        warnings: List[str] = []

        limits = self.RS001_LIMITS

        # 1. Negative / out-of-range fractions
        for slot, frac in allocation.items():
            if frac < 0.0:
                violations.append(
                    f"Slot {slot!r} has negative fraction {frac:.4f}"
                )
            if frac > 1.0:
                violations.append(
                    f"Slot {slot!r} fraction {frac:.4f} exceeds 1.0"
                )

        # 2. Max single-protocol
        max_single = limits["max_single_protocol"]
        for slot, frac in allocation.items():
            if frac > max_single:
                violations.append(
                    f"Slot {slot!r} weight {frac:.4f} exceeds single-protocol cap "
                    f"{max_single:.2%}"
                )

        # 3. Max total crypto exposure
        crypto_total = sum(
            allocation.get(s, 0.0) for s in RS001_CRYPTO_SLOTS
        )
        max_crypto = limits["max_crypto_exposure"]
        if crypto_total > max_crypto:
            violations.append(
                f"Total crypto exposure {crypto_total:.4f} exceeds cap "
                f"{max_crypto:.2%} "
                f"(slots: {sorted(RS001_CRYPTO_SLOTS)})"
            )

        # 4. Min stablecoin
        stable_total = sum(
            allocation.get(s, 0.0) for s in RS001_STABLECOIN_SLOTS
        )
        min_stable = limits["min_stablecoin"]
        if stable_total < min_stable:
            violations.append(
                f"Stablecoin weight {stable_total:.4f} below minimum "
                f"{min_stable:.2%}"
            )

        # 5. Leverage (any slot with negative allocation implies leverage)
        #    Already caught by negative-fraction check above.
        #    Also warn if total > 1.0 (leveraged book)
        total_alloc = sum(allocation.values())
        if total_alloc > 1.0 + 1e-9:
            warnings.append(
                f"Total allocation {total_alloc:.4f} > 1.0 — potential leverage. "
                "Max leverage is 0.0 in research mode."
            )
            if total_alloc > 1.0 + 0.01:
                violations.append(
                    f"Total allocation {total_alloc:.4f} > 1.0 implies leverage, "
                    "which is forbidden (max_leverage=0.0)"
                )

        return {
            "valid": len(violations) == 0,
            "violations": violations,
            "warnings": warnings,
        }

    # ── RS-002 validation ─────────────────────────────────────────────────────

    def check_rs002(
        self,
        allocation: Dict[str, float],
        regime: str = "neutral",
    ) -> Dict[str, Any]:
        """
        Validates RS-002 allocation.

        Returns:
            {
              "valid": bool,
              "violations": [str],
              "warnings": [str],
              "suspended": bool,     # True if bear regime triggered suspension
            }
        """
        violations: List[str] = []
        warnings: List[str] = []
        suspended = False

        limits = self.RS002_LIMITS

        # 0. Bear market suspension check (comes first — supersedes limits)
        if regime in BEAR_REGIMES and limits["bear_market_suspend"]:
            suspended = True
            warnings.append(
                f"RS-002 SUSPENDED: bear market regime {regime!r} detected. "
                "Strategy must not be active."
            )

        # 1. Negative / out-of-range fractions
        for slot, frac in allocation.items():
            if frac < 0.0:
                violations.append(
                    f"Slot {slot!r} has negative fraction {frac:.4f}"
                )
            if frac > 1.0:
                violations.append(
                    f"Slot {slot!r} fraction {frac:.4f} exceeds 1.0"
                )

        # 2. Max concentrated LP total
        conc_lp_total = sum(
            allocation.get(s, 0.0) for s in RS002_CONC_LP_SLOTS
        )
        max_conc = limits["max_conc_lp_total"]
        if conc_lp_total > max_conc:
            violations.append(
                f"Concentrated LP total {conc_lp_total:.4f} exceeds cap "
                f"{max_conc:.2%} "
                f"(slots: {sorted(RS002_CONC_LP_SLOTS)})"
            )

        # 3. Min stablecoin buffer
        stable_total = sum(
            allocation.get(s, 0.0) for s in RS002_STABLECOIN_SLOTS
        )
        min_stable = limits["min_stablecoin_buffer"]
        if stable_total < min_stable:
            violations.append(
                f"Stablecoin buffer {stable_total:.4f} below minimum "
                f"{min_stable:.2%}"
            )

        # 4. Leverage check (total > 1.0)
        total_alloc = sum(allocation.values())
        if total_alloc > 1.0 + 0.01:
            violations.append(
                f"Total allocation {total_alloc:.4f} > 1.0 implies leverage, "
                "which is forbidden (max_leverage=0.0)"
            )

        return {
            "valid": len(violations) == 0,
            "violations": violations,
            "warnings": warnings,
            "suspended": suspended,
        }

    # ── RS-001 enforcement ────────────────────────────────────────────────────

    def enforce_rs001(
        self,
        allocation: Dict[str, float],
    ) -> Dict[str, float]:
        """
        Returns a corrected allocation that passes all RS-001 limits.

        Algorithm:
          1. Clip any negative fractions to 0.0
          2. Clip single-protocol overweights to max_single_protocol
          3. Ensure min stablecoin floor (stablecoin_t1)
          4. Clip crypto total to max_crypto_exposure
          5. Re-normalise so total <= 1.0 (excess goes to implicit cash)

        Raises RiskLimitViolation if the allocation is unfixable
        (e.g. stablecoin min + crypto cap constraints are mutually exclusive
         given the input structure).
        """
        result = {k: max(0.0, v) for k, v in allocation.items()}
        limits = self.RS001_LIMITS
        max_single = limits["max_single_protocol"]
        max_crypto = limits["max_crypto_exposure"]
        min_stable = limits["min_stablecoin"]

        # Step 1: Clip each slot to max_single_protocol
        for slot in list(result.keys()):
            if result[slot] > max_single:
                result[slot] = max_single

        # Step 2: Enforce stablecoin minimum
        current_stable = sum(result.get(s, 0.0) for s in RS001_STABLECOIN_SLOTS)
        if current_stable < min_stable:
            deficit = min_stable - current_stable
            # Distribute deficit equally across stablecoin slots
            stable_slots = [s for s in RS001_STABLECOIN_SLOTS if s in result or True]
            per_slot = deficit / len(stable_slots)
            for s in stable_slots:
                result[s] = result.get(s, 0.0) + per_slot

        # Step 3: Clip crypto total
        crypto_total = sum(result.get(s, 0.0) for s in RS001_CRYPTO_SLOTS)
        if crypto_total > max_crypto:
            scale = max_crypto / crypto_total
            for s in RS001_CRYPTO_SLOTS:
                if s in result:
                    result[s] *= scale

        # Step 4: Final stablecoin check after crypto scaling
        final_stable = sum(result.get(s, 0.0) for s in RS001_STABLECOIN_SLOTS)
        if final_stable < min_stable - 1e-9:
            raise RiskLimitViolation(
                f"Cannot auto-fix: stablecoin {final_stable:.4f} < "
                f"min {min_stable:.2%} after crypto cap enforcement"
            )

        # Step 5: Normalise total to <= 1.0
        total = sum(result.values())
        if total > 1.0 + 1e-9:
            scale = 1.0 / total
            result = {k: v * scale for k, v in result.items()}

        # Final validation
        check = self.check_rs001(result)
        if not check["valid"]:
            raise RiskLimitViolation(
                f"Auto-fix failed, remaining violations: {check['violations']}"
            )

        return result

    # ── RS-002 enforcement ────────────────────────────────────────────────────

    def enforce_rs002(
        self,
        allocation: Dict[str, float],
        regime: str = "neutral",
    ) -> Dict[str, float]:
        """
        Returns corrected RS-002 allocation that passes all limits.

        In bear regime: returns zero allocation for all non-stablecoin slots
        with full stablecoin buffer (suspension mode).

        Raises RiskLimitViolation if cannot fix automatically.
        """
        limits = self.RS002_LIMITS

        # Bear suspension: move everything to stablecoin buffer
        if regime in BEAR_REGIMES and limits["bear_market_suspend"]:
            result: Dict[str, float] = {}
            for slot in RS002_STABLECOIN_SLOTS:
                result[slot] = 1.0 / len(RS002_STABLECOIN_SLOTS)
            # Zero out all other slots from original
            for slot in allocation:
                if slot not in RS002_STABLECOIN_SLOTS:
                    result[slot] = 0.0
            return result

        result = {k: max(0.0, v) for k, v in allocation.items()}
        max_conc = limits["max_conc_lp_total"]
        min_stable = limits["min_stablecoin_buffer"]

        # Step 1: Clip concentrated LP total
        conc_total = sum(result.get(s, 0.0) for s in RS002_CONC_LP_SLOTS)
        if conc_total > max_conc:
            scale = max_conc / conc_total
            for s in RS002_CONC_LP_SLOTS:
                if s in result:
                    result[s] *= scale

        # Step 2: Ensure stablecoin buffer minimum
        current_stable = sum(result.get(s, 0.0) for s in RS002_STABLECOIN_SLOTS)
        if current_stable < min_stable:
            deficit = min_stable - current_stable
            for s in RS002_STABLECOIN_SLOTS:
                result[s] = result.get(s, 0.0) + deficit / len(RS002_STABLECOIN_SLOTS)

        # Step 3: Normalise to <= 1.0
        total = sum(result.values())
        if total > 1.0 + 1e-9:
            scale = 1.0 / total
            result = {k: v * scale for k, v in result.items()}

        # Final validation (ignore suspension — not bear regime here)
        check = self.check_rs002(result, regime=regime)
        if not check["valid"]:
            raise RiskLimitViolation(
                f"RS-002 auto-fix failed, remaining violations: {check['violations']}"
            )

        return result

    # ── Reporting ─────────────────────────────────────────────────────────────

    def limit_report(self) -> Dict[str, Any]:
        """Returns all limits as a structured report."""
        return {
            "schema_version": "1.0",
            "rs001": {
                "limits": dict(self.RS001_LIMITS),
                "crypto_slots": sorted(RS001_CRYPTO_SLOTS),
                "stablecoin_slots": sorted(RS001_STABLECOIN_SLOTS),
                "description": (
                    "Research-only strategy with BTC/ETH perps and stable yield. "
                    "Hard limits enforced even in shadow mode."
                ),
            },
            "rs002": {
                "limits": dict(self.RS002_LIMITS),
                "conc_lp_slots": sorted(RS002_CONC_LP_SLOTS),
                "stablecoin_slots": sorted(RS002_STABLECOIN_SLOTS),
                "bear_regimes": sorted(BEAR_REGIMES),
                "description": (
                    "Concentrated LP / RWA strategy. "
                    "IL risk is AGGRESSIVE — auto-suspend in bear regime."
                ),
            },
        }


# ─── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json

    limits = ResearchRiskLimits()
    report = limits.limit_report()
    print(json.dumps(report, indent=2, ensure_ascii=False))
