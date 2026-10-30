#!/usr/bin/env python3
"""
scripts/edge_measurable_population.py — registry ideas #148 (MPC) and #149 (LBS)

IS_ADVISORY = True
OUTSIDE_RISKPOLICY = True

#148 MPC — Measurable-Population Census.  EXECUTES THE ORDER LEFT VERBATIM BY #145:

    "Name the registry's MEASURABLE POPULATION with an honest number: for each of the 10 books
     print its TEST drawdown and the answer 'is it above the 96 bp toll' — acceptance: the
     number of books whose Calmar denominator is NOT degenerate on TEST is printed, and if that
     number is <= 2, then every conclusion of the series #119...#145 is obliged to carry the
     line 'measured on a population of N books' instead of leaving it unsaid.  Second: check
     whether a window exists on `data/rates_desk/` or in the forward series `data/swarm/` where
     the measurable drawdown comes from a book that is NOT directional — if not, that is a
     limit of the panel, not a limit of the sizers."

  This section invents no rule.  It is a CENSUS, and a census is allowed to look at TEST: it
  does not decide anything, it states what the population of the measurement IS.  Every entry
  from #119 onward divides an annualised return by a realized drawdown; where that drawdown is
  below the round-trip toll the quotient is not a risk-adjusted number at all (#129), so the
  honest denominator of the whole negative series is "how many books could even produce one".

  WHY THE SECOND HALF NEEDS A SEPARATE INSTRUMENT.  #145 measured that excising
  `eth_directional` collapses the PORTFOLIO drawdown to 0.38-1.01 % and concluded "remove the
  only source of measurable risk and no risk manager can show a benefit".  That is a statement
  about equal weighting, not about the books: an equally weighted panel with four frozen books
  dilutes a loser by 10x before anyone measures it.  §1 therefore asks the question one level
  down, per BOOK, where dilution cannot hide the answer; §2 asks it of the REAL forward series,
  where the accounting is the live paper book rather than a backtest.

#149 LBS — Loss-Budget Sizing.  A NEW mechanism (the registry has ZERO occurrences of
  "риск-бюджет" / "risk budget" / "inverse-maxDD" / "1/maxDD").

  Every risk-weighted sizer in the registry divides by a DISPERSION measure: inverse sigma
  (#128 SFS, #131 ASE, #144 GLM), inverse worst single day (#108/#109), an upper bound on the
  tail (#141 TUB).  None divides by the realized DRAWDOWN itself.  The distinction is not
  cosmetic: sigma is two-sided and set by the typical day, while drawdown is one-sided and
  path-dependent — and drawdown is the quantity the kill-switch actually reads (SOFT -5 % /
  HARD -10 %, `spa_core/governance/kill_switch.py`).  A sizer judged by a stop it is not
  sized against is being judged by someone else's ruler.

  RULE.  Declare a portfolio loss budget B (= the SOFT_DERISK rung, READ from the canon and
  never changed).  Give every book an EQUAL share of that budget in dollars, so the weight of
  a book is inversely proportional to its own TRAIN drawdown: w_b ~ 1 / maxDD_b(TRAIN).
  Two variants, both declared before the run:
    • LBS-norm   — weights normalised to 1 (fully invested; directly comparable to EW/INV-sigma)
    • LBS-budget — deployment scaled so the budgeted loss proxy sum(w_b * maxDD_b) <= B, the
                   remainder held in CASH at 0 %.  This is the variant in which "risk lower"
                   is literal rather than relative.

  THE THIRD OUTCOME IS IN THE DENOMINATOR, NOT IN A FOOTNOTE (inv. #17, lesson of #128).  A
  book whose TRAIN drawdown is below the toll has NOT been observed to lose; its drawdown is
  unmeasured, not zero.  Dividing by it would hand unbounded weight to the least observed
  book — exactly the leak #144 measured when raw inverse-sigma bought 70 % of the panel in two
  floor-sigma books.  So the denominator is max(maxDD, toll): the toll is a LOWER BOUND on
  what a book must be assumed to be able to lose, because the toll is what it costs to find out.

  THE TWO CONTROLS THAT DECIDE IT, both inherited from the registry's own lessons:
    • PLACEBO (#146) — 2000 deterministic permutations of the LBS weight VECTOR across books.
      A permutation preserves the concentration profile EXACTLY and destroys the link between a
      weight and the book that earned it.  If LBS sits inside that distribution, the result is
      the profile, not the mechanism, and that is the verdict rather than a caveat.
    • IDENTITY (#128/#131/#144) — Spearman rank correlation between the LBS weight vector and
      the inverse-sigma vectors.  A mechanism that ranks books the same way as an entry already
      in the registry is that entry under a new name, no matter how its TEST table reads.

Window / toll / split / cap conventions are INHERITED from `edge_real_panel_ensemble` so the
numbers stay comparable with #122...#147.  Nothing is written to disk; both sections only print.

stdlib-only, deterministic, read-only, LLM FORBIDDEN.
Advisory / paper-only: no capital moves, the go-live track (data/equity_curve_daily.json) is
never opened, RiskPolicy v1.0 is untouched, and the 20 %/name ceiling and the kill-switch rungs
are MEASURED, never changed.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import random
import statistics
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

IS_ADVISORY = True
OUTSIDE_RISKPOLICY = True

ROOT = Path(__file__).resolve().parent.parent
ENSEMBLE = ROOT / "scripts" / "edge_real_panel_ensemble.py"

#: the two OOS seams used by #143/#145/#146 — reused verbatim so the rows stay comparable.
SPLITS = ("2025-06-30", "2026-01-01")
#: placebo permutations for §3. Deterministic; the count and the seed are declared, not tuned.
PLACEBO_N = 2000
PLACEBO_SEED = 20261030
#: sigma floor of #128 SFS, annualised 1 %/yr expressed as a daily pstdev.
SIGMA_FLOOR_ANNUAL = 0.01

_MOD: Dict[str, object] = {}


class PopulationError(RuntimeError):
    """Fail-CLOSED: the census cannot be reported as clean."""


def _load(path: Path, name: str):
    if name in _MOD:
        return _MOD[name]
    if not path.exists():
        raise PopulationError(f"{name}: {path} missing — refusing to reimplement it")
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    _MOD[name] = mod
    return mod


def ens():
    return _load(ENSEMBLE, "_mpc_ensemble")


def toll() -> float:
    """The canonical round-trip toll. Read from the harness, never written down twice."""
    return float(ens().PLB_ROUNDTRIP)


def policy_cap() -> float:
    """The 20 %/name ceiling. OWNER-GATED: lives in RiskPolicy v1.0 and moves only by ADR."""
    return float(ens().POLICY_CAP)


def loss_budget() -> float:
    """Portfolio loss budget = the SOFT_DERISK rung, READ from the kill-switch canon.

    Read, never redefined: a second copy of this number in a research script is how a rung
    drifts away from the stop that enforces it.  Import failure is the third outcome, not a
    fallback constant (inv. #17) — a budget nobody could read is not 5 %.
    """
    sys.path.insert(0, str(ROOT))
    try:
        from spa_core.governance import kill_switch  # noqa: WPS433 (read-only, no LLM)
    except Exception as exc:  # pragma: no cover - measured by the refusal test
        raise PopulationError(
            f"kill_switch rungs unreadable ({exc}) — refusing to invent a loss budget"
        ) from exc
    return float(kill_switch.SOFT_DERISK_THRESHOLD_PCT) / 100.0


# ── §1 #148 MPC — per-book census ──────────────────────────────────────────────

def split_index(axis: Sequence[str], split: str) -> int:
    """Number of axis days at or before `split` — the TRAIN length."""
    hi = sum(1 for d in axis if d <= split)
    if hi < 60 or len(axis) - hi < 60:
        raise PopulationError(
            f"split {split} leaves TRAIN={hi}d / TEST={len(axis) - hi}d — "
            f"refusing to judge a half shorter than 60 days"
        )
    return hi


def book_measurability(panel_dir: Optional[Path] = None,
                       *, splits: Sequence[str] = SPLITS) -> Dict[str, object]:
    """Per book and per split: TEST drawdown, and whether it clears the toll.

    The returned `n_measurable` is the honest denominator of the negative series: the number of
    books that could produce a non-degenerate Calmar on TEST at all.  Books that never move on
    TEST are reported with `moves_test = 0` and a drawdown of 0.0 that is explicitly labelled
    `unmeasured`, never silently counted as "no risk" (inv. #17).
    """
    e = ens()
    pdir = Path(panel_dir) if panel_dir is not None else e.PANEL_DIR
    axis, rets, books = e.plb_load(pdir)
    t = toll()
    per_split: Dict[str, object] = {}
    for split in splits:
        hi = split_index(axis, split)
        rows: List[dict] = []
        for b in books:
            train, test = rets[b][:hi], rets[b][hi:]
            ptr, pte = e.perf(train), e.perf(test)
            moves_test = sum(1 for x in test if abs(x) > 1e-12)
            dd_test = abs(pte["maxdd"])
            rows.append({
                "book": b,
                "train_maxdd": abs(ptr["maxdd"]),
                "train_measurable": abs(ptr["maxdd"]) > t,
                "test_apy": pte["apy"],
                "test_maxdd": dd_test,
                "test_measurable": dd_test > t,
                "moves_test": moves_test,
                # a book that never moved has an UNMEASURED drawdown, not a zero one
                "unmeasured": "no movement on TEST" if moves_test == 0 else None,
            })
        meas = [r["book"] for r in rows if r["test_measurable"]]
        per_split[split] = {
            "train_days": hi,
            "test_days": len(axis) - hi,
            "rows": rows,
            "measurable": meas,
            "n_measurable": len(meas),
            "n_books": len(books),
            "frozen_on_test": [r["book"] for r in rows if r["moves_test"] == 0],
        }
    return {
        "axis_days": len(axis),
        "axis_first": axis[0],
        "axis_last": axis[-1],
        "books": books,
        "toll": t,
        "splits": dict(per_split),
    }


# ── §2 #148 MPC — is any REAL forward series measurable? ───────────────────────

def _equity_drawdown(eq: Sequence[float]) -> Tuple[float, int]:
    """(max drawdown as a positive fraction, number of down-days) of an equity path."""
    peak, mdd, down = eq[0], 0.0, 0
    for i, v in enumerate(eq):
        peak = max(peak, v)
        mdd = max(mdd, 1.0 - v / peak)
        if i and v < eq[i - 1]:
            down += 1
    return mdd, down


def forward_measurability(data_dir: Optional[Path] = None) -> Dict[str, object]:
    """Every REAL forward series we have, measured against the same toll as §1.

    Sources: the rates desk's own hash-chained equity track (`data/rates_desk/`) and the swarm
    blend plus each of its legs (`data/swarm/blend_forward.json`).  Neither is directional: the
    desk is fixed-rate carry and the blend legs are sUSDe / rates / RWA.  A source that cannot
    be read is reported as `unmeasured` with its reason and does NOT count as a clean zero —
    "we did not look" and "we looked and it was flat" are different answers (inv. #17).
    """
    root = Path(data_dir) if data_dir is not None else ROOT / "data"
    t = toll()
    out: List[dict] = []

    track = root / "rates_desk" / "equity_track.jsonl"
    if not track.exists():
        out.append({"source": "rates_desk/equity_track.jsonl", "unmeasured": "file absent"})
    else:
        rows = [json.loads(ln) for ln in track.read_text().splitlines() if ln.strip()]
        rows.sort(key=lambda r: str(r.get("date") or ""))
        eq = [float(r["close_equity"]) for r in rows if r.get("close_equity") is not None]
        if len(eq) < 30:
            out.append({"source": "rates_desk/equity_track.jsonl",
                        "unmeasured": f"only {len(eq)} points"})
        else:
            mdd, down = _equity_drawdown(eq)
            out.append({
                "source": "rates_desk/equity_track.jsonl", "kind": "fixed-rate carry desk",
                "days": len(eq), "first": rows[0].get("date"), "last": rows[-1].get("date"),
                "total_return": eq[-1] / eq[0] - 1.0, "maxdd": mdd, "down_days": down,
                "measurable": mdd > t, "unmeasured": None,
                "negative_accrual_days": sum(
                    1 for r in rows if (r.get("daily_yield_usd") or 0.0) < 0),
            })

    blend = root / "swarm" / "blend_forward.json"
    if not blend.exists():
        out.append({"source": "swarm/blend_forward.json", "unmeasured": "file absent"})
    else:
        doc = json.loads(blend.read_text())
        win = doc.get("window") or {}
        for label, node in [("blend", doc.get("blend") or {})] + sorted(
                (f"leg:{k}", v) for k, v in (doc.get("legs") or {}).items()):
            dd = node.get("max_dd_pct")
            if dd is None:
                out.append({"source": f"swarm/blend_forward.json[{label}]",
                            "unmeasured": "max_dd_pct absent"})
                continue
            out.append({
                "source": f"swarm/blend_forward.json[{label}]", "kind": "swarm forward leg",
                "days": node.get("days") or doc.get("common_days"),
                "first": (node.get("window") or win).get("start"),
                "last": (node.get("window") or win).get("end"),
                "apy": (node.get("apy_pct") or 0.0) / 100.0,
                "maxdd": float(dd) / 100.0, "down_days": None,
                "measurable": float(dd) / 100.0 > t, "unmeasured": None,
            })

    judged = [r for r in out if not r.get("unmeasured")]
    if not judged:
        raise PopulationError(
            "no forward source could be read — refusing to answer 'none is measurable'"
        )
    return {
        "toll": t, "sources": out,
        "n_judged": len(judged),
        "n_unmeasured": len(out) - len(judged),
        "n_measurable": sum(1 for r in judged if r["measurable"]),
    }


# ── §3 #149 LBS — loss-budget sizing ───────────────────────────────────────────

def cap_weights(raw: Dict[str, float], cap: float) -> Dict[str, float]:
    """Normalise `raw` to 1 and water-fill the per-name ceiling.

    Capping once and renormalising would push an uncapped name back over the ceiling, so the
    fill repeats until nothing exceeds it.  A universe too small to respect the cap
    (n * cap < 1) is a refusal, not a silently violated ceiling.
    """
    names = sorted(raw)
    if len(names) * cap < 1.0 - 1e-12:
        raise PopulationError(
            f"{len(names)} names cannot carry weight 1.0 under a {cap:.0%} ceiling"
        )
    if sum(raw.values()) <= 0:
        raise PopulationError("non-positive raw weights — refusing to normalise")
    # Standard water filling. The set of capped names is CARRIED, not recomputed from the
    # weights: a name already sitting exactly on the ceiling does not read as "over" it, so
    # recomputing the set each pass hands it more spill and the fill oscillates forever
    # (measured here before the fix — the refusal below fired on the real panel).
    capped: set = set()
    for _ in range(len(names) + 1):
        free = [k for k in names if k not in capped]
        room = sum(raw[k] for k in free)
        remaining = 1.0 - cap * len(capped)
        if not free or room <= 0 or remaining < -1e-12:
            raise PopulationError("ceiling spill has nowhere to go — refusing to drop capital")
        w = {k: cap for k in capped}
        for k in free:
            w[k] = remaining * raw[k] / room
        over = [k for k in free if w[k] > cap + 1e-12]
        if not over:
            return w
        capped |= set(over)
    raise PopulationError("per-name ceiling did not converge — refusing to publish the weights")


def lbs_weights(rets: Dict[str, Sequence[float]], books: Sequence[str], *, train_hi: int,
                cap: Optional[float] = None) -> Dict[str, object]:
    """Loss-budget weights from TRAIN only: w ~ 1 / max(maxDD_TRAIN, toll), then capped.

    The floor on the DENOMINATOR is the whole mechanism.  Without it a book that was never
    observed to lose divides by ~0 and takes the portfolio; with it, "not observed to lose"
    costs exactly as much as finding out would (one round trip).
    """
    e, t = ens(), toll()
    cap = policy_cap() if cap is None else cap
    dd: Dict[str, float] = {}
    floored: List[str] = []
    for b in books:
        d = abs(e.perf(list(rets[b][:train_hi]))["maxdd"])
        dd[b] = d
        if d <= t:
            floored.append(b)
    raw = {b: 1.0 / max(dd[b], t) for b in books}
    return {"weights": cap_weights(raw, cap), "train_maxdd": dd,
            "denominator_floored": floored, "cap": cap}


def inv_sigma_weights(rets: Dict[str, Sequence[float]], books: Sequence[str], *, train_hi: int,
                      floor_annual: Optional[float] = None,
                      cap: Optional[float] = None) -> Dict[str, float]:
    """The registry's own inverse-sigma vector (#128/#131/#144), re-used for the identity test.

    `floor_annual=None` is the raw family (#144's INV-sigma raw); a value is the #128 SFS floor.
    Computed through the imported harness so the comparison is with the published mechanism and
    not with a second implementation of it.
    """
    e = ens()
    floor = 1e-5 if floor_annual is None else floor_annual / math.sqrt(365.0)
    w = e.inverse_risk_weights(rets, list(books), end=train_hi, lookback=train_hi,
                               kind="sigma", floor=floor)
    return cap_weights(dict(w), policy_cap() if cap is None else cap)


def arm(rets: Dict[str, Sequence[float]], weights: Dict[str, float], *, lo: int, hi: int,
        roundtrip: Optional[float] = None, deployed: float = 1.0) -> Dict[str, float]:
    """Static weighted arm over [lo, hi): the toll is charged ONCE, on day one.

    `deployed` < 1 holds the remainder in CASH at 0 % — the LBS-budget variant. Cash is modelled
    as exactly 0 %, never as a floor rate: a research arm that pays itself an unearned floor is
    comparing against a benchmark it invented.
    """
    t = toll() if roundtrip is None else roundtrip
    series = [deployed * sum(weights[b] * rets[b][i] for b in weights) for i in range(lo, hi)]
    if not series:
        raise PopulationError("empty slice — refusing to report the performance of no days")
    series[0] -= t * deployed
    p = dict(ens().perf(series))
    p["maxdd"] = abs(p["maxdd"])
    p["calmar_refused"] = p["maxdd"] <= t
    p["n_days"] = float(hi - lo)
    p["deployed"] = deployed
    return p


def placebo_percentile(rets: Dict[str, Sequence[float]], weights: Dict[str, float], *,
                       lo: int, hi: int, n: int = PLACEBO_N,
                       seed: int = PLACEBO_SEED) -> Dict[str, object]:
    """Where the arm sits among permutations of its OWN weight vector.

    A permutation keeps the concentration profile bit-identical and breaks only the pairing
    between a weight and the book that earned it.  That is the one control which separates "the
    mechanism knows something" from "any vector this concentrated would have done it" (#146).
    """
    books = sorted(weights)
    vec = [weights[b] for b in books]
    actual = arm(rets, weights, lo=lo, hi=hi)
    rng = random.Random(seed)
    seen, cal, apy = set(), [], []
    guard = 0
    while len(seen) < n and guard < n * 50:
        guard += 1
        perm = tuple(rng.sample(range(len(books)), len(books)))
        if perm in seen or all(i == j for i, j in enumerate(perm)):
            continue
        seen.add(perm)
        w = {books[i]: vec[perm[i]] for i in range(len(books))}
        p = arm(rets, w, lo=lo, hi=hi)
        cal.append(p["calmar"])
        apy.append(p["apy"])
    if len(seen) < n:
        raise PopulationError(
            f"only {len(seen)} distinct permutations of {n} requested — refusing a thin placebo"
        )
    finite = [c for c in cal if math.isfinite(c)]
    # How many placebo samples landed EXACTLY on the arm. The identity permutation is excluded
    # above, so on a vector of distinct weights over distinct books this is 0 — and it is
    # COUNTED rather than asserted, because "the arm was not scored against itself" is the one
    # property of a placebo that cannot be checked by looking at the percentile.
    ties = sum(1 for c in cal if c == actual["calmar"])
    return {
        "n": len(seen), "seed": seed, "ties_with_actual": ties,
        "actual_calmar": actual["calmar"], "actual_apy": actual["apy"],
        "pct_calmar": 100.0 * sum(1 for c in cal if c <= actual["calmar"]) / len(cal),
        "pct_apy": 100.0 * sum(1 for a in apy if a <= actual["apy"]) / len(apy),
        "median_calmar": statistics.median(finite) if finite else None,
        "best_calmar": max(finite) if finite else None,
        "worst_calmar": min(finite) if finite else None,
        "median_apy": statistics.median(apy), "best_apy": max(apy), "worst_apy": min(apy),
        "n_infinite_calmar": len(cal) - len(finite),
    }


def lbs_report(panel_dir: Optional[Path] = None, *, splits: Sequence[str] = SPLITS,
               placebo_n: int = PLACEBO_N) -> Dict[str, object]:
    e = ens()
    pdir = Path(panel_dir) if panel_dir is not None else e.PANEL_DIR
    axis, rets, books = e.plb_load(pdir)
    budget, t = loss_budget(), toll()
    per_split: Dict[str, object] = {}
    for split in splits:
        hi = split_index(axis, split)
        lbs = lbs_weights(rets, books, train_hi=hi)
        w_lbs = lbs["weights"]
        # the budgeted loss proxy: every book assumed able to repeat its own TRAIN drawdown
        proxy = sum(w_lbs[b] * max(lbs["train_maxdd"][b], t) for b in books)
        deployed = min(1.0, budget / proxy) if proxy > 0 else 1.0
        w_raw = inv_sigma_weights(rets, books, train_hi=hi, floor_annual=None)
        w_flr = inv_sigma_weights(rets, books, train_hi=hi, floor_annual=SIGMA_FLOOR_ANNUAL)
        live_train, frozen_train = e.live_breadth(axis, rets, books, lo=0, hi=hi)
        ew10 = {b: 1.0 / len(books) for b in books}
        ewlive = {b: (1.0 / len(live_train) if b in live_train else 0.0) for b in books}
        # THE TWO CONTROLS THAT DECIDE WHETHER 1/maxDD ADDS ANYTHING OVER ITS OWN FLOOR.
        # LBS hands the per-name ceiling to every book whose TRAIN drawdown sits on the toll,
        # so most of its capital is chosen by the floor, not by the inverse. QUIET and MEAS are
        # the two halves of that split, equally weighted — the trivial rules the machinery has
        # to beat to be a mechanism rather than a long way of saying "buy the quiet ones".
        quiet = list(lbs["denominator_floored"])
        meas = [b for b in books if b not in lbs["denominator_floored"]]
        w_quiet = {b: (1.0 / len(quiet) if b in quiet else 0.0) for b in books} if quiet else None
        w_meas = {b: (1.0 / len(meas) if b in meas else 0.0) for b in books} if meas else None
        # cash-matched control: EW-10 carrying exactly the weight LBS parks in floored books,
        # so "its tail is lower" cannot be the idle fraction alone.
        quiet_w = sum(w_lbs[b] for b in quiet)

        def ident(other: Dict[str, float]) -> object:
            try:
                return e.rank_spearman([w_lbs[b] for b in books], [other[b] for b in books])
            except ValueError as exc:
                return f"НЕ ИЗМЕРЕНО: {exc}"

        per_split[split] = {
            "train_days": hi, "test_days": len(axis) - hi,
            "weights_lbs": w_lbs, "train_maxdd": lbs["train_maxdd"],
            "denominator_floored": lbs["denominator_floored"],
            "loss_proxy": proxy, "budget": budget, "deployed": deployed,
            "live_train": live_train, "frozen_train": frozen_train,
            "arms": {
                "EW-10 (ноль реестра)": arm(rets, ew10, lo=hi, hi=len(axis)),
                "EW-live (TRAIN-живые)": arm(rets, ewlive, lo=hi, hi=len(axis)),
                "INV-σ raw (#144)": arm(rets, w_raw, lo=hi, hi=len(axis)),
                "INV-σ floor 1%/yr (#128)": arm(rets, w_flr, lo=hi, hi=len(axis)),
                "LBS-norm": arm(rets, w_lbs, lo=hi, hi=len(axis)),
                "LBS-budget": arm(rets, w_lbs, lo=hi, hi=len(axis), deployed=deployed),
                f"КОНТРОЛЬ CASH ({(1 - quiet_w) * 100:.0f}% EW-10 + кэш)":
                    arm(rets, ew10, lo=hi, hi=len(axis), deployed=1.0 - quiet_w),
                **({f"КОНТРОЛЬ QUIET-{len(quiet)} (EW тихих)":
                    arm(rets, w_quiet, lo=hi, hi=len(axis))} if w_quiet else {}),
                **({f"КОНТРОЛЬ MEAS-{len(meas)} (EW измеримых)":
                    arm(rets, w_meas, lo=hi, hi=len(axis))} if w_meas else {}),
            },
            "quiet_weight": quiet_w,
            "train_arms": {
                "EW-10 (ноль реестра)": arm(rets, ew10, lo=0, hi=hi),
                "LBS-norm": arm(rets, w_lbs, lo=0, hi=hi),
            },
            "identity_vs_inv_sigma_raw": ident(w_raw),
            "identity_vs_inv_sigma_floor": ident(w_flr),
            "placebo": placebo_percentile(rets, w_lbs, lo=hi, hi=len(axis), n=placebo_n),
        }
    return {"axis_days": len(axis), "axis_first": axis[0], "axis_last": axis[-1],
            "books": books, "toll": t, "budget": budget, "cap": policy_cap(),
            "splits": dict(per_split)}


# ── printing ───────────────────────────────────────────────────────────────────

def _f(x, *, pct: bool = False, nd: int = 2, dash: str = "НЕ ИЗМЕРЕНО") -> str:
    if x is None:
        return dash
    if isinstance(x, str):
        return x
    if isinstance(x, float) and not math.isfinite(x):
        return "∞"
    return f"{x * 100:.{nd}f}" if pct else f"{x:.{nd}f}"


def print_census(rep: Dict[str, object]) -> None:
    t = rep["toll"]
    print("=" * 96)
    print("#148 MPC §1 — ПЕРЕПИСЬ ИЗМЕРИМОГО НАСЕЛЕНИЯ ПАНЕЛИ (исполнение заказа #145)")
    print("=" * 96)
    print(f"ось {rep['axis_days']} дней {rep['axis_first']} … {rep['axis_last']} · "
          f"книг {len(rep['books'])} · пошлина {t * 100:.2f} % (96 bp, канон реестра)")
    for split, s in rep["splits"].items():
        print(f"\n── шов {split}: TRAIN {s['train_days']} дн. · TEST {s['test_days']} дн. ──")
        print(f"{'книга':22}{'TEST APY %':>12}{'TEST maxDD %':>14}{'> пошлины?':>12}"
              f"{'дней с ходом':>14}{'TRAIN maxDD %':>15}")
        for r in s["rows"]:
            mark = "ДА" if r["test_measurable"] else ("НЕ ИЗМЕРЕНО" if r["unmeasured"] else "нет")
            print(f"{r['book']:22}{_f(r['test_apy'], pct=True):>12}"
                  f"{_f(r['test_maxdd'], pct=True, nd=3):>14}{mark:>12}"
                  f"{r['moves_test']:>14}{_f(r['train_maxdd'], pct=True, nd=3):>15}")
        print(f"\n  ИЗМЕРИМЫХ книг (TEST maxDD > пошлины): "
              f"**{s['n_measurable']} из {s['n_books']}** — {', '.join(s['measurable'])}")
        print(f"  замороженных на TEST (0 дней с ходом): {len(s['frozen_on_test'])} — "
              f"{', '.join(s['frozen_on_test']) or '—'}")
        if s["n_measurable"] <= 2:
            print(f"  ⚠️  ОГОВОРКА ЗАКАЗА #145 СРАБОТАЛА: население ≤ 2 ⇒ каждый вывод ряда "
                  f"#119…#148 обязан нести строку «измерено на населении "
                  f"{s['n_measurable']} книг».")


def print_forward(rep: Dict[str, object]) -> None:
    print("\n" + "=" * 96)
    print("#148 MPC §2 — ЕСТЬ ЛИ ИЗМЕРИМАЯ ПРОСАДКА У НЕ-НАПРАВЛЕННОЙ КНИГИ В ЖИВЫХ РЯДАХ")
    print("=" * 96)
    print(f"{'источник':46}{'дней':>7}{'APY/ret %':>11}{'maxDD %':>10}"
          f"{'вниз':>6}{'> пошлины?':>12}")
    for r in rep["sources"]:
        if r.get("unmeasured"):
            print(f"{r['source']:46}{'НЕ ИЗМЕРЕНО: ' + r['unmeasured']:>46}")
            continue
        ret = r.get("total_return", r.get("apy"))
        print(f"{r['source']:46}{r['days'] or 0:>7}{_f(ret, pct=True):>11}"
              f"{_f(r['maxdd'], pct=True, nd=4):>10}"
              f"{('—' if r['down_days'] is None else r['down_days']):>6}"
              f"{('ДА' if r['measurable'] else 'нет'):>12}")
    print(f"\n  источников прочитано {rep['n_judged']} · НЕ ИЗМЕРЕНО {rep['n_unmeasured']} · "
          f"из прочитанных ИЗМЕРИМЫХ **{rep['n_measurable']}**")
    if rep["n_measurable"] == 0:
        print("  ⇒ ответ на вторую половину заказа #145: окна с измеримой просадкой у "
              "НЕ-направленной книги в живых рядах НЕТ. Ноль здесь — «не измерено» "
              "(ряды чисто начислительные), а НЕ «риска нет» (инв. #17).")


def print_lbs(rep: Dict[str, object]) -> None:
    print("\n" + "=" * 96)
    print("#149 LBS — LOSS-BUDGET SIZING: вес обратен СВОЕЙ просадке, а не дисперсии")
    print("=" * 96)
    print(f"ось {rep['axis_days']} дн. {rep['axis_first']} … {rep['axis_last']} · "
          f"пошлина {rep['toll'] * 100:.2f} % · бюджет потерь {rep['budget'] * 100:.1f} % "
          f"(ступень SOFT_DERISK, ПРОЧИТАНА из kill_switch) · потолок {rep['cap'] * 100:.0f} %/имя")
    for split, s in rep["splits"].items():
        print(f"\n── шов {split}: TRAIN {s['train_days']} дн. · TEST {s['test_days']} дн. ──")
        print(f"{'книга':22}{'TRAIN maxDD %':>15}{'знаменатель':>14}{'вес LBS %':>11}")
        for b in rep["books"]:
            fl = "ПОЛ (пошлина)" if b in s["denominator_floored"] else "свой"
            print(f"{b:22}{_f(s['train_maxdd'][b], pct=True, nd=3):>15}{fl:>14}"
                  f"{_f(s['weights_lbs'][b], pct=True):>11}")
        print(f"  знаменатель на полу у {len(s['denominator_floored'])} книг из "
              f"{len(rep['books'])} · они держат {s['quiet_weight'] * 100:.1f} % капитала "
              f"(потолок {rep['cap'] * 100:.0f} %/имя БИНДИТ их все) · прокси потерь "
              f"{s['loss_proxy'] * 100:.2f} % ⇒ развёрнуто {s['deployed'] * 100:.1f} %, "
              f"остальное КЭШ под 0 %")
        print(f"  TRAIN-живость (min 1 ход): живых {len(s['live_train'])} · замороженных "
              f"{len(s['frozen_train'])} ⇒ EW-live {'НЕ отличается от EW-10' if not s['frozen_train'] else 'отличается'}")
        print(f"\n  {'рукав':28}{'TEST APY %':>12}{'TEST maxDD %':>14}{'TEST Calmar':>13}")
        for name, p in s["arms"].items():
            cal = "ОТКАЗАН" if p["calmar_refused"] else _f(p["calmar"], nd=3)
            print(f"  {name:28}{_f(p['apy'], pct=True):>12}"
                  f"{_f(p['maxdd'], pct=True, nd=3):>14}{cal:>13}")
        pl = s["placebo"]
        print(f"\n  ТОЖДЕСТВО (Spearman веса LBS против обратной σ): "
              f"raw {_f(s['identity_vs_inv_sigma_raw'], nd=3)} · "
              f"пол 1 %/год {_f(s['identity_vs_inv_sigma_floor'], nd=3)}")
        print(f"  ПЛАЦЕБО {pl['n']} перестановок ТОГО ЖЕ вектора (seed {pl['seed']}): "
              f"перцентиль Calmar {pl['pct_calmar']:.1f} % · APY {pl['pct_apy']:.1f} %")
        print(f"    медиана Calmar {_f(pl['median_calmar'], nd=3)} · лучшее "
              f"{_f(pl['best_calmar'], nd=3)} · худшее {_f(pl['worst_calmar'], nd=3)} · "
              f"Calmar=∞ у {pl['n_infinite_calmar']}")
        print(f"    медиана APY {_f(pl['median_apy'], pct=True)} % · лучшее "
              f"{_f(pl['best_apy'], pct=True)} % · худшее {_f(pl['worst_apy'], pct=True)} %")


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="registry #148 MPC + #149 LBS (advisory, read-only)")
    ap.add_argument("--panel-dir", default=None, help="panel root (default data/aggressive_lab)")
    ap.add_argument("--data-dir", default=None, help="data root for §2 (default data/)")
    ap.add_argument("--placebo", type=int, default=PLACEBO_N)
    ap.add_argument("--section", choices=("all", "census", "forward", "lbs"), default="all")
    a = ap.parse_args(argv)
    pdir = Path(a.panel_dir) if a.panel_dir else None
    try:
        if a.section in ("all", "census"):
            print_census(book_measurability(pdir))
        if a.section in ("all", "forward"):
            print_forward(forward_measurability(Path(a.data_dir) if a.data_dir else None))
        if a.section in ("all", "lbs"):
            print_lbs(lbs_report(pdir, placebo_n=a.placebo))
    except PopulationError as exc:
        print(f"ОТКАЗ (fail-CLOSED): {exc}", file=sys.stderr)
        return 2
    print("\nIS_ADVISORY=True · OUTSIDE_RISKPOLICY=True · RiskPolicy v1.0 не тронута · "
          "живой трек не открывался · капитал не двигается")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
