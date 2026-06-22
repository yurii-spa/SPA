"""
MP-799 ProtocolDominanceTracker
Tracks each protocol's share of total DeFi TVL within its category,
detects dominance shifts, flags monopoly or concentration risk.

Pure stdlib, read-only advisory, atomic writes, ring-buffer 100.
"""

import json
import os
import time
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_LOG = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "protocol_dominance_log.json"
)
_LOG_MAX = 100

_VALID_CATEGORIES = {"lending", "dex", "yield", "stablecoin", "other"}

# Dominance thresholds (defaults)
_DEFAULT_DOMINANCE_THRESHOLD = 50.0
_DEFAULT_MONOPOLY_THRESHOLD = 70.0

# HHI concentration boundaries
_HHI_MONOPOLISTIC = 0.7
_HHI_CONCENTRATED = 0.4
_HHI_MODERATE = 0.2


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze(protocols: list, config: dict = None) -> dict:
    """
    Analyse protocol TVL dominance within each DeFi category.

    Parameters
    ----------
    protocols : list[dict]
        Each item: {
            "name": str,
            "category": str,           # lending | dex | yield | stablecoin | other
            "tvl_usd": float,
            "tvl_7d_ago_usd": float    # optional
        }
    config : dict, optional
        {
            "dominance_threshold": float,   # default 50.0
            "monopoly_threshold": float     # default 70.0
        }

    Returns
    -------
    dict  (see module docstring for full schema)
    """
    cfg = config or {}
    dominance_threshold = float(cfg.get("dominance_threshold", _DEFAULT_DOMINANCE_THRESHOLD))
    monopoly_threshold = float(cfg.get("monopoly_threshold", _DEFAULT_MONOPOLY_THRESHOLD))

    # ---- group protocols by category ----------------------------------------
    by_category: dict = {}
    total_tvl = 0.0

    for p in protocols:
        cat = str(p.get("category", "other")).lower()
        if cat not in _VALID_CATEGORIES:
            cat = "other"
        tvl = max(0.0, float(p.get("tvl_usd", 0.0)))
        total_tvl += tvl
        by_category.setdefault(cat, []).append({
            "name": str(p.get("name", "")),
            "tvl_usd": tvl,
            "tvl_7d_ago_usd": p.get("tvl_7d_ago_usd"),
        })

    # ---- compute per-category metrics ----------------------------------------
    category_results: dict = {}
    concentration_alerts: list = []
    diversification_opportunities: list = []

    for cat, items in by_category.items():
        cat_tvl = sum(i["tvl_usd"] for i in items)

        # --- build per-protocol rows ---
        proto_rows = []
        for item in items:
            tvl = item["tvl_usd"]
            share = (tvl / cat_tvl * 100.0) if cat_tvl > 0 else 0.0

            # 7-day change
            tvl_7d = item["tvl_7d_ago_usd"]
            tvl_change_7d = None
            share_change_7d = None
            if tvl_7d is not None:
                tvl_7d = float(tvl_7d)
                if tvl_7d > 0:
                    tvl_change_7d = (tvl - tvl_7d) / tvl_7d * 100.0
                else:
                    tvl_change_7d = 0.0
                # what share would have been 7 days ago if category TVL unchanged
                old_share = (tvl_7d / cat_tvl * 100.0) if cat_tvl > 0 else 0.0
                share_change_7d = share - old_share

            # dominance status
            if share >= dominance_threshold:
                status = "DOMINANT"
            elif share >= 20.0:
                status = "MAJOR"
            elif share >= 5.0:
                status = "MINOR"
            else:
                status = "NICHE"

            proto_rows.append({
                "name": item["name"],
                "tvl_usd": tvl,
                "market_share_pct": round(share, 4),
                "tvl_change_7d_pct": round(tvl_change_7d, 4) if tvl_change_7d is not None else None,
                "share_change_7d_ppt": round(share_change_7d, 4) if share_change_7d is not None else None,
                "dominance_status": status,
            })

        # --- sort by TVL desc ---
        proto_rows.sort(key=lambda x: x["tvl_usd"], reverse=True)

        # --- HHI ---
        hhi = sum((r["market_share_pct"] / 100.0) ** 2 for r in proto_rows)

        # --- concentration level ---
        if hhi > _HHI_MONOPOLISTIC:
            conc_level = "MONOPOLISTIC"
        elif hhi > _HHI_CONCENTRATED:
            conc_level = "CONCENTRATED"
        elif hhi > _HHI_MODERATE:
            conc_level = "MODERATE"
        else:
            conc_level = "COMPETITIVE"

        leader = proto_rows[0]["name"] if proto_rows else ""
        leader_share = proto_rows[0]["market_share_pct"] if proto_rows else 0.0

        # --- alerts ---
        for r in proto_rows:
            if r["dominance_status"] == "DOMINANT":
                concentration_alerts.append(
                    f"{r['name']} dominates {cat} with {r['market_share_pct']:.1f}%"
                )

        if conc_level == "MONOPOLISTIC":
            concentration_alerts.append(
                f"Category {cat} is MONOPOLISTIC (HHI={round(hhi, 4)})"
            )

        if conc_level == "COMPETITIVE":
            diversification_opportunities.append(cat)

        category_results[cat] = {
            "total_tvl_usd": round(cat_tvl, 2),
            "protocols": proto_rows,
            "category_hhi": round(hhi, 6),
            "concentration_level": conc_level,
            "leader": leader,
            "leader_share_pct": round(leader_share, 4),
        }

    return {
        "total_tvl_usd": round(total_tvl, 2),
        "by_category": category_results,
        "concentration_alerts": concentration_alerts,
        "diversification_opportunities": diversification_opportunities,
        "timestamp": time.time(),
    }


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

def save_snapshot(result: dict, log_path: str = None) -> None:
    """Append *result* to the ring-buffer JSON log (max 100 entries, atomic)."""
    path = os.path.abspath(log_path or _DEFAULT_LOG)
    _ensure_dir(path)

    existing = _read_log(path)
    existing.append(result)
    if len(existing) > _LOG_MAX:
        existing = existing[-_LOG_MAX:]

    _atomic_write(path, existing)


def load_log(log_path: str = None) -> list:
    """Return the full ring-buffer log list."""
    path = os.path.abspath(log_path or _DEFAULT_LOG)
    return _read_log(path)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _read_log(path: str) -> list:
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _atomic_write(path: str, data) -> None:
    dir_ = os.path.dirname(path) or "."
    atomic_save(data, str(path))
def _ensure_dir(path: str) -> None:
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    sample = [
        {"name": "Aave", "category": "lending", "tvl_usd": 12_000_000_000, "tvl_7d_ago_usd": 11_500_000_000},
        {"name": "Compound", "category": "lending", "tvl_usd": 3_000_000_000, "tvl_7d_ago_usd": 3_100_000_000},
        {"name": "Morpho", "category": "lending", "tvl_usd": 2_000_000_000},
        {"name": "Uniswap", "category": "dex", "tvl_usd": 5_000_000_000},
        {"name": "Curve", "category": "dex", "tvl_usd": 2_500_000_000},
        {"name": "Yearn", "category": "yield", "tvl_usd": 700_000_000},
    ]

    mode = sys.argv[1] if len(sys.argv) > 1 else "--check"
    result = analyze(sample)

    if mode == "--run":
        save_snapshot(result)
        print("Snapshot saved.")
    else:
        print(json.dumps(result, indent=2))
