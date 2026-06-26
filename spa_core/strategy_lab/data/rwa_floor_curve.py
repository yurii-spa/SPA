"""
spa_core/strategy_lab/data/rwa_floor_curve.py — the RWA risk-free-FLOOR forward record.

DISCONNECT (a) FIX. The live RWA feed (spa_core.strategy_lab.data.rwa_feed) measures the
TVL-weighted tokenized-T-bill yield (BUIDL/USYC/USDY/OUSG/USTB/TBILL — a ~$15B market at
~3.3–3.5%) as a SINGLE OVERWRITTEN snapshot (data/market_data/rwa_floor.json). A snapshot is
not a track record. This module gives the floor a daily MEASURED-RATE forward series — one point
per UTC day appended to data/rwa_floor_curve.json — so the GO-thesis benchmark (the floor every
strategy must beat) accrues evidenced forward data, exactly the way the rwa_backstop nav_curve
and the rates-desk paper_rates accrue their forward tracks.

It MIRRORS the rwa_backstop/nav_curve.py append contract (P4-3):
  - one point per UTC day (idempotent — re-running the same day REFRESHES today's point, no dup),
  - ring-buffer capped (~400 days), atomic writes (tmp + shutil.move, repo rule #4),
  - restart-survival (the series is reloaded from disk and continued, never zeroed),
  - FAIL-CLOSED: a bad/empty/unavailable feed SKIPS the day's append (logged) and NEVER
    fabricates a rate; the prior series is left untouched.

Each forward point summarizes the day's live floor measurement:
  {
    "date":               UTC YYYY-MM-DD,
    "ts":                 full UTC ISO timestamp,
    "floor_apy_pct":      the TVL-weighted blended floor (the rate the benchmark accrues at),
    "median_apy_pct":     cross-check median across the qualifying issuer pools,
    "n_pools":            # qualifying tokenized-T-bill issuer pools that day,
    "total_tvl_usd":      aggregate TVL across those pools,
  }

INTERNAL CONSISTENCY: this curve, the RWAFloor benchmark, and the rwa_sleeve all read the SAME
live rate — rwa_feed.RWAFeed.compute()['floor_apy_pct'] is exactly what config.rwa_floor_apy_pct()
returns (via current_rwa_floor_pct, sharing the same cache). So the persisted curve is the audit
trail of the rate the forward paper track actually accrued at.

stdlib only, deterministic, LLM-forbidden, ADVISORY / RESEARCH only (no capital, no go-live).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import json
import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import List, Optional

from spa_core.strategy_lab.data.rwa_feed import RWAFeed

_ROOT = Path(__file__).resolve().parents[3]  # …/SPA_Claude
DEFAULT_CURVE_PATH = _ROOT / "data" / "rwa_floor_curve.json"

CURVE_ID = "rwa_floor_curve"
SERIES_CAP = 400  # ~400 UTC days, mirrors rwa_backstop/nav_curve SERIES_CAP

log = logging.getLogger("spa.strategy_lab.rwa_floor_curve")


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


def _load_curve(path: Path) -> dict:
    """Reload the forward series from disk (restart-survival). A missing/corrupt file → a fresh,
    empty series (never raises — the writer must always be able to append)."""
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
        if isinstance(doc, dict) and isinstance(doc.get("series"), list):
            return doc
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return {"id": CURVE_ID, "series": []}


def _utc_today() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


# ── the day's floor measurement point (deterministic, fail-CLOSED) ─────────────────────────────
def summarize_floor(floor: dict, date: Optional[str] = None) -> Optional[dict]:
    """Distill ONE forward point from a live rwa_feed measurement (RWAFeed.compute() output).
    Returns None (→ SKIP the day's append, fail-CLOSED) when the measurement carries no usable
    floor:
      - not a dict,
      - no numeric floor_apy_pct.
    Never fabricates: a day with no credible measurement is simply not recorded."""
    if not isinstance(floor, dict):
        return None
    apy = floor.get("floor_apy_pct")
    if not isinstance(apy, (int, float)):
        return None

    day = date or _utc_today()
    med = floor.get("median_apy_pct")
    n_pools = floor.get("n_pools")
    total_tvl = floor.get("total_tvl_usd")
    return {
        "date": day,
        "ts": _utc_now_iso(),
        "floor_apy_pct": round(float(apy), 6),
        "median_apy_pct": round(float(med), 6) if isinstance(med, (int, float)) else None,
        "n_pools": int(n_pools) if isinstance(n_pools, (int, float)) else None,
        "total_tvl_usd": round(float(total_tvl), 2) if isinstance(total_tvl, (int, float)) else None,
    }


# ── the forward-record append (idempotent per UTC day, ring-buffered, atomic) ──────────────────
def append_point(point: dict, curve_path: Optional[Path] = None) -> dict:
    """Append ONE forward point to data/rwa_floor_curve.json. Reloads the series from disk first
    (restart-survival), refreshes today's point in place if it already exists (idempotent per UTC
    day — no dup), caps the ring-buffer, and writes atomically. Returns the persisted document."""
    path = Path(curve_path) if curve_path else DEFAULT_CURVE_PATH
    doc = _load_curve(path)
    series: List[dict] = doc.get("series") or []

    if series and isinstance(series[-1], dict) and series[-1].get("date") == point["date"]:
        series = series[:-1]  # refresh today's point (idempotent per UTC day)
    series.append(point)
    if len(series) > SERIES_CAP:
        series = series[-SERIES_CAP:]

    doc = {
        "id": CURVE_ID,
        "model": "rwa_risk_free_floor",
        "thesis": "SPA RWA risk-free floor (tokenized-T-bill TVL-weighted yield) forward record",
        "framing": "live tokenized-T-bill floor forward record — advisory, paper research (no capital)",
        "llm_forbidden": True,
        "advisory": True,
        "research_only": True,
        "series_cap": SERIES_CAP,
        "generated_at": _utc_now_iso(),
        "n_points": len(series),
        "latest": series[-1] if series else None,
        "series": series,
    }
    _atomic_write_json(path, doc)
    return doc


def record_forward_point(
    floor: Optional[dict] = None,
    curve_path: Optional[Path] = None,
    date: Optional[str] = None,
    feed: Optional[RWAFeed] = None,
) -> Optional[dict]:
    """Top-level forward-record entry: get the day's LIVE floor measurement and append it.

    If `floor` is supplied (the rwa_feed.compute() dict — e.g. computed once and reused) it is
    distilled directly. Otherwise the live floor is fetched via `feed` (default RWAFeed()) — its
    cached value is used when fresh, else it refetches (same cache config.rwa_floor_apy_pct uses).

    FAIL-CLOSED — if the floor is unavailable (network down, schema error, empty) OR yields no
    usable rate, logs and SKIPS (no append, returns None). The existing series is untouched.
    Idempotent per UTC day. Called from the daily safety_board run."""
    if floor is None:
        try:
            f = feed or RWAFeed()
            # current_rwa_floor_pct() serves the cache when fresh, else refetches + rewrites it —
            # the SAME cache + value config.rwa_floor_apy_pct() reads, keeping the curve, the
            # benchmark, and the sleeve internally consistent. We pull the full cached dict so the
            # forward point carries n_pools / total_tvl / median for audit.
            f.current_rwa_floor_pct()  # ensures a fresh cache (refetch if stale) — fail-closed
            floor = f.cached()
        except Exception as exc:  # noqa: BLE001 — feed unavailable → fail-closed skip
            log.warning("rwa floor-curve: live feed unavailable → SKIP day's append "
                        "(fail-closed): %s", exc)
            return None

    point = summarize_floor(floor, date=date)
    if point is None:
        log.warning("rwa floor-curve: no usable floor measurement → SKIP day's append (fail-closed)")
        return None
    doc = append_point(point, curve_path=curve_path)
    log.info("rwa floor-curve: appended forward point for %s (n_points=%d, floor=%.4f%%)",
             point["date"], doc.get("n_points"), point["floor_apy_pct"])
    return doc


# ── CLI: fetch the live floor and append today's forward point ─────────────────────────────────
def main() -> int:
    import socket
    socket.setdefaulttimeout(25)
    doc = record_forward_point()
    if doc is None:
        print("rwa floor-curve: live floor unavailable → no forward point appended (fail-closed)")
        return 0
    print(f"rwa floor-curve: forward point appended — {doc['latest']}")
    print(f"  n_points={doc['n_points']}  →  {DEFAULT_CURVE_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
