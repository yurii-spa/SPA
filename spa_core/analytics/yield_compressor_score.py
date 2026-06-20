"""
MP-784: YieldCompressorScore
Detects yield compression trends across the DeFi market.

CLI:
    python3 -m spa_core.analytics.yield_compressor_score --check
    python3 -m spa_core.analytics.yield_compressor_score --run
    python3 -m spa_core.analytics.yield_compressor_score --run --data-dir <dir>
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from datetime import datetime, timezone
from typing import Any

from spa_core.utils.errors import SPAError

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LOG_FILE_DEFAULT = "data/yield_compressor_log.json"
LOG_CAP = 100

REGIME_EXPANDING = "EXPANDING"
REGIME_STABLE = "STABLE"
REGIME_COMPRESSING = "COMPRESSING"
REGIME_SEVERELY_COMPRESSED = "SEVERELY_COMPRESSED"


# ---------------------------------------------------------------------------
# YieldCompressorScore
# ---------------------------------------------------------------------------


class YieldCompressorScore:
    """Detects yield compression trends across the DeFi market.

    Parameters
    ----------
    data_dir : str
        Directory where ``yield_compressor_log.json`` is written.
    """

    def __init__(self, data_dir: str = "") -> None:
        self._data_dir = data_dir
        self._last_result: dict[str, Any] | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compute(self, protocols: list[dict[str, Any]]) -> dict[str, Any]:
        """Compute per-protocol and market-level compression metrics.

        Parameters
        ----------
        protocols : list[dict]
            Each element must contain:
                protocol        str   – protocol name
                apy_30d_ago     float – APY 30 days ago (%)
                apy_now         float – current APY (%)
                tvl_usd         float – current TVL in USD
                category        str   – protocol category
        """
        if not protocols:
            result = self._empty_result()
            self._last_result = result
            return result

        per_protocol: list[dict[str, Any]] = []
        for p in protocols:
            proto = str(p.get("protocol", "unknown"))
            apy_ago = float(p.get("apy_30d_ago", 0.0))
            apy_now = float(p.get("apy_now", 0.0))
            tvl = float(p.get("tvl_usd", 0.0))
            category = str(p.get("category", ""))

            # compression_pct: positive = yield fell (compressed)
            if apy_ago != 0.0:
                compression_pct = (apy_ago - apy_now) / abs(apy_ago) * 100.0
            else:
                compression_pct = 0.0

            compression_rate_per_day = compression_pct / 30.0

            per_protocol.append(
                {
                    "protocol": proto,
                    "apy_30d_ago": apy_ago,
                    "apy_now": apy_now,
                    "tvl_usd": tvl,
                    "category": category,
                    "compression_pct": round(compression_pct, 4),
                    "compression_rate_per_day": round(compression_rate_per_day, 6),
                }
            )

        # Market-level aggregates
        c_pcts = [r["compression_pct"] for r in per_protocol]
        avg_compression_pct = sum(c_pcts) / len(c_pcts) if c_pcts else 0.0

        # Market compression score 0-100
        # Maps avg_compression_pct in range [-inf, +inf] → clamp to [0, 100]
        # 0 compression → score 49 (STABLE); each 1% compression adds 0.5 points
        raw_score = 49.0 + avg_compression_pct * 0.5
        market_compression_score = max(0.0, min(100.0, raw_score))

        compression_regime = self._score_to_regime(market_compression_score)

        # Outliers: compression > 2x market average (only meaningful if avg > 0)
        outliers: list[dict[str, Any]] = []
        threshold = 2.0 * avg_compression_pct if avg_compression_pct > 0 else float("inf")
        for r in per_protocol:
            if avg_compression_pct > 0 and r["compression_pct"] > threshold:
                outliers.append(
                    {
                        "protocol": r["protocol"],
                        "compression_pct": r["compression_pct"],
                        "vs_market_avg": round(
                            r["compression_pct"] / avg_compression_pct if avg_compression_pct else 0.0,
                            3,
                        ),
                    }
                )

        result: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "per_protocol": per_protocol,
            "market": {
                "avg_compression_pct": round(avg_compression_pct, 4),
                "market_compression_score": round(market_compression_score, 2),
                "compression_regime": compression_regime,
                "protocol_count": len(per_protocol),
            },
            "outliers": outliers,
        }
        self._last_result = result
        return result

    def get_market_regime(self) -> str:
        """Return the compression regime from the last ``compute()`` call."""
        if self._last_result is None:
            return REGIME_STABLE
        return self._last_result["market"]["compression_regime"]

    def get_compressed_outliers(self) -> list[dict[str, Any]]:
        """Return outlier protocols from the last ``compute()`` call."""
        if self._last_result is None:
            return []
        return self._last_result.get("outliers", [])

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, data_dir: str = "") -> str:
        """Append the last result to the ring-buffer log (cap 100).

        Returns the path written.
        """
        if self._last_result is None:
            raise SPAError("No result to save – call compute() first.", code="NOT_INITIALIZED")

        base = data_dir or self._data_dir or ""
        path = os.path.join(base, LOG_FILE_DEFAULT) if not base.endswith(".json") else base
        if base:
            path = os.path.join(base, "yield_compressor_log.json")
        else:
            path = LOG_FILE_DEFAULT

        _atomic_append(path, self._last_result, cap=LOG_CAP)
        return path

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _score_to_regime(score: float) -> str:
        if score < 25:
            return REGIME_EXPANDING
        if score < 50:
            return REGIME_STABLE
        if score <= 75:
            return REGIME_COMPRESSING
        return REGIME_SEVERELY_COMPRESSED

    @staticmethod
    def _empty_result() -> dict[str, Any]:
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "per_protocol": [],
            "market": {
                "avg_compression_pct": 0.0,
                "market_compression_score": 50.0,
                "compression_regime": REGIME_STABLE,
                "protocol_count": 0,
            },
            "outliers": [],
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _atomic_append(path: str, entry: dict[str, Any], cap: int = 100) -> None:
    """Read existing log, append entry, cap to ``cap``, atomic write."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    existing: list[dict[str, Any]] = []
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                existing = json.load(fh)
            if not isinstance(existing, list):
                existing = []
        except (json.JSONDecodeError, OSError):
            existing = []

    existing.append(entry)
    existing = existing[-cap:]  # ring-buffer

    dir_ = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(dir=dir_, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(existing, fh, indent=2)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _sample_protocols() -> list[dict]:
    """Realistic sample data for --check / --run."""
    return [
        {"protocol": "Aave V3", "apy_30d_ago": 4.2, "apy_now": 3.5, "tvl_usd": 8_000_000, "category": "lending"},
        {"protocol": "Compound V3", "apy_30d_ago": 5.8, "apy_now": 4.8, "tvl_usd": 6_000_000, "category": "lending"},
        {"protocol": "Morpho Steakhouse", "apy_30d_ago": 7.1, "apy_now": 6.5, "tvl_usd": 5_500_000, "category": "curated-vault"},
        {"protocol": "Yearn V3", "apy_30d_ago": 9.0, "apy_now": 5.0, "tvl_usd": 3_000_000, "category": "vault"},
        {"protocol": "Euler V2", "apy_30d_ago": 6.0, "apy_now": 6.2, "tvl_usd": 2_800_000, "category": "lending"},
    ]


def _main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="MP-784 YieldCompressorScore")
    parser.add_argument("--check", action="store_true", help="Compute + print, no write (default)")
    parser.add_argument("--run", action="store_true", help="Compute + atomic write to log")
    parser.add_argument("--data-dir", default="", help="Override data directory")
    args = parser.parse_args()

    scorer = YieldCompressorScore(data_dir=args.data_dir)
    protocols = _sample_protocols()
    result = scorer.compute(protocols)

    print(json.dumps(result, indent=2))
    print(f"\nRegime: {scorer.get_market_regime()}")
    outliers = scorer.get_compressed_outliers()
    if outliers:
        print(f"Outliers ({len(outliers)}): {[o['protocol'] for o in outliers]}")
    else:
        print("No outliers detected.")

    if args.run:
        path = scorer.save(data_dir=args.data_dir)
        print(f"\nSaved → {path}")


if __name__ == "__main__":
    _main()
