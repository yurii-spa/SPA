"""
spa_core/monitoring/series_anomaly_detector.py — Observability Plane: series anomaly detection.

PARALLEL layer. Pure stdlib (math, statistics), deterministic, no network, no LLM.

This is a SEPARATE detector from the pre-existing cycle-diff detector
(spa_core/monitoring/anomaly_detector.py, MP-1579), which compares the current
cycle snapshot against the previous one. THIS module instead asks a statistical,
self-referential question over the REAL per-protocol APY *history*:

    "Is the LATEST APY value for a protocol an outlier vs its OWN trailing window?"

It reads only; it never mutates state owned by other domains and writes exactly one
artifact of its own: data/anomaly_report.json (atomic via shutil.move).

Series source: data/bee/defillama_apy_history.json, loaded through
spa_core.backtesting.tier1.oos.load_protocol_series().

Three independent, deterministic detectors vote on the latest value vs a trailing
30-day window. A protocol is flagged only when >= 2 detectors agree (consensus →
fewer false positives on near-deterministic stablecoin lending yield):

  (1) robust z-score — |latest - median| / (1.4826 * MAD) over the window.
      Median + MAD (median absolute deviation) are robust: a single fat tail in
      the window does NOT inflate the scale the way mean + stdev would.
  (2) IQR fence (Tukey) — latest outside [Q1 - 1.5*IQR, Q3 + 1.5*IQR].
  (3) day-over-day jump — |latest - prev| in absolute APY-points > threshold.

Also folds in two cheaper signals from sibling artifacts (read-only, optional):
  - depeg deviations from data/peg_report.json (CRITICAL/WARNING statuses);
  - TVL drop > 30% d/d from data/adapter_status.json IF a prior TVL map is supplied
    (the snapshot file carries no time-series, so this is opportunistic / honest).

Severity: CRITICAL when >= 3 APY detectors agree OR a depeg is critical; else WARN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import os
import shutil
import statistics
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from spa_core.backtesting.tier1 import oos as oos_mod

_ROOT = Path(__file__).resolve().parents[2]
_PEG_REPORT = _ROOT / "data" / "peg_report.json"
_ADAPTER_STATUS = _ROOT / "data" / "adapter_status.json"
_OUT = _ROOT / "data" / "anomaly_report.json"

# --- tunables (deterministic) -------------------------------------------------
WINDOW_DAYS = 30          # trailing window for median/MAD/IQR
MAD_Z_THRESHOLD = 3.5     # robust z-score flag (Iglewicz-Hoaglin style)
IQR_K = 1.5               # Tukey fence multiplier
JUMP_PCT_THRESHOLD = 1.0  # absolute APY-point day-over-day jump (in percent)
TVL_DROP_THRESHOLD = 0.30 # 30% drop d/d
MIN_POINTS = 8            # need at least this many trailing points to judge
MAD_SCALE = 1.4826        # MAD → stdev-consistent estimator for normal data
_FLAT_SPIKE_Z = 1e9       # finite sentinel: spike off a perfectly flat window

SEVERITY_CRITICAL = "CRITICAL"
SEVERITY_WARN = "WARN"


# --- math helpers -------------------------------------------------------------
def _quartiles(sorted_vals: List[float]) -> tuple:
    """Q1, Q3 via the inclusive median-of-halves method (deterministic, stdlib).

    Splits at the median; for odd n the median element is shared by both halves
    (inclusive). Fully reproducible and adequate for Tukey fences.
    """
    n = len(sorted_vals)
    if n < 2:
        v = sorted_vals[0] if sorted_vals else 0.0
        return v, v
    mid = n // 2
    if n % 2 == 0:
        lower = sorted_vals[:mid]
        upper = sorted_vals[mid:]
    else:
        lower = sorted_vals[:mid + 1]
        upper = sorted_vals[mid:]
    return statistics.median(lower), statistics.median(upper)


def _mad_zscore(latest: float, window: List[float]) -> float:
    """Robust z-score of `latest` vs `window` using median + MAD.

    Returns 0.0 when MAD is 0 (perfectly flat window) and `latest` equals the
    median; if `latest` differs from a flat baseline it returns a large FINITE
    sentinel so a genuine spike is still caught without raising / returning inf.
    Crucially, a single outlier inside the window does NOT blow the scale up
    (that is the whole point of MAD over stdev).
    """
    if not window:
        return 0.0
    med = statistics.median(window)
    mad = statistics.median([abs(x - med) for x in window])
    if mad == 0.0:
        return 0.0 if latest == med else _FLAT_SPIKE_Z
    return abs(latest - med) / (MAD_SCALE * mad)


# --- core APY detector --------------------------------------------------------
def detect_apy_anomalies(
    series_map: Optional[Dict[str, Dict[str, float]]] = None,
) -> List[dict]:
    """Detect anomalies in the LATEST APY value of each protocol vs its trailing window.

    series_map: {protocol: {date_iso: apy}}. APY may be decimal or percent; values
    are normalised to PERCENT first (heuristic: if the whole series max <= 1.0 it is
    treated as decimal → *100) so the jump threshold and reported numbers are in
    percentage points.

    Returns one record per ANOMALOUS protocol (>= 2 detectors agree), sorted most
    severe first, then by descending robust z-score (deterministic tie-break).
    """
    if series_map is None:
        series_map = oos_mod.load_protocol_series()

    results: List[dict] = []
    for protocol in sorted(series_map.keys()):
        per_date = series_map[protocol]
        if not per_date:
            continue
        ordered = [per_date[d] for d in sorted(per_date.keys())]  # ISO sorts chronologically
        if len(ordered) < MIN_POINTS:
            continue

        if max(ordered) <= 1.0:  # decimal APY → percent
            ordered = [v * 100.0 for v in ordered]

        latest = ordered[-1]
        prev = ordered[-2]
        window = ordered[-(WINDOW_DAYS + 1):-1]  # window BEFORE the latest value
        if len(window) < MIN_POINTS:
            window = ordered[:-1]

        med = statistics.median(window)
        mad_z = _mad_zscore(latest, window)

        q1, q3 = _quartiles(sorted(window))
        iqr = q3 - q1
        lo = q1 - IQR_K * iqr
        hi = q3 + IQR_K * iqr
        iqr_outlier = latest < lo or latest > hi

        jump_pct = abs(latest - prev)

        m1 = mad_z >= MAD_Z_THRESHOLD
        m2 = bool(iqr_outlier)
        m3 = jump_pct > JUMP_PCT_THRESHOLD
        methods_agree = int(m1) + int(m2) + int(m3)

        if methods_agree < 2:
            continue

        severity = SEVERITY_CRITICAL if methods_agree >= 3 else SEVERITY_WARN
        results.append({
            "protocol": protocol,
            "latest_apy": round(latest, 4),
            "median": round(med, 4),
            "mad_z": (round(mad_z, 4) if mad_z < _FLAT_SPIKE_Z else mad_z),
            "iqr_outlier": bool(iqr_outlier),
            "iqr_fence": [round(lo, 4), round(hi, 4)],
            "jump_pct": round(jump_pct, 4),
            "methods_agree": methods_agree,
            "severity": severity,
        })

    results.sort(key=lambda r: (
        0 if r["severity"] == SEVERITY_CRITICAL else 1,
        -(r["mad_z"] if r["mad_z"] < _FLAT_SPIKE_Z else float("inf")),
        r["protocol"],
    ))
    return results


# --- peg / depeg detector -----------------------------------------------------
def detect_peg_anomalies(report: Optional[dict] = None) -> List[dict]:
    """Depeg anomalies from data/peg_report.json (read-only, graceful if absent)."""
    if report is None:
        try:
            report = json.loads(_PEG_REPORT.read_text())
        except Exception:
            return []
    out: List[dict] = []
    for st in (report.get("statuses") or []):
        status = str(st.get("status", "")).upper()
        if status in ("STABLE", "OK", ""):
            continue
        critical = status in ("CRITICAL", "DEPEG")
        out.append({
            "adapter_id": st.get("adapter_id"),
            "asset": st.get("asset"),
            "deviation_pct": st.get("deviation_pct"),
            "status": status,
            "severity": SEVERITY_CRITICAL if critical else SEVERITY_WARN,
        })
    out.sort(key=lambda r: (0 if r["severity"] == SEVERITY_CRITICAL else 1,
                            str(r.get("adapter_id"))))
    return out


# --- TVL detector -------------------------------------------------------------
def _adapter_tvls(status: dict) -> Dict[str, float]:
    """Flatten {adapter_id: tvl_usd} from the adapter_status snapshot."""
    out: Dict[str, float] = {}
    adapters = status.get("adapters")
    if isinstance(adapters, dict):
        for k, v in adapters.items():
            if isinstance(v, dict) and v.get("tvl_usd") is not None:
                out[k] = float(v["tvl_usd"])
    return out


def detect_tvl_anomalies(
    status: Optional[dict] = None,
    prior_tvls: Optional[Dict[str, float]] = None,
) -> List[dict]:
    """TVL drop > 30% d/d.

    The adapter_status snapshot carries no time-series, so a drop can only be
    computed when a prior TVL map is supplied (e.g. by a caller that snapshots the
    previous run, or by the test). Without `prior_tvls` this returns [] honestly
    rather than fabricating a baseline.
    """
    if status is None:
        try:
            status = json.loads(_ADAPTER_STATUS.read_text())
        except Exception:
            return []
    if not prior_tvls:
        return []
    current = _adapter_tvls(status)
    out: List[dict] = []
    for adapter_id, prev in prior_tvls.items():
        cur = current.get(adapter_id)
        if cur is None or prev is None or prev <= 0:
            continue
        drop = (prev - cur) / prev
        if drop > TVL_DROP_THRESHOLD:
            out.append({
                "adapter_id": adapter_id,
                "prev_tvl_usd": round(prev, 2),
                "current_tvl_usd": round(cur, 2),
                "drop_pct": round(drop * 100.0, 2),
                "severity": SEVERITY_CRITICAL if drop > 0.5 else SEVERITY_WARN,
            })
    out.sort(key=lambda r: -r["drop_pct"])
    return out


# --- aggregate ----------------------------------------------------------------
def detect_all(
    series_map: Optional[Dict[str, Dict[str, float]]] = None,
    peg_report: Optional[dict] = None,
    adapter_status: Optional[dict] = None,
    prior_tvls: Optional[Dict[str, float]] = None,
) -> dict:
    """Run all detectors and summarise."""
    apy = detect_apy_anomalies(series_map)
    peg = detect_peg_anomalies(peg_report)
    tvl = detect_tvl_anomalies(adapter_status, prior_tvls)

    all_items: List[dict] = []
    for a in apy:
        all_items.append({"kind": "apy", "id": a["protocol"],
                          "severity": a["severity"], "detail": a})
    for p in peg:
        all_items.append({"kind": "peg", "id": p.get("adapter_id"),
                          "severity": p["severity"], "detail": p})
    for t in tvl:
        all_items.append({"kind": "tvl", "id": t.get("adapter_id"),
                          "severity": t["severity"], "detail": t})

    worst = None
    for it in all_items:
        if worst is None:
            worst = it
        elif it["severity"] == SEVERITY_CRITICAL and worst["severity"] != SEVERITY_CRITICAL:
            worst = it

    return {
        "apy_anomalies": apy,
        "peg_anomalies": peg,
        "tvl_anomalies": tvl,
        "count": len(all_items),
        "worst": worst,
    }


# --- report -------------------------------------------------------------------
def _atomic_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(payload, fh, indent=2, sort_keys=True)
        shutil.move(tmp, str(path))  # atomic; cross-device safe (project rule)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def build_report(
    write: bool = True,
    series_map: Optional[Dict[str, Dict[str, float]]] = None,
    peg_report: Optional[dict] = None,
    adapter_status: Optional[dict] = None,
    prior_tvls: Optional[Dict[str, float]] = None,
) -> dict:
    """Build data/anomaly_report.json (atomic). Deterministic given the same inputs."""
    res = detect_all(series_map, peg_report, adapter_status, prior_tvls)
    critical = sum(1 for it in (
        res["apy_anomalies"] + res["peg_anomalies"] + res["tvl_anomalies"]
    ) if it["severity"] == SEVERITY_CRITICAL)
    report = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generated_by": "series_anomaly_detector",
        "llm_forbidden": True,
        "config": {
            "window_days": WINDOW_DAYS,
            "mad_z_threshold": MAD_Z_THRESHOLD,
            "iqr_k": IQR_K,
            "jump_pct_threshold": JUMP_PCT_THRESHOLD,
            "tvl_drop_threshold": TVL_DROP_THRESHOLD,
        },
        "count": res["count"],
        "critical_count": critical,
        "overall_status": "RED" if critical else ("AMBER" if res["count"] else "GREEN"),
        "apy_anomalies": res["apy_anomalies"],
        "peg_anomalies": res["peg_anomalies"],
        "tvl_anomalies": res["tvl_anomalies"],
        "worst": res["worst"],
    }
    if write:
        _atomic_write(_OUT, report)
    return report


if __name__ == "__main__":
    rep = build_report(write=True)
    print("== SPA APY anomaly detector (real DeFiLlama history) ==")
    print(f"overall: {rep['overall_status']}  total={rep['count']}  "
          f"critical={rep['critical_count']}")
    if not rep["count"]:
        print("No anomalies detected. Stable lending APY series — this is the "
              "expected, honest outcome on calm days.")
    else:
        for it in rep["apy_anomalies"]:
            print(f"  [APY {it['severity']}] {it['protocol']}: latest={it['latest_apy']} "
                  f"median={it['median']} mad_z={it['mad_z']} "
                  f"iqr_outlier={it['iqr_outlier']} jump={it['jump_pct']} "
                  f"({it['methods_agree']}/3 methods)")
        for it in rep["peg_anomalies"]:
            print(f"  [PEG {it['severity']}] {it['adapter_id']} dev={it['deviation_pct']}%")
        for it in rep["tvl_anomalies"]:
            print(f"  [TVL {it['severity']}] {it['adapter_id']} drop={it['drop_pct']}%")
    print(f"report -> {_OUT}")
