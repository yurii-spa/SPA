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

HONESTY (class #29/#31/#35–#38/#40 — never publish a verdict about a check that did not run):
  * `launchctl list` that could not be MEASURED (exception / non-zero / unparseable output)
    is NOT read as "the guardian is not loaded". Such a guardian is reported `unchecked`,
    no launchd action is taken against an unmeasured launchd, and the run is not `healthy`.
  * The Telegram escalation records what actually happened to it. ``push_critical`` is
    documented as returning ``sent?`` and the return value used to be discarded, so a refused
    push (``core_agent_down`` is edge-triggered — a persistent bad state returns False and is
    dropped without even reaching the digest) was booked as "the owner was warned" and the
    flood window was spent on it. Delivery is now tri-state: delivered / refused-by-policy /
    NOT MEASURED, and a push that was never attempted does not spend the flood window.
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

#: Контракт агента (ADR-154/158): что этот агент ПРОИЗВОДИТ.
#: Объявление, а не вывод из кода. Источник — запись, видимая в этом модуле,
#: и/или прямое утверждение автора в докстринге/константах модуля.
#: Сверка — spa_core/monitoring/artifact_contract.py.
PRODUCES = (
    "data/watchdog_alerts.json",
    "data/watchdog_status.json",
)

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


def _loaded_labels() -> Dict[str, int] | None:
    """label -> pid (0 if loaded but not running) for every loaded com.spa.* job.

    Returns ``None`` when launchd could not be MEASURED at all — the call raised, exited
    non-zero, or produced output this parser does not recognise. ``None`` is not ``{}``:
    an empty mapping means "measured, nothing of ours is loaded", while ``None`` means
    "we do not know", and the caller must not turn "do not know" into "not loaded".
    """
    try:
        r = _run(["launchctl", "list"])
    except Exception:
        return None
    if r.returncode != 0:
        return None
    out: Dict[str, int] = {}
    parsed_any = False
    for line in r.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        parsed_any = True
        if parts[2].startswith("com.spa."):
            try:
                pid = int(parts[0])
            except ValueError:
                pid = 0
            out[parts[2]] = pid
    if not parsed_any:
        # Output we could not parse into a single row is not evidence of an empty launchd.
        return None
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


def _send_telegram(msg: str, dedup_key: str | None = None) -> bool | None:
    """Route watchdog escalation through the SINGLE push authority (Tier-1).

    Phase-1 rewire: a core agent down/escalation is a genuine interrupt →
    push_policy ``core_agent_down`` (edge-triggered). Never raises.

    ``dedup_key`` — stable fingerprint of the concrete incident (sorted guardian
    labels being escalated). The ``core_agent_down`` class is shared with
    self_heal/uptime_monitor and nothing ever resolves it, so without a
    fingerprint the FIRST incident left the class ``bad`` and every later,
    DIFFERENT guardian incident was refused (2026-08-05: alerts_undelivered
    [self_heal, threat_reactor], refused_by_push_policy). The same guardian
    persisting broken keeps the same fingerprint and stays deduped.

    Tri-state, because "we tried" is not "the owner was told":
      * ``True``  — the push authority reports the message was sent;
      * ``False`` — the push authority REFUSED it (measured): the edge-trigger is still in
        ``bad``, the daily ceiling is spent, … The owner did not get it either way, but we
        know that on purpose rather than by accident;
      * ``None``  — NOT MEASURED: the authority could not even be reached (import/transport
        blew up), or it answered something that is not a bool. Never reported as delivered.
    """
    try:
        from spa_core.telegram import push_policy
    except Exception:  # noqa: BLE001 — a broken import must not crash the guardian
        return None
    try:
        result = push_policy.push_critical(
            "core_agent_down", "CRITICAL", "SPA Watchdog", msg,
            dedup_key=dedup_key,
        )
    except Exception:  # noqa: BLE001 — documented as never raising; do not trust that blindly
        return None
    if isinstance(result, bool):
        return result
    return None


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
    unchecked: List[str] = []
    guardian_state: Dict[str, dict] = {}
    alerts: List[tuple] = []  # (label, message) flattened into lines for the flood-guarded send

    loaded = _loaded_labels()
    flood = _flood_history()

    for label, status_file in GUARDIANS.items():
        age_min = _status_age_minutes(status_file)
        stale = (age_min is None) or (age_min > STALE_MINUTES)

        if loaded is None:
            # launchd itself is unmeasured. "Not loaded" would be a claim we cannot make, and
            # every remedy here is a launchctl operation against that same unmeasured launchd.
            # Say so, act on nothing, and do not let the run call itself healthy.
            guardian_state[label] = {
                "loaded": None,
                "status_age_min": round(age_min, 2) if age_min is not None else None,
                "stale": stale,
                "action": None,
                "alert": None,
                "unchecked": "launchctl list не измерен — загруженность стража неизвестна",
            }
            unchecked.append(label)
            continue

        is_loaded = label in loaded

        state: Dict[str, object] = {
            "loaded": is_loaded,
            "status_age_min": round(age_min, 2) if age_min is not None else None,
            "stale": stale,
            "action": None,
            "alert": None,
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

    # A run that could not measure a guardian has not established that the plane is healthy.
    healthy = not actions and not failures and not unchecked

    attempted: List[str] = []
    delivered: List[str] = []
    undelivered: List[str] = []
    delivery_unmeasured: List[str] = []

    if not dry_run:
        # Flood-guarded Telegram: only alert for a guardian not alerted within FLOOD_WINDOW.
        send_lines: List[str] = []
        send_labels: List[str] = []
        for label, msg in alerts:
            last = flood.get(label, 0)
            if isinstance(last, bool) or not isinstance(last, (int, float)):
                last = 0
            if now_epoch - last >= FLOOD_WINDOW:
                send_lines.append(msg)
                send_labels.append(label)
            else:
                guardian_state[label]["alert"] = "flood_suppressed"
        if send_lines:
            lines = ["🛡️ <b>SPA Watchdog</b> (guardian-of-guardians)"]
            for m in send_lines:
                lines.append(f"⚠️ {m}")
            for a in actions:
                lines.append(f"✅ {a}")
            for f in failures:
                lines.append(f"❌ {f}")

            attempted = list(send_labels)
            outcome = _send_telegram(
                "\n".join(lines),
                dedup_key="watchdog:" + "|".join(sorted(set(send_labels))),
            )

            if outcome is True:
                delivered = list(send_labels)
                verdict = "delivered"
            elif outcome is False:
                # Measured refusal by the push authority (edge-trigger still `bad`, daily
                # ceiling spent, …). The owner did NOT get it — say so instead of booking it
                # as a warning that was given. The flood window is still spent on purpose:
                # some refusal paths (ceiling_exceeded) queue into the digest, so retrying
                # every 10 min would trade a silent lie for a noisy one. Making the guardian
                # audibly reachable again is an alert-policy decision → owner card.
                undelivered = list(send_labels)
                verdict = "refused_by_push_policy"
            else:
                # Never even reached the push authority ⇒ nothing was attempted downstream,
                # so recording "warned" would be a pure fabrication and retrying costs the
                # owner nothing. Do not spend the flood window.
                delivery_unmeasured = list(send_labels)
                verdict = "not_measured"

            for label in send_labels:
                guardian_state[label]["alert"] = verdict
            if outcome is not None:
                for label in send_labels:
                    flood[label] = now_epoch

        _save_flood_history(flood)

    report = {
        "ts": now_iso,
        "guardians": guardian_state,
        "actions": actions,
        "failures": failures,
        "unchecked": unchecked,
        "healthy": healthy,
        "alerts_attempted": attempted,
        "alerts_delivered": delivered,
        "alerts_undelivered": undelivered,
        "alerts_delivery_unmeasured": delivery_unmeasured,
        "stale_minutes_threshold": STALE_MINUTES,
        "LLM_FORBIDDEN": True,
    }

    if not dry_run:
        _save(report)

    return report


if __name__ == "__main__":
    import sys
    res = run_watchdog(dry_run="--dry-run" in sys.argv)
    print(json.dumps(res, indent=2, ensure_ascii=False))
    raise SystemExit(0 if not res["failures"] else 1)
