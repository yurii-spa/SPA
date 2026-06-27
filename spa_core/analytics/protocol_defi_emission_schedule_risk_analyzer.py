"""
MP-1057 | ProtocolDeFiEmissionScheduleRiskAnalyzer
Read-only / advisory analytics. No trades. Pure stdlib.
Log: data/emission_schedule_risk_log.json (ring-buffer 100)

Scores a protocol's token-emission model across three risk axes:
  1. Annualised inflation rate (emissions vs circulating supply)
  2. Revenue coverage ratio  (protocol revenue vs daily emission value)
  3. 30-day vesting unlock shock (largest near-term supply bump)
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional
from spa_core.utils import clock

_LOG_CAP = 100
_DEFAULT_LOG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "emission_schedule_risk_log.json"
)

_LABEL_SUSTAINABLE = "SUSTAINABLE_TOKENOMICS"
_LABEL_MANAGEABLE  = "MANAGEABLE_INFLATION"
_LABEL_ELEVATED    = "ELEVATED_SELL_PRESSURE"
_LABEL_HIGH_RISK   = "HIGH_INFLATION_RISK"
_LABEL_HYPERINFL   = "HYPERINFLATIONARY_COLLAPSE"

# Score thresholds (exclusive upper bound)
_THRESHOLDS = [
    (20,  _LABEL_SUSTAINABLE),
    (40,  _LABEL_MANAGEABLE),
    (60,  _LABEL_ELEVATED),
    (80,  _LABEL_HIGH_RISK),
    (101, _LABEL_HYPERINFL),
]

# Score component weights / caps
_INFLATION_CAP        = 40.0   # up to 50 % annual inflation → max component score
_INFLATION_RATE_MAX   = 50.0   # % above which inflation component saturates
_COVERAGE_CAP         = 30.0   # max score from low revenue coverage
_UNLOCK_CAP           = 30.0   # max score from 30-day unlock shock
_UNLOCK_SHOCK_MAX     = 30.0   # % of circulating supply unlocking → saturates component


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def _atomic_write_json(path: str, data: Any) -> None:
    """Write JSON atomically: write to .tmp then os.replace."""
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp, path)
    finally:
        try:
            os.remove(tmp)
        except FileNotFoundError:
            pass


def _append_ring_log(path: str, entry: dict, cap: int = _LOG_CAP) -> None:
    """Append *entry* to a ring-buffer JSON list capped at *cap* entries."""
    try:
        with open(path, encoding="utf-8") as fh:
            log: List[dict] = json.load(fh)
        if not isinstance(log, list):
            log = []
    except Exception:
        log = []
    log.append(entry)
    if len(log) > cap:
        log = log[-cap:]
    _atomic_write_json(path, log)


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class ProtocolDeFiEmissionScheduleRiskAnalyzer:
    """
    Advisory-only emission schedule risk analyzer.

    Outputs:
        emission_inflation_rate_pct  – annualised emission / circulating supply * 100
        revenue_coverage_ratio       – protocol_revenue / (emissions_per_day * price)
        max_unlock_30d_pct           – tokens unlocking within 30 days / circulating * 100
        emission_risk_score          – composite 0–100 (higher = riskier)
        label                        – categorical risk tier

    No trades, no writes to allocator/risk/execution state.
    """

    def __init__(self, log_path: Optional[str] = None) -> None:
        self._log_path = os.path.normpath(log_path or _DEFAULT_LOG_PATH)

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def analyze(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parameters
        ----------
        data : dict
            token_name                    : str
            current_price_usd             : float
            total_supply                  : float
            circulating_supply            : float
            emissions_per_day             : float
            vesting_unlock_schedule       : list[dict]
                days_from_now             : int
                tokens                    : float
            current_apy_from_emissions_pct: float
            protocol_revenue_usd_per_day  : float

        Returns
        -------
        dict with keys:
            emission_inflation_rate_pct, revenue_coverage_ratio,
            max_unlock_30d_pct, emission_risk_score, label
        """
        token_name         = str(data.get("token_name") or "UNKNOWN")
        price              = float(data.get("current_price_usd") or 0)
        circulating        = float(data.get("circulating_supply") or 0)
        emissions_per_day  = float(data.get("emissions_per_day") or 0)
        unlock_schedule    = list(data.get("vesting_unlock_schedule") or [])
        revenue_per_day    = float(data.get("protocol_revenue_usd_per_day") or 0)

        inflation_pct      = self._inflation_rate(emissions_per_day, circulating)
        coverage_ratio     = self._revenue_coverage(revenue_per_day, emissions_per_day, price)
        max_unlock_30d_pct = self._max_unlock_30d(unlock_schedule, circulating)
        risk_score         = self._emission_risk_score(
            inflation_pct, coverage_ratio, max_unlock_30d_pct
        )
        label = self._label(risk_score)

        result: Dict[str, Any] = {
            "emission_inflation_rate_pct": round(inflation_pct, 6),
            "revenue_coverage_ratio":      round(coverage_ratio, 6),
            "max_unlock_30d_pct":          round(max_unlock_30d_pct, 6),
            "emission_risk_score":         round(risk_score, 4),
            "label":                       label,
        }

        self._log(token_name, result)
        return result

    # ------------------------------------------------------------------ #
    # Metric calculations                                                  #
    # ------------------------------------------------------------------ #

    def _inflation_rate(self, emissions_per_day: float, circulating: float) -> float:
        """Annualised emission inflation rate (%)."""
        if circulating <= 0:
            return 0.0
        return emissions_per_day * 365.0 / circulating * 100.0

    def _revenue_coverage(
        self, revenue_per_day: float, emissions_per_day: float, price: float
    ) -> float:
        """
        Protocol revenue / daily emission market value.
        - emission value == 0 and revenue > 0  → 999 (no dilution, revenue exists)
        - emission value == 0 and revenue == 0 → 0   (no revenue, undefined)
        """
        emission_value = emissions_per_day * price
        if emission_value <= 0:
            return 999.0 if revenue_per_day > 0 else 0.0
        return revenue_per_day / emission_value

    def _max_unlock_30d(
        self, schedule: List[dict], circulating: float
    ) -> float:
        """Tokens unlocking within the next 30 days as % of circulating supply."""
        if circulating <= 0:
            return 0.0
        unlock_tokens = sum(
            float(ev.get("tokens") or 0)
            for ev in schedule
            if 0 <= float(ev.get("days_from_now") or 0) <= 30
        )
        return unlock_tokens / circulating * 100.0

    def _emission_risk_score(
        self,
        inflation_pct: float,
        coverage_ratio: float,
        max_unlock_30d_pct: float,
    ) -> float:
        """
        Composite risk score 0–100 (higher = riskier).

        Component breakdown:
          Inflation  (0–40):  min(40, inflation_pct / 50 * 40)
          Coverage   (0–30):  max(0, 30 * (1 − min(coverage_ratio, 1)))
          Unlock     (0–30):  min(30, max_unlock_30d_pct / 30 * 30)
        """
        # Inflation: saturates at _INFLATION_RATE_MAX %/year
        inflation_score = min(_INFLATION_CAP, inflation_pct / _INFLATION_RATE_MAX * _INFLATION_CAP)

        # Revenue coverage: 0 when fully covered (coverage >= 1), 30 when zero
        cov_clamped    = min(coverage_ratio, 1.0)
        coverage_score = max(0.0, _COVERAGE_CAP * (1.0 - cov_clamped))

        # Unlock shock: saturates at _UNLOCK_SHOCK_MAX %
        unlock_score = min(_UNLOCK_CAP, max_unlock_30d_pct / _UNLOCK_SHOCK_MAX * _UNLOCK_CAP)

        total = inflation_score + coverage_score + unlock_score
        return min(100.0, max(0.0, total))

    def _label(self, score: float) -> str:
        for threshold, lbl in _THRESHOLDS:
            if score < threshold:
                return lbl
        return _LABEL_HYPERINFL  # score == 100

    # ------------------------------------------------------------------ #
    # Logging                                                              #
    # ------------------------------------------------------------------ #

    def _log(self, token_name: str, result: dict) -> None:
        try:
            entry = {
                "ts":         clock.utcnow().isoformat() + "Z",
                "token_name": token_name,
            }
            entry.update(result)
            _append_ring_log(self._log_path, entry)
        except Exception:
            pass  # advisory — never propagate logging failures
