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
    "protocol_risk", "yield_quality", "onchain", "quant", "market_structure", "chief_investment",
)
_FRESH_AGE_S = 2 * 86400   # an analyst artifact older than this is STALE (daily agents)

#: Public name for the SAME ceiling, for other checks that judge office artifacts (#212/#222).
#: A check must not be more confident about an office artifact than the office's own health
#: monitor: `house_view_gap` refuses to assert a posture in the present tense past this age.
#: One definition, one place — a second literal would drift from this one silently.
#: DO NOT tighten this to fix a single producer: `house_view_gap` uses it as its
#: refuse-to-judge ceiling, so a smaller number makes the office↔book reconciliation go
#: silent EARLIER — findings would vanish and the bridge would close their cards as
#: "solved" (fail-OPEN #29). Per-producer budgets belong in `_CADENCE_BUDGET_S` below.
FRESH_AGE_S: int = _FRESH_AGE_S

#: The office's MAIN artifact — the house view. Named once so "are the analysts healthy?"
#: and "is the house view still alive?" are separable questions (#235).
HOUSE_VIEW: str = "chief_investment"

#: Per-producer freshness budgets, MEASURED from each agent's schedule — not guessed.
#: WHY (#235): one 48h budget covered producers whose real cadences differ by two orders of
#: magnitude (market_regime/reporting refresh in minutes; the chief writes once a DAY). Under
#: a single 48h ceiling the house view could miss a FULL daily beat and still be counted
#: "healthy 11/11" — which is exactly what the roll-up printed while the snapshot was 17h old.
#: A budget that cannot fail in practice is decoration, not a watchdog.
#: com.spa.io_chief_investment: StartInterval=86400 (daily) → 24h + 6h grace.
_CADENCE_BUDGET_S: dict[str, int] = {
    HOUSE_VIEW: 30 * 3600,
}


def budget_s(agent: str) -> int:
    """Freshness budget for one analyst, in seconds. Default = the shared office ceiling."""
    return _CADENCE_BUDGET_S.get(agent, _FRESH_AGE_S)


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
        budget = budget_s(a)
        # the budget is part of the VERDICT, not a hidden constant: a reader must be able to
        # see which ceiling this row was judged against without reading this module.
        row: dict[str, Any] = {"agent": a, "present": False, "fresh": False, "status": None,
                               "max_age_s": budget}
        if p.exists():
            row["present"] = True
            try:
                age = ts.timestamp() - p.stat().st_mtime
                row["age_s"] = round(age)
                row["fresh"] = age <= budget
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

    # ── the house view is answered SEPARATELY (#235) ───────────────────────────────────
    # "11 analysts healthy" was being read as "the office is alive", but the house view is
    # the artifact the orchestrator actually judges from every cycle in step 0-office. It is
    # still counted among the analysts above (that roll-up is unchanged); what is new is that
    # its verdict is now sayable on its own, so a dead house view cannot hide inside a
    # healthy-looking fleet count. fail-CLOSED: no row at all ⇒ UNCHECKED, never fresh.
    hv_row = next((r for r in rows if r["agent"] == HOUSE_VIEW), None)
    if hv_row is None:
        house_view = {"agent": HOUSE_VIEW, "status": "UNCHECKED", "fresh": False,
                      "present": False, "age_s": None, "max_age_s": budget_s(HOUSE_VIEW),
                      "why": f"{HOUSE_VIEW} is not in ANALYSTS — the house view is unjudged"}
    else:
        if not hv_row["present"]:
            hv_status = "MISSING"
        elif hv_row["status"] in ("UNKNOWN", "CORRUPT", None):
            hv_status = "UNKNOWN_OR_CORRUPT"
        elif not hv_row["fresh"]:
            hv_status = "STALE"
        else:
            hv_status = "FRESH"
        house_view = {"agent": HOUSE_VIEW, "status": hv_status,
                      "fresh": bool(hv_row["fresh"]), "present": bool(hv_row["present"]),
                      "age_s": hv_row.get("age_s"), "max_age_s": hv_row["max_age_s"]}

    return {
        "model": "investment_os_health",
        "is_advisory": True,
        "generated_at": ts.isoformat(),
        "overall": overall,
        "counts": {"total": total, "healthy": healthy, "stale": stale,
                   "missing": missing, "unknown_or_corrupt": unknown},
        "house_view": house_view,
        "house_view_fresh": house_view["status"] == "FRESH",
        "analysts": rows,
        "note": ("Product-layer health — are the AI Investment OS analysts producing fresh, real "
                 "(non-UNKNOWN) artifacts. `house_view` answers the SEPARATE question 'is the "
                 "artifact the orchestrator judges from still alive', on its own measured "
                 "cadence. Advisory/read-only; not a gate."),
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
