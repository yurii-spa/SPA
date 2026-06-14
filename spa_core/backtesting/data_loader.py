"""
SPA Backtesting — Historical Data Loader
=========================================

Provides three data sources for the BacktestEngine:
  1. load_from_export_json() — reads the current data/pools.json (single-point snapshot,
     used as a baseline until multi-day history accumulates).
  2. generate_synthetic_history() — creates a realistic 90-day synthetic APY history
     using a random walk around the current/baseline APYs, with ±1.5% realistic variance.
  3. load_from_defillama_api() — fetches real 90-day historical APY data from DeFiLlama
     via DeFiLlamaFetcher.fetch_all_historical(); falls back to generate_synthetic_history()
     on any error.

All three return the same format:
    list[dict] where each dict has:
        {
            "timestamp": "YYYY-MM-DD",      # ISO date string (daily granularity)
            "protocol_key": str,
            "apy": float,                   # total APY in %
            "tvl_usd": float,
            "tier": str,                    # "T1" or "T2"
        }

Records are sorted by (timestamp, protocol_key).
"""

from __future__ import annotations

import json
import random
import math
from datetime import date, timedelta
from pathlib import Path
from typing import Optional


# ── Baseline protocol definitions ─────────────────────────────────────────────
# These are the 7 whitelisted protocols in the SPA universe.
# APY and TVL figures are from the May 2026 deep-research baseline.

_BASELINE_PROTOCOLS = [
    {
        "protocol_key": "aave-v3-usdc-ethereum",
        "tier": "T1",
        "apy": 4.65,
        "tvl_usd": 138_000_000,
    },
    {
        "protocol_key": "aave-v3-usdt-ethereum",
        "tier": "T1",
        "apy": 4.20,
        "tvl_usd": 95_000_000,
    },
    {
        "protocol_key": "compound-v3-usdc-ethereum",
        "tier": "T1",
        "apy": 4.10,
        "tvl_usd": 42_000_000,
    },
    {
        "protocol_key": "morpho-usdc-ethereum",
        "tier": "T1",
        "apy": 5.30,
        "tvl_usd": 112_000_000,
    },
    {
        "protocol_key": "yearn-v3-usdc-ethereum",
        "tier": "T2",
        "apy": 6.80,
        "tvl_usd": 28_000_000,
    },
    {
        "protocol_key": "maple-usdc-ethereum",
        "tier": "T2",
        "apy": 7.50,
        "tvl_usd": 18_000_000,
    },
    {
        "protocol_key": "euler-v2-usdc-ethereum",
        "tier": "T2",
        "apy": 5.90,
        "tvl_usd": 22_000_000,
    },
]


def load_from_export_json(data_dir: str = None) -> list[dict]:
    """
    Load protocol data from the existing data/protocols.json export.

    This creates a single-date snapshot using today's date. As real multi-day
    history accumulates (via GitHub Actions daily runs), this will be replaced
    by a proper time-series loader.

    Args:
        data_dir: Path to the data/ directory. Defaults to ../data/ relative to
                  this file's location (i.e., the repo root data/ folder).

    Returns:
        List of daily-snapshot dicts for the current date only.
        Falls back to synthetic baseline data if the file is missing or malformed.
    """
    if data_dir is None:
        # spa_core/backtesting/ → spa_core/ → repo_root/data/
        data_dir = Path(__file__).parent.parent.parent / "data"
    else:
        data_dir = Path(data_dir)

    protocols_path = data_dir / "protocols.json"
    today = date.today().isoformat()
    records = []

    try:
        raw = json.loads(protocols_path.read_text(encoding="utf-8"))
        for p in raw:
            apy = p.get("apy_total") or p.get("apy")
            tvl = p.get("tvl_usd")
            key = p.get("key") or p.get("protocol_key")
            tier = p.get("tier", "T1")
            if apy is None or tvl is None or not key:
                continue
            records.append({
                "timestamp": today,
                "protocol_key": key,
                "apy": float(apy),
                "tvl_usd": float(tvl),
                "tier": tier,
            })
    except (FileNotFoundError, json.JSONDecodeError, KeyError, TypeError):
        # Fall back to baseline constants
        for p in _BASELINE_PROTOCOLS:
            records.append({
                "timestamp": today,
                "protocol_key": p["protocol_key"],
                "apy": p["apy"],
                "tvl_usd": p["tvl_usd"],
                "tier": p["tier"],
            })

    # If we couldn't get any real data, use baseline
    if not records:
        for p in _BASELINE_PROTOCOLS:
            records.append({
                "timestamp": today,
                "protocol_key": p["protocol_key"],
                "apy": p["apy"],
                "tvl_usd": p["tvl_usd"],
                "tier": p["tier"],
            })

    return sorted(records, key=lambda r: (r["timestamp"], r["protocol_key"]))


def generate_synthetic_history(
    days: int = 90,
    seed: int = 42,
    end_date: Optional[date] = None,
) -> list[dict]:
    """
    Generate a realistic synthetic 90-day APY history for all 7 protocols.

    Uses a mean-reverting random walk (Ornstein-Uhlenbeck style):
      APY(t+1) = APY(t) + θ * (μ - APY(t)) + σ * ε
    where:
      θ = 0.15  (mean-reversion speed — moderate)
      μ = baseline APY for each protocol
      σ = 1.5%  (daily volatility — realistic for stablecoin lending)
      ε ~ N(0, 1)

    TVL also drifts with a light random walk (±2% daily, clamped to ±50% from baseline).

    Args:
        days: Number of days of history to generate (default 90).
        seed: Random seed for reproducibility (default 42).
        end_date: Last date in the series (defaults to today).

    Returns:
        List of dicts with keys: timestamp, protocol_key, apy, tvl_usd, tier.
        Sorted by (timestamp, protocol_key). Total records = days × 7 protocols.
    """
    rng = random.Random(seed)

    if end_date is None:
        end_date = date.today()

    start_date = end_date - timedelta(days=days - 1)

    # OU parameters
    theta = 0.15      # mean reversion speed
    sigma_apy = 1.5   # daily APY volatility in %
    sigma_tvl = 0.02  # daily TVL volatility (fraction)
    apy_min = 0.5     # absolute floor
    apy_max = 25.0    # absolute ceiling

    records = []

    # Initialise current state for each protocol
    state = {
        p["protocol_key"]: {
            "apy": p["apy"],
            "tvl": p["tvl_usd"],
            "mu_apy": p["apy"],           # long-run mean
            "mu_tvl": p["tvl_usd"],       # long-run mean TVL
            "tier": p["tier"],
        }
        for p in _BASELINE_PROTOCOLS
    }

    current_date = start_date
    for _ in range(days):
        date_str = current_date.isoformat()

        for key, s in state.items():
            # Mean-reverting APY update
            eps_apy = _standard_normal(rng)
            delta_apy = theta * (s["mu_apy"] - s["apy"]) + sigma_apy * eps_apy
            new_apy = max(apy_min, min(apy_max, s["apy"] + delta_apy))
            s["apy"] = new_apy

            # Light TVL random walk (mean-reverting toward baseline)
            eps_tvl = _standard_normal(rng)
            tvl_drift = 0.05 * (s["mu_tvl"] - s["tvl"]) / s["mu_tvl"]
            tvl_change = tvl_drift + sigma_tvl * eps_tvl
            new_tvl = s["tvl"] * (1 + tvl_change)
            # Clamp TVL: not below 50% of baseline, not above 300% of baseline
            new_tvl = max(s["mu_tvl"] * 0.50, min(s["mu_tvl"] * 3.0, new_tvl))
            s["tvl"] = new_tvl

            records.append({
                "timestamp": date_str,
                "protocol_key": key,
                "apy": round(new_apy, 4),
                "tvl_usd": round(new_tvl, 0),
                "tier": s["tier"],
            })

        current_date += timedelta(days=1)

    return sorted(records, key=lambda r: (r["timestamp"], r["protocol_key"]))


def load_from_defillama_api(days: int = 90) -> list[dict]:
    """
    Load real historical APY data from DeFiLlama via the fetcher class.

    Calls DeFiLlamaFetcher().fetch_all_historical(days=days) and transforms
    the raw time-series into the standard BacktestEngine format:
        {timestamp: "YYYY-MM-DD", protocol_key, apy, tvl_usd, tier}

    Entries are deduplicated by (date, protocol_key) — keeping the last record
    if the API returns multiple entries per day. Sorted by (timestamp ASC,
    protocol_key ASC).

    Falls back to generate_synthetic_history(days=days) on ANY error (network,
    parse, import) so the rest of the pipeline is never blocked.

    Returns:
        (records, source) where source is "defillama" or "synthetic".
        NOTE: for convenience, the plain list[dict] is returned; check
        load_from_defillama_api.last_source after the call if needed.
    """
    import sys
    import logging
    from pathlib import Path

    log = logging.getLogger("spa.backtesting.data_loader")

    # tier lookup for the 7 backtest protocols
    _TIER_MAP = {
        p["protocol_key"]: p["tier"]
        for p in _BASELINE_PROTOCOLS
    }

    try:
        # Insert spa_core onto the path so the import works regardless of cwd
        spa_core_dir = Path(__file__).parent.parent
        if str(spa_core_dir) not in sys.path:
            sys.path.insert(0, str(spa_core_dir))

        from data_pipeline.defillama_fetcher import DeFiLlamaFetcher

        fetcher = DeFiLlamaFetcher()
        raw_histories = fetcher.fetch_all_historical(days=days)

        if not raw_histories:
            log.warning("DeFiLlama returned empty historical data — falling back to synthetic")
            load_from_defillama_api.last_source = "synthetic"
            return generate_synthetic_history(days=days)

        # Transform: {protocol_key: [{timestamp, tvlUsd, apy}, ...]} →
        #            [{timestamp: YYYY-MM-DD, protocol_key, apy, tvl_usd, tier}]
        records: dict[tuple, dict] = {}  # (date_str, protocol_key) → record

        for protocol_key, history in raw_histories.items():
            tier = _TIER_MAP.get(protocol_key, "T1")
            for entry in history:
                raw_ts  = entry.get("timestamp", "")
                apy_val = entry.get("apy", 0.0)
                tvl_val = entry.get("tvlUsd", 0.0)

                # Normalise timestamp → YYYY-MM-DD
                try:
                    if "T" in raw_ts:
                        date_str = raw_ts[:10]
                    elif len(raw_ts) >= 10:
                        date_str = raw_ts[:10]
                    else:
                        continue  # unparseable — skip
                except (TypeError, AttributeError):
                    continue

                key = (date_str, protocol_key)
                records[key] = {
                    "timestamp":    date_str,
                    "protocol_key": protocol_key,
                    "apy":          round(float(apy_val or 0.0), 4),
                    "tvl_usd":      round(float(tvl_val or 0.0), 0),
                    "tier":         tier,
                }

        if not records:
            log.warning("DeFiLlama historical parse produced 0 records — falling back to synthetic")
            load_from_defillama_api.last_source = "synthetic"
            return generate_synthetic_history(days=days)

        result = sorted(records.values(), key=lambda r: (r["timestamp"], r["protocol_key"]))
        load_from_defillama_api.last_source = "defillama"
        log.info(f"load_from_defillama_api: {len(result)} records for {len(raw_histories)} protocols")
        return result

    except Exception as exc:
        log.warning(f"load_from_defillama_api failed ({exc!r}) — falling back to synthetic")
        load_from_defillama_api.last_source = "synthetic"
        return generate_synthetic_history(days=days)


# Class-level attribute to track which source was used on the last call
load_from_defillama_api.last_source = "synthetic"


def _standard_normal(rng: random.Random) -> float:
    """Box-Muller transform to generate a standard normal sample from a seeded RNG."""
    while True:
        u1 = rng.random()
        u2 = rng.random()
        if u1 > 0:
            z = math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2)
            return z
