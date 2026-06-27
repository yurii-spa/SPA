"""
MP-1094: DeFiProtocolYieldReserveBufferAnalyzer
Analyzes a DeFi protocol's reserve buffer (safety module) adequacy.
Reserves protect against bad debt events; undersized reserves = systemic risk.

Pure stdlib, read-only analytics, atomic ring-buffer log (cap 100).
"""

import json
import os
from spa_core.utils import clock

# --------------------------------------------------------------------------- #
# Log config
# --------------------------------------------------------------------------- #
_LOG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "yield_reserve_buffer_log.json"
)
_LOG_CAP = 100

# --------------------------------------------------------------------------- #
# Reserve labels
# --------------------------------------------------------------------------- #
LABEL_FORTRESS_RESERVES = "FORTRESS_RESERVES"
LABEL_ADEQUATE_BUFFER = "ADEQUATE_BUFFER"
LABEL_THIN_RESERVES = "THIN_RESERVES"
LABEL_UNDERFUNDED = "UNDERFUNDED"
LABEL_CRITICALLY_UNDERFUNDED = "CRITICALLY_UNDERFUNDED"

# --------------------------------------------------------------------------- #
# Score component weights (sum = 100)
# --------------------------------------------------------------------------- #
_WEIGHT_RESERVE_RATIO = 40   # reserve_ratio_pct up to 10% → 40 pts
_WEIGHT_BAD_DEBT_COV  = 30   # bad_debt_coverage_ratio up to 5x  → 30 pts
_WEIGHT_DAYS_DEPLETE  = 20   # days_to_deplete up to 365          → 20 pts
_WEIGHT_INSURED_TVL   = 10   # insured_tvl_pct up to 100%         → 10 pts

# Caps for each component
_CAP_RESERVE_RATIO_PCT = 10.0   # 10% reserve ratio → full score
_CAP_BAD_DEBT_COV      = 5.0    # 5x coverage → full score
_CAP_DAYS_DEPLETE      = 365.0  # 365 days → full score
_CAP_INSURED_TVL_PCT   = 100.0  # 100% insured → full score


# --------------------------------------------------------------------------- #
# Pure helpers (importable for testing)
# --------------------------------------------------------------------------- #

def compute_reserve_ratio_pct(reserve_usd: float, total_tvl_usd: float) -> float:
    """
    Compute reserve ratio as percent of TVL.
    Returns 0.0 if total_tvl_usd <= 0.
    """
    if total_tvl_usd <= 0:
        return 0.0
    return round(reserve_usd / total_tvl_usd * 100.0, 6)


def compute_bad_debt_coverage_ratio(reserve_usd: float, bad_debt_history_usd: float) -> float:
    """
    Compute bad debt coverage ratio: reserve / max(bad_debt_history, 1).
    A ratio >= 1x means reserves can cover all historical bad debt once.
    """
    denominator = max(bad_debt_history_usd, 1.0)
    return round(reserve_usd / denominator, 6)


def compute_days_to_deplete(reserve_usd: float, daily_yield_usd: float) -> float:
    """
    Days the reserve lasts relative to daily yield inflow.
    Formula: reserve / max(daily_yield, 0.01)
    Capped at 99_999.0 to avoid excessively large values.
    """
    divisor = max(daily_yield_usd, 0.01)
    raw = reserve_usd / divisor
    return round(min(raw, 99_999.0), 4)


def compute_reserve_adequacy_score(
    reserve_ratio_pct: float,
    bad_debt_coverage_ratio: float,
    days_to_deplete: float,
    insured_tvl_pct: float,
) -> int:
    """
    Compute reserve adequacy score (int 0-100) from four components:
    - reserve_ratio_pct  (cap 10%)  → up to 40 points
    - bad_debt_coverage_ratio (cap 5x) → up to 30 points
    - days_to_deplete (cap 365 days)   → up to 20 points
    - insured_tvl_pct (cap 100%)       → up to 10 points
    """
    ratio_score = min(max(reserve_ratio_pct, 0.0), _CAP_RESERVE_RATIO_PCT) \
                  / _CAP_RESERVE_RATIO_PCT * _WEIGHT_RESERVE_RATIO

    cov_score = min(max(bad_debt_coverage_ratio, 0.0), _CAP_BAD_DEBT_COV) \
                / _CAP_BAD_DEBT_COV * _WEIGHT_BAD_DEBT_COV

    days_cap = min(max(days_to_deplete, 0.0), _CAP_DAYS_DEPLETE)
    days_score = days_cap / _CAP_DAYS_DEPLETE * _WEIGHT_DAYS_DEPLETE

    insured_score = min(max(insured_tvl_pct, 0.0), _CAP_INSURED_TVL_PCT) \
                    / _CAP_INSURED_TVL_PCT * _WEIGHT_INSURED_TVL

    total = ratio_score + cov_score + days_score + insured_score
    return int(round(min(max(total, 0.0), 100.0)))


def compute_reserve_label(reserve_ratio_pct: float, bad_debt_coverage_ratio: float) -> str:
    """
    Assign reserve adequacy label based on reserve_ratio_pct and bad_debt_coverage_ratio.

    Rules (evaluated in order):
      >= 10% AND bad_debt_coverage >= 5x  → FORTRESS_RESERVES
      >= 5%  AND bad_debt_coverage >= 2x  → ADEQUATE_BUFFER
      >= 2%                               → THIN_RESERVES
      >= 0.5%                             → UNDERFUNDED
      < 0.5%                              → CRITICALLY_UNDERFUNDED
    """
    if reserve_ratio_pct >= 10.0 and bad_debt_coverage_ratio >= 5.0:
        return LABEL_FORTRESS_RESERVES
    if reserve_ratio_pct >= 5.0 and bad_debt_coverage_ratio >= 2.0:
        return LABEL_ADEQUATE_BUFFER
    if reserve_ratio_pct >= 2.0:
        return LABEL_THIN_RESERVES
    if reserve_ratio_pct >= 0.5:
        return LABEL_UNDERFUNDED
    return LABEL_CRITICALLY_UNDERFUNDED


def _atomic_log_append(entry: dict, log_path: str, cap: int) -> None:
    """Append one entry to ring-buffer JSON log atomically (tmp + os.replace)."""
    log_dir = os.path.dirname(log_path)
    if log_dir and not os.path.exists(log_dir):
        os.makedirs(log_dir, exist_ok=True)

    if os.path.exists(log_path):
        try:
            with open(log_path, "r") as fh:
                records = json.load(fh)
            if not isinstance(records, list):
                records = []
        except (json.JSONDecodeError, OSError):
            records = []
    else:
        records = []

    records.append(entry)
    if len(records) > cap:
        records = records[-cap:]

    tmp = log_path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(records, fh, indent=2)
    os.replace(tmp, log_path)


# --------------------------------------------------------------------------- #
# Main class
# --------------------------------------------------------------------------- #

class DeFiProtocolYieldReserveBufferAnalyzer:
    """
    Analyzes a DeFi protocol's reserve buffer (safety module) adequacy.

    Reserves protect against bad debt events; undersized reserves represent
    systemic risk to the protocol and its depositors.

    Inputs (keyword arguments or via dict):
        protocol_name      (str)   — protocol identifier
        reserve_usd        (float) — current reserve fund size in USD
        total_tvl_usd      (float) — total value locked in USD
        bad_debt_history_usd (float) — historical bad debt in last 12 months (USD)
        daily_yield_usd    (float) — protocol daily revenue flowing to reserves (USD)
        insured_tvl_pct    (float) — % of TVL covered by reserves (0-100)

    Outputs (returned dict keys):
        protocol_name          (str)
        reserve_usd            (float)
        total_tvl_usd          (float)
        bad_debt_history_usd   (float)
        daily_yield_usd        (float)
        insured_tvl_pct        (float)
        reserve_ratio_pct      (float) — reserve / tvl * 100
        bad_debt_coverage_ratio (float) — reserve / max(bad_debt_history, 1)
        days_to_deplete        (float) — reserve / max(daily_yield, 0.01)
        reserve_adequacy_score (int)   — 0-100
        reserve_label          (str)   — FORTRESS_RESERVES / ADEQUATE_BUFFER /
                                         THIN_RESERVES / UNDERFUNDED /
                                         CRITICALLY_UNDERFUNDED
        timestamp              (str)   — ISO-8601 UTC

    Usage::

        analyzer = DeFiProtocolYieldReserveBufferAnalyzer()
        result = analyzer.analyze(
            protocol_name="Aave V3",
            reserve_usd=50_000_000,
            total_tvl_usd=500_000_000,
            bad_debt_history_usd=2_000_000,
            daily_yield_usd=50_000,
            insured_tvl_pct=80.0,
        )
    """

    def __init__(self, log_path: str | None = None, log_cap: int = _LOG_CAP):
        self._log_path = log_path or _LOG_PATH
        self._log_cap = log_cap

    # ---------------------------------------------------------------------- #
    # Public API
    # ---------------------------------------------------------------------- #

    def analyze(
        self,
        protocol_name: str,
        reserve_usd: float,
        total_tvl_usd: float,
        bad_debt_history_usd: float,
        daily_yield_usd: float,
        insured_tvl_pct: float,
    ) -> dict:
        """
        Analyze reserve buffer adequacy for a single protocol.

        Parameters
        ----------
        protocol_name       : str   — protocol identifier
        reserve_usd         : float — current reserve fund (USD)
        total_tvl_usd       : float — total value locked (USD)
        bad_debt_history_usd: float — 12-month bad debt history (USD)
        daily_yield_usd     : float — daily protocol revenue to reserves (USD)
        insured_tvl_pct     : float — % of TVL covered by reserves

        Returns
        -------
        dict with computed metrics + logged to ring-buffer.
        """
        # Coerce inputs
        reserve_usd          = float(reserve_usd)
        total_tvl_usd        = float(total_tvl_usd)
        bad_debt_history_usd = float(bad_debt_history_usd)
        daily_yield_usd      = float(daily_yield_usd)
        insured_tvl_pct      = float(insured_tvl_pct)

        # Core computations
        reserve_ratio_pct       = compute_reserve_ratio_pct(reserve_usd, total_tvl_usd)
        bad_debt_coverage_ratio = compute_bad_debt_coverage_ratio(reserve_usd, bad_debt_history_usd)
        days_to_deplete         = compute_days_to_deplete(reserve_usd, daily_yield_usd)
        reserve_adequacy_score  = compute_reserve_adequacy_score(
            reserve_ratio_pct,
            bad_debt_coverage_ratio,
            days_to_deplete,
            insured_tvl_pct,
        )
        reserve_label = compute_reserve_label(reserve_ratio_pct, bad_debt_coverage_ratio)

        timestamp = clock.utcnow().isoformat() + "Z"

        result = {
            "protocol_name":           protocol_name,
            "reserve_usd":             reserve_usd,
            "total_tvl_usd":           total_tvl_usd,
            "bad_debt_history_usd":    bad_debt_history_usd,
            "daily_yield_usd":         daily_yield_usd,
            "insured_tvl_pct":         insured_tvl_pct,
            "reserve_ratio_pct":       reserve_ratio_pct,
            "bad_debt_coverage_ratio": bad_debt_coverage_ratio,
            "days_to_deplete":         days_to_deplete,
            "reserve_adequacy_score":  reserve_adequacy_score,
            "reserve_label":           reserve_label,
            "timestamp":               timestamp,
        }

        log_entry = {
            "timestamp":               timestamp,
            "protocol_name":           protocol_name,
            "reserve_usd":             reserve_usd,
            "total_tvl_usd":           total_tvl_usd,
            "reserve_ratio_pct":       reserve_ratio_pct,
            "bad_debt_coverage_ratio": bad_debt_coverage_ratio,
            "days_to_deplete":         days_to_deplete,
            "reserve_adequacy_score":  reserve_adequacy_score,
            "reserve_label":           reserve_label,
        }
        _atomic_log_append(log_entry, self._log_path, self._log_cap)

        return result

    def analyze_batch(self, protocols: list) -> list:
        """
        Analyze a list of protocol dicts.
        Each dict must contain all required keys (see class docstring).
        Returns list of result dicts in the same order.
        """
        results = []
        for p in protocols:
            result = self.analyze(
                protocol_name        = str(p.get("protocol_name", "unknown")),
                reserve_usd          = float(p.get("reserve_usd", 0.0)),
                total_tvl_usd        = float(p.get("total_tvl_usd", 0.0)),
                bad_debt_history_usd = float(p.get("bad_debt_history_usd", 0.0)),
                daily_yield_usd      = float(p.get("daily_yield_usd", 0.0)),
                insured_tvl_pct      = float(p.get("insured_tvl_pct", 0.0)),
            )
            results.append(result)
        return results

    def rank_by_adequacy(self, protocols: list) -> list:
        """
        Analyze a list of protocol dicts and return them sorted by
        reserve_adequacy_score descending (best first).
        """
        results = self.analyze_batch(protocols)
        return sorted(results, key=lambda r: r["reserve_adequacy_score"], reverse=True)
