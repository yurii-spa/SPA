"""
tests/test_pre_launch_v2.py — MP-1483 (v10.99)

20 tests covering PreLaunchValidation: group runners, check semantics,
blocking vs warning classification, report structure, and markdown output.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from spa_core.backtesting.pre_launch_validation import (
    PreLaunchValidation,
    ValidationCheck,
    ValidationReport,
    VALIDATION_GROUPS,
    SCHEMA_VERSION,
)


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture()
def base_dir(tmp_path):
    """Minimal filesystem tree so all checks can run without crashing."""
    # data/
    data = tmp_path / "data"
    data.mkdir()
    (data / "backtest").mkdir()

    # data/backtest gate files
    (data / "backtest" / "pre_paper_backtest_gate.json").write_text(
        json.dumps({"status": "PASS"}), encoding="utf-8"
    )
    (data / "backtest" / "paper_ready_gate.json").write_text(
        json.dumps({"paper_trading_allowed": True, "status": "READY"}), encoding="utf-8"
    )
    (data / "backtest" / "owner_paper_acceptance_gate.json").write_text(
        json.dumps({"accepted": True, "owner": "Yurii", "accepted_at": "2026-06-20"}),
        encoding="utf-8",
    )

    # data/golive_status.json — 24/26 pass
    (data / "golive_status.json").write_text(
        json.dumps({"passed": 24, "total": 26, "ready": False}), encoding="utf-8"
    )

    # equity curve — 30 real days
    daily = []
    nav = 100_000.0
    for i in range(30):
        from datetime import date, timedelta
        d = (date(2026, 5, 21) + timedelta(days=i)).isoformat()
        nav += 10.8
        daily.append({"date": d, "equity": round(nav, 2), "nav": round(nav, 2),
                       "drawdown_pct": 0.0})
    (data / "equity_curve_daily.json").write_text(
        json.dumps({"daily": daily, "is_demo": False}), encoding="utf-8"
    )

    # trades
    (data / "trades.json").write_text(
        json.dumps([{"id": "t1", "is_demo": False}]), encoding="utf-8"
    )

    # paper_trading_status
    (data / "paper_trading_status.json").write_text(
        json.dumps({
            "is_demo": False,
            "current_apy": 0.03943,
            "portfolio_nav": 100_325.0,
        }),
        encoding="utf-8",
    )

    # gap_monitor
    (data / "gap_monitor.json").write_text(
        json.dumps({"status": "ok", "gaps": [], "real_track_days": 30}),
        encoding="utf-8",
    )

    # adapter_status
    (data / "adapter_status.json").write_text(
        json.dumps({
            "compound_v3": {"status": "ok"},
            "morpho_steakhouse": {"status": "ok"},
            "aave_arbitrum": {"status": "ok"},
        }),
        encoding="utf-8",
    )

    # docs/
    docs = tmp_path / "docs"
    docs.mkdir()
    adr = docs / "adr"
    adr.mkdir()
    (adr / "ADR-002-golive-transfer-rule.md").write_text("# ADR-002", encoding="utf-8")
    legal = docs / "legal"
    legal.mkdir()
    (legal / "investment_agreement.md").write_text("# Agreement", encoding="utf-8")
    (tmp_path / "DR_PROCEDURE_v2.md").write_text("# DR", encoding="utf-8")
    (tmp_path / "MASTER_PLAN_v1.md").write_text("# MP", encoding="utf-8")

    # scripts/
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "kill_switch_drill.py").write_text("# kill", encoding="utf-8")
    (scripts / "gnosis_safe_checklist.py").write_text("# gnosis", encoding="utf-8")
    (scripts / "com.spa.autopush.plist").write_text("<plist/>", encoding="utf-8")
    (scripts / "com.spa.httpserver.plist").write_text("<plist/>", encoding="utf-8")
    (scripts / "com.spa.cloudflared.plist").write_text("<plist/>", encoding="utf-8")

    # push_to_github.py
    (tmp_path / "push_to_github.py").write_text("# push", encoding="utf-8")

    # spa_core/ structure (stubs)
    spa = tmp_path / "spa_core"
    adapters = spa / "adapters"
    adapters.mkdir(parents=True)
    (adapters / "__init__.py").write_text("ADAPTER_REGISTRY = {}", encoding="utf-8")
    (adapters / "aave_v3.py").write_text("", encoding="utf-8")
    (adapters / "compound_v3.py").write_text("", encoding="utf-8")
    (adapters / "morpho_steakhouse_adapter.py").write_text("", encoding="utf-8")
    (adapters / "defillama_feed.py").write_text("import urllib.request", encoding="utf-8")

    strategies = spa / "strategies"
    strategies.mkdir()
    (strategies / "strategy_registry.py").write_text("", encoding="utf-8")

    paper = spa / "paper_trading"
    paper.mkdir()
    (paper / "multi_strategy_runner.py").write_text("", encoding="utf-8")
    (paper / "tournament_evaluator.py").write_text("", encoding="utf-8")
    (paper / "cycle_runner.py").write_text("", encoding="utf-8")

    analytics = spa / "analytics"
    analytics.mkdir()
    (analytics / "rs001_live_apy_engine.py").write_text("", encoding="utf-8")
    (analytics / "rs002_live_apy_engine.py").write_text("", encoding="utf-8")
    (analytics / "investment_memo_generator.py").write_text("", encoding="utf-8")

    risk = spa / "risk"
    risk.mkdir()
    (risk / "policy.py").write_text("VERSION = 'v1.0'", encoding="utf-8")

    family_fund = spa / "family_fund"
    family_fund.mkdir()
    (family_fund / "registry.py").write_text("", encoding="utf-8")

    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    for i in range(12):
        (tests_dir / f"test_module_{i:02d}.py").write_text("", encoding="utf-8")

    core_tests = spa / "tests"
    core_tests.mkdir()
    for i in range(60):
        (core_tests / f"test_core_{i:03d}.py").write_text("", encoding="utf-8")

    return tmp_path


@pytest.fixture()
def validator(base_dir):
    return PreLaunchValidation(base_dir=str(base_dir))


# ── 1. Report structure ────────────────────────────────────────────────────────

def test_run_all_returns_validation_report(validator):
    r = validator.run_all()
    assert isinstance(r, ValidationReport)


def test_report_has_total_40(validator):
    r = validator.run_all()
    assert r.total_count == 40


def test_report_schema_version(validator):
    r = validator.run_all()
    assert r.schema_version == SCHEMA_VERSION


def test_report_generated_at_nonempty(validator):
    r = validator.run_all()
    assert r.generated_at


def test_to_dict_round_trip(validator):
    r = validator.run_all()
    d = r.to_dict()
    assert d["total_count"] == r.total_count
    assert d["passed_count"] == r.passed_count
    assert len(d["checks"]) == r.total_count


# ── 2. Group coverage ──────────────────────────────────────────────────────────

def test_all_groups_represented(validator):
    r = validator.run_all()
    groups_seen = {c.group for c in r.checks}
    assert groups_seen == set(VALIDATION_GROUPS)


def test_run_group_returns_list(validator):
    for g in VALIDATION_GROUPS:
        result = validator.run_group(g)
        assert isinstance(result, list)
        assert all(isinstance(c, ValidationCheck) for c in result)


def test_run_group_unknown_raises(validator):
    with pytest.raises(ValueError):
        validator.run_group("nonexistent_group")


# ── 3. Gate checks ────────────────────────────────────────────────────────────

def test_pre_paper_gate_pass(validator):
    r = validator.run_all()
    c = next(x for x in r.checks if x.name == "pre_paper_gate_pass")
    assert c.passed is True


def test_paper_ready_gate_pass(validator):
    r = validator.run_all()
    c = next(x for x in r.checks if x.name == "paper_ready_gate_pass")
    assert c.passed is True


def test_paper_ready_gate_fail_when_false(base_dir):
    (base_dir / "data" / "backtest" / "paper_ready_gate.json").write_text(
        json.dumps({"paper_trading_allowed": False}), encoding="utf-8"
    )
    v = PreLaunchValidation(base_dir=str(base_dir))
    r = v.run_all()
    c = next(x for x in r.checks if x.name == "paper_ready_gate_pass")
    assert c.passed is False
    assert c.blocking is True


def test_owner_acceptance_signed(validator):
    r = validator.run_all()
    c = next(x for x in r.checks if x.name == "owner_acceptance_signed")
    assert c.passed is True


# ── 4. Evidence checks ────────────────────────────────────────────────────────

def test_equity_curve_30_days(validator):
    r = validator.run_all()
    c = next(x for x in r.checks if x.name == "equity_curve_30_days")
    assert c.passed is True


def test_drawdown_below_kill_switch(validator):
    r = validator.run_all()
    c = next(x for x in r.checks if x.name == "drawdown_below_kill_switch")
    assert c.passed is True


def test_no_demo_trades(validator):
    r = validator.run_all()
    c = next(x for x in r.checks if x.name == "no_demo_trades")
    assert c.passed is True


def test_gap_monitor_clean(validator):
    r = validator.run_all()
    c = next(x for x in r.checks if x.name == "gap_monitor_30d_clean")
    assert c.passed is True


# ── 5. Blocking vs warning semantics ─────────────────────────────────────────

def test_blocking_checks_list(validator):
    validator.run_all()
    bl = validator.blocking_checks()
    assert isinstance(bl, list)
    # In a passing fixture there should be 0 blockers
    assert len(bl) == 0


def test_markdown_output_contains_status(validator):
    r = validator.run_all()
    md = validator.to_markdown(r)
    assert "LAUNCH_READY" in md or "NOT_READY" in md


def test_save_writes_json(validator, tmp_path):
    r = validator.run_all()
    path = validator.save(r)
    assert Path(path).exists()
    with open(path) as f:
        saved = json.load(f)
    assert saved["total_count"] == 40


def test_no_external_runtime_deps(validator):
    """Regex-based check must not false-positive on string literals in the checker itself."""
    r = validator.run_all()
    c = next(x for x in r.checks if x.name == "no_external_runtime_deps")
    # Fixture files contain no real 'import requests' etc → must pass
    assert c.passed is True
