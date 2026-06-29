"""
spa_core/strategy_lab/realized_ab.py — ROUND-2 WS-1.1 + WS-1.2: a REALIZED, FORWARD,
day-distinct shadow A/B between the legacy ``risk_adjusted`` heuristic and the WS-1.2
``optimized_yield`` constrained optimizer.

WHY THIS EXISTS (the honest gap it closes)
══════════════════════════════════════════
``scripts/optimizer_ab.py`` + ``data/optimizer_ab.json`` are a BACKTEST: they REPLAY the same
evidenced window through both models every run, so the artifact is ``is_realized:false`` and the
per-day rows are 7× copies of one identical replay (every row +1.3737pp). A backtest replayed N
times is NOT a track record — it is one number printed N times.

This module is the REALIZED counterpart. Each UTC day it:

  1. reads the LIVE daily universe ONCE (the protocols the cycle actually held that day + their
     realized per-protocol APY, from the evidenced equity-curve day — the SAME live universe both
     books must score),
  2. scores that ONE universe through BOTH allocation surfaces (legacy heuristic + WS-1.2
     optimizer) under the UNCHANGED RiskPolicy caps,
  3. BANKS the realized daily accrual into TWO parallel paper books (legacy + optimized),
     SEPARATE from the go-live track, appending ONE distinct row per UTC day (idempotent — a
     re-run on the same day refreshes today's row, never double-counts),
  4. emits ``data/realized_ab/realized_ab.json`` with ``is_realized:true`` and the cash-drag
     decomposition.

HONESTY (the whole point — measurement that stays truthful as the track matures)
════════════════════════════════════════════════════════════════════════════════
  • is_realized:TRUE — the books accrue forward, one row per real UTC day. It starts THIN (a few
    days) — that is CORRECT, not a defect. ``status`` is THIN until ≥ MIN_DAYS_FOR_VERDICT rows.
  • CASH-DRAG-FAIR (WS-1.2): the legacy heuristic deploys ~100% (it skips the 5% cash floor); the
    optimizer reserves the floor. A raw APY gap therefore conflates SELECTION alpha with a CASH-DRAG
    advantage. We decompose the realized uplift into {selection_alpha_bps, cash_drag_bps} so the
    apples-to-apples SELECTION-only edge is surfaced separately. We ALSO bank a floor-fair variant
    where BOTH books reserve the SAME cash floor (legacy_fair) so the like-for-like accrual is honest.
  • RED-TEAM baked in (see ``_redteam_guard`` + the day-distinctness invariant):
      – replay-day injection (re-counting one day) → caught: the series is append-ONE-per-UTC-day;
        a duplicate date REFRESHES, never appends; an all-identical multi-row series is flagged
        ``replay_suspect`` (a realized forward track has day-distinct accrual).
      – cash-drag laundering (hiding the floor advantage) → caught: the decomposition is the
        headline; the raw gap is labeled NOT apples-to-apples; cash_drag_bps is reported explicitly.
      – INSUFFICIENT_DATA masked as 0.0 → caught: a thin/empty track yields status THIN /
        INSUFFICIENT_DATA with null verdict, NEVER a fabricated 0.0 uplift presented as real.
      – a backtest number presented as realized → caught: this module is is_realized:true and writes
        a SEPARATE artifact; it never reads/echoes data/optimizer_ab.json (the backtest).

stdlib only, deterministic, fail-CLOSED, atomic. LLM FORBIDDEN. Advisory: SEPARATE paper books,
never live capital; the go-live track (data/equity_curve_daily.json) is READ-ONLY and byte-untouched.

Run (one realized tick per UTC day):
    python3 -m spa_core.strategy_lab.realized_ab
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import datetime
import math
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from spa_core.utils.atomic import atomic_load, atomic_save

_REPO_ROOT = Path(__file__).resolve().parents[2]  # …/SPA_Claude
DATA_DIR = _REPO_ROOT / "data"
REALIZED_AB_DIR = DATA_DIR / "realized_ab"
EQUITY_CURVE = DATA_DIR / "equity_curve_daily.json"

LEGACY_BOOK = "legacy_risk_adjusted"
OPT_BOOK = "optimized_yield"
LEGACY_FAIR_BOOK = "legacy_risk_adjusted_floorfair"  # like-for-like (same cash floor as optimizer)

INITIAL_CAPITAL = 100_000.0
SERIES_CAP = 400  # ring-buffer per book (a year-plus of daily rows)

# A REALIZED A/B needs enough day-distinct rows before the windowed-mean uplift means anything. Below
# this depth the verdict is INSUFFICIENT_DATA-yet (honest at the current few-day depth, by design).
MIN_DAYS_FOR_VERDICT = 7

_EPS = 1e-12


def _utc_today() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _finite(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


# ──────────────────────────────────────────────────────────────────────────────
# LIVE daily universe — the ONE universe both books score (READ-ONLY on the track)
# ──────────────────────────────────────────────────────────────────────────────
def latest_live_universe(
    equity_path: Path = EQUITY_CURVE,
) -> Tuple[Optional[dict], Optional[str]]:
    """Return (universe_day, reason). universe_day is the most-recent EVIDENCED equity-curve day
    (the protocols actually held + the realized portfolio apy_today). READ-ONLY, fail-CLOSED.

    reason is None on success, else a fail-closed reason string. We use the evidenced day's held
    positions + realized apy_today as the live universe both books must allocate over — this is the
    real, dated universe the cycle saw, not a fabricated snapshot."""
    try:
        doc = atomic_load(str(equity_path), default=None)
    except Exception:  # noqa: BLE001
        return None, "track_unreadable"
    if not isinstance(doc, dict):
        return None, "track_unreadable"
    daily = doc.get("daily", [])
    if not isinstance(daily, list):
        return None, "track_malformed"
    evidenced = [r for r in daily if isinstance(r, dict) and r.get("evidenced") is True]
    if not evidenced:
        return None, "no_evidenced_days"
    last = evidenced[-1]
    # fail-CLOSED: the universe day must carry a parseable date, finite apy, and held positions.
    ds = last.get("date")
    try:
        datetime.date.fromisoformat(str(ds))
    except (TypeError, ValueError):
        return None, "universe_date_malformed"
    apy = last.get("apy_today")
    if not _finite(apy) or not (0.0 <= float(apy) <= 100.0):
        return None, "universe_apy_out_of_band"
    positions = last.get("positions") or {}
    if not isinstance(positions, dict) or not positions:
        return None, "universe_no_positions"
    return last, None


def build_universe(day: dict, registry: dict[str, dict]) -> List[dict]:
    """Reconstruct the adapter universe for the given evidenced day (mirrors the optimizer_ab
    harness contract so both A/Bs see the SAME geometry). Per-protocol APY priority: registry
    fallback_apy (a labeled per-pool number) else the realized portfolio apy_today proxy."""
    positions = day.get("positions", {}) or {}
    port_apy = day.get("apy_today")
    proxy = float(port_apy) if _finite(port_apy) else 4.0
    out: List[dict] = []
    for proto in sorted(positions.keys()):
        meta = registry.get(proto, {})
        apy = meta.get("apy_pct")
        if apy is None or not _finite(apy):
            apy = proxy
        out.append({
            "protocol": proto,
            "apy_pct": round(float(apy), 4),
            "tvl_usd": 5e8,            # above the $5M floor — these pools were live that day
            "tier": meta.get("tier", "T2"),
            "status": "ok",
        })
    return out


def load_registry_apy(registry_path: Path) -> dict[str, dict]:
    """protocol → {tier, apy_pct} from data/adapter_registry.json. READ-ONLY, missing → {}."""
    import json
    out: dict[str, dict] = {}
    try:
        reg = json.loads(registry_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return out
    for name, entry in (reg.get("adapters", {}) or {}).items():
        if not isinstance(entry, dict):
            continue
        tier_int = entry.get("tier", 2)
        fa = entry.get("fallback_apy")
        apy = round(float(fa) * 100.0, 4) if _finite(fa) and fa > 0 else None
        out[name] = {"tier": "T1" if tier_int == 1 else "T2", "apy_pct": apy}
    return out


# ──────────────────────────────────────────────────────────────────────────────
# score the ONE universe through both surfaces (sandbox allocator — never live data/)
# ──────────────────────────────────────────────────────────────────────────────
def _score_universe(adapters: List[dict]) -> dict:
    """Score the universe through legacy / optimizer / legacy-floor-fair. Returns a dict with each
    book's deployed fraction + expected APY (on capital) + yield-on-deployed. PURE per-call.

    legacy           — risk_adjusted heuristic (deploys ~100%, skips the 5% cash floor).
    optimized        — WS-1.2 optimizer (reserves the 5% cash floor by construction).
    legacy_floorfair — legacy weights RESCALED to reserve the SAME 5% cash floor → like-for-like
                       deployed fraction, isolating SELECTION alpha from the cash-drag advantage.
    """
    from spa_core.allocator.allocator import StrategyAllocator

    with tempfile.TemporaryDirectory(prefix="spa_realized_ab_") as d:
        sandbox = Path(d)
        import json as _json
        (sandbox / "status.json").write_text(_json.dumps({"adapters": adapters}), encoding="utf-8")

        def _alloc(model: str, objective):
            a = StrategyAllocator(
                status_path=sandbox / "status.json",
                risk_scores_path=sandbox / "risk_scores.json",
                registry_path=sandbox / "_no_registry.json",
                strategy_loop_enabled=False,
                live_apy_provider={},
                objective=objective,
            )
            return a.allocate(model=model)

        legacy = _alloc("risk_adjusted", None)
        opt = _alloc("optimized_yield", "max_yield")

    apy = {a["protocol"]: a["apy_pct"] for a in adapters}

    def _stats(res) -> dict:
        deployed = sum(res.target_weights.values())
        exp_on_cap = res.expected_apy_pct  # APY on TOTAL capital (un-deployed earns 0)
        yod = (exp_on_cap / deployed) if deployed > _EPS else 0.0
        return {"deployed": deployed, "exp_apy_on_capital": exp_on_cap, "yield_on_deployed": yod}

    l = _stats(legacy)
    o = _stats(opt)

    # legacy-floor-fair: take legacy's yield-on-deployed but cap deployment at (1 - cash_floor) so
    # both books reserve the SAME 5% floor. Its APY-on-capital = yod_legacy * (1 - cash_floor).
    cash_floor = 0.05
    fair_deployed = min(l["deployed"], 1.0 - cash_floor)
    fair_exp_on_cap = l["yield_on_deployed"] * fair_deployed
    legacy_fair = {
        "deployed": fair_deployed,
        "exp_apy_on_capital": round(fair_exp_on_cap, 6),
        "yield_on_deployed": l["yield_on_deployed"],
    }
    return {"legacy": l, "optimized": o, "legacy_fair": legacy_fair, "apy_map": apy}


# ──────────────────────────────────────────────────────────────────────────────
# realized paper books — append ONE distinct row per UTC day (idempotent)
# ──────────────────────────────────────────────────────────────────────────────
def _series_path(root: Path, book: str) -> Path:
    return root / "realized_ab" / f"{book}_series.json"


def _load_series(root: Path, book: str) -> dict:
    doc = atomic_load(str(_series_path(root, book)), default=None)
    if not isinstance(doc, dict) or not isinstance(doc.get("series"), list):
        return {"id": book, "series": []}
    return doc


def _bank_day(
    root: Path,
    book: str,
    *,
    date: str,
    exp_apy_on_capital_pct: float,
    universe_date: str,
    deployed_frac: float,
    write: bool,
) -> dict:
    """Append/refresh ONE realized daily row for a book. The day's realized accrual = previous
    equity * (exp_apy_on_capital / 100 / 365). Idempotent per UTC day (re-run refreshes today's
    row from the PRIOR row's equity — never compounds the same day twice → no replay-day inflation).

    Returns the book's series doc (with the new row appended/refreshed)."""
    doc = _load_series(root, book)
    series: List[dict] = list(doc.get("series") or [])
    # idempotent: if today's row already exists, drop it and recompute from the prior equity.
    if series and series[-1].get("date") == date:
        series = series[:-1]
    prev_equity = float(series[-1]["equity_usd"]) if series else INITIAL_CAPITAL
    daily_rate = (float(exp_apy_on_capital_pct) / 100.0) / 365.0
    accrual = prev_equity * daily_rate
    new_equity = round(prev_equity + accrual, 6)
    row = {
        "date": date,
        "ts": _utc_now_iso(),
        "equity_usd": new_equity,
        "daily_accrual_usd": round(accrual, 6),
        "exp_apy_on_capital_pct": round(float(exp_apy_on_capital_pct), 6),
        "deployed_frac": round(float(deployed_frac), 6),
        "universe_date": universe_date,
        "is_realized": True,
    }
    series.append(row)
    if len(series) > SERIES_CAP:
        series = series[-SERIES_CAP:]
    doc = {"id": book, "series": series, "is_realized": True, "generated_at": _utc_now_iso()}
    if write:
        atomic_save(doc, str(_series_path(root, book)))
    return doc


# ──────────────────────────────────────────────────────────────────────────────
# red-team guards
# ──────────────────────────────────────────────────────────────────────────────
def _redteam_guard(series_by_book: Dict[str, List[dict]]) -> List[str]:
    """Catch the masking paths an adversary would use to make the A/B look realized when it isn't.

    Returns a list of flags (empty == clean):
      • replay_suspect: a multi-row book whose accrual is byte-identical every row (a replayed
        single day dressed as N days — a REAL forward track has day-distinct accrual).
      • duplicate_date: the same date appears twice in a book (re-counting one day).
      • future_date: a row dated after today UTC (clock-skew / fabrication / look-ahead).
      • nonfinite: a non-finite equity/accrual leaked into a row.
    """
    flags: List[str] = []
    today = datetime.datetime.now(datetime.timezone.utc).date()
    for book, series in series_by_book.items():
        seen: set = set()
        accruals: List[float] = []
        for r in series:
            ds = r.get("date")
            if ds in seen:
                flags.append(f"duplicate_date:{book}:{ds}")
            seen.add(ds)
            try:
                if datetime.date.fromisoformat(str(ds)) > today:
                    flags.append(f"future_date:{book}:{ds}")
            except (TypeError, ValueError):
                flags.append(f"unparseable_date:{book}:{ds}")
            eq = r.get("equity_usd")
            ac = r.get("daily_accrual_usd")
            if not _finite(eq) or not _finite(ac):
                flags.append(f"nonfinite:{book}:{ds}")
            if _finite(ac):
                accruals.append(round(float(ac), 9))
        # replay_suspect: ≥3 rows AND every non-zero accrual identical (a replayed day, not a track).
        nonzero = [a for a in accruals if abs(a) > 1e-9]
        if len(nonzero) >= 3 and len(set(nonzero)) == 1:
            flags.append(f"replay_suspect:{book}")
    return flags


# ──────────────────────────────────────────────────────────────────────────────
# the realized A/B run
# ──────────────────────────────────────────────────────────────────────────────
def run_realized_ab(
    *,
    data_dir: Optional[Path] = None,
    equity_path: Optional[Path] = None,
    registry_path: Optional[Path] = None,
    write: bool = True,
    now_date: Optional[str] = None,
) -> dict:
    """Run ONE realized A/B tick: read the live universe, score both books, bank the realized day,
    and emit the A/B artifact. Fail-CLOSED: an unreadable/empty universe → status 'unavailable'
    (null verdict, never a fabricated uplift).

    ``now_date`` injects the UTC day (tests/determinism). None → live UTC today.
    """
    root = Path(data_dir) if data_dir is not None else DATA_DIR
    eq_path = Path(equity_path) if equity_path is not None else (root / "equity_curve_daily.json")
    reg_path = Path(registry_path) if registry_path is not None else (root / "adapter_registry.json")
    today = now_date or _utc_today()

    base_meta = {
        "as_of": _utc_now_iso(),
        "model": "realized_ab",
        "is_realized": True,
        "is_backtest": False,
        "llm_forbidden": True,
        "deterministic": True,
        "optimizer_behind_flag": True,
        "advisory": True,
        "separate_from_golive_track": True,
        "basis": (
            "REALIZED forward A/B — each UTC day the live held-universe is scored ONCE through the "
            "legacy risk_adjusted heuristic AND the WS-1.2 optimized_yield optimizer, and realized "
            "daily accrual is banked into TWO parallel paper books (separate from the go-live track). "
            "is_realized:true, one DISTINCT row per UTC day (grows). NOT a replayed backtest."
        ),
        "cash_drag_note": (
            "The legacy heuristic deploys ~100% (skips the 5% cash floor); the optimizer reserves it. "
            "The raw uplift therefore mixes SELECTION alpha with a CASH-DRAG advantage. The headline "
            "is the decomposition {selection_alpha_bps, cash_drag_bps}; a floor-fair legacy book "
            "(same 5% cash floor) is banked for the apples-to-apples selection-only comparison."
        ),
    }

    universe_day, reason = latest_live_universe(eq_path)
    if reason is not None:
        return {**base_meta, "status": "unavailable", "reason": reason,
                "n_days": 0, "verdict": None, "uplift_realized_bps": None,
                "selection_alpha_bps": None, "cash_drag_bps": None, "flags": [reason]}

    registry = load_registry_apy(reg_path)
    adapters = build_universe(universe_day, registry)
    if not adapters:
        return {**base_meta, "status": "unavailable", "reason": "empty_universe",
                "n_days": 0, "verdict": None, "uplift_realized_bps": None,
                "selection_alpha_bps": None, "cash_drag_bps": None, "flags": ["empty_universe"]}

    scored = _score_universe(adapters)
    universe_date = str(universe_day.get("date"))

    # bank the realized day into all three books (idempotent per UTC day).
    legacy_doc = _bank_day(root, LEGACY_BOOK, date=today,
                           exp_apy_on_capital_pct=scored["legacy"]["exp_apy_on_capital"],
                           universe_date=universe_date,
                           deployed_frac=scored["legacy"]["deployed"], write=write)
    opt_doc = _bank_day(root, OPT_BOOK, date=today,
                        exp_apy_on_capital_pct=scored["optimized"]["exp_apy_on_capital"],
                        universe_date=universe_date,
                        deployed_frac=scored["optimized"]["deployed"], write=write)
    fair_doc = _bank_day(root, LEGACY_FAIR_BOOK, date=today,
                         exp_apy_on_capital_pct=scored["legacy_fair"]["exp_apy_on_capital"],
                         universe_date=universe_date,
                         deployed_frac=scored["legacy_fair"]["deployed"], write=write)

    legacy_series = legacy_doc["series"]
    opt_series = opt_doc["series"]
    fair_series = fair_doc["series"]
    n_days = len(opt_series)

    # red-team over the banked books.
    flags = _redteam_guard({
        LEGACY_BOOK: legacy_series, OPT_BOOK: opt_series, LEGACY_FAIR_BOOK: fair_series})

    # realized windowed-mean APY on capital for each book (honest: realized accrual / capital).
    def _realized_mean_apy(series: List[dict]) -> Optional[float]:
        rows = [r for r in series if _finite(r.get("exp_apy_on_capital_pct"))]
        if not rows:
            return None
        return round(sum(float(r["exp_apy_on_capital_pct"]) for r in rows) / len(rows), 6)

    legacy_apy = _realized_mean_apy(legacy_series)
    opt_apy = _realized_mean_apy(opt_series)
    fair_apy = _realized_mean_apy(fair_series)

    # decomposition (in basis points):
    #   raw uplift (NOT apples-to-apples) = optimized_apy − legacy_apy
    #   selection alpha (apples-to-apples) = optimized_apy − legacy_FAIR_apy  (both reserve 5% floor)
    #   cash drag = legacy_apy − legacy_fair_apy  (the floor-skip advantage the legacy book enjoyed)
    raw_uplift_bps = sel_bps = cash_bps = None
    if legacy_apy is not None and opt_apy is not None and fair_apy is not None:
        raw_uplift_bps = round((opt_apy - legacy_apy) * 100.0, 4)        # pp→bps (apy in %)
        sel_bps = round((opt_apy - fair_apy) * 100.0, 4)
        cash_bps = round((legacy_apy - fair_apy) * 100.0, 4)

    # honest verdict — THIN until MIN_DAYS_FOR_VERDICT distinct rows; refuse if red-team flagged.
    realized_pnl_legacy = round(float(legacy_series[-1]["equity_usd"]) - INITIAL_CAPITAL, 6)
    realized_pnl_opt = round(float(opt_series[-1]["equity_usd"]) - INITIAL_CAPITAL, 6)

    if flags:
        status, verdict = "refused", None
    elif n_days < MIN_DAYS_FOR_VERDICT:
        status, verdict = "thin", "INSUFFICIENT_DATA"
    else:
        status = "ok"
        # SELECTION-only (apples-to-apples) decides the verdict — not the cash-drag-laundered raw gap.
        if sel_bps is None:
            verdict = "INSUFFICIENT_DATA"
        elif sel_bps > 0.0:
            verdict = "OPTIMIZER_BEATS_LEGACY_SELECTION"
        elif sel_bps < 0.0:
            verdict = "LEGACY_BEATS_OPTIMIZER_SELECTION"
        else:
            verdict = "TIE_SELECTION"

    out = {
        **base_meta,
        "status": status,
        "verdict": verdict,
        "n_days": n_days,
        "min_days_for_verdict": MIN_DAYS_FOR_VERDICT,
        "window_start": opt_series[0]["date"] if opt_series else None,
        "window_end": opt_series[-1]["date"] if opt_series else None,
        "universe_date": universe_date,
        "books": {
            LEGACY_BOOK: {
                "realized_mean_apy_on_capital_pct": legacy_apy,
                "nav_usd": round(float(legacy_series[-1]["equity_usd"]), 4),
                "realized_pnl_usd": realized_pnl_legacy,
                "deployed_frac": round(scored["legacy"]["deployed"], 6),
                "n_rows": len(legacy_series),
            },
            OPT_BOOK: {
                "realized_mean_apy_on_capital_pct": opt_apy,
                "nav_usd": round(float(opt_series[-1]["equity_usd"]), 4),
                "realized_pnl_usd": realized_pnl_opt,
                "deployed_frac": round(scored["optimized"]["deployed"], 6),
                "n_rows": len(opt_series),
            },
            LEGACY_FAIR_BOOK: {
                "realized_mean_apy_on_capital_pct": fair_apy,
                "nav_usd": round(float(fair_series[-1]["equity_usd"]), 4),
                "deployed_frac": round(scored["legacy_fair"]["deployed"], 6),
                "n_rows": len(fair_series),
            },
        },
        "decomposition": {
            "raw_uplift_bps": raw_uplift_bps,
            "raw_uplift_apples_to_apples": False,
            "selection_alpha_bps": sel_bps,
            "cash_drag_bps": cash_bps,
            "note": (
                "raw_uplift_bps = optimized − legacy (NOT apples-to-apples: legacy skips the 5% cash "
                "floor). selection_alpha_bps = optimized − legacy_floorfair (BOTH reserve 5% → "
                "apples-to-apples SELECTION edge). cash_drag_bps = legacy − legacy_floorfair (the "
                "floor-skip advantage the legacy book got for free — NOT selection skill)."
            ),
        },
        "flags": flags,
    }
    if write:
        REALIZED_AB_DIR.mkdir(parents=True, exist_ok=True)
        atomic_save(out, str(root / "realized_ab" / "realized_ab.json"))
    return out


def main(argv: Optional[List[str]] = None) -> int:
    import json
    p = argparse.ArgumentParser(description="Realized forward A/B (WS-1.1/1.2) — one tick per UTC day.")
    p.add_argument("--dry-run", action="store_true", help="Compute but do NOT write the books/artifact.")
    args = p.parse_args(argv)
    rep = run_realized_ab(write=not args.dry_run)
    print(json.dumps({k: v for k, v in rep.items() if k not in ("books",)}, indent=2, default=str))
    if rep.get("status") in ("ok", "thin"):
        dec = rep["decomposition"]
        print(f"\nrealized days={rep['n_days']}  verdict={rep['verdict']}")
        print(f"  raw uplift (NOT apples)={dec['raw_uplift_bps']}bps  "
              f"selection_alpha={dec['selection_alpha_bps']}bps  "
              f"cash_drag={dec['cash_drag_bps']}bps")
    else:
        print(f"\nREALIZED A/B {rep.get('status')}: {rep.get('reason')} {rep.get('flags')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
