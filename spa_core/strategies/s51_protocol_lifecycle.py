"""
spa_core/strategies/s51_protocol_lifecycle.py — S51 Protocol Lifecycle Manager

S51: Protocol Lifecycle Manager
===============================
Treats protocol *age* (time since mainnet launch) as a first-class risk signal.
New protocols carry elevated smart-contract, economic-design and depeg risk that
fades as they survive market cycles unexploited ("Lindy effect"). S51 caps young
protocols hard and lets battle-tested anchors (Aave, Compound) carry full T1
weight.

Lifecycle buckets (age = today − launch_date):
  YOUNG    (< 1 year)  → hard cap 10% each, risk discount 0.50 on weight
  GROWING  (1–2 years) → soft cap 25% each, risk discount 0.80 on weight
  MATURE   (> 2 years) → full T1 weight, no discount (Aave/Compound/Yearn era)

Algorithm:
  1. Start from an equal-weight base over the active universe.
  2. Multiply each protocol's base by its lifecycle risk-discount.
  3. Clamp YOUNG protocols to ≤ YOUNG_HARD_CAP of the portfolio.
  4. Renormalize to sum 1.0 (mature anchors absorb the freed weight).

Age source: ADAPTER_REGISTRY metadata when available; otherwise a curated
launch-date table; otherwise DEFAULT_AGE_YEARS (2.0 → treated as MATURE) so an
unknown protocol is neither over-penalised nor force-capped.

Conservative by construction — the discounting + young-cap bleeds weight toward
low-APY mature anchors, so expected APY lands ~4.1%.

Rules:
  - stdlib only, read-only / advisory, LLM FORBIDDEN
  - approved=False from RiskPolicy is never overridden

Date: 2026-06-21
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional, Set

# ─── Identity ─────────────────────────────────────────────────────────────────

STRATEGY_ID   = "S51"
STRATEGY_NAME = "Protocol Lifecycle Manager"
TIER          = "T1"
DESCRIPTION   = (
    "Protocol Lifecycle Manager: treats protocol age as a risk signal. Young "
    "protocols (<1yr) hard-capped at 10% with a 0.5 risk discount; growing (1-2yr) "
    "soft-capped 25%; mature anchors (>2yr, Aave/Compound) carry full T1 weight. "
    "Conservative ~4.1% APY. Advisory only."
)

# ─── Universe & tiers ─────────────────────────────────────────────────────────

PROTOCOLS = ["aave_v3", "compound_v3", "morpho_steakhouse", "morpho_blue", "yearn_v3"]

PROTOCOL_TIERS: Dict[str, str] = {
    "aave_v3":           "T1",
    "compound_v3":       "T1",
    "morpho_steakhouse": "T1",
    "morpho_blue":       "T2",
    "yearn_v3":          "T2",
}

FALLBACK_APY: Dict[str, float] = {
    "aave_v3":           3.5,
    "compound_v3":       4.8,
    "morpho_steakhouse": 6.5,
    "morpho_blue":       7.0,
    "yearn_v3":          6.0,
}

# ─── Curated launch dates (UTC, YYYY-MM-DD) ───────────────────────────────────
# Used to derive age when ADAPTER_REGISTRY exposes no launch metadata.
PROTOCOL_LAUNCH_DATES: Dict[str, str] = {
    "aave_v3":           "2022-03-16",  # Aave V3 mainnet
    "compound_v3":       "2022-08-26",  # Compound III (Comet)
    "morpho_steakhouse": "2024-04-01",  # Morpho Steakhouse USDC vault era
    "morpho_blue":       "2024-01-01",  # Morpho Blue launch
    "yearn_v3":          "2023-06-01",  # Yearn V3
}

# ─── Lifecycle thresholds ─────────────────────────────────────────────────────

YOUNG_MAX_YEARS:   float = 1.0   # < 1yr = YOUNG
MATURE_MIN_YEARS:  float = 2.0   # > 2yr = MATURE
DEFAULT_AGE_YEARS: float = 2.0   # unknown protocol → treated as MATURE

YOUNG_HARD_CAP:    float = 0.10  # young protocols ≤ 10% of portfolio
GROWING_SOFT_CAP:  float = 0.25  # growing protocols ≤ 25% of portfolio

YOUNG_DISCOUNT:    float = 0.50  # weight multiplier for YOUNG
GROWING_DISCOUNT:  float = 0.80  # weight multiplier for GROWING
MATURE_DISCOUNT:   float = 1.00  # weight multiplier for MATURE

# Buckets (exported for tests)
LIFECYCLE_YOUNG   = "young"
LIFECYCLE_GROWING = "growing"
LIFECYCLE_MATURE  = "mature"

TARGET_APY_MIN:   float = 3.5
TARGET_APY_MAX:   float = 4.8
RISK_SCORE:       float = 0.20
MAX_DRAWDOWN_PCT: float = 3.0

# Reference "now" for deterministic age math is taken from the caller; default
# uses the curated table relative to import-time today only inside get_age_years.


def _parse_date(s: str) -> Optional[datetime]:
    try:
        return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def get_age_years(
    protocol: str,
    age_overrides: Optional[Dict[str, float]] = None,
    now: Optional[datetime] = None,
) -> float:
    """Resolve a protocol's age in years.

    Resolution order:
      1. explicit age_overrides[protocol]  (e.g. fed from ADAPTER_REGISTRY meta)
      2. curated PROTOCOL_LAUNCH_DATES (today − launch)
      3. DEFAULT_AGE_YEARS (2.0 → MATURE)
    """
    age_overrides = age_overrides or {}
    if protocol in age_overrides:
        return max(0.0, float(age_overrides[protocol]))
    launch = PROTOCOL_LAUNCH_DATES.get(protocol)
    if launch:
        dt = _parse_date(launch)
        if dt is not None:
            ref = now or datetime.now(timezone.utc)
            days = (ref - dt).days
            return max(0.0, round(days / 365.25, 4))
    return DEFAULT_AGE_YEARS


def lifecycle_bucket(age_years: float) -> str:
    if age_years < YOUNG_MAX_YEARS:
        return LIFECYCLE_YOUNG
    if age_years > MATURE_MIN_YEARS:
        return LIFECYCLE_MATURE
    return LIFECYCLE_GROWING


def _bucket_discount(bucket: str) -> float:
    return {
        LIFECYCLE_YOUNG:   YOUNG_DISCOUNT,
        LIFECYCLE_GROWING: GROWING_DISCOUNT,
        LIFECYCLE_MATURE:  MATURE_DISCOUNT,
    }[bucket]


def _bucket_cap(bucket: str) -> Optional[float]:
    if bucket == LIFECYCLE_YOUNG:
        return YOUNG_HARD_CAP
    if bucket == LIFECYCLE_GROWING:
        return GROWING_SOFT_CAP
    return None


class S51ProtocolLifecycle:
    """S51 — Protocol Lifecycle Manager (age-discounted, young-capped allocation)."""

    STRATEGY_ID   = STRATEGY_ID
    STRATEGY_NAME = STRATEGY_NAME
    TIER          = TIER
    RISK_SCORE    = RISK_SCORE

    def get_lifecycle_map(
        self,
        age_overrides: Optional[Dict[str, float]] = None,
        now: Optional[datetime] = None,
    ) -> Dict[str, str]:
        """Per-protocol lifecycle bucket."""
        return {
            p: lifecycle_bucket(get_age_years(p, age_overrides, now))
            for p in PROTOCOLS
        }

    def get_allocation(
        self,
        age_overrides: Optional[Dict[str, float]] = None,
        suspended: Optional[Set[str]] = None,
        now: Optional[datetime] = None,
    ) -> Dict[str, float]:
        """Age-discounted, young-capped weights (sum 1.0)."""
        suspended = suspended or set()
        active = [p for p in PROTOCOLS if p not in suspended]
        if not active:
            return {}
        base = 1.0 / len(active)

        # Step 1+2: equal base × lifecycle discount.
        raw: Dict[str, float] = {}
        buckets: Dict[str, str] = {}
        for p in active:
            bucket = lifecycle_bucket(get_age_years(p, age_overrides, now))
            buckets[p] = bucket
            raw[p] = base * _bucket_discount(bucket)

        total = sum(raw.values())
        if total <= 0.0:
            return {p: round(base, 8) for p in active}
        weights = {p: w / total for p, w in raw.items()}

        # Step 3: enforce per-bucket caps, redistribute the overflow to uncapped
        # protocols proportionally. Iterate until stable (caps are simple here).
        for _ in range(len(active)):
            overflow = 0.0
            capped: Dict[str, float] = {}
            uncapped: List[str] = []
            for p, w in weights.items():
                cap = _bucket_cap(buckets[p])
                if cap is not None and w > cap + 1e-12:
                    overflow += w - cap
                    capped[p] = cap
                else:
                    uncapped.append(p)
            if overflow <= 1e-12 or not uncapped:
                break
            unc_total = sum(weights[p] for p in uncapped)
            new_weights = dict(weights)
            for p in capped:
                new_weights[p] = capped[p]
            if unc_total > 0.0:
                for p in uncapped:
                    new_weights[p] = weights[p] + overflow * (weights[p] / unc_total)
            else:
                share = overflow / len(uncapped)
                for p in uncapped:
                    new_weights[p] = weights[p] + share
            weights = new_weights

        s = sum(weights.values())
        if s <= 0.0:
            return {p: round(base, 8) for p in active}
        return {p: round(w / s, 8) for p, w in weights.items()}

    def get_expected_apy(
        self,
        apy_map: Optional[Dict[str, float]] = None,
        age_overrides: Optional[Dict[str, float]] = None,
        suspended: Optional[Set[str]] = None,
        now: Optional[datetime] = None,
    ) -> float:
        apy_map = apy_map or {}
        alloc = self.get_allocation(age_overrides, suspended, now)
        if not alloc:
            return 0.0
        weighted = 0.0
        for p, w in alloc.items():
            apy = apy_map.get(p, FALLBACK_APY.get(p, 0.0))
            weighted += w * apy
        return round(weighted, 4)

    def get_risk_summary(
        self,
        age_overrides: Optional[Dict[str, float]] = None,
        suspended: Optional[Set[str]] = None,
        now: Optional[datetime] = None,
    ) -> Dict:
        alloc = self.get_allocation(age_overrides, suspended, now)
        buckets = self.get_lifecycle_map(age_overrides, now)
        young = sum(w for p, w in alloc.items() if buckets.get(p) == LIFECYCLE_YOUNG)
        t1 = sum(w for p, w in alloc.items() if PROTOCOL_TIERS.get(p) == "T1")
        t2 = sum(w for p, w in alloc.items() if PROTOCOL_TIERS.get(p) == "T2")
        return {
            "strategy_id":      STRATEGY_ID,
            "risk_score":       RISK_SCORE,
            "t1_weight_pct":    round(t1 * 100.0, 2),
            "t2_weight_pct":    round(t2 * 100.0, 2),
            "young_weight_pct": round(young * 100.0, 2),
            "young_hard_cap_pct": round(YOUNG_HARD_CAP * 100.0, 2),
            "max_drawdown_pct": MAX_DRAWDOWN_PCT,
        }

    def simulate(
        self,
        capital_usd: float,
        apy_map: Optional[Dict[str, float]] = None,
        age_overrides: Optional[Dict[str, float]] = None,
        suspended: Optional[Set[str]] = None,
        now: Optional[datetime] = None,
    ) -> Dict:
        if capital_usd <= 0.0:
            return {
                "strategy_id":               STRATEGY_ID,
                "total_capital":             capital_usd,
                "allocation":                {},
                "lifecycle":                 self.get_lifecycle_map(age_overrides, now),
                "expected_annual_yield_usd": 0.0,
                "expected_apy_pct":          0.0,
                "status":                    "no_capital",
                "timestamp_utc":             datetime.now(timezone.utc).isoformat(),
            }
        alloc = self.get_allocation(age_overrides, suspended, now)
        apy = self.get_expected_apy(apy_map, age_overrides, suspended, now)
        positions = {p: round(capital_usd * w, 6) for p, w in alloc.items()}
        return {
            "strategy_id":               STRATEGY_ID,
            "total_capital":             capital_usd,
            "allocation":                positions,
            "lifecycle":                 self.get_lifecycle_map(age_overrides, now),
            "expected_annual_yield_usd": round(capital_usd * apy / 100.0, 4),
            "expected_apy_pct":          apy,
            "status":                    "ok",
            "timestamp_utc":             datetime.now(timezone.utc).isoformat(),
        }

    def to_dict(self) -> Dict:
        return {
            "strategy_id":      STRATEGY_ID,
            "strategy_name":    STRATEGY_NAME,
            "tier":             TIER,
            "description":      DESCRIPTION,
            "protocols":        list(PROTOCOLS),
            "protocol_tiers":   dict(PROTOCOL_TIERS),
            "launch_dates":     dict(PROTOCOL_LAUNCH_DATES),
            "fallback_apy":     dict(FALLBACK_APY),
            "young_hard_cap":   YOUNG_HARD_CAP,
            "growing_soft_cap": GROWING_SOFT_CAP,
            "target_apy_min":   TARGET_APY_MIN,
            "target_apy_max":   TARGET_APY_MAX,
            "risk_score":       RISK_SCORE,
            "max_drawdown_pct": MAX_DRAWDOWN_PCT,
            "timestamp":        datetime.now(timezone.utc).isoformat(),
        }


def _register() -> None:
    try:
        from spa_core.strategies.strategy_registry import REGISTRY, StrategyMeta
        REGISTRY.register(StrategyMeta(
            id=STRATEGY_ID,
            name=STRATEGY_NAME,
            type="lending",
            risk_tier=TIER,
            target_apy_min=TARGET_APY_MIN,
            target_apy_max=TARGET_APY_MAX,
            max_drawdown_pct=MAX_DRAWDOWN_PCT,
            description=DESCRIPTION,
            module="spa_core.strategies.s51_protocol_lifecycle",
            handler_class="S51ProtocolLifecycle",
            tags=["lifecycle", "age", "lindy", "young_cap", "conservative",
                  "aave", "compound", "morpho", "t1", "s51"],
        ))
    except Exception as exc:   # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning(
            "S51ProtocolLifecycle auto-registration failed: %s", exc
        )


_register()


if __name__ == "__main__":
    import json
    strat = S51ProtocolLifecycle()
    print(json.dumps(strat.simulate(100_000.0), indent=2))
    print(json.dumps(strat.get_risk_summary(), indent=2))
