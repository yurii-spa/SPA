"""
MP-782: ImpermanentLossTracker
Computes impermanent loss for LP positions across price scenarios.

Formula:  IL% = 2*sqrt(k) / (1+k) - 1,  k = current_price_ratio / initial_price_ratio
IL% is always <= 0 for any k > 0 (k == 1 gives IL% == 0, no loss).

Pure stdlib.  Atomic write (tmp + os.replace).  Ring-buffer log capped at 100 entries.
"""

import json
import math
import os
import time
from typing import Dict, List, Optional
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_DATA_FILE = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "impermanent_loss_log.json"
)

RING_BUFFER_SIZE = 100

# Severity thresholds (absolute value of IL%)
_SEV_NEGLIGIBLE = 0.005   # < 0.5 %
_SEV_LOW        = 0.02    # < 2 %
_SEV_MEDIUM     = 0.05    # < 5 %
_SEV_HIGH       = 0.10    # < 10 %

SEVERITY_NEGLIGIBLE = "NEGLIGIBLE"
SEVERITY_LOW        = "LOW"
SEVERITY_MEDIUM     = "MEDIUM"
SEVERITY_HIGH       = "HIGH"
SEVERITY_SEVERE     = "SEVERE"


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def _atomic_write_json(path: str, data) -> None:
    """Atomic JSON write via centralized atomic_save (MP-1453)."""
    atomic_save(data, str(path))
def _load_log(path: str) -> List:
    try:
        with open(path, "r") as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []


# ---------------------------------------------------------------------------
# Pure-function helpers (importable for tests)
# ---------------------------------------------------------------------------

def compute_il_pct(initial_price_ratio: float, current_price_ratio: float) -> float:
    """
    Return IL% using the standard constant-product AMM formula.

    IL% = 2*sqrt(k) / (1+k) - 1,   k = current / initial
    Always <= 0 for k > 0; exactly 0 when k == 1.

    Raises ValueError for non-positive ratios.
    """
    if initial_price_ratio <= 0:
        raise ValueError(
            f"initial_price_ratio must be positive, got {initial_price_ratio}"
        )
    k = current_price_ratio / initial_price_ratio
    if k <= 0:
        raise ValueError(
            f"current_price_ratio / initial_price_ratio must be positive, got k={k}"
        )
    return 2.0 * math.sqrt(k) / (1.0 + k) - 1.0


def classify_il_severity(il_abs: float) -> str:
    """Classify absolute-value IL into a severity label."""
    if il_abs < _SEV_NEGLIGIBLE:
        return SEVERITY_NEGLIGIBLE
    if il_abs < _SEV_LOW:
        return SEVERITY_LOW
    if il_abs < _SEV_MEDIUM:
        return SEVERITY_MEDIUM
    if il_abs < _SEV_HIGH:
        return SEVERITY_HIGH
    return SEVERITY_SEVERE


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class ImpermanentLossTracker:
    """
    MP-782: Impermanent Loss Tracker for LP positions.

    Computes IL%, IL in USD, break-even fee APY, and severity label.
    Persists every result to a ring-buffer JSON log (max 100 entries).

    Usage
    -----
    tracker = ImpermanentLossTracker()
    result  = tracker.compute(position)
    results = tracker.compute_scenario(position, [0.5, 0.75, 1.25, 1.5, 2.0])
    fee_apy = tracker.get_break_even_fee(result["il_pct"])
    """

    def __init__(self, data_file: Optional[str] = None) -> None:
        self._data_file: str = os.path.abspath(data_file or _DEFAULT_DATA_FILE)
        self._log: List[Dict] = _load_log(self._data_file)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_result(
        self,
        position: Dict,
        current_price_ratio: float,
    ) -> Dict:
        """Compute IL metrics for one (position, current_price_ratio) pair."""
        token_a            = str(position.get("token_a", "TOKEN_A"))
        token_b            = str(position.get("token_b", "TOKEN_B"))
        initial_pr         = float(position["initial_price_ratio"])
        liquidity_usd      = float(position.get("liquidity_usd", 0.0))

        il_pct             = compute_il_pct(initial_pr, current_price_ratio)
        il_abs             = abs(il_pct)
        il_usd             = liquidity_usd * il_abs
        severity           = classify_il_severity(il_abs)
        k                  = current_price_ratio / initial_pr
        break_even_fee_apy = self.get_break_even_fee(il_pct)

        return {
            "token_a":              token_a,
            "token_b":              token_b,
            "initial_price_ratio":  initial_pr,
            "current_price_ratio":  current_price_ratio,
            "liquidity_usd":        liquidity_usd,
            "price_ratio_k":        k,
            "il_pct":               il_pct,
            "il_usd":               il_usd,
            "break_even_fee_apy":   break_even_fee_apy,
            "il_severity":          severity,
            "timestamp":            time.time(),
        }

    def _append_and_persist(self, entries: List[Dict]) -> None:
        """Append *entries* to the ring-buffer and write atomically."""
        for e in entries:
            self._log.append(e)
        if len(self._log) > RING_BUFFER_SIZE:
            self._log = self._log[-RING_BUFFER_SIZE:]
        _atomic_write_json(self._data_file, self._log)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compute(self, position: Dict) -> Dict:
        """
        Compute IL for a single position and append result to the ring-buffer log.

        Required keys in *position*:
          initial_price_ratio (float)  – price of token_a in token_b at LP entry
          current_price_ratio (float)  – current price of token_a in token_b

        Optional keys:
          token_a (str), token_b (str), liquidity_usd (float)
        """
        current_pr = float(position["current_price_ratio"])
        result = self._build_result(position, current_pr)
        self._append_and_persist([result])
        return result

    def compute_scenario(
        self,
        position: Dict,
        price_scenarios: Optional[List[float]] = None,
    ) -> List[Dict]:
        """
        Compute IL across a set of price ratio multipliers.

        Each value in *price_scenarios* is a multiplier applied to
        initial_price_ratio.  E.g. 2.0 → current = 2 × initial (price doubled).

        Default scenarios: [0.5, 0.75, 1.25, 1.5, 2.0]

        Returns a list of result dicts (one per scenario) and appends
        all of them to the ring-buffer log in one atomic write.
        """
        if price_scenarios is None:
            price_scenarios = [0.5, 0.75, 1.25, 1.5, 2.0]

        initial_pr = float(position["initial_price_ratio"])
        results: List[Dict] = []
        for mult in price_scenarios:
            current_pr = initial_pr * float(mult)
            r = self._build_result(position, current_pr)
            r["scenario_multiplier"] = float(mult)
            results.append(r)

        self._append_and_persist(results)
        return results

    def get_break_even_fee(self, il_pct: float) -> float:
        """
        Fee APY required to break even over a 1-year holding period.

        break_even_fee_apy = |IL%|

        Rationale: if the pool earns this annual fee rate, the fee income
        exactly offsets the impermanent loss accumulated over one year.
        """
        return abs(float(il_pct))

    def get_log(self) -> List[Dict]:
        """Return a shallow copy of the in-memory ring-buffer log."""
        return list(self._log)
