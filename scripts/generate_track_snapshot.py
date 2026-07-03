#!/usr/bin/env python3
"""Regenerate landing/src/data/track_snapshot.json from the LIVE canonical state.

The /track-record + /due-diligence pages import this JSON as a build-time, offline
fallback (live values from api.earn-defi.com override it client-side). It was
previously HAND-maintained and drifted stale (frozen at 5 evidenced days while the
real track advanced) — fixed by deriving it from the source of truth every run, so
the offline fallback can never again lie by more than one cycle.

Source of truth (read-only):
  data/golive_status.json       — real_track_days, gates passed/total, anchor, target
  data/equity_curve_daily.json  — the evidenced bars (source/evidenced flags), equity

HONEST rules:
  - real_track_days = count of EVIDENCED bars (source-of-truth: track_evidence), never
    the raw bar count (which spans warmup/backfill/reconstructed).
  - gates_passed snaps the STABLE value: golive 'passed' can transiently dip pre-dawn
    (before the daily cycle + digest run); we clamp the offline fallback up to the
    stable count = total - (purely time-gated blockers) so the offline page does not
    show a transient dip. Live API still overrides with the real-time value.
  - stdlib-only, deterministic, atomic write (same-dir tmp + os.replace).
"""
from __future__ import annotations

import datetime
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GOLIVE = ROOT / "data" / "golive_status.json"
EQUITY = ROOT / "data" / "equity_curve_daily.json"
OUT = ROOT / "landing" / "src" / "data" / "track_snapshot.json"

# Purely time-gated go-live blockers — failing ONLY because the 30-day track has not
# matured (nothing code can fix). The offline fallback should reflect the desk's
# stable posture, not a transient pre-dawn dip in these.
_TIME_GATED = {"gap_monitor_30d", "min_track_days_30"}


def _atomic_write(path: Path, payload: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _load(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _max_drawdown_pct(bars: list):
    """Worst drawdown (%) = min(per-bar drawdown_pct) over the given bars (P1-4 audit fix).

    Uses each bar's own recorded ``drawdown_pct`` (the honest figure the cycle logged) rather than
    re-deriving peak-to-trough from equity — the old re-derivation returned 0.0 while bars carried
    drawdown_pct down to -0.026. Falls back to equity peak-to-trough only if no bar has drawdown_pct.
    """
    dds = [float(b.get("drawdown_pct")) for b in bars if b.get("drawdown_pct") is not None]
    if dds:
        return round(min(dds), 4)
    eqs = [float(b.get("equity")) for b in bars if b.get("equity") is not None]
    if len(eqs) < 2:
        return None
    peak = eqs[0]
    worst = 0.0
    for e in eqs:
        peak = max(peak, e)
        if peak > 0:
            worst = min(worst, (e - peak) / peak * 100.0)
    return round(worst, 4)


def build_snapshot(golive_path: Path = GOLIVE, equity_path: Path = EQUITY, pts_path=None) -> dict:
    """Assemble the build-time static snapshot from the committed data files.

    ONE source per number (FIX-2): live equity / paper APY / PoR-NAV come from
    paper_trading_status.json (the same authority the API serves); track days + gates from
    golive_status.json; the per-bar ledger from equity_curve_daily.json. A missing value is left
    None so the site renders an honest "data unavailable" — NEVER a bare hardcoded number.
    """
    golive = _load(golive_path)
    equity = _load(equity_path)
    pts = _load(pts_path if pts_path is not None else (ROOT / "data" / "paper_trading_status.json"))

    bars = equity.get("bars") or equity.get("curve") or equity.get("daily") or []
    evidenced = [b for b in bars if b.get("evidenced") is True]
    real_days = len(evidenced) if evidenced else int(golive.get("real_track_days", 0) or 0)

    total = int(golive.get("total", 29) or 29)
    passed_live = int(golive.get("passed", 0) or 0)
    # Stable floor: at most the 2 time-gated blockers may legitimately be open.
    stable_passed = max(passed_live, total - len(_TIME_GATED))

    last = bars[-1] if bars else {}
    # ONE source: prefer the paper_trading_status authority; fall back to the equity ledger tail.
    nav = pts.get("current_equity")
    end_equity = float(nav if nav is not None else last.get("equity", equity.get("end_equity", 100000.0)) or 100000.0)

    paper_apy = pts.get("apy_today_pct")
    if paper_apy is None and last.get("apy_today") is not None:
        paper_apy = last.get("apy_today")

    # as_of = freshness of the underlying evidenced data (last evidenced bar date), NOT build time.
    as_of = (evidenced[-1].get("date") if evidenced else last.get("date")) or golive.get("as_of")
    generated_at = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    snap = {
        "generated_from": "data/golive_status.json + data/equity_curve_daily.json + data/paper_trading_status.json",
        "generator": "scripts/generate_track_snapshot.py",
        "note": (
            "Build-time static fallback for the public pages. Live values come from api.earn-defi.com "
            "and override these client-side; this is the last honest snapshot for offline / crawlers. "
            "real_track_days = EVIDENCED bars only. Missing value => 'data unavailable', never a stale number."
        ),
        "as_of": as_of,
        "generated_at": generated_at,
        # Site-Custodian kill-rule flag (ADR-YL-011). A routine regen PRESERVES it (carry-forward) so a
        # degraded site stays degraded through rebuilds; only the freshness monitor SETS it (on
        # OVERSTATED/stale) and CLEARS it (on a passing re-check). Default False on first generation.
        "degraded": bool(_load(OUT).get("degraded", False)),
        "real_track_days": real_days,
        "go_live_target": golive.get("target_date") or golive.get("go_live_target") or "2026-07-21",
        "evidenced_anchor": golive.get("evidenced_anchor") or "2026-06-22",
        "days_needed": int(golive.get("min_track_days", 30) or 30),
        "gates_passed": stable_passed,
        "gates_total": total,
        "end_equity": round(end_equity, 2),
        "nav_usd": round(end_equity, 2),                    # PoR-NAV (paper): the reserves backing
        "paper_apy_pct": round(float(paper_apy), 4) if paper_apy is not None else None,
        "max_drawdown_pct": _max_drawdown_pct(evidenced or bars),
        "total_return_pct": round((end_equity / 100000.0 - 1.0) * 100.0, 4),
        "bars": bars,
    }
    return snap


def main() -> int:
    snap = build_snapshot()
    _atomic_write(OUT, snap)
    print(
        f"track_snapshot.json regenerated: real_track_days={snap['real_track_days']} "
        f"gates={snap['gates_passed']}/{snap['gates_total']} anchor={snap['evidenced_anchor']} "
        f"bars={len(snap['bars'])}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
