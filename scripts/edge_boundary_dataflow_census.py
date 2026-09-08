#!/usr/bin/env python3
"""Idea #103 BDC — Boundary Dataflow Census: resolving the 21 modules #100 could not.

ORDERED BY THE REGISTRY. Entry #100 §7(в) closed with a named remainder, verbatim:

    "21 | граница используется, но НИКОГДА как индекс среза — передаётся ДАТОЙ в оконную
     функцию; этот скрин следит только за индексными срезами и их НЕ РАЗРЕШАЕТ"

and caveat (в): "21 модуль скрин НЕ РАЗРЕШИЛ и они названы поимённо — это заказ следующей
сессии, а не чистый лист." This file is that session. It answers, for each of those 21, the
question #98/#100 asked of the other 13: at the boundary, is a STATE-CARRYING path RE-RUN on a
truncated series (RESTART — the shape that inflates a published ΔCalmar), or is only the OUTPUT
of one continuous path cut (CARRY)?

WHY A SECOND AST SCREEN WOULD HAVE BEEN THE WRONG INSTRUMENT — and this is the whole design.
The screen of #100 failed on these 21 for a reason it named itself: it followed *index slices*
(`rets[k:]`), and this corpus mostly spells the boundary as a DATE handed to a windowing
primitive (`Panel(subset, TRAIN_END, None)`, `idea62_spw(..., start=TRAIN_END)`). #100 already
recorded what that class of mistake costs: its own first revision searched for the token
`SPLIT_DATE`, missed that most of the branch writes `TRAIN_END`, and pronounced 22 modules
clean. An instrument that answers about the SPELLING prints a clean bill of health it did not
earn. Widening the same screen to more spellings would repeat the method and merely move the
blind spot, so this file does not widen it.

WHAT IS MEASURED INSTEAD — the operators, not the source. Every state-carrying operator of the
CORPUS is WRAPPED, the module is then RUN, and the instrument records the LENGTH of every series
each operator was actually handed. The verdict follows from what the running code did:

  * a decision operator (`trailing_drawdown`, `trailing_vol`, `sig_*`, `kelly_weights`, …)
    handed a series shorter than the full common axis, whose length is exactly a boundary half,
    means decisions in that half were taken COLD — the state (high-water mark, volatility
    window, exposure) was rebuilt from the first day of the half. That is RESTART.
  * only metric operators (`perf`, `max_drawdown`, `equity_path`) seeing the short series means
    a continuous path was computed and its OUTPUT cut. That is CARRY.

This answers about the thing. A module may reach a truncated series through any spelling,
through any number of intermediate frames, through a helper this file has never heard of — the
operator still reports the length it was handed.

THE THIRD OUTCOME IS LOAD-BEARING, AND IT IS THE REASON THIS FILE CAN BE TRUSTED. "No decision
operator ever saw a truncated series" has TWO causes that are indistinguishable at the output:
the module carries state (CARRY), or the probe never reached the module at all — it ran on a
synthetic fixture, refused, or crashed. Reporting the second as CARRY would be the exact defect
this branch keeps finding: "не измерено", handed back as a safe answer. So a CARRY verdict must
EARN itself with a witness: the run must be observed touching the real panel through at least
one wrapped operator. Without that witness the verdict is UNMEASURED, printed with its reason
and counted separately. UNMEASURED is never folded into either resolved bucket.

THE OPERATORS LIVE IN TWO FAMILIES, AND THE FIRST VERSION OF THIS FILE SAW ONLY ONE. Wrapping
the shared toolkit `edge_calm_fp_tax` alone left every calibration control UNMEASURED: the
`gtn` family (`edge_gross_to_net_toll` as loader) does not call the toolkit at all but defines
its OWN state operators — `guarded_path`, `trailing_maxdd`, `_trailing_drawdown`, `_trailing_vol`.
So the operator set is DISCOVERED from the corpus by AST and wrapped wherever it is bound, rather
than named from one module. The discovery is checked, not asserted: `edge_real_panel_ensemble`
(a control) is resolvable ONLY through the second family, so a regression to one family cannot
pass §0.

AND THE FIRST VERSION'S CONTROL WAS AN ORNAMENT — recorded because it is the same defect this
branch keeps naming. All six controls came back UNMEASURED and the run CONTINUED, printing nine
RESTART verdicts from an instrument that had never been calibrated: the control skipped what it
could not measure instead of refusing, so "not measured" was handed back as "fine". A control
that can be silently skipped is not a control. UNMEASURED at §0 is now itself a REFUSAL.

CONTROLS RUN FIRST, AND THEY REFUSE (§0). The census of #100 is re-derived here and must
reproduce its published buckets exactly — 34 screened, 21 unresolved, 5 re-running, 2
output-split, 6 boundary-blind. Then the instrument itself is calibrated against the buckets
#100 already resolved, which are ground truth this file did not choose: the five RE-RUNS
modules MUST come out RESTART, and `edge_mhfc_backtest` (output-split by construction, the
control #100 used to prove its screen did not over-flag) MUST NOT. An instrument that cannot
re-find a known answer does not get to pronounce on an unknown one; if any control fails, this
file prints nothing and exits non-zero.

WHAT THIS FILE DOES NOT SAY. It answers "is a path re-run here", which is NOT "is the published
number wrong" — the same separation #100 drew. Whether a given RESTART verdict moves a given
published table is a separate measurement (#100 §5 did it for #95 §3 alone, and only there).
A RESTART verdict here is a place to look, with a direction of bias already known from #100
(RESTART reported the larger ΔCalmar in 13 of 16 cells), not a correction to anyone's number.

IS_ADVISORY=True · OUTSIDE_RISKPOLICY=True · Evidence L0 · [bt]
No capital moves, no deployed module changes, nothing under data/ is written.

    python3 scripts/edge_boundary_dataflow_census.py
    python3 scripts/edge_boundary_dataflow_census.py --json /tmp/bdc.json
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import edge_calm_fp_tax as cfpt                     # noqa: E402  shared toolkit
import edge_drift_gated_overlay as dgo              # noqa: E402  the Panel primitive
import edge_split_protocol_diagnostic as spd        # noqa: E402  the census of #100


class ControlFailed(RuntimeError):
    """A control that reproduces an already-known answer did not reproduce it."""


@contextlib.contextmanager
def corpus_without_self(scripts_dir: Path):
    """The population to screen, with THIS file removed from it.

    Caught by this file's own §0 control on its first run: the moment it was written into
    `scripts/` as `edge_*.py` mentioning the boundary literal, the census of #100 screened 35
    modules instead of the published 34 — the observer had joined its own population. That is a
    named defect of this branch (a guard that documents an incident then reads its own write-up
    as corpus), and the honest repair is to exclude the observer EXPLICITLY rather than to dodge
    the glob by choosing a name outside the `edge_` convention, which would have hidden the same
    coupling behind a spelling.

    The exclusion is MEASURED, not assumed: exactly one file must disappear, and it must be this
    one. A silent zero would mean the screen never saw this file and the count would drift back;
    a silent two would mean the mirror dropped somebody else's module.
    """
    import tempfile

    me = Path(__file__).resolve()
    with tempfile.TemporaryDirectory(prefix="bdc_corpus_") as tmp:
        mirror = Path(tmp)
        originals = sorted(scripts_dir.glob("edge_*.py"))
        kept = 0
        for path in originals:
            if path.resolve() == me:
                continue
            (mirror / path.name).symlink_to(path.resolve())
            kept += 1
        dropped = len(originals) - kept
        if dropped != 1:
            raise ControlFailed(
                f"the corpus mirror dropped {dropped} files, expected exactly this one. "
                "An observer that cannot account for its own removal cannot be trusted with "
                "the population count it reports."
            )
        yield mirror


# ── what counts as a DECISION operator, and why it is DISCOVERED rather than listed ──────────
#: Name shapes of operators that carry state ALONG a series: an accumulator seeded at the head
#: (high-water mark, volatility window, EMA level, expanding median) or a full guarded path.
#: Handed a truncated series, each rebuilds that state from the first day of the truncation —
#: precisely the cold start #100 §4 measured (10 days with no decision, 50 on a truncated base
#: window, 89 on a short W).
#:
#: These are SHAPES, matched against the corpus's own `def` names, because the branch spells the
#: same operator four ways across two families (`trailing_drawdown`, `_trailing_drawdown`,
#: `trailing_maxdd`, `guarded_path`). Listing names from one module is what left every control
#: UNMEASURED in the first version of this file.
DECISION_SHAPES: Tuple[str, ...] = (
    "trailing_", "_trailing_", "guarded_path", "kelly_weights", "expanding_median",
    "sig_", "maxdd_window", "_mk_", "apply_guardian", "_gross_and_turnover",
)
DECISION_EXACT: Tuple[str, ...] = ("ema", "sma")

#: Operators that summarise a series into a number and carry NOTHING across calls. Applying one
#: to a post-boundary slice is exactly the legitimate CARRY shape — a continuous path was built,
#: its output was cut. They are wrapped only to serve as the WITNESS that the probe reached the
#: module at all; they never produce a RESTART verdict.
METRIC_EXACT: Tuple[str, ...] = (
    "perf", "max_drawdown", "equity_path", "evaluate", "standalone_maxdd", "full_sample_maxdd",
)


def _is_named_candidate(name: str) -> bool:
    """A cheap pre-filter — never a verdict. Everything it admits is then MEASURED."""
    return name in DECISION_EXACT or any(sh in name for sh in DECISION_SHAPES)


#: A synthetic series with a high-water mark, a drawdown and a recovery, so that an operator
#: which carries state has something to carry. Values are small and mixed-sign like daily
#: returns; nothing about the corpus's real numbers is used or needed.
def _probe_series(n: int = 240) -> List[float]:
    out: List[float] = []
    for i in range(n):
        out.append(0.004 if i % 7 else -0.011)
    for i in range(90, 110):
        out[i] = -0.02
    return out


#: Entrypoint-shaped names are never probed. Calling one runs a whole harness rather than an
#: operator; the first version of this probe did exactly that and the process reached 4 GB of
#: resident memory before it was killed. A probe is only allowed to touch something that
#: DECLARES itself a series operator (see `_probeable_signature`).
NEVER_PROBE_PREFIXES: Tuple[str, ...] = ("run", "main", "section", "idea", "report", "load",
                                         "build", "census")

#: Parameter names this corpus uses for "a series of daily numbers". A function whose first
#: parameter is one of these, and whose remaining parameters all have defaults, can be called
#: with a bare series — which is the only shape this probe is willing to invoke.
SERIES_PARAMS: frozenset = frozenset({
    "returns", "rets", "series", "equity", "values", "xs", "gross", "net", "flags", "eq",
})

#: The corpus's OTHER operator shape: a path builder over a whole book of series at once
#: (`capped_bh(book_rets, live, *, cap, cost)`). Its first argument is a dict, so a probe that
#: only knew how to hand over a bare list could not classify it and a tape that measured
#: `len(args[0])` saw the BOOK COUNT rather than the day count. Both blind spots showed up as
#: the same thing — a control that could not be measured.
PANEL_PARAMS: frozenset = frozenset({"book_rets", "panel", "rets_by_book", "books"})


def _probeable_signature(node: object) -> bool:
    """True only when the function DECLARES that a bare series is a complete call.

    Two conditions, both necessary: the first parameter is named like a series, and every other
    parameter has a default. Anything else is left unprobed and reported as such — an operator
    this file could not measure is recorded, never guessed at.
    """
    import ast

    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return False
    if any(node.name.startswith(pfx) for pfx in NEVER_PROBE_PREFIXES):
        return False
    args = node.args
    positional = args.posonlyargs + args.args
    if not positional:
        return False
    first = positional[0].arg
    if first not in SERIES_PARAMS and first not in PANEL_PARAMS:
        return False
    n_required = len(positional) - len(args.defaults)
    # A panel builder legitimately takes a second required argument (the live book list), and
    # keyword-only arguments with defaults do not stand in the way of a bare call.
    return n_required <= (2 if first in PANEL_PARAMS else 1)


def _required_kwonly(node: object) -> Dict[str, float]:
    """Neutral fillers for keyword-only arguments the corpus declares WITHOUT defaults.

    `capped_bh(book_rets, live, *, cap, cost)` cannot be called with two positionals alone, and
    a probe that gave up there left a path builder out of the operator set — which showed up,
    once again, as a control that could not be measured. The fillers are deliberately boring: a
    cap of 0.20 (the corpus's own convention, #38/#46) and a zero toll.

    These values decide only whether the operator is RECOGNISED as state-carrying. They never
    enter a module's verdict: that comes from the lengths the operator is handed during the
    module's OWN run, with the module's own arguments.
    """
    import ast

    out: Dict[str, float] = {}
    for arg, default in zip(node.args.kwonlyargs, node.args.kw_defaults):   # type: ignore[union-attr]
        if default is not None:
            continue
        out[arg.arg] = 0.20 if "cap" in arg.arg else 0.0
    return out


def _probe_kind(node: object) -> str:
    import ast

    positional = node.args.posonlyargs + node.args.args        # type: ignore[union-attr]
    return "panel" if positional[0].arg in PANEL_PARAMS else "series"


def _carries_state(fn: object, kind: str = "series",
                   fillers: Optional[Dict[str, float]] = None) -> Optional[bool]:
    """Does `fn`'s answer for the tail depend on what came BEFORE the tail? Measured, not named.

    This is the property the census actually cares about, stated without reference to any
    spelling: run the operator on a full series and on its tail, and compare the overlapping
    part. If they differ, the operator was carrying something across the cut — a high-water
    mark, a volatility window, an EMA level, a weight book. That is exactly what makes a
    boundary truncation a RESTART rather than an output split.

    Returns None when the operator cannot be probed with a bare series (it needs arguments this
    file cannot invent). None is NOT "stateless": it is recorded as unclassified and reported,
    because guessing here would put a silent hole in the tape.
    """
    full = _probe_series()
    cut = 120
    kw = dict(fillers or {})
    try:
        if kind == "panel":
            # EIGHT books, not two: the corpus's own cap convention is 20 %, which two books
            # cannot satisfy (2 × 0.20 < 1.0). Probed with two, `capped_bh` had no feasible
            # allocation, could not be classified, and a path builder silently stayed out of
            # the operator set — surfacing, as every one of these gaps did, as a control that
            # could not be measured.
            books = {chr(ord("a") + i): [full[(j + 11 * i) % len(full)] for j in range(len(full))]
                     for i in range(8)}
            short = {k: list(v[cut:]) for k, v in books.items()}
            a = fn(books, sorted(books), **kw)         # type: ignore[operator]
            b = fn(short, sorted(short), **kw)         # type: ignore[operator]
        else:
            a = fn(full, **kw)                         # type: ignore[operator]
            b = fn(full[cut:], **kw)                   # type: ignore[operator]
    except BaseException:                              # noqa: BLE001 — unprobeable, not stateless
        return None
    try:
        if len(a) - len(b) != cut:                     # type: ignore[arg-type]
            return None
        tail = list(a)[len(a) - len(b):]               # type: ignore[index,arg-type]
        return any(x != y for x, y in zip(tail, list(b)))
    except BaseException:                              # noqa: BLE001 — not a series→series op
        return None


def discover_operators(scripts_dir: Path) -> Dict[str, Dict[str, str]]:
    """{module: {function name: "decision"|"metric"}} — read off the corpus, not listed here.

    Only module-level `def`s are taken: a closure defined inside another function cannot be
    reached by patching a module attribute, and pretending otherwise would put a hole in the
    tape that looks exactly like a CARRY verdict.
    """
    import ast

    root = scripts_dir.parent
    # THREE families, not two. The `scripts/` corpus is only where the research harnesses live;
    # the operator several of them actually take decisions with is the DEPLOYED organ
    # (`apply_guardian_vol`), imported from spa_core. A tape that watched `scripts/` alone left
    # `edge_cost_quote_divergence` — a control — unmeasurable, which is how this family was
    # found: by a control refusing, not by reading.
    sources = list(sorted(scripts_dir.glob("edge_*.py")))
    sources += [root / "spa_core" / "strategy_lab" / "aggressive_lab" / "guardian.py"]
    sources += sorted((root / "spa_core" / "strategy_lab" / "swarm").glob("*.py"))
    import importlib

    unprobeable: List[str] = []
    found: Dict[str, Dict[str, str]] = {}
    for path in sources:
        if not path.exists() or path.resolve() == Path(__file__).resolve():
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        mod_name = _module_name(path, root)
        try:
            mod = importlib.import_module(mod_name)
        except BaseException:                        # noqa: BLE001 — unimportable ⇒ nothing to wrap
            continue
        ops: Dict[str, str] = {}
        for node in tree.body:                       # module level ONLY, deliberately
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            fn = getattr(mod, node.name, None)
            if not callable(fn):
                continue
            if node.name in METRIC_EXACT:
                ops[node.name] = "metric"
                continue
            carries = (_carries_state(fn, _probe_kind(node), _required_kwonly(node))
                       if _probeable_signature(node) else None)
            if carries is True:
                ops[node.name] = "decision"
            elif carries is None and _is_named_candidate(node.name):
                # Not probeable with a bare series, but shaped like a path builder. Wrapped as
                # a decision operator and counted separately, because leaving it out would be
                # the silent hole; counting it in without saying so would be a claim.
                ops[node.name] = "decision"
                unprobeable.append(f"{mod_name}.{node.name}")
        if ops:
            found[mod_name] = ops
    DISCOVERY_NOTES["unprobeable"] = unprobeable
    return found


#: Filled by `discover_operators` so the report can state how much of the operator set was
#: MEASURED as state-carrying and how much was admitted on its name alone.
DISCOVERY_NOTES: Dict[str, List[str]] = {}


def _module_name(path: Path, root: Path) -> str:
    """Importable name for a source file — `scripts/` is on sys.path, spa_core is a package."""
    try:
        rel = path.resolve().relative_to(root.resolve())
    except ValueError:
        return path.stem
    if rel.parts[0] == "scripts":
        return path.stem
    return ".".join(rel.with_suffix("").parts)

#: The registry-canonical boundary. Same value the corpus and #100 use; not a new convention.
BOUNDARY = "2025-06-30"

#: Modules whose answer #100 already established. Ground truth for calibrating this instrument
#: — chosen by #100, not by this file, which is what makes them a control rather than a mirror.
#: Ground truth is what #100 ASSERTED, not what its screen OUTPUT.
#:
#: The distinction cost this file a rewrite and is the most useful thing it learned. The five
#: modules in #100's "RE-RUNS ON THE SLICE" bucket are that screen's ANSWERS, and #100 said in
#: its own words that the bucket is "a SCREEN, not a verdict … a MAP of where to look, never a
#: clean bill of health". Only two of the five were declared by #100 as controls whose answer it
#: established independently ("`edge_trim_proceeds_destination` и `edge_overlay_domain_
#: admissibility` обязаны попасть в «перезапускает»"). Those two are ground truth. Using the
#: other three as controls would have been calibrating this instrument against the very output
#: it exists to check — and it would have forced the wrong answer, because one of them
#: (`edge_leg_aware_timing`) is a false positive of that screen; see FALSE_POSITIVE_OF_100.
CONTROL_MUST_RESTART: Tuple[str, ...] = (
    "edge_overlay_domain_admissibility", "edge_trim_proceeds_destination",
)

#: Screened as RE-RUNS by #100, measured as CARRY here, and READ to settle which is right.
#: `edge_leg_aware_timing` §4 builds the weight history, gross series and leg turnover over the
#: FULL history (`lat_history(...)`, `css._gross_and_turnover(hist, ...)`, `gtn.leg_turnover`)
#: and slices only the OUTPUT (`gross[sl]`, `tau[sl]`) before scoring it. Nothing is re-run on
#: the half; the callees the screen saw applied to the slice — `css._net`, `css._dcalmar` — are
#: pure functions of the series handed to them. That is the CARRY shape by construction, so the
#: screen's flag is a false positive of exactly the kind #100 said its map could contain.
FALSE_POSITIVE_OF_100: Tuple[str, ...] = ("edge_leg_aware_timing",)
#: #100 resolved TWO modules as output-split (CARRY by construction). `edge_mhfc_backtest` is
#: the one it used as its own negative control, but it exposes no `main()` and therefore cannot
#: be RUN — a behavioural probe has nothing to attach to. Rather than let that gap pass as a
#: pass, the runnable member of the same bucket carries the negative direction, and the
#: unrunnable one is declared here so its absence is visible instead of silent.
CONTROL_MUST_NOT_RESTART: Tuple[str, ...] = ("edge_cost_internalised_timing",)
CONTROL_NOT_RUNNABLE: Tuple[str, ...] = ("edge_mhfc_backtest",)


class OperatorTape:
    """Records the length of every series each wrapped operator is handed.

    One tape per module run. `decision_lengths` answers the question of this census;
    `metric_lengths` exists only to witness that the probe reached the module at all.
    """

    def __init__(self) -> None:
        self.decision: Dict[str, List[int]] = {}
        self.metric: Dict[str, List[int]] = {}

    def note(self, kind: str, name: str, n: int) -> None:
        book = self.decision if kind == "decision" else self.metric
        book.setdefault(name, []).append(n)

    @property
    def touched(self) -> bool:
        """Did ANY wrapped operator run? This is the witness a CARRY verdict must earn."""
        return bool(self.decision or self.metric)

    def lengths(self, kind: str) -> set:
        book = self.decision if kind == "decision" else self.metric
        return {n for lens in book.values() for n in lens}


@contextlib.contextmanager
def taped(tape: OperatorTape, operators: Dict[str, Dict[str, str]]):
    """Wrap every discovered operator at EVERY binding of it, found by identity.

    Patching only the defining module is not enough and the controls proved it: this corpus
    binds the deployed organ with `from spa_core...guardian import apply_guardian_vol`, so the
    caller holds its own reference and calls through it, never through the defining module's
    attribute. A tape that patched definitions alone therefore saw nothing and reported the
    module as taking no decisions — the silent-hole shape this file exists to avoid.

    So the function OBJECTS are collected first, and then every module-level name in every
    loaded `edge_*` / `spa_core.*` module whose value IS one of those objects is replaced. That
    covers aliases, re-exports and direct imports without needing to know which form was used,
    because it matches on the thing rather than on the spelling.
    """
    import importlib

    targets: Dict[int, Tuple[str, str]] = {}          # id(func) -> (name, kind)
    for mod_name, ops in operators.items():
        try:
            mod = importlib.import_module(mod_name)
        except BaseException:                          # noqa: BLE001 — unimportable ⇒ nothing to wrap
            continue
        for op_name, kind in ops.items():
            fn = getattr(mod, op_name, None)
            if callable(fn):
                targets[id(fn)] = (op_name, kind)

    def day_extents(args, kwargs) -> List[int]:
        """Every plausible DAY count among the arguments handed to an operator.

        Not `len(args[0])`: the corpus passes days three ways — a bare series, a dict of series
        keyed by book (where `len` is the BOOK count and the day count lives one level down),
        and an equity path. Measuring only the first argument's length reported the book count
        as if it were a day count, and a control went unmeasurable because of it.
        """
        out: List[int] = []
        for value in list(args) + list(kwargs.values()):
            if isinstance(value, (list, tuple)):
                out.append(len(value))
            elif isinstance(value, dict) and value:
                inner = next(iter(value.values()))
                if isinstance(inner, (list, tuple)):
                    out.append(len(inner))
        return out

    def make(original, kind: str, name: str):
        def wrapper(*args, **kwargs):
            for n in day_extents(args, kwargs) or [-1]:
                tape.note(kind, name, n)
            return original(*args, **kwargs)
        wrapper.__name__ = getattr(original, "__name__", name)
        return wrapper

    saved: List[Tuple[object, str, object]] = []
    try:
        for mod in list(sys.modules.values()):
            name = getattr(mod, "__name__", "")
            if not (name.startswith("edge_") or name.startswith("spa_core")):
                continue
            for attr in list(vars(mod)) if hasattr(mod, "__dict__") else []:
                try:
                    value = getattr(mod, attr)
                except BaseException:                  # noqa: BLE001 — a property that raises
                    continue
                hit = targets.get(id(value))
                if hit is None:
                    continue
                op_name, kind = hit
                saved.append((mod, attr, value))
                setattr(mod, attr, make(value, kind, op_name))
        yield
    finally:
        for mod, attr, original in saved:
            setattr(mod, attr, original)


def direct_import_escapees(scripts_dir: Path,
                           operators: Dict[str, Dict[str, str]]) -> List[str]:
    """Modules that bind a wrapped operator by `from <edge module> import <op>`.

    Such a module holds its own reference, taken at import time, and the tape would never see
    its calls — the escape would look exactly like "this module takes no decisions", i.e. it
    would silently manufacture a CARRY. The escape is therefore MEASURED and reported, not
    assumed away; any module found here is forced to UNMEASURED regardless of its tape.
    """
    import ast

    out: List[str] = []
    watched = {n for ops in operators.values() for n in ops}
    for path in sorted(scripts_dir.glob("edge_*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("edge_"):
                if any(a.name in watched for a in node.names):
                    out.append(path.stem)
                    break
    return out


def axis_facts() -> Dict[str, int]:
    """The lengths that make a truncation recognisable: full axis, train half, test half."""
    panel = cfpt.load_clean_panel()
    axis = cfpt.common_axis(panel)
    train = [d for d in axis if d <= BOUNDARY]
    test = [d for d in axis if d > BOUNDARY]
    return {"full": len(axis), "train": len(train), "test": len(test)}


def run_module(name: str, tape: OperatorTape,
               operators: Dict[str, Dict[str, str]]) -> Tuple[bool, str]:
    """Import and run one harness with the tape installed. Returns (ran, note)."""
    import importlib

    try:
        mod = importlib.import_module(name)
    except BaseException as exc:                      # noqa: BLE001 — any failure is a reason
        return False, f"import failed: {type(exc).__name__}: {exc}"
    entry = getattr(mod, "main", None)
    if entry is None:
        return False, "no main() entrypoint to run"
    buf = io.StringIO()
    try:
        with taped(tape, operators), contextlib.redirect_stdout(buf), \
                contextlib.redirect_stderr(buf):
            try:
                entry([])
            except SystemExit:
                pass
            except TypeError:
                # Two entrypoint conventions live side by side in this corpus: `main(argv)` and
                # `main()`. Treating the second as a crash would have reported a measurable
                # module as UNMEASURED — a spelling deciding a verdict, again.
                try:
                    entry()
                except SystemExit:
                    pass
    except BaseException as exc:                      # noqa: BLE001 — reason, never a verdict
        return False, f"run raised {type(exc).__name__}: {exc}"
    return True, ""


def classify(tape: OperatorTape, facts: Dict[str, int], ran: bool, note: str,
             escaped: bool) -> Dict[str, object]:
    """Turn one tape into a verdict — with UNMEASURED as a first-class outcome."""
    # THREE day conventions live side by side in this corpus, each one day apart, and an
    # exact-length test misses two of them SILENTLY — as a CARRY, which is the direction that
    # hides a defect:
    #   * a returns series spans the half exactly            (n)
    #   * a weight history starts at index 1, one shorter    (n−1; `mh._weights` over
    #     `range(1, len(dates))`)
    #   * an equity path carries its opening 1.0, one longer (n+1; `_equity(rets)`)
    # Both neighbours cost this file a control apiece before they were measured: the weight
    # history hid `edge_leg_aware_timing`'s family at n−1, and the equity path hid
    # `edge_overlay_domain_admissibility` — a control #100 DECLARED — at 483/371 against halves
    # of 482/370. The full-length set is widened identically, so a full-history equity path
    # (853) is never read as a truncation.
    halves = {facts["train"] + d for d in (-1, 0, 1)}
    halves |= {facts["test"] + d for d in (-1, 0, 1)}
    full_lengths = {facts["full"] + d for d in (-1, 0, 1)}
    # NOTE: no `halves -= full_lengths` here. It was written, and then removed with a reason
    # rather than left standing: the same exclusion is applied where it is USED, in `truncated`
    # below, so the subtraction was redundant by construction and no mutation of it could
    # change an answer. A line that cannot be killed is not a safeguard, it is decoration.
    if not ran:
        return {"verdict": "UNMEASURED", "reason": note}
    if not tape.touched:
        return {"verdict": "UNMEASURED",
                "reason": ("ran, but no wrapped operator was ever called — the probe did not "
                           "reach this module's numbers (own fixture or own arithmetic), and "
                           "silence from an instrument that was never connected is not a "
                           "CARRY finding")}
    dec = sorted(tape.lengths("decision"))
    truncated = sorted(n for n in dec if n in halves and n not in full_lengths)
    if truncated:
        return {"verdict": "RESTART", "reason": "",
                "decision_lengths": dec, "truncated_seen": truncated}
    if not dec:
        return {"verdict": "CARRY", "reason": "metric operators only — no decision was taken",
                "decision_lengths": dec, "metric_lengths": sorted(tape.lengths("metric"))}
    return {"verdict": "CARRY", "reason": "every decision saw a full-length series",
            "decision_lengths": dec, "metric_lengths": sorted(tape.lengths("metric"))}


def section0_controls(scripts_dir: Path) -> Dict[str, object]:
    """Reproduce the census of #100, then calibrate this instrument on its resolved buckets."""
    print("=" * 100)
    print("BDC — Boundary Dataflow Census (idea #103, ordered by #100 §7(в))")
    print("IS_ADVISORY=True  OUTSIDE_RISKPOLICY=True  Evidence=L0  [bt]")
    print("=" * 100)
    print("\n0. CONTROLS — run BEFORE any new number, and they REFUSE rather than warn.")

    buf = io.StringIO()
    with corpus_without_self(scripts_dir) as mirror:
        with contextlib.redirect_stdout(buf):
            census = spd.section1_census(mirror)
    buckets = census["buckets"]
    got = {k: len(v) for k, v in buckets.items()}
    want = {
        "BOUNDARY USED, BUT NEVER AS A SLICE INDEX": 21,
        "RE-RUNS ON THE SLICE": 5,
        "OUTPUT-SPLIT (CARRY by construction)": 2,
        "NO BOUNDARY-AWARE FUNCTION": 6,
    }
    if census["population"] != 34:
        raise ControlFailed(
            f"the census of #100 screened {census['population']} modules, not the published 34"
        )
    for key, n in want.items():
        if got.get(key, 0) != n:
            raise ControlFailed(
                f"bucket {key!r} holds {got.get(key, 0)}, and #100 published {n}. The corpus "
                "moved under this order; the remainder must be re-derived before it is resolved."
            )
    print(f"   ✅ #100 census reproduced: {census['population']} screened · "
          f"21 unresolved · 5 re-run · 2 output-split · 6 boundary-blind.")

    facts = axis_facts()
    print(f"   ✅ real panel loaded: axis {facts['full']} days · train {facts['train']} · "
          f"test {facts['test']} (boundary {BOUNDARY}).")
    if facts["train"] + facts["test"] != facts["full"]:
        raise ControlFailed("the two halves do not sum to the axis — the boundary does not cut "
                            "this panel and every length test below would be meaningless")
    return {"census": census, "facts": facts}


def section1_calibrate(facts: Dict[str, int], escapees: Sequence[str],
                       operators: Dict[str, Dict[str, str]]) -> Dict[str, object]:
    """The instrument must re-find answers #100 already established, in BOTH directions.

    UNMEASURED here is a REFUSAL, not a skip. The first version of this file skipped it, and so
    printed nine verdicts from an uncalibrated probe: every control came back UNMEASURED and
    nothing stopped. "Could not measure the control" and "the control passed" must never share
    an outcome.
    """
    print("\n   Calibrating THIS instrument on the buckets #100 already resolved — ground truth")
    print("   it did not choose. Both directions are checked: an instrument that only confirms")
    print("   RESTART would pass by flagging everything.")
    if CONTROL_NOT_RUNNABLE:
        print(f"   ℹ️  not runnable, and named rather than passed over: "
              f"{', '.join(CONTROL_NOT_RUNNABLE)} (no main() to attach a behavioural probe to)")
    results: Dict[str, object] = {}
    for name in CONTROL_MUST_RESTART + CONTROL_MUST_NOT_RESTART + FALSE_POSITIVE_OF_100:
        if name in FALSE_POSITIVE_OF_100:
            tape = OperatorTape()
            ran, note = run_module(name, tape, operators)
            res = classify(tape, facts, ran, note, name in escapees)
            results[name] = res
            if res["verdict"] != "CARRY":
                raise ControlFailed(
                    f"{name} was READ and found to slice only the output of a full-history "
                    f"path, so it must measure as CARRY; this instrument says {res['verdict']}. "
                    "Either the module changed or the reading was wrong — both are stop signs."
                )
            print(f"   ✅ {name}: CARRY — #100's screen flagged it as RE-RUNS; read and "
                  f"measured, that flag is a FALSE POSITIVE (see module docstring)")
            continue
        tape = OperatorTape()
        ran, note = run_module(name, tape, operators)
        res = classify(tape, facts, ran, note, name in escapees)
        results[name] = res
        want_restart = name in CONTROL_MUST_RESTART
        if res["verdict"] == "UNMEASURED":
            raise ControlFailed(
                f"control {name} came back UNMEASURED ({res['reason']}). A control that cannot "
                "be measured has not passed — it has gone unanswered, and continuing would "
                "publish verdicts from an uncalibrated instrument."
            )
        if (res["verdict"] == "RESTART") != want_restart:
            raise ControlFailed(
                f"control {name}: #100 resolved it as "
                f"{'RE-RUNS ON THE SLICE' if want_restart else 'output-split (CARRY)'}, this "
                f"instrument says {res['verdict']}. A probe that cannot re-find a known answer "
                "does not get to pronounce on an unknown one."
            )
        print(f"   ✅ {name}: {res['verdict']} (as #100 resolved it)")
    return results


def section2_resolve(census: Dict[str, object], facts: Dict[str, int],
                     escapees: Sequence[str],
                     operators: Dict[str, Dict[str, str]]) -> Dict[str, object]:
    """The order itself: resolve the 21."""
    unresolved = sorted(census["buckets"]["BOUNDARY USED, BUT NEVER AS A SLICE INDEX"])
    print("\n" + "─" * 100)
    print(f"1. THE ORDER — resolving the {len(unresolved)} modules #100 left named but unresolved.")
    print("   RESTART = a state-carrying operator was handed a boundary half (decisions taken")
    print("   cold). CARRY = only a continuous path's output was cut. UNMEASURED = the probe")
    print("   did not reach this module, printed with its reason and folded into neither.")
    out: Dict[str, object] = {}
    for path_name in unresolved:
        name = path_name[:-3] if path_name.endswith(".py") else path_name
        tape = OperatorTape()
        ran, note = run_module(name, tape, operators)
        out[name] = classify(tape, facts, ran, note, name in escapees)
    return out


def report(resolved: Dict[str, object], facts: Dict[str, int]) -> Dict[str, int]:
    order = {"RESTART": 0, "CARRY": 1, "UNMEASURED": 2}
    rows = sorted(resolved.items(), key=lambda kv: (order[kv[1]["verdict"]], kv[0]))
    print(f"\n   {'module':44s} {'verdict':11s} what the operators were handed")
    print("   " + "─" * 95)
    for name, res in rows:
        if res["verdict"] == "RESTART":
            detail = (f"decision ops saw {res['truncated_seen']} "
                      f"(halves of {facts['full']}); all lengths {res['decision_lengths']}")
        elif res["verdict"] == "CARRY":
            detail = res["reason"]
            if res.get("decision_lengths"):
                detail += f"; decision lengths {res['decision_lengths']}"
        else:
            detail = res["reason"]
        if len(detail) > 60:
            detail = detail[:57] + "..."
        print(f"   {name:44s} {res['verdict']:11s} {detail}")
    tally = {k: sum(1 for _, r in rows if r["verdict"] == k) for k in order}
    print("\n   " + " · ".join(f"{k} {v}" for k, v in tally.items()))
    return tally


def section3_verdict(tally: Dict[str, int], facts: Dict[str, int]) -> None:
    print("\n" + "─" * 100)
    print("2. WHAT THIS RESOLVES — and, just as deliberately, what it does not.")
    resolved = tally["RESTART"] + tally["CARRY"]
    print(f"\n   Of the 21 the order named, {resolved} are now resolved and "
          f"{tally['UNMEASURED']} are honestly not.")
    print(f"   {tally['RESTART']} RESTART a state-carrying path at the boundary — the shape "
          f"#98 caught by")
    print(f"   its loud form and #100 caught by its quiet one, reached here through a THIRD")
    print(f"   spelling: the boundary handed as a DATE to a windowing primitive, which "
          f"truncates")
    print(f"   the axis itself, after which every high-water mark and volatility window is "
          f"rebuilt")
    print(f"   from the first day of the half.")
    print(f"\n   The bias of that shape is not re-derived here — #100 measured it and it has a")
    print(f"   SIGN: RESTART reported the larger ΔCalmar in 13 of 16 cells. So these modules are")
    print(f"   where to look, in a known direction. This file does NOT claim any published")
    print(f"   number is wrong: 'is a path re-run here' and 'is the number wrong' are different")
    print(f"   questions, and the second was answered by #100 for #95 §3 alone.")
    print(f"\n   UNMEASURED is reported, never absorbed. Folding it into CARRY would have been")
    print(f"   the branch's own recurring defect — 'не измерено', handed back as a safe answer.")


def run(scripts_dir: Path = SCRIPTS) -> Dict[str, object]:
    res: Dict[str, object] = {}
    ctl = section0_controls(scripts_dir)
    facts = ctl["facts"]
    operators = discover_operators(scripts_dir)
    n_dec = sum(1 for ops in operators.values() for k in ops.values() if k == "decision")
    n_met = sum(1 for ops in operators.values() for k in ops.values() if k == "metric")
    print(f"   ✅ operator set discovered from the corpus: {n_dec} decision · {n_met} metric "
          f"across {len(operators)} modules (two families, not one).")
    escapees = direct_import_escapees(scripts_dir, operators)
    if escapees:
        print(f"   ℹ️  {len(escapees)} module(s) bind a toolkit operator directly and are forced "
              f"to UNMEASURED: {', '.join(escapees)}")
    else:
        print("   ✅ no module binds a wrapped operator by direct import — none can escape the "
              "tape unseen.")
    res["controls"] = section1_calibrate(facts, escapees, operators)
    res["operators"] = {m: sorted(ops) for m, ops in operators.items()}
    resolved = section2_resolve(ctl["census"], facts, escapees, operators)
    res["resolved"] = resolved
    tally = report(resolved, facts)
    res["tally"] = tally
    res["facts"] = facts
    res["escapees"] = list(escapees)
    section3_verdict(tally, facts)
    return res


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", type=Path, default=None,
                    help="write the measured numbers to this path (never under data/)")
    args = ap.parse_args(argv)
    # Checked BEFORE anything is loaded: a refusal placed after the panel load would have its
    # verdict decided by which tree it runs in rather than by the argument it judges.
    if args.json and "data/" in str(args.json).replace("\\", "/"):
        print("REFUSAL: this harness does not write under data/.", file=sys.stderr)
        return 2
    try:
        res = run()
    except ControlFailed as exc:
        print(f"\nREFUSAL — control failed: {exc}", file=sys.stderr)
        return 2
    if args.json:
        args.json.write_text(json.dumps(res, indent=2, default=str), encoding="utf-8")
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
