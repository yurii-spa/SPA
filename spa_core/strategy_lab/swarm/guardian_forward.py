"""Swarm block 1 — L2 position guardians on the LIVE aggressive_lab forward paper track.

Charter: docs/SWARM_ARCHITECTURE.md · validated numbers: docs/DYNAMIC_LEVERAGE_GUARDIAN.md (idea #1,
OOS-validated pre-emptive vol-guardian). This module gives every aggressive_lab paper book a personal
position guardian: each tick it recomputes, deterministically and causally, the guarded (vol-overlay)
version of the book's FORWARD equity next to the raw one, plus the guardian's live state
(ARMED / DERISKED / WARMUP / NO_FORWARD) and every de-risk / re-entry event with its date.

Design decisions (honest, restart-proof):
  • The canonical overlay `aggressive_lab.guardian.apply_guardian_vol` stays authoritative — this
    module re-derives the SAME math with a per-day exposure trace (`vol_guardian_trace`), and a test
    asserts the two produce identical equity, so they can never silently diverge.
  • The overlay is causal (uses only trailing returns), so re-running the WHOLE overlay from scratch
    each tick is idempotent and needs no persisted state — restart-survival for free.
  • Vol baseline warm-up: the guardian needs ~4×lookback days of history, but the forward track is
    young. We seed it with the tail of the book's own BACKTEST-phase series, normalized so its last
    point equals the first forward point (seam return = 0 — no fabricated jump). Labeled in output.
  • Parameters are the OOS-validated ones from the registry sweep (vol_mult=2.0, lookback=10,
    derisk_frac=0.0 full exit, calm_mult=1.2, roundtrip_cost=0.0015 honest churn drag).
  • Fail-CLOSED: a book with no readable series or no forward days gets state NO_FORWARD and no
    invented numbers. Guardians are DE-RISK-ONLY by construction (exposure ∈ {derisk_frac, 1.0}).

TIER PORT — S1 SHADOW DOMAINS (charter «Тир-перенос», owner-requested 2026-07-11): the same
pre-emptive vol-guardian also watches, SIGNAL-ONLY, (a) every Strategy-Lab sleeve forward series
(the Balanced-tier candidates) and (b) the LIVE conservative go-live equity curve. For those
domains the guardian is a pure SHADOW: it computes the signal and the what-if overlay but acts on
NOTHING — RiskPolicy v1.0 stays the sole execution gate and the two-tier kill ladder is untouched;
wiring this signal into the live cycle would require a new ADR + owner approval (the sanctioned
path is an RTMR sensor). The shadow exists to ACCUMULATE EVIDENCE (S2): how often and how early
the vol signal leads the reactive kill events.

ADVISORY / paper-only / OUTSIDE_RISKPOLICY: moves no capital, never touches the go-live track
(reads it read-only for the shadow), writes ONLY data/swarm/. Deterministic, stdlib-only.
LLM FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Sequence

from spa_core.strategy_lab.aggressive_lab.guardian import apply_guardian_vol, stdev
from spa_core.strategy_lab.swarm.common import (
    GENESIS_HASH,
    append_daily_proof,
    apy_pct as _apy_pct,
    max_drawdown_pct as _max_drawdown_pct,
)
from spa_core.utils.atomic import atomic_save

__all__ = ["vol_guardian_trace", "run_forward_guardian", "GUARDIAN_PARAMS"]

REPO_ROOT = Path(__file__).resolve().parents[3]
AGGRESSIVE_LAB_DIR = REPO_ROOT / "data" / "aggressive_lab"
STRATEGY_LAB_PAPER_DIR = REPO_ROOT / "data" / "strategy_lab_paper"
LIVE_TRACK_PATH = REPO_ROOT / "data" / "equity_curve_daily.json"
RTMR_POSTURE_PATH = REPO_ROOT / "data" / "monitoring" / "risk_posture.json"
SWARM_DIR = REPO_ROOT / "data" / "swarm"
STATUS_NAME = "guardian_forward.json"
PROOF_NAME = "guardian_forward_proof.jsonl"

# ── RTMR exogenous wiring (упреждение раньше собственной vol) ──────────────────────────────────
# Which RTMR posture keys concern which book (matched case-insensitively as substrings against
# the posture entry keys). HONEST SEMANTICS: a posture entry frozen for a STALE/BLIND SENSOR is
# RTMR's own fail-closed housekeeping, NOT market trouble — it must never cascade into a false
# aggressive de-risk (mirrors RTMR's "systemic exit only on FRESH critical" rule). Only entries
# whose reason is NOT staleness count as an exogenous de-risk signal.
BOOK_POSTURE_KEYS: Dict[str, tuple] = {
    "susde_dn": ("usde", "susde", "ethena", "usdt", "usdc"),
    "susde_spot": ("usde", "susde", "ethena"),
    "pendle_pt_levered": ("usde", "susde", "pendle"),
    "pendle_yt_susde": ("usde", "susde", "pendle"),
    "points_farm": ("usde", "susde", "ethena"),
    "eth_directional": ("eth",),
    "lrt_neutral": ("eth", "eeth", "weeth", "restaking"),
    "levered_restaking": ("eth", "steth", "reth"),
    "leverage_loop": ("eth", "steth"),
    "lp_eth_stable": ("eth", "usdc"),
}
_EXOGENOUS_STATES = {"FULL_EXIT", "REDUCE", "FROZEN"}  # FROZEN counts only if reason ≠ staleness


def _load_rtmr_entries(path: Path = RTMR_POSTURE_PATH) -> Dict[str, dict]:
    try:
        doc = json.loads(path.read_text())
        entries = doc.get("entries") if isinstance(doc, dict) else None
        return entries if isinstance(entries, dict) else {}
    except (OSError, ValueError):
        return {}


def _rtmr_context_for(book: str, entries: Dict[str, dict]) -> Optional[dict]:
    """The book's slice of the RTMR posture + the honest exogenous verdict."""
    keys = BOOK_POSTURE_KEYS.get(book)
    if not keys or not entries:
        return None
    hits = {}
    exogenous = False
    for name, e in entries.items():
        if not isinstance(e, dict):
            continue
        low = str(name).lower()
        if any(k in low for k in keys):
            state = str(e.get("state", ""))
            reason = str(e.get("reason", ""))
            stale = "stale" in reason.lower() or "blind" in reason.lower()
            hits[name] = {"state": state, "reason": reason, "stale_sensor": stale}
            if state in _EXOGENOUS_STATES and not stale:
                exogenous = True
    if not hits:
        return None
    return {"entries": hits, "exogenous_derisk": exogenous,
            "note": "stale/blind-sensor freezes are RTMR housekeeping, not market trouble — "
                    "they never trigger the exogenous flag"}

# OOS-validated params (docs/DYNAMIC_LEVERAGE_GUARDIAN.md idea #1 / scripts/guardian_backtest.py sweep).
# min_vol: absolute daily-vol floor guarding zero-vol books from numeric-dust false de-risks
# (caught live on engine_b, 2026-07-11) — see apply_guardian_vol docstring.
GUARDIAN_PARAMS = {
    "lookback": 10,
    "vol_mult": 2.0,
    "derisk_frac": 0.0,
    "calm_mult": 1.2,
    "roundtrip_cost": 0.0015,
    "min_vol": 1e-5,
}
# Warm-up tail taken from the backtest phase: baseline window (4×lookback) + recent window + 1.
WARMUP_POINTS = 4 * GUARDIAN_PARAMS["lookback"] + GUARDIAN_PARAMS["lookback"] + 1


def vol_guardian_trace(
    equity: Sequence[float],
    *,
    lookback: int = GUARDIAN_PARAMS["lookback"],
    vol_mult: float = GUARDIAN_PARAMS["vol_mult"],
    derisk_frac: float = GUARDIAN_PARAMS["derisk_frac"],
    calm_mult: float = GUARDIAN_PARAMS["calm_mult"],
    roundtrip_cost: float = GUARDIAN_PARAMS["roundtrip_cost"],
    min_vol: float = GUARDIAN_PARAMS["min_vol"],
) -> Tuple[List[float], List[float], List[Tuple[int, str]]]:
    """Same math as the canonical `apply_guardian_vol`, but ALSO returns the per-return exposure
    trace and the (index, action) event list. `events` index i refers to the day of equity[i+1]
    (the day the new exposure takes effect). Equity output MUST equal apply_guardian_vol's —
    guarded by test_trace_matches_canonical_overlay."""
    equity = list(equity)
    if len(equity) < lookback + 2:
        return equity, [1.0] * max(0, len(equity) - 1), []
    rets = [equity[i] / equity[i - 1] - 1.0 for i in range(1, len(equity)) if equity[i - 1]]
    guarded = [equity[0]]
    exposure = 1.0
    exposures: List[float] = []
    events: List[Tuple[int, str]] = []
    for i in range(len(rets)):
        if i >= lookback:
            recent = stdev(rets[i - lookback + 1: i + 1])
            base = stdev(rets[max(0, i - 4 * lookback): i - lookback + 1]) or 1e-9
            prev = exposure
            if exposure >= 1.0 and recent > vol_mult * base and recent > min_vol:
                exposure = derisk_frac
            elif exposure < 1.0 and (recent < calm_mult * base or recent < min_vol):
                exposure = 1.0
            if exposure != prev:
                events.append((i, "DERISK" if exposure < prev else "REENTER"))
                if roundtrip_cost:
                    guarded[-1] *= (1.0 - roundtrip_cost * abs(prev - exposure))
        exposures.append(exposure)
        guarded.append(guarded[-1] * (1.0 + rets[i] * exposure))
    return guarded, exposures, events


def _load_series(book_dir: Path) -> List[dict]:
    """Read a book's hash-chained realized_series.jsonl. Malformed lines are skipped (fail-closed:
    we never invent a bar); returns [] if the file is missing/unreadable."""
    path = book_dir / "realized_series.jsonl"
    entries: List[dict] = []
    try:
        with path.open() as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    doc = json.loads(line)
                except ValueError:
                    continue
                if isinstance(doc, dict) and isinstance(doc.get("equity_usd"), (int, float)):
                    entries.append(doc)
    except OSError:
        return []
    return entries


def _guard_book(book_dir: Path) -> dict:
    """Compute one book's guardian view: raw vs guarded FORWARD window + live guardian state."""
    entries = _load_series(book_dir)
    meta = {}
    try:
        meta = json.loads((book_dir / "meta.json").read_text())
    except (OSError, ValueError):
        pass
    base = {
        "risk_class": meta.get("risk_class"),
        "risk_shape": meta.get("risk_shape"),
        "headline_apy_pct": meta.get("headline_apy_pct"),
    }
    backtest = [e for e in entries if e.get("phase") == "backtest"]
    forward = [e for e in entries if e.get("phase") == "forward"]
    if not forward:
        return {**base, "state": "NO_FORWARD", "forward_days": 0,
                "note": "no forward paper days yet — guardian arms on first tick"}

    fwd_eq = [float(e["equity_usd"]) for e in forward]
    fwd_dates = [str(e.get("date") or e.get("as_of") or "") for e in forward]

    # Warm-up: backtest tail normalized so its last point == first forward point (seam return 0).
    tail = [float(e["equity_usd"]) for e in backtest][-WARMUP_POINTS:]
    if tail and tail[-1] > 0:
        scale = fwd_eq[0] / tail[-1]
        combined = [v * scale for v in tail] + fwd_eq[1:]
        fs = len(tail) - 1  # index of the forward start inside `combined`
    else:
        combined, fs = fwd_eq, 0

    guarded, exposures, events = vol_guardian_trace(combined)
    warmed = len(combined) >= GUARDIAN_PARAMS["lookback"] + 2

    # Rebase both windows to the forward start so raw vs guarded compare 1:1.
    raw_w = [v / combined[fs] for v in combined[fs:]]
    grd_w = [v / guarded[fs] for v in guarded[fs:]]
    fwd_days = len(forward)

    # Live signal snapshot (same trailing windows the guardian uses).
    rets = [combined[i] / combined[i - 1] - 1.0 for i in range(1, len(combined)) if combined[i - 1]]
    lb = GUARDIAN_PARAMS["lookback"]
    i = len(rets) - 1
    signal = None
    if warmed and i >= lb:
        recent = stdev(rets[i - lb + 1: i + 1])
        baseline = stdev(rets[max(0, i - 4 * lb): i - lb + 1]) or 1e-9
        signal = {"recent_vol": round(recent, 8), "baseline_vol": round(baseline, 8),
                  "ratio": round(recent / baseline, 3), "derisk_threshold": GUARDIAN_PARAMS["vol_mult"]}

    exposure_now = exposures[-1] if exposures else 1.0
    # Only events on forward days are the live guardian's acts (warmup events are context).
    fwd_events = [
        {"date": fwd_dates[j - fs] if 0 <= j - fs < len(fwd_dates) else None, "action": act}
        for j, act in ((idx + 1, act) for idx, act in events) if j >= fs
    ]
    return {
        **base,
        "state": ("WARMUP" if not warmed else ("DERISKED" if exposure_now < 1.0 else "ARMED")),
        "forward_days": fwd_days,
        "forward_window": {"start": fwd_dates[0], "end": fwd_dates[-1]},
        "raw": {"equity_usd": round(fwd_eq[-1], 2),
                "apy_pct": _apy_pct(raw_w, fwd_days), "max_dd_pct": _max_drawdown_pct(raw_w)},
        "guarded": {"equity_usd": round(fwd_eq[0] * grd_w[-1], 2),
                    "apy_pct": _apy_pct(grd_w, fwd_days), "max_dd_pct": _max_drawdown_pct(grd_w)},
        "exposure_now": exposure_now,
        "derisk_events_forward": fwd_events,
        "signal": signal,
        "warmup_source": "backtest_tail_normalized" if fs else "forward_only",
        "backtest_days_context": len(backtest),
    }


# ── Systemic sentinel (В): the one slow risk no per-book guardian can see ──────────────────────
SYSTEMIC_CORR_WINDOW = 30      # trailing daily returns per book
SYSTEMIC_CORR_THRESHOLD = 0.7  # median pairwise corr above this = books moving as one
SYSTEMIC_MIN_DERISKED = 2      # AND at least this many guardians already fired


def _pearson(a: List[float], b: List[float]) -> Optional[float]:
    n = min(len(a), len(b))
    if n < 5:
        return None
    a, b = a[-n:], b[-n:]
    ma, mb = sum(a) / n, sum(b) / n
    va = sum((x - ma) ** 2 for x in a) ** 0.5
    vb = sum((x - mb) ** 2 for x in b) ** 0.5
    if va < 1e-12 or vb < 1e-12:
        return None  # a flat book has no co-movement to measure — exclude, don't fake 0
    return sum((a[i] - ma) * (b[i] - mb) for i in range(n)) / (va * vb)


def _systemic_sentinel(books: Dict[str, dict], agg_dir: Path) -> dict:
    """Cross-book contagion watch: in a SYSTEMIC crisis all crypto legs correlate toward 1 —
    the registry's own honest caveat, which no per-book guardian can see. Deterministic:
    median pairwise correlation of trailing daily returns + count of already-derisked guardians.
    SIGNAL-ONLY here; the swarm book (block A) is the consumer that acts on it (paper)."""
    rets: Dict[str, List[float]] = {}
    for name in books:
        entries = _load_series(agg_dir / name)[-1 - SYSTEMIC_CORR_WINDOW:]
        # returns WITHIN a phase only — the backtest→forward seam is an equity RE-BASE
        # (163k → 100k), not a market move; naive returns across it fabricate a giant
        # common "crash" that dominates every correlation (caught live 2026-07-11)
        r = [float(entries[i]["equity_usd"]) / float(entries[i - 1]["equity_usd"]) - 1.0
             for i in range(1, len(entries))
             if float(entries[i - 1].get("equity_usd") or 0) > 0
             and entries[i].get("phase") == entries[i - 1].get("phase")]
        if len(r) >= 5:
            rets[name] = r
    names = sorted(rets)
    corrs: List[float] = []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            c = _pearson(rets[names[i]], rets[names[j]])
            if c is not None:
                corrs.append(c)
    median_corr = sorted(corrs)[len(corrs) // 2] if corrs else None
    derisked = sorted(n for n, v in books.items() if v.get("state") == "DERISKED")
    systemic = (median_corr is not None and median_corr > SYSTEMIC_CORR_THRESHOLD
                and len(derisked) >= SYSTEMIC_MIN_DERISKED)
    return {
        "state": "SYSTEMIC" if systemic else "NORMAL",
        "median_pairwise_corr": round(median_corr, 4) if median_corr is not None else None,
        "pairs_measured": len(corrs),
        "books_in_window": names,
        "derisked_now": derisked,
        "thresholds": {"corr": SYSTEMIC_CORR_THRESHOLD, "min_derisked": SYSTEMIC_MIN_DERISKED,
                       "window_days": SYSTEMIC_CORR_WINDOW},
        "note": ("SYSTEMIC = books co-moving (median corr > threshold) AND ≥N guardians already "
                 "fired — the all-to-cash recommendation for the swarm paper book. Window mixes "
                 "backtest+forward bars while the forward track is young (honest, converges)."),
    }


# ── S1 shadow domains: Strategy-Lab sleeves + the LIVE conservative track (signal-only) ────────
def _guard_shadow(dates: List[str], equity: List[float], *, domain: str) -> dict:
    """Pure SHADOW guardian over one continuous daily series: live signal + what-if overlay.
    Signal-only by construction — the returned view carries no authority over any book."""
    if len(equity) < GUARDIAN_PARAMS["lookback"] + 2:
        return {"domain": domain, "state": "WARMUP", "days": len(equity),
                "note": f"needs ≥{GUARDIAN_PARAMS['lookback'] + 2} daily points"}
    guarded, exposures, events = vol_guardian_trace(equity)
    rets = [equity[i] / equity[i - 1] - 1.0 for i in range(1, len(equity)) if equity[i - 1]]
    lb = GUARDIAN_PARAMS["lookback"]
    i = len(rets) - 1
    recent = stdev(rets[i - lb + 1: i + 1])
    baseline = stdev(rets[max(0, i - 4 * lb): i - lb + 1]) or 1e-9
    raw0 = equity[0] or 1.0
    return {
        "domain": domain,
        "state": "DERISKED" if (exposures and exposures[-1] < 1.0) else "ARMED",
        "days": len(equity),
        "window": {"start": dates[0], "end": dates[-1]},
        "signal": {"recent_vol": round(recent, 8), "baseline_vol": round(baseline, 8),
                   "ratio": round(recent / baseline, 3),
                   "derisk_threshold": GUARDIAN_PARAMS["vol_mult"]},
        "what_if": {"raw_max_dd_pct": _max_drawdown_pct([v / raw0 for v in equity]),
                    "guarded_max_dd_pct": _max_drawdown_pct([v / guarded[0] for v in guarded])},
        "derisk_events": [
            {"date": dates[j] if 0 <= (j := idx + 1) < len(dates) else None, "action": act}
            for idx, act in events][-10:],
        "shadow_only": True,
    }


def _load_sleeve_series(path: Path) -> Optional[tuple]:
    """strategy_lab paper series {'series': [{date, equity_usd}, …]} → (dates, equity)."""
    try:
        doc = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    rows = doc.get("series") if isinstance(doc, dict) else None
    if not isinstance(rows, list):
        return None
    pairs = [(str(r["date"]), float(r["equity_usd"])) for r in rows
             if isinstance(r, dict) and r.get("date")
             and isinstance(r.get("equity_usd"), (int, float))]
    pairs.sort()
    return ([d for d, _ in pairs], [e for _, e in pairs]) if pairs else None


def _load_live_track(path: Path) -> Optional[tuple]:
    """READ-ONLY view of the canonical go-live curve {'daily': [{date, close_equity}, …]}."""
    try:
        doc = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    rows = doc.get("daily") if isinstance(doc, dict) else None
    if not isinstance(rows, list):
        return None
    pairs = [(str(r["date"]), float(r["close_equity"])) for r in rows
             if isinstance(r, dict) and r.get("date")
             and isinstance(r.get("close_equity"), (int, float))]
    pairs.sort()
    return ([d for d, _ in pairs], [e for _, e in pairs]) if pairs else None


def _shadow_domains(sleeves_dir: Path, live_track_path: Path) -> dict:
    """All S1 shadow views: every Strategy-Lab sleeve series + the live conservative track."""
    sleeves: Dict[str, dict] = {}
    if sleeves_dir.is_dir():
        for p in sorted(sleeves_dir.glob("*_series.json")):
            name = p.stem.replace("_series", "")
            loaded = _load_sleeve_series(p)
            if loaded:
                sleeves[name] = _guard_shadow(*loaded, domain=f"strategy_lab.{name}")
    live = None
    loaded = _load_live_track(live_track_path)
    if loaded:
        live = _guard_shadow(*loaded, domain="live_track_conservative")
        live["note"] = ("SHADOW of the canonical go-live track — SIGNAL ONLY: RiskPolicy v1.0 "
                        "remains the sole gate and the two-tier kill ladder is untouched; acting "
                        "on this signal requires a new ADR + owner (sanctioned path: RTMR sensor). "
                        "Purpose: accumulate lead-time evidence (S2).")
    return {
        "label": "S1 tier-port shadow guardians / SIGNAL-ONLY / zero authority",
        "sleeves": sleeves,
        "live_track": live if live else {"state": "NO_DATA",
                                         "note": "equity_curve_daily.json missing/unreadable"},
    }


def _append_proof(doc: dict, proof_path: Path) -> bool:
    """Hash-chain one line per UTC day (idempotent per day). Returns True if appended."""
    payload = {
        "books": len(doc["books"]),
        "derisked_now": sorted(b for b, v in doc["books"].items() if v.get("state") == "DERISKED"),
        "forward_days_max": max((v.get("forward_days", 0) for v in doc["books"].values()), default=0),
        "shadow_derisked": doc.get("summary", {}).get("shadow_derisked", []),
    }
    return append_daily_proof(payload, proof_path, day=doc["as_of_utc"][:10])


def run_forward_guardian(
    agg_dir: Path = AGGRESSIVE_LAB_DIR,
    out_dir: Path = SWARM_DIR,
    sleeves_dir: Path = STRATEGY_LAB_PAPER_DIR,
    live_track_path: Path = LIVE_TRACK_PATH,
) -> dict:
    """One guardian pass: every aggressive_lab book (authoritative for the aggressive paper
    domain) + the S1 SHADOW domains (Strategy-Lab sleeves + live conservative track, signal-only).
    Writes the status JSON + daily proof line; deterministic given the inputs (timestamp aside)."""
    books: Dict[str, dict] = {}
    rtmr_entries = _load_rtmr_entries()
    if agg_dir.is_dir():
        for book_dir in sorted(p for p in agg_dir.iterdir() if p.is_dir()):
            if (book_dir / "realized_series.jsonl").exists():
                view = _guard_book(book_dir)
                ctx = _rtmr_context_for(book_dir.name, rtmr_entries)
                if ctx is not None:
                    view["rtmr"] = ctx
                    # exogenous OR-gate: RTMR sees real (non-stale) trouble on this book's
                    # assets → the guardian de-risks NOW, without waiting for the daily bar
                    if ctx["exogenous_derisk"] and view.get("state") == "ARMED":
                        view["state"] = "DERISKED"
                        view["exposure_now"] = 0.0
                        view["derisk_source"] = "rtmr_exogenous"
                books[book_dir.name] = view
    shadow = _shadow_domains(sleeves_dir, live_track_path)
    systemic = _systemic_sentinel(books, agg_dir)
    doc = {
        "domain": "swarm.guardian_forward",
        "label": "SWARM L2 position guardians / ADVISORY / paper / OUTSIDE_RISKPOLICY",
        "is_advisory": True,
        "outside_riskpolicy": True,
        "as_of_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "params": GUARDIAN_PARAMS,
        "honest_limits": (
            "guardian reduces SLOW-risk drawdown compounding only; GAP risk (exploit/instant depeg/"
            "drained exit) is NOT preventable and remains in the tier tail. Backtest-tail warmup is "
            "labeled per book; guarded numbers are paper, not realized capital."
        ),
        "books": books,
        "systemic": systemic,
        "shadow": shadow,
        "summary": {
            "books": len(books),
            "armed": sum(1 for v in books.values() if v.get("state") == "ARMED"),
            "derisked": sum(1 for v in books.values() if v.get("state") == "DERISKED"),
            "warmup_or_none": sum(1 for v in books.values()
                                  if v.get("state") in ("WARMUP", "NO_FORWARD")),
            "shadow_sleeves": len(shadow["sleeves"]),
            "shadow_derisked": sorted(
                [n for n, v in shadow["sleeves"].items() if v.get("state") == "DERISKED"]
                + (["live_track"] if shadow["live_track"].get("state") == "DERISKED" else [])),
            "live_track_state": shadow["live_track"].get("state"),
        },
    }
    atomic_save(doc, str(out_dir / STATUS_NAME))
    doc["proof_appended"] = _append_proof(doc, out_dir / PROOF_NAME)
    return doc


def main() -> int:
    doc = run_forward_guardian()
    s = doc["summary"]
    print(f"swarm.guardian_forward: {s['books']} books · armed={s['armed']} "
          f"derisked={s['derisked']} warmup/none={s['warmup_or_none']} "
          f"proof_appended={doc['proof_appended']}")
    for name, b in doc["books"].items():
        line = f"  {name:18s} {b['state']:9s} fwd_days={b.get('forward_days', 0)}"
        if b.get("signal"):
            line += f" vol_ratio={b['signal']['ratio']}"
        print(line)
    sh = doc["shadow"]
    lt = sh["live_track"]
    print(f"  shadow: {len(sh['sleeves'])} sleeves · live_track={lt.get('state')}"
          + (f" vol_ratio={lt['signal']['ratio']}" if lt.get("signal") else "")
          + f" · derisked={doc['summary']['shadow_derisked'] or 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
