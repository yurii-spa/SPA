#!/usr/bin/env python3
"""Capital Efficiency Tracker (SPA-V622 / MP-770) — read-only / advisory.

Tracks how efficiently capital is deployed across DeFi protocols by scoring
each protocol position on a 0-100 scale that combines utilization rate and
APY weight. Provides per-position grades (A/B/C/D/F) and an aggregate idle
capital opportunity-cost report.

Design constraints
------------------
* Pure stdlib only — no numpy / scipy / requests / pandas / web3.
* Advisory / read-only: never modifies risk/, execution/, monitoring/, allocator/.
* Atomic writes: tmp + os.replace (POSIX-atomic).
* Ring-buffer history capped at 100 entries in data/capital_efficiency_log.json.
* Never raises on the happy path; missing / malformed inputs degrade gracefully.
* NOT imported from risk/, execution/, monitoring/ (LLM_FORBIDDEN_AGENTS).

Capital Efficiency Score (0-100)
---------------------------------
  apy_weight     = min(apy / MAX_APY, 1.0)          where MAX_APY = 0.30 (30 %)
  utilization    = clamp(utilization_rate_pct, 0, 100) / 100.0
  score          = utilization * apy_weight * 100

  Grade mapping:
    A  score >= 80
    B  score >= 60
    C  score >= 40
    D  score >= 20
    F  score <  20

Opportunity Cost
----------------
  idle_capital_pct      = idle_usd / (deployed_usd + idle_usd)  [per position]
  opportunity_cost_usd  = idle_usd * benchmark_apy / 365        [daily]

CLI
---
  python3 -m spa_core.analytics.capital_efficiency_tracker --check   (compute + print, no write)
  python3 -m spa_core.analytics.capital_efficiency_tracker --run     (+ atomic save)
  python3 -m spa_core.analytics.capital_efficiency_tracker --run --data-dir PATH
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from spa_core.utils.atomic import atomic_save
from spa_core.base import BaseAnalytics

# ---------------------------------------------------------------------------
# Constants & paths
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _PROJECT_ROOT / "data"

LOG_FILENAME = "capital_efficiency_log.json"
RING_BUFFER_CAP = 100
MAX_APY: float = 0.30   # 30 % — ceiling for apy_weight normalisation
DEFAULT_BENCHMARK_APY: float = 0.05  # 5 % annualised risk-free proxy

SCHEMA_VERSION = 1
SOURCE_NAME = "capital_efficiency_tracker"
MP_TAG = "MP-770"

log = logging.getLogger("spa.analytics.capital_efficiency_tracker")

# ---------------------------------------------------------------------------
# Grade thresholds
# ---------------------------------------------------------------------------

GRADE_THRESHOLDS: List[tuple] = [
    (80.0, "A"),
    (60.0, "B"),
    (40.0, "C"),
    (20.0, "D"),
    (0.0,  "F"),
]


def _grade(score: float) -> str:
    """Return letter grade for a capital efficiency score (0-100)."""
    for threshold, letter in GRADE_THRESHOLDS:
        if score >= threshold:
            return letter
    return "F"


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def _clamp(value: float, lo: float, hi: float) -> float:
    """Clamp *value* to [lo, hi]."""
    return max(lo, min(hi, value))


def compute_position_efficiency(
    protocol: str,
    deployed_usd: float,
    idle_usd: float,
    apy: float,
    utilization_rate_pct: float,
    benchmark_apy: float = DEFAULT_BENCHMARK_APY,
) -> Dict[str, Any]:
    """Compute capital efficiency metrics for a single protocol position.

    Parameters
    ----------
    protocol:
        Protocol identifier string (e.g. ``"aave_v3"``).
    deployed_usd:
        USD notional actively earning yield.
    idle_usd:
        USD sitting idle / uninvested in this protocol.
    apy:
        Current annualised yield as a decimal (e.g. ``0.05`` = 5 %).
    utilization_rate_pct:
        Percentage of capital actually deployed (0-100).
    benchmark_apy:
        Risk-free benchmark rate as decimal for opportunity cost calc.

    Returns
    -------
    dict with keys: protocol, deployed_usd, idle_usd, apy, utilization_rate_pct,
                    apy_weight, capital_efficiency_score, idle_capital_pct,
                    opportunity_cost_usd_daily, efficiency_grade, warnings.
    """
    warnings: List[str] = []

    # Sanitise inputs
    deployed_usd = max(0.0, float(deployed_usd))
    idle_usd = max(0.0, float(idle_usd))
    apy = float(apy)
    utilization_rate_pct = float(utilization_rate_pct)
    benchmark_apy = float(benchmark_apy)

    if apy < 0.0:
        warnings.append(f"Negative APY ({apy:.4f}) — scored as 0")
        apy = 0.0

    if utilization_rate_pct < 0.0 or utilization_rate_pct > 100.0:
        warnings.append(
            f"utilization_rate_pct={utilization_rate_pct:.2f} out of [0,100]; clamped"
        )
        utilization_rate_pct = _clamp(utilization_rate_pct, 0.0, 100.0)

    total_usd = deployed_usd + idle_usd

    # --- APY weight (0-1) ---
    apy_weight: float = _clamp(apy / MAX_APY, 0.0, 1.0) if MAX_APY > 0 else 0.0

    # --- Capital efficiency score (0-100) ---
    utilization_frac = utilization_rate_pct / 100.0
    score: float = _clamp(utilization_frac * apy_weight * 100.0, 0.0, 100.0)

    # --- Idle capital percentage ---
    if total_usd > 0.0:
        idle_capital_pct = (idle_usd / total_usd) * 100.0
    else:
        idle_capital_pct = 0.0
        if idle_usd == 0.0 and deployed_usd == 0.0:
            warnings.append("Both deployed_usd and idle_usd are zero")

    # --- Daily opportunity cost (idle capital × benchmark / 365) ---
    opportunity_cost_usd_daily: float = idle_usd * benchmark_apy / 365.0

    grade = _grade(score)

    return {
        "protocol": str(protocol),
        "deployed_usd": round(deployed_usd, 6),
        "idle_usd": round(idle_usd, 6),
        "apy": round(apy, 6),
        "utilization_rate_pct": round(utilization_rate_pct, 4),
        "benchmark_apy": round(benchmark_apy, 6),
        "apy_weight": round(apy_weight, 6),
        "capital_efficiency_score": round(score, 4),
        "idle_capital_pct": round(idle_capital_pct, 4),
        "opportunity_cost_usd_daily": round(opportunity_cost_usd_daily, 6),
        "efficiency_grade": grade,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# CapitalEfficiencyTracker class
# ---------------------------------------------------------------------------

class CapitalEfficiencyTracker(BaseAnalytics):
    OUTPUT_PATH = "data/capital_efficiency_tracker.json"
    """Stateful tracker that accumulates runs into a ring-buffer log.

    Usage
    -----
    ::

        tracker = CapitalEfficiencyTracker(data_dir="/path/to/data")
        result  = tracker.track(positions, benchmark_apy=0.05)
        report  = tracker.get_idle_capital_report()
        score   = tracker.get_efficiency_score()
    """

    def __init__(
        self,
        data_dir: Optional[Path | str] = None,
        ring_cap: int = RING_BUFFER_CAP,
    ) -> None:
        self._data_dir = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR
        self._ring_cap = ring_cap
        self._last_result: Optional[Dict[str, Any]] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def track(
        self,
        positions: List[Dict[str, Any]],
        benchmark_apy: float = DEFAULT_BENCHMARK_APY,
    ) -> Dict[str, Any]:
        """Compute capital efficiency for a list of protocol positions.

        Parameters
        ----------
        positions:
            List of dicts, each containing at minimum:
            ``protocol``, ``deployed_usd``, ``idle_usd``, ``apy``,
            ``utilization_rate_pct``.
        benchmark_apy:
            Annualised benchmark rate as decimal for opportunity cost.

        Returns
        -------
        Result dict with per-position details and aggregate metrics.
        """
        timestamp = datetime.now(timezone.utc).isoformat()
        per_position: List[Dict[str, Any]] = []

        for pos in positions:
            try:
                metrics = compute_position_efficiency(
                    protocol=pos.get("protocol", "unknown"),
                    deployed_usd=pos.get("deployed_usd", 0.0),
                    idle_usd=pos.get("idle_usd", 0.0),
                    apy=pos.get("apy", 0.0),
                    utilization_rate_pct=pos.get("utilization_rate_pct", 0.0),
                    benchmark_apy=benchmark_apy,
                )
                per_position.append(metrics)
            except Exception as exc:  # noqa: BLE001
                log.warning("Skipping malformed position %r: %s", pos, exc)
                per_position.append({
                    "protocol": pos.get("protocol", "unknown"),
                    "error": str(exc),
                    "capital_efficiency_score": 0.0,
                    "efficiency_grade": "F",
                })

        aggregate = self._aggregate(per_position)
        result: Dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "source": SOURCE_NAME,
            "mp_tag": MP_TAG,
            "timestamp": timestamp,
            "benchmark_apy": benchmark_apy,
            "position_count": len(per_position),
            "per_position": per_position,
            "aggregate": aggregate,
        }
        self._last_result = result
        return result

    def get_efficiency_score(self) -> Optional[float]:
        """Return the portfolio-level capital efficiency score from the last run.

        Returns ``None`` if :meth:`track` has not been called yet.
        """
        if self._last_result is None:
            return None
        return self._last_result["aggregate"].get("portfolio_efficiency_score")

    def get_idle_capital_report(self) -> Dict[str, Any]:
        """Return idle capital summary from the last :meth:`track` run.

        Returns an empty report dict if :meth:`track` has not been called yet.
        """
        if self._last_result is None:
            return {
                "total_idle_usd": 0.0,
                "total_deployed_usd": 0.0,
                "portfolio_idle_pct": 0.0,
                "total_opportunity_cost_usd_daily": 0.0,
                "per_position": [],
            }
        agg = self._last_result["aggregate"]
        return {
            "total_idle_usd": agg.get("total_idle_usd", 0.0),
            "total_deployed_usd": agg.get("total_deployed_usd", 0.0),
            "portfolio_idle_pct": agg.get("portfolio_idle_pct", 0.0),
            "total_opportunity_cost_usd_daily": agg.get(
                "total_opportunity_cost_usd_daily", 0.0
            ),
            "per_position": [
                {
                    "protocol": p.get("protocol"),
                    "idle_usd": p.get("idle_usd", 0.0),
                    "idle_capital_pct": p.get("idle_capital_pct", 0.0),
                    "opportunity_cost_usd_daily": p.get("opportunity_cost_usd_daily", 0.0),
                }
                for p in self._last_result.get("per_position", [])
                if "error" not in p
            ],
        }

    def save(self) -> bool:
        """Atomically append last result to the ring-buffer log file.

        Returns ``True`` on success, ``False`` on any error (never raises).
        """
        if self._last_result is None:
            log.warning("save() called before track() — nothing to write")
            return False
        try:
            log_path = self._data_dir / LOG_FILENAME
            existing: List[Dict[str, Any]] = _load_json_list(log_path)
            existing.append(self._last_result)
            # Ring-buffer: keep newest N entries
            if len(existing) > self._ring_cap:
                existing = existing[-self._ring_cap:]
            _atomic_write(log_path, existing)
            log.info("capital_efficiency_log written (%d entries)", len(existing))
            return True
        except Exception as exc:  # noqa: BLE001
            log.error("save() failed: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _aggregate(per_position: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Compute portfolio-level aggregate from per-position results."""
        valid = [p for p in per_position if "error" not in p]
        if not valid:
            return {
                "portfolio_efficiency_score": 0.0,
                "portfolio_grade": "F",
                "total_deployed_usd": 0.0,
                "total_idle_usd": 0.0,
                "portfolio_idle_pct": 0.0,
                "total_opportunity_cost_usd_daily": 0.0,
                "grade_distribution": {},
                "position_count_valid": 0,
            }

        scores = [p["capital_efficiency_score"] for p in valid]
        portfolio_score = sum(scores) / len(scores)

        total_deployed = sum(p.get("deployed_usd", 0.0) for p in valid)
        total_idle = sum(p.get("idle_usd", 0.0) for p in valid)
        total_capital = total_deployed + total_idle
        portfolio_idle_pct = (total_idle / total_capital * 100.0) if total_capital > 0 else 0.0
        total_opp_cost = sum(
            p.get("opportunity_cost_usd_daily", 0.0) for p in valid
        )

        grade_dist: Dict[str, int] = {}
        for p in valid:
            g = p.get("efficiency_grade", "F")
            grade_dist[g] = grade_dist.get(g, 0) + 1

        return {
            "portfolio_efficiency_score": round(portfolio_score, 4),
            "portfolio_grade": _grade(portfolio_score),
            "total_deployed_usd": round(total_deployed, 6),
            "total_idle_usd": round(total_idle, 6),
            "portfolio_idle_pct": round(portfolio_idle_pct, 4),
            "total_opportunity_cost_usd_daily": round(total_opp_cost, 6),
            "grade_distribution": grade_dist,
            "position_count_valid": len(valid),
        }


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------


    def to_dict(self) -> dict:
        """Return internal state as a plain dict. LLM FORBIDDEN."""
        return getattr(self, '_data', {})

def _load_json_list(path: Path) -> List[Any]:
    """Load a JSON list from *path*; return [] on any error."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
            return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []


def _atomic_write(path: Path, data: Any) -> None:
    """Write *data* as JSON to *path* atomically (tmp + os.replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_save(data, str(path))
# ---------------------------------------------------------------------------
# Module-level functional API (mirrors paper_trading analytics pattern)
# ---------------------------------------------------------------------------

def build_capital_efficiency_report(
    positions: List[Dict[str, Any]],
    benchmark_apy: float = DEFAULT_BENCHMARK_APY,
) -> Dict[str, Any]:
    """Functional entry-point: compute efficiency for *positions* and return result dict."""
    tracker = CapitalEfficiencyTracker()
    return tracker.track(positions, benchmark_apy=benchmark_apy)


def write_status(
    positions: List[Dict[str, Any]],
    benchmark_apy: float = DEFAULT_BENCHMARK_APY,
    data_dir: Optional[Path | str] = None,
) -> Dict[str, Any]:
    """Compute and atomically write results to the ring-buffer log."""
    tracker = CapitalEfficiencyTracker(data_dir=data_dir)
    result = tracker.track(positions, benchmark_apy=benchmark_apy)
    tracker.save()
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="capital_efficiency_tracker",
        description="MP-770 Capital Efficiency Tracker — read-only advisory module",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check",
        action="store_true",
        default=True,
        help="Compute and print; do NOT write to disk (default)",
    )
    mode.add_argument(
        "--run",
        action="store_true",
        default=False,
        help="Compute, print, and atomically write to data/capital_efficiency_log.json",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help="Override default data/ directory path",
    )
    return parser


def _load_positions_from_data_dir(data_dir: Path) -> List[Dict[str, Any]]:
    """Try to load live positions from data/current_positions.json."""
    positions_path = data_dir / "current_positions.json"
    try:
        with open(positions_path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError, OSError) as exc:
        log.warning("Cannot load current_positions.json: %s", exc)
        return []

    positions: List[Dict[str, Any]] = []
    items = raw if isinstance(raw, list) else raw.get("positions", [])
    for item in items:
        deployed = float(item.get("value_usd", item.get("deployed_usd", 0.0)))
        apy = float(item.get("apy", 0.0))
        # Infer idle_usd and utilization from position data if available
        idle = float(item.get("idle_usd", 0.0))
        utilization = float(item.get("utilization_rate_pct", 100.0 if deployed > 0 else 0.0))
        positions.append({
            "protocol": item.get("protocol", item.get("pool_id", "unknown")),
            "deployed_usd": deployed,
            "idle_usd": idle,
            "apy": apy,
            "utilization_rate_pct": utilization,
        })
    return positions


def main(argv: Optional[List[str]] = None) -> None:
    """CLI entry-point — exit 0 always (pure advisory)."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    parser = _build_cli_parser()
    args = parser.parse_args(argv)

    data_dir = Path(args.data_dir) if args.data_dir else _DEFAULT_DATA_DIR
    write_mode: bool = args.run

    positions = _load_positions_from_data_dir(data_dir)
    if not positions:
        print("[capital_efficiency_tracker] No positions found — using demo data", file=sys.stderr)
        positions = [
            {"protocol": "aave_v3",    "deployed_usd": 40000.0, "idle_usd": 5000.0,  "apy": 0.035, "utilization_rate_pct": 88.9},
            {"protocol": "compound_v3","deployed_usd": 30000.0, "idle_usd": 2000.0,  "apy": 0.048, "utilization_rate_pct": 93.8},
            {"protocol": "morpho",     "deployed_usd": 20000.0, "idle_usd": 10000.0, "apy": 0.065, "utilization_rate_pct": 66.7},
        ]

    tracker = CapitalEfficiencyTracker(data_dir=data_dir)
    result = tracker.track(positions)

    print(json.dumps(result, indent=2, ensure_ascii=False))

    if write_mode:
        ok = tracker.save()
        if not ok:
            print("[capital_efficiency_tracker] WARNING: save() failed", file=sys.stderr)
        else:
            print(
                f"[capital_efficiency_tracker] Written to {data_dir / LOG_FILENAME}",
                file=sys.stderr,
            )

    sys.exit(0)


if __name__ == "__main__":
    main()
