"""spa_core.scheduler.adapter_watchdog — Adapter self-healing watchdog (MP-311).

Monitors adapter health from ``adapter_orchestrator_status.json`` and fires
a restart trigger for unhealthy adapters.

An adapter is considered **unhealthy** if any of:
  * ``status`` field != "ok"
  * ``apy_pct`` is 0 (or missing / None)
  * last successful fetch timestamp is more than 2 hours ago

On detecting an unhealthy adapter the watchdog:
  1. Checks the per-adapter restart count in ``data/watchdog_state.json``
     (rate-limit: max 3 restarts per hour per adapter; resets on UTC-hour tick).
  2. If under the limit: appends a restart record to ``data/watchdog_log.json``
     and sets the ``adapter_restarted`` flag in ``data/orchestrator_trigger.json``
     (consumed by the orchestrator on next cycle).
  3. If rate-limited: logs a WARNING and skips the restart.

No real subprocess is executed — the watchdog only writes trigger files that
the orchestrator layer picks up.  This keeps the watchdog within the
stdlib-only and LLM-FORBIDDEN constraints.

All writes are atomic (tmp + os.replace).  All public functions are fail-safe.

Public API
----------
check_adapter_health(adapter_status: dict) -> list[str]
    Return names of adapters that are currently unhealthy.

attempt_adapter_restart(adapter_name: str, *, data_dir=None) -> dict
    Attempt a logged restart for *adapter_name*.  Returns
    ``{"restarted": bool, "reason": str}``.

run_watchdog_cycle(
    adapter_status_path: str | None = None,
    *,
    data_dir: str | None = None,
) -> dict
    Full watchdog pass: read status, detect unhealthy, attempt restarts.
    Returns a summary dict written atomically to ``data/watchdog_cycle_result.json``.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger("spa.adapter_watchdog")

# ─── Constants ────────────────────────────────────────────────────────────────

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"

WATCHDOG_STATE_FILENAME = "watchdog_state.json"
WATCHDOG_LOG_FILENAME = "watchdog_log.json"
ORCHESTRATOR_TRIGGER_FILENAME = "orchestrator_trigger.json"
WATCHDOG_CYCLE_RESULT_FILENAME = "watchdog_cycle_result.json"
ORCH_STATUS_FILENAME = "adapter_orchestrator_status.json"

MAX_RESTARTS_PER_HOUR = 3
STALE_FETCH_HOURS = 2.0   # adapter is unhealthy if last fetch > 2 h ago
MAX_LOG_ENTRIES = 200     # ring-buffer for watchdog_log.json


# ─── Atomic IO ───────────────────────────────────────────────────────────────


def _atomic_write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, ensure_ascii=False, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        finally:
            raise


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        log.warning("%s unreadable (%s) — using default", path.name, exc)
        return default


def _ddir(data_dir: str | None) -> Path:
    return Path(data_dir) if data_dir is not None else _DEFAULT_DATA_DIR


# ─── Internal helpers ─────────────────────────────────────────────────────────


def _is_stale_fetch(last_fetch_ts: str | None) -> bool:
    """Return True if *last_fetch_ts* is older than STALE_FETCH_HOURS."""
    if not last_fetch_ts:
        return True
    try:
        # Accept both ISO8601 with/without Z suffix.
        ts_str = str(last_fetch_ts).replace("Z", "+00:00")
        ts = datetime.fromisoformat(ts_str)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        delta_hours = (now - ts).total_seconds() / 3600.0
        return delta_hours > STALE_FETCH_HOURS
    except Exception:
        return True  # parse failure → treat as stale


def _current_hour_key() -> str:
    """Return the current UTC hour as a key, e.g. '2026-06-11T08'."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H")


def _get_restart_count(state: dict, adapter_name: str, hour_key: str) -> int:
    """Return the number of restarts for *adapter_name* in *hour_key*."""
    entry = (state.get("adapters") or {}).get(adapter_name, {})
    if not isinstance(entry, dict):
        return 0
    if entry.get("hour_key") != hour_key:
        return 0
    return int(entry.get("count", 0))


def _increment_restart_count(state: dict, adapter_name: str, hour_key: str) -> dict:
    """Increment the restart counter and return the updated state."""
    adapters = dict(state.get("adapters") or {})
    entry = dict(adapters.get(adapter_name) or {})
    if entry.get("hour_key") != hour_key:
        entry = {"hour_key": hour_key, "count": 0}
    entry["count"] = int(entry.get("count", 0)) + 1
    adapters[adapter_name] = entry
    return dict(state, adapters=adapters)


# ─── Public API ───────────────────────────────────────────────────────────────


def check_adapter_health(adapter_status: dict) -> list[str]:
    """Return a list of unhealthy adapter names from *adapter_status*.

    Parameters
    ----------
    adapter_status : dict
        The content of ``adapter_orchestrator_status.json`` or similar
        structure with an ``"adapters"`` list of per-adapter dicts, each
        containing at minimum ``"protocol"``, ``"status"``, ``"apy_pct"``,
        and optionally ``"fetched_at"`` / ``"last_fetch_ts"``.

    Returns
    -------
    list[str]
        Protocol names that are unhealthy.  Empty list → all healthy.
    """
    if not isinstance(adapter_status, dict):
        return []
    adapters = adapter_status.get("adapters") or []
    unhealthy: list[str] = []
    for a in adapters:
        if not isinstance(a, dict):
            continue
        name = str(a.get("protocol") or a.get("name") or "")
        if not name:
            continue

        is_bad = False
        # Criterion 1: status not "ok"
        status = str(a.get("status") or "").lower()
        if status not in ("ok", "partial"):
            is_bad = True

        # Criterion 2: apy_pct == 0 (or None / missing)
        apy = a.get("apy_pct")
        if apy is None or (isinstance(apy, (int, float)) and float(apy) == 0.0):
            is_bad = True

        # Criterion 3: last fetch timestamp is stale (>2h)
        fetch_ts = a.get("fetched_at") or a.get("last_fetch_ts") or a.get("timestamp")
        if _is_stale_fetch(fetch_ts):
            is_bad = True

        if is_bad:
            unhealthy.append(name)

    return unhealthy


def attempt_adapter_restart(
    adapter_name: str,
    *,
    data_dir: str | None = None,
) -> dict:
    """Attempt a rate-limited logged restart for *adapter_name*.

    Returns
    -------
    dict
        ``{"restarted": bool, "reason": str}``
    """
    dd = _ddir(data_dir)
    try:
        hour_key = _current_hour_key()
        state = _read_json(dd / WATCHDOG_STATE_FILENAME, {"adapters": {}})
        if not isinstance(state, dict):
            state = {"adapters": {}}

        count = _get_restart_count(state, adapter_name, hour_key)
        if count >= MAX_RESTARTS_PER_HOUR:
            log.warning(
                "watchdog: adapter %r rate-limited (%d/%d restarts this hour)",
                adapter_name, count, MAX_RESTARTS_PER_HOUR,
            )
            return {
                "restarted": False,
                "reason": f"rate_limited: {count}/{MAX_RESTARTS_PER_HOUR} restarts in hour {hour_key}",
            }

        # Under the limit — record the restart
        ts = datetime.now(timezone.utc).isoformat()

        # 1. Update state (rate-limit counter)
        new_state = _increment_restart_count(state, adapter_name, hour_key)
        _atomic_write_json(dd / WATCHDOG_STATE_FILENAME, new_state)

        # 2. Append to watchdog log (ring-buffer)
        wlog = _read_json(dd / WATCHDOG_LOG_FILENAME, [])
        if not isinstance(wlog, list):
            wlog = []
        wlog.append({
            "ts": ts,
            "adapter": adapter_name,
            "action": "restart_triggered",
            "hour_key": hour_key,
            "restart_count_this_hour": count + 1,
        })
        wlog = wlog[-MAX_LOG_ENTRIES:]
        _atomic_write_json(dd / WATCHDOG_LOG_FILENAME, wlog)

        # 3. Write orchestrator trigger
        trigger = _read_json(dd / ORCHESTRATOR_TRIGGER_FILENAME, {})
        if not isinstance(trigger, dict):
            trigger = {}
        restarted_list = list(trigger.get("adapter_restarted") or [])
        if adapter_name not in restarted_list:
            restarted_list.append(adapter_name)
        trigger["adapter_restarted"] = restarted_list
        trigger["triggered_at"] = ts
        _atomic_write_json(dd / ORCHESTRATOR_TRIGGER_FILENAME, trigger)

        log.info("watchdog: restart triggered for adapter %r (count=%d)", adapter_name, count + 1)
        return {
            "restarted": True,
            "reason": f"restart_triggered: count {count + 1}/{MAX_RESTARTS_PER_HOUR}",
        }

    except Exception as exc:
        log.warning("watchdog attempt_adapter_restart failed (%s)", exc)
        return {"restarted": False, "reason": f"error: {type(exc).__name__}: {exc}"}


def run_watchdog_cycle(
    adapter_status_path: str | None = None,
    *,
    data_dir: str | None = None,
) -> dict:
    """Full watchdog pass: read status → detect unhealthy → attempt restarts.

    Parameters
    ----------
    adapter_status_path : str | None
        Override path to the adapter orchestrator status JSON.  Defaults to
        ``<data_dir>/adapter_orchestrator_status.json``.

    Returns
    -------
    dict
        Summary written to ``data/watchdog_cycle_result.json`` with fields:
        ``ts``, ``status``, ``adapters_checked``, ``adapters_unhealthy``,
        ``restarts_attempted``, ``restarts_succeeded``, ``restarts_rate_limited``.
    """
    try:
        dd = _ddir(data_dir)
        ts = datetime.now(timezone.utc).isoformat()

        status_path = Path(adapter_status_path) if adapter_status_path else dd / ORCH_STATUS_FILENAME
        adapter_status = _read_json(status_path, {})

        adapters_list = (adapter_status.get("adapters") or []) if isinstance(adapter_status, dict) else []
        adapters_checked = len(adapters_list)

        unhealthy = check_adapter_health(adapter_status)
        restarts_attempted = 0
        restarts_succeeded = 0
        restarts_rate_limited = 0
        restart_details: list[dict] = []

        for name in unhealthy:
            result = attempt_adapter_restart(name, data_dir=data_dir)
            restarts_attempted += 1
            if result.get("restarted"):
                restarts_succeeded += 1
            elif "rate_limited" in str(result.get("reason", "")):
                restarts_rate_limited += 1
            restart_details.append({"adapter": name, **result})

        summary = {
            "status": "ok",
            "ts": ts,
            "adapters_checked": adapters_checked,
            "adapters_unhealthy": len(unhealthy),
            "unhealthy_adapters": unhealthy,
            "restarts_attempted": restarts_attempted,
            "restarts_succeeded": restarts_succeeded,
            "restarts_rate_limited": restarts_rate_limited,
            "restart_details": restart_details,
        }
        _atomic_write_json(dd / WATCHDOG_CYCLE_RESULT_FILENAME, summary)
        return summary

    except Exception as exc:
        log.warning("run_watchdog_cycle failed (%s)", exc)
        err_doc = {
            "status": "error",
            "ts": datetime.now(timezone.utc).isoformat(),
            "error": f"{type(exc).__name__}: {exc}",
        }
        try:
            _atomic_write_json(_ddir(data_dir) / WATCHDOG_CYCLE_RESULT_FILENAME, err_doc)
        except Exception:
            pass
        return err_doc
