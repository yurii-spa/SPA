"""EYC v2 — the Equilibrium Yield Controller SHADOW allocator (registry idea #6, OOS-validated).

THE ALGORITHM (what no aggregator on the market computes):
  1. EQUILIBRIUM, not spot: lending APY is a deterministic public function of utilization, so a
     spike is an out-of-equilibrium state that mean-reverts as crowd capital flows in. Score =
     baseline + (spot − baseline) · geo(half_life, H): the venue's excess yield shrunk toward its
     own baseline at its own MEASURED decay speed (idea #6 backtest: 33/34 spikes decayed,
     half-life 1–5d; EYC beat the spot-chaser +0.53pp net with 10× less churn, OOS).
  2. RATE-IMPACT OF OUR OWN SIZE: our deposit D into a pool of supply S moves utilization down —
     the APY we actually receive is NOT the APY we saw. Below the kink the borrow rate is ~linear
     in utilization, so supply APY ≈ borrow(U)·U scales ≈ (S/(S+D))² — the honest quadratic
     "APY after us". Aggregators see 8%, deposit big, and receive 5%; the EYC prices that BEFORE
     moving. (Assumption documented: below-kink linearity; above-kink decay is FASTER, so the
     quadratic is a conservative-side model for spike states.)
  3. COST-AWARE SWITCHING: a move must clear its amortized cost over the horizon (the backtest's
     churn discipline: 2 switches vs the chaser's 19).

SHADOW-ONLY: this allocator recommends; the live StrategyAllocator + RiskPolicy v1.0 remain the
sole capital path. The shadow's picks vs the naive spot pick are logged per tick (S2-style
evidence) so promoting the EYC into the live cycle is an ADR-with-data, not a vibe.

Inputs (all fleet artifacts, fail-closed): data/apy_ranking.json (live daily spot APY+TVL from
the cycle) + data/historical_apy/<venue>.json (baseline + measured half-life). A venue without
baseline history or TVL is listed UNSCORED — never guessed. Writes ONLY data/swarm/.
Deterministic, stdlib-only. LLM FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Dict, List, Optional

from spa_core.strategy_lab.swarm.common import append_daily_proof
from spa_core.utils.atomic import atomic_save

__all__ = ["run_eyc_allocator", "eq_score", "dilution_at_size", "measure_half_life"]

REPO_ROOT = Path(__file__).resolve().parents[3]
RANKING_PATH = REPO_ROOT / "data" / "apy_ranking.json"
HIST_DIR = REPO_ROOT / "data" / "historical_apy"
SWARM_DIR = REPO_ROOT / "data" / "swarm"
STATUS_NAME = "eyc_allocator.json"
PROOF_NAME = "eyc_allocator_proof.jsonl"

# venue ↔ live-ranking protocol id (only venues with real baseline history are scoreable)
VENUE_MAP = {
    "aave_v3_usdc": "aave_v3",
    "compound_v3_usdc": "compound_v3",
    "morpho_blue_usdc": "morpho_blue",
    "yearn_v3_usdc": "yearn_v3",
}
AUM_LEVELS_USD = [100_000, 1_000_000, 10_000_000, 50_000_000]
HORIZON_D = 14
BASELINE_W = 30
SPIKE_MULT = 1.35
DEFAULT_HALF_LIFE_D = 7.0
RANKING_MAX_AGE_H = 36.0  # daily producer; older → fail-closed UNAVAILABLE


def eq_score(spot: float, base: float, half_life: Optional[float], horizon: int = HORIZON_D) -> float:
    """Expected mean APY over the horizon with the excess halving every half_life days."""
    if half_life is None or half_life <= 0:
        return base
    lam = 0.5 ** (1.0 / half_life)
    geo = (1 - lam ** horizon) / (horizon * (1 - lam)) if lam < 1 else 1.0
    return base + (spot - base) * geo


def dilution_at_size(deposit_usd: float, supply_usd: float) -> Optional[float]:
    """(S/(S+D))² — the below-kink quadratic 'APY after us' factor. None if supply unknown."""
    if not supply_usd or supply_usd <= 0:
        return None
    return (supply_usd / (supply_usd + max(0.0, deposit_usd))) ** 2


def measure_half_life(apys: List[float]) -> Optional[float]:
    """Median spike half-life of a daily APY series (the venue's own measured decay speed)."""
    hls: List[float] = []
    for i in range(BASELINE_W, len(apys) - 1):
        base = median(apys[i - BASELINE_W:i])
        if base <= 0.2 or apys[i] <= SPIKE_MULT * base:
            continue
        prev_base = median(apys[i - 1 - BASELINE_W:i - 1]) if i > BASELINE_W else base
        if i > BASELINE_W and apys[i - 1] > SPIKE_MULT * prev_base:
            continue  # not a fresh spike onset
        target = (apys[i] + base) / 2.0
        for j in range(i + 1, min(i + 60, len(apys))):
            if apys[j] <= target:
                hls.append(float(j - i))
                break
    return median(hls) if hls else None


def _load_baselines() -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    for venue in VENUE_MAP:
        try:
            rows = json.loads((HIST_DIR / f"{venue}.json").read_text())
            apys = [float(r["apy"]) for r in rows if isinstance(r.get("apy"), (int, float))]
        except (OSError, ValueError):
            continue
        if len(apys) >= BASELINE_W + 2:
            out[venue] = {"baseline": median(apys[-BASELINE_W:]),
                          "half_life_d": measure_half_life(apys),
                          "history_days": len(apys)}
    return out


def run_eyc_allocator(
    ranking_path: Path = RANKING_PATH,
    hist_dir: Path = HIST_DIR,  # noqa: ARG001 — kept for test injection symmetry
    out_dir: Path = SWARM_DIR,
    now: Optional[datetime] = None,
    baselines: Optional[Dict[str, dict]] = None,
) -> dict:
    now = now or datetime.now(timezone.utc)
    try:
        ranking = json.loads(ranking_path.read_text())
    except (OSError, ValueError):
        ranking = None

    doc: dict = {
        "domain": "swarm.eyc_allocator",
        "label": "EYC v2 shadow allocator / ADVISORY / SHADOW-ONLY — live allocator untouched",
        "is_advisory": True,
        "outside_riskpolicy": True,
        "as_of_utc": now.isoformat(timespec="seconds"),
        "algorithm": {
            "equilibrium": "score = baseline + (spot−baseline)·geo(half_life, H=14d) — excess "
                           "shrunk at the venue's own measured decay speed (idea #6, OOS-validated)",
            "rate_impact": "apy_after_us = apy · (S/(S+D))² — below-kink quadratic; the APY we "
                           "would RECEIVE, not the APY we SEE",
            "authority": "NONE — StrategyAllocator + RiskPolicy v1.0 remain the sole capital path; "
                         "promotion requires an ADR backed by this shadow's logged picks",
        },
    }

    age_ok = False
    if isinstance(ranking, dict):
        try:
            ts = datetime.fromisoformat(str(ranking.get("generated_at", "")).replace("Z", "+00:00"))
            age_ok = (now - ts).total_seconds() / 3600.0 <= RANKING_MAX_AGE_H
        except ValueError:
            age_ok = False
    if not age_ok:
        doc.update({"state": "UNAVAILABLE",
                    "reason": "apy_ranking.json missing/stale — shadow refuses to score (fail-closed)"})
        atomic_save(doc, str(out_dir / STATUS_NAME))
        doc["proof_appended"] = append_daily_proof(
            {"state": "UNAVAILABLE"}, out_dir / PROOF_NAME, day=doc["as_of_utc"][:10])
        return doc

    live = {str(r.get("protocol")): r for r in ranking.get("by_apy") or [] if isinstance(r, dict)}
    baselines = baselines if baselines is not None else _load_baselines()

    venues: Dict[str, dict] = {}
    unscored: List[str] = []
    for venue, proto in VENUE_MAP.items():
        row = live.get(proto)
        b = baselines.get(venue)
        spot = row.get("apy_pct") if row else None
        if not isinstance(spot, (int, float)) or b is None:
            unscored.append(venue)
            continue
        tvl = row.get("tvl_usd")
        score0 = eq_score(float(spot), b["baseline"], b["half_life_d"])
        at_size = {}
        for aum in AUM_LEVELS_USD:
            dil = dilution_at_size(float(aum), float(tvl) if isinstance(tvl, (int, float)) else 0.0)
            at_size[f"${aum:,.0f}"] = (round(score0 * dil, 4) if dil is not None else None)
        venues[venue] = {
            "spot_apy_pct": round(float(spot), 4),
            "baseline_apy_pct": round(b["baseline"], 4),
            "half_life_d": b["half_life_d"],
            "equilibrium_score_pct": round(score0, 4),
            "tvl_usd": tvl,
            "apy_after_us_at_size": at_size,
        }

    picks = {}
    if venues:
        spot_pick = max(venues, key=lambda v: venues[v]["spot_apy_pct"])
        for aum in AUM_LEVELS_USD:
            key = f"${aum:,.0f}"
            scored = {v: d["apy_after_us_at_size"][key] for v, d in venues.items()
                      if d["apy_after_us_at_size"][key] is not None}
            eyc_pick = max(scored, key=scored.get) if scored else None
            picks[key] = {"eyc_pick": eyc_pick,
                          "spot_pick": spot_pick,
                          "divergence": bool(eyc_pick and eyc_pick != spot_pick)}
    doc.update({
        "state": "SCORED" if venues else "NO_SCOREABLE_VENUES",
        "venues": venues,
        "unscored": sorted(unscored),
        "picks": picks,
        "note": ("divergence=true rows are where the naive spot-chaser and the EYC disagree — "
                 "the shadow evidence that accumulates toward the promotion ADR. UNSCORED venues "
                 "lack baseline history or live APY; they are never guessed."),
    })
    atomic_save(doc, str(out_dir / STATUS_NAME))
    payload = {"state": doc["state"],
               "picks": {k: p["eyc_pick"] for k, p in picks.items()},
               "spot_pick": next(iter(picks.values()))["spot_pick"] if picks else None,
               "divergences": sum(1 for p in picks.values() if p["divergence"])}
    doc["proof_appended"] = append_daily_proof(payload, out_dir / PROOF_NAME,
                                               day=doc["as_of_utc"][:10])
    return doc


def main() -> int:
    doc = run_eyc_allocator()
    print(f"swarm.eyc_allocator: state={doc['state']} venues={len(doc.get('venues', {}))} "
          f"unscored={doc.get('unscored')} proof_appended={doc['proof_appended']}")
    for v, d in (doc.get("venues") or {}).items():
        print(f"  {v:20s} spot={d['spot_apy_pct']}% base={d['baseline_apy_pct']}% "
              f"hl={d['half_life_d']}d eq={d['equilibrium_score_pct']}% "
              f"after_us@$10M={d['apy_after_us_at_size'].get('$10,000,000')}%")
    for k, p in (doc.get("picks") or {}).items():
        mark = " ← DIVERGES from spot" if p["divergence"] else ""
        print(f"  pick@{k:12s} eyc={p['eyc_pick']} spot={p['spot_pick']}{mark}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
