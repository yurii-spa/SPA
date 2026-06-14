"""
spa_core.analysis.market_regime
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Market Regime Detector for SPA DeFi yield optimizer.

Classifies the current DeFi market into one of four regimes:
  STABLE           — normal environment (T1 avg APY 3–8%, std_dev <3%)
  HIGH_YIELD       — risk-on / excess liquidity (T1 avg APY >8%)
  COMPRESSED_YIELD — intense competition for liquidity (T1 avg APY <3%)
  VOLATILE         — spread between adapters is wide (APY std_dev >3%)

Priority: VOLATILE > HIGH_YIELD > COMPRESSED_YIELD > STABLE

Usage:
    detector = MarketRegimeDetector()
    result   = detector.detect({"aave-v3": 4.2, "compound-v3": 4.8, ...})

CLI:
    python3 -m spa_core.analysis.market_regime

stdlib-only; no external dependencies.
Atomic cache: data/market_regime.json (mkstemp + os.replace).
"""
from __future__ import annotations

import json
import math
import os
import statistics
import tempfile
from datetime import datetime, timezone
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# T1 adapter ID set (canonical, normalized).
# Covers both snake_case (legacy) and kebab-case (adapter_status.json keys).
# ---------------------------------------------------------------------------
_T1_IDS: frozenset[str] = frozenset({
    # Aave V3 (Ethereum)
    "aave_v3", "aave-v3",
    # Compound V3 / Comet
    "compound_v3", "compound-v3",
    # Aave V3 Arbitrum
    "aave_arbitrum", "aave_v3_arbitrum", "aave-v3-arbitrum",
    # Morpho (both Steakhouse and Blue listed as T1 in task spec)
    "morpho_blue", "morpho-blue",
    "morpho_steakhouse", "morpho-steakhouse",
    # Spark / sUSDS
    "spark_susds", "spark-susds",
    # Aave V3 Base
    "aave_v3_base", "aave-v3-base",
})


class MarketRegimeDetector:
    """
    Classifies the DeFi market regime from a snapshot of adapter APYs.

    All methods are pure / read-only except ``save_to_cache``.
    No LLM calls; no external imports. Thread-safe for reads.
    """

    # Thresholds
    HIGH_YIELD_THRESHOLD_PCT: float = 8.0
    LOW_YIELD_THRESHOLD_PCT: float = 3.0
    VOLATILITY_THRESHOLD_PCT: float = 3.0

    # Regime constants (used as string literals throughout the project)
    REGIME_STABLE: str = "STABLE"
    REGIME_HIGH_YIELD: str = "HIGH_YIELD"
    REGIME_COMPRESSED: str = "COMPRESSED_YIELD"
    REGIME_VOLATILE: str = "VOLATILE"

    def __init__(self, data_dir: Optional[str] = None) -> None:
        """
        Parameters
        ----------
        data_dir:
            Path to the project's ``data/`` directory.
            If None, resolved automatically relative to this file:
            spa_core/analysis/market_regime.py → ../../data/
        """
        if data_dir is None:
            _this = os.path.dirname(os.path.abspath(__file__))   # spa_core/analysis
            _spa  = os.path.dirname(_this)                        # spa_core
            _root = os.path.dirname(_spa)                         # project root
            self._data_dir: str = os.path.join(_root, "data")
        else:
            self._data_dir = os.path.abspath(data_dir)

        self._last_result: Optional[dict] = None

    # ------------------------------------------------------------------
    # Core public API
    # ------------------------------------------------------------------

    def detect(self, apy_map: Dict[str, float]) -> dict:
        """
        Classify market regime from a mapping of adapter → APY.

        Parameters
        ----------
        apy_map:
            ``{adapter_id: apy_float, ...}``
            Values are APY in percent (e.g. ``4.2`` means 4.2 %).
            Non-finite or None values are silently skipped.

        Returns
        -------
        dict with keys:
            regime          — "STABLE" | "HIGH_YIELD" | "COMPRESSED_YIELD" | "VOLATILE"
            t1_avg_apy      — float, mean APY across T1 adapters present in the map
            apy_std_dev     — float, sample std-dev across ALL adapters (0.0 if ≤1 value)
            t1_adapters     — list[str] of T1 adapter IDs found in apy_map
            all_adapters    — list[str] of all adapter IDs in apy_map
            recommendation  — "hold" | "increase_exposure" | "reduce_exposure" | "diversify"
            detected_at     — ISO-8601 UTC timestamp
        """
        # --- Edge case: empty map ----------------------------------------
        if not apy_map:
            result = {
                "regime": self.REGIME_STABLE,
                "t1_avg_apy": 0.0,
                "apy_std_dev": 0.0,
                "t1_adapters": [],
                "all_adapters": [],
                "recommendation": "hold",
                "detected_at": datetime.now(timezone.utc).isoformat(),
            }
            self._last_result = result
            return result

        # --- Filter valid numeric values ----------------------------------
        all_valid: List[float] = [
            float(v) for v in apy_map.values()
            if isinstance(v, (int, float)) and not math.isnan(v) and not math.isinf(v)
        ]

        # --- Identify T1 adapters -----------------------------------------
        t1_adapters: List[str] = [k for k in apy_map if k in _T1_IDS]
        t1_apy_values: List[float] = [
            float(apy_map[k]) for k in t1_adapters
            if isinstance(apy_map[k], (int, float))
            and not math.isnan(apy_map[k])
            and not math.isinf(apy_map[k])
        ]

        # --- T1 average APY -----------------------------------------------
        # If no T1 adapter present, fall back to overall average so the
        # module degrades gracefully (doesn't crash).
        if t1_apy_values:
            t1_avg_apy = statistics.mean(t1_apy_values)
        elif all_valid:
            t1_avg_apy = statistics.mean(all_valid)
        else:
            t1_avg_apy = 0.0

        # --- APY std-dev (all adapters, sample) ---------------------------
        apy_std_dev = statistics.stdev(all_valid) if len(all_valid) >= 2 else 0.0

        # --- Classify (priority: VOLATILE > HIGH_YIELD > COMPRESSED > STABLE)
        if apy_std_dev > self.VOLATILITY_THRESHOLD_PCT:
            regime = self.REGIME_VOLATILE
            recommendation = "diversify"
        elif t1_avg_apy > self.HIGH_YIELD_THRESHOLD_PCT:
            regime = self.REGIME_HIGH_YIELD
            recommendation = "increase_exposure"
        elif t1_avg_apy < self.LOW_YIELD_THRESHOLD_PCT:
            regime = self.REGIME_COMPRESSED
            recommendation = "reduce_exposure"
        else:
            regime = self.REGIME_STABLE
            recommendation = "hold"

        result: dict = {
            "regime": regime,
            "t1_avg_apy": round(t1_avg_apy, 4),
            "apy_std_dev": round(apy_std_dev, 4),
            "t1_adapters": t1_adapters,
            "all_adapters": list(apy_map.keys()),
            "recommendation": recommendation,
            "detected_at": datetime.now(timezone.utc).isoformat(),
        }
        self._last_result = result
        return result

    def get_regime_weights(self, regime: str) -> dict:
        """
        Return tier weight modifiers and exposure multiplier for a given regime.

        T1 / T2 / T3 weights sum to 1.0 within each regime and represent the
        *relative target allocation* between tiers (not absolute caps — those
        are still enforced by RiskPolicy).

        Returns
        -------
        dict with keys: T1 (float), T2 (float), T3 (float),
                        modifier (str), exposure_multiplier (float)
        """
        _weights: Dict[str, dict] = {
            self.REGIME_HIGH_YIELD: {
                "T1": 0.50,
                "T2": 0.30,   # +20 pp vs STABLE T2
                "T3": 0.20,   # elevated T3 in risk-on environment
                "modifier": "increase",
                "exposure_multiplier": 1.20,   # +20% overall exposure
            },
            self.REGIME_COMPRESSED: {
                "T1": 1.00,   # consolidate fully to T1
                "T2": 0.00,
                "T3": 0.00,
                "modifier": "consolidate",
                "exposure_multiplier": 0.90,   # slight reduction
            },
            self.REGIME_VOLATILE: {
                "T1": 0.90,   # stay T1, minimal T2
                "T2": 0.10,
                "T3": 0.00,
                "modifier": "reduce",
                "exposure_multiplier": 0.70,   # -30% overall exposure
            },
            self.REGIME_STABLE: {
                "T1": 0.70,
                "T2": 0.25,
                "T3": 0.05,
                "modifier": "default",
                "exposure_multiplier": 1.00,
            },
        }
        return _weights.get(regime, _weights[self.REGIME_STABLE])

    def to_dict(self) -> dict:
        """Return serializable state snapshot for logging / debugging."""
        return {
            "last_result": self._last_result,
            "config": {
                "HIGH_YIELD_THRESHOLD_PCT": self.HIGH_YIELD_THRESHOLD_PCT,
                "LOW_YIELD_THRESHOLD_PCT": self.LOW_YIELD_THRESHOLD_PCT,
                "VOLATILITY_THRESHOLD_PCT": self.VOLATILITY_THRESHOLD_PCT,
                "t1_adapter_ids": sorted(_T1_IDS),
            },
        }

    # ------------------------------------------------------------------
    # I/O helpers
    # ------------------------------------------------------------------

    def save_to_cache(self, result: dict) -> None:
        """
        Atomically write *result* to ``<data_dir>/market_regime.json``.

        Uses mkstemp + os.replace — safe under concurrent writers.
        """
        os.makedirs(self._data_dir, exist_ok=True)
        cache_path = os.path.join(self._data_dir, "market_regime.json")
        fd, tmp_path = tempfile.mkstemp(dir=self._data_dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(result, fh, indent=2)
            os.replace(tmp_path, cache_path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def load_from_adapter_status(self) -> Dict[str, float]:
        """
        Build an apy_map from ``data/adapter_status.json``.

        Reads ``mock_apy.ethereum.USDC`` first; falls back to other chains/
        assets; skips adapters with no numeric APY.  If the file is missing
        or malformed, returns a small hardcoded fallback map so the CLI
        always produces output.
        """
        status_path = os.path.join(self._data_dir, "adapter_status.json")
        apy_map: Dict[str, float] = {}
        try:
            with open(status_path, encoding="utf-8") as fh:
                data = json.load(fh)

            for adapter in data.get("adapters", []):
                key: str = adapter.get("protocol_key", "")
                if not key:
                    continue
                mock_apy: dict = adapter.get("mock_apy", {})
                apy: Optional[float] = None

                # Preference order: ethereum USDC → ethereum any → any chain any asset
                eth = mock_apy.get("ethereum", {})
                for asset in ("USDC", "USDT", "DAI"):
                    if eth.get(asset) is not None:
                        apy = float(eth[asset])
                        break

                if apy is None:
                    for chain_data in mock_apy.values():
                        if isinstance(chain_data, dict):
                            for v in chain_data.values():
                                if v is not None:
                                    apy = float(v)
                                    break
                        if apy is not None:
                            break

                if apy is not None:
                    apy_map[key] = apy

        except (FileNotFoundError, json.JSONDecodeError, KeyError):
            # Hardcoded fallback — representative STABLE regime values
            apy_map = {
                "aave-v3": 4.2,
                "compound-v3": 4.8,
                "morpho-steakhouse": 6.5,
            }

        return apy_map


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

def _main() -> int:
    detector = MarketRegimeDetector()
    apy_map = detector.load_from_adapter_status()
    result = detector.detect(apy_map)
    detector.save_to_cache(result)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
