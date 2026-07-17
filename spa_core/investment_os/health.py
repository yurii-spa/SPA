"""spa_core/investment_os/health.py — AI Investment OS product-layer health monitor.

A meta-monitor for the product layer (analog of agent_health, but for the analyst OUTPUTS). It scans
data/investment_os/<agent>.json for each known analyst and reports, per analyst: present? fresh (mtime
within the age budget)? and whether the last run produced a real result vs UNKNOWN. Emits a single
data/investment_os/_health.json summary + hash-chained proof.

Deterministic · stdlib · fail-SAFE (a missing/corrupt artifact is reported, never crashes). ADVISORY /
read-only — moves no capital, touches no runtime state beyond its own _health artifact.

CLI::  python3 -m spa_core.investment_os.health [--check]
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from spa_core.utils.atomic import atomic_save
from spa_core.strategy_lab.swarm.common import append_daily_proof

log = logging.getLogger("spa.investment_os.health")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DIR = _REPO_ROOT / "data" / "investment_os"

# the analysts this layer runs (keep in sync with the router's _ANALYSTS)
ANALYSTS: tuple[str, ...] = (
    "stablecoin_yield", "market_regime", "reporting", "red_team", "liquidity",
    "protocol_risk", "yield_quality", "onchain", "chief_investment",
)
_FRESH_AGE_S = 2 * 86400   # an analyst artifact older than this is STALE (daily agents)


def _now(now: Optional[datetime] = None) -> datetime:
    return now or datetime.now(timezone.utc)


def scan(data_dir: Optional[Path] = None, *, now: Optional[datetime] = None) -> dict:
    """Scan each analyst artifact → per-analyst {present, fresh, status} + an overall roll-up."""
    d = Path(data_dir) if data_dir is not None else _DEFAULT_DIR
    ts = _now(now)
    rows = []
    healthy = stale = missing = unknown = 0
    for a in ANALYSTS:
        p = d / f"{a}.json"
        row: dict[str, Any] = {"agent": a, "present": False, "fresh": False, "status": None}
        if p.exists():
            row["present"] = True
            try:
                age = ts.timestamp() - p.stat().st_mtime
                row["age_s"] = round(age)
                row["fresh"] = age <= _FRESH_AGE_S
            except OSError:
                row["fresh"] = False
            try:
                doc = json.loads(p.read_text())
                row["status"] = doc.get("status") if isinstance(doc, dict) else None
            except (OSError, ValueError):
                row["status"] = "CORRUPT"
        # classify
        if not row["present"]:
            missing += 1
        elif row["status"] in ("UNKNOWN", "CORRUPT", None):
            unknown += 1
        elif not row["fresh"]:
            stale += 1
        else:
            healthy += 1
        rows.append(row)

    total = len(ANALYSTS)
    if missing or unknown:
        overall = "DEGRADED"
    elif stale:
        overall = "STALE"
    else:
        overall = "HEALTHY"
    return {
        "model": "investment_os_health",
        "is_advisory": True,
        "generated_at": ts.isoformat(),
        "overall": overall,
        "counts": {"total": total, "healthy": healthy, "stale": stale,
                   "missing": missing, "unknown_or_corrupt": unknown},
        "analysts": rows,
        "note": ("Product-layer health — are the AI Investment OS analysts producing fresh, real "
                 "(non-UNKNOWN) artifacts. Advisory/read-only; not a gate."),
    }


def run(*, now: Optional[datetime] = None, data_dir: Optional[Path] = None, write: bool = True) -> dict:
    d = Path(data_dir) if data_dir is not None else _DEFAULT_DIR
    summary = scan(d, now=now)
    if write:
        try:
            d.mkdir(parents=True, exist_ok=True)
            atomic_save(summary, str(d / "_health.json"))
            append_daily_proof({"model": "investment_os_health", "overall": summary["overall"]},
                               d / "_health_proof.jsonl", day=_now(now).strftime("%Y-%m-%d"))
        except Exception:  # noqa: BLE001 — health write must never crash
            log.warning("investment_os health write failed", exc_info=True)
    return summary


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(prog="python3 -m spa_core.investment_os.health")
    ap.add_argument("--check", action="store_true", help="scan + print, do NOT write _health.json")
    args = ap.parse_args(argv)
    summary = run(write=not args.check)
    if args.check:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(f"investment_os health: {summary['overall']} — {summary['counts']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
