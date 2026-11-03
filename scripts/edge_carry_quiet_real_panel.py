#!/usr/bin/env python3
"""
scripts/edge_carry_quiet_real_panel.py — registry idea #151 (CQR)

EXECUTES THE ORDER LEFT BY #150 (verbatim):

    "Применить тот же CARRY-3+cash тест к реальной 10-книжной панели, когда она будет
     доступна в облаке. Ожидаемое: на живом lrt_carry проверить, мала ли его TRAIN maxDD
     до апрельского depeg — если да, вывод фикстуры воспроизведётся. Запрет #149 остаётся:
     новый сайзер не предлагать до >= 90 дней живых марок."

  #150 could only reach the code-generated FIXTURE: the real panel (`data/aggressive_lab/`)
  is gitignored and lives only on the owner's Mac.  This run is on the REAL panel — 10 books,
  852 common days, 2024-03-06..2026-07-05, loaded through the canonical harness.

WHY THIS IS NOT A NEW SIZER (the #149 prohibition is NOT touched).  #149 forbade proposing a
new SIZER on this panel until >= 90 days of live marks exist.  This script proposes nothing:
it measures two arms that ALREADY EXIST in the registry (QUIET-N, the surviving winner of
#149, and CARRY-3+cash, the control #150 built) and prints the difference the order asked for.
Whether the live-marks precondition has arrived is a separate question, measured by its own
instrument — `scripts/edge_live_marks_gate.py` (idea #152).

DECLARED SELECTORS — every one fixed BEFORE any TEST number was computed.  None is tuned.
  CARRY-3        top 3 by TRAIN APY among NON-DIRECTIONAL books.
                 ADAPTATION, stated before the run: the fixture had a declared "headline APY"
                 per book; the real panel has no headline, so the only honest analogue is the
                 book's own TRAIN-realised APY.  TRAIN-only — no look-ahead.
  DIRECTIONAL    `eth_directional` and nothing else.  This is the ROSTER's own classification
                 (`aggressive_lab/roster.py`: "Class B (beta — NOT alpha)"), the same book
                 #145 EDX excised.  Chosen by the roster, not by this script.
  CARRY-3+cash   75 % EW(CARRY-3) + 25 % cash at exactly 0 %/day.  The toll is charged once,
                 on day one, on the DEPLOYED fraction — the canonical `arm(deployed=)` of #149,
                 imported rather than reimplemented so the rows stay comparable.
  QUIET-N        EW of the N books with the lowest TRAIN maxDD, ties broken ALPHABETICALLY
                 (declared: the real panel has an exact 0.0000 tie, so a tie-break is not
                 optional).  All 10 books eligible as sorting foils, per #150's convention.
                 N in {2, 3, 4}: N=2 matches #150's fixture arm, N=4 is #149's winner.
  QUIET-N-MEASURED  the honest variant #149 raised but never ran: lowest TRAIN maxDD among
                 only those books whose TRAIN maxDD is ABOVE the toll — i.e. books actually
                 OBSERVED losing.  A book below the toll has not been observed to lose; its
                 drawdown is UNMEASURED, not zero (inv. #17).
  SEAMS          2025-06-30 and 2026-01-01, inherited verbatim from #143/#145/#146/#148/#149.
  PLACEBO        EXHAUSTIVE, not sampled: all C(9,3) = 84 three-book subsets of the
                 non-directional universe, each run as CARRY-3+cash.  The universe is small
                 enough to enumerate, so there is no seed and no sampling error to declare —
                 a stronger control than #149's 2000 permutations, not a weaker one.

ACCEPTANCE (the order's own, printed not asserted): the APY and maxDD difference between
QUIET-4 and CARRY-3+cash on both seams, against the 96 bp round-trip toll.  If |dAPY| is
WITHIN the toll the arms are indistinguishable and QUIET-4 must be RENAMED in the registry
to what it actually is.

FAIL-CLOSED / THIRD OUTCOME (inv. #17).  A panel that cannot be read is `PanelUnmeasured`
with a named reason and exit code 2 — never a clean zero and never an invented row.
"Measured and equal to zero" (a book that moved and did not lose) and "not measured" (a book
that never moved) are printed as DIFFERENT answers, because QUIET-N's whole selection rests
on telling them apart.

IS_ADVISORY = True · OUTSIDE_RISKPOLICY = True
No capital moves.  RiskPolicy v1.0 untouched.  The go-live track
(data/equity_curve_daily.json) is never opened.  The 20 %/name ceiling and the kill-switch
rungs are READ, never changed.  stdlib-only, deterministic, read-only, LLM FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import importlib.util
import itertools
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

IS_ADVISORY = True
OUTSIDE_RISKPOLICY = True

ROOT = Path(__file__).resolve().parent.parent
ENSEMBLE = ROOT / "scripts" / "edge_real_panel_ensemble.py"
POPULATION = ROOT / "scripts" / "edge_measurable_population.py"

#: the two OOS seams of #143/#145/#146/#148/#149 — reused verbatim so rows stay comparable.
SEAMS: Tuple[str, ...] = ("2025-06-30", "2026-01-01")
#: the roster's own Class-B book; the only name excluded from CARRY-3.
DIRECTIONAL: Tuple[str, ...] = ("eth_directional",)
#: CARRY-3+cash holds this much in cash at exactly 0 %/day.
CASH_FRACTION = 0.25
#: how many books CARRY-N buys. 3, to match the arm #150 built.
CARRY_N = 3
#: QUIET arms reported. 2 matches #150's fixture arm; 4 is #149's surviving winner.
QUIET_NS: Tuple[int, ...] = (2, 3, 4)

_MOD: Dict[str, object] = {}


class PanelUnmeasured(RuntimeError):
    """Fail-CLOSED: the panel could not be read, so NOTHING is reported as measured."""


def _load(path: Path, name: str):
    if name in _MOD:
        return _MOD[name]
    if not path.exists():
        raise PanelUnmeasured(f"{name}: {path} missing — refusing to reimplement it")
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    _MOD[name] = mod
    return mod


def ens():
    return _load(ENSEMBLE, "edge_real_panel_ensemble")


def pop():
    return _load(POPULATION, "edge_measurable_population")


def toll() -> float:
    """The 96 bp round-trip toll, READ from the harness that declares it (#10/#49)."""
    return float(ens().PLB_ROUNDTRIP)


def load_axis(panel_dir: Path) -> Tuple[List[str], Dict[str, List[float]], List[str]]:
    """(axis, returns-by-book, books) through the canonical loader. Fail-CLOSED."""
    if not panel_dir.exists():
        raise PanelUnmeasured(f"panel dir absent: {panel_dir}")
    try:
        return ens().plb_load(panel_dir)
    except PanelUnmeasured:
        raise
    except Exception as exc:  # the loader's own refusals are reasons, not zeros
        raise PanelUnmeasured(f"panel at {panel_dir} not usable: {exc}") from exc


def seam_index(axis: Sequence[str], seam: str) -> int:
    """TRAIN length = days up to and including the seam. Fail-CLOSED on a useless split."""
    hi = sum(1 for d in axis if d <= seam)
    if hi < 60 or len(axis) - hi < 60:
        raise PanelUnmeasured(
            f"seam {seam} splits {len(axis)} days into {hi}/{len(axis) - hi} — "
            f"refusing to judge an arm on fewer than 60 days a side"
        )
    return hi


def book_stats(rets: Dict[str, Sequence[float]], books: Sequence[str],
               *, lo: int, hi: int) -> Dict[str, dict]:
    """Per book over [lo, hi): apy, maxdd (positive), how many days it MOVED, measurability.

    `moves` is why this helper exists rather than a bare call to `perf`: in the aligned panel a
    frozen book is a run of 0.0 returns and its maxDD is 0.0000 — numerically identical to a
    book that traded every day and never lost. QUIET-N selects on exactly that number, so the
    two cases have to be distinguishable here (inv. #17).
    """
    e, t = ens(), toll()
    out: Dict[str, dict] = {}
    for b in books:
        window = list(rets[b][lo:hi])
        p = e.perf(window)
        mdd = abs(p["maxdd"])
        moves = sum(1 for r in window if abs(r) > 1e-12)
        out[b] = {
            "apy": p["apy"], "maxdd": mdd, "moves": moves, "days": len(window),
            "measurable": mdd > t,
            # "never moved" is NOT "moved and did not lose" — the distinction QUIET-N rests on
            "unmeasured": "never moved" if moves == 0 else (None if mdd > t else "maxDD below toll"),
        }
    return out


def carry_pick(train: Dict[str, dict], books: Sequence[str], *, n: int = CARRY_N,
               directional: Sequence[str] = DIRECTIONAL) -> List[str]:
    """Top `n` by TRAIN APY among non-directional books. Deterministic: ties break by name."""
    pool = [b for b in books if b not in set(directional)]
    if len(pool) < n:
        raise PanelUnmeasured(f"only {len(pool)} non-directional books — cannot pick {n}")
    return sorted(pool, key=lambda b: (-train[b]["apy"], b))[:n]


def quiet_pick(train: Dict[str, dict], books: Sequence[str], *, n: int,
               measured_only: bool = False) -> List[str]:
    """`n` books with the lowest TRAIN maxDD; ties ALPHABETICAL (the real panel has one).

    `measured_only` restricts the pool to books whose TRAIN drawdown is ABOVE the toll — the
    variant #149 raised in prose and never ran.
    """
    pool = [b for b in books if train[b]["measurable"]] if measured_only else list(books)
    if len(pool) < n:
        raise PanelUnmeasured(
            f"pool has {len(pool)} books, need {n}"
            + (" (measured-only: too few books were ever observed losing)" if measured_only else "")
        )
    return sorted(pool, key=lambda b: (train[b]["maxdd"], b))[:n]


def ew(sub: Sequence[str]) -> Dict[str, float]:
    if not sub:
        raise PanelUnmeasured("empty subset — refusing to report a portfolio of nothing")
    return {b: 1.0 / len(sub) for b in sub}


def run_arm(rets: Dict[str, Sequence[float]], sub: Sequence[str], *, lo: int, hi: int,
            deployed: float = 1.0) -> Dict[str, float]:
    """One static equal-weight arm through #149's canonical `arm()` — toll once, cash at 0 %."""
    return pop().arm(rets, ew(sub), lo=lo, hi=hi, roundtrip=toll(), deployed=deployed)


def placebo_exhaustive(rets: Dict[str, Sequence[float]], books: Sequence[str], *,
                       lo: int, hi: int, n: int = CARRY_N,
                       directional: Sequence[str] = DIRECTIONAL) -> Dict[str, object]:
    """EVERY n-subset of the non-directional universe, run as CARRY-n+cash.

    Exhaustive on purpose: C(9,3) = 84 is enumerable, so the control carries no seed and no
    sampling error. Returns the percentile of each measure plus how many subsets could produce
    a measurable drawdown at all — the second number is the one that decides whether the
    "risk lower" half of the claim is answerable on this panel.
    """
    pool = sorted(b for b in books if b not in set(directional))
    subsets = list(itertools.combinations(pool, n))
    if len(subsets) < 10:
        raise PanelUnmeasured(f"only {len(subsets)} subsets — refusing to call that a placebo")
    rows = [(s, run_arm(rets, list(s), lo=lo, hi=hi, deployed=1.0 - CASH_FRACTION))
            for s in subsets]
    apys = sorted(p["apy"] for _, p in rows)
    best = max(rows, key=lambda r: r[1]["apy"])
    return {
        "n_subsets": len(subsets), "apys": apys,
        "median": apys[len(apys) // 2], "best": apys[-1], "worst": apys[0],
        "best_subset": list(best[0]),
        "n_measurable": sum(1 for _, p in rows if p["maxdd"] > toll()),
    }


def percentile_of(values: Sequence[float], actual: float) -> float:
    """Share of the placebo population strictly below `actual`, in percent."""
    if not values:
        raise PanelUnmeasured("empty placebo population — no percentile exists")
    return 100.0 * sum(1 for v in values if v < actual) / len(values)


def seam_report(axis: Sequence[str], rets: Dict[str, Sequence[float]], books: Sequence[str],
                seam: str) -> Dict[str, object]:
    """Everything the order asked for, on one seam. Computes; prints nothing."""
    hi = seam_index(axis, seam)
    train = book_stats(rets, books, lo=0, hi=hi)
    test = book_stats(rets, books, lo=hi, hi=len(axis))
    carry3 = carry_pick(train, books)

    arms: List[dict] = [{
        "label": "EW-10 (ноль реестра)", "books": list(books), "deployed": 1.0,
        "perf": run_arm(rets, books, lo=hi, hi=len(axis)),
    }]
    quiet_sets: Dict[int, List[str]] = {}
    for n in QUIET_NS:
        sub = quiet_pick(train, books, n=n)
        quiet_sets[n] = sub
        arms.append({"label": f"QUIET-{n}", "books": sub, "deployed": 1.0,
                     "perf": run_arm(rets, sub, lo=hi, hi=len(axis))})
    # the honest variant #149 raised: only books actually observed losing are eligible
    measured_sub: Optional[List[str]] = None
    measured_reason: Optional[str] = None
    try:
        measured_sub = quiet_pick(train, books, n=CARRY_N, measured_only=True)
        arms.append({"label": f"QUIET-{CARRY_N}-ИЗМЕРИМЫХ", "books": measured_sub,
                     "deployed": 1.0,
                     "perf": run_arm(rets, measured_sub, lo=hi, hi=len(axis))})
    except PanelUnmeasured as exc:
        measured_reason = str(exc)

    carry_perf = run_arm(rets, carry3, lo=hi, hi=len(axis), deployed=1.0 - CASH_FRACTION)
    arms.append({"label": f"CARRY-{CARRY_N} + {CASH_FRACTION * 100:.0f} % кэша",
                 "books": carry3, "deployed": 1.0 - CASH_FRACTION, "perf": carry_perf})

    q_top = quiet_sets[max(QUIET_NS)]
    q_perf = next(a["perf"] for a in arms if a["label"] == f"QUIET-{max(QUIET_NS)}")
    d_apy = q_perf["apy"] - carry_perf["apy"]
    d_dd = q_perf["maxdd"] - carry_perf["maxdd"]

    placebo = placebo_exhaustive(rets, books, lo=hi, hi=len(axis))

    # QUIET composition: how much of each arm sits in books never observed losing
    composition = {
        n: {
            "books": quiet_sets[n],
            "n_unmeasured": sum(1 for b in quiet_sets[n] if not train[b]["measurable"]),
            "n_never_moved": sum(1 for b in quiet_sets[n] if train[b]["moves"] == 0),
        } for n in QUIET_NS
    }
    return {
        "seam": seam, "train_days": hi, "test_days": len(axis) - hi,
        "train": train, "test": test, "carry3": carry3, "arms": arms,
        "quiet_sets": quiet_sets, "quiet_top": q_top,
        "measured_sub": measured_sub, "measured_reason": measured_reason,
        "d_apy": d_apy, "d_maxdd": d_dd, "toll": toll(),
        "within_toll": abs(d_apy) <= toll(),
        "carry_dominates": (carry_perf["apy"] > q_perf["apy"]
                            and carry_perf["maxdd"] < q_perf["maxdd"]),
        "placebo": placebo,
        "placebo_pct_apy": percentile_of(placebo["apys"], carry_perf["apy"]),
        "composition": composition,
    }


def report(panel_dir: Path, *, seams: Sequence[str] = SEAMS) -> Dict[str, object]:
    axis, rets, books = load_axis(panel_dir)
    return {
        "panel_dir": str(panel_dir), "axis_days": len(axis),
        "first": axis[0], "last": axis[-1], "books": books, "toll": toll(),
        "seams": [seam_report(axis, rets, books, s) for s in seams],
    }


def _cal(p: Dict[str, float]) -> str:
    """Calmar, or the word ОТКАЗАН when the denominator is below the toll (#129)."""
    return "ОТКАЗАН" if p.get("calmar_refused") else f"{p['apy'] / p['maxdd']:.3f}"


def print_report(rep: Dict[str, object]) -> None:
    t = float(rep["toll"])
    print("=" * 94)
    print("#151 CQR — CARRY-3+cash против QUIET-N на РЕАЛЬНОЙ панели (исполнение заказа #150)")
    print("=" * 94)
    print(f"панель: {rep['panel_dir']}")
    print(f"книг: {len(rep['books'])} · общая ось: {rep['axis_days']} дн. "
          f"{rep['first']}..{rep['last']} · пошлина: {t * 100:.2f} %")
    print(f"книги: {', '.join(rep['books'])}")
    print("\nВСЕ СЕЛЕКТОРЫ ОБЪЯВЛЕНЫ ДО ПРОГОНА (см. docstring): CARRY-3 = топ-3 по TRAIN APY "
          f"без {'/'.join(DIRECTIONAL)} · QUIET-N = N книг с наименьшей TRAIN maxDD "
          "(ничья — по алфавиту) · кэш 25 % под РОВНО 0 %")

    for s in rep["seams"]:
        print("\n" + "#" * 94)
        print(f"ШОВ {s['seam']} · TRAIN {s['train_days']} дн. · TEST {s['test_days']} дн.")
        print("#" * 94)
        print("\nПО КНИГАМ (TRAIN слева — на нём ТОЛЬКО и выбирают; TEST справа):")
        print(f"  {'книга':20s} {'TR ходов':>8s} {'TR maxDD%':>10s} {'TR APY%':>8s} "
              f"{'TE APY%':>8s} {'TE maxDD%':>10s}  род TRAIN-просадки")
        order = sorted(rep["books"], key=lambda b: (s["train"][b]["maxdd"], b))
        for b in order:
            tr, te = s["train"][b], s["test"][b]
            kind = ("НЕ ИЗМЕРЕНА: книга не двигалась" if tr["moves"] == 0 else
                    "измерена" if tr["measurable"] else "НЕ ИЗМЕРЕНА: ниже пошлины")
            print(f"  {b:20s} {tr['moves']:8d} {tr['maxdd'] * 100:10.4f} {tr['apy'] * 100:8.2f} "
                  f"{te['apy'] * 100:8.2f} {te['maxdd'] * 100:10.4f}  {kind}")

        print(f"\nCARRY-{CARRY_N} (топ TRAIN APY, без направленной) = {s['carry3']}")
        print("\nРУКАВА НА TEST (хвост РЯДОМ с доходом, инв. #8; Calmar на вырожденном "
              "знаменателе = ОТКАЗАН, #129):")
        print(f"  {'рукав':26s} {'APY%':>8s} {'maxDD%':>9s} {'Calmar':>9s}  состав")
        for a in s["arms"]:
            p = a["perf"]
            print(f"  {a['label']:26s} {p['apy'] * 100:8.2f} {p['maxdd'] * 100:9.4f} "
                  f"{_cal(p):>9s}  {','.join(a['books'])}")
        if s["measured_reason"]:
            print(f"  QUIET-{CARRY_N}-ИЗМЕРИМЫХ: НЕ ИЗМЕРЕНО — {s['measured_reason']}")

        print(f"\nПРИЁМКА ЗАКАЗА #150 (QUIET-{max(QUIET_NS)} против CARRY-{CARRY_N}+кэш):")
        print(f"  ΔAPY   = {s['d_apy'] * 100:+.2f} pp   против пошлины {t * 100:.2f} pp"
              f"  ⇒ {'В ПРЕДЕЛАХ пошлины ⇒ рукава НЕРАЗЛИЧИМЫ' if s['within_toll'] else 'ВНЕ пошлины ⇒ различимы'}")
        print(f"  ΔmaxDD = {s['d_maxdd'] * 100:+.4f} pp")
        if s["carry_dominates"]:
            print(f"  CARRY-{CARRY_N}+кэш ДОМИНИРУЕТ СТРОГО: и доход выше, и хвост ниже.")

        print(f"\nСОСТАВ QUIET-N — на чём именно стоит отбор:")
        for n in QUIET_NS:
            c = s["composition"][n]
            print(f"  QUIET-{n}: {c['n_unmeasured']}/{n} книг с НЕ ИЗМЕРЕННОЙ TRAIN-просадкой"
                  f" · {c['n_never_moved']}/{n} не двигались ВОВСЕ · {','.join(c['books'])}")

        pl = s["placebo"]
        print(f"\nИСЧЕРПЫВАЮЩЕЕ ПЛАЦЕБО — все C(9,{CARRY_N}) = {pl['n_subsets']} троек + кэш "
              "(без семени: население перечислено целиком):")
        print(f"  перцентиль APY CARRY-{CARRY_N} = {s['placebo_pct_apy']:.1f} % · "
              f"медиана {pl['median'] * 100:.2f} % · лучшее {pl['best'] * 100:.2f} % "
              f"({','.join(pl['best_subset'])}) · худшее {pl['worst'] * 100:.2f} %")
        print(f"  троек, способных произвести ИЗМЕРИМУЮ просадку (> {t * 100:.2f} %): "
              f"{pl['n_measurable']} из {pl['n_subsets']}"
              + ("  ⇒ половина «риск ниже» на этом шве НЕ ОТВЕЧАЕМА НИ ДЛЯ ОДНОГО рукава"
                 if pl["n_measurable"] == 0 else ""))

    print("\n" + "=" * 94)
    print("IS_ADVISORY=True · OUTSIDE_RISKPOLICY=True · RiskPolicy v1.0 не тронута · "
          "живой трек не открыт")
    print("Нового сайзера НЕ предложено — запрет #149 не задет (мерены рукава, уже лежащие "
          "в реестре).")
    print("=" * 94)


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="#151 CQR — order #150 on the REAL panel")
    ap.add_argument("--panel-dir", default=None,
                    help="panel directory (default: <repo>/data/aggressive_lab). The real panel "
                         "is gitignored, so a run from a worktree must name the prod path.")
    ns = ap.parse_args(list(argv) if argv is not None else None)
    panel = Path(ns.panel_dir) if ns.panel_dir else ROOT / "data" / "aggressive_lab"
    try:
        print_report(report(panel))
    except PanelUnmeasured as exc:
        print(f"НЕ ИЗМЕРЕНО: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
