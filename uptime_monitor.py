"""
spa_core/monitoring/uptime_monitor.py
======================================
SPA Uptime Monitor — 24/7 availability checks (MP-211).

Checks:
  1. check_launchd_service(name)    — is launchd job running?
  2. check_http_server(port)        — is local HTTP server responding?
  3. check_cycle_freshness(data_dir) — did paper-trading cycle run recently?
  4. check_git_push(repo_dir)       — was git push done recently?
  5. run_all_checks(data_dir, repo_dir) — run all 4, write data/uptime_status.json

Rules:
  - STDLIB ONLY — no external dependencies
  - READ-ONLY — never writes to state files except data/uptime_status.json
  - FAIL-SAFE — every subprocess / network call catches exceptions, never crashes
  - ATOMIC writes — tmp + os.replace
  - LLM FORBIDDEN in this module

CLI:
  python3 -m spa_core.monitoring.uptime_monitor
  exit 0 on a successful run (even when the monitored system is DEGRADED);
  exit 1 only if the monitor itself failed to run.
  Pass --strict to restore the legacy "exit 1 on DEGRADED" behaviour.

Exit-code policy (why exit 0 on DEGRADED):
  A health monitor must report problems via its OUTPUT (uptime_status.json +
  Telegram alerts), NOT via a non-zero process exit. Under launchd a non-zero
  exit is recorded as LastExitStatus (e.g. exit 1 → 256) and treated as the
  *monitor* having crashed — which made the monitor look broken on every run
  where any agent was degraded, leaving the operator effectively blind. So a
  normal run that successfully writes its status file is exit 0; a real internal
  failure (could not run the checks at all) is exit 1.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

STALE_CYCLE_HOURS: float = 2.0   # cycle is stale if last run > 2 h ago
STALE_PUSH_HOURS: float = 3.0    # git push is stale if last commit > 3 h ago
HTTP_TIMEOUT_SEC: float = 2.0    # HTTP health-check timeout
UPTIME_STATUS_FILE = "uptime_status.json"
UPTIME_PREV_STATE_FILE = "uptime_prev_state.json"  # previous running-state + alert timestamps
ALERT_RATE_LIMIT_SEC: float = 3600.0  # max 1 Telegram alert per agent per hour

# Repo root, used for resolving agent output files (data/...).
# spa_core/monitoring/uptime_monitor.py → repo root is 3 parents up.
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Persistent daemons (plist KeepAlive=true). These SHOULD have a live PID at
# all times; absence of a PID is a genuine failure. Everything else is a
# periodic agent (StartInterval / StartCalendarInterval) that exits between
# runs — for those, "loaded but no live PID" is the NORMAL idle state, not a
# failure, so we judge liveness by the freshness of their output file instead.
KEEPALIVE_SERVICES: set[str] = {
    "com.spa.httpserver",
    "com.spa.cloudflared",
    "com.spa.bot_commands",
}

# Maps each launchd label to (output_file_relative_to_repo, max_age_seconds).
# A periodic agent is considered "alive" if its output file was modified within
# max_age_seconds. max_age is derived from the agent's schedule with generous
# slack (≈ 2–3× the run interval) so a single missed tick doesn't flap.
#   output_file == None  → no file to check (judge by launchctl/port only).
AGENT_OUTPUT_FILES: dict[str, tuple[str | None, int]] = {
    # KeepAlive daemons — no file check needed (judged by PID / HTTP / port).
    "com.spa.httpserver":          (None, 0),
    "com.spa.cloudflared":         (None, 0),
    "com.spa.fund-api":            (None, 0),   # KeepAlive=false run-once helper

    # 5-minute StartInterval monitors → allow up to 30 min of staleness.
    "com.spa.uptime_monitor":      ("data/uptime_status.json", 1800),
    "com.spa.cycle_health":        ("data/cycle_health.json", 1800),
    "com.spa.cycle_gap_monitor":   ("data/cycle_gap_state.json", 1800),
    "com.spa.portfolio_monitor":   ("data/monitor_snapshots.json", 1800),
    "com.spa.peg_monitor":         ("data/peg_report.json", 1800),
    "com.spa.red_flag_monitor":    ("data/red_flags.json", 1800),

    # 15-minute StartInterval → allow 45 min.
    "com.spa.governance_watcher":  ("data/governance_proposals.json", 2700),

    # 30-minute paper-trading cycle → allow 90 min.
    "com.spa.daily_cycle":         ("data/paper_trading_status.json", 5400),

    # 90-minute autopush → allow 4 h.
    "com.spa.autopush":            ("logs/auto_push.log", 14400),

    # Calendar-interval (daily / event-driven) agents → allow ~30 h.
    "com.spa.base_gas_monitor":    ("data/base_gas_history.json", 108000),
    "com.spa.sky_monitor":         ("data/sky_status.json", 108000),
    "com.spa.daily-paper-report":  ("data/paper_trading_status.json", 108000),
    "com.spa.checkpoint-7day":     ("logs/checkpoint_7day.log", 691200),  # weekly → 8 d
    "com.spa.weekly_backup":       (None, 0),   # backup target outside repo
    "com.spa.analytics_tier_c":    ("data/analytics_report_full.json", 129600),  # daily 05:00 → 86400*1.5 = 36h window
    "com.spa.bot_commands":        (None, 0),  # KeepAlive long-poll → judged via launchctl
}

# Port-checked daemons: label → TCP port. Used as a liveness signal for
# KeepAlive daemons that may not surface a PID via launchctl in some domains.
AGENT_PORTS: dict[str, int] = {
    "com.spa.httpserver": 8765,
}


# ---------------------------------------------------------------------------
# 1. Launchd service check
# ---------------------------------------------------------------------------

def check_launchd_service(service_name: str) -> dict[str, Any]:
    """
    Check whether a launchd service is currently running.

    Uses `launchctl list <service_name>` and parses the output.

    Returns:
        {
            "running": bool,
            "pid": int | None,
            "last_exit": int | None,
            "error": str | None,
        }
    """
    result: dict[str, Any] = {
        "running": False,
        "pid": None,
        "last_exit": None,
        "error": None,
    }
    try:
        proc = subprocess.run(
            ["launchctl", "list", service_name],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if proc.returncode != 0:
            # Service not loaded / not found
            result["error"] = f"launchctl exit {proc.returncode}: {proc.stderr.strip()}"
            return result

        # Parse plist-style output: key = value lines
        for line in proc.stdout.splitlines():
            line = line.strip().strip('"').rstrip('"').rstrip(';')
            parts = line.split("=", 1)
            if len(parts) != 2:
                continue
            key = parts[0].strip().strip('"')
            val = parts[1].strip().strip('"').rstrip(';')
            if key == "PID":
                try:
                    pid = int(val)
                    result["pid"] = pid
                    result["running"] = pid > 0
                except ValueError:
                    pass
            elif key == "LastExitStatus":
                try:
                    result["last_exit"] = int(val)
                except ValueError:
                    pass

        # If PID key was absent, service is loaded but not running
        # running stays False if we never set it to True

    except subprocess.TimeoutExpired:
        result["error"] = "launchctl timed out"
    except FileNotFoundError:
        result["error"] = "launchctl not found (non-macOS?)"
    except subprocess.CalledProcessError as exc:
        result["error"] = f"CalledProcessError: {exc}"
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"unexpected: {exc}"

    return result


# ---------------------------------------------------------------------------
# 1b. Output-file freshness fallback (for periodic launchd agents)
# ---------------------------------------------------------------------------

def check_agent_by_output(
    label: str,
    max_age_seconds: int | None = None,
    base_dir: str | Path | None = None,
) -> dict[str, Any]:
    """
    Judge a periodic launchd agent's liveness by the freshness of its output file.

    Periodic agents (StartInterval / StartCalendarInterval) exit between runs,
    so `launchctl list` reports them loaded with no PID — which is NORMAL, not a
    failure. Instead of trusting a live PID, we check whether the file the agent
    is responsible for producing has been touched within ``max_age_seconds``.

    Args:
        label: launchd label, e.g. "com.spa.peg_monitor".
        max_age_seconds: override the default max age from AGENT_OUTPUT_FILES.
        base_dir: repo root override (defaults to BASE_DIR) — used by tests.

    Returns:
        {
            "running": bool | None,   # None when there is no file to check
            "method": str,            # how the verdict was reached
            "file": str | None,
            "age_seconds": int | None,
            "max_age": int | None,
        }
    """
    root = Path(base_dir) if base_dir is not None else BASE_DIR

    mapping = AGENT_OUTPUT_FILES.get(label)
    if mapping is None:
        return {
            "running": None,
            "method": "no_mapping",
            "file": None,
            "age_seconds": None,
            "max_age": None,
        }

    output_file, default_max_age = mapping
    if output_file is None:
        return {
            "running": None,
            "method": "no_output_file",
            "file": None,
            "age_seconds": None,
            "max_age": None,
        }

    max_age = int(max_age_seconds) if max_age_seconds is not None else int(default_max_age)
    path = root / output_file

    try:
        mtime = path.stat().st_mtime
    except FileNotFoundError:
        return {
            "running": False,
            "method": "output_file_missing",
            "file": output_file,
            "age_seconds": None,
            "max_age": max_age,
        }
    except OSError as exc:
        return {
            "running": False,
            "method": f"output_file_stat_error: {exc}",
            "file": output_file,
            "age_seconds": None,
            "max_age": max_age,
        }

    age = time.time() - mtime
    return {
        "running": age <= max_age,
        "method": "output_file_age",
        "file": output_file,
        "age_seconds": int(age),
        "max_age": max_age,
    }


def check_tcp_port(port: int, host: str = "127.0.0.1", timeout: float = 2.0) -> bool:
    """Return True if a TCP connection to host:port succeeds. Fail-safe."""
    import socket
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (OSError, ValueError):
        return False
    except Exception:  # noqa: BLE001
        return False


# ---------------------------------------------------------------------------
# 1c. Combined agent check: launchctl PID + output-file fallback
# ---------------------------------------------------------------------------

def check_agent(label: str, base_dir: str | Path | None = None) -> dict[str, Any]:
    """
    Determine whether a launchd agent is healthy, using the right method for
    its type:

      * KeepAlive daemons (KEEPALIVE_SERVICES): must have a live PID. If launchctl
        cannot confirm a PID, fall back to a TCP port probe (when one is known).
      * Periodic agents: a live PID is a bonus but NOT required — they are healthy
        as long as their output file is fresh. So we try launchctl first; if it
        reports a live PID we accept it, otherwise we fall back to output-file age.

    The returned dict always carries a "running" bool plus diagnostic fields.
    """
    launchd = check_launchd_service(label)

    # --- Persistent daemons: a live PID is required. ---
    if label in KEEPALIVE_SERVICES:
        if launchd.get("running"):
            launchd["method"] = "launchctl_pid"
            return launchd
        # No PID — try a port probe as a secondary signal.
        port = AGENT_PORTS.get(label)
        if port is not None and check_tcp_port(port):
            launchd["running"] = True
            launchd["method"] = "tcp_port"
            launchd["port"] = port
            return launchd
        launchd["method"] = "launchctl_no_pid"
        return launchd

    # --- Periodic agents: a live PID is sufficient but not necessary. ---
    if launchd.get("running"):
        launchd["method"] = "launchctl_pid"
        return launchd

    # No live PID (idle between runs, or launchctl unavailable) → output-file age.
    fallback = check_agent_by_output(label, base_dir=base_dir)
    # Preserve any launchctl diagnostics for visibility.
    fallback["launchctl_pid"] = launchd.get("pid")
    fallback["launchctl_last_exit"] = launchd.get("last_exit")
    fallback["launchctl_error"] = launchd.get("error")
    # If the agent has no output file to judge by, defer to launchctl's verdict.
    if fallback.get("running") is None:
        launchd["method"] = fallback.get("method", "launchctl_no_pid")
        return launchd
    return fallback


# ---------------------------------------------------------------------------
# 2. HTTP server check
# ---------------------------------------------------------------------------

def check_http_server(port: int = 8765) -> dict[str, Any]:
    """
    Check whether the local HTTP server is responding.

    Sends GET http://localhost:{port}/health with a 2 s timeout.

    Returns:
        {
            "ok": bool,
            "status_code": int | None,
            "latency_ms": float | None,
            "error": str | None,
        }
    """
    result: dict[str, Any] = {
        "ok": False,
        "status_code": None,
        "latency_ms": None,
        "error": None,
    }
    url = f"http://localhost:{port}/health"
    t0 = time.monotonic()
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SEC) as resp:
            elapsed_ms = (time.monotonic() - t0) * 1000
            result["status_code"] = resp.status
            result["latency_ms"] = round(elapsed_ms, 2)
            result["ok"] = 200 <= resp.status < 300
    except urllib.error.HTTPError as exc:
        elapsed_ms = (time.monotonic() - t0) * 1000
        result["status_code"] = exc.code
        result["latency_ms"] = round(elapsed_ms, 2)
        result["error"] = f"HTTP {exc.code}: {exc.reason}"
    except urllib.error.URLError as exc:
        result["error"] = f"URLError: {exc.reason}"
    except OSError as exc:
        result["error"] = f"OSError: {exc}"
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"unexpected: {exc}"

    return result


# ---------------------------------------------------------------------------
# 3. Cycle freshness check
# ---------------------------------------------------------------------------

def check_cycle_freshness(data_dir: str | Path) -> dict[str, Any]:
    """
    Check whether the paper-trading cycle ran recently.

    Reads data/paper_trading_status.json and inspects `last_cycle_ts`.
    Cycle is considered stale if last_cycle_ts is older than STALE_CYCLE_HOURS.

    Returns:
        {
            "ok": bool,
            "last_run_ts": float | None,   # unix epoch seconds
            "stale_hours": float | None,   # how many hours since last run
            "error": str | None,
        }
    """
    result: dict[str, Any] = {
        "ok": False,
        "last_run_ts": None,
        "stale_hours": None,
        "error": None,
    }
    status_file = Path(data_dir) / "paper_trading_status.json"
    try:
        raw = status_file.read_text(encoding="utf-8")
        data = json.loads(raw)
    except FileNotFoundError:
        result["error"] = f"file not found: {status_file}"
        return result
    except json.JSONDecodeError as exc:
        result["error"] = f"JSON parse error: {exc}"
        return result
    except OSError as exc:
        result["error"] = f"OSError reading {status_file}: {exc}"
        return result

    # last_cycle_ts may be ISO-8601 string or epoch float
    raw_ts = data.get("last_cycle_ts")
    if raw_ts is None:
        result["error"] = "last_cycle_ts missing from paper_trading_status.json"
        return result

    epoch_ts: float | None = None
    if isinstance(raw_ts, (int, float)):
        epoch_ts = float(raw_ts)
    elif isinstance(raw_ts, str):
        # Parse ISO-8601 with optional timezone
        try:
            from datetime import datetime, timezone as _tz
            # Strip microseconds-and-timezone variants
            ts_clean = raw_ts
            # Try fromisoformat (Python 3.7+; handles +HH:MM in 3.11+)
            try:
                dt = datetime.fromisoformat(ts_clean)
            except ValueError:
                # Fallback: strip trailing timezone manually
                import re
                ts_clean = re.sub(r"[+-]\d{2}:\d{2}$", "+00:00", raw_ts)
                dt = datetime.fromisoformat(ts_clean)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=_tz.utc)
            epoch_ts = dt.timestamp()
        except Exception as exc:  # noqa: BLE001
            result["error"] = f"cannot parse last_cycle_ts '{raw_ts}': {exc}"
            return result
    else:
        result["error"] = f"unexpected last_cycle_ts type: {type(raw_ts)}"
        return result

    now = time.time()
    stale_hours = (now - epoch_ts) / 3600.0
    result["last_run_ts"] = epoch_ts
    result["stale_hours"] = round(stale_hours, 3)
    result["ok"] = stale_hours <= STALE_CYCLE_HOURS

    return result


# ---------------------------------------------------------------------------
# 4. Git push freshness check
# ---------------------------------------------------------------------------

def check_git_push(repo_dir: str | Path) -> dict[str, Any]:
    """
    Check how recently the last git commit was made.

    Runs `git -C <repo_dir> log -1 --format=%ct` to get the unix timestamp
    of the most recent commit. Stale if > STALE_PUSH_HOURS.

    Returns:
        {
            "ok": bool,
            "last_push_ts": float | None,   # unix epoch seconds
            "stale_hours": float | None,
            "error": str | None,
        }
    """
    result: dict[str, Any] = {
        "ok": False,
        "last_push_ts": None,
        "stale_hours": None,
        "error": None,
    }
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_dir), "log", "-1", "--format=%ct"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if proc.returncode != 0:
            result["error"] = f"git log exit {proc.returncode}: {proc.stderr.strip()}"
            return result

        raw = proc.stdout.strip()
        if not raw:
            result["error"] = "git log returned empty output (no commits?)"
            return result

        epoch_ts = float(raw)
        now = time.time()
        stale_hours = (now - epoch_ts) / 3600.0
        result["last_push_ts"] = epoch_ts
        result["stale_hours"] = round(stale_hours, 3)
        result["ok"] = stale_hours <= STALE_PUSH_HOURS

    except subprocess.TimeoutExpired:
        result["error"] = "git log timed out"
    except FileNotFoundError:
        result["error"] = "git executable not found"
    except ValueError as exc:
        result["error"] = f"cannot parse git timestamp: {exc}"
    except subprocess.CalledProcessError as exc:
        result["error"] = f"CalledProcessError: {exc}"
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"unexpected: {exc}"

    return result


# ---------------------------------------------------------------------------
# 4b. Telegram down-alert on running→not-running transition
# ---------------------------------------------------------------------------

def _load_prev_state(data_dir: Path) -> dict[str, Any]:
    """
    Load previous-run agent state from data/uptime_prev_state.json.

    Structure:
        {
            "agents": {"com.spa.X": {"running": bool}, ...},
            "alerts": {"com.spa.X": <unix_epoch_of_last_alert>, ...}
        }

    Fail-safe: missing / corrupt file → empty structure.
    """
    path = data_dir / UPTIME_PREV_STATE_FILE
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {"agents": {}, "alerts": {}}
    if not isinstance(data, dict):
        return {"agents": {}, "alerts": {}}
    data.setdefault("agents", {})
    data.setdefault("alerts", {})
    if not isinstance(data["agents"], dict):
        data["agents"] = {}
    if not isinstance(data["alerts"], dict):
        data["alerts"] = {}
    return data


def _write_prev_state(data_dir: Path, state: dict[str, Any]) -> None:
    """Atomically write the previous-state file (tmp + os.replace). Fail-safe."""
    out_file = data_dir / UPTIME_PREV_STATE_FILE
    tmp_file = data_dir / (UPTIME_PREV_STATE_FILE + ".tmp")
    try:
        tmp_file.write_text(
            json.dumps(state, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        os.replace(str(tmp_file), str(out_file))
    except OSError as exc:
        print(
            f"[uptime_monitor] WARNING: could not write {out_file}: {exc}",
            file=sys.stderr,
        )
        try:
            tmp_file.unlink(missing_ok=True)
        except OSError:
            pass


def _send_agent_alert(label: str, age_minutes: int, file_hint: str | None) -> bool:
    """
    Send a Telegram alert that a launchd agent has gone down.

    Uses the shared Keychain-backed helper spa_core.alerts.telegram_client.
    Fail-safe: any failure (import error, missing credentials, network) →
    returns False, never raises.

    Returns True only if the message was accepted by the Telegram API.
    """
    file_line = f"\nФайл: {file_hint}" if file_hint else ""
    text = (
        f"⚠️ SPA Agent DOWN: {label}\n"
        f"Остановлен {age_minutes} минут назад{file_line}"
    )
    try:
        from spa_core.alerts.telegram_client import send_message
        return bool(send_message(text))
    except Exception as exc:  # noqa: BLE001 — alerts must never crash the monitor
        print(
            f"[uptime_monitor] WARNING: Telegram alert failed for {label}: {exc}",
            file=sys.stderr,
        )
        return False


def _process_agent_alerts(
    data_dir: Path,
    checks: dict[str, Any],
    now: float | None = None,
) -> dict[str, Any]:
    """
    Compare current launchd-agent running-state against the previous run and
    fire a Telegram alert for each agent that transitioned running→down.

    Rules:
      * Alert only on a True→False transition (was running, now not).
      * Rate-limit: at most one alert per agent per ALERT_RATE_LIMIT_SEC (1h),
        tracked via the "alerts" map in uptime_prev_state.json.
      * No alert if the agent is still running or was already down.
      * Always persists the fresh running-state (+ alert timestamps) so the
        next run can detect transitions.

    Returns the new state dict that was written (useful for tests).
    """
    now = time.time() if now is None else now
    prev = _load_prev_state(data_dir)
    prev_agents: dict[str, Any] = prev.get("agents", {})
    alert_ts: dict[str, Any] = dict(prev.get("alerts", {}))

    new_agents: dict[str, Any] = {}
    for key, chk in checks.items():
        if not key.startswith("launchd_") or not isinstance(chk, dict):
            continue
        label = "com.spa." + key[len("launchd_"):]
        running = bool(chk.get("running", False))
        new_agents[label] = {"running": running}

        was_running = bool(prev_agents.get(label, {}).get("running", False))
        if was_running and not running:
            # running → down transition. Apply rate-limit.
            last_alert = alert_ts.get(label)
            within_limit = (
                isinstance(last_alert, (int, float))
                and (now - float(last_alert)) < ALERT_RATE_LIMIT_SEC
            )
            if not within_limit:
                age_seconds = chk.get("age_seconds")
                if isinstance(age_seconds, (int, float)):
                    age_minutes = int(age_seconds // 60)
                else:
                    age_minutes = 0
                file_hint = chk.get("file")
                if _send_agent_alert(label, age_minutes, file_hint):
                    alert_ts[label] = now

    new_state = {"agents": new_agents, "alerts": alert_ts}
    _write_prev_state(data_dir, new_state)
    return new_state


# ---------------------------------------------------------------------------
# 5. Run all checks + write uptime_status.json
# ---------------------------------------------------------------------------

LAUNCHD_SERVICES = [
    "com.spa.httpserver",
    "com.spa.cloudflared",
    "com.spa.fund-api",
    "com.spa.uptime_monitor",
    "com.spa.cycle_health",
    "com.spa.cycle_gap_monitor",
    "com.spa.portfolio_monitor",
    "com.spa.peg_monitor",
    "com.spa.red_flag_monitor",
    "com.spa.governance_watcher",
    "com.spa.autopush",
    "com.spa.daily_cycle",
    "com.spa.base_gas_monitor",
    "com.spa.sky_monitor",
    "com.spa.daily-paper-report",
    "com.spa.checkpoint-7day",
    "com.spa.weekly_backup",
    "com.spa.analytics_tier_c",  # daily 05:00 → data/analytics_report_full.json (36h window)
    "com.spa.bot_commands",      # KeepAlive long-poll daemon (no output file; launchctl liveness)
]


def run_all_checks(
    data_dir: str | Path,
    repo_dir: str | Path,
) -> dict[str, Any]:
    """
    Run all 4 uptime checks, write data/uptime_status.json atomically,
    and return the combined result.

    Returns:
        {
            "all_ok": bool,
            "ts": float,           # unix epoch seconds of this check
            "checks": {
                "launchd_autopush":   {...},
                "launchd_httpserver": {...},
                "http_server":        {...},
                "cycle_freshness":    {...},
                "git_push":           {...},
            }
        }
    """
    data_dir = Path(data_dir)
    ts_now = time.time()

    checks: dict[str, Any] = {}

    # 1. Launchd services — use the type-aware check_agent(), which judges
    #    KeepAlive daemons by live PID/port and periodic agents by output-file
    #    freshness (idle-between-runs is NOT a failure for periodic agents).
    repo_root = Path(repo_dir)
    for svc in LAUNCHD_SERVICES:
        key = "launchd_" + svc.replace(".", "_").replace("com_spa_", "")
        checks[key] = check_agent(svc, base_dir=repo_root)

    # 2. HTTP server
    checks["http_server"] = check_http_server(port=8765)

    # 3. Cycle freshness
    checks["cycle_freshness"] = check_cycle_freshness(data_dir)

    # 4. Git push
    checks["git_push"] = check_git_push(repo_dir)

    # Determine all_ok
    ok_flags: list[bool] = []
    for key, chk in checks.items():
        if key.startswith("launchd_"):
            ok_flags.append(chk.get("running", False))
        else:
            ok_flags.append(chk.get("ok", False))

    all_ok = all(ok_flags)

    result: dict[str, Any] = {
        "all_ok": all_ok,
        "ts": ts_now,
        "checks": checks,
    }

    # Atomic write to data/uptime_status.json
    out_file = data_dir / UPTIME_STATUS_FILE
    tmp_file = data_dir / (UPTIME_STATUS_FILE + ".tmp")
    try:
        tmp_file.write_text(
            json.dumps(result, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        os.replace(str(tmp_file), str(out_file))
    except OSError as exc:
        # Non-fatal: log to stderr, do not crash
        print(f"[uptime_monitor] WARNING: could not write {out_file}: {exc}", file=sys.stderr)
    finally:
        # Clean up tmp if it still exists (write or replace failed)
        try:
            tmp_file.unlink(missing_ok=True)
        except OSError:
            pass

    # Telegram down-alerts on running→down transitions (fail-safe, rate-limited).
    # Also persists the fresh running-state to data/uptime_prev_state.json.
    try:
        _process_agent_alerts(data_dir, checks, now=ts_now)
    except Exception as exc:  # noqa: BLE001 — alerting must never break the monitor
        print(
            f"[uptime_monitor] WARNING: agent-alert processing failed: {exc}",
            file=sys.stderr,
        )

    return result


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _format_check(name: str, chk: dict[str, Any]) -> str:
    """Format a single check result for human-readable output."""
    if name.startswith("launchd_"):
        ok = chk.get("running", False)
        status = "OK" if ok else "FAIL"
        method = chk.get("method", "")
        pid = chk.get("pid")
        if method == "output_file_age":
            age = chk.get("age_seconds")
            mx = chk.get("max_age")
            age_min = f"{age // 60}m" if isinstance(age, int) else "?"
            mx_min = f"{mx // 60}m" if isinstance(mx, int) else "?"
            detail = f"file-age={age_min}/{mx_min}"
        elif method == "tcp_port":
            detail = f"port={chk.get('port')}"
        elif pid:
            detail = f"pid={pid}"
        elif method == "output_file_missing":
            detail = f"output missing: {chk.get('file')}"
        else:
            detail = chk.get("error") or method or "not running"
    else:
        ok = chk.get("ok", False)
        status = "OK" if ok else "FAIL"
        parts = []
        if "latency_ms" in chk and chk["latency_ms"] is not None:
            parts.append(f"{chk['latency_ms']:.1f}ms")
        if "stale_hours" in chk and chk["stale_hours"] is not None:
            parts.append(f"age={chk['stale_hours']:.2f}h")
        if chk.get("error"):
            parts.append(chk["error"])
        detail = ", ".join(parts) if parts else ""

    return f"  [{status:4s}] {name:<30s} {detail}"


def main(argv: list[str] | None = None) -> int:
    """
    CLI: run all checks, print results, return an exit code.

    Exit-code policy (see module docstring):
      * Default: a run that completes and writes its status file → 0, EVEN when
        the monitored system is DEGRADED. A genuine internal failure (the checks
        could not be run at all) → 1.
      * --strict: legacy behaviour — return 1 whenever the system is DEGRADED.

    Returns the integer exit code (does not call sys.exit so it is testable).
    """
    args = sys.argv[1:] if argv is None else argv
    strict = "--strict" in args

    # Determine paths relative to this file's location
    here = Path(__file__).resolve()
    repo_dir = here.parent.parent.parent  # spa_core/monitoring/uptime_monitor.py → repo root
    data_dir = repo_dir / "data"

    try:
        result = run_all_checks(data_dir=data_dir, repo_dir=repo_dir)
    except Exception as exc:  # noqa: BLE001 — only a real internal failure reaches here
        print(f"[uptime_monitor] FATAL: run_all_checks failed: {exc}", file=sys.stderr)
        return 1

    ts_str = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(result["ts"]))
    overall = "ALL OK ✓" if result["all_ok"] else "DEGRADED ✗"
    print(f"\nSPA Uptime Monitor — {ts_str}")
    print(f"Status: {overall}\n")
    for name, chk in result["checks"].items():
        print(_format_check(name, chk))
    print()

    if strict:
        return 0 if result["all_ok"] else 1
    # Default: the monitor ran successfully. DEGRADED is reported via the status
    # file + alerts, NOT via the process exit code.
    return 0


if __name__ == "__main__":
    sys.exit(main())
