"""
spa_core/strategies/s45_mean_reversion.py — S45 Mean-Reversion Yield

S45: Mean-Reversion Yield
=========================
DeFi lending APY mean-reverts. When a venue's rate is *temporarily depressed*
below its long-run mean, deposit demand has rotated elsewhere and the rate
tends to climb back; when it is *elevated* above the mean, the spread attracts
fresh deposits and compresses the rate back down. S45 bets on that reversion:
it OVERWEIGHTS protocols trading below their mean (they should revert up) and
UNDERWEIGHTS protocols trading above their mean (they should revert down).

This is the structural inverse of S28 Momentum Yield (chase what's rising);
S45 deliberately leans against the move.

Real-track evidence (data/historical_apy/, 365-day series, 2025-06→2026-06):
  aave_v3      min 1.57%  max 12.60%  mean 3.64%   ← reverts hard
  compound_v3  min 2.34%  max 11.70%  mean 3.78%
  morpho_blue  min 3.55%  max  9.57%  mean 6.87%
  yearn_v3     min 1.37%  max 16.05%  mean 4.95%
  sky_susds    min 3.60%  max  4.75%  mean 4.20%   ← near-constant (peg)
When Aave dropped to 1.57% demand shifted to Compound/Morpho; when it spiked to
12.60% it normalized. S45 sizes positions on the *deviation from mean*.

Allocation model (deterministic)
--------------------------------
  N            = number of protocols with a valid current APY + mean
  base_weight  = 1 / N                                    (equal weight)
  deviation    = (current_apy - mean_apy) / mean_apy      (signed, fraction)
  adjustment   = -TILT * deviation                        (TILT = 0.30)
  raw_weight   = clamp(base_weight + adjustment, 0.05, per_protocol_cap)
  weights are then normalized to (1 - CASH_BUFFER) and the T2-total cap
  (≤ 50%, ADR-019) is enforced; CASH_BUFFER (5%) is held as dry powder.

`per_protocol_cap` is the RiskPolicy per-protocol limit by tier — T1 → 40%,
T2 → 20% — NOT a flat T2 cap, so a depressed T1 anchor like Aave can be
overweighted toward its 40% ceiling while T2 venues stay bounded at 20%.

Worked example — Aave at 1.57% (mean 3.64%):
  deviation  = (1.57 - 3.64) / 3.64 = -0.569  (−56.9%, depressed)
  adjustment = -0.30 * (-0.569)     = +0.171
  raw_weight = 0.20 + 0.171         = 0.371   → overweight, betting on reversion
A protocol spiking to +50% above mean gets adjustment −0.15 → trimmed to 0.05.

Regime overlay
--------------
  ALL protocols BELOW mean  → market-wide stress / demand flight: de-risk to an
                              80% T1 book (T2 → 0), 20% cash. Reversion bets are
                              riskier when the whole curve is depressed together.
  ALL protocols ABOVE mean  → T2 spike season: no reversion edge to harvest, so
                              stay diversified at equal weight.
  otherwise                 → mean-reversion tilt as above.

Expected APY ≈ 4.5–5.0% long-run, regime-timing dependent.

Rules: stdlib only · read-only / advisory · LLM FORBIDDEN · no execution imports.
The deterministic RiskPolicy gate retains final authority; `approved=False` is
never overridden. S45 never opens positions itself — it emits a target weight
map and a regime verdict for the allocator/operator to consider.

Date: 2026-06-21
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional

# ─── Identity ─────────────────────────────────────────────────────────────────

STRATEGY_ID   = "S45"
STRATEGY_NAME = "Mean-Reversion Yield"
TIER          = "T2"
DESCRIPTION   = (
    "Mean-Reversion Yield: overweights protocols whose APY is temporarily "
    "depressed below their long-run mean (they should revert up) and underweights "
    "protocols trading above mean (revert down). weight = clamp(1/N - 0.3*deviation, "
    "0.05, per-protocol cap), normalized with a 5% cash buffer and T2≤50% cap. "
    "Regime overlay: all-below-mean → 80% T1 de-risk; all-above-mean → stay "
    "diversified. Expected ~4.5-5.0% APY. Advisory-only, deterministic, stdlib."
)

CASH_KEY = "cash"

# ─── Protocol universe ────────────────────────────────────────────────────────

PROTOCOLS: List[str] = ["aave_v3", "compound_v3", "morpho_blue", "yearn_v3", "sky_susds"]

PROTOCOL_TIERS: Dict[str, str] = {
    "aave_v3":     "T1",
    "compound_v3": "T1",
    "morpho_blue": "T2",
    "yearn_v3":    "T2",
    "sky_susds":   "T1",
    CASH_KEY:      "CASH",
}

# Historical-APY file per protocol (data/historical_apy/<file>).
HISTORICAL_FILES: Dict[str, str] = {
    "aave_v3":     "aave_v3_usdc.json",
    "compound_v3": "compound_v3_usdc.json",
    "morpho_blue": "morpho_blue_usdc.json",
    "yearn_v3":    "yearn_v3_usdc.json",
    "sky_susds":   "sky_susds.json",
}

# Long-run mean APY (%) fallback when no historical series is available.
# Sourced from the 365-day real track (data/historical_apy/, 2025-06→2026-06).
MEAN_APY_DEFAULTS: Dict[str, float] = {
    "aave_v3":     3.64,
    "compound_v3": 3.78,
    "morpho_blue": 6.87,
    "yearn_v3":    4.95,
    "sky_susds":   4.20,
}

# Current-APY fallback (≈ mean) when no live snapshot is supplied.
APY_DEFAULTS: Dict[str, float] = dict(MEAN_APY_DEFAULTS)

# ─── Model parameters ─────────────────────────────────────────────────────────

TILT:             float = 0.30   # deviation→weight sensitivity (-TILT * deviation)
MIN_WEIGHT:       float = 0.05   # per-protocol floor
CASH_BUFFER:      float = 0.05   # min cash buffer (RiskPolicy ≥ 5%)
MEAN_WINDOW_DAYS: int   = 30     # trailing window for the historical mean

# Per-protocol caps by tier (RiskPolicy: T1 40%, T2 20%).
PER_PROTOCOL_CAP: Dict[str, float] = {"T1": 0.40, "T2": 0.20}
T2_TOTAL_CAP:     float = 0.50   # ADR-019: T2 aggregate ≤ 50%

STRESS_T1_WEIGHT: float = 0.80   # all-below-mean regime → 80% T1 book

# ─── Targets / risk ───────────────────────────────────────────────────────────

TARGET_APY_MIN:   float = 4.5
TARGET_APY_MAX:   float = 5.0
RISK_SCORE:       float = 0.40
MAX_DRAWDOWN_PCT: float = 3.0


def _is_number(x: object) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and x == x  # not NaN


def _clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


def _cap_for(protocol: str) -> float:
    return PER_PROTOCOL_CAP.get(PROTOCOL_TIERS.get(protocol, "T2"), 0.20)


def _default_data_dir() -> str:
    # spa_core/strategies/s45_mean_reversion.py → repo_root/data/historical_apy
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(os.path.dirname(here))
    return os.path.join(root, "data", "historical_apy")


class S45MeanReversion:
    """S45 — Mean-Reversion Yield (deviation-sized, regime-aware, advisory)."""

    STRATEGY_ID   = STRATEGY_ID
    STRATEGY_NAME = STRATEGY_NAME
    TIER          = TIER
    RISK_SCORE    = RISK_SCORE

    def __init__(self, data_dir: Optional[str] = None, window_days: int = MEAN_WINDOW_DAYS):
        self.data_dir = data_dir or _default_data_dir()
        self.window_days = max(1, int(window_days))

    # ── Historical mean loading ────────────────────────────────────────────────

    def load_mean_apys(self) -> Dict[str, float]:
        """Trailing `window_days` mean APY (%) per protocol from historical_apy/.

        Falls back to MEAN_APY_DEFAULTS for any protocol whose series is missing,
        empty, or unreadable. Never raises — read-only, offline-safe.
        """
        means: Dict[str, float] = {}
        for protocol in PROTOCOLS:
            mean = self._load_one_mean(protocol)
            means[protocol] = mean if mean is not None else MEAN_APY_DEFAULTS.get(protocol, 0.0)
        return means

    def _load_one_mean(self, protocol: str) -> Optional[float]:
        fname = HISTORICAL_FILES.get(protocol)
        if not fname:
            return None
        path = os.path.join(self.data_dir, fname)
        try:
            with open(path, "r", encoding="utf-8") as fh:
                rows = json.load(fh)
        except (OSError, ValueError):
            return None
        if not isinstance(rows, list) or not rows:
            return None
        apys = [float(r["apy"]) for r in rows
                if isinstance(r, dict) and _is_number(r.get("apy"))]
        if not apys:
            return None
        window = apys[-self.window_days:]
        return round(sum(window) / len(window), 6)

    # ── Deviation & regime ──────────────────────────────────────────────────────

    def deviation_scores(
        self,
        current_apys: Dict[str, float],
        mean_apys: Optional[Dict[str, float]] = None,
    ) -> Dict[str, float]:
        """Signed deviation (current - mean)/mean per protocol with valid inputs."""
        mean_apys = mean_apys or self.load_mean_apys()
        scores: Dict[str, float] = {}
        for protocol in PROTOCOLS:
            cur = current_apys.get(protocol)
            mean = mean_apys.get(protocol)
            if _is_number(cur) and _is_number(mean) and mean != 0:
                scores[protocol] = round((float(cur) - float(mean)) / float(mean), 6)
        return scores

    def detect_regime(self, deviations: Dict[str, float]) -> str:
        """'stress' (all below mean), 'spike' (all above mean), or 'reversion'."""
        if not deviations:
            return "reversion"
        vals = list(deviations.values())
        if all(d < 0 for d in vals):
            return "stress"
        if all(d > 0 for d in vals):
            return "spike"
        return "reversion"

    # ── Allocation ──────────────────────────────────────────────────────────────

    def compute_weights(
        self,
        current_apys: Optional[Dict[str, float]] = None,
        mean_apys: Optional[Dict[str, float]] = None,
    ) -> Dict[str, float]:
        """Target weight map (fractions summing to 1.0, including cash).

        Empty/None current_apys → fall back to APY_DEFAULTS (≈ mean → flat tilt).
        """
        current_apys = current_apys or dict(APY_DEFAULTS)
        mean_apys = mean_apys or self.load_mean_apys()

        universe = [p for p in PROTOCOLS
                    if _is_number(current_apys.get(p))
                    and _is_number(mean_apys.get(p)) and mean_apys.get(p) != 0]
        if not universe:
            return {CASH_KEY: 1.0}

        deviations = {p: (float(current_apys[p]) - float(mean_apys[p])) / float(mean_apys[p])
                      for p in universe}
        regime = self.detect_regime(deviations)

        if regime == "stress":
            raw = self._stress_weights(universe, deviations)
        elif regime == "spike":
            raw = {p: 1.0 / len(universe) for p in universe}   # diversified, equal weight
        else:
            raw = self._reversion_weights(universe, deviations)

        weights = self._finalize(raw, regime)
        return weights

    def _reversion_weights(
        self, universe: List[str], deviations: Dict[str, float]
    ) -> Dict[str, float]:
        base = 1.0 / len(universe)
        raw: Dict[str, float] = {}
        for p in universe:
            adjustment = -TILT * deviations[p]
            raw[p] = _clamp(base + adjustment, MIN_WEIGHT, _cap_for(p))
        return raw

    def _stress_weights(
        self, universe: List[str], deviations: Dict[str, float]
    ) -> Dict[str, float]:
        """De-risk: 80% across T1 (mean-reversion-tilted), T2 → 0, rest cash."""
        t1 = [p for p in universe if PROTOCOL_TIERS.get(p) == "T1"]
        if not t1:                       # no T1 venue available → hold cash
            return {}
        base = 1.0 / len(t1)
        raw: Dict[str, float] = {}
        for p in t1:
            adjustment = -TILT * deviations[p]
            raw[p] = _clamp(base + adjustment, MIN_WEIGHT, _cap_for(p))
        total = sum(raw.values())
        # scale T1 book to STRESS_T1_WEIGHT; remainder becomes cash in _finalize.
        return {p: w / total * STRESS_T1_WEIGHT for p, w in raw.items()}

    def _finalize(self, raw: Dict[str, float], regime: str) -> Dict[str, float]:
        """Normalize protocol weights, enforce per-protocol caps (water-filling so
        caps hold *after* normalization) and the T2 total cap, then attach cash."""
        if not raw:
            return {CASH_KEY: 1.0}

        investable = 1.0 - CASH_BUFFER
        # In 'stress', raw is already scaled to STRESS_T1_WEIGHT (≤ investable); the
        # de-risk target is that explicit book, so don't re-inflate it to investable.
        target = sum(raw.values()) if regime == "stress" else investable

        weights = self._normalize_with_caps(raw, target)
        weights = self._enforce_t2_cap(weights)

        # Cash = whatever is left after the (capped) protocol book (≥ CASH_BUFFER).
        deployed = sum(weights.values())
        weights[CASH_KEY] = max(0.0, 1.0 - deployed)
        return {p: round(w, 6) for p, w in weights.items() if w > 0}

    @staticmethod
    def _normalize_with_caps(raw: Dict[str, float], target: float) -> Dict[str, float]:
        """Scale `raw` to sum to `target` while respecting each protocol's per-tier
        cap. Water-fill: protocols that would breach their cap are frozen at the cap
        and the remaining budget is redistributed across the rest, until stable.
        Any budget that cannot be placed (all capped) is simply left undeployed."""
        remaining = {p: w for p, w in raw.items() if w > 0}
        if not remaining or target <= 0:
            return {}
        frozen: Dict[str, float] = {}
        budget = target
        # At most one freeze per protocol → bounded loop.
        for _ in range(len(remaining) + 1):
            raw_total = sum(remaining.values())
            if raw_total <= 0:
                break
            scaled = {p: w / raw_total * budget for p, w in remaining.items()}
            breaches = {p: _cap_for(p) for p, s in scaled.items() if s > _cap_for(p) + 1e-12}
            if not breaches:
                frozen.update(scaled)
                remaining = {}
                break
            for p, cap in breaches.items():
                frozen[p] = cap
                budget -= cap
                remaining.pop(p, None)
            if budget <= 0 or not remaining:
                break
        return frozen

    def _enforce_t2_cap(self, weights: Dict[str, float]) -> Dict[str, float]:
        """If aggregate T2 weight exceeds T2_TOTAL_CAP, scale T2 down to the cap.
        Freed weight stays in cash (conservative; does not force-feed T1)."""
        t2 = {p: w for p, w in weights.items() if PROTOCOL_TIERS.get(p) == "T2"}
        t2_total = sum(t2.values())
        if t2_total <= T2_TOTAL_CAP or t2_total <= 0:
            return weights
        scale = T2_TOTAL_CAP / t2_total
        return {p: (w * scale if PROTOCOL_TIERS.get(p) == "T2" else w)
                for p, w in weights.items()}

    def get_weights(
        self,
        current_apys: Optional[Dict[str, float]] = None,
        mean_apys: Optional[Dict[str, float]] = None,
    ) -> Dict[str, float]:
        return self.compute_weights(current_apys, mean_apys)

    def get_allocation(
        self,
        capital_usd: float,
        current_apys: Optional[Dict[str, float]] = None,
        mean_apys: Optional[Dict[str, float]] = None,
    ) -> Dict[str, float]:
        """Target USD allocation per venue. Empty on non-positive capital."""
        if capital_usd <= 0.0:
            return {}
        weights = self.compute_weights(current_apys, mean_apys)
        return {p: round(capital_usd * w, 6) for p, w in weights.items()}

    # ── Expected return ──────────────────────────────────────────────────────────

    def get_expected_apy(
        self,
        current_apys: Optional[Dict[str, float]] = None,
        mean_apys: Optional[Dict[str, float]] = None,
    ) -> float:
        """Weighted expected APY (%) of the proposed book (cash earns 0)."""
        current_apys = current_apys or dict(APY_DEFAULTS)
        weights = self.compute_weights(current_apys, mean_apys)
        weighted = 0.0
        for p, w in weights.items():
            if p == CASH_KEY:
                continue
            weighted += w * float(current_apys.get(p, APY_DEFAULTS.get(p, 0.0)))
        return round(weighted, 4)

    # ── Summaries ────────────────────────────────────────────────────────────────

    def get_risk_summary(self, weights: Optional[Dict[str, float]] = None) -> Dict:
        weights = weights or self.compute_weights()
        t1 = sum(w for p, w in weights.items() if PROTOCOL_TIERS.get(p) == "T1")
        t2 = sum(w for p, w in weights.items() if PROTOCOL_TIERS.get(p) == "T2")
        cash = weights.get(CASH_KEY, 0.0)
        return {
            "strategy_id":      STRATEGY_ID,
            "risk_score":       RISK_SCORE,
            "t1_weight_pct":    round(t1 * 100.0, 2),
            "t2_weight_pct":    round(t2 * 100.0, 2),
            "cash_weight_pct":  round(cash * 100.0, 2),
            "max_drawdown_pct": MAX_DRAWDOWN_PCT,
        }

    def simulate(
        self,
        capital_usd: float,
        current_apys: Optional[Dict[str, float]] = None,
        mean_apys: Optional[Dict[str, float]] = None,
    ) -> Dict:
        means = mean_apys or self.load_mean_apys()
        cur = current_apys or dict(APY_DEFAULTS)
        if capital_usd <= 0.0:
            return {
                "strategy_id":               STRATEGY_ID,
                "total_capital":             capital_usd,
                "allocation":                {},
                "expected_annual_yield_usd": 0.0,
                "expected_apy_pct":          0.0,
                "regime":                    self.detect_regime(self.deviation_scores(cur, means)),
                "status":                    "no_capital",
                "timestamp_utc":             datetime.now(timezone.utc).isoformat(),
            }
        weights = self.compute_weights(cur, means)
        apy = self.get_expected_apy(cur, means)
        deviations = self.deviation_scores(cur, means)
        return {
            "strategy_id":               STRATEGY_ID,
            "total_capital":             capital_usd,
            "weights":                   weights,
            "allocation":                {p: round(capital_usd * w, 6) for p, w in weights.items()},
            "expected_annual_yield_usd": round(capital_usd * apy / 100.0, 4),
            "expected_apy_pct":          apy,
            "deviation_scores":          deviations,
            "regime":                    self.detect_regime(deviations),
            "mean_apys":                 means,
            "risk_summary":              self.get_risk_summary(weights),
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
            "protocol_tiers":   {p: PROTOCOL_TIERS[p] for p in PROTOCOLS},
            "mean_apy_defaults": dict(MEAN_APY_DEFAULTS),
            "tilt":             TILT,
            "min_weight":       MIN_WEIGHT,
            "cash_buffer":      CASH_BUFFER,
            "per_protocol_cap": dict(PER_PROTOCOL_CAP),
            "t2_total_cap":     T2_TOTAL_CAP,
            "mean_window_days": MEAN_WINDOW_DAYS,
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
            module="spa_core.strategies.s45_mean_reversion",
            handler_class="S45MeanReversion",
            tags=["mean_reversion", "contrarian", "deviation", "regime_aware",
                  "apy_normalization", "advisory", "s45"],
        ))
    except Exception as exc:   # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning(
            "S45MeanReversion auto-registration failed: %s", exc
        )


_register()


if __name__ == "__main__":
    strat = S45MeanReversion()
    print(json.dumps(strat.simulate(100_000.0), indent=2))
    # Depressed-Aave reversion bet (the canonical example):
    depressed = {"aave_v3": 1.57, "compound_v3": 4.80, "morpho_blue": 6.50,
                 "yearn_v3": 5.00, "sky_susds": 4.20}
    print(json.dumps(strat.simulate(100_000.0, current_apys=depressed), indent=2))
