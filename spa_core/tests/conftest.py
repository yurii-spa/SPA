"""Shared pytest fixtures for SPA tests."""
import pytest
import os
import json


@pytest.fixture
def sample_portfolio():
    return {
        "total_capital_usd": 100000.0,
        "total_pnl_usd": 138.0,
        "total_pnl_pct": 0.138,
        "current_apy": 4.35,
        "cash_usd": 5000.0,
        "total_drawdown_pct": 0.0,
    }


@pytest.fixture
def sample_positions():
    return [
        {
            "protocol_key": "aave-v3-usdc-ethereum",
            "protocol": "Aave V3 USDC",
            "tier": "T1",
            "amount_usd": 40000,
            "current_apy": 4.23,
            "unrealized_pnl_usd": 4.63,
        },
        {
            "protocol_key": "compound-v3-usdc-ethereum",
            "protocol": "Compound",
            "tier": "T1",
            "amount_usd": 35000,
            "current_apy": 4.02,
            "unrealized_pnl_usd": 3.88,
        },
        {
            "protocol_key": "maple-usdc-ethereum",
            "protocol": "Maple Finance",
            "tier": "T2",
            "amount_usd": 20000,
            "current_apy": 4.80,
            "unrealized_pnl_usd": 2.63,
        },
    ]


@pytest.fixture
def temp_data_dir(tmp_path, sample_portfolio, sample_positions):
    """Creates a temp directory with minimal valid JSON data files."""
    data = {
        "portfolio.json": sample_portfolio,
        "positions.json": sample_positions,
        "risk_alerts.json": {
            "count": 0,
            "status": "OK",
            "alerts": [],
            "generated_at": "2026-05-21T16:00:00Z",
        },
        "backtest_results.json": {
            "metrics": {
                "sharpe_ratio": 24.76,
                "max_drawdown_pct": 0.0,
                "total_return_pct": 1.38,
            },
            "equity_curve": [],
            "generated_at": "2026-05-21T16:00:00Z",
        },
        "status.json": {
            "portfolio": sample_portfolio,
            "positions": sample_positions,
            "timestamp": "2026-05-21T16:00:00Z",
        },
    }
    for filename, content in data.items():
        (tmp_path / filename).write_text(json.dumps(content))
    return str(tmp_path)
