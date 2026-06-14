"""
MP-819 CollateralDiversificationScorer
=======================================
Advisory/read-only module.
Scores how well a lending protocol's collateral is diversified across asset
types, reducing systemic correlation risk.

CLI:
    python3 -m spa_core.analytics.collateral_diversification_scorer --check
    python3 -m spa_core.analytics.collateral_diversification_scorer --run
    python3 -m spa_core.analytics.collateral_diversification_scorer --run --data-dir <dir>

Pure stdlib only. Atomic ring-buffer log (cap 100) written to
data/collateral_diversification_log.json.
"""

from __future__ import annotations

import json
import os
import time
import argparse
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_DEFAULT_MAX_SINGLE_ASSET_PCT: float = 30.0
_DEFAULT_MAX_SINGLE_CATEGORY_PCT: float = 50.0
_LOG_CAP: int = 100
_DEFAULT_LOG_FILE: str = "data/collateral_diversification_log.json"

_VALID_CATEGORIES = {
    "stablecoin",
    "eth_derivative",
    "btc_derivative",
    "defi_token",
    "rwa",
    "other",
}

# ---------------------------------------------------------------------------
# Grade thresholds
# ---------------------------------------------------------------------------
def _grade(total_score: int) -> str:
    if total_score >= 80:
        return "A"
    if total_score >= 65:
        return "B"
    if total_score >= 50:
        return "C"
    if total_score >= 35:
        return "D"
    return "F"


# ---------------------------------------------------------------------------
# Core analysis
# ---------------------------------------------------------------------------
def analyze(
    protocol: str,
    collateral_assets: list[dict],
    config: dict | None = None,
) -> dict:
    """
    Analyze collateral diversification for a lending protocol.

    Parameters
    ----------
    protocol : str
        Name of the lending protocol.
    collateral_assets : list[dict]
        Each element must have:
            symbol            : str
            category          : str  (see _VALID_CATEGORIES)
            collateral_usd    : float
            volatility_30d_pct: float  (annualised 30-day vol %)
            correlation_to_eth: float  (-1.0 … 1.0)
    config : dict | None
        Optional overrides:
            max_single_asset_pct    : float  (default 30.0)
            max_single_category_pct : float  (default 50.0)

    Returns
    -------
    dict
        Full analysis result (see module docstring for schema).
    """
    cfg = config or {}
    max_single_asset_pct: float = float(
        cfg.get("max_single_asset_pct", _DEFAULT_MAX_SINGLE_ASSET_PCT)
    )
    max_single_category_pct: float = float(
        cfg.get("max_single_category_pct", _DEFAULT_MAX_SINGLE_CATEGORY_PCT)
    )

    ts = time.time()

    # ------------------------------------------------------------------
    # Edge case: empty collateral list
    # ------------------------------------------------------------------
    if not collateral_assets:
        return {
            "protocol": protocol,
            "total_collateral_usd": 0.0,
            "asset_count": 0,
            "by_category": {},
            "top_assets": [],
            "metrics": {
                "weighted_volatility": 0.0,
                "weighted_eth_correlation": 0.0,
                "hhi": 0.0,
                "diversification_ratio": 0.0,
            },
            "scores": {
                "asset_diversity_score": 0,
                "category_diversity_score": 0,
                "concentration_score": 0,
                "volatility_score": 0,
                "total_score": 0,
            },
            "grade": "F",
            "risk_flags": [],
            "timestamp": ts,
        }

    # ------------------------------------------------------------------
    # Aggregate totals
    # ------------------------------------------------------------------
    total_usd: float = sum(
        max(0.0, float(a.get("collateral_usd", 0.0))) for a in collateral_assets
    )

    # Build per-asset pct (guard against zero total)
    asset_records: list[dict] = []
    for a in collateral_assets:
        usd = max(0.0, float(a.get("collateral_usd", 0.0)))
        pct = (usd / total_usd * 100.0) if total_usd > 0 else 0.0
        asset_records.append(
            {
                "symbol": str(a.get("symbol", "")),
                "category": str(a.get("category", "other")),
                "collateral_usd": usd,
                "pct": pct,
                "volatility_30d_pct": float(a.get("volatility_30d_pct", 0.0)),
                "correlation_to_eth": float(a.get("correlation_to_eth", 0.0)),
            }
        )

    # ------------------------------------------------------------------
    # by_category aggregation
    # ------------------------------------------------------------------
    by_category: dict[str, Any] = {}
    for ar in asset_records:
        cat = ar["category"]
        if cat not in by_category:
            by_category[cat] = {"usd": 0.0, "pct": 0.0, "assets": []}
        by_category[cat]["usd"] += ar["collateral_usd"]
        by_category[cat]["assets"].append(ar["symbol"])

    for cat, info in by_category.items():
        info["pct"] = (info["usd"] / total_usd * 100.0) if total_usd > 0 else 0.0

    # ------------------------------------------------------------------
    # top_assets: all assets sorted by collateral_usd descending
    # ------------------------------------------------------------------
    top_assets = sorted(asset_records, key=lambda x: x["collateral_usd"], reverse=True)
    top_assets_out = [
        {
            "symbol": ar["symbol"],
            "category": ar["category"],
            "pct": round(ar["pct"], 4),
            "volatility_30d_pct": ar["volatility_30d_pct"],
        }
        for ar in top_assets
    ]

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------
    weighted_volatility: float = sum(
        (ar["pct"] / 100.0) * ar["volatility_30d_pct"] for ar in asset_records
    )
    weighted_eth_correlation: float = sum(
        (ar["pct"] / 100.0) * ar["correlation_to_eth"] for ar in asset_records
    )
    hhi: float = sum((ar["pct"] / 100.0) ** 2 for ar in asset_records)
    diversification_ratio: float = 1.0 - hhi

    # ------------------------------------------------------------------
    # Scores
    # ------------------------------------------------------------------
    asset_count = len(asset_records)
    unique_categories = len(by_category)

    asset_diversity_score = int(min(asset_count * 5, 40))
    category_diversity_score = int(min(unique_categories * 6, 30))
    concentration_score = int(round(20 * diversification_ratio))

    if weighted_volatility < 30:
        volatility_score = 10
    elif weighted_volatility < 60:
        volatility_score = 5
    else:
        volatility_score = 0

    total_score = max(
        0,
        min(
            100,
            asset_diversity_score
            + category_diversity_score
            + concentration_score
            + volatility_score,
        ),
    )

    # ------------------------------------------------------------------
    # Risk flags
    # ------------------------------------------------------------------
    risk_flags: list[str] = []

    # Per-asset concentration flags
    for ar in asset_records:
        if ar["pct"] > max_single_asset_pct:
            risk_flags.append(
                f"{ar['symbol']} exceeds {max_single_asset_pct:.0f}% of collateral "
                f"({ar['pct']:.1f}%)"
            )

    # Per-category concentration flags
    for cat, info in by_category.items():
        if info["pct"] > max_single_category_pct:
            risk_flags.append(
                f"{cat} category exceeds {max_single_category_pct:.0f}% "
                f"({info['pct']:.1f}%)"
            )

    # Systemic-risk flags
    if weighted_eth_correlation > 0.8:
        risk_flags.append("High ETH correlation (>0.8) — systemic risk")

    if weighted_volatility > 80:
        risk_flags.append("High weighted collateral volatility (>80%)")

    # ------------------------------------------------------------------
    # Build final result
    # ------------------------------------------------------------------
    result: dict = {
        "protocol": protocol,
        "total_collateral_usd": round(total_usd, 4),
        "asset_count": asset_count,
        "by_category": {
            cat: {
                "usd": round(info["usd"], 4),
                "pct": round(info["pct"], 4),
                "assets": info["assets"],
            }
            for cat, info in by_category.items()
        },
        "top_assets": top_assets_out,
        "metrics": {
            "weighted_volatility": round(weighted_volatility, 4),
            "weighted_eth_correlation": round(weighted_eth_correlation, 4),
            "hhi": round(hhi, 6),
            "diversification_ratio": round(diversification_ratio, 6),
        },
        "scores": {
            "asset_diversity_score": asset_diversity_score,
            "category_diversity_score": category_diversity_score,
            "concentration_score": concentration_score,
            "volatility_score": volatility_score,
            "total_score": total_score,
        },
        "grade": _grade(total_score),
        "risk_flags": risk_flags,
        "timestamp": ts,
    }
    return result


# ---------------------------------------------------------------------------
# Log persistence (ring-buffer, cap 100, atomic write)
# ---------------------------------------------------------------------------
def _append_log(result: dict, data_dir: str = "data") -> None:
    """Atomically append *result* to the ring-buffer log (cap 100 entries)."""
    log_path = os.path.join(data_dir, "collateral_diversification_log.json")
    tmp_path = log_path + ".tmp"

    try:
        with open(log_path, "r", encoding="utf-8") as fh:
            log: list = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        log = []

    log.append(result)
    if len(log) > _LOG_CAP:
        log = log[-_LOG_CAP:]

    with open(tmp_path, "w", encoding="utf-8") as fh:
        json.dump(log, fh, indent=2)
    os.replace(tmp_path, log_path)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------
def _sample_assets() -> list[dict]:
    """Return a synthetic sample for demo/check mode."""
    return [
        {
            "symbol": "ETH",
            "category": "eth_derivative",
            "collateral_usd": 40_000_000.0,
            "volatility_30d_pct": 55.0,
            "correlation_to_eth": 1.0,
        },
        {
            "symbol": "USDC",
            "category": "stablecoin",
            "collateral_usd": 25_000_000.0,
            "volatility_30d_pct": 0.5,
            "correlation_to_eth": 0.05,
        },
        {
            "symbol": "WBTC",
            "category": "btc_derivative",
            "collateral_usd": 20_000_000.0,
            "volatility_30d_pct": 50.0,
            "correlation_to_eth": 0.75,
        },
        {
            "symbol": "UNI",
            "category": "defi_token",
            "collateral_usd": 8_000_000.0,
            "volatility_30d_pct": 80.0,
            "correlation_to_eth": 0.65,
        },
        {
            "symbol": "ONDO",
            "category": "rwa",
            "collateral_usd": 7_000_000.0,
            "volatility_30d_pct": 35.0,
            "correlation_to_eth": 0.2,
        },
    ]


def main() -> None:  # pragma: no cover
    parser = argparse.ArgumentParser(
        description="MP-819 CollateralDiversificationScorer"
    )
    parser.add_argument("--check", action="store_true", help="Run analysis, no write")
    parser.add_argument("--run", action="store_true", help="Run analysis + write log")
    parser.add_argument("--data-dir", default="data", help="Directory for JSON logs")
    args = parser.parse_args()

    assets = _sample_assets()
    result = analyze("SampleProtocol", assets)

    print(json.dumps(result, indent=2))
    print(f"\nGrade: {result['grade']}  Score: {result['scores']['total_score']}")

    if args.run:
        os.makedirs(args.data_dir, exist_ok=True)
        _append_log(result, data_dir=args.data_dir)
        print(f"[MP-819] Log written to {args.data_dir}/collateral_diversification_log.json")


if __name__ == "__main__":  # pragma: no cover
    main()
