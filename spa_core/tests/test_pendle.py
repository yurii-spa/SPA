"""
Unit tests for Pendle PT integration — SPA APY gap closure.

Tests cover:
  1–3.  PendlePosition accrual math (day 0, day 7, day 30)
  4–6.  pendle_allocation_size() with various APY inputs
  7–9.  PendleFetcher.filter_pools() with mock DeFiLlama data
  10.   auto_allocate() produces OPEN_PENDLE_PT action with valid pool
  11.   T2 allocation limit enforced (RiskPolicy blocks over-limit Pendle)
  12.   apy_gap_report() returns correct structure and values

Run:
    cd spa_core
    python -m pytest tests/test_pendle.py -v
"""

from __future__ import annotations

import sys
import datetime
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import tempfile

from paper_trading.pendle_strategy import (
    PendlePosition,
    pendle_allocation_size,
    build_pendle_position,
)
from data_pipeline.pendle_fetcher import PendleFetcher
from data_pipeline.apy_gap_report import apy_gap_report, TARGET_APY
from database.init_db import init_database
from paper_trading.engine import PaperTrader
from risk.policy import RiskConfig


# ─── Fixtures ────────────────────────────────────────────────────────────────

SAMPLE_POOL = {
    "pool_id":          "abc123",
    "protocol":         "Pendle PT",
    "symbol":           "PT-USDC-26DEC2026",
    "chain":            "arbitrum",
    "tier":             "T2",
    "apy":              7.5,
    "tvl_usd":          25_000_000.0,
    "asset":            "PT-STABLE",
    "special":          "fixed_rate",
    "underlying_symbol": "pt-usdc-26dec2026",
    "project":          "pendle-v2",
    "maturity_date":    "2026-12-26",
    "days_to_maturity": 218,
}


def make_trader(config: RiskConfig = None):
    """Create a PaperTrader backed by an isolated temp SQLite DB."""
    tmp = tempfile.mktemp(suffix=".db")
    db_path = Path(tmp)
    init_database(db_path=db_path)
    trader = PaperTrader(db_path=db_path, config=config)
    return trader, db_path


def _insert_fresh_apy(db_path: Path, protocol_key: str = "aave-v3-usdc-ethereum",
                       apy: float = 4.65, tvl: float = 138_000_000.0) -> None:
    """Insert a fresh APY snapshot so auto_allocate() doesn't early-exit.

    All NOT NULL columns required by the schema are included.
    """
    from database.init_db import get_connection
    with get_connection(db_path) as conn:
        conn.execute("""
            INSERT INTO apy_snapshots
                (protocol_key, protocol, asset, chain, tier,
                 apy_total, apy_base, apy_reward, tvl_usd,
                 timestamp, is_valid)
            VALUES (?, 'Aave V3', 'USDC', 'Ethereum', 'T1',
                    ?, 0, 0, ?, datetime('now'), 1)
        """, (protocol_key, apy, tvl))
        conn.commit()


# ─── Test 1: PendlePosition accrual at day 0 ─────────────────────────────────

def test_pendle_position_accrual_day0():
    """Newly opened position has 0 days held and 0 accrued return."""
    today = datetime.date.today().isoformat()
    pos = PendlePosition(
        pool_id="test-pool",
        symbol="PT-USDC-26DEC2026",
        chain="arbitrum",
        amount_usd=10_000.0,
        entry_apy=7.5,
        entry_date=today,
        maturity_date="2026-12-26",
        days_to_maturity=218,
    )
    assert pos.days_held == 0
    assert pos.accrued_return_usd == 0.0
    assert pos.current_value_usd == 10_000.0


# ─── Test 2: PendlePosition accrual at day 7 ─────────────────────────────────

def test_pendle_position_accrual_day7():
    """Position held for 7 days accrues 7 days of simple interest."""
    entry = (datetime.date.today() - datetime.timedelta(days=7)).isoformat()
    pos = PendlePosition(
        pool_id="test-pool",
        symbol="PT-USDC-26DEC2026",
        chain="arbitrum",
        amount_usd=10_000.0,
        entry_apy=7.5,
        entry_date=entry,
        maturity_date="2026-12-26",
        days_to_maturity=218,
    )
    expected_accrual = 10_000.0 * (7.5 / 100 / 365) * 7
    assert pos.days_held == 7
    assert abs(pos.accrued_return_usd - expected_accrual) < 0.001
    assert pos.current_value_usd > 10_000.0


# ─── Test 3: PendlePosition accrual at day 30 ────────────────────────────────

def test_pendle_position_accrual_day30():
    """Position held 30 days accrues ~0.616% on a 7.5% APY position."""
    entry = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()
    pos = PendlePosition(
        pool_id="test-pool",
        symbol="PT-USDC-26DEC2026",
        chain="arbitrum",
        amount_usd=20_000.0,
        entry_apy=7.5,
        entry_date=entry,
        maturity_date="2026-12-26",
        days_to_maturity=218,
    )
    expected_accrual = 20_000.0 * (7.5 / 100 / 365) * 30
    assert pos.days_held == 30
    assert abs(pos.accrued_return_usd - expected_accrual) < 0.01
    # Sanity: ~$123 accrued on $20K at 7.5% for 30 days
    assert 100.0 < pos.accrued_return_usd < 150.0


# ─── Test 4: pendle_allocation_size — below min premium → 0 ─────────────────

def test_pendle_allocation_size_below_min_premium():
    """APY 5% with T1 baseline 4% = 1% premium < 2% min → returns 0."""
    result = pendle_allocation_size(
        capital=100_000.0,
        current_apy=5.0,
        t1_baseline_apy=4.0,
        max_t2_pct=0.20,
        min_premium=2.0,
    )
    assert result == 0.0


# ─── Test 5: pendle_allocation_size — at min premium → 50% of cap ───────────

def test_pendle_allocation_size_at_min_premium():
    """APY 6% with T1 baseline 4% = 2% premium exactly = 50% of 20% cap = $10K."""
    result = pendle_allocation_size(
        capital=100_000.0,
        current_apy=6.0,
        t1_baseline_apy=4.0,
        max_t2_pct=0.20,
        min_premium=2.0,
    )
    assert result == 10_000.0


# ─── Test 6: pendle_allocation_size — above 2× min premium → full cap ────────

def test_pendle_allocation_size_at_full_cap():
    """APY 8% with T1 baseline 4% = 4% premium = 2× min → full 20% cap = $20K."""
    result = pendle_allocation_size(
        capital=100_000.0,
        current_apy=8.0,
        t1_baseline_apy=4.0,
        max_t2_pct=0.20,
        min_premium=2.0,
    )
    assert result == 20_000.0


# ─── Test 7: filter_pools — passes valid Pendle PT pool ─────────────────────

def test_filter_pools_passes_valid_pool():
    """A valid pendle-v2 PT-USDC pool with good APY/TVL passes the filter."""
    fetcher = PendleFetcher()
    # Maturity ~120 days from today (within 14–180 day window)
    maturity = (datetime.date.today() + datetime.timedelta(days=120)).strftime("%d%b%Y").upper()
    symbol = f"PT-USDC-{maturity}"
    raw = [{
        "project": "pendle-v2",
        "symbol":  symbol,
        "apy":     7.5,
        "tvlUsd":  25_000_000.0,
        "chain":   "Arbitrum",
        "pool":    "mock-pool-id",
    }]
    result = fetcher.filter_pools(raw)
    assert len(result) == 1
    assert result[0]["apy"] == 7.5
    assert result[0]["tier"] == "T2"
    assert result[0]["special"] == "fixed_rate"


# ─── Test 8: filter_pools — rejects non-Pendle projects ─────────────────────

def test_filter_pools_rejects_non_pendle():
    """Pools not from pendle-v2 are excluded regardless of other criteria."""
    fetcher = PendleFetcher()
    raw = [{
        "project": "aave-v3",
        "symbol":  "USDC",
        "apy":     8.0,
        "tvlUsd":  50_000_000.0,
        "chain":   "Ethereum",
        "pool":    "mock-pool-id",
    }]
    result = fetcher.filter_pools(raw)
    assert result == []


# ─── Test 9: filter_pools — rejects low APY and small TVL ───────────────────

def test_filter_pools_rejects_low_apy_and_tvl():
    """Pools below min APY (6%) or min TVL ($5M) are filtered out."""
    fetcher = PendleFetcher()
    maturity = (datetime.date.today() + datetime.timedelta(days=90)).strftime("%d%b%Y").upper()
    raw = [
        # Below min APY
        {
            "project": "pendle-v2",
            "symbol":  f"PT-USDC-{maturity}",
            "apy":     5.0,
            "tvlUsd":  20_000_000.0,
            "chain":   "Arbitrum",
            "pool":    "low-apy",
        },
        # Below min TVL
        {
            "project": "pendle-v2",
            "symbol":  f"PT-USDT-{maturity}",
            "apy":     8.0,
            "tvlUsd":  1_000_000.0,
            "chain":   "Ethereum",
            "pool":    "low-tvl",
        },
    ]
    result = fetcher.filter_pools(raw)
    assert result == []


# ─── Test 10: auto_allocate produces OPEN_PENDLE_PT action ──────────────────

def test_auto_allocate_produces_open_pendle_pt():
    """
    When PendleFetcher.get_best_pt() returns a valid pool and cash is available,
    auto_allocate() must include an OPEN_PENDLE_PT action in its output.
    """
    trader, db_path = make_trader()
    # Insert at least one fresh APY snapshot so auto_allocate doesn't early-exit
    _insert_fresh_apy(db_path, "aave-v3-usdc-ethereum", apy=4.65)

    # Patch at source so the lazy import inside auto_allocate() is intercepted
    with patch("data_pipeline.pendle_fetcher.PendleFetcher") as MockFetcher:
        mock_instance = MockFetcher.return_value
        mock_instance.get_best_pt.return_value = dict(SAMPLE_POOL)
        actions = trader.auto_allocate()

    pendle_actions = [a for a in actions if a.get("action") == "OPEN_PENDLE_PT"]
    assert len(pendle_actions) >= 1, (
        f"Expected at least one OPEN_PENDLE_PT action; got: "
        f"{[(a['action'], a.get('reason','')) for a in actions]}"
    )
    pa = pendle_actions[0]
    assert pa["tier"] == "T2"
    assert pa["special"] == "fixed_rate"
    assert pa["apy"] == 7.5
    assert pa["amount_usd"] > 0
    assert pa["approved"] is True


# ─── Test 11: T2 limit blocks oversized Pendle allocation ────────────────────

def test_pendle_blocked_when_t2_limit_exhausted():
    """
    When T2 allocation is already at/near the policy limit, the RiskPolicy check
    should block the Pendle allocation (action == 'BLOCKED' or no OPEN_PENDLE_PT).
    """
    from database.init_db import get_connection
    # Use a tight T2 limit (10%) so any Pendle allocation is blocked
    config = RiskConfig(max_total_t2_allocation=0.10, max_concentration_t2=0.10)
    trader, db_path = make_trader(config=config)
    _insert_fresh_apy(db_path, "aave-v3-usdc-ethereum", apy=4.65)

    # Pre-fill 10% T2 already deployed (equal to the T2 cap)
    with get_connection(db_path) as conn:
        conn.execute("""
            INSERT INTO paper_trades
                (trade_id, strategy_id, timestamp_open, protocol_key, asset, action,
                 amount_usd, apy_at_open, net_apy_annualized, risk_check_passed)
            VALUES ('T2-FULL', 'paper-v1',
                    datetime('now', 'utc') || '+00:00',
                    'maple-usdc-ethereum',
                    'USDC', 'OPEN', 10000.0, 5.0, 5.0, 1)
        """)
        conn.commit()

    # Pendle pool with very large proposed size that would breach T2 cap
    big_pool = dict(SAMPLE_POOL, tvl_usd=50_000_000.0)

    with patch("data_pipeline.pendle_fetcher.PendleFetcher") as MockFetcher:
        mock_instance = MockFetcher.return_value
        mock_instance.get_best_pt.return_value = big_pool
        actions = trader.auto_allocate()

    # Either no OPEN_PENDLE_PT, or a BLOCKED action — NOT an approved open
    pendle_opens = [a for a in actions if a.get("action") == "OPEN_PENDLE_PT"]
    pendle_blocked = [a for a in actions if a.get("action") == "BLOCKED" and "pendle" in str(a.get("protocol", "")).lower()]

    # If any OPEN_PENDLE_PT exists, its size must be 0 or negligible (< $100 → shouldn't happen)
    # Primary assertion: T2 limit prevents a full allocation
    for pa in pendle_opens:
        assert pa.get("amount_usd", 0) < 100.0, (
            f"Pendle should be blocked but got ${pa['amount_usd']:.0f} allocation"
        )


# ─── Test 12: apy_gap_report — structure and values ─────────────────────────

def test_apy_gap_report_structure_and_values():
    """apy_gap_report() returns all required keys and correct gap calculation."""
    portfolio_status = {
        "portfolio": {
            "total_capital_usd": 100_000.0,
            "cash_usd": 5_000.0,
        },
        "positions": [
            {
                "protocol_key": "aave-v3-usdc-ethereum",
                "tier":         "T1",
                "amount_usd":   60_000.0,
                "current_apy":  4.65,
            },
            {
                "protocol_key": "compound-v3-usdc-ethereum",
                "tier":         "T1",
                "amount_usd":   35_000.0,
                "current_apy":  3.90,
            },
        ],
    }
    report = apy_gap_report(portfolio_status)

    # Required keys present
    required_keys = {
        "current_weighted_apy", "target_apy", "gap",
        "gap_closeable_by_pendle", "gap_closeable_by_sky",
        "on_track", "summary",
    }
    assert required_keys.issubset(report.keys()), (
        f"Missing keys: {required_keys - report.keys()}"
    )

    # Target APY is always 7.3
    assert report["target_apy"] == TARGET_APY

    # Weighted APY: (60K × 4.65 + 35K × 3.90) / 100K = 4.155%
    expected_apy = (60_000.0 * 4.65 + 35_000.0 * 3.90) / 100_000.0
    assert abs(report["current_weighted_apy"] - expected_apy) < 0.01

    # Gap = target - current (positive since current < 7.3)
    assert report["gap"] > 0
    assert abs(report["gap"] - (TARGET_APY - expected_apy)) < 0.01

    # Not on track (current << 7.3)
    assert report["on_track"] is False

    # Pendle contribution positive (there's T2 headroom)
    assert report["gap_closeable_by_pendle"] > 0

    # Sky contribution positive (always estimated, PENDING whitelist)
    assert report["gap_closeable_by_sky"] > 0

    # Summary is a non-empty string
    assert isinstance(report["summary"], str) and len(report["summary"]) > 10


# ─── Test 13 (bonus): build_pendle_position round-trip ──────────────────────

def test_build_pendle_position_round_trip():
    """build_pendle_position() correctly maps pool fields onto PendlePosition."""
    pos = build_pendle_position(SAMPLE_POOL, amount_usd=15_000.0)
    assert pos.pool_id == "abc123"
    assert pos.symbol == "PT-USDC-26DEC2026"
    assert pos.chain == "arbitrum"
    assert pos.amount_usd == 15_000.0
    assert pos.entry_apy == 7.5
    assert pos.maturity_date == "2026-12-26"
    assert pos.days_to_maturity == 218
    d = pos.to_dict()
    assert d["tier"] == "T2"
    assert d["special"] == "fixed_rate"
    assert d["protocol"] == "Pendle PT"
