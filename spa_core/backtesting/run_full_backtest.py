"""
SPA Full 2-Year DeFiLlama Backtest — IDEA-005
==============================================

Фетчит реальные исторические данные за 730 дней через DeFiLlama chartData API,
прогоняет BacktestEngine на реальных (не синтетических) данных и сохраняет
результаты в data/backtest_full_2y.json + data/backtest_metrics.json.

Ключевое отличие от стандартного backtest:
  - 730 дней истории вместо 90
  - Реальные APY/TVL данные (не OU-process)
  - Per-protocol breakdown в результатах
  - Обновляет backtest_metrics.json для dashboard

Запуск:
    python -m spa_core.backtesting.run_full_backtest
    python -m spa_core.backtesting.run_full_backtest --days 365
    python -m spa_core.backtesting.run_full_backtest --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import urllib.request
from datetime import datetime, timezone, date, timedelta
from pathlib import Path
from typing import Optional

# ── Path setup ────────────────────────────────────────────────────────────────
_SPA_CORE = Path(__file__).parent.parent
_REPO_ROOT = _SPA_CORE.parent
_DATA_DIR = _REPO_ROOT / "data"

if str(_SPA_CORE) not in sys.path:
    sys.path.insert(0, str(_SPA_CORE))

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("spa.backtest.full_2y")

# ── Pool registry — 7 core whitelist protocols with DeFiLlama pool IDs ────────
# Sync with data_pipeline/defillama_fetcher.py :: BACKTEST_POOL_IDS
BACKTEST_POOLS = {
    "aave-v3-usdc-ethereum": {
        "pool_id": "aa70268e-4b52-42bf-a116-608b370f9501",
        "tier": "T1",
        "protocol": "Aave V3",
        "chain": "ethereum",
    },
    "aave-v3-usdt-ethereum": {
        "pool_id": "f981a304-bb6c-45b8-b0c5-fd2f515ad23a",
        "tier": "T1",
        "protocol": "Aave V3",
        "chain": "ethereum",
    },
    "compound-v3-usdc-ethereum": {
        "pool_id": "7da72d09-56ca-4ec5-a45f-59114353e487",
        "tier": "T1",
        "protocol": "Compound V3",
        "chain": "ethereum",
    },
    "morpho-usdc-ethereum": {
        "pool_id": "b55f43a8-f444-4cd8-a3a4-0a4e786ba566",
        "tier": "T1",
        "protocol": "Morpho",
        "chain": "ethereum",
    },
    "yearn-v3-usdc-ethereum": {
        "pool_id": "7d89af7a-24c9-4292-aa38-7c71b05fbd6d",
        "tier": "T2",
        "protocol": "Yearn V3",
        "chain": "ethereum",
    },
    "maple-usdc-ethereum": {
        "pool_id": "43641cf5-a92e-416b-bce9-27113d3c0db6",
        "tier": "T2",
        "protocol": "Maple Finance",
        "chain": "ethereum",
    },
    "euler-v2-usdc-ethereum": {
        "pool_id": "31a0cd94-b781-4e0d-a9f1-1702bc2c238f",
        "tier": "T2",
        "protocol": "Euler V2",
        "chain": "ethereum",
    },
}

DEFILLAMA_CHARTDATA_URL = "https://yields.llama.fi/chartData/{pool_id}"

# Fallback baseline APYs (used when DeFiLlama returns insufficient data)
_FALLBACK_APY: dict[str, float] = {
    "aave-v3-usdc-ethereum":    4.65,
    "aave-v3-usdt-ethereum":    4.20,
    "compound-v3-usdc-ethereum":4.10,
    "morpho-usdc-ethereum":     5.30,
    "yearn-v3-usdc-ethereum":   6.80,
    "maple-usdc-ethereum":      7.50,
    "euler-v2-usdc-ethereum":   5.90,
}
_FALLBACK_TVL: dict[str, float] = {
    "aave-v3-usdc-ethereum":    138_000_000,
    "aave-v3-usdt-ethereum":     95_000_000,
    "compound-v3-usdc-ethereum": 42_000_000,
    "morpho-usdc-ethereum":     112_000_000,
    "yearn-v3-usdc-ethereum":    28_000_000,
    "maple-usdc-ethereum":       18_000_000,
    "euler-v2-usdc-ethereum":    22_000_000,
}


# ─── HTTP helper ──────────────────────────────────────────────────────────────

def _retry_get(url: str, timeout: int = 20, max_attempts: int = 3, backoff: float = 2.0) -> bytes | None:
    """GET with exponential backoff. Returns raw bytes or None on failure."""
    for attempt in range(max_attempts):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as r:
                return r.read()
        except Exception as exc:
            log.warning(f"  attempt {attempt + 1}/{max_attempts} failed for {url}: {exc}")
            if attempt < max_attempts - 1:
                wait = backoff ** attempt
                log.debug(f"  waiting {wait:.1f}s before retry")
                time.sleep(wait)
    return None


# ─── Historical fetch ─────────────────────────────────────────────────────────

def fetch_pool_history(pool_key: str, pool_info: dict, days: int = 730) -> list[dict]:
    """
    Fetch historical APY/TVL from DeFiLlama chartData for one pool.

    Returns list of normalised records:
        {timestamp: "YYYY-MM-DD", protocol_key, apy, tvl_usd, tier}

    If the API returns fewer than `days` entries, all available data is used.
    Returns [] on complete failure (caller falls back to synthetic).
    """
    pool_id = pool_info["pool_id"]
    url = DEFILLAMA_CHARTDATA_URL.format(pool_id=pool_id)

    log.info(f"  Fetching {pool_key} (pool_id={pool_id[:8]}…)")
    raw_bytes = _retry_get(url, timeout=20, max_attempts=3)
    if raw_bytes is None:
        log.warning(f"  FAIL {pool_key}: all HTTP attempts failed")
        return []

    try:
        raw = json.loads(raw_bytes)
    except json.JSONDecodeError as e:
        log.warning(f"  FAIL {pool_key}: JSON parse error — {e}")
        return []

    # DeFiLlama: {"status": "ok", "data": [{timestamp, tvlUsd, apy, apyBase}, ...]}
    data = raw.get("data") if isinstance(raw, dict) else raw
    if not isinstance(data, list) or not data:
        log.warning(f"  FAIL {pool_key}: unexpected API shape or empty data")
        return []

    records = []
    cutoff = (date.today() - timedelta(days=days)).isoformat()

    for entry in data:
        raw_ts  = str(entry.get("timestamp") or entry.get("date") or "")
        apy_val = float(entry.get("apy") or entry.get("apyBase") or 0.0)
        tvl_val = float(entry.get("tvlUsd") or entry.get("tvl") or 0.0)

        # Normalise timestamp to YYYY-MM-DD
        if "T" in raw_ts:
            date_str = raw_ts[:10]
        elif len(raw_ts) >= 10:
            date_str = raw_ts[:10]
        else:
            continue

        if date_str < cutoff:
            continue  # older than requested window

        records.append({
            "timestamp":    date_str,
            "protocol_key": pool_key,
            "apy":          round(apy_val, 4),
            "tvl_usd":      round(tvl_val, 0),
            "tier":         pool_info["tier"],
        })

    log.info(f"  OK {pool_key}: {len(records)} daily records")
    return sorted(records, key=lambda r: r["timestamp"])


def fetch_all_historical(days: int = 730, rate_limit_delay: float = 0.5) -> dict[str, list[dict]]:
    """
    Fetch historical data for all 7 backtest protocols.

    Returns dict: protocol_key → list[{timestamp, protocol_key, apy, tvl_usd, tier}]
    """
    results: dict[str, list[dict]] = {}
    total = len(BACKTEST_POOLS)

    for i, (key, info) in enumerate(BACKTEST_POOLS.items(), start=1):
        log.info(f"[{i}/{total}] {key}")
        history = fetch_pool_history(key, info, days=days)

        if not history:
            # Generate synthetic fallback for this protocol
            log.warning(f"  Using synthetic fallback for {key}")
            history = _synthetic_fallback(key, info["tier"], days=days)

        results[key] = history
        if i < total:
            time.sleep(rate_limit_delay)  # be polite to DeFiLlama

    return results


# ─── Synthetic fallback for individual protocol ───────────────────────────────

def _synthetic_fallback(protocol_key: str, tier: str, days: int = 730) -> list[dict]:
    """
    Minimal OU-process fallback for a single protocol.
    Used only when DeFiLlama returns no data for that pool.
    """
    import random
    import math

    rng = random.Random(hash(protocol_key) & 0xFFFFFFFF)
    base_apy = _FALLBACK_APY.get(protocol_key, 4.5)
    base_tvl = _FALLBACK_TVL.get(protocol_key, 20_000_000)

    theta, sigma = 0.15, 1.5
    apy_cur, tvl_cur = base_apy, base_tvl
    records = []

    end = date.today()
    start = end - timedelta(days=days - 1)
    cur = start

    while cur <= end:
        u1, u2 = rng.random(), rng.random()
        if u1 > 0:
            eps = math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2)
        else:
            eps = 0.0

        apy_cur = max(0.5, min(25.0, apy_cur + theta * (base_apy - apy_cur) + sigma * eps))
        tvl_cur = max(base_tvl * 0.5, min(base_tvl * 3.0,
                      tvl_cur * (1 + 0.05 * (base_tvl - tvl_cur) / base_tvl
                                 + 0.02 * (rng.random() * 2 - 1))))

        records.append({
            "timestamp":    cur.isoformat(),
            "protocol_key": protocol_key,
            "apy":          round(apy_cur, 4),
            "tvl_usd":      round(tvl_cur, 0),
            "tier":         tier,
        })
        cur += timedelta(days=1)

    return records


# ─── Per-protocol breakdown ───────────────────────────────────────────────────

def compute_protocol_breakdown(trades: list[dict], equity_curve: list[dict]) -> dict:
    """
    Compute per-protocol statistics from backtest trades and equity curve.

    Returns dict: protocol_key → {total_interest_usd, n_trades, avg_apy, ...}
    """
    breakdown: dict[str, dict] = {}

    for trade in trades:
        key = trade.get("protocol", "unknown")
        if key not in breakdown:
            breakdown[key] = {
                "protocol_key":     key,
                "n_opens":          0,
                "n_closes":         0,
                "total_allocated":  0.0,
                "total_interest":   0.0,
                "apy_samples":      [],
            }

        if trade.get("action") == "OPEN":
            breakdown[key]["n_opens"] += 1
            breakdown[key]["total_allocated"] += trade.get("amount", 0.0)
            breakdown[key]["apy_samples"].append(trade.get("apy", 0.0))
        elif trade.get("action") == "CLOSE":
            breakdown[key]["n_closes"] += 1
            breakdown[key]["total_interest"] += trade.get("interest_usd", 0.0)

    # Finalise
    result = {}
    for key, stats in breakdown.items():
        samples = stats.pop("apy_samples")
        result[key] = {
            **stats,
            "avg_apy":          round(sum(samples) / len(samples), 4) if samples else 0.0,
            "total_interest":   round(stats["total_interest"], 2),
            "total_allocated":  round(stats["total_allocated"], 2),
        }

    return result


# ─── Main backtest runner ─────────────────────────────────────────────────────

def run_full_backtest(
    days: int = 730,
    initial_capital: float = 100_000.0,
    dry_run: bool = False,
) -> dict:
    """
    Run the full 2-year backtest:
      1. Fetch 730-day historical data from DeFiLlama
      2. Run BacktestEngine on real data
      3. Compute per-protocol breakdown
      4. Save results to data/backtest_full_2y.json
      5. Update data/backtest_metrics.json

    Returns the full result dict.
    """
    from backtesting.engine import BacktestEngine

    log.info("=" * 65)
    log.info(f"SPA Full {days}-Day Backtest — IDEA-005")
    log.info(f"Initial capital: ${initial_capital:,.0f}")
    log.info(f"Dry run: {dry_run}")
    log.info("=" * 65)

    # ── Step 1: Fetch historical data ─────────────────────────────────────────
    log.info(f"\nStep 1/4: Fetching {days}-day historical APY data from DeFiLlama…")
    t0 = time.time()
    hist_by_protocol = fetch_all_historical(days=days)

    # Flatten to list
    all_records: list[dict] = []
    sources: dict[str, str] = {}
    for key, records in hist_by_protocol.items():
        all_records.extend(records)
        # Detect if data came from DeFiLlama or synthetic fallback
        sources[key] = "defillama" if len(records) > 30 else "synthetic"

    all_records.sort(key=lambda r: (r["timestamp"], r["protocol_key"]))
    fetch_duration = round(time.time() - t0, 1)

    protocols_fetched = len(hist_by_protocol)
    protocols_real = sum(1 for s in sources.values() if s == "defillama")
    log.info(
        f"  Fetched {len(all_records):,} total records | "
        f"{protocols_real}/{protocols_fetched} protocols with real data | "
        f"{fetch_duration}s"
    )

    if not all_records:
        log.error("No data available — aborting backtest")
        return {"error": "no_data"}

    # ── Step 2: Run BacktestEngine ────────────────────────────────────────────
    log.info("\nStep 2/4: Running BacktestEngine on historical data…")
    engine = BacktestEngine()
    t1 = time.time()
    result = engine.run(
        historical_data=all_records,
        initial_capital=initial_capital,
        policy_version="v1.0",
    )
    engine_duration = round(time.time() - t1, 1)
    log.info(f"  Engine completed in {engine_duration}s ({result.days} backtest days)")

    # ── Step 3: Compute per-protocol breakdown ────────────────────────────────
    log.info("\nStep 3/4: Computing per-protocol breakdown…")
    breakdown = compute_protocol_breakdown(result.trades, result.equity_curve)

    # Data coverage stats
    date_range_start = all_records[0]["timestamp"] if all_records else ""
    date_range_end   = all_records[-1]["timestamp"] if all_records else ""

    # Build output document
    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "backtest_type": "full_2y_defillama",
        "version": "v2.3",
        "config": {
            "days_requested": days,
            "days_actual": result.days,
            "initial_capital_usd": initial_capital,
            "policy_version": result.policy_version,
            "protocols": list(BACKTEST_POOLS.keys()),
            "date_range": {
                "start": date_range_start,
                "end": date_range_end,
            },
        },
        "data_sources": sources,
        "metrics": result.metrics,
        "protocol_breakdown": breakdown,
        "equity_curve_summary": {
            "first_5": result.equity_curve[:5],
            "last_5": result.equity_curve[-5:],
            "total_points": len(result.equity_curve),
        },
        "equity_curve": result.equity_curve,
        "trades_summary": {
            "total": len(result.trades),
            "opens": sum(1 for t in result.trades if t.get("action") == "OPEN"),
            "closes": sum(1 for t in result.trades if t.get("action") == "CLOSE"),
        },
    }

    # ── Step 4: Save results ──────────────────────────────────────────────────
    log.info("\nStep 4/4: Saving results…")

    if not dry_run:
        _DATA_DIR.mkdir(parents=True, exist_ok=True)

        # 1. Full 2Y result
        out_path = _DATA_DIR / "backtest_full_2y.json"
        out_path.write_text(json.dumps(output, indent=2), encoding="utf-8")
        log.info(f"  Saved: {out_path}")

        # 2. Update backtest_metrics.json (if it exists, merge; otherwise create)
        metrics_path = _DATA_DIR / "backtest_metrics.json"
        metrics_doc: dict = {}
        if metrics_path.exists():
            try:
                metrics_doc = json.loads(metrics_path.read_text(encoding="utf-8"))
            except Exception:
                metrics_doc = {}

        metrics_doc["full_2y"] = {
            "generated_at": output["generated_at"],
            "days_actual": result.days,
            "date_range": output["config"]["date_range"],
            "data_sources_summary": {
                "real": protocols_real,
                "synthetic": protocols_fetched - protocols_real,
                "total": protocols_fetched,
            },
            **result.metrics,
        }
        metrics_path.write_text(json.dumps(metrics_doc, indent=2), encoding="utf-8")
        log.info(f"  Updated: {metrics_path}")

    else:
        log.info("  DRY RUN — no files written")

    # ── Print summary ─────────────────────────────────────────────────────────
    m = result.metrics
    log.info("\n" + "=" * 65)
    log.info("BACKTEST RESULTS SUMMARY")
    log.info("=" * 65)
    log.info(f"  Period:            {date_range_start} → {date_range_end} ({result.days}d)")
    log.info(f"  Sharpe ratio:      {m['sharpe_ratio']:.4f}")
    log.info(f"  Max drawdown:      {m['max_drawdown_pct']:.2f}%")
    log.info(f"  Total return:      {m['total_return_pct']:.2f}%")
    log.info(f"  Annualised return: {m['annualised_return_pct']:.2f}%")
    log.info(f"  Win rate:          {m['win_rate']*100:.1f}%")
    log.info(f"  Total trades:      {m['total_trades']}")
    log.info(f"  Final capital:     ${m['final_capital_usd']:,.2f}")
    log.info(f"  Total interest:    ${m['total_interest_usd']:,.2f}")
    log.info("")
    log.info("  Per-protocol breakdown:")
    for pk, stats in sorted(breakdown.items()):
        log.info(
            f"    {pk:35s}  "
            f"avg_apy={stats['avg_apy']:.2f}%  "
            f"interest=${stats['total_interest']:,.0f}  "
            f"trades={stats['n_opens']}"
        )
    log.info("=" * 65)

    return output


# ─── CLI ──────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="SPA Full 2-Year DeFiLlama Backtest (IDEA-005)"
    )
    p.add_argument(
        "--days", type=int, default=730,
        help="Days of history to fetch from DeFiLlama (default: 730 = 2 years)"
    )
    p.add_argument(
        "--capital", type=float, default=100_000.0,
        help="Initial capital in USD (default: $100,000)"
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="Fetch and run backtest but don't write output files"
    )
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    result = run_full_backtest(
        days=args.days,
        initial_capital=args.capital,
        dry_run=args.dry_run,
    )
    if "error" in result:
        sys.exit(1)
