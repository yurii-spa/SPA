"""
MP-1131: Protocol DeFi Position Sizing Optimizer
=================================================
Read-only / advisory analytics module.
NEVER modifies trades, allocator, risk, or execution domains.
Pure Python stdlib only — no third-party imports.

Class: ProtocolDeFiPositionSizingOptimizer
Log:   data/position_sizing_log.json  (ring-buffer, cap=100)

Purpose
-------
Calculates optimal position size for a DeFi yield strategy using the Kelly
Criterion adapted for DeFi (incorporating hack probability as the loss event).
Prevents over-sizing into high-risk protocols.

Kelly Criterion (DeFi-adapted)
------------------------------
    b = strategy_expected_apy_pct / strategy_loss_pct_if_hack
    p = strategy_win_probability          (probability of NOT losing)
    q = 1 - p                             (probability of loss / hack)
    kelly_fraction = (p * b - q) / b

    where b is the net payoff ratio: how much you gain (in units of potential loss)
    if the strategy pays out vs the loss magnitude if hacked.

Inputs
------
total_portfolio_usd         : float — total portfolio value in USD
strategy_expected_apy_pct   : float — expected annual yield (e.g. 8.0 = 8%)
strategy_win_probability    : float — 0–1, probability of NOT losing (e.g. 0.97)
strategy_loss_pct_if_hack   : float — % of position lost in worst case (e.g. 80.0)
max_concentration_pct       : float — hard cap on single position (e.g. 20.0)
current_position_usd        : float — current allocation
num_similar_positions       : int   — diversification context
protocol_name               : str

Outputs
-------
kelly_fraction              : float — raw Kelly (may be negative)
kelly_position_usd          : float — total_portfolio * max(0, kelly_fraction)
capped_kelly_pct            : float — min(kelly*100, max_concentration_pct), floor 0
recommended_position_usd    : float — total_portfolio * capped_kelly_pct / 100
current_vs_recommended_ratio: float — current / recommended (0.0 if both zero)
sizing_label                : str

Label by current_vs_recommended_ratio
--------------------------------------
<= 1.1   → OPTIMAL_SIZE
<= 1.5   → SLIGHTLY_OVERSIZED
<= 2.0   → OVERSIZED
<= 3.0   → SIGNIFICANTLY_OVERSIZED
> 3.0    → DANGEROUSLY_OVERSIZED

Edge cases
----------
If recommended_position_usd == 0 and current_position_usd == 0: ratio = 0.0
If recommended_position_usd == 0 and current_position_usd > 0:  ratio = _INF_SENTINEL
"""

import json
import os
import time
from typing import Any, Dict, List, Optional
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_LOG_FILE = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "position_sizing_log.json"
)
LOG_CAP = 100

# Sentinel for "infinite" ratio (current > 0, recommended = 0)
# JSON-safe large float stored in the output dict
_INF_SENTINEL = 9999.0

_LABEL_OPTIMAL = "OPTIMAL_SIZE"
_LABEL_SLIGHTLY = "SLIGHTLY_OVERSIZED"
_LABEL_OVERSIZED = "OVERSIZED"
_LABEL_SIGNIFICANTLY = "SIGNIFICANTLY_OVERSIZED"
_LABEL_DANGEROUS = "DANGEROUSLY_OVERSIZED"


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class ProtocolDeFiPositionSizingOptimizer:
    """
    Computes Kelly Criterion optimal position size for DeFi strategies.

    Advisory/read-only — never modifies allocator, risk, or execution domains.
    Pure stdlib. Atomic ring-buffer log capped at 100 entries.
    """

    def __init__(
        self,
        log_file: str = DEFAULT_LOG_FILE,
        log_cap: int = LOG_CAP,
    ) -> None:
        self.log_file = os.path.abspath(log_file)
        self.log_cap = log_cap

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(
        self,
        total_portfolio_usd: float,
        strategy_expected_apy_pct: float,
        strategy_win_probability: float,
        strategy_loss_pct_if_hack: float,
        max_concentration_pct: float,
        current_position_usd: float,
        num_similar_positions: int,
        protocol_name: str,
    ) -> Dict[str, Any]:
        """
        Compute Kelly-criterion position sizing and return result dict.
        Appends to ring-buffer log atomically.
        """
        self._validate(
            total_portfolio_usd=total_portfolio_usd,
            strategy_expected_apy_pct=strategy_expected_apy_pct,
            strategy_win_probability=strategy_win_probability,
            strategy_loss_pct_if_hack=strategy_loss_pct_if_hack,
            max_concentration_pct=max_concentration_pct,
            current_position_usd=current_position_usd,
            num_similar_positions=num_similar_positions,
            protocol_name=protocol_name,
        )

        # --- Kelly Criterion ---
        p: float = float(strategy_win_probability)
        q: float = 1.0 - p

        # b = apy / loss  (dimensionless ratio of gain to loss magnitude)
        b: float = float(strategy_expected_apy_pct) / float(strategy_loss_pct_if_hack)

        # kelly_fraction = (p * b - q) / b
        # Guard b=0 (zero APY): no payoff edge → kelly = -q (fully negative)
        if b == 0.0:
            kelly_fraction = -q
        else:
            kelly_fraction = (p * b - q) / b

        # kelly_position_usd: full Kelly (floored at 0 — never short)
        kelly_position_usd: float = (
            float(total_portfolio_usd) * max(0.0, kelly_fraction)
        )

        # capped_kelly_pct: clamp raw Kelly to [0, max_concentration_pct]
        raw_kelly_pct: float = kelly_fraction * 100.0
        capped_kelly_pct: float = min(max(raw_kelly_pct, 0.0), float(max_concentration_pct))

        # recommended_position_usd
        recommended_position_usd: float = (
            float(total_portfolio_usd) * capped_kelly_pct / 100.0
        )

        # current_vs_recommended_ratio
        current_vs_recommended_ratio: float = self._compute_ratio(
            current_position_usd=float(current_position_usd),
            recommended_position_usd=recommended_position_usd,
        )

        # sizing_label
        sizing_label: str = self._classify(current_vs_recommended_ratio)

        result: Dict[str, Any] = {
            "protocol_name": protocol_name,
            "kelly_fraction": round(kelly_fraction, 6),
            "kelly_position_usd": round(kelly_position_usd, 6),
            "capped_kelly_pct": round(capped_kelly_pct, 6),
            "recommended_position_usd": round(recommended_position_usd, 6),
            "current_vs_recommended_ratio": round(current_vs_recommended_ratio, 6),
            "sizing_label": sizing_label,
            "num_similar_positions": int(num_similar_positions),
            "analyzed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

        self._append_log(result)
        return result

    # ------------------------------------------------------------------
    # Ratio computation
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_ratio(
        current_position_usd: float,
        recommended_position_usd: float,
    ) -> float:
        """
        Compute current / recommended.
        If recommended == 0 and current > 0: return _INF_SENTINEL (dangerously oversized).
        If both == 0: return 0.0 (nothing allocated, nothing recommended).
        """
        if recommended_position_usd > 0.0:
            return current_position_usd / recommended_position_usd
        if current_position_usd > 0.0:
            return _INF_SENTINEL  # Any allocation when Kelly says 0 is dangerous
        return 0.0  # Nothing in, nothing recommended

    # ------------------------------------------------------------------
    # Label classification
    # ------------------------------------------------------------------

    @staticmethod
    def _classify(ratio: float) -> str:
        """Map current/recommended ratio to a sizing label."""
        if ratio <= 1.1:
            return _LABEL_OPTIMAL
        if ratio <= 1.5:
            return _LABEL_SLIGHTLY
        if ratio <= 2.0:
            return _LABEL_OVERSIZED
        if ratio <= 3.0:
            return _LABEL_SIGNIFICANTLY
        return _LABEL_DANGEROUS

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    @staticmethod
    def _validate(
        total_portfolio_usd: float,
        strategy_expected_apy_pct: float,
        strategy_win_probability: float,
        strategy_loss_pct_if_hack: float,
        max_concentration_pct: float,
        current_position_usd: float,
        num_similar_positions: int,
        protocol_name: str,
    ) -> None:
        if not isinstance(protocol_name, str) or not protocol_name.strip():
            raise ValueError("protocol_name must be a non-empty string")

        if float(total_portfolio_usd) <= 0.0:
            raise ValueError("total_portfolio_usd must be > 0")

        if float(strategy_expected_apy_pct) < 0.0:
            raise ValueError("strategy_expected_apy_pct must be >= 0")

        wp = float(strategy_win_probability)
        if not (0.0 <= wp <= 1.0):
            raise ValueError(
                f"strategy_win_probability must be 0–1, got {strategy_win_probability}"
            )

        if float(strategy_loss_pct_if_hack) <= 0.0:
            raise ValueError("strategy_loss_pct_if_hack must be > 0")

        mc = float(max_concentration_pct)
        if not (0.0 < mc <= 100.0):
            raise ValueError(
                f"max_concentration_pct must be (0, 100], got {max_concentration_pct}"
            )

        if float(current_position_usd) < 0.0:
            raise ValueError("current_position_usd must be >= 0")

        if int(num_similar_positions) < 0:
            raise ValueError("num_similar_positions must be >= 0")

    # ------------------------------------------------------------------
    # Atomic ring-buffer log
    # ------------------------------------------------------------------

    def _append_log(self, entry: Dict[str, Any]) -> None:
        """Append entry to JSON log; trim to log_cap. Atomic write via tmp+replace."""
        log_dir = os.path.dirname(self.log_file)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)

        try:
            with open(self.log_file, "r") as fh:
                log: List[Dict[str, Any]] = json.load(fh)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            log = []

        log.append(entry)
        if len(log) > self.log_cap:
            log = log[-self.log_cap :]

        atomic_save(log, str(self.log_file))
    # ------------------------------------------------------------------
    # Convenience: load log
    # ------------------------------------------------------------------

    def load_log(self) -> List[Dict[str, Any]]:
        """Return the current log contents (empty list if missing or corrupt)."""
        try:
            with open(self.log_file, "r") as fh:
                return json.load(fh)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return []


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _demo() -> None:
    optimizer = ProtocolDeFiPositionSizingOptimizer()

    scenarios = [
        {
            "desc": "Conservative stablecoin strategy (near-optimal sizing)",
            "kwargs": dict(
                total_portfolio_usd=100_000.0,
                strategy_expected_apy_pct=5.0,
                strategy_win_probability=0.99,
                strategy_loss_pct_if_hack=80.0,
                max_concentration_pct=20.0,
                current_position_usd=18_000.0,
                num_similar_positions=3,
                protocol_name="Aave V3 USDC",
            ),
        },
        {
            "desc": "Leveraged strategy (oversized)",
            "kwargs": dict(
                total_portfolio_usd=100_000.0,
                strategy_expected_apy_pct=25.0,
                strategy_win_probability=0.90,
                strategy_loss_pct_if_hack=100.0,
                max_concentration_pct=15.0,
                current_position_usd=40_000.0,
                num_similar_positions=1,
                protocol_name="Delta Neutral sUSDe",
            ),
        },
    ]

    for s in scenarios:
        result = optimizer.analyze(**s["kwargs"])
        print(f"\n=== {s['desc']} ===")
        for k, v in result.items():
            print(f"  {k}: {v}")


if __name__ == "__main__":
    _demo()
