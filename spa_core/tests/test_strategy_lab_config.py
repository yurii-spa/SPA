"""Tests for spa_core.strategy_lab.config — SSOT loader, validation, risk-limit sourcing.

Hermetic: writes a temp config and points the loader at it; verifies risk limits come from
spa_core.risk.policy (not duplicated).
"""
# LLM_FORBIDDEN
import json
import os
import tempfile

import pytest

from spa_core.strategy_lab import config as cfg
from spa_core.risk.policy import RiskConfig


def _write(tmpdir, data):
    p = os.path.join(tmpdir, "strategy_lab_config.json")
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    return p


VALID = {
    "global": {
        "initial_capital": 100000,
        "window_start": "2026-06-10",
        "window_end": "2026-07-10",
        "seed": 42,
        "gas_usd_per_rebalance": 8.0,
        "slippage_bps": 5.0,
        "rebalance_bps": 2.0,
        "funding_settles_per_day": 3,
        "rwa_floor_apy_pct": 4.5,
    },
    "strategies": {
        "variant_n": {
            "lrt_symbol": "eeth",
            "hedge_ratio": 1.0,
            "funding_kill_threshold": -0.0003,
            "funding_kill_hours": 24,
            "lrt_depeg_kill_pct": 2.0,
            "points_apy_assumption": 0.03,
        },
        "variant_d": {"lrt_symbol": "eeth", "drawdown_kill_pct": 25.0},
        "engine_a": {"capital_usd": 100000},
        "engine_b": {"capital_usd": 20000},
        "engine_c": {"capital_usd": 10000},
        "rwa_floor": {"capital_usd": 100000, "apy_pct": 4.5},
    },
}


def test_shipped_config_loads_and_validates():
    """The real data/strategy_lab_config.json loads and passes validation."""
    c = cfg.load_config(force_reload=True)
    assert c["global"]["initial_capital"] == 100000
    assert c["global"]["seed"] == 42
    g = cfg.global_config()
    assert g["window_start"] == "2026-06-10"
    assert cfg.rwa_floor_apy_pct() == 4.5


def test_strategy_config_blocks():
    with tempfile.TemporaryDirectory() as d:
        p = _write(d, VALID)
        n = cfg.strategy_config("variant_n", path=p)
        assert n["lrt_symbol"] == "eeth"
        assert n["funding_kill_threshold"] == -0.0003
        assert n["funding_kill_hours"] == 24
        assert n["lrt_depeg_kill_pct"] == 2.0
        d_block = cfg.strategy_config("variant_d", path=p)
        assert d_block["drawdown_kill_pct"] == 25.0
        # capital splits reference the real sleeves
        assert cfg.strategy_config("engine_a", path=p)["capital_usd"] == 100000
        assert cfg.strategy_config("engine_b", path=p)["capital_usd"] == 20000
        assert cfg.strategy_config("engine_c", path=p)["capital_usd"] == 10000


def test_unknown_strategy_raises():
    with tempfile.TemporaryDirectory() as d:
        p = _write(d, VALID)
        with pytest.raises(cfg.ConfigError):
            cfg.strategy_config("does_not_exist", path=p)


def test_missing_global_key_raises():
    bad = json.loads(json.dumps(VALID))
    del bad["global"]["seed"]
    with tempfile.TemporaryDirectory() as d:
        p = _write(d, bad)
        with pytest.raises(cfg.ConfigError):
            cfg.load_config(path=p)


def test_missing_strategy_threshold_raises():
    bad = json.loads(json.dumps(VALID))
    del bad["strategies"]["variant_n"]["funding_kill_threshold"]
    with tempfile.TemporaryDirectory() as d:
        p = _write(d, bad)
        with pytest.raises(cfg.ConfigError):
            cfg.load_config(path=p)


def test_missing_strategy_block_raises():
    bad = json.loads(json.dumps(VALID))
    del bad["strategies"]["variant_d"]
    with tempfile.TemporaryDirectory() as d:
        p = _write(d, bad)
        with pytest.raises(cfg.ConfigError):
            cfg.load_config(path=p)


def test_missing_file_raises():
    with pytest.raises(cfg.ConfigError):
        cfg.load_config(path="/nonexistent/path/strategy_lab_config.json")


def test_malformed_json_raises():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "strategy_lab_config.json")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write("{not valid json")
        with pytest.raises(cfg.ConfigError):
            cfg.load_config(path=p)


def test_risk_limits_sourced_from_policy_not_duplicated():
    """risk_limits() must return the SAME values as RiskConfig — proving no duplication."""
    rc = RiskConfig()
    limits = cfg.risk_limits()
    assert limits["tvl_floor_usd"] == rc.min_tvl_usd
    assert limits["max_concentration_t1"] == rc.max_concentration_t1
    assert limits["max_concentration_t2"] == rc.max_concentration_t2
    assert limits["max_total_t2"] == rc.max_total_t2_allocation
    assert limits["max_drawdown_stop"] == rc.max_drawdown_stop
    assert limits["min_cash_pct"] == rc.min_cash_pct
    assert limits["max_apy_pct"] == rc.max_apy_for_new_position
    assert limits["min_apy_pct"] == rc.min_apy_for_new_position


def test_risk_limits_not_hardcoded_in_config_module():
    """The config source must NOT redeclare risk caps — assert it imports RiskConfig instead."""
    import inspect
    src = inspect.getsource(cfg)
    assert "from spa_core.risk.policy import RiskConfig" in src
    # No literal risk thresholds redefined in the lab config module.
    assert "max_concentration_t1 =" not in src
    assert "max_drawdown_stop =" not in src
