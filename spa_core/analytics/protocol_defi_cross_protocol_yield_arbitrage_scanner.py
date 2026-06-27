"""
MP-1109: Protocol DeFi Cross-Protocol Yield Arbitrage Scanner
==============================================================
Scans across multiple protocol/asset combinations to find the best yield
arbitrage opportunity — where to move capital from lower to higher yield,
net of switching costs.

Pure stdlib, no external dependencies.
Atomic writes: tmp + os.replace.
Ring-buffer log capped at 100 entries.
"""

import json
import math
import os
from typing import Any, Dict, List, Optional
from spa_core.utils import clock

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEFAULT_LOG_PATH: str = "data/cross_protocol_yield_arbitrage_log.json"
LOG_CAP: int = 100

VALID_LABELS = frozenset(
    {
        "STAY_PUT",
        "MARGINAL_OPPORTUNITY",
        "GOOD_SWITCH",
        "EXCELLENT_SWITCH",
        "ARBITRAGE_BONANZA",
    }
)

# Label thresholds as fraction of position_size_usd
_MARGINAL_THRESHOLD = 0.005   # net_gain < 0.5% of position
_GOOD_THRESHOLD = 0.02        # net_gain < 2% of position
_EXCELLENT_THRESHOLD = 0.05   # net_gain < 5% of position
# >= 5% of position → ARBITRAGE_BONANZA


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _atomic_write(path: str, data: Any) -> None:
    """Write *data* to *path* atomically via a temp file + os.replace."""
    dir_name = os.path.dirname(path) or "."
    os.makedirs(dir_name, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(data, fh, indent=2)
    os.replace(tmp, path)


def _safe_round(value: float, ndigits: int = 6) -> float:
    """Round a finite float; return the value unchanged if infinite."""
    if math.isfinite(value):
        return round(value, ndigits)
    return value


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------

class ProtocolDeFiCrossProtocolYieldArbitrageScanner:
    """
    Scans multiple protocol/asset pairs to find the best yield arbitrage
    opportunity — highest net gain after accounting for switching costs.

    Key formulas
    ------------
    daily_yield_gain  = position * (cand_apy - current_apy) / 365 / 100
    gross_gain        = position * (cand_apy - current_apy) * holding_days / 365 / 100
    net_gain          = gross_gain - entry_cost_usd - exit_from_current_cost_usd
    payback_days      = (entry_cost + exit_cost) / daily_yield_gain   (inf if gain <= 0)
    risk_adjusted_apy = cand_apy * (100 - risk_score) / 100

    Label (by best_candidate.net_gain_usd vs position_size_usd)
    ------------------------------------------------------------
    STAY_PUT             : best net_gain <= 0
    MARGINAL_OPPORTUNITY : best net_gain in (0, position * 0.5%)
    GOOD_SWITCH          : best net_gain in [position * 0.5%, position * 2%)
    EXCELLENT_SWITCH     : best net_gain in [position * 2%, position * 5%)
    ARBITRAGE_BONANZA    : best net_gain >= position * 5%
    """

    def __init__(
        self,
        log_path: str = DEFAULT_LOG_PATH,
        log_cap: int = LOG_CAP,
    ) -> None:
        self.log_path = log_path
        self.log_cap = log_cap

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def scan(
        self,
        current_protocol: str,
        current_apy_pct: float,
        position_size_usd: float,
        candidates: List[Dict[str, Any]],
        min_apy_improvement_pct: float,
        holding_days: int,
    ) -> Dict[str, Any]:
        """
        Scan *candidates* and return arbitrage analysis.

        Parameters
        ----------
        current_protocol        : name of the protocol currently used
        current_apy_pct         : current yield (%/year)
        position_size_usd       : size of the position in USD
        candidates              : list of dicts with keys:
                                    protocol, apy_pct, entry_cost_usd,
                                    exit_from_current_cost_usd,
                                    risk_score_0_to_100
        min_apy_improvement_pct : minimum APY gain to consider a switch worthwhile
        holding_days            : planned holding period (days)

        Returns
        -------
        dict with all output fields
        """
        # --- Validation ---
        if not isinstance(current_protocol, str):
            raise TypeError("current_protocol must be a str")
        if position_size_usd < 0:
            raise ValueError("position_size_usd must be >= 0")
        if holding_days <= 0:
            raise ValueError("holding_days must be > 0")
        if not isinstance(candidates, list):
            raise TypeError("candidates must be a list")

        # --- Current annual yield ---
        current_annual_yield_usd: float = position_size_usd * current_apy_pct / 100

        # --- Process candidates ---
        ranked: List[Dict[str, Any]] = []
        for cand in candidates:
            processed = self._process_candidate(
                cand=cand,
                current_apy_pct=current_apy_pct,
                position_size_usd=position_size_usd,
                min_apy_improvement_pct=min_apy_improvement_pct,
                holding_days=holding_days,
            )
            ranked.append(processed)

        # Sort by net_gain_usd descending (None/inf-safe via finite check)
        ranked.sort(key=lambda x: x["net_gain_usd"], reverse=True)

        # --- Best candidate ---
        best_candidate: Optional[Dict[str, Any]] = None
        if ranked:
            best = ranked[0]
            best_candidate = {
                "protocol": best["protocol"],
                "net_gain_usd": best["net_gain_usd"],
                "payback_days": best["payback_days"],
                "risk_adjusted_apy_pct": best["risk_adjusted_apy_pct"],
            }

        # --- Opportunity count ---
        opportunity_count: int = sum(1 for c in ranked if c["net_gain_usd"] > 0)

        # --- Label ---
        best_net_gain = best_candidate["net_gain_usd"] if best_candidate else 0.0
        scanner_label: str = self._compute_label(best_net_gain, position_size_usd)

        return {
            "current_protocol": current_protocol,
            "current_apy_pct": current_apy_pct,
            "position_size_usd": position_size_usd,
            "holding_days": holding_days,
            "current_annual_yield_usd": round(current_annual_yield_usd, 6),
            "best_candidate": best_candidate,
            "opportunity_count": opportunity_count,
            "scanner_label": scanner_label,
            "ranked_candidates": ranked,
            "timestamp": clock.utcnow().isoformat() + "Z",
        }

    def scan_and_log(
        self,
        current_protocol: str,
        current_apy_pct: float,
        position_size_usd: float,
        candidates: List[Dict[str, Any]],
        min_apy_improvement_pct: float,
        holding_days: int,
    ) -> Dict[str, Any]:
        """Scan and append result to ring-buffer log (capped at self.log_cap)."""
        result = self.scan(
            current_protocol=current_protocol,
            current_apy_pct=current_apy_pct,
            position_size_usd=position_size_usd,
            candidates=candidates,
            min_apy_improvement_pct=min_apy_improvement_pct,
            holding_days=holding_days,
        )

        log: list = []
        if os.path.exists(self.log_path):
            try:
                with open(self.log_path) as fh:
                    log = json.load(fh)
                if not isinstance(log, list):
                    log = []
            except (json.JSONDecodeError, OSError):
                log = []

        log.append(result)
        if len(log) > self.log_cap:
            log = log[-self.log_cap :]

        _atomic_write(self.log_path, log)
        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _process_candidate(
        self,
        cand: Dict[str, Any],
        current_apy_pct: float,
        position_size_usd: float,
        min_apy_improvement_pct: float,
        holding_days: int,
    ) -> Dict[str, Any]:
        """Compute all derived metrics for a single candidate."""
        protocol = str(cand.get("protocol", ""))
        cand_apy = float(cand.get("apy_pct", 0.0))
        entry_cost = float(cand.get("entry_cost_usd", 0.0))
        exit_cost = float(cand.get("exit_from_current_cost_usd", 0.0))
        risk_score = float(cand.get("risk_score_0_to_100", 0.0))
        total_switch_cost = entry_cost + exit_cost

        # APY improvement over current
        apy_improvement = cand_apy - current_apy_pct

        # Gross gain over holding period
        gross_gain = (
            position_size_usd * apy_improvement * holding_days / 365.0 / 100.0
        )

        # Net gain after switching costs
        net_gain = gross_gain - total_switch_cost

        # Payback days
        daily_yield_gain = position_size_usd * apy_improvement / 365.0 / 100.0
        if daily_yield_gain > 0:
            payback_days_raw: float = total_switch_cost / daily_yield_gain
            payback_days: Optional[float] = round(payback_days_raw, 2)
        else:
            payback_days = None  # infinite / not applicable

        # Risk-adjusted APY: cand_apy * (100 - risk_score) / 100
        risk_adjusted_apy_pct = cand_apy * (100.0 - risk_score) / 100.0

        # Switch recommended?
        switch_recommended = (
            net_gain > 0 and apy_improvement >= min_apy_improvement_pct
        )

        return {
            "protocol": protocol,
            "apy_pct": cand_apy,
            "entry_cost_usd": entry_cost,
            "exit_from_current_cost_usd": exit_cost,
            "risk_score_0_to_100": risk_score,
            "net_gain_usd": _safe_round(net_gain, 6),
            "payback_days": payback_days,
            "risk_adjusted_apy_pct": round(risk_adjusted_apy_pct, 6),
            "switch_recommended": switch_recommended,
        }

    def _compute_label(
        self, best_net_gain: float, position_size_usd: float
    ) -> str:
        """
        Compute scanner label based on best net gain relative to position size.
        """
        if best_net_gain <= 0:
            return "STAY_PUT"
        if position_size_usd <= 0:
            # Tiny or zero position — treat any positive gain as bonanza
            return "ARBITRAGE_BONANZA"
        ratio = best_net_gain / position_size_usd
        if ratio < _MARGINAL_THRESHOLD:
            return "MARGINAL_OPPORTUNITY"
        if ratio < _GOOD_THRESHOLD:
            return "GOOD_SWITCH"
        if ratio < _EXCELLENT_THRESHOLD:
            return "EXCELLENT_SWITCH"
        return "ARBITRAGE_BONANZA"
