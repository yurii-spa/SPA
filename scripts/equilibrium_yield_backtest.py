#!/usr/bin/env python3
"""Idea #6 — Equilibrium Yield Controller (EYC): allocate on EQUILIBRIUM yield, not spot yield.

THESIS (docs/DYNAMIC_LEVERAGE_GUARDIAN.md registry): lending APY is a DETERMINISTIC public
function of utilization; an APY spike is an out-of-equilibrium state that mean-reverts as crowd
capital flows in. Every naive aggregator allocates on SPOT APY — arriving at 8%, holding while
the crowd dilutes it back to 4%, and paying switching costs for yield that was never going to
persist. The EYC scores each venue by its expected yield OVER THE HOLDING HORIZON — shrinking
spikes toward the venue's own baseline at the venue's own measured decay speed — and switches
only when the equilibrium gain clears amortized costs.

This backtest measures, on REAL 365-day daily APY history (data/historical_apy/, 4 USDC venues —
sky excluded: policy pins sUSDS to 0%):
  1. SPIKE DECAY EVIDENCE — do APY spikes actually mean-revert, and how fast (per-venue half-life)?
  2. STRATEGY RACE (identical costs, 1-day execution lag, no look-ahead):
       spot_chaser   — daily move to max SPOT apy (what naive aggregators do)
       eyc           — move to max EQUILIBRIUM score iff gain > amortized switch cost
       best_single   — buy-and-hold the ex-post best venue (hindsight upper reference)
       equal_weight  — static 1/N (the no-skill floor)
Honest limits: DAILY bars → intraday kink-harvest is invisible here (separate, finer-data test);
the decay model is fitted on the SAME series it trades (in-sample) → the verdict below runs a
train/test split (first 6 months fit half-lives / last 6 months trade) to be honest.
stdlib-only, deterministic. LLM FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parents[1]
HIST = ROOT / "data" / "historical_apy"
VENUES = ["aave_v3_usdc", "compound_v3_usdc", "morpho_blue_usdc", "yearn_v3_usdc"]
SWITCH_COST_BPS = 2.0     # USDC→USDC venue move: gas + approval, generous for L2s
HORIZON_D = 14            # holding horizon the equilibrium score integrates over
SPIKE_MULT = 1.35         # spike = apy > trailing-median × this
BASELINE_W = 30           # trailing window for the venue baseline


def load() -> dict[str, dict[str, float]]:
    out = {}
    for v in VENUES:
        rows = json.loads((HIST / f"{v}.json").read_text())
        out[v] = {r["date"]: float(r["apy"]) for r in rows if r.get("apy") is not None}
    return out


def common_dates(series: dict) -> list[str]:
    ds = set.intersection(*(set(s) for s in series.values()))
    return sorted(ds)


# ── 1. spike decay evidence ────────────────────────────────────────────────────────────────────
def spike_decay(series: dict, dates: list[str]) -> dict:
    per_venue = {}
    for v, s in series.items():
        events = []
        for i in range(BASELINE_W, len(dates) - 1):
            base = median(s[d] for d in dates[i - BASELINE_W:i])
            apy = s[dates[i]]
            if base > 0.2 and apy > SPIKE_MULT * base and (i == BASELINE_W or s[dates[i - 1]] <= SPIKE_MULT * median(s[d] for d in dates[i - 1 - BASELINE_W:i - 1])):
                # measure half-life: days until apy falls below (apy+base)/2
                target = (apy + base) / 2.0
                hl = None
                for j in range(i + 1, min(i + 60, len(dates))):
                    if s[dates[j]] <= target:
                        hl = j - i
                        break
                events.append({"date": dates[i], "apy": round(apy, 3), "baseline": round(base, 3),
                               "half_life_d": hl})
        hls = [e["half_life_d"] for e in events if e["half_life_d"] is not None]
        per_venue[v] = {"spikes": len(events),
                        "decayed": len(hls),
                        "median_half_life_d": (median(hls) if hls else None),
                        "events": events[:6]}
    return per_venue


# ── 2. strategy race ───────────────────────────────────────────────────────────────────────────
def eq_score(apy: float, base: float, half_life: float, horizon: int) -> float:
    """Mean APY over the horizon if the excess (apy−base) halves every half_life days."""
    if half_life is None or half_life <= 0:
        return base  # no measured persistence → trust only the baseline
    lam = 0.5 ** (1.0 / half_life)
    excess = apy - base
    # mean of excess·lam^t over t=0..H-1
    geo = (1 - lam ** horizon) / (horizon * (1 - lam)) if lam < 1 else 1.0
    return base + excess * geo


def run_race(series: dict, dates: list[str], half_lives: dict[str, float],
             start_i: int) -> dict:
    cost_daily = SWITCH_COST_BPS / 100.0  # in APY-percent units charged once per switch on equity
    res = {}

    def realized(pick_fn, threshold: float = 0.0) -> dict:
        eq = 100_000.0
        held = None
        switches = 0
        for i in range(start_i, len(dates) - 1):
            pick = pick_fn(i, held, threshold)
            if pick != held:
                if held is not None:
                    eq *= (1 - cost_daily / 100.0)
                    switches += 1
                held = pick
            # earn TOMORROW's apy of today's pick (1-day lag, no look-ahead)
            apy_next = series[held][dates[i + 1]]
            eq *= (1 + apy_next / 100.0 / 365.0)
        days = len(dates) - 1 - start_i
        return {"apy_net_pct": round(((eq / 100_000.0) ** (365.0 / days) - 1) * 100, 3),
                "switches": switches}

    def spot_pick(i, held, thr):
        return max(VENUES, key=lambda v: series[v][dates[i]])

    def eyc_pick(i, held, thr):
        base = {v: median(series[v][d] for d in dates[max(0, i - BASELINE_W):i] or dates[:1])
                for v in VENUES}
        score = {v: eq_score(series[v][dates[i]], base[v], half_lives.get(v), HORIZON_D)
                 for v in VENUES}
        best = max(VENUES, key=lambda v: score[v])
        if held is not None and score[best] - score[held] < thr:
            return held  # not worth the churn
        return best

    res["spot_chaser"] = realized(spot_pick)
    res["eyc"] = realized(eyc_pick, threshold=SWITCH_COST_BPS / 100.0 * 365.0 / HORIZON_D)
    # baselines
    days = len(dates) - 1 - start_i
    for v in VENUES:
        eqv = 100_000.0
        for i in range(start_i, len(dates) - 1):
            eqv *= (1 + series[v][dates[i + 1]] / 100.0 / 365.0)
        res.setdefault("hold_each", {})[v] = round(((eqv / 1e5) ** (365.0 / days) - 1) * 100, 3)
    res["best_single_hindsight"] = max(res["hold_each"].values())
    ew = 100_000.0
    for i in range(start_i, len(dates) - 1):
        r = sum(series[v][dates[i + 1]] for v in VENUES) / len(VENUES)
        ew *= (1 + r / 100.0 / 365.0)
    res["equal_weight"] = round(((ew / 1e5) ** (365.0 / days) - 1) * 100, 3)
    return res


def main() -> int:
    series = load()
    dates = common_dates(series)
    print(f"venues={len(VENUES)} common_days={len(dates)} ({dates[0]}..{dates[-1]})")

    print("\n== 1. SPIKE DECAY EVIDENCE (does spot yield mean-revert?) ==")
    decay = spike_decay(series, dates)
    for v, d in decay.items():
        print(f"  {v:22s} spikes={d['spikes']:2d} decayed={d['decayed']:2d} "
              f"median_half_life={d['median_half_life_d']}d")

    # honest split: fit half-lives on first half, trade the second half only
    mid = len(dates) // 2
    train_dates = dates[:mid]
    hl_train = {v: (spike_decay({v: series[v]}, train_dates)[v]["median_half_life_d"] or 7)
                for v in VENUES}
    print(f"\n== 2. STRATEGY RACE (train {dates[0]}..{dates[mid-1]} fits half-lives "
          f"{hl_train}; trade {dates[mid]}..{dates[-1]}, cost {SWITCH_COST_BPS}bps/switch, "
          f"1-day lag) ==")
    race = run_race(series, dates, hl_train, start_i=mid)
    for k in ("spot_chaser", "eyc"):
        print(f"  {k:22s} net_apy={race[k]['apy_net_pct']}%  switches={race[k]['switches']}")
    print(f"  equal_weight           net_apy={race['equal_weight']}%")
    print(f"  hold-each              {race['hold_each']}")
    print(f"  best_single(hindsight) {race['best_single_hindsight']}%")
    print("\nHONEST NOTES: daily bars (intraday kink-harvest invisible); decay fitted on train "
          "half only; 1-day lag both strategies; venue set = 4 real USDC T1/T2 venues.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
