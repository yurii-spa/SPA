"""
spa_core/strategy_lab/rates_desk/refusal_engine.py — PRODUCTION advisory refusal engine.

Promotes the §8 de-risk-VALIDATED tail-risk scorer (risk_score.py + the REFUSE classifier in
fair_value.py) into a LIVE DAILY ADVISORY engine. The retrospective tests (retro.py) showed the
scorer flagged the toxic LRTs (ezETH/restaking) BEFORE their drawdowns (3/3) while keeping stETH
in the safe band — this module runs that same, UNCHANGED model every day on LIVE feed data and
writes a per-underlying verdict file the rest of SPA can consult.

CONTRACT (inherited from the Rates-Desk + repo rules):
  - PURE stdlib, deterministic — two runs over the same cached feeds produce byte-identical output
    (modulo the generated_at timestamp).
  - LLM-FORBIDDEN — no model is consulted anywhere in the verdict path.
  - FAIL-CLOSED — bad / missing / insufficient data for an underlying yields verdict UNKNOWN
    (treated as max risk), NEVER a fabricated SAFE.
  - ATOMIC write — tmp + shutil.move (repo rule #4, cross-device safe).
  - ADVISORY ONLY — this engine NEVER trades, never touches the go-live track, never overrides a
    sleeve's own depeg-kill. It writes data/refusal_status.json and exposes refusal_verdict() for
    observability / promotion-engine reasoning. Nothing here can move capital.

VERDICTS (per underlying):
  SAFE    — tail_score in the safe band (typical tight-peg LST behaviour).
  WATCH   — elevated tail score (between the safe band and the REFUSE threshold): degrading peg /
            downside drift / a hostile funding regime is building, but not yet toxic.
  REFUSE  — tail_score >= the validated REFUSE threshold: the quoted yield is tail-comp; do not
            add / consider downgrading exposure.
  UNKNOWN — fail-closed: no usable data for this underlying this run (never silently SAFE).

The verdict is derived from the SAME validated thresholds (config.SAFE_MEDIAN_BAND /
config.TAIL_REFUSE_THRESHOLD) used by the retro tests, evaluated on the LATEST date of a trailing
window of LIVE ratio + funding data (no look-ahead — score_on_date uses only data up to the date).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Dict, List, Optional

from spa_core.strategy_lab.base import InvalidDataError
from spa_core.strategy_lab.data.market_data import MarketData
from spa_core.strategy_lab.rates_desk import config as C
from spa_core.strategy_lab.rates_desk.risk_score import score_on_date

_ROOT = Path(__file__).resolve().parents[3]  # …/SPA_Claude
_DATA = _ROOT / "data"
DEFAULT_OUT = _DATA / "refusal_status.json"

# Underlyings we score from the live feeds. LRT/restaking = the suspects; LST = the safe path.
# (Order preserved for a stable, deterministic report ordering.)
LRT_SUSPECT = ("ezeth", "eeth", "weeth")   # restaking tokens
LST_SAFE = ("steth", "reth")               # plain-staking tokens
TRACKED_UNDERLYINGS = LRT_SUSPECT + LST_SAFE

# Trailing window (days) of live ratio history pulled for scoring. Must comfortably exceed the
# scorer's longest trailing window (RATIO_PEAK_WINDOW / DRIFT_VOL_WINDOW / FUNDING_WINDOW) so the
# latest date is scored on a full, warmed-up window rather than failing-closed on warm-up.
SCORE_WINDOW_DAYS = max(C.RATIO_PEAK_WINDOW, C.DRIFT_VOL_WINDOW, C.FUNDING_WINDOW) + 15

# Verdict labels (single source of truth).
SAFE = "SAFE"
WATCH = "WATCH"
REFUSE = "REFUSE"
UNKNOWN = "UNKNOWN"


# ── atomic JSON write (repo rule #4) ──────────────────────────────────────────────────────────
def _atomic_write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix="." + path.stem + "_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=2, sort_keys=True)
        shutil.move(tmp, str(path))  # atomic, cross-device safe (repo rule #4)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


# ── verdict classification (from the VALIDATED thresholds) ────────────────────────────────────
def classify(tail_score: float, failed_closed: bool) -> str:
    """Map a tail score (0..1) to SAFE / WATCH / REFUSE, fail-CLOSED to UNKNOWN.

    Bands (the SAME validated cutoffs the retro tests use):
        score >= TAIL_REFUSE_THRESHOLD      → REFUSE  (yield is tail-comp)
        score >  SAFE_MEDIAN_BAND           → WATCH   (elevated, building risk)
        else                                → SAFE
    A fail-closed score (no usable data) or a malformed score → UNKNOWN (never a silent SAFE)."""
    if failed_closed:
        return UNKNOWN
    if not isinstance(tail_score, (int, float)) or not (0.0 <= tail_score <= 1.0):
        return UNKNOWN
    if tail_score >= C.TAIL_REFUSE_THRESHOLD:
        return REFUSE
    if tail_score > C.SAFE_MEDIAN_BAND:
        return WATCH
    return SAFE


def _funding_regime(funding_flip_prob: float, failed_closed: bool) -> str:
    """Human-readable funding regime from the funding-flip probability (advisory text only)."""
    if failed_closed:
        return "unknown"
    if funding_flip_prob >= C.FUNDING_FLIP_FULL:
        return "hostile (carry unwinding)"
    if funding_flip_prob > 0.0:
        return "mixed"
    return "benign"


def _reason(symbol: str, verdict: str, ts) -> str:
    """One-line, deterministic justification for the verdict, citing the driving components."""
    if verdict == UNKNOWN:
        return f"{symbol}: no usable live data this run — fail-closed to UNKNOWN ({ts.reason or 'insufficient history'})"
    depeg_pct = round(ts.depeg_dd * 100, 2)
    dd_vol_pct = round(ts.downside_drift_vol * 100, 3)
    regime = _funding_regime(ts.funding_flip_prob, ts.failed_closed)
    base = (f"{symbol}: depeg drawdown {depeg_pct}% (vs trailing peak), "
            f"downside-drift vol {dd_vol_pct}%/day, funding regime {regime}")
    if verdict == REFUSE:
        return (f"REFUSE — tail score {round(ts.score, 3)} >= {C.TAIL_REFUSE_THRESHOLD} "
                f"(quoted yield is tail-comp). {base}")
    if verdict == WATCH:
        return (f"WATCH — tail score {round(ts.score, 3)} above safe band {C.SAFE_MEDIAN_BAND}. "
                f"{base}")
    return f"SAFE — tail score {round(ts.score, 3)} within safe band {C.SAFE_MEDIAN_BAND}. {base}"


# ── live data loading ──────────────────────────────────────────────────────────────────────────
def _load_live(market: Optional[MarketData]):
    """Pull a trailing window of LIVE ratio + funding history from the market-data unifier.

    Returns (ratios_by_symbol, funding_by_date, latest_date). On any data-layer failure the
    underlyings simply come back empty and the engine fails-closed to UNKNOWN per underlying —
    we NEVER fabricate a series."""
    md = market or MarketData()
    # latest available date across the loaded series; build a trailing window ending there.
    try:
        latest = md.latest()
    except InvalidDataError:
        return {}, {}, None
    end = latest.date
    try:
        start = (datetime.date.fromisoformat(end)
                 - datetime.timedelta(days=SCORE_WINDOW_DAYS)).isoformat()
    except ValueError:
        return {}, {}, None

    ratios_by_symbol: Dict[str, Dict[str, float]] = {s: {} for s in TRACKED_UNDERLYINGS}
    funding_by_date: Dict[str, float] = {}
    try:
        snaps = md.historical_range(start, end)
    except InvalidDataError:
        return {}, {}, end
    for snap in snaps:
        f, ok = snap.get_funding()
        if ok and f is not None:
            funding_by_date[snap.date] = float(f)
        for sym in TRACKED_UNDERLYINGS:
            r, rok = snap.get_lrt_ratio(sym)
            if rok and r is not None and r > 0:
                ratios_by_symbol[sym][snap.date] = float(r)
    return ratios_by_symbol, funding_by_date, end


# ── report ──────────────────────────────────────────────────────────────────────────────────────
def build_report(
    write: bool = True,
    market: Optional[MarketData] = None,
    out_path: Optional[Path] = None,
    cfg=C,
) -> dict:
    """Score EVERY tracked underlying from LIVE data and (optionally) write
    data/refusal_status.json atomically.

    Args:
        write:    write the JSON when True (default). False = compute only (tests/determinism).
        market:   inject a MarketData (tests/hermetic). None → the live unifier.
        out_path: override the output path (tests).
        cfg:      threshold config (tests). Defaults to the validated rates_desk config.

    Returns the report dict:
        {generated_at, model, llm_forbidden, advisory, latest_date, thresholds,
         verdict_counts, underlyings:[{symbol, group, tail_score, verdict, reason,
         metrics:{depeg_pct, dd_vol, funding_regime, ...}}]}

    Deterministic + FAIL-CLOSED: an underlying with no usable live data scores UNKNOWN (never a
    fabricated SAFE). This engine is ADVISORY — it writes a file and nothing else; it cannot trade."""
    ratios_by_symbol, funding_by_date, latest_date = _load_live(market)

    underlyings: List[dict] = []
    for sym in TRACKED_UNDERLYINGS:
        rser = ratios_by_symbol.get(sym, {})
        group = "LRT(restaking)" if sym in LRT_SUSPECT else "LST(staking)"
        if not rser or latest_date is None:
            # fail-closed: no usable live data → UNKNOWN (max risk), never SAFE.
            underlyings.append({
                "symbol": sym,
                "group": group,
                "tail_score": None,
                "verdict": UNKNOWN,
                "reason": (f"{sym}: no usable live ratio data this run — fail-closed to UNKNOWN"),
                "metrics": {
                    "depeg_pct": None, "dd_vol": None, "funding_regime": "unknown",
                    "funding_flip_prob": None, "failed_closed": True, "score_date": latest_date,
                },
            })
            continue

        # score the LATEST date on the trailing window (no look-ahead — score_on_date uses <= date)
        score_date = max(rser)
        ts = score_on_date(sym, rser, score_date, funding_by_date, cfg)
        verdict = classify(ts.score, ts.failed_closed)
        underlyings.append({
            "symbol": sym,
            "group": group,
            "tail_score": None if ts.failed_closed else round(ts.score, 6),
            "verdict": verdict,
            "reason": _reason(sym, verdict, ts),
            "metrics": {
                "depeg_pct": round(ts.depeg_dd * 100, 4),
                "dd_vol": round(ts.downside_drift_vol, 6),
                "funding_regime": _funding_regime(ts.funding_flip_prob, ts.failed_closed),
                "funding_flip_prob": round(ts.funding_flip_prob, 6),
                "depeg_sub": round(ts.depeg_sub, 6),
                "drift_sub": round(ts.drift_sub, 6),
                "funding_sub": round(ts.funding_sub, 6),
                "failed_closed": ts.failed_closed,
                "score_date": score_date,
            },
        })

    verdict_counts: Dict[str, int] = {SAFE: 0, WATCH: 0, REFUSE: 0, UNKNOWN: 0}
    for u in underlyings:
        verdict_counts[u["verdict"]] = verdict_counts.get(u["verdict"], 0) + 1

    report = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "model": "rates_desk_refusal_engine",
        "llm_forbidden": True,
        "advisory": True,  # NEVER trades / touches the go-live track
        "latest_date": latest_date,
        "thresholds": {
            "refuse_threshold": cfg.TAIL_REFUSE_THRESHOLD,
            "safe_band": cfg.SAFE_MEDIAN_BAND,
            "depeg_dd_full": cfg.DEPEG_DD_FULL,
            "drift_vol_full": cfg.DRIFT_VOL_FULL,
            "funding_flip_full": cfg.FUNDING_FLIP_FULL,
            "weights": {"depeg": cfg.W_DEPEG, "drift": cfg.W_DRIFT, "funding": cfg.W_FUNDING},
        },
        "verdict_counts": verdict_counts,
        "underlyings": underlyings,
    }

    if write:
        _atomic_write_json(Path(out_path) if out_path else DEFAULT_OUT, report)
    return report


# ── advisory consultation helper (for sleeves / the promotion engine) ─────────────────────────
def refusal_verdict(symbol: str, status_path: Optional[Path] = None) -> dict:
    """Read the latest refusal verdict for one underlying from data/refusal_status.json.

    ADVISORY / observability only — callers (the crypto sleeves' diagnostics, the promotion
    engine's reasoning) consult this to FLAG / DOWNGRADE an underlying marked REFUSE. It does NOT
    and MUST NOT alter any sleeve's own depeg-kill logic or the go-live track.

    FAIL-CLOSED: a missing/corrupt status file, or an unscored symbol, returns
    {verdict: "UNKNOWN", ...} — never a fabricated SAFE.

    Returns {symbol, verdict, tail_score, reason, generated_at}."""
    path = Path(status_path) if status_path else DEFAULT_OUT
    sym = (symbol or "").lower()
    fallback = {
        "symbol": sym, "verdict": UNKNOWN, "tail_score": None,
        "reason": "no refusal_status.json (advisory verdict unavailable — fail-closed)",
        "generated_at": None,
    }
    try:
        with open(path, "r", encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return fallback
    if not isinstance(doc, dict):
        return fallback
    gen = doc.get("generated_at")
    for u in doc.get("underlyings", []) or []:
        if isinstance(u, dict) and str(u.get("symbol", "")).lower() == sym:
            return {
                "symbol": sym,
                "verdict": u.get("verdict", UNKNOWN),
                "tail_score": u.get("tail_score"),
                "reason": u.get("reason", ""),
                "generated_at": gen,
            }
    return {**fallback, "generated_at": gen,
            "reason": f"{sym} not in refusal_status.json (fail-closed to UNKNOWN)"}


def is_refused(symbol: str, status_path: Optional[Path] = None) -> bool:
    """Convenience advisory boolean: True iff the underlying's latest verdict is REFUSE.

    Fail-closed: UNKNOWN / missing is NOT reported as refused here (it is surfaced as UNKNOWN via
    refusal_verdict); this helper is strictly 'is the live verdict an explicit REFUSE'."""
    return refusal_verdict(symbol, status_path).get("verdict") == REFUSE


# ── CLI ──────────────────────────────────────────────────────────────────────────────────────
def _print_table(report: dict) -> None:
    print(f"Rates-Desk Refusal Engine (ADVISORY)   latest_date={report.get('latest_date')}")
    thr = report.get("thresholds", {})
    print(f"  REFUSE >= {thr.get('refuse_threshold')}   SAFE <= {thr.get('safe_band')}")
    vc = report.get("verdict_counts", {})
    print(f"  SAFE={vc.get('SAFE', 0)}  WATCH={vc.get('WATCH', 0)}  "
          f"REFUSE={vc.get('REFUSE', 0)}  UNKNOWN={vc.get('UNKNOWN', 0)}")
    print()
    hdr = f"{'underlying':10s} {'group':16s} {'verdict':8s} {'tail':>7s} {'depeg%':>8s} {'ddvol':>8s}  funding"
    print(hdr)
    print("-" * len(hdr))
    for u in report.get("underlyings", []):
        m = u.get("metrics", {})
        ts = u.get("tail_score")
        ts_s = f"{ts:7.3f}" if isinstance(ts, (int, float)) else f"{'—':>7s}"
        dp = m.get("depeg_pct")
        dp_s = f"{dp:8.2f}" if isinstance(dp, (int, float)) else f"{'—':>8s}"
        dv = m.get("dd_vol")
        dv_s = f"{dv*100:7.3f}%" if isinstance(dv, (int, float)) else f"{'—':>8s}"
        print(f"{u['symbol']:10s} {u['group']:16s} {u['verdict']:8s} {ts_s} {dp_s} {dv_s}  "
              f"{m.get('funding_regime', '?')}")


def main() -> int:
    report = build_report(write=True)
    _print_table(report)
    print(f"\nWrote {DEFAULT_OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
