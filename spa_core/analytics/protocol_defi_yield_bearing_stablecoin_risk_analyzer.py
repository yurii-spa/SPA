"""
MP-1067: ProtocolDeFiYieldBearingStablecoinRiskAnalyzer
---------------------------------------------------------
Risk assessment for yield-bearing stablecoins (sDAI, sUSDe, USDY, etc.).

For each token it computes four sub-scores and a composite:
  depeg_risk_score           0-100  (higher = more likely to depeg)
  yield_sustainability_score 0-100  (higher = yield more sustainable)
  collateral_adequacy_score  0-100  (higher = better collateral coverage)
  composite_risk_score       0-100  (higher = riskier overall)
  risk_label                 GOLD_STANDARD / SOUND / MODERATE_RISK
                             / HIGH_RISK / AVOID

Input dict keys:
  token_name              str
  peg_asset               str    "USD" / "EUR" / etc.
  current_price_usd       float  current market price in USD
  apy_pct                 float  annualised yield advertised (percent)
  yield_source            str    "treasuries" / "lending" / "staking" / "algo"
  collateral_ratio_pct    float  collateral / token supply × 100
  collateral_asset        str    e.g. "ETH" / "USDC" / "T-Bills"
  collateral_apy_pct      float  yield earned on collateral (percent)
  redemption_delay_days   float  days until user can redeem
  has_circuit_breaker     bool   True = protocol has emergency pause
  protocol_tvl_usd        float  total protocol TVL in USD
  days_since_depeg_event  float  0 = no prior depeg event;
                                 > 0 = days since last depeg event

Read-only / advisory. Pure stdlib. Atomic ring-buffer JSON log (cap 100).
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
_LOG_FILENAME = "yield_bearing_stablecoin_risk_log.json"
_LOG_CAP = 100
_DEFAULT_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data")

# ---- Depeg Risk ----
_DEPEG_BASE = 20.0

_YIELD_SOURCE_DEPEG_PENALTY: dict[str, float] = {
    "algo": 40.0,
    "lending": 20.0,
    "staking": 15.0,
    "treasuries": 5.0,
}

# Peg deviation penalty: per 1 % deviation from $1.00
_PEG_DEV_PENALTY_PER_PCT = 15.0
_PEG_DEV_CAP = 40.0

# Collateral ratio depeg contribution
_COL_RATIO_SEVERE_THRESH = 100.0    # undercollateralised → heavy penalty
_COL_RATIO_WARN_THRESH = 120.0      # thin coverage → moderate penalty
_COL_RATIO_SAFE_THRESH = 150.0      # comfortable → small relief

_COL_RATIO_SEVERE_DEPEG = 30.0
_COL_RATIO_WARN_DEPEG = 15.0
_COL_RATIO_SAFE_RELIEF = 10.0

# Redemption delay → depeg risk
_REDEMPTION_LONG_THRESH = 7.0
_REDEMPTION_VERY_LONG_THRESH = 30.0
_REDEMPTION_WARN_PENALTY = 10.0
_REDEMPTION_SEVERE_PENALTY = 15.0

# TVL → depeg risk
_TVL_SMALL_THRESH = 10_000_000.0     # < $10M → risky
_TVL_SMALL_PENALTY = 15.0

# Circuit breaker relief
_CIRCUIT_BREAKER_DEPEG_RELIEF = 10.0

# Historical depeg events
_DEPEG_RECENT_THRESH = 90.0          # < 90 days → very recent
_DEPEG_MODERATE_THRESH = 365.0       # < 365 days → notable
_DEPEG_RECENT_PENALTY = 30.0
_DEPEG_MODERATE_PENALTY = 15.0
_DEPEG_OLD_PENALTY = 5.0

# ---- Yield Sustainability ----
_YIELD_SOURCE_SUSTAINABILITY_BASE: dict[str, float] = {
    "treasuries": 80.0,
    "lending": 65.0,
    "staking": 55.0,
    "algo": 10.0,
}
_YIELD_SUSTAINABILITY_DEFAULT_BASE = 40.0

# APY penalty tiers
_APY_VERY_HIGH_THRESH = 30.0
_APY_HIGH_THRESH = 20.0
_APY_MOD_THRESH = 15.0
_APY_LOW_THRESH = 10.0
_APY_VERY_HIGH_PENALTY = 30.0
_APY_HIGH_PENALTY = 20.0
_APY_MOD_PENALTY = 10.0
_APY_LOW_PENALTY = 5.0

# Collateral yield vs. token yield
_COL_YIELD_FULL_COVER_BONUS = 15.0  # col_apy >= token_apy
_COL_YIELD_PARTIAL_COVER_BONUS = 5.0  # col_apy >= token_apy * 0.8
_COL_YIELD_DEFICIT_PENALTY = 10.0

# TVL scale bonus
_TVL_LARGE_THRESH = 100_000_000.0
_TVL_LARGE_BONUS = 10.0

# Circuit breaker sustainability bonus
_CIRCUIT_BREAKER_SUSTAIN_BONUS = 5.0

# ---- Collateral Adequacy ----
# Ratio bands → base score
_COL_ADEQUACY_BANDS = [
    (80.0, 0.0),
    (100.0, 20.0),
    (120.0, 40.0),
    (150.0, 60.0),
    (200.0, 80.0),
    (float("inf"), 95.0),
]

# Collateral asset quality modifiers
_COL_ASSET_PREMIUM: frozenset[str] = frozenset(
    {"ETH", "WETH", "BTC", "WBTC", "T-BILLS", "T-BILL", "TBILLS", "TREASURIES"}
)
_COL_ASSET_STABLE: frozenset[str] = frozenset(
    {"USDC", "USDT", "DAI", "FRAX", "BUSD", "TUSD"}
)
_COL_ASSET_ALGO: frozenset[str] = frozenset({"ALGO", "ALGORITHMIC", "NONE"})

_COL_ASSET_PREMIUM_BONUS = 10.0
_COL_ASSET_STABLE_BONUS = 5.0
_COL_ASSET_ALGO_PENALTY = 10.0

# Redemption delay → adequacy penalty
_REDEMPTION_LONG_ADEQUACY_PENALTY = 10.0
_REDEMPTION_VERY_LONG_ADEQUACY_PENALTY = 20.0

# Instant redemption bonus
_REDEMPTION_INSTANT_THRESH = 1.0
_REDEMPTION_INSTANT_BONUS = 5.0

# Circuit breaker adequacy bonus
_CIRCUIT_BREAKER_ADEQUACY_BONUS = 5.0

# ---- Composite ----
# Weighted average of sub-risks (depeg_risk and inverted sub-scores)
_COMPOSITE_DEPEG_WEIGHT = 0.40
_COMPOSITE_COLLATERAL_WEIGHT = 0.35
_COMPOSITE_SUSTAIN_WEIGHT = 0.25

# ---- Label thresholds (composite_risk_score) ----
_LABEL_GOLD = 20.0
_LABEL_SOUND = 40.0
_LABEL_MODERATE = 60.0
_LABEL_HIGH = 80.0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def _atomic_write(path: str, data: Any) -> None:
    """Write *data* as JSON to *path* atomically via tmp + os.replace."""
    abs_path = os.path.abspath(path)
    dir_name = os.path.dirname(abs_path)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)
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


def _load_ring_buffer(path: str, cap: int) -> list:
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

class ProtocolDeFiYieldBearingStablecoinRiskAnalyzer:
    """
    Risk assessment for yield-bearing stablecoins.

    Usage::

        analyzer = ProtocolDeFiYieldBearingStablecoinRiskAnalyzer()
        result   = analyzer.analyze(input_dict)
    """

    LOG_CAP = _LOG_CAP

    def __init__(self, data_dir: str | None = None) -> None:
        self.data_dir = data_dir or _DEFAULT_DATA_DIR

    # ------------------------------------------------------------------
    # Sub-scores
    # ------------------------------------------------------------------

    @staticmethod
    def _depeg_risk_score(inp: dict) -> float:
        """
        Compute depeg risk 0-100 (higher = more likely to depeg).
        """
        score = _DEPEG_BASE

        # 1. Yield source
        ys = str(inp.get("yield_source", "lending")).lower()
        score += _YIELD_SOURCE_DEPEG_PENALTY.get(ys, 20.0)

        # 2. Price deviation from peg
        price = float(inp.get("current_price_usd", 1.0))
        peg = 1.0  # simplified: all USD-pegged expected at 1.00
        deviation_pct = abs(price - peg) * 100.0
        dev_penalty = min(deviation_pct * _PEG_DEV_PENALTY_PER_PCT, _PEG_DEV_CAP)
        score += dev_penalty

        # 3. Collateral ratio
        col_ratio = float(inp.get("collateral_ratio_pct", 100.0))
        if col_ratio < _COL_RATIO_SEVERE_THRESH:
            score += _COL_RATIO_SEVERE_DEPEG
        elif col_ratio < _COL_RATIO_WARN_THRESH:
            score += _COL_RATIO_WARN_DEPEG
        elif col_ratio >= _COL_RATIO_SAFE_THRESH:
            score -= _COL_RATIO_SAFE_RELIEF

        # 4. Redemption delay
        redemption = float(inp.get("redemption_delay_days", 0.0))
        if redemption > _REDEMPTION_VERY_LONG_THRESH:
            score += _REDEMPTION_SEVERE_PENALTY
        elif redemption > _REDEMPTION_LONG_THRESH:
            score += _REDEMPTION_WARN_PENALTY

        # 5. TVL
        tvl = float(inp.get("protocol_tvl_usd", 0.0))
        if tvl < _TVL_SMALL_THRESH:
            score += _TVL_SMALL_PENALTY

        # 6. Circuit breaker
        if inp.get("has_circuit_breaker", False):
            score -= _CIRCUIT_BREAKER_DEPEG_RELIEF

        # 7. Historical depeg events
        days_depeg = float(inp.get("days_since_depeg_event", 0.0))
        if days_depeg > 0.0:
            if days_depeg < _DEPEG_RECENT_THRESH:
                score += _DEPEG_RECENT_PENALTY
            elif days_depeg < _DEPEG_MODERATE_THRESH:
                score += _DEPEG_MODERATE_PENALTY
            else:
                score += _DEPEG_OLD_PENALTY

        return round(_clamp(score), 4)

    @staticmethod
    def _yield_sustainability_score(inp: dict) -> float:
        """
        Compute yield sustainability 0-100 (higher = more sustainable).
        """
        ys = str(inp.get("yield_source", "lending")).lower()
        score = _YIELD_SOURCE_SUSTAINABILITY_BASE.get(
            ys, _YIELD_SUSTAINABILITY_DEFAULT_BASE
        )

        # APY penalty tiers
        apy = float(inp.get("apy_pct", 0.0))
        if apy > _APY_VERY_HIGH_THRESH:
            score -= _APY_VERY_HIGH_PENALTY
        elif apy > _APY_HIGH_THRESH:
            score -= _APY_HIGH_PENALTY
        elif apy > _APY_MOD_THRESH:
            score -= _APY_MOD_PENALTY
        elif apy > _APY_LOW_THRESH:
            score -= _APY_LOW_PENALTY

        # Collateral yield coverage
        col_apy = float(inp.get("collateral_apy_pct", 0.0))
        if col_apy >= apy:
            score += _COL_YIELD_FULL_COVER_BONUS
        elif col_apy >= apy * 0.8:
            score += _COL_YIELD_PARTIAL_COVER_BONUS
        else:
            score -= _COL_YIELD_DEFICIT_PENALTY

        # TVL scale
        tvl = float(inp.get("protocol_tvl_usd", 0.0))
        if tvl >= _TVL_LARGE_THRESH:
            score += _TVL_LARGE_BONUS

        # Circuit breaker
        if inp.get("has_circuit_breaker", False):
            score += _CIRCUIT_BREAKER_SUSTAIN_BONUS

        return round(_clamp(score), 4)

    @staticmethod
    def _collateral_adequacy_score(inp: dict) -> float:
        """
        Compute collateral adequacy 0-100 (higher = better coverage).
        """
        col_ratio = float(inp.get("collateral_ratio_pct", 100.0))

        # Band-based base score
        base = 0.0
        for threshold, band_score in _COL_ADEQUACY_BANDS:
            if col_ratio < threshold:
                base = band_score
                break

        # Collateral asset quality
        asset = str(inp.get("collateral_asset", "")).upper()
        if asset in _COL_ASSET_PREMIUM:
            base += _COL_ASSET_PREMIUM_BONUS
        elif asset in _COL_ASSET_STABLE:
            base += _COL_ASSET_STABLE_BONUS
        elif asset in _COL_ASSET_ALGO:
            base -= _COL_ASSET_ALGO_PENALTY

        # Redemption delay
        redemption = float(inp.get("redemption_delay_days", 0.0))
        if redemption > _REDEMPTION_VERY_LONG_THRESH:
            base -= _REDEMPTION_VERY_LONG_ADEQUACY_PENALTY
        elif redemption > _REDEMPTION_LONG_THRESH:
            base -= _REDEMPTION_LONG_ADEQUACY_PENALTY
        if redemption <= _REDEMPTION_INSTANT_THRESH:
            base += _REDEMPTION_INSTANT_BONUS

        # Circuit breaker
        if inp.get("has_circuit_breaker", False):
            base += _CIRCUIT_BREAKER_ADEQUACY_BONUS

        return round(_clamp(base), 4)

    @staticmethod
    def _composite_risk_score(
        depeg: float, sustainability: float, adequacy: float
    ) -> float:
        """
        Compute composite risk 0-100 (higher = riskier).

        composite = depeg*0.40 + (100-adequacy)*0.35 + (100-sustainability)*0.25
        """
        raw = (
            depeg * _COMPOSITE_DEPEG_WEIGHT
            + (100.0 - adequacy) * _COMPOSITE_COLLATERAL_WEIGHT
            + (100.0 - sustainability) * _COMPOSITE_SUSTAIN_WEIGHT
        )
        return round(_clamp(raw), 4)

    @staticmethod
    def _risk_label(composite: float) -> str:
        """
        Derive label from composite_risk_score.

          <= 20   GOLD_STANDARD
          <= 40   SOUND
          <= 60   MODERATE_RISK
          <= 80   HIGH_RISK
          >  80   AVOID
        """
        if composite <= _LABEL_GOLD:
            return "GOLD_STANDARD"
        if composite <= _LABEL_SOUND:
            return "SOUND"
        if composite <= _LABEL_MODERATE:
            return "MODERATE_RISK"
        if composite <= _LABEL_HIGH:
            return "HIGH_RISK"
        return "AVOID"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self, inp: dict, write_log: bool = True) -> dict:
        """
        Analyze risk for a single yield-bearing stablecoin.

        Parameters
        ----------
        inp : dict
            Input with keys documented in the module docstring.
        write_log : bool
            If True (default), append a log entry to the ring-buffer file.

        Returns
        -------
        dict with all five output metrics plus echoed inputs and metadata.
        """
        depeg = self._depeg_risk_score(inp)
        sustainability = self._yield_sustainability_score(inp)
        adequacy = self._collateral_adequacy_score(inp)
        composite = self._composite_risk_score(depeg, sustainability, adequacy)
        label = self._risk_label(composite)

        result = {
            # --- core outputs ---
            "depeg_risk_score": depeg,
            "yield_sustainability_score": sustainability,
            "collateral_adequacy_score": adequacy,
            "composite_risk_score": composite,
            "risk_label": label,
            # --- echoed inputs ---
            "token_name": str(inp.get("token_name", "")),
            "peg_asset": str(inp.get("peg_asset", "USD")),
            "current_price_usd": float(inp.get("current_price_usd", 1.0)),
            "apy_pct": float(inp.get("apy_pct", 0.0)),
            "yield_source": str(inp.get("yield_source", "")),
            "collateral_ratio_pct": float(inp.get("collateral_ratio_pct", 100.0)),
            "collateral_asset": str(inp.get("collateral_asset", "")),
            "collateral_apy_pct": float(inp.get("collateral_apy_pct", 0.0)),
            "redemption_delay_days": float(inp.get("redemption_delay_days", 0.0)),
            "has_circuit_breaker": bool(inp.get("has_circuit_breaker", False)),
            "protocol_tvl_usd": float(inp.get("protocol_tvl_usd", 0.0)),
            "days_since_depeg_event": float(inp.get("days_since_depeg_event", 0.0)),
            # --- metadata ---
            "module": "ProtocolDeFiYieldBearingStablecoinRiskAnalyzer",
            "mp": "MP-1067",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

        if write_log:
            log_path = os.path.join(self.data_dir, _LOG_FILENAME)
            entry = {
                "timestamp": result["timestamp"],
                "token_name": result["token_name"],
                "depeg_risk_score": depeg,
                "yield_sustainability_score": sustainability,
                "collateral_adequacy_score": adequacy,
                "composite_risk_score": composite,
                "risk_label": label,
            }
            buf = _load_ring_buffer(log_path, self.LOG_CAP)
            buf.append(entry)
            buf = buf[-self.LOG_CAP:]
            _atomic_write(log_path, buf)

        return result

    def analyze_batch(self, inputs: list[dict], write_log: bool = True) -> list[dict]:
        """
        Analyze multiple stablecoins.  One batch-summary log entry is written.
        """
        results = [self.analyze(inp, write_log=False) for inp in inputs]
        if write_log and results:
            log_path = os.path.join(self.data_dir, _LOG_FILENAME)
            entry = {
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "batch_size": len(results),
                "avoid_count": sum(
                    1 for r in results if r["risk_label"] == "AVOID"
                ),
                "gold_standard_count": sum(
                    1 for r in results if r["risk_label"] == "GOLD_STANDARD"
                ),
                "avg_composite_risk": round(
                    sum(r["composite_risk_score"] for r in results) / len(results), 2
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
            "token_name": "sDAI",
            "peg_asset": "USD",
            "current_price_usd": 1.0002,
            "apy_pct": 5.0,
            "yield_source": "lending",
            "collateral_ratio_pct": 102.0,
            "collateral_asset": "DAI",
            "collateral_apy_pct": 5.1,
            "redemption_delay_days": 0.0,
            "has_circuit_breaker": True,
            "protocol_tvl_usd": 2_000_000_000.0,
            "days_since_depeg_event": 0.0,
        },
        {
            "token_name": "sUSDe",
            "peg_asset": "USD",
            "current_price_usd": 1.0001,
            "apy_pct": 27.0,
            "yield_source": "staking",
            "collateral_ratio_pct": 110.0,
            "collateral_asset": "ETH",
            "collateral_apy_pct": 4.5,
            "redemption_delay_days": 7.0,
            "has_circuit_breaker": True,
            "protocol_tvl_usd": 3_500_000_000.0,
            "days_since_depeg_event": 0.0,
        },
        {
            "token_name": "USDY",
            "peg_asset": "USD",
            "current_price_usd": 1.0000,
            "apy_pct": 5.2,
            "yield_source": "treasuries",
            "collateral_ratio_pct": 102.0,
            "collateral_asset": "T-Bills",
            "collateral_apy_pct": 5.3,
            "redemption_delay_days": 2.0,
            "has_circuit_breaker": True,
            "protocol_tvl_usd": 500_000_000.0,
            "days_since_depeg_event": 0.0,
        },
        {
            "token_name": "AlgoStable",
            "peg_asset": "USD",
            "current_price_usd": 0.97,
            "apy_pct": 45.0,
            "yield_source": "algo",
            "collateral_ratio_pct": 75.0,
            "collateral_asset": "ALGO",
            "collateral_apy_pct": 0.0,
            "redemption_delay_days": 14.0,
            "has_circuit_breaker": False,
            "protocol_tvl_usd": 5_000_000.0,
            "days_since_depeg_event": 45.0,
        },
    ]

    analyzer = ProtocolDeFiYieldBearingStablecoinRiskAnalyzer()
    results = analyzer.analyze_batch(_DEMO_INPUTS)
    import json
    print(json.dumps(results, indent=2))
