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

ADVISORY / paper-only / OUTSIDE_RISKPOLICY: moves no capital, never touches the go-live track,
writes ONLY data/swarm/. Deterministic, stdlib-only. LLM FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from spa_core.strategy_lab.aggressive_lab.guardian import apply_guardian_vol, stdev
from spa_core.utils.atomic import atomic_save

__all__ = ["vol_guardian_trace", "run_forward_guardian", "GUARDIAN_PARAMS"]

REPO_ROOT = Path(__file__).resolve().parents[3]
AGGRESSIVE_LAB_DIR = REPO_ROOT / "data" / "aggressive_lab"
SWARM_DIR = REPO_ROOT / "data" / "swarm"
STATUS_NAME = "guardian_forward.json"
PROOF_NAME = "guardian_forward_proof.jsonl"
GENESIS_HASH = "0" * 64

# OOS-validated params (docs/DYNAMIC_LEVERAGE_GUARDIAN.md idea #1 / scripts/guardian_backtest.py sweep).
GUARDIAN_PARAMS = {
    "lookback": 10,
    "vol_mult": 2.0,
    "derisk_frac": 0.0,
    "calm_mult": 1.2,
    "roundtrip_cost": 0.0015,
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
            if exposure >= 1.0 and recent > vol_mult * base:
                exposure = derisk_frac
            elif exposure < 1.0 and recent < calm_mult * base:
                exposure = 1.0
            if exposure != prev:
                events.append((i, "DERISK" if exposure < prev else "REENTER"))
                if roundtrip_cost:
                    guarded[-1] *= (1.0 - roundtrip_cost * abs(prev - exposure))
        exposures.append(exposure)
        guarded.append(guarded[-1] * (1.0 + rets[i] * exposure))
    return guarded, exposures, events


def _max_drawdown_pct(equity: Sequence[float]) -> float:
    peak, worst = float("-inf"), 0.0
    for v in equity:
        peak = max(peak, v)
        if peak > 0:
            worst = min(worst, v / peak - 1.0)
    return round(worst * 100.0, 4)


def _apy_pct(equity: Sequence[float], days: int) -> Optional[float]:
    if days < 1 or len(equity) < 2 or equity[0] <= 0 or equity[-1] <= 0:
        return None
    return round(((equity[-1] / equity[0]) ** (365.0 / days) - 1.0) * 100.0, 4)


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


def _append_proof(doc: dict, proof_path: Path) -> bool:
    """Hash-chain one line per UTC day (idempotent per day). Returns True if appended."""
    today = doc["as_of_utc"][:10]
    prev_hash, last_day = GENESIS_HASH, None
    try:
        with proof_path.open() as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    prev_hash = rec.get("hash", prev_hash)
                    last_day = rec.get("date", last_day)
                except ValueError:
                    continue
    except OSError:
        pass
    if last_day == today:
        return False
    payload = {
        "date": today,
        "books": len(doc["books"]),
        "derisked_now": sorted(b for b, v in doc["books"].items() if v.get("state") == "DERISKED"),
        "forward_days_max": max((v.get("forward_days", 0) for v in doc["books"].values()), default=0),
        "prev_hash": prev_hash,
    }
    payload["hash"] = hashlib.sha256(
        (prev_hash + json.dumps(payload, sort_keys=True)).encode()).hexdigest()
    proof_path.parent.mkdir(parents=True, exist_ok=True)
    with proof_path.open("a") as fh:
        fh.write(json.dumps(payload, sort_keys=True) + "\n")
    return True


def run_forward_guardian(
    agg_dir: Path = AGGRESSIVE_LAB_DIR,
    out_dir: Path = SWARM_DIR,
) -> dict:
    """One guardian pass over every aggressive_lab book. Writes the status JSON + daily proof line;
    returns the status doc. Deterministic given the input series (timestamp aside)."""
    books: Dict[str, dict] = {}
    if agg_dir.is_dir():
        for book_dir in sorted(p for p in agg_dir.iterdir() if p.is_dir()):
            if (book_dir / "realized_series.jsonl").exists():
                books[book_dir.name] = _guard_book(book_dir)
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
        "summary": {
            "books": len(books),
            "armed": sum(1 for v in books.values() if v.get("state") == "ARMED"),
            "derisked": sum(1 for v in books.values() if v.get("state") == "DERISKED"),
            "warmup_or_none": sum(1 for v in books.values()
                                  if v.get("state") in ("WARMUP", "NO_FORWARD")),
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
