#!/usr/bin/env python3
"""
scripts/edge_static_guardian_perimeter.py — registry idea SGP (number claimed at delivery: #136)

IS_ADVISORY = True
OUTSIDE_RISKPOLICY = True

THE QUESTION, WHICH IS THE COMPOSITION OF TWO RESULTS THE REGISTRY ALREADY HAS
==============================================================================
Two entries were measured on different objects and never composed.

  #95 ODA (2026-09-02) killed the DYNAMIC per-day admission gate against its own INVERSE
      control, and left exactly one survivor, stated as a STATIC fact about a book:
          "do not run the overlay on a book whose base drawdown is smaller than the cost of
           its round trip."
      That survivor was measured PER BOOK, at a 15 bp toll convention, against a base that
      itself peeks one day (#94). It was never carried to a portfolio.

  #132 GZ (2026-10-13) carried flagship #1's overlay to the PORTFOLIO on the real panel, at
      toll parity (96 bp), against both zeros — and found it negative: dCalmar -0.241 (EW-10)
      and -1.064 (EW-live) for the pre-emptive variant. But #132 applied the overlay to
      EVERYTHING. Its own by-book table splits the sign by one visible property: the overlay
      helps the four books with a REAL tail (raw DD 16...67 %, negative raw income) and hurts
      the carriers (`pendle_pt_levered` -1.508, `susde_spot` -0.935).

The unasked question is the composition:

      Does the portfolio-level sign of #132 FLIP when the overlay is confined to a STATIC
      PERIMETER chosen the way #95's survivor says — and chosen on TRAIN only, so the choice
      is not the look-ahead that #124 and #129 have twice caught?

This is a different dial from every entry in the registry. #1/#9/#32/#33 tune WHEN the overlay
fires; #82/#88/#89 tune WHAT IT COSTS; #35 DGO and #95 ODA gate it PER DAY (both died against
their own controls); #132 measured it ON ALL BOOKS at portfolio level. Nothing has measured a
STATIC PERIMETER at PORTFOLIO level out of sample. The prior from #124 (composition choice does
not transfer) and #129 (tail persistence does not transfer) is that it fails — which is the
reason the controls below decide the verdict and the headline number does not.

MECHANISM
---------
  perimeter P(K) = { book b : maxDD_raw(b over TRAIN) >= K * price_of_round },
  price_of_round = 2 * ROUNDTRIP (the #95 convention; ROUNDTRIP is imported, never retyped).

  A book whose TRAIN maxDD is UNMEASURED (not one day below zero) is NOT admitted, and that is
  #95's survivor taken literally: "nothing to protect". The three outcomes stay apart (inv. #17)
  — `measured` / `no_down_day` / `unmeasured_empty` — and the printout names which one kept a
  book out.

  Books inside P follow flagship #1's PUBLISHED pre-emptive settings (imported from
  edge_admitted_set_guardian_zero.IDEA1_VOL, which imports the overlay itself from
  scripts/guardian_backtest.py). Books outside P stay RAW. The portfolio is equal weight over
  the universe, the same two universes as #132 (all ten books, and the live arm of #122).

  The overlay runs on the FULL book series and the judged window is sliced out of the GUARDED
  path, not restarted at the seam: restarting would hand the TEST half a flat exposure warm-up
  that no operator would have had.

  Toll parity with #132: each exposure switch costs ROUNDTRIP on the switching book, i.e.
  ROUNDTRIP * switches(b) / |U| of portfolio capital. The untolled column is kept beside it so
  the comparison with table #1 (which charges nothing) stays possible.

WHY THE ARMS ARE BUILT THIS WAY
-------------------------------
#132's portfolio arm overlays the BASKET; this file overlays EACH BOOK and then averages. Those
are different objects, and mixing them would make the headline unreadable. So the `all` arm here
is built exactly like every other arm — overlay on each book, then average — and it is the
perimeter `= universe`, which the test file pins BITWISE against a directly computed equal
weight of guarded books (and `perimeter = {}` against raw). #132's basket number is printed
beside it as a LABELLED reference, never as the base.

K = 0 is NOT that control and must not be mistaken for it: at K = 0 the threshold vanishes but
the MEASURABILITY requirement does not, so K = 0 admits every book with a measured TRAIN
drawdown and still refuses the books that never fell. On the real panel that is 7 of 10 books,
not 10 — and the gap between those two rows is exactly #95's survivor doing its one job.

Controls, all mandatory:
  * `none`       — raw equal weight, the base every delta is taken against;
  * `all`        — overlay on every book (the #132 claim rebuilt in this file's own geometry);
  * `inverse`    — overlay on the COMPLEMENT of the train perimeter. This is how #35 and #95
                   died; if the inverse is not worse, the perimeter is not measuring what it
                   claims to measure;
  * `oracle`     — perimeter chosen ON THE TEST SLICE from the overlay's realised per-book
                   benefit (LOOK-AHEAD, never a result). It is the ceiling of what perfect
                   knowledge of "who benefits" could buy. #129's lesson: if the oracle is below
                   the base, the mechanism is falsified and the headline is noise;
  * `anti_oracle`— its complement.

Acceptance is #129's three conditions, printed as three separate booleans: denominator above the
toll, per-name ceiling not breached, income above the base. A positive verdict additionally
requires the inverse control to be worse and the oracle to be above the base.

Advisory only. No capital moves, the go-live track is never opened, RiskPolicy v1.0 is untouched,
no module is built, no agent is deployed, nothing is written to disk — the report only prints.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

IS_ADVISORY = True
OUTSIDE_RISKPOLICY = True

ROOT = Path(__file__).resolve().parent.parent
GZ_PATH = ROOT / "scripts" / "edge_admitted_set_guardian_zero.py"

#: K grid for the perimeter threshold, fixed BEFORE the first number was read.
#: K = 0 admits every book that has a measured drawdown at all and is the positive control.
K_GRID: Tuple[float, ...] = (0.0, 0.5, 1.0, 2.0, 5.0, 10.0, 25.0)

_MOD_CACHE: Dict[str, object] = {}


def _load(path: Path, name: str):
    key = f"{name}:{path}"
    if key not in _MOD_CACHE:
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"cannot import {name} at {path}")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
        _MOD_CACHE[key] = mod
    return _MOD_CACHE[key]


def gz_mod(path: Path = GZ_PATH):
    """#131/#132's instrument set: the overlay wrapper, the toll, the verdicts, the three conditions."""
    return _load(path, "edge_admitted_set_guardian_zero")


def sfs_mod():
    return gz_mod().sfs_mod()


def panel_mod():
    return gz_mod().panel_mod()


# ───────────────────────────── the perimeter ─────────────────────────────
def book_drawdown(rets: Dict[str, Sequence[float]], book: str, *, lo: int,
                  hi: int) -> Dict[str, object]:
    """Raw maxDD of one book over [lo, hi) WITH its status (inv. #17), from the #128/#129 verdict.

    Reused, not reimplemented: `drawdown_verdict` is the function that decides, everywhere in
    this series, whether a zero is an observation or an artifact of a non-decreasing ledger.
    """
    S = sfs_mod()
    v = dict(S.drawdown_verdict(list(rets[book])[lo:hi]))
    return {"maxdd": v["maxdd"], "status": v["status"], "down_days": v["down_days"],
            "apy": v["apy"], "reason": v["reason"]}


def train_perimeter(rets: Dict[str, Sequence[float]], universe: Sequence[str], *, lo: int,
                    seam: int, k: float, price_of_round: float) -> Dict[str, object]:
    """#95's survivor as a SET, decided on TRAIN only.

    Admitted iff the book's TRAIN drawdown is MEASURED and at least `k` times the price of a
    round trip. A book with no measured down day is refused admission with its own named cause,
    never with a zero that would let it compete against books that actually fell.
    """
    admitted: List[str] = []
    detail: Dict[str, Dict[str, object]] = {}
    for b in universe:
        d = book_drawdown(rets, b, lo=lo, hi=seam)
        mdd = d["maxdd"]
        ok = (mdd is not None) and (mdd >= k * price_of_round)
        detail[b] = {**d, "threshold": k * price_of_round, "admitted": ok,
                     "refused_because": (None if ok else
                                         d["status"] if mdd is None else "below_threshold")}
        if ok:
            admitted.append(b)
    return {"k": k, "price_of_round": price_of_round, "admitted": sorted(admitted),
            "excluded": sorted(set(universe) - set(admitted)), "detail": detail}


# ───────────────────────────── the portfolio ─────────────────────────────
def guarded_book_returns(rets: Dict[str, Sequence[float]], books: Sequence[str]
                         ) -> Dict[str, List[float]]:
    """Flagship #1's pre-emptive overlay on each book over the FULL axis (causal, with warm-up)."""
    GZ = gz_mod()
    GB = GZ.guardian_mod()
    out: Dict[str, List[float]] = {}
    for b in books:
        eq = GZ.equity_of(rets[b])
        out[b] = GZ.returns_of(GB.apply_guardian_vol(eq, **GZ.IDEA1_VOL))
    return out


def book_switches(rets: Dict[str, Sequence[float]], guarded: Dict[str, List[float]], book: str,
                  *, lo: int, hi: int) -> int:
    """Exposure switches of one book INSIDE the judged window, by #132's own inference."""
    GZ = gz_mod()
    return GZ.exposure_switches(GZ.equity_of(list(rets[book])[lo:hi]),
                                GZ.equity_of(list(guarded[book])[lo:hi]))


def perimeter_portfolio(rets: Dict[str, Sequence[float]], guarded: Dict[str, List[float]],
                        universe: Sequence[str], perimeter: Set[str], *, lo: int, hi: int,
                        cap: Optional[float] = None) -> Dict[str, object]:
    """Equal-weight portfolio in which only the books inside `perimeter` carry the overlay.

    The toll is charged per switching book and scaled by that book's weight, because a switch in
    one tenth of the capital costs one tenth of a round trip — charging it whole would make
    selectivity look expensive for a reason arithmetic, not economic.
    """
    GZ = gz_mod()
    S = sfs_mod()
    cap = S.POLICY_CAP if cap is None else cap
    u = list(universe)
    n = len(u)
    if n == 0:
        raise ValueError("empty universe")
    w = 1.0 / n
    series = [sum((guarded[b] if b in perimeter else list(rets[b]))[i] for b in u) / n
              for i in range(lo, hi)]
    sw_per_book = {b: book_switches(rets, guarded, b, lo=lo, hi=hi) for b in sorted(perimeter)}
    sw_total = sum(sw_per_book.values())
    weighted_switches = sw_total * w
    row = GZ.judge_curve(GZ.equity_of(series), switches=weighted_switches)
    row.update({
        "perimeter": sorted(perimeter), "perimeter_size": len(perimeter),
        "universe": u, "n_books": n, "name_weight": w,
        "switches_per_book": sw_per_book, "switches_raw_count": sw_total,
        "weighted_switches": weighted_switches,
        # the keys #129's three_conditions reads, named as IT expects them. Getting this
        # mapping wrong is silent: a missing `maxdd` makes every denominator verdict False and
        # the acceptance section prints "fails" over a denominator six times the toll. Pinned by
        # test_three_conditions_sees_the_measured_denominator.
        "maxdd": row["maxdd_frac"],
        "apy_net": row["apy_frac"],
        "days_over_policy_cap": ((hi - lo) if w > cap else 0),
        "policy_cap": cap,
    })
    return row


def oracle_perimeter(rets: Dict[str, Sequence[float]], guarded: Dict[str, List[float]],
                     universe: Sequence[str], *, lo: int, hi: int) -> Dict[str, object]:
    """LOOK-AHEAD ceiling: admit exactly the books the overlay actually helped on THIS slice.

    Never a result. It exists so that a negative headline can be told apart from a headline that
    is negative because there was nothing to find — #129's `hindsight` lesson, where perfect
    knowledge of the tails was itself below equal weight and thereby falsified the mechanism.
    """
    GZ = gz_mod()
    admitted: List[str] = []
    detail: Dict[str, Dict[str, object]] = {}
    for b in universe:
        raw = GZ.judge_curve(GZ.equity_of(list(rets[b])[lo:hi]))
        gud = GZ.judge_curve(GZ.equity_of(list(guarded[b])[lo:hi]),
                             switches=book_switches(rets, guarded, b, lo=lo, hi=hi))
        d = GZ.delta_calmar(gud, raw)
        helped = (d["status"] == "measured" and d["delta_calmar"] > 0.0)
        detail[b] = {"delta_calmar": d["delta_calmar"], "status": d["status"],
                     "reason": d["reason"], "admitted": helped}
        if helped:
            admitted.append(b)
    return {"admitted": sorted(admitted), "excluded": sorted(set(universe) - set(admitted)),
            "detail": detail}


def benefit_persistence(rets: Dict[str, Sequence[float]], guarded: Dict[str, List[float]],
                        universe: Sequence[str], *, lo: int, seam: int, hi: int
                        ) -> Dict[str, object]:
    """THE PREMISE OF THE WHOLE IDEA, measured directly instead of assumed.

    A static perimeter can only work if "this book is one the overlay helps" is a property of the
    BOOK and not of the WINDOW. So: per-book dCalmar on TRAIN and on TEST, side by side, with the
    refusals kept apart from the measurements (inv. #17). A book measurable in only one half tells
    us nothing about persistence and is counted as such, never as agreement.
    """
    GZ = gz_mod()
    rows: Dict[str, Dict[str, object]] = {}
    for b in universe:
        halves: Dict[str, Dict[str, object]] = {}
        for half, (a, z) in (("train", (lo, seam)), ("test", (seam, hi))):
            raw = GZ.judge_curve(GZ.equity_of(list(rets[b])[a:z]))
            gud = GZ.judge_curve(GZ.equity_of(list(guarded[b])[a:z]),
                                 switches=book_switches(rets, guarded, b, lo=a, hi=z))
            halves[half] = GZ.delta_calmar(gud, raw)
        tr, te = halves["train"], halves["test"]
        both = (tr["status"] == "measured" and te["status"] == "measured")
        rows[b] = {
            "train_delta": tr["delta_calmar"], "train_status": tr["status"],
            "test_delta": te["delta_calmar"], "test_status": te["status"],
            "measurable_in_both": both,
            "sign_agrees": (None if not both else
                            (tr["delta_calmar"] > 0) == (te["delta_calmar"] > 0)),
        }
    both_n = sum(1 for r in rows.values() if r["measurable_in_both"])
    agree = sum(1 for r in rows.values() if r["sign_agrees"] is True)
    return {
        "per_book": rows, "measurable_in_both": both_n, "sign_agreements": agree,
        "n_books": len(universe),
        "verdict": ("unmeasured" if both_n == 0 else
                    "persistent" if agree == both_n else
                    "not_persistent" if agree == 0 else "mixed"),
        "note": (f"{both_n} of {len(universe)} books carry a measurable dCalmar in BOTH halves; "
                 f"of those, {agree} keep the sign. A book measurable in one half only is "
                 f"counted in neither column — that is the third outcome, not a disagreement."),
    }


def k_rank_transfer(train_rows: Sequence[Dict[str, object]],
                    test_rows: Sequence[Dict[str, object]]) -> Dict[str, object]:
    """Does the TRAIN ordering of K survive into TEST? Spearman over the K grid, refusals dropped.

    A rank correlation near -1 says the choice procedure does not merely fail to transfer: it
    transfers inverted, i.e. it systematically selects the cell that is WORST out of sample. That
    is a stronger statement than "no edge" and it is the one this panel supports.
    """
    H = panel_mod()
    pairs = [(a["calmar"], b["calmar"]) for a, b in zip(train_rows, test_rows)
             if a["calmar"] is not None and b["calmar"] is not None
             and not a["calmar_degenerate"] and not b["calmar_degenerate"]]
    if len(pairs) < 3:
        return {"spearman": None, "n": len(pairs), "status": "unmeasured",
                "reason": "fewer than three non-degenerate K cells in both halves"}
    rho = H.rank_spearman([p[0] for p in pairs], [p[1] for p in pairs])
    return {"spearman": rho, "n": len(pairs), "status": "measured", "reason": None}


def arm_row(rets, guarded, universe, perimeter, *, lo, hi, base: Optional[Dict[str, object]],
            label: str) -> Dict[str, object]:
    GZ = gz_mod()
    row = perimeter_portfolio(rets, guarded, universe, set(perimeter), lo=lo, hi=hi)
    row["label"] = label
    if base is not None:
        row["delta"] = GZ.delta_calmar(row, base)
        row["three"] = GZ.three_conditions(row, base)
        row["d_apy"] = (None if (row["apy_frac"] is None or base["apy_frac"] is None)
                        else row["apy_frac"] - base["apy_frac"])
        row["d_maxdd"] = (None if (row["maxdd_frac"] is None or base["maxdd_frac"] is None)
                          else row["maxdd_frac"] - base["maxdd_frac"])
        row["d_apy_tolled"] = (
            None if (row["apy_frac_after_switch_toll"] is None
                     or base["apy_frac_after_switch_toll"] is None)
            else row["apy_frac_after_switch_toll"] - base["apy_frac_after_switch_toll"])
    return row


def k_sweep(rets, guarded, universe, *, lo_choice, seam, lo_judge, hi_judge, price_of_round,
            base: Dict[str, object]) -> List[Dict[str, object]]:
    """Every K on the grid, perimeter CHOSEN on [lo_choice, seam), portfolio JUDGED on [lo_judge, hi_judge).

    When the two windows coincide the row is in-sample and the printer says so; the caller never
    gets to forget which it is holding.
    """
    rows: List[Dict[str, object]] = []
    for k in K_GRID:
        per = train_perimeter(rets, universe, lo=lo_choice, seam=seam, k=k,
                              price_of_round=price_of_round)
        row = arm_row(rets, guarded, universe, per["admitted"], lo=lo_judge, hi=hi_judge,
                      base=base, label=f"K={k:g}")
        row["k"] = k
        row["perimeter_detail"] = per
        rows.append(row)
    return rows


def pick_k(rows: Sequence[Dict[str, object]]) -> Dict[str, object]:
    """Best K by Calmar among the rows whose denominator is NOT degenerate.

    A degenerate row cannot win: ranking a portfolio whose drawdown is below its own toll against
    one that actually fell is the error #129 made mandatory to refuse.
    """
    usable = [r for r in rows if not r["calmar_degenerate"] and r["calmar"] is not None]
    if not usable:
        return {"k": None, "status": "refused",
                "reason": "every K on the grid produced a degenerate denominator on TRAIN — "
                          "no out-of-sample claim can be made from this choice"}
    best = max(usable, key=lambda r: r["calmar"])
    return {"k": best["k"], "status": "chosen", "reason": None,
            "train_calmar": best["calmar"], "train_apy": best["apy_frac"],
            "train_maxdd": best["maxdd_frac"],
            "perimeter": best["perimeter"], "candidates": len(usable)}


def sgp_report(panel_dir: Optional[Path] = None, *, lookback: int = 30) -> Dict[str, object]:
    """#136: the static perimeter of the overlay, at portfolio level, out of sample."""
    GZ = gz_mod()
    S = sfs_mod()
    H = panel_mod()
    pd_ = Path(panel_dir) if panel_dir else H.PANEL_DIR
    axis, rets, books = H.plb_load(pd_)
    census = H.book_census(pd_)
    era_idx, last_kill = H.post_kill_era(axis, census)
    live, frozen = H.live_breadth(axis, rets, books, lo=era_idx)
    live = sorted(live)

    lo, hi = lookback, len(axis)
    seam = GZ.split_index(axis, H.TRAIN_END)
    if not (lo < seam < hi):
        raise RuntimeError(f"train/test seam at index {seam} is outside the judged slice "
                           f"[{lo}, {hi}) — refusing to report an out-of-sample claim")
    price_of_round = 2.0 * S.ROUNDTRIP
    guarded = guarded_book_returns(rets, books)

    universes = {"ew10": list(books), "ew_live": live}
    out_u: Dict[str, object] = {}
    for uname, universe in universes.items():
        base_train = arm_row(rets, guarded, universe, set(), lo=lo, hi=seam, base=None,
                             label="none(raw)")
        base_test = arm_row(rets, guarded, universe, set(), lo=seam, hi=hi, base=None,
                            label="none(raw)")
        base_full = arm_row(rets, guarded, universe, set(), lo=lo, hi=hi, base=None,
                            label="none(raw)")

        train_rows = k_sweep(rets, guarded, universe, lo_choice=lo, seam=seam, lo_judge=lo,
                             hi_judge=seam, price_of_round=price_of_round, base=base_train)
        choice = pick_k(train_rows)
        test_rows = k_sweep(rets, guarded, universe, lo_choice=lo, seam=seam, lo_judge=seam,
                            hi_judge=hi, price_of_round=price_of_round, base=base_test)

        k_star = choice["k"]
        chosen_per = (train_perimeter(rets, universe, lo=lo, seam=seam, k=k_star,
                                      price_of_round=price_of_round)
                      if k_star is not None else None)
        arms: Dict[str, Dict[str, object]] = {"none": base_test}
        if chosen_per is not None:
            arms["train"] = arm_row(rets, guarded, universe, chosen_per["admitted"], lo=seam,
                                    hi=hi, base=base_test, label="train-perimeter")
            arms["inverse"] = arm_row(rets, guarded, universe, chosen_per["excluded"], lo=seam,
                                      hi=hi, base=base_test, label="inverse-perimeter")
        arms["all"] = arm_row(rets, guarded, universe, universe, lo=seam, hi=hi, base=base_test,
                              label="all(=#132 claim, own geometry)")
        orc = oracle_perimeter(rets, guarded, universe, lo=seam, hi=hi)
        arms["oracle"] = arm_row(rets, guarded, universe, orc["admitted"], lo=seam, hi=hi,
                                 base=base_test, label="oracle(LOOK-AHEAD)")
        arms["anti_oracle"] = arm_row(rets, guarded, universe, orc["excluded"], lo=seam, hi=hi,
                                      base=base_test, label="anti-oracle(LOOK-AHEAD)")

        # #132's own basket-level arm, printed as a labelled reference and never as the base
        basket = [sum(rets[b][i] for b in universe) / len(universe) for i in range(len(axis))]
        basket_ref = {
            "raw": GZ.guardian_on(basket, kind="raw"),
            "vol": GZ.guardian_on(basket, kind="vol"),
        }
        basket_ref["delta_vol"] = GZ.delta_calmar(basket_ref["vol"], basket_ref["raw"])

        persistence = benefit_persistence(rets, guarded, universe, lo=lo, seam=seam, hi=hi)
        rank_transfer = k_rank_transfer(train_rows, test_rows)
        verdict = sgp_verdict(arms)
        out_u[uname] = {
            "benefit_persistence": persistence, "k_rank_transfer": rank_transfer,
            "universe": universe, "n_books": len(universe),
            "train": {"rows": train_rows, "base": base_train, "choice": choice},
            "test": {"rows": test_rows, "base": base_test, "arms": arms},
            "full_sample_base": base_full,
            "chosen_perimeter": chosen_per,
            "oracle_perimeter": orc,
            "basket_reference_132": basket_ref,
            "verdict": verdict,
        }

    return {
        "panel_dir": str(pd_), "axis_days": len(axis), "axis": [axis[0], axis[-1]],
        "books": books, "live_arm": live, "frozen": sorted(frozen),
        "post_kill_era_index": era_idx, "last_kill": last_kill,
        "lookback": lookback, "lo": lo, "seam_index": seam, "hi": hi,
        "train_end": H.TRAIN_END, "train_days": seam - lo, "test_days": hi - seam,
        "price_of_round": price_of_round, "roundtrip": S.ROUNDTRIP, "k_grid": list(K_GRID),
        "settings_vol": dict(GZ.IDEA1_VOL),
        "universes": out_u,
    }


def sgp_verdict(arms: Dict[str, Dict[str, object]]) -> Dict[str, object]:
    """The verdict rule, written down before the numbers and evaluated from them.

    POSITIVE requires all four at once, on TEST:
      1. dCalmar(train perimeter vs raw) measured and > 0;
      2. #129's three conditions all true;
      3. the INVERSE control is worse than the train perimeter (otherwise the perimeter is not
         measuring what it claims — the way #35 and #95 died);
      4. the ORACLE is above the base (otherwise there was nothing to find and the headline,
         whatever its sign, is noise — #129's `hindsight` lesson).
    """
    t = arms.get("train")
    if t is None:
        return {"verdict": "refused", "reason": "no K was choosable on TRAIN", "checks": {}}
    d = t.get("delta", {})
    inv = arms.get("inverse", {})
    orc = arms.get("oracle", {})
    c1 = (d.get("status") == "measured" and (d.get("delta_calmar") or 0.0) > 0.0)
    c2 = bool(t.get("three", {}).get("all_three"))
    inv_d = inv.get("delta", {})
    c3 = (inv_d.get("status") == "measured" and d.get("status") == "measured"
          and inv_d.get("delta_calmar") < d.get("delta_calmar"))
    orc_d = orc.get("delta", {})
    c4 = (orc_d.get("status") == "measured" and (orc_d.get("delta_calmar") or 0.0) > 0.0)
    checks = {"delta_positive": c1, "three_conditions": c2, "inverse_worse": c3,
              "oracle_above_base": c4}
    return {"verdict": ("positive" if all(checks.values()) else "negative"),
            "checks": checks,
            "reason": (None if all(checks.values()) else
                       "; ".join(k for k, v in checks.items() if not v) + " — failed")}


# ───────────────────────────────── printing ─────────────────────────────────
def _f(x, *, pct: bool = False, nd: int = 2, dash: str = "НЕ ИЗМЕРЕН") -> str:
    if x is None:
        return dash
    return f"{x * 100:.{nd}f} %" if pct else f"{x:.{nd}f}"


def _cal(row: Dict[str, object]) -> str:
    return "ОТКАЗАН" if row.get("calmar_degenerate") else _f(row.get("calmar"), nd=3)


def _delta(row: Dict[str, object]) -> str:
    d = row.get("delta")
    if not d:
        return "—"
    return (f"{d['delta_calmar']:+.3f}" if d["status"] == "measured" else "ОТКАЗАН")


def print_sgp(rep: Dict[str, object]) -> None:
    print("=" * 112)
    print("#136 SGP — СТАТИЧЕСКИЙ ПЕРИМЕТР ОВЕРЛЕЯ НА УРОВНЕ ПОРТФЕЛЯ "
          "(композиция выжившего вывода #95 и отрицательного #132)")
    print("=" * 112)
    print("прибор: оверлей и метрики ИМПОРТИРОВАНЫ через edge_admitted_set_guardian_zero "
          "(он — из scripts/guardian_backtest.py)")
    print(f"настройки #1 (UPD5, OOS): {rep['settings_vol']}")
    print(f"панель {rep['panel_dir']} · ось {rep['axis'][0]}…{rep['axis'][1]} "
          f"({rep['axis_days']} дней)")
    print(f"шов train/test = {rep['train_end']} (индекс {rep['seam_index']}): "
          f"TRAIN {rep['train_days']} дней · TEST {rep['test_days']} дней")
    print(f"цена круга = 2 × пошлина {rep['roundtrip']:.4f} = {rep['price_of_round']:.4f}; "
          f"сетка K {rep['k_grid']} зафиксирована ДО первого числа")

    for uname, u in rep["universes"].items():
        print("\n" + "─" * 112)
        print(f"ВСЕЛЕННАЯ {uname} ({u['n_books']} книг: {', '.join(u['universe'])})")
        print("─" * 112)

        ch = u["train"]["choice"]
        print(f"\n§1 ВЫБОР K НА TRAIN (in-sample — это НЕ результат, это ВХОД шага 2)")
        print(f"{'K':>6} {'в периметре':>12} {'APY':>9} {'maxDD':>9} {'Calmar':>9} "
              f"{'перекл.':>8} {'APY по пошлине':>15}  периметр")
        for r in u["train"]["rows"]:
            print(f"{r['k']:>6g} {r['perimeter_size']:>12} {_f(r['apy_frac'], pct=True):>9} "
                  f"{_f(r['maxdd_frac'], pct=True):>9} {_cal(r):>9} "
                  f"{r['switches_raw_count']:>8} "
                  f"{_f(r['apy_frac_after_switch_toll'], pct=True):>15}  "
                  f"{', '.join(r['perimeter']) or '—'}")
        if ch["status"] == "chosen":
            print(f"  K* = {ch['k']:g} (Calmar TRAIN {ch['train_calmar']:.3f}), "
                  f"периметр: {', '.join(ch['perimeter']) or '—'}")
        else:
            print(f"  K* ОТКАЗАН — {ch['reason']}")

        if u["chosen_perimeter"]:
            print("\n§2 ПОЧЕМУ КАЖДАЯ КНИГА ВОШЛА ИЛИ НЕ ВОШЛА (решено ТОЛЬКО по TRAIN)")
            print(f"{'книга':22} {'TRAIN maxDD':>12} {'статус':>22} {'дней вниз':>10} "
                  f"{'порог':>9} {'в периметре':>12} {'причина отказа':>22}")
            for b, d in sorted(u["chosen_perimeter"]["detail"].items()):
                print(f"{b:22} {_f(d['maxdd'], pct=True):>12} {str(d['status']):>22} "
                      f"{str(d['down_days']):>10} {_f(d['threshold'], pct=True):>9} "
                      f"{str(d['admitted']):>12} {str(d['refused_because'] or '—'):>22}")

        print("\n§3 TEST — ВСЕ РУКАВА ПРОТИВ ОДНОГО НУЛЯ (сырой равный вес), геометрия у всех одна")
        print(f"{'рукав':30} {'в пер.':>7} {'APY':>9} {'maxDD':>9} {'Calmar':>9} "
              f"{'ΔCalmar':>9} {'ΔAPY пп':>9} {'ΔmaxDD пп':>10} {'перекл.':>8} "
              f"{'APY пошл.':>11} {'3 усл.':>7}")
        order = ["none", "train", "inverse", "all", "oracle", "anti_oracle"]
        for key in order:
            r = u["test"]["arms"].get(key)
            if r is None:
                continue
            three = r.get("three", {})
            print(f"{r['label']:30} {r['perimeter_size']:>7} {_f(r['apy_frac'], pct=True):>9} "
                  f"{_f(r['maxdd_frac'], pct=True):>9} {_cal(r):>9} {_delta(r):>9} "
                  f"{_f(r.get('d_apy'), pct=True, dash='—'):>9} "
                  f"{_f(r.get('d_maxdd'), pct=True, dash='—'):>10} "
                  f"{r['switches_raw_count']:>8} "
                  f"{_f(r['apy_frac_after_switch_toll'], pct=True):>11} "
                  f"{str(three.get('all_three', '—')):>7}")

        bref = u["basket_reference_132"]
        bd = bref["delta_vol"]
        bd_txt = (f"{bd['delta_calmar']:+.3f}" if bd["status"] == "measured" else "ОТКАЗАН")
        print(f"  СПРАВКА (не база): #132 оверлеит КОРЗИНУ, а не книги — её ΔCalmar {bd_txt} "
              f"на ПОЛНОЙ оси. Это ДРУГОЙ объект, и базой здесь он не является.")

        print("\n§4 ОВЕРФИТ-ЗАПАС: тот же K-свип, судимый НА TEST (K* выбран слепо на TRAIN)")
        print(f"{'K':>6} {'в периметре':>12} {'APY':>9} {'maxDD':>9} {'Calmar':>9} "
              f"{'ΔCalmar':>9}  периметр")
        for r in u["test"]["rows"]:
            mark = " ← K*" if (ch["status"] == "chosen" and r["k"] == ch["k"]) else ""
            print(f"{r['k']:>6g} {r['perimeter_size']:>12} {_f(r['apy_frac'], pct=True):>9} "
                  f"{_f(r['maxdd_frac'], pct=True):>9} {_cal(r):>9} {_delta(r):>9}  "
                  f"{', '.join(r['perimeter']) or '—'}{mark}")

        orc = u["oracle_perimeter"]
        print(f"\n§5 ORACLE (ВЗГЛЯД ИЗ БУДУЩЕГО, не результат) — кому оверлей ПОМОГ на самой TEST")
        print(f"  помог: {', '.join(orc['admitted']) or '—'}")
        for b, d in sorted(orc["detail"].items()):
            if d["status"] != "measured":
                print(f"    {b:22} ΔCalmar ОТКАЗАН — {d['reason']}")
            else:
                print(f"    {b:22} ΔCalmar {d['delta_calmar']:+.3f}")

        bp = u["benefit_persistence"]
        print(f"\n§6 ПРЕДПОСЫЛКА ИДЕИ, ИЗМЕРЕННАЯ ПРЯМО: ПЕРЕНОСИТСЯ ЛИ «кому оверлей помогает»")
        print(f"{'книга':22} {'ΔCalmar TRAIN':>14} {'статус':>12} {'ΔCalmar TEST':>14} "
              f"{'статус':>12} {'знак совпал':>12}")
        for b, d in sorted(bp["per_book"].items()):
            print(f"{b:22} {_f(d['train_delta'], nd=3, dash='ОТКАЗАН'):>14} "
                  f"{str(d['train_status']):>12} {_f(d['test_delta'], nd=3, dash='ОТКАЗАН'):>14} "
                  f"{str(d['test_status']):>12} {str(d['sign_agrees'] if d['sign_agrees'] is not None else '—'):>12}")
        print(f"  вердикт переносимости: {bp['verdict'].upper()} — {bp['note']}")
        kt = u["k_rank_transfer"]
        if kt["status"] == "measured":
            print(f"  перенос ПОРЯДКА K (spearman TRAIN↔TEST по {kt['n']} невырожденным клеткам): "
                  f"{kt['spearman']:+.3f}")
        else:
            print(f"  перенос порядка K: НЕ ИЗМЕРЕН — {kt['reason']}")

        v = u["verdict"]
        print(f"\n§7 ВЕРДИКТ {uname}: {v['verdict'].upper()}")
        for k, val in v["checks"].items():
            print(f"    {k:22} {val}")
        if v["reason"]:
            print(f"    причина: {v['reason']}")


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="registry #136 SGP (advisory, read-only)")
    ap.add_argument("--panel", default=None,
                    help="panel dir (from a worktree pass the prod tree's data/aggressive_lab — "
                         "the panel is untracked)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    rep = sgp_report(Path(a.panel) if a.panel else None)
    if a.json:
        print(json.dumps(rep, indent=2, ensure_ascii=False, default=str))
    else:
        print_sgp(rep)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
