"""
MP-935 ProtocolEcosystemHealthScorecard
-----------------------------------------
Comprehensive ecosystem health scoring for DeFi protocols.

Each protocol dict:
    name                    str
    tvl_usd                 float
    tvl_30d_change_pct      float    e.g. +15.0 = +15%
    daily_active_users      int
    dau_30d_change_pct      float
    revenue_monthly_usd     float
    token_price_change_30d_pct  float
    github_commits_30d      int
    audit_count             int
    incident_count_12m      int
    community_score         float    0-100
    developer_count         int
    integrations_count      int
    chain_count             int

5 sub-scores (each 0-100):
    financial_health    (weight 30%): TVL + TVL trend + revenue + token price
    user_adoption       (weight 25%): DAU + DAU growth
    security_posture    (weight 20%): audits + incidents
    developer_activity  (weight 15%): commits + dev_count + integrations
    ecosystem_reach     (weight 10%): chains + community + integrations

composite_score (0-100) = weighted sum of sub-scores

Health label: THRIVING (>=80) / HEALTHY (>=65) / STABLE (>=50) / DECLINING (>=35) / CRITICAL (<35)

Flags:
    ALL_METRICS_POSITIVE    all 5 sub-scores > 70
    SECURITY_CONCERN        security_posture < 40
    DEVELOPER_EXODUS        github_commits_30d < 30 AND developer_count < 5
    VIRAL_ADOPTION          dau_30d_change_pct > 50
    TVL_DOMINANCE           tvl_usd > 1_000_000_000

Aggregates:
    healthiest_protocol, most_critical, average_composite,
    thriving_count, critical_count, ecosystem_composite_score

Ring-buffer log → data/ecosystem_health_log.json (cap 100, atomic write).
Advisory / read-only. Pure stdlib.
"""

from __future__ import annotations

import json
import math
import os
import time
from typing import Any
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_LOG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "ecosystem_health_log.json"
)
_LOG_CAP = 100

# Sub-score weights
_W_FINANCIAL  = 0.30
_W_ADOPTION   = 0.25
_W_SECURITY   = 0.20
_W_DEVELOPER  = 0.15
_W_ECOSYSTEM  = 0.10

# Health label thresholds
_THRIVING  = 80.0
_HEALTHY   = 65.0
_STABLE    = 50.0
_DECLINING = 35.0

# Flag thresholds
_ALL_METRICS_THRESHOLD     = 70.0
_SECURITY_CONCERN_THRESH   = 40.0
_DEV_EXODUS_COMMITS_MAX    = 30
_DEV_EXODUS_DEVCOUNT_MAX   = 5
_VIRAL_ADOPTION_THRESH     = 50.0
_TVL_DOMINANCE_THRESH      = 1_000_000_000.0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def _log_scale_score(value: float, lo: float, hi: float) -> float:
    """Map value logarithmically to [0, 100] within [lo, hi]."""
    if value <= 0.0 or lo <= 0.0:
        return 0.0
    log_lo = math.log10(lo)
    log_hi = math.log10(hi)
    log_v  = math.log10(max(lo, min(hi, value)))
    if log_hi == log_lo:
        return 100.0
    return _clamp(((log_v - log_lo) / (log_hi - log_lo)) * 100.0)


def _atomic_log(log_path: str, entry: dict) -> None:
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
    atomic_save(data, str(abs_path))
def _health_label(composite: float) -> str:
    if composite >= _THRIVING:
        return "THRIVING"
    if composite >= _HEALTHY:
        return "HEALTHY"
    if composite >= _STABLE:
        return "STABLE"
    if composite >= _DECLINING:
        return "DECLINING"
    return "CRITICAL"


# ---------------------------------------------------------------------------
# Sub-score calculators
# ---------------------------------------------------------------------------

def _financial_health(p: dict) -> float:
    """TVL base (log 100K–10B) + TVL trend ± bonus + revenue (log 10K–100M) + token price ± bonus."""
    tvl         = float(p.get("tvl_usd", 0.0))
    tvl_chg     = float(p.get("tvl_30d_change_pct", 0.0))
    revenue     = float(p.get("revenue_monthly_usd", 0.0))
    tok_chg     = float(p.get("token_price_change_30d_pct", 0.0))

    # TVL component (0-60)
    tvl_base = _log_scale_score(tvl, 1e5, 1e10) * 0.60   # 0-60

    # TVL trend bonus (-12 to +12)
    if tvl_chg >= 30.0:
        tvl_trend = 12.0
    elif tvl_chg >= 10.0:
        tvl_trend = 8.0
    elif tvl_chg >= 0.0:
        tvl_trend = 3.0
    elif tvl_chg >= -15.0:
        tvl_trend = -6.0
    else:
        tvl_trend = -12.0

    # Revenue component (0-20)
    rev_base = _log_scale_score(revenue, 1e4, 1e8) * 0.20  # 0-20

    # Token price bonus (-8 to +8)
    if tok_chg >= 50.0:
        tok_bonus = 8.0
    elif tok_chg >= 10.0:
        tok_bonus = 4.0
    elif tok_chg >= -10.0:
        tok_bonus = 0.0
    elif tok_chg >= -30.0:
        tok_bonus = -4.0
    else:
        tok_bonus = -8.0

    score = tvl_base + tvl_trend + rev_base + tok_bonus
    return _clamp(score)


def _user_adoption(p: dict) -> float:
    """DAU (log 10–1M) base + DAU growth bonus."""
    dau     = float(p.get("daily_active_users", 0.0))
    dau_chg = float(p.get("dau_30d_change_pct", 0.0))

    # DAU base (0-70)
    dau_base = _log_scale_score(dau, 10.0, 1_000_000.0) * 0.70

    # Growth bonus (-30 to +30)
    if dau_chg >= 50.0:
        growth = 30.0
    elif dau_chg >= 20.0:
        growth = 20.0
    elif dau_chg >= 5.0:
        growth = 10.0
    elif dau_chg >= -10.0:
        growth = 0.0
    elif dau_chg >= -30.0:
        growth = -15.0
    else:
        growth = -30.0

    score = dau_base + growth
    return _clamp(score)


def _security_posture(p: dict) -> float:
    """Audits (0-60) + incidents penalty (0-40)."""
    audits    = int(p.get("audit_count", 0))
    incidents = int(p.get("incident_count_12m", 0))

    # Audit score (0-60)
    if audits == 0:
        audit_s = 0.0
    elif audits == 1:
        audit_s = 30.0
    elif audits == 2:
        audit_s = 45.0
    elif audits == 3:
        audit_s = 54.0
    else:
        audit_s = 60.0

    # Incident score (0-40): 0 incidents = 40, penalised per incident
    if incidents == 0:
        inc_s = 40.0
    elif incidents == 1:
        inc_s = 24.0
    elif incidents == 2:
        inc_s = 10.0
    else:
        inc_s = 0.0

    return _clamp(audit_s + inc_s)


def _developer_activity(p: dict) -> float:
    """Commits (0-40) + dev_count (0-40) + integrations (0-20)."""
    commits      = int(p.get("github_commits_30d", 0))
    dev_count    = int(p.get("developer_count", 0))
    integrations = int(p.get("integrations_count", 0))

    # Commits sub-score (0-40)
    if commits >= 500:
        c_s = 40.0
    elif commits >= 200:
        c_s = 32.0
    elif commits >= 100:
        c_s = 24.0
    elif commits >= 50:
        c_s = 16.0
    elif commits > 0:
        c_s = 8.0
    else:
        c_s = 0.0

    # Dev count sub-score (0-40)
    if dev_count >= 100:
        d_s = 40.0
    elif dev_count >= 50:
        d_s = 32.0
    elif dev_count >= 20:
        d_s = 24.0
    elif dev_count >= 10:
        d_s = 16.0
    elif dev_count > 0:
        d_s = 8.0
    else:
        d_s = 0.0

    # Integrations sub-score (0-20)
    if integrations >= 50:
        i_s = 20.0
    elif integrations >= 20:
        i_s = 16.0
    elif integrations >= 10:
        i_s = 12.0
    elif integrations >= 5:
        i_s = 8.0
    else:
        i_s = 4.0

    return _clamp(c_s + d_s + i_s)


def _ecosystem_reach(p: dict) -> float:
    """Chains (0-30) + community_score (0-40) + integrations (0-30)."""
    chains       = int(p.get("chain_count", 0))
    community    = _clamp(float(p.get("community_score", 0.0)))
    integrations = int(p.get("integrations_count", 0))

    # Chains sub-score (0-30)
    if chains >= 10:
        ch_s = 30.0
    elif chains >= 5:
        ch_s = 24.0
    elif chains >= 3:
        ch_s = 18.0
    elif chains >= 2:
        ch_s = 12.0
    elif chains == 1:
        ch_s = 6.0
    else:
        ch_s = 0.0

    # Community (already 0-100) scaled to 0-40
    com_s = community * 0.40

    # Integrations sub-score (0-30)
    if integrations >= 50:
        i_s = 30.0
    elif integrations >= 20:
        i_s = 24.0
    elif integrations >= 10:
        i_s = 18.0
    elif integrations >= 5:
        i_s = 12.0
    else:
        i_s = 6.0

    return _clamp(ch_s + com_s + i_s)


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class ProtocolEcosystemHealthScorecard:
    """
    Scores the ecosystem health of each protocol in a batch.

    Usage::

        scorecard = ProtocolEcosystemHealthScorecard()
        result = scorecard.score(protocols, config)

    config keys (all optional):
        log_path   str   custom log file path
        write_log  bool  default True
    """

    def _score_protocol(self, p: dict) -> dict:
        name = str(p.get("name", "unknown"))

        fin  = _financial_health(p)
        adp  = _user_adoption(p)
        sec  = _security_posture(p)
        dev  = _developer_activity(p)
        eco  = _ecosystem_reach(p)

        composite = (
            fin  * _W_FINANCIAL +
            adp  * _W_ADOPTION  +
            sec  * _W_SECURITY  +
            dev  * _W_DEVELOPER +
            eco  * _W_ECOSYSTEM
        )
        composite = _clamp(composite)
        label = _health_label(composite)

        # Flags
        flags: list[str] = []
        if fin > _ALL_METRICS_THRESHOLD and adp > _ALL_METRICS_THRESHOLD and \
           sec > _ALL_METRICS_THRESHOLD and dev > _ALL_METRICS_THRESHOLD and \
           eco > _ALL_METRICS_THRESHOLD:
            flags.append("ALL_METRICS_POSITIVE")
        if sec < _SECURITY_CONCERN_THRESH:
            flags.append("SECURITY_CONCERN")
        commits   = int(p.get("github_commits_30d", 0))
        dev_count = int(p.get("developer_count", 0))
        if commits < _DEV_EXODUS_COMMITS_MAX and dev_count < _DEV_EXODUS_DEVCOUNT_MAX:
            flags.append("DEVELOPER_EXODUS")
        dau_chg = float(p.get("dau_30d_change_pct", 0.0))
        if dau_chg > _VIRAL_ADOPTION_THRESH:
            flags.append("VIRAL_ADOPTION")
        tvl = float(p.get("tvl_usd", 0.0))
        if tvl > _TVL_DOMINANCE_THRESH:
            flags.append("TVL_DOMINANCE")

        return {
            "name":               name,
            "financial_health":   round(fin, 2),
            "user_adoption":      round(adp, 2),
            "security_posture":   round(sec, 2),
            "developer_activity": round(dev, 2),
            "ecosystem_reach":    round(eco, 2),
            "composite_score":    round(composite, 2),
            "health_label":       label,
            "flags":              flags,
        }

    def _build_aggregates(self, results: list[dict]) -> dict:
        if not results:
            return {
                "healthiest_protocol":      None,
                "most_critical":            None,
                "average_composite":        0.0,
                "thriving_count":           0,
                "critical_count":           0,
                "ecosystem_composite_score": 0.0,
            }

        composites = [r["composite_score"] for r in results]
        max_idx = composites.index(max(composites))
        min_idx = composites.index(min(composites))
        avg = sum(composites) / len(composites)
        thriving = sum(1 for r in results if r["health_label"] == "THRIVING")
        critical = sum(1 for r in results if r["health_label"] == "CRITICAL")

        return {
            "healthiest_protocol":      results[max_idx]["name"],
            "most_critical":            results[min_idx]["name"],
            "average_composite":        round(avg, 2),
            "thriving_count":           thriving,
            "critical_count":           critical,
            "ecosystem_composite_score": round(avg, 2),
        }

    def score(self, protocols: list, config: dict | None = None) -> dict:
        """
        Score ecosystem health for a list of DeFi protocols.

        Parameters
        ----------
        protocols : list[dict]
            Each dict describes one protocol (see module docstring).
        config : dict, optional
            Optional overrides (see class docstring).

        Returns
        -------
        dict with keys:
            results      list[dict]   per-protocol scores
            aggregates   dict         portfolio-level aggregates
            timestamp    float        unix timestamp
        """
        if config is None:
            config = {}
        if not isinstance(protocols, list):
            raise TypeError("protocols must be a list")

        results = [self._score_protocol(p) for p in protocols]
        aggregates = self._build_aggregates(results)
        ts = time.time()

        output: dict[str, Any] = {
            "results":    results,
            "aggregates": aggregates,
            "timestamp":  ts,
        }

        write_log = config.get("write_log", True)
        if write_log:
            log_path = config.get("log_path", _LOG_PATH)
            try:
                _atomic_log(
                    log_path,
                    {
                        "timestamp":       ts,
                        "protocol_count":  len(results),
                        "aggregates":      aggregates,
                    },
                )
            except Exception:
                pass

        return output
