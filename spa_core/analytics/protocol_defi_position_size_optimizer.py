"""
MP-1029: ProtocolDeFiPositionSizeOptimizer

Optimizes DeFi position sizes using Kelly Criterion adaptation,
accounting for liquidity constraints and concentration risk.
Read-only analytics module. Writes ring-buffer log to
data/position_size_optimizer_log.json (cap 100, atomic write).

stdlib only — no external dependencies.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

LOG_CAP = 100
_LOG_FILENAME = "position_size_optimizer_log.json"

VALID_LABELS = frozenset({
    "FULL_KELLY",
    "HALF_KELLY",
    "QUARTER_KELLY",
    "MINIMAL_POSITION",
    "DO_NOT_ENTER",
})

VALID_FLAGS = frozenset({
    "HIGH_CONFIDENCE_OPPORTUNITY",
    "KELLY_POSITIVE",
    "LARGE_POOL_IMPACT",
    "ILLIQUID_EXIT",
    "CONCENTRATED_RISK",
    "DIVERSIFICATION_REQUIRED",
})


class ProtocolDeFiPositionSizeOptimizer:
    """
    Optimizes DeFi position sizes using Kelly Criterion adaptation.

    Each opportunity dict keys:
        name                      str
        protocol                  str
        expected_apy_pct          float   e.g. 12.5 (%)
        apy_confidence_pct        float   0-100
        max_loss_scenario_pct     float   worst-case drawdown (%)
        protocol_risk_score       float   0-100
        tvl_usd                   float
        our_position_impact_pct   float   our capital as % of pool TVL
        max_single_position_pct   float   hard cap (risk policy)
        portfolio_total_usd       float
        min_viable_size_usd       float
        liquidity_exit_days       float   days to exit without major impact
    """

    def __init__(self, data_dir: str = "data") -> None:
        self.data_dir = data_dir

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def optimize(self, opportunities: list, config: dict) -> dict:
        """
        Optimize position sizes for a list of DeFi opportunities.

        Args:
            opportunities: list[dict] — each dict describes one opportunity.
            config:        dict — optional overrides:
                             log_enabled (bool, default True)
                             data_dir    (str, overrides self.data_dir)

        Returns:
            dict with keys: timestamp, module, mp,
                            opportunity_count, opportunities, aggregates
        """
        if not isinstance(opportunities, list):
            raise TypeError("opportunities must be a list")
        if not isinstance(config, dict):
            raise TypeError("config must be a dict")

        data_dir = config.get("data_dir", self.data_dir)
        log_enabled = config.get("log_enabled", True)

        results = [self._analyze_opportunity(o) for o in opportunities]
        aggregates = self._compute_aggregates(results)

        output = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "module": "ProtocolDeFiPositionSizeOptimizer",
            "mp": "MP-1029",
            "opportunity_count": len(results),
            "opportunities": results,
            "aggregates": aggregates,
        }

        if log_enabled:
            self._append_log(output, data_dir)

        return output

    # ------------------------------------------------------------------
    # Per-opportunity analysis
    # ------------------------------------------------------------------

    def _analyze_opportunity(self, opp: dict) -> dict:
        name = str(opp.get("name", "unknown"))
        protocol = str(opp.get("protocol", "unknown"))
        expected_apy = float(opp.get("expected_apy_pct", 0.0))
        confidence = float(opp.get("apy_confidence_pct", 0.0))
        max_loss = float(opp.get("max_loss_scenario_pct", 100.0))
        our_impact = float(opp.get("our_position_impact_pct", 0.0))
        max_single = float(opp.get("max_single_position_pct", 20.0))
        portfolio_total = float(opp.get("portfolio_total_usd", 100_000.0))
        exit_days = float(opp.get("liquidity_exit_days", 1.0))

        # Clamp
        confidence = max(0.0, min(100.0, confidence))
        our_impact = max(0.0, our_impact)
        max_single = max(0.0, min(100.0, max_single))
        exit_days = max(0.0, exit_days)

        # --- Kelly fraction f* = (p*b - q) / b ---
        kelly_fraction = self._compute_kelly(expected_apy, confidence, max_loss)

        # --- Half-Kelly percentage ---
        half_kelly_pct = max(0.0, (kelly_fraction / 2.0) * 100.0)

        # --- Impact-adjusted pct ---
        impact_adj_pct = self._apply_impact_adjustment(half_kelly_pct, our_impact)

        # --- Label (needed before optimal_pct) ---
        label = self._determine_label(kelly_fraction, confidence, max_loss)

        # --- Optimal position pct ---
        if label == "DO_NOT_ENTER":
            optimal_pct = 0.0
        else:
            optimal_pct = min(half_kelly_pct, max_single, impact_adj_pct)
            optimal_pct = max(0.0, optimal_pct)

        optimal_usd = optimal_pct / 100.0 * portfolio_total

        # --- Position score (0-100) ---
        position_score = self._compute_position_score(
            label, expected_apy, confidence, exit_days
        )

        # --- Flags ---
        flags = self._compute_flags(
            confidence,
            kelly_fraction,
            our_impact,
            exit_days,
            optimal_pct,
            max_single,
            half_kelly_pct,
        )

        return {
            "name": name,
            "protocol": protocol,
            "expected_apy_pct": expected_apy,
            "kelly_fraction": round(kelly_fraction, 6),
            "half_kelly_pct": round(half_kelly_pct, 4),
            "position_impact_adjusted_pct": round(impact_adj_pct, 4),
            "optimal_position_pct": round(optimal_pct, 4),
            "optimal_position_usd": round(optimal_usd, 2),
            "position_score": round(position_score, 4),
            "label": label,
            "flags": flags,
        }

    # ------------------------------------------------------------------
    # Sub-computations (exposed for unit testing)
    # ------------------------------------------------------------------

    def _compute_kelly(
        self,
        expected_apy: float,
        confidence: float,
        max_loss: float,
    ) -> float:
        """
        Kelly fraction f* = (p*b - q) / b
        where b = expected_apy / max_loss (win-to-loss ratio),
              p = confidence / 100,
              q = 1 - p.
        Returns negative value when kelly is negative (don't enter).
        Returns 0.0 when max_loss == 0.
        """
        if max_loss <= 0.0:
            return 0.0
        p = confidence / 100.0
        q = 1.0 - p
        b = expected_apy / max_loss
        if b <= 0.0:
            return -1.0
        return (p * b - q) / b

    def _apply_impact_adjustment(
        self, half_kelly_pct: float, our_impact: float
    ) -> float:
        """Reduce position if our capital would impact the pool > 5%."""
        if our_impact > 5.0:
            return half_kelly_pct * (5.0 / our_impact)
        return half_kelly_pct

    def _determine_label(
        self,
        kelly_fraction: float,
        confidence: float,
        max_loss: float,
    ) -> str:
        """Assign position size label."""
        if kelly_fraction < 0.0 or confidence < 20.0 or max_loss > 50.0:
            return "DO_NOT_ENTER"
        kelly_pct = kelly_fraction * 100.0
        if kelly_pct > 10.0 and confidence > 80.0:
            return "FULL_KELLY"
        if kelly_pct >= 5.0:
            return "HALF_KELLY"
        if kelly_pct >= 2.0:
            return "QUARTER_KELLY"
        return "MINIMAL_POSITION"

    def _compute_position_score(
        self,
        label: str,
        expected_apy: float,
        confidence: float,
        exit_days: float,
    ) -> float:
        """Position score 0-100."""
        if label == "DO_NOT_ENTER":
            return 0.0
        expected_value = expected_apy * (confidence / 100.0)
        liquidity_factor = min(1.0, 7.0 / max(1.0, exit_days))
        score = min(100.0, expected_value * 2.0 * liquidity_factor)
        return max(0.0, score)

    def _compute_flags(
        self,
        confidence: float,
        kelly_fraction: float,
        our_impact: float,
        exit_days: float,
        optimal_pct: float,
        max_single: float,
        half_kelly_pct: float,
    ) -> list:
        flags = []
        if confidence > 80.0:
            flags.append("HIGH_CONFIDENCE_OPPORTUNITY")
        if kelly_fraction > 0.0:
            flags.append("KELLY_POSITIVE")
        if our_impact > 3.0:
            flags.append("LARGE_POOL_IMPACT")
        if exit_days > 7.0:
            flags.append("ILLIQUID_EXIT")
        if optimal_pct > 20.0:
            flags.append("CONCENTRATED_RISK")
        if half_kelly_pct > max_single:
            flags.append("DIVERSIFICATION_REQUIRED")
        return flags

    # ------------------------------------------------------------------
    # Aggregates
    # ------------------------------------------------------------------

    def _compute_aggregates(self, results: list) -> dict:
        if not results:
            return {
                "best_opportunity": None,
                "avoid_list": [],
                "total_optimal_allocation_pct": 0.0,
                "do_not_enter_count": 0,
                "full_kelly_count": 0,
            }

        non_dne = [r for r in results if r["label"] != "DO_NOT_ENTER"]
        best = max(non_dne, key=lambda r: r["position_score"]) if non_dne else None

        avoid_list = [r["name"] for r in results if r["label"] == "DO_NOT_ENTER"]
        total_pct = sum(r["optimal_position_pct"] for r in results)
        do_not_enter_count = sum(1 for r in results if r["label"] == "DO_NOT_ENTER")
        full_kelly_count = sum(1 for r in results if r["label"] == "FULL_KELLY")

        return {
            "best_opportunity": best["name"] if best else None,
            "avoid_list": avoid_list,
            "total_optimal_allocation_pct": round(total_pct, 4),
            "do_not_enter_count": do_not_enter_count,
            "full_kelly_count": full_kelly_count,
        }

    # ------------------------------------------------------------------
    # Ring-buffer log (atomic write)
    # ------------------------------------------------------------------

    def _append_log(self, record: dict, data_dir: str) -> None:
        """Append compact entry to ring-buffer log (cap=LOG_CAP). Atomic."""
        os.makedirs(data_dir, exist_ok=True)
        log_path = os.path.join(data_dir, _LOG_FILENAME)

        try:
            with open(log_path, "r") as fh:
                log: list = json.load(fh)
            if not isinstance(log, list):
                log = []
        except (FileNotFoundError, json.JSONDecodeError):
            log = []

        entry = {
            "timestamp": record["timestamp"],
            "opportunity_count": record["opportunity_count"],
            "aggregates": record["aggregates"],
        }
        log.append(entry)
        log = log[-LOG_CAP:]  # ring-buffer trim

        tmp_path = log_path + ".tmp"
        with open(tmp_path, "w") as fh:
            json.dump(log, fh, indent=2)
        os.replace(tmp_path, log_path)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="MP-1029 ProtocolDeFiPositionSizeOptimizer"
    )
    parser.add_argument("--check", action="store_true", help="Compute and print, no write")
    parser.add_argument("--run", action="store_true", help="Compute and write log")
    parser.add_argument("--data-dir", default="data", help="Data directory")
    args = parser.parse_args()

    _sample = [
        {
            "name": "Aave USDC Lending",
            "protocol": "Aave V3",
            "expected_apy_pct": 8.5,
            "apy_confidence_pct": 85.0,
            "max_loss_scenario_pct": 5.0,
            "protocol_risk_score": 20.0,
            "tvl_usd": 5_000_000_000,
            "our_position_impact_pct": 0.01,
            "max_single_position_pct": 25.0,
            "portfolio_total_usd": 100_000.0,
            "min_viable_size_usd": 1_000.0,
            "liquidity_exit_days": 1.0,
        },
        {
            "name": "Risky Farm",
            "protocol": "UnknownProtocol",
            "expected_apy_pct": 200.0,
            "apy_confidence_pct": 15.0,
            "max_loss_scenario_pct": 80.0,
            "protocol_risk_score": 90.0,
            "tvl_usd": 100_000,
            "our_position_impact_pct": 10.0,
            "max_single_position_pct": 5.0,
            "portfolio_total_usd": 100_000.0,
            "min_viable_size_usd": 500.0,
            "liquidity_exit_days": 14.0,
        },
    ]

    _optimizer = ProtocolDeFiPositionSizeOptimizer(data_dir=args.data_dir)
    _log_enabled = args.run and not args.check
    _result = _optimizer.optimize(_sample, config={"log_enabled": _log_enabled})

    import json as _json
    print(_json.dumps(_result, indent=2))
