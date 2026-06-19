"""
spa_core/analytics/paper_backtest_drift_v2.py

Compares paper trading NAV with the expected trajectory derived from backtest.
CPA-methodology: drift = deviation from backtest baseline.

Drift metrics
─────────────
- nav_drift_pct  : (paper_nav - backtest_expected_nav) / backtest_expected_nav * 100
- apy_drift      : paper_apy - backtest_apy  (percentage points)
- allocation_drift: KL-divergence between actual and expected allocation
- source_drift   : sources absent in paper vs backtest

Alerts
──────
- WARN     if |nav_drift_pct| > 2 %
- CRITICAL if |nav_drift_pct| > 5 %
- WARN     if apy_drift < -2 % (paper underperforms backtest)

Design constraints
──────────────────
- stdlib only (no external dependencies)
- atomic writes: tmp + os.replace
- ring-buffer cap = 100 daily records
- LLM_FORBIDDEN (monitoring component)
"""

import json
import math
import os
import tempfile
from datetime import datetime, timezone
from typing import Dict, List, Optional

__all__ = ["PaperBacktestDriftV2"]

_RING_CAP = 100
_WARN_DRIFT_PCT = 2.0
_CRITICAL_DRIFT_PCT = 5.0
_WARN_APY_UNDERPERFORM = -2.0  # paper_apy - backtest_apy


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _kl_divergence(p: Dict[str, float], q: Dict[str, float]) -> float:
    """
    Symmetric KL-divergence (Jensen-Shannon style sum) between two allocation
    dicts.  Missing keys are treated as ε to avoid log(0).
    Returns 0.0 if both dicts are empty.
    """
    eps = 1e-9
    keys = set(p) | set(q)
    if not keys:
        return 0.0
    total = 0.0
    for k in keys:
        pv = p.get(k, 0.0) + eps
        qv = q.get(k, 0.0) + eps
        total += pv * math.log(pv / qv)
    return max(0.0, total)


def _normalise(d: Dict[str, float]) -> Dict[str, float]:
    """Normalise allocation dict so values sum to 1.0."""
    s = sum(d.values())
    if s <= 0:
        return {k: 0.0 for k in d}
    return {k: v / s for k, v in d.items()}


def _expected_nav(initial_nav: float, backtest_apy: float, days: int) -> float:
    """
    Expected NAV after *days* at a constant daily rate derived from backtest_apy.
    backtest_apy is a decimal fraction (e.g. 0.068 for 6.8 %).
    Formula: NAV * (1 + apy/365) ** days
    """
    daily_rate = backtest_apy / 365.0
    return initial_nav * ((1.0 + daily_rate) ** days)


# ─────────────────────────────────────────────────────────────────────────────
# Main class
# ─────────────────────────────────────────────────────────────────────────────

class PaperBacktestDriftV2:
    """
    CPA paper-vs-backtest drift tracker.

    Parameters
    ----------
    backtest_apy : float
        Expected annualised yield from backtest as a *decimal fraction*
        (e.g. 0.068 for 6.8 %).  Defaults to 0.0 (flat baseline).
    initial_nav : float
        Starting paper NAV in USD.  Default $100,000.
    backtest_expected_allocations : dict, optional
        Protocol → weight (decimal, 0–1) mapping from backtest.
        Used for allocation_drift (KL-divergence).
    backtest_sources : list, optional
        Protocol identifiers that provided yield data in the backtest.
        Used for source_drift.
    """

    def __init__(
        self,
        backtest_apy: float = 0.0,
        initial_nav: float = 100_000.0,
        backtest_expected_allocations: Optional[Dict[str, float]] = None,
        backtest_sources: Optional[List[str]] = None,
    ) -> None:
        self.backtest_apy = float(backtest_apy)
        self.initial_nav = float(initial_nav)
        self.backtest_expected_allocations: Dict[str, float] = (
            _normalise(dict(backtest_expected_allocations))
            if backtest_expected_allocations
            else {}
        )
        self.backtest_sources: List[str] = list(backtest_sources or [])

        # Ring-buffer of daily records (cap = _RING_CAP)
        self._records: List[Dict] = []

        # Week accumulator for weekly_drift_report
        self._week_navs: List[float] = []
        self._week_drifts: List[float] = []

    # ─────────────────────────────────────────────────────────────────────────
    # Core drift calculations
    # ─────────────────────────────────────────────────────────────────────────

    def nav_drift(self, paper_nav: float, days_elapsed: int) -> float:
        """
        Returns nav_drift_pct = (paper_nav - expected_nav) / expected_nav * 100.
        Returns 0.0 if days_elapsed <= 0 (no baseline yet).
        """
        if days_elapsed <= 0:
            return 0.0
        expected = _expected_nav(self.initial_nav, self.backtest_apy, days_elapsed)
        if expected == 0.0:
            return 0.0
        return (paper_nav - expected) / expected * 100.0

    def drift_alert(self, drift_pct: float) -> str:
        """
        Returns 'OK', 'WARN', or 'CRITICAL' based on |drift_pct|.

        Thresholds:
          |drift_pct| <= 2 %  → 'OK'
          2 < |drift_pct| <= 5 % → 'WARN'
          |drift_pct| > 5 %   → 'CRITICAL'

        Note: negative apy_drift is handled separately in record_paper_day.
        """
        abs_drift = abs(drift_pct)
        if abs_drift > _CRITICAL_DRIFT_PCT:
            return "CRITICAL"
        if abs_drift > _WARN_DRIFT_PCT:
            return "WARN"
        return "OK"

    def allocation_drift(self, actual_allocations: Dict[str, float]) -> float:
        """
        KL-divergence between paper allocation and backtest expected allocation.
        Returns 0.0 if no backtest_expected_allocations were provided.
        """
        if not self.backtest_expected_allocations:
            return 0.0
        normalised_actual = _normalise(dict(actual_allocations))
        return _kl_divergence(normalised_actual, self.backtest_expected_allocations)

    def source_drift(self, sources_used: List[str]) -> List[str]:
        """
        Returns list of backtest sources missing in this paper day.
        Empty list → no source drift.
        """
        if not self.backtest_sources:
            return []
        used_set = set(sources_used)
        return [s for s in self.backtest_sources if s not in used_set]

    # ─────────────────────────────────────────────────────────────────────────
    # Daily recording
    # ─────────────────────────────────────────────────────────────────────────

    def record_paper_day(
        self,
        date: str,
        paper_nav: float,
        allocations: Dict[str, float],
        sources_used: List[str],
    ) -> Dict:
        """
        Records a paper day and returns a drift metrics dict.

        Parameters
        ----------
        date          : ISO date string, e.g. '2026-06-19'
        paper_nav     : Paper NAV in USD at end-of-day
        allocations   : Protocol → weight mapping for today's paper positions
        sources_used  : List of protocol/source IDs that supplied yield data today

        Returns
        -------
        dict with keys:
            date, paper_nav, expected_nav, days_elapsed,
            nav_drift_pct, nav_alert, apy_drift, apy_alert,
            allocation_drift_kl, source_drift_missing
        """
        days_elapsed = len(self._records) + 1  # 1-indexed

        # Expected NAV at this point
        expected = _expected_nav(self.initial_nav, self.backtest_apy, days_elapsed)

        # NAV drift
        nav_drift_pct = self.nav_drift(paper_nav, days_elapsed)
        nav_alert = self.drift_alert(nav_drift_pct)

        # Approximate paper APY from running NAV (annualised)
        if days_elapsed > 0 and self.initial_nav > 0:
            paper_apy = ((paper_nav / self.initial_nav) ** (365.0 / days_elapsed) - 1.0)
        else:
            paper_apy = 0.0

        apy_drift = paper_apy - self.backtest_apy
        apy_alert = "WARN" if apy_drift < (_WARN_APY_UNDERPERFORM / 100.0) else "OK"

        # Allocation drift (KL)
        alloc_drift_kl = self.allocation_drift(allocations)

        # Source drift
        missing_sources = self.source_drift(sources_used)

        record = {
            "date": date,
            "paper_nav": round(paper_nav, 4),
            "expected_nav": round(expected, 4),
            "days_elapsed": days_elapsed,
            "nav_drift_pct": round(nav_drift_pct, 6),
            "nav_alert": nav_alert,
            "apy_drift": round(apy_drift, 6),
            "apy_alert": apy_alert,
            "allocation_drift_kl": round(alloc_drift_kl, 6),
            "source_drift_missing": missing_sources,
        }

        # Ring-buffer append with cap
        self._records.append(record)
        if len(self._records) > _RING_CAP:
            self._records = self._records[-_RING_CAP:]

        # Week accumulators
        self._week_navs.append(paper_nav)
        self._week_drifts.append(nav_drift_pct)

        return record

    # ─────────────────────────────────────────────────────────────────────────
    # Weekly report
    # ─────────────────────────────────────────────────────────────────────────

    def weekly_drift_report(self) -> Dict:
        """
        Returns a weekly summary dict with drift, alerts, and recommendations.

        Keys guaranteed to be present:
            week_records, avg_nav_drift_pct, max_nav_drift_pct,
            min_nav_drift_pct, drift_alert, apy_drift_avg,
            critical_days, warn_days, ok_days,
            total_days_tracked, recommendations, generated_at
        """
        if not self._records:
            return {
                "week_records": 0,
                "avg_nav_drift_pct": 0.0,
                "max_nav_drift_pct": 0.0,
                "min_nav_drift_pct": 0.0,
                "drift_alert": "OK",
                "apy_drift_avg": 0.0,
                "critical_days": 0,
                "warn_days": 0,
                "ok_days": 0,
                "total_days_tracked": 0,
                "recommendations": ["No records yet — begin recording paper days."],
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }

        recent = self._records[-7:]
        drifts = [r["nav_drift_pct"] for r in recent]
        apy_drifts = [r["apy_drift"] for r in recent]

        avg_drift = sum(drifts) / len(drifts)
        max_drift = max(drifts)
        min_drift = min(drifts)
        avg_apy_drift = sum(apy_drifts) / len(apy_drifts)

        critical_days = sum(1 for r in recent if r["nav_alert"] == "CRITICAL")
        warn_days     = sum(1 for r in recent if r["nav_alert"] == "WARN")
        ok_days       = sum(1 for r in recent if r["nav_alert"] == "OK")

        # Overall week alert level
        if critical_days > 0:
            week_alert = "CRITICAL"
        elif warn_days > 0:
            week_alert = "WARN"
        else:
            week_alert = "OK"

        # Recommendations
        recs: List[str] = []
        if week_alert == "CRITICAL":
            recs.append("CRITICAL drift detected — review allocations and risk blocks immediately.")
        if avg_apy_drift < (_WARN_APY_UNDERPERFORM / 100.0):
            recs.append("Paper APY underperforming backtest baseline — check adapter health and T2 caps.")
        if any(r["source_drift_missing"] for r in recent):
            missing = set()
            for r in recent:
                missing.update(r["source_drift_missing"])
            recs.append(f"Missing backtest sources in paper: {', '.join(sorted(missing))}.")
        if any(r["allocation_drift_kl"] > 0.1 for r in recent):
            recs.append("High allocation drift (KL > 0.1) — portfolio diverging from backtest target.")
        if not recs:
            recs.append("Drift within tolerance — paper track nominal.")

        return {
            "week_records": len(recent),
            "avg_nav_drift_pct": round(avg_drift, 4),
            "max_nav_drift_pct": round(max_drift, 4),
            "min_nav_drift_pct": round(min_drift, 4),
            "drift_alert": week_alert,
            "apy_drift_avg": round(avg_apy_drift, 6),
            "critical_days": critical_days,
            "warn_days": warn_days,
            "ok_days": ok_days,
            "total_days_tracked": len(self._records),
            "recommendations": recs,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Persistence
    # ─────────────────────────────────────────────────────────────────────────

    def save(self, path: str = "data/paper/drift_v2.json") -> None:
        """
        Atomically saves the current state to *path*.
        Directory is created if absent.
        """
        os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)

        payload = {
            "schema_version": "2.0",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "config": {
                "backtest_apy": self.backtest_apy,
                "initial_nav": self.initial_nav,
                "backtest_expected_allocations": self.backtest_expected_allocations,
                "backtest_sources": self.backtest_sources,
            },
            "ring_buffer_cap": _RING_CAP,
            "total_days_tracked": len(self._records),
            "records": self._records,
        }

        dir_name = os.path.dirname(os.path.abspath(path))
        fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2)
            os.replace(tmp_path, path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    @classmethod
    def load(cls, path: str = "data/paper/drift_v2.json") -> "PaperBacktestDriftV2":
        """
        Loads a previously saved state from *path*.
        Returns a new default instance if the file is absent or malformed.
        """
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (FileNotFoundError, json.JSONDecodeError):
            return cls()

        cfg = data.get("config", {})
        instance = cls(
            backtest_apy=cfg.get("backtest_apy", 0.0),
            initial_nav=cfg.get("initial_nav", 100_000.0),
            backtest_expected_allocations=cfg.get("backtest_expected_allocations"),
            backtest_sources=cfg.get("backtest_sources"),
        )
        instance._records = data.get("records", [])[-_RING_CAP:]
        return instance
