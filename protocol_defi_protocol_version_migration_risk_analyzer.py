"""
MP-1113  ProtocolDeFiProtocolVersionMigrationRiskAnalyzer
==========================================================
Analyzes the **risk and opportunity** of migrating from an old protocol
version to a new one (e.g. Uniswap V2→V3, Aave V2→V3, Curve old→new
gauges). New versions often offer better APY, but migration incurs gas
costs, slippage, smart-contract risk, and opportunity cost.

Maturity score (0–100, int)
---------------------------
Three components:

* **Age score** (max 40 pts):
    ``age_score = min(40, round(new_version_age_days / 365 * 40))``
  Full score at ≥ 365 days on-chain; scales linearly below.

* **TVL score** (max 30 pts):
    ``tvl_score = min(30, round(min(tvl, 100_000_000) / 100_000_000 * 30))``
  Full score at ≥ $100 M TVL; scales linearly below.

* **Audit score** (max 30 pts):
    ``audit_score = min(30, new_version_audit_count * 10)``
  Full score at ≥ 3 completed audits.

``new_version_maturity_score = min(100, age_score + tvl_score + audit_score)``

Migration payback and net gain
-------------------------------
::

    daily_gain_usd   = position_size_usd * apy_improvement_pct / 100 / 365
    migration_payback_days = migration_cost_usd / daily_gain_usd
                             (inf when apy_improvement_pct ≤ 0 or position = 0)
    net_gain_usd = position_size_usd * apy_improvement_pct / 100
                   / 365 * holding_days  -  migration_cost_usd

Recommendation labels (evaluated in priority order)
----------------------------------------------------
1. ``apy_improvement_pct ≤ 0``                              → STAY_OLD_VERSION
2. ``net_gain > 0 AND maturity ≥ 70 AND payback < holding/2`` → MIGRATE_NOW
3. ``net_gain > 0 AND maturity ≥ 50``                       → MIGRATE_SOON
4. ``net_gain > 0 AND maturity < 50``                       → WAIT_FOR_MATURITY
5. ``net_gain ≤ 0 AND apy_improvement > 0``                 → NOT_WORTH_IT

Log file: data/protocol_version_migration_risk_log.json (ring-buffer, cap 100).

Advisory / read-only. Pure stdlib. Atomic ring-buffer JSON log (cap 100).
"""

from __future__ import annotations

import json
import math
import os
import tempfile
import time
from typing import Any, Dict, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_LOG_PATH = os.path.join(
    os.path.dirname(__file__),
    "..",
    "..",
    "data",
    "protocol_version_migration_risk_log.json",
)
_LOG_CAP = 100

# Maturity score caps per component
_AGE_MAX_SCORE = 40
_TVL_MAX_SCORE = 30
_AUDIT_MAX_SCORE = 30
_AGE_FULL_DAYS = 365
_TVL_FULL_USD = 100_000_000.0  # $100 M
_AUDIT_PTS_EACH = 10           # 10 pts per audit, capped at _AUDIT_MAX_SCORE

# Recommendation thresholds
_MATURITY_MIGRATE_NOW = 70
_MATURITY_MIGRATE_SOON = 50
_INF_PAYBACK = float("inf")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _compute_maturity_score(
    age_days: int,
    tvl_usd: float,
    audit_count: int,
) -> int:
    """
    Compute new-version maturity score (0–100).

    Parameters
    ----------
    age_days    : int    Days since new version launched
    tvl_usd     : float  TVL in USD of the new version
    audit_count : int    Number of completed security audits
    """
    age_days = max(0, int(age_days))
    tvl_usd = max(0.0, float(tvl_usd))
    audit_count = max(0, int(audit_count))

    age_score = min(_AGE_MAX_SCORE, round(age_days / _AGE_FULL_DAYS * _AGE_MAX_SCORE))
    tvl_score = min(
        _TVL_MAX_SCORE,
        round(min(tvl_usd, _TVL_FULL_USD) / _TVL_FULL_USD * _TVL_MAX_SCORE),
    )
    audit_score = min(_AUDIT_MAX_SCORE, audit_count * _AUDIT_PTS_EACH)

    return min(100, age_score + tvl_score + audit_score)


def _compute_payback_days(
    migration_cost_usd: float,
    position_size_usd: float,
    apy_improvement_pct: float,
) -> float:
    """
    Days to recoup migration cost from extra daily yield.

    Returns ``math.inf`` if improvement ≤ 0 or position is 0.
    """
    if apy_improvement_pct <= 0.0 or position_size_usd <= 0.0:
        return _INF_PAYBACK
    daily_gain = position_size_usd * apy_improvement_pct / 100.0 / 365.0
    if daily_gain <= 0.0:
        return _INF_PAYBACK
    return migration_cost_usd / daily_gain


def _compute_net_gain(
    position_size_usd: float,
    apy_improvement_pct: float,
    holding_days: int,
    migration_cost_usd: float,
) -> float:
    """Net USD gain over the holding period after subtracting migration cost."""
    gross = position_size_usd * apy_improvement_pct / 100.0 / 365.0 * holding_days
    return gross - migration_cost_usd


def _recommend(
    apy_improvement_pct: float,
    net_gain_usd: float,
    maturity_score: int,
    payback_days: float,
    holding_days: int,
) -> str:
    """
    Return migration recommendation string.
    Evaluated in strict priority order (see module docstring).
    """
    if apy_improvement_pct <= 0.0:
        return "STAY_OLD_VERSION"

    if net_gain_usd > 0.0:
        half_holding = holding_days / 2.0
        if (
            maturity_score >= _MATURITY_MIGRATE_NOW
            and (payback_days < half_holding or math.isinf(payback_days) is False
                 and payback_days < half_holding)
        ):
            # Extra guard: payback must be finite AND < half holding
            if not math.isinf(payback_days) and payback_days < half_holding:
                return "MIGRATE_NOW"
        if maturity_score >= _MATURITY_MIGRATE_SOON:
            return "MIGRATE_SOON"
        return "WAIT_FOR_MATURITY"

    # net_gain_usd <= 0 but apy_improvement > 0
    return "NOT_WORTH_IT"


def _atomic_log(log_path: str, entry: dict) -> None:
    """Append entry to ring-buffer JSON array (cap=_LOG_CAP), atomic write."""
    abs_path = os.path.abspath(log_path)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)

    try:
        with open(abs_path, "r", encoding="utf-8") as fh:
            data: list = json.load(fh)
        if not isinstance(data, list):
            data = []
    except (FileNotFoundError, json.JSONDecodeError):
        data = []

    data.append(entry)
    if len(data) > _LOG_CAP:
        data = data[-_LOG_CAP:]

    dir_name = os.path.dirname(abs_path)
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp_path, abs_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class ProtocolDeFiProtocolVersionMigrationRiskAnalyzer:
    """
    Analyzes risk and opportunity of migrating between protocol versions.

    Usage
    -----
    ::

        analyzer = ProtocolDeFiProtocolVersionMigrationRiskAnalyzer()
        result = analyzer.analyze({
            "old_version_apy_pct": 4.0,
            "new_version_apy_pct": 6.5,
            "migration_cost_usd": 150.0,
            "new_version_audit_count": 3,
            "new_version_age_days": 400,
            "new_version_tvl_usd": 80_000_000.0,
            "old_version_tvl_usd": 200_000_000.0,
            "position_size_usd": 50_000.0,
            "holding_days": 180,
            "protocol_name": "Aave",
        })
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(
        self,
        data: Dict[str, Any],
        config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Analyze migration risk/opportunity for a single protocol upgrade.

        Parameters
        ----------
        data : dict
            Required keys:
                old_version_apy_pct       float
                new_version_apy_pct       float
                migration_cost_usd        float  gas + slippage
                new_version_audit_count   int    security audits completed
                new_version_age_days      int    days since new version launched
                new_version_tvl_usd       float
                old_version_tvl_usd       float
                position_size_usd         float
                holding_days              int
                protocol_name             str

        config : dict, optional
            write_log  bool  Whether to write to log file (default True)
            log_path   str   Override log file path

        Returns
        -------
        dict with keys:
            protocol_name                str
            old_version_apy_pct          float
            new_version_apy_pct          float
            apy_improvement_pct          float
            migration_cost_usd           float
            new_version_audit_count      int
            new_version_age_days         int
            new_version_tvl_usd          float
            old_version_tvl_usd          float
            position_size_usd            float
            holding_days                 int
            migration_payback_days       float  (inf when not beneficial)
            net_gain_usd                 float
            new_version_maturity_score   int
            migration_recommendation     str
            timestamp                    float
        """
        if config is None:
            config = {}

        # -- Extract and coerce inputs ----------------------------------
        old_apy = float(data.get("old_version_apy_pct", 0.0))
        new_apy = float(data.get("new_version_apy_pct", 0.0))
        migration_cost = float(data.get("migration_cost_usd", 0.0))
        audit_count = int(data.get("new_version_audit_count", 0))
        age_days = int(data.get("new_version_age_days", 0))
        new_tvl = float(data.get("new_version_tvl_usd", 0.0))
        old_tvl = float(data.get("old_version_tvl_usd", 0.0))
        position_size = float(data.get("position_size_usd", 0.0))
        holding_days = int(data.get("holding_days", 0))
        protocol_name = str(data.get("protocol_name", "unknown"))

        # Sanity guards
        migration_cost = max(0.0, migration_cost)
        audit_count = max(0, audit_count)
        age_days = max(0, age_days)
        new_tvl = max(0.0, new_tvl)
        old_tvl = max(0.0, old_tvl)
        position_size = max(0.0, position_size)
        holding_days = max(0, holding_days)

        # -- Core calculations -----------------------------------------
        apy_improvement_pct = round(new_apy - old_apy, 6)

        payback_days = _compute_payback_days(migration_cost, position_size, apy_improvement_pct)

        net_gain_usd = _compute_net_gain(
            position_size, apy_improvement_pct, holding_days, migration_cost
        )

        maturity_score = _compute_maturity_score(age_days, new_tvl, audit_count)

        recommendation = _recommend(
            apy_improvement_pct, net_gain_usd, maturity_score, payback_days, holding_days
        )

        # -- Build result ----------------------------------------------
        ts = time.time()

        # Serialize payback: inf is not JSON-native → store as null-sentinel
        payback_serializable: Any = (
            None if math.isinf(payback_days) else round(payback_days, 6)
        )

        result: Dict[str, Any] = {
            "protocol_name": protocol_name,
            "old_version_apy_pct": round(old_apy, 6),
            "new_version_apy_pct": round(new_apy, 6),
            "apy_improvement_pct": apy_improvement_pct,
            "migration_cost_usd": round(migration_cost, 6),
            "new_version_audit_count": audit_count,
            "new_version_age_days": age_days,
            "new_version_tvl_usd": round(new_tvl, 6),
            "old_version_tvl_usd": round(old_tvl, 6),
            "position_size_usd": round(position_size, 6),
            "holding_days": holding_days,
            "migration_payback_days": payback_serializable,
            "net_gain_usd": round(net_gain_usd, 6),
            "new_version_maturity_score": maturity_score,
            "migration_recommendation": recommendation,
            "timestamp": ts,
        }

        # -- Ring-buffer log ------------------------------------------
        write_log = config.get("write_log", True)
        if write_log:
            log_path = config.get("log_path", _LOG_PATH)
            try:
                _atomic_log(
                    log_path,
                    {
                        "timestamp": ts,
                        "protocol_name": protocol_name,
                        "apy_improvement_pct": apy_improvement_pct,
                        "net_gain_usd": round(net_gain_usd, 4),
                        "maturity_score": maturity_score,
                        "migration_recommendation": recommendation,
                    },
                )
            except Exception:
                pass  # advisory: never block caller

        return result

    # ------------------------------------------------------------------
    # Convenience: batch mode
    # ------------------------------------------------------------------

    def analyze_batch(
        self,
        migrations: list,
        config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Analyze a list of migration opportunities.

        Parameters
        ----------
        migrations : list[dict]
            Each element is a ``data`` dict as accepted by ``analyze()``.
        config : dict, optional
            Same as ``analyze()``; write_log controls logging per call.

        Returns
        -------
        dict with keys:
            results      list[dict]  per-migration analysis
            summary      dict        aggregated stats
            timestamp    float
        """
        if config is None:
            config = {}
        if not isinstance(migrations, list):
            raise TypeError("migrations must be a list")

        results = [self.analyze(m, config) for m in migrations]

        if results:
            recommendations = [r["migration_recommendation"] for r in results]
            net_gains = [r["net_gain_usd"] for r in results]
            improvements = [r["apy_improvement_pct"] for r in results]
            scores = [r["new_version_maturity_score"] for r in results]

            summary: Dict[str, Any] = {
                "count": len(results),
                "migrate_now_count": recommendations.count("MIGRATE_NOW"),
                "migrate_soon_count": recommendations.count("MIGRATE_SOON"),
                "not_worth_it_count": recommendations.count("NOT_WORTH_IT"),
                "stay_old_count": recommendations.count("STAY_OLD_VERSION"),
                "wait_maturity_count": recommendations.count("WAIT_FOR_MATURITY"),
                "avg_apy_improvement_pct": round(
                    sum(improvements) / len(improvements), 6
                ),
                "total_net_gain_usd": round(sum(net_gains), 6),
                "avg_maturity_score": round(sum(scores) / len(scores), 2),
            }
        else:
            summary = {
                "count": 0,
                "migrate_now_count": 0,
                "migrate_soon_count": 0,
                "not_worth_it_count": 0,
                "stay_old_count": 0,
                "wait_maturity_count": 0,
                "avg_apy_improvement_pct": 0.0,
                "total_net_gain_usd": 0.0,
                "avg_maturity_score": 0.0,
            }

        return {
            "results": results,
            "summary": summary,
            "timestamp": time.time(),
        }
