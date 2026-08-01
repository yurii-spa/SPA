#!/usr/bin/env python3
"""
scripts/edge_real_cascade_hedge.py — Idea #21: Real-Cost Funding-Conditional Cascade Hedge (RC-CACH)

NOVEL EDGE IDEA #21 (docs/DYNAMIC_LEVERAGE_GUARDIAN.md registry)

WHAT THIS TESTS (and why it is NOT a repeat of #20)
  Idea #20 (CACH) established a STRUCTURAL claim on the SYNTHETIC stress fixture:
  "a permanent short in a crisis-correlated asset has positive NPV" — Calmar up to 11.53 (bt).
  Its own honest caveats named the two things that were never tested:
    (б) real hedge cost is NOT the fixture's (variant_APY − rates_APY) — it is perp funding
        + borrow + slippage, and it is TIME-VARYING;
    (а) fixture crisis correlations are matched BY CONSTRUCTION — real co-movement may not exist.

  #21 tests exactly those two on REAL data:
    1. PREMISE TEST — on the real 10-book aggressive_lab panel + real ETH prices
       (data/rates_desk/prices_deep.json), does the core carry portfolio actually CO-MOVE
       with ETH on its worst days?  A hedge can only pay if the co-movement is real.
    2. REAL-COST TEST — price the short leg with the REAL ETH perp funding series
       (data/rates_desk/funding_deep.json, 8h rate, 2024-06-01..2026-06-25).  Crucially,
       a SHORT perp RECEIVES funding when funding > 0 — the fixture modelled the hedge as a
       pure cost; in reality it has been a positive-carry position ~84% of days.
    3. NEW MECHANISM — FUNDING-CONDITIONAL SIZING: size the hedge from the causal, exogenous,
       slow-moving funding signal that the live agent com.spa.funding_regime already computes
       (trailing 7d median funding, lag-1 → no look-ahead).  Hedge ON when being short is PAID,
       OFF when short must PAY.  This is a sizing rule no prior registry idea used: #1/#9/#14
       size on the book's OWN volatility/drawdown, #4 on inverse vol, #15 on Kelly, #20 is a
       CONSTANT hedge.  #21 sizes a hedge on an EXOGENOUS CASH-FLOW price.

PORTFOLIOS
  CORE-A (registry-analogue, comparable to #3/#20 baseline, real sUSDe leg):
      25% susde_dn (REAL book series) + 50% rates-carry (constant 4.6%/yr proxy)
      + 25% RWA floor (constant 3.31%/yr)
  CORE-B (all-real robustness): 1/3 susde_dn + 1/3 susde_spot + 1/3 points_farm (all REAL books)

  HEDGE LEG (short ETH perp, weight h of NAV):
      daily P&L = h × ( −r_eth_spot + 3 × funding_8h ) − rebalance_cost
      funding sign convention: funding > 0 → longs pay shorts → SHORT RECEIVES.
      rebalance cost = fee_bps × |Δ notional| (daily re-set to constant weight h).

  SIZING VARIANTS
      static   : h_t = h                                  (#20 analogue on real data)
      gated    : h_t = h if med7(funding, ≤ t−1) > 0 else 0
      thin     : h_t = h if carry_ann(med7, ≤ t−1) > 5%/yr else 0   (live agent's THIN_CARRY threshold)

  OOS split 2025-06-01 (same as #11/#15/#19/#20).

stdlib-only, deterministic, read-only, LLM FORBIDDEN.
Advisory / paper-only: touches no live track, no RiskPolicy, no execution path.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import datetime
import json
import statistics
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PRICES = REPO / "data" / "rates_desk" / "prices_deep.json"
FUNDING = REPO / "data" / "rates_desk" / "funding_deep.json"
BOOKS_DIR = REPO / "data" / "aggressive_lab"

OOS_SPLIT = "2025-06-01"
RWA_FLOOR_APY = 0.0331          # registry constant (real RWA floor ~3.31%/yr)
RATES_CARRY_APY = 0.046         # registry constant rates-carry proxy (#3/#20 baseline)
THIN_CARRY_ANN = 0.05           # live funding_regime agent threshold (5%/yr)
FUNDING_PERIODS_PER_DAY = 3     # 8h funding
DAY = 1.0 / 365.0


# ── loaders ──────────────────────────────────────────────────────────────────────────────────────
def load_prices(asset: str = "eth") -> dict:
    return {d: float(v) for d, v in json.loads(PRICES.read_text())["series"][asset].items()}


def load_funding() -> dict:
    return {d: float(v) for d, v in json.loads(FUNDING.read_text())["series"].items()}


def load_book_equity(name: str) -> dict:
    path = BOOKS_DIR / name / "realized_series.jsonl"
    eq = {}
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        eq[row["date"]] = float(row["equity_usd"])
    return eq


def _d(date_str: str) -> datetime.date:
    return datetime.date.fromisoformat(date_str)


def step_returns(levels: dict, grid: list) -> list:
    """Return per-STEP returns over the aligned grid (gap days are compounded, never dropped)."""
    out = []
    for i in range(1, len(grid)):
        prev, cur = levels[grid[i - 1]], levels[grid[i]]
        out.append(cur / prev - 1.0 if prev > 0 else 0.0)
    return out


def step_days(grid: list) -> list:
    return [(_d(grid[i]) - _d(grid[i - 1])).days for i in range(1, len(grid))]


def step_funding(funding: dict, grid: list) -> list:
    """Funding accrued to a SHORT over each step: sum of 3×f_8h across the step's calendar days."""
    out = []
    for i in range(1, len(grid)):
        start, end = _d(grid[i - 1]), _d(grid[i])
        total, day = 0.0, start + datetime.timedelta(days=1)
        while day <= end:
            key = day.isoformat()
            if key in funding:
                total += FUNDING_PERIODS_PER_DAY * funding[key]
            day += datetime.timedelta(days=1)
        out.append(total)
    return out


# ── metrics ──────────────────────────────────────────────────────────────────────────────────────
def metrics(grid, rets) -> dict:
    """grid has len(rets)+1 dates; annualisation uses CALENDAR days, not step count."""
    if not rets:
        return {"apy_pct": 0.0, "maxDD_pct": 0.0, "calmar": 0.0, "days": 0}
    equity, peak, maxdd = 1.0, 1.0, 0.0
    for r in rets:
        equity *= 1.0 + r
        peak = max(peak, equity)
        if peak > 0:
            maxdd = max(maxdd, (peak - equity) / peak)
    cal_days = max(1, (_d(grid[-1]) - _d(grid[0])).days)
    apy = equity ** (365.0 / cal_days) - 1.0
    calmar = apy / maxdd if maxdd > 1e-9 else float("inf")
    return {
        "apy_pct": apy * 100.0,
        "maxDD_pct": maxdd * 100.0,
        "calmar": calmar,
        "days": cal_days,
        "steps": len(rets),
        "first": grid[0],
        "last": grid[-1],
    }


def med(seq):
    return statistics.median(seq) if seq else 0.0


# ── core portfolios (real books + registry constant legs) ────────────────────────────────────────
def core_returns(kind: str, book_steps: dict, dts: list) -> list:
    if kind == "A":
        s = book_steps["susde_dn"]
        return [0.25 * s[i] + 0.50 * (RATES_CARRY_APY * dt * DAY) + 0.25 * (RWA_FLOOR_APY * dt * DAY)
                for i, dt in enumerate(dts)]
    if kind == "B":
        legs = ("susde_dn", "susde_spot", "points_farm")
        return [sum(book_steps[b][i] for b in legs) / len(legs) for i in range(len(dts))]
    raise ValueError(kind)


# ── hedge overlay ────────────────────────────────────────────────────────────────────────────────
def hedge_weights(mode: str, grid: list, funding: dict, h: float, lookback: int = 7) -> list:
    """Causal hedge weight per STEP: signal = funding over the `lookback` calendar days ending at
    the PREVIOUS grid date (strictly past → no look-ahead)."""
    weights = []
    for i in range(1, len(grid)):
        if mode == "static":
            weights.append(h)
            continue
        end = _d(grid[i - 1])
        window = []
        for k in range(lookback):
            key = (end - datetime.timedelta(days=k)).isoformat()
            if key in funding:
                window.append(funding[key])
        if len(window) < 3:
            weights.append(0.0)                       # fail-closed: no signal → no hedge
            continue
        m7 = med(window)
        if mode == "gated":
            weights.append(h if m7 > 0 else 0.0)
        elif mode == "thin":
            carry_ann = m7 * FUNDING_PERIODS_PER_DAY * 365.0
            weights.append(h if carry_ann > THIN_CARRY_ANN else 0.0)
        else:
            raise ValueError(mode)
    return weights


def run_overlay(grid, core_rets, eth_steps, fund_steps, h, mode, funding, fee_bps=5.0):
    """Return (portfolio step returns, decomposition dict)."""
    weights = hedge_weights(mode, grid, funding, h)
    out, prev_w = [], 0.0
    fund_income = price_pnl = cost_total = 0.0
    on_steps = 0
    for i in range(len(core_rets)):
        w = weights[i]
        hedge_price = -w * eth_steps[i]
        hedge_fund = w * fund_steps[i]
        turnover = abs(w - prev_w) + w * abs(eth_steps[i])   # re-set to constant weight each step
        cost = (fee_bps / 10000.0) * turnover
        out.append(core_rets[i] + hedge_price + hedge_fund - cost)
        price_pnl += hedge_price
        fund_income += hedge_fund
        cost_total += cost
        on_steps += 1 if w > 0 else 0
        prev_w = w
    return out, {
        "hedge_on_steps": on_steps,
        "hedge_duty_pct": 100.0 * on_steps / max(1, len(core_rets)),
        "hedge_funding_income_pct": fund_income * 100.0,
        "hedge_price_pnl_pct": price_pnl * 100.0,
        "hedge_cost_pct": cost_total * 100.0,
    }


# ── premise diagnostics ──────────────────────────────────────────────────────────────────────────
# Relative standard deviation below which the worst decile counts as FLAT — i.e. it carries no
# variance to regress on, only floating-point rounding.  Double precision puts rounding noise at
# ~1e-16 of the data scale; genuine day-to-day dispersion inside a decile of real returns is
# >= ~1e-4 of it.  1e-9 sits ~7 orders above the noise and ~5 below any real signal.
_DEGENERATE_REL_STD = 1e-9


def ols_beta(xs, ys):
    """Beta of ys on xs, refusing (0.0) when xs carries no dispersion.  Returns (beta, mean_y).

    A FLAT sample (every x the same value) has TRUE variance zero and no beta.  A bare
    ``var > 0`` cannot see that: ``sum(xs) / m`` is not bit-exact, so ``var`` comes out as the
    SQUARE of the mean's rounding error (~1e-34) and ``cov / var`` is one rounding divided by
    another — pure noise, and noise of a size that looks like a real answer.  Measured on this
    code before the guard: a completely flat book (x = -0.23 on every day of the sample,
    y = 0.23) returned beta = -1.000, and the hermetic test in CI returned 2**-7 = 0.0078125 on
    Linux/py3.11 while macOS/py3.12+ returned 0.0 (CPython 3.12 made ``sum()`` compensated, so
    the same input rounds differently per interpreter).  Compare against the SCALE of the data
    instead and fail CLOSED to 0.0, like the short-series branch of ``downside_beta``.
    """
    m = len(xs)
    if m == 0:
        return 0.0, 0.0
    mx, my = sum(xs) / m, sum(ys) / m
    cov = sum((a - mx) * (b - my) for a, b in zip(xs, ys)) / m
    var = sum((a - mx) ** 2 for a in xs) / m
    scale = max(abs(a) for a in xs)
    if var <= (_DEGENERATE_REL_STD * scale) ** 2:
        return 0.0, my
    return cov / var, my


def downside_beta(x, y):
    """Beta of y on x restricted to the worst-decile x days (crisis co-movement)."""
    n = len(x)
    if n < 20:
        return 0.0, 0.0
    thr = sorted(x)[max(0, int(0.10 * n) - 1)]
    xs = [a for a in x if a <= thr]
    ys = [b for a, b in zip(x, y) if a <= thr]
    return ols_beta(xs, ys)


# How many standard errors below chance the conditional mean must sit before the REVERSE premise
# check is allowed to call co-movement real.  2.0 ≈ 2.3% one-sided under normality — the usual bar,
# and far stricter than the bare threshold it replaces (see `conditional_mean_z`).
_SELECTION_Z = 2.0
# Economic bar kept from the original check: even a statistically real concentration of ETH losses
# is not worth hedging if it is tiny.  BOTH bars must clear.
_HEDGE_PAYS_THRESHOLD = -0.005


def conditional_mean_z(values, selected):
    """Is the mean of ``values`` over ``selected`` days distinguishable from a RANDOM pick?

    Returns ``(observed_mean, unconditional_mean, z, measured)``.  ``measured`` is False when the
    question cannot be answered at all (empty/degenerate input) — the caller must then refuse,
    never fall back to a number.

    **Why this exists.** The reverse premise check ("when the CORE has its worst days, is ETH
    falling too?") ranks days by the core's own return and averages ETH over the worst decile.
    That is only a measurement if ranking by the core actually selects distinctive days.  For a
    delta-neutral carry book it does not: measured on the real panel 2024-06-01..2026-06-24,
    CORE-A's daily dispersion is 0.0076%/d against ETH's 3.92%/d — a factor of ~500 — so the
    "worst decile" is ranked by what is effectively noise, and the ETH days it collects are close
    to a random 42-of-427 draw.

    The old test compared the resulting average against a flat -0.5%/d and printed
    "hedge CAN pay" / "CANNOT pay".  Two things are wrong with that, both measured:
      1. the null is not zero — ETH DRIFTED -0.231%/d over this window, so any random subset
         averages -0.231%/d before any co-movement exists;
      2. the spread of a 42-day average is huge (se ~0.60%/d), so a random draw clears the
         -0.5%/d bar **32.1% of the time** (200k-draw permutation check, seed 20260801).
    A verdict that fires on a third of random inputs is not a measurement.  Between the registry
    run (2026-07-29) and 2026-08-01 that coin landed the other way — -0.077%/d became -0.810%/d
    and the printed verdict flipped from "CANNOT pay" to "CAN pay" — with no change in the
    aligned grid (591 points both times).  Card `agent-idea21-verdict-data-drift`.

    So compare against the right null instead: under a random draw of k days out of n WITHOUT
    replacement the sample mean has mean = the unconditional mean and standard error
    ``sd/sqrt(k) * sqrt((n-k)/(n-1))`` (finite-population correction).  The z that falls out is
    exact, deterministic and needs no RNG — it reproduces the 200k-draw permutation percentile to
    a tenth of a point (CORE-A: z = -1.01 ⇒ 15.7th percentile; permutation gave 15.7%).

    Note this refuses in the SAME direction as the rest of the file: `ols_beta` fails closed on a
    flat regressor, `downside_beta` on a short series, and this on a selection that carries no
    information.  A near-zero z is not "no co-movement" — it is "this input cannot tell".
    """
    n = len(values)
    k = len(selected)
    if n < 2 or k == 0 or k >= n:
        return 0.0, 0.0, 0.0, False
    uncond = sum(values) / n
    obs = sum(values[i] for i in selected) / k
    var = sum((v - uncond) ** 2 for v in values) / n
    # A perfectly flat series (points_farm is exactly this on the real panel) has no sampling
    # spread, so no z exists.  Refuse rather than divide by zero.
    scale = max(abs(v) for v in values) or 1.0
    if var <= (_DEGENERATE_REL_STD * scale) ** 2:
        return obs, uncond, 0.0, False
    se = (var / k) ** 0.5 * (((n - k) / (n - 1)) ** 0.5)
    return obs, uncond, (obs - uncond) / se, True


def hedge_can_pay(values, selected):
    """(verdict, detail) for the reverse premise check — three-valued, fail-CLOSED.

    ``verdict`` is True / False / None, where **None means NOT MEASURED** and must never be
    rendered as "no co-movement": the two are different claims and conflating them is exactly the
    fail-OPEN class this repo keeps finding (a plausible number published about a check that never
    ran).  True requires BOTH bars: statistically below chance (z <= -2) AND economically material
    (< -0.5%/d).
    """
    obs, uncond, z, measured = conditional_mean_z(values, selected)
    if not measured:
        return None, {"observed_pct": obs * 100.0, "unconditional_pct": uncond * 100.0,
                      "z": None, "reason": "selection carries no dispersion — no z exists"}
    detail = {"observed_pct": obs * 100.0, "unconditional_pct": uncond * 100.0, "z": z,
              "reason": ""}
    if z > -_SELECTION_Z:
        detail["reason"] = (f"indistinguishable from a random draw of the same size "
                            f"(z={z:+.2f}, needs <= {-_SELECTION_Z:.1f})")
        return None, detail
    if obs >= _HEDGE_PAYS_THRESHOLD:
        detail["reason"] = (f"concentration is real (z={z:+.2f}) but immaterial "
                            f"({obs*100:+.3f}%/d vs bar {_HEDGE_PAYS_THRESHOLD*100:+.3f}%/d)")
        return False, detail
    detail["reason"] = f"ETH losses concentrate on the core's worst days (z={z:+.2f})"
    return True, detail


def series_fingerprint(mapping):
    """sha256 over a date→value series, so two runs can be compared EXACTLY.

    **Why a hash and not just the date bounds.** Card `agent-idea21-verdict-data-drift` assumed the
    books had simply grown longer.  They had not — the aligned grid was identical (591 points,
    2024-06-01..2026-06-24) while the numbers moved anyway.  Diffing the live books against the
    2026-07-25 full-repo backup showed why: `susde_dn`'s realized series is REGENERATED, not
    appended — all 853 historical rows changed, by up to -9.70% (2026-07-05: 163150.97 → 147322.68),
    and `lrt_neutral`'s 761 of 853 (up to -1.34%); the other four books were byte-identical.
    Bounds and row counts are blind to that; a content hash is not.  Printing it makes every run
    of this script comparable to every other one, which is the reproducibility criterion the card
    asked for.
    """
    import hashlib
    h = hashlib.sha256()
    for d in sorted(mapping):
        h.update(f"{d}={mapping[d]!r}\n".encode())
    return h.hexdigest()[:16]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fee-bps", type=float, default=5.0, help="per-unit-turnover cost, bps")
    ap.add_argument("--json", action="store_true", help="emit machine-readable JSON block")
    args = ap.parse_args()

    prices = load_prices("eth")
    funding = load_funding()
    book_names = ("susde_dn", "susde_spot", "points_farm", "eth_directional",
                  "lrt_neutral", "pendle_pt_levered")
    books = {n: load_book_equity(n) for n in book_names}

    grid = sorted(set(prices) & set(funding) & set.intersection(*[set(b) for b in books.values()]))
    dts = step_days(grid)
    eth_steps = step_returns(prices, grid)
    fund_steps = step_funding(funding, grid)
    book_steps = {n: step_returns(books[n], grid) for n in book_names}

    oos_start = next(i for i, d in enumerate(grid) if d >= OOS_SPLIT)
    oos_grid = grid[oos_start:]

    print("=" * 78)
    print("Idea #21 — Real-Cost Funding-Conditional Cascade Hedge (RC-CACH)")
    print("REAL data only: ETH spot (prices_deep) + ETH perp funding (funding_deep) + real books")
    print(f"aligned grid: {len(grid)} points / {len(dts)} steps  {grid[0]}..{grid[-1]}  "
          f"(calendar {(_d(grid[-1])-_d(grid[0])).days}d, gaps compounded)   "
          f"OOS(≥{OOS_SPLIT}): {len(oos_grid)-1} steps")
    fv = [funding[d] for d in sorted(funding) if grid[0] <= d <= grid[-1]]
    print(f"funding 8h: median {med(fv):.6f}  → carry {med(fv)*3*365*100:.2f}%/yr  "
          f"negative-days {100.0*sum(1 for v in fv if v < 0)/len(fv):.1f}%")
    daily = [(eth_steps[i], dts[i]) for i in range(len(dts)) if dts[i] == 1]
    print(f"ETH ann vol (1-day steps only, n={len(daily)}): "
          f"{statistics.pstdev([r for r, _ in daily])*(365**0.5)*100:.1f}%")

    # ── PROVENANCE — makes this run comparable to any other one (see series_fingerprint) ───────
    provenance = {"eth_prices": {"sha": series_fingerprint(prices), "rows": len(prices),
                                 "first": min(prices), "last": max(prices)},
                  "eth_funding": {"sha": series_fingerprint(funding), "rows": len(funding),
                                  "first": min(funding), "last": max(funding)}}
    for n_ in book_names:
        provenance[n_] = {"sha": series_fingerprint(books[n_]), "rows": len(books[n_]),
                          "first": min(books[n_]), "last": max(books[n_])}
    print("\ninput series (sha256[:16] of date=value — a rerun that prints different shas is")
    print("NOT comparable to this one, even when the aligned grid is identical):")
    for n_, p in provenance.items():
        print(f"   {n_:22s} {p['sha']}  rows {p['rows']:4d}  {p['first']}..{p['last']}")

    # ── 1. PREMISE TEST (1-day steps only — clean co-movement measurement) ────────────────────
    idx1 = [i for i in range(len(dts)) if dts[i] == 1]
    eth1 = [eth_steps[i] for i in idx1]
    print("\n" + "-" * 78)
    print("1. PREMISE TEST — does the REAL core co-move with ETH when it matters?")
    print("   (a hedge can only pay if the core loses WHEN ETH loses; 1-day steps only)")
    print(f"   {'book/core':22s} {'β(all)':>8s} {'β(ETH worst 10%)':>18s} {'mean ret on those days':>24s}")
    for name in ("susde_dn", "susde_spot", "points_farm", "lrt_neutral",
                 "pendle_pt_levered", "eth_directional"):
        y = [book_steps[name][i] for i in idx1]
        # same degeneracy guard as the decile beta — a flat x sample has no beta (see ols_beta)
        beta, _ = ols_beta(eth1, y)
        dbeta, dmean = downside_beta(eth1, y)
        print(f"   {name:22s} {beta:+8.3f} {dbeta:+18.3f} {dmean*100:+23.3f}%/d")

    premise = {}
    for kind in ("A", "B"):
        core_all = core_returns(kind, book_steps, dts)
        core1 = [core_all[i] for i in idx1]
        dbeta, dmean = downside_beta(eth1, core1)
        print(f"   {'CORE-'+kind:22s} {'':8s} {dbeta:+18.3f} {dmean*100:+23.3f}%/d")
        worst = sorted(range(len(core1)), key=lambda i: core1[i])[:max(1, int(0.10 * len(core1)))]
        can_pay, det = hedge_can_pay(eth1, worst)
        eth_on_core_worst = det["observed_pct"] / 100.0
        premise[kind] = {"down_beta": dbeta, "core_mean_on_eth_worst_pct": dmean * 100.0,
                         "eth_on_core_worst_pct": det["observed_pct"],
                         "eth_unconditional_pct": det["unconditional_pct"],
                         "selection_z": det["z"], "hedge_can_pay": can_pay,
                         "core_daily_sd_pct": statistics.pstdev(core1) * 100.0}
        label = ({True: "hedge CAN pay", False: "hedge CANNOT pay"}[can_pay]
                 if can_pay is not None else "NOT MEASURED")
        print(f"   {'  ↳ ETH on CORE-'+kind+' worst 10% days':38s} {eth_on_core_worst*100:+.3f}%/d "
              f"({label} — {det['reason']})")
        print(f"   {'     vs ETH unconditional':38s} {det['unconditional_pct']:+.3f}%/d   "
              f"core daily sd {statistics.pstdev(core1)*100:.4f}%/d vs ETH "
              f"{statistics.pstdev(eth1)*100:.4f}%/d")

    # ── 2/3. REAL-COST + FUNDING-CONDITIONAL SIZING ───────────────────────────────────────────
    results = []
    for kind in ("A", "B"):
        core = core_returns(kind, book_steps, dts)
        base = metrics(grid, core)
        results.append({"core": kind, "mode": "no-hedge", "h_pct": 0.0, **base,
                        "oos": metrics(oos_grid, core[oos_start:])})
        print("\n" + "-" * 78)
        print(f"2. REAL-COST HEDGE SWEEP — CORE-{kind}  "
              f"(baseline APY {base['apy_pct']:.3f}% / maxDD {base['maxDD_pct']:.3f}% / "
              f"Calmar {base['calmar']:.2f})")
        print(f"   {'mode':8s} {'h%':>5s} {'APY%':>8s} {'maxDD%':>8s} {'Calmar':>8s} {'OOS Calmar':>11s} "
              f"{'duty%':>7s} {'fund+':>7s} {'price':>8s} {'cost':>6s}")
        for mode in ("static", "gated", "thin"):
            for h in (0.02, 0.05, 0.10, 0.15):
                rets, dec = run_overlay(grid, core, eth_steps, fund_steps, h, mode,
                                        funding, args.fee_bps)
                m = metrics(grid, rets)
                m_oos = metrics(oos_grid, rets[oos_start:])
                results.append({"core": kind, "mode": mode, "h_pct": h * 100.0,
                                **m, "oos": m_oos, **dec})
                print(f"   {mode:8s} {h*100:5.0f} {m['apy_pct']:8.3f} {m['maxDD_pct']:8.3f} "
                      f"{m['calmar']:8.2f} {m_oos['calmar']:11.2f} {dec['hedge_duty_pct']:7.1f} "
                      f"{dec['hedge_funding_income_pct']:+7.2f} {dec['hedge_price_pnl_pct']:+8.2f} "
                      f"{dec['hedge_cost_pct']:6.2f}")

    # ── verdict ───────────────────────────────────────────────────────────────────────────────
    print("\n" + "=" * 78)
    print("VERDICT (bt = backtest on REAL series, L1-real-feed, advisory only):")
    for kind in ("A", "B"):
        base = next(r for r in results if r["core"] == kind and r["mode"] == "no-hedge")
        hedged = [r for r in results if r["core"] == kind and r["mode"] != "no-hedge"]
        best = max(hedged, key=lambda r: r["calmar"])
        better = best["calmar"] > base["calmar"]
        print(f"  CORE-{kind}: baseline Calmar {base['calmar']:.2f} (APY {base['apy_pct']:.2f}% / "
              f"DD {base['maxDD_pct']:.2f}%) → best hedge {best['mode']} h={best['h_pct']:.0f}%: "
              f"Calmar {best['calmar']:.2f} (APY {best['apy_pct']:.2f}% / DD {best['maxDD_pct']:.2f}%)")
        print(f"           {'IMPROVES' if better else 'DOES NOT IMPROVE'} on the real panel; "
              f"maxDD {'↓' if best['maxDD_pct'] < base['maxDD_pct'] else '↑'} "
              f"({base['maxDD_pct']:.2f}% → {best['maxDD_pct']:.2f}%)")
        gated = [r for r in hedged if r["mode"] == "gated"]
        static = [r for r in hedged if r["mode"] == "static"]
        bg, bs = max(gated, key=lambda r: r["calmar"]), max(static, key=lambda r: r["calmar"])
        print(f"           funding-conditional sizing vs constant hedge: "
              f"Calmar {bg['calmar']:.2f} (gated) vs {bs['calmar']:.2f} (static) → "
              f"{'gating HELPS' if bg['calmar'] > bs['calmar'] else 'gating does NOT rescue the hedge'}")

    print("\nHONEST CAVEATS (mandatory):")
    print("  (a) Perp price is proxied by ETH SPOT: basis moves, perp/spot dislocation and")
    print("      liquidation mechanics are NOT modelled → real short P&L is noisier than shown.")
    print("  (b) Funding series = one venue's 8h rate; short-side funding receipt assumes fills")
    print("      at that rate with no venue/counterparty haircut.")
    print("  (c) Costs modelled as fee_bps on daily re-set turnover; real slippage in a crisis")
    print("      (exactly when the hedge must be resized) is higher and path-dependent.")
    print("  (d) Real book series are REAL-feed reconstructions of advisory paper books, not")
    print("      realized capital returns — evidence level L1, never a live-return claim.")
    print("  (e) Sizing signal is causal (lag-1, strictly past funding) — no look-ahead used.")
    print("  (f) Advisory / paper-only: no live track, no RiskPolicy, no execution path touched.")
    print("=" * 78)

    if args.json:
        print("\nJSON_RESULT " + json.dumps(
            {"grid_points": len(grid), "first": grid[0], "last": grid[-1],
             "oos_split": OOS_SPLIT, "premise": premise, "results": results,
             "provenance": provenance}, sort_keys=True))


if __name__ == "__main__":
    main()
