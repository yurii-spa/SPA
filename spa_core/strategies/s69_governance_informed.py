"""
spa_core/strategies/s69_governance_informed.py — S69 Governance-Informed

S69: Governance-Informed
========================
On-chain governance moves rates before the rate feed does. A passed proposal to
raise a borrow cap, add incentives, or open a new market tends to LIFT a venue's
deposit APY; an emergency pause, risk-reduction, or market offboarding tends to
SUPPRESS it. S69 reads the governance watcher's output
(`data/governance_proposals.json`, produced by
`spa_core.alerts.governance_watcher`) and tilts an equal-weight base book toward
protocols with APY-positive proposals and away from APY-negative ones.

Tilt model (deterministic)
--------------------------
  base_weight  = 1 / N                         (S0-style equal weight)
  direction    = +1  if a venue's active proposals net APY-positive
                 -1  if they net APY-negative
                  0  otherwise / no proposal
  tilted       = base_weight * (1 + GOV_TILT * direction)   (GOV_TILT = 0.10)
  weights are normalized, then the per-protocol caps (T1 40% / T2 20%) and the
  T2 aggregate cap (≤ 50%, ADR-019) are enforced; freed weight falls to cash.

Direction is classified by transparent keyword matching on each ACTIVE
proposal's title + category:
  INCREASE: incentive, reward, emission, gauge, boost, raise/increase cap,
            new market, higher rate, add collateral …
  DECREASE: pause, freeze, halt, emergency, exploit, hack, offboard, deprecate,
            reduce, lower, cut, decrease, risk reduction …
A proposal hitting only DECREASE keywords → −1; only INCREASE → +1; both/neither
→ 0 (neutral). Per-protocol directions are summed and reduced to their sign.

No-governance-data fallback
---------------------------
Missing/empty/unreadable file, or no proposals touching the S69 universe →
the strategy returns the plain S0 equal-weight book (no tilt). Read-only,
offline-safe, never raises.

Rules: stdlib only · read-only / advisory · LLM FORBIDDEN · no execution imports.
The deterministic RiskPolicy gate retains final authority; `approved=False` is
never overridden. S69 emits target weights + the governance signal it used; it
never opens positions itself.

Date: 2026-06-21
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional

# ─── Identity ─────────────────────────────────────────────────────────────────

STRATEGY_ID   = "S69"
STRATEGY_NAME = "Governance-Informed"
TIER          = "T2"   # universe includes T2 venues (Morpho/Yearn) → classified T2
DESCRIPTION   = (
    "Governance-Informed: reads the governance watcher output "
    "(data/governance_proposals.json) and tilts an equal-weight base ±10% toward "
    "protocols with APY-positive active proposals and away from APY-negative ones "
    "(keyword-classified). Caps enforced (T1 40%/T2 20%, T2≤50%). No-data "
    "fallback = S0 equal weight. Advisory-only, deterministic, stdlib."
)

CASH_KEY = "cash"

# ─── Universe ─────────────────────────────────────────────────────────────────

PROTOCOLS: List[str] = ["aave_v3", "compound_v3", "morpho_blue", "yearn_v3", "sky_susds"]

PROTOCOL_TIERS: Dict[str, str] = {
    "aave_v3":     "T1",
    "compound_v3": "T1",
    "sky_susds":   "T1",
    "morpho_blue": "T2",
    "yearn_v3":    "T2",
    CASH_KEY:      "CASH",
}

# Governance source-slug → S69 protocol key.
SLUG_MAP: Dict[str, str] = {
    "aave":        "aave_v3",
    "aave-v3":     "aave_v3",
    "aave_v3":     "aave_v3",
    "compound":    "compound_v3",
    "compound-v3": "compound_v3",
    "compound_v3": "compound_v3",
    "morpho":      "morpho_blue",
    "morpho-blue": "morpho_blue",
    "morpho_blue": "morpho_blue",
    "yearn":       "yearn_v3",
    "yearn-v3":    "yearn_v3",
    "sky":         "sky_susds",
    "maker":       "sky_susds",
    "makerdao":    "sky_susds",
    "sky_susds":   "sky_susds",
}

INCREASE_KEYWORDS = (
    "incentive", "reward", "emission", "gauge", "boost", "raise", "increase",
    "new market", "add market", "add collateral", "higher", "expand", "onboard",
)
DECREASE_KEYWORDS = (
    "pause", "freeze", "halt", "emergency", "exploit", "hack", "offboard",
    "deprecate", "reduce", "lower", "cut", "decrease", "risk reduction", "wind down",
    "sunset",
)

APY_DEFAULTS: Dict[str, float] = {
    "aave_v3":     3.64,
    "compound_v3": 3.78,
    "morpho_blue": 6.87,
    "yearn_v3":    4.95,
    "sky_susds":   4.20,
}

# ─── Model parameters ─────────────────────────────────────────────────────────

GOV_TILT:        float = 0.10   # ±10% overweight/underweight per governance signal
PER_PROTOCOL_CAP: Dict[str, float] = {"T1": 0.40, "T2": 0.20}
T2_TOTAL_CAP:    float = 0.50

# ─── Targets / risk ───────────────────────────────────────────────────────────

TARGET_APY_MIN:   float = 4.0
TARGET_APY_MAX:   float = 5.2
RISK_SCORE:       float = 0.42
MAX_DRAWDOWN_PCT: float = 3.0


def _is_number(x: object) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and x == x


def _cap_for(protocol: str) -> float:
    return PER_PROTOCOL_CAP.get(PROTOCOL_TIERS.get(protocol, "T2"), 0.20)


def _default_gov_paths() -> List[str]:
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(os.path.dirname(here))
    data = os.path.join(root, "data")
    # Prefer the real watcher output; accept the alerts alias for forward-compat.
    return [os.path.join(data, "governance_proposals.json"),
            os.path.join(data, "governance_alerts.json")]


class S69GovernanceInformed:
    """S69 — Governance-Informed (proposal-tilted equal-weight book)."""

    STRATEGY_ID   = STRATEGY_ID
    STRATEGY_NAME = STRATEGY_NAME
    TIER          = TIER
    RISK_SCORE    = RISK_SCORE

    def __init__(self, gov_path: Optional[str] = None):
        self.gov_paths = [gov_path] if gov_path else _default_gov_paths()

    # ── Governance loading ────────────────────────────────────────────────────────

    def load_proposals(self) -> List[dict]:
        """Load proposals from the first readable governance file. Never raises."""
        for path in self.gov_paths:
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    doc = json.load(fh)
            except (OSError, ValueError):
                continue
            if isinstance(doc, dict) and isinstance(doc.get("proposals"), list):
                return doc["proposals"]
            if isinstance(doc, list):
                return doc
        return []

    @staticmethod
    def _classify(proposal: dict) -> int:
        """+1 (APY-positive), -1 (APY-negative), or 0 (neutral) for a proposal."""
        text = " ".join(str(proposal.get(k, "")) for k in ("title", "category")).lower()
        up = any(kw in text for kw in INCREASE_KEYWORDS)
        down = any(kw in text for kw in DECREASE_KEYWORDS)
        if up and not down:
            return 1
        if down and not up:
            return -1
        return 0

    def governance_signal(self, proposals: Optional[List[dict]] = None) -> Dict[str, int]:
        """Net APY-direction sign per S69 protocol from ACTIVE proposals."""
        proposals = self.load_proposals() if proposals is None else proposals
        raw: Dict[str, int] = {}
        for p in proposals:
            if not isinstance(p, dict):
                continue
            if str(p.get("state", "active")).lower() not in ("active", "pending"):
                continue
            slug = str(p.get("protocol", "")).lower()
            key = SLUG_MAP.get(slug)
            if key is None or key not in PROTOCOLS:
                continue
            raw[key] = raw.get(key, 0) + self._classify(p)
        # Reduce to sign.
        return {k: (1 if v > 0 else -1 if v < 0 else 0) for k, v in raw.items()}

    # ── Allocation ──────────────────────────────────────────────────────────────

    def _enforce_caps(self, weights: Dict[str, float]) -> Dict[str, float]:
        capped = {p: min(w, _cap_for(p)) for p, w in weights.items()}
        t2_total = sum(w for p, w in capped.items() if PROTOCOL_TIERS.get(p) == "T2")
        if t2_total > T2_TOTAL_CAP and t2_total > 0:
            scale = T2_TOTAL_CAP / t2_total
            capped = {p: (w * scale if PROTOCOL_TIERS.get(p) == "T2" else w)
                      for p, w in capped.items()}
        deployed = sum(capped.values())
        out = {p: round(w, 6) for p, w in capped.items() if w > 0}
        cash = max(0.0, 1.0 - deployed)
        if cash > 1e-9:
            out[CASH_KEY] = round(cash, 6)
        return out

    def compute_weights(self, proposals: Optional[List[dict]] = None) -> Dict[str, float]:
        """Equal-weight base tilted ±GOV_TILT by governance signal, then capped.

        No relevant governance signal → plain S0 equal weight (cap-enforced)."""
        base = 1.0 / len(PROTOCOLS)
        signal = self.governance_signal(proposals)
        if not any(signal.values()):
            return self._enforce_caps({p: base for p in PROTOCOLS})
        tilted = {p: base * (1.0 + GOV_TILT * signal.get(p, 0)) for p in PROTOCOLS}
        total = sum(tilted.values())
        normalized = {p: w / total for p, w in tilted.items()} if total > 0 else {}
        return self._enforce_caps(normalized)

    def get_weights(self, proposals: Optional[List[dict]] = None) -> Dict[str, float]:
        return self.compute_weights(proposals)

    def get_allocation(self, capital_usd: float,
                       proposals: Optional[List[dict]] = None) -> Dict[str, float]:
        if capital_usd <= 0.0:
            return {}
        return {p: round(capital_usd * w, 6) for p, w in self.compute_weights(proposals).items()}

    # ── Expected return ──────────────────────────────────────────────────────────

    def get_expected_apy(self, current_apys: Optional[Dict[str, float]] = None,
                         proposals: Optional[List[dict]] = None) -> float:
        apys = current_apys or dict(APY_DEFAULTS)
        weights = self.compute_weights(proposals)
        weighted = 0.0
        for p, w in weights.items():
            if p == CASH_KEY:
                continue
            apy = apys.get(p, APY_DEFAULTS.get(p, 0.0))
            weighted += w * (float(apy) if _is_number(apy) else APY_DEFAULTS.get(p, 0.0))
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

    def simulate(self, capital_usd: float,
                 current_apys: Optional[Dict[str, float]] = None,
                 proposals: Optional[List[dict]] = None) -> Dict:
        cur = current_apys or dict(APY_DEFAULTS)
        signal = self.governance_signal(proposals)
        if capital_usd <= 0.0:
            return {
                "strategy_id":               STRATEGY_ID,
                "total_capital":             capital_usd,
                "allocation":                {},
                "expected_annual_yield_usd": 0.0,
                "expected_apy_pct":          0.0,
                "governance_signal":         signal,
                "status":                    "no_capital",
                "timestamp_utc":             datetime.now(timezone.utc).isoformat(),
            }
        weights = self.compute_weights(proposals)
        apy = self.get_expected_apy(cur, proposals)
        return {
            "strategy_id":               STRATEGY_ID,
            "total_capital":             capital_usd,
            "governance_signal":         signal,
            "used_fallback":             not any(signal.values()),
            "weights":                   weights,
            "allocation":                {p: round(capital_usd * w, 6) for p, w in weights.items()},
            "expected_annual_yield_usd": round(capital_usd * apy / 100.0, 4),
            "expected_apy_pct":          apy,
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
            "slug_map":         dict(SLUG_MAP),
            "gov_tilt":         GOV_TILT,
            "increase_keywords": list(INCREASE_KEYWORDS),
            "decrease_keywords": list(DECREASE_KEYWORDS),
            "per_protocol_cap": dict(PER_PROTOCOL_CAP),
            "t2_total_cap":     T2_TOTAL_CAP,
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
            module="spa_core.strategies.s69_governance_informed",
            handler_class="S69GovernanceInformed",
            tags=["governance", "proposal_aware", "event_driven", "tilt",
                  "advisory", "s69"],
        ))
    except Exception as exc:   # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning(
            "S69GovernanceInformed auto-registration failed: %s", exc
        )


_register()


if __name__ == "__main__":
    strat = S69GovernanceInformed()
    print(json.dumps(strat.simulate(100_000.0), indent=2))
    demo = [
        {"protocol": "aave", "title": "Raise USDC borrow cap + add incentives",
         "category": "risk_param", "state": "active"},
        {"protocol": "compound", "title": "Emergency pause of USDC market",
         "category": "emergency", "state": "active"},
    ]
    print(json.dumps(strat.simulate(100_000.0, proposals=demo), indent=2))
