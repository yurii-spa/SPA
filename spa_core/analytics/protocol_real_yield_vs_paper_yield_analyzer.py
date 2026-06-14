"""
MP-931 ProtocolRealYieldVsPaperYieldAnalyzer
---------------------------------------------
Separates genuine (fee-based) yield from "paper" yield driven by token
emissions and inflationary token-price effects.

For each protocol it computes:
  real_apy_pct          fee_revenue_apy - inflation cost
  paper_yield_pct       emission_apy × price-change factor
  true_total_apy_pct    real_apy + paper_yield
  yield_quality_ratio   real_apy / true_total  (0–1)
  token_dilution_cost   inflation_rate_pct (dilution of holder stake)

Yield labels:
  GENUINE_YIELD  |  MOSTLY_REAL  |  MIXED  |  MOSTLY_EMISSIONS  |  ILLUSORY

Flags:
  NEGATIVE_REAL_YIELD   real_apy < 0
  TOKEN_COLLAPSE        token_price_change_30d < -40 %
  EMISSION_DOMINANT     emissions > 80 % of gross APY
  GENUINE_REVENUE       fee_revenue_apy > 5 %
  MISLEADING_APY        |advertised − true_total| > 50 % of advertised

Input protocol keys:
  name                      str
  advertised_apy_pct        float
  fee_revenue_apy_pct       float
  token_emission_apy_pct    float
  token_price_change_30d_pct float
  inflation_rate_pct        float
  tvl_usd                   float
  protocol_revenue_monthly_usd float

Advisory / read-only. Pure stdlib. Atomic ring-buffer JSON log (cap 100).
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_LOG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "real_vs_paper_yield_log.json"
)
_LOG_CAP = 100

# Yield quality ratio thresholds → labels
_GENUINE_THRESHOLD = 0.8
_MOSTLY_REAL_THRESHOLD = 0.6
_MIXED_THRESHOLD = 0.4
_MOSTLY_EMISSIONS_THRESHOLD = 0.2

# Flags
_NEGATIVE_REAL_YIELD_THRESHOLD = 0.0
_TOKEN_COLLAPSE_THRESHOLD = -40.0          # pct 30d price change
_EMISSION_DOMINANT_RATIO = 0.8             # emissions / gross APY
_GENUINE_REVENUE_THRESHOLD = 5.0           # fee_revenue_apy_pct
_MISLEADING_APY_RATIO = 0.5               # |advertised - true| / advertised


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _clamp_ratio(value: float) -> float:
    """Clamp to [0, 1]."""
    return max(0.0, min(1.0, value))


def _atomic_log(log_path: str, entry: dict) -> None:
    """Append entry to ring-buffer JSON array (cap=_LOG_CAP), atomic write."""
    abs_path = os.path.abspath(log_path)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)

    try:
        with open(abs_path, "r", encoding="utf-8") as fh:
            data: list = json.load(fh)
        if not isinstance(data, list):
            data = []
    except (FileNotFoundError, json.JSONDecodeError):
        data = []

    data.append(entry)
    if len(data) > _LOG_CAP:
        data = data[-_LOG_CAP:]

    dir_name = os.path.dirname(abs_path)
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp_path, abs_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class ProtocolRealYieldVsPaperYieldAnalyzer:
    """
    Decomposes advertised DeFi APY into genuine (fee-based) and paper
    (emission-inflation) components.

    Usage::

        analyzer = ProtocolRealYieldVsPaperYieldAnalyzer()
        result = analyzer.analyze(protocols, config)

    config keys (all optional):
        log_path   str   override default log file location
        write_log  bool  default True; set False to skip disk write
    """

    # ------------------------------------------------------------------
    # Per-protocol calculations
    # ------------------------------------------------------------------

    def _real_apy(self, p: dict) -> float:
        """
        Real APY = fee_revenue_apy - inflation_rate.

        Inflation dilutes the holder's relative stake in the protocol,
        making it a cost even when holding token rewards.
        """
        fee_apy = float(p.get("fee_revenue_apy_pct", 0.0))
        inflation = float(p.get("inflation_rate_pct", 0.0))
        return round(fee_apy - inflation, 6)

    def _paper_yield(self, p: dict) -> float:
        """
        Paper yield = emission_apy × price_change_factor.

        If the emitted token price has fallen, the nominal emission APY
        is worth less in real terms.  We clamp the factor at 0 so a
        collapsed token does not produce negative paper yield (the loss
        is captured in real_apy via inflation / price effects).
        """
        emission_apy = float(p.get("token_emission_apy_pct", 0.0))
        price_change = float(p.get("token_price_change_30d_pct", 0.0))
        # Annualise the 30-day price factor (rough approximation)
        monthly_factor = 1.0 + price_change / 100.0
        # Clamp so that a full token collapse does not make paper yield negative
        price_factor = max(0.0, monthly_factor)
        return round(emission_apy * price_factor, 6)

    def _true_total_apy(self, real_apy: float, paper_yield: float) -> float:
        return round(real_apy + paper_yield, 6)

    def _yield_quality_ratio(self, real_apy: float, true_total: float) -> float:
        """
        Fraction of total yield that is genuinely real (fee-based).
        Returns 0 if total yield is non-positive.
        """
        if true_total <= 0.0:
            return 0.0
        ratio = max(0.0, real_apy) / true_total
        return round(_clamp_ratio(ratio), 6)

    def _token_dilution_cost(self, p: dict) -> float:
        """Annualised inflation rate represents the dilution cost to holders."""
        return float(p.get("inflation_rate_pct", 0.0))

    def _yield_label(self, quality_ratio: float) -> str:
        """Map yield quality ratio to a human-readable label."""
        if quality_ratio >= _GENUINE_THRESHOLD:
            return "GENUINE_YIELD"
        if quality_ratio >= _MOSTLY_REAL_THRESHOLD:
            return "MOSTLY_REAL"
        if quality_ratio >= _MIXED_THRESHOLD:
            return "MIXED"
        if quality_ratio >= _MOSTLY_EMISSIONS_THRESHOLD:
            return "MOSTLY_EMISSIONS"
        return "ILLUSORY"

    def _compute_flags(
        self,
        p: dict,
        real_apy: float,
        true_total: float,
    ) -> list:
        """Return list of applicable flag strings."""
        flags: list[str] = []

        fee_apy = float(p.get("fee_revenue_apy_pct", 0.0))
        emission_apy = float(p.get("token_emission_apy_pct", 0.0))
        price_change = float(p.get("token_price_change_30d_pct", 0.0))
        advertised = float(p.get("advertised_apy_pct", 0.0))

        if real_apy < _NEGATIVE_REAL_YIELD_THRESHOLD:
            flags.append("NEGATIVE_REAL_YIELD")

        if price_change < _TOKEN_COLLAPSE_THRESHOLD:
            flags.append("TOKEN_COLLAPSE")

        gross_apy = fee_apy + emission_apy
        if gross_apy > 0.0 and emission_apy / gross_apy > _EMISSION_DOMINANT_RATIO:
            flags.append("EMISSION_DOMINANT")

        if fee_apy > _GENUINE_REVENUE_THRESHOLD:
            flags.append("GENUINE_REVENUE")

        if advertised > 0.0:
            deviation = abs(advertised - true_total)
            if deviation > advertised * _MISLEADING_APY_RATIO:
                flags.append("MISLEADING_APY")

        return flags

    # ------------------------------------------------------------------
    # Single-protocol analysis
    # ------------------------------------------------------------------

    def _analyze_protocol(self, p: dict) -> dict:
        """Analyse one protocol and return result dict."""
        real_apy = self._real_apy(p)
        paper_yield = self._paper_yield(p)
        true_total = self._true_total_apy(real_apy, paper_yield)
        quality_ratio = self._yield_quality_ratio(real_apy, true_total)
        dilution_cost = self._token_dilution_cost(p)
        label = self._yield_label(quality_ratio)
        flags = self._compute_flags(p, real_apy, true_total)

        return {
            "name": p.get("name", "unknown"),
            "advertised_apy_pct": float(p.get("advertised_apy_pct", 0.0)),
            "real_apy_pct": real_apy,
            "paper_yield_pct": paper_yield,
            "true_total_apy_pct": true_total,
            "yield_quality_ratio": quality_ratio,
            "token_dilution_cost_pct": dilution_cost,
            "yield_label": label,
            "flags": flags,
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self, protocols: list, config: dict | None = None) -> dict:
        """
        Analyse a list of DeFi protocols for real vs paper yield.

        Parameters
        ----------
        protocols : list[dict]
            Each dict describes one protocol (see module docstring).
        config : dict, optional
            Optional overrides:
                log_path  str   custom log file path
                write_log bool  set False to skip log write (default True)

        Returns
        -------
        dict with keys:
            results     list[dict]  per-protocol analysis
            aggregates  dict        portfolio-level summary
            timestamp   float       unix timestamp
        """
        if config is None:
            config = {}
        if not isinstance(protocols, list):
            raise TypeError("protocols must be a list")

        results = [self._analyze_protocol(p) for p in protocols]

        # ── Aggregates ───────────────────────────────────────────────
        if results:
            real_apys = [r["real_apy_pct"] for r in results]
            quality_ratios = [r["yield_quality_ratio"] for r in results]
            true_apys = [r["true_total_apy_pct"] for r in results]

            best_idx = real_apys.index(max(real_apys))
            worst_idx = real_apys.index(min(real_apys))
            best_real_yield = results[best_idx]["name"]
            worst_real_yield = results[worst_idx]["name"]
            avg_quality = sum(quality_ratios) / len(quality_ratios)
            avg_true_apy = sum(true_apys) / len(true_apys)
            genuine_yield_count = sum(
                1 for r in results if r["yield_label"] == "GENUINE_YIELD"
            )
        else:
            best_real_yield = None
            worst_real_yield = None
            avg_quality = 0.0
            avg_true_apy = 0.0
            genuine_yield_count = 0

        aggregates = {
            "best_real_yield": best_real_yield,
            "worst_real_yield": worst_real_yield,
            "average_yield_quality_ratio": round(avg_quality, 6),
            "average_true_apy": round(avg_true_apy, 6),
            "genuine_yield_count": genuine_yield_count,
        }

        ts = time.time()
        output: dict[str, Any] = {
            "results": results,
            "aggregates": aggregates,
            "timestamp": ts,
        }

        # ── Ring-buffer log ──────────────────────────────────────────
        write_log = config.get("write_log", True)
        if write_log:
            log_path = config.get("log_path", _LOG_PATH)
            try:
                _atomic_log(
                    log_path,
                    {
                        "timestamp": ts,
                        "protocol_count": len(results),
                        "aggregates": aggregates,
                    },
                )
            except Exception:
                pass  # advisory: never block caller

        return output
