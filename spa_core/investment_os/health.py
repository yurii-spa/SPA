"""spa_core/investment_os/health.py — AI Investment OS product-layer health monitor.

A meta-monitor for the product layer (analog of agent_health, but for the analyst OUTPUTS). It scans
data/investment_os/<agent>.json for each known analyst and reports, per analyst: present? fresh (mtime
within the age budget)? and whether the last run produced a real result vs UNKNOWN. Emits a single
data/investment_os/_health.json summary + hash-chained proof.

Freshness budgets are READ from the fleet's constitution (`architecture/manifest.json`,
`slo_hours`), never copied into this file — see `cadence_budgets`. Every row names the budget it
was judged against AND where that budget came from (`budget_source`).

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

from spa_core.monitoring import manifest_slo
from spa_core.utils.atomic import atomic_save
from spa_core.strategy_lab.swarm.common import append_daily_proof

#: Контракт агента (ADR-154/158): что этот агент ПРОИЗВОДИТ.
#: Объявление, а не вывод из кода — вывести производителя разбором нельзя
#: (замер 28.08: верно 13 из 27, одна ошибка, семья harness недостижима).
#: Сверяется с фактической записью — spa_core/monitoring/artifact_contract.py.
PRODUCES = (
    "data/investment_os/_health.json",
)

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

#: The constitution of the fleet — the ONE place a cadence is decided (`CLAUDE.md` inv. 13:
#: only files in git are the source of truth). Read through the SHARED reader
#: (`monitoring.manifest_slo`), never parsed here: a second parse is a second literal waiting
#: to happen, which is the exact defect this file is fixing (#342).
_MANIFEST_PATH = manifest_slo.MANIFEST_PATH

#: Hand-copied fallback budgets — used ONLY when the constitution cannot be read, and the
#: row says so out loud (`budget_source`). This dict is NOT the answer; it is the last
#: resort, and every value in it is a snapshot that has already gone stale once.
#:
#: WHY it is no longer the answer (#340, measured 2026-08-22). #235 wrote `HOUSE_VIEW: 30*3600`
#: with the comment "MEASURED from each agent's schedule — not guessed" and the derivation
#: "StartInterval=86400 (daily) → 24h + 6h grace". That was true on 2026-08-16 and false by
#: construction: a schedule copied by hand has no link to its source, so when owner decision
#: ADR-104 changed the chief's cadence `86400s → 300s` (and its SLO `26h → 1h`) on 21.08 at
#: 07:44Z, the literal did not move and COULD not move. Live cost, same artifact, same hour:
#:   architecture_conformance (B2) — WARN, "возраст 18.8ч > SLO 1ч"   (reads the manifest)
#:   investment_os.health        — "house view FRESH, 12.4h of 30h"   (read this literal)
#: Two guards, one file, verdicts 30x apart — and the one that says "healthy" is the one
#: step 0-office prints FIRST, every cycle. A guard that testifies FOR health on a stale
#: artifact is worse than a silent one.
_FALLBACK_BUDGET_S: dict[str, int] = {
    HOUSE_VIEW: 30 * 3600,
}


def cadence_budgets(manifest_path: Optional[Path] = None) -> dict[str, dict]:
    """Freshness budget per analyst, READ from the constitution — one number, one place.

    Returns ``{agent: {"seconds": int, "source": str, "why": str}}`` for every analyst.
    ``source`` is part of the verdict, not decoration: a reader must be able to tell a
    budget that was MEASURED from one that was fallen back to.

      manifest_slo  — `slo_hours` of `data/investment_os/<agent>.json` in the manifest
      fallback      — constitution unreadable/silent about this artifact, hand literal used
      ceiling       — neither: the shared office ceiling

    fail-SAFE, never raises (this module's contract) and fail-CLOSED in what it CLAIMS:
    an unreadable manifest never yields a measured-looking budget, it yields a named
    fallback plus the reason.
    """
    p = Path(manifest_path) if manifest_path is not None else _MANIFEST_PATH
    by_path, why_all = manifest_slo.slo_hours_by_path(p)
    slo: dict[str, float] = {Path(k).stem: v for k, v in by_path.items()
                             if k.startswith("data/investment_os/")}

    out: dict[str, dict] = {}
    for a in ANALYSTS:
        if a in slo:
            out[a] = {"seconds": int(slo[a] * 3600), "source": "manifest_slo",
                      "why": f"architecture/manifest.json: slo_hours={slo[a]:g}"}
        elif a in _FALLBACK_BUDGET_S:
            out[a] = {"seconds": _FALLBACK_BUDGET_S[a], "source": "fallback",
                      "why": why_all or f"{p.name} declares no active SLO for {a}"}
        else:
            out[a] = {"seconds": _FRESH_AGE_S, "source": "ceiling",
                      "why": why_all or f"{p.name} declares no active SLO for {a}"}
    return out


def budget_s(agent: str, budgets: Optional[dict[str, dict]] = None) -> int:
    """Freshness budget for one analyst, in seconds. Default = read the constitution."""
    b = budgets if budgets is not None else cadence_budgets()
    return int(b.get(agent, {}).get("seconds", _FRESH_AGE_S))


def _now(now: Optional[datetime] = None) -> datetime:
    return now or datetime.now(timezone.utc)


def scan(data_dir: Optional[Path] = None, *, now: Optional[datetime] = None,
         budgets: Optional[dict[str, dict]] = None) -> dict:
    """Scan each analyst artifact → per-analyst {present, fresh, status} + an overall roll-up.

    `budgets` is an INPUT, exactly like `now` (rule ".claude/rules/deployment.md": time is an
    input, not an environment). The cadence a guard judges by is the same kind of moving
    ground as the clock — the fix for both is to pass it in. Default: read the constitution.
    """
    d = Path(data_dir) if data_dir is not None else _DEFAULT_DIR
    ts = _now(now)
    b = budgets if budgets is not None else cadence_budgets()
    rows = []
    healthy = stale = missing = unknown = 0
    for a in ANALYSTS:
        p = d / f"{a}.json"
        spec = b.get(a) or {"seconds": _FRESH_AGE_S, "source": "ceiling", "why": "no budget given"}
        budget = int(spec["seconds"])
        # the budget is part of the VERDICT, not a hidden constant: a reader must be able to
        # see which ceiling this row was judged against — AND where that ceiling came from —
        # without reading this module (#340: a budget whose source is unsayable is unarguable).
        row: dict[str, Any] = {"agent": a, "present": False, "fresh": False, "status": None,
                               "max_age_s": budget, "budget_source": spec.get("source"),
                               "budget_why": spec.get("why", "")}
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
                      "present": False, "age_s": None, "max_age_s": budget_s(HOUSE_VIEW, b),
                      "budget_source": (b.get(HOUSE_VIEW) or {}).get("source"),
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
                      "age_s": hv_row.get("age_s"), "max_age_s": hv_row["max_age_s"],
                      "budget_source": hv_row.get("budget_source"),
                      "budget_why": hv_row.get("budget_why", "")}

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
                 "artifact the orchestrator judges from still alive', on the cadence the fleet's "
                 "constitution declares for it (`architecture/manifest.json`; each row carries "
                 "`budget_source`). Advisory/read-only; not a gate."),
    }


def run(*, now: Optional[datetime] = None, data_dir: Optional[Path] = None, write: bool = True,
        budgets: Optional[dict[str, dict]] = None) -> dict:
    d = Path(data_dir) if data_dir is not None else _DEFAULT_DIR
    summary = scan(d, now=now, budgets=budgets)
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
