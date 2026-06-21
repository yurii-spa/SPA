"""
spa_core/strategies/s50_tournament_champion.py — S50 Tournament Champion

S50 Tournament Champion (meta-strategy)
=======================================
A self-adapting overlay: it does **not** hold any positions of its own.
Each cycle it reads the live tournament ranking, identifies the current
leader (best composite score / 7-day paper APY), and **copies that
strategy's allocation weights**. As the tournament evolves, S50 follows
whoever is winning — a momentum-of-strategies meta-bet.

Resolution order for the copied weights:
  1. Read `data/tournament_ranking.json` → top-ranked `strategy_id`.
  2. Look the leader up in the REGISTRY; import its module; copy its
     `WEIGHTS` / `ALLOCATION_WEIGHTS` (or call `get_allocation`).
  3. If the leader is unresolvable (no data, unknown id, no weights, or a
     self-reference to S50), fall back to the **S0 equal-weight** book:
     Aave / Compound / Sky at ⅓ each (conservative all-T1 default).

The fallback makes S50 fully deterministic and safe even with an empty or
malformed tournament file — it always produces a valid, policy-shaped book.

Expected APY: dynamic — tracks the leader's expected APY; the S0 fallback
yields ~3.8% (0.333*(3.6+3.9+4.0) = 3.833%).

Rules:
  - stdlib only, read-only / advisory, LLM FORBIDDEN
  - approved=False from RiskPolicy cannot be overridden
  - never copies its own weights (anti-recursion guard)
  - atomic data/ writes only — this module writes nothing (read-only of data/)

Date: 2026-06-21 (S46–S50 income batch)
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from spa_core.strategies._income_common import (
    AdapterAPYMixin,
    PROTOCOL_TIER,
    PROTOCOL_RISK_SCORE,
    MIN_APY_ELIGIBLE,
    MAX_APY_ELIGIBLE,
)

# ─── Strategy identity ────────────────────────────────────────────────────────

STRATEGY_ID   = "S50"
STRATEGY_NAME = "Tournament Champion"
TIER          = "T2"   # meta — may copy a T1/T2 leader; default fallback is T1
DESCRIPTION   = (
    "Meta-strategy: copies the allocation weights of the current tournament "
    "leader (best 7-day paper APY) each cycle — adapts as the tournament "
    "evolves. Falls back to S0 equal-weight (Aave/Compound/Sky ⅓ each) when "
    "no tournament data is available. Holds no positions of its own."
)

# ─── S0 equal-weight fallback book (all T1) ───────────────────────────────────

S0_FALLBACK_WEIGHTS: Dict[str, float] = {
    "aave_v3":     1.0 / 3.0,
    "compound_v3": 1.0 / 3.0,
    "sky_susds":   1.0 / 3.0,
}

# Default tournament ranking source (read-only).
_DEFAULT_RANKING_FILE = "tournament_ranking.json"

# All slots S50 might touch via fallback / copied leaders (for adapter loading).
_ALL_KEYS: List[str] = list(PROTOCOL_TIER.keys())

# ─── Target metrics ───────────────────────────────────────────────────────────

TARGET_APY_PCT: float = 3.8           # nominal (S0-fallback) — actual tracks leader
TARGET_APY_MIN: float = 3.0
TARGET_APY_MAX: float = 6.0
RISK_SCORE:     float = 0.30
MAX_DRAWDOWN_PCT: float = 5.0


class TournamentChampionStrategy(AdapterAPYMixin):
    """S50 — Tournament Champion: copies the current leader's weights.

    Stdlib only, advisory/read-only. RiskPolicy approved=False is final.

    Args:
        data_dir: directory containing tournament_ranking.json. Defaults to the
                  repo-level data/ directory. Injectable for tests.
    """

    STRATEGY_ID    = STRATEGY_ID
    STRATEGY_NAME  = STRATEGY_NAME
    TIER           = TIER
    TARGET_APY_PCT = TARGET_APY_PCT
    RISK_SCORE     = RISK_SCORE

    def __init__(self, data_dir: Optional[str] = None) -> None:
        self._simulate_history: List[Dict] = []
        if data_dir is not None:
            self._data_dir = Path(data_dir)
        else:
            # spa_core/strategies/ → repo root → data/
            self._data_dir = Path(__file__).resolve().parent.parent.parent / "data"
        self._load_adapters()

    def _adapter_keys(self) -> List[str]:
        return list(_ALL_KEYS)

    # ── Tournament leader resolution ──────────────────────────────────────────

    def get_leader_id(self) -> Optional[str]:
        """Top-ranked strategy_id from the tournament ranking file, or None."""
        ranking_path = self._data_dir / _DEFAULT_RANKING_FILE
        try:
            with open(ranking_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception:   # noqa: BLE001 — missing/malformed → no leader
            return None
        strategies = data.get("strategies") if isinstance(data, dict) else None
        if not isinstance(strategies, list) or not strategies:
            return None
        # Prefer explicit rank==1, else first entry.
        leader = None
        for s in strategies:
            if isinstance(s, dict) and s.get("rank") == 1:
                leader = s
                break
        if leader is None and isinstance(strategies[0], dict):
            leader = strategies[0]
        if not isinstance(leader, dict):
            return None
        sid = leader.get("strategy_id")
        return str(sid) if sid is not None else None

    def _leader_weights(self, leader_id: str) -> Optional[Dict[str, float]]:
        """Best-effort copy of a leader strategy's weight vector.

        Returns a {slot: weight} dict, or None if the leader is unresolvable.
        Anti-recursion: never copies S50 itself.
        """
        if not leader_id or leader_id.upper() == STRATEGY_ID:
            return None
        try:
            from spa_core.strategies.strategy_registry import REGISTRY
        except Exception:   # noqa: BLE001
            return None
        meta = REGISTRY.get(leader_id)
        if meta is None:
            return None
        try:
            import importlib
            mod = importlib.import_module(meta.module)
        except Exception:   # noqa: BLE001
            return None
        # 1) module-level WEIGHTS / ALLOCATION_WEIGHTS
        for attr in ("WEIGHTS", "ALLOCATION_WEIGHTS"):
            weights = getattr(mod, attr, None)
            if isinstance(weights, dict) and weights:
                clean = {k: float(v) for k, v in weights.items()
                         if k in PROTOCOL_TIER and isinstance(v, (int, float))}
                if clean:
                    return self._normalize_weights(clean)
        # 2) instantiate handler and call get_allocation($1) → relative weights
        try:
            cls = getattr(mod, meta.handler_class)
            inst = cls()
            alloc = inst.get_allocation(1.0)   # type: ignore[attr-defined]
            if isinstance(alloc, dict) and alloc:
                clean = {k: float(v) for k, v in alloc.items()
                         if k in PROTOCOL_TIER and isinstance(v, (int, float)) and v > 0}
                if clean:
                    return self._normalize_weights(clean)
        except Exception:   # noqa: BLE001
            pass
        return None

    @staticmethod
    def _normalize_weights(weights: Dict[str, float]) -> Dict[str, float]:
        """Scale a weight dict so the values sum to 1.0 (drops if total ≤ 0)."""
        total = sum(weights.values())
        if total <= 0:
            return dict(S0_FALLBACK_WEIGHTS)
        return {k: v / total for k, v in weights.items()}

    def get_active_weights(self) -> Dict[str, float]:
        """The weight vector S50 will deploy this cycle (leader's, or S0 fallback)."""
        leader_id = self.get_leader_id()
        if leader_id is not None:
            copied = self._leader_weights(leader_id)
            if copied:
                return copied
        return dict(S0_FALLBACK_WEIGHTS)

    def is_following_leader(self) -> bool:
        """True if S50 resolved a real leader's weights this cycle (not fallback)."""
        leader_id = self.get_leader_id()
        return bool(leader_id is not None and self._leader_weights(leader_id))

    # ── Public API ────────────────────────────────────────────────────────────

    def get_allocation(self, capital_usd: float) -> Dict[str, float]:
        weights = self.get_active_weights()
        if capital_usd <= 0.0:
            return {k: 0.0 for k in weights}
        out: Dict[str, float] = {}
        for key, w in weights.items():
            if self._is_eligible(key):
                out[key] = round(capital_usd * w, 6)
        return out

    def get_expected_apy(self) -> float:
        weights = self.get_active_weights()
        weighted = 0.0
        for key, w in weights.items():
            if self._is_eligible(key):
                weighted += w * self._get_adapter_apy(key)
        return round(weighted, 4)

    def get_risk_summary(self) -> Dict:
        weights = self.get_active_weights()
        t1 = sum(w for k, w in weights.items() if PROTOCOL_TIER.get(k) == "T1")
        t2 = sum(w for k, w in weights.items() if PROTOCOL_TIER.get(k) == "T2")
        leader_id = self.get_leader_id()
        following = self.is_following_leader()
        return {
            "risk_score":       RISK_SCORE,
            "leader_id":        leader_id,
            "following_leader": following,
            "source":           "leader" if following else "s0_fallback",
            "t1_weight_pct":    round(t1 * 100.0, 2),
            "t2_weight_pct":    round(t2 * 100.0, 2),
            "risk_note": (
                f"S50 Tournament Champion: "
                + (f"copying leader '{leader_id}' weights (T1={t1*100:.0f}% T2={t2*100:.0f}%)."
                   if following else
                   "no resolvable leader → S0 equal-weight fallback (100% T1).")
            ),
        }

    def get_health(self) -> Dict:
        weights = self.get_active_weights()
        slots_info: Dict[str, Dict] = {}
        eligible_count = 0
        for key, w in weights.items():
            eligible = self._is_eligible(key)
            if eligible:
                eligible_count += 1
            slots_info[key] = {
                "weight":   round(w, 6),
                "tier":     PROTOCOL_TIER.get(key, "?"),
                "eligible": eligible,
                "apy":      self._get_adapter_apy(key),
                "loaded":   key in getattr(self, "_adapters", {}),
            }
        if eligible_count == len(weights):
            status = "ok"
        elif eligible_count == 0:
            status = "critical"
        else:
            status = "degraded"
        return {
            "strategy_id":      STRATEGY_ID,
            "name":             STRATEGY_NAME,
            "leader_id":        self.get_leader_id(),
            "following_leader": self.is_following_leader(),
            "eligible_slots":   eligible_count,
            "total_slots":      len(weights),
            "slots":            slots_info,
            "expected_apy":     self.get_expected_apy(),
            "target_apy":       TARGET_APY_PCT,
            "risk_score":       RISK_SCORE,
            "overall_status":   status,
        }

    def simulate(self, capital_usd: float) -> Dict:
        allocation = self.get_allocation(capital_usd)
        if not allocation or capital_usd <= 0.0:
            return {
                "total_capital":             capital_usd,
                "leader_id":                 self.get_leader_id(),
                "allocation":                {},
                "deployed_usd":              0.0,
                "cash_usd":                  max(capital_usd, 0.0),
                "expected_annual_yield_usd": 0.0,
                "expected_apy_pct":          0.0,
                "status":                    "no_capital",
                "slot_results":              {},
                "risk_summary":              self.get_risk_summary(),
                "timestamp_utc":             datetime.now(timezone.utc).isoformat(),
            }
        total_yield = 0.0
        deployed = 0.0
        slot_results: Dict[str, Dict] = {}
        for key, amount in allocation.items():
            apy = self._get_adapter_apy(key)
            annual_yield = amount * (apy / 100.0)
            total_yield += annual_yield
            deployed += amount
            slot_results[key] = {
                "amount_usd":       round(amount, 4),
                "apy_pct":          apy,
                "annual_yield_usd": round(annual_yield, 4),
                "tier":             PROTOCOL_TIER.get(key, "?"),
                "risk_score":       PROTOCOL_RISK_SCORE.get(key, 0.0),
            }
        result = {
            "total_capital":             capital_usd,
            "leader_id":                 self.get_leader_id(),
            "following_leader":          self.is_following_leader(),
            "allocation":                allocation,
            "deployed_usd":              round(deployed, 4),
            "cash_usd":                  round(capital_usd - deployed, 4),
            "expected_annual_yield_usd": round(total_yield, 4),
            "expected_apy_pct":          round(self.get_expected_apy(), 4),
            "status":                    "ok",
            "slot_results":              slot_results,
            "risk_summary":              self.get_risk_summary(),
            "timestamp_utc":             datetime.now(timezone.utc).isoformat(),
        }
        self._simulate_history.append(result)
        if len(self._simulate_history) > 365:
            self._simulate_history = self._simulate_history[-365:]
        return result

    def to_dict(self) -> Dict:
        return {
            "strategy_id":       STRATEGY_ID,
            "strategy_name":     STRATEGY_NAME,
            "tier":              TIER,
            "description":       DESCRIPTION,
            "leader_id":         self.get_leader_id(),
            "following_leader":  self.is_following_leader(),
            "active_weights":    {k: round(v, 6) for k, v in self.get_active_weights().items()},
            "s0_fallback_weights": {k: round(v, 6) for k, v in S0_FALLBACK_WEIGHTS.items()},
            "target_apy_pct":    TARGET_APY_PCT,
            "target_apy_min":    TARGET_APY_MIN,
            "target_apy_max":    TARGET_APY_MAX,
            "risk_score":        RISK_SCORE,
            "max_drawdown_pct":  MAX_DRAWDOWN_PCT,
            "min_apy_eligible":  MIN_APY_ELIGIBLE,
            "max_apy_eligible":  MAX_APY_ELIGIBLE,
            "expected_apy":      self.get_expected_apy(),
            "health":            self.get_health(),
            "risk_summary":      self.get_risk_summary(),
            "timestamp":         datetime.now(timezone.utc).isoformat(),
        }


# ─── Auto-registration ────────────────────────────────────────────────────────

def _register() -> None:
    try:
        from spa_core.strategies.strategy_registry import REGISTRY, StrategyMeta
        REGISTRY.register(StrategyMeta(
            id=STRATEGY_ID,
            name=STRATEGY_NAME,
            type="lending",
            risk_tier="T2",
            target_apy_min=TARGET_APY_MIN,
            target_apy_max=TARGET_APY_MAX,
            max_drawdown_pct=MAX_DRAWDOWN_PCT,
            description=DESCRIPTION,
            module="spa_core.strategies.s50_tournament_champion",
            handler_class="TournamentChampionStrategy",
            tags=[
                "s50", "tournament_champion", "meta", "follow_leader",
                "adaptive", "income", "s0_fallback",
            ],
        ))
    except Exception as exc:   # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning(
            "TournamentChampionStrategy auto-registration failed: %s", exc
        )


_register()
