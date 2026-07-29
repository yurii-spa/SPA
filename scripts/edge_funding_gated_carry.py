#!/usr/bin/env python3
"""
scripts/edge_funding_gated_carry.py — Idea #22: Funding-Sign-Gated Cash-and-Carry (FSGC)

NOVEL EDGE IDEA #22 (docs/DYNAMIC_LEVERAGE_GUARDIAN.md registry)

WHY THIS IS NOT A REPEAT
  Every prior registry idea takes the BOOKS as given and asks how to size/select/hedge them
  (#1–#21).  #22 goes one level down: it prices the RAW CASH FLOW that the whole sUSDe/DN
  family ultimately lives on — ETH perpetual funding — on the REAL 2-year series, and asks a
  question none of the prior ideas asked:

     "Is the delta-neutral funding carry itself improvable by a causal ON/OFF gate,
      and does it clear the RWA floor (3.31%/yr) AFTER realistic switching costs?"

  This matters for the product: the aggressive tier's carry leg is sold on the claim that
  funding carry is a durable income source.  #22 measures that claim on real data instead of
  assuming it, and it quantifies the exact cost budget the sleeve can afford.

MECHANISM UNDER TEST
  Position (when ON): long ETH spot + short ETH perp = delta-neutral.
     step return = Σ over the step's days of (3 × funding_8h)  − switching cost
  Position (when OFF): flat (cash at 0%), or the RWA floor variant (3.31%/yr).

  GATES (all CAUSAL — the signal only ever uses funding STRICTLY BEFORE the step):
     always     : ON every day (the honest baseline / "buy-and-hold carry")
     sign7      : ON iff median(funding, prev 7d)  > 0
     sign30     : ON iff median(funding, prev 30d) > 0
     thin5      : ON iff annualised carry from median(prev 7d) > 5%/yr
                  (the exact threshold the live agent com.spa.funding_regime already uses)

  MECHANISM PRE-TEST (before any P&L): funding autocorrelation and gate hit-rate.  A gate can
  only work if past funding predicts NEXT-day funding.  If the hit-rate of "m7 > 0 ⇒ next-day
  funding > 0" is no better than the unconditional base rate, the gate is noise and any P&L
  difference is luck.  This is reported FIRST and the verdict is bound to it.

COST MODEL / BREAK-EVEN
  Each ON→OFF or OFF→ON switch costs `round_trip_bps / 2` (one leg) on the full notional —
  both legs (spot + perp) are included in the quoted bps.  Sweep bps ∈ {0, 5, 10, 25, 50, 100}
  and report the BREAK-EVEN cost at which each gate stops beating `always`, and at which the
  sleeve stops clearing the RWA floor.

stdlib-only, deterministic, read-only, LLM FORBIDDEN.
Advisory / paper-only: no live track, no RiskPolicy, no execution path touched.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import datetime
import json
import statistics
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FUNDING = REPO / "data" / "rates_desk" / "funding_deep.json"

OOS_SPLIT = "2025-06-01"
RWA_FLOOR_APY = 3.31            # %/yr — registry constant (real RWA floor)
FUNDING_PERIODS_PER_DAY = 3     # 8h funding
THIN_CARRY_ANN = 0.05           # live funding_regime agent threshold (5%/yr)
GATES = ("always", "sign7", "sign30", "thin5")


def _d(s: str) -> datetime.date:
    return datetime.date.fromisoformat(s)


def load_funding() -> dict:
    return {d: float(v) for d, v in json.loads(FUNDING.read_text())["series"].items()}


def med(seq):
    return statistics.median(seq) if seq else 0.0


def gate_on(mode: str, dates: list, funding: dict, i: int) -> bool:
    """Causal gate decision for day dates[i] using ONLY days strictly before it."""
    if mode == "always":
        return True
    lookback = 30 if mode == "sign30" else 7
    end = _d(dates[i]) - datetime.timedelta(days=1)
    window = []
    for k in range(lookback):
        key = (end - datetime.timedelta(days=k)).isoformat()
        if key in funding:
            window.append(funding[key])
    if len(window) < 3:
        return False                                  # fail-closed: no signal → flat
    m = med(window)
    if mode in ("sign7", "sign30"):
        return m > 0
    if mode == "thin5":
        return m * FUNDING_PERIODS_PER_DAY * 365.0 > THIN_CARRY_ANN
    raise ValueError(mode)


def simulate(dates, funding, mode, round_trip_bps, off_apy_pct=0.0):
    """Daily-step simulation. Returns (step returns, stats)."""
    rets, prev_on, switches, on_days = [], False, 0, 0
    for i, d in enumerate(dates):
        on = gate_on(mode, dates, funding, i)
        gross = FUNDING_PERIODS_PER_DAY * funding[d] if on else (off_apy_pct / 100.0) / 365.0
        cost = (round_trip_bps / 2.0) / 10000.0 if on != prev_on else 0.0
        rets.append(gross - cost)
        switches += 1 if on != prev_on else 0
        on_days += 1 if on else 0
        prev_on = on
    return rets, {"switches": switches, "on_days": on_days,
                  "duty_pct": 100.0 * on_days / max(1, len(dates))}


def metrics(dates, rets) -> dict:
    equity, peak, maxdd = 1.0, 1.0, 0.0
    for r in rets:
        equity *= 1.0 + r
        peak = max(peak, equity)
        maxdd = max(maxdd, (peak - equity) / peak)
    cal = max(1, (_d(dates[-1]) - _d(dates[0])).days)
    apy = (equity ** (365.0 / cal) - 1.0) * 100.0
    vol = statistics.pstdev(rets) * (365 ** 0.5) * 100.0 if len(rets) > 1 else 0.0
    return {"apy_pct": apy, "maxDD_pct": maxdd * 100.0,
            "calmar": apy / (maxdd * 100.0) if maxdd > 1e-9 else float("inf"),
            "vol_pct": vol, "sharpe": apy / vol if vol > 1e-9 else float("inf"),
            "days": cal}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    funding = load_funding()
    dates = sorted(funding)
    oos_i = next(i for i, d in enumerate(dates) if d >= OOS_SPLIT)
    vals = [funding[d] for d in dates]

    print("=" * 78)
    print("Idea #22 — Funding-Sign-Gated Cash-and-Carry (FSGC)")
    print("REAL ETH perp funding series (data/rates_desk/funding_deep.json), delta-neutral sleeve")
    print(f"days: {len(dates)}  {dates[0]}..{dates[-1]}   OOS(≥{OOS_SPLIT}): {len(dates)-oos_i}")
    print(f"funding 8h: median {med(vals):.6f} → carry {med(vals)*3*365*100:.2f}%/yr  ·  "
          f"mean {statistics.fmean(vals)*3*365*100:.2f}%/yr  ·  "
          f"negative days {100.0*sum(1 for v in vals if v < 0)/len(vals):.1f}%")

    # ── 0. MECHANISM PRE-TEST — is funding predictable at all? ────────────────────────────────
    print("\n" + "-" * 78)
    print("0. MECHANISM PRE-TEST — can a causal gate know anything?")
    mu = statistics.fmean(vals)
    var = statistics.pvariance(vals)
    for lag in (1, 3, 7, 14):
        pairs = [(vals[i - lag], vals[i]) for i in range(lag, len(vals))]
        cov = sum((a - mu) * (b - mu) for a, b in pairs) / len(pairs)
        print(f"   autocorrelation lag-{lag:<2d} = {cov/var:+.3f}")
    base_rate = 100.0 * sum(1 for v in vals if v > 0) / len(vals)
    print(f"   unconditional P(funding_t > 0)            = {base_rate:.1f}%")
    hitrates = {}
    for mode in ("sign7", "sign30", "thin5"):
        on_idx = [i for i in range(len(dates)) if gate_on(mode, dates, funding, i)]
        hit = 100.0 * sum(1 for i in on_idx if vals[i] > 0) / max(1, len(on_idx))
        off_idx = [i for i in range(len(dates)) if i not in set(on_idx)]
        hit_off = 100.0 * sum(1 for i in off_idx if vals[i] > 0) / max(1, len(off_idx))
        hitrates[mode] = {"on_hit_pct": hit, "off_hit_pct": hit_off,
                          "lift_pp": hit - base_rate, "on_days": len(on_idx)}
        print(f"   P(funding_t > 0 | gate {mode:6s} ON) = {hit:.1f}%  "
              f"(lift {hit-base_rate:+.1f}pp; when OFF: {hit_off:.1f}%)")
    best_lift = max(h["lift_pp"] for h in hitrates.values())
    print(f"   → best conditional lift over base rate: {best_lift:+.1f}pp "
          f"({'signal present' if best_lift > 3.0 else 'NO usable signal — gate is near-noise'})")

    # ── 1. P&L SWEEP ─────────────────────────────────────────────────────────────────────────
    results = []
    print("\n" + "-" * 78)
    print("1. SLEEVE P&L (OFF = flat cash 0%)  ·  RWA floor reference = "
          f"{RWA_FLOOR_APY:.2f}%/yr")
    print(f"   {'gate':8s} {'rt_bps':>7s} {'APY%':>8s} {'maxDD%':>8s} {'vol%':>7s} {'Sharpe':>8s} "
          f"{'duty%':>7s} {'switch':>7s} {'OOS APY%':>9s}")
    for mode in GATES:
        for bps in (0.0, 5.0, 10.0, 25.0, 50.0, 100.0):
            rets, st = simulate(dates, funding, mode, bps)
            m = metrics(dates, rets)
            m_oos = metrics(dates[oos_i:], rets[oos_i:])
            results.append({"gate": mode, "round_trip_bps": bps, **m, **st,
                            "oos_apy_pct": m_oos["apy_pct"], "oos_calmar": m_oos["calmar"]})
            print(f"   {mode:8s} {bps:7.0f} {m['apy_pct']:8.3f} {m['maxDD_pct']:8.3f} "
                  f"{m['vol_pct']:7.2f} {m['sharpe']:8.2f} {st['duty_pct']:7.1f} "
                  f"{st['switches']:7d} {m_oos['apy_pct']:9.3f}")

    # ── 2. BREAK-EVEN ────────────────────────────────────────────────────────────────────────
    print("\n" + "-" * 78)
    print("2. BREAK-EVEN COST BUDGET")
    always0 = next(r for r in results if r["gate"] == "always" and r["round_trip_bps"] == 0.0)
    print(f"   ungated carry at zero cost: APY {always0['apy_pct']:.3f}%/yr  "
          f"(vs RWA floor {RWA_FLOOR_APY:.2f}% → "
          f"{'clears' if always0['apy_pct'] > RWA_FLOOR_APY else 'DOES NOT clear'})")
    for mode in ("sign7", "sign30", "thin5"):
        beats = [r for r in results if r["gate"] == mode
                 and r["apy_pct"] > next(x["apy_pct"] for x in results
                                         if x["gate"] == "always"
                                         and x["round_trip_bps"] == r["round_trip_bps"])]
        max_bps = max((r["round_trip_bps"] for r in beats), default=None)
        floor_ok = [r for r in results if r["gate"] == mode and r["apy_pct"] > RWA_FLOOR_APY]
        floor_bps = max((r["round_trip_bps"] for r in floor_ok), default=None)
        print(f"   gate {mode:7s}: beats ungated on APY up to round-trip "
              f"{('%.0f bps' % max_bps) if max_bps is not None else 'NEVER (loses at 0 bps)'}"
              f"  ·  clears RWA floor up to "
              f"{('%.0f bps' % floor_bps) if floor_bps is not None else 'NEVER'}")

    # fine scan: the gate's real budget is risk-adjusted, so find where Sharpe crosses
    print("   fine scan — cost budget of the gate measured on Sharpe (0.1 bps steps):")
    always_sharpe = {}
    for bps10 in range(0, 201):
        bps = bps10 / 10.0
        r, _ = simulate(dates, funding, "always", bps)
        always_sharpe[bps] = metrics(dates, r)["sharpe"]
    breakeven = {}
    for mode in ("sign7", "sign30", "thin5"):
        last_ok = None
        for bps10 in range(0, 201):
            bps = bps10 / 10.0
            r, _ = simulate(dates, funding, mode, bps)
            if metrics(dates, r)["sharpe"] > always_sharpe[bps]:
                last_ok = bps
            else:
                break
        breakeven[mode] = last_ok
        print(f"     {mode:7s}: gate beats ungated on Sharpe up to "
              f"{('%.1f bps round-trip' % last_ok) if last_ok is not None else 'NEVER (loses at 0 bps)'}")

    # ── VERDICT ──────────────────────────────────────────────────────────────────────────────
    print("\n" + "=" * 78)
    print("VERDICT (bt = backtest on REAL funding series, L1-real-feed, advisory only):")
    ranked = sorted([r for r in results if r["round_trip_bps"] == 10.0],
                    key=lambda r: r["apy_pct"], reverse=True)
    print("   at a realistic 10 bps round-trip:")
    for r in ranked:
        print(f"     {r['gate']:8s} APY {r['apy_pct']:6.3f}%  maxDD {r['maxDD_pct']:5.3f}%  "
              f"Sharpe {r['sharpe']:6.2f}  duty {r['duty_pct']:5.1f}%  OOS APY {r['oos_apy_pct']:6.3f}%")
    top = ranked[0]
    print(f"   best gate: {top['gate']} — "
          f"{'gating ADDS value' if top['gate'] != 'always' else 'GATING ADDS NOTHING: ungated carry wins'}")

    print("\nHONEST CAVEATS (mandatory):")
    print("  (a) BASIS RISK NOT MODELLED: perp is assumed to track spot exactly. Real cash-and-carry")
    print("      P&L includes perp/spot basis moves and, at leverage, liquidation risk — the single")
    print("      largest omission here. These numbers are a CEILING for the sleeve, not a forecast.")
    print("  (b) One venue's 8h funding series, taken at face value; no venue haircut, no fill risk,")
    print("      no size impact — a real book of size receives less than the quoted rate.")
    print("  (c) Costs are a flat round-trip bps on switches only; borrow/margin and spot slippage")
    print("      on entry are folded into that number rather than modelled separately.")
    print("  (d) Gate decisions are strictly causal (past funding only) — no look-ahead.")
    print("  (e) OOS split is the same 2025-06-01 used by #11/#15/#19/#20; the OOS half contains")
    print("      no severe funding dislocation, so it does NOT validate crisis behaviour.")
    print("  (f) Evidence level L1 (real feed, backtest). NEVER present as realized capital returns.")
    print("  (g) Advisory / paper-only: no live track, no RiskPolicy, no execution path touched.")
    print("=" * 78)

    if args.json:
        print("\nJSON_RESULT " + json.dumps(
            {"days": len(dates), "first": dates[0], "last": dates[-1], "oos_split": OOS_SPLIT,
             "base_rate_pct": base_rate, "hitrates": hitrates, "results": results},
            sort_keys=True))


if __name__ == "__main__":
    main()
