"""
MP-1087: Protocol DeFi Liquidation Cascade Risk Analyzer
Estimates liquidation cascade risk in DeFi lending markets.

Models what happens when collateral prices drop and liquidations trigger
more selling, amplifying the initial price move (reflexive feedback).

Pure Python stdlib only. No external dependencies.
Atomic writes (tmp + os.replace). Ring-buffer log cap 100.

Supersedes MP-1033 (same filename, extended interface).
"""

import json
import os
import time
from typing import Any, Dict, List


class ProtocolDeFiLiquidationCascadeRiskAnalyzer:
    """
    Estimates liquidation cascade risk given lending market parameters.

    Key computed outputs:
        buffer_to_liquidation_pct  — % price drop required to breach liq. threshold
        at_risk_collateral_usd     — collateral value after hypothetical price drop
        estimated_liquidations_usd — debt liquidated if drop scenario materialises
        market_impact_pct          — liquidations as % of daily volume (cascade proxy)
        cascade_risk_score         — 0 (safe) to 100 (systemic)
        cascade_label              — categorical severity label

    Labels (evaluated in priority order, most severe first):
        SYSTEMIC_CASCADE  — market_impact > 60% OR current_ltv > liquidation_threshold
        HIGH_CASCADE      — buffer < 5% OR market_impact >= 30%
        CASCADE_RISK      — buffer < 10% OR market_impact >= 15%
        WATCHLIST         — buffer <= 20% OR market_impact >= 5%
        SAFE_MARGINS      — buffer > 20% AND market_impact < 5%

    Risk score components:
        buffer_score  0–50:  min(50, max(0, (25 - buffer_pct) / 25 × 50))
        impact_score  0–40:  min(40, market_impact_pct / 60 × 40)
        ltv_bonus     0–10:  10 if current_ltv >= liquidation_threshold, else 0
    """

    LOG_FILE_NAME: str = "liquidation_cascade_risk_log.json"
    LOG_CAP: int = 100

    # Label constants
    SAFE_MARGINS: str = "SAFE_MARGINS"
    WATCHLIST: str = "WATCHLIST"
    CASCADE_RISK: str = "CASCADE_RISK"
    HIGH_CASCADE: str = "HIGH_CASCADE"
    SYSTEMIC_CASCADE: str = "SYSTEMIC_CASCADE"

    def __init__(self, data_dir: str = "data") -> None:
        self.data_dir = data_dir
        self.log_file = os.path.join(data_dir, self.LOG_FILE_NAME)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(
        self,
        total_collateral_usd: float,
        total_debt_usd: float,
        liquidation_threshold_pct: float,
        current_ltv_pct: float,
        price_drop_pct: float,
        liquidation_penalty_pct: float,
        protocol_tvl_usd: float,
        daily_volume_usd: float,
        protocol_name: str,
    ) -> Dict[str, Any]:
        """
        Analyze liquidation cascade risk.

        Args:
            total_collateral_usd:      Total collateral value in USD.
            total_debt_usd:            Total outstanding debt in USD.
            liquidation_threshold_pct: LTV % triggering liquidations (e.g. 80.0).
            current_ltv_pct:           Current loan-to-value percentage.
            price_drop_pct:            Hypothetical collateral price drop (%).
            liquidation_penalty_pct:   Bonus liquidators receive (e.g. 5.0 = 5%).
            protocol_tvl_usd:          Protocol total value locked.
            daily_volume_usd:          Market daily volume (liquidity proxy).
            protocol_name:             Human-readable protocol identifier.

        Returns:
            dict with keys:
                buffer_to_liquidation_pct  (float)
                at_risk_collateral_usd     (float)
                estimated_liquidations_usd (float)
                market_impact_pct          (float)
                cascade_risk_score         (int, 0–100)
                cascade_label              (str)
                log_entry                  (dict)
        """
        buffer_to_liquidation_pct: float = self._compute_buffer(
            current_ltv_pct, liquidation_threshold_pct
        )
        at_risk_collateral_usd: float = self._compute_at_risk_collateral(
            total_collateral_usd, price_drop_pct
        )
        estimated_liquidations_usd: float = self._compute_estimated_liquidations(
            total_debt_usd, at_risk_collateral_usd, liquidation_threshold_pct
        )
        market_impact_pct: float = self._compute_market_impact(
            estimated_liquidations_usd, daily_volume_usd
        )
        cascade_label: str = self._compute_cascade_label(
            buffer_to_liquidation_pct,
            market_impact_pct,
            current_ltv_pct,
            liquidation_threshold_pct,
        )
        cascade_risk_score: int = self._compute_cascade_risk_score(
            buffer_to_liquidation_pct,
            market_impact_pct,
            current_ltv_pct,
            liquidation_threshold_pct,
        )

        log_entry: Dict[str, Any] = {
            "protocol_name": protocol_name,
            "total_collateral_usd": total_collateral_usd,
            "total_debt_usd": total_debt_usd,
            "liquidation_threshold_pct": liquidation_threshold_pct,
            "current_ltv_pct": current_ltv_pct,
            "price_drop_pct": price_drop_pct,
            "liquidation_penalty_pct": liquidation_penalty_pct,
            "protocol_tvl_usd": protocol_tvl_usd,
            "daily_volume_usd": daily_volume_usd,
            "buffer_to_liquidation_pct": buffer_to_liquidation_pct,
            "at_risk_collateral_usd": at_risk_collateral_usd,
            "estimated_liquidations_usd": estimated_liquidations_usd,
            "market_impact_pct": market_impact_pct,
            "cascade_risk_score": cascade_risk_score,
            "cascade_label": cascade_label,
            "analyzed_at": time.time(),
        }

        return {
            "buffer_to_liquidation_pct": buffer_to_liquidation_pct,
            "at_risk_collateral_usd": at_risk_collateral_usd,
            "estimated_liquidations_usd": estimated_liquidations_usd,
            "market_impact_pct": market_impact_pct,
            "cascade_risk_score": cascade_risk_score,
            "cascade_label": cascade_label,
            "log_entry": log_entry,
        }

    def log_result(self, log_entry: Dict[str, Any]) -> None:
        """
        Append log_entry to ring-buffer log (cap=LOG_CAP, atomic write).
        Oldest entry is dropped when the cap is exceeded.
        """
        entries: List[Dict[str, Any]] = self._read_log()
        entries.append(log_entry)
        if len(entries) > self.LOG_CAP:
            entries = entries[-self.LOG_CAP :]
        self._write_log(entries)

    # ------------------------------------------------------------------
    # Static computation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_buffer(
        current_ltv_pct: float,
        liquidation_threshold_pct: float,
    ) -> float:
        """
        Buffer until liquidation as a price-drop percentage.

        buffer = 100 × (1 − current_ltv / liquidation_threshold)

        Interpretation: this is the percentage by which collateral prices can
        fall before the liquidation threshold is breached.
        Negative values indicate the threshold is already breached.
        Returns 0.0 if liquidation_threshold_pct is zero.
        """
        if liquidation_threshold_pct == 0.0:
            return 0.0
        return 100.0 * (1.0 - current_ltv_pct / liquidation_threshold_pct)

    @staticmethod
    def _compute_at_risk_collateral(
        total_collateral_usd: float,
        price_drop_pct: float,
    ) -> float:
        """
        Collateral value after the hypothetical price drop.
        Clamped to ≥ 0 (collateral cannot go negative).
        """
        return max(0.0, total_collateral_usd * (1.0 - price_drop_pct / 100.0))

    @staticmethod
    def _compute_estimated_liquidations(
        total_debt_usd: float,
        at_risk_collateral_usd: float,
        liquidation_threshold_pct: float,
    ) -> float:
        """
        Debt that would need to be liquidated to restore LTV to threshold.

        Model: estimated_liquidations = max(0, debt − threshold_ratio × collateral_post_drop)

        If post-drop collateral still supports the debt within the threshold, returns 0.
        Returns 0.0 if liquidation_threshold_pct ≤ 0.
        """
        if liquidation_threshold_pct <= 0.0:
            return 0.0
        threshold_ratio: float = liquidation_threshold_pct / 100.0
        safe_debt: float = threshold_ratio * at_risk_collateral_usd
        return max(0.0, total_debt_usd - safe_debt)

    @staticmethod
    def _compute_market_impact(
        estimated_liquidations_usd: float,
        daily_volume_usd: float,
    ) -> float:
        """
        Liquidation volume as a percentage of daily market volume (cascade proxy).

        Returns:
            0.0   — no liquidations
            100.0 — volume is zero but liquidations are positive (maximum impact)
            ratio — estimated_liquidations / daily_volume × 100 otherwise
        """
        if estimated_liquidations_usd <= 0.0:
            return 0.0
        if daily_volume_usd <= 0.0:
            return 100.0
        return estimated_liquidations_usd / daily_volume_usd * 100.0

    @staticmethod
    def _compute_cascade_label(
        buffer_to_liquidation_pct: float,
        market_impact_pct: float,
        current_ltv_pct: float,
        liquidation_threshold_pct: float,
    ) -> str:
        """
        Determine cascade severity label.  Most severe condition wins (priority order).

        1. market_impact > 60% OR current_ltv > threshold  → SYSTEMIC_CASCADE
        2. buffer < 5%  OR market_impact >= 30%            → HIGH_CASCADE
        3. buffer < 10% OR market_impact >= 15%            → CASCADE_RISK
        4. buffer <= 20% OR market_impact >= 5%            → WATCHLIST
        5. buffer > 20% AND market_impact < 5%             → SAFE_MARGINS
        """
        if market_impact_pct > 60.0 or current_ltv_pct > liquidation_threshold_pct:
            return "SYSTEMIC_CASCADE"
        if buffer_to_liquidation_pct < 5.0 or market_impact_pct >= 30.0:
            return "HIGH_CASCADE"
        if buffer_to_liquidation_pct < 10.0 or market_impact_pct >= 15.0:
            return "CASCADE_RISK"
        if buffer_to_liquidation_pct <= 20.0 or market_impact_pct >= 5.0:
            return "WATCHLIST"
        return "SAFE_MARGINS"

    @staticmethod
    def _compute_cascade_risk_score(
        buffer_to_liquidation_pct: float,
        market_impact_pct: float,
        current_ltv_pct: float,
        liquidation_threshold_pct: float,
    ) -> int:
        """
        Cascade risk score in range [0, 100].

        Components:
            buffer_score  0–50:  min(50, max(0, (25 − buffer_pct) / 25 × 50))
                                  buffer ≥ 25 → score = 0; buffer ≤ 0 → score = 50
            impact_score  0–40:  min(40, market_impact_pct / 60 × 40)
            ltv_bonus     0–10:  10 if current_ltv >= liquidation_threshold, else 0

        Final value = sum of components, clamped to [0, 100], rounded half-up.
        """
        buffer_score: float = min(
            50.0, max(0.0, (25.0 - buffer_to_liquidation_pct) / 25.0 * 50.0)
        )
        impact_score: float = min(40.0, market_impact_pct / 60.0 * 40.0)
        ltv_bonus: int = (
            10 if current_ltv_pct >= liquidation_threshold_pct else 0
        )

        total: float = buffer_score + impact_score + ltv_bonus
        return min(100, max(0, int(total + 0.5)))

    # ------------------------------------------------------------------
    # Log persistence helpers
    # ------------------------------------------------------------------

    def _read_log(self) -> List[Dict[str, Any]]:
        """Read existing log file; return empty list on missing/corrupt file."""
        if not os.path.exists(self.log_file):
            return []
        try:
            with open(self.log_file, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, IOError, OSError, ValueError):
            return []

    def _write_log(self, entries: List[Dict[str, Any]]) -> None:
        """Atomically write entries list to log file (tmp + os.replace)."""
        os.makedirs(self.data_dir, exist_ok=True)
        tmp_path: str = self.log_file + ".tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as fh:
                json.dump(entries, fh, indent=2)
            os.replace(tmp_path, self.log_file)
        except OSError:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
            raise
