#!/usr/bin/env python3
"""Edge R&D #69 CLS — Causal Liveness Selector: the one axis #68 left open, and its deflation.

WHY THIS FILE EXISTS
════════════════════
#68 FFB ended on a diagnosis sharper than its own idea:

    «средняя доходность НЕ ОТЛИЧАЕТ МЁРТВУЮ книгу от ПЛОХОЙ (#54): мёртвая ранжируется НИЖЕ
     живой carry-книги и вытесняет из списка ту единственную книгу, ради которой список
     имел смысл.»

That sentence contains an obvious repair, and the registry has never run it: rank the books for
demotion ONLY AMONG THE ONES THAT ARE STILL ALIVE, and treat a dark feed as a refusal (#54's
gate) instead of as a very low score. Two questions follow, and they are different questions:

  (A) IS THE REGISTRY'S OWN "SIX LIVE BOOKS" PANEL CAUSAL? Every table since #54 is printed twice
      — ten books and "six live" — and the six come from `ets.live_books`, whose density runs over
      the WHOLE sample, TEST days included. If a causal census (fit window only) would have named
      a different six, then every out-of-sample row on that panel has been carrying a universe
      chosen with hindsight, and the honest panel is the less honest one. Nobody has checked.

  (B) DOES THE REPAIR WORK? #69 LFF = freeze the causally-dark books (#54's gate) and, separately,
      freeze the bottom-k of the books that are ALIVE at the freeze date. Prediction from #68's own
      law, written down BEFORE the run: the repair should put `eth_directional` back into the
      freeze list at the splits where #68 lost it, and Calmar should follow the book, not the rule.

WHAT MAKES THIS DIFFERENT FROM #54 AND FROM #68
═══════════════════════════════════════════════
#54 measured the DARK GATE alone (freeze what does not print) and found it trades drawdown for
return out of sample. #68 measured the MEAN-RETURN SELECTOR alone (freeze bottom-k of everything).
Neither measured them composed, and composition is exactly where #68's failure lives: the gate
removes the dead books from the ranking, so the selector's k is finally spent on live ones.

That is why the dark gate is printed here as its own row (`CONTROL dark-only (#54)`): without it,
any advantage of LFF could be #54's gate wearing a new name, and the entry would be a rediscovery.

THE CONTROL THAT DECIDES THE VERDICT — AND IT IS NOT THE INVERSION
══════════════════════════════════════════════════════════════════
A freeze list has a size. LFF freezes `dead ∪ bottom-k(live)`, which on a holed panel is a LARGER
list than FFB's `bottom-k(all)`. So LFF differs from #68 in two ways at once — WHICH books and HOW
MANY — and #68 says in its own reservations that the ladder over k was never run. Therefore this
file runs the FULL k-LADDER of #68 and asks the deflating question directly:

    IS #69's FREEZE SET EQUAL, BOOK FOR BOOK, TO #68's SET AT SOME LARGER k?

If it is, the liveness census invents no selection at all — it is `k` in disguise, and the entry's
honest content is the ladder, not the census. That question is answered by set identity (exact,
not by comparing returns), so it cannot be argued with.

HONESTY / SCOPE
═══════════════
  • Evidence L0 — backtest over the research feed panel, NOT a live track. Segments are labelled
    [TRAIN] / [TEST]; nothing fitted on TRAIN is ever quoted as an out-of-sample number.
  • The panel is holed (#54: 4 of 10 books dark for ~80 % of the sample) and REGENERATED NIGHTLY
    (card `agent-aggressive-lab-books-are-regenerated`) — numbers reproduce only against the panel
    snapshot of the run date, which is why every test below runs on hand-built series instead.
  • The census threshold (density ≥ 0.5) is the registry's own from #54 and is NOT re-tuned here.
    The dispersion census beside it is printed as a DIAGNOSTIC and deliberately left without a
    threshold: on this panel the dispersion ladder has no gap to put one in, and a cut chosen
    after seeing which book it catches is a fitted parameter wearing a census's clothes.
  • k, M, L, the cap and the cost are inherited (#37/#39/#40/#10) and not re-tuned. The k-LADDER
    is printed whole — every rung, not the winning one.
  • Read-only. Writes nothing, imports no execution code, touches neither the live track nor
    `data/` nor RiskPolicy v1.0 nor the kill-switch. IS_ADVISORY = True, OUTSIDE_RISKPOLICY = True.
    Capital does not move. No agent is deployed by this file.

Usage:
    python3 scripts/edge_causal_liveness_selector.py             # everything
    python3 scripts/edge_causal_liveness_selector.py --census    # (A) causal vs hindsight census
    python3 scripts/edge_causal_liveness_selector.py --ladder    # (B) LFF vs #68 vs #54 vs #40
    python3 scripts/edge_causal_liveness_selector.py --identity  # the deflating k-identity scan
    python3 scripts/edge_causal_liveness_selector.py --controls  # permutation on the unseen side
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import statistics
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import edge_calm_fp_tax as cfpt                 # noqa: E402  (panel loader, perf, BP)
import edge_capital_recycling as ecr            # noqa: E402  (allocator, costs)
import edge_drift_gated_overlay as dgo          # noqa: E402  (Panel of #35/#36/#37)
import edge_event_time_scoring as ets           # noqa: E402  (SynthPanel + live/dead census of #54)
import edge_redundancy_demotion as erd          # noqa: E402  (criterion dispatcher of #44/#45)
import edge_score_proportional as spw           # noqa: E402  (#40's weights + the #38 controls)
import edge_static_tilt_transfer as stt         # noqa: E402  (#67/#68: segments, FFB, both bills)

IS_ADVISORY = True
OUTSIDE_RISKPOLICY = True

LOOKBACK = stt.LOOKBACK              # 60 — #37/#39/#40, NOT re-tuned here
TRAIN_END = stt.TRAIN_END            # "2025-06-30" — the registry's own split
REF_K = stt.REF_K                    # 2 — #40's reference k, so every row is like-for-like
REF_M = stt.REF_M                    # 20 — #40's published stickiness
CONC_CAP = stt.CONC_CAP              # 0.20 — the project's own per-name cap
SPLITS = stt.SPLITS                  # the four-split ladder of #67/#68
SEEDS = stt.SEEDS                    # 20 control seeds, as #38/#40/#58/#63/#65/#68
BP = cfpt.BP
EPS = ecr.EPS
PRINT_EPS = ets.PRINT_EPS            # what counts as "the feed printed something" (#54)
MIN_DENSITY = 0.5                    # #54's own liveness threshold — inherited, not re-tuned


# ═══════════════════════════════ (A) the census — causal and not ═══════════════════════════════
def density(panel, book: str, i0: int, i1: int) -> float:
    """Share of days in [i0, i1) on which this book's feed printed anything at all.

    Fail-CLOSED on a bad window: a density over no days is not 0.0, it is unanswerable, and
    returning a number there would let a book be declared dead by an empty question.
    """
    if not 0 <= i0 < i1 <= panel.n:
        raise ValueError(f"bad window [{i0}, {i1}) over {panel.n} days — refusing to judge liveness")
    if book not in panel.rets:
        raise KeyError(f"{book} is not in this panel")
    return sum(1 for x in panel.rets[book][i0:i1] if abs(x) > PRINT_EPS) / (i1 - i0)


def causal_live_books(panel, i0: int, i1: int, min_density: float = MIN_DENSITY) -> List[str]:
    """#54's census restricted to a window that ENDS BEFORE the days it will be used to trade.

    `ets.live_books` answers the same question over the whole sample, which is right for an audit
    of the panel and wrong for a rule: it knows in March which feeds will still be printing next
    December. The only difference here is the window — the threshold, the epsilon and the tie
    conventions are #54's, unchanged, so the two censuses can be compared as like for like.
    """
    if not 0.0 <= min_density <= 1.0:
        raise ValueError(f"min_density {min_density} is not a share")
    return sorted(b for b in panel.books if density(panel, b, i0, i1) >= min_density)


def census_lag(panel, min_density: float = MIN_DENSITY,
               min_window: int = LOOKBACK) -> Dict[str, dict]:
    """When would an EXPANDING-window census have first called each book dead — and how late?

    The registry's census is a share over everything seen so far, so a book that stops printing
    does not become "dead" on the day it goes quiet: it becomes dead when its accumulated share
    finally decays through the threshold. That delay is a property of the definition, not of the
    book, and it is the number an allocator would actually live with, so it is printed rather
    than assumed. `None` in `first_dead` means the census never reaches a verdict on this sample —
    which is itself an answer, and the honest one is "not measured", never "alive".

    The census is REFUSED before `min_window` days (the family's own 60-day warm-up): a share over
    three days is not a liveness measurement, and without this floor a book whose first day happens
    to be blank is "dead" on day one — a verdict about the calendar, not about the feed.

    A NEGATIVE lag is not a bug and is not suppressed: it means the census reached its final "dead"
    verdict while the feed was still printing occasionally, i.e. the book never cleared the
    threshold in the first place. That is the honest reading of a book that trickles.
    """
    if min_window < 1:
        raise ValueError("a census needs a window — refusing to judge liveness on nothing")
    out: Dict[str, dict] = {}
    for b in panel.books:
        r = panel.rets[b]
        prints = [i for i, x in enumerate(r) if abs(x) > PRINT_EPS]
        last = prints[-1] if prints else None
        first_dead = None
        run = 0
        for i in range(1, panel.n + 1):
            run += 1 if abs(r[i - 1]) > PRINT_EPS else 0
            if i < min_window:
                continue                 # not yet answerable — refusal, never a verdict
            if run / i < min_density:
                if first_dead is None:
                    first_dead = i - 1
            else:
                first_dead = None        # it climbed back out — the verdict was not final
        out[b] = {
            "prints": len(prints),
            "density_full": len(prints) / panel.n if panel.n else 0.0,
            "last_print_i": last,
            "last_print": panel.axis[last] if last is not None else None,
            "first_dead_i": first_dead,
            "first_dead": panel.axis[first_dead] if first_dead is not None else None,
            "lag_days": (first_dead - last) if (first_dead is not None and last is not None) else None,
        }
    return out


def dispersion_census(panel, i0: int, i1: int) -> Dict[str, dict]:
    """DIAGNOSTIC ONLY — the class of degeneracy that a density census cannot see.

    A book can print every single day and still carry no risk: `points_farm` accrues a literal
    constant. Density calls it maximally alive; a portfolio rule that demotes "the worst mean"
    will happily spend its k on it, and a rule that rewards calm (#45) will protect it for ever
    — #54 measured exactly that failure for DARK books and this is its sibling for CONSTANT ones.
    No threshold is offered here on purpose: on this panel the dispersion ladder has no gap like
    the 69.7 %/18.4 % one that justified #54's 0.5, and a cut placed after seeing which book it
    catches would be a fitted parameter, not a census.
    """
    if not 0 <= i0 < i1 <= panel.n:
        raise ValueError(f"bad window [{i0}, {i1}) over {panel.n} days — refusing to judge dispersion")
    out: Dict[str, dict] = {}
    for b in panel.books:
        seg = panel.rets[b][i0:i1]
        out[b] = {
            "stdev_bp": statistics.pstdev(seg) * BP if len(seg) > 1 else 0.0,
            "distinct": len(set(round(x, 12) for x in seg)),
            "mean_apy": sum(seg) / len(seg) * 365.0,
            "density": density(panel, b, i0, i1),
        }
    return out


# ═══════════════════════════ (B) the selector — #54's gate ∘ #68's ranking ═══════════════════════
def live_mean_ranking(panel, i0: int, i1: int,
                      min_density: float = MIN_DENSITY) -> List[Tuple[str, float]]:
    """Books ALIVE in the fit window, ordered worst → best by mean return over it. Ties by name.

    Identical to `stt.train_mean_ranking` except for who is allowed on the list. That is the whole
    idea of #69, and keeping the rest byte-identical is what makes the comparison with #68 a
    comparison of one thing.
    """
    live = causal_live_books(panel, i0, i1, min_density)
    if not live:
        raise ValueError("no live book in the fit window — refusing to rank a dark panel")
    means = {b: sum(panel.rets[b][i0:i1]) / (i1 - i0) for b in live}
    return sorted(means.items(), key=lambda kv: (kv[1], kv[0]))


def lff_freeze_set(panel, i0: int, i1: int, k: int = REF_K, invert: bool = False,
                   min_density: float = MIN_DENSITY, gate_dark: bool = True) -> Set[str]:
    """#69's freeze list: the causally-dark books (refusal, #54) PLUS the k worst LIVE books.

    `invert` takes the k BEST live books instead — the refuting control: if freezing the best is
    not worse, the TRAIN ranking of the live sub-panel carries no persistence and the whole idea
    is a shape. `gate_dark=False` isolates the other half (rank among the live, but keep the dark
    books invested) so the two ingredients can be read apart rather than credited to each other.

    Fail-CLOSED at the edges, on the LIVE count and not the book count: k at or above the number
    of live books would freeze the entire investable panel, which is a request for an all-cash
    book wearing a selector's name.
    """
    if k < 0:
        raise ValueError("k must be non-negative — refusing to un-demote books")
    order = live_mean_ranking(panel, i0, i1, min_density)
    if k >= len(order):
        raise ValueError(f"k={k} would freeze out all {len(order)} live books — not a selector")
    live = {b for b, _ in order}
    dark = {b for b in panel.books if b not in live} if gate_dark else set()
    chosen = {b for b, _ in (order[len(order) - k:] if invert else order[:k])} if k else set()
    return dark | chosen


def flags_from(panel, frozen: Set[str], n: int) -> Dict[str, List[bool]]:
    """A freeze set held for n days — the flags never move again, exactly as in #68."""
    unknown = frozen - set(panel.books)
    if unknown:
        raise KeyError(f"freezing books that are not on the panel: {sorted(unknown)}")
    return {b: [b in frozen] * n for b in panel.books}


def lff_weights(panel, i0: int, i1: int, k: int = REF_K, n: Optional[int] = None,
                cap: Optional[float] = CONC_CAP, invert: bool = False,
                min_density: float = MIN_DENSITY, gate_dark: bool = True
                ) -> Dict[str, List[float]]:
    """#69 — #40's own allocator over #69's freeze list. Same allocator, same cap, same k."""
    days = panel.n if n is None else n
    return ecr.alloc_recycle(panel.books, flags_from(panel, lff_freeze_set(
        panel, i0, i1, k, invert, min_density, gate_dark), days), days, cap=cap)


def dark_only_weights(panel, i0: int, i1: int, n: Optional[int] = None,
                      cap: Optional[float] = CONC_CAP,
                      min_density: float = MIN_DENSITY) -> Dict[str, List[float]]:
    """#54's causal dark gate ALONE — the row without which #69 could be a rediscovery of it."""
    days = panel.n if n is None else n
    return ecr.alloc_recycle(panel.books, flags_from(panel, lff_freeze_set(
        panel, i0, i1, 0, min_density=min_density), days), days, cap=cap)


# ═════════════════════ the deflating question: is #69 just #68 at a larger k? ═════════════════════
def ffb_freeze_set(panel, i0: int, i1: int, k: int, invert: bool = False) -> Set[str]:
    """#68's freeze list, read out of its own code path so the two sets are comparable as sets."""
    flags = stt.frozen_flags(panel, i0, i1, k, 1, invert)
    return {b for b in panel.books if flags[b][0]}


def identity_k(panel, i0: int, i1: int, k: int = REF_K,
               min_density: float = MIN_DENSITY) -> Optional[int]:
    """The k at which #68's set is EXACTLY #69's set, or None if no k reproduces it.

    Set identity, not a comparison of returns: if some k' makes the two lists the same books, then
    on this panel #69 selected nothing that #68 could not have selected by turning one dial it
    already had — and #68's own reservations record that this dial was never turned.
    """
    target = lff_freeze_set(panel, i0, i1, k, min_density=min_density)
    for kk in range(len(panel.books)):
        if ffb_freeze_set(panel, i0, i1, kk) == target:
            return kk
    return None


# ═══════════════════════════════════════ reporting ═══════════════════════════════════════
def _rows(panel, scores, split: str, k: int = REF_K, cap: Optional[float] = CONC_CAP
          ) -> Tuple[int, List[Tuple[str, Dict[str, List[float]]]]]:
    s = stt.split_index(panel, split)
    if s <= 0 or s >= panel.n:
        raise ValueError(f"split {split} leaves one side empty — refusing to fit or score on it")
    n, nb = panel.n, len(panel.books)
    ident = identity_k(panel, 0, s, k)
    return s, [
        ("raw equal weight", {b: [1.0 / nb] * n for b in panel.books}),
        (f"#40 XSD k={k} M={REF_M} [published]", spw.binary_weights(panel, scores, k, REF_M, cap)),
        ("#68 FFB frozen bottom-k of ALL", stt.ffb_weights(panel, 0, s, k, n, cap)),
        ("CONTROL dark-only gate (#54)", dark_only_weights(panel, 0, s, n, cap)),
        ("#69 LFF dark + bottom-k of LIVE", lff_weights(panel, 0, s, k, n, cap)),
        ("  CONTROL LFF invert (TOP-k live)", lff_weights(panel, 0, s, k, n, cap, invert=True)),
        ("  CONTROL rank-live, dark INVESTED", lff_weights(panel, 0, s, k, n, cap, gate_dark=False)),
        (f"  DEFLATION #68 at k={ident} [set-identical]" if ident is not None
         else "  DEFLATION #68 — no k reproduces #69's set",
         stt.ffb_weights(panel, 0, s, ident if ident is not None else k, n, cap)),
    ]


_COLS = (f"{'configuration':38s} {'APY':>8s} {'maxDD':>8s} {'Calmar':>7s} {'turnT':>7s} "
         f"{'turnI':>7s} {'netT':>8s} {'netI':>8s}")


def _print_rows(title: str, seg, rows, i0: int, i1: int) -> Dict[str, Dict[str, float]]:
    print()
    print("=" * 112)
    print(title)
    print("=" * 112)
    print(_COLS)
    out: Dict[str, Dict[str, float]] = {}
    for name, w in rows:
        m = stt.evaluate(seg, stt.slice_weights(w, i0, i1))
        out[name.strip()] = m
        print(f"{name:38s} {m['apy']*100:7.2f}% {m['maxdd']*100:7.2f}% {m['calmar']:7.2f} "
              f"{m['turnover_yr']:7.2f} {m['turnover_impl_yr']:7.2f} "
              f"{m['net_apy_after_cost']*100:7.2f}% {m['net_apy_after_impl']*100:7.2f}%")
    return out


def census_report(subset: Optional[Sequence[str]], label: str) -> None:
    """(A) — the audit of the registry's own panel. Causal census vs the hindsight one."""
    panel = dgo.Panel(subset)
    lagged = census_lag(panel)
    hind = set(ets.live_books(panel))
    print()
    print("=" * 112)
    print(f"(A) CENSUS — {label}  ·  {panel.n} days  ·  {panel.axis[0]} … {panel.axis[-1]}")
    print("=" * 112)
    print(f"{'book':22s} {'prints':>7s} {'dens':>6s} {'last print':>12s} "
          f"{'census says dead':>17s} {'lag d':>6s} {'hindsight':>10s}")
    for b in panel.books:
        c = lagged[b]
        print(f"{b:22s} {c['prints']:7d} {c['density_full']:6.3f} "
              f"{str(c['last_print']):>12s} {str(c['first_dead']):>17s} "
              f"{('—' if c['lag_days'] is None else str(c['lag_days'])):>6s} "
              f"{('LIVE' if b in hind else 'dead'):>10s}")
    print("-" * 112)
    print("`census says dead` is the FIRST day an expanding-window census (#54's own share ≥ 0.5) "
          "would have\nreached that verdict and never reverted; `lag d` is how long after the last "
          "print that took. The lag is a\nproperty of the DEFINITION — an accumulated share decays "
          "slowly — and it is the delay a curator lives with.")
    print()
    print(f"{'split':12s} {'trainDays':>10s} {'causal census (fit window only)':>34s}  verdict")
    for split in SPLITS:
        s = stt.split_index(panel, split)
        cau = set(causal_live_books(panel, 0, s))
        same = "IDENTICAL to the hindsight six" if cau == hind else \
               f"DIFFERS: causal-only {sorted(cau - hind)}, hindsight-only {sorted(hind - cau)}"
        print(f"{split:12s} {s:10d} {len(cau):>34d}  {same}")
    print("-" * 112)
    print("If these agree at every split, the registry's «6 живых» panel is NOT a hindsight "
          "universe and every\nout-of-sample row printed on it since #54 is clean on THAT axis. "
          "If they disagree anywhere, they are not.")
    print()
    s = stt.split_index(panel, TRAIN_END)
    disp = dispersion_census(panel, 0, s)
    print(f"DIAGNOSTIC — dispersion over TRAIN (≤{TRAIN_END}), the degeneracy density cannot see:")
    print(f"{'book':22s} {'stdev bp/d':>11s} {'distinct':>9s} {'mean %/yr':>10s} {'density':>8s}")
    for b in sorted(panel.books, key=lambda x: disp[x]["stdev_bp"]):
        d = disp[b]
        print(f"{b:22s} {d['stdev_bp']:11.2f} {d['distinct']:9d} {d['mean_apy']*100:9.2f}% "
              f"{d['density']:8.3f}")
    print("-" * 112)
    print("A book at the top of `density` and the bottom of `stdev` is an unsigned fixed-rate "
          "sleeve, not a\nstrategy book. NO threshold is proposed: there is no gap here to put "
          "one in, and a cut chosen after\nseeing which book it catches is a fitted parameter, "
          "not a census. Named, not ruled on.")


def report(subset: Optional[Sequence[str]], label: str, split: str = TRAIN_END,
           k: int = REF_K, cap: Optional[float] = CONC_CAP) -> Dict[str, Dict[str, float]]:
    """(B) — fit the freeze list on TRAIN, score it on TRAIN and on the unseen TEST."""
    panel = dgo.Panel(subset)
    scores = erd.panel_scores(panel, "drift", LOOKBACK)
    s, rows = _rows(panel, scores, split, k, cap)
    head = f"{label}  ·  {panel.n} days  ·  {len(panel.books)} books  ·  split {split}"
    stt._print_rows(f"#69 CLS — [FULL — the segment the registry prints] — {head}",
                    panel, rows, 0, panel.n)
    stt._print_rows(f"#69 CLS — [TRAIN, freeze list fitted HERE: {s} days] — {head}",
                    stt.segment(panel, 0, s), rows, 0, s)
    te = stt._print_rows(f"#69 CLS — [TEST, unseen: {panel.n - s} days] — {head}",
                         stt.segment(panel, s, panel.n), rows, s, panel.n)
    print("-" * 112)
    print(f"frozen by #68 (bottom-{k} of ALL) : {sorted(ffb_freeze_set(panel, 0, s, k))}")
    print(f"frozen by #69 (dark + bottom-{k} live): {sorted(lff_freeze_set(panel, 0, s, k))}")
    ident = identity_k(panel, 0, s, k)
    print("DEFLATION: " + ("no k reproduces #69's set — the census selects something #68 cannot"
                          if ident is None else
                          f"#69's set IS #68's set at k={ident} — the census selected nothing that "
                          f"#68's own dial could not"))
    for rule in ("#69 LFF dark + bottom-k of LIVE", "#68 FFB frozen bottom-k of ALL"):
        c = stt._capture(te, rule)
        print(f"CAPTURE on TEST · {rule:34s}: "
              + ("#40 has no excess over raw on this segment — ratio refused"
                 if c is None else f"{c*100:6.1f}% of #40's netI excess over raw"))
    return te


def ladder(subset: Optional[Sequence[str]], label: str, k: int = REF_K,
           cap: Optional[float] = CONC_CAP) -> None:
    """The four-split ladder for #69 — and the WHOLE k-ladder of #68 beside it.

    #68's own reservations say the k-ladder was never run («лестница по k НЕ прогонялась»). It is
    run here in full because #69 changes the SIZE of the freeze list as well as its membership,
    and a comparison against a single rung would credit the census with whatever the dial does.
    """
    panel = dgo.Panel(subset)
    scores = erd.panel_scores(panel, "drift", LOOKBACK)
    measured = []
    for split in SPLITS:
        s, rows = _rows(panel, scores, split, k, cap)
        seg = stt.segment(panel, s, panel.n)
        measured.append((split, s,
                         [stt.evaluate(seg, stt.slice_weights(w, s, panel.n)) for _, w in rows],
                         sorted(lff_freeze_set(panel, 0, s, k)), identity_k(panel, 0, s, k)))
    for key, unit in (("net_apy_after_impl", "netAPY after the IMPLEMENTATION bill (#49)"),
                      ("calmar", "Calmar")):
        pct = key != "calmar"
        print()
        print("=" * 112)
        print(f"(B) SPLIT LADDER (TEST side only, {unit}) — {label}")
        print("=" * 112)
        print(f"{'split':12s} {'testD':>6s} {'raw':>9s} {'#40':>9s} {'#68 FFB':>9s} "
              f"{'dark-only':>9s} {'#69 LFF':>9s} {'LFF-inv':>9s} {'rank-only':>9s} {'#68@k*':>9s}")
        for split, s, ms, _fr, _id in measured:
            cells = [f"{m[key]*100:8.2f}%" if pct else f"{m[key]:9.2f}" for m in ms]
            print(f"{split:12s} {panel.n - s:6d} " + " ".join(cells))
    print("-" * 112)
    print("The four TEST windows are NESTED (#67): the later split's window is a suffix of the "
          "earlier one, so four\nagreeing rows are four views of the same tail, not four "
          "confirmations. `#68@k*` is #68 run at the k whose\nfreeze set is IDENTICAL to #69's — "
          "where such a k exists, the two columns must agree to the last digit.")
    print("WHAT #69 FREEZES, AND WHETHER #68 COULD HAVE FROZEN IT:")
    for split, _s, _ms, frozen, ident in measured:
        print(f"  {split}: {', '.join(frozen)}"
              + (f"   ← identical to #68 at k={ident}" if ident is not None
                 else "   ← NO k of #68 reproduces this set"))
    print()
    print("=" * 112)
    print(f"THE FULL k-LADDER OF #68 (TEST side, netI% and Calmar) — {label}")
    print("=" * 112)
    ks = range(0, len(panel.books) - 1)
    print(f"{'split':12s}" + "".join(f"{'k=' + str(kk):>18s}" for kk in ks))
    for split in SPLITS:
        s = stt.split_index(panel, split)
        seg = stt.segment(panel, s, panel.n)
        cells = []
        for kk in ks:
            m = stt.evaluate(seg, stt.slice_weights(stt.ffb_weights(panel, 0, s, kk, panel.n, cap),
                                                    s, panel.n))
            cells.append(f"{m['net_apy_after_impl']*100:7.2f}% ({m['calmar']:5.1f})")
        print(f"{split:12s}" + "".join(f"{c:>18s}" for c in cells))
    print("-" * 112)
    print("A rung is not a proposal. The ladder is printed WHOLE so that «the good k» cannot be "
          "quoted without the\nsplits where the same k is the worst one — which is the only way "
          "to see whether k is a parameter or a\nname for something else.")


def controls(subset: Optional[Sequence[str]], label: str, split: str = TRAIN_END,
             k: int = REF_K, cap: Optional[float] = CONC_CAP) -> None:
    """#38's permutation control, on the unseen side, for #69's rows only."""
    panel = dgo.Panel(subset)
    scores = erd.panel_scores(panel, "drift", LOOKBACK)
    s, rows = _rows(panel, scores, split, k, cap)
    seg = stt.segment(panel, s, panel.n)
    print()
    print("=" * 112)
    print(f"CONTROLS on the UNSEEN side — {label}  ·  {seg.n} days  ·  {SEEDS} seeds  ·  {split}")
    print("=" * 112)
    print(f"{'rule':38s} {'Calmar':>8s} {'permuted mean':>15s} {'p(perm≥real)':>13s}")
    for name, w in rows:
        if not name.strip().startswith(("#68", "#69", "CONTROL dark")):
            continue
        sw = stt.slice_weights(w, s, panel.n)
        real = stt.evaluate(seg, sw)["calmar"]
        perms = [stt.evaluate(seg, spw.permuted_weights(sw, seg.books, sd))["calmar"]
                 for sd in range(SEEDS)]
        beat = sum(1 for c in perms if c >= real)
        print(f"{name:38s} {real:8.2f} {sum(perms)/len(perms):15.2f} "
              f"{(beat + 1) / (SEEDS + 1):13.3f}")
    print("-" * 112)
    print("Permutation re-attaches the frozen weights to the WRONG books: deployment, "
          "concentration and the bill\nsurvive exactly, only book identity dies. Convention "
          "(beat+1)/(seeds+1), as #38/#40/#58/#65/#68.")


# ═══════════════════════════════════════ CLI ═══════════════════════════════════════
def main(argv: Sequence[str]) -> int:
    ap = argparse.ArgumentParser(description="Edge R&D #69 CLS — causal liveness selector")
    ap.add_argument("--census", action="store_true", help="(A) causal vs hindsight census")
    ap.add_argument("--ladder", action="store_true", help="(B) split ladder + the full k-ladder")
    ap.add_argument("--identity", action="store_true", help="the deflating set-identity scan")
    ap.add_argument("--controls", action="store_true", help="permutation on the unseen side")
    ap.add_argument("--split", default=TRAIN_END, help=f"fit/score split (default {TRAIN_END})")
    args = ap.parse_args(argv)

    panel = dgo.Panel()
    live = ets.live_books(panel)
    panels = [(None, "all 10 real books"), (live, f"{len(live)} live books (#54)")]
    everything = not (args.census or args.ladder or args.identity or args.controls)

    if everything or args.census:
        census_report(None, "all 10 real books")
    if everything or args.identity:
        print()
        print("=" * 112)
        print("SET-IDENTITY SCAN — does some k of #68 reproduce #69's freeze list exactly?")
        print("=" * 112)
        print(f"{'panel':22s} {'split':12s} {'#69 set':>9s} {'identical #68 k':>16s}")
        for subset, label in panels:
            p = dgo.Panel(subset)
            for split in SPLITS:
                s = stt.split_index(p, split)
                ident = identity_k(p, 0, s, REF_K)
                print(f"{label:22s} {split:12s} "
                      f"{len(lff_freeze_set(p, 0, s, REF_K)):9d} "
                      f"{('—' if ident is None else 'k=' + str(ident)):>16s}")
        print("-" * 112)
        print("On the live-only panel the dark set is empty BY CONSTRUCTION, so #69 must collapse "
              "onto #68 at the same\nk there — that row is the identity check of this file's own "
              "arithmetic, not a finding.")
    if everything or not (args.census or args.identity or args.controls):
        for subset, label in panels:
            report(subset, label, args.split)
    if everything or args.ladder:
        for subset, label in panels:
            ladder(subset, label)
    if everything or args.controls:
        for subset, label in panels:
            controls(subset, label, args.split)
    return 0


if __name__ == "__main__":                      # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
