#!/usr/bin/env python3
"""Edge R&D #67 STT / #68 FFB — the STANDING TILT the registry keeps finding and never testing.

WHY THIS FILE EXISTS
════════════════════
Three entries in a row (#63, #65, #66) end on the same sentence, and none of them acted on it:

    «Открытым остаётся то же … стоячий наклон, который статический двойник берёт при НУЛЕВОМ
     обороте (адрес — ADR-055, не рой).»

The observation behind it is `ecr.alloc_static_matched` — the time-average of a dynamic rule's own
weights, held constant. On BOTH panels that twin beats the published rule #40 on Calmar while
trading nothing at all (8.50 vs 8.32 on ten books, 9.83 vs 9.08 on the six live ones). If that is
real, then a large part of what this family has been calling "timing" is a tilt an allocator could
take ONCE and hold — which is an ADR-055 matter (Head-of-Investment layer), not a swarm rule, and
it would be cheaper, calmer and simpler than everything #35–#66 built.

But the twin as printed is UNTESTABLE AS A PROPOSAL, for two reasons that no entry has named:

  1. **It is fitted on the days it is scored on.** The average runs over the WHOLE sample, so the
     twin knows in March which books will be good in the following December. It is an accounting
     decomposition ("how much of the result needed timing"), never a rule anybody could have run.

  2. **It is billed at zero, and a constant target is not a free portfolio.** #49 RDT measured
     exactly this: the registry charges the change of the TARGET, so constant weights cost nothing
     on paper while reality pays for pushing drifted weights back — `raw` really pays 86 bp/year,
     `static-matched` 52. Every static-twin row ever printed in this registry carries a bill of
     zero that its own registry knows to be wrong.

This file removes both. One knob, and only one:

    WHEN IS THE TILT ALLOWED TO LEARN?   ← the whole subject

    twin (as printed)  : average over the segment it is scored on        ← hindsight, upper bound
    #67 STT            : average over TRAIN ONLY, frozen, scored on TEST ← a rule one could run
    #68 FFB            : never sees #40 at all — the bottom-k books over TRAIN are frozen OUT

TWO IDEAS, TWO DIFFERENT QUESTIONS
══════════════════════════════════
#67 STT (Static Tilt Transferability) — DOES THE TILT SURVIVE ITS OWN SPLIT? Take #40's realised
    weight path, average it over TRAIN, freeze that vector, hold it through TEST with no trading
    decision of any kind. Three numbers decide it:
      • does the frozen tilt beat raw equal weight out of sample at all;
      • how much of #40's own out-of-sample excess it captures (the CAPTURE ratio);
      • and does its MIRROR — the same tilt reflected through equal weight — do worse? A tilt
        whose inversion is not worse is not information, it is a shape (the lesson of #66, where
        the anti-gate beat the gate on both panels).

#68 FFB (Frozen-Flag Baseline) — IS THE STATE MACHINE NEEDED AT ALL? #40's apparatus is a
    trailing drift score, a bottom-k ranking and an M=20 stickiness latch. Replace all of it with
    the crudest thing that can be called a tilt: rank the books by their MEAN RETURN over TRAIN,
    freeze the bottom k out for ever, water-fill the rest at the 20 % cap. Same allocator
    (`ecr.alloc_recycle`), same k, same cap — the ONLY difference is that the flags never change
    again. If this matches #40 out of sample, the machinery is buying nothing that a one-line
    exclusion list does not already have. Its refuting control is the same rule with the TOP k
    frozen out: if excluding the best books is not worse, TRAIN ranking carries no persistence.

WHAT IS DELIBERATELY NOT VARIED
═══════════════════════════════
No new criterion, no new lookback, no new k, M or cap: L=60, k=2, M=20, cap 20 % are inherited
from #37/#39/#40 and are not re-tuned here. The split is the registry's own 2025-06-30 — and
because a single split is a parameter in disguise (#65's own conviction, where the optimum moved
1.00 → 1.5–2.0 across it), the verdict is printed on a LADDER of four splits, not one.

HONESTY / SCOPE
═══════════════
  • Evidence L0 — backtest over the real feed panel, NOT a live track. Every table names its
    segment ([TRAIN] / [TEST]) so an in-sample row cannot be read as an out-of-sample one, and the
    hindsight twin is printed on every table, labelled as hindsight, so the honest number always
    has its own upper bound beside it.
  • The panel is the family's own and it is holed: 4 of 10 books are dark (#54). EVERY table is
    printed twice — all ten and the six live — and the two are NEVER averaged.
  • Both bills are printed side by side on every row: `turnT` (change of target — the registry's
    convention, comparable with #35–#66) and `turnI` (implementation turnover of #49, what a real
    book would pay). netAPY is given under BOTH. For a constant tilt these differ by construction;
    quoting only the first is how a static row gets to look free.
  • The tilt is a VECTOR OF WEIGHTS, not a forecast. It is causal only in the sense that it is
    fitted strictly before the segment it is scored on; nothing here claims a book's TRAIN average
    predicts its TEST average — that claim is precisely what the measurement decides.
  • Read-only. Writes nothing anywhere, imports no execution code, touches neither the live track
    nor `data/` nor RiskPolicy v1.0 nor the kill-switch. IS_ADVISORY = True,
    OUTSIDE_RISKPOLICY = True. Capital does not move. No agent is deployed by this file.

Usage:
    python3 scripts/edge_static_tilt_transfer.py               # everything
    python3 scripts/edge_static_tilt_transfer.py --idea 67     # STT only
    python3 scripts/edge_static_tilt_transfer.py --idea 68     # FFB only
    python3 scripts/edge_static_tilt_transfer.py --splits      # the four-split ladder
    python3 scripts/edge_static_tilt_transfer.py --controls    # permutation of the frozen tilt
    python3 scripts/edge_static_tilt_transfer.py --tilt        # print the frozen vectors themselves
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import edge_calm_fp_tax as cfpt                 # noqa: E402  (panel loader, perf, BP)
import edge_capital_recycling as ecr            # noqa: E402  (allocator, costs, static twin)
import edge_cross_sectional_demotion as xsd     # noqa: E402  (rank state machine of #40)
import edge_drift_gated_overlay as dgo          # noqa: E402  (Panel of #35/#36/#37)
import edge_event_time_scoring as ets           # noqa: E402  (SynthPanel + live/dead census of #54)
import edge_rebalance_drift_tax as rdt          # noqa: E402  (the REAL bill of #49)
import edge_redundancy_demotion as erd          # noqa: E402  (criterion dispatcher of #44/#45)
import edge_score_proportional as spw           # noqa: E402  (#40's weights + the #38 controls)

IS_ADVISORY = True
OUTSIDE_RISKPOLICY = True

LOOKBACK = xsd.LOOKBACK              # 60 — inherited from #37/#39/#40, NOT re-tuned here
TRAIN_END = ecr.TRAIN_END            # "2025-06-30" — the registry's own split
REF_K = 2                            # #40's reference k, so every row is like-for-like
REF_M = 20                           # #40's published stickiness
CONC_CAP = ecr.CONC_CAP              # 0.20 — the project's own per-name cap
COST_BP_ROUND_TRIP = ecr.COST_BP_ROUND_TRIP   # 96 bp (#10), the same bill as every other entry
BP = cfpt.BP
EPS = ecr.EPS
SEEDS = 20                           # control seeds, same count as #38/#40/#58/#59/#63/#65

# Four splits, fixed BEFORE any result was looked at: quarter-ends spanning the middle of the
# sample, so the shortest TEST window is still ~half a year. A verdict that only holds at the
# registry's own 2025-06-30 is a verdict about that date (#65's lesson, paid for once already).
SPLITS = ("2025-03-31", "2025-06-30", "2025-09-30", "2025-12-31")


# ═══════════════════════════ segments: score a fixed path on a window ═══════════════════════════
def split_index(panel, split_date: str) -> int:
    """First index of the TEST side. `dgo.Panel` slices with `d > start`, and so does this."""
    for i, d in enumerate(panel.axis):
        if d > split_date:
            return i
    return panel.n


def segment(panel, i0: int, i1: int):
    """A Panel-shaped view over days [i0, i1) of an existing panel — same books, same returns.

    Why this exists instead of `dgo.Panel(subset, start, end)`: a fresh Panel makes the rule's
    60-day lookback warm up again INSIDE the window, so the TEST rows of a segmented run are a
    different program from the FULL one. Here the weight path is computed ONCE over the whole
    sample and only SCORED on a window, which is the comparison this file needs — the tilt and
    the rule must be judged on the same days with the same history behind them.

    Fail-CLOSED on an empty or reversed window: a metric over no days is not a small number.
    """
    if not 0 <= i0 < i1 <= panel.n:
        raise ValueError(f"bad window [{i0}, {i1}) over {panel.n} days — refusing to score on it")
    return ets.SynthPanel(list(panel.axis[i0:i1]),
                          {b: list(panel.rets[b][i0:i1]) for b in panel.books})


def slice_weights(weights: Dict[str, List[float]], i0: int, i1: int) -> Dict[str, List[float]]:
    return {b: list(w[i0:i1]) for b, w in weights.items()}


# ═══════════════════════════════ #67 — the frozen tilt ═══════════════════════════════
def tilt_from(weights: Dict[str, List[float]], i0: int, i1: int) -> Dict[str, float]:
    """The time-average of a weight path over days [i0, i1) — the tilt, as a vector.

    Over the WHOLE path this is `ecr.alloc_static_matched` by definition (pinned by the test-suite
    in both directions: identical on the full range, materially different on a sub-range). The
    single difference that makes this file a measurement rather than a decomposition is that i1
    is allowed to stop before the days being scored.
    """
    if not weights:
        raise ValueError("no weights — a tilt over an empty allocation is not a tilt")
    n = len(next(iter(weights.values())))
    if not 0 <= i0 < i1 <= n:
        raise ValueError(f"bad fit window [{i0}, {i1}) over {n} days — refusing to fit on it")
    return {b: sum(w[i0:i1]) / (i1 - i0) for b, w in weights.items()}


def const_weights(tilt: Dict[str, float], n: int) -> Dict[str, List[float]]:
    """Hold a tilt for n days. Zero decisions, zero target turnover — and a real bill (see #49)."""
    if n <= 0:
        raise ValueError("refusing to hold a tilt for a non-positive number of days")
    return {b: [v] * n for b, v in tilt.items()}


def _waterfill_to(tilt: Dict[str, float], total: float,
                  cap: Optional[float]) -> Tuple[Dict[str, float], float]:
    """Push a non-negative vector back up to `total`, respecting `cap`. Returns (vector, unplaced).

    What will not fit under the cap is NOT redistributed into a breach and NOT silently dropped:
    it comes back as `unplaced` and the caller reports it as cash. Same decision `ecr._waterfill`
    makes, and for the same reason — a cap that bends under pressure is not a cap.
    """
    out = {b: max(0.0, v) for b, v in tilt.items()}
    if cap is not None:
        out = {b: min(v, cap) for b, v in out.items()}
    for _ in range(len(out) + 2):
        short = total - sum(out.values())
        if short <= EPS:
            break
        room = {b: (float("inf") if cap is None else cap - out[b]) for b in out}
        takers = [b for b in out if room[b] > EPS]
        if not takers:
            break
        per = short / len(takers)
        for b in takers:
            out[b] += min(per, room[b])
    return out, max(0.0, total - sum(out.values()))


def mirror_tilt(tilt: Dict[str, float], cap: Optional[float] = CONC_CAP
                ) -> Tuple[Dict[str, float], float]:
    """THE refuting control: the same tilt reflected through its own equal-weight centre.

        w'_b = 2·(S/N) − w_b,   then clipped to [0, cap] and water-filled back to S

    Deployment, concentration and the character of the portfolio survive; the ORDER of the books
    is exactly reversed. If the mirror is not worse out of sample, the tilt carries no information
    about which book is which — which is precisely how #66's gate died, and the control that
    killed it is the one being reused here.
    """
    if not tilt:
        raise ValueError("no tilt to mirror")
    total = sum(tilt.values())
    centre = total / len(tilt)
    return _waterfill_to({b: 2.0 * centre - v for b, v in tilt.items()}, total, cap)


# ═══════════════════════════════ #68 — the frozen flag list ═══════════════════════════════
def train_mean_ranking(panel, i0: int, i1: int) -> List[Tuple[str, float]]:
    """Books ordered worst → best by MEAN RETURN over the fit window. Ties break by name."""
    seg = segment(panel, i0, i1)
    means = {b: sum(seg.rets[b]) / seg.n for b in seg.books}
    return sorted(means.items(), key=lambda kv: (kv[1], kv[0]))


def frozen_flags(panel, i0: int, i1: int, k: int, n: int,
                 invert: bool = False) -> Dict[str, List[bool]]:
    """Flag the k WORST books of the fit window — for ever. `invert` flags the k BEST instead.

    Fail-CLOSED at the edges: k below zero is not a rule, and k at or above the book count would
    demote the entire panel, which is a request for an all-cash book wearing a tilt's name. At
    k = 0 nothing is flagged and the allocator returns equal weight — the corner that makes this
    rule continuous with `raw`, pinned by the test-suite.
    """
    if k < 0:
        raise ValueError("k must be non-negative — refusing to un-demote books")
    if k >= len(panel.books):
        raise ValueError(f"k={k} would freeze out all {len(panel.books)} books — not a tilt")
    order = train_mean_ranking(panel, i0, i1)
    chosen = {b for b, _ in (order[len(order) - k:] if invert else order[:k])} if k else set()
    return {b: [b in chosen] * n for b in panel.books}


def ffb_weights(panel, i0: int, i1: int, k: int = REF_K, n: Optional[int] = None,
                cap: Optional[float] = CONC_CAP, invert: bool = False) -> Dict[str, List[float]]:
    """#68 — #40's own allocator over a flag set that was decided once and never moves again."""
    days = panel.n if n is None else n
    flags = frozen_flags(panel, i0, i1, k, days, invert)
    return ecr.alloc_recycle(panel.books, flags, days, cap=cap)


# ═══════════════════════════════ scoring: BOTH bills, always ═══════════════════════════════
def evaluate(seg, weights: Dict[str, List[float]]) -> Dict[str, float]:
    """Registry metrics plus the implementation bill of #49 — never one without the other."""
    m = dict(ecr.portfolio_metrics(seg, weights, cost_bp_round_trip=COST_BP_ROUND_TRIP))
    impl = rdt.implementation_turnover(seg, weights)
    m["turnover_impl_yr"] = impl
    m["cost_impl_bp_yr"] = 0.5 * COST_BP_ROUND_TRIP * impl
    m["net_apy_after_impl"] = m["apy"] - m["cost_impl_bp_yr"] / BP
    return m


def rows_for(panel, scores, split: str, k: int = REF_K,
             cap: Optional[float] = CONC_CAP) -> Tuple[int, List[Tuple[str, Dict[str, List[float]]]]]:
    """Every row this file prints, on the FULL-sample axis; the caller scores them on a window.

    Building them all here — including the two hindsight rows — is deliberate: a report that runs
    the honest rule on one table and its upper bound on another lets the reader compare numbers
    that were never computed on the same days.
    """
    s = split_index(panel, split)
    if s <= 0 or s >= panel.n:
        raise ValueError(f"split {split} leaves one side empty — refusing to fit or score on it")
    n = panel.n
    nb = len(panel.books)
    pub = spw.binary_weights(panel, scores, k, REF_M, cap)
    stt = tilt_from(pub, 0, s)
    mir, unplaced = mirror_tilt(stt, cap)
    rows: List[Tuple[str, Dict[str, List[float]]]] = [
        ("raw equal weight", {b: [1.0 / nb] * n for b in panel.books}),
        (f"#40 XSD k={k} M={REF_M} [published]", pub),
        ("#67 STT tilt fitted on TRAIN", const_weights(stt, n)),
        ("  CONTROL mirror of the TRAIN tilt", const_weights(mir, n)),
        ("#68 FFB frozen bottom-k of TRAIN", ffb_weights(panel, 0, s, k, n, cap)),
        ("  CONTROL FFB frozen TOP-k (invert)", ffb_weights(panel, 0, s, k, n, cap, invert=True)),
        ("  HINDSIGHT twin of #40 (whole sample)", ecr.alloc_static_matched(pub)),
    ]
    if unplaced > EPS:
        print(f"[note] mirror could not place {unplaced*100:.2f}% under the {cap:.0%} cap — "
              f"it is held as CASH, not as a breach")
    return s, rows


# ═══════════════════════════════ reporting ═══════════════════════════════
_COLS = (f"{'configuration':38s} {'APY':>8s} {'maxDD':>8s} {'Calmar':>7s} {'turnT':>7s} "
         f"{'turnI':>7s} {'netT':>8s} {'netI':>8s}")


def _print_rows(title: str, seg, rows: Sequence[Tuple[str, Dict[str, List[float]]]],
                i0: int, i1: int) -> Dict[str, Dict[str, float]]:
    print()
    print("=" * 110)
    print(title)
    print("=" * 110)
    print(_COLS)
    out: Dict[str, Dict[str, float]] = {}
    for name, w in rows:
        m = evaluate(seg, slice_weights(w, i0, i1))
        out[name.strip()] = m
        print(f"{name:38s} {m['apy']*100:7.2f}% {m['maxdd']*100:7.2f}% {m['calmar']:7.2f} "
              f"{m['turnover_yr']:7.2f} {m['turnover_impl_yr']:7.2f} "
              f"{m['net_apy_after_cost']*100:7.2f}% {m['net_apy_after_impl']*100:7.2f}%")
    return out


def _capture(res: Dict[str, Dict[str, float]], rule: str, key: str = "net_apy_after_impl"
             ) -> Optional[float]:
    """Share of #40's own excess over raw that a row captures. None when #40 has no excess to
    share — a ratio against a non-positive denominator is a number with no meaning, and printing
    one anyway is how a losing segment turns into a triumphant percentage."""
    raw = res["raw equal weight"][key]
    pub = next(v[key] for kk, v in res.items() if kk.startswith("#40 XSD"))
    if pub - raw <= EPS:
        return None
    return (res[rule][key] - raw) / (pub - raw)


def _only(rows: Sequence[Tuple[str, Dict[str, List[float]]]], idea: Optional[int]
          ) -> List[Tuple[str, Dict[str, List[float]]]]:
    """Keep one idea's rows — and ALWAYS raw, #40 and the hindsight bound beside them.

    A row cannot be read without its baselines, so `--idea` drops the OTHER idea and nothing else.
    """
    if idea is None:
        return list(rows)
    other = "#68" if idea == 67 else "#67"
    keep = []
    for name, w in rows:
        t = name.strip()
        if t.startswith(other) or (other == "#68" and t.startswith("CONTROL FFB")) \
                or (other == "#67" and t.startswith("CONTROL mirror")):
            continue
        keep.append((name, w))
    return keep


def report(subset: Optional[Sequence[str]], label: str, split: str = TRAIN_END,
           k: int = REF_K, cap: Optional[float] = CONC_CAP,
           idea: Optional[int] = None) -> Dict[str, Dict[str, float]]:
    """The main measurement: fit on TRAIN, score on TRAIN and on the unseen TEST."""
    panel = dgo.Panel(subset)
    scores = erd.panel_scores(panel, "drift", LOOKBACK)
    s, rows = rows_for(panel, scores, split, k, cap)
    rows = _only(rows, idea)
    head = f"{label}  ·  {panel.n} days  ·  {len(panel.books)} books  ·  split {split}"
    _print_rows(f"#67 STT / #68 FFB — [FULL — the segment the registry has always printed] — {head}",
                panel, rows, 0, panel.n)
    _print_rows(f"#67 STT / #68 FFB — [TRAIN, tilt fitted HERE: {s} days] — {head}",
                segment(panel, 0, s), rows, 0, s)
    te = _print_rows(f"#67 STT / #68 FFB — [TEST, unseen: {panel.n - s} days] — {head}",
                     segment(panel, s, panel.n), rows, s, panel.n)
    print("-" * 110)
    print("turnT = change of TARGET (the registry's own bill, #35–#66) · turnI = implementation "
          "turnover (#49,\nwhat a real book pays to hold a constant target while the books drift "
          "apart). netT/netI are APY minus\neach. The HINDSIGHT row averages the WHOLE sample "
          "including these very TEST days — it is an upper\nbound and never a proposal; the STT "
          "row is the same construction that could actually have been run.")
    for rule in ("#67 STT tilt fitted on TRAIN", "#68 FFB frozen bottom-k of TRAIN"):
        if rule not in te:
            continue
        c = _capture(te, rule)
        print(f"CAPTURE on TEST · {rule:34s}: "
              + ("#40 has no excess over raw on this segment — ratio refused"
                 if c is None else f"{c*100:6.1f}% of #40's netI excess over raw"))
    return te


def splits_ladder(subset: Optional[Sequence[str]], label: str, k: int = REF_K,
                  cap: Optional[float] = CONC_CAP) -> None:
    """The same question at four split dates — because one split is a fitted parameter (#65).

    BOTH ladders are printed, netAPY and Calmar, because the two ideas make their case on
    different columns: a ladder that shows only the column the headline row happens to win is a
    choice made after seeing the numbers.
    """
    panel = dgo.Panel(subset)
    scores = erd.panel_scores(panel, "drift", LOOKBACK)
    # Measured once per split and printed twice: recomputing per metric would run the mirror's
    # cap diagnostic twice and drop its note into the middle of the second table.
    measured: List[Tuple[str, int, List[str], List[Dict[str, float]]]] = []
    for split in SPLITS:
        s, rows = rows_for(panel, scores, split, k, cap)
        seg = segment(panel, s, panel.n)
        fl = frozen_flags(panel, 0, s, k, panel.n)
        measured.append((split, s, [b for b in panel.books if fl[b][0]],
                         [evaluate(seg, slice_weights(w, s, panel.n)) for _, w in rows]))
    for key, unit in (("net_apy_after_impl", "netAPY after the IMPLEMENTATION bill"),
                      ("calmar", "Calmar")):
        pct = key != "calmar"
        print()
        print("=" * 110)
        print(f"SPLIT LADDER (TEST side only, {unit}) — {label}")
        print("=" * 110)
        print(f"{'split':12s} {'testDays':>8s} {'raw':>8s} {'#40':>8s} {'#67 STT':>8s} "
              f"{'mirror':>8s} {'#68 FFB':>8s} {'FFB-top':>8s} {'hindsight':>10s}")
        for split, s, _names, ms in measured:
            vals = [m[key] for m in ms]
            cells = [f"{v*100:7.2f}%" if pct else f"{v:8.2f}" for v in vals[:-1]]
            tail = f" {vals[-1]*100:9.2f}%" if pct else f" {vals[-1]:10.2f}"
            print(f"{split:12s} {panel.n - s:8d} " + " ".join(cells) + tail)
    frozen_by_split = [(split, names) for split, _s, names, _m in measured]
    print("-" * 110)
    print("A tilt that only transfers at one split date is a statement about that date. The "
          "mirror column is\nthe refuting control (#66's): wherever it is not clearly worse than "
          "#67, the tilt is a shape, not\ninformation about WHICH book is which.")
    print("The four TEST windows are NESTED, not independent samples: the later split's window is "
          "a suffix of\nthe earlier one, so four agreeing rows are four views of the same tail, "
          "not four confirmations.")
    print("WHICH books #68 freezes out — the mechanism of its own instability, printed rather "
          "than inferred:")
    for split, names in frozen_by_split:
        print(f"  {split}: " + (", ".join(names) if names else "(none)"))


def controls(subset: Optional[Sequence[str]], label: str, split: str = TRAIN_END,
             k: int = REF_K, cap: Optional[float] = CONC_CAP) -> None:
    """#38's permutation control, applied to the frozen vectors on the TEST side only."""
    panel = dgo.Panel(subset)
    scores = erd.panel_scores(panel, "drift", LOOKBACK)
    s, rows = rows_for(panel, scores, split, k, cap)
    seg = segment(panel, s, panel.n)
    named = [(n_, w) for n_, w in rows if n_.strip().startswith(("#67", "#68"))]
    print()
    print("=" * 110)
    print(f"CONTROLS on the UNSEEN side — {label}  ·  {seg.n} days  ·  {SEEDS} seeds  ·  "
          f"split {split}")
    print("=" * 110)
    print(f"{'rule':38s} {'Calmar':>8s} {'permuted mean':>15s} {'p(perm≥real)':>13s}")
    for name, w in named:
        sw = slice_weights(w, s, panel.n)
        real = evaluate(seg, sw)["calmar"]
        perms = [evaluate(seg, spw.permuted_weights(sw, seg.books, sd))["calmar"]
                 for sd in range(SEEDS)]
        beat = sum(1 for c in perms if c >= real)
        print(f"{name:38s} {real:8.2f} {sum(perms)/len(perms):15.2f} "
              f"{(beat + 1) / (SEEDS + 1):13.3f}")
    print("-" * 110)
    print("Permutation re-attaches the frozen weights to the WRONG books: deployment, "
          "concentration and the\nbill survive exactly, only book identity dies. A frozen tilt "
          "that scores as well against its own\nscramble is holding an unusual constant "
          "portfolio, not a persistent one. Convention (beat+1)/(seeds+1),\nas #38/#40/#58/#65.")


def print_tilts(subset: Optional[Sequence[str]], label: str, split: str = TRAIN_END,
                k: int = REF_K, cap: Optional[float] = CONC_CAP) -> None:
    """The vectors themselves — a tilt nobody can read is a claim, not a proposal."""
    panel = dgo.Panel(subset)
    scores = erd.panel_scores(panel, "drift", LOOKBACK)
    s = split_index(panel, split)
    pub = spw.binary_weights(panel, scores, k, REF_M, cap)
    stt = tilt_from(pub, 0, s)
    full = tilt_from(pub, 0, panel.n)
    mir, _ = mirror_tilt(stt, cap)
    frozen = frozen_flags(panel, 0, s, k, panel.n)
    means_tr = dict(train_mean_ranking(panel, 0, s))
    means_te = dict(train_mean_ranking(panel, s, panel.n))
    print()
    print("=" * 110)
    print(f"THE FROZEN VECTORS — {label}  ·  split {split}  ·  TRAIN {s}d / TEST {panel.n - s}d")
    print("=" * 110)
    print(f"{'book':26s} {'TRAIN mean %/yr':>15s} {'TEST mean %/yr':>15s} {'#67 tilt':>9s} "
          f"{'mirror':>8s} {'hindsight':>10s} {'#68 out?':>9s}")
    for b in panel.books:
        print(f"{b:26s} {means_tr[b]*365*100:14.2f}% {means_te[b]*365*100:14.2f}% "
              f"{stt[b]*100:8.2f}% {mir[b]*100:7.2f}% {full[b]*100:9.2f}% "
              f"{'OUT' if frozen[b][0] else '-':>9s}")
    print("-" * 110)
    order_tr = [b for b, _ in train_mean_ranking(panel, 0, s)]
    order_te = [b for b, _ in train_mean_ranking(panel, s, panel.n)]
    moved = sum(1 for i, b in enumerate(order_tr) if order_te.index(b) != i)
    print(f"Rank persistence, worst→best: {len(order_tr) - moved}/{len(order_tr)} books keep their "
          f"exact TRAIN rank on TEST.\nThis is the mechanism the whole file rests on, printed as a "
          f"fact rather than assumed: a frozen tilt can\nonly transfer as far as the ordering it "
          f"was fitted to does.")


# ═══════════════════════════════ CLI ═══════════════════════════════
def main(argv: Sequence[str]) -> int:
    ap = argparse.ArgumentParser(description="Edge R&D #67 STT / #68 FFB — the standing tilt")
    ap.add_argument("--idea", type=int, choices=(67, 68), default=None,
                    help="drop the OTHER idea's rows from the main table (baselines always stay)")
    ap.add_argument("--splits", action="store_true", help="the four-split ladder, TEST side")
    ap.add_argument("--controls", action="store_true", help="permutation of the frozen vectors")
    ap.add_argument("--tilt", action="store_true", help="print the frozen vectors themselves")
    ap.add_argument("--split", default=TRAIN_END, help=f"fit/score split (default {TRAIN_END})")
    args = ap.parse_args(argv)

    panel = dgo.Panel()
    live = ets.live_books(panel)
    panels = [(None, "all 10 real books"), (live, f"{len(live)} live books (#54)")]
    everything = not (args.splits or args.controls or args.tilt)

    if everything or args.idea is not None:
        for subset, label in panels:
            report(subset, label, args.split, idea=args.idea)
    if everything or args.tilt:
        for subset, label in panels:
            print_tilts(subset, label, args.split)
    if everything or args.splits:
        for subset, label in panels:
            splits_ladder(subset, label)
    if everything or args.controls:
        for subset, label in panels:
            controls(subset, label, args.split)
    return 0


if __name__ == "__main__":                      # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
