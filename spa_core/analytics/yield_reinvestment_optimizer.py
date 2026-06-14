"""
MP-796: YieldReinvestmentOptimizer
Calculates optimal reinvestment strategy for accumulated yield.
Ring-buffer log capped 100, atomic write. Pure stdlib.
"""

import json
import os
import time
import tempfile
from typing import Optional, Dict

# ── constants ──────────────────────────────────────────────────────────────────

_LOG_FILE = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "yield_reinvestment_log.json"
)
_LOG_FILE = os.path.normpath(_LOG_FILE)
_RING_CAP = 100
_MIN_BLENDED_IMPROVEMENT_PCT = 0.1   # 0.1 % APY improvement required


# ── helpers ────────────────────────────────────────────────────────────────────

def _atomic_write(path: str, data) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".tmp", dir=os.path.dirname(path), delete=False
    ) as fh:
        tmp = fh.name
        json.dump(data, fh, indent=2)
    os.replace(tmp, path)


def _load_log(path: str) -> list:
    try:
        with open(path) as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _blended_apy(allocations: Dict[str, float], apys: Dict[str, float]) -> float:
    """
    Weighted average APY.  allocations values are % weights (sum ~ 100).
    Missing APY entries default to 0.
    """
    total_weight = sum(allocations.values())
    if total_weight <= 0:
        return 0.0
    weighted = sum(
        allocations[p] * apys.get(p, 0.0)
        for p in allocations
    )
    return weighted / total_weight


# ── main class ─────────────────────────────────────────────────────────────────

class YieldReinvestmentOptimizer:
    """
    Computes the optimal reinvestment target for accumulated yield.

    Parameters
    ----------
    log_path : str, optional
        Override path to the ring-buffer log file.
    """

    def __init__(self, log_path: Optional[str] = None):
        self._log_path = log_path or _LOG_FILE
        self._last_result: Optional[dict] = None

    # ── public API ─────────────────────────────────────────────────────────────

    def optimize(self, reinvest_data: dict) -> dict:
        """
        Compute reinvestment optimisation metrics.

        Parameters
        ----------
        reinvest_data : dict
            Keys:
              current_yield_usd          float  ≥ 0
              portfolio_allocations      dict   {protocol: weight_pct}
              protocol_apys              dict   {protocol: apy_pct}
              reinvest_threshold_usd     float  ≥ 0
              gas_cost_per_tx_usd        float  ≥ 0

        Returns
        -------
        dict with all computed fields.
        """
        # ── extract inputs ────────────────────────────────────────────────────
        current_yield = float(reinvest_data.get("current_yield_usd", 0.0))
        allocations: Dict[str, float] = dict(reinvest_data.get("portfolio_allocations", {}))
        apys: Dict[str, float] = dict(reinvest_data.get("protocol_apys", {}))
        threshold = float(reinvest_data.get("reinvest_threshold_usd", 0.0))
        gas_cost = float(reinvest_data.get("gas_cost_per_tx_usd", 0.0))

        # ── net reinvest value ────────────────────────────────────────────────
        net_reinvest_value = current_yield - gas_cost

        # ── blended APY before reinvestment ──────────────────────────────────
        blended_apy_before = _blended_apy(allocations, apys)

        # ── optimal target ────────────────────────────────────────────────────
        optimal_target, blended_apy_after = self._compute_optimal_target(
            current_yield, allocations, apys
        )

        # ── reinvest worthwhile? ──────────────────────────────────────────────
        apy_improvement = blended_apy_after - blended_apy_before
        above_threshold = current_yield >= threshold
        reinvest_worthwhile = (
            above_threshold
            and net_reinvest_value > 0
            and apy_improvement >= _MIN_BLENDED_IMPROVEMENT_PCT
        )

        # ── compounding boost ─────────────────────────────────────────────────
        compounding_boost_annual_pct = self.get_compounding_boost(
            current_yield, allocations, apys, gas_cost, threshold
        )

        # ── assemble ──────────────────────────────────────────────────────────
        result = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            # inputs
            "current_yield_usd": current_yield,
            "reinvest_threshold_usd": threshold,
            "gas_cost_per_tx_usd": gas_cost,
            # computed
            "net_reinvest_value": round(net_reinvest_value, 4),
            "optimal_reinvest_target": optimal_target,
            "blended_apy_before": round(blended_apy_before, 4),
            "blended_apy_after_reinvest": round(blended_apy_after, 4),
            "apy_improvement_pct": round(apy_improvement, 4),
            "reinvest_worthwhile": reinvest_worthwhile,
            "compounding_boost_annual_pct": compounding_boost_annual_pct,
        }

        self._last_result = result
        self._append_log(result)
        return result

    def get_optimal_target(self) -> Optional[str]:
        """Return the optimal_reinvest_target from the most recent optimize() call."""
        if self._last_result is None:
            return None
        return self._last_result.get("optimal_reinvest_target")

    def get_compounding_boost(
        self,
        current_yield_usd: float,
        allocations: Dict[str, float],
        apys: Dict[str, float],
        gas_cost_per_tx_usd: float,
        reinvest_threshold_usd: float,
    ) -> float:
        """
        Estimate additional annual APY from optimal compounding frequency.

        Approach:
          portfolio_size ≈ sum(allocations * apys / 100 * 365) — we derive it
          from average_apy and assume $100k base for normalisation, OR we accept
          it's a relative boost.

          optimal_frequency = how many times per year reinvesting is profitable:
              freq = floor(total_annual_yield / max(current_yield_usd, threshold))
              each reinvest adds blended_apy / 100 compounding gain.

          boost = (1 + blended_apy/100 / freq)^freq - (1 + blended_apy/100) in pct
                = effective annual rate - nominal rate

          If current_yield <= gas_cost or threshold == 0 → boost = 0.
        """
        if current_yield_usd <= 0 or gas_cost_per_tx_usd >= current_yield_usd:
            return 0.0
        if not apys:
            return 0.0

        blended = _blended_apy(allocations, apys)
        if blended <= 0:
            return 0.0

        # How many times a year would we reinvest?
        # Use threshold as the trigger; assume portfolio ~ $100k normalised
        NORMALISED_PORTFOLIO = 100_000.0
        annual_yield_usd = NORMALISED_PORTFOLIO * blended / 100.0
        effective_threshold = max(reinvest_threshold_usd, current_yield_usd, 1.0)
        freq = max(1, int(annual_yield_usd / effective_threshold))
        freq = min(freq, 365)          # cap at daily

        # EAR with compounding vs simple annual
        periodic_rate = blended / 100.0 / freq
        ear = (1.0 + periodic_rate) ** freq - 1.0
        nominal = blended / 100.0
        boost = (ear - nominal) * 100.0
        return round(max(0.0, boost), 4)

    # ── private helpers ────────────────────────────────────────────────────────

    def _compute_optimal_target(
        self,
        current_yield: float,
        allocations: Dict[str, float],
        apys: Dict[str, float],
    ):
        """
        Find the protocol where adding current_yield maximises blended APY.

        Returns (protocol_name, blended_apy_after).
        If allocations is empty or apys is empty → returns (None, 0.0).
        """
        if not allocations or not apys:
            return None, _blended_apy(allocations, apys)

        total_weight = sum(allocations.values())
        if total_weight <= 0:
            # Just pick the highest APY protocol
            best = max(apys, key=lambda p: apys[p])
            return best, apys.get(best, 0.0)

        best_protocol: Optional[str] = None
        best_blended: float = _blended_apy(allocations, apys)

        # Approximate current portfolio size as 100 (weights sum to ~100)
        portfolio_value = total_weight   # treat weights as proportional $ units

        for protocol in apys:
            # Simulate adding current_yield to this protocol
            new_alloc = dict(allocations)
            new_alloc[protocol] = new_alloc.get(protocol, 0.0) + current_yield
            new_total = portfolio_value + current_yield
            # Recompute blended with new_total as denominator
            weighted = sum(
                new_alloc[p] * apys.get(p, 0.0)
                for p in new_alloc
            )
            candidate_blended = weighted / new_total if new_total > 0 else 0.0
            if candidate_blended > best_blended:
                best_blended = candidate_blended
                best_protocol = protocol

        # If no protocol improved (all same or worse), pick highest APY
        if best_protocol is None and apys:
            best_protocol = max(apys, key=lambda p: apys[p])
            # Recompute blended for that choice
            new_alloc = dict(allocations)
            new_alloc[best_protocol] = new_alloc.get(best_protocol, 0.0) + current_yield
            new_total = portfolio_value + current_yield
            weighted = sum(new_alloc[p] * apys.get(p, 0.0) for p in new_alloc)
            best_blended = weighted / new_total if new_total > 0 else 0.0

        return best_protocol, best_blended

    def _append_log(self, entry: dict) -> None:
        log = _load_log(self._log_path)
        log.append(entry)
        if len(log) > _RING_CAP:
            log = log[-_RING_CAP:]
        _atomic_write(self._log_path, log)
