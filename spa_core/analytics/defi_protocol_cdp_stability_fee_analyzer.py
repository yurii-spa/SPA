"""
DeFiProtocolCdpStabilityFeeAnalyzer
MP-1082: CDP collateralization, stability fee, and health analysis.

Read-only advisory module. No trades. Pure stdlib. Atomic writes.
Ring-buffer log capped at 100 entries (data/cdp_stability_fee_log.json).
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


class DeFiProtocolCdpStabilityFeeAnalyzer:
    """
    Analyzes CDP (Collateralized Debt Position) stability fee mechanics,
    collateralization health, and liquidation risk.

    Inputs (dict keys):
        protocol_name           - name of the lending/CDP protocol
        collateral_asset        - collateral token symbol
        collateral_value_usd    - current USD value of posted collateral
        debt_usd                - outstanding debt in USD
        stability_fee_pct       - annual stability / borrow fee (%)
        liquidation_ratio_pct   - minimum collateralization ratio (%)
        current_price_usd       - current market price of collateral asset
        target_price_usd        - peg / target price (for stablecoins = 1.0)
        surplus_buffer_usd      - protocol surplus buffer (bad-debt cushion)
        total_debt_ceiling_usd  - maximum allowed protocol-wide debt
        debt_utilization_pct    - current protocol debt / ceiling (%)

    Outputs (dict keys):
        collateralization_ratio_pct - collateral / debt * 100
        safe_debt_capacity_usd      - additional debt before liquidation threshold
        liquidation_price_usd       - collateral price that triggers liquidation
        fee_cost_usd_per_year       - annual fee cost on outstanding debt
        cdp_health_score            - 0-100 composite health score
        cdp_label                   - FORTRESS_CDP / SAFE / WATCH /
                                      DANGER / NEAR_LIQUIDATION

    Read-only / advisory. Never modifies allocator, risk, or execution.
    """

    LOG_PATH: str = "data/cdp_stability_fee_log.json"
    MAX_LOG_ENTRIES: int = 100

    def __init__(self, log_path: str = None) -> None:
        self.log_path = log_path if log_path is not None else self.LOG_PATH

    # ------------------------------------------------------------------
    # Primary API
    # ------------------------------------------------------------------

    def analyze(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze a CDP and return health metrics.

        Parameters
        ----------
        data : dict
            See class docstring for required keys.

        Returns
        -------
        dict with keys: protocol_name, collateral_asset,
            collateralization_ratio_pct, safe_debt_capacity_usd,
            liquidation_price_usd, fee_cost_usd_per_year,
            cdp_health_score, cdp_label
        """
        # --- input parsing ----------------------------------------------------
        protocol_name = str(data.get("protocol_name", ""))
        collateral_asset = str(data.get("collateral_asset", ""))
        collateral_value_usd = float(data.get("collateral_value_usd", 0.0))
        debt_usd = float(data.get("debt_usd", 0.0))
        stability_fee_pct = float(data.get("stability_fee_pct", 0.0))
        liquidation_ratio_pct = float(data.get("liquidation_ratio_pct", 150.0))
        current_price_usd = float(data.get("current_price_usd", 1.0))
        target_price_usd = float(data.get("target_price_usd", 1.0))
        # surplus_buffer_usd and total_debt_ceiling_usd feed protocol-risk
        surplus_buffer_usd = float(data.get("surplus_buffer_usd", 0.0))
        total_debt_ceiling_usd = float(data.get("total_debt_ceiling_usd", 1.0))
        debt_utilization_pct = float(data.get("debt_utilization_pct", 0.0))

        # --- collateralization ratio ------------------------------------------
        if debt_usd > 0.0:
            collateralization_ratio_pct = round(
                collateral_value_usd / debt_usd * 100.0, 4
            )
        else:
            collateralization_ratio_pct = 0.0

        # --- safe debt capacity ----------------------------------------------
        # How much additional debt can be taken before hitting liquidation ratio
        # max_safe_debt = collateral_value / (liquidation_ratio / 100)
        if liquidation_ratio_pct > 0.0:
            max_safe_debt = collateral_value_usd / (liquidation_ratio_pct / 100.0)
        else:
            max_safe_debt = 0.0
        safe_debt_capacity_usd = round(max(0.0, max_safe_debt - debt_usd), 4)

        # --- liquidation price -----------------------------------------------
        # Price at which: collateral_amount * price = debt * (liq_ratio / 100)
        # => price = debt * (liq_ratio / 100) / collateral_amount
        if current_price_usd > 0.0 and collateral_value_usd > 0.0:
            collateral_amount = collateral_value_usd / current_price_usd
            if collateral_amount > 0.0 and debt_usd > 0.0:
                liquidation_price_usd = round(
                    debt_usd * (liquidation_ratio_pct / 100.0) / collateral_amount,
                    6,
                )
            else:
                liquidation_price_usd = 0.0
        else:
            liquidation_price_usd = 0.0

        # --- annual fee cost -------------------------------------------------
        fee_cost_usd_per_year = round(debt_usd * stability_fee_pct / 100.0, 4)

        # --- CDP health score (0-100) ----------------------------------------
        cdp_health_score = self._compute_health_score(
            collateralization_ratio_pct=collateralization_ratio_pct,
            liquidation_ratio_pct=liquidation_ratio_pct,
            debt_usd=debt_usd,
            stability_fee_pct=stability_fee_pct,
            current_price_usd=current_price_usd,
            target_price_usd=target_price_usd,
            surplus_buffer_usd=surplus_buffer_usd,
            total_debt_ceiling_usd=total_debt_ceiling_usd,
            debt_utilization_pct=debt_utilization_pct,
        )

        # --- label -----------------------------------------------------------
        cdp_label = self._assign_label(cdp_health_score)

        return {
            "protocol_name": protocol_name,
            "collateral_asset": collateral_asset,
            "collateralization_ratio_pct": collateralization_ratio_pct,
            "safe_debt_capacity_usd": safe_debt_capacity_usd,
            "liquidation_price_usd": liquidation_price_usd,
            "fee_cost_usd_per_year": fee_cost_usd_per_year,
            "cdp_health_score": cdp_health_score,
            "cdp_label": cdp_label,
        }

    def analyze_and_log(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze CDP and atomically append result to ring-buffer log."""
        result = self.analyze(data)
        self._append_log(result)
        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _compute_health_score(
        self,
        collateralization_ratio_pct: float,
        liquidation_ratio_pct: float,
        debt_usd: float,
        stability_fee_pct: float,
        current_price_usd: float,
        target_price_usd: float,
        surplus_buffer_usd: float,
        total_debt_ceiling_usd: float,
        debt_utilization_pct: float,
    ) -> float:
        """Compute composite CDP health score (0-100)."""
        if debt_usd <= 0.0:
            # No debt → perfectly healthy
            return 100.0

        # 1. Safety margin: how far above liquidation threshold (%)
        if liquidation_ratio_pct > 0.0:
            safety_margin_pct = (
                (collateralization_ratio_pct - liquidation_ratio_pct)
                / liquidation_ratio_pct
                * 100.0
            )
        else:
            safety_margin_pct = 0.0

        # Base score: 0.65 multiplier → 100% safety margin yields 65 base pts.
        # A safety margin of ~154% maps to 100 (before deductions).
        base_score = min(100.0, max(0.0, safety_margin_pct * 0.65))

        # 2. Peg deviation penalty (for pegged collateral losing its peg)
        peg_penalty = 0.0
        if target_price_usd > 0.0:
            peg_dev_pct = (
                abs(current_price_usd - target_price_usd) / target_price_usd * 100.0
            )
            peg_penalty = min(20.0, peg_dev_pct * 2.0)

        # 3. Debt ceiling utilization penalty (protocol-level systemic risk)
        if debt_utilization_pct >= 95.0:
            util_penalty = 20.0
        elif debt_utilization_pct >= 90.0:
            util_penalty = 15.0
        elif debt_utilization_pct >= 80.0:
            util_penalty = 8.0
        elif debt_utilization_pct >= 70.0:
            util_penalty = 4.0
        else:
            util_penalty = 0.0

        # 4. Stability fee drag (high fee erodes position over time)
        fee_penalty = min(10.0, stability_fee_pct * 0.5)

        # 5. Surplus buffer bonus (deeper cushion = better protocol health)
        #    Capped at +5 pts; only meaningful when buffer > 0
        if total_debt_ceiling_usd > 0.0 and surplus_buffer_usd > 0.0:
            buffer_ratio = surplus_buffer_usd / total_debt_ceiling_usd
            buffer_bonus = min(5.0, buffer_ratio * 500.0)
        else:
            buffer_bonus = 0.0

        raw = base_score - peg_penalty - util_penalty - fee_penalty + buffer_bonus
        return round(max(0.0, min(100.0, raw)), 4)

    @staticmethod
    def _assign_label(score: float) -> str:
        """Map health score to human-readable label."""
        if score >= 80.0:
            return "FORTRESS_CDP"
        if score >= 60.0:
            return "SAFE"
        if score >= 40.0:
            return "WATCH"
        if score >= 20.0:
            return "DANGER"
        return "NEAR_LIQUIDATION"

    def _append_log(self, entry: Dict[str, Any]) -> None:
        """Atomically append entry to JSON ring-buffer log (cap 100)."""
        log_path = Path(self.log_path)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        existing: list = []
        if log_path.exists():
            try:
                with open(log_path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                if isinstance(data, list):
                    existing = data
            except (json.JSONDecodeError, OSError):
                existing = []

        record = dict(entry)
        record["_logged_at"] = datetime.now(timezone.utc).isoformat()
        existing.append(record)

        if len(existing) > self.MAX_LOG_ENTRIES:
            existing = existing[-self.MAX_LOG_ENTRIES :]

        tmp_path = str(log_path) + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(existing, fh, indent=2)
        os.replace(tmp_path, str(log_path))
