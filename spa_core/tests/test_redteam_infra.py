# LLM_FORBIDDEN
"""test_redteam_infra.py — META-VERIFY the standing red-team + smoke infrastructure (WS-2).

This is the verify-the-verifier suite: it proves the red-team harness actually CATCHES flaws (not
rubber-stamps), that it is fail-CLOSED on an uncaught one, that every seeded scenario fires + is
caught on the current healthy surfaces, that the rotation is deterministic + the report is hash-
anchored + self-verifies, and — the canary — that injecting a KNOWN flaw into a sandbox surface is
caught by the registry/rotation.

GUARDRAIL: every red-team/smoke run here is sandbox-only (the runner's own tmp dirs); the live-data
guard is exercised but never depended on to mutate anything.
"""
from __future__ import annotations

import datetime
import json
from pathlib import Path

import pytest

from spa_core.redteam import REGISTRY, Finding, RedTeamScenario, Surface
from spa_core.redteam import rotation, runner
from spa_core.redteam.registry import by_name, covered_surfaces, scenarios_for_surface


# Hermetic guard (WS-6): a rotation run appends to the tamper-evident audit chain;
# redirect it to a throwaway tmp file so this suite never writes the LIVE
# data/audit_chain.jsonl (tests must not touch live data/).
@pytest.fixture(autouse=True)
def _hermetic_audit_chain(tmp_path, monkeypatch):
    from spa_core.audit import hash_chain
    monkeypatch.setattr(hash_chain, "_CHAIN", tmp_path / "audit_chain.jsonl")
    yield


# ════════════════════════════════════════════════════════════════════════════════════════════════
# the ABC + Finding contract
# ════════════════════════════════════════════════════════════════════════════════════════════════
def test_finding_ok_is_fail_closed():
    """Finding.ok is True ONLY when the attack fired, the control passed, the forgery was caught, and
    nothing raised. Every other combination is not-ok (fail-CLOSED)."""
    assert Finding("s", "x", attempted=True, caught=True, control_ok=True, evidence="e").ok
    # uncaught forgery → not ok
    assert not Finding("s", "x", attempted=True, caught=False, control_ok=True, evidence="e").ok
    # control failed (false alarm) → not ok even if 'caught'
    assert not Finding("s", "x", attempted=True, caught=True, control_ok=False, evidence="e").ok
    # never fired → not ok
    assert not Finding("s", "x", attempted=False, caught=True, control_ok=True, evidence="e").ok
    # raised → not ok
    assert not Finding("s", "x", attempted=True, caught=True, control_ok=True, evidence="e",
                       error="boom").ok


def test_abc_cannot_instantiate_without_attack():
    """RedTeamScenario is abstract — a subclass MUST implement attack()."""
    with pytest.raises(TypeError):
        RedTeamScenario()  # type: ignore[abstract]


# ════════════════════════════════════════════════════════════════════════════════════════════════
# the registry — ≥7 scenarios, one per surface, unique names
# ════════════════════════════════════════════════════════════════════════════════════════════════
def test_registry_has_at_least_seven_scenarios():
    assert len(REGISTRY) >= 7


def test_registry_covers_every_surface():
    """Every Surface.ALL entry has at least one registered scenario (no un-probed surface)."""
    covered = set(covered_surfaces())
    assert set(Surface.ALL) <= covered, f"un-probed surfaces: {set(Surface.ALL) - covered}"


def test_registry_names_unique():
    names = [s.name for s in REGISTRY]
    assert len(names) == len(set(names)), f"duplicate scenario names: {names}"


def test_every_scenario_targets_a_known_surface():
    for s in REGISTRY:
        assert s.surface in Surface.ALL, f"{s.name} targets unknown surface {s.surface!r}"


# ════════════════════════════════════════════════════════════════════════════════════════════════
# the 7 (8) seeded scenarios all run + report caught:true on the current HEALTHY surfaces
# ════════════════════════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("scenario", REGISTRY, ids=lambda s: s.name)
def test_each_seeded_scenario_fires_and_is_caught(scenario):
    """Each seeded scenario, run against a fresh sandbox, fires its forgery AND the real defense
    catches it (attempted + control_ok + caught, no error)."""
    finding = runner.run_scenario(scenario)
    assert finding.attempted, f"{scenario.name} did not fire: {finding.evidence}"
    assert finding.control_ok, f"{scenario.name} control (healthy-artifact) failed: {finding.evidence}"
    assert finding.caught, f"{scenario.name} did NOT catch its forgery: {finding.evidence}"
    assert not finding.error, f"{scenario.name} raised: {finding.error}"
    assert finding.ok


def test_runner_run_all_passes_on_healthy_desk():
    """The full suite over fresh sandboxes → ok=True, every scenario caught, live data untouched."""
    verdict = runner.run_all(check_live_untouched=True)
    assert verdict["ok"], [f for f in verdict["findings"] if not f["ok"]]
    assert verdict["n_failed"] == 0
    assert verdict["n_caught"] == verdict["n"] >= 7
    assert verdict["live_data_untouched"] is True


# ════════════════════════════════════════════════════════════════════════════════════════════════
# THE META-CANARY — inject a KNOWN flaw → the registry/rotation MUST catch it (not rubber-stamp)
# ════════════════════════════════════════════════════════════════════════════════════════════════
class _RubberStampScenario(RedTeamScenario):
    """A DELIBERATELY BROKEN scenario: it 'attacks' a surface whose defense has been NEUTERED, so the
    forgery is NOT caught. If the harness were a rubber stamp it would still report ok; a real harness
    must report this as a FAIL (the canary)."""

    name = "canary_uncaught_flaw"
    surface = Surface.PROOF
    description = "a planted uncaught forgery — the harness MUST fail on it (anti-rubber-stamp canary)"

    def attack(self, sandbox: Path) -> Finding:
        # the forged artifact is never actually checked against a real defense → 'caught' is a lie if
        # we claimed True. We honestly report caught=False (an uncaught flaw) and the runner must FAIL.
        return self._uncaught("planted uncaught forgery — a real defense never vetted it")


def test_meta_canary_uncaught_flaw_fails_the_runner():
    """A planted UNCAUGHT forgery → the runner verdict is FAIL (fail-CLOSED). This proves the harness
    catches real holes rather than rubber-stamping."""
    verdict = runner.run_all([_RubberStampScenario()], check_live_untouched=False)
    assert verdict["ok"] is False
    assert verdict["n_failed"] == 1
    bad = verdict["findings"][0]
    assert bad["attempted"] and not bad["caught"] and not bad["ok"]


class _RaisingScenario(RedTeamScenario):
    name = "canary_raises"
    surface = Surface.FEEDS
    description = "a scenario that raises — must become a fail-CLOSED Finding, not a crash"

    def attack(self, sandbox: Path) -> Finding:
        raise RuntimeError("kaboom")


def test_a_raising_scenario_is_fail_closed_not_a_crash():
    """A scenario that RAISES must become a fail-CLOSED Finding (attempted=False, error set), never
    abort the suite."""
    finding = runner.run_scenario(_RaisingScenario())
    assert not finding.ok
    assert finding.error and "kaboom" in finding.error
    assert finding.attempted is False
    # and it fails the whole verdict
    verdict = runner.run_all([_RaisingScenario()], check_live_untouched=False)
    assert verdict["ok"] is False


class _MutatingScenario(RedTeamScenario):
    """A scenario that ESCAPES its sandbox and writes a watched LIVE file — the runner's live-data
    guard MUST fail the run even though the scenario itself reports 'caught'."""

    name = "canary_mutates_live"
    surface = Surface.PROOF
    description = "a scenario that mutates a live watched file — the live-data guard must FAIL the run"

    def attack(self, sandbox: Path) -> Finding:
        # write to a watched live file (then we clean it up after, so the test never leaves dirt).
        live = runner._ROOT / runner._WATCHED_LIVE_FILES[-1]  # data/golive_status.json
        self._scratch = live
        self._orig = live.read_bytes() if live.exists() else None
        live.parent.mkdir(parents=True, exist_ok=True)
        live.write_bytes((self._orig or b"{}") + b"\n/* redteam canary scratch */")
        return self._caught("(this scenario reports caught, but it mutated live data)")


def test_live_data_mutation_canary_fails_the_run(tmp_path):
    """A scenario that mutates a watched LIVE file → run_all reports live_data_untouched=False and
    ok=False, EVEN THOUGH the scenario itself claimed 'caught'. The guardrail is enforced, not
    promised. The canary restores the file so the live tree is left pristine."""
    scen = _MutatingScenario()
    try:
        verdict = runner.run_all([scen], check_live_untouched=True)
        assert verdict["live_data_untouched"] is False
        assert verdict["ok"] is False
        assert "data/golive_status.json" in verdict["live_data_mutated_files"]
    finally:
        # restore the watched file to its original bytes (or remove if we created it).
        live = getattr(scen, "_scratch", None)
        orig = getattr(scen, "_orig", None)
        if live is not None:
            if orig is None:
                live.unlink(missing_ok=True)
            else:
                live.write_bytes(orig)


# ════════════════════════════════════════════════════════════════════════════════════════════════
# the rotation — deterministic by UTC day, covers every surface, writes status atomically
# ════════════════════════════════════════════════════════════════════════════════════════════════
def test_rotation_is_deterministic_by_utc_day():
    """surface_for_day is a pure function of the UTC date — same day → same surface, and it cycles
    through every covered surface over a full period."""
    covered = covered_surfaces()
    seen = set()
    base = datetime.date(2026, 6, 1)
    for i in range(len(covered)):
        d = base + datetime.timedelta(days=i)
        s1 = rotation.surface_for_day(d)
        s2 = rotation.surface_for_day(d)
        assert s1 == s2  # deterministic
        seen.add(s1)
    assert seen == set(covered), "rotation does not cover every surface over a full period"


def test_rotation_writes_status_and_self_verifies(tmp_path):
    """A rotation run writes data/redteam_status.json (here a sandbox path) with a report_hash that
    re-derives from the verdict body (the anchored claim is verifiable), without touching live data."""
    sp = tmp_path / "redteam_status.json"
    status = rotation.run(surface=Surface.PROOF, anchor=False, status_path=sp,
                          ts="2026-06-28T00:00:00+00:00")
    assert sp.exists()
    on_disk = json.loads(sp.read_text(encoding="utf-8"))
    assert on_disk["schema"] == "redteam_status.v1"
    # the report_hash re-derives from the verdict body (reproducible).
    assert rotation.report_hash(status["verdict"]) == status["report_hash"]
    assert on_disk["report_hash"] == status["report_hash"]
    # the probed surface's scenarios all caught.
    assert status["verdict"]["ok"] is True
    assert status["verdict"]["surface"] == Surface.PROOF


def test_rotation_report_hash_is_stable_across_runs(tmp_path):
    """Two rotation runs of the same surface produce the SAME report_hash (deterministic identity —
    the hash anchors the set of findings, not the wall-clock)."""
    a = rotation.run(surface=Surface.OPTIMIZER, anchor=False,
                     status_path=tmp_path / "a.json", ts="2026-06-28T00:00:00+00:00")
    b = rotation.run(surface=Surface.OPTIMIZER, anchor=False,
                     status_path=tmp_path / "b.json", ts="2026-06-28T01:00:00+00:00")
    assert a["report_hash"] == b["report_hash"]


def test_rotation_all_surfaces_sweep(tmp_path):
    """The --all sweep probes every registered scenario in one verdict, all caught."""
    status = rotation.run(run_all_surfaces=True, anchor=False,
                          status_path=tmp_path / "s.json", ts="2026-06-28T00:00:00+00:00")
    assert status["verdict"]["scope"] == "all"
    assert status["verdict"]["n"] == len(REGISTRY)
    assert status["verdict"]["ok"] is True


# ════════════════════════════════════════════════════════════════════════════════════════════════
# the anchored report verifies (hash_chain anchor) — in a redirected chain so live data is untouched
# ════════════════════════════════════════════════════════════════════════════════════════════════
def test_anchored_report_appends_to_chain_and_verifies(tmp_path, monkeypatch):
    """With anchoring ON, the verdict is appended to the tamper-evident hash_chain and the anchor
    block records a valid chain. We redirect the chain file to a tmp path so live data/ is untouched."""
    from spa_core.audit import hash_chain

    chain_file = tmp_path / "audit_chain.jsonl"
    monkeypatch.setattr(hash_chain, "_CHAIN", chain_file)

    sp = tmp_path / "redteam_status.json"
    status = rotation.run(surface=Surface.KILL_SWITCH, anchor=True, status_path=sp,
                          ts="2026-06-28T00:00:00+00:00")
    anchor = status["anchor"]
    assert anchor and anchor["anchored"] is True
    assert anchor["event_type"] == rotation.REPORT_HASH_EVENT
    assert anchor["chain_valid"] is True
    # the appended entry carries our report_hash and the chain re-verifies independently.
    assert chain_file.exists()
    rows = [json.loads(ln) for ln in chain_file.read_text().splitlines() if ln.strip()]
    assert rows[-1]["event_type"] == rotation.REPORT_HASH_EVENT
    assert rows[-1]["payload"]["report_hash"] == status["report_hash"]
    assert hash_chain.verify_chain()["valid"] is True


def test_anchored_report_chain_breaks_if_tampered(tmp_path, monkeypatch):
    """Tampering the anchored verdict row breaks the hash_chain (the anchor is real tamper-evidence,
    not decoration)."""
    from spa_core.audit import hash_chain
    chain_file = tmp_path / "audit_chain.jsonl"
    monkeypatch.setattr(hash_chain, "_CHAIN", chain_file)

    rotation.run(surface=Surface.PROOF, anchor=True, status_path=tmp_path / "s.json",
                 ts="2026-06-28T00:00:00+00:00")
    rows = [json.loads(ln) for ln in chain_file.read_text().splitlines() if ln.strip()]
    rows[-1]["payload"]["report_hash"] = "0" * 64  # forge the anchored hash without re-hashing
    chain_file.write_text("".join(
        json.dumps(r, sort_keys=True, separators=(",", ":")) + "\n" for r in rows))
    assert hash_chain.verify_chain()["valid"] is False


# ════════════════════════════════════════════════════════════════════════════════════════════════
# lookup helpers
# ════════════════════════════════════════════════════════════════════════════════════════════════
def test_scenarios_for_surface_and_by_name():
    for srf in covered_surfaces():
        got = scenarios_for_surface(srf)
        assert got and all(s.surface == srf for s in got)
    names = by_name()
    assert set(names) == {s.name for s in REGISTRY}
