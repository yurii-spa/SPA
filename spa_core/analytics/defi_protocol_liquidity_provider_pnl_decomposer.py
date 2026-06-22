"""
MP-1084: DeFi Protocol Liquidity Provider PnL Decomposer
=========================================================
Read-only / advisory analytics module.
NEVER modifies trades, allocator, risk, or execution domains.
Pure Python stdlib only — no third-party imports.

Class: DeFiProtocolLiquidityProviderPnlDecomposer
Log:   data/lp_pnl_decomposer_log.json  (ring-buffer, cap=100)
"""

import json
import math
import os
import time
from typing import Any, Dict, List, Optional
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_LOG_FILE = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "lp_pnl_decomposer_log.json"
)
LOG_CAP = 100

VALID_POOL_TYPES = frozenset({"constant_product", "stable_swap", "concentrated"})

# Stable-swap IL is ~10 % of constant-product IL (flatter curve)
STABLE_SWAP_IL_MULTIPLIER = 0.10


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class DeFiProtocolLiquidityProviderPnlDecomposer:
    """
    Decomposes P&L for a DeFi LP position into:
      - hodl_value_usd        : value if you held the initial tokens
      - lp_value_usd          : current LP value (before fees)
      - impermanent_loss_usd  : IL in USD  (≤ 0)
      - impermanent_loss_pct  : IL as % of HODL value  (≤ 0)
      - fee_income_pct        : fee income as % of initial capital
      - net_vs_hodl_pct       : net LP+fees vs HODL  (can be +/-)
      - pnl_label             : one of five categorical labels

    Pool-type handling
    ------------------
    constant_product  : standard AMM IL formula  2√r/(1+r) − 1
    stable_swap       : IL ≈ 10 % of constant-product IL
    concentrated      : IL = constant-product IL × concentration_factor
                        (clamped to −100 %)

    Assumptions
    -----------
    - 50/50 initial token split (standard for most AMMs)
    - fee_income_usd is the cumulative fee earned over days_held
    - HODL assumes the same 50/50 token split at entry
    """

    # ------------------------------------------------------------------
    # PnL label thresholds (net_vs_hodl_pct)
    # ------------------------------------------------------------------
    _LABELS: List[tuple] = [
        (5.0,   "LP_CRUSHING_HODL"),
        (0.0,   "LP_BEATING_HODL"),
        (-1.0,  "NEUTRAL"),
        (-10.0, "LP_LAGGING_HODL"),
    ]
    _LABEL_FLOOR = "SEVERE_LP_UNDERPERFORMANCE"

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

    def analyze(self, position: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze one LP position and return the PnL decomposition dict.

        Required *position* keys
        ------------------------
        pool_name             str
        entry_price_a         float > 0
        entry_price_b         float > 0
        current_price_a       float > 0
        current_price_b       float > 0
        initial_position_usd  float > 0
        fee_income_usd        float >= 0
        days_held             float >= 0
        pool_type             str  ∈ {constant_product, stable_swap, concentrated}
        concentration_factor  float >= 1.0  (used only for concentrated pools)
        """
        self._validate(position)

        entry_a  = float(position["entry_price_a"])
        entry_b  = float(position["entry_price_b"])
        cur_a    = float(position["current_price_a"])
        cur_b    = float(position["current_price_b"])
        v0       = float(position["initial_position_usd"])
        fees     = float(position["fee_income_usd"])
        pool_t   = str(position["pool_type"])
        cf       = float(position.get("concentration_factor", 1.0))
        days     = float(position["days_held"])

        # Relative price-change ratios (dimensionless)
        r_a = cur_a / entry_a
        r_b = cur_b / entry_b

        # HODL value: hold original 50/50 token split at entry prices
        hodl_value_usd = v0 / 2.0 * (r_a + r_b)

        # Impermanent-loss factor (≤ 0)
        il_factor = self._il_factor(r_a, r_b, pool_t, cf)

        # LP value before fees
        lp_value_usd = max(0.0, hodl_value_usd * (1.0 + il_factor))

        impermanent_loss_usd = lp_value_usd - hodl_value_usd   # ≤ 0
        impermanent_loss_pct = il_factor * 100.0

        fee_income_pct = (fees / v0 * 100.0) if v0 > 0 else 0.0
        net_lp_value   = lp_value_usd + fees
        net_vs_hodl_pct = (
            (net_lp_value - hodl_value_usd) / hodl_value_usd * 100.0
            if hodl_value_usd > 0 else 0.0
        )

        pnl_label = self._classify(net_vs_hodl_pct)

        result: Dict[str, Any] = {
            "pool_name":            position["pool_name"],
            "pool_type":            pool_t,
            "days_held":            days,
            "hodl_value_usd":       round(hodl_value_usd, 6),
            "lp_value_usd":         round(lp_value_usd, 6),
            "impermanent_loss_usd": round(impermanent_loss_usd, 6),
            "impermanent_loss_pct": round(impermanent_loss_pct, 6),
            "fee_income_usd":       round(fees, 6),
            "fee_income_pct":       round(fee_income_pct, 6),
            "net_lp_value_usd":     round(net_lp_value, 6),
            "net_vs_hodl_pct":      round(net_vs_hodl_pct, 6),
            "pnl_label":            pnl_label,
            "analyzed_at":          time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

        self._append_log(result)
        return result

    # ------------------------------------------------------------------
    # IL calculation
    # ------------------------------------------------------------------

    @staticmethod
    def _il_factor(r_a: float, r_b: float, pool_type: str, cf: float) -> float:
        """
        Compute impermanent-loss factor relative to HODL (always ≤ 0).

        r_a  : current_price_a / entry_price_a
        r_b  : current_price_b / entry_price_b
        """
        if r_b <= 0.0 or r_a <= 0.0:
            return 0.0

        # Relative price ratio of A vs B
        r = r_a / r_b

        # Standard constant-product IL formula
        sqrt_r = math.sqrt(r)
        denom  = 1.0 + r
        if denom == 0.0:
            return 0.0
        il_cp = (2.0 * sqrt_r / denom) - 1.0  # always ≤ 0

        if pool_type == "constant_product":
            return il_cp
        elif pool_type == "stable_swap":
            return il_cp * STABLE_SWAP_IL_MULTIPLIER
        elif pool_type == "concentrated":
            il_conc = il_cp * cf
            return max(-1.0, il_conc)  # bounded: cannot lose > 100 %
        return il_cp

    # ------------------------------------------------------------------
    # Label classification
    # ------------------------------------------------------------------

    @classmethod
    def _classify(cls, net_vs_hodl_pct: float) -> str:
        for threshold, label in cls._LABELS:
            if net_vs_hodl_pct > threshold:
                return label
        return cls._LABEL_FLOOR

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    @staticmethod
    def _validate(p: Dict[str, Any]) -> None:
        required = [
            "pool_name", "entry_price_a", "entry_price_b",
            "current_price_a", "current_price_b",
            "initial_position_usd", "fee_income_usd",
            "days_held", "pool_type",
        ]
        for key in required:
            if key not in p:
                raise ValueError(f"Missing required key: '{key}'")

        for key in ("entry_price_a", "entry_price_b",
                    "current_price_a", "current_price_b"):
            val = float(p[key])
            if val <= 0.0:
                raise ValueError(f"'{key}' must be > 0, got {val}")

        if float(p["initial_position_usd"]) <= 0.0:
            raise ValueError("'initial_position_usd' must be > 0")

        if float(p["fee_income_usd"]) < 0.0:
            raise ValueError("'fee_income_usd' must be >= 0")

        if float(p["days_held"]) < 0.0:
            raise ValueError("'days_held' must be >= 0")

        if p["pool_type"] not in VALID_POOL_TYPES:
            raise ValueError(
                f"'pool_type' must be one of {sorted(VALID_POOL_TYPES)}, "
                f"got '{p['pool_type']}'"
            )

        cf = float(p.get("concentration_factor", 1.0))
        if cf < 1.0:
            raise ValueError(
                f"'concentration_factor' must be >= 1.0, got {cf}"
            )

    # ------------------------------------------------------------------
    # Atomic ring-buffer log
    # ------------------------------------------------------------------

    def _append_log(self, entry: Dict[str, Any]) -> None:
        """Append *entry* to JSON log; cap at self.log_cap. Atomic write."""
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
            log = log[-self.log_cap:]

        atomic_save(log, str(self.log_file))
