# LLM_FORBIDDEN
"""
SPA Artifact Freshness Registry — single source of truth for "what must stay fresh".

WHY (2026-07-23 owner-investigation): freshness knowledge was SCATTERED — every monitor
hardcoded its own file + threshold (STATUS_FRESH_H, RISKWIRE_MEASUREMENTS_FRESH_H, ...), so a
NEW producer-without-a-schedule froze SILENTLY (riskwire 29d, rate_surface 25.06, refusal_cost 34d,
rates-desk capacity 36d) while its stale output was served as "live". This registry makes staleness
IMPOSSIBLE to introduce quietly: every public/committed artifact MUST be listed with its producer +
max age; anything past its age is reported STALE (never silently OK).

Design invariants:
  * fail-CLOSED — a MISSING required file, an UNPARSEABLE timestamp, or a read error is NEVER "fresh";
    it is STALE / UNCHECKED, so absence of data can never read as absence of problems.
  * deterministic, stdlib-only, LLM-forbidden — pure function of (registry, filesystem, `now`).
  * read-only over data/ — this module never mutates state; `write_report` uses atomic_save.
  * `now` is injectable so tests are hermetic (no wall-clock).

This is ADVISORY / measurement — it NEVER gates execution, RiskPolicy, or the kill-switch.
"""
# LLM_FORBIDDEN

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ── status vocabulary (fail-CLOSED: only FRESH is a clean pass) ──────────────────────
FRESH = "FRESH"
STALE = "STALE"          # exists + parseable, but older than max_age_hours
MISSING = "MISSING"      # required file absent → RED (never "skipped")
UNCHECKED = "UNCHECKED"  # exists but timestamp unparseable / read error → RED-ish, never FRESH


@dataclass(frozen=True)
class Artifact:
    """One freshness-tracked artifact. `max_age_hours` is the RED threshold."""
    name: str
    path: str                      # relative to data_dir
    producer: str                  # agent/cron/cycle that MUST refresh it (accountability)
    max_age_hours: float
    public: bool = False           # served on a public surface (site/API) — stricter concern
    required: bool = True          # absent required file → MISSING(RED); optional → UNCHECKED
    ts_fields: tuple = ("generated_at", "as_of", "last_updated", "ts")
    allow_mtime: bool = True       # fall back to file mtime when no ts field present


# ── THE REGISTRY — every public/committed artifact that must stay fresh ───────────────
# Adding a producer WITHOUT adding it here is the bug this module exists to prevent:
# a new stale-able artifact must be registered, and staleness then shows up RED.
ARTIFACT_REGISTRY: tuple = (
    # cycle-written, daily (~06:00 UTC) → 26h = one cycle + grace
    Artifact("kill_switch_status", "kill_switch_status.json", "daily_cycle", 26.0),
    Artifact("derisk_status", "derisk_status.json", "daily_cycle", 26.0),
    Artifact("paper_trading_status", "paper_trading_status.json", "daily_cycle", 26.0),
    Artifact("paper_evidence", "paper_evidence.json", "daily_cycle", 30.0, public=True),
    # daily producers with slack
    Artifact("dfb_pools", "dfb/pools.json", "dfb_capture", 30.0),
    Artifact("strategy_tournament", "strategy_tournament.json", "tournament_engine", 30.0),
    # 2026-08-15 (#235): the office's MAIN artifact had no expiry at all. The orchestrator's
    # mandatory step 0-office takes the house-view posture and the opportunity list from this
    # file every cycle, yet no watchdog judged whether it was still alive. Budget is MEASURED,
    # not guessed: com.spa.io_chief_investment runs StartInterval=86400 (daily) → 24h + grace.
    Artifact("investment_os_chief", "investment_os/chief_investment.json",
             "com.spa.io_chief_investment", 30.0),
    # KNOWN-STALE 2026-07-23 (producer without schedule) — registry makes them RED, not silent:
    Artifact("riskwire_measurements", "riskwire/measurements.json", "riskwire_facade(NEW)", 30.0, public=True),
    Artifact("rates_desk_rate_surface", "rates_desk/rate_surface.json", "rates_desk", 30.0, public=True),
    Artifact("refusal_cost", "refusal_cost.json", "rates_desk", 48.0),
    Artifact("rates_desk_capacity", "rates_desk/capacity.json", "rates_desk_capacity_aggregator", 48.0,
             public=True, required=False),  # served on /fundability; file path may differ per deploy
)

_REPORT_FILENAME = "artifact_freshness.json"


def _parse_ts(raw: object) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp fail-CLOSED; return None on anything unparseable."""
    if not isinstance(raw, str) or not raw:
        return None
    try:
        s = raw.strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _artifact_ts(full_path: Path, art: Artifact) -> Optional[datetime]:
    """Best available timestamp for an artifact: a ts field, else mtime (if allowed)."""
    try:
        with open(full_path, "r", encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError):
        doc = None
    if isinstance(doc, dict):
        for fld in art.ts_fields:
            dt = _parse_ts(doc.get(fld))
            if dt is not None:
                return dt
    if art.allow_mtime:
        try:
            return datetime.fromtimestamp(os.path.getmtime(full_path), timezone.utc)
        except OSError:
            return None
    return None


@dataclass
class FreshnessResult:
    name: str
    producer: str
    status: str
    age_hours: Optional[float]
    max_age_hours: float
    public: bool
    path: str

    @property
    def ok(self) -> bool:
        return self.status == FRESH


def check_freshness(data_dir, *, now: Optional[datetime] = None,
                    registry: tuple = ARTIFACT_REGISTRY) -> list:
    """
    Evaluate every registered artifact. Returns a list[FreshnessResult].

    fail-CLOSED: required file absent → MISSING; timestamp unparseable → UNCHECKED;
    age > max_age_hours → STALE. Only a present, parseable, in-window artifact is FRESH.
    `now` is injectable for hermetic tests.
    """
    base = Path(data_dir)
    now = now or datetime.now(timezone.utc)
    results: list = []
    for art in registry:
        full = base / art.path
        if not full.exists():
            status = MISSING if art.required else UNCHECKED
            results.append(FreshnessResult(art.name, art.producer, status, None,
                                           art.max_age_hours, art.public, art.path))
            continue
        ts = _artifact_ts(full, art)
        if ts is None:
            results.append(FreshnessResult(art.name, art.producer, UNCHECKED, None,
                                           art.max_age_hours, art.public, art.path))
            continue
        age_h = (now - ts).total_seconds() / 3600.0
        status = FRESH if age_h <= art.max_age_hours else STALE
        results.append(FreshnessResult(art.name, art.producer, status, round(age_h, 2),
                                       art.max_age_hours, art.public, art.path))
    return results


def summarize(results: list) -> dict:
    """Aggregate to a report dict. `any_stale` is the single honest headline."""
    stale = [r for r in results if r.status in (STALE, MISSING)]
    unchecked = [r for r in results if r.status == UNCHECKED]
    return {
        "llm_forbidden": True,
        "deterministic": True,
        "advisory": True,
        "n_artifacts": len(results),
        "any_stale": bool(stale),
        "n_stale": len(stale),
        "n_unchecked": len(unchecked),
        "stale": [{"name": r.name, "producer": r.producer, "status": r.status,
                   "age_hours": r.age_hours, "max_age_hours": r.max_age_hours,
                   "public": r.public} for r in stale],
        "artifacts": [{"name": r.name, "producer": r.producer, "status": r.status,
                       "age_hours": r.age_hours, "max_age_hours": r.max_age_hours,
                       "public": r.public, "path": r.path} for r in results],
    }


def write_report(data_dir, *, now: Optional[datetime] = None) -> dict:
    """Run the check and atomically write data/artifact_freshness.json. Returns the report."""
    report = summarize(check_freshness(data_dir, now=now))
    report["generated_at"] = (now or datetime.now(timezone.utc)).isoformat()
    try:
        from spa_core.utils.atomic import atomic_save
        atomic_save(report, str(Path(data_dir) / _REPORT_FILENAME))
    except Exception:  # pragma: no cover — report write must never crash the caller
        pass
    return report


def _alert_if_stale(report: dict) -> bool:
    """Queue a digest entry when any artifact is stale. Fail-safe: never raises.

    Staleness is advisory, not a Tier-1 interrupt, so it goes through the single
    push authority's digest queue (folded into the one daily digest) — a direct
    ``telegram_client.send_message`` here is a rogue sender per
    ``test_telegram_single_authority`` and, being level-triggered, would re-fire
    on every agent run while an artifact stays stale.
    """
    if not report.get("any_stale"):
        return False
    try:
        from spa_core.telegram.push_policy import enqueue_digest
        lines = []
        for s in report.get("stale", [])[:12]:
            pub = " (public)" if s.get("public") else ""
            age = s.get("age_hours")
            age_s = f"{age:.0f}h" if isinstance(age, (int, float)) else s.get("status")
            lines.append(f"• {s['name']}{pub}: {age_s} > {s['max_age_hours']:.0f}h — producer {s['producer']}")
        enqueue_digest(
            "artifact_freshness",
            f"⚠️ Artifact freshness: {report['n_stale']} stale",
            "\n".join(lines),
            severity="WARNING",
            reason="advisory",
        )
        return True
    except Exception:  # pragma: no cover — alerting must never crash the agent
        return False


def run_agent(data_dir: str = "data") -> dict:
    """Agent entry point: write the report and alert on staleness. Returns the report."""
    report = write_report(data_dir)
    _alert_if_stale(report)
    return report


if __name__ == "__main__":  # pragma: no cover
    import sys
    # SPA_DATA_DIR lets the pre-deploy gate sandbox this run; else CLI arg; else "data".
    ddir = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("SPA_DATA_DIR", "data")
    rep = run_agent(ddir)
    print(json.dumps({k: rep[k] for k in ("any_stale", "n_stale", "n_unchecked", "n_artifacts")}, indent=2))
