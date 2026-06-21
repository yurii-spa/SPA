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
_SEVERITY = {OK: 0, WARNING: 1, CRITICAL: 2}


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

# System-check thresholds
EQUITY_STALE_H = 30.0
CYCLE_STALE_H = 26.0
PORTFOLIO_HEALTH_FLOOR = 70.0
AUTOPUSH_LAG_H = 2.0


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
                launchctl: Dict[str, dict], now: datetime) -> AgentHealth:
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
    if not health.loaded:
        health.status = CRITICAL
        health.issue = "not loaded in launchctl"
        return health

    # 2) Malformed plist (loaded but config unparseable) → WARNING
    if not parse_ok:
        issues.append("malformed plist")
        health.status = _worst(health.status, WARNING)

    # 3) Non-zero last exit status
    # Skip this check for always-on servers that are currently running (PID != 0):
    # launchctl retains the previous exit code even after a successful restart, so
    # -15 (SIGTERM from a clean stop) would produce a false CRITICAL while the
    # process is alive.
    _server_alive = cat == CAT_ALWAYS_ON and health.pid != 0
    if health.last_exit not in (None, 0) and not _server_alive:
        issues.append(f"last_exit={health.last_exit}")
        # always-on server: any nonzero exit means crash → CRITICAL.
        if cat == CAT_ALWAYS_ON:
            sev = CRITICAL
        else:
            sev = WARNING
        health.status = _worst(health.status, sev)

    # 4) Always-on servers: must have a live PID
    if cat == CAT_ALWAYS_ON:
        if health.pid == 0:
            issues.append("PID=0 (server down)")
            health.status = _worst(health.status, CRITICAL)
    elif cat in _FRESHNESS_THRESHOLD_MIN:
        # 5) Scheduled agents: log freshness. Judge by the *freshest* of the
        # stdout/stderr logs — modules that log via Python's `logging` write to
        # stderr, leaving StandardOutPath empty/frozen (false "stale" otherwise).
        logps = plist_log_paths(plist)
        age = freshest_log_age_minutes(logps, now)
        health.log_age_min = age
        threshold = _FRESHNESS_THRESHOLD_MIN[cat]
        if not logps:
            # no log configured — can't assess freshness, leave as-is
            pass
        elif age is None:
            issues.append("log missing (never ran?)")
            health.status = _worst(health.status, CRITICAL)
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

    # --- portfolio health score ---
    ph = _load_json(data_dir, "portfolio_health.json")
    if ph:
        score = ph.get("health_score", ph.get("score"))
        if isinstance(score, (int, float)):
            checks["portfolio_health_score"] = round(float(score), 1)
            if score < PORTFOLIO_HEALTH_FLOOR:
                issues.append(f"portfolio_health {score:.1f}/100 (<{PORTFOLIO_HEALTH_FLOOR:.0f})")
                status = _worst(status, WARNING)

    # --- red flags ---
    rf = _load_json(data_dir, "red_flags.json")
    if rf:
        flags = rf.get("red_flags") or rf.get("flags") or []
        crit = sum(1 for f in flags
                   if isinstance(f, dict)
                   and str(f.get("severity", "")).upper() in ("CRITICAL", "CRIT"))
        checks["critical_flags"] = crit
        if crit > 0:
            issues.append(f"{crit} CRITICAL red flag(s)")
            status = _worst(status, CRITICAL)

    # --- autopush lag ---
    age = file_age_minutes(autopush_log, now)
    if age is not None:
        lag_h = age / 60.0
        checks["autopush_lag_h"] = round(lag_h, 2)
        if lag_h > AUTOPUSH_LAG_H:
            issues.append(f"autopush lag {lag_h:.1f}h (>{AUTOPUSH_LAG_H:.0f}h)")
            status = _worst(status, WARNING)

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


def _send_telegram(message: str) -> bool:
    """Send via the shared telegram client (HTML). Fail-safe."""
    try:
        from spa_core.alerts.telegram_client import _post_message
        return _post_message({"text": message, "parse_mode": "HTML"})
    except Exception as exc:  # noqa: BLE001
        log.warning("telegram send failed: %s", exc)
        return False


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
            plist, parse_ok = _load_plist(path)
            agents.append(check_agent(label, plist, parse_ok, launchctl, self.now))

        sys_checks, sys_status, sys_issues = check_system(
            self.data_dir, self.now, self.autopush_log)
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
            previous = self._previous()
            report = self.collect()
            do_send, new_issues = should_alert(report, previous)
            report["alert_sent"] = False
            report["new_issues"] = new_issues
            if send and do_send:
                ok = _send_telegram(format_alert(report))
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
