"""
agent_health_monitor.py — SPA Agent Health "Heartbeat" Monitor.

Hourly watchdog over every ``com.spa.*`` launchd agent plus the core
system-state files. Detects:

  * agents not loaded into launchctl
  * always-on servers with PID == 0 (crashed / not running)
  * non-zero LastExitStatus
  * stale logs (per-agent expected freshness derived from the plist schedule)
  * malformed / unparseable plists
  * stale daily cycle / equity curve
  * low portfolio health score
  * CRITICAL red flags
  * autopush lag

Writes ``data/agent_health.json`` (atomic) and sends a Telegram alert ONLY
when the overall status is CRITICAL **or** new issues appeared since the
previous run (dedup against the prior agent_health.json) — never spams when
everything is OK.

Design rules (per CLAUDE.md):
  * stdlib only
  * atomic writes (tmp + os.replace via spa_core.utils.atomic)
  * fail-safe: never raises out of run(); always exits 0
  * read-only w.r.t. allocator / risk / execution domains
  * monitoring component → LLM FORBIDDEN

CLI:
    python3 -m spa_core.monitoring.agent_health_monitor --check   # compute+write+print, NO telegram
    python3 -m spa_core.monitoring.agent_health_monitor --run     # compute+write+SEND telegram
"""
from __future__ import annotations

import argparse
import glob
import json
import logging
import os
import plistlib
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from spa_core.monitoring.agent_registry_refresh import refresh_if_stale
from spa_core.monitoring.cycle_lock_watch import check_cycle_lock

log = logging.getLogger("spa.monitoring.agent_health_monitor")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _PROJECT_ROOT / "data"
_DEFAULT_LAUNCH_AGENTS_DIR = Path.home() / "Library" / "LaunchAgents"
_OUTPUT_FILENAME = "agent_health.json"
_AUTOPUSH_LOG = str(_PROJECT_ROOT / "logs" / "auto_push.log")

# ---------------------------------------------------------------------------
# Status constants (ordered by severity)
# ---------------------------------------------------------------------------
OK = "OK"
WARNING = "WARNING"
CRITICAL = "CRITICAL"
# Reader-side verdicts (never written by the monitor itself): a snapshot older
# than its freshness contract is STALE — its healthy counts are HISTORY, not a
# statement about the fleet right now (2026-08-05: an 8h-old "healthy 69/69"
# was displayed while 39 agents were down since 07:00Z).
STALE = "STALE"
UNCHECKED = "UNCHECKED"
_SEVERITY = {OK: 0, WARNING: 1, CRITICAL: 2}

# Snapshot freshness contract (self-describing — embedded in every report so
# consumers do not need to hard-code the monitor's cadence):
# com.spa.agent_health runs HOURLY; a snapshot older than 1 missed run + buffer
# must be treated as unknown fleet state, never as current health.
SNAPSHOT_CADENCE_MIN = 60.0
SNAPSHOT_STALE_MIN = 90.0

# WAKE_STORM: N agents carrying a nonzero last exit at the same time = a mass
# simultaneous failure (host wake / broken deploy / exec-bit strip), a distinct
# CRITICAL signal even when each individual agent would only be WARNING.
# 2026-08-05 07:00Z: 39 of 69 agents fell in the same minute.
WAKE_STORM_MIN_AGENTS = 5

# Shared red-flag severity vocabulary + portfolio_health field reader (single
# source — N8). Matching the critical SET (not a hard-coded literal) means a
# red_flag_monitor severity rename can only widen detection, never disable it.
try:
    from spa_core.alerts.severity import is_critical as _is_critical_severity
    from spa_core.alerts.severity import (
        read_portfolio_health_score as _read_portfolio_health_score,
    )
except Exception:                          # noqa: BLE001 — never let an import gap blind the monitor
    _FALLBACK_CRIT = frozenset({"CRITICAL", "CRIT", "FATAL", "SEVERE", "EMERGENCY"})

    def _is_critical_severity(sev) -> bool:  # type: ignore[no-redef]
        return isinstance(sev, str) and sev.strip().upper() in _FALLBACK_CRIT

    def _read_portfolio_health_score(doc):   # type: ignore[no-redef]
        if not isinstance(doc, dict):
            return None
        for k in ("health_score", "score", "portfolio_health_score", "overall_score"):
            v = doc.get(k)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                return float(v)
        return None


def _worst(*statuses: str) -> str:
    """Return the highest-severity status among the args."""
    return max(statuses, key=lambda s: _SEVERITY.get(s, 0)) if statuses else OK


# ---------------------------------------------------------------------------
# Freshness categories — derived from the plist schedule.
# Each maps to a "stale" threshold in minutes. Logs older than the threshold
# are WARNING; older than 2x are CRITICAL.
# ---------------------------------------------------------------------------
CAT_HIGH_FREQ = "high_freq"      # StartInterval <= 600s  (~5 min agents)
CAT_MID_FREQ = "mid_freq"        # 600 < StartInterval <= 7200s (15-120 min)
CAT_DAILY = "daily"              # StartCalendarInterval (hourly/daily) or interval > 7200s
CAT_WEEKLY = "weekly"            # StartCalendarInterval with Weekday key (repeating weekly)
CAT_ONE_TIME = "one_time"        # StartCalendarInterval with specific Month+Day (runs once)
CAT_ALWAYS_ON = "always_on"      # KeepAlive server — check PID, not log age
CAT_ON_DEMAND = "on_demand"      # RunAtLoad-once, no schedule/keepalive

_FRESHNESS_THRESHOLD_MIN = {
    CAT_HIGH_FREQ: 30,          # alert if log > 30 min old
    CAT_MID_FREQ: 180,          # alert if log > 3 h old
    CAT_DAILY: 26 * 60,         # alert if log > 26 h old
    CAT_WEEKLY: 7 * 24 * 60,    # alert if log > 7 days old (CRIT at 14 days)
}

# Categories whose agents launchd keeps RESIDENT in `launchctl list` between runs:
#   * KeepAlive daemons (always_on) — a live long-running process / port.
#   * StartInterval agents (high/mid freq) — launchd holds them loaded and fires
#     them on the interval; absence from launchctl means they were never
#     bootstrapped / got unloaded → a real fault.
# Calendar/one-time agents (CAT_DAILY/WEEKLY/ONE_TIME backed by
# StartCalendarInterval + RunAtLoad:False) legitimately EXIT between scheduled
# runs and need not be resident at this instant — they are judged by LOG
# FRESHNESS (did they run within their window?), never by residency. Judging a
# correctly-idle calendar job "not loaded" is the chronic false-CRITICAL bug.
_RESIDENCY_REQUIRED_CATS = frozenset({CAT_ALWAYS_ON, CAT_HIGH_FREQ, CAT_MID_FREQ})

# Agents that have been RETIRED / superseded and must NOT be flagged or revived.
#   * com.spa.bot_commands — replaced by com.spa.telegram_bot, which runs the
#     IDENTICAL module (spa_core.telegram.bot). Running both would open two
#     getUpdates long-polls → Telegram 409 conflict. The .plist may linger on a
#     host; treat it as retired so it is neither false-flagged nor bootstrapped.
#   * com.spa.httpserver — retired (owner decision 2026-06-27): its module bound
#     :8765, the same port the apiserver (FastAPI/uvicorn) owns → EADDRINUSE
#     crash-loop. apiserver fully covers the HTTP-API surface, so httpserver is
#     retired rather than rehomed to another port.
#   * The RETIRED DAILY-REPORT fleet (Telegram rebuild 2026-06-27): the daily /
#     weekly Telegram digest is now owned SOLELY by com.spa.digest_daily
#     (@08:10 UTC → spa_core.telegram.reports.daily) and com.spa.digest_weekly
#     (Sun 10:00 → spa_core.telegram.reports.weekly), which collapse the former
#     four+ duplicate daily/weekly senders into ONE message each and route
#     everything else through push_policy. The standalone senders below ran the
#     digest BUILDERS directly (or were earlier daily reports) → duplicate sends.
#     Their .plist may linger on a host (some already *.disabled); treat them as
#     retired so they are neither false-flagged "Missing (not loaded)" nor
#     revived. (NOT retired and intentionally absent here: telegram_milestone =
#     distinct milestone celebrations via push_policy; tier1_digest = distinct
#     weekly Tier-1 strategy digest; both remain live.)
#       - com.spa.telegram_daily       → replaced by com.spa.digest_daily
#       - com.spa.telegram_weekly      → replaced by com.spa.digest_weekly
#       - com.spa.morning_digest       → old daily report (already *.disabled)
#       - com.spa.daily-paper-report   → old daily report (already *.disabled)
RETIRED_LABELS = frozenset({
    "com.spa.bot_commands",
    "com.spa.httpserver",
    "com.spa.telegram_daily",
    "com.spa.telegram_weekly",
    "com.spa.morning_digest",
    "com.spa.daily-paper-report",
    # Telegram digest agents consolidated into the single daily report (same
    # anti-flood intent as the telegram_* retirements above). Both were loaded
    # but not firing (empty /tmp logs) — delivering nothing — so agent_health
    # should stop expecting a fresh heartbeat from them. Owner may fully unload
    # + delete their plists at leisure, or revive if a separate digest is wanted.
    "com.spa.tier1_digest",
    "com.spa.digest_weekly",
    # Q3-1: weekly_backup is a coarse whole-tree tar to a LOCAL folder (~/Documents/SPA_Backups)
    # — same-host (SPOF, does not survive host loss) and redundant with the real DR path
    # (com.spa.daily_backup runs daily_backup.py DB snapshot + dr_offsite_copy offsite-verified;
    # source already lives in git/GitHub). It stood WARNING ("log missing (never ran?)") persistently
    # → pure alert-fatigue with ~0 DR value beyond daily_backup. Retired so agent_health reaches clean
    # all-OK. REVERSIBLE: remove this line + re-add to install_all_agents.sh to revive. OWNER: unload the
    # lingering plist on the prod host (`launchctl bootout gui/$(id -u)/com.spa.weekly_backup`).
    "com.spa.weekly_backup",
    # own-21 (owner-approved 2026-07-23): checkpoint-7day is a SPENT one-shot — schedule Month:6 Day:19
    # fired once on 2026-06-19 and will not fire again until next June. Left loaded = dead weight.
    # Unloaded + plist moved to data/retired_plists_backup/. REVERSIBLE: remove this line + re-add to
    # install_all_agents.sh + restore plist to revive.
    "com.spa.checkpoint-7day",
})


def _runs_at_load(plist: Optional[dict]) -> bool:
    """RunAtLoad value (default True — launchd's documented default when the key
    is absent). A calendar agent with RunAtLoad:False is the one that should NOT
    be expected resident between scheduled runs."""
    if not plist:
        return True
    val = plist.get("RunAtLoad")
    return True if val is None else bool(val)


def requires_residency(category: str, plist: Optional[dict]) -> bool:
    """Whether an agent should be present in `launchctl list` right now.

    KeepAlive daemons and StartInterval guardians: YES (launchd keeps them
    resident; absence = fault). Calendar/one-time agents that exit between runs
    (RunAtLoad:False): NO — judge them by log freshness instead. A calendar
    agent declared RunAtLoad:True is a boot-time one-shot we DO expect resident
    only transiently, so it is still judged by freshness, not residency.
    """
    return category in _RESIDENCY_REQUIRED_CATS

# System-check thresholds
EQUITY_STALE_H = 30.0
CYCLE_STALE_H = 26.0
PORTFOLIO_HEALTH_FLOOR = 70.0
AUTOPUSH_LAG_H = 2.0
# Track-accrual SLA: daily cadence (24h) + 6h buffer = one fully-missed cycle.
TRACK_SLA_H = 30.0
# Resilience DR-posture SLA: com.spa.resilience runs every 6h → stale past ~13h
# means it missed two runs (advisory WARNING — DR proof rotting, not money-path).
RESILIENCE_STALE_H = 13.0

# Fleet-parity freshness: the declared-vs-plist-vs-retired drift guard (Q3-2). Fleet
# composition changes rarely, so a generous window — a status older than this just means
# nobody re-ran the parity check (advisory WARNING, not money-path).
FLEET_PARITY_STALE_H = 26.0


# ===========================================================================
# Dataclasses
# ===========================================================================
@dataclass
class AgentHealth:
    label: str
    status: str = OK
    pid: int = 0
    last_exit: Optional[int] = None
    log_age_min: Optional[float] = None
    category: str = CAT_ON_DEMAND
    loaded: bool = False
    issue: str = ""

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "status": self.status,
            "pid": self.pid,
            "last_exit": self.last_exit,
            "log_age_min": (round(self.log_age_min, 1)
                            if self.log_age_min is not None else None),
            "category": self.category,
            "loaded": self.loaded,
            "issue": self.issue,
        }


# ===========================================================================
# launchctl parsing
# ===========================================================================
def parse_launchctl_list(text: str) -> Dict[str, dict]:
    """Parse ``launchctl list`` tab-separated output → {label: {pid, exit}}.

    Format per line:  ``<PID>\t<Status>\t<Label>`` where PID may be ``-``.
    Header line ("PID\tStatus\tLabel") and blanks are skipped.
    """
    out: Dict[str, dict] = {}
    for line in (text or "").splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        pid_s, status_s, label = parts[0].strip(), parts[1].strip(), parts[2].strip()
        if label == "Label" or not label:
            continue  # header / blank

        try:
            pid = int(pid_s) if pid_s not in ("-", "") else 0
        except ValueError:
            pid = 0
        try:
            exit_code: Optional[int] = int(status_s) if status_s not in ("-", "") else None
        except ValueError:
            exit_code = None

        out[label] = {"pid": pid, "exit": exit_code}
    return out


def _run_launchctl_list() -> str:
    """Run ``launchctl list``; fail-safe → '' on error."""
    try:
        proc = subprocess.run(
            ["launchctl", "list"],
            capture_output=True, text=True, timeout=15,
        )
        return proc.stdout or ""
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("launchctl list failed: %s", exc)
        return ""


# ===========================================================================
# plist discovery & classification
# ===========================================================================
def discover_plists(launch_agents_dir: Path) -> List[Path]:
    """All ``com.spa.*.plist`` files (excluding ``*.disabled``)."""
    pattern = str(Path(launch_agents_dir) / "com.spa.*.plist")
    return sorted(Path(p) for p in glob.glob(pattern) if not p.endswith(".disabled"))


def label_from_path(path: Path) -> str:
    """``.../com.spa.foo.plist`` → ``com.spa.foo``."""
    return Path(path).name[:-len(".plist")] if str(path).endswith(".plist") else Path(path).name


def _load_plist(path: Path) -> Tuple[Optional[dict], bool]:
    """Return (plist_dict, parse_ok). On malformed XML, attempt a best-effort
    regex fallback so we can still locate the log + interval."""
    try:
        with open(path, "rb") as f:
            return plistlib.load(f), True
    except Exception as exc:  # noqa: BLE001 — any parse error is non-fatal
        log.warning("plist parse failed for %s: %s", path, exc)
        return _regex_plist_fallback(path), False


def _regex_plist_fallback(path: Path) -> dict:
    """Extract StandardOutPath / StartInterval / StartCalendarInterval / KeepAlive
    from a malformed plist via regex. Best-effort only."""
    out: dict = {}
    try:
        raw = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    m = re.search(r"<key>StandardOutPath</key>\s*<string>([^<]+)</string>", raw)
    if m:
        out["StandardOutPath"] = m.group(1).strip()
    m = re.search(r"<key>StandardErrorPath</key>\s*<string>([^<]+)</string>", raw)
    if m:
        out["StandardErrorPath"] = m.group(1).strip()
    m = re.search(r"<key>StartInterval</key>\s*<integer>(\d+)</integer>", raw)
    if m:
        out["StartInterval"] = int(m.group(1))
    if re.search(r"<key>StartCalendarInterval</key>", raw):
        cal: dict = {}
        # Detect weekly schedule (Weekday key present)
        m = re.search(r"<key>Weekday</key>\s*<integer>(\d+)</integer>", raw)
        if m:
            cal["Weekday"] = int(m.group(1))
        # Detect specific date (Month + Day = one-time run)
        mm = re.search(r"<key>Month</key>\s*<integer>(\d+)</integer>", raw)
        dm = re.search(r"<key>Day</key>\s*<integer>(\d+)</integer>", raw)
        if mm:
            cal["Month"] = int(mm.group(1))
        if dm:
            cal["Day"] = int(dm.group(1))
        out["StartCalendarInterval"] = cal
    if re.search(r"<key>KeepAlive</key>\s*<true\s*/>", raw):
        out["KeepAlive"] = True
    return out


def classify_agent(plist: Optional[dict]) -> str:
    """Map a plist's schedule to a freshness category."""
    if not plist:
        return CAT_ON_DEMAND
    if plist.get("KeepAlive"):
        return CAT_ALWAYS_ON
    si = plist.get("StartInterval")
    if isinstance(si, int) and si > 0:
        if si <= 600:
            return CAT_HIGH_FREQ
        if si <= 7200:
            return CAT_MID_FREQ
        return CAT_DAILY
    cal = plist.get("StartCalendarInterval")
    if cal is not None:
        if isinstance(cal, dict):
            # Specific date (Month + Day) → one-time job, no freshness alarm
            if "Month" in cal and "Day" in cal:
                return CAT_ONE_TIME
            # Weekly schedule (Weekday key)
            if "Weekday" in cal:
                return CAT_WEEKLY
        return CAT_DAILY
    return CAT_ON_DEMAND


def plist_log_path(plist: Optional[dict]) -> Optional[str]:
    if not plist:
        return None
    return plist.get("StandardOutPath") or None


def plist_log_paths(plist: Optional[dict]) -> List[str]:
    """Both log streams (stdout + stderr) configured for an agent.

    A module that logs via Python's ``logging`` writes to stderr, so its
    StandardOutPath stays empty/frozen while StandardErrorPath is live
    (and vice-versa for ``print``-based agents). Returning both lets freshness
    be judged by whichever stream the agent actually writes to."""
    if not plist:
        return []
    paths: List[str] = []
    for key in ("StandardOutPath", "StandardErrorPath"):
        val = plist.get(key)
        if val:
            paths.append(val)
    return paths


def _agent_short_name(label: str) -> str:
    """``com.spa.foo`` → ``foo`` (the per-agent log basename)."""
    return label[len("com.spa."):] if label.startswith("com.spa.") else label


def candidate_log_paths(
    label: str,
    plist: Optional[dict],
    project_root: Path = _PROJECT_ROOT,
) -> List[str]:
    """All log paths whose mtime can evidence an agent's last run.

    After the launchd fleet migration, agents no longer write
    ``logs/<name>.log`` under ~/Documents. Each agent now logs through the
    canonical wrapper (``scripts/agent_template.sh``) to
    ``/tmp/spa_<name>.log`` while launchd captures the wrapper's stdout/stderr
    to the plist's StandardOutPath/StandardErrorPath
    (``/tmp/spa_<name>.launchd.{out,err}``).

    The wrapper redirects ALL of its python's output to ``/tmp/spa_<name>.log``,
    so the plist's ``.launchd.out``/``.launchd.err`` only get touched at the
    launchd START banner and can lag the real run — judging freshness solely by
    them falsely flags a recently-run agent stale (the migration regression).

    Resolution order (freshest mtime wins — see ``freshest_log_age_minutes``):
      1. the plist's StandardOutPath/StandardErrorPath (true new location),
      2. the wrapper log ``/tmp/spa_<name>.log`` (where the work actually logs),
      3. the legacy ``logs/<name>.log`` under the repo (pre-migration fallback).

    A genuinely-not-run agent has NONE of these → freshness is None → still
    flagged (fail-CLOSED). Order/dedup is preserved; only readable paths matter.
    """
    paths: List[str] = list(plist_log_paths(plist))
    short = _agent_short_name(label)
    for cand in (
        f"/tmp/spa_{short}.log",
        str(Path(project_root) / "logs" / f"{short}.log"),
    ):
        if cand not in paths:
            paths.append(cand)
    return paths


# ===========================================================================
# Time helpers (now & file age injectable for tests)
# ===========================================================================
def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def file_age_minutes(path: Optional[str], now: datetime) -> Optional[float]:
    """Minutes since ``path`` was last modified. None if missing/unreadable."""
    if not path:
        return None
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return None
    age_s = now.timestamp() - mtime
    return max(0.0, age_s / 60.0)


def freshest_log_age_minutes(paths: List[str], now: datetime) -> Optional[float]:
    """Minutes since the most-recently-written of ``paths`` was touched.

    Ignores missing/unreadable paths; returns None only when none are
    readable. Used so an agent that writes only stderr isn't judged stale by
    its empty stdout log."""
    ages = [a for a in (file_age_minutes(p, now) for p in paths) if a is not None]
    return min(ages) if ages else None


def _parse_iso(ts: Optional[str]) -> Optional[datetime]:
    if not ts or not isinstance(ts, str):
        return None
    s = ts.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _hours_since(ts: Optional[str], now: datetime) -> Optional[float]:
    dt = _parse_iso(ts)
    if dt is None:
        return None
    return max(0.0, (now - dt).total_seconds() / 3600.0)


# ===========================================================================
# Per-agent check
# ===========================================================================
def check_agent(label: str, plist: Optional[dict], parse_ok: bool,
                launchctl: Dict[str, dict], now: datetime,
                project_root: Path = _PROJECT_ROOT) -> AgentHealth:
    """Classify the health of a single agent. Fail-safe."""
    cat = classify_agent(plist)
    health = AgentHealth(label=label, category=cat)

    entry = launchctl.get(label)
    health.loaded = entry is not None
    if entry is not None:
        health.pid = int(entry.get("pid") or 0)
        health.last_exit = entry.get("exit")

    issues: List[str] = []

    # 1) Loaded into launchctl?
    # Only KeepAlive daemons and StartInterval guardians are expected to be
    # RESIDENT at this instant — for them, absence is a real fault. Calendar /
    # one-time agents (StartCalendarInterval + RunAtLoad:False) correctly EXIT
    # between scheduled runs; "not resident right now" is their normal idle state
    # and must NOT be CRITICAL. They are judged below by log freshness — i.e. did
    # they actually run within their schedule window (fail-CLOSED: a calendar job
    # whose log is stale past its window IS still flagged).
    if not health.loaded:
        if requires_residency(cat, plist):
            health.status = CRITICAL
            health.issue = "not loaded in launchctl"
            return health
        # Non-resident calendar/one-time agent: installed but idle between runs.
        # Fall through to the freshness check (does NOT short-circuit). With no
        # launchctl entry there is no PID/exit to read, so skip those checks.

    # 2) Malformed plist (loaded but config unparseable) → WARNING
    if not parse_ok:
        issues.append("malformed plist")
        health.status = _worst(health.status, WARNING)

    # 3) Non-zero last exit status — an agent whose LAST exit was a failure can
    # never be OK. The ONLY carve-out is an always-on server that is currently
    # running (PID != 0) whose last exit was a SIGNAL (negative code): launchctl
    # retains the previous exit even after a successful restart, so -15 (SIGTERM
    # from a clean stop/redeploy) would produce a false alarm while the process
    # is alive. A POSITIVE nonzero exit is a real crash of the previous
    # incarnation and stays visible as WARNING even when KeepAlive restarted it
    # (2026-08-05: telegram_bot last_exit=1 was reported OK — fail-OPEN).
    _server_alive = cat == CAT_ALWAYS_ON and health.pid != 0
    _clean_signal_restart = (
        _server_alive
        and isinstance(health.last_exit, int)
        and health.last_exit < 0
    )
    if health.last_exit not in (None, 0) and not _clean_signal_restart:
        if _server_alive:
            # crashed previously, KeepAlive brought it back → visible, not OK
            issues.append(f"last_exit={health.last_exit} (prior crash; restarted)")
            sev = WARNING
        elif cat == CAT_ALWAYS_ON:
            # always-on server NOT running with a nonzero exit → crash → CRITICAL
            issues.append(f"last_exit={health.last_exit}")
            sev = CRITICAL
        else:
            issues.append(f"last_exit={health.last_exit}")
            sev = WARNING
        health.status = _worst(health.status, sev)

    # 4) Always-on servers: must have a live PID
    if cat == CAT_ALWAYS_ON:
        if health.pid == 0:
            issues.append("PID=0 (server down)")
            health.status = _worst(health.status, CRITICAL)
    elif cat in _FRESHNESS_THRESHOLD_MIN:
        # 5) Scheduled agents: log freshness. Judge by the *freshest* of ALL
        # candidate logs — the plist's stdout/stderr streams PLUS the migrated
        # wrapper log /tmp/spa_<name>.log and the legacy logs/<name>.log. After
        # the fleet migration the plist's .launchd.out/.err only carry the START
        # banner and lag the real run, while the wrapper writes the actual work
        # to /tmp/spa_<name>.log — judging by the freshest avoids false "stale".
        logps = candidate_log_paths(label, plist, project_root)
        age = freshest_log_age_minutes(logps, now)
        health.log_age_min = age
        threshold = _FRESHNESS_THRESHOLD_MIN[cat]
        if not logps:
            # no log configured — can't assess freshness, leave as-is
            pass
        elif age is None:
            # No log file. For a RESIDENT guardian (high/mid-freq agent launchd
            # keeps loaded) this means it has never produced output → CRITICAL.
            # For a non-resident calendar/one-time agent, a missing log is
            # ambiguous: it may simply not have fired yet within its window, or
            # its log (often /tmp) was wiped on reboot — we cannot prove a real
            # outage, so it is an advisory WARNING (fail-closed but not a false
            # CRITICAL). A calendar agent with a STALE log past its window is
            # still flagged below — a genuine missed run is NOT masked.
            issues.append("log missing (never ran?)")
            if requires_residency(cat, plist):
                health.status = _worst(health.status, CRITICAL)
            else:
                health.status = _worst(health.status, WARNING)
        elif age > 2 * threshold:
            issues.append(f"log stale {_fmt_age(age)} (>{_fmt_age(2*threshold)})")
            health.status = _worst(health.status, CRITICAL)
        elif age > threshold:
            issues.append(f"log stale {_fmt_age(age)} (>{_fmt_age(threshold)})")
            health.status = _worst(health.status, WARNING)
    # CAT_ON_DEMAND: only loaded + exit checks above.

    health.issue = "; ".join(issues)
    return health


def _fmt_age(minutes: float) -> str:
    """Human-friendly age: '25min' / '3.1h' / '1.2d'."""
    if minutes < 90:
        return f"{round(minutes)}min"
    hours = minutes / 60.0
    if hours < 36:
        return f"{hours:.1f}h"
    return f"{hours/24.0:.1f}d"


# ===========================================================================
# System-state checks
# ===========================================================================
def _load_json(data_dir: Path, *names: str) -> Optional[dict]:
    """Load the first existing JSON among ``names`` from data_dir. None if none."""
    for name in names:
        p = Path(data_dir) / name
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (OSError, ValueError) as exc:
                log.warning("failed to read %s: %s", p, exc)
                return None
    return None


def check_system(data_dir: Path, now: datetime,
                 autopush_log: str = _AUTOPUSH_LOG) -> Tuple[dict, str, List[str]]:
    """Run system-state checks. Returns (system_checks, status, issue_lines)."""
    checks: dict = {
        "cycle_freshness_h": None,
        "equity_last_update_h": None,
        "portfolio_health_score": None,
        "critical_flags": 0,
        "autopush_lag_h": None,
        "track_fresh": None,
        "track_age_h": None,
        "resilience_posture": None,
        "resilience_age_h": None,
    }
    status = OK
    issues: List[str] = []

    # --- equity curve freshness ---
    equity = _load_json(data_dir, "equity_curve_daily.json")
    if equity:
        ts = equity.get("generated_at")
        if not ts:
            daily = equity.get("daily") or []
            if daily and isinstance(daily[-1], dict):
                ts = daily[-1].get("date")
        h = _hours_since(ts, now)
        checks["equity_last_update_h"] = round(h, 2) if h is not None else None
        if h is not None and h > EQUITY_STALE_H:
            issues.append(f"equity_curve stale {h:.1f}h (>{EQUITY_STALE_H:.0f}h)")
            status = _worst(status, CRITICAL)

    # --- cycle freshness (cycle_status.json | cycle_health.json | paper_trading_status.json) ---
    cyc = _load_json(data_dir, "cycle_status.json", "cycle_health.json",
                     "paper_trading_status.json")
    if cyc:
        ts = (cyc.get("last_run")
              or cyc.get("last_cycle_ts")
              or (cyc.get("checks", {}).get("cycle_gap", {}) or {}).get("last_cycle_at"))
        h = _hours_since(ts, now)
        checks["cycle_freshness_h"] = round(h, 2) if h is not None else None
        if h is not None and h > CYCLE_STALE_H:
            issues.append(f"daily cycle stale {h:.1f}h (>{CYCLE_STALE_H:.0f}h)")
            status = _worst(status, CRITICAL)

    # --- track-accrual SLA (the one thing that matters: the honest go-live track
    # accruing a fresh EVIDENCED bar daily). Uses the shared track_freshness gate
    # so the API health endpoint and this monitor agree. Fail-CLOSED: an
    # unreadable track is stale, not silently healthy. The stable issue string is
    # deduped by should_alert() → one debounced alert, not one per run. ---
    # Only assessed when a real track surface is present — i.e. the equity-curve
    # file carries a ``daily`` bar series (the production host always does). When
    # there is no bar series there is nothing accruing to alert on here (file
    # absence / a bare generated_at file are handled by the equity/cycle
    # freshness checks above and existing fixtures), so we skip rather than
    # double-flag. When a ``daily`` series IS present, this is fail-CLOSED:
    # empty / no-evidenced-bar / stale → degraded → CRITICAL alert.
    _equity_for_track = _load_json(data_dir, "equity_curve_daily.json")
    if isinstance(_equity_for_track, dict) and isinstance(
        _equity_for_track.get("daily"), list
    ):
        try:
            from spa_core.paper_trading.track_freshness import (
                check_track_freshness,
            )

            track = check_track_freshness(data_dir, now=now, sla_hours=TRACK_SLA_H)
            checks["track_fresh"] = bool(track.get("track_fresh"))
            checks["track_age_h"] = track.get("age_hours")
            if not track.get("track_fresh"):
                age = track.get("age_hours")
                if age is None:
                    issues.append(
                        f"track accrual STALE: {track.get('reason', 'unreadable')} "
                        f"(>{TRACK_SLA_H:.0f}h SLA)"
                    )
                else:
                    issues.append(
                        f"track accrual STALE: newest evidenced bar {age:.1f}h old "
                        f"(>{TRACK_SLA_H:.0f}h SLA)"
                    )
                # Advisory WARNING (not CRITICAL): the stale-track issue is a
                # STABLE string, so should_alert() fires it exactly ONCE (deduped
                # against the prior agent_health.json) rather than every run. The
                # daily cycle / equity-curve CRITICAL checks above still catch a
                # truly dead cycle; this is the focused, debounced track-SLA signal.
                status = _worst(status, WARNING)
        except Exception as exc:  # noqa: BLE001 — never let the gate blind the monitor
            log.warning("track freshness check failed: %s", exc)
            checks["track_fresh"] = False
            issues.append("track accrual STALE: freshness check error (fail-closed)")
            status = _worst(status, WARNING)

    # --- portfolio health score ---
    ph = _load_json(data_dir, "portfolio_health.json")
    if ph:
        # Read the ACTUAL key the writer emits via the one shared helper both
        # monitors use (N8): health_score → score → … precedence.
        score = _read_portfolio_health_score(ph)
        if isinstance(score, (int, float)):
            checks["portfolio_health_score"] = round(float(score), 1)
            if score < PORTFOLIO_HEALTH_FLOOR:
                issues.append(f"portfolio_health {score:.1f}/100 (<{PORTFOLIO_HEALTH_FLOOR:.0f})")
                status = _worst(status, WARNING)

    # --- red flags (market intel — advisory unless a HELD protocol is hit) ---
    # A red flag concerns an EXTERNAL protocol's market conditions, not the health
    # of SPA's own agents. It drives SYSTEM status to CRITICAL only when it hits a
    # protocol we actually hold. Flags on protocols we don't hold — or from
    # fallback/bootstrap data (live feed down) — are surfaced at WARNING (advisory).
    rf = _load_json(data_dir, "red_flags.json")
    if rf:
        flags = rf.get("red_flags") or rf.get("flags") or []
        crit_flags = [
            f for f in flags
            if isinstance(f, dict)
            and _is_critical_severity(f.get("severity"))
        ]
        if crit_flags:
            pos = _load_json(data_dir, "current_positions.json") or {}
            held = {str(k).lower() for k in (pos.get("positions") or {})}
            fallback = bool(rf.get("fallback_used"))

            def _hits_held(flag: dict) -> bool:
                proto = str(flag.get("protocol", "")).lower().replace("-", "_")
                return any(h and (h in proto or proto in h) for h in held)

            held_crit = [] if fallback else [f for f in crit_flags if _hits_held(f)]
            advisory = len(crit_flags) - len(held_crit)
            # Only HELD-protocol flags are true system criticals. critical_flags
            # feeds critical_count, which must stay 0 ⟺ overall != CRITICAL.
            checks["critical_flags"] = len(held_crit)
            checks["advisory_flags"] = advisory
            if held_crit:
                issues.append(f"{len(held_crit)} CRITICAL red flag(s) on HELD protocols")
                status = _worst(status, CRITICAL)
            if advisory > 0:
                # Advisory ONLY: red flags on EXTERNAL (non-held) protocols — or
                # from fallback/bootstrap data — are market intel, NOT a fault in
                # SPA's own agents. They must NOT escalate the overall health
                # status (that produced false WARNING on a fully-healthy fleet).
                # Recorded for visibility (checks["advisory_flags"] + this note)
                # but deliberately kept OUT of the status-driving `issues` list.
                checks["advisory_note"] = (
                    f"{advisory} red flag(s) on external protocols "
                    f"(advisory, non-escalating)"
                )
        else:
            checks["critical_flags"] = 0

    # --- autopush lag ---
    age = file_age_minutes(autopush_log, now)
    if age is not None:
        lag_h = age / 60.0
        checks["autopush_lag_h"] = round(lag_h, 2)
        if lag_h > AUTOPUSH_LAG_H:
            issues.append(f"autopush lag {lag_h:.1f}h (>{AUTOPUSH_LAG_H:.0f}h)")
            status = _worst(status, WARNING)

    # --- resilience DR posture (Q1-10) ---
    # resilience_status.py rolls up offsite-copy + restore + fleet drills into one
    # posture. A stale rollup (com.spa.resilience not running) or a non-OK posture
    # (a drill failed / offsite unverified) is a rotting DR guarantee — surface it
    # as an advisory WARNING so a decaying posture pages rather than sitting silent
    # in a JSON nobody reads. Advisory (WARNING, not CRITICAL): DR is not the
    # money-path; the track/kill checks above own criticality. Only assessed when
    # the file is present (like the checks above) so sandbox/CI fixtures without a
    # resilience_status.json are not falsely flagged; a truly missing posture on the
    # prod host is caught by the per-agent freshness check for com.spa.resilience.
    res = _load_json(data_dir, "resilience_status.json")
    if res:
        rts = res.get("generated_at")
        rh = _hours_since(rts, now)
        checks["resilience_age_h"] = round(rh, 2) if rh is not None else None
        posture = (str(res.get("overall")).upper() if res.get("overall") else None)
        checks["resilience_posture"] = posture
        if rh is not None and rh > RESILIENCE_STALE_H:
            issues.append(
                f"resilience posture stale {rh:.1f}h (>{RESILIENCE_STALE_H:.0f}h) "
                "— DR proof-chain not fresh"
            )
            status = _worst(status, WARNING)
        elif posture and posture != OK:
            issues.append(f"resilience posture {posture} (DR drill/offsite not passing)")
            status = _worst(status, WARNING)

    # --- fleet parity drift (Q3-2) ---
    # fleet_parity_check compares the installer's DECLARED fleet vs the on-disk plists vs
    # RETIRED_LABELS (and, on the prod host, the live launchctl set). A DRIFT — a retired
    # label still installed (revival / Telegram-409 flood hazard), an orphan plist nobody
    # installs, a declared label with no plist, or a declared agent not running — currently
    # writes a JSON nobody is paged on. Surface it as an advisory WARNING (fleet hygiene is
    # not the money-path; the track/kill checks own criticality). Only assessed when present
    # so sandbox/CI fixtures without the file are not falsely flagged.
    fp = _load_json(data_dir, "fleet_parity.json")
    if fp:
        fh = _hours_since(fp.get("generated_at") or fp.get("ts"), now)
        checks["fleet_parity_age_h"] = round(fh, 2) if fh is not None else None
        fp_status = str(fp.get("status")).upper() if fp.get("status") else None
        checks["fleet_parity_status"] = fp_status
        if fh is not None and fh > FLEET_PARITY_STALE_H:
            issues.append(
                f"fleet parity stale {fh:.1f}h (>{FLEET_PARITY_STALE_H:.0f}h) — drift guard not re-run"
            )
            status = _worst(status, WARNING)
        elif fp_status == "DRIFT":
            classes = []
            for k, lbl in (("retired_but_installed", "retired-still-installed"),
                           ("orphan_plist_not_declared", "orphan-plist"),
                           ("broken_declared_no_plist", "declared-no-plist")):
                n = len(fp.get(k) or [])
                if n:
                    classes.append(f"{n} {lbl}")
            live = fp.get("live") or {}
            dnr = len(live.get("declared_not_running") or [])
            if dnr:
                classes.append(f"{dnr} declared-not-running")
            issues.append("fleet parity DRIFT (" + ", ".join(classes or ["see fleet_parity.json"]) + ")")
            status = _worst(status, WARNING)

    # --- tournament data-trust (6mo-M2 #16) ---
    # data_trust_monitor watches the tournament trustworthy flags + promotion counter. The expected
    # state today is OK (trustworthy=False, total_promotions=0). An ALERT means either the data-trust
    # claim flipped True or a strategy was promoted on untrusted data — a human-review event, surfaced
    # here as an advisory WARNING so it pages rather than sitting silent in a JSON nobody reads.
    # Advisory (WARNING, not CRITICAL): the tournament is research-only and never gates live allocation.
    # Only assessed when present (sandbox/CI fixtures without the file are not falsely flagged).
    dt = _load_json(data_dir, "data_trust_status.json")
    if dt:
        dt_status = str(dt.get("status")).upper() if dt.get("status") else None
        checks["data_trust_status"] = dt_status
        if dt_status == "ALERT":
            why = "; ".join(dt.get("reasons") or []) or "tournament data-trust ALERT"
            issues.append(f"tournament data-trust ALERT — {why} (human review)")
            status = _worst(status, WARNING)

    # --- capital efficiency (Q1-13, owner-flagged 2026-07-12) ---
    # capital_efficiency guard flags LAZY idle cash — deployable T1/T2 headroom left at 0% beyond the
    # min-cash floor — the class of silent under-earning that previously had NO check anywhere. Advisory
    # WARNING (capital efficiency is not the money-path safety plane; the track/kill checks own
    # criticality). STRUCTURAL cash (caps genuinely exhausted) is verdict OK and never flagged. Only
    # assessed when present so sandbox/CI fixtures without the file are not falsely flagged; the guard's
    # own verdict is fail-CLOSED (idle book + unreadable feed → UNKNOWN → still surfaced).
    ce = _load_json(data_dir, "capital_efficiency.json")
    if ce:
        ce_verdict = str(ce.get("verdict")).upper() if ce.get("verdict") else None
        checks["capital_efficiency"] = ce_verdict
        checks["capital_idle_excess_pct"] = ce.get("idle_excess_pct")
        # Y2 (ADR-055): when the cycle's cash attribution exists, surface it so the
        # verdict is auditable here (EXPLAINED = cash is a logged decision, no issue;
        # LAZY = the UNEXPLAINED remainder specifically, not gross idle).
        if ce.get("attribution_status") is not None:
            checks["capital_cash_attribution"] = ce.get("attribution_status")
            checks["capital_cash_unexplained_pct"] = ce.get("cash_unexplained_pct")
        if ce_verdict == "WARNING":
            fb = ce.get("forgone_yield_bps_est")
            unexpl = ce.get("cash_unexplained_pct")
            if isinstance(unexpl, (int, float)):
                issues.append(
                    "capital-efficiency LAZY: {:.1f}% of capital idle UNEXPLAINED "
                    "after attribution{} (fundable headroom left unused)".format(
                        unexpl, f" — ~{fb}bps/yr forgone" if fb else "",
                    )
                )
            else:
                issues.append(
                    "capital-efficiency LAZY: {:.0f}% deployable capital idle at 0%{} "
                    "(allocator left safe headroom unused)".format(
                        (ce.get("deployable_now_pct") or 0) * 100,
                        f" — ~{fb}bps/yr forgone" if fb else "",
                    )
                )
            status = _worst(status, WARNING)
        elif ce_verdict == "UNKNOWN":
            issues.append("capital-efficiency UNKNOWN (idle book, feed unreadable — fail-closed)")
            status = _worst(status, WARNING)

    # --- застрявший замок дневного цикла (цикл #164) ---
    # Единственный вопрос, на который здесь до сих пор не отвечал НИКТО: замок цикла
    # держит труп? Соседние проверки его не закрывают и не могут: cycle-freshness
    # молчит, пока цикл отработал хоть раз за сутки (08.08 он отработал в 09:52 — и
    # тут же встал на 68 минут отказов), а `last_exit=2` у агента одинаков и для
    # «вежливо отказал, защищая трек», и для «упал». Сторож ничего не чинит: правка
    # самого замка — money-path и ждёт владельца
    # (`owner-decision-zamok-dnevnogo-tsikla-ne-sprashivaet-zhi`).
    # CRITICAL здесь безопасен: потребителей `system_issues` у kill-switch /
    # threat_reactor нет (проверено grep'ом), self_heal читает из этого модуля
    # только общие помощники, а не вердикт — эскалация отчётности, капитал не двигает.
    lock_verdict = check_cycle_lock(data_dir, now)
    checks["cycle_lock_state"] = lock_verdict.state
    checks["cycle_lock_refusals"] = lock_verdict.refusals_since_lock
    if lock_verdict.issue:
        issues.append(lock_verdict.issue)
        status = _worst(status, lock_verdict.severity)

    return checks, status, issues


# ===========================================================================
# Report assembly
# ===========================================================================
def build_report(agents: List[AgentHealth], system_checks: dict,
                 system_status: str, system_issues: List[str],
                 now: datetime) -> dict:
    healthy = sum(1 for a in agents if a.status == OK)
    warning = sum(1 for a in agents if a.status == WARNING)
    # agent-level criticals + system-level critical_flags — maintains invariant:
    # critical_count == 0  ⟺  overall_status != CRITICAL
    critical = (sum(1 for a in agents if a.status == CRITICAL)
                + system_checks.get("critical_flags", 0))

    overall = _worst(system_status, *[a.status for a in agents]) if agents else system_status

    return {
        "timestamp": now.isoformat(),
        # Self-describing freshness contract: consumers (and load_report) judge
        # snapshot age against THIS, so a dead monitor can never keep serving
        # yesterday's "healthy 69/69" as if it were current.
        "cadence_minutes": SNAPSHOT_CADENCE_MIN,
        "stale_after_minutes": SNAPSHOT_STALE_MIN,
        "overall_status": overall,
        "healthy_count": healthy,
        "warning_count": warning,
        "critical_count": critical,
        "total_agents": len(agents),
        "agents": [a.to_dict() for a in agents],
        "system_checks": system_checks,
        "system_issues": system_issues,
    }


# ===========================================================================
# Mass simultaneous failure (WAKE_STORM)
# ===========================================================================
def detect_wake_storm(agents: List[AgentHealth],
                      min_agents: int = WAKE_STORM_MIN_AGENTS) -> Optional[dict]:
    """Detect a mass simultaneous agent failure.

    N (>= ``min_agents``) agents carrying a nonzero last exit at the same time
    is a fleet-level event (host wake storm / broken deploy / stripped exec
    bits), not N independent WARNINGs — per-agent rollup alone under-reports it
    (2026-08-04: 67/69 dead for 5h; 2026-08-05 07:00Z: 39 fell in one minute).

    Only counts agents that are actually flagged (status != OK) with a nonzero
    exit code — an alive KeepAlive server whose previous incarnation was
    SIGTERM'd is not part of a storm. Returns None when below threshold.
    """
    failed = [
        a for a in agents
        if a.status != OK and a.last_exit not in (None, 0)
    ]
    if len(failed) < max(1, int(min_agents)):
        return None
    # Best-effort simultaneity evidence: cluster the freshest-log ages (minutes)
    # of the failed agents into 15-min buckets; the biggest bucket approximates
    # the common failure timestamp.
    buckets: Dict[int, int] = {}
    for a in failed:
        if a.log_age_min is not None:
            buckets[int(a.log_age_min // 15)] = buckets.get(int(a.log_age_min // 15), 0) + 1
    cluster = max(buckets.values()) if buckets else 0
    cluster_age_min = None
    if buckets:
        top = max(buckets.items(), key=lambda kv: kv[1])[0]
        cluster_age_min = top * 15
    exit_codes: Dict[str, int] = {}
    for a in failed:
        k = str(a.last_exit)
        exit_codes[k] = exit_codes.get(k, 0) + 1
    return {
        "count": len(failed),
        "labels": sorted(a.label for a in failed)[:20],
        "exit_codes": exit_codes,
        "clustered_count": cluster,
        "cluster_age_min": cluster_age_min,
    }


# ===========================================================================
# Canonical fail-CLOSED reader for consumers of data/agent_health.json
# ===========================================================================
def load_report(data_dir: Path | str = _DEFAULT_DATA_DIR,
                now: Optional[datetime] = None) -> dict:
    """Load ``agent_health.json`` and annotate its FRESHNESS. Never raises.

    The 2026-08-05 fail-OPEN: 39 agents fell at 07:00Z, the hourly monitor was
    among them, and at 08:43 every consumer kept rendering the 8h-old snapshot's
    "healthy 69/69, critical 0" as if it were current. A snapshot's healthy
    counts are claims about the moment it was WRITTEN — consumers must go
    through this reader (or apply the same rule) so stale health is displayed
    as UNKNOWN, not as health.

    Returns the report dict with three added fields:
      * ``snapshot_age_min``  — minutes since the report's ``timestamp`` (None
        if the timestamp is missing/unparseable);
      * ``snapshot_stale``    — True when the age exceeds the report's own
        ``stale_after_minutes`` contract (default SNAPSHOT_STALE_MIN), or when
        the age cannot be established at all (fail-CLOSED);
      * ``snapshot_reason``   — human-readable staleness reason (only when stale).

    When stale, ``overall_status`` is coerced: a stale OK/WARNING becomes
    ``STALE`` (old good news must not read as current health), and the original
    is preserved in ``raw_overall_status``. A stale CRITICAL stays CRITICAL —
    old bad news never becomes reassurance. A missing/unreadable file returns a
    minimal ``UNCHECKED`` report (fail-CLOSED, never an empty "all fine").
    """
    now = now or _utcnow()
    p = Path(data_dir) / _OUTPUT_FILENAME
    doc: Optional[dict] = None
    try:
        with open(p, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        if isinstance(loaded, dict):
            doc = loaded
    except (OSError, ValueError) as exc:
        log.warning("load_report: %s unreadable: %s", p, exc)
    if doc is None:
        return {
            "overall_status": UNCHECKED,
            "snapshot_age_min": None,
            "snapshot_stale": True,
            "snapshot_reason": f"{_OUTPUT_FILENAME} missing or unreadable",
        }

    ts = _parse_iso(doc.get("timestamp"))
    age_min: Optional[float] = None
    if ts is not None:
        age_min = max(0.0, (now - ts).total_seconds() / 60.0)
    try:
        stale_after = float(doc.get("stale_after_minutes") or SNAPSHOT_STALE_MIN)
    except (TypeError, ValueError):
        stale_after = SNAPSHOT_STALE_MIN

    stale = age_min is None or age_min > stale_after
    doc["snapshot_age_min"] = round(age_min, 1) if age_min is not None else None
    doc["snapshot_stale"] = stale
    if stale:
        doc["snapshot_reason"] = (
            "timestamp missing/unparseable (fail-closed)"
            if age_min is None
            else f"snapshot is {_fmt_age(age_min)} old (contract: {stale_after:.0f}min)"
        )
        if doc.get("overall_status") != CRITICAL:
            doc["raw_overall_status"] = doc.get("overall_status")
            doc["overall_status"] = STALE
    return doc


# ===========================================================================
# Dedup / alert decision
# ===========================================================================
def _issue_keys(report: dict) -> set:
    """Stable set of (label, issue) + system issue strings, for dedup."""
    keys = set()
    for a in report.get("agents", []):
        if a.get("status") != OK and a.get("issue"):
            keys.add(f"{a['label']}::{a['issue']}")
    for s in report.get("system_issues", []):
        keys.add(f"system::{s}")
    return keys


def should_alert(current: dict, previous: Optional[dict]) -> Tuple[bool, List[str]]:
    """Decide whether to send a Telegram alert.

    Alert when:
      * overall status is CRITICAL, OR
      * new issues appeared since the previous run.
    Never alert when everything is OK and nothing is new.
    Returns (send?, new_issue_keys).
    """
    cur_keys = _issue_keys(current)
    prev_keys = _issue_keys(previous or {})
    new_keys = sorted(cur_keys - prev_keys)

    if current.get("overall_status") == CRITICAL:
        return True, new_keys
    if new_keys:
        return True, new_keys
    return False, new_keys


# ===========================================================================
# Telegram alert formatting
# ===========================================================================
def format_alert(report: dict) -> str:
    """HTML Telegram message summarizing problems."""
    overall = report.get("overall_status", OK)
    agents = report.get("agents", [])
    problems = [a for a in agents if a.get("status") != OK]
    sys_issues = report.get("system_issues", [])

    n_issues = len(problems) + len(sys_issues)
    lines = [
        "🚨 <b>SPA Agent Health Alert</b>",
        f"Status: {overall} | {n_issues} issue(s) found",
        "",
    ]
    # agents (critical first)
    for a in sorted(problems, key=lambda x: -_SEVERITY.get(x.get("status"), 0)):
        icon = "❌" if a.get("status") == CRITICAL else "⚠️"
        issue = a.get("issue") or a.get("status")
        lines.append(f"{icon} {a['label']} — {issue}")
    # system issues
    for s in sys_issues:
        # WARN vs CRIT not tracked per-line; use ⚠️ unless mentions stale/critical
        icon = "⚠️"
        lines.append(f"{icon} {s}")

    lines.append("")
    ts = report.get("timestamp", "")
    dt = _parse_iso(ts)
    stamp = dt.strftime("%Y-%m-%d %H:%M UTC") if dt else ts
    lines.append(f"<i>{stamp}</i>")
    return "\n".join(lines)


def _push_via_policy(report: dict) -> bool:
    """Route agent-health CRITICAL through the SINGLE push authority (Tier-1).

    Phase-1 rewire: agent_health no longer pushes directly. It pushes ONLY when
    the overall status is CRITICAL, via ``push_policy.push_critical`` with the
    ``agent_health_critical`` whitelisted key. push_policy is EDGE-TRIGGERED, so
    a *persistent* CRITICAL condition pushes ONCE on entry and is silent while it
    persists — this is the fix for the hourly 17×/day re-fire. WARNING-only
    states no longer push at all (their detail lives in the digest / on-demand
    ``/agents`` view); the monitor keeps WRITING agent_health.json regardless.

    Returns whether a push was actually emitted. Fail-safe (never raises).
    """
    try:
        from spa_core.telegram import push_policy
    except Exception as exc:  # noqa: BLE001
        log.warning("push_policy import failed: %s", exc)
        return False

    overall = report.get("overall_status", OK)
    if overall == CRITICAL:
        return bool(
            push_policy.push_critical(
                "agent_health_critical",
                "CRITICAL",
                "SPA Agent Health — CRITICAL",
                format_alert(report),
            )
        )
    # Not critical anymore → emit the single edge-triggered RESOLVED (no-op if we
    # were never in a bad state).
    return bool(
        push_policy.resolve(
            "agent_health_critical",
            "SPA Agent Health — recovered",
            "All agents healthy again.",
        )
    )


# ===========================================================================
# Orchestration
# ===========================================================================
class AgentHealthMonitor:
    """Heartbeat monitor over all com.spa.* launchd agents + system state."""

    def __init__(self,
                 data_dir: Path = _DEFAULT_DATA_DIR,
                 launch_agents_dir: Path = _DEFAULT_LAUNCH_AGENTS_DIR,
                 launchctl_output: Optional[str] = None,
                 autopush_log: str = _AUTOPUSH_LOG,
                 now: Optional[datetime] = None):
        self.data_dir = Path(data_dir)
        self.launch_agents_dir = Path(launch_agents_dir)
        self._launchctl_output = launchctl_output
        self.autopush_log = autopush_log
        self.now = now or _utcnow()

    # -- inputs --------------------------------------------------------------
    def _launchctl(self) -> Dict[str, dict]:
        text = self._launchctl_output
        if text is None:
            text = _run_launchctl_list()
        return parse_launchctl_list(text)

    # -- core ----------------------------------------------------------------
    def collect(self) -> dict:
        """Build the report (no side effects beyond reading)."""
        launchctl = self._launchctl()
        agents: List[AgentHealth] = []
        for path in discover_plists(self.launch_agents_dir):
            label = label_from_path(path)
            # Retired/superseded agents (e.g. bot_commands → telegram_bot) are not
            # part of the live fleet — skip so they neither false-flag nor count.
            if label in RETIRED_LABELS:
                continue
            plist, parse_ok = _load_plist(path)
            agents.append(check_agent(label, plist, parse_ok, launchctl, self.now))

        sys_checks, sys_status, sys_issues = check_system(
            self.data_dir, self.now, self.autopush_log)

        # WAKE_STORM: a mass simultaneous failure is a fleet-level CRITICAL,
        # even when each individual agent only rates WARNING (last_exit != 0).
        storm = detect_wake_storm(agents)
        if storm:
            sys_checks["wake_storm"] = storm
            codes = ", ".join(
                f"exit {k}×{v}" for k, v in sorted(storm["exit_codes"].items()))
            sys_issues.append(
                f"WAKE_STORM: {storm['count']} agents failed simultaneously "
                f"({codes}) — mass fleet failure, not isolated crashes"
            )
            sys_status = _worst(sys_status, CRITICAL)

        return build_report(agents, sys_checks, sys_status, sys_issues, self.now)

    def _previous(self) -> Optional[dict]:
        p = self.data_dir / _OUTPUT_FILENAME
        if not p.exists():
            return None
        try:
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    def run(self, send: bool = True) -> dict:
        """Full cycle: collect → dedup → (alert) → atomic write. Fail-safe."""
        try:
            # data/agent_registry.json — производитель В РАСПИСАНИИ (находка ADR-066
            # B2:stale, реестр протух на 482ч при SLO 26ч). Скрипт-сборщик существовал
            # и был покрыт тестами, но его не звал никто: отсутствовал не код, а вызов.
            # Место здесь, потому что этот агент уже ходит раз в час ровно в те же
            # источники (launchctl + ~/Library/LaunchAgents), а новый агент — деплой,
            # то есть owner-gated.
            #
            # ДО collect(), а не после, и это не косметика: упади сбор пульса по своей
            # причине — реестр снова начал бы молча гнить, то есть ровно та авария,
            # которую мы здесь и чиним, вернулась бы через чужую поломку.
            # refresh_if_stale НЕ бросает по контракту: пульс флота важнее свежести реестра.
            registry_refresh = refresh_if_stale(self.data_dir, now=self.now)
            previous = self._previous()
            report = self.collect()
            report["registry_refresh"] = registry_refresh
            # should_alert() is retained for observability (new_issues), but the
            # SEND decision is now owned entirely by push_policy's edge-trigger:
            # CRITICAL → one push on entry (silent while it persists), recovery →
            # one RESOLVED. This kills the hourly CRITICAL re-fire at the source.
            _, new_issues = should_alert(report, previous)
            report["alert_sent"] = False
            report["new_issues"] = new_issues
            if send:
                ok = _push_via_policy(report)
                report["alert_sent"] = bool(ok)
            self._write(report)
            return report
        except Exception as exc:  # noqa: BLE001 — never raise out of run()
            log.exception("agent_health_monitor run failed: %s", exc)
            return {
                "timestamp": self.now.isoformat(),
                "overall_status": CRITICAL,
                "error": str(exc),
            }

    def _write(self, report: dict) -> None:
        from spa_core.utils.atomic import atomic_save
        atomic_save(report, str(self.data_dir / _OUTPUT_FILENAME))


# ===========================================================================
# CLI
# ===========================================================================
def _print_summary(report: dict) -> None:
    print(f"Overall: {report.get('overall_status')}  "
          f"(OK={report.get('healthy_count')} "
          f"WARN={report.get('warning_count')} "
          f"CRIT={report.get('critical_count')} "
          f"/ {report.get('total_agents')} agents)")
    for a in report.get("agents", []):
        if a.get("status") != OK:
            print(f"  [{a['status']}] {a['label']} — {a.get('issue')}")
    for s in report.get("system_issues", []):
        print(f"  [SYS] {s}")
    sc = report.get("system_checks", {})
    print(f"  system_checks: {json.dumps(sc)}")
    if report.get("alert_sent"):
        print("  telegram alert: SENT")


def main(argv: Optional[List[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="SPA agent health heartbeat monitor")
    g = parser.add_mutually_exclusive_group()
    g.add_argument("--check", action="store_true",
                   help="compute + write agent_health.json + print, NO telegram")
    g.add_argument("--run", action="store_true",
                   help="compute + write + SEND telegram alert if needed")
    parser.add_argument("--data-dir", default=str(_DEFAULT_DATA_DIR))
    parser.add_argument("--launch-agents-dir", default=str(_DEFAULT_LAUNCH_AGENTS_DIR))
    args = parser.parse_args(argv)

    send = bool(args.run)  # default (no flag) and --check do NOT send
    monitor = AgentHealthMonitor(
        data_dir=Path(args.data_dir),
        launch_agents_dir=Path(args.launch_agents_dir),
    )
    report = monitor.run(send=send)
    _print_summary(report)
    return 0  # always exit 0 (fail-safe daemon)


if __name__ == "__main__":
    sys.exit(main())
