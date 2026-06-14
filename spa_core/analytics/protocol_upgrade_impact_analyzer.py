"""
MP-816 ProtocolUpgradeImpactAnalyzer
Advisory/read-only module — analyzes historical protocol upgrades to estimate the
impact on APY, TVL, and security risk, and evaluates upcoming upgrades.

Data log: data/upgrade_impact_log.json  (ring-buffer 100, atomic write)
Pure stdlib only. LLM FORBIDDEN.
"""

import json
import os
import time
import tempfile
from typing import Optional

_LOG_RING_SIZE: int = 100
_LOG_PATH_DEFAULT: str = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "upgrade_impact_log.json",
)


# ── helpers ───────────────────────────────────────────────────────────────────

def _load_log(path: str) -> list:
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _save_log(path: str, entries: list) -> None:
    """Atomic write with ring-buffer cap."""
    entries = entries[-_LOG_RING_SIZE:]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
            json.dump(entries, fh, indent=2)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _safe_float(val) -> Optional[float]:
    """Convert to float or return None for None/missing."""
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _pct_change(before: Optional[float], after: Optional[float]) -> Optional[float]:
    """(after - before) / before * 100, or None if inputs invalid."""
    if before is None or after is None:
        return None
    if before == 0.0:
        return None
    return (after - before) / before * 100.0


def _classify_outcome(
    had_incident: bool,
    apy_after,
    tvl_after,
    apy_impact: Optional[float],
    tvl_impact: Optional[float],
) -> str:
    if had_incident:
        return "INCIDENT"
    if apy_after is None and tvl_after is None:
        return "PENDING"
    # Treat partial pending gracefully: if apy_after is None but tvl_after present
    if apy_after is None:
        # Use only tvl impact
        if tvl_impact is not None:
            if tvl_impact > 10:
                return "POSITIVE"
            if tvl_impact < -10:
                return "NEGATIVE"
        return "PENDING"
    # apy_after is not None
    if apy_impact is not None and apy_impact > 5:
        return "POSITIVE"
    if tvl_impact is not None and tvl_impact > 10:
        return "POSITIVE"
    if apy_impact is not None and apy_impact < -5:
        return "NEGATIVE"
    if tvl_impact is not None and tvl_impact < -10:
        return "NEGATIVE"
    return "NEUTRAL"


def _classify_track_record(incident_rate_pct: float, avg_apy_impact: Optional[float]) -> str:
    if incident_rate_pct == 0 and (avg_apy_impact is None or avg_apy_impact >= 0):
        return "EXCELLENT"
    if incident_rate_pct < 10:
        return "GOOD"
    if incident_rate_pct < 25:
        return "MIXED"
    return "POOR"


def _build_recommendation(track_record: str, pending_count: int) -> str:
    if track_record == "EXCELLENT" and pending_count == 0:
        return "Strong upgrade history — minimal risk"
    if track_record == "EXCELLENT":
        return "Strong track record — monitor upcoming upgrades closely"
    if track_record == "GOOD":
        return "Good track record — monitor upcoming upgrades"
    if track_record == "MIXED":
        return "Mixed history — exercise caution during upgrade periods"
    return "Poor upgrade track record — high caution advised"


def _compute_risk_score(
    audited_pct: float,
    incident_rate_pct: float,
    completed: int,
) -> int:
    raw = 50.0 - (audited_pct * 0.3) + (incident_rate_pct * 1.0) - min(completed * 2, 20)
    return int(max(0, min(100, raw)))


# ── public API ────────────────────────────────────────────────────────────────

def analyze(
    protocol: str,
    upgrades: list,
    config: Optional[dict] = None,
    *,
    log_path: Optional[str] = None,
    persist: bool = True,
) -> dict:
    """
    Analyze historical and pending protocol upgrades.

    Parameters
    ----------
    protocol : str
        Protocol identifier.
    upgrades : list[dict]
        Each entry: {name, date, type, apy_before, apy_after, tvl_before_usd,
                      tvl_after_usd, had_incident, audited}.
    config : dict, optional
        Reserved for future configuration.
    log_path : str, optional
        Override default log file path.
    persist : bool
        Write result to log (default True).

    Returns
    -------
    dict  — see module docstring for full schema.
    """
    now_ts = time.time()

    # ── build upgrade_history ─────────────────────────────────────────────────
    upgrade_history = []
    completed_apy_impacts = []
    completed_tvl_impacts = []
    total_audited = 0
    total_upgrades = len(upgrades)
    completed = 0
    pending = 0
    incidents = 0

    for u in upgrades:
        name = u.get("name", "")
        utype = u.get("type", "unknown")
        date = u.get("date", "")
        had_incident = bool(u.get("had_incident", False))
        audited = bool(u.get("audited", False))

        apy_before = _safe_float(u.get("apy_before"))
        apy_after = _safe_float(u.get("apy_after"))
        tvl_before = _safe_float(u.get("tvl_before_usd"))
        tvl_after = _safe_float(u.get("tvl_after_usd"))

        apy_impact = _pct_change(apy_before, apy_after)
        tvl_impact = _pct_change(tvl_before, tvl_after)

        # Determine status
        is_pending = (apy_after is None and tvl_after is None and not had_incident)
        status = "PENDING" if is_pending else "COMPLETED"

        outcome = _classify_outcome(had_incident, apy_after, tvl_after, apy_impact, tvl_impact)

        if audited:
            total_audited += 1

        if status == "COMPLETED":
            completed += 1
            if had_incident:
                incidents += 1
            if apy_impact is not None:
                completed_apy_impacts.append(apy_impact)
            if tvl_impact is not None:
                completed_tvl_impacts.append(tvl_impact)
        else:
            pending += 1

        upgrade_history.append({
            "name": name,
            "type": utype,
            "date": date,
            "status": status,
            "apy_impact_pct": apy_impact,
            "tvl_impact_pct": tvl_impact,
            "outcome": outcome,
        })

    # ── statistics ────────────────────────────────────────────────────────────
    incident_rate_pct = (incidents / completed * 100.0) if completed > 0 else 0.0
    audited_pct = (total_audited / total_upgrades * 100.0) if total_upgrades > 0 else 0.0
    avg_apy_impact = (
        sum(completed_apy_impacts) / len(completed_apy_impacts)
        if completed_apy_impacts else None
    )
    avg_tvl_impact = (
        sum(completed_tvl_impacts) / len(completed_tvl_impacts)
        if completed_tvl_impacts else None
    )

    statistics = {
        "total_upgrades": total_upgrades,
        "completed": completed,
        "pending": pending,
        "incident_rate_pct": incident_rate_pct,
        "audited_pct": audited_pct,
        "avg_apy_impact_pct": avg_apy_impact,
        "avg_tvl_impact_pct": avg_tvl_impact,
    }

    # ── track_record ──────────────────────────────────────────────────────────
    track_record = _classify_track_record(incident_rate_pct, avg_apy_impact)

    # ── upgrade_risk_score ────────────────────────────────────────────────────
    upgrade_risk_score = _compute_risk_score(audited_pct, incident_rate_pct, completed)

    # ── recommendation ────────────────────────────────────────────────────────
    recommendation = _build_recommendation(track_record, pending)

    result = {
        "protocol": protocol,
        "upgrade_history": upgrade_history,
        "statistics": statistics,
        "track_record": track_record,
        "upgrade_risk_score": upgrade_risk_score,
        "recommendation": recommendation,
        "timestamp": now_ts,
    }

    if persist:
        _path = log_path or _LOG_PATH_DEFAULT
        entries = _load_log(_path)
        entries.append(result)
        _save_log(_path, entries)

    return result


def init_log(path: Optional[str] = None) -> None:
    """Ensure log file exists and is a valid empty list."""
    _path = path or _LOG_PATH_DEFAULT
    os.makedirs(os.path.dirname(_path), exist_ok=True)
    if not os.path.exists(_path):
        _save_log(_path, [])


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="MP-816 ProtocolUpgradeImpactAnalyzer")
    parser.add_argument("--protocol", default="demo_protocol")
    parser.add_argument("--check", action="store_true", help="Compute without persisting")
    parser.add_argument("--run", action="store_true", help="Compute and persist to log")
    args = parser.parse_args()

    _demo_upgrades = [
        {
            "name": "V2→V3 Migration",
            "date": "2024-01-15",
            "type": "migration",
            "apy_before": 3.5,
            "apy_after": 4.8,
            "tvl_before_usd": 500_000_000,
            "tvl_after_usd": 650_000_000,
            "had_incident": False,
            "audited": True,
        },
        {
            "name": "Interest Rate Model Update",
            "date": "2024-06-01",
            "type": "parameter",
            "apy_before": 4.8,
            "apy_after": 5.1,
            "tvl_before_usd": 650_000_000,
            "tvl_after_usd": 680_000_000,
            "had_incident": False,
            "audited": True,
        },
        {
            "name": "Liquidity Mining V2",
            "date": "2025-01-01",
            "type": "tokenomics",
            "apy_before": 5.0,
            "apy_after": None,
            "tvl_before_usd": 700_000_000,
            "tvl_after_usd": None,
            "had_incident": False,
            "audited": False,
        },
    ]

    _persist = args.run and not args.check
    _result = analyze(args.protocol, _demo_upgrades, persist=_persist)
    print(json.dumps(_result, indent=2))
