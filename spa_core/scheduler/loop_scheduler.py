"""spa_core.scheduler.loop_scheduler — 3-loop scheduler (MP-311).

Three control loops at different cadences and LLM requirements:

FAST_LOOP (every paper-trading cycle, deterministic — NO LLM)
-------------------------------------------------------------
``run_fast_loop(cycle_result: dict, *, data_dir=None) -> dict``

  Runs after every paper-trading cycle.  Checks:
    * gap_monitor.json for track continuity
    * Kill-switch state (kill_switch_active in cycle result)
    * Risk alerts (policy violations / kill_switch)

  If the cycle's risk_verdict is "approved" (policy_approved=True and
  kill_switch_active=False), persists the effective allocation as
  ``data/last_approved_allocation.json``.

  Output: ``data/fast_loop_status.json`` (written atomically).


SLOW_LOOP (daily, LLM-advisory)
--------------------------------
``run_slow_loop(date: str, *, llm_available: bool = False, data_dir=None) -> dict``

  Runs once per UTC day.  Reads analytics_summary.json, shadow_portfolio.json,
  adapter_orchestrator_status.json.

  When ``llm_available=True``: stub returns a structured insights dict (the real
  LLM call is injected by the calling layer; the LLM SDK is NOT imported here —
  LLM_FORBIDDEN protection).

  When ``llm_available=False``: copies the previous
  ``data/slow_loop_insights.json`` content, or emits
  ``{"status": "degraded", "insights": [], "reason": "llm_unavailable"}``.

  Output: ``data/slow_loop_insights.json`` (written atomically).


STRATEGIC_LOOP (weekly — every Monday)
----------------------------------------
``run_strategic_loop(week_start: str, *, llm_available: bool = False, data_dir=None) -> dict``

  Runs once per Monday.  Reads equity_curve_daily.json (last 30 days),
  ceo_decisions.json, alpha_candidates.json.

  When ``llm_available=False``: emits
  ``{"status": "skipped", "reason": "llm_unavailable", "week_start": week_start}``.

  Output: ``data/strategic_loop_notes.json`` (written atomically).


Degradation contract
--------------------
* fast_loop ALWAYS runs — fully deterministic, no network, no LLM.
* slow_loop degrades to a cached/degraded status doc when LLM unavailable.
* strategic_loop is skipped (writes a skip record) when LLM unavailable.
* All functions are fail-safe: any unexpected exception is caught, logged as
  WARNING, and returned as ``{"status": "error", "error": str(exc)}``.
  The caller (cycle_runner) is never blocked.

All writes: atomic (tmp + os.replace).  No *.tmp files left on success.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger("spa.loop_scheduler")

# ─── Paths / filenames ────────────────────────────────────────────────────────

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"

FAST_LOOP_STATUS_FILENAME = "fast_loop_status.json"
SLOW_LOOP_INSIGHTS_FILENAME = "slow_loop_insights.json"
STRATEGIC_LOOP_NOTES_FILENAME = "strategic_loop_notes.json"
LAST_APPROVED_ALLOC_FILENAME = "last_approved_allocation.json"


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


# ─── FAST LOOP ────────────────────────────────────────────────────────────────


def run_fast_loop(
    cycle_result: dict,
    *,
    data_dir: str | None = None,
) -> dict:
    """Execute the fast (every-cycle) deterministic loop.

    Parameters
    ----------
    cycle_result : dict
        The ``CycleResult.to_dict()`` output from the current cycle.

    Returns
    -------
    dict
        Fast-loop status document written to ``data/fast_loop_status.json``.
        Keys: ``status``, ``ts``, ``gap_detected``, ``kill_switch_active``,
        ``policy_approved``, ``last_approved_config_updated``, ``alerts``.
    """
    try:
        dd = _ddir(data_dir)
        ts = datetime.now(timezone.utc).isoformat()

        # --- gap_monitor check -----------------------------------------------
        gm = _read_json(dd / "gap_monitor.json", {})
        gap_detected: bool = bool(gm.get("gap_detected", False)) if isinstance(gm, dict) else False

        # --- kill-switch check -----------------------------------------------
        ks_active: bool = bool(cycle_result.get("kill_switch_active", False))
        ks_reason: str = str(cycle_result.get("kill_switch_reason") or "")

        # --- policy verdict --------------------------------------------------
        policy_approved: bool = bool(cycle_result.get("policy_approved", True))
        policy_violations: list = list(cycle_result.get("policy_violations") or [])

        # --- build alert list ------------------------------------------------
        alerts: list[str] = []
        if gap_detected:
            hours = float(gm.get("hours_since_last_entry", 0.0) if isinstance(gm, dict) else 0.0)
            alerts.append(f"gap_detected: {hours:.1f}h since last entry")
        if ks_active:
            alerts.append(f"kill_switch_active: {ks_reason}")
        if not policy_approved:
            for v in policy_violations:
                alerts.append(f"policy_violation: {v}")

        # --- persist last_approved_allocation if this cycle was clean --------
        config_updated = False
        is_approved_cycle = policy_approved and not ks_active
        if is_approved_cycle:
            positions = dict(cycle_result.get("positions") or {})
            approved_config = {
                "generated_at": ts,
                "cycle_date": cycle_result.get("date", ""),
                "positions": positions,
                "apy_today_pct": cycle_result.get("apy_today_pct", 0.0),
                "model_used": cycle_result.get("model_used"),
                "equity": cycle_result.get("current_equity", 0.0),
            }
            _atomic_write_json(dd / LAST_APPROVED_ALLOC_FILENAME, approved_config)
            config_updated = True

        # --- build status document -------------------------------------------
        status_doc = {
            "status": "ok",
            "ts": ts,
            "cycle_date": cycle_result.get("date", ""),
            "gap_detected": gap_detected,
            "kill_switch_active": ks_active,
            "kill_switch_reason": ks_reason,
            "policy_approved": policy_approved,
            "policy_violations": policy_violations,
            "last_approved_config_updated": config_updated,
            "alerts": alerts,
            "alert_count": len(alerts),
        }
        _atomic_write_json(dd / FAST_LOOP_STATUS_FILENAME, status_doc)
        return status_doc

    except Exception as exc:
        log.warning("fast_loop failed (%s) — cycle continues", exc)
        return {"status": "error", "error": f"{type(exc).__name__}: {exc}"}


# ─── SLOW LOOP ────────────────────────────────────────────────────────────────


def run_slow_loop(
    date: str,
    *,
    llm_available: bool = False,
    data_dir: str | None = None,
) -> dict:
    """Execute the daily slow loop.

    When ``llm_available=False`` (default), degrades to the previous insight
    snapshot or emits a minimal degraded status record.  The LLM SDK is NEVER
    imported here (LLM_FORBIDDEN protection applies to spa_core modules).

    Parameters
    ----------
    date : str
        ISO date string for today (``"2026-06-11"``).
    llm_available : bool
        Injected by the caller after it has verified LLM reachability.
        Defaults to ``False`` (safe / degraded mode).

    Returns
    -------
    dict
        Insights document written to ``data/slow_loop_insights.json``.
    """
    try:
        dd = _ddir(data_dir)
        ts = datetime.now(timezone.utc).isoformat()

        # Gather inputs (all fail-safe reads)
        analytics = _read_json(dd / "analytics_summary.json", {})
        shadow = _read_json(dd / "shadow_portfolio.json", {})
        orch_status = _read_json(dd / "adapter_orchestrator_status.json", {})

        if not llm_available:
            # Degraded path: reuse previous insights or emit minimal placeholder.
            prev = _read_json(dd / SLOW_LOOP_INSIGHTS_FILENAME, None)
            if isinstance(prev, dict) and prev.get("status") != "degraded":
                doc = dict(prev)
                doc["status"] = "degraded_cached"
                doc["degraded_at"] = ts
                doc["degraded_reason"] = "llm_unavailable"
                doc["date"] = date
            else:
                doc = {
                    "status": "degraded",
                    "date": date,
                    "ts": ts,
                    "insights": [],
                    "reason": "llm_unavailable",
                }
            _atomic_write_json(dd / SLOW_LOOP_INSIGHTS_FILENAME, doc)
            return doc

        # LLM-available path: the real LLM call is made by the calling layer
        # and its structured result is passed in via the return value contract.
        # Here we build the skeleton; real insights payload is empty (the
        # caller injects it after receiving the returned dict).
        total_equity = 0.0
        if isinstance(analytics, dict):
            eq_info = analytics.get("equity_summary") or analytics.get("equity") or {}
            if isinstance(eq_info, dict):
                total_equity = float(eq_info.get("current_equity") or 0.0)

        doc = {
            "status": "ok",
            "date": date,
            "ts": ts,
            "total_equity_usd": total_equity,
            "num_active_shadows": len(shadow.get("strategies") or []) if isinstance(shadow, dict) else 0,
            "num_adapters_live": len(
                [a for a in (orch_status.get("adapters") or []) if isinstance(a, dict) and a.get("status") == "ok"]
            ) if isinstance(orch_status, dict) else 0,
            "insights": [],  # populated by calling layer with LLM output
            "llm_used": True,
        }
        _atomic_write_json(dd / SLOW_LOOP_INSIGHTS_FILENAME, doc)
        return doc

    except Exception as exc:
        log.warning("slow_loop failed (%s) — degraded status written", exc)
        err_doc = {
            "status": "error",
            "date": date,
            "ts": datetime.now(timezone.utc).isoformat(),
            "error": f"{type(exc).__name__}: {exc}",
            "insights": [],
        }
        try:
            _atomic_write_json(_ddir(data_dir) / SLOW_LOOP_INSIGHTS_FILENAME, err_doc)
        except Exception:
            pass
        return err_doc


# ─── STRATEGIC LOOP ───────────────────────────────────────────────────────────


def run_strategic_loop(
    week_start: str,
    *,
    llm_available: bool = False,
    data_dir: str | None = None,
) -> dict:
    """Execute the weekly strategic loop (Monday cadence).

    When ``llm_available=False`` (default), emits a skip record.  The LLM SDK
    is NEVER imported here.

    Parameters
    ----------
    week_start : str
        ISO date string for the start of this week (Monday).
    llm_available : bool
        Set to ``True`` only by the calling layer after confirming LLM
        reachability.

    Returns
    -------
    dict
        Strategy notes document written to ``data/strategic_loop_notes.json``.
    """
    try:
        dd = _ddir(data_dir)
        ts = datetime.now(timezone.utc).isoformat()

        if not llm_available:
            doc = {
                "status": "skipped",
                "week_start": week_start,
                "ts": ts,
                "reason": "llm_unavailable",
                "notes": [],
            }
            _atomic_write_json(dd / STRATEGIC_LOOP_NOTES_FILENAME, doc)
            return doc

        # LLM-available path: gather inputs.
        equity_raw = _read_json(dd / "equity_curve_daily.json", {})
        daily_bars = []
        if isinstance(equity_raw, dict):
            all_bars = list(equity_raw.get("daily") or [])
            daily_bars = all_bars[-30:]  # last 30 days

        ceo_decisions = _read_json(dd / "ceo_decisions.json", [])
        alpha_candidates = _read_json(dd / "alpha_candidates.json", {})

        doc = {
            "status": "ok",
            "week_start": week_start,
            "ts": ts,
            "equity_bars_analyzed": len(daily_bars),
            "ceo_decisions_count": len(ceo_decisions) if isinstance(ceo_decisions, list) else 0,
            "alpha_candidates_count": len(
                alpha_candidates.get("candidates") or []
            ) if isinstance(alpha_candidates, dict) else 0,
            "notes": [],  # populated by calling layer with LLM strategic analysis
            "llm_used": True,
        }
        _atomic_write_json(dd / STRATEGIC_LOOP_NOTES_FILENAME, doc)
        return doc

    except Exception as exc:
        log.warning("strategic_loop failed (%s) — skip record written", exc)
        err_doc = {
            "status": "error",
            "week_start": week_start,
            "ts": datetime.now(timezone.utc).isoformat(),
            "error": f"{type(exc).__name__}: {exc}",
            "notes": [],
        }
        try:
            _atomic_write_json(_ddir(data_dir) / STRATEGIC_LOOP_NOTES_FILENAME, err_doc)
        except Exception:
            pass
        return err_doc
