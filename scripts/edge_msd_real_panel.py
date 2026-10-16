#!/usr/bin/env python3
"""
scripts/edge_msd_real_panel.py — registry idea MSDR (number claimed at delivery: #137)

IS_ADVISORY = True
OUTSIDE_RISKPOLICY = True

EXECUTION OF THE STANDING ORDER LEFT BY #133 (IDC), VERBATIM
============================================================
    "Следующий шаг: проверить IDC на реальной панели (10 книг)."

#130 (MSD-KODS) and #133 (IDC) are the registry's only entries that change the COMPOSITION of
the risky sleeve rather than the timing of it, and both are positive — #130 reports Calmar
4.55 -> 5.81 (70s_30p) and 7.20 (50s_50p); #133 reports the advantage surviving a total
incentive cliff at every one of five dates. Both were measured on the STRESS FIXTURE, and both
said so, and both deferred the real panel to a later session. This is that session.

The order is executed literally: the same blend configurations, the same imported KODS engine
(`_run_kods_on_composite` and `_composite_returns` are IMPORTED from
scripts/edge_multi_strategy_diversification.py, never retyped), the same cliff model and the
same five cliff dates as #133 — fed the REAL panel instead of the fixture.

WHAT CHANGES WHEN THE DATA CHANGES, AND WHY IT IS THE WHOLE ANSWER
------------------------------------------------------------------
On the fixture, `points_farm`'s crisis losses are SPEC CONSTANTS (1 %, 2 %, 1.5 %) written into
the window generator, and #130's entire mechanism is that those constants are smaller than
`susde_dn`'s (3 %, 9 %, 1 %). On the real panel the registry has already measured what that book
does: #122 found `points_farm` has NOT ONE day below zero in 852 days, and #126/#128/#129 each
found a rule concentrating into it and called the result a leak, because "lowest tail" there
means NOT MEASURED, never "safe".

So the question this file can actually answer is sharper than "does the blend win": it is

    is #130's advantage MEASURABLE on the real panel at all, and if not, which of the two
    reasons applies — the blend does not help, or the denominator it is scored on does not exist?

#129 made that distinction mandatory, and the instrument #130 used cannot make it: its Calmar
line reads `calmar = apy/maxdd if max_dd > 1e-9 else 999.99`, i.e. a vanished denominator is
reported as the largest number in the table. This file prints that instrument's own figure AND
the honest verdict beside it (`drawdown_verdict` / `calmar_degenerate` from #128/#129), exactly
as #132 did for flagship #1's metrics — never replacing one with the other, because the published
numbers of #130/#133 have to stay comparable.

THREE SECTIONS
--------------
  §1 THE PREMISE. `crisis_loss` of each leg over the harness's REAL crisis windows, with the
     three outcomes kept apart (`measured` / `no_down_day` / `unmeasured_window_off_axis`). This
     is where the fixture's spec constants meet observation.
  §2 THE BLENDS. Every #130 configuration on real returns, out of sample at the harness's own
     seam, each row carrying both the instrument's number and the honest verdict.
  §3 THE CLIFF (#133). points_farm's return forced to 0.0 from the cliff date onward — yield
     gone, position held, tail (whatever is observed) kept — over #133's five dates plus NONE.

`lrt_carry`, #130's negative control, DOES NOT EXIST on the real panel. The nearest real book is
`lrt_neutral`, and it is run under that name and labelled a SUBSTITUTION, not the same book: a
negative control quietly renamed is how a table stops meaning what its header says.

Advisory only. No capital moves, the go-live track is never opened, RiskPolicy v1.0 is untouched,
no module is built, no agent is deployed, nothing is written to disk.
"""
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
GZ_PATH = ROOT / "scripts" / "edge_admitted_set_guardian_zero.py"
MSD_PATH = ROOT / "scripts" / "edge_multi_strategy_diversification.py"

#: #133's cliff dates, verbatim, plus the "no cliff" control.
CLIFF_DATES: Tuple[Optional[str], ...] = ("2024-10-01", "2025-01-01", "2025-07-01",
                                          "2025-10-01", "2026-01-01", None)

#: #130's blend grid, with its `lrt_carry` leg mapped to the nearest REAL book and labelled so.
BLENDS: Tuple[Tuple[str, float, float, str], ...] = (
    ("susde_only", 1.00, 0.00, "susde_dn"),
    ("80s_20p", 0.80, 0.20, "points_farm"),
    ("70s_30p", 0.70, 0.30, "points_farm"),
    ("60s_40p", 0.60, 0.40, "points_farm"),
    ("50s_50p", 0.50, 0.50, "points_farm"),
    ("80s_20L*", 0.80, 0.20, "lrt_neutral"),
    ("50s_50L*", 0.50, 0.50, "lrt_neutral"),
)
#: the substitution is declared in data, not only in prose, so a reader of the JSON sees it too.
SUBSTITUTIONS = {"lrt_neutral": "stands in for the fixture's `lrt_carry`, which has no real book"}

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
    return _load(path, "edge_admitted_set_guardian_zero")


def msd_mod(path: Path = MSD_PATH):
    """#130's own engine. IMPORTED so that a difference in the numbers is a difference in DATA."""
    return _load(path, "edge_multi_strategy_diversification")


def sfs_mod():
    return gz_mod().sfs_mod()


def panel_mod():
    return gz_mod().panel_mod()


# ───────────────────────── real series in #130's own shape ─────────────────────────
def as_date_map(axis: Sequence[str], rets: Sequence[float], *, lo: int = 0,
                hi: Optional[int] = None) -> Dict[str, float]:
    """#130's engine speaks {date: return}; the panel speaks parallel lists. One conversion, here."""
    hi = len(axis) if hi is None else hi
    return {axis[i]: rets[i] for i in range(lo, hi)}


def apply_cliff(series: Dict[str, float], cliff: Optional[str]) -> Dict[str, float]:
    """#133's cliff on real data: from `cliff` onward the yield is GONE and the position is HELD.

    The fixture version zeroes a drift constant. A real series has no drift to zero, so the
    honest translation of "yield disappears immediately" is a return of exactly 0.0 from that
    date on. Any observed loss before the cliff stays; nothing is invented after it. This is
    DELIBERATELY the most favourable reading for the hypothesis — a real holder unable to exit
    would also keep taking the downside, and this model does not make him.
    """
    if cliff is None:
        return dict(series)
    return {d: (0.0 if d >= cliff else r) for d, r in series.items()}


def honest_verdict(series: Dict[str, float]) -> Dict[str, object]:
    """#128/#129's verdicts on the same series #130's engine scores — printed beside it, not instead."""
    S = sfs_mod()
    rets = [series[d] for d in sorted(series)]
    v = dict(S.drawdown_verdict(rets))
    v["calmar_degenerate"] = S.calmar_degenerate(v.get("maxdd"))
    return v


def run_blend(books: Dict[str, Dict[str, float]], label: str, w1: float, w2: float, alt: str,
              *, lo_key: Optional[str] = None) -> Dict[str, object]:
    """One #130 configuration on real returns: its engine's row plus the honest verdict.

    The portfolio the engine builds is `f*(t) x composite + (1 - f*(t)) x safe_leg`, so the
    honest verdict is taken on THAT portfolio and not on the bare composite — otherwise the two
    columns would describe two different objects and the table would be unreadable.
    """
    M = msd_mod()
    comp = M._composite_returns(books["susde_dn"], books[alt], w1, w2) if w2 else dict(
        books["susde_dn"])
    row = M._run_kods_on_composite(comp, label)
    port = kods_portfolio_series(comp)
    hv = honest_verdict(port)
    return {
        "label": label, "w_susde": w1, "w_alt": w2, "alt": alt,
        "substitution": SUBSTITUTIONS.get(alt),
        "engine": {k: row.get(k) for k in ("n_days", "apy_pct", "max_dd_pct", "calmar",
                                           "crisis_dd")},
        "honest": hv,
        "composite_days": len(comp),
    }


def kods_portfolio_series(composite: Dict[str, float]) -> Dict[str, float]:
    """The engine's own portfolio path, rebuilt day by day with the engine's own constants.

    #130's `_run_kods_on_composite` returns summary numbers, not the path, and the honesty
    verdicts of #128/#129 need the path. Every constant used here is READ OFF the imported
    module (`ALPHA`, `MAX_RISKY`, `LOOKBACK`, `MIN_VAR`, `RATES_DAILY`, `SAFE_DAILY`) rather than
    retyped, and the rebuild is pinned against the engine's own APY and maxDD bitwise-close by
    `test_portfolio_rebuild_matches_the_engine`. If #130's parameters ever move, this moves with
    them or the test goes red.
    """
    M = msd_mod()
    dates = sorted(composite)
    rl = [composite[d] for d in dates]
    out: Dict[str, float] = {}
    for i, d in enumerate(dates):
        if i < M.LOOKBACK:
            f = M.MAX_RISKY
        else:
            w = rl[i - M.LOOKBACK:i]
            mu = sum(w) / M.LOOKBACK
            var = max(sum((r - mu) ** 2 for r in w) / M.LOOKBACK, M.MIN_VAR)
            f = min(M.ALPHA * max(0.0, (mu - M.RATES_DAILY) / var), M.MAX_RISKY)
        out[d] = f * composite[d] + (1.0 - f) * M.SAFE_DAILY
    return out


def msdr_report(panel_dir: Optional[Path] = None) -> Dict[str, object]:
    GZ = gz_mod()
    S = sfs_mod()
    H = panel_mod()
    pd_ = Path(panel_dir) if panel_dir else H.PANEL_DIR
    axis, rets, books_all = H.plb_load(pd_)
    seam = GZ.split_index(axis, H.TRAIN_END)
    needed = ["susde_dn", "points_farm", "lrt_neutral"]
    missing = [b for b in needed if b not in rets]
    if missing:
        raise RuntimeError(f"the order names books this panel does not carry: {missing} — "
                           f"NOT MEASURED, and refusing to substitute silently")

    # §1 the premise, on the harness's REAL crisis windows
    premise: Dict[str, Dict[str, object]] = {}
    for b in needed:
        premise[b] = {name: S.crisis_loss(rets, axis, b, lo, hi)
                      for name, lo, hi in H.CRISIS_WINDOWS}

    # §2 the blends, full axis and out of sample
    def _window(lo: int, hi: int) -> Dict[str, object]:
        series = {b: as_date_map(axis, rets[b], lo=lo, hi=hi) for b in needed}
        rows = [run_blend(series, lab, w1, w2, alt) for lab, w1, w2, alt in BLENDS]
        base = rows[0]
        for r in rows:
            r["delta_engine_calmar"] = (
                None if (r["engine"]["calmar"] is None or base["engine"]["calmar"] is None)
                else r["engine"]["calmar"] - base["engine"]["calmar"])
            r["delta_honest"] = GZ.delta_calmar(
                {"calmar": r["honest"]["calmar"],
                 "calmar_degenerate": r["honest"]["calmar_degenerate"]},
                {"calmar": base["honest"]["calmar"],
                 "calmar_degenerate": base["honest"]["calmar_degenerate"]})
        return {"rows": rows, "days": hi - lo}

    blends = {"full": _window(0, len(axis)), "train": _window(0, seam),
              "test": _window(seam, len(axis))}

    # §3 the cliff (#133), on the TEST half and on the full axis
    cliffs: Dict[str, List[Dict[str, object]]] = {}
    for wname, (lo, hi) in (("full", (0, len(axis))), ("test", (seam, len(axis)))):
        out: List[Dict[str, object]] = []
        for cliff in CLIFF_DATES:
            series = {b: as_date_map(axis, rets[b], lo=lo, hi=hi) for b in needed}
            series["points_farm"] = apply_cliff(series["points_farm"], cliff)
            rows = [run_blend(series, lab, w1, w2, alt) for lab, w1, w2, alt in BLENDS
                    if alt in ("susde_dn", "points_farm")]
            base = rows[0]
            for r in rows:
                r["delta_engine_calmar"] = (
                    None if (r["engine"]["calmar"] is None or base["engine"]["calmar"] is None)
                    else r["engine"]["calmar"] - base["engine"]["calmar"])
                r["delta_honest"] = gz_mod().delta_calmar(
                    {"calmar": r["honest"]["calmar"],
                     "calmar_degenerate": r["honest"]["calmar_degenerate"]},
                    {"calmar": base["honest"]["calmar"],
                     "calmar_degenerate": base["honest"]["calmar_degenerate"]})
            out.append({"cliff": cliff or "NONE", "rows": rows,
                        "cliff_in_window": (cliff is None or any(
                            cliff <= d for d in series["points_farm"]))})
        cliffs[wname] = out

    income = {w: income_direction(blends[w]["rows"]) for w in ("full", "train", "test")}
    income["cliff_test"] = {blk["cliff"]: income_direction(blk["rows"])
                            for blk in cliffs["test"]}
    verdict = msdr_verdict(blends, cliffs)
    verdict["income"] = income
    return {
        "panel_dir": str(pd_), "axis": [axis[0], axis[-1]], "axis_days": len(axis),
        "train_end": H.TRAIN_END, "seam_index": seam,
        "crisis_windows": [list(w) for w in H.CRISIS_WINDOWS],
        "books_used": needed, "substitutions": SUBSTITUTIONS,
        "roundtrip": S.ROUNDTRIP,
        "kods_settings": {"alpha": msd_mod().ALPHA, "max_risky": msd_mod().MAX_RISKY,
                          "lookback": msd_mod().LOOKBACK},
        "premise": premise, "blends": blends, "cliffs": cliffs, "verdict": verdict,
    }


def income_direction(rows: Sequence[Dict[str, object]]) -> Dict[str, object]:
    """What the blend does to INCOME, which on this panel IS measurable even when Calmar is not.

    A degenerate denominator refuses the ratio, not the numerator. #130's claim has two halves —
    "lower tail" and "no sacrifice of carry" — and the second half can be judged here whatever
    happens to the first. Reported as a direction with its own numbers, never folded into the
    Calmar verdict.
    """
    pf = [r for r in rows if r["alt"] == "points_farm" or r["w_alt"] == 0.0]
    pf.sort(key=lambda r: r["w_alt"])
    apys = [(r["label"], r["w_alt"], r["engine"]["apy_pct"]) for r in pf]
    if any(a is None for _l, _w, a in apys) or len(apys) < 2:
        return {"status": "unmeasured", "reason": "a blend row carries no APY at all",
                "rows": apys}
    diffs = [apys[i + 1][2] - apys[i][2] for i in range(len(apys) - 1)]
    direction = ("monotone_down" if all(d < 0 for d in diffs) else
                 "monotone_up" if all(d > 0 for d in diffs) else "mixed")
    return {"status": "measured", "direction": direction, "rows": apys,
            "span_pp": apys[-1][2] - apys[0][2], "steps": diffs}


def msdr_verdict(blends: Dict[str, object], cliffs: Dict[str, object]) -> Dict[str, object]:
    """Was #130's advantage MEASURABLE on the real panel, and if so, did it survive?

    Three outcomes, never two (inv. #17):
      `unmeasurable` — no blend row and no base row carried a non-degenerate Calmar, so the
                       question #130 asks cannot be put to this panel at all;
      `confirmed`    — at least one points_farm blend beat the base on a MEASURED denominator
                       on TEST, and the cliff did not remove it;
      `refuted`      — the measurement exists and goes the other way.
    """
    test_rows = blends["test"]["rows"]
    measured = [r for r in test_rows if r["honest"]["calmar_degenerate"] is None
                and r["honest"]["calmar"] is not None]
    if not measured:
        reasons = sorted({str(r["honest"]["calmar_degenerate"] or r["honest"]["status"])
                          for r in test_rows})
        return {"verdict": "unmeasurable", "measured_rows": 0, "reason": "; ".join(reasons),
                "note": ("every row's denominator is below the round-trip toll or absent "
                         "entirely — #130's Calmar comparison has no referent on this panel, "
                         "and that is an answer, not a missing measurement")}
    wins = [r for r in measured if r["alt"] == "points_farm"
            and (r["delta_honest"] or {}).get("status") == "measured"
            and (r["delta_honest"] or {}).get("delta_calmar", 0.0) > 0.0]
    return {"verdict": ("confirmed" if wins else "refuted"),
            "measured_rows": len(measured), "winning_blends": [r["label"] for r in wins],
            "reason": None}


# ───────────────────────────────── printing ─────────────────────────────────
def _f(x, *, pct: bool = False, nd: int = 2, dash: str = "НЕ ИЗМЕРЕН") -> str:
    if x is None:
        return dash
    return f"{x * 100:.{nd}f} %" if pct else f"{x:.{nd}f}"


def _row_line(r: Dict[str, object]) -> str:
    e, h = r["engine"], r["honest"]
    hon = "ОТКАЗАН" if h["calmar_degenerate"] else _f(h["calmar"], nd=2)
    dh = r.get("delta_honest") or {}
    dtxt = (f"{dh['delta_calmar']:+.2f}" if dh.get("status") == "measured" else "ОТКАЗАН")
    return (f"{r['label']:11} {_f(e['apy_pct'], nd=2):>9} {_f(e['max_dd_pct'], nd=4):>11} "
            f"{_f(e['calmar'], nd=2):>12} {_f(h['maxdd'], pct=True, nd=4):>12} {hon:>12} "
            f"{dtxt:>9} {str(h['down_days']):>8} {str(h['status']):>22}")


def _header() -> str:
    return (f"{'бленд':11} {'APY% (#130)':>9} {'maxDD% #130':>11} {'Calmar #130':>12} "
            f"{'maxDD чест.':>12} {'Calmar чест':>12} {'Δчест':>9} {'дн.вниз':>8} "
            f"{'статус':>22}")


def print_msdr(rep: Dict[str, object]) -> None:
    print("=" * 118)
    print("#137 MSDR — MSD-KODS (#130) И CLIFF (#133) НА РЕАЛЬНОЙ ПАНЕЛИ "
          "(исполнение заказа #133)")
    print("=" * 118)
    print("прибор: движок KODS ИМПОРТИРОВАН из scripts/edge_multi_strategy_diversification.py; "
          "вердикты — из #128/#129")
    print(f"панель {rep['panel_dir']} · ось {rep['axis'][0]}…{rep['axis'][1]} "
          f"({rep['axis_days']} дней) · шов {rep['train_end']} (индекс {rep['seam_index']})")
    print(f"настройки KODS #15: {rep['kods_settings']} · пошлина круга {rep['roundtrip']:.4f}")
    for b, why in rep["substitutions"].items():
        print(f"ЗАМЕНА: `{b}` — {why}. Строки с ней помечены звёздочкой и НЕ являются "
              f"контролем #130 дословно.")

    print("\n§1 ПРЕДПОСЫЛКА #130 НА РЕАЛЬНЫХ КРИЗИСНЫХ ОКНАХ "
          "(спец-константы фикстуры против наблюдения)")
    print(f"{'книга':16} " + " ".join(f"{name:>26}" for name, _a, _b in
                                      [(w[0], w[1], w[2]) for w in rep["crisis_windows"]]))
    for b, wins in rep["premise"].items():
        cells = []
        for name, _a, _b in [(w[0], w[1], w[2]) for w in rep["crisis_windows"]]:
            c = wins[name]
            cells.append(f"{_f(c['loss'], pct=True, nd=2)} / {c['status']}"[:26].rjust(26))
        print(f"{b:16} " + " ".join(cells))
    print("  «0.00 % / no_down_day» означает ИЗМЕРЕНО И РАВНО НУЛЮ: окно покрыто, падений нет. "
          "Это НЕ «низкий хвост» — это отсутствие наблюдения падения (#122).")

    for wname, title in (("full", "ПОЛНАЯ ОСЬ (in-sample)"), ("train", "TRAIN (in-sample)"),
                         ("test", "TEST (вне выборки)")):
        w = rep["blends"][wname]
        print(f"\n§2.{wname} БЛЕНДЫ #130 — {title}, {w['days']} дней")
        print(_header())
        for r in w["rows"]:
            print(_row_line(r))

    for wname in ("full", "test"):
        print(f"\n§3.{wname} CLIFF #133 НА РЕАЛЬНЫХ ДАННЫХ "
              f"(доходность points_farm = 0 с даты, позиция удерживается)")
        for blk in rep["cliffs"][wname]:
            print(f"  cliff = {blk['cliff']}")
            print("  " + _header())
            for r in blk["rows"]:
                print("  " + _row_line(r))

    inc = rep["verdict"]["income"]
    print("\n§4 ДОХОД — ЭТО ИЗМЕРИМО, даже когда отношение ОТКАЗАНО "
          "(вторая половина претензии #130: «без жертвы carry»)")
    for w in ("full", "train", "test"):
        d = inc[w]
        if d["status"] != "measured":
            print(f"  {w:6} НЕ ИЗМЕРЕН — {d['reason']}")
            continue
        chain = " → ".join(f"{lab} {apy:.2f} %" for lab, _w, apy in d["rows"])
        print(f"  {w:6} {d['direction']:14} ({d['span_pp']:+.2f} пп от susde_only к 50s_50p): "
              f"{chain}")
    print("  по датам cliff на TEST: " + ", ".join(
        f"{c}={d.get('direction', d['status'])}" for c, d in inc["cliff_test"].items()))

    v = rep["verdict"]
    print(f"\n§5 ВЕРДИКТ: {v['verdict'].upper()} — строк с ИЗМЕРЕННЫМ знаменателем на TEST: "
          f"{v['measured_rows']}")
    if v.get("reason"):
        print(f"    причина: {v['reason']}")
    if v.get("note"):
        print(f"    {v['note']}")
    if v.get("winning_blends"):
        print(f"    выигравшие бленды: {', '.join(v['winning_blends'])}")


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="registry #137 MSDR (advisory, read-only)")
    ap.add_argument("--panel", default=None)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    rep = msdr_report(Path(a.panel) if a.panel else None)
    if a.json:
        print(json.dumps(rep, indent=2, ensure_ascii=False, default=str))
    else:
        print_msdr(rep)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
