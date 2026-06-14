"""
MP-1088: DeFiProtocolYieldOptimizerFeeDragAnalyzer
Calculates true net yield after all fee layers in yield optimizers/aggregators
(Yearn-style vaults, Beefy, Convex, etc.).

Pure stdlib, read-only analytics, atomic writes, ring-buffer log capped at 100.
"""

from __future__ import annotations

import datetime
import json
import math
import os
import tempfile
from typing import Any

__version__ = "1.0.0"
__mp__ = "MP-1088"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LOG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "yield_optimizer_fee_drag_log.json"
)
LOG_CAP = 100

# Fee label constants
LOW_FEE_VAULT = "LOW_FEE_VAULT"
MODERATE_FEES = "MODERATE_FEES"
HIGH_FEE_DRAG = "HIGH_FEE_DRAG"
FEE_HEAVY = "FEE_HEAVY"
FEE_EXCEEDS_YIELD = "FEE_EXCEEDS_YIELD"

# Sentinel for "never breaks even" (100 years in days)
_NEVER_BREAKEVEN = 36500


# ---------------------------------------------------------------------------
# Atomic I/O helpers
# ---------------------------------------------------------------------------


def _atomic_write(path: str, data: Any) -> None:
    """Write JSON atomically via tmp + os.replace."""
    abs_path = os.path.abspath(path)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(abs_path))
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp, abs_path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _load_log(path: str) -> list:
    try:
        with open(path) as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _append_log(path: str, entry: dict, cap: int) -> None:
    log = _load_log(path)
    log.append(entry)
    if len(log) > cap:
        log = log[-cap:]
    _atomic_write(path, log)


# ---------------------------------------------------------------------------
# Pure computation helpers
# ---------------------------------------------------------------------------


def _compute_fee_drag(
    gross_apy_pct: float,
    management_fee_pct: float,
    performance_fee_pct: float,
    deposit_fee_pct: float,
    withdrawal_fee_pct: float,
    holding_period_days: int,
) -> dict:
    """
    Compute annualised fee-drag components.

    - Performance fee: fraction of gross yield taken as profit share.
    - Management fee: direct annual percentage of AUM.
    - Deposit / withdrawal fees: one-time costs amortised over the holding period
      and expressed as an annualised percentage.

    Returns a dict with individual drag components and total.
    """
    days = max(1, holding_period_days)

    perf_drag = gross_apy_pct * performance_fee_pct / 100.0
    mgmt_drag = management_fee_pct
    deposit_drag = deposit_fee_pct * 365.0 / days
    withdrawal_drag = withdrawal_fee_pct * 365.0 / days

    total = perf_drag + mgmt_drag + deposit_drag + withdrawal_drag

    return {
        "perf_drag": perf_drag,
        "mgmt_drag": mgmt_drag,
        "deposit_drag": deposit_drag,
        "withdrawal_drag": withdrawal_drag,
        "total_fee_drag_pct": total,
    }


def _compute_fee_drag_ratio(total_drag: float, gross_apy_pct: float) -> float:
    """
    fee_drag / gross_apy, clamped to [0.0, 1.0].
    Returns 1.0 when gross_apy is zero and there is drag (fees exceed yield).
    Returns 0.0 when both are zero (no yield and no fees).
    """
    if gross_apy_pct <= 0:
        return 1.0 if total_drag > 0 else 0.0
    ratio = total_drag / gross_apy_pct
    return min(1.0, max(0.0, ratio))


def _compute_fee_label(net_apy_pct: float, fee_drag_ratio: float) -> str:
    """
    Derive fee label.  net_apy <= 0 takes priority.

    Label thresholds (fee_drag_ratio):
      < 0.10            → LOW_FEE_VAULT
      0.10 – 0.25       → MODERATE_FEES
      0.25 – 0.40       → HIGH_FEE_DRAG
      0.40 – 1.0        → FEE_HEAVY
      net_apy_pct <= 0  → FEE_EXCEEDS_YIELD  (highest priority)
    """
    if net_apy_pct <= 0:
        return FEE_EXCEEDS_YIELD
    if fee_drag_ratio < 0.10:
        return LOW_FEE_VAULT
    if fee_drag_ratio < 0.25:
        return MODERATE_FEES
    if fee_drag_ratio < 0.40:
        return HIGH_FEE_DRAG
    return FEE_HEAVY


def _compute_breakeven_days(
    net_apy_pct: float,
    deposit_fee_pct: float,
    withdrawal_fee_pct: float,
) -> int:
    """
    Days needed for cumulative net yield to cover one-time deposit + withdrawal fees.

    Returns 0 when there are no upfront fees.
    Returns _NEVER_BREAKEVEN when net_apy <= 0 (never breaks even).
    """
    upfront = deposit_fee_pct + withdrawal_fee_pct
    if upfront <= 0:
        return 0
    if net_apy_pct <= 0:
        return _NEVER_BREAKEVEN
    net_daily = net_apy_pct / 365.0
    return math.ceil(upfront / net_daily)


def _compute_fee_efficiency_score(fee_drag_ratio: float) -> int:
    """
    Integer score 0-100 where 100 = lowest fees (fee_drag_ratio = 0)
    and 0 = fee_drag_ratio >= 1 (all yield consumed by fees or more).
    Linear mapping: score = round(100 * (1 - clamped_ratio)).
    """
    clamped = min(1.0, max(0.0, fee_drag_ratio))
    return round(100 * (1.0 - clamped))


# ---------------------------------------------------------------------------
# Main analyser class
# ---------------------------------------------------------------------------


class DeFiProtocolYieldOptimizerFeeDragAnalyzer:
    """
    Calculates the true net yield after all fee layers in DeFi yield optimisers /
    aggregators (Yearn-style vaults, Beefy, Convex, etc.).

    Call ``analyze()`` with the vault's fee parameters to get a complete breakdown.
    Results are also appended to a ring-buffer JSON log (capped at 100 entries).
    """

    def __init__(
        self,
        log_path: str | None = None,
        log_cap: int = LOG_CAP,
    ) -> None:
        self._log_path = log_path or LOG_PATH
        self._log_cap = log_cap

    # ------------------------------------------------------------------
    def analyze(
        self,
        gross_apy_pct: float,
        management_fee_pct: float,
        performance_fee_pct: float,
        deposit_fee_pct: float,
        withdrawal_fee_pct: float,
        holding_period_days: int,
        protocol_name: str,
        tvl_usd: float,
    ) -> dict:
        """
        Analyse fee drag for a yield optimiser vault.

        Parameters
        ----------
        gross_apy_pct : float
            Advertised (gross) APY before any fees, e.g. 10.0 for 10 %.
        management_fee_pct : float
            Annual management fee on AUM, e.g. 2.0 for 2 %.
        performance_fee_pct : float
            Percentage of profits taken as performance fee, e.g. 20.0 for 20 %.
        deposit_fee_pct : float
            One-time deposit fee, e.g. 0.1 for 0.1 %.
        withdrawal_fee_pct : float
            One-time withdrawal fee, e.g. 0.5 for 0.5 %.
        holding_period_days : int
            Planned holding duration (used to amortise one-time fees).
        protocol_name : str
            Vault / protocol identifier.
        tvl_usd : float
            Total Value Locked in USD.

        Returns
        -------
        dict
            Keys: net_apy_pct, total_fee_drag_pct, fee_drag_ratio,
                  breakeven_days, fee_efficiency_score, fee_label,
                  fee_breakdown, protocol_name, tvl_usd, gross_apy_pct,
                  holding_period_days, analysis_timestamp, module, version.
        """
        gross = float(gross_apy_pct)
        mgmt = float(management_fee_pct)
        perf = float(performance_fee_pct)
        dep = float(deposit_fee_pct)
        wd = float(withdrawal_fee_pct)
        days = max(1, int(holding_period_days))
        tvl = float(tvl_usd)

        drag = _compute_fee_drag(gross, mgmt, perf, dep, wd, days)
        total_drag = drag["total_fee_drag_pct"]
        net_apy = gross - total_drag

        fee_drag_ratio = _compute_fee_drag_ratio(total_drag, gross)
        fee_label = _compute_fee_label(net_apy, fee_drag_ratio)
        breakeven_days = _compute_breakeven_days(net_apy, dep, wd)
        fee_efficiency_score = _compute_fee_efficiency_score(fee_drag_ratio)

        result: dict = {
            "protocol_name": str(protocol_name),
            "tvl_usd": tvl,
            "gross_apy_pct": round(gross, 6),
            "net_apy_pct": round(net_apy, 6),
            "total_fee_drag_pct": round(total_drag, 6),
            "fee_drag_ratio": round(fee_drag_ratio, 6),
            "breakeven_days": breakeven_days,
            "fee_efficiency_score": fee_efficiency_score,
            "fee_label": fee_label,
            "fee_breakdown": {
                "management_drag_pct": round(drag["mgmt_drag"], 6),
                "performance_drag_pct": round(drag["perf_drag"], 6),
                "deposit_drag_pct": round(drag["deposit_drag"], 6),
                "withdrawal_drag_pct": round(drag["withdrawal_drag"], 6),
            },
            "holding_period_days": days,
            "analysis_timestamp": datetime.datetime.utcnow().isoformat() + "Z",
            "module": __mp__,
            "version": __version__,
        }

        # Append to ring-buffer log (best-effort; never crash analysis)
        log_entry = {
            "ts": result["analysis_timestamp"],
            "protocol_name": str(protocol_name),
            "gross_apy_pct": round(gross, 4),
            "net_apy_pct": round(net_apy, 4),
            "total_fee_drag_pct": round(total_drag, 4),
            "fee_drag_ratio": round(fee_drag_ratio, 4),
            "fee_label": fee_label,
            "fee_efficiency_score": fee_efficiency_score,
        }
        try:
            _append_log(self._log_path, log_entry, self._log_cap)
        except Exception:
            pass

        return result
