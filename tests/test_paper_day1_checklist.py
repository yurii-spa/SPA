"""
tests/test_paper_day1_checklist.py

MP-1428 (v10.44): 30 tests for PaperDay1Checklist.

Verifies:
  - Class is importable and instantiates
  - Each check method returns correct schema
  - run_all() aggregates correctly
  - to_markdown() and print_report() work
  - Safety-critical checks behave correctly

stdlib only, no external dependencies.
"""
from __future__ import annotations

import os
import sys
import io
from pathlib import Path
from typing import Any, Dict

import pytest

# ── Repo root ─────────────────────────────────────────────────────────────────
REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO))

from spa_core.backtesting.paper_day1_checklist import PaperDay1Checklist


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def checklist():
    """A PaperDay1Checklist instance pointed at the real repo root."""
    return PaperDay1Checklist(base_dir=str(REPO))


@pytest.fixture(scope="module")
def all_results(checklist):
    """Full run_all() result, computed once."""
    return checklist.run_all()


# ════════════════════════════════════════════════════════════════════════════
# Group 1: Instantiation & structure
# ════════════════════════════════════════════════════════════════════════════

class TestInstantiation:
    """T01–T05: PaperDay1Checklist creates correctly."""

    def test_can_import(self):
        """T01: PaperDay1Checklist is importable"""
        from spa_core.backtesting.paper_day1_checklist import PaperDay1Checklist
        assert PaperDay1Checklist is not None

    def test_default_instantiation(self):
        """T02: Instantiates with no arguments"""
        c = PaperDay1Checklist()
        assert c is not None

    def test_custom_base_dir(self):
        """T03: Accepts base_dir parameter"""
        c = PaperDay1Checklist(base_dir=str(REPO))
        assert c is not None

    def test_has_run_all(self, checklist):
        """T04: has run_all() method"""
        assert callable(getattr(checklist, "run_all", None))

    def test_has_print_report(self, checklist):
        """T05: has print_report() method"""
        assert callable(getattr(checklist, "print_report", None))


# ════════════════════════════════════════════════════════════════════════════
# Group 2: Individual check method schemas
# ════════════════════════════════════════════════════════════════════════════

def _assert_check_schema(result: Dict[str, Any], name: str) -> None:
    """Helper: verify check result has required keys."""
    assert isinstance(result, dict), f"{name}: must return dict"
    assert "pass" in result, f"{name}: missing 'pass' key"
    assert "critical" in result, f"{name}: missing 'critical' key"
    assert "detail" in result, f"{name}: missing 'detail' key"
    assert isinstance(result["pass"], bool), f"{name}: 'pass' must be bool"
    assert isinstance(result["critical"], bool), f"{name}: 'critical' must be bool"
    assert isinstance(result["detail"], str), f"{name}: 'detail' must be str"


class TestIndividualChecks:
    """T06–T16: Each check method returns valid schema."""

    def test_check_evidence_calculator_schema(self, checklist):
        """T06: check_evidence_calculator() returns valid schema"""
        r = checklist.check_evidence_calculator()
        _assert_check_schema(r, "evidence_calculator")

    def test_check_cycle_with_evidence_schema(self, checklist):
        """T07: check_cycle_with_evidence() returns valid schema"""
        r = checklist.check_cycle_with_evidence()
        _assert_check_schema(r, "cycle_with_evidence")

    def test_check_telegram_bot_schema(self, checklist):
        """T08: check_telegram_bot() returns valid schema (even if Keychain absent)"""
        r = checklist.check_telegram_bot()
        _assert_check_schema(r, "telegram_bot")

    def test_check_telegram_bot_is_advisory(self, checklist):
        """T09: Telegram check is non-critical (advisory only)"""
        r = checklist.check_telegram_bot()
        assert r["critical"] is False, "Telegram check must be advisory (CI has no Keychain)"

    def test_check_launchd_plist_schema(self, checklist):
        """T10: check_launchd_plist() returns valid schema"""
        r = checklist.check_launchd_plist()
        _assert_check_schema(r, "launchd_plist")

    def test_check_launchd_plist_passes(self, checklist):
        """T11: launchd plist check passes (plist exists and is correct)"""
        r = checklist.check_launchd_plist()
        assert r["pass"] is True, f"launchd_plist failed: {r['detail']}"

    def test_check_live_trading_gate_schema(self, checklist):
        """T12: check_live_trading_gate() returns valid schema"""
        r = checklist.check_live_trading_gate()
        _assert_check_schema(r, "live_trading_gate")

    def test_check_live_trading_gate_is_locked(self, checklist):
        """T13: LiveTradingGate check passes — gate is LOCKED (safe for paper trading)"""
        r = checklist.check_live_trading_gate()
        assert r["pass"] is True, (
            f"LiveTradingGate is not locked — DANGEROUS for paper trading! "
            f"Detail: {r['detail']}"
        )

    def test_check_data_directories_schema(self, checklist):
        """T14: check_data_directories() returns valid schema"""
        r = checklist.check_data_directories()
        _assert_check_schema(r, "data_directories")

    def test_check_kill_switch_schema(self, checklist):
        """T15: check_kill_switch() returns valid schema"""
        r = checklist.check_kill_switch()
        _assert_check_schema(r, "kill_switch")

    def test_check_adapter_registry_schema(self, checklist):
        """T16: check_adapter_registry() returns valid schema"""
        r = checklist.check_adapter_registry()
        _assert_check_schema(r, "adapter_registry")


# ════════════════════════════════════════════════════════════════════════════
# Group 3: run_all() structure and aggregation
# ════════════════════════════════════════════════════════════════════════════

class TestRunAll:
    """T17–T24: run_all() aggregates results correctly."""

    def test_run_all_returns_dict(self, all_results):
        """T17: run_all() returns a dict"""
        assert isinstance(all_results, dict)

    def test_run_all_has_all_critical_pass(self, all_results):
        """T18: run_all() contains 'all_critical_pass' bool"""
        assert "all_critical_pass" in all_results
        assert isinstance(all_results["all_critical_pass"], bool)

    def test_run_all_has_checks(self, all_results):
        """T19: run_all() contains 'checks' dict"""
        assert "checks" in all_results
        assert isinstance(all_results["checks"], dict)

    def test_run_all_checks_count(self, all_results):
        """T20: run_all() contains all 8 checks"""
        assert len(all_results["checks"]) == 8

    def test_run_all_has_critical_counts(self, all_results):
        """T21: run_all() contains critical pass counts"""
        assert "critical_pass_count" in all_results
        assert "critical_total" in all_results

    def test_run_all_has_advisory_counts(self, all_results):
        """T22: run_all() contains advisory counts"""
        assert "advisory_pass_count" in all_results
        assert "advisory_total" in all_results

    def test_run_all_checks_have_schema(self, all_results):
        """T23: every check in run_all() has pass/critical/detail"""
        for name, check in all_results["checks"].items():
            assert "pass" in check, f"{name}: missing 'pass'"
            assert "critical" in check, f"{name}: missing 'critical'"
            assert "detail" in check, f"{name}: missing 'detail'"

    def test_run_all_critical_total_correct(self, all_results):
        """T24: critical_total matches sum of critical checks"""
        checks = all_results["checks"].values()
        expected = sum(1 for c in checks if c.get("critical", True))
        assert all_results["critical_total"] == expected


# ════════════════════════════════════════════════════════════════════════════
# Group 4: to_markdown() and print_report()
# ════════════════════════════════════════════════════════════════════════════

class TestReporting:
    """T25–T30: Reporting methods produce correct output."""

    def test_to_markdown_returns_str(self, checklist):
        """T25: to_markdown() returns a string"""
        md = checklist.to_markdown()
        assert isinstance(md, str)

    def test_to_markdown_contains_checkmarks(self, checklist):
        """T26: to_markdown() contains ✅ or ❌"""
        md = checklist.to_markdown()
        assert "✅" in md or "❌" in md, "Markdown must contain ✅ or ❌"

    def test_to_markdown_contains_status_header(self, checklist):
        """T27: to_markdown() contains readiness status header"""
        md = checklist.to_markdown()
        assert "Day 1 Readiness" in md or "Readiness" in md

    def test_to_markdown_contains_check_names(self, checklist):
        """T28: to_markdown() mentions key checks by name"""
        md = checklist.to_markdown()
        assert "live_trading_gate" in md or "adapter_registry" in md

    def test_print_report_outputs_to_stdout(self, checklist, capsys):
        """T29: print_report() writes output to stdout"""
        checklist.print_report()
        captured = capsys.readouterr()
        assert len(captured.out) > 0, "print_report() produced no output"

    def test_print_report_shows_pass_or_fail(self, checklist, capsys):
        """T30: print_report() output contains ✅ or ❌"""
        checklist.print_report()
        captured = capsys.readouterr()
        assert "✅" in captured.out or "❌" in captured.out
