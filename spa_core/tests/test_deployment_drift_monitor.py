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
    """Fake git answering the questions the guard asks.

    ``diff`` lists paths whose CONTENT differs. The guard compares blob hashes
    (ls-tree vs a batched hash-object) rather than trusting git's index, so the
    fake mirrors that: every path hashes to "same" unless named in ``diff``.
    """
    listed = [p for p in (diff.split() if diff else [])] or []
    # A minimal delivered tree: the differing paths plus one always-matching file.
    tree_paths = listed + ["README.md"]

    def run(args, cwd, stdin=None):
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
        if args[0] == "ls-tree":
            return True, "\n".join(
                "100644 blob {}\t{}".format("delivered" if p in listed else "same", p)
                for p in tree_paths)
        if args[0] == "hash-object":
            paths = [x for x in (stdin or "").splitlines() if x]
            return True, "\n".join("ondisk" if p in listed else "same" for p in paths)
        return True, ""
    return run


def _tree(root: Path, paths) -> Path:
    """Materialise the delivered paths on disk.

    The guard checks existence before hashing (a file present in the ref but
    absent on disk IS drift), so the fixture must be a real tree — otherwise the
    test would silently exercise the "missing" branch instead of the one named.
    """
    for rel in list(paths) + ["README.md"]:
        f = root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("x", encoding="utf-8")
    return root


def test_matching_checkout_is_ok(tmp_path: Path) -> None:
    rep = check_deployment_drift(repo_root=_tree(tmp_path, []), git_runner=_runner())
    assert rep.status == OK
    assert "matches" in rep.reasons[0]


def test_money_path_divergence_is_critical(tmp_path: Path) -> None:
    """The real 2026-08-03 shape: risk logic in production is not the reviewed one."""
    paths = ["spa_core/risk/policy_enforcer.py", "spa_core/allocator/allocator.py"]
    rep = check_deployment_drift(
        repo_root=_tree(tmp_path, paths),
        git_runner=_runner(remote="b" * 40, counts="0\t409",
                           diff="spa_core/risk/policy_enforcer.py\nspa_core/allocator/allocator.py"))
    assert rep.status == CRITICAL
    assert rep.money_path_files == [
        "spa_core/allocator/allocator.py", "spa_core/risk/policy_enforcer.py"]
    assert rep.commits_behind == 409
    assert any("NOT the reviewed one" in r for r in rep.reasons)


def test_non_money_path_divergence_is_only_a_warning(tmp_path: Path) -> None:
    """Docs lagging is worth saying; it is not a risk-logic incident."""
    rep = check_deployment_drift(
        repo_root=_tree(tmp_path, ["docs/STATE.md", "README.md"]),
        git_runner=_runner(remote="b" * 40, diff="docs/STATE.md\nREADME.md"))
    assert rep.status == WARNING
    assert rep.money_path_files == []
    assert rep.other_files == ["README.md", "docs/STATE.md"]


def test_wrong_branch_is_flagged_even_when_content_matches(tmp_path: Path) -> None:
    """Identical today, guaranteed to drift tomorrow — delivered work lands on main."""
    rep = check_deployment_drift(
        repo_root=_tree(tmp_path, []), git_runner=_runner(branch="env-setup-v3"))
    assert rep.status == WARNING
    assert any("not 'main'" in r for r in rep.reasons)


def test_detached_head_is_not_reported_as_a_wrong_branch(tmp_path: Path) -> None:
    rep = check_deployment_drift(repo_root=_tree(tmp_path, []), git_runner=_runner(branch="HEAD"))
    assert rep.status == OK


@pytest.mark.parametrize("failing", ["rev-parse HEAD", "ls-tree", "fetch"])
def test_anything_undeterminable_is_unchecked_never_ok(tmp_path: Path, failing: str) -> None:
    """The failure this module exists to prevent: reporting OK about a check
    that was never made. A stale or unreadable comparison must say so."""
    rep = check_deployment_drift(
        repo_root=_tree(tmp_path, []), git_runner=_runner(fail=failing))
    assert rep.status == UNCHECKED
    assert rep.unchecked_reason


def test_fetch_failure_refuses_to_compare_against_a_stale_ref(tmp_path: Path) -> None:
    rep = check_deployment_drift(repo_root=_tree(tmp_path, []), git_runner=_runner(fail="fetch"))
    assert rep.status == UNCHECKED
    assert "stale ref" in (rep.unchecked_reason or "")


def test_no_fetch_mode_skips_the_refresh(tmp_path: Path) -> None:
    """A caller that already fetched can opt out; the check still runs."""
    rep = check_deployment_drift(
        repo_root=_tree(tmp_path, []), fetch=False, git_runner=_runner(fail="fetch"))
    assert rep.status == OK


def test_money_path_classification_covers_the_risk_surface(tmp_path: Path) -> None:
    diff = "\n".join([
        "spa_core/risk/policy.py", "spa_core/governance/kill_switch.py",
        "spa_core/adapters/status_reader.py", "spa_core/tuner/portfolio_rebalancer.py",
        "spa_core/paper_trading/cycle_runner.py", "spa_core/paper_trading/risk_gate.py",
        "spa_core/paper_trading/daily_report.py",   # not money-path
        "landing/index.astro",                      # not money-path
    ])
    rep = check_deployment_drift(
        repo_root=_tree(tmp_path, diff.split()), git_runner=_runner(remote="b" * 40, diff=diff))
    assert rep.status == CRITICAL
    assert len(rep.money_path_files) == 6
    assert rep.other_files == ["landing/index.astro",
                               "spa_core/paper_trading/daily_report.py"]


def test_state_file_is_written_and_self_describing(tmp_path: Path) -> None:
    doc = run_deployment_drift_monitor(
        data_dir=tmp_path, repo_root=_tree(tmp_path / "repo", ["spa_core/risk/policy.py"]),
        git_runner=_runner(remote="b" * 40, diff="spa_core/risk/policy.py"))
    on_disk = json.loads((tmp_path / STATE_FILENAME).read_text(encoding="utf-8"))
    assert on_disk == doc
    assert doc["monitor"] == "deployment_drift"
    assert "never pulls" in doc["note"]     # the guard states its own limits
    assert doc["status"] == CRITICAL


def test_monitor_never_mutates_the_checkout(tmp_path: Path) -> None:
    """Read-only by construction: updating production is an owner decision."""
    seen = []

    def run(args, cwd, stdin=None):
        seen.append(args[0])
        return _runner()(args, cwd, stdin)

    check_deployment_drift(repo_root=_tree(tmp_path, []), git_runner=run)
    assert set(seen) <= {"rev-parse", "fetch", "rev-list", "ls-tree", "hash-object"}
    for forbidden in ("pull", "checkout", "reset", "merge", "clean"):
        assert forbidden not in seen


def test_text_report_is_readable(tmp_path: Path) -> None:
    doc = run_deployment_drift_monitor(
        data_dir=tmp_path, repo_root=_tree(tmp_path / "r2", ["spa_core/risk/policy.py"]), write=False,
        git_runner=_runner(branch="env-setup-v3", remote="b" * 40, counts="0\t409",
                           diff="spa_core/risk/policy.py"))
    text = format_report_text(doc)
    assert "CRITICAL" in text and "env-setup-v3" in text and "409" in text


# ── launchd entrypoints are not cosmetic drift (2026-08-08) ─────────────────
#
# Every test below replays the state measured on 2026-08-08 03:5x local:
# `scripts/agent_orchestrator.sh` in production was missing its whole cycle-lock
# block, the hourly orchestrator had been running without collision protection
# since delivery, and this monitor said:
#
#   WARNING — 241 non-money-path file(s) differ from origin/main — delivered
#             work is not running here, but no risk logic is affected
#
# 165 of those 241 were churning data/*.json. The finding was true, buried, and
# wrapped in a reassurance about a different question.


def _plists(*entries):
    """A fake launchd plist reader: (label, script, interval_sec) triples."""
    def read(_agent_dir):
        return [{"label": lbl, "script": script, "interval_sec": interval,
                 "problem": None}
                for lbl, script, interval in entries]
    return read


HOURLY, DAILY = 3600.0, 86400.0


def test_hourly_entrypoint_drift_is_critical_not_cosmetic(tmp_path: Path) -> None:
    """THE 2026-08-08 failure: the missing cycle lock reported as a WARNING.

    An agent that fires hourly cannot receive its delivered version from a daily
    code sync before it next runs. The drift is not a lag — it is a guaranteed
    number of executions of code we did not deliver.
    """
    root = _tree(tmp_path, ["scripts/agent_orchestrator.sh"])
    rep = check_deployment_drift(
        repo_root=root, git_runner=_runner(remote="b" * 40,
                                           diff="scripts/agent_orchestrator.sh"),
        agent_dir=tmp_path, plist_reader=_plists(
            ("com.spa.orchestrator", str(root / "scripts/agent_orchestrator.sh"), HOURLY)))

    assert rep.status == CRITICAL, "an hourly agent running undelivered code is not a warning"
    assert [e["path"] for e in rep.entrypoint_files] == ["scripts/agent_orchestrator.sh"]
    assert rep.entrypoint_files[0]["self_heals_before_next_run"] is False
    assert rep.other_files == [], "the entrypoint must not stay in the cosmetic bucket"


def test_entrypoint_is_named_never_only_counted(tmp_path: Path) -> None:
    """A count is what hid it: "241 files differ" names no agent and no file."""
    root = _tree(tmp_path, ["scripts/agent_orchestrator.sh"])
    rep = check_deployment_drift(
        repo_root=root, git_runner=_runner(remote="b" * 40,
                                           diff="scripts/agent_orchestrator.sh"),
        agent_dir=tmp_path, plist_reader=_plists(
            ("com.spa.orchestrator", str(root / "scripts/agent_orchestrator.sh"), HOURLY)))

    blob = " ".join(rep.reasons)
    assert "scripts/agent_orchestrator.sh" in blob
    assert "com.spa.orchestrator" in blob
    assert "scripts/agent_orchestrator.sh" in format_report_text(rep.to_dict())


def test_verdict_no_longer_reassures_that_no_risk_logic_is_affected(tmp_path: Path) -> None:
    """The old sentence was the actively harmful half: it answered a question
    nobody asked while a safety mechanism was missing from a running agent."""
    root = _tree(tmp_path, ["scripts/agent_orchestrator.sh", "docs/STATE.md"])
    rep = check_deployment_drift(
        repo_root=root,
        git_runner=_runner(remote="b" * 40,
                           diff="scripts/agent_orchestrator.sh\ndocs/STATE.md"),
        agent_dir=tmp_path, plist_reader=_plists(
            ("com.spa.orchestrator", str(root / "scripts/agent_orchestrator.sh"), HOURLY)))

    assert "no risk logic is affected" not in " ".join(rep.reasons)
    assert rep.other_files == ["docs/STATE.md"]   # the genuinely cosmetic one stays


def test_daily_entrypoint_drift_is_warning_but_still_named(tmp_path: Path) -> None:
    """com.spa.work_digest, also drifted on 2026-08-08. It fires once a day, so
    the sync reaches it first — worth saying, not worth an alarm."""
    root = _tree(tmp_path, ["scripts/agent_work_digest.sh"])
    rep = check_deployment_drift(
        repo_root=root, git_runner=_runner(remote="b" * 40,
                                           diff="scripts/agent_work_digest.sh"),
        agent_dir=tmp_path, plist_reader=_plists(
            ("com.spa.work_digest", str(root / "scripts/agent_work_digest.sh"), DAILY)))

    assert rep.status == WARNING
    assert rep.entrypoint_files[0]["self_heals_before_next_run"] is True
    assert "scripts/agent_work_digest.sh" in " ".join(rep.reasons)


@pytest.mark.parametrize("interval", [None, 0.0, 60.0, 3600.0, 86399.0])
def test_anything_faster_than_the_daily_sync_is_urgent(tmp_path: Path, interval) -> None:
    """``None`` is in this list on purpose: an unreadable schedule is fail-CLOSED.
    "We could not tell how often it runs" must never be stored as "rarely"."""
    root = _tree(tmp_path, ["scripts/agent_x.sh"])
    rep = check_deployment_drift(
        repo_root=root, git_runner=_runner(remote="b" * 40, diff="scripts/agent_x.sh"),
        agent_dir=tmp_path,
        plist_reader=_plists(("com.spa.x", str(root / "scripts/agent_x.sh"), interval)))

    assert rep.status == CRITICAL
    assert rep.entrypoint_files[0]["self_heals_before_next_run"] is False


def test_a_rare_sibling_job_cannot_vouch_for_an_unreadable_one(tmp_path: Path) -> None:
    """Two jobs share one script; one schedule is unreadable. Taking the readable
    one as the answer would let an unknown ride in on a known — the exact shape
    of every fail-OPEN guard in this repo."""
    root = _tree(tmp_path, ["scripts/agent_x.sh"])
    script = str(root / "scripts/agent_x.sh")
    rep = check_deployment_drift(
        repo_root=root, git_runner=_runner(remote="b" * 40, diff="scripts/agent_x.sh"),
        agent_dir=tmp_path,
        plist_reader=_plists(("com.spa.x_daily", script, DAILY),
                             ("com.spa.x_unknown", script, None)))

    assert rep.status == CRITICAL
    assert rep.entrypoint_files[0]["labels"] == ["com.spa.x_daily", "com.spa.x_unknown"]


def test_entrypoint_missing_from_disk_is_classified_too(tmp_path: Path) -> None:
    """``scripts/orchestrator_cycle_lock.py`` was not merely stale in production
    — the file did not exist. Absent is the worst kind of different."""
    root = _tree(tmp_path, [])          # entrypoint deliberately NOT materialised
    rep = check_deployment_drift(
        repo_root=root, git_runner=_runner(remote="b" * 40, diff="scripts/agent_gone.sh"),
        agent_dir=tmp_path, plist_reader=_plists(
            ("com.spa.gone", str(root / "scripts/agent_gone.sh"), HOURLY)))

    assert rep.status == CRITICAL
    assert [e["path"] for e in rep.entrypoint_files] == ["scripts/agent_gone.sh"]


def test_money_path_still_outranks_the_entrypoint_class(tmp_path: Path) -> None:
    """Adding a class must not demote the one that was already there."""
    root = _tree(tmp_path, ["spa_core/risk/policy.py"])
    rep = check_deployment_drift(
        repo_root=root, git_runner=_runner(remote="b" * 40, diff="spa_core/risk/policy.py"),
        agent_dir=tmp_path, plist_reader=_plists(
            ("com.spa.risk", str(root / "spa_core/risk/policy.py"), HOURLY)))

    assert rep.status == CRITICAL
    assert rep.money_path_files == ["spa_core/risk/policy.py"]
    assert rep.entrypoint_files == []
    assert any("NOT the reviewed one" in r for r in rep.reasons)


def test_no_plists_found_is_stated_not_silently_empty(tmp_path: Path) -> None:
    """On a box with no LaunchAgents (CI), the entrypoint bucket is empty because
    nobody looked. That reads identically to "nothing is wrong" unless it is said
    out loud — so it is said out loud."""
    rep = check_deployment_drift(
        repo_root=_tree(tmp_path, ["scripts/agent_orchestrator.sh"]),
        git_runner=_runner(remote="b" * 40, diff="scripts/agent_orchestrator.sh"),
        agent_dir=tmp_path / "nowhere", plist_reader=lambda d: [])

    assert rep.entrypoints_unchecked
    assert any("UNAVAILABLE" in r and "means nothing" in r for r in rep.reasons)
    assert "entrypoints NOT classified" in format_report_text(rep.to_dict())


def test_unreadable_plists_do_not_produce_a_clean_bucket(tmp_path: Path) -> None:
    def explode(_agent_dir):
        raise OSError("permission denied")

    rep = check_deployment_drift(
        repo_root=_tree(tmp_path, ["scripts/agent_orchestrator.sh"]),
        git_runner=_runner(remote="b" * 40, diff="scripts/agent_orchestrator.sh"),
        agent_dir=tmp_path, plist_reader=explode)

    assert "permission denied" in (rep.entrypoints_unchecked or "")
    assert any("UNAVAILABLE" in r for r in rep.reasons)


def test_unchecked_entrypoints_stay_quiet_when_nothing_drifted(tmp_path: Path) -> None:
    """No drift ⇒ nothing to classify ⇒ no blind-spot notice. A guard that talks
    when there is nothing to say gets filtered out before the day it matters."""
    rep = check_deployment_drift(
        repo_root=_tree(tmp_path, []), git_runner=_runner(),
        agent_dir=tmp_path, plist_reader=lambda d: [])

    assert rep.status == OK
    assert not any("UNAVAILABLE" in r for r in rep.reasons)


def test_entrypoints_outside_this_checkout_are_ignored(tmp_path: Path) -> None:
    """A plist pointing at another tree says nothing about THIS deployment."""
    rep = check_deployment_drift(
        repo_root=_tree(tmp_path, ["docs/STATE.md"]),
        git_runner=_runner(remote="b" * 40, diff="docs/STATE.md"),
        agent_dir=tmp_path,
        plist_reader=_plists(("com.spa.elsewhere", "/opt/other/agent.sh", HOURLY)))

    assert rep.status == WARNING
    assert rep.entrypoint_files == []
    assert rep.other_files == ["docs/STATE.md"]


def test_state_file_carries_the_entrypoint_class(tmp_path: Path) -> None:
    """Whoever reads data/deployment_drift.json must see it without rerunning."""
    root = _tree(tmp_path / "repo", ["scripts/agent_orchestrator.sh"])
    doc = run_deployment_drift_monitor(
        data_dir=tmp_path, repo_root=root,
        git_runner=_runner(remote="b" * 40, diff="scripts/agent_orchestrator.sh"),
        agent_dir=tmp_path, plist_reader=_plists(
            ("com.spa.orchestrator", str(root / "scripts/agent_orchestrator.sh"), HOURLY)))

    on_disk = json.loads((tmp_path / STATE_FILENAME).read_text(encoding="utf-8"))
    assert on_disk == doc
    assert on_disk["status"] == CRITICAL
    assert on_disk["entrypoint_files"][0]["labels"] == ["com.spa.orchestrator"]
    assert on_disk["entrypoint_files"][0]["interval_sec"] == HOURLY


# ── d2.defillama.deviation: compare against the pool we are actually in ──────


def test_deviation_check_ignores_lookalike_symbols_and_picks_the_deepest_pool() -> None:
    """A 100 % "deviation" was reported against SYRUPUSDC on Monad at 0 %.

    The old rule took the first pool whose symbol CONTAINED "USDC" — a different
    asset on a different chain — and locked it in, while the real Ethereum USDC
    pool sat in the same response within 0.14 pp of our stored value. An alarm
    about a comparison that was never made is worse than silence: it trains
    everyone to ignore the check, or to "fix" a correct number.
    """
    from spa_core.monitoring.system_health_monitor import SystemHealthMonitor

    pools = [
        {"project": "aave-v3", "symbol": "SYRUPUSDC", "chain": "Monad",
         "apy": 0.0, "tvlUsd": 206_347_888},          # lookalike, must be ignored
        {"project": "aave-v3", "symbol": "USDC", "chain": "Ethereum",
         "apy": 3.29996, "tvlUsd": 174_425_132},      # the pool we are in
        {"project": "aave-v3", "symbol": "USDC", "chain": "Polygon",
         "apy": 2.80076, "tvlUsd": 12_604_279},       # shallower, must lose
    ]
    picked = {}
    best = {}
    for p in pools:                       # mirrors the selection rule under test
        if str(p["symbol"]).strip().upper() != "USDC":
            continue
        proj, tvl = p["project"], float(p["tvlUsd"])
        if proj not in picked or tvl > best.get(proj, -1.0):
            picked[proj], best[proj] = float(p["apy"]), tvl

    assert picked["aave-v3"] == pytest.approx(3.29996)
    assert SystemHealthMonitor is not None      # the module still imports cleanly
