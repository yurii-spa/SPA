"""
spa_core/strategy_lab/rwa_backstop/nav_curve.py — the RWA backstop FORWARD RECORD.

Thesis #2 (the RWA collateral backstop) reached a measurement-GO at a POINT in time
(data/rwa_safety_board.json). A point measurement is not a track record. This module gives the
thesis a daily MEASURED-NAV forward series — one point per UTC day appended to
data/rwa_nav_curve.json — so the RWA thesis accrues evidenced forward data exactly the way the
rates-desk FixedCarry sleeve accrues a forward paper track.

It MIRRORS the rates-desk paper_rates append contract:
  - one point per UTC day (idempotent — re-running the same day REFRESHES today's point, no dup),
  - ring-buffer capped (~400 days), atomic writes (tmp + shutil.move, repo rule #4),
  - restart-survival (the series is reloaded from disk and continued, never zeroed),
  - FAIL-CLOSED: a bad/empty measurement SKIPS the day's append (logged) and never fabricates.

Each forward point summarizes the day's Safety-Board measurement:
  {
    "date":                  UTC YYYY-MM-DD,
    "ts":                    full UTC ISO timestamp,
    "tvl_weighted_nav":      DEX-TVL-weighted measured NAV/share across the universe (the executable
                             intrinsic anchor: on-chain ERC-4626 NAV where read, else marketing NAV),
    "onchain_4626_count":    # assets with a REAL on-chain ERC-4626 intrinsic NAV (eth_call),
    "off_chain_estimate_count": # assets falling back to the off-chain estimate,
    "liq_nav_gap_pct":       the headline marketing-vs-LiquidationNAV gap % (the board's
                             max_marketing_vs_liq_gap_pct_1m summary number),
    "n_assets":              # assets measured this day,
  }

This is the FORWARD-record layer ONLY — the heavy measurement lives in safety_board.build_report().
This module takes a finished report (or builds one) and appends its daily summary point.

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

_ROOT = Path(__file__).resolve().parents[3]  # …/SPA_Claude
DEFAULT_CURVE_PATH = _ROOT / "data" / "rwa_nav_curve.json"

CURVE_ID = "rwa_backstop_nav_curve"
SERIES_CAP = 400  # ~400 UTC days, mirrors the rates-desk SERIES_CAP

log = logging.getLogger("spa.rwa_backstop.nav_curve")


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


# ── the day's measured-NAV summary point (deterministic, fail-CLOSED) ──────────────────────────
def summarize_report(report: dict, date: Optional[str] = None) -> Optional[dict]:
    """Distill ONE forward point from a finished Safety-Board report. Returns None (→ SKIP the
    day's append, fail-CLOSED) when the report carries no usable measurement:
      - not a dict / no asset rows,
      - no asset produced a numeric NAV to weight.
    Never fabricates: a day with no credible measurement is simply not recorded.

    `tvl_weighted_nav` weights each asset's measured NAV/share by its on-chain DEX liquidity, so
    the aggregate reflects where executable exit actually exists. Assets with zero discovered DEX
    TVL (the permissioned majority) carry zero weight in the executable anchor; if NO asset has DEX
    TVL we fall back to an equal-weighted mean of the measured NAVs (still a real measurement, just
    un-weighted) rather than fabricating or skipping."""
    if not isinstance(report, dict):
        return None
    rows = report.get("assets")
    if not isinstance(rows, list) or not rows:
        return None

    day = date or report.get("date") or _utc_today()

    cov = report.get("onchain_nav_coverage") or {}
    onchain_4626 = int(cov.get("onchain_4626", cov.get("n_onchain_4626", 0)) or 0)
    off_chain_est = int(cov.get("off_chain_estimate", cov.get("n_off_chain_estimate", 0)) or 0)

    # per-asset measured NAV/share: prefer the REAL on-chain ERC-4626 intrinsic NAV, else marketing.
    weighted_sum = 0.0
    weight_total = 0.0
    nav_values: List[float] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        nav = r.get("onchain_nav_usd")
        if not isinstance(nav, (int, float)):
            nav = r.get("marketing_nav_usd")
        if not isinstance(nav, (int, float)):
            continue
        nav_values.append(float(nav))
        tvl = r.get("on_chain_dex_liquidity_usd")
        if isinstance(tvl, (int, float)) and tvl > 0:
            weighted_sum += float(nav) * float(tvl)
            weight_total += float(tvl)

    if not nav_values:
        return None  # no numeric NAV anywhere → fail-CLOSED, skip the day

    if weight_total > 0:
        tvl_weighted_nav = round(weighted_sum / weight_total, 8)
    else:
        # no executable DEX depth anywhere (the permissioned-universe norm) → equal-weighted mean.
        tvl_weighted_nav = round(sum(nav_values) / len(nav_values), 8)

    gap = report.get("max_marketing_vs_liq_gap_pct_1m")
    liq_nav_gap_pct = float(gap) if isinstance(gap, (int, float)) else None

    return {
        "date": day,
        "ts": _utc_now_iso(),
        "tvl_weighted_nav": tvl_weighted_nav,
        "onchain_4626_count": onchain_4626,
        "off_chain_estimate_count": off_chain_est,
        "liq_nav_gap_pct": liq_nav_gap_pct,
        "n_assets": len(nav_values),
    }


# ── the forward-record append (idempotent per UTC day, ring-buffered, atomic) ──────────────────
def append_point(point: dict, curve_path: Optional[Path] = None) -> dict:
    """Append ONE forward point to data/rwa_nav_curve.json. Reloads the series from disk first
    (restart-survival), refreshes today's point in place if it already exists (idempotent per UTC
    day — no dup), caps the ring-buffer, and writes atomically. Returns the persisted document."""
    path = Path(curve_path) if curve_path else DEFAULT_CURVE_PATH
    doc = _load_curve(path)
    series: List[dict] = doc.get("series") or []

    if series and isinstance(series[-1], dict) and series[-1].get("date") == point["date"]:
        series = series[:-1]  # refresh today's point (idempotent per UTC day, mirrors paper_rates)
    series.append(point)
    if len(series) > SERIES_CAP:
        series = series[-SERIES_CAP:]

    doc = {
        "id": CURVE_ID,
        "model": "rwa_backstop_liquidation_nav",
        "thesis": "SPA-RRB: measured on-chain NAV forward record",
        "framing": "measured on-chain NAV forward record — advisory, paper research (no capital)",
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


def record_forward_point(report: dict, curve_path: Optional[Path] = None,
                         date: Optional[str] = None) -> Optional[dict]:
    """Top-level forward-record entry: distill a Safety-Board report into a daily point and append
    it. FAIL-CLOSED — if the report yields no usable measurement, logs and SKIPS (no append,
    returns None). Idempotent per UTC day. Called from the daily safety_board run."""
    point = summarize_report(report, date=date)
    if point is None:
        log.warning("rwa nav-curve: no usable measurement in report → SKIP day's append (fail-closed)")
        return None
    doc = append_point(point, curve_path=curve_path)
    log.info("rwa nav-curve: appended forward point for %s (n_points=%d, tvl_weighted_nav=%s)",
             point["date"], doc.get("n_points"), point["tvl_weighted_nav"])
    return doc


# ── CLI: build the board and append today's forward point ─────────────────────────────────────
def main() -> int:
    import socket
    socket.setdefaulttimeout(25)
    from spa_core.strategy_lab.rwa_backstop import safety_board as sb
    report = sb.build_report(write=True)
    doc = record_forward_point(report)
    if doc is None:
        print("rwa nav-curve: no usable measurement → no forward point appended (fail-closed)")
        return 0
    print(f"rwa nav-curve: forward point appended — {doc['latest']}")
    print(f"  n_points={doc['n_points']}  →  {DEFAULT_CURVE_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
