#!/usr/bin/env python3
"""
scripts/edge_live_marks_gate.py — registry idea #152 (LMG: Live-Marks Gate)

THE QUESTION.  #149 closed the registry's sizer class with a PROHIBITION, and #150 restated it:

    "новый сайзер на этой панели больше НЕ предлагать до появления >= 90 дней живых марок
     (`exit_nav.json` против форвардных NAV) — #148 §2 измерил, что измеримой просадки в
     живых рядах нет НИ ОДНОЙ."

  That prohibition has a COUNTER in it, and nobody has ever read the counter.  This instrument
  reads it.  The panel's own forward block turned 90 rows on 2026-11-02, so the gate is at its
  stated number TODAY — which makes "is the number the right unit?" a question with a deadline
  rather than a philosophical one.

WHY THIS IS NOT #148 §2 AGAIN.  `edge_measurable_population.forward_measurability` looks at
TWO sources: `data/rates_desk/equity_track.jsonl` and `data/swarm/blend_forward.json`.  It
does NOT look at the forward block of the ten-book panel — the object the prohibition is
actually about (`data/aggressive_lab/*/realized_series.jsonl`, `phase != "backtest"`).  That
block is a different series with a different accounting, and it has never been measured by
anything.  This instrument measures it, and prints #148's two sources beside it so the three
answers are comparable rather than merely adjacent.

THE THREE UNITS A GATE CAN BE COUNTED IN — and they are NOT interchangeable (inv. #17):

  1. CALENDAR DAYS      how many forward rows exist.  This is what the prohibition says.
  2. MARKED book-days   days whose row carries a non-zero mark-to-market.  A row that only
                        accrues carry is a BOOKKEEPING entry, not a mark: it cannot disagree
                        with the world, so it cannot be evidence about the world.
  3. MEASURABLE books   books whose forward drawdown exceeds the 96 bp toll — the ONLY unit in
                        which the prohibition's own PURPOSE is expressed, because #148/#149
                        wanted live marks in order to get a non-degenerate Calmar denominator.

  A gate counted in unit 1 opens on schedule no matter what the series contains.  A MONOTONE
  forward path has maxDD == 0 BY CONSTRUCTION, so for a monotone book unit 3 can never be
  reached — not "has not been reached yet", but cannot be, however many days are added.  The
  instrument therefore reports monotonicity per book: it is the difference between a gate that
  is waiting and a gate that is stuck.

FAIL-CLOSED / THIRD OUTCOME.  A panel, book or source that cannot be read is reported
`unmeasured` WITH ITS REASON and never counted as a clean zero.  "No measurable drawdown
found" and "we could not look" are printed as different answers, and a run that can read
nothing at all exits 2 rather than announcing an empty gate.

WHAT THIS INSTRUMENT DOES NOT DO.  It does not change the prohibition — a prohibition written
by a registry entry is lifted by a registry entry.  It does not propose a sizer (that is
exactly what the prohibition forbids).  It measures the gate and prints which unit its counter
is in; the verdict belongs to the registry entry that reads this output.

IS_ADVISORY = True · OUTSIDE_RISKPOLICY = True
Read-only.  No capital moves.  RiskPolicy v1.0 untouched.  The go-live track
(data/equity_curve_daily.json) is never opened.  stdlib-only, deterministic, LLM FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

IS_ADVISORY = True
OUTSIDE_RISKPOLICY = True

ROOT = Path(__file__).resolve().parent.parent
ENSEMBLE = ROOT / "scripts" / "edge_real_panel_ensemble.py"

#: the number the #149 prohibition names, in the unit the prohibition names it in.
GATE_DAYS = 90
#: the phase label of the live-marks block. Anything that is not "backtest" is forward.
BACKTEST_PHASE = "backtest"
#: `exit_nav.json` is named by the prohibition itself; these are the places it could live.
EXIT_NAV_CANDIDATES: Tuple[str, ...] = (
    "exit_nav.json",
    "rates_desk/exit_nav.json",
    "aggressive_lab/exit_nav.json",
    "dd_snapshot/exit_nav.json",
)

_MOD: Dict[str, object] = {}


class GateUnmeasured(RuntimeError):
    """Fail-CLOSED: the gate could not be read, so it is not reported open OR shut."""


def _load(path: Path, name: str):
    if name in _MOD:
        return _MOD[name]
    if not path.exists():
        raise GateUnmeasured(f"{name}: {path} missing — refusing to reimplement it")
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    _MOD[name] = mod
    return mod


def ens():
    return _load(ENSEMBLE, "edge_real_panel_ensemble")


def toll() -> float:
    """The 96 bp round-trip toll, READ from the harness that declares it (#10/#49)."""
    return float(ens().PLB_ROUNDTRIP)


def _rows(path: Path) -> List[dict]:
    out: List[dict] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def forward_block(rows: Sequence[dict]) -> List[dict]:
    """Rows whose phase is NOT "backtest", in date order — the live-marks block.

    Defined by exclusion on purpose: a future phase label ("live", "paper2") must land in the
    block this gate judges, not silently outside it. A label this function has never heard of
    is still not a backtest row.
    """
    keep = [r for r in rows if r.get("phase") != BACKTEST_PHASE]
    keep.sort(key=lambda r: str(r.get("date") or r.get("as_of") or ""))
    return keep


def _drawdown(eq: Sequence[float]) -> float:
    peak, mdd = eq[0], 0.0
    for v in eq:
        peak = max(peak, v)
        if peak > 0:
            mdd = min(mdd, v / peak - 1.0)
    return abs(mdd)


def book_forward(path: Path, *, t: float) -> Dict[str, object]:
    """One book's forward block, measured in all three units. Never invents a row."""
    rows = forward_block(_rows(path))
    if not rows:
        return {"unmeasured": "no forward rows", "days": 0}
    eq: List[float] = []
    dates: List[str] = []
    marked = 0
    for r in rows:
        e = r.get("equity_usd")
        if e is None or float(e) <= 0:
            continue
        eq.append(float(e))
        dates.append(str(r.get("date") or r.get("as_of")))
        mtm = r.get("mtm_today_pct")
        if mtm is not None and abs(float(mtm)) > 1e-12:
            marked += 1
    if len(eq) < 2:
        return {"unmeasured": f"only {len(eq)} usable equity points", "days": len(eq)}
    rets = [eq[i] / eq[i - 1] - 1.0 for i in range(1, len(eq))]
    mdd = _drawdown(eq)
    moves = sum(1 for r in rets if abs(r) > 1e-12)
    down = sum(1 for r in rets if r < -1e-12)
    n = len(rets)
    return {
        "unmeasured": None,
        "days": len(eq), "first": dates[0], "last": dates[-1],
        "apy": (eq[-1] / eq[0]) ** (365.0 / n) - 1.0,
        "maxdd": mdd,
        "moves": moves,
        "down_days": down,
        # a monotone path CANNOT produce a drawdown — the gate is stuck, not waiting
        "monotone": down == 0,
        "marked_days": marked,
        "mark_sources": sorted({str(r.get("mtm_source")) for r in rows}),
        "measurable": mdd > t,
        "frozen": moves == 0,
    }


def panel_gate(panel_dir: Path) -> Dict[str, object]:
    """The gate, read off the panel's own forward block. Fail-CLOSED."""
    if not panel_dir.exists():
        raise GateUnmeasured(f"panel dir absent: {panel_dir}")
    t = toll()
    books: Dict[str, dict] = {}
    for sub in sorted(panel_dir.glob("*/realized_series.jsonl")):
        try:
            books[sub.parent.name] = book_forward(sub, t=t)
        except Exception as exc:  # a book we could not parse is NOT a quiet book
            books[sub.parent.name] = {"unmeasured": f"unreadable: {exc}", "days": 0}
    if not books:
        raise GateUnmeasured(
            f"no book series under {panel_dir} — refusing to report a gate state"
        )
    judged = {b: d for b, d in books.items() if not d.get("unmeasured")}
    if not judged:
        raise GateUnmeasured(
            "no book had a readable forward block — refusing to answer 'nothing is measurable'"
        )
    days = sorted({int(d["days"]) for d in judged.values()})
    return {
        "panel_dir": str(panel_dir), "toll": t, "gate_days": GATE_DAYS,
        "books": books,
        "n_books": len(books), "n_judged": len(judged),
        "n_unmeasured": len(books) - len(judged),
        # UNIT 1 — calendar days (what the prohibition says)
        "days_per_book": days,
        "min_days": days[0], "max_days": days[-1],
        "unit1_open": days[0] >= GATE_DAYS,
        # UNIT 2 — marked book-days (a mark, not a bookkeeping entry)
        "marked_book_days": sum(int(d["marked_days"]) for d in judged.values()),
        "total_book_days": sum(int(d["days"]) for d in judged.values()),
        "n_unmarked_books": sum(1 for d in judged.values() if int(d["marked_days"]) == 0),
        # UNIT 3 — measurable books (the prohibition's own PURPOSE)
        "n_measurable": sum(1 for d in judged.values() if d["measurable"]),
        "measurable_books": sorted(b for b, d in judged.items() if d["measurable"]),
        "n_monotone": sum(1 for d in judged.values() if d["monotone"]),
        "monotone_books": sorted(b for b, d in judged.items() if d["monotone"]),
        "n_frozen": sum(1 for d in judged.values() if d["frozen"]),
        "frozen_books": sorted(b for b, d in judged.items() if d["frozen"]),
    }


def exit_nav_presence(data_dir: Path) -> List[dict]:
    """Where `exit_nav.json` — named by the prohibition itself — does and does not exist."""
    return [{"path": c, "present": (data_dir / c).exists()} for c in EXIT_NAV_CANDIDATES]


def neighbour_sources(data_dir: Path) -> Dict[str, object]:
    """#148 §2's two sources, read through #148's own instrument when it is importable.

    Printed beside the panel gate so the three answers are comparable. Its absence is a named
    reason, not a silent omission: this instrument does not re-implement #148.
    """
    pop_path = ROOT / "scripts" / "edge_measurable_population.py"
    if not pop_path.exists():
        return {"unmeasured": f"{pop_path} absent — #148 §2 not re-implemented here"}
    try:
        mod = _load(pop_path, "edge_measurable_population")
        return {"unmeasured": None, "report": mod.forward_measurability(data_dir)}
    except Exception as exc:
        return {"unmeasured": f"#148 §2 refused: {exc}"}


def report(panel_dir: Path, data_dir: Path) -> Dict[str, object]:
    return {
        "gate": panel_gate(panel_dir),
        "exit_nav": exit_nav_presence(data_dir),
        "neighbours": neighbour_sources(data_dir),
    }


def print_report(rep: Dict[str, object]) -> None:
    g = rep["gate"]
    t = float(g["toll"])
    print("=" * 94)
    print("#152 LMG — ВОРОТА ЖИВЫХ МАРОК: в какой ЕДИНИЦЕ считается счётчик запрета #149")
    print("=" * 94)
    print(f"панель: {g['panel_dir']} · пошлина: {t * 100:.2f} % · "
          f"число запрета: {g['gate_days']} дн.")
    print(f"книг: {g['n_books']} · прочитано: {g['n_judged']} · "
          f"НЕ ИЗМЕРЕНО: {g['n_unmeasured']}")

    print("\nФОРВАРДНЫЙ БЛОК ПО КНИГАМ (хвост РЯДОМ с доходом, инв. #8):")
    print(f"  {'книга':20s} {'дней':>5s} {'ходов':>6s} {'вниз':>5s} {'с маркой':>8s} "
          f"{'APY%':>8s} {'maxDD%':>8s} {'моно':>5s} {'измерима':>8s}")
    for b in sorted(g["books"]):
        d = g["books"][b]
        if d.get("unmeasured"):
            print(f"  {b:20s} {'':>5s} {'':>6s} {'':>5s} {'':>8s} {'':>8s} {'':>8s} "
                  f"{'':>5s} НЕ ИЗМЕРЕНО: {d['unmeasured']}")
            continue
        print(f"  {b:20s} {d['days']:5d} {d['moves']:6d} {d['down_days']:5d} "
              f"{d['marked_days']:8d} {d['apy'] * 100:8.2f} {d['maxdd'] * 100:8.4f} "
              f"{('ДА' if d['monotone'] else 'нет'):>5s} {('ДА' if d['measurable'] else 'нет'):>8s}")

    print("\nТРИ ЕДИНИЦЫ СЧЁТА — и они НЕ взаимозаменяемы:")
    print(f"  1. КАЛЕНДАРНЫЕ ДНИ (то, что СКАЗАНО в запрете): {g['min_days']}..{g['max_days']} "
          f"дн. на книгу ⇒ порог {g['gate_days']} дн. "
          f"{'ДОСТИГНУТ' if g['unit1_open'] else 'НЕ достигнут'}")
    print(f"  2. ДНИ С МАРКОЙ (строка несёт переоценку, а не только начисление): "
          f"{g['marked_book_days']} из {g['total_book_days']} книго-дней; "
          f"книг БЕЗ ни одной марки: {g['n_unmarked_books']} из {g['n_judged']}")
    print(f"  3. ИЗМЕРИМЫЕ КНИГИ (просадка > {t * 100:.2f} % — ЦЕЛЬ запрета): "
          f"{g['n_measurable']} из {g['n_judged']}"
          + (f" ({', '.join(g['measurable_books'])})" if g["measurable_books"] else ""))
    print(f"     из них путь МОНОТОНЕН (просадка невозможна ПО ПОСТРОЕНИЮ, сколько дней ни "
          f"добавь): {g['n_monotone']} из {g['n_judged']}"
          + (f" — {', '.join(g['monotone_books'])}" if g["monotone_books"] else ""))
    print(f"     заморожено ВОВСЕ (ни одного хода): {g['n_frozen']} из {g['n_judged']}"
          + (f" — {', '.join(g['frozen_books'])}" if g["frozen_books"] else ""))

    print("\n`exit_nav.json` — файл, НАЗВАННЫЙ самим запретом:")
    for row in rep["exit_nav"]:
        print(f"  {'ЕСТЬ      ' if row['present'] else 'НЕТ       '} data/{row['path']}")

    nb = rep["neighbours"]
    print("\nСОСЕДНИЕ ФОРВАРДНЫЕ ИСТОЧНИКИ (#148 §2, прочитаны ЕГО прибором):")
    if nb.get("unmeasured"):
        print(f"  НЕ ИЗМЕРЕНО: {nb['unmeasured']}")
    else:
        r = nb["report"]
        print(f"  источников: {len(r['sources'])} · прочитано: {r['n_judged']} · "
              f"НЕ ИЗМЕРЕНО: {r['n_unmeasured']} · ИЗМЕРИМЫХ: {r['n_measurable']}")
        for s in r["sources"]:
            if s.get("unmeasured"):
                print(f"    НЕ ИЗМЕРЕНО: {s['source']} — {s['unmeasured']}")
            else:
                print(f"    {s['source']}: {s.get('days')} дн. · maxDD "
                      f"{s['maxdd'] * 100:.4f} % · измерима: "
                      f"{'ДА' if s['measurable'] else 'нет'}")

    print("\n" + "=" * 94)
    print("IS_ADVISORY=True · OUTSIDE_RISKPOLICY=True · RiskPolicy v1.0 не тронута · "
          "живой трек не открыт")
    print("Запрет #149 этим прибором НЕ снимается: прибор МЕРИТ ворота и называет единицу "
          "счёта. Снять запрет вправе только запись реестра.")
    print("=" * 94)


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="#152 LMG — read the #149 live-marks gate")
    ap.add_argument("--panel-dir", default=None,
                    help="panel directory (default: <repo>/data/aggressive_lab)")
    ap.add_argument("--data-dir", default=None,
                    help="data root for exit_nav / #148 §2 sources (default: <repo>/data)")
    ns = ap.parse_args(list(argv) if argv is not None else None)
    panel = Path(ns.panel_dir) if ns.panel_dir else ROOT / "data" / "aggressive_lab"
    data = Path(ns.data_dir) if ns.data_dir else (
        panel.parent if ns.panel_dir else ROOT / "data")
    try:
        print_report(report(panel, data))
    except GateUnmeasured as exc:
        print(f"НЕ ИЗМЕРЕНО: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
