"""
spa_core/monitoring/watchdog.py — watchdog-over-watchdog guardian (Self-Healing Plane 1.7).

self_heal (com.spa.self_heal, every 5min) revives the OTHER agents, and threat_reactor
(com.spa.threat_reactor, every 5min) auto-activates the kill-switch on CRITICAL threats.
But nothing guarantees those two guardians are themselves alive: if self_heal is dead, the
whole self-healing plane is blind. This tiny INDEPENDENT guardian closes that gap.

Rule (deterministic, stdlib only, LLM FORBIDDEN), for each guardian in GUARDIANS:
  1. NOT loaded in `launchctl list`        → bootstrap its plist (mirrors self_heal revive).
  2. loaded but its data/<x>_status.json `ts` is STALE (> STALE_MINUTES old) or unreadable
     while the agent has been around long enough to have written one → kickstart -k.
  3. Any action (or repeated failure) → Telegram alert via the canonical client,
     FLOOD-GUARDED (no more than one alert per guardian per FLOOD_WINDOW).

Runs every 10 min via com.spa.watchdog — OFFSET from self_heal's 5 min so the two never
fight over the same launchd operation. Fail-safe: a guardian-heal attempt never crashes the
watchdog. Atomic writes (tmp + os.replace) → data/watchdog_status.json.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Dict, List

_ROOT = Path(__file__).resolve().parents[2]
_DATA = _ROOT / "data"
_LA = Path.home() / "Library" / "LaunchAgents"
_STATUS = _DATA / "watchdog_status.json"
_FLOOD_LOG = _DATA / "watchdog_alerts.json"

STALE_MINUTES = 20.0       # a guardian status older than this → it is not running on schedule
SUBPROC_TIMEOUT = 25
FLOOD_WINDOW = 3600.0      # at most one Telegram alert per guardian per hour

# label -> status file each guardian writes its `ts` heartbeat into.
GUARDIANS = {
    "com.spa.self_heal": _DATA / "self_heal_status.json",
    "com.spa.threat_reactor": _DATA / "threat_reactor_status.json",
}


def _uid() -> str:
    return str(os.getuid())


def _run(args: List[str]) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, timeout=SUBPROC_TIMEOUT)


def _loaded_labels() -> Dict[str, int]:
    """label -> pid (0 if loaded but not running) for every loaded com.spa.* job."""
    out: Dict[str, int] = {}
    try:
        r = _run(["launchctl", "list"])
        for line in r.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) >= 3 and parts[2].startswith("com.spa."):
                try:
                    pid = int(parts[0])
                except ValueError:
                    pid = 0
                out[parts[2]] = pid
    except Exception:
        pass
    return out


def _bootstrap(label: str) -> bool:
    """Mirror self_heal's revive: bootstrap the plist into the gui domain if present."""
    plist = _LA / f"{label}.plist"
    if not plist.exists():
        return False
    try:
        r = _run(["launchctl", "bootstrap", f"gui/{_uid()}", str(plist)])
        return r.returncode == 0
    except Exception:
        return False


def _kickstart(label: str) -> bool:
    try:
        r = _run(["launchctl", "kickstart", "-k", f"gui/{_uid()}/{label}"])
        return r.returncode == 0
    except Exception:
        return False


def _status_age_minutes(status_file: Path) -> float | None:
    """Age in minutes of the guardian's status `ts`, or None if absent/unreadable."""
    try:
        d = json.loads(status_file.read_text())
        ts = d.get("ts")
        if not ts:
            return None
        t = datetime.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=datetime.timezone.utc)
        now = datetime.datetime.now(datetime.timezone.utc)
        return (now - t).total_seconds() / 60.0
    except Exception:
        return None


def _send_telegram(msg: str) -> None:
    """Route watchdog escalation through the SINGLE push authority (Tier-1).

    Phase-1 rewire: a core agent down/escalation is a genuine interrupt →
    push_policy ``core_agent_down`` (edge-triggered). Never raises.
    """
    try:
        from spa_core.telegram import push_policy
        push_policy.push_critical(
            "core_agent_down", "CRITICAL", "SPA Watchdog", msg,
        )
    except Exception:  # noqa: BLE001
        pass


def _flood_history() -> dict:
    try:
        d = json.loads(_FLOOD_LOG.read_text())
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save_flood_history(hist: dict) -> None:
    try:
        _DATA.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=_DATA, prefix=".wd_alerts_")
        with os.fdopen(fd, "w") as f:
            json.dump(hist, f)
        os.replace(tmp, _FLOOD_LOG)
    except Exception:
        pass


def _save(report: dict) -> None:
    try:
        _DATA.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=_DATA, prefix=".watchdog_")
        with os.fdopen(fd, "w") as f:
            json.dump(report, f, indent=2)
        os.replace(tmp, _STATUS)
    except Exception:
        pass


def run_watchdog(dry_run: bool = False) -> dict:
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    now_epoch = time.time()
    actions: List[str] = []
    failures: List[str] = []
    guardian_state: Dict[str, dict] = {}
    alerts: List[str] = []  # (label, message) flattened into lines for the flood-guarded send

    loaded = _loaded_labels()
    flood = _flood_history()

    for label, status_file in GUARDIANS.items():
        is_loaded = label in loaded
        age_min = _status_age_minutes(status_file)
        stale = (age_min is None) or (age_min > STALE_MINUTES)

        state = {
            "loaded": is_loaded,
            "status_age_min": round(age_min, 2) if age_min is not None else None,
            "stale": stale,
            "action": None,
        }

        if not is_loaded:
            # Missing entirely → bootstrap (mirror self_heal's revive logic).
            if dry_run:
                state["action"] = "would bootstrap (missing)"
                actions.append(f"would bootstrap {label} (not loaded)")
            elif _bootstrap(label):
                state["action"] = "bootstrap"
                actions.append(f"revived (bootstrap) {label} (was not loaded)")
            else:
                state["action"] = "bootstrap_failed"
                failures.append(f"bootstrap failed {label} (not loaded)")
            alerts.append((label, f"guardian {label} was NOT loaded"))
        elif stale:
            # Loaded but heartbeat is stale / unreadable → kickstart -k.
            why = "no status ts" if age_min is None else f"{age_min:.1f}min old"
            if dry_run:
                state["action"] = "would kickstart (stale)"
                actions.append(f"would kickstart {label} (stale: {why})")
            elif _kickstart(label):
                state["action"] = "kickstart"
                actions.append(f"kickstarted {label} (stale: {why})")
            else:
                state["action"] = "kickstart_failed"
                failures.append(f"kickstart failed {label} (stale: {why})")
            alerts.append((label, f"guardian {label} heartbeat stale ({why})"))

        guardian_state[label] = state

    healthy = not actions and not failures

    report = {
        "ts": now_iso,
        "guardians": guardian_state,
        "actions": actions,
        "failures": failures,
        "healthy": healthy,
        "stale_minutes_threshold": STALE_MINUTES,
        "LLM_FORBIDDEN": True,
    }

    if not dry_run:
        _save(report)
        # Flood-guarded Telegram: only alert for a guardian not alerted within FLOOD_WINDOW.
        send_lines: List[str] = []
        for label, msg in alerts:
            last = flood.get(label, 0)
            if now_epoch - (last if isinstance(last, (int, float)) else 0) >= FLOOD_WINDOW:
                send_lines.append(msg)
                flood[label] = now_epoch
        if send_lines:
            lines = ["🛡️ <b>SPA Watchdog</b> (guardian-of-guardians)"]
            for m in send_lines:
                lines.append(f"⚠️ {m}")
            for a in actions:
                lines.append(f"✅ {a}")
            for f in failures:
                lines.append(f"❌ {f}")
            _send_telegram("\n".join(lines))
        _save_flood_history(flood)

    return report


if __name__ == "__main__":
    import sys
    res = run_watchdog(dry_run="--dry-run" in sys.argv)
    print(json.dumps(res, indent=2, ensure_ascii=False))
    raise SystemExit(0 if not res["failures"] else 1)
