"""
MP-960: DeFiLiquidityMiningROICalculator
Рассчитывает реальный ROI программ liquidity mining с учётом IL, gas drag,
волатильности reward-токенов и корреляции активов пары.
Только stdlib Python. Атомарные записи (tmp + os.replace).
"""

import json
import math
import os
from typing import Any
from spa_core.utils.atomic import atomic_save
from spa_core.utils import clock


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_LOG_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "data", "liquidity_mining_roi_log.json")
_LOG_CAP = 100

ROI_LABELS = {
    "EXCEPTIONAL": "> 25% final net APY",
    "STRONG": "15–25% final net APY",
    "MODERATE": "5–15% final net APY",
    "MARGINAL": "0–5% final net APY",
    "NEGATIVE": "Negative net APY",
}


def _atomic_write(path: str, data: Any) -> None:
    """Write JSON atomically via tmp + os.replace."""
    abs_path = os.path.abspath(path)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    atomic_save(data, str(abs_path))
def _load_log(path: str) -> list:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return []


# ---------------------------------------------------------------------------
# Core class
# ---------------------------------------------------------------------------
class DeFiLiquidityMiningROICalculator:
    """
    Calculates real ROI of liquidity mining programs accounting for:
    swap fees, mining rewards, impermanent loss, gas costs,
    reward-token volatility, and asset correlation.
    """

    def __init__(self, log_path: str | None = None):
        self._log_path = log_path or _LOG_FILE

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def calculate(self, programs: list[dict], config: dict | None = None) -> dict:
        """
        Args:
            programs: list of program dicts (see module docstring for fields)
            config: optional overrides (log_enabled, log_path, …)

        Returns:
            dict with per-program results and aggregate metrics
        """
        config = config or {}
        results = []
        for prog in programs:
            results.append(self._analyze_program(prog))

        aggregate = self._aggregate(results)
        output = {
            "timestamp": clock.utcnow().isoformat() + "Z",
            "program_count": len(programs),
            "programs": results,
            "aggregate": aggregate,
        }

        if config.get("log_enabled", True):
            self._append_log(output, config.get("log_path", self._log_path))

        return output

    # ------------------------------------------------------------------
    # Per-program analysis
    # ------------------------------------------------------------------
    def _analyze_program(self, p: dict) -> dict:
        protocol = p.get("protocol", "unknown")
        pair = p.get("pair", "unknown")
        base_fee_apy = float(p.get("base_swap_fee_apy_pct", 0.0))
        mining_reward_apy = float(p.get("mining_reward_apy_pct", 0.0))
        reward_token_price = float(p.get("reward_token_price_usd", 1.0))
        reward_token_vol = float(p.get("reward_token_volatility_pct", 0.0))
        il_estimate = float(p.get("il_estimate_pct", 0.0))
        entry_gas = float(p.get("entry_gas_usd", 0.0))
        exit_gas = float(p.get("exit_gas_usd", 0.0))
        claim_gas = float(p.get("claim_gas_usd", 0.0))
        claim_freq = float(p.get("claim_frequency_days", 1.0))
        program_duration = float(p.get("program_duration_days", 365.0))
        days_remaining = float(p.get("days_remaining", program_duration))
        capital = float(p.get("capital_usd", 10000.0))
        corr = float(p.get("price_correlation_coefficient", 0.0))

        # Safety clamps
        claim_freq = max(claim_freq, 0.01)
        capital = max(capital, 0.01)
        days_remaining = max(days_remaining, 0.0)

        # --- Core metrics ---
        gross_mining_apy = base_fee_apy + mining_reward_apy

        # IL adjusted APY
        net_apy_after_il = gross_mining_apy - il_estimate

        # Gas drag
        num_claims = math.ceil(days_remaining / claim_freq) if days_remaining > 0 else 0
        total_gas = entry_gas + exit_gas + num_claims * claim_gas
        years_remaining = days_remaining / 365.0
        if years_remaining > 0:
            gas_drag = (total_gas / capital / years_remaining) * 100.0
        else:
            gas_drag = 0.0

        # Reward token risk-adjusted APY (discount by half the volatility)
        volatility_discount = min(reward_token_vol / 200.0, 1.0)
        reward_token_risk_adjusted_apy = mining_reward_apy * max(0.0, 1.0 - volatility_discount)

        # Final net APY (after all costs)
        final_net_apy = net_apy_after_il - gas_drag

        # Expected PnL
        expected_pnl = capital * (final_net_apy / 100.0) * years_remaining

        # ROI label
        roi_label = self._roi_label(final_net_apy)

        # Flags
        flags = self._compute_flags(
            il_estimate=il_estimate,
            reward_token_vol=reward_token_vol,
            days_remaining=days_remaining,
            gas_drag=gas_drag,
            corr=corr,
        )

        return {
            "protocol": protocol,
            "pair": pair,
            "gross_mining_apy_pct": round(gross_mining_apy, 4),
            "net_apy_after_il_pct": round(net_apy_after_il, 4),
            "gas_drag_pct": round(gas_drag, 4),
            "final_net_apy_pct": round(final_net_apy, 4),
            "reward_token_risk_adjusted_apy": round(reward_token_risk_adjusted_apy, 4),
            "expected_pnl_usd": round(expected_pnl, 4),
            "roi_label": roi_label,
            "flags": flags,
            # meta
            "total_gas_usd": round(total_gas, 4),
            "num_claims": num_claims,
            "days_remaining": days_remaining,
            "capital_usd": capital,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _roi_label(final_net_apy: float) -> str:
        if final_net_apy > 25.0:
            return "EXCEPTIONAL"
        if final_net_apy > 15.0:
            return "STRONG"
        if final_net_apy > 5.0:
            return "MODERATE"
        if final_net_apy >= 0.0:
            return "MARGINAL"
        return "NEGATIVE"

    @staticmethod
    def _compute_flags(
        il_estimate: float,
        reward_token_vol: float,
        days_remaining: float,
        gas_drag: float,
        corr: float,
    ) -> list[str]:
        flags = []
        if il_estimate > 15.0:
            flags.append("HIGH_IL_RISK")
        if reward_token_vol > 80.0:
            flags.append("REWARD_VOLATILE")
        if 0 < days_remaining < 14.0:
            flags.append("PROGRAM_ENDING_SOON")
        if gas_drag > 3.0:
            flags.append("GAS_HEAVY")
        if corr > 0.8:
            flags.append("CORRELATED_PAIR")
        if corr < 0.3:
            flags.append("UNCORRELATED_PAIR")
        return flags

    # ------------------------------------------------------------------
    # Aggregates
    # ------------------------------------------------------------------
    @staticmethod
    def _aggregate(results: list[dict]) -> dict:
        if not results:
            return {
                "best_roi_program": None,
                "worst_roi_program": None,
                "total_expected_pnl_usd": 0.0,
                "average_final_net_apy": 0.0,
                "negative_roi_count": 0,
            }

        sorted_by_apy = sorted(results, key=lambda r: r["final_net_apy_pct"], reverse=True)
        best = sorted_by_apy[0]
        worst = sorted_by_apy[-1]

        total_pnl = sum(r["expected_pnl_usd"] for r in results)
        avg_apy = sum(r["final_net_apy_pct"] for r in results) / len(results)
        neg_count = sum(1 for r in results if r["final_net_apy_pct"] < 0)

        return {
            "best_roi_program": {"protocol": best["protocol"], "pair": best["pair"],
                                 "final_net_apy_pct": best["final_net_apy_pct"]},
            "worst_roi_program": {"protocol": worst["protocol"], "pair": worst["pair"],
                                  "final_net_apy_pct": worst["final_net_apy_pct"]},
            "total_expected_pnl_usd": round(total_pnl, 4),
            "average_final_net_apy": round(avg_apy, 4),
            "negative_roi_count": neg_count,
        }

    # ------------------------------------------------------------------
    # Ring-buffer log
    # ------------------------------------------------------------------
    def _append_log(self, entry: dict, path: str) -> None:
        log = _load_log(path)
        log.append({
            "ts": entry["timestamp"],
            "program_count": entry["program_count"],
            "aggregate": entry["aggregate"],
        })
        if len(log) > _LOG_CAP:
            log = log[-_LOG_CAP:]
        try:
            _atomic_write(path, log)
        except Exception:
            pass  # log failure is non-fatal
