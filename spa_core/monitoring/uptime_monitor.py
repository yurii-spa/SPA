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
  exit 0 if all_ok, exit 1 otherwise
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

    # 1. Launchd services
    for svc in LAUNCHD_SERVICES:
        key = "launchd_" + svc.replace(".", "_").replace("com_spa_", "")
        checks[key] = check_launchd_service(svc)

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

    return result


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _format_check(name: str, chk: dict[str, Any]) -> str:
    """Format a single check result for human-readable output."""
    if name.startswith("launchd_"):
        ok = chk.get("running", False)
        status = "OK" if ok else "FAIL"
        pid = chk.get("pid")
        err = chk.get("error", "")
        detail = f"pid={pid}" if pid else (err or "not running")
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


def main() -> None:
    """CLI: run all checks, print results, exit 0/1."""
    # Determine paths relative to this file's location
    here = Path(__file__).resolve()
    repo_dir = here.parent.parent.parent  # spa_core/monitoring/uptime_monitor.py → repo root
    data_dir = repo_dir / "data"

    result = run_all_checks(data_dir=data_dir, repo_dir=repo_dir)

    ts_str = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(result["ts"]))
    overall = "ALL OK ✓" if result["all_ok"] else "DEGRADED ✗"
    print(f"\nSPA Uptime Monitor — {ts_str}")
    print(f"Status: {overall}\n")
    for name, chk in result["checks"].items():
        print(_format_check(name, chk))
    print()

    sys.exit(0 if result["all_ok"] else 1)


if __name__ == "__main__":
    main()
