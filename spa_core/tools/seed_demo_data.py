"""
Demo Data Seeder for SPA Dashboard

Generates 7 days of realistic synthetic paper trading data so the dashboard
is populated when first deployed. Run once after setup:

    python -m spa_core.tools.seed_demo_data

All generated data is clearly marked as DEMO and will be overwritten
by the first real GitHub Actions run.
"""

from __future__ import annotations

import argparse
import json
import math
import random
from datetime import datetime, timezone, timedelta
from pathlib import Path


# ─── Demo positions whitelist ────────────────────────────────────────────────

DEMO_POSITIONS = [
    {
        "name": "Aave V3 USDC",
        "protocol": "aave-v3",
        "tier": "T1",
        "apy": 5.23,
        "allocation_usd": 30000,
        "allocation_pct": 30.0,
    },
    {
        "name": "Compound V3 USDT",
        "protocol": "compound-v3",
        "tier": "T1",
        "apy": 4.87,
        "allocation_usd": 25000,
        "allocation_pct": 25.0,
    },
    {
        "name": "Morpho USDC",
        "protocol": "morpho",
        "tier": "T1",
        "apy": 5.61,
        "allocation_usd": 15000,
        "allocation_pct": 15.0,
    },
    {
        "name": "Yearn V3 USDC",
        "protocol": "yearn-v3",
        "tier": "T2",
        "apy": 6.42,
        "allocation_usd": 10000,
        "allocation_pct": 10.0,
    },
    {
        "name": "Pendle PT stETH",
        "protocol": "pendle",
        "tier": "T2",
        "apy": 8.15,
        "allocation_usd": 5000,
        "allocation_pct": 5.0,
    },
]


# ─── OU process helper ────────────────────────────────────────────────────────

def _ou_walk(
    n: int,
    mu: float = 0.0002,
    theta: float = 0.3,
    sigma: float = 0.001,
    x0: float = 0.0002,
    rng: random.Random = None,
) -> list[float]:
    """
    Ornstein-Uhlenbeck mean-reverting random walk.

    x(t+1) = x(t) + theta*(mu - x(t)) + sigma*N(0,1)

    Generates `n` daily return values centered around `mu`
    (≈ 7.3% APY → 0.02% daily).
    """
    if rng is None:
        rng = random.Random(42)
    x = x0
    out = []
    for _ in range(n):
        noise = rng.gauss(0.0, 1.0)
        x = x + theta * (mu - x) + sigma * noise
        out.append(x)
    return out


# ─── Individual file builders ─────────────────────────────────────────────────

def _build_status(capital: float, now: datetime) -> dict:
    deployed = round(capital * 0.85, 2)
    cash = round(capital - deployed, 2)
    # 7 days at ~7.3% APY → ≈ 0.14% total → $847 on $100K
    total_pnl = round(capital * 0.007 * (7 / 365), 2)

    positions = []
    for pos in DEMO_POSITIONS:
        days = 7
        pnl = round(pos["allocation_usd"] * (pos["apy"] / 100) * (days / 365), 4)
        positions.append({
            "protocol_key": pos["protocol"],
            "tier": pos["tier"],
            "amount_usd": pos["allocation_usd"],
            "current_apy": pos["apy"],
            "unrealized_pnl_usd": pnl,
            "unrealized_pnl_pct": round(pnl / pos["allocation_usd"], 6),
            "days_held": float(days),
        })

    return {
        "timestamp": now.isoformat(),
        "portfolio": {
            "total_capital_usd": capital,
            "deployed_usd": deployed,
            "cash_usd": cash,
            "cash_pct": round(cash / capital, 4),
            "total_pnl_usd": total_pnl,
            "total_drawdown_pct": 0.0,
        },
        "positions": positions,
        "risk": {
            "health_approved": True,
            "violations": [],
            "warnings": [],
            "var_usd": round(capital * 0.005, 2),
            "var_pct": 0.5,
            "var_breach": False,
        },
        "paper_trading": {
            "days_elapsed": 7,
            "weeks_elapsed": 1.0,
            "min_weeks_required": 8,
            "go_live_ready": False,
            "first_trade": (now - timedelta(days=7)).isoformat(),
        },
        "strategy": {
            "strategy_id": "paper-v1",
            "total_capital_usd": capital,
            "deployed_capital_usd": deployed,
            "cash_usd": cash,
            "total_pnl_usd": total_pnl,
            "max_drawdown_pct": 0.0,
            "sharpe_to_date": 1.42,
            "trade_count": len(DEMO_POSITIONS),
        },
        "is_demo": True,
    }


def _build_pnl_history(
    days: int,
    capital: float,
    now: datetime,
    runs_per_day: int = 6,
) -> list[dict]:
    """
    Build PnL history using an OU random walk.
    Total entries = days × runs_per_day.
    """
    rng = random.Random(42)
    n_total = days * runs_per_day
    # Daily mu ≈ 7.3% / 365 ≈ 0.0002; per-run mu = daily / runs_per_day
    mu_run = 0.0002 / runs_per_day
    returns = _ou_walk(n_total, mu=mu_run, theta=0.3, sigma=0.001, x0=mu_run, rng=rng)

    interval_hours = 24 // runs_per_day  # 4 hours
    start_ts = now - timedelta(days=days)

    history = []
    portfolio_value = capital
    cumulative_pnl = 0.0

    for i, ret in enumerate(returns):
        ts = start_ts + timedelta(hours=i * interval_hours)
        portfolio_value = portfolio_value * (1 + ret)
        cumulative_pnl = portfolio_value - capital
        history.append({
            "timestamp": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "total_capital_usd": round(portfolio_value, 2),
            "deployed_capital_usd": round(portfolio_value * 0.85, 2),
            "cash_usd": round(portfolio_value * 0.15, 2),
            "total_pnl_usd": round(cumulative_pnl, 2),
            "total_pnl_pct": round(cumulative_pnl / capital * 100, 6),
            "daily_return_pct": round(ret * 100, 6),
            "current_apy": round((math.pow(1 + ret, 365 * runs_per_day) - 1) * 100, 4),
            "trade_count": len(DEMO_POSITIONS),
            "is_demo": True,
        })

    return history


def _build_protocols(now: datetime) -> list[dict]:
    """Active positions with realistic APY data."""
    out = []
    for pos in DEMO_POSITIONS:
        out.append({
            "key": pos["protocol"],
            "protocol": pos["protocol"],
            "asset": "USDC" if "usdc" in pos["name"].lower() or "steth" in pos["name"].lower() else "USDT",
            "chain": "ethereum",
            "tier": pos["tier"],
            "is_active": 1,
            "apy_total": pos["apy"],
            "apy_base": round(pos["apy"] * 0.85, 4),
            "apy_reward": round(pos["apy"] * 0.15, 4),
            "tvl_usd": 150_000_000.0,
            "last_snapshot": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "allocation_usd": pos["allocation_usd"],
            "allocation_pct": pos["allocation_pct"],
            "name": pos["name"],
            "is_demo": True,
        })
    return out


def _build_risk_alerts(now: datetime) -> dict:
    return {
        "generated_at": now.isoformat(),
        "count": 0,
        "status": "ok",
        "alerts": [],
        "last_check": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "is_demo": True,
    }


def _build_golive_readiness(days: int, now: datetime) -> dict:
    paper_start = now - timedelta(days=days)
    days_remaining = max(0, 56 - days)
    return {
        "generated_at": now.isoformat(),
        "verdict": f"PENDING — {days}/56 days complete",
        "verdict_emoji": "⏳",
        "criteria_passed": 3,
        "criteria_total": 11,
        "days_remaining": days_remaining,
        "paper_start_date": paper_start.date().isoformat(),
        "criteria": {
            "paper_duration": {
                "status": "PENDING",
                "note": f"Need 14+ days — currently {days}d",
            },
            "total_return": {
                "status": "PENDING",
                "note": "Need 30+ days of data",
            },
            "sharpe_ratio": {
                "status": "PENDING",
                "note": "Insufficient data for Sharpe calculation",
            },
            "max_drawdown": {
                "status": "PASS",
                "note": "Within -5% limit so far",
            },
            "concentration": {
                "status": "PASS",
                "note": "All positions within T1 40% / T2 20% limits",
            },
            "whitelist_only": {
                "status": "PASS",
                "note": "All protocols in approved whitelist",
            },
            "risk_policy": {
                "status": "PASS",
                "note": "RiskPolicy v1.0 active — no violations",
            },
            "strategy_tournament": {
                "status": "PENDING",
                "note": "Need more data for tournament evaluation",
            },
            "sky_monitor": {
                "status": "PENDING",
                "note": "SKY/sUSDS GSM Pause Delay not yet confirmed",
            },
            "apy_gap": {
                "status": "PENDING",
                "note": "APY gap analysis needs 30+ days",
            },
            "tournament_winner": {
                "status": "PENDING",
                "note": "Awaiting strategy tournament winner",
            },
        },
        "blocking_criteria": [
            "paper_duration",
            "total_return",
            "sharpe_ratio",
            "strategy_tournament",
            "sky_monitor",
            "apy_gap",
            "tournament_winner",
        ],
        "next_check_date": (now + timedelta(days=1)).date().isoformat(),
        "is_demo": True,
    }


def _build_pipeline_health(now: datetime) -> dict:
    return {
        "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sections_run": 20,
        "sections_ok": 20,
        "sections_failed": 0,
        "failed_sections": [],
        "total_pools_fetched": 12,
        "pendle_pools_found": 3,
        "export_duration_seconds": 3.8,
        "next_run_eta": "4h",
        "is_demo": True,
    }


def _build_meta(days: int, capital: float, now: datetime) -> dict:
    paper_start = now - timedelta(days=days)
    return {
        "updated_at": now.isoformat(),
        "paper_trading_day": days,
        "paper_start_date": paper_start.date().isoformat(),
        "go_live_target": "2026-07-15",
        "capital_usd": capital,
        "target_apy": 7.3,
        "version": "1.6",
        "source": "demo_seeder",
        "is_demo": True,
    }


# ─── Main seeder ──────────────────────────────────────────────────────────────

def seed_demo_data(
    days: int = 7,
    capital: float = 100_000.0,
    output_dir: str = "data",
) -> None:
    """
    Generate all demo JSON files in `output_dir`.

    Args:
        days:        Days of history to generate (default 7).
        capital:     Starting capital in USD (default 100000).
        output_dir:  Directory to write files into (default "data").
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    # Ensure .gitkeep exists so the data/ dir is tracked by git even when empty
    gitkeep = out / ".gitkeep"
    if not gitkeep.exists():
        gitkeep.write_text("")
        print(f"  ✓  {gitkeep}  (created)")

    now = datetime.now(timezone.utc)

    files = {
        "status.json":           _build_status(capital, now),
        "pnl_history.json":      _build_pnl_history(days, capital, now),
        "protocols.json":        _build_protocols(now),
        "risk_alerts.json":      _build_risk_alerts(now),
        "golive_readiness.json": _build_golive_readiness(days, now),
        "pipeline_health.json":  _build_pipeline_health(now),
        "meta.json":             _build_meta(days, capital, now),
    }

    for filename, data in files.items():
        path = out / filename
        path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
        size = path.stat().st_size
        entries = (
            len(data) if isinstance(data, list) else
            len(data.get("criteria", data.get("alerts", [])))
            if isinstance(data, dict) and ("criteria" in data or "alerts" in data)
            else ""
        )
        entry_str = f"  ({entries} entries)" if entries != "" else ""
        print(f"  ✓  {path}  ({size:,} bytes){entry_str}")

    print(
        f"\n✅  Demo data seeded: {len(files)} files written to {out.resolve()}\n"
        f"   {days} days of history | capital=${capital:,.0f} | "
        f"{days * 6} PnL data points\n"
        f"   All files marked is_demo=true — will be overwritten by first "
        f"real GitHub Actions run."
    )


# ─── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Seed SPA demo data")
    p.add_argument("--days", type=int, default=7, help="Days of history to generate")
    p.add_argument("--capital", type=float, default=100000, help="Starting capital")
    p.add_argument("--output-dir", default="data", help="Output directory")
    args = p.parse_args()
    seed_demo_data(days=args.days, capital=args.capital, output_dir=args.output_dir)
