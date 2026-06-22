"""
MP-1115 — ProtocolDeFiSmartMoneyFlowAnalyzer
=============================================
Detects smart money (whale) TVL flow patterns. Large sudden outflows from
whales often precede protocol issues; large inflows signal opportunity.
Analyzes TVL change vs address-count change to distinguish whale vs retail flow.

Pure Python stdlib only. Atomic JSON log writes (tmp + os.replace).
Log file: data/smart_money_flow_log.json (ring-buffer, cap 100).
"""

from __future__ import annotations

import json
import os
import time
import uuid

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
LOG_PATH_DEFAULT = "data/smart_money_flow_log.json"
LOG_CAP = 100

# flow_signal thresholds (tvl_change_24h_pct)
_FLOW_SIGNAL_THRESHOLDS = [
    (10.0, "STRONG_INFLOW"),
    (2.0, "MODERATE_INFLOW"),
    (-2.0, "NEUTRAL"),
    (-10.0, "MODERATE_OUTFLOW"),
    (float("-inf"), "WHALE_EXIT"),
]

# whale_concentration_score cap for top10_wallets_share
_WHALE_SCORE_CAP = 100


# ---------------------------------------------------------------------------
# Public analyzer
# ---------------------------------------------------------------------------
class ProtocolDeFiSmartMoneyFlowAnalyzer:
    """
    Detect smart money (whale) TVL flow patterns.

    Parameters
    ----------
    log_path : str
        Path to the JSON ring-buffer log file.
    """

    def __init__(self, log_path: str = LOG_PATH_DEFAULT) -> None:
        self.log_path = log_path

    # ------------------------------------------------------------------
    # Primary API
    # ------------------------------------------------------------------
    def analyze(
        self,
        tvl_now_usd: float,
        tvl_24h_ago_usd: float,
        tvl_7d_ago_usd: float,
        unique_depositors_now: int,
        unique_depositors_7d_ago: int,
        top10_wallets_share_pct: float,
        largest_single_deposit_24h_usd: float,
        largest_single_withdrawal_24h_usd: float,
        protocol_name: str = "",
        *,
        write_log: bool = True,
    ) -> dict:
        """
        Analyze TVL flow and whale activity for a protocol.

        Returns a dict with all required output fields.
        """
        tvl_now_usd = float(tvl_now_usd)
        tvl_24h_ago_usd = float(tvl_24h_ago_usd)
        tvl_7d_ago_usd = float(tvl_7d_ago_usd)
        unique_depositors_now = int(unique_depositors_now)
        unique_depositors_7d_ago = int(unique_depositors_7d_ago)
        top10_wallets_share_pct = float(top10_wallets_share_pct)
        largest_single_deposit_24h_usd = float(largest_single_deposit_24h_usd)
        largest_single_withdrawal_24h_usd = float(
            largest_single_withdrawal_24h_usd
        )

        tvl_change_24h_pct = self._pct_change(tvl_now_usd, tvl_24h_ago_usd)
        tvl_change_7d_pct = self._pct_change(tvl_now_usd, tvl_7d_ago_usd)
        depositor_growth_7d_pct = self._pct_change(
            unique_depositors_now, unique_depositors_7d_ago
        )
        avg_position_size_usd = self._avg_position(
            tvl_now_usd, unique_depositors_now
        )
        whale_concentration_score = self._whale_concentration_score(
            top10_wallets_share_pct,
            largest_single_deposit_24h_usd,
            largest_single_withdrawal_24h_usd,
            tvl_now_usd,
        )
        flow_signal = self._flow_signal(tvl_change_24h_pct)
        smart_money_label = self._smart_money_label(
            tvl_change_7d_pct, depositor_growth_7d_pct
        )

        result = {
            "module": "MP-1115",
            "protocol_name": protocol_name,
            "tvl_change_24h_pct": round(tvl_change_24h_pct, 6),
            "tvl_change_7d_pct": round(tvl_change_7d_pct, 6),
            "depositor_growth_7d_pct": round(depositor_growth_7d_pct, 6),
            "avg_position_size_usd": round(avg_position_size_usd, 4),
            "whale_concentration_score": whale_concentration_score,
            "flow_signal": flow_signal,
            "smart_money_label": smart_money_label,
            "timestamp": time.time(),
        }

        if write_log:
            self._append_log(result)

        return result

    # ------------------------------------------------------------------
    # Calculations
    # ------------------------------------------------------------------
    @staticmethod
    def _pct_change(now: float, before: float) -> float:
        """Percentage change from *before* to *now*."""
        if before == 0:
            return 0.0
        return (now - before) / abs(before) * 100.0

    @staticmethod
    def _avg_position(tvl: float, depositors: int) -> float:
        if depositors <= 0:
            return tvl if tvl > 0 else 0.0
        return tvl / depositors

    @staticmethod
    def _whale_concentration_score(
        top10_share: float,
        largest_deposit: float,
        largest_withdrawal: float,
        tvl: float,
    ) -> int:
        """
        0–100 composite whale concentration.
        Weights: top10_share (60%), largest_24h_move_as_pct_tvl (40%).
        """
        # component 1: top-10 wallet share (already 0–100 pct → use directly)
        c1 = min(100.0, max(0.0, top10_share))

        # component 2: largest single move in 24 h as fraction of TVL
        if tvl > 0:
            largest_move = max(largest_deposit, largest_withdrawal)
            move_pct = min(100.0, largest_move / tvl * 100.0)
        else:
            move_pct = 0.0

        score = 0.60 * c1 + 0.40 * move_pct
        return int(min(100, max(0, round(score))))

    @staticmethod
    def _flow_signal(tvl_change_24h_pct: float) -> str:
        """Classify 24 h TVL flow."""
        if tvl_change_24h_pct >= 10.0:
            return "STRONG_INFLOW"
        if tvl_change_24h_pct >= 2.0:
            return "MODERATE_INFLOW"
        if tvl_change_24h_pct >= -2.0:
            return "NEUTRAL"
        if tvl_change_24h_pct >= -10.0:
            return "MODERATE_OUTFLOW"
        return "WHALE_EXIT"

    @staticmethod
    def _smart_money_label(
        tvl_change_7d_pct: float, depositor_growth_7d_pct: float
    ) -> str:
        """
        Classify 7-day smart money behavior.

        Rules (in priority order):
        1. tvl < -15% OR (tvl < -5% AND depositors falling) → PANIC_EXIT
        2. tvl -5% to -15% AND depositors growing            → DISTRIBUTION
        3. |tvl_change_7d| < 5%                              → STABLE
        4. tvl +5% OR depositors +10%                        → GROWING
        5. tvl +10% AND depositors +5%                       → ACCUMULATION
        """
        tvl = tvl_change_7d_pct
        dep = depositor_growth_7d_pct

        # Rule 1 — PANIC_EXIT (highest priority)
        if tvl < -15.0 or (tvl < -5.0 and dep <= 0):
            return "PANIC_EXIT"

        # Rule 2 — DISTRIBUTION (whales leaving, retail entering)
        if -15.0 <= tvl < -5.0 and dep > 0:
            return "DISTRIBUTION"

        # Rule 3 — ACCUMULATION: both TVL ≥ 10% AND depositors ≥ 5%
        if tvl >= 10.0 and dep >= 5.0:
            return "ACCUMULATION"

        # Rule 4 — GROWING: TVL ≥ 5% OR depositors ≥ 10%
        # (checked before STABLE so strong depositor growth isn't silenced by small TVL)
        if tvl >= 5.0 or dep >= 10.0:
            return "GROWING"

        # Rule 5 — STABLE: |tvl| < 5% and no qualifying depositor signal
        return "STABLE"

    # ------------------------------------------------------------------
    # Ring-buffer log (cap 100, atomic)
    # ------------------------------------------------------------------
    def _append_log(self, entry: dict) -> None:
        entry_with_id = {**entry, "log_id": str(uuid.uuid4())}
        try:
            os.makedirs(os.path.dirname(self.log_path) or ".", exist_ok=True)
            try:
                with open(self.log_path, "r", encoding="utf-8") as f:
                    records = json.load(f)
                if not isinstance(records, list):
                    records = []
            except (FileNotFoundError, json.JSONDecodeError):
                records = []

            records.append(entry_with_id)
            records = records[-LOG_CAP:]  # ring-buffer

            tmp_path = self.log_path + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(records, f, indent=2)
            os.replace(tmp_path, self.log_path)
        except Exception:
            pass  # never raise from logging


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------
def analyze_smart_money_flow(
    tvl_now_usd: float,
    tvl_24h_ago_usd: float,
    tvl_7d_ago_usd: float,
    unique_depositors_now: int,
    unique_depositors_7d_ago: int,
    top10_wallets_share_pct: float,
    largest_single_deposit_24h_usd: float,
    largest_single_withdrawal_24h_usd: float,
    protocol_name: str = "",
    log_path: str = LOG_PATH_DEFAULT,
    write_log: bool = False,
) -> dict:
    """Module-level convenience wrapper."""
    return ProtocolDeFiSmartMoneyFlowAnalyzer(log_path=log_path).analyze(
        tvl_now_usd=tvl_now_usd,
        tvl_24h_ago_usd=tvl_24h_ago_usd,
        tvl_7d_ago_usd=tvl_7d_ago_usd,
        unique_depositors_now=unique_depositors_now,
        unique_depositors_7d_ago=unique_depositors_7d_ago,
        top10_wallets_share_pct=top10_wallets_share_pct,
        largest_single_deposit_24h_usd=largest_single_deposit_24h_usd,
        largest_single_withdrawal_24h_usd=largest_single_withdrawal_24h_usd,
        protocol_name=protocol_name,
        write_log=write_log,
    )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    analyzer = ProtocolDeFiSmartMoneyFlowAnalyzer()
    result = analyzer.analyze(
        tvl_now_usd=100_000_000,
        tvl_24h_ago_usd=95_000_000,
        tvl_7d_ago_usd=90_000_000,
        unique_depositors_now=1200,
        unique_depositors_7d_ago=1000,
        top10_wallets_share_pct=35.0,
        largest_single_deposit_24h_usd=2_000_000,
        largest_single_withdrawal_24h_usd=500_000,
        protocol_name="Aave V3",
        write_log=False,
    )
    import json
    print(json.dumps(result, indent=2))
