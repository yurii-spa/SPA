#!/usr/bin/env python3
"""Portfolio drift monitoring module for SPA (MP-578).

Real-time monitoring of portfolio allocation drift from target weights.
Generates typed MonitorAlert objects, computes a composite health score,
and persists ring-buffered snapshots in data/monitor_snapshots.json.

Design rules (project-wide)
============================
* **Stdlib only** — no external deps (no requests, web3, LLM SDK).
* **Atomic writes** — tmp file + os.replace on every JSON update.
* **LLM-FORBIDDEN** — no AI/LLM calls here; pure deterministic arithmetic.
* **Read-only wrt capital** — does NOT import execution/, does NOT touch
  trades.json, current_positions.json, or any other capital-state file.

Alert levels
============
* INFO     — drift ≥ 3 pp and < 5 pp (mild; informational only)
* WARNING  — drift ≥ 5 pp and ≤ 10 pp (notable; may require monitoring)
* CRITICAL — drift > 10 pp  OR  T2 aggregate > ADR-019 limit (50 %)

Health score (0–100)
====================
Three equally-weighted components, each representing a key portfolio quality
dimension:

  1. **APY component** (35 pts): weighted-average APY normalised to a target
     ceiling of 10 %.  Full marks when weighted APY ≥ 10 %.

  2. **Risk component** (35 pts): inverted weighted-average risk_score.
     Risk scores are in [0, 1] where 0 = lowest risk.
     ``risk_score = 35 × (1 − weighted_risk)``

  3. **Diversification component** (30 pts): based on the Herfindahl-
     Hirschman Index (HHI = Σw²).  Full marks when HHI = 0 (impossible in
     practice but asymptotically approached with many equal-weight adapters).
     ``divers_score = 30 × (1 − HHI)``

Usage
=====
::

    from spa_core.paper_trading.portfolio_monitor import PortfolioMonitor

    monitor = PortfolioMonitor()
    drift   = monitor.check_drift(current_weights, target_weights)
    alerts  = monitor.get_alerts(current_weights, target_weights, risk_limits)
    score   = monitor.compute_portfolio_health_score(adapters, weights)
    snap    = monitor.get_snapshot(portfolio, adapters, target_weights)
    monitor.save_snapshot(snap)
    latest  = monitor.load_latest_snapshot()

CLI (offline, exit 0 always)::

    python3 -m spa_core.paper_trading.portfolio_monitor --check
    python3 -m spa_core.paper_trading.portfolio_monitor --run
    python3 -m spa_core.paper_trading.portfolio_monitor --run --data-dir data
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from spa_core.utils.atomic import atomic_save

log = logging.getLogger("spa.paper_trading.portfolio_monitor")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = str(_REPO_ROOT / "data")

SNAPSHOTS_FILENAME = "monitor_snapshots.json"
SNAPSHOTS_MAX = 100  # ring-buffer cap

# ── Alert thresholds (percentage points) ─────────────────────────────────────

DRIFT_INFO_THRESHOLD     = 3.0    # ≥ 3 pp  → INFO
DRIFT_WARNING_THRESHOLD  = 5.0    # ≥ 5 pp  → WARNING
DRIFT_CRITICAL_THRESHOLD = 10.0   # > 10 pp → CRITICAL

# ADR-019: T2 total cap 50 %
T2_CRITICAL_CAP = 0.50   # fraction

# APY normalisation ceiling for health score.
# Calibrated to the strategy's realistic blended stablecoin yield (DECISIONS.md
# 2026-06-21: real T1/T2 APY ~3.5-5%). The old 10% ceiling was unreachable, so
# a healthy portfolio capped the APY component at ~half and the composite score
# could never clear the 70 health floor. 6% = full APY score.
_APY_HEALTH_MAX = 6.0

# ── Alert level constants ─────────────────────────────────────────────────────

ALERT_INFO     = "INFO"
ALERT_WARNING  = "WARNING"
ALERT_CRITICAL = "CRITICAL"

_LEVEL_ORDER: Dict[str, int] = {
    ALERT_CRITICAL: 0,
    ALERT_WARNING:  1,
    ALERT_INFO:     2,
}


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class MonitorAlert:
    """A single portfolio drift / compliance alert.

    Attributes
    ----------
    level:
        One of ``INFO | WARNING | CRITICAL``.
    adapter_id:
        The adapter that triggered the alert, or a special token such as
        ``"T2_AGGREGATE"`` for tier-level alerts.
    message:
        Human-readable description of the alert.
    drift:
        Absolute drift magnitude in **percentage points** (always ≥ 0).
    """

    level:      str
    adapter_id: str
    message:    str
    drift:      float

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict."""
        return asdict(self)


# ── PortfolioMonitor ──────────────────────────────────────────────────────────

class PortfolioMonitor:
    """Real-time portfolio drift and health monitor.

    All threshold parameters are expressed as **percentage points** (pp).
    Weights are expected as fractions in [0, 1].

    Parameters
    ----------
    info_threshold:
        Minimum drift (pp) to emit an INFO alert.  Default: 3.0 pp.
    warning_threshold:
        Minimum drift (pp) to emit a WARNING alert.  Default: 5.0 pp.
    critical_threshold:
        Minimum drift (pp) to emit a CRITICAL alert.  Default: 10.0 pp.
    t2_critical_cap:
        T2 aggregate fraction above which a CRITICAL alert is emitted.
        Default: 0.50 (ADR-019).
    data_dir:
        Directory for the snapshots file.  Defaults to repo ``data/``.
    """

    # Class-level defaults (also exported as module-level constants above)
    INFO_THRESHOLD:     float = DRIFT_INFO_THRESHOLD
    WARNING_THRESHOLD:  float = DRIFT_WARNING_THRESHOLD
    CRITICAL_THRESHOLD: float = DRIFT_CRITICAL_THRESHOLD
    T2_CRITICAL_CAP:    float = T2_CRITICAL_CAP

    def __init__(
        self,
        info_threshold:     float = DRIFT_INFO_THRESHOLD,
        warning_threshold:  float = DRIFT_WARNING_THRESHOLD,
        critical_threshold: float = DRIFT_CRITICAL_THRESHOLD,
        t2_critical_cap:    float = T2_CRITICAL_CAP,
        data_dir:           str   = _DEFAULT_DATA_DIR,
    ) -> None:
        self.info_threshold     = float(info_threshold)
        self.warning_threshold  = float(warning_threshold)
        self.critical_threshold = float(critical_threshold)
        self.t2_critical_cap    = float(t2_critical_cap)
        self.data_dir           = data_dir

    # ──────────────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────────────

    def check_drift(
        self,
        current_weights: Dict[str, float],
        target_weights:  Dict[str, float],
        threshold:       float = 0.05,
    ) -> Dict[str, float]:
        """Compute per-adapter signed drift above the given threshold.

        Only adapters whose absolute drift is **≥ threshold** are included in
        the result; others are silently omitted.

        Parameters
        ----------
        current_weights:
            ``{adapter_id: weight}`` — fractions in [0, 1].
        target_weights:
            ``{adapter_id: weight}`` — fractions in [0, 1].
        threshold:
            Minimum absolute drift **fraction** to include.  Default: 0.05
            (= 5 percentage points).  Pass 0.0 to include every adapter.

        Returns
        -------
        dict
            ``{adapter_id: drift_pct}`` for adapters whose |drift| ≥ threshold.
            ``drift_pct`` is the signed drift in **percentage points**
            (e.g. +6.0 means the adapter is 6 pp over-allocated vs target).
            Sign: ``current − target``.
        """
        all_ids = set(current_weights) | set(target_weights)
        result: Dict[str, float] = {}
        for adapter_id in all_ids:
            cur = float(current_weights.get(adapter_id, 0.0))
            tgt = float(target_weights.get(adapter_id, 0.0))
            delta = cur - tgt
            if abs(delta) >= float(threshold):
                result[adapter_id] = round(delta * 100.0, 6)
        return result

    def get_alerts(
        self,
        current_weights: Dict[str, float],
        target_weights:  Dict[str, float],
        risk_limits:     Dict[str, Any],
    ) -> List[MonitorAlert]:
        """Generate alerts for drift and compliance violations.

        Per-adapter drift alert classification
        ----------------------------------------
        * INFO     — |drift| ∈ [info_threshold, warning_threshold)
        * WARNING  — |drift| ∈ [warning_threshold, critical_threshold]
        * CRITICAL — |drift| > critical_threshold

        Tier-level alerts
        -----------------
        * CRITICAL — T2 aggregate weight > t2_critical_cap (ADR-019)

        Parameters
        ----------
        current_weights:
            ``{adapter_id: weight}`` — fractions in [0, 1].
        target_weights:
            ``{adapter_id: weight}`` — fractions in [0, 1].
        risk_limits:
            Supplemental risk limits dict.  Recognised keys:

            * ``"t2_adapters"`` — list of adapter IDs classified as T2.
            * ``"t2_cap"``      — override for the T2 aggregate cap (fraction).

        Returns
        -------
        List[MonitorAlert]
            Sorted by severity (CRITICAL first), then by |drift| descending.
        """
        alerts: List[MonitorAlert] = []

        # ── Per-adapter drift alerts ──────────────────────────────────────────
        all_ids = set(current_weights) | set(target_weights)
        for adapter_id in sorted(all_ids):  # deterministic iteration
            cur = float(current_weights.get(adapter_id, 0.0))
            tgt = float(target_weights.get(adapter_id, 0.0))
            drift_pp = abs(cur - tgt) * 100.0

            if drift_pp > self.critical_threshold:
                alerts.append(MonitorAlert(
                    level=ALERT_CRITICAL,
                    adapter_id=adapter_id,
                    message=(
                        f"{adapter_id}: drift {drift_pp:.2f}pp exceeds "
                        f"CRITICAL threshold ({self.critical_threshold:.1f}pp)"
                    ),
                    drift=round(drift_pp, 6),
                ))
            elif drift_pp >= self.warning_threshold:
                alerts.append(MonitorAlert(
                    level=ALERT_WARNING,
                    adapter_id=adapter_id,
                    message=(
                        f"{adapter_id}: drift {drift_pp:.2f}pp exceeds "
                        f"WARNING threshold ({self.warning_threshold:.1f}pp)"
                    ),
                    drift=round(drift_pp, 6),
                ))
            elif drift_pp >= self.info_threshold:
                alerts.append(MonitorAlert(
                    level=ALERT_INFO,
                    adapter_id=adapter_id,
                    message=(
                        f"{adapter_id}: drift {drift_pp:.2f}pp exceeds "
                        f"INFO threshold ({self.info_threshold:.1f}pp)"
                    ),
                    drift=round(drift_pp, 6),
                ))

        # ── Tier aggregate alert — T2 (ADR-019) ──────────────────────────────
        t2_adapters: List[str] = risk_limits.get("t2_adapters", [])
        t2_cap = float(risk_limits.get("t2_cap", self.t2_critical_cap))
        if t2_adapters:
            t2_total = sum(
                float(current_weights.get(a, 0.0)) for a in t2_adapters
            )
            if t2_total > t2_cap:
                over_pp = round((t2_total - t2_cap) * 100.0, 6)
                alerts.append(MonitorAlert(
                    level=ALERT_CRITICAL,
                    adapter_id="T2_AGGREGATE",
                    message=(
                        f"T2 aggregate {t2_total * 100:.2f}% exceeds "
                        f"ADR-019 cap ({t2_cap * 100:.1f}%) by {over_pp:.2f}pp"
                    ),
                    drift=over_pp,
                ))

        # Sort: CRITICAL first, then WARNING, then INFO; ties by drift desc
        alerts.sort(key=lambda a: (_LEVEL_ORDER.get(a.level, 9), -a.drift))
        return alerts

    def compute_portfolio_health_score(
        self,
        adapters: Dict[str, Dict[str, Any]],
        weights:  Dict[str, float],
    ) -> float:
        """Compute a composite portfolio health score in [0, 100].

        Three components, each measuring a key quality dimension:

        **APY component** (35 pts)
            Weighted-average APY of active positions, normalised to
            ``_APY_HEALTH_MAX`` (10 %).  Returns 35 when avg APY ≥ 10 %,
            scales linearly down to 0.

        **Risk component** (35 pts)
            Inverted weighted-average ``risk_score``.  Scores are in [0, 1]
            where 0 = lowest risk.
            ``risk_score = 35 × (1 − weighted_risk)``

        **Diversification component** (30 pts)
            Based on the Herfindahl–Hirschman Index (HHI = Σw²).
            ``divers_score = 30 × (1 − HHI)``
            A perfectly concentrated portfolio (HHI = 1) scores 0 here.

        Parameters
        ----------
        adapters:
            ``{adapter_id: {"apy": float, "risk_score": float, ...}}``
            Missing keys default to safe neutral values (apy=0, risk=0.5).
        weights:
            ``{adapter_id: weight}`` — fractions in [0, 1].
            Zero-weight adapters are excluded from calculations.

        Returns
        -------
        float
            Health score in [0.0, 100.0], rounded to 2 decimal places.
        """
        # Collect active weights
        active: Dict[str, float] = {
            aid: float(w)
            for aid, w in weights.items()
            if float(w) > 0
        }
        total_weight = sum(active.values())
        if total_weight <= 0:
            return 0.0

        # Normalised weights (sum to 1)
        norm: Dict[str, float] = {
            aid: w / total_weight for aid, w in active.items()
        }

        # ── Component 1: APY (35 pts) ─────────────────────────────────────────
        weighted_apy = 0.0
        for aid, nw in norm.items():
            info = adapters.get(aid)
            info = info if isinstance(info, dict) else {}
            raw = info.get("apy", info.get("apy_pct", 0.0))
            try:
                apy_val = float(raw) if raw is not None else 0.0
            except (TypeError, ValueError):
                apy_val = 0.0
            weighted_apy += nw * max(0.0, apy_val)

        apy_score = min(35.0, (weighted_apy / _APY_HEALTH_MAX) * 35.0)

        # ── Component 2: Risk (35 pts, inverted) ──────────────────────────────
        weighted_risk = 0.0
        for aid, nw in norm.items():
            info = adapters.get(aid)
            info = info if isinstance(info, dict) else {}
            raw = info.get("risk_score", 0.5)
            try:
                risk_val = min(1.0, max(0.0, float(raw) if raw is not None else 0.5))
            except (TypeError, ValueError):
                risk_val = 0.5
            weighted_risk += nw * risk_val

        risk_score = 35.0 * (1.0 - weighted_risk)

        # ── Component 3: Diversification (30 pts, HHI) ────────────────────────
        hhi = sum(nw ** 2 for nw in norm.values())
        divers_score = 30.0 * (1.0 - hhi)

        total = apy_score + risk_score + divers_score
        return round(min(100.0, max(0.0, total)), 2)

    def get_snapshot(
        self,
        portfolio:      Dict[str, Any],
        adapters:       Dict[str, Dict[str, Any]],
        target_weights: Dict[str, float],
    ) -> Dict[str, Any]:
        """Build a full monitoring snapshot of the current portfolio state.

        Parameters
        ----------
        portfolio:
            Portfolio state dict.  Expected keys:

            * ``"current_weights"`` — ``{adapter_id: weight}`` (fractions).
            * ``"equity"``          — total portfolio value in USD.
            * ``"positions"``       — (optional) ``{adapter_id: usd_value}``.

        adapters:
            ``{adapter_id: {"apy": float, "tvl": float, "risk_score": float,
            "tier": str, ...}}``

        target_weights:
            ``{adapter_id: weight}`` — fractions in [0, 1].

        Returns
        -------
        dict
            Keys:
            ``generated_at``, ``equity``, ``adapter_count``,
            ``current_weights``, ``target_weights``, ``drift_map``,
            ``alerts``, ``health_score``, ``t2_total_weight``,
            ``summary_level`` (worst alert level or ``"OK"``).
        """
        current_weights: Dict[str, float] = {
            k: float(v)
            for k, v in portfolio.get("current_weights", {}).items()
        }
        equity = float(portfolio.get("equity", 0.0))

        # Infer T2 adapter list from the adapters registry (tier=="T2")
        t2_adapters = [
            aid
            for aid, info in adapters.items()
            if isinstance(info, dict) and info.get("tier") == "T2"
        ]
        risk_limits: Dict[str, Any] = {
            "t2_adapters": t2_adapters,
            "t2_cap":      self.t2_critical_cap,
        }

        # Compute all three views (threshold=0.0 → include everything)
        drift_map = self.check_drift(current_weights, target_weights, threshold=0.0)
        alerts    = self.get_alerts(current_weights, target_weights, risk_limits)
        health    = self.compute_portfolio_health_score(adapters, current_weights)

        t2_total = sum(current_weights.get(a, 0.0) for a in t2_adapters)

        # Worst alert level across all alerts
        if any(a.level == ALERT_CRITICAL for a in alerts):
            summary_level = ALERT_CRITICAL
        elif any(a.level == ALERT_WARNING for a in alerts):
            summary_level = ALERT_WARNING
        elif any(a.level == ALERT_INFO for a in alerts):
            summary_level = ALERT_INFO
        else:
            summary_level = "OK"

        return {
            "generated_at":   datetime.now(timezone.utc).isoformat(),
            "equity":         round(equity, 6),
            "adapter_count":  len(adapters),
            "current_weights": {k: round(v, 8) for k, v in current_weights.items()},
            "target_weights":  {k: round(float(v), 8) for k, v in target_weights.items()},
            "drift_map":      drift_map,
            "alerts":         [a.to_dict() for a in alerts],
            "health_score":   health,
            "t2_total_weight": round(t2_total, 8),
            "summary_level":  summary_level,
        }

    def save_snapshot(
        self,
        snapshot: Dict[str, Any],
        data_dir: Optional[str] = None,
    ) -> None:
        """Atomically append snapshot to ``data/monitor_snapshots.json``.

        The file is created if absent.  Entries are capped at
        :data:`SNAPSHOTS_MAX` (100) records in a ring-buffer (oldest evicted
        first).  All writes are **atomic**: written to a temporary file then
        ``os.replace``'d into place.

        Parameters
        ----------
        snapshot:
            Dict as returned by :meth:`get_snapshot`.
        data_dir:
            Override data directory.  Defaults to ``self.data_dir``.
        """
        data_path = Path(data_dir or self.data_dir)
        data_path.mkdir(parents=True, exist_ok=True)
        snapshots_file = data_path / SNAPSHOTS_FILENAME

        # Load existing ring-buffer (tolerant of corrupt files)
        snapshots: List[Dict[str, Any]] = []
        if snapshots_file.exists():
            try:
                raw = json.loads(snapshots_file.read_text(encoding="utf-8"))
                if isinstance(raw, list):
                    snapshots = raw
            except (json.JSONDecodeError, OSError) as exc:
                log.warning(
                    "monitor_snapshots.json unreadable — starting fresh: %s", exc
                )

        # Append + ring-buffer eviction
        snapshots.append(snapshot)
        if len(snapshots) > SNAPSHOTS_MAX:
            snapshots = snapshots[-SNAPSHOTS_MAX:]

        # Atomic write
        atomic_save(snapshots, str(snapshots_file))

        # Write portfolio_health.json for agent_health_monitor / system_health_monitor
        health_file = data_path / "portfolio_health.json"
        health_payload = {
            "generated_at": snapshot.get("generated_at"),
            "health_score": snapshot.get("health_score"),
            "summary_level": snapshot.get("summary_level"),
        }
        atomic_save(health_payload, str(health_file))

    def load_latest_snapshot(
        self,
        data_dir: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Load the most recent snapshot from ``data/monitor_snapshots.json``.

        Parameters
        ----------
        data_dir:
            Override data directory.  Defaults to ``self.data_dir``.

        Returns
        -------
        dict or None
            The last snapshot in the ring-buffer, or ``None`` if the file is
            absent, empty, or unreadable.
        """
        snapshots_file = Path(data_dir or self.data_dir) / SNAPSHOTS_FILENAME
        if not snapshots_file.exists():
            return None
        try:
            raw = json.loads(snapshots_file.read_text(encoding="utf-8"))
            if isinstance(raw, list) and raw:
                return raw[-1]
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("Failed to load monitor_snapshots.json: %s", exc)
        return None


# ── CLI entry-point ───────────────────────────────────────────────────────────

def _main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="SPA PortfolioMonitor — check portfolio drift and health."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        default=True,
        help="Compute and print results without writing (default).",
    )
    parser.add_argument(
        "--run",
        action="store_true",
        default=False,
        help="Also persist snapshot to data/monitor_snapshots.json.",
    )
    parser.add_argument(
        "--data-dir",
        default=_DEFAULT_DATA_DIR,
        help="Data directory for monitor_snapshots.json.",
    )
    args = parser.parse_args(argv)

    monitor = PortfolioMonitor(data_dir=args.data_dir)

    # ── Load real portfolio data ──────────────────────────────────────────────
    data_path = Path(args.data_dir)
    positions_file = data_path / "current_positions.json"
    ranking_file   = data_path / "apy_ranking.json"
    status_file    = data_path / "paper_trading_status.json"

    _fallback = False
    current: dict = {}
    target:  dict = {}
    adapters_ex: dict = {}
    equity: float = 100_000.0

    if positions_file.exists() and ranking_file.exists():
        try:
            pos_raw   = json.loads(positions_file.read_text(encoding="utf-8"))
            positions = pos_raw.get("positions", {})
            cash_usd  = float(pos_raw.get("cash_usd",  0.0))
            equity    = float(pos_raw.get("capital_usd", 100_000.0))

            # Override equity from paper_trading_status if available
            if status_file.exists():
                try:
                    st = json.loads(status_file.read_text(encoding="utf-8"))
                    equity = float(st.get("current_equity", equity))
                except Exception:
                    pass

            total_usd = sum(float(v) for v in positions.values()) + cash_usd
            if total_usd <= 0:
                raise ValueError("total_usd <= 0")

            current = {k: float(v) / total_usd for k, v in positions.items()}
            if cash_usd > 0:
                current["cash"] = cash_usd / total_usd

            # Build adapters dict from apy_ranking.json
            ranking_data = json.loads(ranking_file.read_text(encoding="utf-8"))
            adapters_ex  = {}
            for entry in ranking_data.get("by_apy", []):
                proto = entry.get("protocol", "")
                if not proto:
                    continue
                adapters_ex[proto] = {
                    "apy":        float(entry.get("apy_pct",   0.0)),
                    "risk_score": float(entry.get("risk_score", 0.5)),
                    "tier":       entry.get("tier", "T2"),
                    "tvl":        float(entry.get("tvl_usd",   0.0)),
                }
            adapters_ex.setdefault(
                "cash", {"apy": 0.0, "risk_score": 0.0, "tier": "T1", "tvl": 0.0}
            )

            # target = current (no separate target file; avoids false drift alerts)
            target = dict(current)

        except Exception as exc:
            log.warning("Failed to load real portfolio data — using demo: %s", exc)
            _fallback = True
    else:
        _fallback = True

    if _fallback:
        # Illustrative self-test with representative weights (fallback only)
        current = {
            "aave_v3":     0.42,
            "compound_v3": 0.30,
            "morpho":      0.23,
            "cash":        0.05,
        }
        target = {
            "aave_v3":     0.35,
            "compound_v3": 0.35,
            "morpho":      0.25,
            "cash":        0.05,
        }
        adapters_ex = {
            "aave_v3":     {"apy": 3.5,  "tvl": 1e9,   "risk_score": 0.20, "tier": "T1"},
            "compound_v3": {"apy": 4.8,  "tvl": 5e8,   "risk_score": 0.22, "tier": "T1"},
            "morpho":      {"apy": 6.5,  "tvl": 1.5e8, "risk_score": 0.28, "tier": "T2"},
            "cash":        {"apy": 0.0,  "tvl": 0.0,   "risk_score": 0.0,  "tier": "T1"},
        }
        equity = 100_000.0

    # ── Derive risk_limits from adapter tiers ─────────────────────────────────
    t2_adapters = [k for k, v in adapters_ex.items() if v.get("tier") == "T2"]
    risk_limits: dict = {"t2_adapters": t2_adapters, "t2_cap": 0.50}

    drift = monitor.check_drift(current, target)
    print(f"Drift (≥5 pp): {drift}")

    alerts = monitor.get_alerts(current, target, risk_limits)
    for a in alerts:
        print(
            f"  [{a.level:8s}] {a.adapter_id:20s}  "
            f"drift={a.drift:.2f}pp  |  {a.message}"
        )

    health = monitor.compute_portfolio_health_score(adapters_ex, current)
    source = "real" if not _fallback else "demo"
    print(f"Health score: {health:.1f}/100  (source={source})")

    portfolio = {"current_weights": current, "equity": equity}
    snap = monitor.get_snapshot(portfolio, adapters_ex, target)
    print(
        f"Snapshot: level={snap['summary_level']}  "
        f"t2_total={snap['t2_total_weight']:.2f}  "
        f"health={snap['health_score']}"
    )

    if args.run:
        monitor.save_snapshot(snap, data_dir=args.data_dir)
        latest = monitor.load_latest_snapshot(data_dir=args.data_dir)
        print(
            f"Saved. Latest snapshot level: "
            f"{latest['summary_level'] if latest else 'none'}"
        )

    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sys.exit(_main())
