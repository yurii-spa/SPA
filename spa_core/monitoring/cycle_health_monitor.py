"""
spa_core/monitoring/cycle_health_monitor.py
============================================
Monitors paper trading cycle health (MP-cycle-health).

Detects:
  1. Missed / delayed cycles      — check_cycle_gap()
  2. Sudden equity anomalies      — check_equity_anomaly()
  3. Stale data files             — check_data_freshness()

Writes: data/cycle_health.json (atomic tmp + os.replace)

Rules:
  - STDLIB ONLY — no external dependencies
  - READ-ONLY — never modifies any state except data/cycle_health.json
  - ATOMIC writes — tmp + os.replace
  - LLM FORBIDDEN in this module
  - FAIL-SAFE — every check catches exceptions, never crashes

CLI:
  python3 -m spa_core.monitoring.cycle_health_monitor          # check only
  python3 -m spa_core.monitoring.cycle_health_monitor --run    # check + write
  exit 0 if HEALTHY/WARNING, exit 1 if CRITICAL
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# The daily cycle (launchd com.spa.daily_cycle) runs once per day at 08:00, so a
# healthy gap is ~24 h. Thresholds give grace for a late/woken-from-sleep run.
# (Were 2 h / 4 h — tuned for the old every-30-min cadence, retired 2026-06-18.)
MAX_CYCLE_GAP_HOURS: float = 26.0       # WARNING if last cycle > 26 h ago
CRITICAL_CYCLE_GAP_HOURS: float = 30.0  # CRITICAL if last cycle > 30 h ago
MAX_EQUITY_DROP_PCT: float = 5.0        # WARNING if single-entry drop > 5 %
STALE_REGIME_HOURS: float = 4.0         # STALE if market_regime.json > 4 h old
STALE_ADAPTER_HOURS: float = 24.0       # STALE if adapter_status.json > 24 h old
STALE_TOURNAMENT_HOURS: float = 168.0   # STALE if tournament_ranking.json > 7 d old

HEALTH_FILE = "cycle_health.json"

# Files monitored by check_data_freshness and their staleness thresholds (hours)
_WATCHED_FILES: dict[str, float] = {
    "market_regime.json": STALE_REGIME_HOURS,
    "adapter_status.json": STALE_ADAPTER_HOURS,
    "tournament_ranking.json": STALE_TOURNAMENT_HOURS,
}

# Status constants
OK = "OK"
WARNING = "WARNING"
CRITICAL = "CRITICAL"
STALE = "STALE"
HEALTHY = "HEALTHY"


# ---------------------------------------------------------------------------
# Helper — parse ISO-8601 timestamp string → datetime (UTC-aware)
# ---------------------------------------------------------------------------

def _parse_iso(ts: str) -> datetime:
    """
    Parse an ISO-8601 timestamp string into a UTC-aware datetime.
    Handles both offset-aware (e.g. '+00:00') and naive (assumed UTC) strings.
    """
    try:
        dt = datetime.fromisoformat(ts)
    except ValueError:
        # Last-resort: strip sub-second and tz, treat as UTC
        dt = datetime.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# ---------------------------------------------------------------------------
# CycleHealthMonitor
# ---------------------------------------------------------------------------

class CycleHealthMonitor:
    """
    Paper trading cycle health checker.

    All check_* methods are pure functions (no I/O side-effects).
    check_data_freshness reads the filesystem (os.path.getmtime).
    save_health_report writes data/cycle_health.json atomically.
    """

    # Re-export as class attributes so callers / tests can reference them
    MAX_CYCLE_GAP_HOURS: float = MAX_CYCLE_GAP_HOURS
    MAX_EQUITY_DROP_PCT: float = MAX_EQUITY_DROP_PCT
    STALE_REGIME_HOURS: float = STALE_REGIME_HOURS

    # ------------------------------------------------------------------ #
    # 1. Cycle-gap check
    # ------------------------------------------------------------------ #

    def check_cycle_gap(self, equity_history: list) -> dict[str, Any]:
        """
        Check how long ago the last cycle entry was recorded.

        Looks at equity_history[-1]:
          - Prefers "timestamp" key (ISO-8601 string or epoch float).
          - Falls back to "date" key (YYYY-MM-DD → midnight UTC).

        Returns
        -------
        {
            "status":          "OK" | "WARNING" | "CRITICAL",
            "last_cycle_at":   ISO string | None,
            "hours_since":     float | None,
            "threshold_hours": 2.0,
        }

        Thresholds:
          < 2 h  → OK
          2–4 h  → WARNING
          > 4 h  → CRITICAL
          empty  → CRITICAL (last_cycle_at: None, hours_since: None)
        """
        result: dict[str, Any] = {
            "status": CRITICAL,
            "last_cycle_at": None,
            "hours_since": None,
            "threshold_hours": MAX_CYCLE_GAP_HOURS,
        }

        if not equity_history:
            result["detail"] = "equity_history is empty"
            return result

        last = equity_history[-1]
        now_utc = datetime.now(tz=timezone.utc)
        dt_last: datetime | None = None

        # Try "timestamp" first
        raw_ts = last.get("timestamp")
        if raw_ts is not None:
            try:
                if isinstance(raw_ts, (int, float)):
                    dt_last = datetime.fromtimestamp(float(raw_ts), tz=timezone.utc)
                else:
                    dt_last = _parse_iso(str(raw_ts))
            except Exception:
                dt_last = None

        # Fall back to "date" (YYYY-MM-DD → midnight UTC)
        if dt_last is None:
            raw_date = last.get("date")
            if raw_date:
                try:
                    dt_last = datetime.strptime(str(raw_date), "%Y-%m-%d").replace(
                        tzinfo=timezone.utc
                    )
                except ValueError:
                    pass

        if dt_last is None:
            result["detail"] = "cannot parse timestamp or date from last equity_history entry"
            return result

        hours_since = (now_utc - dt_last).total_seconds() / 3600.0
        result["last_cycle_at"] = dt_last.isoformat()
        result["hours_since"] = round(hours_since, 3)

        if hours_since < MAX_CYCLE_GAP_HOURS:
            result["status"] = OK
        elif hours_since <= CRITICAL_CYCLE_GAP_HOURS:
            result["status"] = WARNING
        else:
            result["status"] = CRITICAL

        return result

    # ------------------------------------------------------------------ #
    # 2. Equity anomaly check
    # ------------------------------------------------------------------ #

    def check_equity_anomaly(self, equity_history: list) -> dict[str, Any]:
        """
        Detect a sudden equity drop between the last two entries.

        Returns
        -------
        {
            "status":             "OK" | "WARNING",
            "today_change_pct":   float | None,   # positive = gain, negative = loss
            "max_drop_threshold": 5.0,
            "prev_equity":        float | None,
            "curr_equity":        float | None,
        }

        WARNING if today_change_pct < -5.0 %.
        OK if only one (or zero) entry or drop is within threshold.
        """
        result: dict[str, Any] = {
            "status": OK,
            "today_change_pct": None,
            "max_drop_threshold": MAX_EQUITY_DROP_PCT,
            "prev_equity": None,
            "curr_equity": None,
        }

        if len(equity_history) < 2:
            result["detail"] = "insufficient history for anomaly detection"
            return result

        try:
            prev_equity = float(equity_history[-2]["equity"])
            curr_equity = float(equity_history[-1]["equity"])
        except (KeyError, TypeError, ValueError) as exc:
            result["detail"] = f"cannot read equity values: {exc}"
            return result

        result["prev_equity"] = prev_equity
        result["curr_equity"] = curr_equity

        if prev_equity == 0.0:
            result["detail"] = "prev_equity is 0, cannot compute change_pct"
            return result

        change_pct = (curr_equity - prev_equity) / abs(prev_equity) * 100.0
        result["today_change_pct"] = round(change_pct, 4)

        if change_pct < -MAX_EQUITY_DROP_PCT:
            result["status"] = WARNING
            result["detail"] = (
                f"equity dropped {abs(change_pct):.2f}% "
                f"(threshold {MAX_EQUITY_DROP_PCT}%)"
            )

        return result

    # ------------------------------------------------------------------ #
    # 3. Data freshness check
    # ------------------------------------------------------------------ #

    def check_data_freshness(self, data_dir: str = "data") -> dict[str, Any]:
        """
        Check whether key JSON data files have been updated recently
        using os.path.getmtime().

        Monitored files and their staleness thresholds:
          market_regime.json    → > 4 h  → STALE
          adapter_status.json   → > 24 h → STALE
          tournament_ranking.json → > 168 h (7 d) → STALE

        Returns
        -------
        {
            "status":       "OK" | "STALE",
            "stale_files":  [{"file": str, "age_hours": float, "threshold_hours": float}, ...],
            "fresh_files":  [{"file": str, "age_hours": float, "threshold_hours": float}, ...],
            "missing_files": [str, ...],
        }
        """
        result: dict[str, Any] = {
            "status": OK,
            "stale_files": [],
            "fresh_files": [],
            "missing_files": [],
        }

        data_path = Path(data_dir)
        now_epoch = _now_epoch()

        for filename, threshold_hours in _WATCHED_FILES.items():
            filepath = data_path / filename
            try:
                mtime = os.path.getmtime(str(filepath))
            except FileNotFoundError:
                result["missing_files"].append(filename)
                continue
            except OSError as exc:
                result["missing_files"].append(f"{filename} (OSError: {exc})")
                continue

            age_hours = (now_epoch - mtime) / 3600.0
            entry = {
                "file": filename,
                "age_hours": round(age_hours, 3),
                "threshold_hours": threshold_hours,
            }
            if age_hours > threshold_hours:
                result["stale_files"].append(entry)
                result["status"] = STALE
            else:
                result["fresh_files"].append(entry)

        return result

    # ------------------------------------------------------------------ #
    # 4. Run all checks
    # ------------------------------------------------------------------ #

    def run_all_checks(self, data_dir: str = "data") -> dict[str, Any]:
        """
        Run all three health checks and combine the results.

        Reads equity_history.json and pnl_history.json from data_dir.

        Returns
        -------
        {
            "overall": "HEALTHY" | "WARNING" | "CRITICAL",
            "checks": {
                "cycle_gap":       {...},
                "equity_anomaly":  {...},
                "data_freshness":  {...},
            },
            "checked_at": ISO string (UTC),
            "recommendations": [str, ...],
        }

        Priority:
          - CRITICAL  → overall CRITICAL  (any check is CRITICAL)
          - WARNING / STALE → overall WARNING  (no CRITICAL present)
          - All OK/HEALTHY  → overall HEALTHY
        """
        checked_at = datetime.now(tz=timezone.utc).isoformat()

        # Load equity history — prefers equity_curve_daily.json (the file the
        # cycle actually writes), falls back to legacy equity_history.json.
        equity_history: list = _load_equity_history(Path(data_dir))

        # Run individual checks
        cycle_gap = self.check_cycle_gap(equity_history)
        equity_anomaly = self.check_equity_anomaly(equity_history)
        data_freshness = self.check_data_freshness(data_dir=data_dir)

        checks = {
            "cycle_gap": cycle_gap,
            "equity_anomaly": equity_anomaly,
            "data_freshness": data_freshness,
        }

        # Determine overall status
        statuses = {
            cycle_gap["status"],
            equity_anomaly["status"],
            data_freshness["status"],
        }

        if CRITICAL in statuses:
            overall = CRITICAL
        elif WARNING in statuses or STALE in statuses:
            overall = WARNING
        else:
            overall = HEALTHY

        # Build recommendations
        recommendations: list[str] = []

        if cycle_gap["status"] == CRITICAL:
            recommendations.append(
                "CRITICAL: Cycle has not run for over 4 hours. "
                "Check launchd com.spa.daily_cycle and /tmp/spa_cycle_err.log."
            )
        elif cycle_gap["status"] == WARNING:
            recommendations.append(
                "WARNING: Cycle gap is between 2–4 hours. "
                "Verify launchd schedule and network connectivity."
            )

        if equity_anomaly["status"] == WARNING:
            drop = equity_anomaly.get("today_change_pct")
            recommendations.append(
                f"WARNING: Sudden equity drop detected ({drop:.2f}%). "
                "Review data/trades.json and data/risk_policy_blocks.json."
            )

        if data_freshness["stale_files"]:
            stale_names = [e["file"] for e in data_freshness["stale_files"]]
            recommendations.append(
                f"STALE data files detected: {', '.join(stale_names)}. "
                "Run cycle_runner manually or check adapters."
            )

        if data_freshness["missing_files"]:
            recommendations.append(
                f"Missing data files: {', '.join(data_freshness['missing_files'])}. "
                "Ensure cycle has run at least once."
            )

        if overall == HEALTHY:
            recommendations.append("All checks passed. Cycle is healthy.")

        return {
            "overall": overall,
            "checks": checks,
            "checked_at": checked_at,
            "recommendations": recommendations,
        }

    # ------------------------------------------------------------------ #
    # 5. Save health report
    # ------------------------------------------------------------------ #

    def save_health_report(self, report: dict, data_dir: str = "data") -> None:
        """
        Atomically write the health report to data/cycle_health.json.

        Uses tmp file + os.replace to guarantee atomicity.
        Raises OSError on write failure (caller decides how to handle).
        """
        data_path = Path(data_dir)
        out_file = data_path / HEALTH_FILE
        tmp_file = data_path / (HEALTH_FILE + ".tmp")

        payload = json.dumps(report, indent=2, ensure_ascii=False)
        try:
            tmp_file.write_text(payload, encoding="utf-8")
            os.replace(str(tmp_file), str(out_file))
        finally:
            # Clean up tmp if replace failed
            try:
                if tmp_file.exists():
                    tmp_file.unlink()
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _now_epoch() -> float:
    """Return current time as POSIX epoch (seconds). Extracted for test patching."""
    return datetime.now(tz=timezone.utc).timestamp()


def _load_json_list(path: Path) -> list:
    """
    Load a JSON file that is expected to be a list.
    Returns [] on any error (file missing, bad JSON, wrong type).
    """
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
        if isinstance(data, list):
            return data
        return []
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []


def _load_equity_history(data_dir: Path) -> list:
    """Return the equity history as a flat list of ``{date/timestamp, equity}``.

    Source of truth is ``equity_curve_daily.json`` (written every cycle by
    ``cycle_runner``); its ``daily`` array carries ``date`` + ``close_equity``,
    which we normalise to the ``{date, equity}`` shape the health checks expect.
    Falls back to the legacy flat ``equity_history.json`` when the curve file is
    absent (older seeds / unit tests), so behaviour is unchanged when neither
    exists (→ empty list → CRITICAL "equity_history is empty").
    """
    curve_path = data_dir / "equity_curve_daily.json"
    try:
        doc = json.loads(curve_path.read_text(encoding="utf-8"))
        daily = doc.get("daily") if isinstance(doc, dict) else None
        if isinstance(daily, list) and daily:
            history: list = []
            for bar in daily:
                if not isinstance(bar, dict):
                    continue
                equity = bar.get("equity", bar.get("close_equity"))
                if equity is None:
                    continue
                history.append({"date": bar.get("date"), "equity": equity})
            if history:
                # Daily bars carry only a date (→ midnight UTC), which would
                # overstate the gap. Stamp the latest entry with the doc's
                # generated_at (the real cycle write-time) for an accurate gap.
                generated_at = doc.get("generated_at")
                if generated_at:
                    history[-1] = {**history[-1], "timestamp": generated_at}
                return history
    except (FileNotFoundError, json.JSONDecodeError, OSError, AttributeError):
        pass

    # Legacy fallback — flat list already in the expected shape.
    return _load_json_list(data_dir / "equity_history.json")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    """
    CLI runner.

    Usage:
        python3 -m spa_core.monitoring.cycle_health_monitor          # check, no write
        python3 -m spa_core.monitoring.cycle_health_monitor --run    # check + write
    """
    if argv is None:
        argv = sys.argv[1:]

    write_output = "--run" in argv

    here = Path(__file__).resolve()
    repo_dir = here.parent.parent.parent  # .../spa_core/monitoring/... → repo root
    data_dir = repo_dir / "data"

    monitor = CycleHealthMonitor()
    report = monitor.run_all_checks(data_dir=str(data_dir))

    if write_output:
        monitor.save_health_report(report, data_dir=str(data_dir))

    # Human-readable output
    overall = report["overall"]
    print(f"\nSPA Cycle Health Monitor — {report['checked_at']}")
    print(f"Overall: {overall}\n")

    for name, chk in report["checks"].items():
        status = chk.get("status", "?")
        detail = chk.get("detail", "")
        hours = chk.get("hours_since")
        hours_str = f" (age={hours:.2f}h)" if hours is not None else ""
        stale = chk.get("stale_files", [])
        stale_str = f" stale={[e['file'] for e in stale]}" if stale else ""
        print(f"  [{status:8s}] {name}{hours_str}{stale_str} {detail}")

    if report["recommendations"]:
        print("\nRecommendations:")
        for rec in report["recommendations"]:
            print(f"  • {rec}")
    print()

    if write_output:
        print(f"  → Written to {data_dir / HEALTH_FILE}")

    return 0 if overall != CRITICAL else 1


if __name__ == "__main__":
    sys.exit(main())
