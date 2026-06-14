"""
MP-930 DeFiMEVExposureEstimator
---------------------------------
Estimates MEV (Maximal Extractable Value) exposure for DeFi transactions.

For each transaction it computes:
  - sandwich_attack_risk (0-100)
  - frontrun_risk (0-100)
  - mev_cost_estimate_usd  (expected USD extracted by MEV bots)
  - effective_slippage_with_mev_pct
  - protection_recommendation: private_mempool | limit_order | split_trade | rfq | none
  - mev_label: MINIMAL | LOW | MODERATE | HIGH | EXTREME
  - flags: SANDWICH_TARGET | LIQUIDATION_MEV | PRIVATE_POOL_SAFE |
           SPLIT_RECOMMENDED | HIGH_GAS_COMPETITION

Input transaction keys:
  protocol               str
  tx_type                str   swap | liquidation | mint | redeem | arbitrage
  size_usd               float
  slippage_tolerance_pct float
  pool_depth_usd         float
  gas_price_gwei         float
  is_private_mempool     bool
  dex_type               str   amm | orderbook | rfq
  time_sensitivity       str   immediate | flexible | delayed

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
    os.path.dirname(__file__), "..", "..", "data", "mev_exposure_log.json"
)
_LOG_CAP = 100

# DEX base sandwich risk (public mempool susceptibility)
_DEX_SANDWICH_BASE: dict[str, float] = {
    "amm": 55.0,
    "orderbook": 15.0,
    "rfq": 8.0,
}

# DEX base frontrun risk
_DEX_FRONTRUN_BASE: dict[str, float] = {
    "amm": 15.0,
    "orderbook": 10.0,
    "rfq": 5.0,
}

# tx_type adjustments for sandwich risk
_TX_SANDWICH_ADJ: dict[str, float] = {
    "swap": 15.0,
    "liquidation": 10.0,
    "mint": 5.0,
    "redeem": 3.0,
    "arbitrage": 5.0,
}

# tx_type adjustments for frontrun risk
_TX_FRONTRUN_ADJ: dict[str, float] = {
    "swap": 10.0,
    "liquidation": 45.0,
    "mint": 5.0,
    "redeem": 3.0,
    "arbitrage": 30.0,
}

# Time sensitivity frontrun adjustments
_TIME_SENSITIVITY_ADJ: dict[str, float] = {
    "immediate": 35.0,
    "flexible": 15.0,
    "delayed": 3.0,
}

# Slippage bonus per pct point (capped)
_SLIPPAGE_BONUS_PER_PCT = 4.0
_SLIPPAGE_BONUS_CAP = 25.0

# Gas competition thresholds
_GAS_HIGH_GWEI = 100.0
_GAS_MED_GWEI = 50.0
_GAS_HIGH_ADJ = 25.0
_GAS_MED_ADJ = 15.0

# Private mempool risk reduction
_PRIVATE_MEMPOOL_REDUCTION = 55.0

# Split-trade threshold: size > pool_depth * 1%
_SPLIT_THRESHOLD_PCT = 0.01

# Flag thresholds
_HIGH_GAS_THRESHOLD = 100.0
_SANDWICH_TARGET_MIN_SLIPPAGE = 1.0

# MEV extraction rate for swaps (fraction of slippage extracted by sandwich)
_SWAP_MEV_EXTRACTION_RATE = 0.45

# Liquidation bonus fraction
_LIQ_BONUS_RATE = 0.05

# Arbitrage leakage fraction
_ARB_LEAKAGE_RATE = 0.003

# MEV label thresholds (combined_risk = max(sandwich_risk, frontrun_risk))
_LABEL_EXTREME = 80.0
_LABEL_HIGH = 60.0
_LABEL_MODERATE = 40.0
_LABEL_LOW = 20.0

# Recommendation thresholds
_REC_PRIVATE_THRESHOLD = 70.0
_REC_LIMIT_ORDER_THRESHOLD = 60.0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    """Clamp value to [lo, hi]."""
    return max(lo, min(hi, value))


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

class DeFiMEVExposureEstimator:
    """
    Estimates MEV exposure for a batch of DeFi transactions.

    Usage::

        est = DeFiMEVExposureEstimator()
        result = est.estimate(transactions, config)

    config keys (all optional):
        log_path   str   override default log file location
        write_log  bool  default True; set False to skip disk write
    """

    # ------------------------------------------------------------------
    # Per-transaction risk scores
    # ------------------------------------------------------------------

    def _sandwich_risk(self, tx: dict) -> float:
        """Compute sandwich attack risk score 0-100 for a single transaction."""
        dex = str(tx.get("dex_type", "amm")).lower()
        base = _DEX_SANDWICH_BASE.get(dex, 30.0)

        tx_type = str(tx.get("tx_type", "swap")).lower()
        adj = _TX_SANDWICH_ADJ.get(tx_type, 0.0)

        slippage = float(tx.get("slippage_tolerance_pct", 0.5))
        slippage_bonus = min(slippage * _SLIPPAGE_BONUS_PER_PCT, _SLIPPAGE_BONUS_CAP)

        risk = base + adj + slippage_bonus

        if tx.get("is_private_mempool", False):
            risk -= _PRIVATE_MEMPOOL_REDUCTION

        return _clamp(risk)

    def _frontrun_risk(self, tx: dict) -> float:
        """Compute frontrun risk score 0-100 for a single transaction."""
        dex = str(tx.get("dex_type", "amm")).lower()
        base = _DEX_FRONTRUN_BASE.get(dex, 10.0)

        tx_type = str(tx.get("tx_type", "swap")).lower()
        adj = _TX_FRONTRUN_ADJ.get(tx_type, 0.0)

        ts = str(tx.get("time_sensitivity", "flexible")).lower()
        ts_adj = _TIME_SENSITIVITY_ADJ.get(ts, 10.0)

        gas = float(tx.get("gas_price_gwei", 30.0))
        if gas >= _GAS_HIGH_GWEI:
            gas_adj = _GAS_HIGH_ADJ
        elif gas >= _GAS_MED_GWEI:
            gas_adj = _GAS_MED_ADJ
        else:
            gas_adj = 0.0

        risk = base + adj + ts_adj + gas_adj

        if tx.get("is_private_mempool", False):
            risk -= _PRIVATE_MEMPOOL_REDUCTION

        return _clamp(risk)

    def _mev_cost_usd(
        self, tx: dict, sandwich_risk: float, frontrun_risk: float
    ) -> float:
        """Estimate expected USD value extracted by MEV bots for this transaction."""
        size = float(tx.get("size_usd", 0.0))
        if size <= 0.0:
            return 0.0

        tx_type = str(tx.get("tx_type", "swap")).lower()
        slippage = float(tx.get("slippage_tolerance_pct", 0.5))

        if tx_type == "liquidation":
            # Searchers race for liquidation bonuses
            liq_risk_factor = frontrun_risk / 100.0
            return round(size * _LIQ_BONUS_RATE * liq_risk_factor, 6)

        if tx_type in ("swap", "mint", "redeem"):
            sandwich_prob = sandwich_risk / 100.0
            cost = size * (slippage / 100.0) * sandwich_prob * _SWAP_MEV_EXTRACTION_RATE
            return round(max(0.0, cost), 6)

        if tx_type == "arbitrage":
            # Competing bots steal a fraction of the arb profit
            fr_factor = frontrun_risk / 100.0
            return round(size * _ARB_LEAKAGE_RATE * fr_factor, 6)

        return 0.0

    def _effective_slippage(self, tx: dict, mev_cost_usd: float) -> float:
        """Return slippage tolerance + MEV cost expressed as percentage of trade size."""
        size = float(tx.get("size_usd", 0.0))
        base_slip = float(tx.get("slippage_tolerance_pct", 0.5))
        if size <= 0.0:
            return base_slip
        mev_pct = (mev_cost_usd / size) * 100.0
        return round(base_slip + mev_pct, 6)

    def _compute_flags(self, tx: dict) -> list:
        """Return list of applicable flag strings for this transaction."""
        flags: list[str] = []
        tx_type = str(tx.get("tx_type", "swap")).lower()
        dex = str(tx.get("dex_type", "amm")).lower()
        slippage = float(tx.get("slippage_tolerance_pct", 0.5))
        size = float(tx.get("size_usd", 0.0))
        pool_depth = float(tx.get("pool_depth_usd", 1.0))
        gas = float(tx.get("gas_price_gwei", 30.0))

        if tx_type == "swap" and dex == "amm" and slippage >= _SANDWICH_TARGET_MIN_SLIPPAGE:
            flags.append("SANDWICH_TARGET")
        if tx_type == "liquidation":
            flags.append("LIQUIDATION_MEV")
        if tx.get("is_private_mempool", False):
            flags.append("PRIVATE_POOL_SAFE")
        if pool_depth > 0.0 and size > pool_depth * _SPLIT_THRESHOLD_PCT:
            flags.append("SPLIT_RECOMMENDED")
        if gas >= _HIGH_GAS_THRESHOLD:
            flags.append("HIGH_GAS_COMPETITION")

        return flags

    def _mev_label(self, combined_risk: float) -> str:
        """Return MEV label based on combined risk score."""
        if combined_risk >= _LABEL_EXTREME:
            return "EXTREME"
        if combined_risk >= _LABEL_HIGH:
            return "HIGH"
        if combined_risk >= _LABEL_MODERATE:
            return "MODERATE"
        if combined_risk >= _LABEL_LOW:
            return "LOW"
        return "MINIMAL"

    def _protection_recommendation(
        self,
        tx: dict,
        sandwich_risk: float,
        frontrun_risk: float,
        flags: list,
    ) -> str:
        """Return protection recommendation string for this transaction."""
        # Already protected via private mempool
        if tx.get("is_private_mempool", False):
            return "none"

        # Critical risk → private mempool
        if sandwich_risk >= _REC_PRIVATE_THRESHOLD or frontrun_risk >= _REC_PRIVATE_THRESHOLD:
            return "private_mempool"

        # Large trade relative to pool
        if "SPLIT_RECOMMENDED" in flags:
            return "split_trade"

        # High frontrun risk → limit order
        if frontrun_risk >= _REC_LIMIT_ORDER_THRESHOLD:
            return "limit_order"

        # AMM swap/mint → RFQ for better price
        tx_type = str(tx.get("tx_type", "swap")).lower()
        dex = str(tx.get("dex_type", "amm")).lower()
        if tx_type in ("swap", "mint") and dex == "amm":
            return "rfq"

        return "none"

    # ------------------------------------------------------------------
    # Single-transaction analysis
    # ------------------------------------------------------------------

    def _analyze_tx(self, tx: dict) -> dict:
        """Analyse one transaction and return per-tx result dict."""
        sr = self._sandwich_risk(tx)
        fr = self._frontrun_risk(tx)
        mev_cost = self._mev_cost_usd(tx, sr, fr)
        eff_slip = self._effective_slippage(tx, mev_cost)
        flags = self._compute_flags(tx)
        combined = max(sr, fr)
        label = self._mev_label(combined)
        rec = self._protection_recommendation(tx, sr, fr, flags)

        return {
            "protocol": tx.get("protocol", "unknown"),
            "tx_type": tx.get("tx_type", "unknown"),
            "size_usd": float(tx.get("size_usd", 0.0)),
            "sandwich_attack_risk": round(sr, 2),
            "frontrun_risk": round(fr, 2),
            "mev_cost_estimate_usd": round(mev_cost, 4),
            "effective_slippage_with_mev_pct": round(eff_slip, 4),
            "protection_recommendation": rec,
            "mev_label": label,
            "flags": flags,
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def estimate(self, transactions: list, config: dict | None = None) -> dict:
        """
        Estimate MEV exposure for a list of DeFi transactions.

        Parameters
        ----------
        transactions : list[dict]
            Each dict describes one transaction (see module docstring).
        config : dict, optional
            Optional overrides:
                log_path  str   custom log file path
                write_log bool  set False to skip log write (default True)

        Returns
        -------
        dict with keys:
            results     list[dict]  per-transaction analysis
            aggregates  dict        portfolio-level summary
            timestamp   float       unix timestamp
        """
        if config is None:
            config = {}
        if not isinstance(transactions, list):
            raise TypeError("transactions must be a list")

        results = [self._analyze_tx(tx) for tx in transactions]

        # ── Aggregates ──────────────────────────────────────────────
        if results:
            combined_risks = [
                max(r["sandwich_attack_risk"], r["frontrun_risk"]) for r in results
            ]
            avg_risk = sum(combined_risks) / len(combined_risks)
            max_idx = combined_risks.index(max(combined_risks))
            min_idx = combined_risks.index(min(combined_risks))
            highest_mev_risk = results[max_idx]["protocol"]
            safest_transaction = results[min_idx]["protocol"]
            total_mev_usd = sum(r["mev_cost_estimate_usd"] for r in results)
            extreme_count = sum(1 for r in results if r["mev_label"] == "EXTREME")
        else:
            avg_risk = 0.0
            highest_mev_risk = None
            safest_transaction = None
            total_mev_usd = 0.0
            extreme_count = 0

        aggregates = {
            "highest_mev_risk": highest_mev_risk,
            "safest_transaction": safest_transaction,
            "total_estimated_mev_usd": round(total_mev_usd, 4),
            "average_mev_risk": round(avg_risk, 2),
            "extreme_count": extreme_count,
        }

        ts = time.time()
        output: dict[str, Any] = {
            "results": results,
            "aggregates": aggregates,
            "timestamp": ts,
        }

        # ── Ring-buffer log ─────────────────────────────────────────
        write_log = config.get("write_log", True)
        if write_log:
            log_path = config.get("log_path", _LOG_PATH)
            try:
                _atomic_log(
                    log_path,
                    {
                        "timestamp": ts,
                        "tx_count": len(results),
                        "aggregates": aggregates,
                    },
                )
            except Exception:
                pass  # advisory: never block caller

        return output
