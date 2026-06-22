"""
MP-1066: DeFiProtocolSandwichAttackExposureAnalyzer
-----------------------------------------------------
Quantifies the sandwich-attack exposure of a DeFi pool/trade combination.

For each input it computes:
  max_sandwich_profit_usd   — maximum USD profit the attacker can extract
  attack_feasibility_score  — 0-100  (higher = easier to attack)
  user_loss_estimate_pct    — percentage of trade lost to the sandwich
  protection_score          — 0-100  (higher = better protected)
  exposure_label            — MEV_PROTECTED / LOW_EXPOSURE / MODERATE_EXPOSURE
                              / HIGH_EXPOSURE / SANDWICH_TARGET

Input dict keys:
  protocol_name             str
  pool_tvl_usd              float   total value locked in the pool
  trade_size_usd            float   size of the user's trade
  slippage_tolerance_pct    float   user's slippage tolerance (percent)
  mempool_visibility        bool    True = tx is publicly visible in mempool
  has_commit_reveal         bool    True = protocol uses commit-reveal
  uses_private_rpc          bool    True = trade is sent via private/protected RPC
  avg_block_time_seconds    float   chain's average block time in seconds
  mev_bot_activity_score    float   0-100, higher = more active MEV bots
  gas_priority_fee_gwei     float   gas priority fee tip in gwei

Read-only / advisory. Pure stdlib. Atomic ring-buffer JSON log (cap 100).
"""

from __future__ import annotations

import json
import os
import time
from typing import Any
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_LOG_FILENAME = "sandwich_attack_exposure_log.json"
_LOG_CAP = 100
_DEFAULT_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data")

# Scoring weights
_MEMPOOL_FEASIBILITY_BONUS = 40.0
_MEV_BOT_FEASIBILITY_WEIGHT = 0.30     # 0-30 contribution
_COMMIT_REVEAL_REDUCTION = 35.0
_PRIVATE_RPC_REDUCTION = 30.0
_SLIPPAGE_HIGH_BONUS = 5.0             # > 1 %
_SLIPPAGE_VERY_HIGH_BONUS = 5.0        # > 3 %
_GAS_MED_BONUS = 5.0                   # > 50 gwei
_GAS_HIGH_BONUS = 5.0                  # > 100 gwei
_FAST_BLOCK_REDUCTION = 5.0            # < 2 s
_FEASIBILITY_BASE = 30.0

# Protection score weights
_PRIVATE_RPC_PROTECT = 35.0
_COMMIT_REVEAL_PROTECT = 35.0
_NO_MEMPOOL_PROTECT = 20.0
_LOW_MEV_BOT_PROTECT = 10.0            # mev_bot_activity_score < 20

# Sandwich profit extraction efficiency
_SANDWICH_EFFICIENCY = 0.50

# User loss scaling
_USER_LOSS_SCALE = 0.60                # feasibility * slippage * this

# Exposure label thresholds (attack_feasibility_score)
_LABEL_TARGET_THRESHOLD = 75.0
_LABEL_HIGH_THRESHOLD = 50.0
_LABEL_MODERATE_THRESHOLD = 25.0
_PROTECTION_LABEL_THRESHOLD = 75.0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def _atomic_write(path: str, data: Any) -> None:
    """Write *data* as JSON to *path* atomically via a tmp file + os.replace."""
    abs_path = os.path.abspath(path)
    dir_name = os.path.dirname(abs_path)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)
    atomic_save(data, str(abs_path))
def _load_ring_buffer(path: str, cap: int) -> list:
    """Load JSON array from *path* or return []. Always returns at most *cap* items."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, list):
            return data[-cap:]
        return []
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        return []


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class DeFiProtocolSandwichAttackExposureAnalyzer:
    """
    Quantifies sandwich-attack exposure for a DeFi pool/trade combination.

    Usage::

        analyzer = DeFiProtocolSandwichAttackExposureAnalyzer()
        result   = analyzer.analyze(input_dict)

    The result contains all five output metrics plus echoed inputs and metadata.
    A log entry is appended to data/sandwich_attack_exposure_log.json (ring-buffer
    capped at 100 entries, atomic write).
    """

    LOG_CAP = _LOG_CAP

    def __init__(self, data_dir: str | None = None) -> None:
        self.data_dir = data_dir or _DEFAULT_DATA_DIR

    # ------------------------------------------------------------------
    # Scoring sub-components
    # ------------------------------------------------------------------

    @staticmethod
    def _max_sandwich_profit_usd(inp: dict) -> float:
        """
        Estimate the maximum USD profit an attacker can extract via sandwich.

        Simplified AMM model:
          price_impact ≈ trade_size / pool_tvl    (constant-product approximation)
          extractable  = min(slippage_tolerance, 2 * price_impact)   [as fraction]
          profit       = trade_size * extractable * EFFICIENCY
        """
        trade_size = float(inp.get("trade_size_usd", 0.0))
        slippage_frac = float(inp.get("slippage_tolerance_pct", 0.5)) / 100.0
        tvl = float(inp.get("pool_tvl_usd", 1.0))
        if tvl <= 0:
            tvl = 1.0

        price_impact_frac = trade_size / tvl
        # attacker can extract at most 2× the natural price impact
        extractable = min(slippage_frac, price_impact_frac * 2.0)
        profit = max(0.0, trade_size * extractable * _SANDWICH_EFFICIENCY)
        return round(profit, 4)

    @staticmethod
    def _protection_score(inp: dict) -> float:
        """
        Compute protection score 0-100 (higher = better protected).

        Drivers:
          uses_private_rpc        +35
          has_commit_reveal       +35
          NOT mempool_visibility  +20
          mev_bot_activity < 20   +10
        """
        score = 0.0
        if inp.get("uses_private_rpc", False):
            score += _PRIVATE_RPC_PROTECT
        if inp.get("has_commit_reveal", False):
            score += _COMMIT_REVEAL_PROTECT
        if not inp.get("mempool_visibility", True):
            score += _NO_MEMPOOL_PROTECT
        if float(inp.get("mev_bot_activity_score", 50.0)) < 20.0:
            score += _LOW_MEV_BOT_PROTECT
        return round(_clamp(score), 4)

    @staticmethod
    def _attack_feasibility_score(inp: dict) -> float:
        """
        Compute attack feasibility 0-100 (higher = easier to attack).

        Base = 30, then:
          +40  if mempool_visibility
          +mev_bot_activity * 0.30   (0-30)
          +5   if slippage > 1%
          +5   if slippage > 3%
          +5   if gas_priority_fee > 50 gwei
          +5   if gas_priority_fee > 100 gwei
          -35  if has_commit_reveal
          -30  if uses_private_rpc
          -5   if avg_block_time < 2 s   (fast chains are harder to sandwich)
        """
        score = _FEASIBILITY_BASE

        if inp.get("mempool_visibility", False):
            score += _MEMPOOL_FEASIBILITY_BONUS

        mev_bots = float(inp.get("mev_bot_activity_score", 50.0))
        score += mev_bots * _MEV_BOT_FEASIBILITY_WEIGHT

        slippage = float(inp.get("slippage_tolerance_pct", 0.5))
        if slippage > 1.0:
            score += _SLIPPAGE_HIGH_BONUS
        if slippage > 3.0:
            score += _SLIPPAGE_VERY_HIGH_BONUS

        gas = float(inp.get("gas_priority_fee_gwei", 5.0))
        if gas > 50.0:
            score += _GAS_MED_BONUS
        if gas > 100.0:
            score += _GAS_HIGH_BONUS

        if inp.get("has_commit_reveal", False):
            score -= _COMMIT_REVEAL_REDUCTION
        if inp.get("uses_private_rpc", False):
            score -= _PRIVATE_RPC_REDUCTION

        block_time = float(inp.get("avg_block_time_seconds", 12.0))
        if block_time < 2.0:
            score -= _FAST_BLOCK_REDUCTION

        return round(_clamp(score), 4)

    @staticmethod
    def _user_loss_estimate_pct(
        feasibility: float, inp: dict
    ) -> float:
        """
        Estimate the percentage of trade value lost to the sandwich attack.

        user_loss_pct = (feasibility / 100) * slippage_tolerance * USER_LOSS_SCALE
        Clipped to [0, slippage_tolerance].
        """
        slippage = float(inp.get("slippage_tolerance_pct", 0.5))
        raw = (feasibility / 100.0) * slippage * _USER_LOSS_SCALE
        return round(_clamp(raw, 0.0, slippage), 4)

    @staticmethod
    def _exposure_label(feasibility: float, protection: float) -> str:
        """
        Derive the exposure label.

          protection >= 75              → MEV_PROTECTED
          feasibility < 25              → LOW_EXPOSURE
          25 <= feasibility < 50        → MODERATE_EXPOSURE
          50 <= feasibility < 75        → HIGH_EXPOSURE
          feasibility >= 75             → SANDWICH_TARGET
        """
        if protection >= _PROTECTION_LABEL_THRESHOLD:
            return "MEV_PROTECTED"
        if feasibility >= _LABEL_TARGET_THRESHOLD:
            return "SANDWICH_TARGET"
        if feasibility >= _LABEL_HIGH_THRESHOLD:
            return "HIGH_EXPOSURE"
        if feasibility >= _LABEL_MODERATE_THRESHOLD:
            return "MODERATE_EXPOSURE"
        return "LOW_EXPOSURE"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self, inp: dict, write_log: bool = True) -> dict:
        """
        Analyze sandwich-attack exposure for a single pool/trade input.

        Parameters
        ----------
        inp : dict
            Input with keys documented in the module docstring.
        write_log : bool
            If True (default), append a summary entry to the ring-buffer log.

        Returns
        -------
        dict with:
            max_sandwich_profit_usd, attack_feasibility_score,
            user_loss_estimate_pct, protection_score, exposure_label,
            plus echoed inputs and metadata.
        """
        profit = self._max_sandwich_profit_usd(inp)
        feasibility = self._attack_feasibility_score(inp)
        protection = self._protection_score(inp)
        user_loss = self._user_loss_estimate_pct(feasibility, inp)
        label = self._exposure_label(feasibility, protection)

        result = {
            # --- core outputs ---
            "max_sandwich_profit_usd": profit,
            "attack_feasibility_score": feasibility,
            "user_loss_estimate_pct": user_loss,
            "protection_score": protection,
            "exposure_label": label,
            # --- echoed inputs ---
            "protocol_name": str(inp.get("protocol_name", "")),
            "pool_tvl_usd": float(inp.get("pool_tvl_usd", 0.0)),
            "trade_size_usd": float(inp.get("trade_size_usd", 0.0)),
            "slippage_tolerance_pct": float(inp.get("slippage_tolerance_pct", 0.5)),
            "mempool_visibility": bool(inp.get("mempool_visibility", False)),
            "has_commit_reveal": bool(inp.get("has_commit_reveal", False)),
            "uses_private_rpc": bool(inp.get("uses_private_rpc", False)),
            "avg_block_time_seconds": float(inp.get("avg_block_time_seconds", 12.0)),
            "mev_bot_activity_score": float(inp.get("mev_bot_activity_score", 50.0)),
            "gas_priority_fee_gwei": float(inp.get("gas_priority_fee_gwei", 5.0)),
            # --- metadata ---
            "module": "DeFiProtocolSandwichAttackExposureAnalyzer",
            "mp": "MP-1066",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

        if write_log:
            log_path = os.path.join(self.data_dir, _LOG_FILENAME)
            entry = {
                "timestamp": result["timestamp"],
                "protocol_name": result["protocol_name"],
                "trade_size_usd": result["trade_size_usd"],
                "attack_feasibility_score": feasibility,
                "protection_score": protection,
                "max_sandwich_profit_usd": profit,
                "exposure_label": label,
            }
            buf = _load_ring_buffer(log_path, self.LOG_CAP)
            buf.append(entry)
            buf = buf[-self.LOG_CAP:]
            _atomic_write(log_path, buf)

        return result

    def analyze_batch(self, inputs: list[dict], write_log: bool = True) -> list[dict]:
        """
        Analyze multiple pool/trade inputs.  Logging is skipped per-item;
        a single summary entry is appended after all items are processed.
        """
        results = [self.analyze(inp, write_log=False) for inp in inputs]
        if write_log and results:
            log_path = os.path.join(self.data_dir, _LOG_FILENAME)
            entry = {
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "batch_size": len(results),
                "sandwich_targets": sum(
                    1 for r in results if r["exposure_label"] == "SANDWICH_TARGET"
                ),
                "mev_protected": sum(
                    1 for r in results if r["exposure_label"] == "MEV_PROTECTED"
                ),
                "avg_feasibility": round(
                    sum(r["attack_feasibility_score"] for r in results) / len(results), 2
                ),
            }
            buf = _load_ring_buffer(log_path, self.LOG_CAP)
            buf.append(entry)
            buf = buf[-self.LOG_CAP:]
            _atomic_write(log_path, buf)
        return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":

    _DEMO_INPUTS = [
        {
            "protocol_name": "Uniswap V3 USDC/ETH",
            "pool_tvl_usd": 8_000_000,
            "trade_size_usd": 50_000,
            "slippage_tolerance_pct": 1.0,
            "mempool_visibility": True,
            "has_commit_reveal": False,
            "uses_private_rpc": False,
            "avg_block_time_seconds": 12.0,
            "mev_bot_activity_score": 75.0,
            "gas_priority_fee_gwei": 30.0,
        },
        {
            "protocol_name": "Curve 3pool",
            "pool_tvl_usd": 200_000_000,
            "trade_size_usd": 500_000,
            "slippage_tolerance_pct": 0.05,
            "mempool_visibility": False,
            "has_commit_reveal": False,
            "uses_private_rpc": True,
            "avg_block_time_seconds": 12.0,
            "mev_bot_activity_score": 60.0,
            "gas_priority_fee_gwei": 20.0,
        },
        {
            "protocol_name": "Balancer V2 weighted",
            "pool_tvl_usd": 5_000_000,
            "trade_size_usd": 200_000,
            "slippage_tolerance_pct": 2.5,
            "mempool_visibility": True,
            "has_commit_reveal": False,
            "uses_private_rpc": False,
            "avg_block_time_seconds": 2.0,
            "mev_bot_activity_score": 90.0,
            "gas_priority_fee_gwei": 120.0,
        },
        {
            "protocol_name": "CoW Protocol",
            "pool_tvl_usd": 50_000_000,
            "trade_size_usd": 100_000,
            "slippage_tolerance_pct": 0.5,
            "mempool_visibility": False,
            "has_commit_reveal": True,
            "uses_private_rpc": True,
            "avg_block_time_seconds": 12.0,
            "mev_bot_activity_score": 10.0,
            "gas_priority_fee_gwei": 5.0,
        },
    ]

    analyzer = DeFiProtocolSandwichAttackExposureAnalyzer()
    results = analyzer.analyze_batch(_DEMO_INPUTS)
    print(json.dumps(results, indent=2))
