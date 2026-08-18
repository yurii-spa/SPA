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


# A timestamp ahead of `now` by more than this is not freshness — it is a broken
# clock or a fabricated stamp. Either way it would mask staleness FOREVER (age is
# negative, so it can never exceed any threshold), so it is UNCHECKED, not FRESH.
FUTURE_TOLERANCE_HOURS = 1.0


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
    # ── content-derived freshness (2026-08-16) ────────────────────────────────
    # For an artifact that IS a series (a track), the honest age is how far its
    # LAST RECORD lags, not when the file was last touched. `series_field` names
    # the list; `series_date_field` names the date inside its final element.
    # When set it is AUTHORITATIVE — it outranks both writer stamps and mtime,
    # because "producer alive, output frozen" is exactly the bug being caught:
    # a writer that re-stamps `generated_at` each run while the series stands
    # still would otherwise report FRESH forever. Configured-but-unreadable is
    # UNCHECKED (fail-CLOSED), never an mtime rescue.
    series_field: Optional[str] = None
    series_date_field: str = "date"
    # Tracked in git and audited FROM the repo → its committed copy is checked as
    # a separate scope (see check_committed_freshness).
    committed: bool = False


# ── THE REGISTRY — every public/committed artifact that must stay fresh ───────────────
# Adding a producer WITHOUT adding it here is the bug this module exists to prevent:
# a new stale-able artifact must be registered, and staleness then shows up RED.
ARTIFACT_REGISTRY: tuple = (
    # cycle-written, daily (~06:00 UTC) → 26h = one cycle + grace
    Artifact("kill_switch_status", "kill_switch_status.json", "daily_cycle", 26.0),
    Artifact("derisk_status", "derisk_status.json", "daily_cycle", 26.0),
    Artifact("paper_trading_status", "paper_trading_status.json", "daily_cycle", 26.0),
    # 2026-08-16: measured FRESH (age 1.27h) while the track inside it had not moved
    # since 2026-08-02 — fourteen days. It carries NO writer stamp at all, so the
    # check fell through to file mtime, and mtime is refreshed by any touch, sync or
    # checkout while the content stands perfectly still. The track's own last day is
    # the only marker that cannot be faked by touching the file.
    # Budget is ARITHMETIC, not taste: the marker is a DATE (midnight-anchored). The
    # 06:00 cycle writes day D at age 6h, and that marker ages to ~30h just before the
    # next cycle — so a healthy track never exceeds ~30h, while one missed cycle passes
    # 36h within half a day. 36h is therefore the tightest threshold that cannot cry
    # wolf on a correct state. (It replaces the 30h mtime budget, which measured a
    # different quantity entirely.)
    Artifact("paper_evidence", "paper_evidence.json", "daily_cycle", 36.0, public=True,
             series_field="days", series_date_field="date", committed=True),
    # 2026-08-18: внутридневной сенсор просадки (ADR-068) — единственная защита
    # лестницы между суточными циклами — не был зарегистрирован здесь ни разу,
    # ровно тот случай, который этот модуль и существует ловить: производитель
    # есть, срока годности у его артефакта нет. Мёртвый сенсор = 24-часовое окно
    # слепоты вернулось, и об этом молчали все.
    # Бюджет АРИФМЕТИЧЕСКИЙ, не на вкус: `com.spa.intraday_equity` —
    # StartInterval=300с, значит здоровый артефакт не старше ~5 минут; 1.0ч = 12
    # пропущенных прогонов подряд, то есть порог не может закричать на исправное
    # состояние. Новых ПОРОГОВ риска здесь нет — это срок годности файла,
    # пороги лестницы (SOFT −5% / HARD −10%) не тронуты.
    Artifact("intraday_equity", "intraday_equity.json", "com.spa.intraday_equity", 1.0),
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


def _series_ts(doc: object, art: Artifact) -> Optional[datetime]:
    """Age marker taken from the LAST record of a series artifact (a track)."""
    if not art.series_field or not isinstance(doc, dict):
        return None
    series = doc.get(art.series_field)
    if not isinstance(series, list) or not series:
        return None
    last = series[-1]
    if not isinstance(last, dict):
        return None
    return _parse_ts(last.get(art.series_date_field))


def _doc_ts(doc: object, art: Artifact) -> Optional[datetime]:
    """Timestamp derived from an artifact's CONTENT (series marker, then ts fields)."""
    series = _series_ts(doc, art)
    if series is not None:
        return series
    if isinstance(doc, dict):
        for fld in art.ts_fields:
            dt = _parse_ts(doc.get(fld))
            if dt is not None:
                return dt
    return None


def _artifact_ts(full_path: Path, art: Artifact) -> Optional[datetime]:
    """Best available timestamp: content marker, else mtime (only when allowed).

    fail-CLOSED on read: an unreadable or corrupt file returns None (→ UNCHECKED)
    and is NEVER rescued by mtime. Before 2026-08-16 it was: a truncated JSON —
    the shape a producer leaves when it dies mid-write — fell through to the file's
    own mtime, and mtime is refreshed by the very write that truncated it. The
    module's stated invariant ("a read error is NEVER fresh") was contradicted by
    its own code, measured returning FRESH on a half-written file.
    """
    try:
        with open(full_path, "r", encoding="utf-8") as fh:
            doc = json.load(fh)
    except OSError:
        return None
    except ValueError:
        return None  # corrupt/truncated JSON — say UNCHECKED, do not guess from mtime

    content_ts = _doc_ts(doc, art)
    if content_ts is not None:
        return content_ts
    # A configured series marker that could not be read is a fail-CLOSED refusal,
    # not an invitation to fall back to the file's mtime.
    if art.series_field:
        return None
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
    required: bool = True
    scope: str = "working"   # "working" = file on disk; "committed" = blob in git

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
            results.append(_result(art, status, None))
            continue
        results.append(_judge(art, _artifact_ts(full, art), now))
    return results


def _result(art: Artifact, status: str, age_hours: Optional[float],
            scope: str = "working") -> FreshnessResult:
    return FreshnessResult(art.name, art.producer, status, age_hours,
                           art.max_age_hours, art.public, art.path,
                           art.required, scope)


def _judge(art: Artifact, ts: Optional[datetime], now: datetime,
           scope: str = "working") -> FreshnessResult:
    """Turn a timestamp into a verdict. fail-CLOSED on both ends of the number line."""
    if ts is None:
        return _result(art, UNCHECKED, None, scope)
    age_h = (now - ts).total_seconds() / 3600.0
    if age_h < -FUTURE_TOLERANCE_HOURS:
        # A future stamp makes age negative, so it can never cross any threshold:
        # the artifact would read FRESH for as long as the bad stamp survives.
        # Refuse to judge it instead of trusting it.
        return _result(art, UNCHECKED, round(age_h, 2), scope)
    status = FRESH if age_h <= art.max_age_hours else STALE
    return _result(art, status, round(age_h, 2), scope)


# ── the COMMITTED copy (the card's original incident) ─────────────────────────────────
# 2026-06-21: the daily cycle kept writing `paper_evidence.json` locally (44 days)
# while the copy IN GIT stood frozen at 12 days. Auditing the track from the repo —
# the only source of truth per CLAUDE.md — was silently broken, and every monitor
# looked at the working tree, so every monitor said fine. Checking the working copy
# does NOT answer this question; a separate scope does.
DEFAULT_GIT_REF = "HEAD"


def _git_show(repo_root, ref: str, rel_path: str) -> tuple:
    """Read a blob out of git. Returns ``(ok, text_or_error)``. Read-only."""
    import subprocess
    try:
        proc = subprocess.run(["git", "show", "{}:{}".format(ref, rel_path)],
                              cwd=str(repo_root), capture_output=True, text=True,
                              timeout=30.0)
    except Exception as exc:  # noqa: BLE001 — git missing / hung / not a repo
        return False, "{}: {}".format(type(exc).__name__, exc)
    if proc.returncode != 0:
        return False, (proc.stderr or proc.stdout or "").strip()[:200]
    return True, proc.stdout


def check_committed_freshness(repo_root, *, now: Optional[datetime] = None,
                              ref: str = DEFAULT_GIT_REF,
                              registry: tuple = ARTIFACT_REGISTRY,
                              data_prefix: str = "data",
                              git_show=None) -> list:
    """Judge the freshness of the COMMITTED copy of every ``committed=True`` artifact.

    A git blob has no mtime, so only the content's own marker can speak — which is
    the honest signal anyway. Anything unreadable is UNCHECKED / MISSING, never FRESH.
    ``git_show`` is injectable so tests describe a repository instead of building one.
    """
    now = now or datetime.now(timezone.utc)
    show = git_show or (lambda rp: _git_show(repo_root, ref, rp))
    results: list = []
    for art in registry:
        if not art.committed:
            continue
        ok, payload = show("{}/{}".format(data_prefix, art.path))
        if not ok:
            results.append(_result(art, MISSING if art.required else UNCHECKED,
                                   None, "committed"))
            continue
        try:
            doc = json.loads(payload)
        except ValueError:
            results.append(_result(art, UNCHECKED, None, "committed"))
            continue
        results.append(_judge(art, _doc_ts(doc, art), now, "committed"))
    return results


def summarize(results: list) -> dict:
    """Aggregate to a report dict. `any_stale` is the single honest headline.

    A REQUIRED artifact that could not be judged counts toward the headline: "we
    could not check it" and "it is fine" must never render as the same signal —
    that is the fail-OPEN shape this module exists to close. An OPTIONAL artifact
    that is simply absent stays out, so the headline cannot be permanently red for
    a state that is correct (a guard nobody can ever see green is a guard nobody
    reads).
    """
    stale = [r for r in results
             if r.status in (STALE, MISSING) or (r.status == UNCHECKED and r.required)]
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
                   "public": r.public, "scope": r.scope} for r in stale],
        "artifacts": [{"name": r.name, "producer": r.producer, "status": r.status,
                       "age_hours": r.age_hours, "max_age_hours": r.max_age_hours,
                       "public": r.public, "path": r.path, "scope": r.scope}
                      for r in results],
    }


def write_report(data_dir, *, now: Optional[datetime] = None,
                 repo_root=None, git_show=None) -> dict:
    """Run the check and atomically write data/artifact_freshness.json. Returns the report.

    When ``repo_root`` is given, the COMMITTED copies are judged too and folded into
    the same headline — a track that is fresh on disk but frozen in git is exactly
    the 2026-06-21 incident, and it must not need a second report to be noticed.
    """
    results = check_freshness(data_dir, now=now)
    if repo_root is not None or git_show is not None:
        results = results + check_committed_freshness(
            repo_root, now=now, git_show=git_show)
    report = summarize(results)
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
            # The scope must be visible: "fresh on disk, frozen in git" is a
            # different incident from "nobody wrote it at all".
            scope = " [git copy]" if s.get("scope") == "committed" else ""
            age = s.get("age_hours")
            age_s = f"{age:.0f}h" if isinstance(age, (int, float)) else s.get("status")
            lines.append(f"• {s['name']}{pub}{scope}: {age_s} > {s['max_age_hours']:.0f}h — producer {s['producer']}")
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


def run_agent(data_dir: str = "data", repo_root=None) -> dict:
    """Agent entry point: write the report and alert on staleness. Returns the report."""
    if repo_root is None:
        repo_root = Path(__file__).resolve().parents[2]
    report = write_report(data_dir, repo_root=repo_root)
    _alert_if_stale(report)
    return report


if __name__ == "__main__":  # pragma: no cover
    import sys
    # SPA_DATA_DIR lets the pre-deploy gate sandbox this run; else CLI arg; else "data".
    ddir = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("SPA_DATA_DIR", "data")
    rep = run_agent(ddir)
    print(json.dumps({k: rep[k] for k in ("any_stale", "n_stale", "n_unchecked", "n_artifacts")}, indent=2))
