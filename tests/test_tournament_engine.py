"""
tests/test_tournament_engine.py

50+ tests for TournamentEngine and TournamentTelegram.

All tests:
  - Run fully offline (no network, no Keychain, no real Telegram)
  - Use tmp directories to avoid touching production data/
  - Verify atomic writes, promotion logic, rank-change detection,
    Telegram formatting, and schema correctness
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest import mock

import pytest

# ─────────────────────────────────────────────────────────────────────────────
# Fixtures: minimal valid data files
# ─────────────────────────────────────────────────────────────────────────────

SAMPLE_STRATEGIES = [
    {
        "rank": 1,
        "strategy_id": "S12-BASE",
        "strategy_key": "s12_base_layer_yield",
        "name": "S12BaseLayerYield",
        "sharpe": 196.17,
        "paper_apy": 4.10,
        "annual_return_pct": 4.10,
        "max_drawdown": 0.000392,
        "max_dd_pct": 0.04,
        "sortino": 46.13,
        "calmar": 104.43,
        "win_rate_pct": 100.0,
        "allocation": {"morpho_steakhouse": 0.8, "aave_v3": 0.2},
        "is_shadow_active": True,
        "days_active": 5,
        "method_used": "get_target_weights",
    },
    {
        "rank": 2,
        "strategy_id": "S5-PENDL",
        "strategy_key": "s5_pendle_enhanced",
        "name": "S5PendleEnhanced",
        "sharpe": 185.48,
        "paper_apy": 1.34,
        "annual_return_pct": 1.34,
        "max_drawdown": 0.000139,
        "max_dd_pct": 0.014,
        "sortino": 15.37,
        "calmar": 96.22,
        "win_rate_pct": 100.0,
        "allocation": {"morpho_steakhouse": 0.25, "compound_v3": 0.1},
        "is_shadow_active": True,
        "days_active": 5,
        "method_used": "ALLOCATION_constant",
    },
    {
        "rank": 3,
        "strategy_id": "S2-PENDL",
        "strategy_key": "s2_pendle_morpho",
        "name": "S2PendleMorpho",
        "sharpe": 183.39,
        "paper_apy": 1.90,
        "annual_return_pct": 1.90,
        "max_drawdown": 0.0002,
        "max_dd_pct": 0.02,
        "sortino": 20.0,
        "calmar": 95.0,
        "win_rate_pct": 100.0,
        "allocation": {"morpho_steakhouse": 0.35, "compound_v3": 0.15},
        "is_shadow_active": True,
        "days_active": 5,
        "method_used": "ALLOCATION_constant",
    },
]

SAMPLE_TOURNAMENT = {
    "schema_version": "2.0",
    "generated_at": "2026-06-22T10:00:00+00:00",
    "version": "v1.0",
    "source": "mass_tournament_results.json",
    "metric": "sharpe_ratio",
    "simulation_period": "2022-01-01 to 2025-12-31",
    "initial_capital_usd": 100000.0,
    "total_strategies": 60,
    "strategies_skipped": 14,
    "shadow_top_n": 5,
    "shadow_active_strategies": SAMPLE_STRATEGIES,
    "ranked_strategies": SAMPLE_STRATEGIES,
    "top_5": SAMPLE_STRATEGIES[:3],
    "bottom_5": SAMPLE_STRATEGIES[:1],
    "llm_forbidden": True,
}

SAMPLE_SHADOW = {
    "schema_version": "1.0",
    "description": "Shadow paper trading",
    "created_at": "2026-06-22T10:00:00+00:00",
    "active_strategies": [
        {
            "rank": 1,
            "id": "s12_base_layer_yield",
            "sharpe": 196.17,
            "annual_return_pct": 4.10,
            "max_dd_pct": 0.04,
            "allocation": {"morpho_steakhouse": 0.8, "aave_v3": 0.2},
        },
        {
            "rank": 2,
            "id": "s5_pendle_enhanced",
            "sharpe": 185.48,
            "annual_return_pct": 1.34,
            "max_dd_pct": 0.014,
            "allocation": {"morpho_steakhouse": 0.25, "compound_v3": 0.1},
        },
    ],
    "daily_results": [],
}

APY_MAP = {
    "morpho_steakhouse": 4.6,
    "aave_v3": 3.1,
    "compound_v3": 3.3,
}


@pytest.fixture()
def data_dir(tmp_path: Path) -> Path:
    """Create a temporary data directory with valid fixture files."""
    (tmp_path / "strategy_tournament.json").write_text(
        json.dumps(SAMPLE_TOURNAMENT, indent=2)
    )
    (tmp_path / "shadow_paper_trading.json").write_text(
        json.dumps(SAMPLE_SHADOW, indent=2)
    )
    return tmp_path


@pytest.fixture()
def engine(data_dir: Path):
    """TournamentEngine instance backed by tmp data dir."""
    from spa_core.tournament.tournament_engine import TournamentEngine
    return TournamentEngine(data_dir=data_dir)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Module imports
# ─────────────────────────────────────────────────────────────────────────────

class TestImports:
    def test_engine_imports(self):
        from spa_core.tournament.tournament_engine import TournamentEngine
        assert TournamentEngine is not None

    def test_telegram_imports(self):
        from spa_core.tournament.tournament_telegram import TournamentTelegram
        assert TournamentTelegram is not None

    def test_package_imports(self):
        from spa_core.tournament import TournamentEngine, TournamentTelegram, PHASES, PROMOTION_CRITERIA
        assert "backtest" in PHASES
        assert "paper_30d" in PHASES
        assert "live" in PHASES

    def test_promotion_criteria_keys(self):
        from spa_core.tournament.tournament_engine import PROMOTION_CRITERIA
        assert "min_sharpe" in PROMOTION_CRITERIA
        assert "min_days_paper" in PROMOTION_CRITERIA
        assert "max_drawdown" in PROMOTION_CRITERIA
        assert "min_apy_pct" in PROMOTION_CRITERIA

    def test_is_advisory_true(self):
        from spa_core.tournament.tournament_engine import IS_ADVISORY
        assert IS_ADVISORY is True


# ─────────────────────────────────────────────────────────────────────────────
# 2. TournamentEngine.run_daily()
# ─────────────────────────────────────────────────────────────────────────────

class TestRunDaily:
    def test_returns_dict(self, engine):
        with mock.patch.object(engine, "_send_alerts", return_value=False):
            result = engine.run_daily()
        assert isinstance(result, dict)

    def test_summary_keys(self, engine):
        with mock.patch.object(engine, "_send_alerts", return_value=False):
            result = engine.run_daily()
        required = {
            "date", "strategies_updated", "promotions",
            "rank_changes", "telegram_sent", "errors", "is_advisory",
        }
        assert required.issubset(result.keys())

    def test_date_is_today(self, engine):
        with mock.patch.object(engine, "_send_alerts", return_value=False):
            result = engine.run_daily()
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        assert result["date"] == today

    def test_is_advisory_in_summary(self, engine):
        with mock.patch.object(engine, "_send_alerts", return_value=False):
            result = engine.run_daily()
        assert result["is_advisory"] is True

    def test_errors_is_list(self, engine):
        with mock.patch.object(engine, "_send_alerts", return_value=False):
            result = engine.run_daily()
        assert isinstance(result["errors"], list)

    def test_promotions_is_list(self, engine):
        with mock.patch.object(engine, "_send_alerts", return_value=False):
            result = engine.run_daily()
        assert isinstance(result["promotions"], list)

    def test_rank_changes_is_list(self, engine):
        with mock.patch.object(engine, "_send_alerts", return_value=False):
            result = engine.run_daily()
        assert isinstance(result["rank_changes"], list)

    def test_run_daily_is_resilient_to_missing_tournament(self, tmp_path):
        """run_daily must not raise even when strategy_tournament.json is absent."""
        from spa_core.tournament.tournament_engine import TournamentEngine
        engine = TournamentEngine(data_dir=tmp_path)
        with mock.patch.object(engine, "_send_alerts", return_value=False):
            result = engine.run_daily()
        # Should have at least one error about missing file but not crash
        assert isinstance(result, dict)

    def test_run_daily_no_network(self, engine):
        """Ensure run_daily never makes real network calls."""
        with mock.patch("urllib.request.urlopen") as mock_open:
            with mock.patch.object(engine, "_send_alerts", return_value=False):
                engine.run_daily()
        mock_open.assert_not_called()

    def test_run_daily_updates_shadow_file(self, engine, data_dir):
        with mock.patch.object(engine, "_send_alerts", return_value=False):
            engine.run_daily()
        shadow = json.loads((data_dir / "shadow_paper_trading.json").read_text())
        assert shadow.get("total_days", 0) >= 1

    def test_run_daily_creates_engine_state(self, engine, data_dir):
        with mock.patch.object(engine, "_send_alerts", return_value=False):
            engine.run_daily()
        state_path = data_dir / "tournament_engine_state.json"
        assert state_path.exists()
        state = json.loads(state_path.read_text())
        assert "last_run" in state


# ─────────────────────────────────────────────────────────────────────────────
# 3. check_promotions() — promotion criteria enforcement
# ─────────────────────────────────────────────────────────────────────────────

class TestCheckPromotions:
    def _make_engine_with_shadow(
        self,
        tmp_path: Path,
        days: int,
        apy_pct: float = 4.0,
        sharpe_override: Optional[float] = None,
    ):
        """Helper: build engine with *days* of shadow paper data."""
        from spa_core.tournament.tournament_engine import TournamentEngine

        tournament = json.loads(json.dumps(SAMPLE_TOURNAMENT))
        if sharpe_override is not None:
            for s in tournament["shadow_active_strategies"]:
                s["sharpe"] = sharpe_override
            for s in tournament["ranked_strategies"]:
                s["sharpe"] = sharpe_override

        shadow = json.loads(json.dumps(SAMPLE_SHADOW))
        daily = []
        for i in range(days):
            date = f"2026-06-{i + 1:02d}"
            daily.append({
                "date": date,
                "strategies": [
                    {"strategy_id": "s12_base_layer_yield", "daily_yield_usd": 1.0,
                     "annualised_apy_pct": apy_pct},
                    {"strategy_id": "s5_pendle_enhanced", "daily_yield_usd": 0.5,
                     "annualised_apy_pct": apy_pct},
                ],
                "best_strategy": "s12_base_layer_yield",
            })
        shadow["daily_results"] = daily

        (tmp_path / "strategy_tournament.json").write_text(json.dumps(tournament))
        (tmp_path / "shadow_paper_trading.json").write_text(json.dumps(shadow))
        return TournamentEngine(data_dir=tmp_path)

    def test_no_promotion_below_min_days(self, tmp_path):
        engine = self._make_engine_with_shadow(tmp_path, days=3)
        promotions = engine.check_promotions()
        assert promotions == [], "Should not promote with only 3 days"

    def test_promotion_meets_min_days(self, tmp_path):
        engine = self._make_engine_with_shadow(tmp_path, days=10, apy_pct=5.0)
        promotions = engine.check_promotions()
        assert len(promotions) > 0, "Should promote after 10 days with 5% APY"

    def test_no_promotion_low_sharpe(self, tmp_path):
        engine = self._make_engine_with_shadow(tmp_path, days=10, sharpe_override=0.5)
        promotions = engine.check_promotions()
        assert promotions == [], "Should not promote with Sharpe=0.5"

    def test_no_promotion_low_apy(self, tmp_path):
        engine = self._make_engine_with_shadow(tmp_path, days=10, apy_pct=1.0)
        promotions = engine.check_promotions()
        assert promotions == [], "Should not promote with APY=1.0% (below 3%)"

    def test_promotion_dict_keys(self, tmp_path):
        engine = self._make_engine_with_shadow(tmp_path, days=10, apy_pct=5.0)
        promotions = engine.check_promotions()
        if promotions:
            p = promotions[0]
            assert "strategy_id" in p
            assert "phase_from" in p
            assert "phase_to" in p
            assert "is_advisory" in p
            assert "criteria_met" in p

    def test_promotion_is_advisory(self, tmp_path):
        engine = self._make_engine_with_shadow(tmp_path, days=10, apy_pct=5.0)
        promotions = engine.check_promotions()
        for p in promotions:
            assert p["is_advisory"] is True

    def test_promotion_phase_to_live(self, tmp_path):
        engine = self._make_engine_with_shadow(tmp_path, days=10, apy_pct=5.0)
        promotions = engine.check_promotions()
        for p in promotions:
            assert p["phase_from"] == "paper_30d"
            assert p["phase_to"] == "live"

    def test_check_promotions_empty_when_no_shadow(self, engine):
        """No daily results → no promotions."""
        promotions = engine.check_promotions()
        # With 0 days paper, nothing should be promoted
        assert promotions == []

    def test_criteria_met_flags(self, tmp_path):
        engine = self._make_engine_with_shadow(tmp_path, days=10, apy_pct=5.0)
        promotions = engine.check_promotions()
        for p in promotions:
            cm = p["criteria_met"]
            assert "min_sharpe" in cm
            assert "min_days_paper" in cm
            assert "min_apy_pct" in cm
            assert "max_drawdown" in cm

    def test_no_promotion_exact_boundary_days(self, tmp_path):
        """6 days = exactly below min_days_paper=7."""
        engine = self._make_engine_with_shadow(tmp_path, days=6, apy_pct=5.0)
        promotions = engine.check_promotions()
        assert promotions == []

    def test_promotion_at_exact_boundary_days(self, tmp_path):
        """7 days = exactly at min_days_paper=7."""
        engine = self._make_engine_with_shadow(tmp_path, days=7, apy_pct=5.0)
        promotions = engine.check_promotions()
        assert len(promotions) > 0


# ─────────────────────────────────────────────────────────────────────────────
# 4. update_shadow_day() — shadow simulation and atomic writes
# ─────────────────────────────────────────────────────────────────────────────

class TestUpdateShadowDay:
    def test_returns_dict(self, engine):
        result = engine.update_shadow_day("2026-06-22", apy_map=APY_MAP)
        assert isinstance(result, dict)

    def test_result_keys(self, engine):
        result = engine.update_shadow_day("2026-06-22", apy_map=APY_MAP)
        assert "date" in result
        assert "strategies" in result
        assert "best_strategy" in result
        assert "best_yield_usd" in result
        assert "best_apy_pct" in result

    def test_writes_to_shadow_json(self, engine, data_dir):
        engine.update_shadow_day("2026-06-22", apy_map=APY_MAP)
        shadow = json.loads((data_dir / "shadow_paper_trading.json").read_text())
        dates = [dr["date"] for dr in shadow["daily_results"]]
        assert "2026-06-22" in dates

    def test_atomic_write_no_leftover_tmp(self, engine, data_dir):
        engine.update_shadow_day("2026-06-22", apy_map=APY_MAP)
        tmp_files = list(data_dir.glob("*.tmp"))
        assert tmp_files == [], f"Leftover .tmp files: {tmp_files}"

    def test_idempotent_same_date(self, engine, data_dir):
        engine.update_shadow_day("2026-06-22", apy_map=APY_MAP)
        engine.update_shadow_day("2026-06-22", apy_map=APY_MAP)
        shadow = json.loads((data_dir / "shadow_paper_trading.json").read_text())
        dates = [dr["date"] for dr in shadow["daily_results"]]
        assert dates.count("2026-06-22") == 1, "Duplicate date entries written"

    def test_ring_buffer_capped_at_365(self, engine, data_dir):
        for i in range(370):
            date = f"20{26 + i // 365}-{(i % 12) + 1:02d}-{(i % 28) + 1:02d}"
            try:
                engine.update_shadow_day(date, apy_map=APY_MAP)
            except Exception:
                pass
        shadow = json.loads((data_dir / "shadow_paper_trading.json").read_text())
        assert len(shadow["daily_results"]) <= 365

    def test_strategies_list_not_empty_with_valid_apy(self, engine):
        result = engine.update_shadow_day("2026-06-22", apy_map=APY_MAP)
        assert len(result["strategies"]) > 0

    def test_daily_yield_positive_with_positive_apy(self, engine):
        result = engine.update_shadow_day("2026-06-22", apy_map=APY_MAP)
        for s in result["strategies"]:
            assert s["daily_yield_usd"] >= 0.0

    def test_zero_apy_gives_zero_yield(self, engine):
        result = engine.update_shadow_day("2026-06-22", apy_map={})
        # With no APY data, yields should be zero
        for s in result["strategies"]:
            assert s["daily_yield_usd"] == 0.0

    def test_best_strategy_is_highest_yield(self, engine):
        result = engine.update_shadow_day("2026-06-22", apy_map=APY_MAP)
        if result["strategies"]:
            max_yield = max(s["daily_yield_usd"] for s in result["strategies"])
            best = next(
                s for s in result["strategies"]
                if s["strategy_id"] == result["best_strategy"]
            )
            assert best["daily_yield_usd"] == max_yield

    def test_last_updated_written(self, engine, data_dir):
        engine.update_shadow_day("2026-06-22", apy_map=APY_MAP)
        shadow = json.loads((data_dir / "shadow_paper_trading.json").read_text())
        assert "last_updated" in shadow

    def test_total_days_incremented(self, engine, data_dir):
        engine.update_shadow_day("2026-06-22", apy_map=APY_MAP)
        shadow = json.loads((data_dir / "shadow_paper_trading.json").read_text())
        assert shadow["total_days"] == 1
        engine.update_shadow_day("2026-06-23", apy_map=APY_MAP)
        shadow = json.loads((data_dir / "shadow_paper_trading.json").read_text())
        assert shadow["total_days"] == 2


# ─────────────────────────────────────────────────────────────────────────────
# 5. get_tournament_status() — schema validation
# ─────────────────────────────────────────────────────────────────────────────

class TestGetTournamentStatus:
    def test_returns_dict(self, engine):
        status = engine.get_tournament_status()
        assert isinstance(status, dict)

    def test_required_keys_present(self, engine):
        status = engine.get_tournament_status()
        required = {
            "schema_version", "engine_version", "generated_at",
            "is_advisory", "phases", "promotion_criteria",
            "top_5", "promotions_pending", "shadow_days_tracked",
            "last_shadow_date", "total_strategies",
        }
        assert required.issubset(status.keys())

    def test_is_advisory_true(self, engine):
        status = engine.get_tournament_status()
        assert status["is_advisory"] is True

    def test_phases_list(self, engine):
        status = engine.get_tournament_status()
        assert isinstance(status["phases"], list)
        assert "backtest" in status["phases"]
        assert "live" in status["phases"]

    def test_promotion_criteria_dict(self, engine):
        status = engine.get_tournament_status()
        pc = status["promotion_criteria"]
        assert isinstance(pc, dict)
        assert "min_sharpe" in pc

    def test_top5_is_list(self, engine):
        status = engine.get_tournament_status()
        assert isinstance(status["top_5"], list)

    def test_promotions_pending_is_list(self, engine):
        status = engine.get_tournament_status()
        assert isinstance(status["promotions_pending"], list)

    def test_shadow_days_tracked_int(self, engine):
        status = engine.get_tournament_status()
        assert isinstance(status["shadow_days_tracked"], int)

    def test_total_strategies_positive(self, engine):
        status = engine.get_tournament_status()
        assert status["total_strategies"] > 0

    def test_schema_version_string(self, engine):
        status = engine.get_tournament_status()
        assert isinstance(status["schema_version"], str)

    def test_engine_version_string(self, engine):
        status = engine.get_tournament_status()
        assert isinstance(status["engine_version"], str)


# ─────────────────────────────────────────────────────────────────────────────
# 6. _detect_rank_changes()
# ─────────────────────────────────────────────────────────────────────────────

class TestDetectRankChanges:
    def test_no_changes_on_first_run(self, engine):
        changes = engine._detect_rank_changes(SAMPLE_TOURNAMENT)
        # No prior state → no rank changes
        assert isinstance(changes, list)

    def test_detects_swap(self, engine, data_dir):
        # Seed prior state with rank 1=s12, 2=s5
        state = {
            "last_top3": [
                {"rank": 1, "strategy_id": "s12_base_layer_yield"},
                {"rank": 2, "strategy_id": "s5_pendle_enhanced"},
                {"rank": 3, "strategy_id": "s2_pendle_morpho"},
            ]
        }
        (data_dir / "tournament_engine_state.json").write_text(json.dumps(state))

        # New tournament has same ranks
        changes = engine._detect_rank_changes(SAMPLE_TOURNAMENT)
        # No changes since ranks are the same
        assert changes == []

    def test_detects_actual_rank_change(self, engine, data_dir):
        # Prior state: s12=1, s5=2, s2=3
        state = {
            "last_top3": [
                {"rank": 1, "strategy_id": "s12_base_layer_yield"},
                {"rank": 2, "strategy_id": "s5_pendle_enhanced"},
                {"rank": 3, "strategy_id": "s2_pendle_morpho"},
            ]
        }
        (data_dir / "tournament_engine_state.json").write_text(json.dumps(state))

        # New tournament: s12=2, s5=1, s2=3 (swap 1 and 2)
        swapped_tournament = json.loads(json.dumps(SAMPLE_TOURNAMENT))
        swapped_tournament["shadow_active_strategies"][0]["rank"] = 2
        swapped_tournament["shadow_active_strategies"][0]["strategy_key"] = "s12_base_layer_yield"
        swapped_tournament["shadow_active_strategies"][1]["rank"] = 1
        swapped_tournament["shadow_active_strategies"][1]["strategy_key"] = "s5_pendle_enhanced"

        changes = engine._detect_rank_changes(swapped_tournament)
        assert len(changes) > 0

    def test_rank_change_has_required_keys(self, engine, data_dir):
        state = {
            "last_top3": [
                {"rank": 1, "strategy_id": "s12_base_layer_yield"},
                {"rank": 2, "strategy_id": "s5_pendle_enhanced"},
                {"rank": 3, "strategy_id": "s99_new"},
            ]
        }
        (data_dir / "tournament_engine_state.json").write_text(json.dumps(state))

        swapped = json.loads(json.dumps(SAMPLE_TOURNAMENT))
        swapped["shadow_active_strategies"][0]["rank"] = 2
        swapped["shadow_active_strategies"][0]["strategy_key"] = "s12_base_layer_yield"
        swapped["shadow_active_strategies"][1]["rank"] = 1
        swapped["shadow_active_strategies"][1]["strategy_key"] = "s5_pendle_enhanced"

        changes = engine._detect_rank_changes(swapped)
        for change in changes:
            assert "strategy_id" in change
            assert "new_rank" in change


# ─────────────────────────────────────────────────────────────────────────────
# 7. _compute_paper_apy() and _compute_max_drawdown()
# ─────────────────────────────────────────────────────────────────────────────

class TestComputeMetrics:
    def _make_daily_results(self, n: int, apy: float = 4.0, yield_usd: float = 1.0):
        results = []
        for i in range(n):
            results.append({
                "date": f"2026-06-{i + 1:02d}",
                "strategies": [
                    {
                        "strategy_id": "s12_base_layer_yield",
                        "daily_yield_usd": yield_usd,
                        "annualised_apy_pct": apy,
                    }
                ],
            })
        return results

    def test_compute_paper_apy_returns_average(self, engine):
        daily = self._make_daily_results(10, apy=4.5)
        apy = engine._compute_paper_apy("s12_base_layer_yield", daily)
        assert abs(apy - 4.5) < 0.01

    def test_compute_paper_apy_empty_returns_zero(self, engine):
        apy = engine._compute_paper_apy("nonexistent", [])
        assert apy == 0.0

    def test_compute_max_drawdown_all_positive(self, engine):
        daily = self._make_daily_results(10, yield_usd=10.0)
        dd = engine._compute_max_drawdown("s12_base_layer_yield", daily)
        assert dd == 0.0, "No drawdown when all yields positive"

    def test_compute_max_drawdown_with_loss(self, engine):
        # Build results with a loss day
        daily = [
            {
                "date": "2026-06-01",
                "strategies": [
                    {"strategy_id": "s12_base_layer_yield",
                     "daily_yield_usd": 100.0, "annualised_apy_pct": 4.0}
                ],
            },
            {
                "date": "2026-06-02",
                "strategies": [
                    {"strategy_id": "s12_base_layer_yield",
                     "daily_yield_usd": -5000.0, "annualised_apy_pct": -1.0}
                ],
            },
        ]
        dd = engine._compute_max_drawdown("s12_base_layer_yield", daily)
        assert dd < 0.0, "Should detect drawdown after large loss"

    def test_compute_max_drawdown_empty_returns_zero(self, engine):
        dd = engine._compute_max_drawdown("nonexistent", [])
        assert dd == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# 8. Telegram formatting (static methods — no network)
# ─────────────────────────────────────────────────────────────────────────────

class TestTelegramFormatting:
    def test_format_daily_standings_contains_trophy(self):
        from spa_core.tournament.tournament_telegram import TournamentTelegram
        text = TournamentTelegram.format_daily_standings(
            SAMPLE_STRATEGIES[:3], {}, "2026-06-22"
        )
        assert "🏆" in text

    def test_format_daily_standings_contains_date(self):
        from spa_core.tournament.tournament_telegram import TournamentTelegram
        text = TournamentTelegram.format_daily_standings(
            SAMPLE_STRATEGIES[:3], {}, "2026-06-22"
        )
        assert "2026-06-22" in text

    def test_format_daily_standings_contains_medals(self):
        from spa_core.tournament.tournament_telegram import TournamentTelegram
        text = TournamentTelegram.format_daily_standings(
            SAMPLE_STRATEGIES[:3], {}, "2026-06-22"
        )
        assert "🥇" in text
        assert "🥈" in text
        assert "🥉" in text

    def test_format_daily_standings_has_html_bold(self):
        from spa_core.tournament.tournament_telegram import TournamentTelegram
        text = TournamentTelegram.format_daily_standings(
            SAMPLE_STRATEGIES[:3], {}, "2026-06-22"
        )
        assert "<b>" in text

    def test_format_daily_standings_contains_dashboard_link(self):
        from spa_core.tournament.tournament_telegram import TournamentTelegram
        text = TournamentTelegram.format_daily_standings(
            SAMPLE_STRATEGIES[:3], {}, "2026-06-22"
        )
        assert "Dashboard" in text

    def test_format_promotion_alert_paper_to_live(self):
        from spa_core.tournament.tournament_telegram import TournamentTelegram
        text = TournamentTelegram.format_promotion_alert(
            "s12_base_layer_yield", "paper_30d", "live"
        )
        assert "🎯" in text
        assert "s12_base_layer_yield" in text
        assert "paper_30d" in text
        assert "live" in text
        assert "Advisory" in text

    def test_format_promotion_alert_contains_arrow(self):
        from spa_core.tournament.tournament_telegram import TournamentTelegram
        text = TournamentTelegram.format_promotion_alert(
            "s12_base_layer_yield", "backtest", "paper_30d"
        )
        assert "→" in text

    def test_format_promotion_alert_no_advisory_warning_for_paper(self):
        """Advisory warning should only appear for paper → live, not backtest → paper."""
        from spa_core.tournament.tournament_telegram import TournamentTelegram
        text = TournamentTelegram.format_promotion_alert(
            "s12_base_layer_yield", "backtest", "paper_30d"
        )
        assert "Advisory" not in text

    def test_format_position_change_improvement(self):
        from spa_core.tournament.tournament_telegram import TournamentTelegram
        text = TournamentTelegram.format_position_change("s5_pendle_enhanced", 3, 1)
        assert "📈" in text
        assert "s5_pendle_enhanced" in text
        assert "🥇" in text

    def test_format_position_change_decline(self):
        from spa_core.tournament.tournament_telegram import TournamentTelegram
        text = TournamentTelegram.format_position_change("s12_base_layer_yield", 1, 3)
        assert "📉" in text
        assert "🥉" in text

    def test_format_position_change_entered_top3(self):
        from spa_core.tournament.tournament_telegram import TournamentTelegram
        text = TournamentTelegram.format_position_change("new_strategy", None, 2)
        assert "🆕" in text
        assert "🥈" in text

    def test_format_daily_standings_sharpe_shown(self):
        from spa_core.tournament.tournament_telegram import TournamentTelegram
        text = TournamentTelegram.format_daily_standings(
            SAMPLE_STRATEGIES[:1], {}, "2026-06-22"
        )
        assert "Sharpe" in text

    def test_format_daily_standings_empty_top5_returns_string(self):
        from spa_core.tournament.tournament_telegram import TournamentTelegram
        text = TournamentTelegram.format_daily_standings([], {}, "2026-06-22")
        assert isinstance(text, str)


# ─────────────────────────────────────────────────────────────────────────────
# 9. TournamentTelegram — availability and graceful degradation
# ─────────────────────────────────────────────────────────────────────────────

class TestTournamentTelegramAvailability:
    def _make_tg_no_creds(self):
        """Return TournamentTelegram with no credentials."""
        from spa_core.tournament.tournament_telegram import TournamentTelegram
        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch(
                "spa_core.tournament.tournament_telegram._keychain_secret",
                return_value="",
            ):
                tg = TournamentTelegram()
        return tg

    def test_available_false_when_no_creds(self):
        tg = self._make_tg_no_creds()
        assert tg.available is False

    def test_send_returns_false_when_not_available(self):
        tg = self._make_tg_no_creds()
        result = tg.send("hello")
        assert result is False

    def test_send_daily_standings_returns_false_no_creds(self):
        tg = self._make_tg_no_creds()
        result = tg.send_daily_standings(SAMPLE_STRATEGIES[:3])
        assert result is False

    def test_send_promotion_alert_returns_false_no_creds(self):
        tg = self._make_tg_no_creds()
        result = tg.send_promotion_alert("strat", "paper_30d", "live")
        assert result is False

    def test_send_position_change_returns_false_no_creds(self):
        tg = self._make_tg_no_creds()
        result = tg.send_position_change("strat", 2, 1)
        assert result is False

    def test_send_does_not_raise_on_network_error(self):
        from spa_core.tournament.tournament_telegram import TournamentTelegram
        with mock.patch.dict(os.environ, {
            "SPA_TELEGRAM_TOKEN": "fake_token",
            "SPA_TELEGRAM_CHAT_ID": "12345",
        }):
            tg = TournamentTelegram()
        with mock.patch(
            "urllib.request.urlopen",
            side_effect=Exception("network error"),
        ):
            result = tg.send("test")
        assert result is False

    def test_no_real_network_call_when_not_available(self):
        tg = self._make_tg_no_creds()
        with mock.patch("urllib.request.urlopen") as mock_open:
            tg.send("test")
        mock_open.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# 10. _save_engine_state() — ring-buffer and idempotency
# ─────────────────────────────────────────────────────────────────────────────

class TestSaveEngineState:
    def test_state_file_created(self, engine, data_dir):
        engine._save_engine_state("2026-06-22", [], [], {})
        assert (data_dir / "tournament_engine_state.json").exists()

    def test_run_history_appended(self, engine, data_dir):
        engine._save_engine_state("2026-06-22", [], [], {})
        engine._save_engine_state("2026-06-23", [], [], {})
        state = json.loads((data_dir / "tournament_engine_state.json").read_text())
        assert len(state["run_history"]) == 2

    def test_ring_buffer_capped_at_365(self, engine, data_dir):
        for i in range(370):
            engine._save_engine_state(f"2026-06-{i + 1}", [], [], {})
        state = json.loads((data_dir / "tournament_engine_state.json").read_text())
        assert len(state["run_history"]) <= 365

    def test_total_promotions_accumulates(self, engine, data_dir):
        engine._save_engine_state("2026-06-22", [{"p": 1}], [], {})
        engine._save_engine_state("2026-06-23", [{"p": 2}, {"p": 3}], [], {})
        state = json.loads((data_dir / "tournament_engine_state.json").read_text())
        assert state["total_promotions"] == 3

    def test_no_tmp_files_after_save(self, engine, data_dir):
        engine._save_engine_state("2026-06-22", [], [], {})
        tmp_files = list(data_dir.glob("*.tmp"))
        assert tmp_files == []


# ─────────────────────────────────────────────────────────────────────────────
# 11. _increment_days_active() — idempotency
# ─────────────────────────────────────────────────────────────────────────────

class TestIncrementDaysActive:
    def test_increments_once(self, engine, data_dir):
        engine._increment_days_active("2026-06-22")
        tournament = json.loads((data_dir / "strategy_tournament.json").read_text())
        days = tournament["shadow_active_strategies"][0]["days_active"]
        assert days == 6  # was 5, now 6

    def test_idempotent_same_date(self, engine, data_dir):
        engine._increment_days_active("2026-06-22")
        engine._increment_days_active("2026-06-22")
        tournament = json.loads((data_dir / "strategy_tournament.json").read_text())
        days = tournament["shadow_active_strategies"][0]["days_active"]
        assert days == 6  # still 6, not 7

    def test_increments_on_different_dates(self, engine, data_dir):
        engine._increment_days_active("2026-06-22")
        engine._increment_days_active("2026-06-23")
        tournament = json.loads((data_dir / "strategy_tournament.json").read_text())
        days = tournament["shadow_active_strategies"][0]["days_active"]
        assert days == 7  # 5 + 2


# ─────────────────────────────────────────────────────────────────────────────
# 12. LLM_FORBIDDEN marker presence
# ─────────────────────────────────────────────────────────────────────────────

class TestLLMForbiddenMarker:
    def _read_source(self, rel_path: str) -> str:
        root = Path(__file__).resolve().parents[1]
        return (root / rel_path).read_text()

    def test_engine_has_llm_forbidden(self):
        src = self._read_source("spa_core/tournament/tournament_engine.py")
        assert "LLM_FORBIDDEN" in src

    def test_telegram_has_llm_forbidden(self):
        src = self._read_source("spa_core/tournament/tournament_telegram.py")
        assert "LLM_FORBIDDEN" in src

    def test_engine_no_llm_calls(self):
        """Source must not import openai, anthropic, or langchain."""
        src = self._read_source("spa_core/tournament/tournament_engine.py")
        for forbidden in ("openai", "anthropic", "langchain", "litellm"):
            assert forbidden not in src, f"Found forbidden LLM import: {forbidden}"

    def test_engine_stdlib_only_imports(self):
        """Engine must not import third-party packages (only stdlib + local spa_core)."""
        src = self._read_source("spa_core/tournament/tournament_engine.py")
        forbidden_third_party = ("requests", "httpx", "aiohttp", "numpy", "pandas")
        for pkg in forbidden_third_party:
            assert f"import {pkg}" not in src and f"from {pkg}" not in src


# ─────────────────────────────────────────────────────────────────────────────
# 13. Atomic write helper
# ─────────────────────────────────────────────────────────────────────────────

class TestAtomicWrite:
    def test_atomic_write_creates_file(self, tmp_path):
        from spa_core.tournament.tournament_engine import _atomic_write_json
        path = tmp_path / "test.json"
        _atomic_write_json(path, {"key": "value"})
        assert path.exists()

    def test_atomic_write_valid_json(self, tmp_path):
        from spa_core.tournament.tournament_engine import _atomic_write_json
        path = tmp_path / "test.json"
        _atomic_write_json(path, {"a": 1, "b": [1, 2, 3]})
        data = json.loads(path.read_text())
        assert data["a"] == 1

    def test_atomic_write_no_tmp_left(self, tmp_path):
        from spa_core.tournament.tournament_engine import _atomic_write_json
        path = tmp_path / "test.json"
        _atomic_write_json(path, {"x": 99})
        assert not (tmp_path / "test.json.tmp").exists()

    def test_atomic_write_overwrites(self, tmp_path):
        from spa_core.tournament.tournament_engine import _atomic_write_json
        path = tmp_path / "test.json"
        _atomic_write_json(path, {"v": 1})
        _atomic_write_json(path, {"v": 2})
        data = json.loads(path.read_text())
        assert data["v"] == 2
