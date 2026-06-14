"""
Extended go-live tests — covers:
  - Criterion 10: Strategy Tournament (check_tournament_winner)
  - Criterion 11: APY Gap (check_apy_gap)
  - days_remaining() utility
  - run_full_check() now returns 11 criteria
  - daily_check output schema
  - WalletMode enum and mode-aware execute()
  - Activation guard (all criteria must PASS before run_activation succeeds)
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

# Ensure spa_core is on the path
sys.path.insert(0, str(Path(__file__).parent.parent))

from golive.checklist import (
    _FAIL, _PASS, _PENDING, _WARN,
    APY_GAP_MAX, APY_TARGET, GO_LIVE_DATE, MIN_PAPER_DAYS, PAPER_START_DATE,
    check_apy_gap,
    check_tournament_winner,
    days_remaining,
    run_full_check,
)


# ─── Shared fixtures ──────────────────────────────────────────────────────────

@pytest.fixture
def good_tournament_data():
    """Tournament where v1_passive wins decisively."""
    return {
        "winner":         "v1_passive",
        "confidence":     "HIGH",
        "recommendation": "Deploy v1_passive.",
        "scores":         {"v1_passive": 0.85, "v2_aggressive": 0.60},
        "metrics":        {},
    }


@pytest.fixture
def losing_tournament_data():
    """Tournament where v2_aggressive beats v1_passive."""
    return {
        "winner":     "v2_aggressive",
        "confidence": "MEDIUM",
        "scores":     {"v1_passive": 0.45, "v2_aggressive": 0.80},
        "metrics":    {},
    }


@pytest.fixture
def tied_tournament_data():
    """Tournament where both strategies score identically."""
    return {
        "winner":     "v2_aggressive",   # winner key present, but scores tie
        "confidence": "LOW",
        "scores":     {"v1_passive": 0.700, "v2_aggressive": 0.700},
        "metrics":    {},
    }


@pytest.fixture
def good_portfolio():
    return {
        "total_capital_usd": 100_000.0,
        "total_pnl_usd":     138.0,
        "current_apy":       7.5,    # within 2% of 7.3%
    }


@pytest.fixture
def good_analytics():
    """advanced_analytics.json with annualised_return_pct within gap."""
    return {
        "summary": {
            "annualised_return_pct": 7.5,   # within 2% of 7.3%
            "total_return_pct":      0.138,
        },
        "data_points": 5,
    }


@pytest.fixture
def extended_temp_data_dir(tmp_path, good_portfolio, good_tournament_data, good_analytics):
    """Temp data directory with all 11 criteria sources present."""
    ts_fresh = datetime.now(timezone.utc).isoformat()
    files = {
        "status.json": {
            "portfolio": good_portfolio,
            "positions": [
                {"protocol_key": "aave-v3", "amount_usd": 50_000},
                {"protocol_key": "compound", "amount_usd": 50_000},
            ],
            "timestamp": ts_fresh,
        },
        "risk_alerts.json": {"count": 0, "alerts": [], "generated_at": ts_fresh},
        "backtest_results.json": {
            "metrics": {"sharpe_ratio": 2.5},
            "generated_at": ts_fresh,
        },
        "tournament_results.json": good_tournament_data,
        "advanced_analytics.json": good_analytics,
    }
    for name, content in files.items():
        (tmp_path / name).write_text(json.dumps(content), encoding="utf-8")
    return str(tmp_path)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Criterion 10 — Strategy Tournament
# ═══════════════════════════════════════════════════════════════════════════════

class TestCheckTournamentWinner:

    def test_v1_winning_gives_pass(self, good_tournament_data):
        result = check_tournament_winner(good_tournament_data)
        assert result["status"] == _PASS

    def test_v1_losing_gives_fail(self, losing_tournament_data):
        result = check_tournament_winner(losing_tournament_data)
        assert result["status"] == _FAIL

    def test_tied_scores_gives_pass(self, tied_tournament_data):
        """Scores within 0.001 of each other should be treated as a tie → PASS."""
        result = check_tournament_winner(tied_tournament_data)
        assert result["status"] == _PASS

    def test_missing_winner_gives_warn(self):
        """No 'winner' key → WARN (data unavailable), not crash."""
        result = check_tournament_winner({})
        assert result["status"] == _WARN

    def test_returns_required_keys(self, good_tournament_data):
        result = check_tournament_winner(good_tournament_data)
        for key in ("name", "status", "value", "threshold", "note"):
            assert key in result

    def test_name_is_correct(self, good_tournament_data):
        result = check_tournament_winner(good_tournament_data)
        assert result["name"] == "Strategy Tournament"

    def test_low_confidence_still_passes(self):
        data = {
            "winner":     "v1_passive",
            "confidence": "LOW",
            "scores":     {"v1_passive": 0.51, "v2_aggressive": 0.49},
        }
        result = check_tournament_winner(data)
        assert result["status"] == _PASS


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Criterion 11 — APY Gap
# ═══════════════════════════════════════════════════════════════════════════════

class TestCheckApyGap:

    def test_apy_within_gap_passes(self, good_analytics, good_portfolio):
        result = check_apy_gap(good_analytics, good_portfolio)
        assert result["status"] == _PASS

    def test_apy_exactly_at_target_passes(self, good_portfolio):
        analytics = {"summary": {"annualised_return_pct": APY_TARGET}}
        result = check_apy_gap(analytics, good_portfolio)
        assert result["status"] == _PASS

    def test_apy_too_far_below_fails(self, good_portfolio):
        """APY 3.0% is 4.3pp below 7.3% — > 3pp threshold → FAIL."""
        analytics = {"summary": {"annualised_return_pct": 3.0}}
        result = check_apy_gap(analytics, good_portfolio)
        assert result["status"] == _FAIL

    def test_apy_too_far_above_fails(self, good_portfolio):
        """APY 11.0% is 3.7pp above 7.3% — > 3pp threshold → FAIL."""
        analytics = {"summary": {"annualised_return_pct": 11.0}}
        result = check_apy_gap(analytics, good_portfolio)
        assert result["status"] == _FAIL

    def test_apy_in_warn_zone(self, good_portfolio):
        """APY 9.8% is 2.5pp above 7.3% — 2–3pp zone → WARN."""
        analytics = {"summary": {"annualised_return_pct": 9.8}}
        result = check_apy_gap(analytics, good_portfolio)
        assert result["status"] == _WARN

    def test_falls_back_to_portfolio_apy(self):
        """No advanced_analytics → falls back to portfolio.current_apy."""
        portfolio = {"total_capital_usd": 100_000.0, "current_apy": 7.0}
        result = check_apy_gap({}, portfolio)
        assert result["status"] == _PASS   # 7.0 is within 2% of 7.3

    def test_no_data_gives_warn(self):
        """Neither analytics nor portfolio has APY → WARN, not crash."""
        result = check_apy_gap({}, {})
        assert result["status"] == _WARN

    def test_value_is_float(self, good_analytics, good_portfolio):
        result = check_apy_gap(good_analytics, good_portfolio)
        assert isinstance(result["value"], float)

    def test_name_is_correct(self, good_analytics, good_portfolio):
        result = check_apy_gap(good_analytics, good_portfolio)
        assert result["name"] == "APY Gap"


# ═══════════════════════════════════════════════════════════════════════════════
# 3. days_remaining()
# ═══════════════════════════════════════════════════════════════════════════════

class TestDaysRemaining:

    def test_returns_non_negative_int(self):
        dr = days_remaining()
        assert isinstance(dr, int)
        assert dr >= 0

    def test_consistent_with_go_live_date(self):
        """days_remaining should equal (GO_LIVE_DATE - today).days, floored at 0."""
        go_live = datetime.fromisoformat(GO_LIVE_DATE).replace(tzinfo=timezone.utc)
        today   = datetime.now(timezone.utc)
        expected = max(0, (go_live - today).days)
        assert days_remaining() == expected


# ═══════════════════════════════════════════════════════════════════════════════
# 4. run_full_check() — 12 criteria, updated schema (Agent Stability added in
# v2.6; tests realigned in sprint v3.21).
# ═══════════════════════════════════════════════════════════════════════════════

EXPECTED_CRITERIA_COUNT = 12  # v3.21: previously 11; +1 = Agent Stability


class TestRunFullCheckExtended:

    def test_returns_expected_criteria_count(self, extended_temp_data_dir):
        result = run_full_check(extended_temp_data_dir)
        assert len(result["criteria"]) == EXPECTED_CRITERIA_COUNT

    def test_includes_tournament_criterion(self, extended_temp_data_dir):
        result   = run_full_check(extended_temp_data_dir)
        names    = [c["name"] for c in result["criteria"]]
        assert "Strategy Tournament" in names

    def test_includes_apy_gap_criterion(self, extended_temp_data_dir):
        result = run_full_check(extended_temp_data_dir)
        names  = [c["name"] for c in result["criteria"]]
        assert "APY Gap" in names

    def test_paper_duration_pending_not_fail(self, extended_temp_data_dir):
        """Paper Duration should be PENDING (≤50 days) never FAIL on a fresh run."""
        result    = run_full_check(extended_temp_data_dir)
        duration  = next(c for c in result["criteria"] if c["name"] == "Paper Duration")
        assert duration["status"] in (_PASS, _PENDING)
        assert duration["status"] != _FAIL


# ═══════════════════════════════════════════════════════════════════════════════
# 5. daily_check output schema
# ═══════════════════════════════════════════════════════════════════════════════

class TestDailyCheckOutputSchema:

    def test_output_has_required_keys(self, extended_temp_data_dir):
        from golive.daily_check import run_daily_golive_check
        result = run_daily_golive_check(extended_temp_data_dir)
        for key in (
            "verdict", "criteria_passed", "criteria_total",
            "days_remaining", "blocking_criteria", "next_check_date",
        ):
            assert key in result, f"Missing key: {key}"

    def test_criteria_passed_is_int(self, extended_temp_data_dir):
        from golive.daily_check import run_daily_golive_check
        result = run_daily_golive_check(extended_temp_data_dir)
        assert isinstance(result["criteria_passed"], int)

    def test_criteria_total_matches_expected(self, extended_temp_data_dir):
        """Sprint v3.21: criteria_total was bumped 11 → 12 when Agent Stability
        was added.  Test now reads the canonical constant so future additions
        require updating EXPECTED_CRITERIA_COUNT in one place."""
        from golive.daily_check import run_daily_golive_check
        result = run_daily_golive_check(extended_temp_data_dir)
        assert result["criteria_total"] == EXPECTED_CRITERIA_COUNT

    def test_blocking_criteria_is_list(self, extended_temp_data_dir):
        from golive.daily_check import run_daily_golive_check
        result = run_daily_golive_check(extended_temp_data_dir)
        assert isinstance(result["blocking_criteria"], list)

    def test_next_check_date_is_valid_date_string(self, extended_temp_data_dir):
        from golive.daily_check import run_daily_golive_check
        result = run_daily_golive_check(extended_temp_data_dir)
        # Should parse as a valid date
        from datetime import date
        date.fromisoformat(result["next_check_date"])

    def test_does_not_raise_on_empty_dir(self, tmp_path):
        from golive.daily_check import run_daily_golive_check
        result = run_daily_golive_check(str(tmp_path))
        assert "verdict" in result

    def test_writes_json_file(self, extended_temp_data_dir, tmp_path):
        """Verify the JSON file is actually written to disk."""
        from golive.daily_check import run_daily_golive_check
        run_daily_golive_check(extended_temp_data_dir)
        out = Path(extended_temp_data_dir) / "golive_readiness.json"
        assert out.exists()
        data = json.loads(out.read_text())
        assert "verdict" in data


# ═══════════════════════════════════════════════════════════════════════════════
# 6. WalletMode enum and mode-aware execute()
# ═══════════════════════════════════════════════════════════════════════════════

class TestWalletModeEnum:

    def test_paper_mode_accepted(self):
        from execution.wallet import SPAWallet, WalletMode
        wallet = SPAWallet(mode="paper")
        assert wallet.wallet_mode == WalletMode.PAPER

    def test_simulation_mode_accepted(self):
        from execution.wallet import SPAWallet, WalletMode
        wallet = SPAWallet(mode="simulation")
        assert wallet.wallet_mode == WalletMode.SIMULATION

    def test_live_mode_accepted_no_raise_on_init(self):
        """LIVE mode init should NOT raise — only execute() raises."""
        from execution.wallet import SPAWallet, WalletMode
        wallet = SPAWallet(mode="live")
        assert wallet.wallet_mode == WalletMode.LIVE

    def test_invalid_mode_raises_value_error(self):
        from execution.wallet import SPAWallet
        with pytest.raises(ValueError):
            SPAWallet(mode="fantasy")

    def test_case_insensitive_mode(self):
        from execution.wallet import SPAWallet, WalletMode
        wallet = SPAWallet(mode="PAPER")
        assert wallet.wallet_mode == WalletMode.PAPER


class TestWalletExecute:

    def test_paper_mode_execute_returns_dict(self):
        from execution.wallet import SPAWallet
        wallet = SPAWallet(mode="paper")
        result = wallet.execute("aave-v3", "supply", 1_000.0)
        assert isinstance(result, dict)

    def test_simulation_mode_execute_returns_dict(self):
        from execution.wallet import SPAWallet
        wallet = SPAWallet(mode="simulation")
        result = wallet.execute("compound", "withdraw", 500.0)
        assert isinstance(result, dict)

    def test_paper_mode_result_has_status_logged(self):
        from execution.wallet import SPAWallet
        wallet = SPAWallet(mode="paper")
        result = wallet.execute("aave-v3", "supply", 200.0)
        assert result.get("status") == "PAPER_LOGGED"
        assert result.get("real") is False

    def test_simulation_mode_result_has_status_logged(self):
        from execution.wallet import SPAWallet
        wallet = SPAWallet(mode="simulation")
        result = wallet.execute("aave-v3", "supply", 200.0)
        assert result.get("status") == "PAPER_LOGGED"

    def test_live_mode_execute_raises_not_implemented(self):
        from execution.wallet import SPAWallet
        wallet = SPAWallet(mode="live")
        with pytest.raises(NotImplementedError) as exc_info:
            wallet.execute("aave-v3", "supply", 5_000.0)
        assert "activate" in str(exc_info.value).lower()

    def test_live_mode_error_message_mentions_activation_script(self):
        from execution.wallet import SPAWallet
        wallet = SPAWallet(mode="live")
        with pytest.raises(NotImplementedError) as exc_info:
            wallet.execute("aave-v3", "supply", 1_000.0)
        assert "spa_core.golive.activate" in str(exc_info.value)


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Activation guard — all criteria must PASS
# ═══════════════════════════════════════════════════════════════════════════════

class TestActivationGuard:

    def test_activation_fails_when_criteria_not_all_pass(self, tmp_path):
        """With no data files, criteria cannot all PASS — activation must reject."""
        from golive.activate import run_activation
        # Empty tmp_path → most criteria will be WARN/PENDING/FAIL
        result = run_activation(
            data_dir=str(tmp_path),
            _auto_confirm=None,   # won't reach confirmation step
        )
        assert result is False

    def test_activation_fails_with_wrong_confirmation_phrase(self, tmp_path):
        """Even if we could pass criteria, wrong phrase must abort."""
        from golive.activate import run_activation
        # We monkeypatch check_all_criteria_pass to return True for this test
        import golive.activate as act_module
        original = act_module.check_all_criteria_pass

        def _fake_all_pass(data_dir=None):
            # Build a fake result with all PASS criteria
            fake_criteria = [
                {"name": f"C{i}", "status": "PASS", "note": "ok"}
                for i in range(11)
            ]
            fake_result = {
                "criteria": fake_criteria,
                "verdict":  "READY",
            }
            return True, fake_result

        act_module.check_all_criteria_pass = _fake_all_pass
        try:
            result = run_activation(
                data_dir=str(tmp_path),
                _auto_confirm="wrong phrase",
            )
        finally:
            act_module.check_all_criteria_pass = original

        assert result is False

    def test_activation_succeeds_with_correct_confirmation(self, tmp_path):
        """All criteria PASS + correct phrase → success and record written."""
        from golive.activate import run_activation, CONFIRMATION_PHRASE
        import golive.activate as act_module
        original = act_module.check_all_criteria_pass

        def _fake_all_pass(data_dir=None):
            fake_criteria = [
                {"name": f"C{i}", "status": "PASS", "note": "ok"}
                for i in range(11)
            ]
            return True, {"criteria": fake_criteria, "verdict": "READY"}

        act_module.check_all_criteria_pass = _fake_all_pass
        try:
            result = run_activation(
                data_dir=str(tmp_path),
                _auto_confirm=CONFIRMATION_PHRASE,
            )
        finally:
            act_module.check_all_criteria_pass = original

        assert result is True
        # Activation record should be written
        record_path = tmp_path / "activation_record.json"
        assert record_path.exists()
        record = json.loads(record_path.read_text())
        assert "activated_at" in record
        assert record["criteria_total"] == 11

    def test_is_activated_false_before_activation(self, tmp_path):
        from golive.activate import is_activated
        assert is_activated(str(tmp_path)) is False

    def test_is_activated_true_after_activation(self, tmp_path):
        from golive.activate import is_activated, run_activation, CONFIRMATION_PHRASE
        import golive.activate as act_module
        original = act_module.check_all_criteria_pass

        def _fake_all_pass(data_dir=None):
            fake_criteria = [
                {"name": f"C{i}", "status": "PASS", "note": "ok"}
                for i in range(11)
            ]
            return True, {"criteria": fake_criteria, "verdict": "READY"}

        act_module.check_all_criteria_pass = _fake_all_pass
        try:
            run_activation(
                data_dir=str(tmp_path),
                _auto_confirm=CONFIRMATION_PHRASE,
            )
        finally:
            act_module.check_all_criteria_pass = original

        assert is_activated(str(tmp_path)) is True


# ═══════════════════════════════════════════════════════════════════════════════
# 8. SPA-V365 — persistent checklist-verdict history / trend
#    (golive/daily_check.append_checklist_history) — mirrors
#    test_readiness_score.TestAppendHistory.
# ═══════════════════════════════════════════════════════════════════════════════

class TestAppendChecklistHistory:
    """append_checklist_history: compact append-only log, dedup, trim, never-raise."""

    def _payload(self, checked_at, passed=8, total=12, verdict="ALMOST_READY"):
        return {
            "checked_at": checked_at,
            "verdict": verdict,
            "criteria_passed": passed,
            "criteria_total": total,
            # extra keys that must NOT leak into the compact record:
            "criteria": [{"name": "C0", "status": "PASS"}],
            "days_remaining": 45,
        }

    def test_first_call_creates_file_with_one_record(self, tmp_path):
        from golive import daily_check as dc
        dc.append_checklist_history(self._payload("2026-05-31T00:00:00Z"),
                                    data_dir=str(tmp_path))
        target = tmp_path / dc.HISTORY_FILENAME
        assert target.exists()
        history = json.loads(target.read_text(encoding="utf-8"))
        assert isinstance(history, list)
        assert len(history) == 1
        assert history[0]["criteria_passed"] == 8

    def test_second_distinct_timestamp_appends(self, tmp_path):
        from golive import daily_check as dc
        dc.append_checklist_history(self._payload("2026-05-31T00:00:00Z"),
                                    data_dir=str(tmp_path))
        dc.append_checklist_history(self._payload("2026-05-31T04:00:00Z", passed=10),
                                    data_dir=str(tmp_path))
        history = json.loads(
            (tmp_path / dc.HISTORY_FILENAME).read_text(encoding="utf-8"))
        assert len(history) == 2
        assert history[-1]["criteria_passed"] == 10

    def test_same_timestamp_replaces_not_duplicates(self, tmp_path):
        from golive import daily_check as dc
        dc.append_checklist_history(self._payload("2026-05-31T00:00:00Z", passed=8),
                                    data_dir=str(tmp_path))
        dc.append_checklist_history(self._payload("2026-05-31T00:00:00Z", passed=12,
                                                  verdict="READY"),
                                    data_dir=str(tmp_path))
        history = json.loads(
            (tmp_path / dc.HISTORY_FILENAME).read_text(encoding="utf-8"))
        assert len(history) == 1
        assert history[0]["criteria_passed"] == 12
        assert history[0]["verdict"] == "READY"

    def test_trims_to_max_history_keeping_latest(self, tmp_path):
        from golive import daily_check as dc
        n = dc.MAX_HISTORY + 25
        for i in range(n):
            dc.append_checklist_history(
                self._payload(f"2026-05-31T{i:05d}", passed=i),
                data_dir=str(tmp_path),
            )
        history = json.loads(
            (tmp_path / dc.HISTORY_FILENAME).read_text(encoding="utf-8"))
        assert len(history) == dc.MAX_HISTORY
        # most recent survives; oldest were trimmed off the front
        assert history[-1]["criteria_passed"] == n - 1
        assert history[0]["criteria_passed"] == n - dc.MAX_HISTORY

    def test_never_raises_on_corrupt_existing_file(self, tmp_path):
        from golive import daily_check as dc
        target = tmp_path / dc.HISTORY_FILENAME
        target.write_text("not json {{{", encoding="utf-8")
        # must not raise, and must overwrite with a valid single-record list
        dc.append_checklist_history(self._payload("2026-05-31T00:00:00Z"),
                                    data_dir=str(tmp_path))
        history = json.loads(target.read_text(encoding="utf-8"))
        assert isinstance(history, list)
        assert len(history) == 1

    def test_record_is_compact(self, tmp_path):
        from golive import daily_check as dc
        dc.append_checklist_history(self._payload("2026-05-31T00:00:00Z"),
                                    data_dir=str(tmp_path))
        history = json.loads(
            (tmp_path / dc.HISTORY_FILENAME).read_text(encoding="utf-8"))
        assert set(history[0].keys()) == {
            "checked_at", "verdict", "criteria_passed", "criteria_total"}

    def test_falls_back_to_generated_at_when_no_checked_at(self, tmp_path):
        from golive import daily_check as dc
        payload = {
            "generated_at": "2026-05-31T09:00:00Z",
            "verdict": "NOT_READY",
            "criteria_passed": 5,
            "criteria_total": 12,
        }
        dc.append_checklist_history(payload, data_dir=str(tmp_path))
        history = json.loads(
            (tmp_path / dc.HISTORY_FILENAME).read_text(encoding="utf-8"))
        assert history[0]["checked_at"] == "2026-05-31T09:00:00Z"

    def test_run_daily_check_writes_main_and_history(self, tmp_path):
        """run_daily_golive_check writes BOTH golive_readiness.json AND the
        compact golive_readiness_history.json next to it."""
        from golive.daily_check import run_daily_golive_check
        from golive import daily_check as dc
        run_daily_golive_check(str(tmp_path))
        main = tmp_path / "golive_readiness.json"
        hist = tmp_path / dc.HISTORY_FILENAME
        assert main.exists()
        assert hist.exists()
        history = json.loads(hist.read_text(encoding="utf-8"))
        assert isinstance(history, list)
        assert len(history) >= 1
        assert set(history[-1].keys()) == {
            "checked_at", "verdict", "criteria_passed", "criteria_total"}
