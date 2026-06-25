"""
spa_core/backtesting/tier1/pipeline_health.py — Tier-1 pipeline observability / SLO health.

PARALLEL MODEL. Pure stdlib, deterministic, LLM-forbidden, atomic writes.

Institutional ops need to know INSTANTLY if any Tier-1 analytical artifact is stale or
missing — a silently-frozen pipeline produces confident-looking but rotten numbers. This
module defines the expected Tier-1 artifacts with per-artifact freshness SLOs (max age in
hours), then for each: does it exist? how old is it (generated_at, mtime fallback)? is it
OK / STALE / MISSING? Rolls up to overall OK | DEGRADED | CRITICAL.

It reads only; it never edits or regenerates any other module. Designed to run LAST in the
daily Tier-1 pipeline (after every artifact has been refreshed) so its verdict reflects the
just-completed run, and to feed agent_health / Telegram with a single ops signal.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import json
from pathlib import Path

from spa_core.utils.atomic import atomic_save

_DATA = Path(__file__).resolve().parents[3] / "data"
_OUT = _DATA / "tier1_pipeline_health.json"

# Daily pipeline → 24h cadence + margin = 30h SLO for daily artifacts.
_DAILY_SLO_H = 30.0

# Expected Tier-1 artifacts: name (path relative to data/), freshness SLO hours, core flag.
# `core` artifacts missing/stale escalate the overall verdict to CRITICAL — they are the
# load-bearing outputs (the verdict and the eligibility gate) the rest of the system reads.
ARTIFACTS = [
    {"name": "tier1_verdict.json",                 "slo_hours": _DAILY_SLO_H, "core": True},
    {"name": "tier1_gate.json",                    "slo_hours": _DAILY_SLO_H, "core": True},
    {"name": "tier1_packages.json",                "slo_hours": _DAILY_SLO_H, "core": False},
    {"name": "tier1_correlation.json",             "slo_hours": _DAILY_SLO_H, "core": False},
    {"name": "tier1_status.json",                  "slo_hours": _DAILY_SLO_H, "core": False},
    {"name": "tier1_data_integrity.json",          "slo_hours": _DAILY_SLO_H, "core": False},
    {"name": "tier1_monte_carlo.json",             "slo_hours": _DAILY_SLO_H, "core": False},
    {"name": "tier1_var.json",                     "slo_hours": _DAILY_SLO_H, "core": False},
    {"name": "tier1_regime.json",                  "slo_hours": _DAILY_SLO_H, "core": False},
    {"name": "tier1_nav_proof.json",               "slo_hours": _DAILY_SLO_H, "core": False},
    {"name": "bee/defillama_apy_history.json",     "slo_hours": _DAILY_SLO_H, "core": False},
]

# Field names that, if present, carry the artifact's own generation timestamp (preferred
# over filesystem mtime, which a `git checkout` / copy can reset).
_TS_FIELDS = ("generated_at", "timestamp", "updated_at", "created_at", "as_of")

STATUSES = ("OK", "STALE", "MISSING")
OVERALL = ("OK", "DEGRADED", "CRITICAL")


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _parse_ts(value) -> datetime.datetime | None:
    """Parse an ISO-8601 timestamp string into an aware UTC datetime, or None."""
    if not isinstance(value, str) or not value:
        return None
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(datetime.timezone.utc)


def _generated_at(path: Path) -> datetime.datetime | None:
    """Best-effort generation time: a timestamp field inside the JSON, else file mtime."""
    try:
        data = json.loads(path.read_text())
        if isinstance(data, dict):
            for field in _TS_FIELDS:
                ts = _parse_ts(data.get(field))
                if ts is not None:
                    return ts
    except Exception:
        pass  # not JSON, unreadable, or no usable field → fall back to mtime
    try:
        return datetime.datetime.fromtimestamp(path.stat().st_mtime, datetime.timezone.utc)
    except OSError:
        return None


def check(now: datetime.datetime | None = None) -> dict:
    """Inspect every expected Tier-1 artifact and roll up an SLO health verdict.

    Returns {artifacts:[{name, exists, age_hours, slo_hours, core, status}], overall,
    stale_count, missing_count, checked_at}. Deterministic for a fixed filesystem + `now`.
    """
    ref = (now or _now()).astimezone(datetime.timezone.utc)
    artifacts = []
    stale_count = 0
    missing_count = 0
    core_broken = False

    for spec in ARTIFACTS:
        name = spec["name"]
        slo_h = float(spec["slo_hours"])
        core = bool(spec["core"])
        path = _DATA / name
        exists = path.is_file()

        if not exists:
            status = "MISSING"
            age_hours = None
            missing_count += 1
            if core:
                core_broken = True
        else:
            gen = _generated_at(path)
            if gen is None:
                age_hours = None
                status = "OK"  # exists but timestamp unreadable → don't false-alarm on age
            else:
                age_hours = round((ref - gen).total_seconds() / 3600.0, 2)
                if age_hours > slo_h:
                    status = "STALE"
                    stale_count += 1
                    if core:
                        core_broken = True
                else:
                    status = "OK"

        artifacts.append({
            "name": name,
            "exists": exists,
            "age_hours": age_hours,
            "slo_hours": slo_h,
            "core": core,
            "status": status,
        })

    if core_broken:
        overall = "CRITICAL"
    elif stale_count or missing_count:
        overall = "DEGRADED"
    else:
        overall = "OK"

    return {
        "checked_at": ref.isoformat(),
        "overall": overall,
        "stale_count": stale_count,
        "missing_count": missing_count,
        "artifacts": artifacts,
    }


def build_report(write: bool = True, now: datetime.datetime | None = None) -> dict:
    """Run check() and (atomically) persist data/tier1_pipeline_health.json."""
    report = check(now=now)
    report = {
        "generated_at": (now or _now()).astimezone(datetime.timezone.utc).isoformat(),
        "model": "tier1_pipeline_health",
        "llm_forbidden": True,
        **report,
    }
    if write:
        atomic_save(report, str(_OUT))
    return report


if __name__ == "__main__":
    r = build_report()
    bad = [a for a in r["artifacts"] if a["status"] != "OK"]
    print("Tier-1 pipeline health: %s  (stale=%d, missing=%d)"
          % (r["overall"], r["stale_count"], r["missing_count"]))
    if bad:
        for a in bad:
            age = "n/a" if a["age_hours"] is None else ("%.1fh" % a["age_hours"])
            print("  [%-7s] %-40s age=%s slo=%.0fh%s"
                  % (a["status"], a["name"], age, a["slo_hours"],
                     " (CORE)" if a["core"] else ""))
    else:
        print("  all %d artifacts fresh" % len(r["artifacts"]))
