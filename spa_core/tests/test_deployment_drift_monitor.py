"""Deployment-drift guard — origin → production, the hop nobody watched.

Pins the behaviour that would have caught 2026-08-03: three accepted ADRs sat on
``origin/main`` while the daily cycle ran a checkout 409 commits behind on another
branch, still ranking 40 % of the book on a literal.

Offline and deterministic: every test describes a repository state through an
injected ``git_runner`` instead of building a real repo.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from spa_core.monitoring.deployment_drift_monitor import (
    CRITICAL,
    OK,
    STATE_FILENAME,
    UNCHECKED,
    WARNING,
    check_deployment_drift,
    format_report_text,
    run_deployment_drift_monitor,
)


def _runner(*, head="a" * 40, branch="main", remote="a" * 40, diff="",
            counts="0\t0", fail=None):
    """Build a fake git that answers the four questions the guard asks."""
    def run(args, cwd):
        key = " ".join(args)
        if fail and fail in key:
            return False, "boom: {}".format(key)
        if args[:2] == ["rev-parse", "HEAD"]:
            return True, head
        if args[:3] == ["rev-parse", "--abbrev-ref", "HEAD"]:
            return True, branch
        if args[0] == "rev-parse":
            return True, remote
        if args[0] == "fetch":
            return True, ""
        if args[0] == "rev-list":
            return True, counts
        if args[0] == "diff":
            return True, diff
        return True, ""
    return run


def test_matching_checkout_is_ok() -> None:
    rep = check_deployment_drift(repo_root=Path("/x"), git_runner=_runner())
    assert rep.status == OK
    assert "matches" in rep.reasons[0]


def test_money_path_divergence_is_critical() -> None:
    """The real 2026-08-03 shape: risk logic in production is not the reviewed one."""
    rep = check_deployment_drift(
        repo_root=Path("/x"),
        git_runner=_runner(remote="b" * 40, counts="0\t409",
                           diff="spa_core/risk/policy_enforcer.py\nspa_core/allocator/allocator.py"))
    assert rep.status == CRITICAL
    assert rep.money_path_files == [
        "spa_core/allocator/allocator.py", "spa_core/risk/policy_enforcer.py"]
    assert rep.commits_behind == 409
    assert any("NOT the reviewed one" in r for r in rep.reasons)


def test_non_money_path_divergence_is_only_a_warning() -> None:
    """Docs lagging is worth saying; it is not a risk-logic incident."""
    rep = check_deployment_drift(
        repo_root=Path("/x"),
        git_runner=_runner(remote="b" * 40, diff="docs/STATE.md\nREADME.md"))
    assert rep.status == WARNING
    assert rep.money_path_files == []
    assert rep.other_files == ["README.md", "docs/STATE.md"]


def test_wrong_branch_is_flagged_even_when_content_matches() -> None:
    """Identical today, guaranteed to drift tomorrow — delivered work lands on main."""
    rep = check_deployment_drift(
        repo_root=Path("/x"), git_runner=_runner(branch="env-setup-v3"))
    assert rep.status == WARNING
    assert any("not 'main'" in r for r in rep.reasons)


def test_detached_head_is_not_reported_as_a_wrong_branch() -> None:
    rep = check_deployment_drift(repo_root=Path("/x"), git_runner=_runner(branch="HEAD"))
    assert rep.status == OK


@pytest.mark.parametrize("failing", ["rev-parse HEAD", "diff", "fetch"])
def test_anything_undeterminable_is_unchecked_never_ok(failing: str) -> None:
    """The failure this module exists to prevent: reporting OK about a check
    that was never made. A stale or unreadable comparison must say so."""
    rep = check_deployment_drift(
        repo_root=Path("/x"), git_runner=_runner(fail=failing))
    assert rep.status == UNCHECKED
    assert rep.unchecked_reason


def test_fetch_failure_refuses_to_compare_against_a_stale_ref() -> None:
    rep = check_deployment_drift(repo_root=Path("/x"), git_runner=_runner(fail="fetch"))
    assert rep.status == UNCHECKED
    assert "stale ref" in (rep.unchecked_reason or "")


def test_no_fetch_mode_skips_the_refresh() -> None:
    """A caller that already fetched can opt out; the check still runs."""
    rep = check_deployment_drift(
        repo_root=Path("/x"), fetch=False, git_runner=_runner(fail="fetch"))
    assert rep.status == OK


def test_money_path_classification_covers_the_risk_surface() -> None:
    diff = "\n".join([
        "spa_core/risk/policy.py", "spa_core/governance/kill_switch.py",
        "spa_core/adapters/status_reader.py", "spa_core/tuner/portfolio_rebalancer.py",
        "spa_core/paper_trading/cycle_runner.py", "spa_core/paper_trading/risk_gate.py",
        "spa_core/paper_trading/daily_report.py",   # not money-path
        "landing/index.astro",                      # not money-path
    ])
    rep = check_deployment_drift(
        repo_root=Path("/x"), git_runner=_runner(remote="b" * 40, diff=diff))
    assert rep.status == CRITICAL
    assert len(rep.money_path_files) == 6
    assert rep.other_files == ["landing/index.astro",
                               "spa_core/paper_trading/daily_report.py"]


def test_state_file_is_written_and_self_describing(tmp_path: Path) -> None:
    doc = run_deployment_drift_monitor(
        data_dir=tmp_path, repo_root=Path("/x"),
        git_runner=_runner(remote="b" * 40, diff="spa_core/risk/policy.py"))
    on_disk = json.loads((tmp_path / STATE_FILENAME).read_text(encoding="utf-8"))
    assert on_disk == doc
    assert doc["monitor"] == "deployment_drift"
    assert "never pulls" in doc["note"]     # the guard states its own limits
    assert doc["status"] == CRITICAL


def test_monitor_never_mutates_the_checkout() -> None:
    """Read-only by construction: updating production is an owner decision."""
    seen = []

    def run(args, cwd):
        seen.append(args[0])
        return _runner()(args, cwd)

    check_deployment_drift(repo_root=Path("/x"), git_runner=run)
    assert set(seen) <= {"rev-parse", "fetch", "rev-list", "diff"}
    for forbidden in ("pull", "checkout", "reset", "merge", "clean"):
        assert forbidden not in seen


def test_text_report_is_readable(tmp_path: Path) -> None:
    doc = run_deployment_drift_monitor(
        data_dir=tmp_path, repo_root=Path("/x"), write=False,
        git_runner=_runner(branch="env-setup-v3", remote="b" * 40, counts="0\t409",
                           diff="spa_core/risk/policy.py"))
    text = format_report_text(doc)
    assert "CRITICAL" in text and "env-setup-v3" in text and "409" in text
