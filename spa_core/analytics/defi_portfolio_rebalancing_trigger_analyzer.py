"""
MP-950 DeFiPortfolioRebalancingTriggerAnalyzer
Advisory/read-only analytics module.
Analyzes rebalancing triggers for DeFi portfolios based on drift, cost, volatility
regime, and time-since-last-rebalance.

Pure stdlib. Atomic writes via tmp + os.replace.
Ring-buffer log → data/rebalancing_trigger_log.json (cap 100).

Labels: IMMEDIATE / RECOMMENDED / OPTIONAL / HOLD / JUST_REBALANCED
Flags:  DRIFT_EXCEEDED / HIGH_VOLATILITY_REGIME / TAX_HARVEST_OPPORTUNITY /
        COST_PROHIBITIVE / OVERDUE

CLI:
  python3 -m spa_core.analytics.defi_portfolio_rebalancing_trigger_analyzer --check
  python3 -m spa_core.analytics.defi_portfolio_rebalancing_trigger_analyzer --run
"""
from __future__ import annotations

import json
import math
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _PROJECT_ROOT / "data"
_LOG_FILENAME = "rebalancing_trigger_log.json"
_RING_CAP = 100

LABEL_IMMEDIATE = "IMMEDIATE"
LABEL_RECOMMENDED = "RECOMMENDED"
LABEL_OPTIONAL = "OPTIONAL"
LABEL_HOLD = "HOLD"
LABEL_JUST_REBALANCED = "JUST_REBALANCED"

FLAG_DRIFT_EXCEEDED = "DRIFT_EXCEEDED"
FLAG_HIGH_VOLATILITY = "HIGH_VOLATILITY_REGIME"
FLAG_TAX_HARVEST = "TAX_HARVEST_OPPORTUNITY"
FLAG_COST_PROHIBITIVE = "COST_PROHIBITIVE"
FLAG_OVERDUE = "OVERDUE"

_VOLATILITY_MULTIPLIERS = {
    "low": 0.7,
    "normal": 1.0,
    "high": 1.4,
}

_DEFAULT_DRIFT_THRESHOLD = 5.0          # pct
_DEFAULT_JUST_REBALANCED_DAYS = 2       # days
_COST_PROHIBITIVE_THRESHOLD = 0.01     # 1% of value
_OVERDUE_DAYS = 90
_OVERDUE_DRIFT = 5.0


# ---------------------------------------------------------------------------
# Core class
# ---------------------------------------------------------------------------

class DeFiPortfolioRebalancingTriggerAnalyzer:
    """Analyzes rebalancing triggers across a list of DeFi portfolios."""

    def __init__(self, data_dir: str | Path | None = None) -> None:
        self._data_dir = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self, portfolios: list[dict], config: dict | None = None) -> dict:
        """Analyze rebalancing triggers for a list of portfolios.

        Parameters
        ----------
        portfolios:
            List of portfolio dicts.  Each must contain at minimum:
            ``name``, ``target_allocations``, ``current_allocations``,
            ``total_value_usd``, ``last_rebalance_days_ago``,
            ``tx_cost_estimate_usd``.
            Optional: ``drift_threshold_pct``, ``volatility_regime``,
            ``tax_harvesting_opportunity``.
        config:
            Global override dict.  Keys: ``drift_threshold_pct``,
            ``just_rebalanced_days``, ``cost_prohibitive_threshold``.

        Returns
        -------
        dict with keys:
            ``portfolios``, ``aggregates``, ``analyzed_at``.
        """
        cfg = self._merge_config(config or {})
        results = []
        for p in portfolios:
            results.append(self._analyze_portfolio(p, cfg))

        aggregates = self._compute_aggregates(results)

        output = {
            "portfolios": results,
            "aggregates": aggregates,
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
        }
        return output

    # ------------------------------------------------------------------
    # Per-portfolio analysis
    # ------------------------------------------------------------------

    def _analyze_portfolio(self, p: dict, global_cfg: dict) -> dict:
        name = str(p.get("name", "unknown"))
        target_alloc: dict = dict(p.get("target_allocations", {}))
        current_alloc: dict = dict(p.get("current_allocations", {}))
        total_value_usd = float(p.get("total_value_usd", 0.0))
        last_rebalance_days = float(p.get("last_rebalance_days_ago", 0.0))
        tx_cost_usd = float(p.get("tx_cost_estimate_usd", 0.0))
        drift_threshold = float(
            p.get("drift_threshold_pct", global_cfg["drift_threshold_pct"])
        )
        vol_regime = str(p.get("volatility_regime", "normal")).lower()
        tax_harvest = bool(p.get("tax_harvesting_opportunity", False))

        # Normalize allocations to ensure sum == 100
        target_alloc = self._normalize_alloc(target_alloc)
        current_alloc = self._normalize_alloc(current_alloc)

        # Per-asset drift
        all_assets = set(target_alloc) | set(current_alloc)
        drifts: list[float] = []
        for asset in all_assets:
            t = target_alloc.get(asset, 0.0)
            c = current_alloc.get(asset, 0.0)
            drifts.append(abs(c - t))

        max_drift_pct = max(drifts) if drifts else 0.0

        # Weighted drift score: sum of |drift| weighted by target alloc (0-100)
        weighted_drift_score = self._weighted_drift_score(
            target_alloc, current_alloc, all_assets
        )

        # Cost as pct of portfolio value
        if total_value_usd > 0:
            rebalance_cost_as_pct_value = (tx_cost_usd / total_value_usd) * 100.0
        else:
            rebalance_cost_as_pct_value = 0.0

        # Urgency score (0-100)
        urgency_score = self._urgency_score(
            max_drift_pct=max_drift_pct,
            drift_threshold=drift_threshold,
            last_rebalance_days=last_rebalance_days,
            vol_regime=vol_regime,
            rebalance_cost_as_pct_value=rebalance_cost_as_pct_value,
        )

        # Trigger label
        label = self._assign_label(
            urgency_score=urgency_score,
            last_rebalance_days=last_rebalance_days,
            just_rebalanced_days=global_cfg["just_rebalanced_days"],
            rebalance_cost_as_pct_value=rebalance_cost_as_pct_value,
        )

        # Flags
        flags = self._compute_flags(
            max_drift_pct=max_drift_pct,
            drift_threshold=drift_threshold,
            vol_regime=vol_regime,
            tax_harvest=tax_harvest,
            rebalance_cost_as_pct_value=rebalance_cost_as_pct_value,
            last_rebalance_days=last_rebalance_days,
        )

        return {
            "name": name,
            "max_drift_pct": round(max_drift_pct, 4),
            "weighted_drift_score": round(weighted_drift_score, 4),
            "rebalance_cost_as_pct_value": round(rebalance_cost_as_pct_value, 6),
            "urgency_score": round(urgency_score, 4),
            "label": label,
            "flags": flags,
            "drift_threshold_pct": drift_threshold,
            "volatility_regime": vol_regime,
            "last_rebalance_days_ago": last_rebalance_days,
            "tx_cost_estimate_usd": tx_cost_usd,
            "total_value_usd": total_value_usd,
            "tax_harvesting_opportunity": tax_harvest,
        }

    # ------------------------------------------------------------------
    # Drift helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_alloc(alloc: dict) -> dict[str, float]:
        """Normalize allocation dict so values are floats; don't enforce sum."""
        return {k: float(v) for k, v in alloc.items()}

    @staticmethod
    def _weighted_drift_score(
        target_alloc: dict,
        current_alloc: dict,
        all_assets: set,
    ) -> float:
        """Weighted drift score 0-100.

        Each asset's drift contribution is weighted by its target allocation.
        A portfolio perfectly on target scores 0; one fully inverted scores 100.
        """
        total_target = sum(target_alloc.values())
        if total_target <= 0:
            # Fall back to simple average drift
            drifts = [abs(current_alloc.get(a, 0.0) - target_alloc.get(a, 0.0))
                      for a in all_assets]
            return min(100.0, sum(drifts) / max(len(drifts), 1))

        score = 0.0
        for asset in all_assets:
            t = target_alloc.get(asset, 0.0)
            c = current_alloc.get(asset, 0.0)
            weight = t / total_target          # fraction of target allocation
            drift_pct = abs(c - t)             # percentage points
            score += weight * drift_pct        # weighted contribution

        # Normalise to 0-100: max possible weighted drift ≈ 100 pct-pts
        return min(100.0, score)

    # ------------------------------------------------------------------
    # Urgency score
    # ------------------------------------------------------------------

    def _urgency_score(
        self,
        max_drift_pct: float,
        drift_threshold: float,
        last_rebalance_days: float,
        vol_regime: str,
        rebalance_cost_as_pct_value: float,
    ) -> float:
        """Compute composite urgency score 0-100."""
        # Drift component (0-50)
        if drift_threshold > 0:
            drift_ratio = max_drift_pct / drift_threshold
        else:
            drift_ratio = max_drift_pct / _DEFAULT_DRIFT_THRESHOLD

        drift_component = min(50.0, drift_ratio * 25.0)

        # Time component (0-30) — ramps to 30 at 90 days
        time_component = min(30.0, (last_rebalance_days / 90.0) * 30.0)

        # Volatility multiplier
        vol_mult = _VOLATILITY_MULTIPLIERS.get(vol_regime, 1.0)

        # Cost penalty (0-20) — high cost suppresses urgency
        if rebalance_cost_as_pct_value > 0:
            cost_penalty = min(20.0, rebalance_cost_as_pct_value * 100.0)
        else:
            cost_penalty = 0.0

        raw = (drift_component + time_component) * vol_mult - cost_penalty
        return max(0.0, min(100.0, raw))

    # ------------------------------------------------------------------
    # Label assignment
    # ------------------------------------------------------------------

    @staticmethod
    def _assign_label(
        urgency_score: float,
        last_rebalance_days: float,
        just_rebalanced_days: float,
        rebalance_cost_as_pct_value: float,
    ) -> str:
        if last_rebalance_days < just_rebalanced_days:
            return LABEL_JUST_REBALANCED
        if rebalance_cost_as_pct_value > _COST_PROHIBITIVE_THRESHOLD * 100:
            # Extremely cost-prohibitive → demote at most to HOLD unless very urgent
            if urgency_score >= 70:
                return LABEL_RECOMMENDED
            return LABEL_HOLD
        if urgency_score >= 70:
            return LABEL_IMMEDIATE
        if urgency_score >= 40:
            return LABEL_RECOMMENDED
        if urgency_score >= 15:
            return LABEL_OPTIONAL
        return LABEL_HOLD

    # ------------------------------------------------------------------
    # Flags
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_flags(
        max_drift_pct: float,
        drift_threshold: float,
        vol_regime: str,
        tax_harvest: bool,
        rebalance_cost_as_pct_value: float,
        last_rebalance_days: float,
    ) -> list[str]:
        flags: list[str] = []
        if max_drift_pct > drift_threshold:
            flags.append(FLAG_DRIFT_EXCEEDED)
        if vol_regime == "high":
            flags.append(FLAG_HIGH_VOLATILITY)
        if tax_harvest:
            flags.append(FLAG_TAX_HARVEST)
        if rebalance_cost_as_pct_value > _COST_PROHIBITIVE_THRESHOLD * 100:
            flags.append(FLAG_COST_PROHIBITIVE)
        if last_rebalance_days > _OVERDUE_DAYS and max_drift_pct > _OVERDUE_DRIFT:
            flags.append(FLAG_OVERDUE)
        return flags

    # ------------------------------------------------------------------
    # Aggregates
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_aggregates(results: list[dict]) -> dict:
        if not results:
            return {
                "most_urgent_portfolio": None,
                "least_urgent_portfolio": None,
                "total_portfolios_needing_rebalance": 0,
                "average_drift": 0.0,
                "immediate_count": 0,
                "total_portfolios": 0,
            }

        sorted_by_urgency = sorted(results, key=lambda r: r["urgency_score"], reverse=True)
        most_urgent = sorted_by_urgency[0]["name"]
        least_urgent = sorted_by_urgency[-1]["name"]

        needs_rebalance = [
            r for r in results
            if r["label"] in (LABEL_IMMEDIATE, LABEL_RECOMMENDED, LABEL_OPTIONAL)
        ]
        average_drift = sum(r["max_drift_pct"] for r in results) / len(results)
        immediate_count = sum(1 for r in results if r["label"] == LABEL_IMMEDIATE)

        return {
            "most_urgent_portfolio": most_urgent,
            "least_urgent_portfolio": least_urgent,
            "total_portfolios_needing_rebalance": len(needs_rebalance),
            "average_drift": round(average_drift, 4),
            "immediate_count": immediate_count,
            "total_portfolios": len(results),
        }

    # ------------------------------------------------------------------
    # Config merge
    # ------------------------------------------------------------------

    @staticmethod
    def _merge_config(config: dict) -> dict:
        return {
            "drift_threshold_pct": float(
                config.get("drift_threshold_pct", _DEFAULT_DRIFT_THRESHOLD)
            ),
            "just_rebalanced_days": float(
                config.get("just_rebalanced_days", _DEFAULT_JUST_REBALANCED_DAYS)
            ),
            "cost_prohibitive_threshold": float(
                config.get("cost_prohibitive_threshold", _COST_PROHIBITIVE_THRESHOLD)
            ),
        }

    # ------------------------------------------------------------------
    # Ring-buffer log (atomic write)
    # ------------------------------------------------------------------

    def write_log(self, output: dict) -> Path:
        """Append ``output`` to ring-buffer log, capped at _RING_CAP entries."""
        log_path = self._data_dir / _LOG_FILENAME
        try:
            with open(log_path) as f:
                log = json.load(f)
            if not isinstance(log, list):
                log = []
        except (FileNotFoundError, json.JSONDecodeError):
            log = []

        log.append(output)
        if len(log) > _RING_CAP:
            log = log[-_RING_CAP:]

        self._atomic_write(log_path, log)
        return log_path

    @staticmethod
    def _atomic_write(path: Path, data: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp_")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp, str(path))
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _sample_portfolios() -> list[dict]:
    return [
        {
            "name": "Core DeFi",
            "target_allocations": {"USDC_Aave": 40, "USDC_Compound": 30, "ETH_Lido": 30},
            "current_allocations": {"USDC_Aave": 50, "USDC_Compound": 25, "ETH_Lido": 25},
            "total_value_usd": 100_000,
            "last_rebalance_days_ago": 14,
            "tx_cost_estimate_usd": 80,
            "drift_threshold_pct": 5.0,
            "volatility_regime": "normal",
            "tax_harvesting_opportunity": False,
        },
        {
            "name": "Yield Farm",
            "target_allocations": {"USDC_Morpho": 50, "USDC_Yearn": 50},
            "current_allocations": {"USDC_Morpho": 72, "USDC_Yearn": 28},
            "total_value_usd": 50_000,
            "last_rebalance_days_ago": 95,
            "tx_cost_estimate_usd": 120,
            "drift_threshold_pct": 8.0,
            "volatility_regime": "high",
            "tax_harvesting_opportunity": True,
        },
    ]


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    run_mode = "--run" in args

    data_dir: Path | None = None
    if "--data-dir" in args:
        idx = args.index("--data-dir")
        if idx + 1 < len(args):
            data_dir = Path(args[idx + 1])

    analyzer = DeFiPortfolioRebalancingTriggerAnalyzer(data_dir=data_dir)
    result = analyzer.analyze(_sample_portfolios())

    print(json.dumps(result, indent=2))

    if run_mode:
        path = analyzer.write_log(result)
        print(f"\n[MP-950] Log written → {path}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
