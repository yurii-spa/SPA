"""
Full Portfolio Master Report (MP-621).
=======================================
Агрегирует все аналитические отчёты в единый master snapshot.
Advisory only — читает только готовые JSON, не вычисляет новые метрики.

Sources consumed (all optional — missing files degrade gracefully):

    data/yield_attribution_tracker.json  — portfolio APY / allocated USD
    data/benchmark_report.json           — benchmark verdict (ALPHA+/ALPHA/LAGGING)
    data/weekly_summary.json             — weekly verdict (EXCELLENT/GOOD/FAIR/POOR)
    data/integrated_risk.json            — integrated risk level (GREEN/YELLOW/RED)
    data/rebalance_plan.json             — rebalance recommendation (HOLD/MONITOR/REBALANCE)
    data/capital_efficiency.json         — capital grade (A/B/C/D)
    data/tier_exposure.json              — tier policy status (COMPLIANT/BREACH)
    data/chain_exposure.json             — chain policy status (COMPLIANT/BREACH)
    data/peg_report.json                 — peg status (GREEN/YELLOW/RED)
    data/yield_forecast.json             — yield trend (RISING/STABLE/FALLING)
    data/stablecoin_exposure.json        — stablecoin contagion risk
    data/concentration_analytics.json    — protocol concentration verdict

Output (ring-buffer 30):

    data/master_report.json

Design constraints
------------------
* Pure stdlib — no external dependencies.
* Advisory only — NEVER touches allocator / risk / execution.
* Atomic writes: tmp-file + os.replace on every JSON update.
* Never raises on happy path — all data-load failures degrade gracefully.
* Telegram message ≤ 2 000 characters.
* Does NOT import risk/, execution/, monitoring/, allocator/, cycle_runner.

CLI
---
``python3 -m spa_core.analytics.full_portfolio_report --check``   (default)
``python3 -m spa_core.analytics.full_portfolio_report --run``     (+ save)
``python3 -m spa_core.analytics.full_portfolio_report --data-dir PATH``
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_OUTPUT_FILE: str = "master_report.json"
_RING_BUFFER_MAX: int = 30
_TELEGRAM_MAX_CHARS: int = 2000

# Health levels
_HEALTH_EXCELLENT = "EXCELLENT"
_HEALTH_GOOD = "GOOD"
_HEALTH_FAIR = "FAIR"
_HEALTH_ALERT = "ALERT"

# Status levels
_STATUS_GREEN = "GREEN"
_STATUS_YELLOW = "YELLOW"
_STATUS_RED = "RED"
_STATUS_UNKNOWN = "UNKNOWN"

# Telegram health emoji
_HEALTH_EMOJI: Dict[str, str] = {
    _HEALTH_EXCELLENT: "🟢",
    _HEALTH_GOOD: "🟢",
    _HEALTH_FAIR: "🟡",
    _HEALTH_ALERT: "🔴",
}

_STATUS_EMOJI: Dict[str, str] = {
    _STATUS_GREEN: "🟢",
    _STATUS_YELLOW: "🟡",
    _STATUS_RED: "🔴",
    _STATUS_UNKNOWN: "⚪",
}


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ModuleStatus:
    """Status summary of a single analytics data source."""

    name: str           # "benchmark" / "weekly" / "risk" / etc.
    file_path: str      # "data/benchmark_report.json"
    loaded: bool        # True if file was successfully loaded
    key_metric: str     # human-readable main metric, e.g. "ALPHA+ (5.22%)"
    status_level: str   # "GREEN" / "YELLOW" / "RED" / "UNKNOWN"
    last_updated: str   # ISO timestamp (trimmed) or "unknown"

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "file_path": self.file_path,
            "loaded": self.loaded,
            "key_metric": self.key_metric,
            "status_level": self.status_level,
            "last_updated": self.last_updated,
        }


@dataclass
class MasterReport:
    """Full portfolio master snapshot aggregating all analytics modules."""

    generated_at: str

    # Sводные метрики (из attribution tracker)
    portfolio_apy_pct: float
    total_allocated_usd: float

    # Статусы модулей
    modules: List[ModuleStatus]
    modules_loaded: int
    modules_failed: int

    # Агрегированные сигналы
    benchmark_verdict: str           # ALPHA+ / ALPHA / BENCHMARK / LAGGING / UNKNOWN
    weekly_verdict: str              # EXCELLENT / GOOD / FAIR / POOR / UNKNOWN
    risk_level: str                  # GREEN / YELLOW / ORANGE / RED / UNKNOWN
    rebalance_recommendation: str    # HOLD / MONITOR / REBALANCE / UNKNOWN
    capital_grade: str               # A / B / C / D / UNKNOWN
    tier_policy_status: str          # COMPLIANT / BREACH / UNKNOWN
    chain_policy_status: str         # COMPLIANT / BREACH / UNKNOWN
    peg_status: str                  # GREEN / YELLOW / RED / UNKNOWN
    forecast_trend: str              # RISING / STABLE / FALLING / UNKNOWN

    # Overall health
    overall_health: str   # EXCELLENT / GOOD / FAIR / ALERT
    health_score: float   # 0.0–1.0 (fraction of GREEN modules)
    action_items: List[str]
    summary: str          # "APY 5.22%, GOOD health, 2 action items"

    def to_dict(self) -> dict:
        return {
            "generated_at": self.generated_at,
            "portfolio_apy_pct": self.portfolio_apy_pct,
            "total_allocated_usd": self.total_allocated_usd,
            "modules": [m.to_dict() for m in self.modules],
            "modules_loaded": self.modules_loaded,
            "modules_failed": self.modules_failed,
            "benchmark_verdict": self.benchmark_verdict,
            "weekly_verdict": self.weekly_verdict,
            "risk_level": self.risk_level,
            "rebalance_recommendation": self.rebalance_recommendation,
            "capital_grade": self.capital_grade,
            "tier_policy_status": self.tier_policy_status,
            "chain_policy_status": self.chain_policy_status,
            "peg_status": self.peg_status,
            "forecast_trend": self.forecast_trend,
            "overall_health": self.overall_health,
            "health_score": self.health_score,
            "action_items": self.action_items,
            "summary": self.summary,
        }


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Convert value to float; return default on bool / None / error."""
    if value is None or isinstance(value, bool):
        return default
    try:
        result = float(value)
        import math
        if math.isnan(result) or math.isinf(result):
            return default
        return result
    except (TypeError, ValueError):
        return default


def _get_latest(data: Optional[dict]) -> dict:
    """
    Return the 'latest' sub-dict from a data file, or {} on failure.

    Handles both ring-buffer style files (with ``latest`` key) and flat
    files (like peg_report.json) which have no ``latest`` key.
    """
    if not isinstance(data, dict):
        return {}
    latest = data.get("latest", {})
    if not isinstance(latest, dict):
        return {}
    return latest


def _extract_timestamp(data: Optional[dict]) -> str:
    """
    Extract the most recent ISO timestamp from a data dict.

    Checks root-level then ``latest`` sub-dict for common timestamp keys.
    Returns "unknown" when nothing is found.
    """
    if not isinstance(data, dict):
        return "unknown"
    _TS_KEYS = ("generated_at", "last_updated", "updated_at", "timestamp")
    for key in _TS_KEYS:
        val = data.get(key)
        if isinstance(val, str) and val:
            return val[:19]
    latest = data.get("latest", {})
    if isinstance(latest, dict):
        for key in _TS_KEYS:
            val = latest.get(key)
            if isinstance(val, str) and val:
                return val[:19]
    return "unknown"


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------


class FullPortfolioReport:
    """
    Aggregate all SPA analytics modules into a single master snapshot.

    Parameters
    ----------
    data_path:
        Path to the ``data/`` directory.  Defaults to the ``data/`` folder
        at the project root (resolved relative to this file).
    """

    # All 12 data sources — paths relative to project root
    DATA_SOURCES: Dict[str, str] = {
        "attribution":        "data/yield_attribution_tracker.json",
        "benchmark":          "data/benchmark_report.json",
        "weekly":             "data/weekly_summary.json",
        "risk":               "data/integrated_risk.json",
        "rebalance":          "data/rebalance_plan.json",
        "capital_efficiency": "data/capital_efficiency.json",
        "tier_exposure":      "data/tier_exposure.json",
        "chain_exposure":     "data/chain_exposure.json",
        "peg_monitor":        "data/peg_report.json",
        "forecast":           "data/yield_forecast.json",
        "stablecoin":         "data/stablecoin_exposure.json",
        "concentration":      "data/concentration_analytics.json",
    }

    def __init__(self, data_path: Optional[str] = None) -> None:
        if data_path is None:
            # spa_core/analytics/full_portfolio_report.py → project_root/data
            data_path = str(Path(__file__).parent.parent.parent / "data")
        self.data_path = Path(data_path)
        self._report: Optional[MasterReport] = None

    # ------------------------------------------------------------------
    # safe_load
    # ------------------------------------------------------------------

    def safe_load(self, key: str) -> Optional[dict]:
        """
        Load the JSON file for *key* from the data directory.

        * Returns ``None`` if the file is missing or invalid JSON.
        * If the parsed value is a JSON array, returns the **last element**.
        * Returns ``None`` if the value (or last element) is not a dict.
        """
        src_path = self.DATA_SOURCES.get(key, "")
        if not src_path:
            return None
        # Strip leading "data/" prefix — data_path IS the data/ directory
        filename = src_path[len("data/"):] if src_path.startswith("data/") else src_path
        full_path = self.data_path / filename
        try:
            with open(full_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, list):
                if not data:
                    return None
                data = data[-1]
            if not isinstance(data, dict):
                return None
            return data
        except Exception:
            return None

    # ------------------------------------------------------------------
    # extract_module_status
    # ------------------------------------------------------------------

    def extract_module_status(self, key: str, data: Optional[dict]) -> ModuleStatus:
        """
        Derive a :class:`ModuleStatus` from raw loaded *data* for *key*.

        Each key has specific extraction logic for ``key_metric`` and
        ``status_level``.  When *data* is ``None`` the status is ``UNKNOWN``.
        """
        file_path = self.DATA_SOURCES.get(key, f"data/{key}.json")
        loaded = data is not None
        last_updated = _extract_timestamp(data)

        if not loaded:
            return ModuleStatus(
                name=key,
                file_path=file_path,
                loaded=False,
                key_metric="N/A",
                status_level=_STATUS_UNKNOWN,
                last_updated="unknown",
            )

        latest = _get_latest(data)

        # ----------------------------------------------------------------
        # Per-key extraction
        # ----------------------------------------------------------------

        if key == "benchmark":
            verdict = str(latest.get("verdict", "") or "").upper()
            apy = _safe_float(latest.get("portfolio_apy_pct"))
            key_metric = f"{verdict} ({apy:.2f}%)" if verdict else _STATUS_UNKNOWN
            if verdict in ("ALPHA+", "ALPHA"):
                status_level = _STATUS_GREEN
            elif verdict == "BENCHMARK":
                status_level = _STATUS_YELLOW
            elif verdict == "LAGGING":
                status_level = _STATUS_RED
            else:
                status_level = _STATUS_UNKNOWN

        elif key == "weekly":
            wv = str(latest.get("weekly_verdict", "") or "").upper()
            days = int(latest.get("days_covered", 0) or 0)
            key_metric = f"{wv} ({days} days)" if wv else _STATUS_UNKNOWN
            if wv in ("EXCELLENT", "GOOD"):
                status_level = _STATUS_GREEN
            elif wv == "FAIR":
                status_level = _STATUS_YELLOW
            elif wv == "POOR":
                status_level = _STATUS_RED
            else:
                status_level = _STATUS_UNKNOWN

        elif key == "risk":
            rl = str(latest.get("overall_level", "") or "").upper()
            score = _safe_float(latest.get("overall_score"))
            key_metric = f"{rl} (score {score:.2f})" if rl else _STATUS_UNKNOWN
            if rl == "GREEN":
                status_level = _STATUS_GREEN
            elif rl in ("YELLOW", "ORANGE"):
                status_level = _STATUS_YELLOW
            elif rl == "RED":
                status_level = _STATUS_RED
            else:
                status_level = _STATUS_UNKNOWN

        elif key == "rebalance":
            rec = str(latest.get("recommendation", "") or "").upper()
            apy_imp = _safe_float(latest.get("apy_improvement"))
            if rec and apy_imp > 0:
                key_metric = f"{rec} (+{apy_imp:.2f}%)"
            elif rec:
                key_metric = rec
            else:
                key_metric = _STATUS_UNKNOWN
            if rec == "HOLD":
                status_level = _STATUS_GREEN
            elif rec == "MONITOR":
                status_level = _STATUS_YELLOW
            elif rec == "REBALANCE":
                status_level = _STATUS_RED
            else:
                status_level = _STATUS_UNKNOWN

        elif key == "capital_efficiency":
            grade = str(latest.get("overall_grade", "") or "").upper()
            raroc = _safe_float(latest.get("portfolio_raroc"))
            key_metric = f"Grade {grade} (RAROC {raroc:.2f}x)" if grade else _STATUS_UNKNOWN
            if grade in ("A", "B"):
                status_level = _STATUS_GREEN
            elif grade == "C":
                status_level = _STATUS_YELLOW
            elif grade == "D":
                status_level = _STATUS_RED
            else:
                status_level = _STATUS_UNKNOWN

        elif key == "tier_exposure":
            ps = str(latest.get("policy_status", "") or "").upper()
            hhi = _safe_float(latest.get("hhi"))
            key_metric = f"{ps} (HHI {hhi:.3f})" if ps else _STATUS_UNKNOWN
            if ps == "COMPLIANT":
                status_level = _STATUS_GREEN
            elif ps == "BREACH":
                status_level = _STATUS_RED
            else:
                status_level = _STATUS_UNKNOWN

        elif key == "chain_exposure":
            ps = str(latest.get("policy_status", "") or "").upper()
            hhi = _safe_float(latest.get("hhi"))
            key_metric = f"{ps} (HHI {hhi:.3f})" if ps else _STATUS_UNKNOWN
            if ps == "COMPLIANT":
                status_level = _STATUS_GREEN
            elif ps == "BREACH":
                status_level = _STATUS_RED
            else:
                status_level = _STATUS_UNKNOWN

        elif key == "peg_monitor":
            # peg_report.json has overall_status at root level (no 'latest')
            os_raw = str(data.get("overall_status", "") or "").upper()
            worst = str(data.get("worst_adapter", "") or "")
            dev = _safe_float(data.get("worst_deviation_pct"))
            if worst and dev > 0:
                key_metric = f"{os_raw} ({worst} {dev:.2f}%)"
            elif os_raw:
                key_metric = os_raw
            else:
                key_metric = _STATUS_UNKNOWN
            if os_raw in (_STATUS_GREEN, _STATUS_YELLOW, _STATUS_RED):
                status_level = os_raw
            else:
                status_level = _STATUS_UNKNOWN

        elif key == "forecast":
            trend = str(latest.get("portfolio_trend", "") or "").upper()
            cur_apy = _safe_float(latest.get("portfolio_current_apy"))
            key_metric = f"{trend} (cur {cur_apy:.2f}%)" if trend else _STATUS_UNKNOWN
            if trend == "RISING":
                status_level = _STATUS_GREEN
            elif trend == "STABLE":
                status_level = _STATUS_YELLOW
            elif trend == "FALLING":
                status_level = _STATUS_RED
            else:
                status_level = _STATUS_UNKNOWN

        elif key == "attribution":
            apy = _safe_float(latest.get("effective_apy_pct"))
            alloc = _safe_float(latest.get("total_allocated_usd"))
            if alloc > 0:
                key_metric = f"APY {apy:.2f}% (${alloc / 1000:.0f}K)"
            else:
                key_metric = f"APY {apy:.2f}%"
            if apy > 0:
                status_level = _STATUS_GREEN
            elif alloc > 0:
                status_level = _STATUS_YELLOW
            else:
                status_level = _STATUS_UNKNOWN

        elif key == "stablecoin":
            contagion = str(latest.get("contagion_risk", "") or "").upper()
            dom_w = _safe_float(latest.get("dominant_weight_pct"))
            key_metric = f"Contagion:{contagion} ({dom_w:.1f}%)" if contagion else _STATUS_UNKNOWN
            if contagion in ("LOW", "NONE"):
                status_level = _STATUS_GREEN
            elif contagion == "MEDIUM":
                status_level = _STATUS_YELLOW
            elif contagion in ("HIGH", "CRITICAL"):
                status_level = _STATUS_RED
            else:
                status_level = _STATUS_UNKNOWN

        elif key == "concentration":
            # concentration_analytics.json has verdict at root level
            verdict = str(data.get("verdict", "") or "").upper()
            hhi = _safe_float(data.get("hhi_protocol"))
            key_metric = f"{verdict} (HHI {hhi:.3f})" if verdict else _STATUS_UNKNOWN
            if verdict in ("DIVERSIFIED", "OK", "GOOD"):
                status_level = _STATUS_GREEN
            elif verdict in ("MODERATE", "CONCENTRATED"):
                status_level = _STATUS_YELLOW
            elif verdict in ("HIGH", "CRITICAL", "BREACH", "FAIL"):
                status_level = _STATUS_RED
            else:
                status_level = _STATUS_UNKNOWN

        else:
            key_metric = _STATUS_UNKNOWN
            status_level = _STATUS_UNKNOWN

        return ModuleStatus(
            name=key,
            file_path=file_path,
            loaded=True,
            key_metric=key_metric,
            status_level=status_level,
            last_updated=last_updated,
        )

    # ------------------------------------------------------------------
    # Compute helpers
    # ------------------------------------------------------------------

    def compute_health_score(self, modules: List[ModuleStatus]) -> float:
        """
        Fraction of loaded modules with ``status_level == GREEN``.

        Returns 0.5 when no modules are loaded (neutral default).
        """
        loaded = [m for m in modules if m.loaded]
        if not loaded:
            return 0.5
        green_count = sum(1 for m in loaded if m.status_level == _STATUS_GREEN)
        return green_count / len(loaded)

    def compute_overall_health(
        self, modules: List[ModuleStatus], data: dict
    ) -> str:
        """
        Derive overall health label from module statuses.

        Rules (in priority order):
        * ``ALERT``     — any loaded module is RED
        * ``EXCELLENT`` — health_score ≥ 0.8 AND no YELLOW modules
        * ``GOOD``      — health_score ≥ 0.6
        * ``FAIR``      — otherwise
        """
        loaded = [m for m in modules if m.loaded]
        has_red = any(m.status_level == _STATUS_RED for m in loaded)
        if has_red:
            return _HEALTH_ALERT

        score = self.compute_health_score(modules)
        has_yellow = any(m.status_level == _STATUS_YELLOW for m in loaded)

        if score >= 0.8 and not has_yellow:
            return _HEALTH_EXCELLENT
        elif score >= 0.6:
            return _HEALTH_GOOD
        else:
            return _HEALTH_FAIR

    def generate_action_items(
        self, modules: List[ModuleStatus], data: dict
    ) -> List[str]:
        """
        Generate up to 5 concrete action items from module statuses.

        RED modules → domain-specific warning text.
        Selected YELLOW modules → advisory notes.
        """
        items: List[str] = []

        for m in modules:
            if len(items) >= 5:
                break
            if not m.loaded:
                continue

            if m.status_level == _STATUS_RED:
                if m.name == "tier_exposure":
                    items.append("⚠️ Policy BREACH: check tier exposure")
                elif m.name == "chain_exposure":
                    items.append("⚠️ Policy BREACH: check chain exposure")
                elif m.name == "rebalance":
                    items.append("⚠️ Rebalance required: REBALANCE signal active")
                elif m.name == "benchmark":
                    items.append("⚠️ Performance LAGGING: review allocation strategy")
                elif m.name == "peg_monitor":
                    items.append("⚠️ Peg issue detected: check stablecoin stability")
                elif m.name == "capital_efficiency":
                    items.append("⚠️ Low capital efficiency: review protocol allocation")
                elif m.name == "forecast":
                    items.append("⚠️ Yield FALLING: prepare defensive reallocation")
                elif m.name == "risk":
                    items.append("⚠️ Risk level RED: review portfolio immediately")
                elif m.name == "weekly":
                    items.append("⚠️ Weekly performance POOR: investigate degradation")
                else:
                    items.append(
                        f"⚠️ {m.name.replace('_', ' ').title()}: {m.key_metric}"
                    )

            elif m.status_level == _STATUS_YELLOW:
                if m.name == "rebalance":
                    items.append("Consider rebalancing: MONITOR signal")
                elif m.name == "risk":
                    items.append("Monitor risk level: elevated signals detected")
                elif m.name == "forecast":
                    items.append("Yield stable: watch for trend change")

        return items[:5]

    # ------------------------------------------------------------------
    # generate_report
    # ------------------------------------------------------------------

    def generate_report(self) -> MasterReport:
        """
        Build the full portfolio master report from all data sources.

        Loads all sources, extracts module statuses, computes health,
        and assembles a :class:`MasterReport` instance.
        """
        now = datetime.now(timezone.utc)
        generated_at = now.isoformat()

        # Load all sources
        loaded_data: Dict[str, Optional[dict]] = {
            key: self.safe_load(key) for key in self.DATA_SOURCES
        }

        # Attribution metrics
        attr = loaded_data.get("attribution") or {}
        attr_latest = _get_latest(attr) if isinstance(attr, dict) else {}
        portfolio_apy_pct = _safe_float(attr_latest.get("effective_apy_pct"))
        total_allocated_usd = _safe_float(attr_latest.get("total_allocated_usd"))

        # Build module statuses (preserve DATA_SOURCES order)
        modules: List[ModuleStatus] = [
            self.extract_module_status(key, loaded_data[key])
            for key in self.DATA_SOURCES
        ]

        modules_loaded = sum(1 for m in modules if m.loaded)
        modules_failed = sum(1 for m in modules if not m.loaded)

        # Extract aggregate verdicts
        bm = _get_latest(loaded_data.get("benchmark") or {})
        benchmark_verdict = str(bm.get("verdict", "UNKNOWN") or "UNKNOWN").upper()

        wk = _get_latest(loaded_data.get("weekly") or {})
        weekly_verdict = str(wk.get("weekly_verdict", "UNKNOWN") or "UNKNOWN").upper()

        rk = _get_latest(loaded_data.get("risk") or {})
        risk_level = str(rk.get("overall_level", "UNKNOWN") or "UNKNOWN").upper()

        rb = _get_latest(loaded_data.get("rebalance") or {})
        rebalance_recommendation = str(
            rb.get("recommendation", "UNKNOWN") or "UNKNOWN"
        ).upper()

        ce = _get_latest(loaded_data.get("capital_efficiency") or {})
        capital_grade = str(ce.get("overall_grade", "UNKNOWN") or "UNKNOWN").upper()

        te = _get_latest(loaded_data.get("tier_exposure") or {})
        tier_policy_status = str(te.get("policy_status", "UNKNOWN") or "UNKNOWN").upper()

        ch = _get_latest(loaded_data.get("chain_exposure") or {})
        chain_policy_status = str(ch.get("policy_status", "UNKNOWN") or "UNKNOWN").upper()

        pg = loaded_data.get("peg_monitor") or {}
        peg_status = str(pg.get("overall_status", "UNKNOWN") or "UNKNOWN").upper()

        fc = _get_latest(loaded_data.get("forecast") or {})
        forecast_trend = str(fc.get("portfolio_trend", "UNKNOWN") or "UNKNOWN").upper()

        # Compute health
        health_score = self.compute_health_score(modules)
        overall_health = self.compute_overall_health(modules, loaded_data)
        action_items = self.generate_action_items(modules, loaded_data)

        n_actions = len(action_items)
        summary = (
            f"APY {portfolio_apy_pct:.2f}%, {overall_health} health, "
            f"{n_actions} action item{'s' if n_actions != 1 else ''}"
        )

        self._report = MasterReport(
            generated_at=generated_at,
            portfolio_apy_pct=portfolio_apy_pct,
            total_allocated_usd=total_allocated_usd,
            modules=modules,
            modules_loaded=modules_loaded,
            modules_failed=modules_failed,
            benchmark_verdict=benchmark_verdict,
            weekly_verdict=weekly_verdict,
            risk_level=risk_level,
            rebalance_recommendation=rebalance_recommendation,
            capital_grade=capital_grade,
            tier_policy_status=tier_policy_status,
            chain_policy_status=chain_policy_status,
            peg_status=peg_status,
            forecast_trend=forecast_trend,
            overall_health=overall_health,
            health_score=health_score,
            action_items=action_items,
            summary=summary,
        )
        return self._report

    # ------------------------------------------------------------------
    # save_report
    # ------------------------------------------------------------------

    def save_report(self, report: Optional[MasterReport] = None) -> str:
        """
        Atomically save *report* to ``data/master_report.json``.

        Maintains a ring-buffer of up to 30 snapshots in ``history``.
        Generates the report first if *report* is None and none has been
        generated yet.

        Returns the path of the written file.
        """
        if report is None:
            if self._report is None:
                self.generate_report()
            report = self._report

        output_path = str(self.data_path / _OUTPUT_FILE)

        # Load existing ring buffer (fail-safe)
        existing: dict = {
            "schema_version": 1,
            "source": "full_portfolio_report",
            "ring_buffer_max": _RING_BUFFER_MAX,
            "report_count": 0,
            "last_updated": "",
            "latest": {},
            "history": [],
        }
        try:
            with open(output_path, "r", encoding="utf-8") as fh:
                loaded = json.load(fh)
            if isinstance(loaded, dict):
                existing = loaded
        except Exception:
            pass

        report_dict = self.to_dict(report)

        history: List[dict] = existing.get("history", [])
        if not isinstance(history, list):
            history = []
        history.append(report_dict)

        if len(history) > _RING_BUFFER_MAX:
            history = history[-_RING_BUFFER_MAX:]

        payload = {
            "schema_version": 1,
            "source": "full_portfolio_report",
            "ring_buffer_max": _RING_BUFFER_MAX,
            "report_count": len(history),
            "last_updated": report_dict["generated_at"],
            "latest": report_dict,
            "history": history,
        }

        # Atomic write: tmp file → os.replace
        out_dir = os.path.dirname(output_path) or "."
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=".tmp",
            dir=out_dir,
            delete=False,
        ) as tmp:
            json.dump(payload, tmp, indent=2, ensure_ascii=False)
            tmp_path = tmp.name

        os.replace(tmp_path, output_path)
        return output_path

    # ------------------------------------------------------------------
    # Formatting
    # ------------------------------------------------------------------

    def format_telegram_message(self, report: Optional[MasterReport] = None) -> str:
        """
        Format a Telegram-ready master report message ≤ 2 000 characters.

        Generates the report first if not yet generated.
        """
        if report is None:
            if self._report is None:
                self.generate_report()
            report = self._report

        health_emoji = _HEALTH_EMOJI.get(report.overall_health, "⚪")
        alloc_k = report.total_allocated_usd / 1000.0

        lines: List[str] = [
            f"📋 SPA Master Report — {report.overall_health}",
            f"APY: {report.portfolio_apy_pct:.2f}% | Capital: ${alloc_k:.0f}K",
            "",
        ]

        # Per-module status lines (skip attribution — already in header)
        for m in report.modules:
            if m.name == "attribution":
                continue
            emoji = _STATUS_EMOJI.get(m.status_level, "⚪")
            label = m.name.replace("_", " ").title()
            lines.append(f"{emoji} {label}: {m.key_metric}")

        lines.append("")

        # Action items
        if report.action_items:
            lines.append("Action items:")
            for item in report.action_items:
                lines.append(f"• {item}")
            lines.append("")

        lines.append(
            f"Modules: {report.modules_loaded}/"
            f"{report.modules_loaded + report.modules_failed} loaded"
        )
        lines.append(f"⏱ {report.generated_at[:19]}Z")

        msg = "\n".join(lines)
        if len(msg) > _TELEGRAM_MAX_CHARS:
            msg = msg[: _TELEGRAM_MAX_CHARS - 1] + "…"
        return msg

    # ------------------------------------------------------------------
    # to_dict
    # ------------------------------------------------------------------

    def to_dict(self, report: Optional[MasterReport] = None) -> dict:
        """Return *report* as a plain dict. Generates if not yet done."""
        if report is None:
            if self._report is None:
                self.generate_report()
            report = self._report
        return report.to_dict()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main(argv: Optional[List[str]] = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Full Portfolio Master Report (MP-621) — unified master snapshot."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        default=False,
        help="Compute and print without saving (default when no flag given).",
    )
    parser.add_argument(
        "--run",
        action="store_true",
        default=False,
        help="Compute and atomically save to data/master_report.json.",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        metavar="PATH",
        help="Override path to the data/ directory.",
    )
    args = parser.parse_args(argv)

    reporter = FullPortfolioReport(data_path=args.data_dir)
    report = reporter.generate_report()

    print(reporter.format_telegram_message(report))
    print("\n" + "=" * 60)
    print(report.summary)

    if args.run:
        path = reporter.save_report(report)
        print(f"\n[FullPortfolioReport] ✅ Saved → {path}")
    else:
        print(
            "\n[FullPortfolioReport] Check mode — no file written (use --run to save)."
        )


if __name__ == "__main__":
    main()
