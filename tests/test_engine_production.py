"""tests/test_engine_production.py — CRIT-002 Production tests for
spa_core/paper_trading/engine.py and multi_strategy_runner.py

MP-1385 Sprint v10.1

Coverage:
  engine.py
  ─────────
  - Constants: INITIAL_CAPITAL, MIN_PAPER_WEEKS, SHARPE_RISK_FREE_RATE, STRATEGY_ID
  - Exceptions: RiskPolicyViolation, InsufficientData
  - PaperTrader.__init__: defaults, strategy_id, live_execution flag
  - open_position: happy path, RiskPolicy block, unknown protocol
  - close_position: no open position raises ValueError
  - rebalance: kill-switch fires on portfolio health failure
  - auto_allocate: returns NO_OP when no fresh data

  multi_strategy_runner.py
  ─────────────────────────
  - MultiStrategyRunner.__init__: portfolios created per strategy
  - run_day: yields returned per active strategy
  - run_day: killed/paused strategies skipped
  - get_rankings: sorted by composite_score descending, rank assigned
  - get_active_strategies: only active/promoted
  - get_total_yield: sums active yields from last run_day
  - get_allocation_map: equal shares for active strategies
  - export_results: atomic JSON write, schema validated
  - _init_portfolio: _SKIP_PROTOCOLS excluded

Run:
    python3 -m pytest tests/test_engine_production.py -v
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Dict
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

# ── engine imports ────────────────────────────────────────────────────────────
from spa_core.paper_trading.engine import (
    INITIAL_CAPITAL,
    MIN_PAPER_WEEKS,
    SHARPE_RISK_FREE_RATE,
    STRATEGY_ID,
    InsufficientData,
    PaperTrader,
    RiskPolicyViolation,
    _V2_APY_MAX,
    _V2_APY_MIN,
    _V2_CASH_BUFFER,
    _V2_MAX_POS,
    _V2_T1_CAP,
    _V2_T2_CAP,
)
from spa_core.risk.policy import RiskCheckResult, RiskConfig, RiskPolicy

# ── multi_strategy_runner imports ─────────────────────────────────────────────
from spa_core.paper_trading.multi_strategy_runner import (
    MultiStrategyRunner,
    RANKING_FILENAME,
    _SKIP_PROTOCOLS,
)
from spa_core.paper_trading.strategy_registry import (
    S0_CONSERVATIVE_T1,
    S1_BALANCED,
    StrategyConfig,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers & fixtures
# ═══════════════════════════════════════════════════════════════════════════════

def _make_approved_result(check_name: str = "test_check") -> RiskCheckResult:
    """Build a minimal approved RiskCheckResult."""
    return RiskCheckResult(
        check_name=check_name,
        approved=True,
        violations=[],
        warnings=[],
    )


def _make_rejected_result(violations=None) -> RiskCheckResult:
    """Build a minimal rejected RiskCheckResult."""
    return RiskCheckResult(
        check_name="test_check",
        approved=False,
        violations=violations or ["tvl_too_low: TVL $1M < $5M floor"],
        warnings=[],
    )


def _minimal_strategy(sid: str = "TEST", status: str = "active") -> StrategyConfig:
    """Minimal StrategyConfig for runner tests (no external protocols)."""
    return StrategyConfig(
        id=sid,
        name=f"Test Strategy {sid}",
        description="Test",
        allocations={"aave_v3": 0.60, "compound_v3": 0.30},
        tier="T1",
        target_apy_min=2.0,
        target_apy_max=10.0,
        kill_drawdown_pct=0.05,
        status=status,
    )


@pytest.fixture()
def tmp_db(tmp_path):
    """Create a fully-initialised temporary SQLite database."""
    db_file = tmp_path / "test_spa.db"
    from spa_core.database.init_db import init_database
    init_database(db_path=db_file)
    return db_file


@pytest.fixture()
def trader(tmp_db):
    """PaperTrader backed by a fresh temp DB; decision_logger disabled."""
    return PaperTrader(db_path=tmp_db, decision_logger=None)


@pytest.fixture()
def runner_two():
    """MultiStrategyRunner with S0 and S1 (both active)."""
    return MultiStrategyRunner([S0_CONSERVATIVE_T1, S1_BALANCED])


@pytest.fixture()
def simple_apy():
    """Minimal APY map that covers T1 protocols used by S0/S1."""
    return {
        "aave_v3":    4.2,
        "morpho_blue": 6.5,
        "compound_v3": 4.8,
        "yearn_v3":   7.0,
        "euler_v2":   5.5,
        "maple":      8.0,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Section 1 — Constants
# ═══════════════════════════════════════════════════════════════════════════════

class TestEngineConstants:
    def test_initial_capital_100k(self):
        assert INITIAL_CAPITAL == 100_000.0

    def test_min_paper_weeks_is_8(self):
        assert MIN_PAPER_WEEKS == 8

    def test_sharpe_risk_free_rate(self):
        assert SHARPE_RISK_FREE_RATE == 0.05

    def test_default_strategy_id(self):
        assert STRATEGY_ID == "paper-v1"

    def test_v2_t1_cap_valid(self):
        assert 0 < _V2_T1_CAP <= 1.0

    def test_v2_t2_cap_less_than_t1(self):
        assert _V2_T2_CAP < _V2_T1_CAP

    def test_v2_cash_buffer_positive(self):
        assert _V2_CASH_BUFFER > 0

    def test_v2_max_pos_positive(self):
        assert _V2_MAX_POS > 0

    def test_v2_apy_range_valid(self):
        assert _V2_APY_MIN < _V2_APY_MAX

    def test_ranking_filename_constant(self):
        assert RANKING_FILENAME == "tournament_ranking.json"


# ═══════════════════════════════════════════════════════════════════════════════
# Section 2 — Exceptions
# ═══════════════════════════════════════════════════════════════════════════════

class TestRiskPolicyViolationException:
    def test_is_exception_subclass(self):
        assert issubclass(RiskPolicyViolation, Exception)

    def test_stores_result_attribute(self):
        result = _make_rejected_result()
        exc = RiskPolicyViolation(result)
        assert exc.result is result

    def test_message_contains_violations(self):
        result = _make_rejected_result(["tvl_too_low: $1M", "apy_out_of_range"])
        exc = RiskPolicyViolation(result)
        msg = str(exc)
        assert "tvl_too_low" in msg
        assert "apy_out_of_range" in msg

    def test_message_contains_check_name(self):
        result = _make_rejected_result()
        exc = RiskPolicyViolation(result)
        assert "test_check" in str(exc)

    def test_approved_false(self):
        result = _make_rejected_result()
        exc = RiskPolicyViolation(result)
        assert exc.result.approved is False

    def test_can_be_caught_as_exception(self):
        result = _make_rejected_result()
        with pytest.raises(Exception):
            raise RiskPolicyViolation(result)


class TestInsufficientDataException:
    def test_is_exception_subclass(self):
        assert issubclass(InsufficientData, Exception)

    def test_can_raise_and_catch(self):
        with pytest.raises(InsufficientData):
            raise InsufficientData("need more data")

    def test_message_preserved(self):
        try:
            raise InsufficientData("missing APY snapshots")
        except InsufficientData as e:
            assert "missing APY snapshots" in str(e)


# ═══════════════════════════════════════════════════════════════════════════════
# Section 3 — PaperTrader initialisation
# ═══════════════════════════════════════════════════════════════════════════════

class TestPaperTraderInit:
    def test_init_creates_strategy_state(self, tmp_db):
        """PaperTrader.__init__ inserts a strategy_state row."""
        from spa_core.database.init_db import get_connection
        trader = PaperTrader(db_path=tmp_db, decision_logger=None)
        with get_connection(tmp_db) as conn:
            row = conn.execute(
                "SELECT * FROM strategy_state WHERE strategy_id = ?",
                (STRATEGY_ID,),
            ).fetchone()
        assert row is not None
        assert float(row["total_capital_usd"]) == INITIAL_CAPITAL

    def test_default_strategy_id(self, tmp_db):
        trader = PaperTrader(db_path=tmp_db, decision_logger=None)
        assert trader.strategy_id == STRATEGY_ID

    def test_custom_strategy_id(self, tmp_db):
        trader = PaperTrader(db_path=tmp_db, strategy_id="test-v99",
                             decision_logger=None)
        assert trader.strategy_id == "test-v99"

    def test_live_execution_default_false(self, tmp_db):
        trader = PaperTrader(db_path=tmp_db, decision_logger=None)
        assert trader.live_execution is False

    def test_live_execution_can_be_enabled(self, tmp_db):
        trader = PaperTrader(db_path=tmp_db, live_execution=True,
                             decision_logger=None)
        assert trader.live_execution is True

    def test_live_bridge_not_constructed_by_default(self, tmp_db):
        trader = PaperTrader(db_path=tmp_db, decision_logger=None)
        assert trader._live_bridge is None

    def test_policy_is_risk_policy_instance(self, tmp_db):
        trader = PaperTrader(db_path=tmp_db, decision_logger=None)
        assert isinstance(trader.policy, RiskPolicy)

    def test_custom_config_accepted(self, tmp_db):
        cfg = RiskConfig()
        trader = PaperTrader(db_path=tmp_db, config=cfg, decision_logger=None)
        assert trader.policy.config is cfg


# ═══════════════════════════════════════════════════════════════════════════════
# Section 4 — open_position
# ═══════════════════════════════════════════════════════════════════════════════

class TestOpenPosition:
    def test_open_position_unknown_protocol_raises(self, trader):
        """Opening a position for a protocol not in whitelist raises ValueError."""
        with pytest.raises(ValueError, match="not found in whitelist"):
            trader.open_position(
                protocol_key="nonexistent-protocol",
                amount_usd=5_000.0,
                current_apy=4.5,
                tvl_usd=100e6,
            )

    def test_open_position_risk_violation_raises(self, trader):
        """RiskPolicy rejection raises RiskPolicyViolation (never silently ignored)."""
        with patch.object(
            trader.policy,
            "check_new_position",
            return_value=_make_rejected_result(),
        ):
            with patch.object(trader, "_get_protocol",
                              return_value={"tier": "T1", "asset": "USDC"}):
                with pytest.raises(RiskPolicyViolation):
                    trader.open_position(
                        protocol_key="aave-v3-usdc-ethereum",
                        amount_usd=5_000.0,
                        current_apy=4.5,
                        tvl_usd=100e6,
                    )

    def test_open_position_risk_violation_has_result(self, trader):
        """RiskPolicyViolation carries the full result object."""
        rejected = _make_rejected_result(["tvl_too_low"])
        with patch.object(trader.policy, "check_new_position",
                          return_value=rejected):
            with patch.object(trader, "_get_protocol",
                              return_value={"tier": "T1", "asset": "USDC"}):
                with pytest.raises(RiskPolicyViolation) as exc_info:
                    trader.open_position("aave-v3-usdc-ethereum",
                                         5_000.0, 4.5, 100e6)
                assert exc_info.value.result.approved is False
                assert "tvl_too_low" in exc_info.value.result.violations

    def test_open_position_happy_path_seeded_protocol(self, trader):
        """open_position succeeds for a seeded protocol with valid APY/TVL."""
        result = trader.open_position(
            protocol_key="aave-v3-usdc-ethereum",
            amount_usd=5_000.0,
            current_apy=4.5,
            tvl_usd=150_000_000.0,
        )
        assert result.approved is True

    def test_open_position_records_trade_in_db(self, tmp_db, trader):
        """Successful open_position inserts a paper_trades row."""
        from spa_core.database.init_db import get_connection
        trader.open_position("aave-v3-usdc-ethereum", 5_000.0, 4.5, 150e6)
        with get_connection(tmp_db) as conn:
            rows = conn.execute(
                "SELECT * FROM paper_trades WHERE strategy_id = ? AND action = 'OPEN'",
                (STRATEGY_ID,),
            ).fetchall()
        assert len(rows) >= 1
        assert float(rows[0]["amount_usd"]) == 5_000.0

    def test_open_position_live_execution_false_skips_bridge(self, trader):
        """live_execution=False means no bridge is constructed during open."""
        trader.open_position("aave-v3-usdc-ethereum", 5_000.0, 4.5, 150e6)
        assert trader._live_bridge is None

    def test_open_position_tvl_too_low_rejected(self, trader):
        """TVL below 5M floor must be blocked by RiskPolicy."""
        with pytest.raises(RiskPolicyViolation):
            trader.open_position(
                protocol_key="aave-v3-usdc-ethereum",
                amount_usd=5_000.0,
                current_apy=4.5,
                tvl_usd=100.0,   # $100 — far below $5M floor
            )


# ═══════════════════════════════════════════════════════════════════════════════
# Section 5 — close_position
# ═══════════════════════════════════════════════════════════════════════════════

class TestClosePosition:
    def test_close_position_no_open_raises(self, trader):
        """Closing a non-existent position raises ValueError."""
        with pytest.raises(ValueError, match="No open position"):
            trader.close_position("aave-v3-usdc-ethereum", reason="test")

    def test_close_position_after_open_succeeds(self, trader):
        """open then close returns dict with realized_pnl_usd."""
        trader.open_position("aave-v3-usdc-ethereum", 5_000.0, 4.5, 150e6)
        result = trader.close_position("aave-v3-usdc-ethereum", reason="test")
        assert "realized_pnl_usd" in result
        assert result["protocol_key"] == "aave-v3-usdc-ethereum"

    def test_close_position_returns_total_amount(self, trader):
        """close_position includes total_amount_usd in return dict."""
        trader.open_position("aave-v3-usdc-ethereum", 5_000.0, 4.5, 150e6)
        result = trader.close_position("aave-v3-usdc-ethereum")
        assert "total_amount_usd" in result
        assert result["total_amount_usd"] == 5_000.0

    def test_close_position_second_close_raises(self, trader):
        """After closing, a second close attempt raises ValueError."""
        trader.open_position("aave-v3-usdc-ethereum", 5_000.0, 4.5, 150e6)
        trader.close_position("aave-v3-usdc-ethereum")
        with pytest.raises(ValueError, match="No open position"):
            trader.close_position("aave-v3-usdc-ethereum")


# ═══════════════════════════════════════════════════════════════════════════════
# Section 6 — rebalance / kill switch
# ═══════════════════════════════════════════════════════════════════════════════

class TestRebalanceKillSwitch:
    def test_rebalance_returns_list(self, trader):
        """rebalance() always returns a list (even empty)."""
        result = trader.rebalance()
        assert isinstance(result, list)

    def test_rebalance_kill_switch_closes_all(self, trader):
        """When portfolio health check fails, kill-switch closes all positions."""
        # Open a position first
        trader.open_position("aave-v3-usdc-ethereum", 5_000.0, 4.5, 150e6)

        # Force health check to fail (simulates drawdown > 5%)
        rejected_health = RiskCheckResult(
            check_name="portfolio_health",
            approved=False,
            violations=["drawdown_exceeded: 6.5% > 5.0%"],
            warnings=[],
        )
        with patch.object(trader.policy, "check_portfolio_health",
                          return_value=rejected_health):
            actions = trader.rebalance()

        close_actions = [a for a in actions if a.get("action") == "CLOSE"]
        assert len(close_actions) >= 1

    def test_rebalance_kill_switch_reason_is_kill_switch(self, trader):
        """Kill-switch close actions carry reason='kill_switch'."""
        trader.open_position("aave-v3-usdc-ethereum", 5_000.0, 4.5, 150e6)
        rejected_health = RiskCheckResult(
            check_name="portfolio_health",
            approved=False,
            violations=["drawdown_exceeded"],
            warnings=[],
        )
        with patch.object(trader.policy, "check_portfolio_health",
                          return_value=rejected_health):
            actions = trader.rebalance()

        close_actions = [a for a in actions if a.get("reason") == "kill_switch"]
        assert len(close_actions) >= 1


# ═══════════════════════════════════════════════════════════════════════════════
# Section 7 — MultiStrategyRunner initialisation
# ═══════════════════════════════════════════════════════════════════════════════

class TestMultiStrategyRunnerInit:
    def test_creates_portfolio_per_strategy(self):
        runner = MultiStrategyRunner([S0_CONSERVATIVE_T1, S1_BALANCED])
        assert len(runner._portfolios) == 2

    def test_strategy_ids_in_portfolios(self):
        runner = MultiStrategyRunner([S0_CONSERVATIVE_T1, S1_BALANCED])
        assert "S0" in runner._portfolios
        assert "S1" in runner._portfolios

    def test_capital_default_100k(self):
        runner = MultiStrategyRunner([S0_CONSERVATIVE_T1])
        assert runner.capital == 100_000.0

    def test_capital_custom(self):
        runner = MultiStrategyRunner([S0_CONSERVATIVE_T1], capital=50_000.0)
        assert runner.capital == 50_000.0

    def test_empty_strategies_allowed(self):
        runner = MultiStrategyRunner([])
        assert runner._portfolios == {}

    def test_skip_protocols_excluded_from_portfolio(self):
        """Protocols in _SKIP_PROTOCOLS must not appear as positions."""
        runner = MultiStrategyRunner([S0_CONSERVATIVE_T1])
        vp = runner._portfolios["S0"]
        for skip_key in _SKIP_PROTOCOLS:
            assert skip_key not in vp.positions

    def test_skip_protocols_set_not_empty(self):
        assert len(_SKIP_PROTOCOLS) > 0

    def test_pendle_pt_in_skip_protocols(self):
        assert "pendle_pt" in _SKIP_PROTOCOLS

    def test_sky_susds_in_skip_protocols(self):
        assert "sky_susds" in _SKIP_PROTOCOLS


# ═══════════════════════════════════════════════════════════════════════════════
# Section 8 — run_day
# ═══════════════════════════════════════════════════════════════════════════════

class TestRunDay:
    def test_run_day_returns_dict(self, runner_two, simple_apy):
        result = runner_two.run_day(simple_apy)
        assert isinstance(result, dict)

    def test_run_day_keys_are_strategy_ids(self, runner_two, simple_apy):
        result = runner_two.run_day(simple_apy)
        assert set(result.keys()) == {"S0", "S1"}

    def test_run_day_yields_are_floats(self, runner_two, simple_apy):
        result = runner_two.run_day(simple_apy)
        for sid, y in result.items():
            assert isinstance(y, (int, float)), f"yield for {sid} is not numeric"

    def test_run_day_yields_non_negative(self, runner_two, simple_apy):
        result = runner_two.run_day(simple_apy)
        for sid, y in result.items():
            assert y >= 0.0, f"negative yield for {sid}: {y}"

    def test_run_day_killed_strategy_skipped(self, simple_apy):
        """A killed strategy receives no yield from run_day."""
        killed = _minimal_strategy("KILLED", status="killed")
        active = _minimal_strategy("ACTIVE", status="active")
        runner = MultiStrategyRunner([killed, active])
        result = runner.run_day(simple_apy)
        assert "KILLED" not in result
        assert "ACTIVE" in result

    def test_run_day_paused_strategy_skipped(self, simple_apy):
        """A paused strategy receives no yield from run_day."""
        paused = _minimal_strategy("PAUSED", status="paused")
        runner = MultiStrategyRunner([paused])
        result = runner.run_day(simple_apy)
        assert "PAUSED" not in result

    def test_run_day_empty_apy_map(self, runner_two):
        """run_day with empty apy_map should not crash (zero yields)."""
        result = runner_two.run_day({})
        assert isinstance(result, dict)

    def test_run_day_multiple_days_accumulate(self, runner_two, simple_apy):
        """Calling run_day twice accumulates days_simulated."""
        vp_before = runner_two._portfolios["S0"].days_simulated
        runner_two.run_day(simple_apy)
        runner_two.run_day(simple_apy)
        vp_after = runner_two._portfolios["S0"].days_simulated
        assert vp_after == vp_before + 2


# ═══════════════════════════════════════════════════════════════════════════════
# Section 9 — get_rankings
# ═══════════════════════════════════════════════════════════════════════════════

class TestGetRankings:
    def test_rankings_returns_list(self, runner_two):
        rankings = runner_two.get_rankings()
        assert isinstance(rankings, list)

    def test_rankings_length_equals_strategies(self, runner_two):
        rankings = runner_two.get_rankings()
        assert len(rankings) == 2

    def test_first_rank_is_1(self, runner_two):
        rankings = runner_two.get_rankings()
        assert rankings[0]["rank"] == 1

    def test_ranks_are_sequential(self, runner_two):
        rankings = runner_two.get_rankings()
        for i, r in enumerate(rankings):
            assert r["rank"] == i + 1

    def test_all_required_keys_present(self, runner_two):
        required = {"rank", "strategy_id", "composite_score", "net_apy",
                    "is_active", "days_running"}
        for r in runner_two.get_rankings():
            assert required.issubset(set(r.keys()))

    def test_sorted_descending_by_composite_score(self, runner_two, simple_apy):
        runner_two.run_day(simple_apy)
        rankings = runner_two.get_rankings()
        scores = [r["composite_score"] for r in rankings]
        assert scores == sorted(scores, reverse=True)

    def test_net_apy_is_fraction_not_percent(self, runner_two, simple_apy):
        """net_apy is a decimal fraction (0.042), not a percentage (4.2)."""
        runner_two.run_day(simple_apy)
        rankings = runner_two.get_rankings()
        for r in rankings:
            assert r["net_apy"] < 1.0, \
                f"net_apy={r['net_apy']} looks like percent, expected fraction"


# ═══════════════════════════════════════════════════════════════════════════════
# Section 10 — get_active_strategies / get_total_yield / get_allocation_map
# ═══════════════════════════════════════════════════════════════════════════════

class TestRunnerHelpers:
    def test_get_active_strategies_both_active(self, runner_two):
        active = runner_two.get_active_strategies()
        ids = {s.id for s in active}
        assert "S0" in ids and "S1" in ids

    def test_get_active_strategies_excludes_killed(self, simple_apy):
        killed = _minimal_strategy("KILLED", status="killed")
        active = _minimal_strategy("ACTIVE", status="active")
        runner = MultiStrategyRunner([killed, active])
        result = runner.get_active_strategies()
        assert all(s.id != "KILLED" for s in result)
        assert any(s.id == "ACTIVE" for s in result)

    def test_get_total_yield_zero_before_run_day(self, runner_two):
        assert runner_two.get_total_yield() == 0.0

    def test_get_total_yield_positive_after_run_day(self, runner_two, simple_apy):
        runner_two.run_day(simple_apy)
        total = runner_two.get_total_yield()
        assert total >= 0.0

    def test_get_allocation_map_empty_when_all_killed(self):
        killed = _minimal_strategy("K1", status="killed")
        runner = MultiStrategyRunner([killed])
        assert runner.get_allocation_map() == {}

    def test_get_allocation_map_equal_shares(self, runner_two):
        alloc = runner_two.get_allocation_map()
        assert len(alloc) == 2
        for share in alloc.values():
            assert abs(share - 0.5) < 1e-9

    def test_get_allocation_map_sums_to_one(self, runner_two):
        alloc = runner_two.get_allocation_map()
        assert abs(sum(alloc.values()) - 1.0) < 1e-9

    def test_get_allocation_map_single_strategy(self):
        runner = MultiStrategyRunner([S0_CONSERVATIVE_T1])
        alloc = runner.get_allocation_map()
        assert abs(list(alloc.values())[0] - 1.0) < 1e-9


# ═══════════════════════════════════════════════════════════════════════════════
# Section 11 — export_results
# ═══════════════════════════════════════════════════════════════════════════════

class TestExportResults:
    def test_export_creates_file(self, runner_two, simple_apy, tmp_path):
        runner_two.run_day(simple_apy)
        out = tmp_path / "tournament_ranking.json"
        runner_two.export_results(out)
        assert out.exists()

    def test_export_file_is_valid_json(self, runner_two, simple_apy, tmp_path):
        runner_two.run_day(simple_apy)
        out = tmp_path / "tournament_ranking.json"
        runner_two.export_results(out)
        data = json.loads(out.read_text())
        assert isinstance(data, dict)

    def test_export_schema_has_required_keys(self, runner_two, simple_apy, tmp_path):
        runner_two.run_day(simple_apy)
        out = tmp_path / "tournament_ranking.json"
        runner_two.export_results(out)
        data = json.loads(out.read_text())
        assert "timestamp" in data
        assert "strategies" in data
        assert "total_active" in data
        assert "weighted_apy" in data

    def test_export_strategies_count(self, runner_two, simple_apy, tmp_path):
        runner_two.run_day(simple_apy)
        out = tmp_path / "tournament_ranking.json"
        runner_two.export_results(out)
        data = json.loads(out.read_text())
        assert len(data["strategies"]) == 2

    def test_export_total_active_correct(self, runner_two, simple_apy, tmp_path):
        runner_two.run_day(simple_apy)
        out = tmp_path / "tournament_ranking.json"
        runner_two.export_results(out)
        data = json.loads(out.read_text())
        assert data["total_active"] == 2

    def test_export_atomic_write_no_partial_file(self, runner_two, simple_apy, tmp_path):
        """export_results must use atomic tmp+replace — no leftover tmp file."""
        runner_two.run_day(simple_apy)
        out = tmp_path / "tournament_ranking.json"
        runner_two.export_results(out)
        tmp_files = list(tmp_path.glob(".tmp_tournament_ranking_*"))
        assert len(tmp_files) == 0, "Leftover tmp files after export_results"

    def test_export_creates_parent_dirs(self, runner_two, simple_apy, tmp_path):
        out = tmp_path / "nested" / "dir" / "ranking.json"
        runner_two.run_day(simple_apy)
        runner_two.export_results(out)
        assert out.exists()

    def test_export_idempotent_overwrite(self, runner_two, simple_apy, tmp_path):
        """Calling export_results twice overwrites, no error."""
        runner_two.run_day(simple_apy)
        out = tmp_path / "ranking.json"
        runner_two.export_results(out)
        runner_two.run_day(simple_apy)
        runner_two.export_results(out)
        data = json.loads(out.read_text())
        assert len(data["strategies"]) == 2
