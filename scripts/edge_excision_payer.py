#!/usr/bin/env python3
"""
scripts/edge_excision_payer.py — registry ideas #145 (EDX) and #146 (PYD)

IS_ADVISORY = True
OUTSIDE_RISKPOLICY = True

#145 EDX — Eth-Directional eXcision.  EXECUTES THE ORDER LEFT VERBATIM BY #143:

    "Re-measure the head rows of the negative series (#123 NLF, #131 ASE, #132 GZ, #141 TUB)
     on the panel WITHOUT `eth_directional` — if their sign changes, the series was about one
     book, and that has to be written into each of them, not only here."

  #143 measured that the whole apparent edge of its own rule was "do not hold eth_directional",
  and that with that book removed EW-10 alone has TEST Calmar ~22. If that one book also
  carries the NEGATIVE verdicts of #123/#131/#132/#141, then a large part of the registry's
  negative series is a statement about one directional book inside a carry panel, not about
  de-risk sizers. This section does not invent a rule. It re-runs the ORIGINAL instruments,
  byte-for-byte, on a panel that is missing one book.

  WHY NOTHING IS REIMPLEMENTED. `ase_report` (#131 + #141), `guardian_zero_report` (#132) and
  `run_plb_nlf` (#122 + #123) are IMPORTED and called with a different `panel_dir`. A second
  copy of any of them would make these numbers incomparable with the entries being re-measured
  BY CONSTRUCTION — the one way this measurement could be green and meaningless at once.

  THE PRECONDITION THAT MAKES THE COMPARISON CLEAN IS MEASURED, NOT ASSUMED. Every loader in
  the chain intersects dates across books (`common_axis`), so dropping a book can only ENLARGE
  the axis, and an enlarged axis would mean the two runs were judged over different days.
  `axis_identity()` measures it and REFUSES (fail-CLOSED) when the axes differ, instead of
  printing a difference that is partly a change of window. Measured on this panel: all 10 books
  carry the identical 852-day axis, so the excised axis is bit-identical and the comparison is
  clean — that is a measured fact about this panel, not a property of excision.

#146 PYD — Payer-Class Diversification.  A NEW mechanism (the registry has ZERO occurrences of
  "payer" / "плательщик" / "кто платит" / "payer class").

  Every composition idea in the registry diversifies over BOOKS (#123 NLF counts legs, #130
  MSD blends two names, #131 ASE expands the admitted set). Claim of this one: books do not
  fail independently, they fail BY PAYER — the yield of two books paid by the same counterparty
  for the same risk has one tail, so spreading 1/10 over ten books that share three payers
  buys less than it looks. Rule: equal weight per PAYER CLASS, split equally inside the class.

  THE TAXONOMY IS DECLARED, NOT FITTED. The payer class is `risk_shape` read from
  `spa_core/strategy_lab/aggressive_lab/roster.py` — "what the headline yield is COMPENSATION
  for". It was written into git long before this measurement and is not touched here, so it
  cannot have been chosen to fit the panel. The rule has ZERO free parameters: there is nothing
  to overfit and nothing selected on TRAIN.

  THE CONTROL THAT DECIDES IT. PYD moves weight into SINGLETON classes (`points_farm` and
  `lp_eth_stable` go 10 % -> 20 %), so any result could be the concentration PROFILE rather
  than the taxonomy's information. PLACEBO: deterministic random partitions with the IDENTICAL
  class-size profile (3,3,2,1,1). If PYD sits inside that distribution, the declared taxonomy
  carries nothing and only the profile does — and that is the honest verdict, not a footnote.

Window / toll / split conventions are INHERITED from the imported harnesses so the numbers stay
comparable with #122…#144. Nothing is written to disk; both sections only print.

stdlib-only, deterministic, read-only, LLM FORBIDDEN.
Advisory / paper-only: no capital moves, the go-live track (data/equity_curve_daily.json) is
never opened, RiskPolicy v1.0 is untouched, and the 20 %/name policy ceiling is MEASURED,
never changed.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import importlib.util
import json
import random
import statistics
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

IS_ADVISORY = True
OUTSIDE_RISKPOLICY = True

ROOT = Path(__file__).resolve().parent.parent
ENSEMBLE = ROOT / "scripts" / "edge_real_panel_ensemble.py"
SFS = ROOT / "scripts" / "edge_sigma_floor_ctac_real.py"
ASE = ROOT / "scripts" / "edge_admitted_set_guardian_zero.py"

#: the book whose excision the order of #143 names.
DROP_DEFAULT = ("eth_directional",)
#: placebo partitions for §2. Deterministic (seeded); the count is declared, not tuned.
PLACEBO_N = 2000
PLACEBO_SEED = 20261027
#: per-name policy ceiling. OWNER-GATED: lives in RiskPolicy v1.0 and moves only by ADR.
#: This file MEASURES what it does and never changes it.
POLICY_CAP = 0.20

_MOD: Dict[str, object] = {}


class ExcisionError(RuntimeError):
    """Fail-CLOSED: the two panels cannot be judged as the same measurement."""


def _load(path: Path, name: str):
    if name in _MOD:
        return _MOD[name]
    if not path.exists():
        raise ExcisionError(f"{name}: {path} missing — refusing to reimplement it")
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    _MOD[name] = mod
    return mod


def ens():
    return _load(ENSEMBLE, "_edx_ensemble")


def sfs():
    return _load(SFS, "_edx_sfs")


def ase():
    return _load(ASE, "_edx_ase")


# ── §1 #145 EDX ────────────────────────────────────────────────────────────────

def build_shadow_panel(real_dir: Path, drop: Sequence[str], stem: Path) -> Tuple[Path, List[str]]:
    """A panel directory holding every book of `real_dir` except `drop`, by SYMLINK.

    Symlinks, not copies: the excised run must read the SAME BYTES as the full run, so that a
    difference in the output cannot be a difference in the data. Returns the directory and the
    names actually dropped — a name in `drop` that is not in the panel is an ERROR, never a
    silent no-op (that would print "excision changes nothing" without having excised anything).
    """
    real_dir = Path(real_dir)
    present = sorted(p.parent.name for p in real_dir.glob("*/realized_series.jsonl"))
    if not present:
        raise ExcisionError(f"no realized_series.jsonl under {real_dir}")
    missing = [b for b in drop if b not in present]
    if missing:
        raise ExcisionError(
            f"cannot excise {missing}: not in the panel {present} — refusing to report an "
            f"excision that did not happen"
        )
    keep = [b for b in present if b not in drop]
    if len(keep) < 2:
        raise ExcisionError(f"excision leaves {len(keep)} book(s) — not a panel")
    stem.mkdir(parents=True, exist_ok=True)
    for b in keep:
        (stem / b).mkdir(exist_ok=True)
        link = stem / b / "realized_series.jsonl"
        if not link.exists():
            link.symlink_to((real_dir / b / "realized_series.jsonl").resolve())
    return stem, [b for b in present if b in drop]


def axis_identity(full_dir: Path, exc_dir: Path) -> Dict[str, object]:
    """Measure whether the two panels are judged over the SAME days. Fail-CLOSED if not.

    `common_axis` is an intersection over books, so removing a book can only ADD dates. An
    enlarged axis would silently fold a change of WINDOW into every number below, and the
    comparison would stop being about the excision. This refuses instead.
    """
    E = ens()
    a_full = E.common_axis(E.load_panel(Path(full_dir)))
    a_exc = E.common_axis(E.load_panel(Path(exc_dir)))
    out = {
        "full_days": len(a_full), "exc_days": len(a_exc),
        "full_span": [a_full[0], a_full[-1]] if a_full else None,
        "exc_span": [a_exc[0], a_exc[-1]] if a_exc else None,
        "identical": a_full == a_exc,
        "grew_by": len(a_exc) - len(a_full),
    }
    if not out["identical"]:
        raise ExcisionError(
            f"excision changed the judged axis ({len(a_full)} -> {len(a_exc)} days, "
            f"{out['full_span']} -> {out['exc_span']}): the two runs would not be the same "
            f"measurement. Refusing — this needs a pinned axis, not a caveat."
        )
    return out


def nlf_shape(rows: Sequence[dict], key: str) -> Dict[str, object]:
    """Is the N-leg frontier falling in N? (#123's claim was 'monotonically falling'.)

    Returns the per-N series, strict monotonicity, and the rank correlation of N against the
    metric. `None` with a named reason where a rung was not admitted (inv. #17) — never a zero.
    """
    E = ens()
    ns, vals, holes = [], [], []
    for r in rows:
        if r.get("admitted") == 0 or r.get(key) is None:
            holes.append({"n": r["n"], "reason": r.get("reason") or f"{key} not measured"})
            continue
        ns.append(float(r["n"]))
        vals.append(float(r[key]["apy"]))
    if len(ns) < 3:
        return {"series": None, "unmeasured": f"only {len(ns)} admitted rungs", "holes": holes}
    mono_down = all(vals[i + 1] <= vals[i] + 1e-12 for i in range(len(vals) - 1))
    mono_up = all(vals[i + 1] >= vals[i] - 1e-12 for i in range(len(vals) - 1))
    rho = E.rank_spearman(ns, vals)
    return {
        "series": [(int(n), v) for n, v in zip(ns, vals)],
        "monotone_down": mono_down, "monotone_up": mono_up,
        "spearman_n_vs_apy": rho,
        "sign": (None if rho is None else ("down" if rho < 0 else "up" if rho > 0 else "flat")),
        "best_n": int(ns[vals.index(max(vals))]),
        "holes": holes,
    }


def gz_signs(gz: Dict[str, object]) -> Dict[str, object]:
    """#132's head number: dCalmar of the flagship overlay against BOTH zeros, with its verdict."""
    out: Dict[str, object] = {}
    for zname, z in (gz.get("zeros") or {}).items():
        base = z.get("raw") or {}
        for overlay, arm_key in (("delta_vol", "vol"), ("delta_reactive", "reactive")):
            d = z.get(overlay) or {}
            dc = d.get("delta_calmar")
            guarded = z.get(arm_key) or {}
            out[f"{zname}/{overlay}"] = {
                "delta_calmar": dc,
                "status": d.get("status"),
                "reason": d.get("reason"),
                "sign": (None if dc is None else ("+" if dc > 0 else "-" if dc < 0 else "0")),
                # the denominator the delta stands on. A dCalmar of +2 on a 40 bp drawdown and
                # one on a 5 % drawdown are not the same claim, and #129's whole lesson is that
                # the table must say which of the two it is.
                "base_maxdd": base.get("maxdd_frac"),
                "guarded_maxdd": guarded.get("maxdd_frac"),
                "base_calmar": d.get("base_calmar"),
                "guarded_calmar": d.get("guarded_calmar"),
                "switches": guarded.get("switches"),
            }
    return out


def tub_tally(a: Dict[str, object]) -> Dict[str, object]:
    """#141's head number: how many ladder x sizer rows beat EW-live on ALL THREE conditions.

    `three_vs_ew_live.all_three` is #129's acceptance. The companion tally is how often the
    portfolio denominator was REFUSED (`calmar_degenerate`) — #141's verdict was that the
    denominator is refused, which is a different statement from "the overlay loses", and the
    two must stay distinguishable (inv. #17).
    """
    rows, all_three, degenerate, unmeasured = [], 0, 0, 0
    for rule, arms in (a.get("oos") or {}).items():
        for sizer, d in arms.items():
            te = d.get("test") or {}
            three = (te.get("three_vs_ew_live") or {}).get("all_three")
            deg = te.get("calmar_degenerate")
            if three is None:
                unmeasured += 1
            elif three:
                all_three += 1
            if deg:
                degenerate += 1
            rows.append({
                "rule": rule, "sizer": sizer,
                "test_apy_net": te.get("apy_net"), "test_maxdd": te.get("maxdd"),
                "test_calmar": te.get("calmar"), "calmar_degenerate": deg,
                "all_three": three,
            })
    return {"rows": rows, "n_rows": len(rows), "all_three_true": all_three,
            "calmar_refused": degenerate, "all_three_unmeasured": unmeasured}


def measure_one(panel_dir: Path, *, caps: Sequence[float]) -> Dict[str, object]:
    """Run the three ORIGINAL instruments on one panel and keep only the head numbers."""
    A, E = ase(), ens()
    a = A.ase_report(Path(panel_dir))
    g = A.guardian_zero_report(Path(panel_dir))
    nlf = E.run_plb_nlf(Path(panel_dir), caps=tuple(caps), verbose=False)
    frontier = nlf.get("frontier")
    if not isinstance(frontier, dict) or not frontier:
        raise ExcisionError(
            f"run_plb_nlf returned no `frontier` (keys {sorted(nlf)}) — refusing to call a "
            f"missing frontier 'not measured' when the instrument changed shape"
        )
    shapes = {}
    for cap, rows in frontier.items():
        shapes[str(cap)] = {"train": nlf_shape(rows, "train"), "test": nlf_shape(rows, "test")}
    return {
        "panel_dir": str(panel_dir),
        "books": a.get("books"), "n_books": len(a.get("books") or []),
        "axis_days": a.get("axis_days"),
        # #131 ASE
        "k_star": a.get("k_star"),
        "admitted_set_exists": a.get("admitted_set_exists"),
        "ase_refusal": a.get("refusal"),
        # #141 TUB
        "tub": tub_tally(a),
        # #132 GZ
        "gz": gz_signs(g),
        # #123 NLF
        "nlf_shapes": shapes,
        "nlf_raw_keys": sorted(nlf) if isinstance(nlf, dict) else None,
        # the two zeros, so "the overlay lost" and "the zero was already good" stay apart
        "zeros_test": {k: {"apy_net": v.get("apy_net"), "maxdd": v.get("maxdd"),
                           "calmar": v.get("calmar"),
                           "calmar_degenerate": v.get("calmar_degenerate")}
                       for k, v in (a.get("zeros_test") or {}).items()},
    }


def edx_report(panel_dir: Optional[Path] = None, *, drop: Sequence[str] = DROP_DEFAULT,
               caps: Sequence[float] = (0.02, 0.05, 0.10)) -> Dict[str, object]:
    real = Path(panel_dir) if panel_dir else ens().PANEL_DIR
    with tempfile.TemporaryDirectory(prefix="edx_panel_") as tmp:
        shadow, dropped = build_shadow_panel(real, drop, Path(tmp) / "panel")
        axis = axis_identity(real, shadow)
        full = measure_one(real, caps=caps)
        exc = measure_one(shadow, caps=caps)
    return {"real_dir": str(real), "dropped": dropped, "axis": axis,
            "full": full, "exc": exc, "flips": flip_verdicts(full, exc)}


def flip_verdicts(full: Dict[str, object], exc: Dict[str, object]) -> Dict[str, object]:
    """Per head: did the SIGN of its published verdict change when the book was removed?

    A sign flip is the order's own acceptance criterion. "Moved but kept its sign" is a third,
    separate answer and is reported as such — it is not a flip and not "no change".
    """
    out: Dict[str, object] = {}

    # #131 ASE — k* is a count, not a sign; "flip" here means k* changed.
    out["#131 ASE k*"] = {
        "full": full.get("k_star"), "exc": exc.get("k_star"),
        "flipped": full.get("k_star") != exc.get("k_star"),
    }

    # #141 TUB — the published verdict was "no row beats EW-live on all three".
    ft, et = full["tub"], exc["tub"]
    out["#141 TUB all_three"] = {
        "full": ft["all_three_true"], "exc": et["all_three_true"],
        "full_refused": ft["calmar_refused"], "exc_refused": et["calmar_refused"],
        "flipped": (ft["all_three_true"] == 0) != (et["all_three_true"] == 0),
    }

    # #132 GZ — the published verdict was dCalmar < 0 against BOTH zeros.
    gz: Dict[str, object] = {}
    for k in sorted(set(full["gz"]) | set(exc["gz"])):
        f, e = full["gz"].get(k, {}), exc["gz"].get(k, {})
        gz[k] = {"full": f.get("delta_calmar"), "exc": e.get("delta_calmar"),
                 "full_sign": f.get("sign"), "exc_sign": e.get("sign"),
                 "flipped": (f.get("sign") is not None and e.get("sign") is not None
                             and f.get("sign") != e.get("sign"))}
    out["#132 GZ dCalmar"] = gz

    # #123 NLF — the published verdict was "the frontier falls monotonically in N".
    nlf: Dict[str, object] = {}
    for cap in sorted(set(full["nlf_shapes"]) | set(exc["nlf_shapes"])):
        for half in ("train", "test"):
            f = (full["nlf_shapes"].get(cap) or {}).get(half) or {}
            e = (exc["nlf_shapes"].get(cap) or {}).get(half) or {}
            nlf[f"cap={cap}/{half}"] = {
                "full_sign": f.get("sign"), "exc_sign": e.get("sign"),
                "full_rho": f.get("spearman_n_vs_apy"), "exc_rho": e.get("spearman_n_vs_apy"),
                "full_monotone_down": f.get("monotone_down"),
                "exc_monotone_down": e.get("monotone_down"),
                "full_best_n": f.get("best_n"), "exc_best_n": e.get("best_n"),
                "flipped": (f.get("sign") is not None and e.get("sign") is not None
                            and f.get("sign") != e.get("sign")),
            }
    out["#123 NLF frontier"] = nlf
    return out


# ── §2 #146 PYD ────────────────────────────────────────────────────────────────

def payer_classes(books: Sequence[str]) -> Dict[str, object]:
    """{book: payer class} read from the DECLARED roster (`risk_shape`), never inferred.

    A book in the panel with no roster entry is NOT quietly bucketed: it lands in `unclassified`
    and is excluded from the rule, because "I do not know who pays" is a third outcome and not
    a class of its own (inv. #17).
    """
    sys.path.insert(0, str(ROOT))
    try:
        from spa_core.strategy_lab.aggressive_lab.roster import build_roster
    except Exception as exc:                                     # pragma: no cover - env guard
        raise ExcisionError(f"roster unreadable ({exc}) — refusing to invent payer classes")
    roster = build_roster()
    shape, unclassified = {}, []
    for b in books:
        s = getattr(roster.get(b), "risk_shape", None) if roster.get(b) is not None else None
        if not s:
            unclassified.append(b)
        else:
            shape[b] = s
    groups: Dict[str, List[str]] = {}
    for b, s in sorted(shape.items()):
        groups.setdefault(s, []).append(b)
    return {"shape": shape, "groups": groups, "unclassified": unclassified,
            "profile": sorted((len(v) for v in groups.values()), reverse=True)}


def partition_weights(groups: Dict[str, Sequence[str]]) -> Dict[str, float]:
    """1/n_classes per class, split equally inside the class."""
    n = len(groups)
    if n == 0:
        raise ExcisionError("no payer classes — refusing to weight nothing")
    w: Dict[str, float] = {}
    for members in groups.values():
        for b in members:
            w[b] = (1.0 / n) / len(members)
    return w


def placebo_partitions(books: Sequence[str], profile: Sequence[int], *,
                       n: int = PLACEBO_N, seed: int = PLACEBO_SEED) -> List[Dict[str, List[str]]]:
    """`n` deterministic random partitions of `books` with the IDENTICAL size profile.

    This is the control that separates "the declared taxonomy knows something" from "the
    concentration profile it implies does". Seeded: the same list on every machine and run.
    """
    if sum(profile) != len(books):
        raise ExcisionError(f"profile {list(profile)} does not cover {len(books)} books")
    rng = random.Random(seed)
    out, seen = [], set()
    for _ in range(n * 20):
        if len(out) >= n:
            break
        order = list(books)
        rng.shuffle(order)
        groups, i = {}, 0
        for j, size in enumerate(profile):
            groups[f"g{j}"] = sorted(order[i:i + size])
            i += size
        key = tuple(sorted(tuple(v) for v in groups.values()))
        if key in seen:
            continue
        seen.add(key)
        out.append(groups)
    return out


def arm(rets: Dict[str, Sequence[float]], weights: Dict[str, float], *, lo: int, hi: int,
        roundtrip: float) -> Dict[str, object]:
    """One static-weight arm, scored by the IMPORTED scorer so it stays comparable."""
    S = sfs()
    d = dict(S.static_weighted(rets, weights, lo=lo, hi=hi, roundtrip=roundtrip))
    d["calmar_degenerate"] = S.calmar_degenerate(d.get("maxdd"))
    d["max_name_weight"] = max(weights.values()) if weights else None
    d["over_policy_cap"] = bool(weights) and max(weights.values()) > POLICY_CAP + 1e-12
    return d


def pyd_report(panel_dir: Optional[Path] = None, *, drop: Sequence[str] = (),
               placebo_n: int = PLACEBO_N, split: Optional[str] = None) -> Dict[str, object]:
    E, S = ens(), sfs()
    real = Path(panel_dir) if panel_dir else E.PANEL_DIR
    panel = E.load_panel(real)
    for b in drop:
        panel.pop(b, None)
    axis = E.common_axis(panel)
    books = sorted(panel)
    rets = {b: [panel[b][d] for d in axis] for b in books}
    n = len(axis)
    seam = split or E.PLB_SPLIT
    ti = sum(1 for d in axis if d <= seam)
    if not (60 <= ti <= n - 60):
        raise ExcisionError(
            f"split {seam} leaves TRAIN {ti} / TEST {n - ti} of {n} days — refusing to judge "
            f"out-of-sample on a half that short"
        )
    toll = S.ROUNDTRIP

    cls = payer_classes(books)
    groups = cls["groups"]
    scorable = [b for b in books if b in cls["shape"]]
    if cls["unclassified"]:
        # the rule is defined only over classified books; EW is printed over BOTH universes so
        # "PYD wins" cannot be an artefact of a smaller universe.
        pass

    halves = {"full": (0, n), "train": (0, ti), "test": (ti, n)}

    def score(weights: Dict[str, float]) -> Dict[str, object]:
        return {k: arm(rets, weights, lo=lo, hi=hi, roundtrip=toll)
                for k, (lo, hi) in halves.items()}

    ew_all = {b: 1.0 / len(books) for b in books}
    ew_cls = {b: 1.0 / len(scorable) for b in scorable}
    pyd = partition_weights(groups)

    arms = {
        f"EW-{len(books)} (ноль реестра)": score(ew_all),
        f"EW-{len(scorable)} (классифицированные — ноль для PYD)": score(ew_cls),
        f"PYD 1/{len(groups)} по плательщику": score(pyd),
    }
    per_class = {
        f"EW внутри класса {name} ({len(members)})": score({b: 1.0 / len(members) for b in members})
        for name, members in sorted(groups.items())
    }

    placebos = placebo_partitions(scorable, cls["profile"], n=placebo_n)
    pl_rows = []
    for g in placebos:
        w = partition_weights(g)
        r = arm(rets, w, lo=ti, hi=n, roundtrip=toll)
        f = arm(rets, w, lo=0, hi=n, roundtrip=toll)
        pl_rows.append({"test_calmar": r.get("calmar"), "test_apy": r.get("apy_net"),
                        "test_maxdd": r.get("maxdd"), "full_calmar": f.get("calmar"),
                        "test_degenerate": r.get("calmar_degenerate")})

    def pct_rank(value: Optional[float], key: str) -> Dict[str, object]:
        vals = [r[key] for r in pl_rows if r[key] is not None]
        if value is None or len(vals) < 20:
            return {"percentile": None,
                    "unmeasured": f"{len(vals)} usable placebos / value={value}"}
        below = sum(1 for v in vals if v < value)
        return {"percentile": below / len(vals) * 100.0, "n": len(vals),
                "median": statistics.median(vals), "best": max(vals), "worst": min(vals)}

    pyd_test = arms[f"PYD 1/{len(groups)} по плательщику"]["test"]
    pyd_full = arms[f"PYD 1/{len(groups)} по плательщику"]["full"]
    return {
        "panel_dir": str(real), "dropped": list(drop),
        "axis_days": n, "train_days": ti, "test_days": n - ti, "split": seam,
        "toll_roundtrip": toll, "books": books,
        "classes": cls, "weights_pyd": pyd,
        "arms": arms, "per_class": per_class,
        "placebo": {
            "n_requested": placebo_n, "n_built": len(pl_rows), "seed": PLACEBO_SEED,
            "profile": cls["profile"],
            "test_calmar": pct_rank(pyd_test.get("calmar"), "test_calmar"),
            "test_apy": pct_rank(pyd_test.get("apy_net"), "test_apy"),
            "full_calmar": pct_rank(pyd_full.get("calmar"), "full_calmar"),
        },
    }


# ── printing ───────────────────────────────────────────────────────────────────

def _f(x, *, pct: bool = False, nd: int = 2, dash: str = "НЕ ИЗМЕРЕН") -> str:
    if x is None:
        return dash
    return f"{x * 100:.{nd}f} %" if pct else f"{x:.{nd}f}"


def print_edx(rep: Dict[str, object]) -> None:
    f, e, fl = rep["full"], rep["exc"], rep["flips"]
    print(f"\n{'=' * 92}")
    print("#145 EDX — ИСПОЛНЕНИЕ ЗАКАЗА #143: головы отрицательного ряда БЕЗ "
          f"{', '.join(rep['dropped'])}  (advisory, [bt])")
    print(f"{'=' * 92}")
    ax = rep["axis"]
    print(f"\n§0 ПРЕДПОСЫЛКА (измерена, не предположена): ось полной панели {ax['full_days']} дн "
          f"{ax['full_span'][0]}..{ax['full_span'][1]}; после выреза {ax['exc_days']} дн; "
          f"выросла на {ax['grew_by']} ⇒ оси {'ТОЖДЕСТВЕННЫ' if ax['identical'] else 'РАЗНЫЕ'}.")
    print(f"    книг: {f['n_books']} -> {e['n_books']}; вырезано {rep['dropped']}")
    print("    Сравнение чисто ПО ЗАМЕРУ: оба прогона судят одни и те же дни теми же приборами.")

    print("\n§1 #131 ASE — k* (сколько имён надо допустить, чтобы сайзер заговорил)")
    k = fl["#131 ASE k*"]
    print(f"    k* полная {k['full']}  ->  без выреза {k['exc']}  ⇒ "
          f"{'ИЗМЕНИЛСЯ' if k['flipped'] else 'НЕ изменился'}")
    print(f"    множество существует: {f['admitted_set_exists']} -> {e['admitted_set_exists']}")

    print("\n§2 #141 TUB — строк, обогнавших EW-live по ВСЕМ ТРЁМ условиям #129")
    t = fl["#141 TUB all_three"]
    print(f"    all_three=True: полная {t['full']}/{f['tub']['n_rows']}  ->  "
          f"без выреза {t['exc']}/{e['tub']['n_rows']}  ⇒ "
          f"{'ЗНАК СМЕНИЛСЯ' if t['flipped'] else 'знак ТОТ ЖЕ'}")
    print(f"    знаменатель ОТКАЗАН (calmar_degenerate): {t['full_refused']} -> {t['exc_refused']}"
          "   («оверлей проиграл» и «знаменатель меньше пошлины» — разные ответы)")
    print(f"    {'правило · сайзер':24}{'TEST APY полн':>14}{'TEST APY выр':>14}"
          f"{'Cal полн':>10}{'Cal выр':>10}{'3 усл. п/в':>12}")
    fmap = {(r["rule"], r["sizer"]): r for r in f["tub"]["rows"]}
    emap = {(r["rule"], r["sizer"]): r for r in e["tub"]["rows"]}
    for key in sorted(set(fmap) | set(emap)):
        a, b = fmap.get(key, {}), emap.get(key, {})
        lbl = f"{key[0]} · {'1/σ' if key[1] == 'inv_sigma' else 'ew'}"
        ca = "ОТКАЗАН" if a.get("calmar_degenerate") else _f(a.get("test_calmar"))
        cb = "ОТКАЗАН" if b.get("calmar_degenerate") else _f(b.get("test_calmar"))
        print(f"    {lbl:24}{_f(a.get('test_apy_net'), pct=True):>14}"
              f"{_f(b.get('test_apy_net'), pct=True):>14}{ca:>10}{cb:>10}"
              f"{str(a.get('all_three')) + '/' + str(b.get('all_three')):>12}")

    print("\n§3 #132 GZ — ΔCalmar флагманского оверлея #1 против ОБОИХ нулей")
    print("    (ЗНАМЕНАТЕЛЬ печатается рядом: ΔCalmar +2 на просадке 40 bp и на просадке 5 % —"
          " разные утверждения, и пошлина реестра 96 bp)")
    print(f"    {'ноль · оверлей':28}{'Δ полная':>10}{'Δ выреза':>10}"
          f"{'maxDD нуля п/в':>18}{'перекл. п/в':>13}{'знак':>15}")
    fg, eg = f["gz"], e["gz"]
    for k2, v in sorted(fl["#132 GZ dCalmar"].items()):
        a, b = fg.get(k2, {}), eg.get(k2, {})
        verdict = ("ЗНАК СМЕНИЛСЯ" if v["flipped"]
                   else f"{v['full_sign']}/{v['exc_sign']}" if v["full_sign"] else "НЕ ИЗМЕРЕН")
        dd = f"{_f(a.get('base_maxdd'), pct=True, nd=2)}/{_f(b.get('base_maxdd'), pct=True, nd=2)}"
        sw = f"{a.get('switches')}/{b.get('switches')}"
        print(f"    {k2:28}{_f(v['full'], nd=3):>10}{_f(v['exc'], nd=3):>10}"
              f"{dd:>18}{sw:>13}{verdict:>15}")

    print("\n§4 #123 NLF — падает ли граница по числу ног N (знак ρ(N, APY))")
    print(f"    {'cap · половина':24}{'ρ полная':>11}{'ρ выреза':>11}{'моно↓ п/в':>12}"
          f"{'лучшее N п/в':>14}{'знак':>16}")
    for k2, v in sorted(fl["#123 NLF frontier"].items()):
        verdict = ("ЗНАК СМЕНИЛСЯ" if v["flipped"]
                   else f"{v['full_sign']}/{v['exc_sign']}" if v["full_sign"] else "НЕ ИЗМЕРЕН")
        print(f"    {k2:24}{_f(v['full_rho'], nd=3):>11}{_f(v['exc_rho'], nd=3):>11}"
              f"{str(v['full_monotone_down']) + '/' + str(v['exc_monotone_down']):>12}"
              f"{str(v['full_best_n']) + '/' + str(v['exc_best_n']):>14}{verdict:>16}")

    print("\n§5 НОЛЬ, против которого всё мерилось (TEST) — «оверлей плох» ≠ «ноль уже хорош»")
    for name in sorted(set(f["zeros_test"]) | set(e["zeros_test"])):
        a, b = f["zeros_test"].get(name, {}), e["zeros_test"].get(name, {})
        print(f"    {name:12} полная APY {_f(a.get('apy_net'), pct=True):>9} "
              f"maxDD {_f(a.get('maxdd'), pct=True):>8} Cal {_f(a.get('calmar')):>7}"
              f"   |   вырез APY {_f(b.get('apy_net'), pct=True):>9} "
              f"maxDD {_f(b.get('maxdd'), pct=True):>8} Cal {_f(b.get('calmar')):>7}")

    flips = [k2 for k2, v in fl.items()
             if (v.get("flipped") if "flipped" in v
                 else any(x.get("flipped") for x in v.values()))]
    print("\n§6 ОТВЕТ НА ЗАКАЗ #143")
    print(f"    голов перемерено: 4 · со СМЕНОЙ знака/значения: {len(flips)} -> {flips}")


def print_pyd(rep: Dict[str, object]) -> None:
    print(f"\n{'=' * 92}")
    print("#146 PYD — Payer-Class Diversification: делить капитал по ПЛАТЕЛЬЩИКУ, а не по книгам"
          "  (advisory, [bt])")
    print(f"{'=' * 92}")
    c = rep["classes"]
    print(f"\n§0 ТАКСОНОМИЯ ОБЪЯВЛЕНА, А НЕ ПОДОБРАНА — `risk_shape` из roster.py (лежит в git "
          "задолго до этого замера; свободных параметров у правила НОЛЬ)")
    print(f"    ось {rep['axis_days']} дн · TRAIN {rep['train_days']} (<= {rep['split']}) · "
          f"TEST {rep['test_days']} · пошлина {rep['toll_roundtrip'] * 100:.2f} % разово")
    for name, members in sorted(c["groups"].items()):
        print(f"    {name:18} ({len(members)}) {', '.join(members)}")
    if c["unclassified"]:
        print(f"    НЕ КЛАССИФИЦИРОВАНЫ (из правила исключены, не ссыпаны в класс): "
              f"{c['unclassified']}")
    print(f"    профиль размеров классов: {c['profile']}")
    print("    веса PYD: " + " · ".join(f"{b} {w * 100:.1f} %"
                                        for b, w in sorted(rep["weights_pyd"].items(),
                                                           key=lambda kv: -kv[1])))

    print("\n§1 РУКАВА (хвост ВСЕГДА рядом с доходностью)")
    print(f"    {'рукав':46}{'TRAIN APY':>11}{'TEST APY':>11}{'TEST maxDD':>12}"
          f"{'TEST Cal':>10}{'макс/имя':>10}")
    for label, d in list(rep["arms"].items()) + list(rep["per_class"].items()):
        tr, te = d["train"], d["test"]
        cal = "ОТКАЗАН" if te.get("calmar_degenerate") else _f(te.get("calmar"))
        cap = _f(te.get("max_name_weight"), pct=True, nd=1)
        flag = " ⚠>cap" if te.get("over_policy_cap") else ""
        print(f"    {label:46}{_f(tr.get('apy_net'), pct=True):>11}"
              f"{_f(te.get('apy_net'), pct=True):>11}{_f(te.get('maxdd'), pct=True):>12}"
              f"{cal:>10}{cap:>10}{flag}")

    p = rep["placebo"]
    print(f"\n§2 ПЛАЦЕБО — {p['n_built']} случайных разбиений С ТЕМ ЖЕ профилем {p['profile']} "
          f"(seed {p['seed']}, детерминировано)")
    print("    Вопрос: знает ли что-то ОБЪЯВЛЕННАЯ таксономия — или знает только профиль "
          "концентрации, который она задаёт?")
    for key, label in (("test_calmar", "TEST Calmar"), ("test_apy", "TEST APY"),
                       ("full_calmar", "FULL Calmar")):
        d = p[key]
        if d.get("percentile") is None:
            print(f"    {label:14} НЕ ИЗМЕРЕНО: {d.get('unmeasured')}")
            continue
        print(f"    {label:14} PYD — перцентиль {d['percentile']:5.1f} % среди {d['n']} плацебо "
              f"(медиана {_f(d['median'])}, лучшее {_f(d['best'])}, худшее {_f(d['worst'])})")


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="#145 EDX + #146 PYD (advisory, read-only)")
    ap.add_argument("--panel", default=None, help="panel dir (default data/aggressive_lab)")
    ap.add_argument("--section", choices=("edx", "pyd", "both"), default="both")
    ap.add_argument("--drop", nargs="*", default=list(DROP_DEFAULT),
                    help="books to excise in §1 (#143 names eth_directional)")
    ap.add_argument("--pyd-drop", nargs="*", default=[],
                    help="books to excise before §2 (empty = full panel)")
    ap.add_argument("--placebo", type=int, default=PLACEBO_N)
    ap.add_argument("--split", default=None,
                    help="TRAIN/TEST seam for §2 (default: the harness PLB_SPLIT)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    panel = Path(a.panel) if a.panel else None
    out: Dict[str, object] = {}
    if a.section in ("edx", "both"):
        out["edx"] = edx_report(panel, drop=tuple(a.drop))
        if not a.json:
            print_edx(out["edx"])
    if a.section in ("pyd", "both"):
        out["pyd"] = pyd_report(panel, drop=tuple(a.pyd_drop), placebo_n=a.placebo,
                                split=a.split)
        if not a.json:
            print_pyd(out["pyd"])
    if a.json:
        print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
