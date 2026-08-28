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

#: Контракт агента (ADR-154/158): что этот агент ПРОИЗВОДИТ.
#: Объявление, а не вывод из кода. Источники: запись, видимая в этом модуле,
#: и авторская карта AGENT_OUTPUT_FILES в spa_core/monitoring/uptime_monitor.py.
#: Сверка — spa_core/monitoring/artifact_contract.py.
PRODUCES = (
    "data/cycle_health.json",
)

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
# "I could not measure this" — distinct from "I measured it and it is fine".
# Invariant #2 (refusal-first): a check that did not run must never be reported
# as a clean verdict. Deliberately NOT escalated to CRITICAL: the exit code and
# alert surface stay as they were; what changes is that the report stops
# claiming a result it does not have.
UNCHECKED = "UNCHECKED"


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
            "threshold_hours": MAX_CYCLE_GAP_HOURS,
        }

        Thresholds (the module constants — the daily cycle runs once a day):
          < MAX_CYCLE_GAP_HOURS (26 h)                  → OK
          MAX…CRITICAL_CYCLE_GAP_HOURS (26–30 h)        → WARNING
          > CRITICAL_CYCLE_GAP_HOURS (30 h)             → CRITICAL
          empty / unparseable                           → CRITICAL
                                                          (last_cycle_at: None)
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
            "status":             "OK" | "WARNING" | "UNCHECKED",
            "today_change_pct":   float | None,   # positive = gain, negative = loss
            "max_drop_threshold": 5.0,
            "prev_equity":        float | None,
            "curr_equity":        float | None,
        }

        WARNING if today_change_pct < -5.0 %.
        OK only when the change was actually computed and is within threshold.
        UNCHECKED (with ``detail``) when the drop could NOT be computed at all —
        fewer than two entries, unreadable equity values, or a zero denominator.
        Reporting those as OK would be a clean verdict about a measurement that
        never happened (invariant #2, refusal-first).
        """
        result: dict[str, Any] = {
            "status": OK,
            "today_change_pct": None,
            "max_drop_threshold": MAX_EQUITY_DROP_PCT,
            "prev_equity": None,
            "curr_equity": None,
        }

        if len(equity_history) < 2:
            result["status"] = UNCHECKED
            result["detail"] = "insufficient history for anomaly detection"
            return result

        try:
            prev_equity = float(equity_history[-2]["equity"])
            curr_equity = float(equity_history[-1]["equity"])
        except (KeyError, TypeError, ValueError) as exc:
            result["status"] = UNCHECKED
            result["detail"] = f"cannot read equity values: {exc}"
            return result

        result["prev_equity"] = prev_equity
        result["curr_equity"] = curr_equity

        if prev_equity == 0.0:
            result["status"] = UNCHECKED
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

        A file whose mtime could not be read (absent, or an OSError) is NOT
        fresh — its age is unknown. Such files land in ``unchecked`` (and, for
        back-compat with existing readers, keep their entry in
        ``missing_files``), and the verdict degrades to UNCHECKED rather than
        claiming OK about files that were never measured.

        Returns
        -------
        {
            "status":       "OK" | "STALE" | "UNCHECKED",
            "stale_files":  [{"file": str, "age_hours": float, "threshold_hours": float}, ...],
            "fresh_files":  [{"file": str, "age_hours": float, "threshold_hours": float}, ...],
            "missing_files": [str, ...],
            "unchecked":    [{"file": str, "reason": str}, ...],
        }
        """
        result: dict[str, Any] = {
            "status": OK,
            "stale_files": [],
            "fresh_files": [],
            "missing_files": [],
            "unchecked": [],
        }

        data_path = Path(data_dir)
        now_epoch = _now_epoch()

        for filename, threshold_hours in _WATCHED_FILES.items():
            filepath = data_path / filename
            try:
                mtime = os.path.getmtime(str(filepath))
            except FileNotFoundError:
                result["missing_files"].append(filename)
                result["unchecked"].append(
                    {"file": filename, "reason": "file not found — age unknown"}
                )
                continue
            except OSError as exc:
                result["missing_files"].append(f"{filename} (OSError: {exc})")
                result["unchecked"].append(
                    {"file": filename, "reason": f"unreadable — age unknown (OSError: {exc})"}
                )
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

        # A real staleness finding outranks "could not measure"; but with no
        # stale finding and at least one unmeasured file, OK would be a claim
        # about files never read.
        if result["status"] == OK and result["unchecked"]:
            result["status"] = UNCHECKED

        return result

    # ------------------------------------------------------------------ #
    # 4. Run all checks
    # ------------------------------------------------------------------ #

    def check_evidence_matches_curve(self, data_dir: str = "data") -> dict[str, Any]:
        """Доказательная база и кривая обязаны говорить об одних деньгах одно число.

        Две записи об одном и том же расходятся (own-32, замер 09.08: 16 дат из 51,
        и число растёт). Механизм: кривую пишут ДВА пути, и в день остановки они
        берут «вчера» из разных источников.

        Проверка живёт здесь, а не в тестах, по осознанной причине: тест-храповик
        требует живого трека и потому не запускается ни в CI, ни агентом — то есть
        сторож существовал бы, но молчал. Этот монитор ходит по живому дереву сам.

        Результат — ЧИСЛО в состоянии монитора, а не строка в логе: вывод, который
        никто не читает, уже был отдельным дефектом (правило честности, 09.08).

        Возвращает UNCHECKED, если файлов нет: «не смогли посмотреть» — не то же
        самое, что «посмотрели, и всё сходится».
        """
        ddir = Path(data_dir)
        ev_path, cu_path = ddir / "paper_evidence.json", ddir / "equity_curve_daily.json"
        if not (ev_path.is_file() and cu_path.is_file()):
            return {"status": UNCHECKED, "divergent_days": None,
                    "detail": "нет paper_evidence.json или equity_curve_daily.json"}
        try:
            ev = json.loads(ev_path.read_text(encoding="utf-8"))
            cu = json.loads(cu_path.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            return {"status": UNCHECKED, "divergent_days": None,
                    "detail": f"не прочитать: {exc}"}

        a = {x["date"]: x.get("equity_value") for x in ev.get("days", []) if "date" in x}
        b = {x["date"]: x.get("close_equity")
             for x in (cu.get("daily") or []) if "date" in x}
        common = set(a) & set(b)
        if not common:
            return {"status": UNCHECKED, "divergent_days": None,
                    "detail": "нет общих дат — сравнивать нечего"}
        # Округляем ДО сравнения: в плавающей арифметике разница ровно в цент даёт
        # 0.010000000000005 и проходила бы порог, поднимая тревогу на округлении.
        # Обе записи и так хранят суммы с точностью до цента.
        bad = sorted(d for d in common
                     if a[d] and b[d] and round(abs(float(a[d]) - float(b[d])), 2) > 0.01)
        worst = max((abs(float(a[d]) - float(b[d])) for d in bad), default=0.0)
        return {
            # WARNING, а не CRITICAL: суммы копеечные и капитал виртуальный. Но и не
            # HEALTHY — go-live проверки читают именно доказательную базу.
            "status": "WARNING" if bad else "HEALTHY",
            "divergent_days": len(bad),
            "compared_days": len(common),
            "max_delta_usd": round(worst, 2),
            "latest_divergent": bad[-1] if bad else None,
            "detail": (f"{len(bad)} из {len(common)} дат расходятся (own-32), "
                       f"максимум ${worst:.2f}") if bad
                      else f"все {len(common)} общих дат сходятся",
        }

    def run_all_checks(self, data_dir: str = "data") -> dict[str, Any]:
        """
        Run all three health checks and combine the results.

        Reads equity_history.json and pnl_history.json from data_dir.

        Returns
        -------
        {
            "overall": "HEALTHY" | "WARNING" | "CRITICAL" | "UNCHECKED",
            "checks": {
                "cycle_gap":       {...},
                "equity_anomaly":  {...},
                "data_freshness":  {...},
            },
            "unchecked": [{"check": str, "reason": str}, ...],
            "checked_at": ISO string (UTC),
            "recommendations": [str, ...],
        }

        Priority:
          - CRITICAL  → overall CRITICAL  (any check is CRITICAL)
          - WARNING / STALE → overall WARNING  (no CRITICAL present)
          - UNCHECKED → overall UNCHECKED  (nothing wrong was found, but at
            least one check could not run — HEALTHY would be a clean verdict
            about a measurement that never happened, invariant #2)
          - All checks actually ran clean → overall HEALTHY
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
            "evidence_vs_curve": self.check_evidence_matches_curve(data_dir),
        }

        # Collect the checks that could NOT be computed, with their reason.
        unchecked: list[dict[str, str]] = []
        # `evidence_vs_curve` — СОВЕТУЮЩИЙ сигнал о согласованности двух записей
        # (own-32), а не проверка здоровья цикла. Его число видно в `checks`, но в
        # вердикт и в список «не измерено» он не входит: у большинства вызывающих
        # (тесты, песочницы) файла доказательной базы нет по построению, и его
        # отсутствие — не пробел в наблюдении, а другой предмет.
        for name, chk in checks.items():
            if name == "evidence_vs_curve":
                continue
            if chk.get("status") == UNCHECKED:
                unchecked.append(
                    {"check": name, "reason": str(chk.get("detail") or "not measured")}
                )
        for entry in data_freshness.get("unchecked", []):
            unchecked.append(
                {
                    "check": f"data_freshness:{entry.get('file')}",
                    "reason": str(entry.get("reason") or "not measured"),
                }
            )

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
        elif unchecked:
            # Nothing wrong was found, but something was never looked at.
            overall = UNCHECKED
        else:
            overall = HEALTHY

        # Build recommendations
        recommendations: list[str] = []

        if cycle_gap["status"] == CRITICAL:
            recommendations.append(
                f"CRITICAL: Cycle has not run for over "
                f"{CRITICAL_CYCLE_GAP_HOURS:.0f} hours (or its timestamp is "
                f"unreadable). Check launchd com.spa.daily_cycle and "
                f"/tmp/spa_cycle_err.log."
            )
        elif cycle_gap["status"] == WARNING:
            recommendations.append(
                f"WARNING: Cycle gap is between {MAX_CYCLE_GAP_HOURS:.0f} and "
                f"{CRITICAL_CYCLE_GAP_HOURS:.0f} hours. "
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

        if unchecked:
            recommendations.append(
                "NOT CHECKED (no verdict — these did not run): "
                + "; ".join(f"{u['check']} — {u['reason']}" for u in unchecked)
            )

        if overall == HEALTHY:
            recommendations.append("All checks passed. Cycle is healthy.")

        return {
            "overall": overall,
            "checks": checks,
            "unchecked": unchecked,
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


def _load_last_cycle_ts(data_dir: Path) -> "str | None":
    """Read ``last_cycle_ts`` from paper_trading_status.json.

    Returns the ISO-8601 timestamp string or None on any error.

    Used as a reliable fallback for cycle-time detection when
    ``equity_curve_daily.json`` is absent or lacks a ``generated_at`` key
    (P1-FIX-002: stale equity_history.json fallback fix).
    """
    try:
        doc = json.loads(
            (data_dir / "paper_trading_status.json").read_text(encoding="utf-8")
        )
        ts = doc.get("last_cycle_ts")
        if ts and isinstance(ts, str):
            return ts
    except (FileNotFoundError, json.JSONDecodeError, OSError, KeyError):
        pass
    return None


def _load_equity_history(data_dir: Path) -> list:
    """Return the equity history as a flat list of ``{date/timestamp, equity}``.

    Source priority (P1-FIX-002 — stale-fallback fix):

    1. ``equity_curve_daily.json`` + ``generated_at``
       → most accurate: precise cycle write-time from cycle_runner.
    2. ``equity_curve_daily.json`` + ``last_cycle_ts`` from
       ``paper_trading_status.json``
       → good: reliable when generated_at is absent.
    3. ``equity_curve_daily.json`` with date-only bar
       → midnight UTC timestamp (overstates gap by up to ~20 h at day-end).
    4. ``paper_trading_status.json`` alone (equity_curve_daily.json missing)
       → minimal single-entry list; cycle_gap check works, anomaly check
       skips gracefully (insufficient history).
    5. ``equity_history.json`` (legacy flat list)
       → last resort; may be arbitrarily stale.
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
                generated_at = doc.get("generated_at")
                if generated_at:
                    # Best case: precise write-time stamped by cycle_runner.
                    history[-1] = {**history[-1], "timestamp": generated_at}
                else:
                    # generated_at absent — cross-check paper_trading_status
                    # to avoid midnight-UTC overstatement (P1-FIX-002).
                    pts_ts = _load_last_cycle_ts(data_dir)
                    if pts_ts:
                        history[-1] = {**history[-1], "timestamp": pts_ts}
                return history
    except (FileNotFoundError, json.JSONDecodeError, OSError, AttributeError):
        pass

    # equity_curve_daily.json fully missing —
    # paper_trading_status.json as sole source (always fresh after a cycle).
    pts_ts = _load_last_cycle_ts(data_dir)
    if pts_ts:
        return [{"timestamp": pts_ts, "equity": 0.0}]

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

        # ── ВНУТРИДНЕВНОЙ контроль просадки ─────────────────────────────────
        #
        # Стоп-кран считался ТОЛЬКО в дневном цикле — раз в сутки. На бумаге
        # терпимо, на реальных деньгах нет: между прогонами может пройти всё
        # падение целиком, и владелец узнает о нём через 24 часа. Владелец
        # отметил это отдельным блокером go-live.
        #
        # Живёт здесь, а не отдельным агентом: cycle_health уже работает каждые
        # 300 секунд — это существующий частый ритм. Новый агент означал бы ещё
        # одного производителя, за которым надо следить, а именно от таких за
        # сутки нашлось шесть штук, и каждый молчал.
        #
        # Проверка НЕ двигает капитал: run_kill_switch_check вычисляет вердикт и
        # пишет статус. Применяет его дневной цикл — здесь только раннее
        # обнаружение и уведомление, чтобы владелец узнал в течение 5 минут,
        # а не суток.
        try:
            from spa_core.governance.kill_switch import run_kill_switch_check

            ks = run_kill_switch_check(data_dir=str(data_dir)) or {}
            if ks.get("triggered"):
                reason = str(ks.get("reason") or "")
                print(f"  [CRITICAL] intraday kill-switch: {reason}")
                # ── ЗАМЕР 2026-08-10: этот путь тоже был холостым ───────────
                #
                # Здесь стоял `TelegramManager(category="p0")`, а он отставлен
                # (Phase-1 Telegram rebuild): `_send_raw` ВСЕГДА возвращает
                # False и уводит текст в суточный дайджест. У дневного цикла
                # была хотя бы дублёрка в лице `threat_reactor`; у ЭТОЙ ветки
                # дублёрки нет — она и есть весь смысл ADR-068 (узнать за
                # 5 минут, а не за сутки). То есть внутридневная просадка
                # доезжала до владельца в лучшем случае суточной сводкой,
                # ровно потеряв то, ради чего проверку и делали.
                #
                # Канонический путь — `push_policy` (ключ `kill_switch` первый
                # в Tier-1 whitelist). Edge-триггер здесь особенно к месту:
                # проверка идёт каждые 5 минут, и без него одна просадка дала
                # бы 288 сообщений в сутки.
                #
                # Пороги стоп-крана не трогаются: чинится доставка (инв. 1).
                try:
                    from spa_core.alerts.kill_switch_alert import notify_kill_switch

                    # data_dir — тот же, по которому судили о стоп-кране выше:
                    # состояние тревоги обязано следовать за каталогом проверки,
                    # иначе прогон над песочницей пишет в ЖИВОЕ edge-состояние и
                    # глушит следующую настоящую тревогу (замер #193).
                    _sent = notify_kill_switch(
                        reason,
                        source="внутридневная проверка",
                        data_dir=data_dir,
                    )
                    if not _sent:
                        print(
                            "  [CRITICAL] стоп-кран сработал, тревога НЕ УШЛА "
                            "сейчас (дедуп того же отпечатка либо отказ канала)"
                        )
                except Exception as _alert_exc:  # noqa: BLE001
                    # Молчать нельзя: несработавшая тревога обязана быть видна
                    # отдельным событием, иначе мы заменим одну тишину другой.
                    print(f"  [CRITICAL] стоп-кран сработал, ТРЕВОГА НЕ ОТПРАВЛЕНА: {_alert_exc}")
        except Exception as _ks_exc:  # noqa: BLE001
            # Сторож не имеет права ронять то, что охраняет: сбой проверки
            # просадки не должен останавливать мониторинг цикла.
            print(f"  (внутридневная проверка просадки пропущена: {_ks_exc})")

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
        print(f"  [{status:9s}] {name}{hours_str}{stale_str} {detail}")

    for item in report.get("unchecked", []):
        print(f"  [NOT CHECKED] {item['check']} — {item['reason']}")

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
