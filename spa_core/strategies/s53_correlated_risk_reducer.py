"""
spa_core/strategies/s53_correlated_risk_reducer.py — S53 Correlated Risk Reducer

S53: Correlated Risk Reducer
============================
Diversification is only real if positions move independently. Two protocols with
APY correlation ≈ 1.0 are effectively *one* position carrying two sets of
smart-contract risk for one stream of return. S53 detects highly-correlated
pairs and collapses each into its higher-yield member, demoting the redundant
twin to a token 5% "monitoring" stub. Quality over quantity.

Algorithm:
  1. Start from an equal-weight base over the active universe.
  2. Read the correlation matrix (data/correlation_matrix.json or supplied dict).
  3. For every pair with |corr| > CORR_THRESHOLD (0.9):
       keep the higher-expected-APY protocol, mark the other "reduced".
       (Tie / missing APY → deterministic preference order, Morpho > Compound.)
  4. Reduced protocols are pinned to REDUCED_WEIGHT (5%); the freed weight is
     redistributed across the surviving (non-reduced) protocols proportionally.
  5. Renormalize to sum 1.0.

If no correlation data is available, S53 falls back to the equal-weight base
(no protocol is reduced) — it never *invents* correlation.

Expected APY ~4.5% — concentrating into the best of each correlated cluster
modestly lifts yield while cutting redundant tail risk.

Rules:
  - stdlib only, read-only / advisory, LLM FORBIDDEN
  - approved=False from RiskPolicy is never overridden

Date: 2026-06-21
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set, Tuple

# ─── Identity ─────────────────────────────────────────────────────────────────

STRATEGY_ID   = "S53"
STRATEGY_NAME = "Correlated Risk Reducer"
TIER          = "T2"
DESCRIPTION   = (
    "Correlated Risk Reducer: detects protocol pairs with APY correlation > 0.9 "
    "and collapses each pair into its higher-yield member, demoting the redundant "
    "twin to a 5% monitoring stub. Prefers Morpho over Compound when correlated. "
    "Quality over quantity — cuts redundant tail risk. ~4.5% APY. Advisory only."
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

# Deterministic tie-break preference (higher index wins on equal APY).
# Morpho ranks above Compound so a correlated Morpho/Compound pair keeps Morpho.
PREFERENCE_ORDER: List[str] = [
    "compound_v3",       # least preferred on a tie
    "aave_v3",
    "yearn_v3",
    "morpho_blue",
    "morpho_steakhouse", # most preferred on a tie
]

# ─── Tuning ───────────────────────────────────────────────────────────────────

CORR_THRESHOLD: float = 0.9    # |corr| above this = "highly correlated"
REDUCED_WEIGHT: float = 0.05   # demoted twin pinned to 5%

DEFAULT_CORR_PATH = os.path.join("data", "correlation_matrix.json")

TARGET_APY_MIN:   float = 4.0
TARGET_APY_MAX:   float = 5.5
RISK_SCORE:       float = 0.35
MAX_DRAWDOWN_PCT: float = 5.0


def _preference_rank(protocol: str) -> int:
    try:
        return PREFERENCE_ORDER.index(protocol)
    except ValueError:
        return -1


def load_correlation_matrix(
    path: Optional[str] = None,
) -> Dict[str, Dict[str, float]]:
    """Load a nested {p: {q: corr}} matrix from correlation_matrix.json.

    Returns {} on any error (missing file, malformed JSON) — the strategy then
    degrades to equal weight. Never raises.
    """
    path = path or DEFAULT_CORR_PATH
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    # Supported shape: {"protocol_correlations": {"matrix": {p: {q: r}}}}
    pc = data.get("protocol_correlations") if isinstance(data, dict) else None
    if isinstance(pc, dict) and isinstance(pc.get("matrix"), dict):
        return _coerce_matrix(pc["matrix"])
    # Or a bare {p: {q: r}} dict.
    if isinstance(data, dict) and all(isinstance(v, dict) for v in data.values()):
        return _coerce_matrix(data)
    return {}


def _coerce_matrix(raw: Dict) -> Dict[str, Dict[str, float]]:
    out: Dict[str, Dict[str, float]] = {}
    for p, row in raw.items():
        if not isinstance(row, dict):
            continue
        out[p] = {}
        for q, val in row.items():
            try:
                out[p][q] = float(val)
            except (TypeError, ValueError):
                continue
    return out


def correlation(
    matrix: Dict[str, Dict[str, float]], a: str, b: str
) -> Optional[float]:
    """Symmetric lookup; None if the pair is absent from the matrix."""
    if a in matrix and b in matrix[a]:
        return matrix[a][b]
    if b in matrix and a in matrix[b]:
        return matrix[b][a]
    return None


class S53CorrelatedRiskReducer:
    """S53 — Correlated Risk Reducer (collapse |corr|>0.9 pairs to best member)."""

    STRATEGY_ID   = STRATEGY_ID
    STRATEGY_NAME = STRATEGY_NAME
    TIER          = TIER
    RISK_SCORE    = RISK_SCORE

    def _apy_of(self, p: str, apy_map: Dict[str, float]) -> float:
        return apy_map.get(p, FALLBACK_APY.get(p, 0.0))

    def _winner(self, a: str, b: str, apy_map: Dict[str, float]) -> str:
        """Pick the keeper of a correlated pair: higher APY, then preference."""
        ya, yb = self._apy_of(a, apy_map), self._apy_of(b, apy_map)
        if ya > yb:
            return a
        if yb > ya:
            return b
        # tie → preference order (Morpho > Compound)
        return a if _preference_rank(a) >= _preference_rank(b) else b

    def get_reduced_set(
        self,
        apy_map: Optional[Dict[str, float]] = None,
        matrix: Optional[Dict[str, Dict[str, float]]] = None,
        active: Optional[List[str]] = None,
    ) -> Set[str]:
        """Protocols demoted because a higher-yield, highly-correlated twin exists."""
        apy_map = apy_map or {}
        if matrix is None:
            matrix = load_correlation_matrix()
        active = active if active is not None else list(PROTOCOLS)
        reduced: Set[str] = set()
        for i in range(len(active)):
            for j in range(i + 1, len(active)):
                a, b = active[i], active[j]
                if a in reduced or b in reduced:
                    continue
                corr = correlation(matrix, a, b)
                if corr is None or abs(corr) <= CORR_THRESHOLD:
                    continue
                keeper = self._winner(a, b, apy_map)
                loser = b if keeper == a else a
                reduced.add(loser)
        return reduced

    def get_allocation(
        self,
        apy_map: Optional[Dict[str, float]] = None,
        matrix: Optional[Dict[str, Dict[str, float]]] = None,
        suspended: Optional[Set[str]] = None,
    ) -> Dict[str, float]:
        """Correlation-pruned weights (sum 1.0). No matrix → equal weight."""
        suspended = suspended or set()
        active = [p for p in PROTOCOLS if p not in suspended]
        if not active:
            return {}
        base = 1.0 / len(active)

        reduced = self.get_reduced_set(apy_map, matrix, active)
        survivors = [p for p in active if p not in reduced]

        if not reduced or not survivors:
            # nothing correlated (or everything reduced) → equal weight
            return {p: round(base, 8) for p in active}

        weights: Dict[str, float] = {}
        for p in reduced:
            weights[p] = REDUCED_WEIGHT
        freed = sum(base for _ in active) - sum(weights.values())  # = 1.0 - reduced_total
        # distribute the remaining mass equally across survivors
        per = freed / len(survivors)
        for p in survivors:
            weights[p] = per

        total = sum(weights.values())
        if total <= 0.0:
            return {p: round(base, 8) for p in active}
        return {p: round(w / total, 8) for p, w in weights.items()}

    def get_expected_apy(
        self,
        apy_map: Optional[Dict[str, float]] = None,
        matrix: Optional[Dict[str, Dict[str, float]]] = None,
        suspended: Optional[Set[str]] = None,
    ) -> float:
        apy_map = apy_map or {}
        alloc = self.get_allocation(apy_map, matrix, suspended)
        if not alloc:
            return 0.0
        weighted = 0.0
        for p, w in alloc.items():
            weighted += w * self._apy_of(p, apy_map)
        return round(weighted, 4)

    def get_risk_summary(
        self,
        apy_map: Optional[Dict[str, float]] = None,
        matrix: Optional[Dict[str, Dict[str, float]]] = None,
        suspended: Optional[Set[str]] = None,
    ) -> Dict:
        alloc = self.get_allocation(apy_map, matrix, suspended)
        reduced = self.get_reduced_set(
            apy_map, matrix,
            [p for p in PROTOCOLS if p not in (suspended or set())],
        )
        t1 = sum(w for p, w in alloc.items() if PROTOCOL_TIERS.get(p) == "T1")
        t2 = sum(w for p, w in alloc.items() if PROTOCOL_TIERS.get(p) == "T2")
        return {
            "strategy_id":       STRATEGY_ID,
            "risk_score":        RISK_SCORE,
            "t1_weight_pct":     round(t1 * 100.0, 2),
            "t2_weight_pct":     round(t2 * 100.0, 2),
            "reduced_protocols": sorted(reduced),
            "corr_threshold":    CORR_THRESHOLD,
            "max_drawdown_pct":  MAX_DRAWDOWN_PCT,
        }

    def simulate(
        self,
        capital_usd: float,
        apy_map: Optional[Dict[str, float]] = None,
        matrix: Optional[Dict[str, Dict[str, float]]] = None,
        suspended: Optional[Set[str]] = None,
    ) -> Dict:
        if capital_usd <= 0.0:
            return {
                "strategy_id":               STRATEGY_ID,
                "total_capital":             capital_usd,
                "allocation":                {},
                "reduced_protocols":         sorted(
                    self.get_reduced_set(apy_map, matrix)),
                "expected_annual_yield_usd": 0.0,
                "expected_apy_pct":          0.0,
                "status":                    "no_capital",
                "timestamp_utc":             datetime.now(timezone.utc).isoformat(),
            }
        alloc = self.get_allocation(apy_map, matrix, suspended)
        apy = self.get_expected_apy(apy_map, matrix, suspended)
        positions = {p: round(capital_usd * w, 6) for p, w in alloc.items()}
        return {
            "strategy_id":               STRATEGY_ID,
            "total_capital":             capital_usd,
            "allocation":                positions,
            "reduced_protocols":         sorted(
                self.get_reduced_set(
                    apy_map, matrix,
                    [p for p in PROTOCOLS if p not in (suspended or set())])),
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
            "fallback_apy":     dict(FALLBACK_APY),
            "preference_order": list(PREFERENCE_ORDER),
            "corr_threshold":   CORR_THRESHOLD,
            "reduced_weight":   REDUCED_WEIGHT,
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
            module="spa_core.strategies.s53_correlated_risk_reducer",
            handler_class="S53CorrelatedRiskReducer",
            tags=["correlation", "diversification", "risk_reduction", "quality",
                  "morpho", "compound", "t2", "s53"],
        ))
    except Exception as exc:   # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning(
            "S53CorrelatedRiskReducer auto-registration failed: %s", exc
        )


_register()


if __name__ == "__main__":
    strat = S53CorrelatedRiskReducer()
    # Demo: Morpho-Blue and Compound perfectly correlated → keep higher-APY Morpho.
    demo_matrix = {
        "compound_v3": {"morpho_blue": 0.97},
        "morpho_blue": {"compound_v3": 0.97},
    }
    print(json.dumps(strat.simulate(100_000.0, matrix=demo_matrix), indent=2))
