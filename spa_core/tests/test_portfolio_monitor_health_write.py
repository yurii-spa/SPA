"""Test that PortfolioMonitor.save_snapshot writes data/portfolio_health.json."""
import json
import tempfile
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.paper_trading.portfolio_monitor import PortfolioMonitor


def test_save_snapshot_writes_portfolio_health_json():
    with tempfile.TemporaryDirectory() as td:
        monitor = PortfolioMonitor(data_dir=td)
        adapters = {
            "aave_v3": {"apy": 3.1, "tvl": 1e9, "risk_score": 0.20, "tier": "T1"},
            "compound_v3": {"apy": 3.3, "tvl": 5e8, "risk_score": 0.22, "tier": "T1"},
            "cash": {"apy": 0.0, "tvl": 0.0, "risk_score": 0.0, "tier": "T1"},
        }
        current = {"aave_v3": 0.50, "compound_v3": 0.45, "cash": 0.05}
        target = {"aave_v3": 0.50, "compound_v3": 0.45, "cash": 0.05}
        portfolio = {"current_weights": current, "equity": 100_000.0}

        snap = monitor.get_snapshot(portfolio, adapters, target)
        monitor.save_snapshot(snap, data_dir=td)

        health_file = Path(td) / "portfolio_health.json"
        assert health_file.exists(), "portfolio_health.json not written"

        data = json.loads(health_file.read_text())
        assert "health_score" in data
        assert isinstance(data["health_score"], (int, float))
        assert data["health_score"] > 0
        assert "generated_at" in data
        assert "summary_level" in data


def test_health_score_readable_by_agent_monitor():
    with tempfile.TemporaryDirectory() as td:
        monitor = PortfolioMonitor(data_dir=td)
        adapters = {
            "aave_v3": {"apy": 5.0, "tvl": 1e9, "risk_score": 0.15, "tier": "T1"},
            "compound_v3": {"apy": 4.0, "tvl": 8e8, "risk_score": 0.18, "tier": "T1"},
            "cash": {"apy": 0.0, "tvl": 0.0, "risk_score": 0.0, "tier": "T1"},
        }
        current = {"aave_v3": 0.55, "compound_v3": 0.40, "cash": 0.05}
        target = current.copy()
        portfolio = {"current_weights": current, "equity": 100_000.0}

        snap = monitor.get_snapshot(portfolio, adapters, target)
        monitor.save_snapshot(snap, data_dir=td)

        ph = json.loads((Path(td) / "portfolio_health.json").read_text())
        score = ph.get("health_score", ph.get("score"))
        assert isinstance(score, (int, float))
        assert 0 <= score <= 100


if __name__ == "__main__":
    test_save_snapshot_writes_portfolio_health_json()
    test_health_score_readable_by_agent_monitor()
    print("All tests passed.")
