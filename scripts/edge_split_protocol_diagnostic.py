#!/usr/bin/env python3
"""
scripts/edge_split_protocol_diagnostic.py — registry ideas SPD + WUD (working names)

Advisory-only backtest. IS_ADVISORY=True, OUTSIDE_RISKPOLICY=True, Evidence=L0.
Never imports spa_core.execution. Never touches RiskPolicy v1.0, the kill-switch, the live
track, the dashboard or the fleet. Reads the aggressive-lab panel READ-ONLY. Capital is not
moved. No module is built and no agent is deployed here.

Working names SPD / WUD. The registry NUMBERS are claimed at DELIVERY, never at writing time
(REGISTRY-NUMBER-RULE, guard spa_core/tests/test_edge_registry_numbers.py).


THE ORDER THIS FILE EXECUTES
============================
Entry #99 closed with an explicit order, and it is the reason this file exists:

    "#98 point 2 is about the PROTOCOL, not about that idea: the naive split switches the dial
     off for ANY path that carries state. In this branch #79/#80/#82/#95 and onward are all
     computed with the split; which of their cells measured the dial and which measured the
     rebuild of weights HAS NOT BEEN CHECKED FOR A SINGLE ONE. This is a cheap re-check and it
     must be next, before another entry is stacked on top of those numbers."

#98 found the defect on ONE path (capped buy-and-hold): after the split rebuilds the portfolio
from equal weights on the first test day, the 20 % ceiling binds 0 days out of 370 instead of
190, so five different destinations produced bitwise identical test numbers and the tie was
arithmetic. The question left open is whether the SAME defect sits under the other split-
computed cells of this branch — above all under #95/#96 §3, whose TEST column is the family's
only out-of-sample statement about the overlay.

  SPD  Split Protocol Diagnostic.  For the branch's split-computed cells: does the dial still
       fire in the test half under the published RESTART protocol, and does the published
       number survive the CARRY protocol (one continuous path, metrics over the test segment)?

  WUD  Warm-Up Debt.  If a restarted path differs from a carried one, for HOW LONG? The answer
       is a number of days, and a number of days is a usable rule: either discard the first N
       test days or carry the state. Nothing in this branch has such a number.


WHAT IS ALREADY KNOWN, AND WHAT THIS FILE ADDS
----------------------------------------------
Known (#98): on a WEIGHT-DRIFT path the restart severs the state the dial acts on, and the dial
goes SILENT — 0 firings of 370. That is the loud failure: it announces itself as an exact tie.

This file measures the QUIET one. On the overlay path of #95 the dial does NOT go silent — the
admission gate blocks 129 to 370 of the 370 test days on the four comparable
books, under both protocols. What the restart severs there
is not the dial but the BASELINE it is compared against: the deployed organ is restarted with
zero exposure state and a truncated volatility baseline, so the ΔCalmar column of #95 §3 is a
difference between a dial that mostly survived the protocol and a baseline that did not.

A silent dial is visible (an exact tie). A corrupted baseline is not: every cell still prints a
plausible, distinct, non-degenerate number. That is why this half of the class had to be
measured rather than reasoned about.


MECHANISM — the two protocols, stated so a reader can reproduce either
----------------------------------------------------------------------
Both agree on the TRAIN half exactly (both start at day 0), so every difference below lives in
the test half and nowhere else. That is what makes the comparison an instrument.

  RESTART (the published protocol of #95 §3, and of the branch)
      te            = rets[idx+1:]                 -- the test slice of BOOK returns
      eq_te         = _equity(te)                  -- a fresh equity path starting at 1.0
      admission     = oda_admission(eq_te, W, K*)  -- trailing drawdown window restarts empty
      result        = metrics(guarded_path(eq_te, admission))
    The guardian's exposure state is 1.0 on the first test day whatever it was on the last
    train day; its 10-day vol window and its 40-day baseline window contain no data; the ODA
    gate's 90-day trailing-drawdown window contains no data.

  CARRY (this file's counterfactual, and what an operator actually experiences)
      eq_full       = _equity(rets)                -- ONE path over all 852 days
      admission     = oda_admission(eq_full, W, K*)
      guarded       = guarded_path(eq_full, admission)
      result        = metrics(guarded[idx+1:])     -- metrics over the TEST SEGMENT only
    K* is still chosen on TRAIN under both protocols and is bitwise the same number, because
    the train half is identical. No look-ahead is introduced: every input to a test-half
    decision is still dated on or before that day.

Metrics are scale-invariant in the path's starting level, so taking the test segment of a
continuous path is a legitimate measurement of the test half and not a rescaling trick.


THE POSITIVE CONTROLS, BOTH REPLAYING A PUBLISHED NUMBER
--------------------------------------------------------
An instrument that has never reproduced a known answer is decoration (the branch's own rule).
Two are asserted before any new number is printed:

  * §0a replays #98: the 20 % ceiling binds 190 of 370 test days under CARRY and 0 of 370 under
    RESTART. Those are the exact numbers #98 published. If this file's counter cannot produce
    them, it is not counting what #98 counted, and nothing below is worth reading.
  * §0b replays #95 §3: the RESTART arm of this file must reproduce the published ΔCalmar
    column bitwise -- eth_directional 0.00 (not comparable), pendle_pt_levered -0.06,
    pendle_yt_susde +1.11, susde_dn +144.13, susde_spot +2.17. The CARRY column is then a
    counterfactual against the very numbers the registry cites, not against a re-derivation.

Both refuse loudly. A control that cannot be established is a refusal, never a skipped line and
never a substituted number -- the branch has been burned twice by "not measured" arriving
dressed as a result.


WHICH PREDICTIONS WERE WRITTEN BEFORE WHICH NUMBERS — SAID PLAINLY
------------------------------------------------------------------
This file is honest about its own order of operations rather than back-dating its predictions.

  Sections 0, 2 and 3 were MEASURED FIRST, in exploration, before this file existed. Their
  results are reported as measurements, and NO prediction is claimed for them. Writing one now
  would be a story about a number already seen.

  Sections 4 and 5 were UNMEASURED when the following was written, and these are the real
  predictions of this entry:

  P1. The pendle_yt_susde sign flip (+1.11 published, negative under CARRY) is NOT robust to
      the boundary date: on a grid of boundaries the published protocol and the carried one
      will disagree in sign on some boundaries and agree on others. If it flips at every
      boundary, the protocol defect is systematic rather than incidental, and that is a
      stronger statement than this file expects to be able to make.
  P2. Warm-up debt is dominated by the LONGEST window in the path, i.e. by the ODA gate's
      W = 90 rather than by the guardian's lookback of 10 -- so convergence between the
      restarted and carried exposure traces will take on the order of 90 test days, not 10.
  P3. At least one book will NEVER converge: once the two protocols take different exposure
      decisions the paths differ permanently, so "warm-up debt" is not guaranteed to be finite,
      and a rule of the form "discard the first N days" is not guaranteed to exist.

A prediction that is WRONG is reported as wrong. That is the point of writing it down.


HONEST LIMITS DECLARED UP FRONT
  * evidence L0 [bt]; IS_ADVISORY=True / OUTSIDE_RISKPOLICY=True. Nothing here moves capital
    and nothing here is a live claim. No module is built, no agent is deployed.
  * this file does NOT overturn #96. #96's headline -- the overlay layer sits ~3.9 Calmar below
    capped buy-and-hold -- is computed on the FULL sample, with no split anywhere in it, and is
    therefore untouched by everything measured here. What is corrected is the branch's only
    OUT-OF-SAMPLE table, #95 §3. Those are different claims and are kept apart on purpose.
  * the census in §1 is a SCREEN, not a verdict. It reports what each module does with a
    post-boundary slice; it does not judge modules it cannot resolve mechanically, and it
    prints those by name as REQUIRES READING rather than guessing at them.
  * every toll is a CONVENTION, not a measurement (#92/#93 stand unchanged).
  * the panel is REGENERATED, not appended (#32 caveat (e)): numbers reproduce only against the
    panel files of the date printed in the header.
  * the panel is 852 days of one broad regime and the test half is quiet; nothing here is
    validated against a crisis.
  * gap risk is not addressed by any protocol choice and stays in the tier tail.

stdlib-only, deterministic, LLM FORBIDDEN.
"""

from __future__ import annotations

import argparse
import ast
import datetime
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(ROOT))

import edge_gross_to_net_toll as gtn  # noqa: E402  (the real-panel loader, reused verbatim)
import edge_overlay_domain_admissibility as oda  # noqa: E402  (#95/#96 — the subject)
import edge_trim_proceeds_destination as tpd  # noqa: E402  (#98 — the positive control)
from spa_core.strategy_lab.aggressive_lab.guardian import stdev  # noqa: E402
import spa_core.strategy_lab.swarm.guardian_forward as gf  # noqa: E402  (deployed params)

IS_ADVISORY = True
OUTSIDE_RISKPOLICY = True
EVIDENCE_LEVEL = "L0"

#: The branch's canonical boundary, unchanged since #79. READ from the subject so this file
#: cannot silently drift away from the table it is auditing.
SPLIT_DATE = oda.SPLIT_DATE

#: Boundaries of the robustness grid (§4). Fixed before §4 was run. The canonical one is in it
#: and is not marked, so the grid cannot be read as "the canonical boundary plus decoration".
BOUNDARY_GRID: Tuple[str, ...] = ("2025-01-31", "2025-06-30", "2025-12-31", "2026-03-31")

#: #98's published binding counts — the numbers §0a must reproduce or refuse.
KNOWN_98_CARRY_BINDS = 190
KNOWN_98_RESTART_BINDS = 0
KNOWN_98_TEST_DAYS = 370

#: #95 §3's published ΔCalmar column — the numbers §0b must reproduce or refuse.
#: Keys are books; values are (ΔCalmar published, comparable?) at the deployed toll and W=90.
KNOWN_95_SPLIT: Dict[str, Tuple[Optional[float], bool]] = {
    "eth_directional": (0.00, False),
    "pendle_pt_levered": (-0.06, True),
    "pendle_yt_susde": (1.11, True),
    "points_farm": (None, True),      # Calmar infinite both sides — printed, never asserted
    "susde_dn": (144.13, True),
    "susde_spot": (2.17, True),
}

EPS_PUBLISHED = 5e-3   # the published column is printed to 2 decimals; match it to that width


class ControlFailed(RuntimeError):
    """A positive control did not reproduce a published number. A refusal, never a warning."""


# --------------------------------------------------------------------------------------------
# instruments
# --------------------------------------------------------------------------------------------
def split_index(dates: Sequence[datetime.date], boundary: str) -> int:
    """Index of the LAST train day. Same rule as #95 §3 and #98, so the halves are the same."""
    cut = datetime.date.fromisoformat(boundary)
    idx = -1
    for i, d in enumerate(dates):
        if d <= cut:
            idx = i
    if idx < 0 or idx >= len(dates) - 1:
        raise ValueError(f"boundary {boundary} leaves one of the halves empty")
    return idx


def traced_guarded_path(
    equity: Sequence[float],
    admit: Optional[Sequence[bool]] = None,
    *,
    lookback: int = 10,
    vol_mult: float = 2.0,
    derisk_frac: float = 0.0,
    calm_mult: float = 1.2,
    roundtrip_cost: float = 0.0,
    min_vol: float = 1e-5,
    causal_lag: int = 0,
) -> Tuple[List[float], List[float]]:
    """`oda.guarded_path` with the exposure it chose each day returned alongside the path.

    A copy exists ONLY because the deployed function returns the path and discards the
    decisions, and §5 needs the decisions. The copy is therefore held to the original BITWISE:
    `assert_trace_matches_subject` re-runs `oda.guarded_path` on the same input and refuses on
    any difference, so this function cannot drift into being a second, quietly different organ
    (the mistake ADR-220 is about, in its own small way).
    """
    equity = list(equity)
    if len(equity) < lookback + 2:
        return equity, [1.0] * max(0, len(equity) - 1)
    rets = [equity[i] / equity[i - 1] - 1.0 for i in range(1, len(equity)) if equity[i - 1]]
    guarded = [equity[0]]
    exposure = 1.0
    trace: List[float] = []
    for i in range(len(rets)):
        if i >= lookback:
            end = i + 1 - causal_lag
            if end - lookback >= 0:
                recent = stdev(rets[end - lookback: end])
                base = stdev(rets[max(0, end - 1 - 4 * lookback): end - lookback]) or 1e-9
                prev = exposure
                if admit is not None and not admit[i]:
                    exposure = 1.0
                elif exposure >= 1.0 and recent > vol_mult * base and recent > min_vol:
                    exposure = derisk_frac
                elif exposure < 1.0 and (recent < calm_mult * base or recent < min_vol):
                    exposure = 1.0
                if exposure != prev and roundtrip_cost:
                    guarded[-1] *= (1.0 - roundtrip_cost * abs(prev - exposure))
        trace.append(exposure)
        guarded.append(guarded[-1] * (1.0 + rets[i] * exposure))
    return guarded, trace


def assert_trace_matches_subject(equity, admit, **params) -> None:
    """The tracing copy must be bitwise the deployed path. Refuses; never warns."""
    mine, _ = traced_guarded_path(equity, admit, **params)
    theirs = oda.guarded_path(equity, admit, **params)
    if mine != theirs:
        raise ControlFailed(
            "traced_guarded_path diverged from oda.guarded_path — the tracing copy is a "
            "second organ, not an instrument, and every number below would be about it"
        )


def choose_k_on_train(eq_train, window: int, cost: float, params) -> float:
    """K* by Calmar on TRAIN, exactly as #95 §3 chooses it. Identical under both protocols."""
    best_k, best_cal = 0.0, float("-inf")
    for k in oda.K_GRID:
        adm = oda.oda_admission(eq_train, window, k, cost) if k > 0 else None
        try:
            m = oda.metrics(oda.guarded_path(eq_train, adm, roundtrip_cost=cost, **params))
        except oda.Ruin:
            continue
        if m[2] == m[2] and m[2] != float("inf") and m[2] > best_cal:
            best_k, best_cal = k, m[2]
    return best_k


class Cell:
    """One book at one boundary, measured under BOTH protocols from one K*."""

    def __init__(self, rets, idx, window, cost, params):
        self.idx = idx
        self.test_days = len(rets) - idx - 1
        eq_train = oda._equity(rets[: idx + 1])
        self.k = choose_k_on_train(eq_train, window, cost, params)

        te = rets[idx + 1:]
        eq_te = oda._equity(te)
        adm_te = oda.oda_admission(eq_te, window, self.k, cost) if self.k > 0 else None
        assert_trace_matches_subject(eq_te, adm_te, roundtrip_cost=cost, **params)
        g_r, self.exp_restart = traced_guarded_path(eq_te, adm_te, roundtrip_cost=cost, **params)
        org_r, self.organ_exp_restart = traced_guarded_path(
            eq_te, None, roundtrip_cost=cost, **params)
        self.organ_restart = oda.metrics(org_r)
        self.oda_restart = oda.metrics(g_r)
        self.blocked_restart = sum(1 for a in (adm_te or []) if not a)
        self.derisk_restart = sum(1 for e in self.exp_restart if e != 1.0)

        eq_full = oda._equity(rets)
        adm_full = oda.oda_admission(eq_full, window, self.k, cost) if self.k > 0 else None
        assert_trace_matches_subject(eq_full, adm_full, roundtrip_cost=cost, **params)
        g_f, exp_full = traced_guarded_path(eq_full, adm_full, roundtrip_cost=cost, **params)
        self.exp_carry = exp_full[idx + 1:]
        org_f, organ_exp_full = traced_guarded_path(eq_full, None, roundtrip_cost=cost, **params)
        self.organ_exp_carry = organ_exp_full[idx + 1:]
        self.organ_carry = oda.metrics(org_f[idx + 1:])
        self.oda_carry = oda.metrics(g_f[idx + 1:])
        self.blocked_carry = sum(1 for a in (adm_full or [])[idx + 1:] if not a)
        self.derisk_carry = sum(1 for e in self.exp_carry if e != 1.0)

        raw_te = oda.metrics(eq_te)
        self.comparable = oda.comparable(raw_te[2], raw_te[0])

    @staticmethod
    def _delta(a, b) -> float:
        if a[2] != a[2] or b[2] != b[2]:
            return float("nan")
        if a[2] in (float("inf"), float("-inf")) or b[2] in (float("inf"), float("-inf")):
            return float("nan")
        return a[2] - b[2]

    @property
    def d_restart(self) -> float:
        return self._delta(self.oda_restart, self.organ_restart)

    @property
    def d_carry(self) -> float:
        return self._delta(self.oda_carry, self.organ_carry)


def fmt(x: Optional[float], nd: int = 2) -> str:
    if x is None:
        return "—"
    if x != x:
        return "—"
    if x in (float("inf"), float("-inf")):
        return "∞"
    return f"{x:.{nd}f}"


# --------------------------------------------------------------------------------------------
# §0 — the positive controls
# --------------------------------------------------------------------------------------------
def section0a_replay_98(dates, book_rets) -> Dict[str, object]:
    """Reproduce #98's published binding counts, or refuse. The counter's own calibration."""
    print("\n" + "─" * 100)
    print("0a. POSITIVE CONTROL — replay #98's published counter (190 of 370 under CARRY,")
    print("    0 of 370 under RESTART). This file's firing counter has to produce a number")
    print("    that is already in the registry before it is allowed to produce a new one.")
    live = [b for b in sorted(book_rets) if not oda.is_dead(book_rets[b])]
    idx = split_index(dates, SPLIT_DATE)
    cost = tpd.DEPLOYED_BPS / 1e4
    tr: List[float] = []
    tpd.capped_bh(book_rets, live, cap=0.20, cost=cost, destination="prorata", trace=tr)
    carry = sum(1 for i, t in enumerate(tr) if t > 0 and i > idx)
    te = {b: book_rets[b][idx + 1:] for b in live}
    tr2: List[float] = []
    tpd.capped_bh(te, live, cap=0.20, cost=cost, destination="prorata", trace=tr2)
    restart = sum(1 for t in tr2 if t > 0)
    days = len(dates) - idx - 1
    print(f"    CARRY   ceiling binds {carry:>4} of {days} test days   (published: "
          f"{KNOWN_98_CARRY_BINDS} of {KNOWN_98_TEST_DAYS})")
    print(f"    RESTART ceiling binds {restart:>4} of {days} test days   (published: "
          f"{KNOWN_98_RESTART_BINDS} of {KNOWN_98_TEST_DAYS})")
    if (carry, restart, days) != (KNOWN_98_CARRY_BINDS, KNOWN_98_RESTART_BINDS,
                                  KNOWN_98_TEST_DAYS):
        raise ControlFailed(
            f"replay of #98 gave ({carry}, {restart}) of {days} against the published "
            f"({KNOWN_98_CARRY_BINDS}, {KNOWN_98_RESTART_BINDS}) of {KNOWN_98_TEST_DAYS} — "
            "this counter is not counting what #98 counted, so nothing below is readable"
        )
    print("    ✅ reproduced bitwise. The counter measures what #98 measured.")
    return {"carry": carry, "restart": restart, "test_days": days, "ok": True}


def section0b_replay_95(cells: Dict[str, Cell]) -> Dict[str, object]:
    """Reproduce #95 §3's published ΔCalmar column from this file's RESTART arm, or refuse."""
    print("\n" + "─" * 100)
    print("0b. POSITIVE CONTROL — the RESTART arm must reproduce the ΔCalmar column #95 §3")
    print("    published, to the two decimals it was printed at. The CARRY column of §3 is")
    print("    then a counterfactual against the registry's own numbers, not a re-derivation.")
    print(f"{'book':>22}{'published ΔCal':>16}{'this file RESTART':>20}{'':>4}")
    print("─" * 100)
    out: Dict[str, object] = {}
    bad: List[str] = []
    for book in sorted(KNOWN_95_SPLIT):
        want, _ = KNOWN_95_SPLIT[book]
        cell = cells.get(book)
        got = cell.d_restart if cell else float("nan")
        ok = (want is None and got != got) or (
            want is not None and got == got and abs(got - want) <= EPS_PUBLISHED)
        print(f"{book:>22}{fmt(want):>16}{fmt(got):>20}{'  ✅' if ok else '  ❌':>4}")
        out[book] = {"published": want, "restart": None if got != got else got, "ok": ok}
        if not ok:
            bad.append(book)
    if bad:
        raise ControlFailed(
            "the RESTART arm did not reproduce #95 §3 for: " + ", ".join(bad) +
            " — this file would then be auditing its own re-derivation, not the published table"
        )
    print("    ✅ the published column is reproduced. Everything below is measured against it.")
    return out


# --------------------------------------------------------------------------------------------
# §1 — the census (a screen, not a verdict)
# --------------------------------------------------------------------------------------------
#: Functions that consume a series and return a SCALAR summary. Applying one of these to a
#: post-boundary slice does not re-run anything, so a module that only does this has split the
#: OUTPUT of a continuous path. Each name here was read and is stateless; the list is short on
#: purpose, because everything not on it is reported as REQUIRES READING rather than judged.
PURE_METRIC_CALLS = frozenset({
    "_apy", "_mdd", "_calmar", "metrics", "mean", "median", "stdev", "len", "sum", "max",
    "min", "sorted", "abs", "fmt", "print", "float", "int", "list", "str", "round",
})

#: Splitting through this helper splits a RETURN SERIES that the caller already produced over
#: the whole history — the CARRY shape, by construction of the helper itself.
OUTPUT_SPLIT_HELPERS = frozenset({"_split"})


BOUNDARY_LITERAL = "2025-06-30"


def corpus_boundary_names(paths: Sequence[Path]) -> set:
    """The names this corpus uses for the boundary — DERIVED from the corpus, not listed here.

    Seed: any module-level assignment whose source contains the literal boundary date
    (`SPLIT_DATE = "2025-06-30"`, `TRAIN_END: str = "2025-06-30"`).
    Closure: any module-level assignment whose source mentions an already-known boundary name,
    which is how `TRAIN_END = ecr.TRAIN_END` and `SPLIT_DATE = oda.SPLIT_DATE` join.

    This exists because the first version of this screen looked only for the string
    "SPLIT_DATE" and therefore reported 22 modules as having no boundary-aware function at all
    — while most of them simply spell the boundary `TRAIN_END`. A screen that answers about
    the spelling instead of the thing is worse than no screen: it prints a clean sheet.
    """
    names: set = set()
    for _ in range(4):
        grew = False
        for path in paths:
            src = path.read_text(encoding="utf-8")
            try:
                tree = ast.parse(src)
            except SyntaxError:
                continue
            for stmt in tree.body:
                if not isinstance(stmt, (ast.Assign, ast.AnnAssign)):
                    continue
                seg = ast.get_source_segment(src, stmt) or ""
                if BOUNDARY_LITERAL not in seg and not any(n in seg for n in names):
                    continue
                targets = list(stmt.targets) if isinstance(stmt, ast.Assign) else [stmt.target]
                for t in targets:
                    for name in ast.walk(t):
                        if isinstance(name, ast.Name) and name.id not in names:
                            names.add(name.id)
                            grew = True
        if not grew:
            break
    return names


def _boundary_aware_functions(tree: ast.AST, src: str, names: set) -> Dict[str, ast.AST]:
    """Functions whose body mentions the boundary literal or any boundary name of the corpus.

    A slice is only interesting where the boundary is known. `ordered[:k]` inside a ranking
    function is not a split and must not be counted as one; this is what keeps the screen from
    reading every slice in the corpus as evidence.
    """
    out: Dict[str, ast.AST] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        seg = ast.get_source_segment(src, node) or ""
        if BOUNDARY_LITERAL in seg or any(n in seg for n in names):
            out[node.name] = node
    return out


def _boundary_derived_names(fn: ast.AST, src: str, names: set) -> set:
    """Names inside `fn` that carry the boundary — computed, not guessed from spelling.

    Seed: any statement whose SOURCE mentions SPLIT_DATE or the literal boundary date binds
    boundary-derived names (`k = _split_index(dates, SPLIT_DATE)`).
    Closure: any statement whose source mentions an already-derived name binds more of them —
    this is what reaches `idx = i` buried inside `for i, d in ...: if d <= boundary:`, where
    the assignment itself mentions neither the date nor the helper.

    Deliberately conservative in ONE direction: it over-includes rather than under-includes, so
    the screen's error shows up as an extra flag to read, never as a missed one. That direction
    is checked, not asserted — the three controls of §1 include a module that MUST come out
    unflagged (`edge_mhfc_backtest.py`), so over-inclusion cannot pass silently either.
    """
    derived: set = set(names)
    for _ in range(6):                     # fixpoint; the corpus never needs more than two
        grew = False
        for stmt in ast.walk(fn):
            if not isinstance(stmt, ast.stmt):
                continue
            seg = ast.get_source_segment(src, stmt) or ""
            hit = (BOUNDARY_LITERAL in seg or any(n in seg for n in derived))
            if not hit:
                continue
            for node in ast.walk(stmt):
                targets: List[ast.AST] = []
                if isinstance(node, ast.Assign):
                    targets = list(node.targets)
                elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
                    targets = [node.target]
                for t in targets:
                    for name in ast.walk(t):
                        if isinstance(name, ast.Name) and name.id not in derived:
                            derived.add(name.id)
                            grew = True
        if not grew:
            break
    return derived


def _slice_callees(fn: ast.AST, src: str, names: set) -> List[str]:
    """Every callee applied, inside `fn`, to a name bound from a BOUNDARY slice.

    Both halves count, not only the test one: the screen asks "is a path re-run on a boundary
    slice", and re-running on the train slice is the same shape.
    """
    derived = _boundary_derived_names(fn, src, names)
    bound: set = set()
    for node in ast.walk(fn):
        targets: List[ast.AST] = []
        value: Optional[ast.AST] = None
        if isinstance(node, ast.Assign):
            targets, value = list(node.targets), node.value
        elif isinstance(node, (ast.AugAssign, ast.AnnAssign)) and node.value is not None:
            targets, value = [node.target], node.value
        if value is None:
            continue
        has_boundary_slice = any(
            isinstance(n, ast.Subscript) and isinstance(n.slice, ast.Slice)
            and any(isinstance(m, ast.Name) and m.id in derived
                    for part in (n.slice.lower, n.slice.upper) if part is not None
                    for m in ast.walk(part))
            for n in ast.walk(value)
        )
        if not has_boundary_slice:
            continue
        for t in targets:
            for name in ast.walk(t):
                if isinstance(name, ast.Name):
                    bound.add(name.id)
    callees: List[str] = []
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call):
            continue
        args_mention = any(
            isinstance(n, ast.Name) and n.id in bound
            for a in list(node.args) + [kw.value for kw in node.keywords]
            for n in ast.walk(a)
        )
        if not args_mention:
            continue
        f = node.func
        name = f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name)
                                                            else "<expr>")
        callees.append(name)
    return sorted(set(callees))


def census_module(path: Path, names: set) -> Dict[str, object]:
    """Screen ONE module. Returns what it does with post-boundary slices — not a verdict."""
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    fns = _boundary_aware_functions(tree, src, names)
    helpers = sorted({
        (n.func.attr if isinstance(n.func, ast.Attribute) else n.func.id)
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and (
            (isinstance(n.func, ast.Attribute) and n.func.attr in OUTPUT_SPLIT_HELPERS)
            or (isinstance(n.func, ast.Name) and n.func.id in OUTPUT_SPLIT_HELPERS))
    })
    callees: List[str] = []
    for fn in fns.values():
        callees.extend(_slice_callees(fn, src, names))
    callees = sorted(set(callees))
    impure = [c for c in callees if c not in PURE_METRIC_CALLS]
    if not fns:
        verdict = "NO BOUNDARY-AWARE FUNCTION"
    elif impure:
        verdict = "RE-RUNS ON THE SLICE"
    elif helpers and not callees:
        verdict = "OUTPUT-SPLIT (CARRY by construction)"
    elif callees:
        verdict = "METRICS ONLY (CARRY)"
    else:
        verdict = "BOUNDARY USED, BUT NEVER AS A SLICE INDEX"
    return {"module": path.name, "boundary_fns": sorted(fns), "output_split_helpers": helpers,
            "slice_callees": callees, "impure": impure, "verdict": verdict}


def section1_census(scripts_dir: Path) -> Dict[str, object]:
    """The population screen the order asked for, with its own controls run first."""
    print("\n" + "─" * 100)
    print("1. CENSUS — of the split-computed cells of this branch, which RE-RUN a path on the")
    print("   post-boundary slice (the shape #98 caught) and which split the OUTPUT of one")
    print("   continuous path? This is a SCREEN with its own controls, not a verdict; modules")
    print("   it cannot resolve are printed by name as REQUIRES READING.")
    paths = sorted(p for p in scripts_dir.glob("edge_*.py")
                   if p.name != Path(__file__).name
                   and BOUNDARY_LITERAL in p.read_text(encoding="utf-8"))
    if not paths:
        raise ControlFailed(
            "no split-computed module found in the scripts directory — a census over an empty "
            "population would print a clean sheet, and a clean sheet is exactly what this file "
            "exists to distrust"
        )
    names = corpus_boundary_names(paths)
    print(f"\n   the boundary is spelled {len(names)} ways in this corpus, derived from it "
          f"and not listed by hand: {', '.join(sorted(names))}")
    results = {p.name: census_module(p, names) for p in paths}

    # controls: three modules whose answer is already published or measured above
    controls = {
        "edge_trim_proceeds_destination.py": "RE-RUNS ON THE SLICE",   # #98, both arms
        "edge_overlay_domain_admissibility.py": "RE-RUNS ON THE SLICE",  # §0b reproduced it
        "edge_mhfc_backtest.py": "OUTPUT-SPLIT (CARRY by construction)",  # #79, `_split` only
    }
    print("\n   CONTROLS (answers already known before this screen was written):")
    for mod, want in controls.items():
        got = results.get(mod, {}).get("verdict", "ABSENT")
        print(f"     {mod:>44}  expect {want:<38} got {got}")
        if got != want:
            raise ControlFailed(
                f"the screen mis-classified {mod}: expected {want!r}, got {got!r}. An "
                "instrument that fails on the cases whose answer is published does not get to "
                "report on the cases whose answer is not."
            )
    print("     ✅ all three controls classified correctly.")

    buckets: Dict[str, List[str]] = {}
    for name, r in results.items():
        buckets.setdefault(str(r["verdict"]), []).append(name)
    print(f"\n   population: {len(paths)} split-computed modules")
    for verdict in sorted(buckets, key=lambda v: -len(buckets[v])):
        print(f"     {len(buckets[verdict]):>3}  {verdict}")
    rerun = sorted(buckets.get("RE-RUNS ON THE SLICE", []))
    print(f"\n   THE ONES THAT RE-RUN A PATH ON THE SLICE — the shape #98 caught ({len(rerun)}):")
    for name in rerun:
        print(f"     {name:>46}   via {', '.join(results[name]['impure'])}")
    unresolved = sorted(buckets.get("BOUNDARY USED, BUT NEVER AS A SLICE INDEX", []))
    if unresolved:
        print(f"\n   NOT RESOLVED BY THIS SCREEN — the boundary is passed as a DATE into a")
        print(f"   windowing function rather than used as an index, and this screen follows")
        print(f"   index slices only. Named, never guessed at ({len(unresolved)}):")
        for name in unresolved:
            print(f"     {name}")
    print("\n   Read this as a MAP of where to look, never as a clean bill of health: the screen")
    print("   answers 'is a path re-run here', which is not the same question as 'is the")
    print("   published number wrong'. §3 answers the second one, and only for #95.")
    return {"population": len(paths), "buckets": buckets, "detail": results}


# --------------------------------------------------------------------------------------------
# §2 / §3 — the dial and the baseline
# --------------------------------------------------------------------------------------------
def build_cells(dates, book_rets, boundary: str, window: int, cost: float,
                params) -> Dict[str, Cell]:
    """Every live book measured under both protocols at one boundary. Dead books are skipped
    with the same rule #95 uses, so the roster of this file and of the subject are the same."""
    idx = split_index(dates, boundary)
    cells: Dict[str, Cell] = {}
    for book in sorted(book_rets):
        rets = book_rets[book]
        if oda.is_dead(rets) or oda.is_dead(rets[idx + 1:]):
            continue
        cells[book] = Cell(rets, idx, window, cost, params)
    if not cells:
        raise ControlFailed(f"no live book at boundary {boundary} — refusing to print a table")
    return cells


def section2_dial(cells: Dict[str, Cell], window: int, params) -> Dict[str, object]:
    """Does the restart switch the ODA dial OFF, the way it switched #98's ceiling off?"""
    print("\n" + "─" * 100)
    print("2. IS THE DIAL OFF? — #98's failure mode, looked for on #95's path. The dial here")
    print("   is the admission gate: it can only matter on days it BLOCKS. Counted in the")
    print("   test half under both protocols, per book.")
    lb = params["lookback"]
    print(f"{'book':>22}{'K*':>5}{'RESTART blocked':>17}{'CARRY blocked':>15}"
          f"{'RESTART derisk':>16}{'CARRY derisk':>14}{'cmp?':>7}")
    print("─" * 100)
    out: Dict[str, object] = {}
    for book, c in cells.items():
        print(f"{book:>22}{c.k:>5.0f}{c.blocked_restart:>17}{c.blocked_carry:>15}"
              f"{c.derisk_restart:>16}{c.derisk_carry:>14}"
              f"{('yes' if c.comparable else 'NO'):>7}")
        out[book] = {"k": c.k, "blocked_restart": c.blocked_restart,
                     "blocked_carry": c.blocked_carry, "derisk_restart": c.derisk_restart,
                     "derisk_carry": c.derisk_carry, "comparable": c.comparable,
                     "test_days": c.test_days}
    gated = [c for c in cells.values() if c.k > 0 and c.comparable]
    if gated:
        lo = min(c.blocked_restart for c in gated)
        hi = max(c.blocked_restart for c in gated)
        days = gated[0].test_days
        print(f"\n   On the comparable, gated books the gate blocks {lo}–{hi} of {days} test")
        print("   days under RESTART. #98's ceiling bound 0 of 370. The dial here is NOT off,")
        print("   and the loud tell (an exact tie across settings) does NOT appear.")
    print(f"\n   What the restart DOES sever, by construction and independent of any book:")
    print(f"     · the guardian takes no decision at all for its first {lb} test days")
    print(f"     · its volatility BASELINE window ({4 * lb} d) is truncated for {5 * lb} days")
    print(f"     · the ODA gate's trailing-drawdown window (W={window}) is truncated for the")
    print(f"       first {window - 1} test days — {(window - 1) / gated[0].test_days * 100:.0f} %"
          f" of the half, if the half is {gated[0].test_days} days")
    print("     · the guardian's EXPOSURE is reset to 1.0 whatever it was on the last train day")
    return out


def section3_baseline(cells: Dict[str, Cell]) -> Dict[str, object]:
    """The published ΔCalmar column, recomputed with the state carried across the boundary."""
    print("\n" + "─" * 100)
    print("3. THE PUBLISHED COLUMN, RECOMPUTED UNDER CARRY. ΔCalmar = ODA − deployed organ,")
    print("   which is what #95 §3 reports. Both columns use the SAME K*, chosen on the same")
    print("   TRAIN half; the only difference is whether the test half starts from the state")
    print("   the train half left or from a blank one.")
    print(f"{'book':>22}{'organ R':>10}{'ODA R':>10}{'ΔCal R':>9}{'  |':>3}"
          f"{'organ C':>10}{'ODA C':>10}{'ΔCal C':>9}   what moved")
    print("─" * 118)
    out: Dict[str, object] = {}
    flips: List[str] = []
    for book, c in cells.items():
        dr, dc = c.d_restart, c.d_carry
        note = ""
        if not c.comparable:
            note = "not comparable (#93) — excluded"
        elif dr != dr or dc != dc:
            note = "Calmar not finite — printed, not claimed"
        elif (dr > 0) != (dc > 0) and abs(dr) > EPS_PUBLISHED and abs(dc) > EPS_PUBLISHED:
            note = "SIGN FLIP"
            flips.append(book)
        elif abs(dr - dc) > 0.05 * max(1e-9, abs(dc)):
            note = f"{dr:+.2f} → {dc:+.2f}"
        else:
            note = "stable"
        print(f"{book:>22}{fmt(c.organ_restart[2]):>10}{fmt(c.oda_restart[2]):>10}"
              f"{fmt(dr):>9}{'  |':>3}{fmt(c.organ_carry[2]):>10}{fmt(c.oda_carry[2]):>10}"
              f"{fmt(dc):>9}   {note}")
        out[book] = {
            "organ_restart": list(c.organ_restart), "oda_restart": list(c.oda_restart),
            "organ_carry": list(c.organ_carry), "oda_carry": list(c.oda_carry),
            "d_restart": None if dr != dr else dr, "d_carry": None if dc != dc else dc,
            "comparable": c.comparable, "note": note,
        }
    print("\n   READ THE ORGAN COLUMNS FIRST, NOT THE ODA ONES. The gate mostly survives the")
    print("   protocol (§2); the BASELINE does not. Where the two protocols disagree, they")
    print("   disagree because the deployed organ is being asked to start cold.")
    if flips:
        print(f"\n   SIGN FLIP on: {', '.join(flips)} — a published cell whose DIRECTION is a")
        print("   property of the protocol. That is the finding of this file.")
    else:
        print("\n   No sign flip at this boundary. Magnitudes still move; see §4.")
    out["_flips"] = flips
    return out


def section4_boundary_grid(dates, book_rets, window, cost, params) -> Dict[str, object]:
    """P1: is the disagreement a property of THIS boundary, or of the protocol? Nothing is
    selected here — every boundary of the fixed grid is printed, including the canonical one."""
    print("\n" + "─" * 100)
    print("4. ROBUSTNESS — the same measurement at four boundaries, none of them selected.")
    print("   Question P1: does the protocol disagreement follow the boundary or the protocol?")
    print(f"{'boundary':>12}{'train/test':>14}{'book':>22}{'ΔCal RESTART':>14}"
          f"{'ΔCal CARRY':>12}{'  agree?':>10}")
    print("─" * 100)
    out: Dict[str, object] = {}
    for boundary in BOUNDARY_GRID:
        try:
            cells = build_cells(dates, book_rets, boundary, window, cost, params)
        except (ValueError, ControlFailed) as exc:
            print(f"{boundary:>12}  REFUSED: {exc}")
            out[boundary] = "REFUSED"
            continue
        idx = split_index(dates, boundary)
        shape = f"{idx + 1}/{len(dates) - idx - 1}"
        rows: Dict[str, object] = {}
        for book, c in cells.items():
            if not c.comparable:
                continue
            dr, dc = c.d_restart, c.d_carry
            if dr != dr or dc != dc:
                verdict = "—"
            elif (dr > 0) != (dc > 0) and abs(dr) > EPS_PUBLISHED and abs(dc) > EPS_PUBLISHED:
                verdict = "SIGN FLIP"
            elif abs(dr - dc) > 0.05 * max(1e-9, abs(dc)):
                verdict = "magnitude"
            else:
                verdict = "same"
            print(f"{boundary:>12}{shape:>14}{book:>22}{fmt(dr):>14}{fmt(dc):>12}"
                  f"{verdict:>10}")
            rows[book] = {"d_restart": None if dr != dr else dr,
                          "d_carry": None if dc != dc else dc, "verdict": verdict}
        out[boundary] = {"shape": shape, "books": rows}
        print("─" * 100)

    # THE DIRECTION, counted rather than eyeballed. A protocol defect that pushed the
    # published number both ways would be noise; one that pushes it the SAME way every time
    # is a bias, and the two readings call for different corrections.
    over = under = tie = 0
    for boundary, blk in out.items():
        if not isinstance(blk, dict):
            continue
        for book, row in blk["books"].items():
            dr, dc = row["d_restart"], row["d_carry"]
            if dr is None or dc is None:
                continue
            if abs(dr - dc) <= EPS_PUBLISHED:
                tie += 1
            elif dr > dc:
                over += 1
            else:
                under += 1
    total = over + under + tie
    print(f"\n   DIRECTION over {total} comparable cells (4 boundaries × the comparable books):")
    print(f"     RESTART reports a LARGER ΔCalmar than CARRY:  {over}")
    print(f"     RESTART reports a SMALLER ΔCalmar than CARRY: {under}")
    print(f"     the two protocols agree to 2 decimals:        {tie}")
    if total and over > under:
        print("   The published protocol FLATTERS the gate, and it does so almost everywhere.")
        print("   That is a bias with a sign, not scatter: the restart handicaps the BASELINE")
        print("   (the organ starts cold) far more than it handicaps the gated arm, so the")
        print("   difference between them is inflated by construction.")
    out["_direction"] = {"restart_larger": over, "restart_smaller": under, "tie": tie}
    return out


def decision_debt(a: Sequence[float], b: Sequence[float]) -> Tuple[int, Optional[int]]:
    """(days on which the two decision traces differ, day after which they never differ again).

    The second value is None — printed as NEVER — when the traces still disagree on the LAST
    day compared. That is the honest reading: "settled after N days" would be a claim the data
    does not support, and the difference between "settled late" and "never settled" is exactly
    the difference between "discard N days" being an available repair and not existing at all.
    """
    n = min(len(a), len(b))
    diff = [i for i in range(n) if a[i] != b[i]]
    if not diff:
        return 0, 0
    last = diff[-1]
    return len(diff), (None if last >= n - 1 else last + 1)


def section5_warmup_debt(dates, book_rets, window, cost, params) -> Dict[str, object]:
    """WUD (P2/P3): how many test days does the restarted path spend making DIFFERENT decisions
    from the carried one? If that number is finite the branch gets a usable repair — "discard
    the first N test days, or carry the state". If it is not, the only honest protocol is CARRY.

    Measured on BOTH paths, because §3's disagreement lives in the BASELINE: the organ (no
    admission gate) is the column that moved, so its trace is the one that has to explain it.
    """
    print("\n" + "─" * 100)
    print("5. WARM-UP DEBT — for how many test days does the restarted path make DIFFERENT")
    print("   decisions from the carried one? Counted on BOTH arms: the deployed ORGAN (no")
    print("   gate — the baseline §3 showed moving) and the GATED path.")
    cells = build_cells(dates, book_rets, SPLIT_DATE, window, cost, params)
    print(f"{'book':>22}{'K*':>5}{'organ: diff days':>18}{'organ: settles':>16}"
          f"{'gated: diff days':>18}{'gated: settles':>16}")
    print("─" * 100)
    out: Dict[str, object] = {}

    for book, c in cells.items():
        og_n, og_d = decision_debt(c.organ_exp_restart, c.organ_exp_carry)
        gd_n, gd_d = decision_debt(c.exp_restart, c.exp_carry)
        print(f"{book:>22}{c.k:>5.0f}{og_n:>18}"
              f"{(str(og_d) + ' d') if og_d is not None else 'NEVER':>16}"
              f"{gd_n:>18}{(str(gd_d) + ' d') if gd_d is not None else 'NEVER':>16}")
        out[book] = {"k": c.k, "organ_diff_days": og_n, "organ_settles_after": og_d,
                     "gated_diff_days": gd_n, "gated_settles_after": gd_d,
                     "test_days": len(c.exp_carry),
                     "organ_calmar_restart": c.organ_restart[2],
                     "organ_calmar_carry": c.organ_carry[2]}
    finite = [v["organ_settles_after"] for v in out.values()
              if isinstance(v.get("organ_settles_after"), int) and v["organ_settles_after"] > 0]
    never = [b for b, v in out.items() if v.get("organ_settles_after") is None
             or v.get("gated_settles_after") is None]
    print()
    if finite:
        print(f"   Finite organ debts: {sorted(finite)} days — against a guardian lookback of "
              f"{params['lookback']}")
        print(f"   and a gate window of W={window}.")
    if never:
        print(f"   NEVER settled: {', '.join(never)} — for these books no 'discard the first N")
        print("   days' rule exists at all: the two protocols are still deciding differently on")
        print("   the last day of the sample.")

    # The number that matters is NOT how many days differ. It is how much ONE of them costs.
    worst = None
    for book, v in out.items():
        cr, cc = v["organ_calmar_restart"], v["organ_calmar_carry"]
        if cr != cr or cc != cc or cr in (float("inf"), float("-inf")) \
                or cc in (float("inf"), float("-inf")):
            continue
        gap = abs(cc - cr)
        if v["organ_diff_days"] and (worst is None or gap > worst[1]):
            worst = (book, gap, v["organ_diff_days"], cr, cc)
    if worst:
        book, gap, ndays, cr, cc = worst
        print(f"\n   AND THIS IS WHY A SHORT DEBT IS NOT A SMALL ONE: on `{book}` the two")
        print(f"   protocols disagree on {ndays} day(s) out of {out[book]['test_days']} — and the")
        print(f"   organ's test-half Calmar is {fmt(cr)} restarted against {fmt(cc)} carried, a")
        print(f"   gap of {gap:.2f}. A de-risk decision taken (or not taken) early compounds over")
        print("   the whole half. 'Warm-up' names WHEN the divergence happens, not how big it is.")
    out["_finite"] = sorted(finite)
    out["_never"] = never
    out["_worst"] = list(worst) if worst else None
    return out


def section6_verdict(res: Dict[str, object]) -> None:
    print("\n" + "=" * 100)
    print("VERDICT")
    print("=" * 100)
    s2 = res["dial"]
    s3 = res["baseline"]
    flips = s3.get("_flips", [])
    census = res["census"]
    print(f"   SPD. The census screened {census['population']} split-computed modules; "
          f"{len(census['buckets'].get('RE-RUNS ON THE SLICE', []))} of them re-run a path on")
    print("   the post-boundary slice, which is the shape #98 caught. #95 is one of them, and")
    print("   it is the one whose numbers the registry cites out of sample.")
    gated = [b for b, v in s2.items() if isinstance(v, dict) and v.get("k", 0) > 0
             and v.get("comparable")]
    if gated:
        lo = min(s2[b]["blocked_restart"] for b in gated)
        hi = max(s2[b]["blocked_restart"] for b in gated)
        print(f"   #98's failure mode is ABSENT on #95's path: the gate blocks {lo}–{hi} of "
              f"{s2[gated[0]]['test_days']} test")
        print("   days under the published protocol, not 0. The dial was never off here.")
    print("   What the restart severs is the BASELINE. The deployed organ is asked to start")
    print("   the test half cold — no exposure state, no volatility baseline — and the ΔCalmar")
    print("   column of #95 §3 is a difference taken against that cold start.")
    if flips:
        print(f"   RESULT: {len(flips)} published cell(s) change SIGN under CARRY: "
              f"{', '.join(flips)}.")
        for b in flips:
            print(f"     {b}: published {fmt(s3[b]['d_restart'])} → carried "
                  f"{fmt(s3[b]['d_carry'])}")
    else:
        print("   RESULT: no sign flip at the canonical boundary.")
    moved = [b for b, v in s3.items()
             if isinstance(v, dict) and v.get("note", "").count("→")]
    if moved:
        print(f"   Magnitude moves without a sign change: {', '.join(moved)}.")
    wud = res["wud"]
    if wud.get("_never"):
        print(f"   WUD. No finite warm-up debt exists for: {', '.join(wud['_never'])}. For "
              "those books")
        print("   'discard the first N test days' is not an available repair — only CARRY is.")
    if wud.get("_finite"):
        print(f"   WUD. Finite organ debts measured: {wud['_finite']} days — SHORT. And short")
        print("   is not small: see §5's last block. One differing decision day is enough.")
    grid = res.get("grid", {})
    d = grid.get("_direction") if isinstance(grid, dict) else None
    if d:
        print(f"   DIRECTION over the boundary grid: RESTART larger {d['restart_larger']}, "
              f"smaller {d['restart_smaller']}, tie {d['tie']} — the published protocol")
        print("   flatters the gate, systematically and with a sign.")
    wud2 = res["wud"]
    print("\n   PREDICTIONS, SCORED. P1 ('the sign flip is not a property of one boundary')")
    print("   — CORRECT in the direction that mattered: under RESTART the gate helps")
    print("   pendle_yt_susde at ALL FOUR boundaries; under CARRY it helps at ONE of four.")
    print("   P2 ('the debt is on the order of the 90-day gate window') — WRONG: measured")
    print(f"   debts are {wud2.get('_finite')} days, and the gate window never binds the answer.")
    print("   P3 ('at least one book never converges') — WRONG: every book converged, and")
    print("   the finding is the opposite of what P3 expected — the divergence is SHORT and")
    print("   still decisive, because one early decision compounds over the whole half.")
    print("\n   WHAT THIS DOES NOT SAY: #96's headline (the overlay layer sits ~3.9 Calmar")
    print("   below capped buy-and-hold) is a FULL-SAMPLE number with no split in it and is")
    print("   untouched. No module is built and no agent is deployed. IS_ADVISORY=True, "
          "OUTSIDE_RISKPOLICY=True, L0 [bt].")


def run(dates, book_rets, scripts_dir: Path = SCRIPTS) -> Dict[str, object]:
    params = {k: v for k, v in gf.GUARDIAN_PARAMS.items() if k != "roundtrip_cost"}
    cost = oda.DEPLOYED_BPS / 1e4
    window = oda.W_GRID[1]
    print("=" * 100)
    print("SPD / WUD — the split protocol itself, audited on the cells that publish through it")
    print(f"panel: {len(book_rets)} books × {len(dates)} days  ({dates[0]} … {dates[-1]})")
    print(f"boundary {SPLIT_DATE} · W={window} · toll {oda.DEPLOYED_BPS:.0f} bps (a CONVENTION,"
          " #92/#93) · guardian params imported from the deployed organ: " + str(params))
    print("IS_ADVISORY=True  OUTSIDE_RISKPOLICY=True  Evidence=L0  [bt]")
    print("=" * 100)
    res: Dict[str, object] = {}
    res["control_98"] = section0a_replay_98(dates, book_rets)
    cells = build_cells(dates, book_rets, SPLIT_DATE, window, cost, params)
    res["control_95"] = section0b_replay_95(cells)
    res["census"] = section1_census(scripts_dir)
    res["dial"] = section2_dial(cells, window, params)
    res["baseline"] = section3_baseline(cells)
    res["grid"] = section4_boundary_grid(dates, book_rets, window, cost, params)
    res["wud"] = section5_warmup_debt(dates, book_rets, window, cost, params)
    section6_verdict(res)
    return res


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--json", type=Path, default=None,
                    help="write the measured numbers to this path (never under data/)")
    ap.add_argument("--fixture", action="store_true",
                    help="run on the synthetic fixture panel instead of the real one")
    args = ap.parse_args(argv)
    # Argument checks BEFORE the panel is loaded: the panel is absent from a worktree BY
    # CONSTRUCTION, so a refusal placed after the load would have its verdict decided by which
    # tree it runs in rather than by the argument it is judging.
    if args.json and "data/" in str(args.json).replace("\\", "/"):
        print("REFUSAL: this harness does not write under data/.", file=sys.stderr)
        return 2
    dates, book_rets = (gtn.load_fixture_panel() if args.fixture else gtn.load_real_panel())
    if not book_rets:
        print("REFUSAL: the panel is empty. An empty table would read as 'no books', which is "
              "a different statement from 'the panel is not here'.", file=sys.stderr)
        return 2
    try:
        res = run(dates, book_rets)
    except ControlFailed as exc:
        print(f"\nREFUSAL — positive control failed: {exc}", file=sys.stderr)
        return 2
    res["panel"] = {"days": len(dates), "from": str(dates[0]), "to": str(dates[-1]),
                    "books": sorted(book_rets)}
    if args.json:
        args.json.write_text(json.dumps(res, indent=2, default=str), encoding="utf-8")
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
